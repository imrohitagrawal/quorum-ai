# ADR-0065: The mutation scope names its oracle tests, and a truncated run is not a score

## Status

Accepted — 2026-08-23. Addresses issue #337 (the gate produces no score even at
minimum scope).

Builds on [ADR-0057](0057-the-mutation-gate-is-a-regression-detector-and-must-reach-the-real-tree.md),
which fixed the abort inside `./mutants/` and named the two things it
deliberately left open:

> **A deadline-truncated run now reads as GREEN, and nothing marks it.** …
> **Marking a truncated run is the parked verdict/UNMEASURED work and the first
> thing issue 337 will need.**

Nothing in ADR-0057 is superseded. Its framing — the gate is a **regression
detector**, not a defect finder — is the reason this record fixes the gate's
speed rather than proposing to retire it, and its anti-vacuity floors are
untouched.

## Context

### The premise everyone was working from was wrong

The inherited diagnosis, carried in `docs/analysis/2026-08-22-session-handoff.md`
and in issue #337's own comment, was:

> Narrowing scope cannot fix it: `tests_for_mutant_names()` runs the tests
> *associated* with the mutants, measured **647 of 2924** for a 3-function
> scope. The same set runs in **78s** standalone, so the gap is instrumentation,
> not suite size.

The 647 was computed by hand, by unioning the association sets in
`mutants/mutmut-stats.json`. It is what mutmut *would* run. It is not what
mutmut *did* run. Measured directly, by calling mutmut's own
`tests_for_mutant_names()` with the exact arguments the Makefile emits:

```
$ python3 -c "
import json, fnmatch
k = json.load(open('mutants/mutmut-stats.json'))['tests_by_mangled_function_name']
pat = 'product_app.costs.xǁCostEstimationServiceǁ_cost_components__mutmut_*'
print(len([x for x in k if fnmatch.fnmatch(x, pat)]))"
0
```

**Zero.** So the association set was never used at all.

### Why zero, and what zero costs

`mutmut run` reads its mutant-name arguments twice, and the two readers match
them against differently-spelled names.

| Reader | Matches against | Example key |
|---|---|---|
| `collect_source_file_mutation_data()` — which mutants to run | concrete mutant keys, **with** the suffix | `product_app.costs.xǁCostEstimationServiceǁ_cost_components__mutmut_7` |
| `tests_for_mutant_names()` — which tests are the oracles | mangled function names recorded at stats collection, **without** it | `product_app.costs.xǁCostEstimationServiceǁ_cost_components` |

The second spelling has no `__mutmut_` in it at all —
`mangled_name_from_mutant_name()` partitions the suffix off before the
trampoline records the hit. The scope emitted only the suffixed glob, so the
oracle lookup returned the empty set.

An empty set is not "run no tests". `PytestRunner._pytest_args_regular_run`
reads a falsy test set as *no selection given* and falls back to the configured
selection, which here is empty — so pytest falls back to its own `testpaths`
and runs **the whole suite**. mutmut's clean-test phase, whose whole purpose is
to run the handful of tests that will act as oracles, was running all 2929
tests in the copy instead.

### Where the 1440 seconds actually went

Phase timings, from a probe that wraps each of mutmut's phases and writes
timestamps to fd 2 (`CatchOutput` only swaps the `sys.stdout`/`sys.stderr`
objects, so `os.write(2, …)` escapes it). Scope: the exact three `costs`
functions CI ran on run `32556128813`, job `96990425891`. Machine: 10-core
Apple silicon, CPython 3.12.13, mutmut 3.6.0, hermetic, $0.

| Phase | Before | After |
|---|---|---|
| Generating mutants (copy + create) | 8.7s | 8.4s |
| Running stats — whole suite, instrumented, in `./mutants/` | 119.6s | 122.3s |
| `tests_for_mutant_names()` returns | **0 tests** | **258 tests** |
| Running clean tests | **≥1102s, killed, never finished** | **18.6s** |
| Running forced fail test | never reached | 2.7s |
| Running mutation testing (359 mutants, `--max-children 8`) | never reached | ~13s |
| **Whole run** | **≥1231s, killed by hand; 1440s and 0 mutants in CI** | **165.5s, complete** |

The after column is one run of the identical scope on the identical tree, with
the companion patterns added. It produced a score:

```
mutants scored: 287 killed, 0 survived, 0 timeout (excluded), 0 no-tests
  (0 skipped, 72 crash, 0 error, 0 type-checked, 0 interrupted, 0 suspicious/unrecognized exit code)
mutation score (killed / (killed+survived)) = 100.0% (threshold 80%)
```

