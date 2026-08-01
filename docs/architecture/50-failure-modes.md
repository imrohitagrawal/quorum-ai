# Failure Modes — Blast-Radius Map

This document maps every significant failure mode in the Release 1 + Release 2 query workflow. For each mode, it states what **stops** (the user gets no result), what **degrades** (the user gets a partial result with visible missing-step explanation), the detection mechanism, the recovery mechanism, and what a reader must not break when changing the code.

The source of truth for failure-mode behaviour is `docs/20-architecture.md` Failure Modes table, `docs/21-domain-model.md` QueryRun State Machine, and `docs/40-threat-model.md` STRIDE threats T-001 through T-013. This document expands each into a blast-radius statement.

---

## Provider Failures

### Primary provider 429 (rate limit)

- What STOPS. Nothing stops. The run never entered `accepted` because the provider returned 429 on the initial call; that slot is recorded as `FAILED` with a provider notice. If all four slots hit 429, the run degrades to `PARTIAL` with no completed initial answers.
- What DEGRADES. The specific slot that hit 429. The other three slots may complete normally. The debate and synthesis stages run over the available completed answers. The served result includes a `provider_failure_notices` entry for the 429 slot.
- Detection mechanism. `providers.py` maps HTTP 429 to a `FAILED` `InitialAnswerStatus` with `error_code="RATE_LIMITED"` and a user-safe `provider_notice`. The `_produce_one_initial_answer` worker catches the provider failure and stamps the slot; the orchestrator continues with the other futures.
- Recovery mechanism. No automatic retry for 429 in the initial-answer path (the retry policy is exhaustion-based, not delay-based). The user sees the degraded result and can re-run. The fallback search path (Tavily) is not triggered by a 429 on the model call — it is triggered when the `:online` search suffix returns no usable sources.
- What you must not break. The `provider_notice` text must remain user-safe (no raw HTTP body, no key fragments). The `InitialAnswerStatus.FAILED` path must not be silently upgraded to `COMPLETED` — a slot that failed on the `OPENROUTER_SEARCH` path must not be counted in `live_count` (RB-5 / D3).

### Primary provider 500 (server error)

- What STOPS. Nothing stops. A 500 on one slot is treated identically to a 429: the slot is `FAILED`, the other slots continue, and the run degrades gracefully. A 500 during the debate or synthesis stage causes that section to fall back to the templated text (synthesis) or the templated critique (debate), with a `provider_notice`.
- What DEGRADES. The specific slot or section that hit 500. The `SynthesisResult.failed_steps` list records which section raised, so the UI can show "Consensus section used a local heuristic because the live synthesis call failed."
- Detection mechanism. `providers.py` maps HTTP 500 to `FAILED`. The synthesis `_safe_section_result` wrapper catches exceptions in section-builder futures and returns the templated fallback text plus the failed-step label.
- Recovery mechanism. No automatic retry for 500 in the initial-answer path. The user re-runs. The debate and synthesis stages each have their own `_call_*_model` helper that returns `None` on any failure, so the templated path serves without raising.
- What you must not break. The `_safe_section_result` wrapper must not let a section exception propagate past the orchestrator — one bad section must not abort the whole synthesis. The `failed_steps` list must be populated so the partial-failure notice is honest.

### Primary provider timeout

- What STOPS. Nothing stops. A per-call timeout (default 8 s, configured by `openrouter_timeout_seconds`) on one slot causes that slot to fail; the run-level deadline (180 s, configured by `quorum_run_deadline_seconds`) is checked at each stage boundary and on every `future.result()` call. A breached run-level deadline degrades the run to `TIMED_OUT` with all completed stages preserved.
- What DEGRADES. The timed-out slot or stage. A run-level deadline breach during `initial_answers` marks the remaining stages (`debate_round_1`, `debate_round_2`, `synthesis`) as `SKIPPED`. A breach during `synthesis` marks only `synthesis` as `SKIPPED`; the debate rounds are already complete.
- Detection mechanism. The `_budget_remaining()` closure inside `_execute_query_run` computes `deadline_seconds - elapsed_wall_clock`. The `future.result(timeout=max(_budget_remaining(), 0.0))` call raises `FuturesTimeoutError` when the budget expires. The `_degrade_for_deadline` helper transitions the run to `TIMED_OUT` and stamps the failed/missing steps.
- Recovery mechanism. The run serves the partial result with an honest `timed_out` status and a `partial_failure_notice`. The user re-runs. The `_degrade_run_for_deadline` transition is atomic (validated under the repository lock); a cancel that lands between entry and write makes the flip raise instead of silently overwriting.
- What you must not break. The `_budget_remaining` check must use `perf_counter`, not `time.time` — `perf_counter` is monotonic and not affected by wall-clock changes. The `TIMED_OUT` transition must go through `transition()` (not `update_status`) so the `ALLOWED_TRANSITIONS` guard prevents a race with a concurrent `COMPLETED` write.

