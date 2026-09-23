"""
Verification status + final lead classification.

The one rule this entire module exists to enforce: a status is computed
from *evidence that was actually recorded* (see app/utils/merge.py), never
from "this looks plausible so let's call it verified". A phone that is
syntactically valid but only ever seen once is Publicly Listed at best,
never Verified — that distinction is the whole point.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Tuple

from app.core.config import TargetingConfig
from app.core.logging_config import get_logger
from app.models.models import Company, VerificationResult
from app.utils.normalize import employee_range_overlaps

logger = get_logger("verification")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def compute_contact_field_status(company: Company, field_name: str) -> str:
    """Verified / Publicly Listed / Conflicting / Unverified / Not Found —
    computed purely from company.verification_evidence and
    company.conflicting_fields, both of which are only ever populated by
    app.utils.merge.merge_field_with_evidence."""
    if field_name in (company.conflicting_fields or []):
        return "Conflicting"

    value = getattr(company, field_name, None)
    if not value:
        return "Not Found"

    field_evidence = (company.verification_evidence or {}).get(field_name, [])
    if len(field_evidence) >= 2:
        return "Verified"
    if len(field_evidence) == 1:
        return "Unverified" if field_evidence[0].get("confidence") == "low" else "Publicly Listed"
    # A value exists but somehow has no recorded evidence (e.g. set directly
    # rather than through merge_field_with_evidence) -- treat conservatively.
    return "Unverified"


def compute_owner_status(company: Company) -> str:
    """Verified / Publicly Identified / Unverified / Not Found. This
    project's connectors only ever produce 'Publicly Identified' (a name
    found on the company's own team/about page) — 'Verified' is reserved
    for a future cross-source match (e.g. the same name also appearing on
    a licensed B2B data source) that this build doesn't have a source for
    yet. That's an honest gap, not a bug."""
    if not company.contacts:
        return "Not Found"
    statuses = {c.verification_status for c in company.contacts}
    if "Verified" in statuses:
        return "Verified"
    if "Publicly Identified" in statuses:
        return "Publicly Identified"
    return "Unverified"


def verify_company(session, company: Company) -> None:
    """Recompute every verification status for one company and write an
    audit row per field (spec: "Audit Log"). Call this after enrichment
    and deduplication have both run, so all evidence is already merged."""
    company.phone_verification_status = compute_contact_field_status(company, "phone")
    company.email_verification_status = compute_contact_field_status(company, "email")
    owner_status = compute_owner_status(company)

    company.last_verified_at = _utcnow()

    for field_name, status in (
        ("phone", company.phone_verification_status),
        ("email", company.email_verification_status),
        ("owner", owner_status),
        ("website", company.website_status),
    ):
        session.add(VerificationResult(
            company_id=company.id,
            field_name=field_name,
            status=status,
            method="evidence_count",
            checked_at=_utcnow(),
        ))

    logger.info(
        "Verified %s: phone=%s email=%s owner=%s website=%s",
        company.name, company.phone_verification_status, company.email_verification_status,
        owner_status, company.website_status,
    )


def classify_lead(company: Company, config: TargetingConfig) -> Tuple[str, str]:
    """Final bucket: master / needs_review / rejected, plus a
    human-readable reason.

    Deliberate tiering — this order matters:
      1. Confident, specific disqualifiers -> REJECTED (closed, no
         presence at all, employee count *confirmed* outside range).
      2. Unresolved uncertainty -> NEEDS_REVIEW, checked BEFORE any
         score-based rejection. An unknown employee count or a genuine
         cross-source conflict means we don't actually know enough to
         reject confidently — a low score on incomplete information is a
         reason to get a human to look, not a reason to discard it (spec:
         "if the system cannot confidently determine employee count, put
         it in NEEDS_REVIEW rather than inventing a number"; a company can
         be CRM=95/Quality=65 -- "excellent prospect, additional
         verification required" -- never silently downgraded to rejected
         because of the low quality score alone).
      3. Only once 1-2 are clear does a low CRM score reject a lead for
         genuine poor fit.
      4. Remaining data-quality/contactability gaps -> NEEDS_REVIEW.
      5. Otherwise -> MASTER.
    """

    if company.business_status == "CLOSED_PERMANENTLY":
        return "rejected", "Business listed as permanently closed."

    if company.website_status == "Unreachable" and company.phone_verification_status == "Not Found" and company.email_verification_status == "Not Found":
        return "rejected", "No reachable website and no verifiable contact information of any kind."

    overlaps = employee_range_overlaps(company.employee_count, config.employee_min, config.employee_max)
    if overlaps is False:
        return "rejected", f"Employee count ({company.employee_count}) falls outside the configured {config.employee_min}-{config.employee_max} range."

    if overlaps is None:
        return "needs_review", "Employee count could not be confidently determined from compliant sources — needs manual research rather than a guess."

    if company.contact_conflict:
        return "needs_review", f"Conflicting information across sources: {company.conflict_notes}"

    if company.crm_opportunity_score is not None and company.crm_opportunity_score < config.crm_score_min:
        return "rejected", f"CRM Opportunity Score {company.crm_opportunity_score} is below the configured minimum of {config.crm_score_min}."

    if company.data_quality_score is not None and company.data_quality_score < config.data_quality_min:
        return "needs_review", f"Data Quality Score {company.data_quality_score} is below the configured minimum of {config.data_quality_min} — likely a real prospect, but under-verified."

    if company.phone_verification_status == "Not Found" and company.email_verification_status == "Not Found":
        return "needs_review", "No phone or email could be found through compliant sources."

    return "master", "Meets all configured quality gates."


def classify_and_bucket(companies, config: TargetingConfig) -> Dict[str, List[Company]]:
    """Runs classify_lead() over a list of companies and applies the
    result directly to each row (lead_authenticity_status,
    rejection_reason), returning them grouped by bucket. Used by both the
    full pipeline run and the standalone `score`/`export` CLI commands so
    there is exactly one place this decision is made."""
    buckets: Dict[str, List[Company]] = {"master": [], "needs_review": [], "rejected": []}
    for company in companies:
        bucket, reason = classify_lead(company, config)
        if bucket == "rejected":
            company.lead_authenticity_status = "REJECTED"
            company.rejection_reason = reason
        elif bucket == "needs_review":
            company.lead_authenticity_status = "NEEDS_REVIEW"
            company.rejection_reason = reason
        else:
            strong = company.phone_verification_status == "Verified" or company.email_verification_status == "Verified"
            company.lead_authenticity_status = "VERIFIED" if strong else "LIKELY_VALID"
        buckets[bucket].append(company)
    return buckets
