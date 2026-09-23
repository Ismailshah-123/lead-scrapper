"""
Demo data — NOT real leads.

Every company name ends in "(Demo)" and every source_url points at
example.com (the IANA-reserved documentation domain) specifically so
these can never be mistaken for real scraped businesses if this data ever
ends up next to genuine output. source_primary is "demo", which is not a
real Source name used anywhere else, so these rows are trivially
filterable/excludable.

These fixtures feed the REAL scoring, verification, classification, and
brief-generation code (see `python -m app demo` / pipeline.run_demo()) —
only the network-dependent discovery/enrichment steps are skipped, since
this sandbox can't reach arbitrary external hosts. The point is to prove
the back half of the pipeline end-to-end and give you real, openable
Excel files before you've wired up a single API key.
"""
from __future__ import annotations

import datetime as dt
from typing import List

from app.models.models import Company, CompanySignal, Contact
from app.utils.merge import merge_field_with_evidence


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _base(**kwargs) -> Company:
    defaults = dict(
        normalized_name="",
        country="USA",
        source_primary="demo",
        source_secondary=[],
        all_source_urls=["https://example.com/demo-source"],
        duplicate_status="unique",
        lead_authenticity_status="NEEDS_REVIEW",
        website_status="Active",
        business_status="OPERATIONAL",
        first_found_at=_utcnow(),
    )
    defaults.update(kwargs)
    defaults["normalized_name"] = defaults["name"].lower().replace("(demo)", "").strip()
    return Company(**defaults)