### Tavily fallback unavailable

- What STOPS. Nothing stops. If Tavily is unreachable (no key, network error, or the call itself 500s), the `:online` search path on the affected slot falls back to `LOCAL_SIMULATION` with a `provider_notice` explaining the fallback. The slot's `provider_path` is `FALLBACK_SEARCH`; its sources carry `is_fallback=True`.
- What DEGRADES. The source-backed answering for the affected slot. The slot still returns an answer, but its citations are stubbed (`LOCAL_SIMULATION_URL_PREFIX` under `example.test`). The `live_count` is decremented by one, and the UI renders a partial demo banner when `live_count < 4`.
- Detection mechanism. `providers.py` catches `URLError`, `HTTPError`, and `TimeoutError` on the Tavily call. The `_tavily_enabled` property gates the call on `TAVILY_API_KEY`; absent the key, the fallback path is never attempted.
- Recovery mechanism. No automatic retry. The user re-runs. The `provider_attempt_order` on the `InitialModelAnswer` records the attempt sequence (`["openrouter_search", "fallback_search"]`), so the audit trail is complete.
- What you must not break. The `is_fallback` flag must remain set on Tavily-sourced sources — since issues #31/#32, the flag means "not the model's own `:online` citation", not "fabricated", and the citation-coverage and grounding logic key on different predicates (`is_fallback` for coverage, host key for grounding).

## Cost

### Cost threshold hit (user's confirmed spend cap)

- What STOPS. The query is blocked at the cost gate with HTTP 402 `COST_LIMIT_EXCEEDED` (hard limit, `> USD 0.25`) or HTTP 402 `COST_CONFIRMATION_REQUIRED` (soft threshold, `> USD 0.15`). No `QueryRun` is created, no provider calls are made.
- What DEGRADES. Nothing degrades because the run never started. The cumulative-spend guard and the daily cap (`DAILY_CAP_USD`) can also block a run even when the per-call estimate is in the `ALLOW` band — these are defense-in-depth against trickle-spend.
- Detection mechanism. `costs.py` `_threshold_for` evaluates the fail-safe `max_cost_usd` (not the point estimate) against `SOFT_THRESHOLD_USD` and `HARD_LIMIT_USD`. The cumulative guard sums accepted estimates from the in-memory event ring; the daily cap reads from the durable SQLite feedback store. A `BLOCK` event is surfaced to Sentry as a warning.
- Recovery mechanism. The user must re-submit with a lower-cost configuration (fewer searching slots, cheaper models). The confirmation token (for `REQUIRE_CONFIRMATION`) is bound to the estimate and expires after `CONFIRMATION_TOKEN_TTL` (5 minutes); a stale token must be re-requested.
- What you must not break. The guardrail must key off `max_cost_usd` (the fail-safe bound), not `estimated_cost_usd` (the point estimate). The bound is always ≥ the estimate, so the rail can only over-protect. If the estimate logic ever produces a bound below the estimate, the rail would wave through a run that then bills past the limit.

### Cost estimation drift (estimate vs actual diverges)

- What STOPS. Nothing stops. A drifted estimate does not block a running run; it weakens the cost gate's honesty over time.
- What DEGRADES. The `cost_estimate_accuracy` log line (emitted at run completion) records the ratio `estimated / measured`. The `cost_source` field on the result response (`"estimated"` vs `"measured"`) tells the UI whether the receipt reflects a real reconciliation or the pre-run estimate standing in for measured usage.
- Detection mechanism. `query_runs._log_estimate_accuracy` emits a structured log line with the ratio whenever the run's actual cost is genuinely `measured` (every contributing live call reported usage). The `cost_source` field on `QueryRunResultResponse` is `"estimated"` by default and becomes `"measured"` only when the strict honesty gate in `_actual_cost` passes.
- Recovery mechanism. The estimate is calibrated against the per-call token model in `costs.py`. Issue #16 established that the old synthetic per-character model under-estimated by ~7.7× on a real live run. The new model prices every billed call (4 initial + 2 debate + `cost_synthesis_sections` synthesis) against the cached catalog rates. If drift reappears, the `cost_*_tokens` knobs in `config.py` are the recalibration surface.
- What you must not break. The `_actual_cost` strict gate must not be loosened. If any contributing live call omitted its usage, the run stays `"estimated"` — fabricating a measured figure from partial data is worse than honestly standing on the estimate. The `COST_DISPLAY_QUANTUM` (4 dp) ensures the UI never shows IEEE-754 noise.

