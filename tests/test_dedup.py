from app.deduplication.dedup import deduplicate_companies
from app.models.models import Company, SourceRecord
from app.utils.merge import merge_field_with_evidence


def _make_company(session, **kwargs):
    defaults = dict(
        normalized_name=kwargs.get("name", "").lower(),
        country="USA", duplicate_status="unique", source_secondary=[], all_source_urls=[],
    )
    defaults.update(kwargs)
    company = Company(**defaults)
    session.add(company)
    session.flush()
    return company


class TestDuplicateDetection:
    def test_same_domain_is_a_duplicate(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", source_primary="google_places")
        b = _make_company(db_session, name="Acme Roofing LLC", domain="acmeroofing.com", source_primary="google_search")
        survivors = deduplicate_companies([a, b])
        assert len(survivors) == 1

    def test_same_phone_is_a_duplicate(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", phone="+15125550101", source_primary="google_places")
        b = _make_company(db_session, name="Acme Roofing Co", phone="+15125550101", source_primary="website")
        survivors = deduplicate_companies([a, b])
        assert len(survivors) == 1

    def test_same_name_and_city_is_a_duplicate(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", city="Austin", source_primary="google_places")
        b = _make_company(db_session, name="Acme Roofing", city="austin", source_primary="google_search")
        survivors = deduplicate_companies([a, b])
        assert len(survivors) == 1

    def test_different_companies_are_not_merged(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", city="Austin", source_primary="google_places")
        b = _make_company(db_session, name="Bluepeak HVAC", domain="bluepeakhvac.com", city="Dallas", source_primary="google_places")
        survivors = deduplicate_companies([a, b])
        assert len(survivors) == 2

    def test_same_name_different_city_not_merged(self, db_session):
        # Two unrelated businesses can share a generic name in different
        # towns -- name alone is not a strong enough signal without city.
        a = _make_company(db_session, name="Family Dental", city="Austin", source_primary="google_places")
        b = _make_company(db_session, name="Family Dental", city="Denver", source_primary="google_places")
        survivors = deduplicate_companies([a, b])
        assert len(survivors) == 2


class TestMergeBehavior:
    def test_merge_preserves_richer_record_as_primary(self, db_session):
        rich = _make_company(
            db_session, name="Acme Roofing", domain="acmeroofing.com",
            website="https://acmeroofing.com", city="Austin", state="TX",
            industry="roofing", source_primary="google_places",
        )
        sparse = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", source_primary="google_search")
        survivors = deduplicate_companies([rich, sparse])
        assert len(survivors) == 1
        assert survivors[0].id == rich.id
        assert sparse.duplicate_status == f"merged_into:{rich.id}"
        assert sparse.merged_into_id == rich.id

    def test_merge_fills_blank_fields_from_the_other_record(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", website="https://acmeroofing.com", source_primary="google_places")
        b = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", city="Austin", state="TX", source_primary="website")
        survivors = deduplicate_companies([a, b])
        primary = survivors[0]
        assert primary.city == "Austin"
        assert primary.state == "TX"
        assert primary.website == "https://acmeroofing.com"

    def test_merge_tracks_source_secondary_and_urls(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", source_primary="google_places", all_source_urls=["https://maps.example/acme"])
        b = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", source_primary="website", all_source_urls=["https://acmeroofing.com"])
        survivors = deduplicate_companies([a, b])
        primary = survivors[0]
        assert "website" in primary.source_secondary
        assert "https://maps.example/acme" in primary.all_source_urls
        assert "https://acmeroofing.com" in primary.all_source_urls

    def test_conflicting_phone_is_flagged_not_silently_overwritten(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", phone="+15125550101", source_primary="google_places")
        merge_field_with_evidence(a, "phone", "+15125550101", "google_places")
        b = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", phone="+15125559999", source_primary="website")
        merge_field_with_evidence(b, "phone", "+15125559999", "website")

        survivors = deduplicate_companies([a, b])
        primary = survivors[0]
        assert primary.contact_conflict is True
        assert "phone" in primary.conflicting_fields
        assert "+15125559999" in primary.alternate_phones

    def test_source_records_reassigned_to_surviving_company(self, db_session):
        from app.models.models import Source
        source = Source(name="website", type="own_site_scrape")
        db_session.add(source)
        db_session.flush()

        a = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", source_primary="google_places")
        b = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", source_primary="website")
        db_session.add(SourceRecord(company_id=b.id, source_id=source.id, source_url="https://acmeroofing.com", raw_data={}))
        db_session.flush()

        survivors = deduplicate_companies([a, b])
        primary = survivors[0]
        db_session.flush()
        all_urls = [sr.source_url for sr in primary.source_records]
        assert "https://acmeroofing.com" in all_urls

    def test_no_duplicates_returns_all_companies_unchanged(self, db_session):
        a = _make_company(db_session, name="Acme Roofing", domain="acmeroofing.com", source_primary="google_places")
        b = _make_company(db_session, name="Totally Different Co", domain="different.com", source_primary="google_places")
        survivors = deduplicate_companies([a, b])
        assert len(survivors) == 2
        assert {c.duplicate_status for c in survivors} == {"unique"}
