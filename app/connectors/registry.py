"""
Connector registry.

One place that knows about every connector, so the CLI's `sources` command
and the pipeline's `discover` stage don't need to import each connector
module individually.
"""
from __future__ import annotations

from typing import Dict, List, Type

from app.connectors.base import BaseConnector
from app.connectors.facebook_pages import FacebookPagesConnector
from app.connectors.google_places import GooglePlacesConnector
from app.connectors.google_search import GoogleCustomSearchConnector
from app.connectors.linkedin import LinkedInConnector
from app.connectors.exa import ExaConnector
from app.connectors.meta_ads import MetaAdLibraryConnector
from app.core.config import TargetingConfig

DISCOVERY_CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = {
    "google_places": GooglePlacesConnector,
    "google_search": GoogleCustomSearchConnector,
    "meta_ads": MetaAdLibraryConnector,
    "facebook_pages": FacebookPagesConnector,
    "linkedin": LinkedInConnector,
    "exa": ExaConnector,
}


def all_connector_descriptions() -> List[Dict[str, str]]:
    """Every connector's self-reported tier/summary, including the
    website-enrichment connector, which isn't in the discovery registry
    above because it enriches an existing lead rather than discovering
    new ones (see app/enrichment/website_analysis.py)."""
    from app.enrichment.website_analysis import WebsiteEnrichmentConnector

    descriptions = [cls.describe() for cls in DISCOVERY_CONNECTOR_REGISTRY.values()]
    descriptions.append(WebsiteEnrichmentConnector.describe())
    return descriptions


def enabled_connector_names(config: TargetingConfig) -> List[str]:
    toggles = config.sources
    enabled = []
    for name in DISCOVERY_CONNECTOR_REGISTRY:
        if getattr(toggles, name, False):
            enabled.append(name)
    return enabled


def build_connector(name: str) -> BaseConnector:
    if name not in DISCOVERY_CONNECTOR_REGISTRY:
        raise KeyError(f"Unknown connector: {name}. Known: {list(DISCOVERY_CONNECTOR_REGISTRY)}")
    return DISCOVERY_CONNECTOR_REGISTRY[name]()
