"""
Shared "merge one more source's value into a Company field" logic.

Both the enrichment step (merging a website finding into the Company that
came from Google Places) and the deduplication step (merging two Company
rows discovered separately) need the exact same behavior: fill an empty
field, recognize corroboration when two sources agree, or flag a genuine
conflict when they don't. Keeping this in one place is what makes
Verified/Publicly Listed/Conflicting/Unverified computable later purely
from recorded evidence, never from a guess (see app/verification/verify.py).
"""
from __future__ import annotations

from typing import Optional

from app.models.models import Company


def _values_equal(field_name: str, a: str, b: str) -> bool:
    if field_name == "email":
        return a.strip().lower() == b.strip().lower()
    return a == b


def merge_field_with_evidence(
    company: Company,
    field_name: str,
    candidate_value: Optional[str],
    source_label: str,
    confidence: str = "normal",
    alt_list_field: Optional[str] = None,
) -> None:
    """Merge `candidate_value` (from `source_label`) into `company.<field_name>`.

    * Empty field -> fill it, record this as the first piece of evidence.
    * Same value as another source already gave -> record corroboration
      (this is what turns "Publicly Listed" into "Verified" later).
    * Different value -> flag a real conflict: mark the field name in
      conflicting_fields, append a human-readable note, and preserve the
      alternate value (in `alt_list_field`, e.g. "alternate_phones") rather
      than silently picking one and discarding the other.
    """
    if not candidate_value:
        return

    evidence = dict(company.verification_evidence or {})
    field_evidence = list(evidence.get(field_name, []))

    current_value = getattr(company, field_name, None)

    if not current_value:
        setattr(company, field_name, candidate_value)
        field_evidence.append({"source": source_label, "confidence": confidence})
    elif _values_equal(field_name, current_value, candidate_value):
        if not any(e.get("source") == source_label for e in field_evidence):
            field_evidence.append({"source": source_label, "confidence": confidence})
    else:
        conflicting = list(company.conflicting_fields or [])
        if field_name not in conflicting:
            conflicting.append(field_name)
        company.conflicting_fields = conflicting
        company.contact_conflict = True

        note = f"Conflicting {field_name}: {current_value!r} vs {candidate_value!r} (from {source_label})"
        company.conflict_notes = f"{company.conflict_notes} | {note}" if company.conflict_notes else note

        if alt_list_field:
            alt_values = list(getattr(company, alt_list_field, None) or [])
            if candidate_value not in alt_values:
                alt_values.append(candidate_value)
            setattr(company, alt_list_field, alt_values)

    evidence[field_name] = field_evidence
    company.verification_evidence = evidence


def fill_if_empty(company: Company, field_name: str, candidate_value) -> None:
    """For fields where "conflict" doesn't make sense (industry,
    description, address...) — just fill it if it's currently empty.
    First source to supply a value wins; nothing is ever overwritten."""
    if candidate_value and not getattr(company, field_name, None):
        setattr(company, field_name, candidate_value)
