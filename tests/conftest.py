"""
Shared fixtures.

Every test that needs a database gets its own throwaway SQLite file under
pytest's tmp_path — never the real data/leads.db a person's actual runs
would use. This works by pointing DATABASE_URL at the temp file and
clearing the config/engine caches (see app.core.config.reset_config_cache
and app.core.db.reset_engine_cache), which exist specifically so tests can
do this cleanly.
"""
from __future__ import annotations

import pytest

from app.core import config as config_module
from app.core import db as db_module


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "test_leads.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config_module.reset_config_cache()
    db_module.reset_engine_cache()

    db_module.init_db()
    session = db_module.get_session_factory()()
    try:
        yield session
    finally:
        session.close()
        config_module.reset_config_cache()
        db_module.reset_engine_cache()
