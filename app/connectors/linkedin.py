"""
LinkedIn connector — UNAVAILABLE.

This is a documented interface, not an implementation. Nothing in this
file makes a request to linkedin.com.

WHY
---
LinkedIn's User Agreement prohibits automated data collection from the
platform, and this is explicit and broad -- it is not limited to gated or
authenticated pages:

    "You agree that you will not... [d]evelop, support or use software,
    devices, scripts, robots, or any other means or processes (including
    crawlers, browser plugins and add-ons, or any other technology) to
    scrape the Services or otherwise copy profiles and other data from
    the Services."

This applies to public profile/company pages too -- "public" changes
nothing about the contract you agreed to when using LinkedIn. It's a
Terms-of-Service breach-of-contract issue, separate from and in addition
to any CAPTCHA/login-bypass concern. In hiQ Labs v. LinkedIn, the
long-running case most often cited to justify scraping "public" LinkedIn
data, LinkedIn ultimately prevailed on its breach-of-contract claim even
after hiQ won narrowly on a federal computer-crime theory. LinkedIn
continues to actively sue scraping operations (e.g. its October 2025
lawsuit against a company selling scraped LinkedIn data via API) and to
suspend/ban accounts and IP ranges associated with automated collection.
Building a scraper here would expose VertexData and its clients to real
legal and account-suspension risk for no durable technical advantage --
LinkedIn also continuously updates anti-automation defenses, so a scraper
built today tends to break within weeks anyway.

WHAT TO DO INSTEAD
------------------
There is no free, fully-compliant, DIY way to bulk-search LinkedIn company
data. The realistic options, roughly cheapest/most-manual to
most-turnkey:

  1. Manual research: a human looks up the company/decision-maker on
     LinkedIn and copies what's needed. Fully compliant (ordinary human
     browsing), just not automatable at scale.
  2. LinkedIn Sales Navigator, used manually or via LinkedIn's own sanctioned
     export tools within its terms -- LinkedIn's own paid product for
     exactly this use case.
  3. A properly licensed third-party B2B data provider (e.g. ZoomInfo,
     Apollo, or similar) that has its own data-sourcing agreements. This
     is the "optional future integration" the original brief already
     anticipated for tools like these -- wire one in here via a new
     connector once you've chosen and licensed one; the RawLead shape
     this project uses (see app/connectors/base.py) will accept whatever
     it returns without changing anything else in the pipeline.

If you enable this connector in config.yaml, discover() raises
ConnectorUnavailableError immediately and explains why -- it will never
silently return an empty list disguised as "ran fine, found nothing".
"""
from __future__ import annotations

from typing import List

from app.connectors.base import BaseConnector, ConnectorAvailability, ConnectorUnavailableError, RawLead


class LinkedInConnector(BaseConnector):
    name = "linkedin"
    availability = ConnectorAvailability.UNAVAILABLE
    capability_summary = (
        "Not implemented, by design. LinkedIn's User Agreement prohibits automated "
        "scraping/collection, public pages included, and LinkedIn actively litigates over "
        "it. See this file's module docstring for compliant alternatives (manual research, "
        "Sales Navigator, or a licensed third-party data provider wired in as a new "
        "connector)."
    )

    def discover(self, query: str, location: str = "", max_results: int = 20) -> List[RawLead]:
        raise ConnectorUnavailableError(
            "LinkedIn discovery is intentionally not implemented -- automated scraping of "
            "LinkedIn (including public pages) breaches its Terms of Service. See "
            "app/connectors/linkedin.py for why and for compliant alternatives."
        )

    def is_available(self) -> bool:
        return False
