# ADR-0069: An equivalent mutant is removed from the code, not recorded in a list

## Status

Accepted — 2026-08-25. Addresses issue #365, and the second half of issue #337.

Builds on [ADR-0057](0057-the-mutation-gate-is-a-regression-detector-and-must-reach-the-real-tree.md)
and [ADR-0065](0065-the-mutation-scope-names-its-oracle-tests-and-a-truncated-run-is-not-a-score.md).
Nothing in either is superseded. ADR-0065 closed the gate's speed defect and
left two things open that this record answers: *"why the clean-test phase was
~9× slower than the stats phase … is not explained"*, and the CI-runner cost of
the mutant phase.

## Context

### The claim the gate made, and where it was false

`Makefile`'s report step printed, on any survivor found before the wall-clock
cut-off:

> N mutant(s) SURVIVED before the cut-off. A survivor is a test gap that was
> DEMONSTRATED — it needs no denominator and the rest of the run cannot take it
> back — so this fails even though no score was produced.

That is a **universal** claim, and it is false for an **equivalent** mutant —
one whose behaviour cannot differ from the original for any input. No test can
kill such a mutant, because there is nothing to catch.

Two lived in `_stance_majority_flags` (`src/product_app/synthesis_consensus.py`).
The function counted labels by hand and used the counts for exactly two things:

```python
sizes[label] = sizes.get(label, 0) + 1
largest = max(sizes.values())
winners = [label for label, size in sizes.items() if size == largest]
```

`sizes.get(label, 0)` → `sizes.get(label, 1)` makes every count `c+1`;
`+ 1` → `+ 2` makes every count `2c`. Both are strictly increasing in `c`, and a
strictly increasing transform cannot move an arg-max set.

Observed in CI job 97435532376 (run 32728631298, 2026-08-24):
`250 killed, 2 survived, 85 timeout (excluded), 0 no-tests`, then the deadline,
then exit 2.

### Two facts that narrow the problem, both measured rather than assumed

**The hard survivor rule lives in the truncated branch only.** The
`SystemExit(1)` quoted above sits inside `if truncated:`. A *complete* run
scoping only this function is 16 killed / 2 survived = **88.9%** against
`MUTATION_MIN_SCORE ?= 80` and is green today. So the observed red job was
truncation *plus* a survivor. At the 90% threshold the gate's own tests use,
88.9% would be permanently red. #365's "no action turns that job green" is true
of the run it observed; the general form arrives via a threshold raise.

**The mutants are equivalent BECAUSE the function is correctly scale-invariant.**
The tally feeds only `max()` and equality with that max. Any edit that makes
`+ 1` → `+ 2` observable must make the code depend on the counts' absolute
magnitude — i.e. must be a behaviour change wearing a refactor's clothes. This
is the general principle, and it is why "just make them killable in place" is
not available.

### mutmut already ships a proof-free silencer, and nothing guarded it

`# pragma: no mutate` makes `MutationVisitor._should_mutate_node` return False,
so the `Mutation` object is never created. The mutant does not survive, does not
time out, and is not `skipped` (exit 34, which the gate already fails on) — **it
never exists**. Nothing reaches `.meta`, so the report counts nothing, prints
nothing, and the denominator silently shrinks.

Measured 2026-08-25 on the refactored `_stance_majority_flags`: one comment on
one line took it from **11 mutants to 9**. `grep -rn "no mutate" src/ tests/
Makefile pyproject.toml` found **zero** uses, and no check anywhere.

This is decisive for the choice below. Any proof-carrying exclusion ledger would
have sat beside a one-line, proof-free alternative. Under deadline, an author
takes the pragma. A mechanism whose threat model omits the cheaper adjacent
hatch has not raised the cost of silencing a survivor — only the cost of doing
it honestly.

### Keying an exclusion on a mutant NUMBER decays into excusing a real bug

mutmut numbers mutants as a per-function ordinal
(`mutmut/mutation/file_mutation.py`: `mutant_name = f"{mangled_name}_{i + 1}"`
over a CST pre-order walk). Measured 2026-08-25 — insert one statement near the
top of the function and:

```
before: __mutmut_8  ==  sizes[label] = sizes.get(label, 1) + 1   <- the equivalent mutant
after : __mutmut_8  ==  sizes[label] = sizes.get(label, ) + 1    <- a REAL, killable mutant
```

`sizes.get(label,)` returns `None`, `None + 1` raises `TypeError`. A
number-keyed entry does not merely go stale; **it silently re-points at a
genuine bug and excuses it.** Two further triggers renumber with no source edit
at the entry's own site: a `# pragma: no mutate` anywhere in the function, and
any mutmut minor release that reorders its operator table (`pyproject.toml`
allows `mutmut>=3.0.0,<4.0`; `uv.lock` pins 3.6.0).

