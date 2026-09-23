"""
Normalization utilities.

These are pure functions with no network access, which is deliberate:
normalization has to be deterministic and cheap to run repeatedly (every
dedup pass re-normalizes), and it has to be testable without mocking
anything. Anything that needs the network (verifying a phone actually
belongs to a business, checking a website resolves) lives in
app/verification/verify.py instead.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

import phonenumbers
from email_validator import EmailNotValidError, validate_email

# Suffixes stripped only for *matching* purposes. The original, as-seen
# company name is always preserved separately (spec section 13: "Normalize
# the company name but preserve the original source name").
_SUFFIX_PATTERN = re.compile(
    r"\b(llc|l\.l\.c\.|inc|inc\.|incorporated|corp|corp\.|corporation|"
    r"ltd|ltd\.|limited|co|co\.|company|group|holdings|enterprises|"
    r"pllc|pc|p\.c\.|llp)\b\.?",
    re.IGNORECASE,
)
_PUNCT_PATTERN = re.compile(r"[^\w\s]")
_WHITESPACE_PATTERN = re.compile(r"\s+")

NOT_FOUND = "Not found"
NOT_PUBLICLY_VERIFIED = "Not publicly verified"


def normalize_company_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation, collapse whitespace.

    Used only as a matching key for deduplication — never shown to the user
    or written into an export in place of the real name.
    """
    if not name:
        return ""
    cleaned = _SUFFIX_PATTERN.sub("", name)
    cleaned = _PUNCT_PATTERN.sub(" ", cleaned)
    cleaned = _WHITESPACE_PATTERN.sub(" ", cleaned).strip().lower()
    return cleaned


def normalize_phone(raw: Optional[str], region: str = "US") -> Optional[str]:
    """Return an E.164-formatted phone number, or None if it can't be
    parsed as a plausible number. Never fabricates a number — a null input
    or an unparsable one both return None, and callers must render that as
    "Not found" in exports, not guess."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(raw: Optional[str], check_deliverability: bool = False) -> Optional[str]:
    """Return a syntax-normalized email, or None if invalid.

    check_deliverability=True performs a DNS MX lookup (a network call) to
    confirm the domain can receive mail. Off by default so normalization
    stays offline/fast; verification of a specific lead's email is a
    separate, explicit step (see app/verification/verify.py) so it's clear
    where network calls happen.
    """
    if not raw or not raw.strip():
        return None
    try:
        result = validate_email(raw.strip(), check_deliverability=check_deliverability)
    except EmailNotValidError:
        return None
    return result.normalized


def extract_domain(url_or_email: Optional[str]) -> Optional[str]:
    """Extract a bare registrable-ish domain (lowercase, no www.) from a URL
    or an email address. Used as the primary deduplication key."""
    if not url_or_email:
        return None
    value = url_or_email.strip()
    if "@" in value and "://" not in value:
        # looks like an email address
        domain = value.rsplit("@", 1)[-1]
    else:
        if "://" not in value:
            value = f"http://{value}"
        domain = urlparse(value).netloc

    domain = domain.lower().split(":")[0]  # drop any port
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or None


def parse_employee_range(employee_count: Optional[str]) -> Optional[tuple[int, Optional[int]]]:
    """Parse "51-100", "Estimated 40-70", "100+", or a bare "45" into a
    (low, high) tuple for range-overlap checks. Returns None for "Unknown"
    or anything else that can't be confidently parsed — callers must treat
    None as "can't determine fit", never as zero or as a reason to guess."""
    if not employee_count:
        return None
    text = employee_count.strip().lower()
    if text in ("unknown", "not found", "n/a", ""):
        return None

    numbers = re.findall(r"\d+", text)
    if not numbers:
        return None
    if "+" in text and len(numbers) == 1:
        return (int(numbers[0]), None)
    if len(numbers) == 1:
        return (int(numbers[0]), int(numbers[0]))
    return (int(numbers[0]), int(numbers[1]))


def employee_range_overlaps(employee_count: Optional[str], min_employees: int, max_employees: int) -> Optional[bool]:
    """True/False if we can tell, None if the employee count is unknown
    and therefore this check simply cannot be made (spec: route those to
    NEEDS_REVIEW rather than guessing either way)."""
    parsed = parse_employee_range(employee_count)
    if parsed is None:
        return None
    low, high = parsed
    if high is None:  # "100+" style: overlaps unless even the low end is already above our max
        return low <= max_employees
    return low <= max_employees and high >= min_employees

def classify_email_type(email: Optional[str], owner_name: Optional[str] = None) -> str:
    """Best-effort classification used for the Email_Type export column.
    Never claims "Owner" unless the local part plausibly matches the
    decision-maker's name that was itself sourced separately."""
    if not email:
        return "Unknown"
    local_part = email.split("@", 1)[0].lower()
    generic_prefixes = {"info", "sales", "contact", "support", "hello", "office", "admin", "enquiries", "inquiries"}
    if local_part in generic_prefixes:
        return "Company Domain (Generic)"
    if owner_name:
        name_tokens = [t.lower() for t in re.split(r"\s+", owner_name) if t]
        if any(token and token in local_part for token in name_tokens):
            return "Owner/Decision-Maker"
    if "@gmail." in email.lower() or "@yahoo." in email.lower() or "@outlook." in email.lower() or "@hotmail." in email.lower():
        return "Free Webmail (verify before treating as official)"
    return "Company Domain"
