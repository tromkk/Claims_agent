"""Central configuration: all tunables live here, overridable via .env / environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM providers
    groq_api_key: str | None = None
    openai_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    openai_model: str = "gpt-4o-mini"
    temperature: float = 0.1
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 2.0

    # Agent behaviour
    max_agent_iterations: int = 8
    use_legacy_react_agent: bool = False
    # Extracted fields below this confidence are surfaced for user confirmation
    confidence_confirm_threshold: float = 0.7

    # Business thresholds
    high_value_threshold: float = 10_000.0
    near_limit_ratio: float = 0.9
    velocity_window_days: int = 180
    velocity_claim_count: int = 3
    new_policy_window_days: int = 30

    # Data
    database_url: str = "sqlite:///data/claims.db"

    # Document parsing
    ocr_min_chars: int = 100
    max_document_chars: int = 6000


@lru_cache
def get_settings() -> Settings:
    return Settings()