The 72 crashes (exit −9/−11) are mutmut's fork-runner artefact, already excluded
by a recorded decision and already named in the summary line; they are the same
class of thing `docs/metrics/mutation-baseline.md` §5 measured as a 24–33%
timeout rate on this app, and this change neither causes nor fixes them.

The CI log agrees on the two phases it reports. From job `96990425891`:

```
Generating mutants
    done in 25958ms (27 files mutated, 1 ignored, 0 unmodified)
Running stats
    done
Running clean tests
Running clean testsrun_with_deadline: 1440s deadline exceeded for 'uv run mutmut run …'
mutants scored: 0 killed, 0 survived, 0 timeout (excluded), 0 no-tests
no mutants were scored — the run did not happen (empty or absent mutants/)
```

Generation and stats both completed. The budget was consumed by a clean-test
phase running a suite it was never supposed to run. For scale, the same suite
uninstrumented on a CI runner in the same workflow run took **352.61s**
(`3110 passed, 68 skipped, 14 warnings`, the `validate-and-test` job).

### The second defect, reachable for the first time

`scripts/run_with_deadline.py` exits **0** when it kills the run — deliberately,
so the recipe still reaches its reporting step (ADR-0057, issue #182). `report()`
scores whatever `mutants/**/*.py.meta` holds and skips every entry mutmut never
filled in (`if code is None: continue`). It has no way to tell a complete run
from a truncated one.

While the gate died in the clean-test phase this never mattered: nothing was
scored, and the anti-vacuity floor failed the job. **No CI run has ever been in
this state** — it becomes reachable only once the gate gets past its clean-test
phase, which is what the first half of this record does. Fixing the speed
without fixing this would have shipped a new silent-pass path.

Demonstrated on a synthetic `.meta` holding 3 killed mutants and 289 unfilled
ones — the shape a mid-run kill leaves — against `report()` with the truncated
branch removed:

```
mutants scored: 3 killed, 0 survived, 0 timeout (excluded), 0 no-tests
mutation score (killed / (killed+survived)) = 100.0% (threshold 90%)
```

Worse, and found only by adversarial review: the first version of the fix
returned 0 for **every** truncated run. Over a synthetic prefix of 3 killed and
7 survived, the shipped gate exits 1 (`30.0%`, `BELOW THRESHOLD`) and that first
version exited 0 — turning a visibly red job green. A survivor is a
*demonstrated* test gap; truncating the run afterwards does not take it back.
The shipped branch therefore fails when any survivor was found, and returns 0
only when the truncated prefix found none.

## Decision

**1. The scope names its oracle tests as well as its mutants.** For every
changed function the scope now emits two patterns instead of one:

```
product_app.costs.xǁCostEstimationServiceǁ_cost_components__mutmut_*
*product_app.costs.xǁCostEstimationServiceǁ_cost_components
```

The leading `*` is what makes the companion pattern precise rather than merely
broad. `fnmatch` measured on real keys:

| Pattern | Matches the mangled name | Matches its mutant keys | Matches a sibling `…_extra` |
|---|---|---|---|
| `<name>__mutmut_*` | no | **yes (148 for `_cost_components`)** | no |
| `*<name>` | **yes** | no | no |
| `<name>*` | yes | yes | **yes — widens the scope** |

So the companion pattern narrows the clean-test phase and adds nothing to what
gets mutated. `<name>*` — the obvious one-character fix — would silently mutate
functions the diff never touched; it is rejected below.

**2. A run its own deadline cut short reports UNMEASURED, never a percentage —
and can never be greener than the same run untruncated.**
`scripts/run_with_deadline.py` creates the file named by
`RUN_WITH_DEADLINE_MARKER` when, and only when, it kills the run, and deletes a
stale one on the way in. `report()` reads the same path — one Makefile variable,
`MUTATION_TRUNCATION_MARKER`, handed to both. The rules, each one shaped by a
demonstrated failure in review:

* **Detection is by CONTENT, not existence.** The marker must begin with the
  wrapper's own sentinel, `run_with_deadline killed this run at `. With an
  existence test, `MUTATION_TRUNCATION_MARKER=/dev/null make mutation-baseline`
  made a completed, below-threshold run report UNMEASURED and exit 0 — and
  `/dev/null` cannot be unlinked, so clear-on-entry could not undo it. The
  variable is also `override :=`, not `?=`, so the environment cannot move it.
* **A truncation notice is printed once, above every diagnosis.** mutmut runs
  its cheapest mutants first and a no-tests mutant costs zero, so "the few we
  reached were all no-tests" is a likely shape for a real truncation — and that
  branch used to tell the author to add a test without ever saying the budget
  had run out.
* **No percentage.** A prefix of the scope has no honest denominator.
* **But a SURVIVOR still fails the gate.** A survivor is a mutant that ran and
  that no test caught; truncating afterwards does not un-demonstrate it. The
  first version of this branch returned 0 unconditionally, and over a prefix of
  3 killed and 7 survived it turned an `exit 1` (`30.0%`, `BELOW THRESHOLD`)
  into an `exit 0` — a visibly red job made green by the mechanism added to make
  the gate more honest. This is deliberately stricter than the complete-run
  rule, which tolerates survivors up to the threshold.
* **A truncation that scored nothing names the deadline and exits 1**, instead
  of `the run did not happen (empty or absent mutants/)` — which was false, and
  which sent three sessions reading `also_copy`. That branch sits *after* the
  all-timeout branch: a scope slow enough to time every mutant out is a scope
  slow enough to hit the wall clock, and "every mutant timed out" is the more
  specific true statement when both hold.
* **The marker write can never cost the kill.** It runs immediately before
  `os.killpg`, and in the first version an `IsADirectoryError` there propagated
  out and the kill never happened — the child outlived its deadline, which is
  issue #182 reopened. The write is suppressed; a missing marker degrades to the
  pre-#337 behaviour, a missing kill degrades to an orphaned worker group.
  Clearing a stale marker, by contrast, fails **loudly** (exit 2) — nothing has
  been started yet, so there is nothing to orphan, and failing open there would
  make every later run in the workspace read as truncated.

## Measurements

All local figures are from a **single run on one machine** — 10-core Apple
silicon, CPython 3.12.13, mutmut 3.6.0, `--max-children 8`, hermetic, $0 — and
none of them survives a fresh checkout, because `mutants/` is generated and
gitignored. Re-deriving any of them means re-running the gate. All CI figures
are from run `32556128813` (2026-08-22), job `96990425891` unless stated.

| What | Value | Command |
|---|---|---|
| Mutants in the failing CI scope | 359 (148 + 49 + 162) | `fnmatch` over `mutants/src/product_app/costs.py.meta` |
| Tests recorded by stats collection | 2929 | `len(json.load(...)['duration_by_test'])` |
| Oracle tests for each of the three functions | 258 | `len(k['product_app.costs.xǁCostEstimationServiceǁ_cost_components'])` |
| Oracle tests the shipped pattern found | **0** | `fnmatch` with the suffixed glob |
| Generating mutants, CI | 25.958s | the log's own `done in 25958ms` |
| Generating mutants, local | 8.7s | phase probe |
| Stats phase, local | 119.6s | phase probe |
| Clean-test phase, local, before | ≥1102s, did not finish | phase probe, killed at 1231s elapsed |
| Whole suite, CI, uninstrumented | 352.61s (3110 passed, 68 skipped) | `validate-and-test` / `Unit tests` |
| Clean-test phase, local, after | 18.6s | phase probe |
| Whole run, local, after | 165.5s | phase probe |
| Whole `make mutation-baseline`, real scope, end to end | ~3 min, `5 killed, 0 survived`, `100.0%`, exit 0 | `make mutation-baseline DIFF_BASE=origin/main` with one comment line added inside `_is_variation_selector` |
| The same, `MUTATION_RUN_DEADLINE_SECONDS=25` | `TRUNCATED` + `UNMEASURED … before any mutant produced a kill-or-survive verdict`, exit 2 | same, with the deadline lowered |
| Mutants scored, local, after | 287 killed, 0 survived, 72 crash | `report` mode of `MUTMUT_SCOPE_PY` |
| Recent PR mutation runs producing a score | **0 of 6** — five died on `deadline exceeded` + `no mutants were scored`, one had an empty scope | `gh run view <id> --log` over `32558988310 32557863001 32554511351 32529064663 32490462765 32556128813` |

`MUTATION_RUN_DEADLINE_SECONDS` is deliberately **not changed**. At 165.5s local
for a 359-mutant scope, the 1440s budget has roughly 8× of headroom on this
machine; the CI runner is slower and by how much is not measured, but nothing
here justifies moving a safety value on a guess (and the local figure is not a
CI figure — see Open).

## Rejected alternatives

**Spell the companion pattern `<name>*`.** One character shorter and it does fix
the oracle lookup. It also matches every mutant key of every function whose name
extends the changed one, so a diff touching `_estimate_bound_usd` would mutate
`_estimate_bound_usd_capped` too and report survivors from code it never
touched. Measured in
`test_the_scope_still_selects_exactly_the_changed_functions_mutants`: the
mutation produces `Left contains one more item:
'pkg.thing.xǁCǁvalue_extra__mutmut_1'`.

**Raise `MUTATION_RUN_DEADLINE_SECONDS` and the job's `timeout-minutes`.**
Rejected as a first move: it buys time for a phase that should not be running at
all, and the study already measured this gate's yield at ~4% of enumerated
escaped defects. Paying a longer runner slot per pull request for a phase that
is 11× larger than it needs to be is spending money to hide a bug.

**Cache `mutants/mutmut-stats.json` between CI runs.** mutmut supports it:
`collect_or_load_stats()` loads the file and then runs only `list_all_tests`
(measured **3.5s** here) plus incremental stats for tests it has not seen. It
would remove the stats phase entirely. Rejected for now, not on principle: a
stale association map silently reclassifies a mutant as `no_tests`, which is the
exact shape of the quietest false pass this gate has
(`tests/unit/test_mutation_test_set_integrity.py` records `63.6% BELOW
THRESHOLD` becoming `100.0% pass` by that route). It is worth doing, with its
own invalidation proof, and is recorded here as the next lever rather than
smuggled into this change.

**Retire the gate, or move it to a nightly schedule.** ADR-0057 rejected
retirement and that stands. Moving it off the per-pull-request path was live
while the fixed cost looked irreducible; with the clean-test phase corrected it
is no longer forced, and changing where a gate runs is a decision that deserves
its own record rather than a footnote in a bug fix.

**Fail a truncated run.** A partial run is a budget event, not a statement about
the diff — the same reasoning the all-timeout branch already applies. It prints
`UNMEASURED` and returns 0 so the recipe's "score or UNMEASURED" guard is
satisfied honestly. The one case that still exits 1 is a truncation that scored
*nothing*, because that is the state a human has to act on.

## Consequences

* The gate produces a score again. On this machine the run that CI could not
  finish in 1440 seconds now finishes in 165.5 and scores 287 mutants. Whether
  that holds on a CI runner is **not yet measured** — see Open.
* A truncated run can no longer print a percentage. If the deadline does fire
  mid-mutant-phase, the job says so and names the count it reached, so the next
  decision (widen the budget, or narrow the scope) is made on a number.
* `scripts/replay_mutation_scope.py` emits the companion pattern too, because
  `tests/unit/test_replay_scope_matches_makefile_scope.py` compares the two
  scope implementations over real commit history and would otherwise go red.
* `scripts/run_with_deadline.py` stays generic: with
  `RUN_WITH_DEADLINE_MARKER` unset it writes nothing and behaves exactly as
  before.

### Open, and deliberately not closed here

* **A function defined in a package `__init__.py` gets two patterns that both
  match nothing.** mutmut strips `.__init__.` from a mutant name before the
  association lookup, so for a function `f` defined in a package's own
  `__init__` module the real key is `pkg.x_f`, while the scope emits
  `pkg.__init__.x_f…`. The *suffixed* half of that miss is
  pre-existing and fails loudly (`assert filtered_mutants`); the companion
  inherits it. Unreachable today — no `src/**/__init__.py` defines a function —
  and a one-line `removesuffix(".__init__")` would close it, but it is a
  separate behaviour change and belongs in its own record.
* **A scope whose changed functions have no recorded test association at all
  still triggers the whole-suite clean phase**, because the association set is
  genuinely empty rather than merely unmatched. The `no_tests > 0` failure catches
  the outcome; the cost is paid first.

* **The CI-runner cost of the mutant phase is unmeasured.** No per-mutant CI
  time has ever been recorded in this repo; `docs/metrics/mutation-gate-study.md`
  §9 already lists "p90 CI runtime unmeasured" as open. The first pull-request
  run after this change is the measurement.
* **Why the clean-test phase was ~9× slower than the stats phase over the same
  suite** (≥1102s versus 119.6s) is not explained. Both run the same tests in
  the same process; the second run of `pytest.main()` in one interpreter is the
  obvious suspect and was not investigated, because the phase should not have
  been running the whole suite in the first place. Recorded rather than guessed.
* **Issue #337's own close condition** is "one `pull_request` run that produces a
  real score line for a real changed function, inside the deadline". This record
  does not assert that; the run does. The issue is named in prose only, with no
  closing keyword — a merge body containing even a negated reference closes an
  issue, measured on PR #174.
