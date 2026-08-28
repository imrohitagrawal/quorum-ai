"""Module-level constants in risk-tier code must be pinned to a literal value.

**The gap this closes.** The mutation gate cannot see module-level code at all:
mutmut only mutates function bodies, and ~35% of `src/product_app` (5,829 lines)
sits outside every `def`. Measured over real history, **8% of pull requests that
changed `src/` Python produced an EMPTY mutation scope** — and three of the five
real cases were money or model configuration: the daily cap, the web-search fee,
the model id. `docs/metrics/mutation-gate-study.md` §3.1.

Measured before this file existed, with a detector that requires the other side
of the comparison to be a LITERAL: of the 38 module-level constants in risk-tier
modules, **3 carried a literal `== VALUE` assertion** — `costs.DAILY_CAP_USD`
(`tests/integration/test_query_run_cost_guardrails.py:501`),
`costs.HARD_LIMIT_USD` (`tests/integration/test_cumulative_cost_guard.py:154`)
and `main.SENTRY_DSN` (`tests/unit/test_sentry_init.py:33`). The other 35 were
referenced only symbolically (`assert x < DAILY_CAP_USD`,
`assert rendered == CONSTANT`), which moves with the code — change the constant
and the test still passes.

(A previous revision of this docstring said "not one". False — and it was a
*correction* of an earlier true statement, introduced while fixing a different
false claim, in the file whose whole purpose is preventing exactly this.
Round-2 adversarial review caught it by running the new detector against
`origin/main`. Left on the record rather than quietly amended.)

The starkest case, and the reason this file is not academic:
`costs._DEFAULT_PRICE_PER_1K_INPUT = 0.0008` — the default behind the recorded
16x mispricing — was referenced only SYMBOLICALLY
(`assert Decimal(cm["default_input_price_per_1k"]) == _DEFAULT_PRICE_PER_1K_INPUT`,
`tests/integration/test_template_data_island_escape.py:89`). That assertion
compares the rendered template against the constant, so it holds no matter what
the constant says. Change 0.0008 to 0.0128 and it stays green.

(An earlier draft of this file claimed the constant had *zero* references and
that its `_OUTPUT` twin was pinned. Adversarial review showed both halves false:
the twin carries the identical symbolic assertion. The error came from a pin
detector that counted `== CONSTANT` as a pin regardless of what the other side
was — the very flaw `test_every_bucket_a_constant_really_has_a_literal_pin` now
exists to prevent. Recorded rather than quietly corrected.)

**#145, closed.** Three gaps were stated rather than implied here (round-2
review, all measured). All three are now closed, each with its own detector
self-test proving both directions (`test_an_assert_inside_if_false_is_not_a_pin`
and friends, `test_is_literal_accepts_pytest_approx` and friends,
`test_class_constants_are_discovered_but_enum_members_are_not`):

* The pin detector now checks reachability. `_pins_in_file` only counts
  asserts inside a COLLECTED test (a top-level or class-method `test_*`
  function, not `@pytest.mark.skip`ped) that are structurally reachable —
  `_reachable_asserts` stops at dead code after an unconditional
  `return`/`raise`/`continue`/`break`, resolves a literal `if True:`/`if False:`
  to the taken branch only, and never descends into a nested `def` (called or
  not — conservative by design: requiring the assert directly in the
  collected test's own body is simpler to reason about than tracking whether
  a nested helper is actually invoked, and every real pin in this repo is
  written that way already).
* `_is_literal` now accepts `pytest.approx(...)` (and the bare `approx(...)`
  form) over literal arguments, and `Tuple`/`List`/`Set`/`Dict` literals whose
  elements are themselves literal. It also resolves the parametrize form the
  issue names as "the natural way to write 13 pins" —
  `@pytest.mark.parametrize('expected', [0.001])` /
  `assert CONST == expected` — via `_parametrize_literal_params`, which binds
  a parameter name to "literal" only when every parametrize case supplies a
  literal for it (`test_a_parametrized_literal_pins_the_constant` and its
  negative and multi-argname partners).
* Discovery now also walks class bodies for ALL-CAPS attributes
  (`_class_constants`), explicitly excluding `StrEnum`/`Enum`/`IntEnum`/
  `IntFlag`/`Flag` subclasses — enum membership is issue #160's surface, not
  this one. This found **17** class constants in the 10 risk-tier modules (not
  sixteen — the original count was itself unmeasured against the fixed
  detector), all now triaged below: six in the two `query_runs` rate-limiter
  classes were already pinned by existing tests once `_qualify` learned to
  resolve a class import to its module (previously
  `_InMemoryIpRateLimiter.CAPACITY` matched with no module prefix and was
  invisible as a *triage* entry even though the assertion existed); the two
  `config.Settings` bounds are pinned behaviourally by existing tests in
  `test_run_deadline.py` / `test_session_rate_limit_override.py` /
  `test_session_mint_cap.py`; the `feedback_store.FeedbackStore` SQL/marker
  attributes split between bucket B (the F-01 migration name and its SELECT,
  both proven idempotent by `test_f01_preview_billing_backfill.py`) and
  bucket C (schema/index DDL, exercised by every store test); the three
  `MAX_EVENTS` ring-buffer caps are bucket C (memory, not correctness).

**Why not pin all 38.** A literal pin on a regex, a filesystem path or a CSP
policy is churn: the value legitimately changes, so the reflex becomes "edit the
test alongside the code", which is the habit this whole exercise exists to
break. Constants are therefore TRIAGED into three buckets below, and
`test_every_risk_constant_is_triaged` fails when a new one belongs to none — so
the decision is forced, never defaulted.
"""

from __future__ import annotations

import ast
import pathlib
import re
from datetime import timedelta
from decimal import Decimal

