"""
Database schema.

Ten tables, matching the spec's section on database design:
    companies, contacts, sources, source_records, company_signals,
    lead_scores, verification_results, crawl_runs, errors, exports

Design notes:
  * `Company` carries the *current* verification/score state directly
    (phone_verification_status, crm_opportunity_score, ...) so exports and
    the CLI don't need a join for the common case.
  * `VerificationResult` and `LeadScore` are append-only audit trails of
    every check/scoring run, so nothing about *why* a status changed is
    ever lost (spec section 31, "Audit Log").
  * Nothing here fabricates data. Nullable fields stay NULL until a
    connector or verification step actually supplies a value — see
    app/utils/normalize.py and app/verification/verify.py for the "Not
    Found" / "Not publicly verified" string constants used when exporting.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Source(Base):
    """One row per connector, e.g. 'google_places', 'website', 'meta_ads'."""

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    # "api" (official, credentialed API) | "own_site_scrape" (a prospect's
    # own public marketing site) | "stub" (interface only, not implemented)
    type = Column(String(32), nullable=False, default="api")

    source_records = relationship("SourceRecord", back_populates="source")


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)

    # --- Identity -----------------------------------------------------
    name = Column(String(255), nullable=False)
    normalized_name = Column(String(255), nullable=False, index=True)
    domain = Column(String(255), index=True)
    website = Column(String(500))
    website_status = Column(String(32), default="Not Checked")  # Active/Unreachable/Not Found/Not Checked

    industry = Column(String(128))
    sub_industry = Column(String(128))

    # --- Contact --------------------------------------------------------
    phone = Column(String(32), index=True)
    phone_verification_status = Column(String(32), default="Not Found")  # Verified/Publicly Listed/Conflicting/Unverified/Not Found
    alternate_phones = Column(JSON, default=list)  # list[str] — kept when sources conflict

    email = Column(String(255))
    email_type = Column(String(32))  # Owner/Decision-Maker, Company Domain, Company Domain (Generic), Free Webmail, Unknown
    email_verification_status = Column(String(32), default="Not Found")  # Verified/Publicly Listed/Conflicting/Unverified/Not Found
    alternate_emails = Column(JSON, default=list)  # list[str] — kept when sources conflict

    # Per-field corroboration trail: {"phone": [{"source": "google_places", "confidence": "normal"}, ...]}
    # This is what phone/email verification status is actually computed
    # from — never a guess based on "looks syntactically valid" (spec:
    # "DO NOT USE FABRICATED VERIFICATION").
    verification_evidence = Column(JSON, default=dict)
    conflicting_fields = Column(JSON, default=list)  # list[str] of field names currently in conflict

    # --- Location ---------------------------------------------------------
    country = Column(String(64))
    state = Column(String(64))
    city = Column(String(128))
    zip = Column(String(16))
    address = Column(String(500))

    # --- External profiles --------------------------------------------
    google_maps_url = Column(String(500))
    facebook_url = Column(String(500))
    linkedin_url = Column(String(500))

    google_rating = Column(Float)
    review_count = Column(Integer)
    business_status = Column(String(32), default="Unknown")  # OPERATIONAL/CLOSED_TEMPORARILY/CLOSED_PERMANENTLY/Unknown

    # --- Advertising evidence (only ever set by a connector that actually checked) ---
    meta_ad_evidence = Column(Text)
    google_ad_evidence = Column(Text)

    # --- Size -------------------------------------------------------------
    employee_count = Column(String(32))  # e.g. "51-100", "Estimated 40-70", "Unknown"
    employee_count_type = Column(String(32), default="Unknown")  # Exact/Public Range/Estimated/Unknown
    employee_count_source = Column(String(255))  # where the figure came from, e.g. "Google Places (type inference)"
    employee_count_confidence = Column(String(16), default="Unknown")  # High/Medium/Low/Unknown

    # --- Narrative ----------------------------------------------------
    services = Column(Text)
    target_customer = Column(Text)
    company_description = Column(Text)

    # --- Provenance -----------------------------------------------------
    source_primary = Column(String(64))
    source_secondary = Column(JSON, default=list)  # list[str] of source names
    all_source_urls = Column(JSON, default=list)  # list[str]

    # --- Conflicts / authenticity --------------------------------------
    contact_conflict = Column(Boolean, default=False)
    conflict_notes = Column(Text)
    lead_authenticity_status = Column(String(32), default="NEEDS_REVIEW")  # VERIFIED/LIKELY_VALID/NEEDS_REVIEW/REJECTED
    rejection_reason = Column(Text)
    duplicate_status = Column(String(64), default="unique")  # unique / duplicate_merged / merged_into:<id>
    merged_into_id = Column(Integer, ForeignKey("companies.id"), nullable=True)

    # --- Scoring (current snapshot; history lives in LeadScore) --------
    crm_opportunity_score = Column(Integer)
    crm_opportunity_level = Column(String(16))  # HOT/VERY HIGH/HIGH/MEDIUM/LOW
    crm_score_breakdown = Column(JSON)
    data_quality_score = Column(Integer)
    data_quality_breakdown = Column(JSON)

    # --- Cold-call output -----------------------------------------------
    cold_call_brief = Column(Text)
    recommended_opening = Column(Text)

    # --- Audit timestamps -------------------------------------------------
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    first_found_at = Column(DateTime(timezone=True), default=utcnow)
    last_verified_at = Column(DateTime(timezone=True))

    contacts = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    source_records = relationship("SourceRecord", back_populates="company", cascade="all, delete-orphan")
    signals = relationship("CompanySignal", back_populates="company", cascade="all, delete-orphan")
    verification_results = relationship("VerificationResult", back_populates="company", cascade="all, delete-orphan")
    lead_scores = relationship("LeadScore", back_populates="company", cascade="all, delete-orphan")

    @property
    def lead_id(self) -> str:
        return f"LEAD-{self.id:05d}" if self.id else "LEAD-PENDING"


class Contact(Base):
    """A decision-maker associated with a company (spec section 10)."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    full_name = Column(String(255))
    title = Column(String(128))
    source_url = Column(String(500))
    verification_status = Column(String(32), default="Unverified")  # Verified/Publicly Identified/Unverified/Not Found

    created_at = Column(DateTime(timezone=True), default=utcnow)

    company = relationship("Company", back_populates="contacts")


