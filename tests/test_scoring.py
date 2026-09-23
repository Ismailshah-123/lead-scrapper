from app.core.config import TargetingConfig
from app.models.models import Company, CompanySignal, Contact
from app.scoring.scoring import score_company, score_crm_opportunity, score_data_quality


def _company(**kwargs) -> Company:
    defaults = dict(name="Test Co", source_primary="google_places", source_secondary=[], signals=[], contacts=[])
    defaults.update(kwargs)
    return Company(**defaults)


class TestCrmOpportunityScore:
    def test_strong_signals_score_high(self):
        config = TargetingConfig()
        company = _company(
            employee_count="45", employee_count_type="Public Range",
            website_status="Active", google_rating=4.7, review_count=64,
            meta_ad_evidence="Active ad found", industry="roofing",
            source_secondary=["website"],
            signals=[
                CompanySignal(signal_type="contact_form_present", evidence_text="x"),
                CompanySignal(signal_type="quote_request_language", evidence_text="x"),
                CompanySignal(signal_type="careers_page_found", evidence_text="x"),
            ],
        )
        score, level, breakdown = score_crm_opportunity(company, config)
        assert score >= 70
        assert level in ("HIGH", "VERY HIGH", "HOT")
        assert sum(breakdown.values()) == score

    def test_weak_signals_score_low(self):
        config = TargetingConfig()
        company = _company(employee_count="Unknown", employee_count_type="Unknown", website_status="Not Checked")
        score, level, breakdown = score_crm_opportunity(company, config)
        assert score < 40
        assert level == "LOW"

    def test_score_never_exceeds_100(self):
        config = TargetingConfig()
        company = _company(
            employee_count="50", employee_count_type="Exact", website_status="Active",
            google_rating=5.0, review_count=999, meta_ad_evidence="x", google_ad_evidence="x",
            industry="roofing", source_secondary=["website", "meta_ads", "google_search"],
            signals=[
                CompanySignal(signal_type="contact_form_present", evidence_text="x"),
                CompanySignal(signal_type="quote_request_language", evidence_text="x"),
                CompanySignal(signal_type="booking_language", evidence_text="x"),
                CompanySignal(signal_type="multiple_locations_mentioned", evidence_text="x"),
                CompanySignal(signal_type="careers_page_found", evidence_text="x"),
            ],
        )
        score, _, _ = score_crm_opportunity(company, config)
        assert score <= 100

    def test_existing_crm_detected_reduces_follow_up_and_automation_subscores(self):
        config = TargetingConfig()
        base_signals = [CompanySignal(signal_type="quote_request_language", evidence_text="x")]
        with_crm = _company(website_status="Active", signals=base_signals + [
            CompanySignal(signal_type="existing_crm_detected", evidence_text="HubSpot detected"),
        ])
        without_crm = _company(website_status="Active", signals=base_signals)

        score_with, _, breakdown_with = score_crm_opportunity(with_crm, config)
        score_without, _, breakdown_without = score_crm_opportunity(without_crm, config)
        assert breakdown_with["customer_follow_up_need"] <= breakdown_without["customer_follow_up_need"]
        assert breakdown_with["automation_opportunity"] <= breakdown_without["automation_opportunity"]

    def test_unknown_employee_count_is_neutral_not_zero(self):
        # A company shouldn't be penalized to zero just because we
        # couldn't determine size -- that's a data gap, not evidence
        # against the fit.
        config = TargetingConfig()
        company = _company(employee_count=None, employee_count_type="Unknown")
        _, _, breakdown = score_crm_opportunity(company, config)
        assert breakdown["business_size_fit"] == 5


class TestDataQualityScore:
    def test_fully_verified_scores_high(self):
        company = _company(
            website_status="Active", phone_verification_status="Verified", email_verification_status="Verified",
            employee_count_type="Exact", city="Austin", state="TX", industry="roofing",
            all_source_urls=["https://example.com"], duplicate_status="unique",
            source_secondary=["website"],
            contacts=[Contact(full_name="Jordan Reyes", title="Owner", verification_status="Verified")],
        )
        score, breakdown = score_data_quality(company)
        assert score >= 80
        assert sum(breakdown.values()) == score

    def test_nothing_found_scores_low(self):
        company = _company(
            website_status="Not Checked", phone_verification_status="Not Found", email_verification_status="Not Found",
            employee_count_type="Unknown", all_source_urls=[], duplicate_status="unique",
        )
        score, _ = score_data_quality(company)
        assert score < 30

    def test_merged_duplicate_never_scores_full_no_duplicate_credit(self):
        company = _company(duplicate_status="merged_into:1")
        _, breakdown = score_data_quality(company)
        assert breakdown["no_duplicate"] == 0

    def test_conflicting_contact_scores_lower_than_verified(self):
        conflicting = _company(phone_verification_status="Conflicting")
        verified = _company(phone_verification_status="Verified")
        _, b1 = score_data_quality(conflicting)
        _, b2 = score_data_quality(verified)
        assert b1["phone_verified"] < b2["phone_verified"]


class TestScoreCompanyWritesBothScores:
    def test_score_company_sets_all_fields(self):
        config = TargetingConfig()
        company = _company(employee_count="45", employee_count_type="Public Range", website_status="Active")
        score_company(company, config)
        assert company.crm_opportunity_score is not None
        assert company.crm_opportunity_level in ("HOT", "VERY HIGH", "HIGH", "MEDIUM", "LOW")
        assert company.data_quality_score is not None
        assert isinstance(company.crm_score_breakdown, dict)
        assert isinstance(company.data_quality_breakdown, dict)
