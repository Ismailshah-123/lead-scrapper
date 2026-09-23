"""
Cold-call brief generation.

Every line is built from a field or signal that's already on the Company
row — nothing here invents a fact. Where information genuinely isn't
available, the line says so plainly ("not publicly identified") instead
of being silently dropped or guessed at, so the brief always has ~10
lines and always tells a caller what's actually known vs not.

The optional LLM polish pass (see llm_provider.py) only rewrites the
already-assembled text for flow; its prompt explicitly forbids adding any
fact, name, or number not already present, and any failure falls back to
the unpolished template text untouched.
"""
from __future__ import annotations

from typing import List

from app.coldcall.llm_provider import get_llm_provider
from app.core.logging_config import get_logger
from app.models.models import Company

logger = get_logger("coldcall.brief")

_INDUSTRY_FALLBACK = "business"


def _industry_label(company: Company) -> str:
    return company.industry or _INDUSTRY_FALLBACK


def _line_what_they_do(company: Company) -> str:
    if company.company_description:
        return f"1. {company.name} — {company.company_description.strip()}"
    return f"1. {company.name} operates in the {_industry_label(company)} sector; a detailed description was not publicly identified."


def _line_services(company: Company) -> str:
    if company.services:
        return f"2. Main services (from their site): {company.services.strip()[:300]}"
    return f"2. Specific services beyond general {_industry_label(company)} offerings were not publicly detailed."


def _line_customers(company: Company) -> str:
    if company.target_customer:
        return f"3. Target customers: {company.target_customer.strip()}"
    return f"3. Target customer base is not explicitly stated; likely typical of the {_industry_label(company)} sector given the services listed."


def _line_geography(company: Company) -> str:
    parts = [p for p in (company.city, company.state) if p]
    if parts:
        return f"4. Operates in/around {', '.join(parts)}."
    return "4. Specific service area was not publicly identified."


def _line_size(company: Company) -> str:
    if company.employee_count and company.employee_count_type not in (None, "Unknown"):
        return f"5. Approximate size: {company.employee_count} employees ({company.employee_count_type})."
    return "5. Employee count could not be confidently determined from compliant public sources."


def _line_lead_generation(company: Company) -> str:
    signal_types = {s.signal_type for s in company.signals}
    notes: List[str] = []
    if "contact_form_present" in signal_types or "form_builder_detected" in signal_types:
        notes.append("an online contact/inquiry form")
    if "quote_request_language" in signal_types:
        notes.append("quote/estimate-request language")
    if "booking_system_detected" in signal_types or "booking_language" in signal_types:
        notes.append("online booking/appointment language")
    if notes:
        return f"6. Lead capture: the website uses {', '.join(notes)} to collect inbound inquiries."
    return "6. No online lead-capture mechanism (form, quote request, or booking) was identified from public website analysis."


def _line_advertising(company: Company) -> str:
    evidence = [e for e in (company.meta_ad_evidence, company.google_ad_evidence) if e]
    if evidence:
        return f"7. Advertising evidence: {'; '.join(evidence)}."
    return "7. No advertising activity was identified through the compliant sources checked (this does not confirm they aren't advertising elsewhere)."


def _line_crm_gap(company: Company) -> str:
    signal_types = {s.signal_type for s in company.signals}
    existing = next((s.evidence_text for s in company.signals if s.signal_type == "existing_crm_detected"), None)
    if existing:
        return f"8. Existing tooling: {existing}. Conversation angle: gaps in their current workflow, not a from-scratch pitch."
    if "chat_widget_detected" in signal_types:
        chat_evidence = next((s.evidence_text for s in company.signals if s.signal_type == "chat_widget_detected"), "")
        return f"8. {chat_evidence}, but no CRM/marketing-automation platform was identified — likely a gap between capturing interest and following it up."
    return "8. No CRM or marketing-automation platform was publicly identified on the website — a likely gap between inbound interest and structured follow-up."


def _line_automation_opportunity(company: Company) -> str:
    breakdown = company.crm_score_breakdown or {}
    automation_score = breakdown.get("automation_opportunity", 0)
    if automation_score >= 5:
        return "9. Automation opportunity: intake looks manual today (forms/contact without visible booking or CRM automation behind them) — a clear opening for automated routing and follow-up."
    return "9. Automation opportunity is limited based on what's publicly visible — some automation may already be in place."


def _line_cold_call_angle(company: Company) -> str:
    level = company.crm_opportunity_level or "unscored"
    strongest_signal = None
    signal_types = {s.signal_type for s in company.signals}
    if "quote_request_language" in signal_types:
        strongest_signal = "how quickly new estimate requests get a response"
    elif "contact_form_present" in signal_types:
        strongest_signal = "how inbound form submissions get followed up"
    elif "careers_page_found" in signal_types:
        strongest_signal = "how a growing team is keeping customer follow-up consistent"
    else:
        strongest_signal = "how new customer inquiries are currently tracked"
    return f"10. Suggested angle ({level} opportunity): open on {strongest_signal}, since that's the most concrete, verifiable observation available."


_LINE_BUILDERS = [
    _line_what_they_do, _line_services, _line_customers, _line_geography, _line_size,
    _line_lead_generation, _line_advertising, _line_crm_gap, _line_automation_opportunity,
    _line_cold_call_angle,
]


def build_template_brief(company: Company) -> str:
    return "\n".join(builder(company) for builder in _LINE_BUILDERS)


def build_template_opening(company: Company) -> str:
    signal_types = {s.signal_type for s in company.signals}
    if "quote_request_language" in signal_types:
        observation = "you're actively inviting visitors to request a quote/estimate online"
    elif "contact_form_present" in signal_types:
        observation = "your site collects inquiries through a contact form"
    elif "careers_page_found" in signal_types:
        observation = "your team looks like it's been growing"
    else:
        observation = f"you're an active {_industry_label(company)} business in {company.city or 'your area'}"

    greeting = "Hi there"
    if company.contacts:
        publicly_identified = next((c for c in company.contacts if c.verification_status in ("Verified", "Publicly Identified")), None)
        if publicly_identified and publicly_identified.full_name:
            first_name = publicly_identified.full_name.split()[0]
            greeting = f"Hi {first_name}"

    return (
        f"{greeting}, I was looking at {company.name} and noticed {observation}. "
        f"I work with {_industry_label(company)} businesses to help automate how new inquiries get captured, "
        f"qualified, and followed up — is your team currently handling that manually, or do you have a CRM in place?"
    )


_POLISH_PROMPT_TEMPLATE = """Rewrite the following cold-call briefing so it reads as natural, flowing \
prose for a salesperson glancing at it before a call. Keep it to roughly the same length and the \
same 10 points, in order. Do NOT add any fact, name, number, company detail, or claim that is not \
already present below -- if a line says something wasn't found or identified, keep that same honest \
framing, just phrase it naturally. Do not invent statistics, dates, or people.

---
{draft}
---

Rewritten version:"""


def generate_brief_and_opening(company: Company) -> None:
    """Writes company.cold_call_brief and company.recommended_opening.
    Call after scoring, since a couple of lines reference the CRM score
    breakdown."""
    draft_brief = build_template_brief(company)
    opening = build_template_opening(company)

    provider = get_llm_provider()
    prompt = _POLISH_PROMPT_TEMPLATE.format(draft=draft_brief)
    polished = provider.polish(prompt, fallback_text=draft_brief)

    company.cold_call_brief = polished
    company.recommended_opening = opening
    logger.info("Generated cold-call brief for %s (%d chars)", company.name, len(polished))
