# ADR-0047: Unscoped event-recorder reads are gated by an annotated waiver, not a blanket ban

## Status

Accepted — 2026-08-15 (#209, follow-up to #104 item 1)

## Context

`product_app` exposes six in-memory event recorders as **process globals**:
`provider_event_recorder`, `debate_event_recorder`, `synthesis_event_recorder`,
`warning_event_recorder`, `model_slot_event_recorder` and
`cost_event_recorder`. Every test in the session shares them.

**Nothing clears them globally.** `tests/conftest.py::_reset_state` (autouse,
before and after every test) resets the query-run repository, the session
repository, both rate limiters, the evaluation memo and the store-reconnect
globals — and none of the six event recorders. Measured: 29 of 254 test files
clear at least one recorder themselves
(`grep -rln "def clear_state\|_event_recorder.clear()" tests/ | wc -l`).

Every module holding one of the reads fixed here IS in that 29 and DOES clear
the recorder it reads — checked per file, not assumed. So the exposure at these
sites is not the trivial "nobody ever cleared it" case; it is the race.
Clearing does not make a read safe: a background query-run worker thread
started by an earlier test (the cookie/CSRF path in `create_query_run` runs the
pipeline in a `Thread`; only the legacy `X-Account-Id` path is inline —
`query_runs.py:803`) can be in flight and append to the same buffer *after* the
clear. #104 measured that: 1 of 14 sequential runs of one test saw
`len(provider_events) == 6` where the test expected 4.

Measured on `origin/main` at `dd154ee` with the AST scanner added in this PR:
**35** `list_events()` call sites under `tests/`. Two were already filtered by
hand (`tests/e2e/test_release_hardening_workflow.py`, the #104 fix; and
`tests/integration/test_query_run_cost_guardrails.py`'s `_events_for`), and
three belong to one security sweep that must not be filtered. The other
**30** were counts, indexes or `all(...)` reads over the whole shared buffer.

The decision this ADR records is not "scope the reads" — that part is
uncontested. It is **how the fix is kept applied**, given that one read in the
suite is correct *because* it is unscoped.

## Decision

**Two mechanisms, in one commit.**

1. **One shared filter.** `tests.helpers.scoped_events(recorder, *,
   account_id=..., query_run_id=...)` returns only the events matching the
   given scope, and **raises `ValueError` when neither key is supplied** — a
   no-key call would be an unfiltered read wearing the helper's name. All six
   recorders' event types carry `account_id` and `query_run_id`, so one
   `Protocol`-typed helper covers all of them. 34 call sites now use it — 28
   in real assertions plus 6 in the helper's own tests.

2. **An AST guard with an in-place annotated waiver.**
   `tests/unit/test_event_recorder_reads_are_scoped.py` parses every file under
   `tests/` and fails on any `list_events()` call that does not carry an
   `# unscoped-ok: <reason>` comment **inside the statement that performs the
   read**, with a reason of at least 20 characters. The waiver *is* the
   allowlist: there is no separate list of exempt paths to drift out of date,
   and a waiver cannot be added without writing down why.

   The guard refuses to pass having measured nothing: it asserts it parsed
   ≥ 200 files, found ≥ 4 call sites, found ≥ 2 waivers naming the two files
   that legitimately hold them, and found ≥ 20 `scoped_events` call sites — so
   a future change that deletes the fix, or that stops the scanner seeing
   anything, goes red rather than green.

**Why a waiver rather than a ban.**
`tests/security/test_release_security_redaction.py` proves the OpenRouter key
never reaches ANY recorded event. Its three reads are `repr()`-then-substring-
absence checks over the whole buffer. Narrowing them to one account would make
a leak into any *other* account's event invisible — it would delete exactly the
coverage the test exists for. A blanket ban would have forced that test to be
rewritten worse, or forced an opaque path-based exemption list. The absence
shape is also why the waiver is safe here: a foreign event can only make a
substring-absence assertion stricter, never falsely green — the opposite of the
count/index reads that #209 scoped.

## Measured

| Question | Command | Result |
|---|---|---|
| `list_events()` call sites under `tests/` on `origin/main` | the PR's `_scan_test_suite()` against `dd154ee` | 35 |
| of those, unfiltered count/index/`all` reads | same scan, minus 3 security-sweep and 2 hand-filtered | 30 |
| call sites after the fix | `_scan_test_suite()` | 5, all waived; 0 unwaived |
| `scoped_events()` call sites after the fix | same | 34 (28 in assertions, 6 in the helper's own tests) |
| test files parsed by the guard | same | 254 |
| guard bites on a planted unfiltered read | reverted one read in `tests/unit/test_debate_orchestration.py:85` | RED, naming the file and line |
| guard bites on a one-word waiver | added `# unscoped-ok: meh` to that read | RED: *"waiver reason is too short: 'meh'"* |
| helper bites | `scoped_events` mutated to return `recorder.list_events()` | 4 of 5 helper tests RED |
| recorder buffers really are shared across tests | instrumented probe stamping each event with the pytest nodeid that recorded it, 3 full-suite runs | 384,255 / 383,833 / 385,032 observations of a test seeing another test's event |
| a foreign event arriving AFTER the reading test's own clear (the #104 race) | same probe, narrowed to recorders the reading test itself cleared, 5 full-suite runs | **0, 0, 0, 0, 0 — NOT reproduced** |
| the affected files flaking | 14 sequential runs of `tests/integration tests/e2e tests/perf tests/security` plus the three vulnerable unit modules | 14/14 green — no flake observed |
| an ordering dependency introduced by this change | full suite with test paths passed in 3 different orders | alphabetical (what CI runs) and unit-first both 2980 passed / 0 failed; a third order produced 1 failure, a DIFFERENT test on each of its two runs (`test_evaluation_persistence_is_idempotent`, then `test_mutation_copy_completeness`), neither file touched here and neither reading an event recorder — see Consequences |

## Rejected alternatives

- **A blanket ban on `list_events()` in `tests/`.** Rejected: it would force
  `test_release_security_redaction.py` to narrow a sweep whose whole value is
  that it is not narrowed, or to route around the ban some other way. A rule
  that forbids a correct piece of code gets worked around rather than followed.
- **A path-based allowlist inside the guard** (a `set` of exempt files).
  Rejected: it drifts silently — a file can be renamed, or a second unrelated
  read added to an already-exempt file, with nothing noticing. The in-place
  annotation is attached to the read itself and cannot be inherited by a
  neighbouring one.
- **Clearing all six recorders in `tests/conftest.py::_reset_state`.** This
  would close the common, deterministic case (a module with no clearing
  fixture reading events from earlier tests) but NOT the case #104 measured: a
  worker thread that appends after the clear, during the next test. It also
  cannot be proven to bite — a fixture that clears more is invisible to every
  assertion once the reads are scoped. Not done here; scoping subsumes it.
- **Making each recorder per-test instead of process-global** (a fixture that
  swaps in a fresh instance, as `tests/helpers.isolated_run_semaphore` does for
  the run semaphore). This is the stronger fix and is NOT rejected on merit —
  it is out of scope for #209, which is a test-hygiene issue, and it would
  change `src/` module state that production also reads. Left as a possible
  follow-up; the guard added here does not block it, and would keep holding if
  it landed.
- **Filtering by `event_type` instead of by run/account.** Rejected: measured
  insufficient at `tests/integration/test_cancel_during_initial_answers_records_event.py`,
  where a `provider_initial_answer_cancelled` event from another test's run
  satisfies the type filter and then fails the `query_run_id` assertion. Type
  is not identity.

## Consequences

- **The #104 race was NOT reproduced in this work — say so, do not imply
  otherwise.** 14 sequential runs of the affected files were 14/14 green, and
  the instrumented probe found 0 post-clear foreign events in 5 full-suite
  runs. #104's 1-in-14 figure is INHERITED, not re-measured here.
  What the probe DID measure, and what does hold: the buffers are genuinely
  shared, with ~384,000 observations per full-suite run of a test seeing an
  event another test recorded. Every module holding a fixed read clears the
  recorder it reads, which is why those specific sites showed nothing — their
  exposure is the narrow post-clear window, and this machine did not hit it.
  The justification is therefore the mechanism plus #104's measurement, plus
  the deterministic demonstration in
  `tests/e2e/test_release_hardening_workflow.py`, which plants a foreign event
  into all four recorders and shows each unfiltered read going red on it.
- **One of the three shuffled full-suite orders shows a single failure, and it
  is not this change.** Passing the test paths as
  `tests/*.py accessibility contract evals resilience e2e integration perf
  security unit` failed once on
  `test_query_run_evaluation_endpoint.py::test_evaluation_persistence_is_idempotent`
  and, on a second run of the very same order, once on a completely different
  test (`test_mutation_copy_completeness.py::test_the_real_copy_runs_the_root_reading_specs`,
  whose failure text is about nested-pytest temp-dir collection). Two different
  single failures in two runs of one order is non-determinism, not an order
  dependency this diff created: neither file is touched here, neither reads an
  event recorder, and the first asserts `run_count() == 1` over
  `run_history_store` — a different global. The order CI actually uses
  (alphabetical, no path arguments) is green in `make quality`, in
  `make diff-cover`'s run, and in the shuffle. NOT chased further and NOT
  filed here; recorded so the next reader does not re-derive it from scratch.
- Reads that must span every writer are now visible: `grep -rn "unscoped-ok"
  tests/` enumerates them, with the argument for each.
- `tests/integration/test_query_run_cost_guardrails.py::_events_for` survives
  as a thin wrapper over `scoped_events` — it carries the module's own reason
  and shortens its 14 call sites in that file. It moved above its first use.
- Two assertions gained a positive partner while being scoped, because
  scoping made their vacuity visible: `all(event.fallback_used for ...)` in
  `test_query_run_provider_stubs.py` (trivially true over an empty list — now
  paired with `len(events) == 4`), and the three absence checks in
  `test_release_security_redaction.py` (now paired with 4/2/1 event-count
  assertions for the run under test). Neither assertion was weakened.

## Related

- #209, #104 item 1
- `tests/helpers.py` (`scoped_events`, `ScopedEvent`, `EventRecorder`)
- `tests/unit/test_scoped_events_helper.py`,
  `tests/unit/test_event_recorder_reads_are_scoped.py`
- ADR-0038 (a guard proves it bites by mutating the artifact it asserts about)
- AGENTS.md rule 16a (process-global test state), rule 7 (a negative check
  needs a positive partner)