def build_demo_companies() -> List[Company]:
    companies: List[Company] = []

    # 1) Strong, well-evidenced prospect -> should land in MASTER.
    c1 = _base(
        name="Riverstone Roofing & Exteriors (Demo)",
        industry="roofing", city="Austin", state="TX", zip="78701",
        website="https://example.com/riverstone-roofing-demo",
        google_maps_url="https://example.com/maps/riverstone-demo",
        review_count=64, google_rating=4.7,
        employee_count="45", employee_count_type="Public Range",
        employee_count_source="Google Places business category + review volume (approximate only)",
        employee_count_confidence="Medium",
        company_description="A residential and commercial roofing company handling replacements, repairs, inspections, and storm-damage work.",
        services="Roof replacement, roof repair, inspections, storm damage restoration",
        meta_ad_evidence="Active ad found via Meta Ad Library (ad_id=demo-001, started 2026-05-01)",
        source_secondary=["website"],
        all_source_urls=["https://example.com/maps/riverstone-demo", "https://example.com/riverstone-roofing-demo"],
    )
    c1.signals = [
        CompanySignal(signal_type="contact_form_present", evidence_text="2 HTML <form> elements found", source_url=c1.website),
        CompanySignal(signal_type="quote_request_language", evidence_text="Page uses quote/estimate-request language", source_url=c1.website),
        CompanySignal(signal_type="careers_page_found", evidence_text="Dedicated careers page found", source_url=c1.website + "/careers"),
        CompanySignal(signal_type="decision_maker_publicly_identified", evidence_text="Jordan Reyes listed as Owner — confirm before using", source_url=c1.website + "/about"),
    ]
    c1.contacts = [Contact(full_name="Jordan Reyes", title="Owner", source_url=c1.website + "/about", verification_status="Publicly Identified")]
    merge_field_with_evidence(c1, "phone", "+15125550101", "google_places", confidence="normal")
    merge_field_with_evidence(c1, "phone", "+15125550101", "website", confidence="normal")  # corroborated -> Verified
    merge_field_with_evidence(c1, "email", "info@example.com", "website", confidence="normal")
    companies.append(c1)

    # 2) Decent prospect, single-source contact info -> illustrates
    #    Publicly Listed rather than Verified.
    c2 = _base(
        name="Bluepeak HVAC Solutions (Demo)",
        industry="hvac", city="Dallas", state="TX", zip="75201",
        website="https://example.com/bluepeak-hvac-demo",
        review_count=18, google_rating=4.5,
        employee_count="Estimated 20-35", employee_count_type="Estimated",
        employee_count_source="Estimated from review volume and service area — not a confirmed figure",
        employee_count_confidence="Low",
        company_description="An HVAC installation and repair company serving the Dallas metro area.",
        services="AC repair, furnace installation, duct cleaning, maintenance plans",
        source_secondary=["website"],
        all_source_urls=["https://example.com/maps/bluepeak-demo", "https://example.com/bluepeak-hvac-demo"],
    )
    c2.signals = [
        CompanySignal(signal_type="booking_system_detected", evidence_text="Calendly booking widget detected", source_url=c2.website),
        CompanySignal(signal_type="quote_request_language", evidence_text="Page uses quote/estimate-request language", source_url=c2.website),
    ]
    merge_field_with_evidence(c2, "phone", "+12145550102", "google_places", confidence="normal")
    companies.append(c2)

    # 3) Good signals, but employee count genuinely unknown -> should be
    #    routed to NEEDS_REVIEW rather than a guessed number.
    c3 = _base(
        name="Homestyle Cleaning Co (Demo)",
        industry="cleaning_services", city="Phoenix", state="AZ", zip="85001",
        website="https://example.com/homestyle-cleaning-demo",
        review_count=41, google_rating=4.8,
        employee_count=None, employee_count_type="Unknown",
        employee_count_source=None, employee_count_confidence="Unknown",
        company_description="A residential and light-commercial cleaning service.",
        services="Recurring house cleaning, move-out cleaning, office cleaning",
        all_source_urls=["https://example.com/maps/homestyle-demo"],
    )
    c3.signals = [
        CompanySignal(signal_type="contact_form_present", evidence_text="1 HTML <form> element found", source_url=c3.website),
        CompanySignal(signal_type="quote_request_language", evidence_text="Page uses quote/estimate-request language", source_url=c3.website),
    ]
    merge_field_with_evidence(c3, "phone", "+16025550103", "google_places", confidence="normal")
    companies.append(c3)

    # 4) Real conflict between sources -> should be flagged, not guessed.
    c4 = _base(
        name="Apex Legal Group (Demo)",
        industry="law_firm", city="Chicago", state="IL", zip="60601",
        website="https://example.com/apex-legal-demo",
        review_count=29, google_rating=4.2,
        employee_count="30-50", employee_count_type="Public Range",
        employee_count_source="Law firm directory listing (demo)",
        employee_count_confidence="Medium",
        company_description="A mid-sized law firm handling personal injury and family law cases.",
        services="Personal injury, family law, free case evaluations",
        source_secondary=["website"],
        all_source_urls=["https://example.com/maps/apex-legal-demo", "https://example.com/apex-legal-demo"],
    )
    c4.signals = [
        CompanySignal(signal_type="quote_request_language", evidence_text="Page uses 'free case evaluation' request language", source_url=c4.website),
    ]
    merge_field_with_evidence(c4, "phone", "+13125550104", "google_places", confidence="normal")
    merge_field_with_evidence(c4, "phone", "+13125559999", "website", confidence="normal")  # deliberately different -> Conflicting
    companies.append(c4)

    # 5) Permanently closed -> should be REJECTED outright.
    c5 = _base(
        name="Old Mill Hardware (Demo)",
        industry="retail", city="Columbus", state="OH", zip="43004",
        website="https://example.com/old-mill-hardware-demo",
        website_status="Unreachable",
        business_status="CLOSED_PERMANENTLY",
        employee_count="Unknown", employee_count_type="Unknown",
        company_description="A local hardware store.",
        all_source_urls=["https://example.com/maps/old-mill-demo"],
    )
    companies.append(c5)

    # 6) Real, active business, but clearly outside the employee range ->
    #    REJECTED for ICP fit, not treated as low-quality data.
    c6 = _base(
        name="TinyDesk Bookkeeping (Demo)",
        industry="accounting_firm", city="Denver", state="CO", zip="80202",
        website="https://example.com/tinydesk-bookkeeping-demo",
        review_count=12, google_rating=5.0,
        employee_count="3", employee_count_type="Exact",
        employee_count_source="Team page lists 3 named staff (demo)",
        employee_count_confidence="High",
        company_description="A boutique bookkeeping practice for local small businesses.",
        services="Monthly bookkeeping, tax prep, payroll for small businesses",
        all_source_urls=["https://example.com/maps/tinydesk-demo"],
    )
    c6.signals = [
        CompanySignal(signal_type="contact_form_present", evidence_text="1 HTML <form> element found", source_url=c6.website),
    ]
    merge_field_with_evidence(c6, "phone", "+13035550106", "google_places", confidence="normal")
    companies.append(c6)

    return companies