## Evaluation

### Layer B judge unavailable or returns malformed JSON

- What STOPS. Nothing stops. The evaluation is best-effort and must never alter the run's terminal state (FR-015). If the judge key is unset, the call is never attempted (zero I/O, zero cost). If the key is set but the provider call fails or returns malformed JSON, the judge returns `None` and `support_verified` stays `False`.
- What DEGRADES. The `TrustScore` numeric score is suppressed (`score IS None`, band is `"unverified"`). The `evaluation` field on the result response still carries the deterministic Layer-A signals, the `faithfulness_label`, and the `hallucination_risk` — only the judge verdict is absent. The served trust surface renders the indeterminate/unverified state.
- Detection mechanism. `evaluation.py` `parse_judge_verdict` attempts `json.loads` then Pydantic strict validation (`strict=True, extra="forbid"`). Any deviation (prose wrapper, missing keys, extra keys, type mismatch) yields `None`. The `_MemoisedRunJudge` wraps the real `EvalJudgeService` and memoises the first outcome; a failed call is memoised as `None` so subsequent polls never retry the spend.
- Recovery mechanism. No automatic retry. The judge verdict is per-run and first-outcome-wins. The in-flight future is shared among concurrent polls (owner thread makes the call; non-owner threads wait up to `_JUDGE_INFLIGHT_WAIT_SECONDS`); on timeout, non-owner threads re-check the memo once and serve suppressed if the memo is still empty.
- What you must not break. The judge must never enter the `TrustScore` composite arithmetic (`compute_composite`). The `StubEvalJudge` deliberately sets `verifies_support = False`, which is what makes judge-OFF and stub-ON byte-identical. If the judge's `verifies_support` property were ever `True` for the stub, the numeric score would silently unlock in CI.

## Infrastructure

### SQLite corruption or disk full

- What STOPS. Nothing stops immediately. The SQLite stores (`feedback_store`, `run_history_store`) are written to on a best-effort basis: the module-level wrappers (`record_terminal_run`, `_update_run_evaluation`) catch all exceptions and log at debug/warning level. The in-memory query-run repository and the in-memory event recorders continue to function. A full disk or a corrupt WAL file will cause the next `INSERT` to raise; the exception is swallowed at the call site.
- What DEGRADES. Durable persistence of the terminal run history and the feedback audit trail. The in-memory state is unaffected. The user still sees the result response; the operator loses the audit record.
- Detection mechanism. SQLite raises `sqlite3.OperationalError` (disk full) or `sqlite3.DatabaseError` (corruption). The `_persist_terminal_run` and `_persist_run_evaluation` functions wrap the entire body in `try/except Exception` and log the exception type at debug level.
- Recovery mechanism. No automatic recovery. The operator must address the disk condition (clean up the Fly volume, restore from backup — but the product currently has no backup mechanism, documented as a deliberate gap in `docs/80-observability.md`). The in-memory state is consistent regardless of the store state.
- What you must not break. The exception guard must remain broad (`Exception`, not a narrower tuple). A narrower guard would let an unanticipated SQLite exception propagate past `_persist_terminal_run`, which would crash the background thread and leave the run in a non-terminal state.

### Memory pressure (in-memory stores grow unbounded)

- What STOPS. Nothing stops immediately. The in-memory stores (`InMemoryQueryRunRepository`, `InMemoryCostEventRecorder`, `InMemorySynthesisEventRecorder`, `InMemoryDebateEventRecorder`, `InMemoryWarningEventRecorder`) each have a `MAX_EVENTS` cap (512–1024) that evicts old entries when the cap is exceeded. The query-run repository's TTL eviction (`QUERY_RUN_TERMINAL_TTL = 1h`, `QUERY_RUN_ACTIVE_TTL = 30m`) runs on every create/get.
- What DEGRADES. Old audit events and old terminal runs are evicted. The bounded caps mean the operator loses visibility into runs older than the TTL window. The `_judge_verdict_memo` is bounded to 512 entries (LRU); an evicted entry costs one fresh judge call on the next read, never a correctness break.
- Detection mechanism. The eviction logic is deterministic and runs synchronously under the store lock. There is no metric for "how many entries were evicted this cycle" — that would be a useful addition but is not currently emitted.
- Recovery mechanism. No automatic recovery. The operator must restart the process (which clears all in-memory state). The durable SQLite stores are unaffected.
- What you must not break. The `MAX_EVENTS` cap must stay on the append path (after the event is added, before the lock is released). Moving it to a periodic sweep would allow unbounded growth between sweeps. The `_purge_expired_locked` TTL check must run on every `create`/`get`, not on a timer — a quiet process followed by a burst would see unbounded growth if eviction ran on a schedule.

