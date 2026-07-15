"""Application configuration.

All values come from environment variables at process start. The settings
object is constructed once and shared. There is no per-request config
reload.

The application must start in one of three ``RUNTIME_ENVIRONMENT`` values
(``local``, ``staging``, ``production``). Production enforces stricter
defaults that the auth layer refuses to bypass.
"""

from __future__ import annotations

import os
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

    # --- Interactive API docs exposure ----------------------------------
    # The Swagger UI (/docs), ReDoc (/redoc), and the raw schema route
    # (/openapi.json) are convenient in development but are surface area we
    # do not want live by default in production. ``None`` (the default)
    # means "derive from the environment": docs are exposed everywhere
    # EXCEPT production. Set ``EXPOSE_API_DOCS=true|false`` to force it on
    # or off regardless of environment. /health and /ready are never gated.
    expose_api_docs: bool | None = None

    @property
    def api_docs_enabled(self) -> bool:
        """Whether the interactive docs + schema route should be served."""
        if self.expose_api_docs is not None:
            return self.expose_api_docs
        return self.runtime_environment is not RuntimeEnvironment.PRODUCTION

    # --- Operator-only provider configuration -------------------------
    # The OpenRouter key is owned by the operator; it is never exposed in
    # API responses, never written to logs, and never sent to the client.
    # Live execution is opt-in: setting OPENROUTER_LIVE_EXECUTION_ENABLED=true
    # alone is not enough — the key must also be present at process start.
    openrouter_api_key: str = Field(default="", repr=False)
    openrouter_live_execution_enabled: bool = False
    openrouter_api_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str = "http://localhost:18084"
    openrouter_app_title: str = "Quorum AI"
    openrouter_timeout_seconds: float = 8.0

    # --- Auth configuration ---------------------------------------------
    # Cookie security: in production we require Secure cookies. The auth
    # layer refuses to start otherwise.
    session_cookie_secure: bool = False
    # Legacy X-Account-Id header is the path the existing test fixture
    # uses. It is *only* available when this flag is true AND the runtime
    # environment is "local". The auth layer enforces both conditions;
    # setting the flag in non-local environments is a startup error.
    # Defaults to False for security; explicitly enable only in local dev.
    account_legacy_header_enabled: bool = False

    # --- Pipeline tuning ------------------------------------------------
    # Synthetic per-stage delay used by the test suite to make state
    # transitions observable. Production may set this to zero.
    stage_delay_ms: int = 5

    # --- Cost guardrails ------------------------------------------------
    soft_threshold_usd: float = 0.15
    hard_limit_usd: float = 0.25

    # --- Cost estimation (issue #16: realistic per-call token model) -----
    # The pre-run estimate is a PURE LOCAL calculation — it makes no API
    # call and spends no tokens. It prices a realistic token model per
    # billed call (4 initial answers + 2 debate rounds + 1 synthesis)
    # against the cached catalog rates. The old model priced only
    # ``len(query_text)/4`` input tokens × an output multiplier, which
    # ignored the fixed system-prompt overhead, the web-search context
    # the ``:online`` suffix injects, and the debate/synthesis calls —
    # producing a ~7.7× UNDER-estimate on a real live run (est $0.0016 vs
    # measured $0.0123). These constants model the tokens each call
    # actually carries; all are tunable per deployment via the matching
    # env vars. They are deliberately calibrated slightly conservative so
    # the estimate rarely falls BELOW the measured actual (the cost
    # guardrail keys off the estimate and must fail safe).
    #
    # Grounding (real live run d7785cd8, 4 default models, all searching):
    # observed prompt tokens/model 2277–2560 (≈ system + web-search +
    # query) and output tokens/model 465–1152.
    #: Fixed system-prompt overhead carried by every billed call (the
    #: quorum / debate / synthesis instructions), in tokens.
    cost_system_prompt_tokens: int = 350
    #: Prompt tokens the ``:online`` web-search suffix injects into each
    #: SEARCHING initial-answer call (retrieved passages). Applied per
    #: slot only when that slot has search enabled; a search-disabled
    #: slot (the cheaper, training-data-only path) omits it.
    cost_web_search_context_tokens: int = 2000
    #: Output-token floor for a single initial answer.
    cost_initial_output_tokens: int = 700
    #: How much each initial answer lengthens per token of query (longer,
    #: richer questions elicit longer answers). Output tokens for an
    #: initial answer = ``cost_initial_output_tokens + this × query_tokens``.
    cost_output_tokens_per_query_token: float = 0.5
    #: Output-token floor for one debate round (the typical, for the point
    #: estimate). The debate model reads the four initial answers (a bounded
    #: context) and emits a critique.
    cost_debate_output_tokens: int = 400
    #: Enforced per-round debate output CAP, used by the fail-safe
    #: ``max_cost_usd`` bound so it is a true ceiling on the debate stage too
    #: (the point estimate keeps the lower typical floor above). MUST stay in
    #: sync with ``debate.DEBATE_ROUND_MAX_TOKENS`` — the value the live debate
    #: call actually enforces.
    cost_debate_output_tokens_cap: int = 700
    #: Output-token floor for one synthesis section call (the reconciled
    #: answer). Synthesis fans out into up to ``cost_synthesis_sections``
    #: independent live calls, each re-sending the full context.
    cost_synthesis_output_tokens: int = 800

    #: Number of independent synthesis section calls the pipeline can make
    #: (``synthesis.SYNTHESIS_SECTION_MAX_TOKENS`` caps each). The realistic
    #: point estimate models synthesis as a SINGLE call (the measured typical
    #: is ~one section's worth); the fail-safe ``max_cost_usd`` bound prices
    #: all ``cost_synthesis_sections`` so it stays a true worst-case ceiling.
    cost_synthesis_sections: int = 5

    #: Hard per-call output cap for the four initial answers, enforced as
    #: ``max_tokens`` on the live call (the debate and synthesis calls are
    #: already capped at 700 / 800). Without it, initial-answer output is
    #: unbounded, so a verbose prompt on an expensive model mix can cost far
    #: more than any pre-run estimate — defeating the cost guardrail. 2000 is
    #: generous (~2× the largest answer observed in the live validation run,
    #: 1152 tokens), so real answers are essentially never truncated, while a
    #: pathological "write a 20,000-word report" request stays bounded. The
    #: cost guardrail's fail-safe upper bound (``max_cost_usd``) prices the
    #: initial-answer output at exactly this cap, so the bound is a true
    #: ceiling on real cost.
    initial_answer_max_tokens: int = 2000

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

    # --- Observability ---------------------------------------------------
    # Sentry DSN. Empty when Sentry is not configured; the Sentry init
    # block in main.py is gated on a non-empty value so local dev and
    # tests run unaffected. Set via SENTRY_DSN in .env or the deploy
    # environment.
    sentry_dsn: str = ""


