"""Application configuration.

All values come from environment variables at process start. The settings
object is constructed once and shared. There is no per-request config
reload.

The application must start in one of three ``RUNTIME_ENVIRONMENT`` values
(``local``, ``staging``, ``production``). Production enforces stricter
defaults that the auth layer refuses to bypass.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeEnvironment(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Quorum-AI"
    runtime_environment: RuntimeEnvironment = RuntimeEnvironment.LOCAL

    # --- Operator-only provider configuration -------------------------
    # The OpenRouter key is owned by the operator; it is never exposed in
    # API responses, never written to logs, and never sent to the client.
    # Live execution is opt-in: setting OPENROUTER_LIVE_EXECUTION_ENABLED=true
    # alone is not enough — the key must also be present at process start.
    openrouter_api_key: str = Field(default="", repr=False)
    openrouter_live_execution_enabled: bool = False
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str = "https://quorum.example.test"
    openrouter_app_title: str = "Quorum AI"
    openrouter_timeout_seconds: float = 8.0

    # --- Auth configuration ---------------------------------------------
    # Cookie security: in production we require Secure cookies. The auth
    # layer refuses to start otherwise.
    session_cookie_secure: bool = False
    # Legacy X-Account-Id header is the path the existing test fixture
    # uses. It is *only* available when this flag is true AND the runtime
    # environment is not "production". The auth layer enforces both
    # conditions; setting the flag in production is a startup error.
    account_legacy_header_enabled: bool = True

    # --- Pipeline tuning ------------------------------------------------
    # Synthetic per-stage delay used by the test suite to make state
    # transitions observable. Production may set this to zero.
    stage_delay_ms: int = 5

    # --- Cost guardrails ------------------------------------------------
    soft_threshold_usd: float = 0.15
    hard_limit_usd: float = 0.25

    # --- Cost estimation -------------------------------------------------
    # Output tokens dominate real LLM bills. The estimate before this
    # multiplier only counted input tokens, which produced a 22×
    # under-estimate vs. the actual provider charge on the live demo.
    # The multiplier is the expected output-to-input token ratio for
    # the average model answer; 3.0 is a conservative industry
    # rule-of-thumb. Operators can tune this per deployment via the
    # COST_OUTPUT_TOKEN_MULTIPLIER env var.
    cost_output_token_multiplier: float = 3.0

    # --- LLM-driven debate + synthesis ----------------------------------
    # Both stages now call a live model. Defaults: Haiku 4.5 for the
    # debate rounds (cheap, fast, good at critique) and gpt-4o-mini for
    # synthesis (cheap, reliable, structured-output friendly).
    # Operators can override via DEBATE_MODEL_ID and SYNTHESIS_MODEL_ID.
    debate_model_id: str = "anthropic/claude-haiku-4.5"
    synthesis_model_id: str = "openai/gpt-4o-mini"

    # --- Catalog fetcher -------------------------------------------------
    # The  model catalog is fetched from a public, unauthenticated
    # endpoint and cached in process memory. Six hours is the
    # default refresh window: the catalog rarely changes, but a fresh
    # pick within the same day means new model releases show up
    # without an app restart. The fetch timeout is short on purpose;
    # if  is slow or unreachable we want to fail fast and fall
    # back to the static catalog.
    catalog_cache_ttl_seconds: float = 21600.0  # 6h
    catalog_fetch_timeout_seconds: float = 4.0

    # --- Logging --------------------------------------------------------
    log_level: str = "INFO"


settings = Settings()


def validate_production_environment() -> None:
    """Refuse to start in a misconfigured production environment."""
    if settings.runtime_environment is not RuntimeEnvironment.PRODUCTION:
        return
    if not settings.session_cookie_secure:
        raise RuntimeError(
            "Refusing to start: runtime_environment=production requires SESSION_COOKIE_SECURE=true."
        )
    if settings.account_legacy_header_enabled:
        raise RuntimeError(
            "Refusing to start: runtime_environment=production requires "
            "ACCOUNT_LEGACY_HEADER_ENABLED=false."
        )
