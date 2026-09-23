"""
LLM provider abstraction — used only to *polish the phrasing* of a
cold-call brief that's already been fully assembled from verified facts
(see brief.py). No provider here is ever the source of a fact; each
polish prompt explicitly forbids adding anything not already given, and
every provider falls back to the unpolished template text on any error,
so a flaky local Ollama server or a missing API key never breaks the
pipeline (spec: "AI must NOT be used to invent missing facts").

LLM_PROVIDER in .env selects one of: template (default, no dependencies),
ollama (local server), xai (xAI/Grok API).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from app.core.config import get_secrets
from app.core.logging_config import get_logger

logger = get_logger("coldcall.llm_provider")


class LLMProvider(ABC):
    @abstractmethod
    def polish(self, prompt: str, fallback_text: str) -> str:
        ...


class TemplateProvider(LLMProvider):
    """The default. Returns the fallback (already-assembled template
    text) untouched — this provider does no rewriting at all, which is
    exactly right for a zero-dependency, zero-network default."""

    def polish(self, prompt: str, fallback_text: str) -> str:
        return fallback_text


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        secrets = get_secrets()
        self.host = secrets.ollama_host.rstrip("/")
        self.model = secrets.ollama_model

    def polish(self, prompt: str, fallback_text: str) -> str:
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=30,
            )
            response.raise_for_status()
            text = (response.json().get("response") or "").strip()
            return text or fallback_text
        except requests.RequestException as exc:
            logger.warning("Ollama polish failed (%s); using unpolished template text.", exc)
            return fallback_text


class XAIProvider(LLMProvider):
    """xAI/Grok provider using xAI's OpenAI-compatible REST API.

    This provider only rewrites the already-assembled cold-call brief.
    It never supplies facts to the pipeline and falls back to the original
    text if the API is unavailable or misconfigured.
    """

    def __init__(self) -> None:
        secrets = get_secrets()
        self.api_key = secrets.xai_api_key
        self.model = secrets.xai_model

    def polish(self, prompt: str, fallback_text: str) -> str:
        if not self.api_key:
            logger.warning("LLM_PROVIDER=xai but XAI_API_KEY is not set; using unpolished template text.")
            return fallback_text
        try:
            response = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Rewrite only the supplied cold-call brief for clarity and natural flow. Do not add, remove, infer, or alter any fact, name, number, date, URL, or claim.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 400,
                    "temperature": 0.2,
                    "stream": False,
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            text = (
                ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                or ""
            ).strip()
            return text or fallback_text
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            logger.warning("xAI/Grok polish failed (%s); using unpolished template text.", exc)
            return fallback_text


def get_llm_provider() -> LLMProvider:
    provider_name = get_secrets().llm_provider.strip().lower()
    if provider_name == "ollama":
        return OllamaProvider()
    if provider_name == "xai":
        return XAIProvider()
    return TemplateProvider()
