# ADR-0049: Unscoped event-recorder reads are gated by an annotated waiver, not a blanket ban

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
three belonged to one security sweep that must not be filtered (that sweep is
six reads now — it was missing three of the six recorders). The other **30**
were counts, indexes or `all(...)` reads over the whole shared buffer.

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
   `Protocol`-typed helper covers all of them. 37 call sites now use it — 31
   in real assertions plus 6 in the helper's own tests
   (`_scan_test_suite()` → `scoped 37`).

2. **An AST guard with an in-place annotated waiver.**
   `tests/unit/test_event_recorder_reads_are_scoped.py` parses every file under
   `tests/` and fails on any `list_events()` call that does not carry an
   `# unscoped-ok: <reason>` comment **inside the statement that performs the
   read**, with a reason of at least 20 characters. The waiver *is* the
   allowlist: there is no separate list of exempt paths to drift out of date,
   and a waiver cannot be added without writing down why.

   The guard refuses to pass having measured nothing: it asserts it parsed
   ≥ 200 files, found at least as many call sites as the known waived ones,
   found ≥ 20 `scoped_events` call sites, and that the **exact** per-file map
   of waived reads matches `_KNOWN_WAIVED_READS` — so a future change that
   deletes the fix, adds a waiver in a new file, or stops the scanner seeing
   anything, goes red rather than green. The map is compared for equality
   rather than as a floor: a floor set one below the real count lets a read be
   deleted unnoticed, which is what the first version of this guard did.

3. **One whole-buffer cardinality assertion, kept on purpose.** See
   "What scoping costs" below.

**Why a waiver rather than a ban.**
`tests/security/test_release_security_redaction.py` proves the OpenRouter key
never reaches ANY recorded event. Its reads are `repr()`-then-substring-
absence checks over the whole buffer. Narrowing them to one account would make
a leak into any *other* account's event invisible — it would delete exactly the
coverage the test exists for. A blanket ban would have forced that test to be
rewritten worse, or forced an opaque path-based exemption list. The absence
shape is also why the waiver is safe here: a foreign event can only make a
substring-absence assertion stricter, never falsely green — the opposite of the
count/index reads that #209 scoped.

That sweep now reads **all six** recorders, not three. Until this PR's review
it read only `provider`, `debate` and `synthesis`, while the prose around it
claimed the secret "reaches NO recorded event" — false by measurement: the
OpenRouter key planted verbatim as a `warning_event_recorder` event type left
the file at `2 passed`. The three missing recorders are now in the sweep and
each was shown to turn it red.

## What scoping costs

Scoping a read by `account_id` deletes the suite's ability to see an event
written under an account nobody asked about. That is not hypothetical:

The plant must be reproduced **exactly**, because two details are load-bearing:
the duplicate goes **immediately before** the real call, and **both** ids are
fabricated. Placing it after the real call, or leaving `query_run_id` real,
gives a smaller gap (2/28/1 and 4/1/2 respectively) and the same conclusion —
but a reader following a looser recipe will get different numbers and conclude
this table is wrong. Measured across all four combinations, 2026-08-17.

| | planted defect | result |
|---|---|---|
| `origin/main` (all reads unscoped) | a duplicate `synthesis_event_recorder.record(...)` inserted IMMEDIATELY BEFORE the real call in `src/product_app/synthesis.py`, with both `account_id=uuid4()` and `query_run_id=uuid4()` | **4 failed**, 24 passed |
| this branch, every read scoped | same plant | **28 passed** — invisible |
| this branch, with the kept whole-buffer assertion | same plant | **1 failed**, 27 passed: `assert [4, 2, 2, 1, 1, 1] == [4, 2, 1, 1, 1, 1]` |

Command for all three rows: `pytest tests/e2e/test_release_hardening_workflow.py
tests/integration/test_query_run_result_endpoint.py
tests/perf/test_query_run_performance_evidence.py tests/unit/test_synthesis.py
tests/security/test_release_security_redaction.py -q --no-cov` (the `main` row
against a `git archive origin/main` copy).

So exactly one whole-buffer cardinality assertion is kept, in
`tests/perf/test_query_run_performance_evidence.py`. That module is the right
home: its fixture clears **all six** recorders and it makes exactly one query
run, on the legacy inline `X-Account-Id` path.

An earlier draft of this paragraph claimed the module's exposure to the #104
race is "strictly less" than on `origin/main`. **That was false, and review
refuted it by execution.** This file still carries six unscoped reads — the
same six as `main` — and still reddens on a single foreign event in any of the
six buffers: planting one foreign provider event reddens `main`
(`assert 8 == 4`) and this branch (`assert [8, 2, 1, 1, 1, 1] == [4, 2, 1, 1, 1, 1]`)
alike. The module's probability of flaking under #104 is **unchanged**. What the
fix removes here is narrower and worth stating exactly: the three unscoped
*index* reads, whose failure would otherwise have named the wrong field on
someone else's event.

Detection redundancy still drops — 4 tests catch the plant on `main`, 1 here —
and that is a real, accepted cost, not a wash.

## Measured

