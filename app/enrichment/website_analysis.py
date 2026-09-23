"""
Website enrichment connector — AVAILABLE, and meant to be the strongest
signal source in the whole pipeline.

This fetches a prospect's OWN public marketing site (homepage + common
subpages), respecting robots.txt and a shared rate limiter. That's
standard, low-risk web fetching of a business's own published content —
categorically different from scraping a third-party platform like
LinkedIn or Facebook, which is why this connector is AVAILABLE while those
are not.

Two honesty rules enforced throughout:
  1. A decision-maker "found" here is only ever status Publicly Identified
     — a name+title pulled from the company's own team/about page. It is
     NEVER marked Verified, because one automated text match is not
     cross-source verification. A human should click the source_url and
     confirm before using it.
  2. Absence of a detected signal is reported as "not identified from
     public website analysis", never as a confirmed negative ("they don't
     have a CRM") — we only saw what's visible in static HTML, not what
     runs behind a login.
"""
from __future__ import annotations

import re
import urllib.robotparser as robotparser
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.connectors.base import ConnectorAvailability
from app.core.config import get_secrets
from app.core.logging_config import get_logger
from app.utils.normalize import normalize_email, normalize_phone
from app.utils.rate_limiter import default_limiter
from app.utils.validators import is_safe_url

logger = get_logger("enrichment.website")

COMMON_PATHS = [
    "", "/about", "/about-us", "/contact", "/contact-us", "/services",
    "/team", "/our-team", "/leadership", "/careers", "/locations",
    "/pricing", "/booking", "/schedule", "/request-a-quote", "/get-a-quote",
    "/quote", "/free-estimate",
]

DECISION_MAKER_TITLES = [
    "owner", "founder", "co-founder", "ceo", "chief executive officer",
    "president", "managing director", "general manager", "head of sales",
    "sales director", "operations director", "marketing director",
    "business development director",
]

CHAT_WIDGET_SIGNATURES = {
    "Intercom": ["widget.intercom.io", "js.intercomcdn.com"],
    "Drift": ["js.driftt.com"],
    "Tawk.to": ["embed.tawk.to"],
    "Zendesk Chat": ["static.zdassets.com", "webwidget.zendesk"],
    "Crisp": ["client.crisp.chat"],
    "LiveChat": ["cdn.livechatinc.com"],
    "Chatra": ["chatra.io"],
}

# Detecting these means the company likely ALREADY has CRM/marketing
# automation — this should reduce (not add to) the CRM Opportunity Score.
CRM_MARKETING_AUTOMATION_SIGNATURES = {
    "HubSpot": ["js.hs-scripts.com", "js.hubspot.com", "forms.hubspot.com"],
    "Salesforce/Pardot": ["pi.pardot.com", "form.salesforce.com"],
    "Marketo": ["munchkin.js", "marketo.net"],
    "ActiveCampaign": ["activehosted.com/proc.php", "trackcmp.net"],
    "Zoho CRM": ["zohopublic.com", "crm.zoho.com"],
    "Keap/Infusionsoft": ["infusionsoft.com", "keap.app"],
}

BOOKING_SIGNATURES = {
    "Calendly": ["calendly.com"],
    "Acuity Scheduling": ["acuityscheduling.com"],
    "Square Appointments": ["squareup.com/appointments"],
    "SimplyBook.me": ["simplybook.me"],
}

FORM_BUILDER_SIGNATURES = {
    "Typeform": ["typeform.com"],
    "JotForm": ["jotform.com"],
    "Google Forms": ["docs.google.com/forms"],
    "Gravity Forms": ["gform_wrapper"],
    "Contact Form 7": ["wpcf7"],
}

QUOTE_KEYWORDS = ["free estimate", "request a quote", "get a quote", "get an estimate", "request quote", "free quote"]
BOOKING_KEYWORDS = ["book now", "book online", "schedule a", "book an appointment", "schedule an appointment", "make an appointment"]

PHONE_TEXT_PATTERN = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_NAME_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z]\.?)?\s[A-Z][a-z]+)\b")


@dataclass
class PageFetch:
    url: str
    status_code: int
    html: str
    final_url: str


@dataclass
class WebsiteEnrichmentResult:
    input_url: str
    status: str = "Not Checked"  # Active/Unreachable/Not Found/Not Checked
    final_url: Optional[str] = None
    title: Optional[str] = None
    meta_description: Optional[str] = None
    services_text: Optional[str] = None
    pages_checked: List[str] = field(default_factory=list)
    structured_phones: List[str] = field(default_factory=list)  # from tel: links -- higher confidence
    extracted_phones: List[str] = field(default_factory=list)  # from free-text pattern matching -- lower confidence
    extracted_emails: List[str] = field(default_factory=list)
    candidate_decision_maker: Optional[Dict[str, str]] = None
    signals: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None