### Rate limiter exhaustion

- What STOPS. A new session request (`GET /v1/session`) from an IP whose token bucket is empty returns HTTP 429 with a `RATE_LIMITED` error. The session is not created. The per-account rate limiter (`_InMemoryAccountRateLimiter`) similarly returns 429 on the estimate, create, warnings, and delete endpoints when the account's bucket is empty.
- What DEGRADES. The affected IP or account cannot create new sessions or submit queries until the bucket refills (30 tokens per minute, refilling continuously). Existing sessions and in-flight runs are unaffected.
- Detection mechanism. `_InMemoryIpRateLimiter.allow` and `_InMemoryAccountRateLimiter.allow` both implement a token-bucket algorithm with stale-bucket eviction (5 minutes at full capacity). The limiter returns `False` when the bucket is empty; the route layer converts that to `HTTPException(429)`.
- Recovery mechanism. Automatic — the bucket refills at `REFILL_PER_MINUTE` tokens per minute. A 5-minute idle period evicts the stale bucket entirely. The `CAPACITY` and `REFILL_PER_MINUTE` can be overridden in `LOCAL` environment via `session_rate_limit_per_minute`; the production validator (`validate_production_environment`) rejects non-`None` overrides in non-LOCAL environments.
- What you must not break. The rate limiter must sit **after** auth and CSRF enforcement — otherwise an attacker could forge headers and burn tokens without authenticating. The `_enforce_account_rate_limit` helper is called after `require_session` and `enforce_csrf` for exactly this reason.

## Run Lifecycle

### Deadline exceeded (180 s hard timeout)

- What STOPS. Nothing stops the run itself; the run degrades to `TIMED_OUT`. The remaining stages are marked `SKIPPED` with the detail "Run exceeded the 180s wall-clock deadline (NFR-004); serving the completed portion." The user receives the partial result with an honest `partial_failure_notice`.
- What DEGRADES. All stages that had not yet started when the deadline breached. Stages that already completed are preserved. A deadline breach during `initial_answers` kills all three downstream stages; a breach during `synthesis` only kills `synthesis` itself.
- Detection mechanism. `_budget_remaining()` is checked at every `future.result()` call in the initial-answer stage and at every stage-boundary transition. The debate stage has its own hard timeout (`DEBATE_HARD_TIMEOUT_MS = 180_000`), which is checked before round 2 starts.
- Recovery mechanism. No automatic retry. The user must re-run. The `_degrade_run_for_deadline` transition is atomic and validated under the repository lock; a concurrent cancel wins the race and the deadline attribution is not applied.
- What you must not break. The deadline must use `perf_counter` (monotonic), not `time.time`. The `TIMED_OUT` transition must go through `transition()` (not `update_status`) so the `ALLOWED_TRANSITIONS` guard rejects races. The `finally` block in `_execute_query_run_safely` must always reach `_persist_terminal_run` so the durable row is written whatever the terminal state.

### Secret/key unavailable

- What STOPS. If `OPENROUTER_API_KEY` is missing while `OPENROUTER_LIVE_EXECUTION_ENABLED=true`, the run fails immediately at the `INITIAL_ANSWERS_RUNNING` stage with `failed_steps=["initial_answers", "debate_round_1", "debate_round_2", "synthesis"]` and `missing_steps` set to the same four stages. The run transitions to `FAILED`. The user receives a `provider_failure_notices` entry: "Live execution is enabled but no server-side key is configured."
- What DEGRADES. Everything degrades because nothing ran. The run is a hard `FAILED`, not a `PARTIAL`.
- Detection mechanism. The check is at the top of `_execute_query_run`, before any provider call is made. It reads `settings.openrouter_api_key` (which is never logged or echoed). The `readiness.py` probe surfaces the same condition on `/ready` as `offline_by_no_key`.
- Recovery mechanism. Operator must set the key and restart. The readiness probe is the detection surface for this condition at startup; in production the `/ready` endpoint reports `state: offline_by_no_key`.
- What you must not break. The key must never appear in error messages, log lines, or response bodies. The `_redact_sentry_event` hook strips `query` and `prompt` keys from Sentry events as defense-in-depth; the key itself is never passed to Sentry because `send_default_pii=False`.

