"""
Pipeline orchestration.

Stage order: DISCOVER -> NORMALIZE -> ENRICH -> DEDUPLICATE -> VERIFY ->
SCORE -> GENERATE BRIEFS -> FILTER -> EXPORT.

This reorders two stages relative to the original brief's literal
DISCOVER->NORMALIZE->VERIFY->ENRICH->DEDUPLICATE->SCORE order, for a
concrete reason worth stating rather than silently deviating: enrichment
adds the fields (a second phone/email source, CRM signals) that
deduplication and verification actually need to compare, and
deduplication should merge same-company records from different
connectors into one canonical row *before* verification/scoring run —
otherwise you'd verify and score fragments and immediately redo it after
merging anyway. Every other guarantee from the brief holds: one
connector's failure never stops the run (ConnectorUnavailableError and
any unexpected exception are both caught, logged to ErrorLog, and
processing continues), and nothing is exported without going through
real verification and scoring first.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from app.coldcall.brief import generate_brief_and_opening
from app.connectors.base import ConnectorUnavailableError, RawLead
from app.connectors.registry import build_connector, enabled_connector_names
from app.connectors.search_terms import build_queries, resolve_industries
from app.core.config import PROJECT_ROOT, TargetingConfig, get_targeting_config
from app.core.db import session_scope
from app.core.logging_config import get_logger
from app.deduplication.dedup import deduplicate_companies
from app.enrichment.website_analysis import WebsiteEnrichmentConnector, WebsiteEnrichmentResult
from app.exports import excel_export
from app.models.models import Company, CompanySignal, Contact, CrawlRun, ErrorLog, ExportLog, Source, SourceRecord
from app.scoring.scoring import score_company
from app.utils.merge import fill_if_empty, merge_field_with_evidence
from app.utils.normalize import classify_email_type, extract_domain, normalize_company_name, normalize_email, normalize_phone
from app.verification.verify import classify_and_bucket, verify_company

logger = get_logger("pipeline")

DATA_DIR = PROJECT_ROOT / "data"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _raw_lead_to_json(lead: RawLead) -> dict:
    data = dataclasses.asdict(lead)
    data["date_found"] = lead.date_found.isoformat()
    return data


def _dump_snapshot(subfolder: str, run_id: int, tag: str, payload) -> None:
    """Best-effort audit snapshot into data/<subfolder>/. Losing a
    snapshot must never crash a run -- it's an audit convenience, not the
    system of record (the database is)."""
    try:
        target_dir = DATA_DIR / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = target_dir / f"run{run_id}_{tag}_{_utcnow().strftime('%Y%m%dT%H%M%S')}.json"
        with open(filename, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
    except OSError as exc:
        logger.warning("Could not write audit snapshot %s/%s: %s", subfolder, tag, exc)


class Pipeline:
    def __init__(self, config: Optional[TargetingConfig] = None) -> None:
        self.config = config or get_targeting_config()

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------

    def run(self, industries: Optional[List[str]] = None, location: str = "", demo: bool = False) -> Dict:
        with session_scope() as session:
            crawl_run = CrawlRun(started_at=_utcnow(), status="running", config_snapshot=dataclasses.asdict(self.config))
            session.add(crawl_run)
            session.flush()
            run_id = crawl_run.id

            stats: Dict = {
                "discovered": 0, "duplicates": 0, "rejected": 0, "needs_review": 0,
                "verified": 0, "qualified": 0, "by_source": {}, "by_industry": {}, "by_state": {},
            }

            try:
                if demo:
                    companies = self._run_demo(session)
                else:
                    companies = self._run_live(session, crawl_run, industries, location)

                session.flush()
                stats["discovered"] = len(companies)

                survivors = deduplicate_companies(companies)
                stats["duplicates"] = len(companies) - len(survivors)

                for company in survivors:
                    verify_company(session, company)
                    score_company(company, self.config)
                    generate_brief_and_opening(company)

                buckets: Dict[str, List[Company]] = classify_and_bucket(survivors, self.config)

                stats["qualified"] = len(buckets["master"])
                stats["needs_review"] = len(buckets["needs_review"])
                stats["rejected"] = len(buckets["rejected"])
                stats["verified"] = sum(
                    1 for c in survivors
                    if c.phone_verification_status == "Verified" or c.email_verification_status == "Verified"
                )
                for c in survivors:
                    stats["by_source"][c.source_primary] = stats["by_source"].get(c.source_primary, 0) + 1
                    if c.industry:
                        stats["by_industry"][c.industry] = stats["by_industry"].get(c.industry, 0) + 1
                    if c.state:
                        stats["by_state"][c.state] = stats["by_state"].get(c.state, 0) + 1

                session.flush()
                _dump_snapshot("verified", run_id, "master", [c.name for c in buckets["master"]])
                _dump_snapshot("rejected", run_id, "rejected", [{"name": c.name, "reason": c.rejection_reason} for c in buckets["rejected"]])

                export_paths = excel_export.export_all(session, buckets)
                for path in export_paths:
                    session.add(ExportLog(crawl_run_id=run_id, filename=Path(path).name, row_count=0))

                excel_export.write_run_report(run_id, stats, export_paths)

                crawl_run.status = "completed"
                crawl_run.finished_at = _utcnow()
                crawl_run.stats_json = stats

                return {"run_id": run_id, "stats": stats, "exports": export_paths}

            except Exception as exc:  # noqa: BLE001 - top-level guard: always record *why* a run failed
                crawl_run.status = "failed"
                crawl_run.finished_at = _utcnow()
                session.add(ErrorLog(crawl_run_id=run_id, source="pipeline", operation="run", error_message=str(exc)))
                logger.exception("Pipeline run failed")
                raise

    # ------------------------------------------------------------------
    # Demo mode — no network, exercises scoring/verification/export
    # ------------------------------------------------------------------

    def _run_demo(self, session) -> List[Company]:
        from app.connectors.demo_data import build_demo_companies

        companies = build_demo_companies()
        demo_source = self._get_or_create_source(session, "demo")
        for company in companies:
            session.add(company)
        session.flush()
        for company in companies:
            session.add(SourceRecord(
                company_id=company.id, source_id=demo_source.id,
                source_url=(company.all_source_urls or [None])[0],
                raw_data={"note": "Synthetic demo fixture -- not a real scraped lead."},
                date_found=_utcnow(),
            ))
        return companies

    # ------------------------------------------------------------------
    # Live mode
    # ------------------------------------------------------------------

    def _run_live(self, session, crawl_run: CrawlRun, industries: Optional[List[str]], location: str) -> List[Company]:
        industry_keys = resolve_industries(industries or self.config.industries)
        connector_names = enabled_connector_names(self.config)
        all_companies: List[Company] = []

        for connector_name in connector_names:
            try:
                connector = build_connector(connector_name)
            except KeyError as exc:
                logger.error(str(exc))
                continue

            if not connector.is_available():
                logger.warning("[%s] unavailable, skipping (%s)", connector_name, connector.capability_summary)
                session.add(ErrorLog(crawl_run_id=crawl_run.id, source=connector_name, operation="availability_check",
                                      error_message="Connector reported itself unavailable before any request was made."))
                continue

            source_row = self._get_or_create_source(session, connector_name)

            for industry_key in industry_keys:
                for query in build_queries(industry_key, location):
                    try:
                        raw_leads = connector.discover(query, location=location, max_results=self.config.max_results_per_query)
                    except ConnectorUnavailableError as exc:
                        logger.warning("[%s] became unavailable mid-run: %s", connector_name, exc)
                        session.add(ErrorLog(crawl_run_id=crawl_run.id, source=connector_name, operation="discover", error_message=str(exc)))
                        break
                    except Exception as exc:  # noqa: BLE001 - one bad query must not kill the whole run
                        logger.exception("[%s] discover failed for %r", connector_name, query)
                        session.add(ErrorLog(crawl_run_id=crawl_run.id, source=connector_name, operation="discover", error_message=str(exc)))
                        continue

                    _dump_snapshot("raw", crawl_run.id, connector_name, [_raw_lead_to_json(rl) for rl in raw_leads])

                    for raw_lead in raw_leads:
                        raw_lead.industry = raw_lead.industry or industry_key.replace("_", " ")
                        company = self._normalize_and_persist(session, raw_lead, source_row)
                        if company is not None:
                            all_companies.append(company)

        session.flush()
        _dump_snapshot("processed", crawl_run.id, "normalized", [{"name": c.name, "domain": c.domain} for c in all_companies])

        if self.config.sources.website_enrichment:
            website_connector = WebsiteEnrichmentConnector()
            for company in all_companies:
                if company.website and company.website_status == "Not Checked":
                    try:
                        result = website_connector.enrich(company.website)
                        self._merge_website_result(company, result)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Website enrichment failed for %s", company.name)
                        session.add(ErrorLog(crawl_run_id=crawl_run.id, source="website", company_name=company.name,
                                              operation="enrich", error_message=str(exc)))

        return all_companies

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_or_create_source(session, name: str) -> Source:
        source = session.query(Source).filter_by(name=name).one_or_none()
        if source is None:
            source_type = "own_site_scrape" if name == "website" else ("stub" if name == "linkedin" else "api")
            source = Source(name=name, type=source_type)
            session.add(source)
            session.flush()
        return source

    def _normalize_and_persist(self, session, raw_lead: RawLead, source_row: Source) -> Optional[Company]:
        if not raw_lead.company_name or raw_lead.company_name.strip().lower() == "unknown":
            return None

        normalized_phone = normalize_phone(raw_lead.phone)
        normalized_email = normalize_email(raw_lead.email)
        domain = extract_domain(raw_lead.website) if raw_lead.website else None

        company = Company(
            name=raw_lead.company_name.strip(),
            normalized_name=normalize_company_name(raw_lead.company_name),
            domain=domain,
            website=raw_lead.website,
            industry=raw_lead.industry,
            address=raw_lead.address, city=raw_lead.city, state=raw_lead.state, zip=raw_lead.zip,
            country=raw_lead.country or self.config.country,
            google_maps_url=raw_lead.google_maps_url, facebook_url=raw_lead.facebook_url, linkedin_url=raw_lead.linkedin_url,
            google_rating=raw_lead.google_rating, review_count=raw_lead.review_count,
            business_status=raw_lead.business_status or "Unknown",
            employee_count=raw_lead.employee_count, employee_count_type=raw_lead.employee_count_type or "Unknown",
            employee_count_source=raw_lead.employee_count_source,
            meta_ad_evidence=raw_lead.meta_ad_evidence, google_ad_evidence=raw_lead.google_ad_evidence,
            services=raw_lead.services, company_description=raw_lead.description,
            source_primary=raw_lead.source,
            all_source_urls=[raw_lead.source_url] if raw_lead.source_url else [],
            duplicate_status="unique",
            first_found_at=raw_lead.date_found,
        )
        if normalized_phone:
            merge_field_with_evidence(company, "phone", normalized_phone, raw_lead.source)
        if normalized_email:
            merge_field_with_evidence(company, "email", normalized_email, raw_lead.source)
            company.email_type = classify_email_type(normalized_email)

        if raw_lead.owner_name:
            company.contacts.append(Contact(
                full_name=raw_lead.owner_name, title=raw_lead.owner_title or "Unknown",
                source_url=raw_lead.owner_source_url, verification_status="Unverified",
            ))

        session.add(company)
        session.flush()
        session.add(SourceRecord(
            company_id=company.id, source_id=source_row.id, source_url=raw_lead.source_url,
            raw_data=_raw_lead_to_json(raw_lead), date_found=raw_lead.date_found,
        ))
        return company

    @staticmethod
    def _merge_website_result(company: Company, result: WebsiteEnrichmentResult) -> None:
        company.website_status = result.status
        if result.final_url:
            company.website = result.final_url

        fill_if_empty(company, "company_description", result.meta_description)
        fill_if_empty(company, "services", result.services_text)

        for phone in result.structured_phones:
            merge_field_with_evidence(company, "phone", phone, "website", confidence="normal", alt_list_field="alternate_phones")
        for phone in result.extracted_phones:
            merge_field_with_evidence(company, "phone", phone, "website_text_match", confidence="low", alt_list_field="alternate_phones")
        for email in result.extracted_emails:
            merge_field_with_evidence(company, "email", email, "website", confidence="normal", alt_list_field="alternate_emails")
            if not company.email_type or company.email_type == "Unknown":
                company.email_type = classify_email_type(company.email)

        if result.candidate_decision_maker and not company.contacts:
            candidate = result.candidate_decision_maker
            company.contacts.append(Contact(
                full_name=candidate["name"], title=candidate["title"],
                source_url=candidate["source_url"], verification_status=candidate["status"],
            ))

        for sig in result.signals:
            company.signals.append(CompanySignal(
                signal_type=sig["signal_type"], evidence_text=sig["evidence_text"], source_url=sig.get("source_url"),
            ))

        company.all_source_urls = list(dict.fromkeys((company.all_source_urls or []) + result.pages_checked))
        if company.source_primary != "website" and "website" not in (company.source_secondary or []):
            secondary = list(company.source_secondary or [])
            secondary.append("website")
            company.source_secondary = secondary