from product_app import (
    auth,
    catalog_fetcher,
    costs,
    feedback_store,
    main,
    model_slots,
    query_runs,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "product_app"
TESTS = REPO_ROOT / "tests"

#: The modules whose module-level constants are risk-bearing.
#:
#: KNOWN GAP, stated rather than implied: `config.py` is listed but contributes
#: ZERO constants, because all 41 of its settings are `Settings` class
#: attributes with defaults, not module-level names. So the largest
#: configuration surface in the repo — including
#: `cost_web_search_request_fee_usd`, one of the money changes that produced an
#: empty mutation scope — is NOT covered by this file. Extending the registry to
#: Pydantic field defaults is tracked separately; listing `config.py` here keeps
#: the module in view rather than letting it read as covered by omission.
RISK_TIER_MODULES = (
    "costs.py",
    "config.py",
    "catalog_fetcher.py",
    "model_slots.py",
    "safety.py",
    "auth.py",
    "main.py",
    # Added 2026-08-03. These three hold the module-level state behind the
    # spend cap, and a review pass found FIVE defects in ~40 lines of that
    # logic -- none in the predicates, all in wiring. The 2000ms readiness
    # timeout and the reconnect cooldown are exactly the shape this gate
    # exists to force a decision about, and neither was triaged because
    # neither module was listed here.
    "feedback_store.py",
    # Added 2026-08-26 with ADR-0073. It holds a CREDENTIAL at rest (the
    # session digest) and the interval that bounds how much of a session's
    # remaining life a restart loses. It was not listed when it was written,
    # so none of its constants was triaged -- exactly the "covered by
    # omission" shape the RISK_TIER_MODULES comment above warns about.
    "session_store.py",
    "readiness.py",
    "query_runs.py",
    # #303: the run state machine, repository and pipeline constants that used
    # to live in `query_runs.py` moved to their own module (ADR-0036). Listed
    # separately rather than folded into the `query_runs.py` comment above
    # because it is now a distinct file, not a rename of the same one.
    "query_run_orchestration.py",
    "store_reconnect.py",
)

#: A wrong value here is silently harmful and nothing else constrains it.
#: Every name must have a literal `== VALUE` assertion in tests/.
BUCKET_A_LITERAL_PIN = (
    # A wrong value is silently harmful in both directions: dropping "https"
    # breaks every production catalog fetch, and adding "file" turns an
    # operator's typo into an arbitrary local-file read served as live prices.
    "catalog_fetcher._FETCHABLE_SCHEMES",
    "costs.SOFT_THRESHOLD_USD",
    "costs.DAILY_CAP_USD",
    "costs.HARD_LIMIT_USD",
    "costs.GLOBAL_DAILY_CEILING_USD",
    "costs._DEFAULT_PRICE_PER_1K_INPUT",
    "costs._DEFAULT_PRICE_PER_1K_OUTPUT",
    "costs.CHARS_PER_TOKEN",
    "costs.COST_DISPLAY_QUANTUM",
    "costs.CONFIRMATION_TOKEN_TTL",
    "auth.SESSION_TTL",
    "auth.SESSION_MINT_CAP_PER_IP",
    # The rolling window the cap is counted over. A LITERAL pin for the same
    # reason the cap itself is one: cap and window are one control, and
    # widening the window silently tightens the cap while narrowing it
    # silently loosens a spend guard -- in the fail-open direction, and with
    # no other value in the code constraining it. It is also now user-facing:
    # the 429 page derives its advertised wait from this number.
    "feedback_store.FeedbackStore.SESSION_MINT_WINDOW",
    "auth._SESSION_COOKIE_NAME_PREFIXED",
    "auth.CSRF_HEADER_NAME",
    "main._HSTS_HEADER",
    "model_slots.EXPECTED_SLOT_COUNT",
    # The four cost event-type strings (#255, #376). A LITERAL pin, not a
    # behaviour one, because these values are written into a DURABLE table that
    # outlives every deploy: change one and the meter stops counting every row
    # already on the production volume — silently, and in the fail-open
    # direction. The string IS the contract with rows that already exist, which
    # is exactly "a wrong value is silently harmful and nothing else constrains
    # it". ``COST_ACCEPTED_SIMULATED_EVENT`` joins them for the same reason and
    # one more: it is the discriminator that keeps a simulated run out of
    # ``global_daily_spend``, so a typo in it puts them all back in.
    "feedback_store.COST_ACCEPTED_EVENT",
    "feedback_store.COST_ACCEPTED_SIMULATED_EVENT",
    "feedback_store.COST_RECONCILED_EVENT",
    "feedback_store.COST_CHARGE_VOIDED_EVENT",
    # --- Added with #145/#160: class-level constants the fixed detector
    # can now see. Already pinned by `test_session_rate_limit_override.py`
    # (`_InMemoryIpRateLimiter.CAPACITY == 10` etc, `test_production_default_is_ten`
    # / `test_account_limiter_is_pinned_at_thirty`) -- invisible as a TRIAGE
    # entry before `_qualify` learned to resolve a class import to its
    # module. `STALE_BUCKET_SECONDS` had no existing pin (SEC-H3: it bounds
    # the memory a /16 scan can pin in the rate-limiter's bucket dict; a
    # wrong value is silently harmful and nothing else constrains it), so
    # `test_the_rate_limiter_eviction_windows_are_pinned` below adds one.
    "query_runs._InMemoryIpRateLimiter.CAPACITY",
    "query_runs._InMemoryIpRateLimiter.REFILL_PER_MINUTE",
    "query_runs._InMemoryIpRateLimiter.STALE_BUCKET_SECONDS",
    "query_runs._InMemoryAccountRateLimiter.CAPACITY",
    "query_runs._InMemoryAccountRateLimiter.REFILL_PER_MINUTE",
    "query_runs._InMemoryAccountRateLimiter.STALE_BUCKET_SECONDS",
)

#: Pin the BEHAVIOUR, not the literal — these legitimately change, and a literal
#: pin would teach people to edit the test alongside the code.
BUCKET_B_PIN_BEHAVIOUR = {
    # --- Added 2026-08-26 with the live-vs-simulated ledger (#376, ADR-0074) ---
    "feedback_store._LAST_CHARGE_SCAN_LIMIT": (
        "how far last_live_charge_at walks back looking for a parseable "
        "recorded_at. The VALUE legitimately moves with the cost of holding the "
        "store lock on the unauthenticated /status path; what must not move is "
        "that ONE malformed row does not make the field report None, which a "
        "watchdog reads as 'this deployment has never spent live' while dated "
        "live charges sit on disk. Asserted with 2 rows, not 16, so the test is "
        "independent of this constant (rule 7a): tests/integration/"
        "test_ledger_live_versus_simulated.py::TestLastLiveChargeAt::"
        "test_one_unreadable_row_does_not_erase_every_live_charge"
    ),
    "feedback_store._ACCOUNT_CHARGE_EVENTS": (
        "which opening-charge types the PER-ACCOUNT rail counts. Its membership "
        "legitimately grows as charge types are added -- what must not move is "
        "that a simulated charge still fills DAILY_CAP_USD, so an account cannot "
        "get unbounded free compute. Asserted by tests/integration/"
        "test_ledger_live_versus_simulated.py::"
        "TestThePerAccountCapStillCountsSimulatedRuns"
    ),
    "feedback_store._LIVE_CHARGE_EVENTS": (
        "which opening-charge types the DEPLOYMENT-WIDE rail counts. The strings "
        "themselves are pinned in bucket A; what this needs is the behaviour -- "
        "simulated traffic far past $5.00 must not degrade the deployment, and "
        "the same dollars as LIVE charges must. Both asserted by tests/"
        "integration/test_ledger_live_versus_simulated.py::"
        "TestSimulatedRunsLeaveTheGlobalMeterAlone"
    ),
    "costs._RING_CHARGE_EVENT_TYPES": (
        "the in-process ring's mirror of _ACCOUNT_CHARGE_EVENTS. A literal pin "
        "would not catch the failure that matters, which is the two per-account "
        "rails DIVERGING (ADR-0051 measured that at 20x). Asserted by tests/"
        "integration/test_ledger_live_versus_simulated.py::"
        "TestThePerAccountCapStillCountsSimulatedRuns::"
        "test_the_in_process_ring_counts_simulated_charges_too"
    ),
    # --- Added 2026-08-26 with session_store.py (ADR-0073) ---
    "session_store.SESSION_TOUCH_PERSIST_INTERVAL_S": (
        "a write-amplification throttle, not a guard. Its error is bounded and "
        "one-directional in BOTH directions -- too small costs SQLite writes on "
        "the authenticated hot path, too large understates a restored session's "
        "remaining life by at most the interval -- so it legitimately moves with "
        "measurement. What must not move is that a burst of touches does NOT "
        "produce a burst of writes, and that a touch past the interval DOES "
        "write; both are asserted by "
        "tests/security/test_durable_session_store.py::"
        "test_a_touch_does_not_write_through_on_every_request"
    ),
    # --- Added 2026-08-07 with the Sentry redaction fix (ADR-0023) ---
    "main._USER_TEXT_FIELDS": (
        "assert that a payload carrying any of these fields comes back with the user's "
        "prose GONE, not that the tuple has a particular membership -- the set grows as "
        "the domain model grows, so a literal pin would go red on every legitimate "
        "addition while still not proving anything was actually redacted; "
        "tests/unit/test_sentry_redaction.py drives real event AND transaction payloads "
        "through both hooks and sweeps the whole serialised body for the query, and "
        "additionally pins every entry to a real occurrence in src/ so a rename cannot "
        "silently shrink the redaction set"
    ),
    # --- Added 2026-08-06 with the #265 judge cap term ---
    "costs._JUDGE_EVIDENCE_SECTIONS": (
        "assert the judge reserve does NOT track settings.cost_synthesis_sections and "
        "that build_judge_evidence really emits this many sections -- the number must "
        "equal what the evidence builder emits, and a literal pin alone would not "
        "catch the two drifting apart"
    ),
    # --- Added 2026-08-07 with the #268 judge source-block bound ---
    "costs._JUDGE_SOURCE_LINE_OVERHEAD_CHARS": (
        "assert the widest line build_judge_evidence can actually emit still fits the "
        "budget this constant reserves -- it models the '[NN] ', ' :: ' and newline "
        "scaffolding around the two truncated fields, so a literal pin alone would not "
        "catch the format string growing a separator and silently outgrowing the "
        "reserve; tests/unit/test_judge_evidence_source_lines_are_bounded.py measures "
        "the real emitted lines against it in both directions"
    ),
    # --- Added 2026-08-10 with the #284 evaluation memo ---
    # #303: moved from query_runs.py to query_run_orchestration.py (ADR-0036).
    "query_run_orchestration._EVALUATION_MEMO_MAX": (
        "assert that the entry ONE over the cap evicts the oldest and keeps the "
        "newest, not that the cap is 512 -- the size is tunable (a wrong value "
        "costs memory or one extra evaluation, never a wrong answer), the "
        "unbounded growth is not; "
        "tests/unit/test_query_run_evaluation_memo.py drives six real runs "
        "through query_run_orchestration._evaluate_terminal_run with the cap "
        "monkeypatched to 5, so the eviction it asserts is the one the "
        "production write path performs -- an earlier version of this sentence "
        "said 'drives the real memo' while the test called the "
        "_evaluation_memo_store helper, and a direct dict write inside "
        "_evaluate_terminal_run survived it"
    ),
    # --- Added 2026-08-03 with feedback_store / query_runs / readiness ---
    # #303: moved from query_runs.py to query_run_orchestration.py (ADR-0036).
    "query_run_orchestration._MAX_CONCURRENT_RUNS": (
        "assert the (N+1)th concurrent run is refused, not the number 16 -- the "
        "capacity is tunable, the refusal is not"
    ),
    "query_runs._QUERY_TEXT_MAX_LENGTH": (
        "assert over-length is refused and that /warnings uses the SAME bound; "
        "they diverged once (8000 vs 20000) and broke the probe-then-create flow"
    ),
    # #303: moved from query_runs.py to query_run_orchestration.py (ADR-0036).
    "query_run_orchestration.ALLOWED_TRANSITIONS": (
        "assert the legal moves and that a terminal status has no successor; "
        "the map grows when a status is added"
    ),
    "query_run_orchestration.TERMINAL_STATUSES": (
        "assert membership of completed/failed/cancelled, not the literal set"
    ),
    "query_runs._CONTEXT_MAX_LENGTHS": (
        "assert an over-long value is refused on BOTH the create and /warnings "
        "routes; the numbers are tunable, the shared refusal is not (#155)"
    ),
    "readiness.APPROVED_REASON_PREFIXES": (
        "assert an unapproved reason cannot reach /ready; the list grows"
    ),
    "readiness._CREDENTIAL_REFUSED_STATUSES": (
        "assert 401/403 map to offline_by_bad_key; the set may grow"
    ),
    "feedback_store._METERED_WRITES": (
        "assert lost_billed_writes counts exactly the pairs daily_spend_for sums "
        "-- ADR-0004 depends on those two agreeing; the SET grows (it gained "
        "cost_reconciled in #255), the agreement must not"
    ),
    "main._CSP_POLICY": "assert the key directives, not the whole string",
    "safety.HIGH_STAKES_PATTERN": (
        "assert it matches 'medical' and not 'weather'; the regex should grow"
    ),
    "safety._OWN_CAVEAT_TEXT": (
        "not a literal at all — it IS synthesis_length._CaveatEnforcer.FULL_CAVEAT, "
        "imported; assert it still equals synthesis.HIGH_STAKES_NOTICE_FRAGMENT, "
        "which remains a separate copy"
    ),
    "safety._OWN_CAVEAT_OPTIONAL_OPENING": (
        "assert a truncated caveat (which synthesis_length emits without this "
        "opening) is still stripped; the clause tracks _truncate_with_caveat_present"
    ),
    "safety._OWN_CAVEAT_PATTERN": (
        "assert it strips this app's own caveat but NOT a hostile sentence that "
        "merely appends the marker, nor one continuing past 'advice.'; the "
        "wording tolerance inside the anchors should grow, the anchors must not "
        "(tests/unit/test_high_stakes_context_discriminator.py)"
    ),
    "safety.WARNING_VERSION": "assert the ISO-date shape, not the value",
    "model_slots._MODEL_ID_RE": "assert accept/reject on samples",
    "catalog_fetcher._VENDOR_RE": "assert accept/reject on samples",
    "main._KNOWN_HTTP_METHODS": "assert non-empty and contains GET/POST",
    "main._PYDANTIC_TYPE_TO_CODE": "assert the mappings the API contract depends on",
    "auth._SESSION_COOKIE_NAME_UNPREFIXED": (
        "assert where the unprefixed fallback is accepted (F-02)"
    ),
    "auth.LEGACY_CSRF_PLACEHOLDER": "assert the legacy path it marks, not the string",
    "catalog_fetcher.DEFAULT_VENDORS": (
        "assert it equals the vendor set of DEFAULT_MODEL_IDS; it changes on a slot swap"
    ),
    "catalog_fetcher._FALLBACK_CATALOG": (
        "assert every DEFAULT_MODEL_ID has a row; prices change upstream"
    ),
    "model_slots.DEFAULT_MODEL_IDS": (
        "assert the count and that each id resolves in the catalog; ids are swapped"
    ),
    "model_slots.FALLBACK_CATALOG_OPTIONS": (
        "assert the shape the slot picker relies on, not the members"
    ),
    "model_slots.ONLINE_CAPABLE_VENDORS": (
        "assert it stays within DEFAULT_VENDORS; :online support is unverified (study §7)"
    ),
    "model_slots._DEFAULT_MODEL_ID_SET": (
        "derived from DEFAULT_MODEL_IDS; assert they stay consistent"
    ),
    "model_slots._UNAUTHENTICATED_VARIANT_SUFFIXES": (
        "assert the suffixes are stripped, not the literal tuple"
    ),
    "safety.WARNING_COPY": (
        "assert the mandatory caveat is present; the wording is edited deliberately"
    ),
    # --- Added with #145/#160: class-level constants the fixed detector
    # can now see (previously invisible to discovery entirely). ---
    "config.Settings.RUN_DEADLINE_MAX_SECONDS": (
        "assert a deadline one second over the bound is refused and the bound "
        "itself is accepted, with literals on both sides -- "
        "tests/integration/test_run_deadline.py::"
        "test_a_non_positive_or_non_finite_deadline_is_rejected drives 3_601 "
        "(rejected) and 3_600 (accepted)"
    ),
    "config.Settings.SESSION_RATE_LIMIT_MAX": (
        "assert an override one over the bound is refused and the bound itself "
        "is accepted -- tests/unit/test_session_rate_limit_override.py"
    ),
    "config.Settings.SESSION_MINT_CAP_OVERRIDE_MAX": (
        "assert an override one over the bound is refused and the bound itself "
        "is accepted -- tests/unit/test_session_mint_cap.py"
    ),
    "feedback_store.FeedbackStore._F01_MIGRATION": (
        "assert the F-01 relabel runs at most once across repeated opens of "
        "the same database, not the marker string -- "
        "tests/integration/test_f01_preview_billing_backfill.py proves "
        "idempotency directly against the DB (a wrong/renamed marker would "
        "silently re-run the relabel, over-zeroing legitimate rows, on every "
        "restart)"
    ),
    "feedback_store.FeedbackStore._F01_PREVIEW_SELECT": (
        "assert only rows shaped recorder=cost, event_type=cost_guardrail_"
        "accepted, query_run_id IS NULL are relabeled and every other row is "
        "untouched -- tests/integration/test_f01_preview_billing_backfill.py::"
        "test_backfill_leaves_every_other_cost_row_alone and "
        "test_backfill_never_relabels_a_row_written_after_it_ran"
    ),
}

#: No pin. A literal here restates the implementation and catches nothing.
BUCKET_C_NO_PIN = {
    # --- Added 2026-08-03 with feedback_store / query_runs / readiness ---
    "feedback_store.DEFAULT_DB_PATH": (
        "filesystem path, overridden by FEEDBACK_DB_PATH everywhere it matters"
    ),
    "feedback_store.LOST_COST_EVENT_LOG_INTERVAL_S": (
        "log rate limit; a wrong value costs log volume, not money or safety"
    ),
    "feedback_store._CLOSE_LOCK_TIMEOUT_S": (
        "teardown-only bound; a wrong value delays process exit, nothing else"
    ),
    # #303: the four TTL/pool/wait constants below moved from query_runs.py to
    # query_run_orchestration.py (ADR-0036); the two _CONTEXT_PRIOR_* lengths
    # stayed in query_runs.py (they belong to the request-schema validator).
    "query_run_orchestration.QUERY_RUN_ACTIVE_TTL": (
        "cache lifetime; exercised by the resume tests"
    ),
    "query_run_orchestration.QUERY_RUN_TERMINAL_TTL": (
        "cache lifetime; exercised by the result-fetch tests"
    ),
    "query_runs._CONTEXT_PRIOR_QUESTION_MAX_LENGTH": "derived from _QUERY_TEXT_MAX_LENGTH",
    "query_runs._CONTEXT_PRIOR_SYNTHESIS_MAX_LENGTH": (
        "derived; the pair is pinned via _CONTEXT_MAX_LENGTHS"
    ),
    "query_run_orchestration._INITIAL_ANSWER_POOL_SIZE": (
        "thread-pool width; a wrong value costs latency, not correctness"
    ),
    "query_run_orchestration._SYNTHESIS_POOL_SIZE": (
        "thread-pool width; a wrong value costs latency, not correctness"
    ),
    "query_run_orchestration._JUDGE_INFLIGHT_WAIT_SECONDS": (
        "coalescing wait; a wrong value costs latency"
    ),
    "query_run_orchestration._JUDGE_VERDICT_MEMO_MAX": (
        "memo bound; a wrong value costs memory, not correctness"
    ),
    "readiness.REASON_BAD_KEY": "reason string; pinned as a set via APPROVED_REASON_PREFIXES",
    "readiness.REASON_NO_KEY": "reason string; pinned as a set via APPROVED_REASON_PREFIXES",
    "readiness.REASON_OFFLINE_BY_CONFIG": "reason string; pinned via APPROVED_REASON_PREFIXES",
    "readiness.REASON_CATALOG_UNREACHABLE": "reason string; pinned via APPROVED_REASON_PREFIXES",
    "readiness.REASON_CATALOG_DRIFT_PREFIX": "reason prefix; pinned via APPROVED_REASON_PREFIXES",
    "readiness._KEY_PROBE_OPENER": "probe path; exercised by the readiness probe tests",
    "main.TEMPLATES_DIR": "filesystem path, exercised by every template render",
    "main.STATIC_DIR": "filesystem path, exercised by every static fetch",
    "main._FEEDBACK_DIR": "filesystem path, exercised by the feedback store tests",
    "main._APP_START_MONOTONIC": "runtime value, not a configuration choice",
    "main.SENTRY_DSN": "derived from the environment at import",
    "main._VENDOR_PREFIX": "routing prefix, exercised by the routes that use it",
    "costs.DAILY_CAP_BYPASS_LOG_INTERVAL_S": (
        "log throttle; a wrong value costs log volume, not money"
    ),
    # --- Added with #145/#160: class-level constants the fixed detector
    # can now see (previously invisible to discovery entirely). ---
    "costs.InMemoryCostEventRecorder.MAX_EVENTS": (
        "in-memory event ring size; a wrong value costs memory or telemetry "
        "recall, not correctness (the durable feedback_store row is the real "
        "record)"
    ),
    "model_slots.InMemoryModelSlotEventRecorder.MAX_EVENTS": (
        "in-memory event ring size; a wrong value costs memory or telemetry recall, not correctness"
    ),
    "safety.InMemoryWarningEventRecorder.MAX_EVENTS": (
        "in-memory event ring size; a wrong value costs memory or telemetry recall, not correctness"
    ),
    "feedback_store.FeedbackStore._SCHEMA": (
        "SQL DDL, not a value; malformed SQL fails loudly at the first CREATE "
        "TABLE and every FeedbackStore test opens a real database with it"
    ),
    "feedback_store.FeedbackStore._MIGRATIONS_DDL": (
        "SQL DDL, not a value; malformed SQL fails loudly at open, exercised "
        "by every migration test"
    ),
    # --- Added 2026-08-26 with session_store.py (ADR-0073) ---
    "auth.SESSION_GC_INTERVAL_S": (
        "how often the session-gc daemon purges. A wrong value costs memory "
        "headroom or idle wakeups, never correctness: expiry is enforced on "
        "every READ as well (session_store.fetch's last_used_at predicate), so "
        "a purge that ran late -- or never -- cannot make an expired session "
        "resolvable. That read-side enforcement is what tests/security/"
        "test_durable_session_store.py::"
        "test_an_expired_row_never_resolves_even_if_the_purge_never_ran pins, "
        "and it is what makes this interval a tuning knob rather than a guard"
    ),
    "session_store.DEFAULT_DB_PATH": (
        "filesystem path, overridden by SESSION_DB_PATH everywhere it matters"
    ),
    "session_store._CLOSE_LOCK_TIMEOUT_S": (
        "teardown-only bound; a wrong value delays process exit, nothing else"
    ),
    "session_store.SessionStore._SCHEMA": (
        "SQL DDL, not a value; malformed SQL fails loudly at the first CREATE "
        "TABLE and every SessionStore test opens a real database with it"
    ),
    "feedback_store.FeedbackStore._SPEND_RAIL_INDEX": (
        "best-effort covering index; its own docstring measures the cost of "
        "losing it as latency (2.13ms -> 96.40ms over 300 days of history), "
        "never correctness -- losing it must never cost availability"
    ),
}


#: Constant-looking names. The floor is 2 trailing chars, not 3: a future
#: `URL`, `TTL`, `CAP` or `FEE` would otherwise be invisible to the whole guard.
_CONST_NAME = re.compile(r"_?[A-Z][A-Z0-9_]{2,}")


def _module_constants() -> dict[str, int]:
    """`module.NAME` -> line, for every module-level constant in a risk module.

    Covers `ast.AnnAssign` as well as `ast.Assign`, and tuple targets. An
    earlier version matched only bare `Assign`, which hid EIGHT constants —
    including `catalog_fetcher.DEFAULT_VENDORS`, `catalog_fetcher._FALLBACK_CATALOG`
    and `model_slots.DEFAULT_MODEL_IDS`, i.e. precisely the surface behind the
    recorded 16x mispricing. Found by adversarial review.
    """
    found: dict[str, int] = {}
    for name in RISK_TIER_MODULES:
        path = SRC / name
        if not path.is_file():
            continue
        module = path.stem
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                targets: list[ast.expr] = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            flat: list[ast.expr] = []
            for target in targets:
                flat.extend(target.elts if isinstance(target, ast.Tuple) else [target])
            for element in flat:
                if isinstance(element, ast.Name) and _CONST_NAME.fullmatch(element.id):
                    found[f"{module}.{element.id}"] = node.lineno
    return found


#: Names of the stdlib `enum` module's base classes. A class whose base
#: resolves (via `_enum_import_names`, i.e. an actual `from enum import ...`
#: in the same file) to one of these is excluded from `_class_constants` —
#: its ALL-CAPS members are enum membership, issue #160's surface, not this
#: file's (#145 gap 3's own docstring: "most are enum members, but these are
#: not"). This is a set of names to import-match against, NOT a set of bare
#: identifiers to match a class base against directly — see
#: `_enum_import_names`.
_ENUM_BASE_NAMES = frozenset({"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag"})


def _enum_import_names(tree: ast.Module) -> frozenset[str]:
    """Local names in `tree` that are actually bound to a `from enum import
    ...` of one of `_ENUM_BASE_NAMES`, aliases included.

    Matching a class base by bare `ast.Name.id` text (the previous approach)
    let an unrelated local class named or aliased `Enum` swallow an entire
    risk-tier class's constants — no relation to python's `enum` module
    required. This resolves by PROVENANCE instead: a name only counts if this
    file actually imports it from `enum` (rule 8's substring-vs-structure
    trap, this time inside the detector itself).
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "enum":
            for alias in node.names:
                if alias.name in _ENUM_BASE_NAMES:
                    names.add(alias.asname or alias.name)
    return frozenset(names)


def _class_constants_in(path: pathlib.Path, module: str) -> dict[str, int]:
    """`module.Class.NAME` -> line, for ALL-CAPS class attributes in `path`.

    Non-enum classes only (see `_ENUM_BASE_NAMES` / `_enum_import_names`).
    Split from `_class_constants` so it can be unit-tested against a
    synthetic file instead of only the real risk-tier modules.
    """
    found: dict[str, int] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    enum_names = _enum_import_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {b.id for b in node.bases if isinstance(b, ast.Name)}
        if base_names & enum_names:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                targets: list[ast.expr] = list(stmt.targets)
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and _CONST_NAME.fullmatch(target.id):
                    found[f"{module}.{node.name}.{target.id}"] = stmt.lineno
    return found


def _class_constants() -> dict[str, int]:
    """`module.Class.NAME` -> line, for every ALL-CAPS class attribute in a
    risk module's non-enum classes.

    #145 gap 3: sixteen (measured here: seventeen) such attributes were
    invisible to discovery entirely, including `config.Settings.
    RUN_DEADLINE_MAX_SECONDS` and `config.Settings.SESSION_RATE_LIMIT_MAX`.
    """
    found: dict[str, int] = {}
    for name in RISK_TIER_MODULES:
        path = SRC / name
        if not path.is_file():
            continue
        found.update(_class_constants_in(path, path.stem))
    return found


def _qualify(node: ast.expr, origins: dict[str, str]) -> str | None:
    """`module.NAME` or `module.Class.NAME` for a reference that really is OUR
    constant, else None.

    Keying on the bare attribute name was a hole: `fake._HSTS_HEADER == "wrong"`
    pinned `main._HSTS_HEADER`, and so did any same-named local, mock attribute
    or loop variable. 122 distinct bare names in tests/ satisfied the old
    predicate — a namespace ~9x the set being guarded.

    #145 gap 3 extends this to class attributes, two import shapes:
    `config.Settings.RUN_DEADLINE_MAX_SECONDS` (module imported, then two
    attribute hops) and `Settings.RUN_DEADLINE_MAX_SECONDS` (the class
    imported directly via `from product_app.config import Settings`, one
    attribute hop but resolved through `origins` to the same three-part name).
    A single attribute hop whose base is NOT a class import (e.g.
    `costs.DAILY_CAP_USD`, where `costs` is the module itself) still qualifies
    as the plain two-part module-level form.
    """
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
        inner = node.value
        if isinstance(inner.value, ast.Name):
            return f"{inner.value.id}.{inner.attr}.{node.attr}"
        return None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        base = node.value.id
        if base in origins:
            return f"{origins[base]}.{base}.{node.attr}"
        return f"{base}.{node.attr}"
    if isinstance(node, ast.Name):
        module = origins.get(node.id)
        return f"{module}.{node.id}" if module else None
    return None


def _is_literal(node: ast.expr) -> bool:
    """A literal value, `Decimal("…")`/`timedelta(…)`/`pytest.approx(…)` over
    literals, or a `Tuple`/`List`/`Set`/`Dict` literal built entirely from
    literals.

    #145 gap 2: `pytest.approx` (the repo's own correct way to pin a float,
    used 74 times) and container literals were rejected outright.
    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_literal(node.operand)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return bool(node.elts) and all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        if not node.keys:
            return False
        return all(k is not None and _is_literal(k) for k in node.keys) and all(
            _is_literal(v) for v in node.values
        )
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in ("Decimal", "timedelta", "frozenset", "Path", "approx"):
            # `all([])` is True, so a ZERO-ARG call would qualify:
            # `assert EXPECTED_SLOT_COUNT == frozenset()` would read as a pin.
            if not (node.args or node.keywords):
                return False
            return all(_is_literal(a) for a in node.args) and all(
                _is_literal(k.value) for k in node.keywords
            )
    return False