### Secret/key present but REJECTED by the provider

- What STOPS. Nothing stops. This is the dangerous one: the key is a non-empty string, so every "is it configured?" check passes, and each provider call fails individually and falls back. Runs complete and look normal.
- What DEGRADES. Every model answer, the debate, and the synthesis come from local simulation while the deployment reports itself configured.
- Detection mechanism. A credential probe (`readiness.start_key_auth_probe`) issues `GET {openrouter_api_base_url}/key` — auth-required and zero token cost — on a background daemon thread, and publishes a verdict that `run_startup_probe` reads from cache. A 401/403 sets `state: offline_by_bad_key` on `/ready`, flips `/status.live_execution` to `false`, and raises the workspace banner. Only an explicit 401/403 does this: a timeout, a 429, or a 5xx leaves the state unchanged, because a network fault is not evidence about a credential — and an inconclusive probe never overwrites a recorded verdict, so one blip cannot re-advertise a refused key as live. Measured 2026-07-28: a funded valid key returns 200 and a valid but UNFUNDED key returns 401, so this state legitimately covers "empty account" as well as "bad credential" — the two are not separable at this endpoint. Since #112, the probe re-checks every `key_auth_reprobe_interval_seconds` (default 1800s) for as long as the process runs, not just once at startup — so a key revoked or drained of credit mid-life is caught within one interval, not only at the next restart. Known gap, not yet fixed: a proxy or WAF answering 403 on the `/key` path is indistinguishable from the provider doing so, and would pin a healthy deployment to `offline_by_bad_key`.
- Recovery mechanism. A key that starts rejected and is later fixed self-heals within one `key_auth_reprobe_interval_seconds` window — no restart needed, since a later `"ok"` verdict overwrites the earlier `"unauthorized"` the same way any verdict change is recorded. A restart still clears the state immediately, for an operator who does not want to wait out the interval.
- What you must not break. The probe must stay on a background thread (module import already blocks on the catalog fetch) and must stay gated on live-flag AND key-present, which is what keeps the test suite socket-free and the contract gate's no-outbound-socket guard green. The reason string is served on the public `/ready`, so it must come from `APPROVED_REASON_PREFIXES` and never interpolate the key or a raw provider error.

### Browser disconnection mid-query

- What STOPS. Nothing stops on the server side. The browser disconnecting drops the HTTP response stream; the background thread continues executing the pipeline to a terminal state.
- What DEGRADES. The user's browser session loses the polling channel. If the user refreshes, the new session cannot read the old run's result because the run is scoped to the original `account_id` (session cookie). The run completes or times out normally; the durable `run_history_store` row is written.
- Detection mechanism. No server-side detection. The background thread is a `daemon=True` thread with no browser-bound lifecycle. The `_execute_query_run_safely` try/except guarantees a terminal state regardless of browser state.
- Recovery mechanism. The user must open a new session. The old run is unreachable from the new session (wrong-identity access is denied by `get_for_account`). This is a known UX limitation of session-scoped auth; durable accounts would allow cross-session result retrieval.
- What you must not break. The background thread must not depend on the request context after the 202 response is returned. The `_run_semaphore` is released in the `finally` block of `_execute_query_run_with_semaphore_release`; a thread that holds the semaphore forever would exhaust the `_MAX_CONCURRENT_RUNS` cap.

### Concurrent query attempt (one active query per session)

- What STOPS. The second concurrent query from the same session is rejected with HTTP 409 `ACTIVE_QUERY_EXISTS`. No `QueryRun` is created for the second request.
- What DEGRADES. Nothing degrades. The first run continues to its terminal state. The second request returns a clear error message: "One query can run at a time for this account."
- Detection mechanism. `InMemoryQueryRunRepository.create` calls `get_active_for_account` under the repository lock. If a non-terminal run exists for the account, it raises `ActiveQueryRunExistsError`. The route layer catches this and returns 409.
- Recovery mechanism. The user must wait for the first run to reach a terminal state or cancel it via `DELETE /v1/query-runs/{id}`. The cancel path goes through `transition()`, which validates the state machine — a run that already completed cannot be overwritten with `CANCELLED`.
- What you must not break. The active-query check must sit inside the repository lock — two concurrent `create` calls from the same account must not both pass the check. The lock is the serialisation point; the semaphore (`_run_semaphore`) is a separate process-wide cap that does not replace the per-account check.