## Decision

**1. Remove the equivalent mutants from the code.** The tally becomes
`collections.Counter(stance.values())`. This is a refactor, not a change —
measured at 0 differences over all 5,460 label assignments — and it deletes the
two lines the equivalent mutants live on. 18 mutants become 11, none equivalent.

**2. Do NOT build an exclusion ledger.** Recorded as premature, not as wrong,
with the trigger for revisiting stated below.

**3. Make the survivor verdict stop claiming what the gate cannot know.** It
reads a `.meta` file of exit codes and never sees source, so it cannot tell a
missing test from an equivalent mutant. It now names both cases, names the right
fix for each, and still fails — because both need a human.

**4. Close the pragma hatch in the same change.**
`tests/unit/test_no_mutation_pragma_silences_a_survivor.py` refuses any
`# pragma: no mutate` under `src/`, and any `do_not_mutate` /
`do_not_mutate_patterns` in `[tool.mutmut]`. It runs in the merge-blocking
`pytest (Python 3.12)` context, unlike the mutation job itself, which is
advisory. Detection is on COMMENT tokens and on parsed TOML, never on raw text.

**5. (#337) A truncated run states its denominator.** It reported "N of the
scope's mutants" and never said out of how many, so the one question a reader
acts on — is this most of the diff or almost none of it? — had no answer in the
log or the artifact. The total is derivable: the globs the recipe handed to
`mutmut run` are on disk in `build/mutation/scope.txt`. It now reads
`reached 252 of the scope's 337 mutants (75% of the scope)`. The read fails
soft; a denominator is a reporting improvement and must never become a new way
for the gate to die.

**6. (#337) Neither raise the deadline nor add a nightly lane.** Both rejected
below, with the measurements.

### The trigger for revisiting decision 2

Build the proof-carrying mechanism when a **third** equivalent mutant appears in
a function where no behaviour-preserving rewrite removes it. At that point the
population has been enumerated rather than guessed, and this record's rejected
alternatives are the starting design. Until then, the honest path is "remove
it", and gate 4 makes the dishonest path loud.

## Measurements

All figures 2026-08-25, mutmut 3.6.0, CPython 3.12.13, hermetic, $0, no provider
call. Mutants generated with `mutmut.mutation.file_mutation.mutate_file_contents`
— the same pure function `mutmut run` calls from `write_all_mutants_to_file`.
`mutate_only_covered_lines` defaults to False and is not set in
`pyproject.toml`, so what was measured is what the gate would run.

| Shape of the tally | Mutants | Equivalent (unkillable) |
|---|---:|---:|
| `sizes.get(label, 0) + 1` (before) | 18 | **2** — `__mutmut_8`, `__mutmut_9` |
| `Counter(stance.values())` (after) | **11** | **0** |
| after, plus one `# pragma: no mutate` | 9 | 0, and 2 silently gone |

Differential enumeration over all 5,460 label assignments (panel sizes 1–6, four
labels). A mutant is unkillable only if it never differs **and** never raises —
a raising mutant is killed by any test that calls the function.

| Comparison | Differs in |
|---|---:|
| `__mutmut_8` (`get(label, 0)`→`1`) vs original | **0 / 5460**, raises 0 |
| `__mutmut_9` (`+ 1`→`+ 2`) vs original | **0 / 5460**, raises 0 |
| CONTROL, `max`→`min`, vs original | 3780 / 5460 |
| Counter rewrite vs the pre-#365 implementation | **0 / 5460**, raises 0 |
| each of the Counter shape's 11 mutants vs it | 2016–5460, or raises; never both zero |

The control line is why the zeros mean anything: a harness that reports 0 for
everything proves nothing. In the shipped test the partner is stronger than one
control — all eleven mutants are individually shown detectable, and the
hand-written `max`→`min` control is shown detectable on top, so the "nothing is
unkillable" claim rests on twelve positive results rather than on an absence.

Of the 18 mutants the old shape generated, the two equivalent ones were the only
pair that was both silent and non-raising; the other sixteen either differed
(2016–5460 cases) or raised.

### #337, the truncation half

| What | Value | Source |
|---|---|---|
| `MUTATION_RUN_DEADLINE_SECONDS` | 1440s | `Makefile` |
| Mutation job `timeout-minutes` | 30 (1800s) | `.github/workflows/ci.yml` |
| Job wall clock on the truncated run | **1454s** — 346s of headroom | job 97435532376 step times |
| Mutants reached / survived / timed out | 337 verdicts: 250 killed, 2 survived, 85 timeout (**25%**) | the job's own log |
| Changed functions in scope | 17, across 4 modules | `changed functions in scope:` in the log |
| Last 20 `pull_request` mutation runs producing a score line | **0** — 15 empty-scope greens, 1 truncated with real counts, 4 truncated with none | `gh run list --workflow=ci.yml --event=pull_request --limit 20`, each job's log |
| Repo visibility (Actions cost) | PUBLIC — runner time is free; the cost is elapsed time | `gh repo view --json visibility` |

**The premise this work was handed was false, and is corrected here.** ADR-0065
left open *"why the clean-test phase was ~9× slower than the stats phase"*, and
that framing was carried forward into this work. Re-measured on job 97435532376
it is **the other way round**, because ADR-0065's own oracle-glob fix moved it:

| Phase | Spinner frames | Duration floor | Finished? |
|---|---:|---:|---|
| Generating mutants | 149 | 26.083s (printed) | yes |
| **Running stats** | 3114 | **≥311s** | yes |
| Running clean tests | 531 | **≥53s** | yes |
| Running forced fail test | 15 | ≥1.4s | yes |
| Mutation testing | — | the remainder | killed at 1440s |

Frames are a floor, not a duration — `mutmut/__main__.py` rate-limits them at
0.1s — so this establishes the ordering, not the exact ratio. Corroboration: on
the same commit the `pytest (Python 3.12)` job's test step took **290s**, and the
stats phase runs the whole suite once, which matches the ≥311s floor. On the
pre-fix runs of 2026-08-22 the shape is inverted and the old claim was true
(stats 3022 frames, clean tests 1748–1941 frames and **no `done` at all** — the
deadline killed the job inside that phase).

Root cause of the fixed cost, read from the source rather than inferred:
`collect_or_load_stats` is called **once** (not per source file);
`run_stats_collection` passes `tests=None`, which becomes "all"; and
`_pytest_args_regular_run` falls back to the whole suite with no
`--collect-only` and no parallelism. mutmut's only `--collect-only` pass
(`list_all_tests`) runs on the incremental path only, and the recipe does
`rm -rf mutants` before every run, so the cold path is paid every time.

## Rejected alternatives

**A recorded proven-equivalent exclusion ledger, with a mandatory proof.** This
is what #365 asked for, and a working design was reached before it was rejected:
one exact mutant key per entry (no globs), a sha256 pinning the *generated
mutant source* rather than the mutant number, a cited proof module, and a
merge-blocking guard that regenerates and re-verifies every pin offline in about
half a second. Rejected on four measured grounds.

1. **The population is a sample of one.** One function, two mutants, found once.
   AGENTS.md requires a gate's yield to be measured against defect history
   first, and the measured history is **0 of 16** `src/` defects caught by an
   automated check (`docs/metrics/defect-discovery-audit.md`). Designing the
   general mechanism now is designing for a population nobody has enumerated.
2. **The cheaper, worse twin is already installed.** `# pragma: no mutate`,
   measured above at 2 of 11 mutants deleted per comment, with no proof and no
   review signal. Building the careful door next to an open window is not a
   safeguard. Closing the window (decision 4) is, and it costs one test module.
3. **Eliminating beats excluding.** An excluded mutant is still generated, still
   run, and still costs wall clock on a gate that already spent 25% of its
   mutant budget on timeouts. A deleted one costs nothing, forever, and the code
   is shorter.
4. **Every abuse path needs its own guard, and the list is long.** Number-keyed
   decay (measured above, and it excuses a real `TypeError` bug); entries
   outliving their code, which the gate structurally cannot notice because its
   scope is a diff and it almost never touches the function again; a pin nobody
   can independently recompute, which turns re-blessing into a rubber stamp;
   growth with nothing reporting size or age — this repo has **no** precedent
   for a size- or age-reporting allowlist to copy. ADR-0049's annotated waiver
   is the closest precedent and needed an AST parser, a minimum-reason length,
   an exact-equality known-waiver map and four separate floors to stay honest.

   **The honest weakness of rejecting it:** the ledger *generalises* and the
   refactor does not. The next equivalent mutant will be a different shape and
   will need its own thought. That is why the revisit trigger above is written
   down rather than left to be rediscovered.

**Have the gate classify survivors it cannot distinguish, and soften the verdict
for one class.** Rejected as dishonest in the specific sense this repo cares
about. Equivalence is undecidable in general, and `report()` reads exit codes —
it never sees source and could not run a differential enumeration inside a
deadline it already exhausts. Any workable version keys off a human declaration,
which is the ledger with the proof requirement dropped: it renames the silence
rather than removing it. What *was* taken from this option is the narrow, honest
part — fix the **message**, not the verdict (decision 3).

**Make the mutants killable where they stand.** Two shapes, both worse.
*Exposing the tally in the return value* keeps all 18 mutants and makes an
internal count part of the contract for the function's single caller, which
ignores it — textbook test-induced design damage. *Switching to an absolute
more-than-half majority* (`size * 2 > len(stance)`) does kill both mutants, and
changes the answer on **2304 of 5460** panels — including the 3-vs-1 shape
`test_a_three_to_one_panel_counts_the_three_and_not_the_one` pins. That is the
"gratuitously non-monotonic" outcome #365 names, and it is a behaviour change,
not a refactor.

**`Counter(...).most_common()`.** 15 mutants instead of 11, because it
introduces integer index literals (`ranked[0][1]`) whose mutations are less
obviously killable. Strictly worse on the only metric that matters here.

**(#337) Raise `MUTATION_RUN_DEADLINE_SECONDS`.** There is real headroom — 1454s
of an 1800s job ceiling, so ~1680s is available — and at the derived ~3.1s per
mutant that buys roughly +77 mutants, about +17% of what the truncated run
measured. Rejected as a first move for the reason ADR-0065 already gave and
which still holds: it buys time for phases that are the actual cost, and the
rate it is derived from comes from two *floors*, not a measurement. The two real
levers are the ~300s full-suite stats phase and the 25% timeout rate, and either
is worth more than any deadline change. Revisit once the denominator line from
decision 5 has run against a few real pull requests and can say whether four
more minutes would have closed anything — which is precisely what that line
exists to tell us.

**(#337) Move the gate, or a copy of it, to a nightly schedule.** The repo has
seven scheduled workflows, so the mechanism and the quiet window both exist.
Rejected for now. A whole-tree nightly does not fit anyway — 11,687 mutants at
~3.1s is roughly 10 hours against GitHub's 6-hour job ceiling — so a nightly
lane would still have to be scoped or sharded, inheriting the same problem it
was meant to escape. And its result is not attached to a diff: a survivor found
at 04:00 UTC has no pull request to turn red and becomes a filed finding. That is
a legitimate instrument, but a *different* one, and ADR-0065 already recorded
that changing where a gate runs deserves its own record rather than a footnote.

**(#337) Cap the scope and refuse to start a doomed run.** Genuinely attractive
— the mutant count is known right after the 26s generation step, so the gate
could say "scope too large, budget covers ~K" and free the runner instead of
spending 24 minutes to say UNMEASURED. Not built here: there is no measured
basis for the cap's value yet, and a cap set too low silently stops measuring
legitimate diffs, which is the failure mode this whole family of records exists
to remove. **This is the named next lever**, and decision 5's denominator is the
measurement that would set its value.

## Consequences

* `_stance_majority_flags` stops generating equivalent mutants, so the gate's
  survivor verdict is true of every survivor it can now report **for this
  function**. It is not true in general, which is why decision 3 changed the
  wording rather than relying on decision 1.
* **This does not generalise.** The next equivalent mutant needs its own
  analysis. The revisit trigger is recorded above.
* Seven fewer mutants for this function on every run that has it in scope. The
  gate is diff-scoped, so that only pays off when the function is edited —
  which is exactly when it hurt.
* `# pragma: no mutate` is now unavailable under `src/`. If someone genuinely
  needs it, the gate's failure message sends them here rather than letting them
  silence a mutant unreviewed. The cost is that a legitimate future use requires
  editing a test — deliberate.
* A truncated run now reports a percentage **of the scope**, which is not a
  mutation score and is worded so it cannot be read as one. When
  `build/mutation/scope.txt` is unreadable the pre-#337 sentence returns.
* `docs/analysis` gains no new file; this record carries the measurements.

### Open, and deliberately not closed here

* **The scope's total mutant count in the truncated CI run is UNVERIFIED.** The
  progress line read `337/11687`, but 11687 is every mutant in all 27 mutated
  files, not the scope — `print_stats` sums the whole map while only the
  filtered list executes. Decision 5 computes the right number from
  `scope.txt` going forward; the historical run's true denominator was never
  recorded. It would be settled by generating mutants into a throwaway copy and
  counting `.meta` keys matching the 17 globs — no test execution, ~30s.
* **Exact per-phase durations remain floors, not measurements.** Settled by
  re-running with mutmut's output line-buffered and timestamped
  (`stdbuf -oL … | ts`), reading the deltas between its phase markers.
* **The 25% mutant timeout rate is unexplained and unaddressed.** It is the
  largest single lever on this gate's throughput and is engineering work, not a
  decision.
* **Decision 3 is prose with no structural test.** The exit status is
  deliberately unchanged, so there is nothing but the wording to assert on. The
  shipped test pins the string and says in its own docstring that it cannot see
  whether the prose is true.
