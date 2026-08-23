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
scored, and the anti-vacuity floor failed the job. The moment the gate starts
reaching the mutant phase, a run killed after 2 of 359 mutants — both killed —
prints `mutation score (killed / (killed+survived)) = 100.0%` and exits 0.
Fixing the speed without fixing this would have shipped a new silent-pass path.

Reproduced, on the shipped `report()` with the truncated branch removed:

```
mutants scored: 3 killed, 0 survived, 0 timeout (excluded), 0 no-tests
mutation score (killed / (killed+survived)) = 100.0% (threshold 90%)
```

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

**2. A run its own deadline cut short reports UNMEASURED, never a percentage.**
`scripts/run_with_deadline.py` creates the file named by
`RUN_WITH_DEADLINE_MARKER` when, and only when, it kills the run, and deletes a
stale one on the way in. `report()` reads the same path — one Makefile variable,
`MUTATION_TRUNCATION_MARKER`, handed to both — and:

* prints the survivors it did find (a survivor found before the cut-off is a
  real finding; only the percentage is withheld);
* prints `UNMEASURED … after scoring N of the scope's mutants` and returns,
  matching the posture the all-timeout branch already had — not failed, because
  the cause is the gate's budget rather than the diff, and emphatically not a
  pass;
* and, when nothing at all was scored, names the deadline and exits 1 instead of
  printing `the run did not happen (empty or absent mutants/)` — which was false,
  and which sent three sessions reading `also_copy`.

## Measurements

All local figures on 10-core Apple silicon, CPython 3.12.13, mutmut 3.6.0,
`--max-children 8`, hermetic, $0. All CI figures from run `32556128813`
(2026-08-22), job `96990425891` unless stated.

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
| Mutants scored, local, after | 287 killed, 0 survived, 72 crash | `report` mode of `MUTMUT_SCOPE_PY` |
| PR runs that produced a score, last 11 before this | 0 | issue #337 |

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
