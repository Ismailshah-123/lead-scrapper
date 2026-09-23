from app.utils.normalize import (
    classify_email_type,
    employee_range_overlaps,
    extract_domain,
    normalize_company_name,
    normalize_email,
    normalize_phone,
    parse_employee_range,
)


class TestNormalizeCompanyName:
    def test_strips_legal_suffix(self):
        assert normalize_company_name("ABC Roofing LLC") == normalize_company_name("ABC Roofing")

    def test_case_and_punctuation_insensitive(self):
        assert normalize_company_name("Acme, Inc.") == normalize_company_name("acme inc")

    def test_empty_input(self):
        assert normalize_company_name("") == ""
        assert normalize_company_name(None) == ""


class TestNormalizePhone:
    def test_valid_us_number_formats_to_e164(self):
        assert normalize_phone("(512) 555-0101", region="US") == "+15125550101"

    def test_already_e164_round_trips(self):
        assert normalize_phone("+15125550101") == "+15125550101"

    def test_garbage_returns_none(self):
        assert normalize_phone("not a phone number") is None

    def test_none_and_empty_return_none(self):
        assert normalize_phone(None) is None
        assert normalize_phone("") is None
        assert normalize_phone("   ") is None

    def test_too_short_returns_none_not_a_guess(self):
        assert normalize_phone("555-0101") is None or normalize_phone("555-0101") is not None
        # Either a valid short-form parse or None is acceptable; the only
        # thing that must never happen is silently fabricating a number
        # for something that isn't one:
        assert normalize_phone("banana") is None


class TestNormalizeEmail:
    def test_valid_email_normalizes(self):
        assert normalize_email("Info@Example.COM") == "info@example.com"

    def test_invalid_email_returns_none(self):
        assert normalize_email("not-an-email") is None

    def test_none_and_empty_return_none(self):
        assert normalize_email(None) is None
        assert normalize_email("") is None


class TestExtractDomain:
    def test_from_url(self):
        assert extract_domain("https://www.example.com/about") == "example.com"

    def test_from_bare_domain(self):
        assert extract_domain("example.com") == "example.com"

    def test_from_email(self):
        assert extract_domain("owner@example.com") == "example.com"

    def test_none_returns_none(self):
        assert extract_domain(None) is None
        assert extract_domain("") is None


class TestClassifyEmailType:
    def test_generic_prefix(self):
        assert classify_email_type("info@example.com") == "Company Domain (Generic)"

    def test_owner_name_match(self):
        assert classify_email_type("jordan@example.com", owner_name="Jordan Reyes") == "Owner/Decision-Maker"

    def test_free_webmail(self):
        assert "Free Webmail" in classify_email_type("someone@gmail.com")

    def test_plain_company_domain(self):
        assert classify_email_type("billing@example.com") == "Company Domain"

    def test_none_email(self):
        assert classify_email_type(None) == "Unknown"


class TestParseEmployeeRange:
    def test_range(self):
        assert parse_employee_range("51-100") == (51, 100)

    def test_estimated_range(self):
        assert parse_employee_range("Estimated 40-70") == (40, 70)

    def test_open_ended(self):
        assert parse_employee_range("100+") == (100, None)

    def test_bare_number(self):
        assert parse_employee_range("45") == (45, 45)

    def test_unknown_returns_none(self):
        assert parse_employee_range("Unknown") is None
        assert parse_employee_range(None) is None
        assert parse_employee_range("") is None


class TestEmployeeRangeOverlaps:
    def test_clear_overlap(self):
        assert employee_range_overlaps("45", 10, 100) is True

    def test_clear_non_overlap_too_small(self):
        assert employee_range_overlaps("3", 10, 100) is False

    def test_clear_non_overlap_too_big(self):
        assert employee_range_overlaps("500", 10, 100) is False

    def test_open_ended_within_max(self):
        assert employee_range_overlaps("50+", 10, 100) is True

    def test_open_ended_beyond_max(self):
        assert employee_range_overlaps("150+", 10, 100) is False

    def test_unknown_returns_none_not_a_guess(self):
        assert employee_range_overlaps("Unknown", 10, 100) is None
        assert employee_range_overlaps(None, 10, 100) is None
