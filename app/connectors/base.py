"""
Connector abstraction shared by every discovery/enrichment source.

Availability tiers (used everywhere a connector describes itself — CLI,
README, RUN_REPORT): a connector must self-report one of these truthfully.
Nothing in this project is allowed to claim AVAILABLE while quietly doing
nothing, or LIMITED while actually behaving like AVAILABLE.

    AVAILABLE    Works right now through a compliant, official method.
    LIMITED      Works, but with real restrictions you need to know about
                 (a narrow data slice, geographic limits, needs a Page you
                 already manage, etc).
    OPTIONAL     Not wired up by default; can be turned on later via an
                 official API or a licensed data provider.
    UNAVAILABLE  Cannot currently be done through any compliant/free
                 method. Ships as a documented interface, not a fake
                 implementation — see linkedin.py.
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.logging_config import get_logger


class ConnectorAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    LIMITED = "LIMITED"
    OPTIONAL = "OPTIONAL"
    UNAVAILABLE = "UNAVAILABLE"


class ConnectorUnavailableError(Exception):
    """Raised when a connector cannot run right now (missing API key, an
    API that's closed to new signups, disabled in config, etc).

    The pipeline always catches this at the connector-call boundary, logs
    an ErrorLog row, and moves on to the next connector — a single
    unavailable source must never stop a run (spec: "Source Fallback
    Strategy" / "one bad source should not take down the whole run")."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class RawLead:
    """The common shape every connector normalizes its findings into,
    before normalization/dedup/verification touch it. Unknown fields stay
    None — connectors must never invent a plausible-looking value."""

    company_name: str
    source: str  # matches a Source.name row, e.g. "google_places"
    source_url: Optional[str] = None

    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None

    industry: Optional[str] = None
    services: Optional[str] = None
    description: Optional[str] = None

    google_maps_url: Optional[str] = None
    facebook_url: Optional[str] = None
    linkedin_url: Optional[str] = None

    google_rating: Optional[float] = None
    review_count: Optional[int] = None
    business_status: Optional[str] = None

    owner_name: Optional[str] = None
    owner_title: Optional[str] = None
    owner_source_url: Optional[str] = None

    employee_count: Optional[str] = None
    employee_count_type: Optional[str] = None  # Exact/Public Range/Estimated/Unknown
    employee_count_source: Optional[str] = None

    # Ad-evidence flags, set only by connectors that actually check
    meta_ad_evidence: Optional[str] = None
    google_ad_evidence: Optional[str] = None

    raw_extra: Dict[str, Any] = field(default_factory=dict)
    date_found: dt.datetime = field(default_factory=_utcnow)


class BaseConnector(ABC):
    name: str = "base"
    availability: ConnectorAvailability = ConnectorAvailability.UNAVAILABLE
    capability_summary: str = "Not implemented."

    def __init__(self) -> None:
        self.logger = get_logger(f"connector.{self.name}")

    @abstractmethod
    def discover(self, query: str, location: str = "", max_results: int = 20) -> List[RawLead]:
        """Return a list of RawLead. Must raise ConnectorUnavailableError
        (not return an empty list) when the connector cannot run at all —
        an empty list means "ran fine, found nothing", which is a very
        different fact for RUN_REPORT.json than "didn't run"."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Fast, no-network check (credentials present? feature enabled?)
        used by the pipeline to skip an entire connector with one log line
        instead of hitting ConnectorUnavailableError once per query.
        Default assumes available; override where there's something cheap
        to check first."""
        return True

    @classmethod
    def describe(cls) -> Dict[str, str]:
        return {
            "name": cls.name,
            "availability": cls.availability.value,
            "summary": cls.capability_summary,
        }
