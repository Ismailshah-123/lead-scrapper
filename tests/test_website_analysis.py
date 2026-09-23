from bs4 import BeautifulSoup

from app.enrichment.website_analysis import WebsiteEnrichmentResult, analyze_html_signals


def _analyze(html: str, url: str = "https://example.com", path_hint: str = "") -> WebsiteEnrichmentResult:
    soup = BeautifulSoup(html, "html.parser")
    result = WebsiteEnrichmentResult(input_url=url)
    analyze_html_signals(soup, url, result, path_hint=path_hint)
    return result


class TestBasicExtraction:
    def test_title_and_meta_description(self):
        html = """<html><head><title>Acme Roofing</title>
        <meta name="description" content="Residential and commercial roofing."></head><body></body></html>"""
        result = _analyze(html)
        assert result.title == "Acme Roofing"
        assert result.meta_description == "Residential and commercial roofing."

    def test_mailto_link_extracted_and_normalized(self):
        html = '<html><body><a href="mailto:Info@Example.COM">Email us</a></body></html>'
        result = _analyze(html)
        assert result.extracted_emails == ["info@example.com"]

    def test_tel_link_is_structured_not_text_matched(self):
        html = '<html><body><a href="tel:+15125550101">Call us</a></body></html>'
        result = _analyze(html)
        assert "+15125550101" in result.structured_phones
        assert "+15125550101" not in result.extracted_phones

    def test_bare_text_phone_is_text_matched_only(self):
        html = "<html><body><p>Call us at (512) 555-0101 today.</p></body></html>"
        result = _analyze(html)
        assert "+15125550101" in result.extracted_phones
        assert "+15125550101" not in result.structured_phones

    def test_invalid_looking_phone_is_not_fabricated(self):
        html = "<html><body><p>We've served 1234 happy customers since 1999.</p></body></html>"
        result = _analyze(html)
        assert result.extracted_phones == []


class TestSignalDetection:
    def test_form_present(self):
        html = '<html><body><form><input type="email"></form></body></html>'
        result = _analyze(html)
        assert any(s["signal_type"] == "contact_form_present" for s in result.signals)

    def test_quote_request_language(self):
        html = "<html><body><h1>Get a free estimate today</h1></body></html>"
        result = _analyze(html)
        assert any(s["signal_type"] == "quote_request_language" for s in result.signals)

    def test_no_quote_language_no_false_positive(self):
        html = "<html><body><p>Welcome to our site.</p></body></html>"
        result = _analyze(html)
        assert not any(s["signal_type"] == "quote_request_language" for s in result.signals)

    def test_calendly_booking_widget_detected(self):
        html = '<html><body><script src="https://assets.calendly.com/widget.js"></script></body></html>'
        result = _analyze(html)
        assert any(s["signal_type"] == "booking_system_detected" and "Calendly" in s["evidence_text"] for s in result.signals)

    def test_hubspot_existing_crm_detected(self):
        html = '<html><head><script src="https://js.hs-scripts.com/12345.js"></script></head><body></body></html>'
        result = _analyze(html)
        assert any(s["signal_type"] == "existing_crm_detected" and "HubSpot" in s["evidence_text"] for s in result.signals)

    def test_intercom_chat_widget_detected(self):
        html = '<html><body><script src="https://widget.intercom.io/widget/abc"></script></body></html>'
        result = _analyze(html)
        assert any(s["signal_type"] == "chat_widget_detected" and "Intercom" in s["evidence_text"] for s in result.signals)

    def test_careers_page_signal_only_on_careers_path(self):
        html = "<html><body><p>We're hiring!</p></body></html>"
        result = _analyze(html, url="https://example.com/careers", path_hint="/careers")
        assert any(s["signal_type"] == "careers_page_found" for s in result.signals)


class TestDecisionMakerCandidate:
    def test_finds_owner_name_and_title_on_team_page(self):
        html = "<html><body><h3>Jordan Reyes, Owner</h3><p>Jordan has run the shop since 2010.</p></body></html>"
        result = _analyze(html, url="https://example.com/about", path_hint="/about")
        assert result.candidate_decision_maker is not None
        assert result.candidate_decision_maker["name"] == "Jordan Reyes"
        assert result.candidate_decision_maker["title"] == "Owner"
        assert result.candidate_decision_maker["status"] == "Publicly Identified"

    def test_never_returns_verified_status(self):
        html = "<html><body><h3>Jordan Reyes, Founder</h3></body></html>"
        result = _analyze(html, url="https://example.com/about", path_hint="/about")
        assert result.candidate_decision_maker["status"] != "Verified"

    def test_no_match_returns_none_rather_than_guessing(self):
        html = "<html><body><p>We are a family-owned business since 1999.</p></body></html>"
        result = _analyze(html, url="https://example.com/about", path_hint="/about")
        assert result.candidate_decision_maker is None

    def test_not_extracted_outside_team_about_paths(self):
        html = "<html><body><h3>Jordan Reyes, Owner</h3></body></html>"
        result = _analyze(html, url="https://example.com/services", path_hint="/services")
        assert result.candidate_decision_maker is None
