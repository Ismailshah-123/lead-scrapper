"""
Google Places connector — AVAILABLE.

Uses the official Places API (New): https://places.googleapis.com/v1/
Requires GOOGLE_PLACES_API_KEY (Google Cloud Console -> enable "Places API
(New)" -> create a key, restrict it to that API). Has a limited free
monthly allowance and then usage-based billing; Google has changed this
pricing more than once, so check the current Maps Platform pricing page
before relying on a specific number.

This connector deliberately does NOT try to determine employee count,
owner/decision-maker, or CRM signals — Places data doesn't contain those.
It hands off `website` to the website-enrichment connector, which is where
that analysis happens (spec section: "Do NOT assume Google Places alone
provides owner / employee count / email / CRM information").
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential, retry

from app.connectors.base import BaseConnector, ConnectorAvailability, ConnectorUnavailableError, RawLead
from app.core.config import get_secrets
from app.utils.rate_limiter import default_limiter

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.addressComponents",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.googleMapsUri",
        "places.primaryTypeDisplayName",
        "places.types",
    ]
)

# Places API businessStatus values map cleanly onto ours already, but keep
# an explicit map so a future API change surfaces as "Unknown" rather than
# silently passing through an unrecognized string as if we understood it.
_BUSINESS_STATUS_MAP = {
    "OPERATIONAL": "OPERATIONAL",
    "CLOSED_TEMPORARILY": "CLOSED_TEMPORARILY",
    "CLOSED_PERMANENTLY": "CLOSED_PERMANENTLY",
}


class GooglePlacesConnector(BaseConnector):
    name = "google_places"
    availability = ConnectorAvailability.AVAILABLE
    capability_summary = (
        "Official Places API (New). Returns name, address, phone, website, rating, "
        "review count, and operating status. Does NOT provide employee count, owner, "
        "or CRM signals — those come from the website-enrichment connector downstream."
    )

    def __init__(self) -> None:
        super().__init__()
        self._api_key = get_secrets().google_places_api_key

    def _require_key(self) -> str:
        if not self._api_key:
            raise ConnectorUnavailableError(
                "GOOGLE_PLACES_API_KEY is not set. Get one at "
                "https://console.cloud.google.com/google/maps-apis/api-list "
                "(enable 'Places API (New)') and add it to .env."
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
    def _search_text(self, text_query: str, max_results: int) -> Dict[str, Any]:
        api_key = self._require_key()
        default_limiter.wait()
        secrets = get_secrets()
        response = requests.post(
            TEXT_SEARCH_URL,
            json={"textQuery": text_query, "maxResultCount": min(max_results, 20)},
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            timeout=secrets.request_timeout_seconds,
        )
        if response.status_code == 401 or response.status_code == 403:
            raise ConnectorUnavailableError(
                f"Google Places API rejected the request (HTTP {response.status_code}). "
                "Check GOOGLE_PLACES_API_KEY, that billing is enabled on the project, and "
                "that 'Places API (New)' is enabled for this key."
            )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_component(components: List[Dict[str, Any]], type_name: str) -> Optional[str]:
        for comp in components or []:
            if type_name in comp.get("types", []):
                return comp.get("shortText") or comp.get("longText")
        return None

    def _to_raw_lead(self, place: Dict[str, Any], query: str) -> RawLead:
        components = place.get("addressComponents", [])
        display_name = (place.get("displayName") or {}).get("text", "").strip()
        place_id = place.get("id", "")
        business_status = _BUSINESS_STATUS_MAP.get(place.get("businessStatus", ""), "Unknown")

        return RawLead(
            company_name=display_name or "Unknown",
            source=self.name,
            source_url=place.get("googleMapsUri"),
            website=place.get("websiteUri"),
            phone=place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber"),
            address=place.get("formattedAddress"),
            city=self._extract_component(components, "locality"),
            state=self._extract_component(components, "administrative_area_level_1"),
            zip=self._extract_component(components, "postal_code"),
            country=self._extract_component(components, "country"),
            industry=(place.get("primaryTypeDisplayName") or {}).get("text"),
            google_maps_url=place.get("googleMapsUri"),
            google_rating=place.get("rating"),
            review_count=place.get("userRatingCount"),
            business_status=business_status,
            raw_extra={"place_id": place_id, "types": place.get("types", []), "matched_query": query},
        )

    def discover(self, query: str, location: str = "", max_results: int = 20) -> List[RawLead]:
        self._require_key()
        text_query = f"{query} in {location}" if location else query
        self.logger.info("Google Places text search: %r", text_query)

        try:
            data = self._search_text(text_query, max_results)
        except ConnectorUnavailableError:
            raise
        except requests.RequestException as exc:
            self.logger.error("Google Places request failed: %s", exc)
            return []

        places = data.get("places", [])
        leads = [self._to_raw_lead(p, text_query) for p in places]
        self.logger.info("Google Places returned %d result(s) for %r", len(leads), text_query)
        return leads