class SourceRecord(Base):
    """One raw record as it came from a connector, before/alongside merge
    into the canonical Company row. Preserves per-source traceability even
    after deduplication merges records together (spec section 20)."""

    __tablename__ = "source_records"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)

    source_url = Column(String(500))
    raw_data = Column(JSON)  # the connector's raw dict, for auditability
    date_found = Column(DateTime(timezone=True), default=utcnow)

    company = relationship("Company", back_populates="source_records")
    source = relationship("Source", back_populates="source_records")


class CompanySignal(Base):
    """Evidence used by the scoring engine — e.g. 'has_contact_form',
    'meta_ad_activity', 'multiple_locations'. Kept as discrete rows (rather
    than boolean columns on Company) so new signal types don't need a
    migration (spec section 16, "CRM Opportunity Analysis")."""

    __tablename__ = "company_signals"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    signal_type = Column(String(64), nullable=False)
    evidence_text = Column(Text)
    source_url = Column(String(500))
    detected_at = Column(DateTime(timezone=True), default=utcnow)

    company = relationship("Company", back_populates="signals")


class VerificationResult(Base):
    """Audit trail: every time a field's verification status is
    (re)computed, a row goes here — independent of the current snapshot
    stored directly on Company (spec section 31, "Audit Log")."""

    __tablename__ = "verification_results"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    field_name = Column(String(32), nullable=False)  # phone/email/website/company_name
    status = Column(String(32), nullable=False)
    method = Column(String(64))  # e.g. cross_source_match, http_head_check
    notes = Column(Text)
    checked_at = Column(DateTime(timezone=True), default=utcnow)

    company = relationship("Company", back_populates="verification_results")


class LeadScore(Base):
    """Audit trail of scoring runs. Company.crm_opportunity_score /
    data_quality_score always mirror the most recent row here."""

    __tablename__ = "lead_scores"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    crm_opportunity_score = Column(Integer, nullable=False)
    crm_opportunity_level = Column(String(16), nullable=False)
    data_quality_score = Column(Integer, nullable=False)
    breakdown = Column(JSON)  # full sub-score dict for both scores
    scored_at = Column(DateTime(timezone=True), default=utcnow)

    company = relationship("Company", back_populates="lead_scores")


class CrawlRun(Base):
    """One row per `pipeline` / `discover` invocation — powers
    RUN_REPORT.xlsx / .json (spec section 52)."""

    __tablename__ = "crawl_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String(16), default="running")  # running/completed/failed
    config_snapshot = Column(JSON)
    stats_json = Column(JSON)

    errors = relationship("ErrorLog", back_populates="crawl_run")
    exports = relationship("ExportLog", back_populates="crawl_run")


class ErrorLog(Base):
    """Every handled error, so a bad website/timeout/malformed result never
    crashes a run — it's logged and processing continues (spec section 29)."""

    __tablename__ = "errors"

    id = Column(Integer, primary_key=True)
    crawl_run_id = Column(Integer, ForeignKey("crawl_runs.id"), nullable=True)

    source = Column(String(64))
    company_name = Column(String(255))
    operation = Column(String(64))
    error_message = Column(Text)
    timestamp = Column(DateTime(timezone=True), default=utcnow)

    crawl_run = relationship("CrawlRun", back_populates="errors")


class ExportLog(Base):
    __tablename__ = "exports"

    id = Column(Integer, primary_key=True)
    crawl_run_id = Column(Integer, ForeignKey("crawl_runs.id"), nullable=True)

    filename = Column(String(255), nullable=False)
    row_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    crawl_run = relationship("CrawlRun", back_populates="exports")


__all__ = [
    "Base",
    "Source",
    "Company",
    "Contact",
    "SourceRecord",
    "CompanySignal",
    "VerificationResult",
    "LeadScore",
    "CrawlRun",
    "ErrorLog",
    "ExportLog",
]
