"""
Facebook Pages connector — LIMITED.

Uses the official Graph API (`GET /{page-id}`) with a Page Access Token.
This only works for:
  (a) Pages you or your client already manage, using a token generated
      through that Page's own settings, or
  (b) Pages made accessible to your app after Meta App Review grants the
      relevant public-data permissions.

It is NOT a general public-Facebook-page harvester. Meta's Terms of
Service prohibit automated collection of Page data outside these
sanctioned paths, independent of any anti-bot/CAPTCHA bypass -- the same
principle covered in the README's Compliance notes for LinkedIn. Disabled
by default in config.yaml (sources.facebook_pages: false); this connector
only does something if you deliberately supply a token for pages you're
entitled to query.
"""
from __future__ import annotations

from typing import Any, Dict, List

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.connectors.base import BaseConnector, ConnectorAvailability, ConnectorUnavailableError, RawLead
from app.core.config import get_secrets
from app.utils.rate_limiter import default_limiter

FIELDS = "id,name,about,website,phone,emails,category,location,fan_count"


class FacebookPagesConnector(BaseConnector):
    name = "facebook_pages"
    availability = ConnectorAvailability.LIMITED
    capability_summary = (
        "Official Graph API. Only returns data for Pages you already manage (via a Page "
        "Access Token) or that Meta App Review has granted your app access to. NOT a "
        "public-page scraper/discovery tool -- pass Page IDs you're entitled to query via "
        "discover(query=<page_id>), it does not search Facebook for prospects."
    )

    def __init__(self) -> None:
        super().__init__()
        self._token = get_secrets().facebook_page_access_token

    def _require_token(self) -> str:
        if not self._token:
            raise ConnectorUnavailableError(
                "FACEBOOK_PAGE_ACCESS_TOKEN is not set. This connector only works for Pages "
                "you manage or have App Review access to -- see README Compliance notes. "
                "It cannot discover new prospect Pages."
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
    def _get_page(self, page_id: str) -> Dict[str, Any]:
        token = self._require_token()
        default_limiter.wait()
        secrets = get_secrets()
        response = requests.get(
            f"https://graph.facebook.com/v23.0/{page_id}",
            params={"fields": FIELDS, "access_token": token},
            timeout=secrets.request_timeout_seconds,
        )
        if response.status_code in (401, 403):
            raise ConnectorUnavailableError(
                f"Graph API rejected the request for page_id={page_id} (HTTP {response.status_code}). "
                "The token likely doesn't have access to this Page."
            )
        response.raise_for_status()
        return response.json()

    def discover(self, query: str, location: str = "", max_results: int = 20) -> List[RawLead]:
        """`query` here is a Facebook Page ID you already have permission to
        read -- NOT a search term. This connector cannot search Facebook
        for prospects; see capability_summary."""
        self._require_token()
        try:
            page = self._get_page(query)
        except ConnectorUnavailableError:
            raise
        except requests.RequestException as exc:
            self.logger.error("Facebook Graph API request failed for %s: %s", query, exc)
            return []

        location_data = page.get("location", {}) or {}
        lead = RawLead(
            company_name=page.get("name", "Unknown"),
            source=self.name,
            source_url=f"https://www.facebook.com/{page.get('id')}",
            website=page.get("website"),
            phone=page.get("phone"),
            email=(page.get("emails") or [None])[0],
            city=location_data.get("city"),
            state=location_data.get("state"),
            zip=location_data.get("zip"),
            country=location_data.get("country"),
            industry=page.get("category"),
            description=page.get("about"),
            facebook_url=f"https://www.facebook.com/{page.get('id')}",
            review_count=page.get("fan_count"),
            raw_extra={"note": "Retrieved via Graph API with a Page Access Token you supplied."},
        )
        return [lead]