def _imported_from(tree: ast.Module) -> dict[str, str]:
    """Bare name -> product_app module it was imported FROM, for this test file.

    Only `from product_app.<module> import <Symbol>` populates this — a bare
    `from product_app import <module>` (used throughout this file itself,
    e.g. `costs`) imports the MODULE, not a symbol inside it, so `costs` must
    stay resolvable as a module prefix in `_qualify` rather than being
    rewritten to `product_app.costs.…`.
    """
    origins: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "product_app" or not node.module.startswith("product_app"):
                continue
            tail = node.module.split(".")[-1]
            for alias in node.names:
                origins[alias.asname or alias.name] = tail
    return origins


def _is_skipped(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if a `@pytest.mark.skip`/`skipif` decorator means pytest never
    collects/runs this test. #145 gap 1.

    Structural, not textual (rule 8): matches the decorator's AST shape —
    `Attribute(attr="skip"|"skipif", value=Attribute(attr="mark", ...))`,
    called or bare — rather than a substring of `ast.dump`, which would never
    contain the literal text "mark.skip" for a real `pytest.mark.skip(...)`
    decorator (`ast.dump` separates `attr='mark'` and `attr='skip'`).
    """
    for deco in func.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if (
            isinstance(target, ast.Attribute)
            and target.attr in ("skip", "skipif")
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "mark"
        ):
            return True
    return False


def _collected_test_functions(
    tree: ast.Module,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Module-level `test_*` functions, and `test_*` methods one level inside
    a class — the shapes pytest actually collects — excluding skipped ones."""
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") and not _is_skipped(node):
                funcs.append(node)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if (
                    isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and sub.name.startswith("test_")
                    and not _is_skipped(sub)
                ):
                    funcs.append(sub)
    return funcs


def _reachable_asserts(stmts: list[ast.stmt]) -> list[ast.Assert]:
    """Asserts in `stmts` that execute UNCONDITIONALLY on a normal run.

    #145 gap 1: stops at dead code after an unconditional
    `return`/`raise`/`continue`/`break`; resolves a literal `if True:`/
    `if False:` to only the taken branch; and never descends into a nested
    `def`/`async def` — conservative by design (an uncalled nested function
    must not count, and every real pin in this repo already writes its
    assert directly in the collected test's own body, so this costs nothing
    real while closing the gap).
    """
    found: list[ast.Assert] = []
    for stmt in stmts:
        if isinstance(stmt, ast.Assert):
            found.append(stmt)
        elif isinstance(stmt, ast.If):
            test = stmt.test
            if isinstance(test, ast.Constant):
                branch = stmt.body if test.value else stmt.orelse
                found.extend(_reachable_asserts(branch))
            else:
                found.extend(_reachable_asserts(stmt.body))
                found.extend(_reachable_asserts(stmt.orelse))
        elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            found.extend(_reachable_asserts(stmt.body))
            found.extend(_reachable_asserts(stmt.orelse))
        elif isinstance(stmt, ast.Try):
            found.extend(_reachable_asserts(stmt.body))
            for handler in stmt.handlers:
                found.extend(_reachable_asserts(handler.body))
            found.extend(_reachable_asserts(stmt.orelse))
            found.extend(_reachable_asserts(stmt.finalbody))
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            found.extend(_reachable_asserts(stmt.body))
        if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
            break  # everything after is dead code
    return found


def _parametrize_names(node: ast.expr) -> list[str] | None:
    """The argument-name list of a `@pytest.mark.parametrize(names, ...)`
    call, from either spelling pytest accepts: a comma-separated string
    (`"label,expected"`) or a list/tuple of name strings. `None` if `node`
    isn't a recognisable name spec."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [part.strip() for part in node.value.split(",")]
    if isinstance(node, (ast.List, ast.Tuple)):
        names: list[str] = []
        for elt in node.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                return None
            names.append(elt.value)
        return names
    return None


def _indirect_params(deco: ast.Call, names: list[str]) -> set[str] | None:
    """The parameter names this `@pytest.mark.parametrize` call routes
    through a FIXTURE rather than passing to the test directly.

    #325. Under `indirect`, pytest hands each value to a fixture of the same
    name and passes the FIXTURE'S return value to the test. The fixture may
    transform, clamp or ignore the value, so a literal in the decorator does
    not prove what the assert compares against — such a case must not count
    as a literal pin.

    `indirect` takes two static VALUE shapes: a bool (all names, or none) and
    a list/tuple of the names to route. It also has two ARRIVAL paths, and
    #325's first fix read only one of them. pytest's signature is
    ``parametrize(argnames, argvalues, indirect=False, ids=None, scope=None)``,
    so ``@pytest.mark.parametrize("expected", [0.001], True)`` is a real,
    working indirect parametrize with no ``indirect=`` text anywhere in it.
    Measured on pytest 8.4.2: the test receives the fixture's return value,
    not `0.001`. The positional third argument is therefore resolved FIRST,
    before the keyword scan.

    Returns `None` when `indirect` is present but cannot be resolved
    statically — a bare name, a call, or a `**kwargs` splat that could be
    hiding `indirect=True`. The caller must treat `None` as "assume indirect
    and count nothing": a detector that OVER-counts pins is the failure this
    file exists to prevent, so the unknown case fails closed. That posture is
    identical on both arrival paths.
    """

    def _resolve(node: ast.expr) -> set[str] | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return set(names) if node.value else set()
        if isinstance(node, (ast.List, ast.Tuple)):
            listed: set[str] = set()
            for elt in node.elts:
                if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                    return None
                listed.add(elt.value)
            return listed
        return None

    if len(deco.args) > 2:
        # pytest: parametrize(argnames, argvalues, indirect, ids, scope).
        # A positional `indirect` and an `indirect=` keyword cannot both be
        # present (Python raises TypeError), so there is no precedence
        # question. An `*args` splat here is an `ast.Starred`, which
        # `_resolve` cannot read and so fails closed.
        return _resolve(deco.args[2])
    for keyword in deco.keywords:
        if keyword.arg is None:
            return None  # **kwargs splat: `indirect` may be in there
        if keyword.arg != "indirect":
            continue
        return _resolve(keyword.value)
    return set()


def _parametrize_literal_params(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Parameter names that `@pytest.mark.parametrize` binds to a LITERAL
    value on every case, for `func`.

    #145 gap 2, the parametrize form the issue names as "the natural way to
    write 13 pins": `@pytest.mark.parametrize('expected', [0.001])` /
    `assert CONST == expected`. `expected` is an `ast.Name` at the assert
    site — `_is_literal` alone can never see it, since the literal value
    lives in the decorator, not the comparison. A name only counts if EVERY
    parametrize case supplies a literal for it — one symbolic case (e.g. a
    value computed from another constant) means the assert does not prove
    the constant against a literal on every run, so it must not count as a
    pin (the negative partner in
    `test_a_parametrized_non_literal_does_not_pin_the_constant`).

    #325: a name routed through a fixture by `indirect` is not bound to the
    decorator's literal at all — see `_indirect_params`, whose unresolvable
    case is treated as indirect so the detector never over-counts pins.
    """
    literal_params: set[str] = set()
    for deco in func.decorator_list:
        if not isinstance(deco, ast.Call):
            continue
        target = deco.func
        if not (
            isinstance(target, ast.Attribute)
            and target.attr == "parametrize"
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "mark"
        ):
            continue
        if len(deco.args) < 2:
            continue
        names = _parametrize_names(deco.args[0])
        values_node = deco.args[1]
        if names is None or not isinstance(values_node, (ast.List, ast.Tuple)):
            continue
        indirect = _indirect_params(deco, names)
        if indirect is None:
            continue  # #325: cannot resolve `indirect` -> assume all of them are
        cases = values_node.elts
        if not cases:
            continue
        literal_for_name = dict.fromkeys(names, True)
        for case in cases:
            if len(names) == 1:
                case_values: list[ast.expr] | None = [case]
            elif isinstance(case, (ast.List, ast.Tuple)) and len(case.elts) == len(names):
                case_values = case.elts
            else:
                case_values = None
            if case_values is None:
                for name in names:
                    literal_for_name[name] = False
                continue
            for name, value in zip(names, case_values, strict=True):
                if not _is_literal(value):
                    literal_for_name[name] = False
        literal_params.update(
            name for name, ok in literal_for_name.items() if ok and name not in indirect
        )
    return literal_params


def _pins_in_file(path: pathlib.Path) -> set[str]:
    """Constants compared with `==` to a LITERAL inside a REACHABLE assert of
    a COLLECTED test in `path`.

    Split from `_literally_pinned_constants` so it can be unit-tested against
    a synthetic file. Parsed with `ast`, per file — NOT a grep over
    concatenated sources. A grep was the first implementation and it
    accepted, all measured:
      * `assert costs.DAILY_CAP_USD == costs.HARD_LIMIT_USD` (purely symbolic),
      * a commented-out assertion,
      * an assertion inside a string literal in an unrelated file.
    Each satisfied "bucket A is pinned" while pinning nothing.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
        return set()
    origins = _imported_from(tree)
    pinned: set[str] = set()
    for func in _collected_test_functions(tree):
        literal_params = _parametrize_literal_params(func)
        for assert_node in _reachable_asserts(func.body):
            for cmp_node in ast.walk(assert_node.test):
                if not isinstance(cmp_node, ast.Compare):
                    continue
                if not all(isinstance(op, ast.Eq) for op in cmp_node.ops):
                    continue
                sides = [cmp_node.left, *cmp_node.comparators]
                for index, side in enumerate(sides):
                    qualified = _qualify(side, origins)
                    if not qualified:
                        continue
                    others = [s for j, s in enumerate(sides) if j != index]
                    if any(
                        _is_literal(other)
                        or (isinstance(other, ast.Name) and other.id in literal_params)
                        for other in others
                    ):
                        pinned.add(qualified)
    return pinned


def _literally_pinned_constants() -> set[str]:
    """`_pins_in_file`, unioned over every test file in the repo."""
    pinned: set[str] = set()
    for path in TESTS.rglob("test_*.py"):
        pinned |= _pins_in_file(path)
    return pinned


# ---------------------------------------------------------------------------
# The pins themselves. Each is a literal, so changing the constant fails here.
# ---------------------------------------------------------------------------


def test_money_constants_are_pinned_to_their_literal_values() -> None:
    """Turns red if: any spend rail moves. That is the point — it must be reviewed.

    A PIN IS NOT A VALIDATION. This makes a change visible; it does not say the
    value is right. **#151, resolved 2026-08-01**: `_DEFAULT_PRICE_PER_1K_INPUT`
    / `_OUTPUT` were a hand-picked 0.0008 / 0.002 that, against the four
    shipped default models, OVER-charged three (5.3x, 2.7x, and 16.0x for
    nvidia — the recorded "16x mispricing") while UNDER-charging
    anthropic/claude-haiku-4.5 by 25% — the unsafe direction for a spend cap.
    Now DERIVED (`costs.py`, next to the constants): the max real input/output
    price across `DEFAULT_MODEL_IDS`, read from `_FALLBACK_CATALOG` — 0.001 /
    0.005, conservative for every shipped model by construction.
    `test_default_price_floor_never_undercharges_a_shipped_model` (this file)
    pins that PROPERTY independently of this literal, so a future re-add of
    a fifth default model with an even higher real price is still caught even
    if this literal pin is updated to match a bad value by mistake.

    These are statements about real money.
    """
    assert Decimal("0.15") == costs.SOFT_THRESHOLD_USD
    assert Decimal("0.20") == costs.DAILY_CAP_USD
    assert Decimal("0.25") == costs.HARD_LIMIT_USD
    assert Decimal("0.001") == costs._DEFAULT_PRICE_PER_1K_INPUT
    assert Decimal("0.005") == costs._DEFAULT_PRICE_PER_1K_OUTPUT
    assert Decimal(4) == costs.CHARS_PER_TOKEN
    assert Decimal("0.0001") == costs.COST_DISPLAY_QUANTUM
    assert timedelta(minutes=5) == costs.CONFIRMATION_TOKEN_TTL


def test_default_price_floor_never_undercharges_a_shipped_model() -> None:
    """#151: the floor must be >= every DEFAULT_MODEL_IDS model's real
    fallback-catalog price, in both directions — independent of the exact
    derivation formula, so a future re-derivation (or a new default model
    with a higher real price than today's four) that still under-covers one
    model is caught here even if the literal pin above is updated to match
    a bad value.

    What turns it red: the pre-#151 constants (0.0008 / 0.002) — the
    anthropic/claude-haiku-4.5 row's real input price (0.001) exceeds the
    old input floor, and the real output price (0.005) exceeds the old
    output floor too. Verified by mutation: hardcoding the old literals back
    in reds this test on both assertions for that model.
    """
    catalog = {entry.model_id: entry for entry in catalog_fetcher._FALLBACK_CATALOG}
    for model_id in model_slots.DEFAULT_MODEL_IDS:
        entry = catalog[model_id]
        assert entry.input_price_per_1k <= costs._DEFAULT_PRICE_PER_1K_INPUT, (
            f"{model_id}: floor {costs._DEFAULT_PRICE_PER_1K_INPUT} under-covers "
            f"real input price {entry.input_price_per_1k}"
        )
        assert entry.output_price_per_1k <= costs._DEFAULT_PRICE_PER_1K_OUTPUT, (
            f"{model_id}: floor {costs._DEFAULT_PRICE_PER_1K_OUTPUT} under-covers "
            f"real output price {entry.output_price_per_1k}"
        )


def test_the_spend_rails_keep_their_ordering() -> None:
    """The literals above pin the values; this pins the RELATIONSHIP.

    Neither replaces the other: an ordering assertion still passes if all three
    move together, and literal pins still pass if the ordering is inverted by
    swapping two of them.

    Turns red if: soft >= cap, or cap >= hard.
    """
    assert costs.SOFT_THRESHOLD_USD < costs.DAILY_CAP_USD < costs.HARD_LIMIT_USD


def test_auth_and_transport_constants_are_pinned() -> None:
    """Turns red if: the `__Host-` prefix, the CSRF header name, the session
    lifetime, or the HSTS max-age changes.

    The `__Host-` prefix IS the security control (it forces Secure, host-only,
    path=/). A silently shortened HSTS max-age weakens transport security with
    no other visible symptom.
    """
    assert timedelta(hours=2) == auth.SESSION_TTL
    assert auth._SESSION_COOKIE_NAME_PREFIXED == "__Host-quorum_session"
    assert auth.CSRF_HEADER_NAME == "X-CSRF-Token"
    assert main._HSTS_HEADER == "max-age=31536000; includeSubDomains"


def test_the_session_mint_window_is_pinned() -> None:
    """Turns red if: the rolling window the per-IP mint cap is counted over
    moves off 24 hours.

    Cap and window are ONE control, and only the cap half was pinned. Widening
    the window silently tightens the cap; narrowing it silently loosens a spend
    guard, which is the fail-open direction. Since ADR-0073 the number is also
    user-facing -- the 429 page derives its advertised wait from it -- so a
    change here would quietly make that page lie.

    A literal on both sides deliberately (rule 7a): asserting against
    `SESSION_MINT_WINDOW` itself would move with the code and pin nothing.
    """
    assert timedelta(hours=24) == feedback_store.FeedbackStore.SESSION_MINT_WINDOW


def test_the_rate_limiter_eviction_windows_are_pinned() -> None:
    """Turns red if: either rate limiter's stale-bucket eviction window moves.

    SEC-H3: a scripted /16 IPv4 scan adds one bucket per source IP; without
    eviction that dict grows unbounded. `CAPACITY`/`REFILL_PER_MINUTE` are
    already pinned in `test_session_rate_limit_override.py`
    (`test_production_default_is_ten` / `test_account_limiter_is_pinned_at_thirty`)
    — `STALE_BUCKET_SECONDS` had no pin anywhere before this.
    """
    assert query_runs._InMemoryIpRateLimiter.STALE_BUCKET_SECONDS == 300.0
    assert query_runs._InMemoryAccountRateLimiter.STALE_BUCKET_SECONDS == 300.0


def test_the_slot_count_is_pinned() -> None:
    """Turns red if: EXPECTED_SLOT_COUNT moves.

    It drives the "N of 4" honesty banner — the surface that tells a user how
    many models actually answered.
    """
    assert model_slots.EXPECTED_SLOT_COUNT == 4


def test_every_default_slot_vendor_is_listed_in_default_vendors() -> None:
    """The half of the WP-G1 swap that `test_catalog_fetcher.py:303` does NOT cover.

    That test checks the model id has a catalog ROW. This checks its VENDOR is
    listed — the other thing the half-done slot-4 swap left stale.

    Deliberately a SUBSET check, not equality: an extra entry in
    `DEFAULT_VENDORS` is not a defect (it is the default argument of
    `cheapest_per_vendor`, and `ONLINE_CAPABLE_VENDORS` is documented as living
    *within* it), whereas a slot whose vendor is missing is.

    Turns red if: a slot moves to a vendor absent from DEFAULT_VENDORS.
    """
    from_ids = {model_id.split("/")[0] for model_id in model_slots.DEFAULT_MODEL_IDS}
    assert from_ids, "no default model ids — the comparison below would be vacuous"
    unlisted = sorted(from_ids - set(catalog_fetcher.DEFAULT_VENDORS))
    assert not unlisted, (
        f"default slots use vendors missing from DEFAULT_VENDORS: {unlisted} "
        f"(listed: {sorted(catalog_fetcher.DEFAULT_VENDORS)})"
    )


def test_there_are_exactly_as_many_default_ids_as_slots() -> None:
    """Turns red if: DEFAULT_MODEL_IDS and EXPECTED_SLOT_COUNT drift apart.

    EXPECTED_SLOT_COUNT drives the "N of 4" honesty banner; a mismatch makes
    that banner lie about how many models were asked.
    """
    assert len(model_slots.DEFAULT_MODEL_IDS) == model_slots.EXPECTED_SLOT_COUNT


# ---------------------------------------------------------------------------
# The triage guard: a new constant must be classified, never defaulted.
# ---------------------------------------------------------------------------


def _all_risk_constants() -> dict[str, int]:
    """Module-level AND class-level (#145 gap 3) risk constants, combined."""
    return _module_constants() | _class_constants()


def test_the_registry_is_not_empty() -> None:
    """A guard over an empty collection proves nothing.

    Turns red if: the discovery regex or RISK_TIER_MODULES stops matching.
    """
    discovered = _all_risk_constants()
    assert len(discovered) >= 25, f"only {len(discovered)} constants discovered — glob is wrong"
    class_only = _class_constants()
    assert len(class_only) >= 15, (
        f"only {len(class_only)} class-level constants discovered (#145 gap 3) — glob is wrong"
    )
    assert BUCKET_A_LITERAL_PIN and BUCKET_B_PIN_BEHAVIOUR and BUCKET_C_NO_PIN


def test_every_risk_constant_is_triaged() -> None:
    """A new module- or class-level constant in risk code must be put in a
    bucket.

    This is the load-bearing test. Without it, a new spend rail or auth value
    lands with no pin and nothing notices — which is exactly the state measured
    before this file existed (3 of 30 pinned).

    Turns red if: a constant is added to a risk-tier module (or a non-enum
    class inside one) and not classified.
    """
    discovered = set(_all_risk_constants())
    triaged = set(BUCKET_A_LITERAL_PIN) | set(BUCKET_B_PIN_BEHAVIOUR) | set(BUCKET_C_NO_PIN)

    untriaged = sorted(discovered - triaged)
    assert not untriaged, (
        f"module- or class-level constants in risk-tier code with no bucket: "
        f"{untriaged}. Decide: A (literal pin - a wrong value is silently "
        "harmful), B (pin the behaviour - the value legitimately changes), or "
        "C (no pin - with a one-line reason). Nothing defaults."
    )


def test_the_registry_names_no_constant_that_has_been_deleted() -> None:
    """A registry naming removed symbols rots into a comment.

    Turns red if: a triaged constant is renamed or deleted without updating
    this file.
    """
    discovered = set(_all_risk_constants())
    triaged = set(BUCKET_A_LITERAL_PIN) | set(BUCKET_B_PIN_BEHAVIOUR) | set(BUCKET_C_NO_PIN)
    stale = sorted(triaged - discovered)
    assert not stale, f"triaged constants that no longer exist: {stale}"


def test_every_bucket_a_constant_really_has_a_literal_pin() -> None:
    """Bucket A is a promise; this checks the promise is kept.

    Keys off a literal `== <literal>` comparison in a test, not a mere mention:
    `assert x < DAILY_CAP_USD` is a symbolic reference that moves with the code
    and is exactly what this file exists to replace.

    Turns red if: a constant is added to BUCKET_A_LITERAL_PIN without writing
    its pin (verified by adding a name with no assertion).
    """
    pinned = _literally_pinned_constants()
    missing = sorted(q for q in BUCKET_A_LITERAL_PIN if q not in pinned)
    assert not missing, (
        f"bucket A names these but no test compares them to a LITERAL: {missing}. "
        "A symbolic assertion (`assert rendered == CONSTANT`) is not a pin — it "
        "moves with the code."
    )


def test_bucket_c_entries_each_carry_a_reason() -> None:
    """A silent exemption is the same failure in a new coat.

    Turns red if: a constant is exempted with an empty or placeholder reason.
    """
    thin = sorted(k for k, v in BUCKET_C_NO_PIN.items() if len(v.strip()) < 20)
    assert not thin, f"bucket C entries with no real reason: {thin}"


# ---------------------------------------------------------------------------
# Detector self-tests (#145): the three known gaps, each closed and proven in
# both directions on a synthetic file/expression — never the real risk
# modules or tests/, so these do not depend on anything else in this repo.
# ---------------------------------------------------------------------------


def test_an_assert_inside_if_false_is_not_a_pin(tmp_path: pathlib.Path) -> None:
    """#145 gap 1, the exact repro from the issue.

    Turns red if: the reachability filter in `_pins_in_file` regresses and
    unreachable code counts as a pin again.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "from product_app import costs\n\n"
        "def test_fake_pin() -> None:\n"
        "    if False:\n"
        "        assert costs._DEFAULT_PRICE_PER_1K_INPUT == 999999\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_an_assert_in_a_skipped_test_is_not_a_pin(tmp_path: pathlib.Path) -> None:
    """#145 gap 1."""
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.skip(reason='wip')\n"
        "def test_fake_pin() -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == 999999\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_an_assert_in_an_uncalled_nested_function_is_not_a_pin(
    tmp_path: pathlib.Path,
) -> None:
    """#145 gap 1."""
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "from product_app import costs\n\n"
        "def test_fake_pin() -> None:\n"
        "    def _never_called() -> None:\n"
        "        assert costs._DEFAULT_PRICE_PER_1K_INPUT == 999999\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_an_assert_after_an_unconditional_return_is_dead_code(
    tmp_path: pathlib.Path,
) -> None:
    """#145 gap 1: dead code after `return` is a fourth unreachability shape
    the issue names alongside `if False:`, skip, and uncalled nested defs."""
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "from product_app import costs\n\n"
        "def test_fake_pin() -> None:\n"
        "    return\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == 999999\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_a_reachable_assert_in_a_collected_test_is_still_a_pin(
    tmp_path: pathlib.Path,
) -> None:
    """Positive partner (rule 7) for the four negative checks above: the
    detector must still catch the ordinary case, or the four checks above
    would be trivially true over a detector that finds nothing at all."""
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "from product_app import costs\n\n"
        "def test_real_pin() -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == 0.001\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" in _pins_in_file(synthetic)


