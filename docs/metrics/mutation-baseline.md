# Mutation gate — measured baseline (mutmut)

Ledger item: **RB-7** ("mutmut 70%/2wk plucked/unmeasured; changed-module scope
is gameable and slow"), with the RED proof named by **FS-3**
(`query_runs.py::_persist_terminal_run`, pre-fix SHA `d7469ce`).

The previously written **70% / 2-week** figure was never measured. This file
replaces it with numbers that were. Per `guardrail-values-need-measurement`, the
threshold below is derived from the measurement, not the other way round.

> **Re-measured 2026-07-19.** The first baseline recorded here (425 mutants,
> 96.4–96.5%) **no longer reproduces** and is superseded by §3. The cause is not
> a regression in the tests — it is that the **RB-3 leak fix landed in this same
> working tree after that baseline was taken**, adding `close()`, `__del__()`
> and `_close_open_stores()` to both stores and rewriting
> `FeedbackStore.iter_events`. Those functions are now *in scope* (the gate
> scopes to changed functions), they add **79 mutants**, and they are largely
> **unkilled**. See §3.1 for the full accounting and §4 for the re-derived
> threshold. The old numbers are kept in §2/§3.1 for the audit trail, clearly
> marked superseded.

- Tool: **mutmut 3.6.0** (`[project.optional-dependencies].quality`, never in
  the runtime image or the Docker build).
- Config: `[tool.mutmut]` in `pyproject.toml` (every option there has a
  measured reason attached).
- Runner: `make mutation-baseline` — **ADVISORY in CI** (reports, does not
  block a merge), CI job `mutation-baseline` in `.github/workflows/ci.yml`.
  `make` itself exits non-zero honestly; only the CI job carries
  `continue-on-error`. Issue #130 asked to promote it; the promotion was built,
  measured, and reversed — the evidence is in `docs/metrics/mutation-gate-study.md`.
- Hardware for every number below: Apple M-series, 10 cores, macOS 25.5,
  `--max-children 8`, hermetic (`OPENROUTER_LIVE_EXECUTION_ENABLED=false`,
  `SENTRY_DSN=`, no network, **$0**).

---

## 1. The proof that matters: the gate bites on the real defect

The defect is the `is_terminal` guard in `_persist_terminal_run`
(`src/product_app/query_runs.py`):

```python
query_run = query_run_repository.get(query_run_id)
if not query_run.is_terminal:
    return
```

At `d7469ce` this guard had **no test**. The test
(`tests/integration/test_query_run_history_persist.py::test_non_terminal_run_is_not_persisted`)
was added in `8c09a26` after a hand-run mutation found the hole. So the guard is
the perfect subject: the same mutant must **survive** the old suite and be
**killed** by the current one.

Method (no `git checkout`; the working tree was never mutated): the repo was
copied to a scratch dir, the guard's two lines were deleted from the copy, and
the persistence test file was swapped between its `d7469ce` version
(`git show d7469ce:tests/integration/test_query_run_history_persist.py`) and its
HEAD version. `tests/test_store_lifecycle.py` is deselected in all three runs
(it is an unrelated GC/`ResourceWarning` spec that is order-sensitive), so the
only variable is the persistence test file.

**RED — mutant + `d7469ce` tests → SURVIVES:**

```
533 passed, 1 skipped, 10 deselected, 6 warnings in 8.58s
```

**GREEN — same mutant + HEAD tests → KILLED:**

```
=========================== short test summary info ============================
FAILED tests/integration/test_query_run_history_persist.py::test_non_terminal_run_is_not_persisted
1 failed, 533 passed, 1 skipped, 10 deselected, 6 warnings in 8.43s
```

**Control — unmutated source + HEAD tests → green** (proves the failure is the
mutant, not the test):

```
534 passed, 1 skipped, 10 deselected, 6 warnings in 8.83s
```

### A finding about mutmut's own operator set

mutmut 3.6.0 does **not** generate the guard-deletion mutant. Of the 66 mutants
it generates for `_persist_terminal_run`, exactly one touches the guard —
`x__persist_terminal_run__mutmut_3`, which *inverts* it to
`if query_run.is_terminal: return`. That inversion also stops **terminal** runs
being persisted, so the pre-existing `test_completed_run_persisted_…` test kills
it at `d7469ce` too; it is killed at HEAD as well
(`🎉 product_app.query_runs.x__persist_terminal_run__mutmut_3`).

So the mutant that actually escaped the old suite is one mutmut would never have
produced. **The gate is a floor, not a proof of test strength** — that is
recorded here rather than glossed over. It is why the gate is a floor under
changed code and nothing more — passing it is not evidence that a change is
well tested.

---

## 2. Historical — full module, `run_history_store.py` (SUPERSEDED)

Taken **before** the RB-3 leak fix, when the module had 313 mutants (it now has
323 — `close`/`__del__`/`_close_open_stores` are new). Kept for the audit trail;
the current numbers are §3.

| Outcome | Count |
| --- | ---: |
| killed | 261 |
| **survived** | **8** |
| timeout (harness artifact — see §5) | 43 |
| no tests cover the mutant | 1 |
| **total generated** | **313** |

- Score (killed / (killed + survived)) = 261 / 269 = 97.0%.
- Wall clock: 2 min 12 s including stats collection.

The 8 survivors (`iter_runs` ×6, `update_evaluation` ×2) are unchanged today —
see §3.2. They are the *only* part of that older measurement that still holds.

## 3. Measured baseline — the changed-function scope (this branch)

The scope the gate actually runs: every function whose body overlaps a line
changed vs `origin/main` (plus uncommitted worktree changes) on
`feat/r2-s1-run-history-persistence` — now **21 functions across 3 modules**
(`query_runs.py`, `run_history_store.py`, `feedback_store.py`), **504 mutants**
(`build/mutation/scope.txt`).

**Three consecutive `make mutation-baseline` runs, 2026-07-19**, plus the two
runs that first exposed the drift the same day (R0a/R0b — same tree, same
command, run under heavier machine load):

| run | date | mutants | killed | survived | timeout | no-tests | score |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R0a | 2026-07-19 | 504 | 336 | 43 | 123 | 2 | 88.7% |
| R0b | 2026-07-19 | 504 | 294 | 43 | 165 | 2 | 87.2% |
| R1 | 2026-07-19 | 504 | 336 | 43 | 123 | 2 | 88.7% |
| R2 | 2026-07-19 | 504 | 333 | 43 | 126 | 2 | 88.6% |
| R3 | 2026-07-19 | 504 | 336 | 43 | 123 | 2 | 88.7% |

### The 2026-07-29 repair probe — deliberately NOT a row in the table above

**This is a PROBE, not a baseline.** It is kept out of the per-run table on
purpose: the guard in `tests/test_mutation_baseline_doc.py` cross-checks any
recorded run against the `**total**` survivor row, and a 2-mutant probe cannot
satisfy that. Widening the guard to admit it was tried and reverted — bending a
check to fit a throwaway artifact is the failure this document is about. It
exists to answer the question `docs/metrics/mutation-gate-study.md` §9 left open:
*does the repaired gate produce a score at all?* It scoped one function
(`untrusted_text.fence`, engaged by a deliberate temporary edit that was reverted)
and printed:

```
mutants scored: 2 killed, 0 survived, 0 timeout (excluded), 0 no-tests
mutation score (killed / (killed+survived)) = 100.0% (threshold 80%)
```

Run immediately before it on the **same tree** with the pre-#158 root resolution
restored, the same command aborted at `assert 514 <= 55` /
`failed to collect stats` and scored nothing. That pair is the causal evidence
that the root-resolution repair is what produced the number.

**First real runtime data point for #137** (p90 CI runtime was previously an
extrapolation from two local points): mutant *generation* took **23.4s** for the
whole tree (23 files mutated, 9,370 mutants generated) before scoping filtered
execution to 2, which then ran at **7.32 mutations/second**. Generation cost is
therefore close to fixed per run regardless of scope size — the part that scales
with scope is execution. This is a 10-core laptop; a 2-core CI runner will be
slower. Still not a p90 measurement.

