from unittest.mock import MagicMock, patch

from app.connectors.exa import ExaConnector
from app.core import config as config_module


def test_is_available_false_without_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    config_module.reset_config_cache()
    assert ExaConnector().is_available() is False


def test_discover_parses_results(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "fake-key-for-test")
    config_module.reset_config_cache()

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": [
            {
                "title": "Acme Roofing",
                "url": "https://acmeroofing.com",
                "text": "Residential roofing in Austin.",
                "id": "abc123",
            }
        ]
    }

    with patch("requests.post", return_value=fake_response):
        leads = ExaConnector().discover(
            "roofing companies", location="Austin, TX"
        )

    assert len(leads) == 1
    assert leads[0].company_name == "Acme Roofing"
    assert leads[0].website == "https://acmeroofing.com"
    config_module.reset_config_cache()
