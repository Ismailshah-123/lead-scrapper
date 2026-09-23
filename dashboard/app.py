from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd
import streamlit as st

# Make `app/` importable even when Streamlit is launched from another cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.connectors.registry import all_connector_descriptions  # noqa: E402
from app.coldcall.brief import generate_brief_and_opening  # noqa: E402
from app.core.config import get_secrets, get_targeting_config, reset_config_cache  # noqa: E402
from app.core.db import init_db, session_scope  # noqa: E402
from app.models.models import Company, Contact, CompanySignal, SourceRecord  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.scoring.scoring import score_company  # noqa: E402
from app.deduplication.dedup import deduplicate_companies  # noqa: E402
from app.verification.verify import verify_company  # noqa: E402

st.set_page_config(
    page_title="Lead Intelligence Engine",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --navy: #0b2545;
            --blue: #2563eb;
            --blue-soft: #eff6ff;
            --ink: #0f172a;
            --muted: #64748b;
            --line: #dbe4f0;
            --bg: #f6f9fd;
            --card: #ffffff;
            --good: #16845b;
            --warn: #a16207;
            --bad: #c2413d;
        }

        .stApp { background: var(--bg); color: var(--ink); }
        .block-container { padding-top: 1.1rem; padding-bottom: 2.5rem; max-width: 1480px; }
        [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
        [data-testid="stSidebar"] .block-container { padding-top: 1.1rem; }
        h1, h2, h3 { color: var(--navy); letter-spacing: -0.02em; }
        h1 { font-size: 2rem !important; }
        h2 { font-size: 1.3rem !important; }
        h3 { font-size: 1rem !important; }

        .brand { display:flex; gap:12px; align-items:center; padding: 8px 0 18px; }
        .brand-mark { width:40px; height:40px; border-radius:12px; background:var(--navy); color:white; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:18px; }
        .brand-name { font-weight:700; color:var(--navy); font-size:16px; line-height:1.15; }
        .brand-sub { color:var(--muted); font-size:11px; margin-top:3px; }

        .hero { background:linear-gradient(180deg,#ffffff 0%,#f8fbff 100%); border:1px solid var(--line); border-radius:18px; padding:22px 24px; margin-bottom:18px; }
        .eyebrow { color:var(--blue); font-size:11px; font-weight:700; letter-spacing:.10em; text-transform:uppercase; }
        .hero-title { color:var(--navy); font-size:28px; font-weight:750; margin-top:5px; }
        .hero-text { color:#526277; max-width:900px; line-height:1.55; margin-top:5px; }

        .metric-card { background:var(--card); border:1px solid var(--line); border-radius:15px; padding:16px 17px; min-height:114px; box-shadow:0 2px 10px rgba(15,23,42,.03); }
        .metric-label { color:var(--muted); font-size:12px; font-weight:650; }
        .metric-value { color:var(--navy); font-size:28px; line-height:1.1; font-weight:750; margin-top:7px; }
        .metric-help { color:#8290a3; font-size:11px; margin-top:7px; }

        .section-card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:18px 19px; box-shadow:0 2px 10px rgba(15,23,42,.025); }
        .section-title { color:var(--navy); font-weight:700; font-size:14px; margin-bottom:12px; }
        .muted { color:var(--muted); }
        .status-pill { display:inline-flex; align-items:center; gap:6px; padding:5px 9px; border-radius:999px; border:1px solid var(--line); background:#fff; font-size:11px; font-weight:700; }
        .dot { width:7px; height:7px; border-radius:50%; display:inline-block; }
        .dot-good { background:var(--good); }
        .dot-warn { background:#d39d28; }
        .dot-bad { background:var(--bad); }
        .dot-neutral { background:#94a3b8; }

        .lead-id { color:var(--blue); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; font-weight:700; }
        .small-label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; font-weight:700; }
        .detail-value { color:var(--ink); font-size:14px; margin-top:3px; }
        .notice { background:var(--blue-soft); border:1px solid #cfe0ff; color:#214a87; border-radius:12px; padding:11px 13px; font-size:12px; line-height:1.5; }
        .warning { background:#fffaf0; border:1px solid #f0d79c; color:#7a5a08; border-radius:12px; padding:11px 13px; font-size:12px; line-height:1.5; }
        .errorbox { background:#fff6f6; border:1px solid #f3cccc; color:#8b3131; border-radius:12px; padding:11px 13px; font-size:12px; line-height:1.5; }

        div[data-testid="stMetric"] { background:var(--card); border:1px solid var(--line); border-radius:15px; padding:12px 15px; }
        .stButton > button, .stDownloadButton > button { border-radius:10px; font-weight:650; border:1px solid #cfd9e7; }
        .stButton > button[kind="primary"] { background:var(--navy); border-color:var(--navy); }
        .stButton > button[kind="primary"]:hover { background:#113761; border-color:#113761; }
        .stTabs [data-baseweb="tab"] { font-weight:650; }
        .stDataFrame { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_html(label: str, state: str) -> str:
    state_lower = state.lower()
    if "available" in state_lower or "connected" in state_lower or "ready" in state_lower:
        dot = "dot-good"
    elif "limited" in state_lower or "configured" in state_lower or "review" in state_lower:
        dot = "dot-warn"
    elif "error" in state_lower or "unavailable" in state_lower or "missing" in state_lower:
        dot = "dot-bad"
    else:
        dot = "dot-neutral"
    return f'<span class="status-pill"><span class="dot {dot}"></span>{label}: {state}</span>'


def safe_init_db() -> None:
    try:
        init_db()
    except Exception:
        # Individual pages surface the actual problem when the DB is queried.
        pass


def unique_companies(session) -> list[Company]:
    return (
        session.query(Company)
        .filter(Company.duplicate_status == "unique")
        .order_by(Company.updated_at.desc(), Company.id.desc())
        .all()
    )


def company_rows(companies: Iterable[Company]) -> pd.DataFrame:
    rows = []
    for c in companies:
        rows.append(
            {
                "Lead ID": c.lead_id,
                "Company": c.name,
                "Industry": c.industry or "Not Found",
                "City": c.city or "Not Found",
                "State": c.state or "Not Found",
                "Phone": c.phone or "Not Found",
                "Email": c.email or "Not Found",
                "Employees": c.employee_count or "Unknown",
                "CRM Score": c.crm_opportunity_score if c.crm_opportunity_score is not None else 0,
                "Quality": c.data_quality_score if c.data_quality_score is not None else 0,
                "Status": c.lead_authenticity_status or "NEEDS_REVIEW",
                "Source": c.source_primary or "Unknown",
            }
        )
    return pd.DataFrame(rows)


def run_cli(command: list[str]) -> tuple[bool, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "app", *command],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=1800,
        env=os.environ.copy(),
    )
    return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()


def refresh_config() -> None:
    reset_config_cache()
    st.cache_data.clear()


@st.cache_data(ttl=10)
def dashboard_snapshot() -> dict:
    init_db()
    with session_scope() as session:
        companies = unique_companies(session)
        statuses = {}
        industries = {}
        states = {}
        sources = {}
        for c in companies:
            status = c.lead_authenticity_status or "NEEDS_REVIEW"
            statuses[status] = statuses.get(status, 0) + 1
            if c.industry:
                industries[c.industry] = industries.get(c.industry, 0) + 1
            if c.state:
                states[c.state] = states.get(c.state, 0) + 1
            if c.source_primary:
                sources[c.source_primary] = sources.get(c.source_primary, 0) + 1
        return {
            "total": len(companies),
            "verified": sum(1 for c in companies if (c.phone_verification_status == "Verified" or c.email_verification_status == "Verified")),
            "qualified": statuses.get("VERIFIED", 0) + statuses.get("LIKELY_VALID", 0),
            "needs_review": statuses.get("NEEDS_REVIEW", 0),
            "rejected": statuses.get("REJECTED", 0),
            "avg_crm": round(sum((c.crm_opportunity_score or 0) for c in companies) / len(companies), 1) if companies else 0,
            "avg_quality": round(sum((c.data_quality_score or 0) for c in companies) / len(companies), 1) if companies else 0,
            "industries": industries,
            "states": states,
            "sources": sources,
        }


def render_metric(label: str, value: str | int | float, help_text: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-help">{help_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="hero"><div class="eyebrow">Lead Intelligence Platform</div><div class="hero-title">{title}</div><div class="hero-text">{subtitle}</div></div>', unsafe_allow_html=True)


def render_sidebar() -> str:
    st.sidebar.markdown(
        '<div class="brand"><div class="brand-mark">LI</div><div><div class="brand-name">Lead Intelligence<br>Engine</div><div class="brand-sub">B2B discovery & verification</div></div></div>',
        unsafe_allow_html=True,
    )
    page = st.sidebar.radio(
        "Navigation",
        [
            "Dashboard",
            "Lead Discovery",
            "Leads",
            "Verification & Scoring",
            "Cold Call Prospects",
            "Exports",
            "System Status",
            "Settings",
        ],
        label_visibility="collapsed",
    )

    st.sidebar.divider()
    try:
        secrets = get_secrets()
        config = get_targeting_config()
        providers = {
            "Google Places": bool(secrets.google_places_api_key),
            "Exa": bool(secrets.exa_api_key),
            "xAI / Grok": bool(secrets.xai_api_key) and secrets.llm_provider.lower() == "xai",
        }
        st.sidebar.markdown("**Services**")
        for label, ok in providers.items():
            st.sidebar.markdown(status_html(label, "Connected" if ok else "Not configured"), unsafe_allow_html=True)
        st.sidebar.caption(f"Target: {config.country} · {config.employee_min}-{config.employee_max} employees")
    except Exception as exc:
        st.sidebar.markdown(status_html("Config", "Error"), unsafe_allow_html=True)
        st.sidebar.caption(str(exc))
    return page


def dashboard_page() -> None:
    render_header("Turn raw discovery into sales-ready intelligence", "A single workspace for discovery, enrichment, verification, scoring, cold-call briefs, and Excel exports — backed by the existing Lead Intelligence Engine pipeline.")
    try:
        snap = dashboard_snapshot()
    except Exception as exc:
        st.error(f"Database is not ready: {exc}")
        if st.button("Initialize database", type="primary"):
            init_db()
            dashboard_snapshot.clear()
            st.rerun()
        return

    cols = st.columns(7)
    metrics = [
        ("Total Leads", snap["total"], "Unique company records"),
        ("Verified", snap["verified"], "Phone or email verified"),
        ("Qualified", snap["qualified"], "Verified / likely valid"),
        ("Needs Review", snap["needs_review"], "Manual review required"),
        ("Rejected", snap["rejected"], "Did not pass quality gate"),
        ("Avg CRM Score", snap["avg_crm"], "Opportunity score / 100"),
        ("Avg Data Quality", snap["avg_quality"], "Trust / completeness / 100"),
    ]
    for col, (label, value, help_text) in zip(cols, metrics):
        with col:
            render_metric(label, value, help_text)

    st.write("")
    left, right = st.columns([1.2, 1])
    with left:
        st.markdown('<div class="section-card"><div class="section-title">Lead pipeline</div>', unsafe_allow_html=True)
        pipeline_df = pd.DataFrame(
            {"Stage": ["Discovered", "Verified", "Qualified", "Needs Review", "Rejected"], "Leads": [snap["total"], snap["verified"], snap["qualified"], snap["needs_review"], snap["rejected"]]}
        ).set_index("Stage")
        st.bar_chart(pipeline_df, height=260)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="section-card"><div class="section-title">By source</div>', unsafe_allow_html=True)
        source_df = pd.DataFrame(list(snap["sources"].items()), columns=["Source", "Leads"]).set_index("Source") if snap["sources"] else pd.DataFrame({"Leads": []})
        if not source_df.empty:
            st.bar_chart(source_df, height=260)
        else:
            st.info("No source data yet. Run discovery or the demo pipeline.")
        st.markdown('</div>', unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        st.markdown('<div class="section-card"><div class="section-title">Industries</div>', unsafe_allow_html=True)
        df = pd.DataFrame(list(snap["industries"].items()), columns=["Industry", "Leads"]).sort_values("Leads", ascending=False) if snap["industries"] else pd.DataFrame(columns=["Industry", "Leads"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="section-card"><div class="section-title">States</div>', unsafe_allow_html=True)
        df = pd.DataFrame(list(snap["states"].items()), columns=["State", "Leads"]).sort_values("Leads", ascending=False) if snap["states"] else pd.DataFrame(columns=["State", "Leads"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.write("")
    a, b, c = st.columns(3)
    with a:
        if st.button("Run demo pipeline", use_container_width=True, type="primary"):
            with st.spinner("Running the full demo pipeline..."):
                ok, out, err = run_cli(["demo"])
            if ok:
                st.success("Demo pipeline completed.")
                st.code(out[-4000:] if out else "Completed.")
                dashboard_snapshot.clear(); st.rerun()
            else:
                st.error("Demo pipeline failed."); st.code(err or out)
    with b:
        if st.button("Refresh data", use_container_width=True):
            dashboard_snapshot.clear(); st.rerun()
    with c:
        if st.button("Open lead workspace", use_container_width=True):
            st.session_state["nav_target"] = "Leads"
            st.rerun()


def lead_discovery_page() -> None:
    render_header("Lead Discovery", "Run one connector for targeted research or run the complete pipeline for discovery through export.")
    config = get_targeting_config()
    connector_desc = all_connector_descriptions()
    discovery_names = [d["name"] for d in connector_desc if d["name"] != "website"]
    available = {d["name"]: d for d in connector_desc}

    with st.form("discovery_form"):
        c1, c2, c3 = st.columns([1, 1.2, .8])
        with c1:
            default_industries = [i for i in config.industries if i != "ALL"]
            industry = st.selectbox("Industry", ["ALL"] + sorted(set(default_industries + ["roofing", "hvac", "plumbing", "cleaning", "restoration", "electrical", "pest_control"])) )
        with c2:
            location = st.text_input("Location", placeholder="Texas, Austin, TX, Florida...")
        with c3:
            st.number_input("Configured max results / query", min_value=1, max_value=100, value=min(config.max_results_per_query, 100), step=1, disabled=True)

        st.markdown("**Discovery source**")
        source = st.selectbox("Source", discovery_names, format_func=lambda x: f"{x} · {available[x]['availability']}", label_visibility="collapsed")
        source_meta = available.get(source, {})
        st.markdown(f'<div class="notice"><b>{source}</b> — {source_meta.get("summary", "")}</div>', unsafe_allow_html=True)
        submitted = st.form_submit_button("Run discovery", type="primary", use_container_width=True)

    if submitted:
        cmd = ["discover", "--source", source, "--industry", industry]
        if location.strip():
            cmd += ["--location", location.strip()]
        with st.spinner(f"Discovering leads with {source}..."):
            ok, out, err = run_cli(cmd)
        if ok:
            st.success("Discovery completed. New records are now in the database.")
            if out:
                st.code(out[-5000:])
            dashboard_snapshot.clear()
        else:
            st.error("Discovery failed.")
            st.code(err or out)

    st.divider()
    st.markdown("### Full pipeline")
    st.caption("The full run executes discovery → normalize → enrich → deduplicate → verify → score → cold-call briefs → export.")
    c1, c2 = st.columns([1, 2])
    with c1:
        full_industry = st.selectbox("Pipeline industry", ["ALL", "roofing", "hvac", "plumbing", "cleaning", "restoration", "electrical", "pest_control", "solar", "landscaping"], key="full_industry")
    with c2:
        full_location = st.text_input("Pipeline location", placeholder="USA-wide or a state/city", key="full_location")
    if st.button("Run full pipeline", type="primary", use_container_width=True):
        cmd = ["pipeline"]
        if full_industry != "ALL":
            cmd += ["--industry", full_industry]
        if full_location.strip():
            cmd += ["--location", full_location.strip()]
        with st.spinner("Running the complete lead intelligence pipeline..."):
            ok, out, err = run_cli(cmd)
        if ok:
            st.success("Full pipeline completed.")
            st.code(out[-6000:] if out else "Completed.")
            dashboard_snapshot.clear()
        else:
            st.error("Full pipeline failed.")
            st.code(err or out)


def leads_page() -> None:
    render_header("Leads", "Search, filter, inspect, and work with the canonical company records stored by the pipeline.")
    try:
        with session_scope() as session:
            companies = unique_companies(session)
            df = company_rows(companies)
            if df.empty:
                st.info("No leads are in the database yet. Run the demo pipeline or discovery.")
                return

            f1, f2, f3, f4 = st.columns(4)
            with f1:
                search = st.text_input("Search", placeholder="Company, phone, email, city...")
            with f2:
                industries = [x for x in sorted(df["Industry"].dropna().unique()) if x != "Not Found"]
                industry_filter = st.multiselect("Industry", industries)
            with f3:
                states = [x for x in sorted(df["State"].dropna().unique()) if x != "Not Found"]
                state_filter = st.multiselect("State", states)
            with f4:
                statuses = sorted(df["Status"].dropna().unique())
                status_filter = st.multiselect("Status", statuses)

            f5, f6 = st.columns(2)
            with f5:
                min_score = st.slider("Minimum CRM score", 0, 100, 0)
            with f6:
                min_quality = st.slider("Minimum data quality", 0, 100, 0)

            view = df.copy()
            if search:
                mask = view.apply(lambda row: row.astype(str).str.contains(search, case=False, regex=False).any(), axis=1)
                view = view[mask]
            if industry_filter:
                view = view[view["Industry"].isin(industry_filter)]
            if state_filter:
                view = view[view["State"].isin(state_filter)]
            if status_filter:
                view = view[view["Status"].isin(status_filter)]
            view = view[(view["CRM Score"] >= min_score) & (view["Quality"] >= min_quality)]

            st.caption(f"Showing {len(view)} of {len(df)} unique leads")
            st.dataframe(view, use_container_width=True, hide_index=True, height=500)

            ids = view["Lead ID"].tolist()
            if ids:
                selected_id = st.selectbox("Open lead profile", ids)
                numeric_id = int(str(selected_id).split("-")[-1])
                company = session.get(Company, numeric_id)
                if company:
                    st.divider()
                    st.markdown(f"### {company.name}")
                    st.markdown(f'<div class="lead-id">{company.lead_id}</div>', unsafe_allow_html=True)
                    a, b, c, d = st.columns(4)
                    a.metric("CRM Score", company.crm_opportunity_score or 0)
                    b.metric("Data Quality", company.data_quality_score or 0)
                    c.metric("Status", company.lead_authenticity_status or "NEEDS_REVIEW")
                    d.metric("Employees", company.employee_count or "Unknown")

                    tabs = st.tabs(["Company", "Verification", "Signals", "Cold Call", "Sources"])
                    with tabs[0]:
                        x, y, z = st.columns(3)
                        with x:
                            st.markdown(f'<div class="small-label">Website</div><div class="detail-value">{company.website or "Not Found"}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="small-label">Phone</div><div class="detail-value">{company.phone or "Not Found"}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="small-label">Email</div><div class="detail-value">{company.email or "Not Found"}</div>', unsafe_allow_html=True)
                        with y:
                            st.markdown(f'<div class="small-label">Industry</div><div class="detail-value">{company.industry or "Not Found"}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="small-label">Location</div><div class="detail-value">{", ".join(x for x in [company.city, company.state] if x) or "Not Found"}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="small-label">Business status</div><div class="detail-value">{company.business_status or "Unknown"}</div>', unsafe_allow_html=True)
                        with z:
                            st.markdown(f'<div class="small-label">Google rating</div><div class="detail-value">{company.google_rating if company.google_rating is not None else "Not Found"}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="small-label">Reviews</div><div class="detail-value">{company.review_count if company.review_count is not None else "Not Found"}</div>', unsafe_allow_html=True)
                            st.markdown(f'<div class="small-label">Primary source</div><div class="detail-value">{company.source_primary or "Unknown"}</div>', unsafe_allow_html=True)
                        st.markdown("**Description**")
                        st.write(company.company_description or "Not publicly identified.")
                        st.markdown("**Services**")
                        st.write(company.services or "Not publicly identified.")
                    with tabs[1]:
                        verification = {
                            "Phone": company.phone_verification_status,
                            "Email": company.email_verification_status,
                            "Website": company.website_status,
                            "Lead authenticity": company.lead_authenticity_status,
                        }
                        st.dataframe(pd.DataFrame(list(verification.items()), columns=["Field", "Status"]), use_container_width=True, hide_index=True)
                        if company.conflict_notes:
                            st.markdown(f'<div class="warning">{company.conflict_notes}</div>', unsafe_allow_html=True)
                        if company.crm_score_breakdown:
                            st.markdown("**CRM Opportunity Score breakdown**")
                            st.dataframe(pd.DataFrame(list(company.crm_score_breakdown.items()), columns=["Factor", "Points"]), use_container_width=True, hide_index=True)
                        if company.data_quality_breakdown:
                            st.markdown("**Data Quality Score breakdown**")
                            st.dataframe(pd.DataFrame(list(company.data_quality_breakdown.items()), columns=["Factor", "Points"]), use_container_width=True, hide_index=True)
                    with tabs[2]:
                        signals = [
                            {"Signal": s.signal_type, "Evidence": s.evidence_text or "", "Source URL": s.source_url or ""}
                            for s in company.signals
                        ]
                        st.dataframe(pd.DataFrame(signals), use_container_width=True, hide_index=True) if signals else st.info("No signals recorded.")
                    with tabs[3]:
                        st.markdown("**Recommended opening**")
                        st.write(company.recommended_opening or "Not generated yet.")
                        st.markdown("**Cold-call brief**")
                        st.text_area("", value=company.cold_call_brief or "Not generated yet.", height=300, label_visibility="collapsed")
                    with tabs[4]:
                        sources = [{"Source": sr.source.name if sr.source else "", "URL": sr.source_url or "", "Date": sr.date_found} for sr in company.source_records]
                        st.dataframe(pd.DataFrame(sources), use_container_width=True, hide_index=True) if sources else st.info("No source records.")
            
    except Exception as exc:
        st.error(f"Could not load leads: {exc}")


def verification_page() -> None:
    render_header("Verification & Scoring", "Re-run the existing pipeline stages independently when you need to refresh evidence, duplicates, scores, or exports.")
    actions = [
        ("Website enrichment", "enrich", "Fetch and analyze prospect-owned websites that have not been checked."),
        ("Deduplication", "deduplicate", "Merge duplicate company records using the existing deduplication logic."),
        ("Verification", "verify", "Recompute phone, email, website, and related verification statuses."),
        ("Scoring", "score", "Recompute CRM Opportunity and Data Quality scores."),
        ("Export", "export", "Reclassify current companies and write the configured Excel exports."),
    ]
    for idx, (title, command, desc) in enumerate(actions):
        left, right = st.columns([4, 1])
        with left:
            st.markdown(f'<div class="section-card"><div class="section-title">{title}</div><div class="muted">{desc}</div></div>', unsafe_allow_html=True)
        with right:
            if st.button("Run", key=f"action_{command}", use_container_width=True, type="primary" if command in ("verify", "score") else "secondary"):
                with st.spinner(f"Running {command}..."):
                    ok, out, err = run_cli([command])
                if ok:
                    st.success(f"{title} completed.")
                    if out:
                        st.code(out[-4500:])
                    dashboard_snapshot.clear()
                else:
                    st.error(f"{title} failed.")
                    st.code(err or out)
        if idx < len(actions) - 1:
            st.write("")

    st.divider()
    st.markdown("### Refresh cold-call briefs with the selected LLM")
    provider = get_secrets().llm_provider
    st.markdown(f'<div class="notice">Current LLM provider: <b>{provider}</b>. Brief generation only rewrites facts already present on the company record.</div>', unsafe_allow_html=True)
    if st.button("Regenerate briefs for current leads", use_container_width=True):
        count = 0
        with st.spinner("Generating cold-call briefs..."):
            with session_scope() as session:
                companies = unique_companies(session)
                config = get_targeting_config()
                for company in companies:
                    score_company(company, config)
                    generate_brief_and_opening(company)
                    count += 1
        st.success(f"Regenerated {count} lead brief(s).")


def cold_call_page() -> None:
    render_header("Cold Call Prospects", "Work from the generated company briefs and recommended openings produced from verified database facts.")
    with session_scope() as session:
        companies = [c for c in unique_companies(session) if c.cold_call_brief or c.recommended_opening]
        if not companies:
            st.info("No cold-call briefs are available yet. Run the full pipeline or regenerate briefs from Verification & Scoring.")
            return
        df = company_rows(companies)
        c1, c2 = st.columns(2)
        with c1:
            min_score = st.slider("Minimum CRM score", 0, 100, 70, key="cold_min_score")
        with c2:
            status = st.multiselect("Lead status", sorted(df["Status"].unique()), key="cold_status")
        view = df[df["CRM Score"] >= min_score]
        if status:
            view = view[view["Status"].isin(status)]
        st.dataframe(view[["Lead ID", "Company", "Industry", "Phone", "Email", "CRM Score", "Quality", "Status"]], use_container_width=True, hide_index=True, height=380)
        ids = view["Lead ID"].tolist()
        if ids:
            selected = st.selectbox("Open call brief", ids, key="cold_selected")
            company = session.get(Company, int(selected.split("-")[-1]))
            if company:
                st.divider()
                a, b = st.columns(2)
                with a:
                    st.markdown("**Recommended opening**")
                    st.text_area("Opening", value=company.recommended_opening or "", height=140, label_visibility="collapsed")
                with b:
                    st.markdown("**Company context**")
                    st.write(company.company_description or "Not publicly identified.")
                    st.write(f"Industry: {company.industry or 'Not Found'}")
                    st.write(f"CRM score: {company.crm_opportunity_score or 0}")
                st.markdown("**Call brief**")
                st.text_area("Brief", value=company.cold_call_brief or "", height=360, label_visibility="collapsed")


def exports_page() -> None:
    render_header("Exports", "Download the files generated by the existing export layer. Runtime exports remain local unless you choose to publish them yourself.")
    export_dir = PROJECT_ROOT / "exports"
    demo_dir = PROJECT_ROOT / "demo_output"
    files = sorted([p for p in export_dir.iterdir() if p.is_file() and p.suffix.lower() in {".xlsx", ".json", ".csv"}], key=lambda p: p.stat().st_mtime, reverse=True) if export_dir.exists() else []
    if not files:
        st.info("No runtime exports found yet. Run the pipeline or the demo first.")
    for p in files:
        col1, col2, col3 = st.columns([4, 2, 1.3])
        with col1:
            st.markdown(f"**{p.name}**")
            st.caption(f"Updated {datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')} · {p.stat().st_size/1024:.1f} KB")
        with col2:
            st.caption("Runtime export")
        with col3:
            with open(p, "rb") as fh:
                st.download_button("Download", fh.read(), file_name=p.name, key=f"download_{p.name}", use_container_width=True)

    st.divider()
    st.markdown("### Pre-generated demo files")
    demo_files = sorted([p for p in demo_dir.iterdir() if p.is_file() and p.suffix.lower() in {".xlsx", ".json"}], key=lambda p: p.name) if demo_dir.exists() else []
    if demo_files:
        st.caption("These are sample outputs shipped with the project for review; they are not live scraped data.")
        for p in demo_files:
            with open(p, "rb") as fh:
                st.download_button(f"Download {p.name}", fh.read(), file_name=p.name, key=f"demo_{p.name}")


def system_status_page() -> None:
    render_header("System Status", "A practical health view for database connectivity, connectors, credentials, and generated runtime output.")
    try:
        init_db()
        with session_scope() as session:
            lead_count = session.query(Company).filter(Company.duplicate_status == "unique").count()
            contact_count = session.query(Contact).count()
            signal_count = session.query(CompanySignal).count()
            source_record_count = session.query(SourceRecord).count()
        st.markdown(status_html("Database", "Ready"), unsafe_allow_html=True)
        a, b, c = st.columns(3)
        a.metric("Unique leads", lead_count)
        b.metric("Contacts", contact_count)
        c.metric("Signals", signal_count)
        st.metric("Source records", source_record_count)
    except Exception as exc:
        st.markdown(status_html("Database", "Error"), unsafe_allow_html=True)
        st.code(str(exc))

    st.divider()
    st.markdown("### Connector availability")
    try:
        descriptions = all_connector_descriptions()
        rows = []
        for desc in descriptions:
            name = desc["name"]
            # Match the live availability check without performing discovery.
            if name == "website":
                state = "AVAILABLE"
            else:
                from app.connectors.registry import build_connector
                connector = build_connector(name)
                state = desc["availability"]
                if desc["availability"] == "AVAILABLE":
                    state = "AVAILABLE" if connector.is_available() else "NOT CONFIGURED"
            rows.append({"Connector": name, "Status": state, "Capability": desc["summary"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Could not inspect connectors: {exc}")

    st.divider()
    st.markdown("### Runtime paths")
    st.code(
        "Project: " + str(PROJECT_ROOT) + "\n"
        "Database: " + str(PROJECT_ROOT / "data" / "leads.db") + "\n"
        "Exports: " + str(PROJECT_ROOT / "exports") + "\n"
        "Logs: " + str(PROJECT_ROOT / "logs")
    )


def settings_page() -> None:
    render_header("Settings", "Review targeting thresholds and connector configuration without exposing any secret values in the dashboard.")
    config = get_targeting_config()
    secrets = get_secrets()

    st.markdown("### Targeting")
    a, b, c = st.columns(3)
    a.metric("Country", config.country)
    b.metric("Employee range", f"{config.employee_min}–{config.employee_max}")
    c.metric("Preferred range", f"{config.preferred_employee_min}–{config.preferred_employee_max}")
    a, b, c = st.columns(3)
    a.metric("CRM threshold", config.crm_score_min)
    b.metric("Quality threshold", config.data_quality_min)
    c.metric("Max results/query", config.max_results_per_query)

    st.markdown("### Enabled sources")
    rows = []
    for name in ["google_places", "google_search", "website_enrichment", "meta_ads", "facebook_pages", "linkedin", "exa"]:
        rows.append({"Source": name, "Enabled in config": bool(getattr(config.sources, name, False))})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("### Credential status")
    credentials = [
        ("Google Places", bool(secrets.google_places_api_key), "GOOGLE_PLACES_API_KEY"),
        ("Exa", bool(secrets.exa_api_key), "EXA_API_KEY"),
        ("xAI / Grok", bool(secrets.xai_api_key), "XAI_API_KEY"),
        ("Meta", bool(secrets.meta_access_token), "META_ACCESS_TOKEN"),
        ("Facebook Pages", bool(secrets.facebook_page_access_token), "FACEBOOK_PAGE_ACCESS_TOKEN"),
        ("Google Custom Search", bool(secrets.google_custom_search_api_key and secrets.google_custom_search_cx), "GOOGLE_CUSTOM_SEARCH_API_KEY + GOOGLE_CUSTOM_SEARCH_CX"),
    ]
    st.dataframe(pd.DataFrame([{ "Service": n, "Configured": "Yes" if ok else "No", "Environment variable(s)": env } for n, ok, env in credentials]), use_container_width=True, hide_index=True)
    st.markdown('<div class="notice">Secrets are intentionally managed in <code>.env</code>, not in the UI. After changing <code>.env</code>, restart Streamlit so the process picks up the new environment.</div>', unsafe_allow_html=True)

    st.markdown("### Current LLM")
    st.code(f"LLM_PROVIDER={secrets.llm_provider}\nXAI_MODEL={secrets.xai_model}")


def main() -> None:
    inject_css()
    safe_init_db()
    page = render_sidebar()

    nav_target = st.session_state.pop("nav_target", None)
    if nav_target:
        page = nav_target

    pages = {
        "Dashboard": dashboard_page,
        "Lead Discovery": lead_discovery_page,
        "Leads": leads_page,
        "Verification & Scoring": verification_page,
        "Cold Call Prospects": cold_call_page,
        "Exports": exports_page,
        "System Status": system_status_page,
        "Settings": settings_page,
    }
    pages[page]()


if __name__ == "__main__":
    main()