| Question | Command | Result |
|---|---|---|
| `list_events()` call sites under `tests/` on `origin/main` | the PR's `_scan_test_suite()` against `dd154ee` | 35 |
| of those, unfiltered count/index/`all` reads | same scan, minus 3 security-sweep and 2 hand-filtered | 30 |
| call sites after the fix | `_scan_test_suite()` | 14, all waived; 0 unwaived |
| `scoped_events()` call sites after the fix | same | 37 (31 in assertions, 6 in the helper's own tests) |
| test files parsed by the guard | same | 254 |
| guard bites on a planted unfiltered read | reverted one read in `tests/unit/test_debate_orchestration.py:85` | RED, naming the file and line |
| guard bites on a one-word waiver | added `# unscoped-ok: meh` to that read | RED: *"waiver reason is too short: 'meh'"* |
| helper bites | `scoped_events` mutated to return `recorder.list_events()` | 4 of 5 helper tests RED (re-measured 2026-08-17) |
| the security sweep saw only 3 of 6 recorders | planted the OpenRouter key verbatim as a `warning_event_recorder` event type | **2 passed** — the leak was invisible |
| the sweep, extended to all six, bites | same plant into `warning`, then `cost`, then `model_slot`, each count-neutral (`clear()` then one record) | RED all three times, on the substring-absence assertion itself |
| a compound statement's header inherits a stale waiver from its body | a read in a `for` header, waiver 4 lines down in the body | was waived; now unwaived after `_statement_end` trims to the header |
| `_statement_end` bites | `if body_starts:` → `if False:` | RED: `assert True is False` on `test_a_waiver_in_a_loop_body_...` |
| the waiver-length bound's exact boundary | 19- and 20-character reasons through `find_recorder_reads` | 19 rejected, 20 accepted |
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
  Rejected: it drifts silently — a file can be renamed with nothing noticing,
  and the reason for the exemption lives somewhere other than the code it
  exempts. The in-place annotation keeps the argument next to the read.
  **It is per-STATEMENT, not per-call, and the shipped code relies on that**:
  one comment waives the six reads of the security sweep's list literal, and
  another waives the six of the perf module's. So a seventh read added to
  either list would inherit a reason that may not be true of it — a smaller
  hole than a path allowlist, but a real one, and review is what closes it.
  What *was* fixed here is the worse version: a read in a `for`/`while`/`if`/
  `with`/`try` **header** used to inherit the span of the whole block, so an
  unrelated comment an arbitrary distance down in the body waived it.
  `_statement_end` now trims a compound statement to its header lines, pinned
  by `test_a_waiver_in_a_loop_body_does_not_waive_the_read_in_its_header`.
  This ADR asserted the opposite ("cannot be inherited by a neighbouring one")
  until review measured it; the sentence was false when written.
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
  dependency this diff created: neither file is touched here, neither READS an
  event recorder (`test_query_run_evaluation_endpoint.py` imports and clears
  three of them at lines 85-87 but calls `list_events` zero times —
  `grep -c list_events` on it returns `0`), and the first asserts
  `run_count() == 1` over
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
  paired with `len(events) == 4`), and the absence checks in
  `test_release_security_redaction.py` (now paired with 4/2/1/1/1/1 event-count
  assertions for the run under test). Neither assertion was weakened.
- **About fourteen assertions are now tautologies** — `assert
  events[0].account_id == account_id` after `scoped_events(..., account_id=
  account_id)` restates the filter key and cannot fail for any
  implementation. They are kept as readable statements of intent, not removed,
  because the count or index assertion beside each one does bite. Where the
  pairing is meaningful the keys differ: `tests/unit/test_synthesis.py` scopes
  by `query_run_id` and asserts the `account_id`, which is a real check. The
  comment in `test_cancel_during_initial_answers_records_event.py` that
  claimed its trailing `query_run_id` assertion would catch a foreign event
  was corrected — after scoping by that same key, a foreign event never
  reaches it.
- **Nothing checks `docs/adr/` for duplicate numbers**, which is how this ADR
  and `origin/main`'s ADR-0047 both got written as 0047 and why this one is
  0049 (`0048` is claimed by the open #226 branch). `scripts/generate_adr_index.py`
  emits one row per file and never compares numbers; `--check` only diffs the
  rendered text, so two identically-numbered rows are "up to date"; and
  `tests/unit/test_docs_numbering_no_collisions.py` matches `^docs/(\d+)-`,
  which `docs/adr/NNNN-*.md` never hits. Verified: with both 0047 files
  present, `make validate` exited 0 and printed
  `adr-index: up to date (48 records)`. **Deliberately NOT fixed here** —
  it is a different concern (AGENTS.md rule 17) and three branches are racing
  on this same directory right now, so a fourth simultaneous edit to the
  generator would collide again. It needs its own issue.

## Related

- #209, #104 item 1
- `tests/helpers.py` (`scoped_events`, `ScopedEvent`, `EventRecorder`)
- `tests/unit/test_scoped_events_helper.py`,
  `tests/unit/test_event_recorder_reads_are_scoped.py`
- ADR-0038 (a guard proves it bites by mutating the artifact it asserts about)
- AGENTS.md rule 16a (process-global test state), rule 7 (a negative check
  needs a positive partner)
