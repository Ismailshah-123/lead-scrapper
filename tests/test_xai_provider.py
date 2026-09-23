from unittest.mock import patch, MagicMock

from app.coldcall.llm_provider import XAIProvider
from app.core import config as config_module


def test_xai_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_MODEL", "grok-4.7")
    config_module.reset_config_cache()
    assert XAIProvider().polish("prompt", "fallback") == "fallback"


def test_xai_parses_chat_completion(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "fake-key")
    monkeypatch.setenv("XAI_MODEL", "grok-4.7")
    config_module.reset_config_cache()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"choices": [{"message": {"content": "polished"}}]}
    response.raise_for_status.return_value = None
    with patch("requests.post", return_value=response) as post:
        assert XAIProvider().polish("prompt", "fallback") == "polished"
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-key"
    config_module.reset_config_cache()