settings = Settings()


def validate_production_environment() -> None:
    """Refuse to start in a misconfigured production environment."""
    if settings.runtime_environment is RuntimeEnvironment.LOCAL:
        return
    if not settings.session_cookie_secure:
        raise RuntimeError(
            "Refusing to start: runtime_environment="
            + settings.runtime_environment.value
            + " requires SESSION_COOKIE_SECURE=true."
        )
    if settings.account_legacy_header_enabled:
        raise RuntimeError(
            "Refusing to start: runtime_environment="
            + settings.runtime_environment.value
            + " requires ACCOUNT_LEGACY_HEADER_ENABLED=false. "
            "The X-Account-Id header is not part of the production auth contract."
        )
    # SEC-H2: enforce QUORUM_TOKEN_SECRET in non-local environments.
    # An auto-generated per-process secret breaks multi-instance
    # deployments (token minted by instance A cannot be verified by
    # instance B) and invalidates all outstanding tokens on every
    # restart. Warning alone is insufficient: a misconfigured deploy
    # should fail loudly at startup, not silently invalidate tokens
    # later.
    quorum_token_secret = os.environ.get("QUORUM_TOKEN_SECRET", "")
    if not quorum_token_secret:
        raise RuntimeError(
            "Refusing to start: runtime_environment="
            + settings.runtime_environment.value
            + " requires QUORUM_TOKEN_SECRET to be set to a stable, "
            "non-empty value. Generate one with: openssl rand -hex 32"
        )
