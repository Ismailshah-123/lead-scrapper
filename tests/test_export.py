
from pathlib import Path
import pandas as pd

from app.exports import excel_export
from app.models.models import Company, Contact
from app.utils.normalize import NOT_FOUND, NOT_PUBLICLY_VERIFIED


def _company(**kwargs) -> Company:
    defaults = dict(
        name="Test Co", normalized_name="test co", source_primary="google_places",
        source_secondary=[], all_source_urls=[], contacts=[], signals=[],
        duplicate_status="unique",
    )
    defaults.update(kwargs)
    return Company(**defaults)


class TestMasterRow:
    def test_missing_fields_render_as_not_found_never_blank_or_fabricated(self):
        company = _company(id=1)
        row = excel_export.master_row(company)
        assert row["Website"] == NOT_FOUND
        assert row["Company_Phone"] == NOT_FOUND
        assert row["Owner_Name"] == NOT_PUBLICLY_VERIFIED

    def test_lead_id_format(self):
        company = _company(id=7)
        row = excel_export.master_row(company)
        assert row["Lead_ID"] == "LEAD-00007"

    def test_populated_fields_pass_through(self):
        company = _company(id=1, website="https://acme.com", phone="+15125550101", phone_verification_status="Verified")
        row = excel_export.master_row(company)
        assert row["Website"] == "https://acme.com"
        assert row["Company_Phone"] == "+15125550101"
        assert row["Phone_Verification_Status"] == "Verified"

    def test_owner_prefers_verified_over_publicly_identified(self):
        company = _company(id=1, contacts=[
            Contact(full_name="Alex Unverified", title="Manager", verification_status="Unverified"),
            Contact(full_name="Jordan Verified", title="Owner", verification_status="Verified"),
        ])
        row = excel_export.master_row(company)
        assert row["Owner_Name"] == "Jordan Verified"

    def test_all_master_columns_present(self):
        company = _company(id=1)
        row = excel_export.master_row(company)
        assert set(row.keys()) == set(excel_export.MASTER_COLUMNS)


class TestRejectedAndNeedsReviewRows:
    def test_rejected_row_carries_reason(self):
        company = _company(id=1, rejection_reason="Employee count (3) falls outside range.")
        row = excel_export.rejected_row(company)
        assert row["Reason_Rejected"] == "Employee count (3) falls outside range."

    def test_needs_review_row_carries_reason(self):
        company = _company(id=1, rejection_reason="Employee count could not be determined.")
        row = excel_export.needs_review_row(company)
        assert row["Reason_For_Review"] == "Employee count could not be determined."


class TestExportAllProducesEveryFile(object):
    def test_writes_every_expected_file_with_header_even_when_empty(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(excel_export, "EXPORTS_DIR", tmp_path)
        buckets = {"master": [], "needs_review": [], "rejected": []}
        paths = excel_export.export_all(db_session, buckets)

        expected_names = {
            "MASTER_VERIFIED_LEADS.xlsx", "NEEDS_REVIEW.xlsx", "REJECTED_LEADS.xlsx",
            "COLD_CALL_PROSPECTS.xlsx", "GOOGLE_MAPS_LEADS.xlsx", "GOOGLE_SEARCH_LEADS.xlsx",
            "META_LEADS.xlsx", "FACEBOOK_LEADS.xlsx", "LINKEDIN_LEADS.xlsx", "WEBSITE_ENRICHED_LEADS.xlsx",
        }
        actual_names = {Path(p).name for p in paths}
        assert expected_names == actual_names

        master_df = pd.read_excel(tmp_path / "MASTER_VERIFIED_LEADS.xlsx")
        assert list(master_df.columns) == excel_export.MASTER_COLUMNS
        assert len(master_df) == 0

    def test_master_bucket_rows_land_in_the_file(self, db_session, tmp_path, monkeypatch):
        monkeypatch.setattr(excel_export, "EXPORTS_DIR", tmp_path)
        company = _company(id=1, name="Acme Roofing (Test)", crm_opportunity_score=85, crm_opportunity_level="VERY HIGH")
        buckets = {"master": [company], "needs_review": [], "rejected": []}
        excel_export.export_all(db_session, buckets)

        master_df = pd.read_excel(tmp_path / "MASTER_VERIFIED_LEADS.xlsx")
        assert len(master_df) == 1
        assert master_df.iloc[0]["Company_Name"] == "Acme Roofing (Test)"

    def test_run_report_json_and_xlsx_are_written(self, tmp_path, monkeypatch):
        monkeypatch.setattr(excel_export, "EXPORTS_DIR", tmp_path)
        stats = {"discovered": 10, "duplicates": 2, "verified": 3, "qualified": 3, "needs_review": 2, "rejected": 3,
                  "by_source": {"google_places": 10}, "by_industry": {"roofing": 5}, "by_state": {"TX": 10}}
        excel_export.write_run_report(1, stats, [])

        assert (tmp_path / "RUN_REPORT.json").exists()
        assert (tmp_path / "RUN_REPORT.xlsx").exists()

        import json
        payload = json.loads((tmp_path / "RUN_REPORT.json").read_text())
        assert payload["discovered"] == 10
        assert payload["qualified"] == 3