Per-module, captured from `mutants/**/*.py.meta` for R1/R2/R3:

| Module (changed functions only) | mutants | killed | survived | timeout | no-tests |
| --- | ---: | ---: | ---: | ---: | ---: |
| `run_history_store.py` (13 functions) | 323 | 261 | 8 | 53 | 1 |
| `query_runs.py` (3 functions) | 93 | 25–28 | 0 | 65–68 | 0 |
| `feedback_store.py` (5 functions) | 88 | 47 | 35 | 5 | 1 |
| **total** | **504** | **336** | **43** | **123** | **2** |

The `**total**` row is R1/R3 (and the artifact currently in
`build/mutation/score.txt`):

```
mutants scored: 336 killed, 43 survived, 123 timeout (excluded), 2 no-tests
mutation score (killed / (killed+survived)) = 88.7% (threshold 80%)
```

- **Score = 336 / (336 + 43) = 88.7%** — the definition the gate uses.
- Wall clock: **538 s / 547 s / 536 s** (8 min 56 s / 9 min 7 s / 8 min 56 s).

### Which number is the stable signal

The score's denominator excludes timeouts, and **timeouts are the only column
that moves**. Measured directly: across R1/R2/R3 the per-mutant outcome map for
`run_history_store.py` and `feedback_store.py` was **byte-identical**; the entire
run-to-run delta was `query_runs.py`'s killed/timeout split (28/65 → 25/68 →
28/65). Under the heavier load of R0b that split degraded far further and the
score fell to 87.2%.

