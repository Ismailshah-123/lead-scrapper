"""
Deduplication.

Identity priority, strongest first: official domain > phone > normalized
company name + city. Merging never deletes information — the losing
Company row is kept as a tombstone (duplicate_status="merged_into:<id>")
for audit, its SourceRecord/CompanySignal/Contact rows are reassigned to
the surviving row so every downstream export and scoring pass sees the
complete picture, and any genuinely conflicting field goes through
app.utils.merge.merge_field_with_evidence rather than silently picking one
value and discarding the other.
"""
from __future__ import annotations

from typing import List

from app.core.logging_config import get_logger
from app.models.models import Company
from app.utils.merge import fill_if_empty, merge_field_with_evidence

logger = get_logger("deduplication")

_FILL_ONLY_FIELDS = [
    "website", "address", "city", "state", "zip", "country",
    "industry", "sub_industry", "services", "target_customer", "company_description",
    "google_maps_url", "facebook_url", "linkedin_url", "business_status",
    "meta_ad_evidence", "google_ad_evidence",
]


def _is_same_company(a: Company, b: Company) -> bool:
    if a.domain and b.domain and a.domain == b.domain:
        return True
    if a.phone and b.phone and a.phone == b.phone:
        return True
    if a.normalized_name and b.normalized_name and a.normalized_name == b.normalized_name:
        if (a.city or "").strip().lower() == (b.city or "").strip().lower() and a.normalized_name:
            return True
    return False


def _completeness_score(c: Company) -> int:
    fields = [c.website, c.phone, c.email, c.address, c.city, c.state, c.industry,
              c.services, c.company_description, c.google_maps_url]
    return sum(1 for f in fields if f)


def find_duplicate_groups(companies: List[Company]) -> List[List[Company]]:
    """O(n^2) greedy grouping — fine at this project's target scale
    (tens of qualified leads per run, spec explicitly favors quality over
    volume), and simple enough to be obviously correct and testable."""
    groups: List[List[Company]] = []
    used = set()
    for i, c1 in enumerate(companies):
        if c1.id in used:
            continue
        group = [c1]
        used.add(c1.id)
        for c2 in companies[i + 1:]:
            if c2.id in used:
                continue
            if _is_same_company(c1, c2):
                group.append(c2)
                used.add(c2.id)
        groups.append(group)
    return groups


def _merge_into(primary: Company, dup: Company) -> None:
    for field_name in _FILL_ONLY_FIELDS:
        fill_if_empty(primary, field_name, getattr(dup, field_name, None))

    dup_source_label = dup.source_primary or "unknown_source"
    merge_field_with_evidence(primary, "phone", dup.phone, dup_source_label, alt_list_field="alternate_phones")
    merge_field_with_evidence(primary, "email", dup.email, dup_source_label, alt_list_field="alternate_emails")

    secondary = set(primary.source_secondary or [])
    if dup.source_primary:
        secondary.add(dup.source_primary)
    secondary.update(dup.source_secondary or [])
    secondary.discard(primary.source_primary)
    primary.source_secondary = sorted(secondary)

    primary.all_source_urls = list(dict.fromkeys((primary.all_source_urls or []) + (dup.all_source_urls or [])))

    # Reassign child rows so exports/scoring see the complete picture under
    # a single surviving id -- nothing is deleted, the dup row remains as
    # a tombstone with its own original snapshot intact.
    for sr in list(dup.source_records):
        sr.company_id = primary.id
    for sig in list(dup.signals):
        sig.company_id = primary.id
    for contact in list(dup.contacts):
        contact.company_id = primary.id

    dup.duplicate_status = f"merged_into:{primary.id}"
    dup.merged_into_id = primary.id
    logger.info("Merged %r (id=%s) into %r (id=%s)", dup.name, dup.id, primary.name, primary.id)


def deduplicate_companies(companies: List[Company]) -> List[Company]:
    """Returns the list of surviving (non-merged-away) companies. Expects
    `companies` to already be flushed (have ids) — call within an active
    session so the id-based bookkeeping above works."""
    active = [c for c in companies if c.duplicate_status in ("unique", None, "")]
    groups = find_duplicate_groups(active)

    survivors: List[Company] = []
    for group in groups:
        if len(group) == 1:
            survivors.append(group[0])
            continue
        group_sorted = sorted(group, key=_completeness_score, reverse=True)
        primary = group_sorted[0]
        for dup in group_sorted[1:]:
            _merge_into(primary, dup)
        primary.duplicate_status = "unique"
        survivors.append(primary)

    logger.info("Deduplication: %d input companies -> %d surviving records", len(companies), len(survivors))
    return survivors
