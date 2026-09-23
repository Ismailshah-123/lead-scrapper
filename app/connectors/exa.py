"""
Exa connector — AVAILABLE once EXA_API_KEY is set.

Uses Exa's public Search API:
POST https://api.exa.ai/search with x-api-key authentication.
"""
from __future__ import annotations

from typing import Any, Dict, List

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.connectors.base import (
    BaseConnector,
    ConnectorAvailability,
    ConnectorUnavailableError,
    RawLead,
)
from app.core.config import get_secrets
from app.utils.rate_limiter import default_limiter

SEARCH_URL = "https://api.exa.ai/search"


class ExaConnector(BaseConnector):
    name = "exa"
    availability = ConnectorAvailability.AVAILABLE
    capability_summary = (
        "Exa public web search API (api.exa.ai) for supplemental lead discovery."
    )

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_secrets().exa_api_key

    def _require_key(self) -> str:
        if not self._api_key:
            raise ConnectorUnavailableError(
                "EXA_API_KEY is not set. Get one at https://dashboard.exa.ai/api-keys "
                "and add it to .env."
            )
        return self._api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def _search(self, query: str, max_results: int) -> Dict[str, Any]:
        api_key = self._require_key()
        default_limiter.wait()
        secrets = get_secrets()
        response = requests.post(
            SEARCH_URL,
            json={
                "query": query,
                "text": True,
                "numResults": min(max_results, 20),
            },
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            timeout=secrets.request_timeout_seconds,
        )
        if response.status_code in (401, 403):
            raise ConnectorUnavailableError(
                f"Exa rejected the request (HTTP {response.status_code}). Check EXA_API_KEY."
            )
        response.raise_for_status()
        return response.json()

    def _to_raw_lead(self, item: Dict[str, Any], query: str) -> RawLead:
        return RawLead(
            company_name=item.get("title") or item.get("url") or "Unknown",
            source=self.name,
            source_url=item.get("url"),
            website=item.get("url"),
            description=(item.get("text") or "")[:500] or None,
            raw_extra={
                "matched_query": query,
                "exa_id": item.get("id"),
                "published_date": item.get("publishedDate"),
            },
        )

    def discover(
        self, query: str, location: str = "", max_results: int = 20
    ) -> List[RawLead]:
        self._require_key()
        full_query = f"{query} {location}".strip()
        self.logger.info("Exa search: %r", full_query)
        try:
            data = self._search(full_query, max_results)
        except ConnectorUnavailableError:
            raise
        except requests.RequestException as exc:
            self.logger.error("Exa request failed: %s", exc)
            return []

        items = data.get("results", [])
        leads = [
            self._to_raw_lead(item, full_query)
            for item in items[:max_results]
        ]
        self.logger.info(
            "Exa returned %d result(s) for %r", len(leads), full_query
        )
        return leads
