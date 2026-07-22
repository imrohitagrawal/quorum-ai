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
from typing import ClassVar

from pydantic import Field, field_validator
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
    # The Swagger UI (/docs) and the raw schema route (/openapi.json) are
    # convenient in development but are surface area we do not want live by
    # default in any DEPLOYED environment. ``None``
    # (the default) means "derive from the environment": docs are exposed
    # ONLY in local dev, and off-by-default in both staging AND production
    # so an internet-reachable box never serves the unauthenticated schema
    # unless an operator explicitly opts in. Set ``EXPOSE_API_DOCS=true``
    # to force them on (e.g. a locked-down staging box behind a VPN), or
    # ``EXPOSE_API_DOCS=false`` to force them off. /health and /ready are
    # never gated.
    expose_api_docs: bool | None = None

    @field_validator("expose_api_docs", mode="before")
    @classmethod
    def _blank_expose_api_docs_is_unset(cls, value: object) -> object:
        """Treat a blank ``EXPOSE_API_DOCS`` as unset (derive from environment).

        A common operator footgun is leaving ``EXPOSE_API_DOCS=`` (empty) in a
        ``.env`` or deploy config. Pydantic's bool parser rejects ``""`` with a
        ValidationError, which would crash the app at startup. An empty/whitespace
        value should mean "I didn't set this" — i.e. ``None`` → derive the default
        from the runtime environment — not a hard boot failure.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def api_docs_enabled(self) -> bool:
        """Whether the interactive docs + schema route should be served."""
        if self.expose_api_docs is not None:
            return self.expose_api_docs
        return self.runtime_environment is RuntimeEnvironment.LOCAL

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

    # --- Real web-search fallback (Tavily) ------------------------------
    # The fallback source path replaces a fabricated ``example.test`` stub
    # with a real web search when — and only when — ``TAVILY_API_KEY`` is
    # set at process start. Absent (the default), the fallback keeps the
    # deterministic local-simulation stub so CI stays hermetic, free, and
    # needs no live key to merge; the key is never logged or returned to
    # the client (issues #31 / #32). Tavily is a paid API — leaving the key
    # unset costs nothing and changes no behaviour.
    tavily_api_key: str = Field(default="", repr=False)
    tavily_api_base_url: str = "https://api.tavily.com"
    #: Number of web results requested from Tavily per fallback search. The
    #: fallback attaches these as ``is_fallback=True`` sources (they do not
    #: count toward the model's own citation-coverage metric).
    tavily_max_results: int = 5
    tavily_timeout_seconds: float = 8.0

    # --- Layer-B evaluation judge (FR-015, PR-EVAL-JUDGE-v1) -------------
    # The optional LLM-as-judge in ``evaluation.py`` is gated SOLELY on the
    # presence of ``QUORUM_EVAL_JUDGE_API_KEY``, exactly the way the Tavily
    # fallback above is gated on ``TAVILY_API_KEY``. Absent (the default),
    # no judge call is ever made: CI stays hermetic and free, and the
    # deterministic Layer-A TrustScore is byte-identical with the judge on
    # or off (NFR-012). The key is never logged or returned to a client.
    # The judge is advisory and UNCALIBRATED until the R2-S4 golden set
    # exists; enabling it in any environment is an explicit human decision.
    quorum_eval_judge_api_key: str = Field(default="", repr=False)
    #: Pinned judge model id. Verdicts from different models are not
    #: comparable, so the id is configuration rather than a default: with
    #: no id pinned the judge does not run even when a key is present.
    quorum_eval_judge_model_id: str = ""
    #: Token cap for a judge response. The output contract is a small
    #: strict-JSON object; a response longer than this is malformed by
    #: definition and yields no verdict.
    quorum_eval_judge_max_tokens: int = 512

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

    # --- Session rate-limit override (Stage B / D0) --------------------
    # The ``GET /v1/session`` endpoint is per-IP token-bucket limited to
    # ``_InMemoryIpRateLimiter.CAPACITY`` (30/min) in production. Every
    # browser spec's ``boot()`` GETs it once, so a ``--repeat-each`` e2e
    # run exhausts the bucket and measures the limiter instead of the
    # product (the long-standing parity/axe flake). This override raises
    # the per-IP capacity *only in the hermetic test lanes*.
    #
    # SECURITY: this is a rate-limit control. It is ``None`` (unset) by
    # default, applied ONLY when ``runtime_environment is LOCAL``, and
    # ``validate_production_environment()`` REFUSES TO START if it is set
    # in any non-LOCAL environment. The value is bounded: ``0``/negative
    # (which would lock the app out — a zero bucket never opens) and an
    # absurd upper bound are rejected, so it can never silently disable
    # the limiter or become an unbounded ``session_repository`` growth
    # sink. Env var: ``SESSION_RATE_LIMIT_PER_MINUTE``.
    session_rate_limit_per_minute: int | None = None

    #: Inclusive upper bound on the session-rate override. Sized to admit
    #: the measured e2e need (parity ≈ 53 boots/run × 10 repeats ≈ 530)
    #: with headroom, while still bounding in-memory session growth in the
    #: lanes that mint the most sessions. Not configurable.
    SESSION_RATE_LIMIT_MAX: ClassVar[int] = 10_000

    @field_validator("session_rate_limit_per_minute", mode="before")
    @classmethod
    def _blank_session_rate_is_unset(cls, value: object) -> object:
        """Treat a blank ``SESSION_RATE_LIMIT_PER_MINUTE`` as unset (``None``).

        Same footgun as ``EXPOSE_API_DOCS``: a stray empty value in a deploy
        config should mean "I didn't set this", not crash the int parser.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator("session_rate_limit_per_minute", mode="after")
    @classmethod
    def _session_rate_within_bounds(cls, value: int | None) -> int | None:
        """Reject a zero/negative/absurd override.

        ``0`` must never mean "unlimited": a zero-capacity bucket locks the
        endpoint out entirely rather than opening it. An unbounded value
        would remove the only cap on in-memory ``session_repository`` growth
        in the lanes that mint the most sessions.
        """
        if value is None:
            return None
        if value < 1 or value > cls.SESSION_RATE_LIMIT_MAX:
            raise ValueError(
                "SESSION_RATE_LIMIT_PER_MINUTE must be between 1 and "
                f"{cls.SESSION_RATE_LIMIT_MAX} (got {value}); "
                "0 or negative would lock the endpoint out, not open it."
            )
        return value

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
    #: Flat per-request fee OpenRouter's ``:online`` web-search plugin charges
    #: for EACH searching initial-answer call, IN ADDITION to the token costs
    #: above. OpenRouter bills the web plugin at ~$4 per 1,000 results with a
    #: default of 5 results/request → ~$0.02/request. This term is independent
    #: of the model's token price, so it is the ONLY web-search cost a
    #: ``$0``-priced (``:free``) model incurs — without it a searching
    #: :free-model slot is estimated at $0, which under-counts the real spend
    #: and (because the guardrail keys off the estimate) is a fail-safe hole
    #: (issue #18). Applied per slot only when that slot has search enabled;
    #: search-disabled slots omit it. Tunable via ``COST_WEB_SEARCH_REQUEST_FEE_USD``.
    #:
    #: DEFAULT 0.0 — INTENTIONALLY, PERMANENTLY OFF (accepted decision, 2026-07-17;
    #: see AC-037 in docs/12-acceptance-criteria.md and issue #18). The fee is a
    #: real OpenRouter charge (~$4/1,000 results × 5 = ~$0.02/request per their
    #: docs), but we have ACCEPTED not to account for it: the 2026-07-17 measured
    #: live run showed the pre-run estimate already runs ABOVE the actual token
    #: cost (est $0.0199 ≥ measured $0.0149), so the cost guardrail — which keys
    #: off the estimate — stays fail-safe without this term. The plumbing (server
    #: + client, per-slot) is retained ONLY as a dormant repo-tracking hook, not a
    #: pending TODO; it is never surfaced to users (at 0.0 it folds invisibly into
    #: the total estimate, no separate line). Activating it would shift the
    #: CONFIRM/BLOCK bands and is deliberately NOT done. Leave at 0.0.
    cost_web_search_request_fee_usd: float = 0.0
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
    #: (``synthesis.SYNTHESIS_SECTION_MAX_TOKENS`` caps each). The live pipeline
    #: fans synthesis out into this many independent billed calls whenever a key
    #: is configured (``synthesis.produce_final_synthesis`` submits five). BOTH
    #: the displayed point estimate AND the fail-safe ``max_cost_usd`` bound now
    #: price all ``cost_synthesis_sections`` calls — the point estimate at the
    #: typical per-section output floor, the bound at the enforced cap — so the
    #: headline reflects the real fan-out (it previously modelled ONE section,
    #: reading ~17–38% below the actual on cheap-model runs where synthesis
    #: dominates; issue #24, see ``costs._estimate_breakdown``).
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
    if settings.session_rate_limit_per_minute is not None:
        raise RuntimeError(
            "Refusing to start: runtime_environment="
            + settings.runtime_environment.value
            + " requires SESSION_RATE_LIMIT_PER_MINUTE to be unset. "
            "The session rate-limit override is a hermetic-test-lane control "
            "and must never weaken the per-IP limiter in a deployed environment."
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
