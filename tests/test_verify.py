from app.core.config import TargetingConfig
from app.models.models import Company, Contact
from app.verification.verify import classify_lead, compute_contact_field_status, compute_owner_status


def _company(**kwargs) -> Company:
    defaults = dict(
        name="Test Co", source_primary="google_places", business_status="OPERATIONAL",
        website_status="Active", phone_verification_status="Not Found", email_verification_status="Not Found",
        duplicate_status="unique", verification_evidence={}, conflicting_fields=[], contacts=[],
    )
    defaults.update(kwargs)
    return Company(**defaults)


class TestComputeContactFieldStatus:
    def test_no_value_is_not_found(self):
        company = _company(phone=None)
        assert compute_contact_field_status(company, "phone") == "Not Found"

    def test_single_normal_source_is_publicly_listed(self):
        company = _company(phone="+15125550101", verification_evidence={"phone": [{"source": "google_places", "confidence": "normal"}]})
        assert compute_contact_field_status(company, "phone") == "Publicly Listed"

    def test_single_low_confidence_source_is_unverified(self):
        company = _company(phone="+15125550101", verification_evidence={"phone": [{"source": "website_text_match", "confidence": "low"}]})
        assert compute_contact_field_status(company, "phone") == "Unverified"

    def test_two_corroborating_sources_is_verified(self):
        company = _company(phone="+15125550101", verification_evidence={"phone": [
            {"source": "google_places", "confidence": "normal"},
            {"source": "website", "confidence": "normal"},
        ]})
        assert compute_contact_field_status(company, "phone") == "Verified"

    def test_flagged_conflict_wins_over_any_evidence_count(self):
        company = _company(phone="+15125550101", conflicting_fields=["phone"], verification_evidence={"phone": [
            {"source": "google_places", "confidence": "normal"}, {"source": "website", "confidence": "normal"},
        ]})
        assert compute_contact_field_status(company, "phone") == "Conflicting"


class TestComputeOwnerStatus:
    def test_no_contacts_is_not_found(self):
        assert compute_owner_status(_company(contacts=[])) == "Not Found"

    def test_publicly_identified_contact(self):
        company = _company(contacts=[Contact(full_name="Jordan Reyes", title="Owner", verification_status="Publicly Identified")])
        assert compute_owner_status(company) == "Publicly Identified"

    def test_never_verified_without_a_verified_contact(self):
        company = _company(contacts=[Contact(full_name="Jordan Reyes", title="Owner", verification_status="Unverified")])
        assert compute_owner_status(company) == "Unverified"


class TestClassifyLeadTiering:
    """Regression tests for the ordering bug caught during manual testing:
    unresolved uncertainty (unknown employee count, genuine conflicts)
    must route to needs_review BEFORE a low score can reject the lead."""

    def test_closed_business_is_rejected_regardless_of_score(self):
        config = TargetingConfig()
        company = _company(business_status="CLOSED_PERMANENTLY", crm_opportunity_score=95, employee_count="50", employee_count_type="Exact")
        bucket, reason = classify_lead(company, config)
        assert bucket == "rejected"
        assert "closed" in reason.lower()

    def test_confirmed_outside_employee_range_is_rejected(self):
        config = TargetingConfig(employee_min=10, employee_max=100)
        company = _company(employee_count="3", employee_count_type="Exact", crm_opportunity_score=95)
        bucket, reason = classify_lead(company, config)
        assert bucket == "rejected"
        assert "employee" in reason.lower()

    def test_unknown_employee_count_is_needs_review_even_with_low_score(self):
        # This is the exact bug caught by hand: a low CRM score must NOT
        # pre-empt the "we don't actually know if this fits" signal.
        config = TargetingConfig(crm_score_min=70)
        company = _company(employee_count=None, employee_count_type="Unknown", crm_opportunity_score=52)
        bucket, reason = classify_lead(company, config)
        assert bucket == "needs_review"
        assert "employee count" in reason.lower()

    def test_contact_conflict_is_needs_review_even_with_low_score(self):
        config = TargetingConfig(crm_score_min=70)
        company = _company(
            employee_count="30-50", employee_count_type="Public Range", crm_opportunity_score=66,
            contact_conflict=True, conflict_notes="Conflicting phone: a vs b",
        )
        bucket, reason = classify_lead(company, config)
        assert bucket == "needs_review"
        assert "conflicting" in reason.lower()

    def test_low_score_alone_with_no_uncertainty_is_rejected(self):
        config = TargetingConfig(crm_score_min=70)
        company = _company(employee_count="25", employee_count_type="Public Range", crm_opportunity_score=61, contact_conflict=False)
        bucket, reason = classify_lead(company, config)
        assert bucket == "rejected"
        assert "crm opportunity score" in reason.lower()

    def test_good_score_but_low_data_quality_is_needs_review_not_rejected(self):
        # "Excellent prospect, additional verification required" -- never
        # silently downgraded to rejected.
        config = TargetingConfig(crm_score_min=70, data_quality_min=75)
        company = _company(
            employee_count="45", employee_count_type="Public Range", crm_opportunity_score=95,
            data_quality_score=60,
        )
        bucket, reason = classify_lead(company, config)
        assert bucket == "needs_review"
        assert "data quality" in reason.lower()

    def test_passes_everything_is_master(self):
        config = TargetingConfig(crm_score_min=70, data_quality_min=50)
        company = _company(
            employee_count="45", employee_count_type="Public Range", crm_opportunity_score=85,
            data_quality_score=80, phone_verification_status="Verified",
        )
        bucket, reason = classify_lead(company, config)
        assert bucket == "master"

    def test_no_contact_info_at_all_is_needs_review(self):
        config = TargetingConfig(crm_score_min=70, data_quality_min=50)
        company = _company(
            employee_count="45", employee_count_type="Public Range", crm_opportunity_score=85,
            data_quality_score=80, phone_verification_status="Not Found", email_verification_status="Not Found",
        )
        bucket, reason = classify_lead(company, config)
        assert bucket == "needs_review"

    def test_no_reachable_presence_at_all_is_rejected(self):
        config = TargetingConfig()
        company = _company(
            website_status="Unreachable", phone_verification_status="Not Found", email_verification_status="Not Found",
            employee_count="45", employee_count_type="Public Range",
        )
        bucket, reason = classify_lead(company, config)
        assert bucket == "rejected"
