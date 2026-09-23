"""
Excel export.

Every exported sheet gets a bold header row, frozen header, and
auto-sized columns — nothing exotic, just readable the moment it's
opened. An empty bucket (e.g. no rejected leads this run) still produces
a correctly-headed sheet with zero data rows, never a blank file — see
the `columns=` fallback on every pd.DataFrame([...]) call below.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.coldcall.brief import _line_automation_opportunity, _line_crm_gap
from app.core.config import PROJECT_ROOT
from app.core.logging_config import get_logger
from app.models.models import Company, Source, SourceRecord
from app.utils.normalize import NOT_FOUND, NOT_PUBLICLY_VERIFIED

logger = get_logger("exports.excel")

EXPORTS_DIR = PROJECT_ROOT / "exports"

MASTER_COLUMNS = [
    "Lead_ID", "Company_Name", "Normalized_Company_Name", "Industry", "Sub_Industry",
    "Website", "Website_Status", "Company_Phone", "Phone_Verification_Status",
    "Email", "Email_Type", "Email_Verification_Status",
    "Owner_Name", "Owner_Title", "Owner_Source",
    "Employee_Count", "Employee_Count_Type",
    "Country", "State", "City", "ZIP", "Address",
    "Google_Maps_URL", "Facebook_URL", "LinkedIn_URL",
    "Meta_Ad_Evidence", "Google_Ad_Evidence",
    "Review_Count", "Business_Status",
    "Services", "Target_Customer", "Company_Description",
    "CRM_Opportunity_Score", "CRM_Opportunity_Level", "Data_Quality_Score",
    "CRM_Pain_Points", "Automation_Opportunity",
    "Cold_Call_Brief", "Recommended_Opening",
    "Source_Primary", "Source_Secondary", "Source_URL",
    "Date_Found", "Date_Verified", "Verification_Notes", "Duplicate_Status",
]

NEEDS_REVIEW_COLUMNS = [
    "Company_Name", "Website", "Phone", "Email", "City", "State", "Industry",
    "Employee_Count", "CRM_Opportunity_Score", "Data_Quality_Score",
    "Reason_For_Review", "Verification_Notes", "Source_Primary", "Source_URL", "Date_Found",
]

REJECTED_COLUMNS = [
    "Company_Name", "Reason_Rejected", "Source_Primary", "Website",
    "Industry", "Employee_Count", "Date_Found", "Verification_Notes",
]

COLD_CALL_COLUMNS = [
    "Company", "Owner/Decision Maker", "Title", "Phone", "Email", "Website", "Industry",
    "Employee Count", "CRM Score", "Data Quality Score", "Main Problem", "Why They Need CRM",
    "Automation Opportunity", "10-Line Company Brief", "Suggested Opening", "Source", "Verification Status",
]

SOURCE_COLUMNS = [
    "Company_Name", "Website", "Phone", "Email", "City", "State", "Country", "Industry",
    "Google_Rating", "Review_Count", "Business_Status", "Ad_Evidence", "Source_URL",
    "Date_Found", "Linked_Company_Record",
]

SOURCE_FILE_MAP = {
    "google_places": "GOOGLE_MAPS_LEADS.xlsx",
    "google_search": "GOOGLE_SEARCH_LEADS.xlsx",
    "meta_ads": "META_LEADS.xlsx",
    "facebook_pages": "FACEBOOK_LEADS.xlsx",
    "linkedin": "LINKEDIN_LEADS.xlsx",
    "website": "WEBSITE_ENRICHED_LEADS.xlsx",
}


def _val(value, fallback=NOT_FOUND):
    if value is None or value == "":
        return fallback
    return value


def _strip_line_number(text: str) -> str:
    return re.sub(r"^\d+\.\s*", "", text or "")


def _owner_fields(company: Company):
    if not company.contacts:
        return NOT_PUBLICLY_VERIFIED, NOT_PUBLICLY_VERIFIED, NOT_FOUND
    best = None
    for status in ("Verified", "Publicly Identified", "Unverified"):
        best = next((c for c in company.contacts if c.verification_status == status), None)
        if best:
            break
    best = best or company.contacts[0]
    return (best.full_name or NOT_PUBLICLY_VERIFIED, best.title or NOT_PUBLICLY_VERIFIED, best.source_url or NOT_FOUND)


def _fmt_dt(value: dt.datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def master_row(company: Company) -> dict:
    owner_name, owner_title, owner_source = _owner_fields(company)
    return {
        "Lead_ID": company.lead_id,
        "Company_Name": company.name,
        "Normalized_Company_Name": company.normalized_name,
        "Industry": _val(company.industry),
        "Sub_Industry": _val(company.sub_industry),
        "Website": _val(company.website),
        "Website_Status": _val(company.website_status, "Not Checked"),
        "Company_Phone": _val(company.phone),
        "Phone_Verification_Status": company.phone_verification_status or "Not Found",
        "Email": _val(company.email),
        "Email_Type": _val(company.email_type, "Unknown"),
        "Email_Verification_Status": company.email_verification_status or "Not Found",
        "Owner_Name": owner_name,
        "Owner_Title": owner_title,
        "Owner_Source": owner_source,
        "Employee_Count": _val(company.employee_count, "Unknown"),
        "Employee_Count_Type": _val(company.employee_count_type, "Unknown"),
        "Country": _val(company.country),
        "State": _val(company.state),
        "City": _val(company.city),
        "ZIP": _val(company.zip),
        "Address": _val(company.address),
        "Google_Maps_URL": _val(company.google_maps_url),
        "Facebook_URL": _val(company.facebook_url),
        "LinkedIn_URL": _val(company.linkedin_url),
        "Meta_Ad_Evidence": _val(company.meta_ad_evidence, NOT_PUBLICLY_VERIFIED),
        "Google_Ad_Evidence": _val(company.google_ad_evidence, NOT_PUBLICLY_VERIFIED),
        "Review_Count": company.review_count if company.review_count is not None else NOT_FOUND,
        "Business_Status": _val(company.business_status, "Unknown"),
        "Services": _val(company.services),
        "Target_Customer": _val(company.target_customer),
        "Company_Description": _val(company.company_description),
        "CRM_Opportunity_Score": company.crm_opportunity_score,
        "CRM_Opportunity_Level": company.crm_opportunity_level,
        "Data_Quality_Score": company.data_quality_score,
        "CRM_Pain_Points": _strip_line_number(_line_crm_gap(company)),
        "Automation_Opportunity": _strip_line_number(_line_automation_opportunity(company)),
        "Cold_Call_Brief": company.cold_call_brief,
        "Recommended_Opening": company.recommended_opening,
        "Source_Primary": company.source_primary,
        "Source_Secondary": ", ".join(company.source_secondary or []) or "None",
        "Source_URL": (company.all_source_urls or [NOT_FOUND])[0],
        "Date_Found": _fmt_dt(company.first_found_at),
        "Date_Verified": _fmt_dt(company.last_verified_at),
        "Verification_Notes": _val(company.conflict_notes, "None"),
        "Duplicate_Status": company.duplicate_status,
    }


def needs_review_row(company: Company) -> dict:
    return {
        "Company_Name": company.name,
        "Website": _val(company.website),
        "Phone": _val(company.phone),
        "Email": _val(company.email),
        "City": _val(company.city),
        "State": _val(company.state),
        "Industry": _val(company.industry),
        "Employee_Count": _val(company.employee_count, "Unknown"),
        "CRM_Opportunity_Score": company.crm_opportunity_score,
        "Data_Quality_Score": company.data_quality_score,
        "Reason_For_Review": company.rejection_reason or "Needs manual verification.",
        "Verification_Notes": _val(company.conflict_notes, "None"),
        "Source_Primary": company.source_primary,
        "Source_URL": (company.all_source_urls or [NOT_FOUND])[0],
        "Date_Found": _fmt_dt(company.first_found_at),
    }


def rejected_row(company: Company) -> dict:
    return {
        "Company_Name": company.name,
        "Reason_Rejected": company.rejection_reason or "Did not meet the configured quality gate.",
        "Source_Primary": company.source_primary,
        "Website": _val(company.website),
        "Industry": _val(company.industry),
        "Employee_Count": _val(company.employee_count, "Unknown"),
        "Date_Found": _fmt_dt(company.first_found_at),
        "Verification_Notes": _val(company.conflict_notes, "None"),
    }


def cold_call_row(company: Company) -> dict:
    owner_name, owner_title, _ = _owner_fields(company)
    return {
        "Company": company.name,
        "Owner/Decision Maker": owner_name,
        "Title": owner_title,
        "Phone": _val(company.phone),
        "Email": _val(company.email),
        "Website": _val(company.website),
        "Industry": _val(company.industry),
        "Employee Count": _val(company.employee_count, "Unknown"),
        "CRM Score": company.crm_opportunity_score,
        "Data Quality Score": company.data_quality_score,
        "Main Problem": _strip_line_number(_line_crm_gap(company)),
        "Why They Need CRM": company.crm_opportunity_level,
        "Automation Opportunity": _strip_line_number(_line_automation_opportunity(company)),
        "10-Line Company Brief": company.cold_call_brief,
        "Suggested Opening": company.recommended_opening,
        "Source": company.source_primary,
        "Verification Status": company.lead_authenticity_status,
    }


def source_specific_rows(session, source_name: str) -> List[dict]:
    source = session.query(Source).filter_by(name=source_name).one_or_none()
    if source is None:
        return []
    records = session.query(SourceRecord).filter_by(source_id=source.id).all()
    rows = []
    for rec in records:
        data = rec.raw_data or {}
        rows.append({
            "Company_Name": data.get("company_name") or NOT_FOUND,
            "Website": data.get("website") or NOT_FOUND,
            "Phone": data.get("phone") or NOT_FOUND,
            "Email": data.get("email") or NOT_FOUND,
            "City": data.get("city") or NOT_FOUND,
            "State": data.get("state") or NOT_FOUND,
            "Country": data.get("country") or NOT_FOUND,
            "Industry": data.get("industry") or NOT_FOUND,
            "Google_Rating": data.get("google_rating") if data.get("google_rating") is not None else NOT_FOUND,
            "Review_Count": data.get("review_count") if data.get("review_count") is not None else NOT_FOUND,
            "Business_Status": data.get("business_status") or "Unknown",
            "Ad_Evidence": data.get("meta_ad_evidence") or data.get("google_ad_evidence") or NOT_FOUND,
            "Source_URL": rec.source_url or NOT_FOUND,
            "Date_Found": _fmt_dt(rec.date_found),
            "Linked_Company_Record": rec.company.lead_id if rec.company else NOT_FOUND,
        })
    return rows


def _style_sheet(ws, df: pd.DataFrame) -> None:
    header_font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
    header_fill = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    for idx, col in enumerate(df.columns, start=1):
        sample = df[col].tolist()[:200] if len(df) else []
        max_len = max([len(str(col))] + [len(str(v)) for v in sample])
        ws.column_dimensions[get_column_letter(idx)].width = min(max(max_len + 2, 12), 70)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = Font(name="Calibri", size=10)
            cell.alignment = Alignment(vertical="top")


def _write_df(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
        _style_sheet(writer.sheets["Leads"], df)
    logger.info("Wrote %s (%d rows)", path.name, len(df))


def export_all(session, buckets: Dict[str, List[Company]]) -> List[str]:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    paths: List[str] = []

    master_df = pd.DataFrame([master_row(c) for c in buckets["master"]], columns=MASTER_COLUMNS)
    _write_df(master_df, EXPORTS_DIR / "MASTER_VERIFIED_LEADS.xlsx")
    paths.append(str(EXPORTS_DIR / "MASTER_VERIFIED_LEADS.xlsx"))

    needs_review_df = pd.DataFrame([needs_review_row(c) for c in buckets["needs_review"]], columns=NEEDS_REVIEW_COLUMNS)
    _write_df(needs_review_df, EXPORTS_DIR / "NEEDS_REVIEW.xlsx")
    paths.append(str(EXPORTS_DIR / "NEEDS_REVIEW.xlsx"))

    rejected_df = pd.DataFrame([rejected_row(c) for c in buckets["rejected"]], columns=REJECTED_COLUMNS)
    _write_df(rejected_df, EXPORTS_DIR / "REJECTED_LEADS.xlsx")
    paths.append(str(EXPORTS_DIR / "REJECTED_LEADS.xlsx"))

    cold_call_df = pd.DataFrame([cold_call_row(c) for c in buckets["master"]], columns=COLD_CALL_COLUMNS)
    _write_df(cold_call_df, EXPORTS_DIR / "COLD_CALL_PROSPECTS.xlsx")
    paths.append(str(EXPORTS_DIR / "COLD_CALL_PROSPECTS.xlsx"))

    for source_name, filename in SOURCE_FILE_MAP.items():
        rows = source_specific_rows(session, source_name)
        df = pd.DataFrame(rows, columns=SOURCE_COLUMNS)
        path = EXPORTS_DIR / filename
        _write_df(df, path)
        paths.append(str(path))

    return paths


def write_run_report(run_id: int, stats: dict, export_paths: List[str]) -> None:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()

    json_payload = {"run_id": run_id, "generated_at": generated_at, **stats,
                     "exports": [Path(p).name for p in export_paths]}
    with open(EXPORTS_DIR / "RUN_REPORT.json", "w", encoding="utf-8") as fh:
        json.dump(json_payload, fh, indent=2, default=str)

    rows = [
        {"Metric": "Run ID", "Value": run_id},
        {"Metric": "Generated At (UTC)", "Value": generated_at},
        {"Metric": "Discovered", "Value": stats.get("discovered", 0)},
        {"Metric": "Duplicates merged", "Value": stats.get("duplicates", 0)},
        {"Metric": "Verified (cross-source contact match)", "Value": stats.get("verified", 0)},
        {"Metric": "Qualified for MASTER_VERIFIED_LEADS", "Value": stats.get("qualified", 0)},
        {"Metric": "Needs review", "Value": stats.get("needs_review", 0)},
        {"Metric": "Rejected", "Value": stats.get("rejected", 0)},
    ]
    for source, count in (stats.get("by_source") or {}).items():
        rows.append({"Metric": f"By source: {source}", "Value": count})
    for industry, count in (stats.get("by_industry") or {}).items():
        rows.append({"Metric": f"By industry: {industry}", "Value": count})
    for state, count in (stats.get("by_state") or {}).items():
        rows.append({"Metric": f"By state: {state}", "Value": count})

    _write_df(pd.DataFrame(rows, columns=["Metric", "Value"]), EXPORTS_DIR / "RUN_REPORT.xlsx")