def _extract_decision_maker_candidate(soup: BeautifulSoup, url: str) -> Optional[Dict[str, str]]:
    """Best-effort only. Scans short text blocks for a role keyword
    co-located with a name-shaped phrase. Always returns status
    'Publicly Identified' — never 'Verified'. Returns None rather than a
    low-confidence guess when nothing clearly matches."""
    candidates: List[Dict[str, str]] = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "span"]):
        segment = tag.get_text(" ", strip=True)
        if not segment or len(segment) > 120:
            continue
        lower_segment = segment.lower()
        matched_title = next((t for t in DECISION_MAKER_TITLES if t in lower_segment), None)
        if not matched_title:
            continue
        name_match = _NAME_PATTERN.search(segment)
        if not name_match:
            continue
        candidates.append({
            "name": name_match.group(1),
            "title": matched_title.title(),
            "source_url": url,
            "status": "Publicly Identified",
        })
    if not candidates:
        return None
    for title_kw in DECISION_MAKER_TITLES:  # priority order matches spec section 10
        for c in candidates:
            if c["title"].lower() == title_kw:
                return c
    return candidates[0]


def analyze_html_signals(soup: BeautifulSoup, url: str, result: WebsiteEnrichmentResult, path_hint: str = "") -> None:
    """Pure(ish) parsing step — takes an already-fetched, already-parsed
    page and mutates `result` in place. No network calls happen here,
    which is what makes it fully unit-testable with static HTML fixtures."""
    text = soup.get_text(" ", strip=True)
    lower_text = text.lower()
    html_str = str(soup)

    if not result.title and soup.title and soup.title.string:
        result.title = soup.title.string.strip()
    if not result.meta_description:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            result.meta_description = meta["content"].strip()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("mailto:"):
            candidate = href.split(":", 1)[1].split("?")[0]
            normalized = normalize_email(candidate)
            if normalized and normalized not in result.extracted_emails:
                result.extracted_emails.append(normalized)
        elif href.lower().startswith("tel:"):
            candidate = href.split(":", 1)[1]
            normalized = normalize_phone(candidate)
            if normalized and normalized not in result.structured_phones:
                result.structured_phones.append(normalized)

    for match in PHONE_TEXT_PATTERN.finditer(text):
        normalized = normalize_phone(match.group(0))
        if normalized and normalized not in result.extracted_phones and normalized not in result.structured_phones:
            result.extracted_phones.append(normalized)

    forms = soup.find_all("form")
    if forms:
        result.signals.append({
            "signal_type": "contact_form_present",
            "evidence_text": f"{len(forms)} HTML <form> element(s) found",
            "source_url": url,
        })

    if any(kw in lower_text for kw in QUOTE_KEYWORDS):
        result.signals.append({
            "signal_type": "quote_request_language",
            "evidence_text": "Page uses quote/estimate-request language",
            "source_url": url,
        })

    if any(kw in lower_text for kw in BOOKING_KEYWORDS):
        result.signals.append({
            "signal_type": "booking_language",
            "evidence_text": "Page uses booking/appointment language",
            "source_url": url,
        })

    for vendor, needles in BOOKING_SIGNATURES.items():
        if any(needle in html_str for needle in needles):
            result.signals.append({"signal_type": "booking_system_detected", "evidence_text": f"{vendor} booking widget detected", "source_url": url})

    for vendor, needles in CHAT_WIDGET_SIGNATURES.items():
        if any(needle in html_str for needle in needles):
            result.signals.append({"signal_type": "chat_widget_detected", "evidence_text": f"{vendor} chat widget detected", "source_url": url})

    for vendor, needles in CRM_MARKETING_AUTOMATION_SIGNATURES.items():
        if any(needle in html_str for needle in needles):
            result.signals.append({"signal_type": "existing_crm_detected", "evidence_text": f"{vendor} footprint detected on site (likely already has CRM/marketing automation)", "source_url": url})

    for vendor, needles in FORM_BUILDER_SIGNATURES.items():
        if any(needle in html_str for needle in needles):
            result.signals.append({"signal_type": "form_builder_detected", "evidence_text": f"{vendor} form embed detected", "source_url": url})

    if path_hint == "/careers" or "careers" in url.lower():
        result.signals.append({"signal_type": "careers_page_found", "evidence_text": "Dedicated careers page found (possible growth/hiring signal)", "source_url": url})

    if path_hint == "/locations" or "our locations" in lower_text or "multiple locations" in lower_text:
        result.signals.append({"signal_type": "multiple_locations_mentioned", "evidence_text": "Page references multiple locations", "source_url": url})

    if path_hint == "/services" and not result.services_text:
        result.services_text = text[:600]

    if path_hint in ("/team", "/our-team", "/leadership", "/about", "/about-us") and result.candidate_decision_maker is None:
        candidate = _extract_decision_maker_candidate(soup, url)
        if candidate:
            result.candidate_decision_maker = candidate
            result.signals.append({
                "signal_type": "decision_maker_publicly_identified",
                "evidence_text": f"{candidate['name']} listed as {candidate['title']} — confirm before using",
                "source_url": url,
            })


