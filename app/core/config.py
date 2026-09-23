"""
Central configuration for the Lead Intelligence Engine.

Two sources are merged here, deliberately kept separate on disk:

  * .env          -> secrets and machine-specific values (API keys, DB URL,
                     crawl timing). Never committed (.gitignore).
  * config.yaml   -> targeting/scoring knobs a non-engineer should be able to
                     tune without reading code (employee range, industries,
                     score thresholds, which connectors run).

Everything is optional. A missing API key does not crash the app — it makes
the relevant connector report itself unavailable (see
app/connectors/base.py::ConnectorUnavailableError) and the pipeline
continues with whatever connectors *are* configured, per the "one bad
source should not take down the whole run" rule in the project spec.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

# Load .env once, at import time. Real environment variables (e.g. set by a
# process manager or CI) always win over what's in the file.
load_dotenv(dotenv_path=DEFAULT_ENV_PATH, override=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Secrets:
    """Everything that comes from the environment / .env file."""

    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'data' / 'leads.db'}"))

    google_places_api_key: str = field(default_factory=lambda: _env("GOOGLE_PLACES_API_KEY"))
    exa_api_key: str = field(default_factory=lambda: _env("EXA_API_KEY"))

    google_custom_search_api_key: str = field(default_factory=lambda: _env("GOOGLE_CUSTOM_SEARCH_API_KEY"))
    google_custom_search_cx: str = field(default_factory=lambda: _env("GOOGLE_CUSTOM_SEARCH_CX"))

    meta_access_token: str = field(default_factory=lambda: _env("META_ACCESS_TOKEN"))
    meta_api_version: str = field(default_factory=lambda: _env("META_API_VERSION", "v23.0"))

    facebook_page_access_token: str = field(default_factory=lambda: _env("FACEBOOK_PAGE_ACCESS_TOKEN"))

    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "template"))
    ollama_host: str = field(default_factory=lambda: _env("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3.1"))
    xai_api_key: str = field(default_factory=lambda: _env("XAI_API_KEY"))
    xai_model: str = field(default_factory=lambda: _env("XAI_MODEL", "grok-4.7"))

    request_delay_seconds: float = field(default_factory=lambda: _env_float("REQUEST_DELAY_SECONDS", 1.5))
    request_timeout_seconds: int = field(default_factory=lambda: _env_int("REQUEST_TIMEOUT_SECONDS", 10))
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 3))
    user_agent: str = field(default_factory=lambda: _env(
        "USER_AGENT",
        "VertexDataLeadBot/1.0 (+https://vertex-data-system.vercel.app/)",
    ))


@dataclass(frozen=True)
class SourceToggles:
    google_places: bool = True
    google_search: bool = True
    website_enrichment: bool = True
    meta_ads: bool = True
    facebook_pages: bool = False
    linkedin: bool = False
    exa: bool = True


@dataclass(frozen=True)
class TargetingConfig:
    """Everything that comes from config.yaml."""

    country: str = "USA"
    states: List[str] = field(default_factory=list)

    employee_min: int = 10
    employee_max: int = 100
    preferred_employee_min: int = 20
    preferred_employee_max: int = 100

    crm_score_min: int = 70
    data_quality_min: int = 50

    industries: List[str] = field(default_factory=lambda: ["ALL"])
    max_results_per_query: int = 20

    sources: SourceToggles = field(default_factory=SourceToggles)


def load_targeting_config(path: Path = DEFAULT_CONFIG_PATH) -> TargetingConfig:
    if not path.exists():
        return TargetingConfig()

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    sources_raw = raw.get("sources", {}) or {}
    sources = SourceToggles(
        google_places=bool(sources_raw.get("google_places", True)),
        google_search=bool(sources_raw.get("google_search", True)),
        website_enrichment=bool(sources_raw.get("website_enrichment", True)),
        meta_ads=bool(sources_raw.get("meta_ads", True)),
        facebook_pages=bool(sources_raw.get("facebook_pages", False)),
        linkedin=bool(sources_raw.get("linkedin", False)),
        exa=bool(sources_raw.get("exa", True)),
    )

    return TargetingConfig(
        country=raw.get("country", "USA"),
        states=list(raw.get("states", []) or []),
        employee_min=int(raw.get("employee_min", 10)),
        employee_max=int(raw.get("employee_max", 100)),
        preferred_employee_min=int(raw.get("preferred_employee_min", 20)),
        preferred_employee_max=int(raw.get("preferred_employee_max", 100)),
        crm_score_min=int(raw.get("crm_score_min", 70)),
        data_quality_min=int(raw.get("data_quality_min", 50)),
        industries=list(raw.get("industries", ["ALL"]) or ["ALL"]),
        max_results_per_query=int(raw.get("max_results_per_query", 20)),
        sources=sources,
    )


_secrets: Secrets | None = None
_targeting: TargetingConfig | None = None


def get_secrets() -> Secrets:
    global _secrets
    if _secrets is None:
        _secrets = Secrets()
    return _secrets


def get_targeting_config(path: Path = DEFAULT_CONFIG_PATH) -> TargetingConfig:
    global _targeting
    if _targeting is None:
        _targeting = load_targeting_config(path)
    return _targeting


def reset_config_cache() -> None:
    """Used by tests that want a fresh read of env/yaml."""
    global _secrets, _targeting
    _secrets = None
    _targeting = None
