"""
Meta Ad Library connector — LIMITED.

Uses the official, public Ad Library API:
https://www.facebook.com/ads/library/api/
This is ad-transparency data, not a scraper — Meta built this endpoint
specifically to be queried. Requires META_ACCESS_TOKEN from a Meta
developer app that has completed identity verification.

REAL LIMITATION (checked at build time, 2026): for ad_reached_countries
outside the UK/EU, the API only indexes political and social-issue ads.
Ordinary commercial ads (a roofing company's lead-gen ad, say) are only
covered when the ad ran in a UK/EU country. For a USA-targeted build —
your stated ICP — this means most calls for typical SMB categories will
legitimately come back empty. That's Meta's restriction, not a bug here.
Set ad_reached_countries to a UK/EU country to see this connector's full
behavior, or treat it as a UK/EU-expansion channel rather than a US one.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.connectors.base import BaseConnector, ConnectorAvailability, ConnectorUnavailableError, RawLead
from app.core.config import get_secrets
from app.utils.rate_limiter import default_limiter

FIELDS = "id,page_name,page_id,ad_creation_time,ad_delivery_start_time,ad_snapshot_url,publisher_platforms"


class MetaAdLibraryConnector(BaseConnector):
    name = "meta_ads"
    availability = ConnectorAvailability.LIMITED
    capability_summary = (
        "Official Ad Library API (ad transparency, not scraping). For ad_reached_countries "
        "outside the UK/EU, Meta only indexes political/social-issue ads -- ordinary "
        "commercial SMB ads in the US will mostly return nothing. Useful signal source if "
        "you expand to UK/EU; for US leads, treat as best-effort/likely-empty."
    )

    def __init__(self) -> None:
        super().__init__()
        secrets = get_secrets()
        self._token = secrets.meta_access_token
        self._api_version = secrets.meta_api_version

    def _require_token(self) -> str:
        if not self._token:
            raise ConnectorUnavailableError(
                "META_ACCESS_TOKEN is not set. Requires a Meta developer app with identity "
                "verification completed -- see https://www.facebook.com/ads/library/api/. "
                "Add the token to .env to enable this connector."
            )
        return self._token

    def is_available(self) -> bool:
        return bool(self._token)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def _call_api(self, search_terms: str, country: str) -> Dict[str, Any]:
        token = self._require_token()
        default_limiter.wait()
        secrets = get_secrets()
        url = f"https://graph.facebook.com/{self._api_version}/ads_archive"
        response = requests.get(
            url,
            params={
                "access_token": token,
                "search_terms": search_terms,
                "ad_reached_countries": json.dumps([country]),
                "ad_active_status": "ALL",
                "fields": FIELDS,
                "limit": 25,
            },
            timeout=secrets.request_timeout_seconds,
        )
        if response.status_code in (401, 403):
            raise ConnectorUnavailableError(
                f"Meta Ad Library API rejected the request (HTTP {response.status_code}). "
                "Check META_ACCESS_TOKEN and that the app has completed identity verification."
            )
        response.raise_for_status()
        return response.json()

    def _to_raw_lead(self, ad: Dict[str, Any], query: str) -> RawLead:
        return RawLead(
            company_name=ad.get("page_name", "Unknown"),
            source=self.name,
            source_url=ad.get("ad_snapshot_url"),
            facebook_url=f"https://www.facebook.com/{ad['page_id']}" if ad.get("page_id") else None,
            meta_ad_evidence=f"Active/past ad found (ad_id={ad.get('id')}, started {ad.get('ad_delivery_start_time', 'unknown date')})",
            raw_extra={"matched_query": query, "publisher_platforms": ad.get("publisher_platforms", [])},
        )

    def discover(self, query: str, location: str = "", max_results: int = 20) -> List[RawLead]:
        self._require_token()
        country = "US"
        for candidate in ("US", "USA", "United States"):
            if candidate.lower() in (location or "").lower():
                country = "US"
        self.logger.info("Meta Ad Library search: %r (country=%s)", query, country)

        try:
            data = self._call_api(query, country)
        except ConnectorUnavailableError:
            raise
        except requests.RequestException as exc:
            self.logger.error("Meta Ad Library request failed: %s", exc)
            return []

        ads = data.get("data", [])
        if not ads and country == "US":
            self.logger.info(
                "No results for %r in US -- expected, since Meta's API only indexes "
                "political/social-issue ads outside the UK/EU.", query,
            )
        leads = [self._to_raw_lead(ad, query) for ad in ads[:max_results]]
        self.logger.info("Meta Ad Library returned %d result(s) for %r", len(leads), query)
        return leads
