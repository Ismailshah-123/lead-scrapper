"""
CLI entry point. Run as `python -m app <command>`.

    python -m app initdb
    python -m app sources
    python -m app demo
    python -m app pipeline --industry roofing --location "Texas"
    python -m app discover --source google_places --industry hvac --location "Dallas, TX"
    python -m app enrich
    python -m app verify
    python -m app deduplicate
    python -m app score
    python -m app export

The granular commands (discover/enrich/verify/deduplicate/score/export)
operate on whatever is already in the database — useful for re-running one
stage after tuning config.yaml without repeating the others. `pipeline`
and `demo` run the whole thing end to end in one call and are the ones
most people will actually use day to day.
"""
from __future__ import annotations

import argparse
import json

from app.connectors.registry import all_connector_descriptions, build_connector, enabled_connector_names
from app.connectors.search_terms import build_queries, resolve_industries
from app.core.config import get_targeting_config
from app.core.db import init_db, session_scope
from app.core.logging_config import configure_logging, get_logger
from app.deduplication.dedup import deduplicate_companies
from app.enrichment.website_analysis import WebsiteEnrichmentConnector
from app.exports import excel_export
from app.models.models import Company
from app.pipeline import Pipeline
from app.scoring.scoring import score_company
from app.verification.verify import classify_and_bucket, verify_company

logger = get_logger("cli")


def _active_companies(session):
    return session.query(Company).filter(Company.duplicate_status == "unique").all()


def cmd_initdb(_args) -> None:
    init_db()
    print("Database initialized (tables created if they didn't already exist).")


def cmd_sources(_args) -> None:
    print(f"{'NAME':<16} {'AVAILABILITY':<12} SUMMARY")
    print("-" * 100)
    for desc in all_connector_descriptions():
        print(f"{desc['name']:<16} {desc['availability']:<12} {desc['summary']}")


def cmd_demo(_args) -> None:
    result = Pipeline().run(demo=True)
    _print_result(result)


def cmd_pipeline(args) -> None:
    config = get_targeting_config()
    result = Pipeline(config).run(industries=args.industry, location=args.location or "")
    _print_result(result)


def cmd_discover(args) -> None:
    config = get_targeting_config()
    industries = resolve_industries(args.industry or config.industries)
    sources = [args.source] if args.source else enabled_connector_names(config)

    with session_scope() as session:
        from app.pipeline import Pipeline as _Pipeline
        pipeline = _Pipeline(config)
        from app.models.models import CrawlRun
        import datetime as dt
        crawl_run = CrawlRun(started_at=dt.datetime.now(dt.timezone.utc), status="running")
        session.add(crawl_run)
        session.flush()

        total = 0
        for source_name in sources:
            try:
                connector = build_connector(source_name)
            except KeyError as exc:
                print(str(exc))
                continue
            if not connector.is_available():
                print(f"[{source_name}] unavailable: {connector.capability_summary}")
                continue
            source_row = pipeline._get_or_create_source(session, source_name)
            for industry_key in industries:
                for query in build_queries(industry_key, args.location or ""):
                    try:
                        raw_leads = connector.discover(query, location=args.location or "", max_results=config.max_results_per_query)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[{source_name}] {query!r} failed: {exc}")
                        continue
                    for raw_lead in raw_leads:
                        raw_lead.industry = raw_lead.industry or industry_key.replace("_", " ")
                        company = pipeline._normalize_and_persist(session, raw_lead, source_row)
                        if company is not None:
                            total += 1
        crawl_run.status = "completed"
        print(f"Discovered {total} raw company record(s). Run `python -m app enrich` next.")


def cmd_enrich(_args) -> None:
    with session_scope() as session:
        connector = WebsiteEnrichmentConnector()
        companies = [c for c in _active_companies(session) if c.website and c.website_status == "Not Checked"]
        for company in companies:
            result = connector.enrich(company.website)
            Pipeline._merge_website_result(company, result)
        print(f"Enriched {len(companies)} compan(y/ies) with a website.")


def cmd_verify(_args) -> None:
    with session_scope() as session:
        companies = _active_companies(session)
        for company in companies:
            verify_company(session, company)
        print(f"Verified {len(companies)} compan(y/ies).")


def cmd_deduplicate(_args) -> None:
    with session_scope() as session:
        companies = _active_companies(session)
        survivors = deduplicate_companies(companies)
        print(f"{len(companies)} record(s) -> {len(survivors)} after deduplication.")


def cmd_score(_args) -> None:
    config = get_targeting_config()
    with session_scope() as session:
        companies = _active_companies(session)
        for company in companies:
            score_company(company, config)
        print(f"Scored {len(companies)} compan(y/ies).")


def cmd_export(_args) -> None:
    config = get_targeting_config()
    with session_scope() as session:
        companies = _active_companies(session)
        buckets = classify_and_bucket(companies, config)
        paths = excel_export.export_all(session, buckets)
        excel_export.write_run_report(0, {
            "discovered": len(companies), "duplicates": 0,
            "verified": sum(1 for c in companies if c.phone_verification_status == "Verified" or c.email_verification_status == "Verified"),
            "qualified": len(buckets["master"]), "needs_review": len(buckets["needs_review"]), "rejected": len(buckets["rejected"]),
            "by_source": {}, "by_industry": {}, "by_state": {},
        }, paths)
        print("Exported:")
        for path in paths:
            print(f"  {path}")


def _print_result(result: dict) -> None:
    print(json.dumps(result, indent=2, default=str))
    print("\nExports written to ./exports/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="Lead Intelligence Engine CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="Create database tables").set_defaults(func=cmd_initdb)
    sub.add_parser("sources", help="List every connector and its availability tier").set_defaults(func=cmd_sources)
    sub.add_parser("demo", help="Run the full pipeline on synthetic demo data (no API keys needed)").set_defaults(func=cmd_demo)

    p = sub.add_parser("pipeline", help="Run discover -> ... -> export end to end")
    p.add_argument("--industry", action="append", help="Industry key (repeatable). Default: config.yaml")
    p.add_argument("--location", default="", help='e.g. "Texas" or "Austin, TX"')
    p.set_defaults(func=cmd_pipeline)

    d = sub.add_parser("discover", help="Run discovery + normalization only")
    d.add_argument("--source", help="One connector name (default: every enabled connector)")
    d.add_argument("--industry", action="append", help="Industry key (repeatable). Default: config.yaml")
    d.add_argument("--location", default="")
    d.set_defaults(func=cmd_discover)

    sub.add_parser("enrich", help="Run website enrichment on companies not yet checked").set_defaults(func=cmd_enrich)
    sub.add_parser("verify", help="Recompute verification statuses for all companies").set_defaults(func=cmd_verify)
    sub.add_parser("deduplicate", help="Merge duplicate company records").set_defaults(func=cmd_deduplicate)
    sub.add_parser("score", help="Recompute CRM Opportunity / Data Quality scores").set_defaults(func=cmd_score)
    sub.add_parser("export", help="Classify current data and write every Excel export").set_defaults(func=cmd_export)

    return parser


def main(argv=None) -> None:
    configure_logging()
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
