"""LLM provider selection, retry with backoff, and provider fallback."""

from __future__ import annotations

import logging
import time

from langchain_core.language_models.chat_models import BaseChatModel

from config import get_settings

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    """Raised when no LLM provider is configured."""


NO_KEY_MESSAGE = (
    "No LLM API key configured. Set `GROQ_API_KEY` (free at console.groq.com) "
    "or `OPENAI_API_KEY` as an environment variable or Streamlit secret."
)


def get_chat_model() -> BaseChatModel:
    """Primary chat model: Groq if configured, else OpenAI."""
    s = get_settings()
    if s.groq_api_key:
        from langchain_groq import ChatGroq

        return ChatGroq(model=s.groq_model, temperature=s.temperature, api_key=s.groq_api_key)
    if s.openai_api_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=s.openai_model, temperature=s.temperature, api_key=s.openai_api_key)
    raise LLMConfigError(NO_KEY_MESSAGE)


def get_fallback_model() -> BaseChatModel | None:
    """Secondary model used when the primary keeps failing (Groq → OpenAI)."""
    s = get_settings()
    if s.groq_api_key and s.openai_api_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=s.openai_model, temperature=s.temperature, api_key=s.openai_api_key)
    return None


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in ("rate limit", "429", "500", "502", "503", "timeout", "connection", "overloaded")
    )


def invoke_with_retry(runnable, payload):
    """Invoke with exponential backoff on transient errors."""
    s = get_settings()
    last_exc: Exception | None = None
    for attempt in range(s.llm_max_retries):
        try:
            return runnable.invoke(payload)
        except Exception as exc:  # noqa: BLE001 - provider SDKs raise many types
            last_exc = exc
            if not _is_retryable(exc) or attempt == s.llm_max_retries - 1:
                raise
            delay = s.llm_retry_base_delay * (2**attempt)
            logger.warning("LLM call failed (%s); retrying in %.1fs", exc, delay)
            time.sleep(delay)
    raise last_exc  # pragma: no cover - unreachable