class WebsiteEnrichmentConnector:
    """Deliberately NOT a BaseConnector subclass: this operates per-lead on
    an existing website URL via `enrich(url)`, not a text query via
    `discover(query)`. Still exposes describe() so it lists alongside real
    connectors in `python -m app sources`."""

    name = "website"
    availability = ConnectorAvailability.AVAILABLE
    capability_summary = (
        "Fetches a prospect's OWN public marketing site (homepage + ~15 common subpages), "
        "respecting robots.txt and rate limits. Extracts contact details and CRM-opportunity "
        "signals (forms, booking widgets, chat widgets, existing CRM footprints). Any "
        "decision-maker found this way is 'Publicly Identified', never 'Verified'."
    )

    def __init__(self) -> None:
        self.logger = get_logger(f"connector.{self.name}")
        self.session = requests.Session()

    @classmethod
    def describe(cls) -> Dict[str, str]:
        return {"name": cls.name, "availability": cls.availability.value, "summary": cls.capability_summary}

    def _load_robots(self, base_url: str) -> robotparser.RobotFileParser:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        try:
            if is_safe_url(robots_url):
                default_limiter.wait()
                resp = self.session.get(
                    robots_url,
                    timeout=get_secrets().request_timeout_seconds,
                    headers={"User-Agent": get_secrets().user_agent},
                )
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            else:
                rp.parse([])
        except requests.RequestException:
            rp.parse([])  # no robots.txt reachable -> permissive default, per convention
        return rp

    def _fetch(self, url: str, robots: robotparser.RobotFileParser) -> Optional[PageFetch]:
        if not is_safe_url(url):
            self.logger.warning("Refusing to fetch unsafe URL: %s", url)
            return None
        user_agent = get_secrets().user_agent
        if not robots.can_fetch(user_agent, url):
            self.logger.info("robots.txt disallows fetching %s", url)
            return None
        try:
            default_limiter.wait()
            resp = self.session.get(
                url, timeout=get_secrets().request_timeout_seconds,
                headers={"User-Agent": user_agent}, allow_redirects=True,
            )
        except requests.RequestException as exc:
            self.logger.info("Fetch failed for %s: %s", url, exc)
            return None
        if resp.status_code >= 400:
            return None
        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return None
        return PageFetch(url=url, status_code=resp.status_code, html=resp.text, final_url=resp.url)

    def enrich(self, website_url: str) -> WebsiteEnrichmentResult:
        result = WebsiteEnrichmentResult(input_url=website_url or "")

        if not website_url:
            result.status = "Not Found"
            result.error = "No website URL supplied."
            return result

        if not is_safe_url(website_url):
            result.status = "Unreachable"
            result.error = "URL failed safety validation (invalid, non-http(s), or resolves to a private/reserved address)."
            return result

        robots = self._load_robots(website_url)
        home = self._fetch(website_url, robots)
        if home is None:
            result.status = "Unreachable"
            return result

        result.status = "Active"
        result.final_url = home.final_url
        base = home.final_url

        soup = BeautifulSoup(home.html, "html.parser")
        analyze_html_signals(soup, home.url, result, path_hint="")
        result.pages_checked.append(home.url)

        for path in COMMON_PATHS[1:]:
            page_url = urljoin(base, path)
            if urlparse(page_url).netloc != urlparse(base).netloc:
                continue
            fetched = self._fetch(page_url, robots)
            if fetched is None:
                continue
            page_soup = BeautifulSoup(fetched.html, "html.parser")
            analyze_html_signals(page_soup, fetched.url, result, path_hint=path)
            result.pages_checked.append(fetched.url)

        return result
