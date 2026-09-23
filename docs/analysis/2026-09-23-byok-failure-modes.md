# Bring-your-own-key: the failure modes, listed before any code (2026-09-23)

**PROPOSED — AWAITING OWNER.** AGENTS.md rule 16e: before code that touches
money, auth or safety, list the known failure modes on one page and design
against the list. The owner planned BYOK on 2026-09-23 (CHG-011 D8, ADR-0121,
PROPOSED); nothing of it is built. Every "today" claim below names the grep
that produces it, run on `main` at `2f60eef`. Nothing here was measured with
a paid call.

## The two facts every mode turns on

- **The key never chooses anything today.** `credential_source` is
  hard-coded to `APP_OWNED` (`query_run_orchestration.py`,
  `grep -n "credential_source = ProviderCredentialSource"`) and is only
  recorded on provider events (`providers.py`, every `record(...,
  credential_source=...)`); the key itself travels separately as
  `openrouter_key`. So a BYOK build cannot "switch on" a dormant path: it has
  to introduce the first place a credential source is resolved.
- **Every rail is keyed on the app's money.** `GLOBAL_DAILY_CEILING_USD`
  empties the run's key (`query_run_orchestration.py` ~1180), `DAILY_CAP_USD`
  blocks per account (`costs.py` ~907), `HARD_LIMIT_USD` blocks per run
  (`costs.py::_threshold_for`), the live window gates dispatch
  (`providers.py::_live_execution_enabled`), and `SESSION_MINT_CAP_PER_IP = 2`
  (`auth.py`) exists because a mint is a claim on the app's key.

## The modes

