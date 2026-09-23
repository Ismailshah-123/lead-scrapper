"""
Scoring: two deliberately separate 0-100 numbers.

  CRM Opportunity Score — "how likely is this company to benefit from
  CRM/automation?" Computed from CompanySignal rows the enrichment step
  recorded (forms, booking systems, ad evidence, existing-CRM footprint,
  etc) plus a few Company fields (employee fit, review count, industry).

  Data Quality Score — "how trustworthy/complete is what we have?"
  Computed from verification statuses. A company can score CRM=95 /
  Quality=60: an excellent prospect that still needs manual verification
  before you call them, which is exactly the distinction the two scores
  exist to preserve — never combine them into one number.
"""
from __future__ import annotations

from typing import Dict, Set, Tuple

from app.core.config import TargetingConfig
from app.core.logging_config import get_logger
from app.models.models import Company
from app.utils.normalize import employee_range_overlaps

logger = get_logger("scoring")

HIGH_FOLLOW_UP_INDUSTRIES = {
    "roofing", "hvac", "plumbing", "real estate", "real_estate", "dental",
    "healthcare_clinic", "insurance_agency", "law_firm", "auto_repair",
    "property_management", "solar", "remodeling",
}


def _signal_types(company: Company) -> Set[str]:
    return {s.signal_type for s in company.signals}


def _business_size_fit(company: Company, config: TargetingConfig) -> int:
    if not company.employee_count or company.employee_count_type in (None, "Unknown"):
        return 5  # neutral: can't confirm fit, but not disqualifying on its own
    preferred = employee_range_overlaps(company.employee_count, config.preferred_employee_min, config.preferred_employee_max)
    full_range = employee_range_overlaps(company.employee_count, config.employee_min, config.employee_max)
    if preferred:
        return 15
    if full_range:
        return 10
    return 0


def _lead_generation_activity(signals: Set[str]) -> int:
    score = 0
    if "contact_form_present" in signals or "form_builder_detected" in signals:
        score += 5
    if "quote_request_language" in signals:
        score += 5
    if "booking_language" in signals or "booking_system_detected" in signals:
        score += 5
    return min(score, 15)


def _sales_complexity(company: Company, signals: Set[str]) -> int:
    score = 0
    if "multiple_locations_mentioned" in signals:
        score += 5
    if company.review_count and company.review_count >= 20:
        score += 5
    if "careers_page_found" in signals:
        score += 5
    return min(score, 15)


def _customer_follow_up_need(company: Company, signals: Set[str]) -> int:
    score = 0
    industry_key = (company.industry or "").strip().lower().replace(" ", "_")
    if industry_key in HIGH_FOLLOW_UP_INDUSTRIES:
        score += 5
    if company.website_status == "Active" and "existing_crm_detected" not in signals:
        score += 5
    if "quote_request_language" in signals or "booking_language" in signals:
        score += 5
    return min(score, 15)


def _digital_presence(company: Company) -> int:
    score = 0
    if company.website_status == "Active":
        score += 4
    if company.google_rating is not None:
        score += 3
    if company.review_count:
        score += 3
    return min(score, 10)


def _automation_opportunity(company: Company, signals: Set[str]) -> int:
    score = 0
    if company.website_status == "Active" and "chat_widget_detected" not in signals and "existing_crm_detected" not in signals:
        score += 5
    has_some_digital_intake = "contact_form_present" in signals or "quote_request_language" in signals
    if has_some_digital_intake and "booking_system_detected" not in signals:
        score += 5
    return min(score, 10)


def _evidence_quality(company: Company) -> int:
    sources = {company.source_primary} if company.source_primary else set()
    sources.update(company.source_secondary or [])
    sources.discard(None)
    count = len(sources)
    if count >= 3:
        return 10
    if count == 2:
        return 6
    if count == 1:
        return 2
    return 0


def score_crm_opportunity(company: Company, config: TargetingConfig) -> Tuple[int, str, Dict[str, int]]:
    signals = _signal_types(company)

    breakdown = {
        "business_size_fit": _business_size_fit(company, config),
        "lead_generation_activity": _lead_generation_activity(signals),
        "advertising_activity": min(
            (5 if company.meta_ad_evidence else 0) + (5 if company.google_ad_evidence else 0), 10
        ),
        "sales_complexity": _sales_complexity(company, signals),
        "customer_follow_up_need": _customer_follow_up_need(company, signals),
        "digital_presence": _digital_presence(company),
        "automation_opportunity": _automation_opportunity(company, signals),
        "evidence_quality": _evidence_quality(company),
    }
    total = min(sum(breakdown.values()), 100)

    if total >= 90:
        level = "HOT"
    elif total >= 80:
        level = "VERY HIGH"
    elif total >= 70:
        level = "HIGH"
    elif total >= 60:
        level = "MEDIUM"
    else:
        level = "LOW"

    return total, level, breakdown


def score_data_quality(company: Company) -> Tuple[int, Dict[str, int]]:
    contact_field_points = {"Verified": 10, "Publicly Listed": 6, "Unverified": 3, "Conflicting": 2, "Not Found": 0}
    owner_points = {"Verified": 10, "Publicly Identified": 7, "Unverified": 3, "Not Found": 0}
    employee_points = {"Exact": 10, "Public Range": 8, "Estimated": 5, "Unknown": 0, None: 0}

    owner_status = "Not Found"
    if company.contacts:
        statuses = {c.verification_status for c in company.contacts}
        owner_status = "Verified" if "Verified" in statuses else ("Publicly Identified" if "Publicly Identified" in statuses else "Unverified")

    breakdown = {
        "company_name_traceable": 10 if len(company.source_secondary or []) >= 1 else 5,
        "website_verified": 10 if company.website_status == "Active" else 0,
        "phone_verified": contact_field_points.get(company.phone_verification_status, 0),
        "email_verified": contact_field_points.get(company.email_verification_status, 0),
        "owner_verified": owner_points.get(owner_status, 0),
        "employee_count_supported": employee_points.get(company.employee_count_type, 0),
        "location_verified": 10 if (company.city and company.state) else (5 if (company.city or company.state) else 0),
        "industry_verified": 10 if company.industry else 0,
        "source_traceability": 10 if (company.all_source_urls or []) else 0,
        "no_duplicate": 10 if company.duplicate_status == "unique" else 0,
    }
    total = min(sum(breakdown.values()), 100)
    return total, breakdown


def score_company(company: Company, config: TargetingConfig) -> None:
    """Compute and write both scores directly onto the Company row. Caller
    is responsible for also appending a LeadScore audit row (see
    pipeline.py) so score history isn't lost across re-runs."""
    crm_score, crm_level, crm_breakdown = score_crm_opportunity(company, config)
    quality_score, quality_breakdown = score_data_quality(company)

    company.crm_opportunity_score = crm_score
    company.crm_opportunity_level = crm_level
    company.crm_score_breakdown = crm_breakdown
    company.data_quality_score = quality_score
    company.data_quality_breakdown = quality_breakdown

    logger.info(
        "Scored %s: CRM=%d (%s) Quality=%d", company.name, crm_score, crm_level, quality_score
    )