def test_a_parametrized_literal_pins_the_constant(tmp_path: pathlib.Path) -> None:
    """#145 gap 2, the parametrize form: the issue names
    `@pytest.mark.parametrize('expected', [0.001])` /
    `assert CONST == expected` as "the natural way to write 13 pins", and it
    was not handled — `_is_literal` only resolves the argument as an
    `ast.Name` with no branch for a parametrize-bound value, so `expected`
    read as symbolic and the assert did not count as a pin.

    Turns red if `_pins_in_file` (or the parametrize resolution inside it)
    regresses to ignoring parametrize-bound values again.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('expected', [0.001])\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" in _pins_in_file(synthetic)


def test_a_parametrized_non_literal_does_not_pin_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """Negative partner: if even one case in the parametrize list is not a
    literal (e.g. computed from another symbol), the bound name must not be
    treated as a pin — it does not prove the constant against a literal on
    every call."""
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "_OTHER = costs._DEFAULT_PRICE_PER_1K_INPUT\n\n"
        "@pytest.mark.parametrize('expected', [_OTHER])\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_a_parametrized_multi_arg_literal_pins_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """The multi-argname `parametrize("name,expected", [(...), ...])` shape,
    matched positionally against each tuple case."""
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('label,expected', [('a', 0.001), ('b', 0.002)])\n"
        "def test_fake_pin(label, expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" in _pins_in_file(synthetic)


def test_an_indirect_parametrize_does_not_pin_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """#325: `indirect=True` routes every parametrize value through a FIXTURE
    of the same name before the test ever sees it. The fixture can transform
    the value, clamp it, or ignore it entirely, so the literal in the
    decorator proves nothing about what the assert compares against — the
    constant is NOT pinned to that literal.

    Turns red if: `_parametrize_literal_params` stops reading `indirect=` and
    counts an indirect case as a literal pin again.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('expected', [0.001], indirect=True)\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_an_indirect_list_naming_the_param_does_not_pin_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """#325, the other spelling: `indirect` may be a LIST of argument names
    rather than `True`, making only those names fixture-routed. A name in
    that list is exactly as unpinned as under `indirect=True`.

    Turns red if: only the `indirect=True` form is handled and the list form
    still counts as a literal pin.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('expected', [0.001], indirect=['expected'])\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_an_unresolvable_indirect_value_is_treated_as_indirect(
    tmp_path: pathlib.Path,
) -> None:
    """#325, the conservative direction. When `indirect=` is a name, a call
    or anything else this AST pass cannot resolve, the detector cannot know
    which parameters are fixture-routed. Over-counting pins is the failure
    mode this whole file exists to prevent, so an unresolvable `indirect`
    counts NOTHING from that decorator.

    Turns red if: an unrecognised `indirect` value falls through to "direct"
    and the literal is counted as a pin.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "_ROUTE = True\n\n"
        "@pytest.mark.parametrize('expected', [0.001], indirect=_ROUTE)\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_a_splatted_keyword_on_parametrize_is_treated_as_indirect(
    tmp_path: pathlib.Path,
) -> None:
    """#325, the second unresolvable shape: `**kwargs` on the decorator call
    could carry `indirect=True` and is invisible to a static read of
    `deco.keywords[*].arg`, which is `None` for a splat.

    Turns red if: a `**kwargs` splat is ignored rather than treated as
    possibly-indirect, letting the literal count as a pin.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "_OPTS = {'indirect': True}\n\n"
        "@pytest.mark.parametrize('expected', [0.001], **_OPTS)\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_an_indirect_list_naming_another_param_still_pins_this_one(
    tmp_path: pathlib.Path,
) -> None:
    """POSITIVE PARTNER for #325 (rule 7). `indirect=['label']` routes only
    `label` through a fixture; `expected` is still passed directly, so its
    literal still pins the constant. Without this partner the four negative
    checks above would be satisfied by a detector that simply refused every
    parametrize carrying an `indirect` keyword at all.

    Turns red if: any `indirect=` keyword disqualifies the whole decorator
    instead of only the names it actually lists.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize("
        "'label,expected', [('a', 0.001)], indirect=['label'])\n"
        "def test_fake_pin(label, expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" in _pins_in_file(synthetic)


def test_an_explicit_indirect_false_still_pins_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """POSITIVE PARTNER for #325. `indirect=False` is pytest's default spelt
    out; it must behave exactly like omitting the keyword.

    Turns red if: the presence of the `indirect` keyword, rather than its
    value, is what disqualifies the pin.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('expected', [0.001], indirect=False)\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" in _pins_in_file(synthetic)


def test_a_positional_indirect_true_does_not_pin_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """#325 review round. `indirect` is pytest's THIRD POSITIONAL parameter
    (`parametrize(argnames, argvalues, indirect=False, ids=None, scope=None)`),
    so `@pytest.mark.parametrize('expected', [0.001], True)` is genuinely
    indirect while containing no `indirect=` text at all. Measured on pytest
    8.4.2 with a fixture that multiplies by 1000: the test received `1.0`,
    not `0.001`. The first #325 fix read `deco.keywords` only and counted
    this as a literal pin.

    Turns red if: `_indirect_params` stops reading `deco.args[2]`.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('expected', [0.001], True)\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_a_positional_indirect_list_does_not_pin_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """#325 review round, the list spelling of the positional argument.
    Verified to run under pytest 8.4.2 the same way `True` does.

    Turns red if: the positional slot is read but only the bool shape is
    resolved, letting the list form fall through to "direct".
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('expected', [0.001], ['expected'])\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_a_positional_indirect_false_still_pins_the_constant(
    tmp_path: pathlib.Path,
) -> None:
    """POSITIVE PARTNER for the positional read (rule 7). Without it, the two
    negatives above are satisfied by a detector that simply disqualifies any
    decorator carrying a third positional argument. `indirect=False` written
    positionally is pytest's default spelt out and must still pin.

    Turns red if: the positional branch returns "all names are indirect"
    (or `None`) regardless of the argument's value.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('expected', [0.001], False)\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" in _pins_in_file(synthetic)


def test_a_positional_indirect_list_naming_another_param_still_pins_this_one(
    tmp_path: pathlib.Path,
) -> None:
    """SECOND POSITIVE PARTNER for the positional read. A positional list
    that names only `label` leaves `expected` passed directly, exactly as the
    keyword spelling does, so the literal still pins the constant.

    Turns red if: the positional branch treats a list as "all names are
    indirect" instead of resolving which names it actually contains.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "@pytest.mark.parametrize('label,expected', [('a', 0.001)], ['label'])\n"
        "def test_fake_pin(label, expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" in _pins_in_file(synthetic)


def test_an_unresolvable_positional_indirect_is_treated_as_indirect(
    tmp_path: pathlib.Path,
) -> None:
    """#325 review round, the conservative direction on the positional path.
    A name in the third slot cannot be resolved statically, so the detector
    must assume it routes everything through a fixture and count no pin —
    the same posture the keyword path already takes.

    Turns red if: the positional branch resolves only bool/list and then
    falls through to the keyword scan (which finds no `indirect=` and returns
    "nothing is indirect") instead of returning `None`.
    """
    synthetic = tmp_path / "test_synthetic.py"
    synthetic.write_text(
        "import pytest\n"
        "from product_app import costs\n\n"
        "_ROUTE = True\n\n"
        "@pytest.mark.parametrize('expected', [0.001], _ROUTE)\n"
        "def test_fake_pin(expected) -> None:\n"
        "    assert costs._DEFAULT_PRICE_PER_1K_INPUT == expected\n"
    )
    assert "costs._DEFAULT_PRICE_PER_1K_INPUT" not in _pins_in_file(synthetic)


def test_is_literal_accepts_pytest_approx_over_a_literal() -> None:
    """#145 gap 2."""
    node = ast.parse("pytest.approx(0.0008)", mode="eval").body
    assert _is_literal(node)


def test_is_literal_accepts_the_bare_approx_import_form() -> None:
    """#145 gap 2: `from pytest import approx` is the other spelling in use."""
    node = ast.parse("approx(0.0008, rel=0.01)", mode="eval").body
    assert _is_literal(node)


def test_is_literal_rejects_approx_over_a_non_literal() -> None:
    """Negative partner: `pytest.approx(some_var)` is symbolic, not a pin."""
    node = ast.parse("pytest.approx(some_var)", mode="eval").body
    assert not _is_literal(node)


def test_is_literal_accepts_tuple_list_set_and_dict_literals() -> None:
    """#145 gap 2: container literals, rejected before, now accepted."""
    assert _is_literal(ast.parse("(1, 2, 3)", mode="eval").body)
    assert _is_literal(ast.parse("[1, 2, 'x']", mode="eval").body)
    assert _is_literal(ast.parse("{1, 2, 3}", mode="eval").body)
    assert _is_literal(ast.parse("{'a': 1, 'b': 2}", mode="eval").body)


def test_is_literal_rejects_a_container_holding_a_name() -> None:
    """Negative partner: one non-literal element taints the whole container,
    same reasoning as the existing zero-arg-call guard below it."""
    assert not _is_literal(ast.parse("(1, some_var)", mode="eval").body)
    assert not _is_literal(ast.parse("{'a': some_var}", mode="eval").body)


def test_class_constants_are_discovered_but_enum_members_are_not(
    tmp_path: pathlib.Path,
) -> None:
    """#145 gap 3, and the reason `_ENUM_BASE_NAMES` exists: enum membership
    is issue #160's surface, not this file's, so an enum's ALL-CAPS members
    must stay invisible here even though they satisfy `_CONST_NAME`."""
    synthetic = tmp_path / "fake_module.py"
    synthetic.write_text(
        "from enum import StrEnum\n\n"
        "class RealEnum(StrEnum):\n"
        "    ONE = 'one'\n"
        "    TWO = 'two'\n\n"
        "class Settings:\n"
        "    RUN_DEADLINE_MAX_SECONDS = 3600.0\n"
        "    lowercase_field: int = 1\n"
    )
    found = _class_constants_in(synthetic, "fake_module")
    assert set(found) == {"fake_module.Settings.RUN_DEADLINE_MAX_SECONDS"}


def test_class_constants_not_hidden_by_a_locally_named_enum_lookalike(
    tmp_path: pathlib.Path,
) -> None:
    """Adversarial-review finding on this PR: `_ENUM_BASE_NAMES` used to match
    by BARE IDENTIFIER TEXT (`base_names & _ENUM_BASE_NAMES`), not by actual
    provenance. A risk-tier class could be made fully invisible to the pin
    detector just by naming an unrelated local class `Enum` and inheriting
    from it — no relation to python's stdlib `enum` module at all.

    Turns red if `_class_constants_in` goes back to matching a base by its
    bare `ast.Name.id` instead of checking it resolves to a real
    `from enum import ...` binding: the fake `Enum` base would once again
    swallow `_InMemoryIpRateLimiter`'s three constants, and `found` would come
    back empty instead of holding all three.
    """
    synthetic = tmp_path / "fake_risk_module.py"
    synthetic.write_text(
        "class Enum:\n"
        "    pass\n\n"
        "class _InMemoryIpRateLimiter(Enum):\n"
        "    CAPACITY = 10\n"
        "    REFILL_PER_MINUTE = 5\n"
        "    STALE_BUCKET_SECONDS = 300.0\n"
    )
    found = _class_constants_in(synthetic, "fake_risk_module")
    assert set(found) == {
        "fake_risk_module._InMemoryIpRateLimiter.CAPACITY",
        "fake_risk_module._InMemoryIpRateLimiter.REFILL_PER_MINUTE",
        "fake_risk_module._InMemoryIpRateLimiter.STALE_BUCKET_SECONDS",
    }


def test_class_constants_still_hidden_for_a_real_enum_alias(
    tmp_path: pathlib.Path,
) -> None:
    """Positive partner (rule 7): the provenance check must still recognise a
    genuine `from enum import StrEnum as SE` alias as an enum base, not just
    the unaliased name — otherwise the fix above would over-correct and start
    pinning real enum members (issue #160's surface, not this file's)."""
    synthetic = tmp_path / "fake_module_alias.py"
    synthetic.write_text(
        "from enum import StrEnum as SE\n\n"
        "class RealEnum(SE):\n"
        "    ONE = 'one'\n\n"
        "class Settings:\n"
        "    TIMEOUT_SECONDS = 30\n"
    )
    found = _class_constants_in(synthetic, "fake_module_alias")
    assert set(found) == {"fake_module_alias.Settings.TIMEOUT_SECONDS"}


def test_the_catalog_fetchable_schemes_are_pinned() -> None:
    """Turns red if: `_FETCHABLE_SCHEMES` gains or loses a scheme.

    A LITERAL pin, which is what bucket A means. Both members matter and they
    fail in opposite directions: without `https` every production catalog fetch
    raises, and with `file` an operator's typo becomes an arbitrary local-file
    read whose contents are served as the live price catalog (ADR-0080).

    `tests/unit/test_catalog_fetcher.py` asserts the BEHAVIOUR either side of
    this set; this asserts the set itself, so a widening cannot slip in behind
    a behaviour test that only ever tries the schemes it already knows about.
    """
    from product_app import catalog_fetcher

    assert frozenset({"http", "https"}) == catalog_fetcher._FETCHABLE_SCHEMES
