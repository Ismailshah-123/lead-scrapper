"""
Search query templates, one list per industry.

Per the spec: don't just search "roofing companies" — search for the CRM
*opportunity* signal too ("roofing companies running ads", "HVAC companies
request quote"). Google Places/Search connectors pull from here rather
than hardcoding query strings, so tuning targeting is a config-file-level
change, not a code change.

This list is intentionally a practical subset (not all ~35 industries the
original brief mentions) — add more by adding a key here; nothing else
needs to change. Use industries: ["ALL"] in config.yaml to run every key.
"""
from __future__ import annotations

from typing import Dict, List

INDUSTRY_QUERY_TEMPLATES: Dict[str, List[str]] = {
    "roofing": [
        "roofing companies",
        "roofing contractors free estimate",
        "roofing company storm damage repair",
    ],
    "hvac": [
        "HVAC companies",
        "HVAC repair request quote",
        "air conditioning installation company",
    ],
    "plumbing": [
        "plumbing companies",
        "plumbing contractor emergency service",
        "plumbing company request quote",
    ],
    "construction": [
        "construction companies",
        "general contractor multiple locations",
        "construction company request estimate",
    ],
    "remodeling": [
        "home remodeling companies",
        "kitchen bathroom remodeling request quote",
    ],
    "landscaping": [
        "landscaping companies",
        "commercial landscaping request quote",
    ],
    "cleaning_services": [
        "commercial cleaning companies",
        "cleaning service request quote",
    ],
    "solar": [
        "solar installation companies",
        "solar panel company free consultation",
    ],
    "real_estate": [
        "real estate agencies",
        "real estate brokerage sales team",
    ],
    "property_management": [
        "property management companies",
        "property management company multiple properties",
    ],
    "insurance_agency": [
        "insurance agencies",
        "independent insurance agency request quote",
    ],
    "financial_services": [
        "financial advisory firms",
        "financial services firm consultation request",
    ],
    "dental": [
        "dental practices",
        "dental clinic appointment booking online",
    ],
    "healthcare_clinic": [
        "medical clinics",
        "healthcare clinic appointment booking",
    ],
    "law_firm": [
        "law firms",
        "law firm free consultation request",
    ],
    "accounting_firm": [
        "accounting firms",
        "CPA firm request consultation",
    ],
    "marketing_agency": [
        "marketing agencies",
        "digital marketing agency lead generation clients",
    ],
    "recruitment_staffing": [
        "staffing agencies",
        "recruitment agency multiple clients",
    ],
    "it_services": [
        "IT services companies",
        "managed IT services provider request quote",
    ],
    "security_companies": [
        "security services companies",
        "commercial security company request quote",
    ],
    "logistics_transportation": [
        "logistics companies",
        "transportation company multiple locations",
    ],
    "auto_dealership": [
        "auto dealerships",
        "car dealership sales team",
    ],
    "auto_repair": [
        "auto repair shops",
        "auto repair shop appointment booking",
    ],
    "education_training": [
        "training companies",
        "corporate training provider request quote",
    ],
    "manufacturing_wholesale": [
        "manufacturing companies",
        "wholesale distributor B2B sales team",
    ],
    "hospitality_travel": [
        "hospitality management companies",
        "travel agency corporate clients",
    ],
}


def resolve_industries(configured: List[str]) -> List[str]:
    """Expand "ALL" into every known industry key; otherwise return only
    the keys that actually exist in the template map (silently skipping
    typos rather than crashing a whole run over one bad config line —
    the caller's logger should still warn about unknown keys)."""
    if not configured or "ALL" in [c.upper() for c in configured]:
        return list(INDUSTRY_QUERY_TEMPLATES.keys())
    return [key for key in configured if key in INDUSTRY_QUERY_TEMPLATES]


def build_queries(industry_key: str, location: str = "") -> List[str]:
    templates = INDUSTRY_QUERY_TEMPLATES.get(industry_key, [industry_key.replace("_", " ")])
    if location:
        return [f"{t} in {location}" for t in templates]
    return list(templates)