So:

- **Timeout-insensitive figure: 43 survivors / 504 generated = 8.5% survived,
  i.e. 91.5% not-survived. This was identical in all five runs.**
- Timeout-sensitive figure (the gate's): **87.2%–88.7%**, a 1.5-point spread.

**The stable signal is the survivor set — 43 mutants, byte-identical mutant
names in all five runs.** That is what should be tracked and driven down. The
percentage the gate prints is a load-dependent derivative of it and should be
quoted as a **range**, never as a single number. The threshold in §4 is
therefore set against the *worst* observed score, not the typical one.

### 3.1 Why the old 96.4% is superseded — the interesting part

The 425-mutant / 96.4–96.5% baseline was taken **before the RB-3 leak fix landed
in the same worktree**. That fix added `close()`, `__del__()` and
`_close_open_stores()` to both stores and rewrote `FeedbackStore.iter_events` to
materialise rows inside the lock. Because the gate scopes to **changed
functions**, all of that code walked straight into scope:

| Module | mutants before | mutants after | Δ |
| --- | ---: | ---: | ---: |
| `run_history_store.py` | 313 | 323 | +10 |
| `query_runs.py` | 93 | 93 | 0 |
| `feedback_store.py` | 19 | 88 | +69 |
| **total** | **425** | **504** | **+79** |

Of those 79 new mutants, **32 of the 35 new survivors are in `feedback_store.py`**
(3 were already there). The score did not fall because tests got worse; it fell
because **a bug fix shipped without behavioural tests strong enough to pin it**,
and the changed-function gate did exactly what it exists to do — it noticed.

This is the failure mode to remember: on a changed-function scope, *the score is
not comparable across commits*. Every commit redefines the denominator. The
number is a statement about the code that commit touched, and a fix that adds
untested code will lower it even when nothing regressed.

### 3.2 The 43 survivors, enumerated

Each mutant's actual source change was extracted by diffing
`xǁClassǁmethod__mutmut_N` against `…__mutmut_orig` inside `mutants/`.

**A. Equivalent mutants — cannot be killed (24 of 43).** SQLite keywords,
identifiers and `sqlite3.Row` key lookup are all **case-insensitive**, so these
mutants are semantically identical to the original. No test can distinguish
them; they are pure noise in the denominator.

| Mutants | Change |
| --- | --- |
| `feedback_store.iter_events` 6, 18, 21 | SQL keyword/column case (`recorded_at`→`RECORDED_AT`, ` WHERE `→` where `, ` AND `→` and `) |
| `feedback_store.iter_events` 44, 46, 48, 50, 52, 55, 58 | `row["id"]`→`row["ID"]` etc. — `sqlite3.Row` lookup is case-insensitive |
| `run_history_store.iter_runs` 6, 12, 17, 20, 27 | SQL keyword/column case (incl. ` LIMIT `→` limit `) |
| `run_history_store.update_evaluation` 6, 7 | whole UPDATE statement lower/upper-cased |
| `feedback_store.close` 8, 9, 10, 11 | the warning **message text** only (`"XX…XX"`, upper-cased) |
| `feedback_store.close` 4, 5, 6, 7 | the warning's format string / args replaced with `None` or dropped |

The last two rows are "logging-only" rather than strictly equivalent — they do
change what a log line says. Asserting on log wording is not a behavioural
oracle and is not worth a test; they are counted here as uninteresting.

**B. Genuine coverage gaps — killable, currently unkilled (19 of 43).**

| Mutants | Function | What survives, and the missing oracle |
| --- | --- | --- |
| `iter_events` 7 | `FeedbackStore.iter_events` | `params.append(None)` for `since` — the `since=` filter is **never exercised**; with `NULL` the query returns nothing |
| `iter_events` 9, 10, 11, 12, 13, 14 | `FeedbackStore.iter_events` | the whole `recorders=` whitelist branch (`placeholders`, the `IN (…)` clause, `params.extend`) — **never exercised** |
| `iter_events` 20 | `FeedbackStore.iter_events` | `" AND "`→`"XX AND XX"` — only observable when **both** filters are passed at once; never done |
| `iter_events` 31, 32, 33, 34 | `FeedbackStore.iter_events` | `event_type`/`account_id`/`query_run_id`/`recorded_at` set to `None` on the yielded row — no test asserts those four fields |
| `run_history_store.iter_runs` 19 | `RunHistoryStore.iter_runs` | same combined-filter gap: `since=` **and** `account_id=` together |
| `feedback_store.close` 1 | `FeedbackStore.close` | `acquired = None` → always takes the "could not take the lock" path **and never releases the lock** |
| `feedback_store.close` 3 | `FeedbackStore.close` | `if not acquired:` → `if acquired:` — warns on the success path, silent on the timeout path |
| `feedback_store.close` 12, 13 | `FeedbackStore.close` | `self._closed = True` → `None`/`False` — idempotence flag never asserted |
| `feedback_store.__del__` 1 | `FeedbackStore.__del__` | `suppress(Exception)`→`suppress(None)` — nothing proves `__del__` swallows a raising `close()` |

`_close_open_stores` in both modules generated mutants but **none survived** —
they timed out or were killed. The **2 no-tests** mutants (exit 33) are one each
in `run_history_store.py` and `feedback_store.py`.

**Why these are structurally hard to kill here.** `[tool.mutmut]
pytest_add_cli_args` deselects **`tests/test_store_lifecycle.py` and
`tests/test_store_shutdown_safety.py`** — the two files that actually exercise
`close`/`__del__`/`_close_open_stores` — because they fail under mutmut's
stats instrumentation (measured; reason recorded in `pyproject.toml`). So the
7 lifecycle survivors in group B **have no oracle inside the mutation run at
all**, and adding tests to those two files would not move this number by a
single mutant. Fixing them requires either lifecycle assertions in a
non-deselected test module or making those two files mutmut-safe — both are
follow-up work, out of scope for this re-measurement, and deliberately not
faked here.

The 12 `iter_events`/`iter_runs` filter-and-mapping survivors in group B *are*
killable by ordinary tests in a non-deselected module. They are the honest,
actionable backlog from this run.

## 4. Threshold — re-derived from the new measurement

```
MUTATION_MIN_SCORE ?= 80          # Makefile
```

Derivation, using the same method as the superseded version — *set below the
lowest score actually observed, with headroom for the measured harness noise*:

| Input | Value |
| --- | ---: |
| Lowest score observed across the five runs in §3 (R0b) | 87.2% |
| Highest | 88.7% |
| Measured run-to-run spread | 1.5 points |
| Headroom applied (unchanged from the superseded derivation) | 6.4 points |
| **Threshold** | **87.2 − 6.4 = 80.8 → floored to 80%** |

Notes, so the number is falsifiable rather than plausible:

- It is **below the worst observed run**, not the typical one. A threshold pinned
  near 87% would fail on the next heavy-load run, and a gate that cries wolf gets
  switched off.
- The 6.4-point headroom is not new taste: it is the exact margin the previous
  derivation used (96.4 → 90). Reusing it keeps the method constant while the
  measurement changes, which is the whole point of
  `guardrail-values-need-measurement`.
- **80 is a floor on a load-dependent number, not a quality target.** The quality
  target is the survivor count: **43 today, of which 19 are killable** (§3.2).
- **Unmeasured, stated plainly:** every number here is from one macOS M-series
  machine. CI is a 2-core ubuntu runner, where the timeout column — the only one
  that moves — will be *worse*. The score there could fall below 80 without any
  test regressing. **This is the one live risk carried by making the gate
  blocking (#130), and it is named here rather than discovered later.**

  **The CI number is not merely unmeasured — it has never existed.** Issue #130
  argued the gate was ready because it "finished in 1m 9s on PR #96 and
  passed". Both halves are false, and the job's own log says so (run
  `30376617533`, job `90333801913`, 16:06:01Z → 16:07:12Z):

  ```
  FAILED tests/contract/test_golden_fixture_matches_served_schema.py::test_the_shared_fixture_exists
  failed to collect stats. runner returned 1
  mutation-baseline: mutmut run failed — see build/mutation/run.log
  make: [Makefile:322: mutation-baseline] Error 1 (ignored)
  ```

  It finished in ~1m07s because it **aborted before scoring a single mutant**,
  and it was green only because the advisory `-` ignored the error. Four
  sampled pull-request runs all show the same 1m04–1m11s abort. So there is no
  measured CI runtime, no measured CI score, and `timeout-minutes: 30` has
  never been exercised by a real run. `MUTMUT_MAX_CHILDREN ?= 8` is tuned for a
  10-core M-series machine; eight forks on a 2-core runner multiplies exactly
  the `RLIMIT_CPU` timeouts described above.

  If the gate does fire on an honest change, read the job's own uploaded
  artifact first — the fix is to record the measured CI number and derive a
  threshold from it, never to re-add `continue-on-error` and never to raise the
  floor above what the evidence supports.

The threshold was proven to bite, on the real R3 report (`mutants/**/*.py.meta`
from the run in §3, re-scored at two thresholds):

```
$ ... report origin/main 90
mutation score (killed / (killed+survived)) = 88.7% (threshold 90%)
BELOW THRESHOLD          # exit 1  ← the old floor now fails
$ ... report origin/main 80
mutation score (killed / (killed+survived)) = 88.7% (threshold 80%)
                         # exit 0  ← the re-derived floor passes
```

The obsolete **70%** figure stays retired, and **90% is retired with it**: 90 was
derived from a scope that no longer exists (§3.1), and every run of the current
scope is below it.

## 5. Runtime, and what the advisory window was for (now closed)

- Whole-module `query_runs.py`: **1009 mutants**. Extrapolated from the measured
  rate this is roughly an hour of CI per run — which is exactly why the ledger
  called whole-module scoping "gameable and slow", and why the gate scopes to
  changed functions instead.
- Changed-function scope on this branch: **536–547 s** (~9 min) for 504 mutants,
  `--max-children 8`. This branch is a worst case — it adds a whole module, so
  21 functions are in scope; a typical change touching 2–3 functions is a small
  fraction of that.
- CI job timeout is **30 minutes**, and the job is **advisory** (it carries
  `continue-on-error`). At ~9 min locally the headroom is ~3.3×, not 4×.

Two known harness problems, both measured, were the reason for the advisory
window rather than immediate blocking:

1. **Timeouts are a fork artifact, not a signal.** mutmut re-runs the suite by
   `fork()`ing a parent that has already imported the app and run the suite
   in-process. For mutants of thread-spawning code (`query_runs.py`) the child
   burns its `RLIMIT_CPU` budget and is killed with `SIGXCPU` even though the
   same test set finishes in **1.7 s** when run directly. Verified: 66/66
   mutants of `_persist_terminal_run` timed out under mutmut while the selected
   28 tests pass in `1.34s` standalone. Across the whole changed-function scope
   this is **123–165 of 504 mutants (24.4–32.7%)** across the five runs in §3 —
   and for `query_runs.py` alone **65–68 of 93 (70–73%)**, so the mutation number
   for that module remains close to meaningless. The decisive evidence that this
   is load, not behaviour: in R1/R2/R3 the outcome map for the other two modules
   was **identical**, and *only* `query_runs.py` moved. Timeouts are therefore
   **excluded from the score** and reported separately — counting them as kills
   would flatter the number, counting them as survivors would fail the gate for
   a tooling defect.
2. **`.env` leakage.** mutmut copies the project into `./mutants/`. A
   developer's real `.env` was picked up on the first run and initialised Sentry
   inside every mutant child. The Makefile target and the CI job now force
   `SENTRY_DSN=`, `OPENROUTER_LIVE_EXECUTION_ENABLED=false` and a dummy
   `QUORUM_TOKEN_SECRET`, and `.env` is not in `also_copy`.

**Advisory window: superseded 2026-07-29.** Issue #130 asked to convert the
gate to blocking. The conversion was built, measured, and REVERSED — see
`docs/metrics/mutation-gate-study.md`. What survived is the repair: the leading
`-` is gone from the `mutation-baseline` recipe, so `make` now exits non-zero
honestly, while `continue-on-error` REMAINS on the CI job so a red gate reports
without blocking a merge. Both switches mattered — the `-` swallowed every
failure inside the run, so removing the workflow flag alone would have left a gate that still could not
fail.

The recorded precondition was that problem (1) be **fixed or ring-fenced**. It
is ring-fenced, two ways, and the second one was missing until the promotion:

1. Timeouts are excluded from the score's denominator (`killed + survived`), so
   a timeout storm cannot drag the percentage down. This was already true.
2. A scope in which *everything* timed out no longer collapses into the
   "the run did not happen" failure. `killed + survived == 0` was a hard exit 1
   whose message named an absent or crashed `mutants/` tree — false, and while
   the gate was advisory nobody paid for it. Measured worst case: **66/66
   mutants of `_persist_terminal_run` timed out** while the same tests pass in
   1.34s standalone, so a change touching only that function would have been
   blocked by a tooling artifact, with a message sending its author after a
   crash that never happened. That case now reports `UNMEASURED` with the
   timeout count, exits 0, and prints **no score** — it is neither a pass that
   looks measured nor a failure for something the author did not do.

A run that produced no metadata at all still fails closed, unchanged. The three
states are distinguishable in the log and in `build/mutation/score.txt`, and
each is pinned by a test in `tests/unit/test_mutation_gate_integrity.py`.

**The residual gap, stated plainly:** an all-timeout scope means that change
carries no mutation evidence, and the gate says so rather than pretending
otherwise. It does not block. If timeout storms become common rather than
confined to thread-spawning code in `query_runs.py`, the answer is to fix the
fork-runner interaction, not to widen this exception.

## 6. Scoping method (changed functions, not changed modules)

`make mutation-baseline`:

1. `git diff -U0 $(DIFF_BASE)...HEAD -- src` **plus** `git diff -U0 HEAD -- src`
   → the set of new-side line numbers per file.
2. `ast.parse` each file; any `def`/`async def` whose `lineno..end_lineno` span
   intersects those lines is in scope (innermost function, class-qualified).
3. Each becomes a mutmut mutant-name glob —
   `product_app.query_runs.x__persist_terminal_run__mutmut_*` for a function,
   `product_app.run_history_store.xǁRunHistoryStoreǁiter_runs__mutmut_*` for a
   method — written to `build/mutation/scope.txt` and passed to `mutmut run`.
4. `build/mutation/score.txt` holds the score, the survivor list and the
   threshold verdict; CI uploads `build/mutation/` as an artifact.

Verified on the real changed hunk of this branch (21 functions, listed in
`build/mutation/scope.txt`). Empty scope is a no-op, not a failure: a change
that touches no Python function under `src/` has nothing to mutate.

**Consequence, learned the hard way (§3.1): the scope moves with the diff, so the
score is not a time series.** Re-measure after any change to the functions in
scope; do not carry a previous run's number forward.

## 7. Reproduce, and what the doc-honesty guard can and cannot check

```bash
uv sync --extra quality
make mutation-baseline                      # vs origin/main
make mutation-baseline DIFF_BASE=origin/foo  # vs another base
```

Across five runs the measured spread is **294–336 killed, 43 survived (identical
mutant names every time), 123–165 timeout, 2 no-tests → 87.2–88.7%**. When
quoting a single number, quote a **range**; when a single figure is unavoidable,
quote the **lower** bound (87.2%).

`tests/test_mutation_baseline_doc.py` enforces this file's honesty in two tiers,
because the two kinds of claim have different portability:

- **Machine-independent (runs everywhere, including CI, with no artifact):**
  the §3 `**total**` row must be arithmetically self-consistent and its score
  recorded; every run row in the §3 table must be self-consistent; and
  `MUTATION_MIN_SCORE` in the `Makefile` must equal the threshold this file
  states **and** sit strictly below the lowest score any recorded run reports.
  That is the check that catches a stale doc — a re-derivation that forgets to
  move the Makefile, or a threshold quietly raised above the evidence.
- **Machine-dependent (skipped without `build/mutation/score.txt`):** the exact
  killed/survived/timeout counts in this file must match the local artifact.
  This **cannot** be a blocking CI check: the killed/timeout split is hardware-
  and load-dependent (§5), so a Linux runner legitimately produces different
  counts for an unchanged tree. The CI `mutation-baseline` job runs this guard
  immediately after producing its own artifact, so drift is *visible* in the job
  log — but on that Linux runner this tier now reports **SKIPPED**. It used to
  be kept harmless ONLY by the job's `continue-on-error`. The tier now also
  skips unless it is running on the hardware profile §2 records (macOS), so it
  no longer depends on that flag alone. That is the honest form: comparing Linux counts against
  macOS-recorded ones was never a signal, and a `continue-on-error` on the step
  would have made the whole job read as advisory to
  `tests/test_doc_gate_consistency.py`. **This is a real, accepted limitation:
  a stale count in this file is caught locally, on the machine that can produce
  a comparable number, and never by CI.**

`./mutants/` and `mutmut-stats.json` are created in the repo root by mutmut and
are build artifacts — they must not be committed and belong in `.gitignore`
(`build/` already is). `build/mutation/scope.txt` and `build/mutation/score.txt`
are the run's outputs and are what CI uploads.
