"""
Google Custom Search connector — LIMITED.

Uses the official Custom Search JSON API:
https://developers.google.com/custom-search/v1/overview

IMPORTANT (checked at build time, 2026): this API is closed to new
customers and Google has announced it will be fully discontinued on
2027-01-01. If you don't already have an existing Programmable Search
Engine + API key from before the closure, you cannot sign up for one now —
this connector will simply report itself unavailable. That is Google's
restriction, not a bug in this code. Treat Google Places + website
enrichment as your primary Google-side discovery path; this connector is
here so the interface exists (and works immediately) for anyone who does
have a legacy key, or if Google reopens/replaces the program later.

Never scrapes google.com/search directly — that violates Google's Terms
of Service independent of any CAPTCHA/anti-bot bypass.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.connectors.base import BaseConnector, ConnectorAvailability, ConnectorUnavailableError, RawLead
from app.core.config import get_secrets
from app.utils.rate_limiter import default_limiter

SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

_TITLE_JUNK_PATTERN = re.compile(
    r"\s*[\|\-–—:]\s*(home|official site|homepage|welcome).*$", re.IGNORECASE
)


class GoogleCustomSearchConnector(BaseConnector):
    name = "google_search"
    availability = ConnectorAvailability.LIMITED
    capability_summary = (
        "Official Custom Search JSON API. Works ONLY if you already have an existing "
        "API key + Search Engine ID from before Google closed the program to new "
        "customers (2026); the API is being fully shut down 2027-01-01. Falls back "
        "cleanly (ConnectorUnavailableError) if not configured — use Google Places + "
        "website enrichment as the primary Google-side channel instead."
    )

    def __init__(self) -> None:
        super().__init__()
        secrets = get_secrets()
        self._api_key = secrets.google_custom_search_api_key
        self._cx = secrets.google_custom_search_cx

    def _require_credentials(self) -> None:
        if not self._api_key or not self._cx:
            raise ConnectorUnavailableError(
                "GOOGLE_CUSTOM_SEARCH_API_KEY / GOOGLE_CUSTOM_SEARCH_CX are not set. "
                "Note: Google closed this API to new customers in 2026 and is retiring "
                "it entirely on 2027-01-01 — this only works with a pre-existing key. "
                "Rely on Google Places + website enrichment instead."
            )

    def is_available(self) -> bool:
        return bool(self._api_key and self._cx)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def _search(self, query: str, start_index: int) -> Dict[str, Any]:
        default_limiter.wait()
        secrets = get_secrets()
        response = requests.get(
            SEARCH_URL,
            params={"key": self._api_key, "cx": self._cx, "q": query, "start": start_index},
            timeout=secrets.request_timeout_seconds,
        )
        if response.status_code in (401, 403):
            raise ConnectorUnavailableError(
                f"Google Custom Search rejected the request (HTTP {response.status_code}). "
                "Key/CX may be invalid, quota exhausted, or the project predates the 2026 "
                "new-customer closure but has since lost access."
            )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _clean_title(title: str) -> str:
        return _TITLE_JUNK_PATTERN.sub("", title or "").strip()

    def _to_raw_lead(self, item: Dict[str, Any], query: str) -> RawLead:
        return RawLead(
            company_name=self._clean_title(item.get("title", "")) or item.get("displayLink", "Unknown"),
            source=self.name,
            source_url=item.get("link"),
            website=item.get("link"),
            description=item.get("snippet"),
            raw_extra={"matched_query": query, "display_link": item.get("displayLink")},
        )

    def discover(self, query: str, location: str = "", max_results: int = 20) -> List[RawLead]:
        self._require_credentials()
        full_query = f"{query} {location}".strip()
        self.logger.info("Google Custom Search: %r", full_query)

        leads: List[RawLead] = []
        # The API returns up to 10 results per call; page via `start`.
        for start_index in range(1, min(max_results, 20) + 1, 10):
            try:
                data = self._search(full_query, start_index)
            except ConnectorUnavailableError:
                raise
            except requests.RequestException as exc:
                self.logger.error("Google Custom Search request failed: %s", exc)
                break
            items = data.get("items", [])
            if not items:
                break
            leads.extend(self._to_raw_lead(item, full_query) for item in items)
            if len(leads) >= max_results:
                break

        leads = leads[:max_results]
        self.logger.info("Google Custom Search returned %d result(s) for %r", len(leads), full_query)
        return leads
