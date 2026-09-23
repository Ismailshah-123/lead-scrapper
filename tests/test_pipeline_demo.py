import pandas as pd

import app.pipeline as pipeline_module
from app.core import config as config_module
from app.core import db as db_module
from app.exports import excel_export
from app.pipeline import Pipeline


def test_demo_pipeline_end_to_end(tmp_path, monkeypatch):
    """Runs the real pipeline (no mocks on the business logic — only the
    database and export locations are redirected to a temp dir) and
    checks that every demo fixture lands in the bucket it was designed to
    exercise. This is the same check performed by hand while building the
    project; it exists here so a future change can't silently reintroduce
    the classify_lead ordering bug that hand-testing caught."""
    db_path = tmp_path / "test_leads.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config_module.reset_config_cache()
    db_module.reset_engine_cache()
    db_module.init_db()

    exports_dir = tmp_path / "exports"
    monkeypatch.setattr(excel_export, "EXPORTS_DIR", exports_dir)
    monkeypatch.setattr(pipeline_module, "DATA_DIR", tmp_path / "data")

    try:
        result = Pipeline().run(demo=True)

        stats = result["stats"]
        assert stats["discovered"] == 6
        assert stats["qualified"] >= 1
        assert stats["needs_review"] >= 1
        assert stats["rejected"] >= 1

        master_df = pd.read_excel(exports_dir / "MASTER_VERIFIED_LEADS.xlsx")
        assert "Riverstone Roofing & Exteriors (Demo)" in master_df["Company_Name"].values
        master_row = master_df[master_df["Company_Name"] == "Riverstone Roofing & Exteriors (Demo)"].iloc[0]
        assert master_row["Phone_Verification_Status"] == "Verified"
        assert isinstance(master_row["Cold_Call_Brief"], str) and len(master_row["Cold_Call_Brief"]) > 50

        needs_review_df = pd.read_excel(exports_dir / "NEEDS_REVIEW.xlsx")
        needs_review_names = set(needs_review_df["Company_Name"].values)
        assert "Homestyle Cleaning Co (Demo)" in needs_review_names  # unknown employee count
        assert "Apex Legal Group (Demo)" in needs_review_names  # conflicting phone

        rejected_df = pd.read_excel(exports_dir / "REJECTED_LEADS.xlsx")
        rejected_names = set(rejected_df["Company_Name"].values)
        assert "Old Mill Hardware (Demo)" in rejected_names  # permanently closed
        assert "TinyDesk Bookkeeping (Demo)" in rejected_names  # outside employee range

        cold_call_df = pd.read_excel(exports_dir / "COLD_CALL_PROSPECTS.xlsx")
        assert len(cold_call_df) == stats["qualified"]

        assert (exports_dir / "RUN_REPORT.json").exists()
        assert (exports_dir / "RUN_REPORT.xlsx").exists()

    finally:
        config_module.reset_config_cache()
        db_module.reset_engine_cache()