| # | Failure mode | Threat | What pins it today (measured) | What BYOK must add |
|---|---|---|---|---|
| 1 | **The user's key leaks** through a browser payload, a log line, a model prompt, an error body or an analytics event. | T-004 | Responses and all six event recorders: `tests/security/test_release_security_redaction.py::test_provider_secret_values_do_not_leak_into_responses_or_events` (with per-recorder event counts as the positive partner). Logs and Sentry: `tests/unit/test_logging_config_sentry_redaction.py` (about 20 "never_reaches_a_sentry_breadcrumb" tests) and `tests/unit/test_logging_config_redaction.py`; the patterns are `logging_config.py::_REDACTION_PATTERNS` (`Bearer …`, `sk-…`, `api_key=`). Redirects: `tests/unit/test_credential_transport_guard.py::test_a_redirect_never_delivers_the_openrouter_key`, partner `…_still_carries_the_key`. Unsafe base: `tests/unit/test_credentialed_base_url_guard.py`. Readiness reason: `tests/unit/test_readiness.py:215`. `/status`: `tests/integration/test_judge_configuration_is_observable.py:170`. | **No test today asserts the key is absent from a model PROMPT** (grep of `tests/` for a prompt-body assertion: no hits). BYOK adds one, with a real prompt as the positive partner. Every existing absence test gets a BYOK sibling that uses the USER key's shape (an OpenRouter user key is also `sk-or-…`, so the `sk-` pattern already matches; assert it, do not assume it). |
| 2 | **Cross-account reuse:** one session's key is used by, or its status read by, another account. | T-006 | `GET /v1/query-runs/{id}` is owner-scoped (`query_runs.py` ~993 → `get_for_account`; `query_run_orchestration.py` ~620 `query_run.account_id != account_id`). Sessions are keyed by a SHA-256 digest of the session id (`session_store.py`). | The key is stored against the account the session names, never in the browser (AC-026 keeps the browser clean); key STATUS (present/absent, last 4) is owner-scoped like a run; a test drives two sessions and proves the second cannot read or spend the first's key. |
| 3 | **Use after removal:** the user removes the key while a run is in flight. | T-004, EDGE-013 | EDGE-013 in `docs/16-edge-case-catalog.md` is "Planned"; nothing pins it. The orchestrator copies `openrouter_key` into a local at run start (~1159), so a removal mid-run would NOT stop calls already dispatched. | Decide and pin: either the run finishes on the copy (state it on the receipt) or the next stage re-reads and fails closed. Either way a test that removes the key between the answer stage and the debate stage and asserts the outcome. |
| 4 | **Spend runaway on the user's key:** a run, or a day of runs, spends more than the user expected. | money | Per-run: `HARD_LIMIT_USD` (0.50) and the cumulative rail (`costs.py` ~748). Per day: `DAILY_CAP_USD` (0.40) — which BYOK DROPS. One run at a time: `ActiveQueryRunExistsError` → 409. | The user budget window ($5 default) replaces the envelope, enforced through the same `evaluate_confirmation` gate; rule 6b: the test asserts HOW MANY runs cross it, not that one did. The judge's spend joins the ledger it is outside of today (ADR-0013, ADR-0097). |
| 5 | **Judge-key ownership:** the judge silently runs on the app's judge key for a user's run, or on the user's key without a priced row. | money, honesty | `evaluation.py` ~1914: `call_with_prompt(openrouter_key=settings.quorum_eval_judge_api_key, …)` — the operator key, always; `call_with_prompt` does not consult `_live_execution_enabled`. | Under a user key the judge call passes the USER key; the estimate carries a judge `by_stage` row; a wire-level test asserts which key the judge request carried (the `Authorization` header captured, as `test_credential_transport_guard.py` already does for answers). |
| 6 | **Infrastructure abuse through a cheap key:** a visitor supplies a worthless or revoked key to consume compute, mint sessions, or probe the service. | availability | Per-IP burst limiter on session mint (`query_runs.py` `CAPACITY = 10`, `REFILL_PER_MINUTE = 10`), the durable mint cap (2 per IP per 24h) and the process semaphore (`_MAX_CONCURRENT_RUNS = 16` → 503). A refused key fails every slot, so no critic call is reached (ADR-0116). | The owner's numbers (about 100 to 200 mints per IP per day; about 10 requests per 1 to 2 minutes) replace the app-key cap for BYOK sessions only; the key is validated once at intake with the free `GET /api/v1/auth/key` shape (a bad key answers `401 {"error":{"message":"User not found.","code":401}}`, AGENTS rule 8c) before any run is accepted. |
| 7 | **The confirmation token does not bind the slot list or the shape.** | money | `costs.py::_format_token` binds `account_id, query_run_id, estimated_cost_usd, expires_at, nonce` only; `docs/analysis/2026-09-23-session-handoff.md` §3 records the debt. Harmless today only because no per-run toggle exists. | Prerequisite for any per-run toggle (ADR-0121 Consequences, CHG-011 D9): bind `model_slots` and the shape into the HMAC input first; the test mints for a moderator panel of two and proves it cannot confirm a peer panel of four. |
| 8 | **The copy lies about the posture.** A BYOK run shows the app-key copy ("off on this deployment") or the reverse. | honesty | `_peer_critique_in_effect` is the ONE predicate all shape copy reads (`main.py`; the island, `/status`, the landing subhead, the composer shape line). | BYOK adds ONE term to that predicate (credential source), never a second predicate; `tests/unit/test_ui_honesty.py` and `test_w4_copy_outside_run_path.py` get a BYOK posture row each. |

## What the existing FR-011 / FR-012 rows really pin

- FR-011 (server-side keys) is pinned by the tests in row 1; the RTM's
  `TEST-FR-011` label appears in no test file (`grep -rn "TEST-FR-011" tests/`:
  no hits) — the coverage is real, the label is not.
- FR-012 is titled "Required bring-your-own OpenRouter key" and its Behavior
  says the opposite (server keys only); its RTM row cites
  `tests/unit/test_provider_keys.py` and
  `tests/integration/test_provider_key_endpoints.py`, neither of which exists.
  AC-025 is mapped to FR-011 in `docs/12` and to FR-012 in the RTM. The first
  BYOK pull request rewrites FR-012 to the two-posture rule and repairs both
  rows; this page only records the gap.

## Reproduced at $0 (this session)

- `credential_source` hard-coded and passed through unread: grep as above.
- Token binding: read `costs.py::_format_token` and `_verify_confirmation_token`.
- No prompt-body absence test: grep of `tests/` as above.
- Nothing else was reproduced; no live call, no key, no window.
