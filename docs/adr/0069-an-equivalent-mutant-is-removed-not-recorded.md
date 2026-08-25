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
scoping only this function would be 16 killed / 2 survived = **88.9%** against
`MUTATION_MIN_SCORE ?= 80` and green today. That 16 was ASSUMED when this record
was drafted — enumeration shows the 16 non-equivalent mutants are *killable*,
which is not the same as this suite killing them. **It is now measured for the
shape that shipped**: see "The first run" below. The 2 survivors of the old
shape are measured (CI job 97435532376). So the observed red job was
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
one line took it from **11 mutants to 9**. `grep -rn "no mutate" src/` found
**zero** uses, and no check anywhere. (An earlier draft quoted that grep over
`src/ tests/ Makefile pyproject.toml`. It returned zero *before* this change and
returns 14 after it, because the new guard and its tests necessarily name the
pragma. Scoped to `src/`, which is what the claim is about, it is still zero.)

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

**The first version of this guard was evadable in one line, and adversarial
review broke it before it shipped.** mutmut's predicate is two INDEPENDENT
membership tests — `if "# pragma:" not in text or "no mutate" not in text` —
so it is order-independent. The guard required `no mutate` to follow `pragma:`,
which left `# no mutate  # pragma: no cover` honoured by mutmut and invisible to
the guard. In its `block` form at module level that evasion took
`synthesis_consensus.py` from **384 mutants to 0** with the guard still green.
The fix is to mirror mutmut's predicate exactly and assert every honoured
spelling, including the three that evaded it. Recorded because it is the whole
lesson of this ADR turned on its author: a guard against silencing is worth
exactly as much as its measurement of the tool it guards.

**5. (#337) A truncated run states its denominator.** It reported "N of the
scope's mutants" and never said out of how many, so the one question a reader
acts on — is this most of the diff or almost none of it? — had no answer in the
log or the artifact. The total is derivable: the globs the recipe handed to
`mutmut run` are on disk in `build/mutation/scope.txt`. It now reads
`reached N of the scope's M mutants (X% of the scope) and scored K of those`.
(No worked example from a real run is quoted here on purpose: on the only CI run
that got this far, M was never recorded — see Open.) The read fails
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

Three shapes the 5,460-case enumeration does not reach were checked separately,
because "0 differences over my chosen inputs" is exactly the narrow-sample trap:
an **empty** `stance` raises `ValueError: max() iterable argument is empty` from
*both* shapes, identically; **20,000 random panels** of size 1–8 over 8 labels —
wider than the enumeration on both axes — give 0 differences; and non-string
labels (`int`, `None`, `tuple`) agree. Iteration order cannot matter either:
`winners[0]` is reached only after `len(winners) != 1` has returned, so the list
has exactly one element whenever it is indexed.

The control line is why the zeros mean anything: a harness that reports 0 for
everything proves nothing. In the shipped test the partner is stronger than one
control — all eleven mutants are individually shown detectable, and the
hand-written `max`→`min` control is shown detectable on top, so the "nothing is
unkillable" claim rests on twelve positive results rather than on an absence.

Of the 18 mutants the old shape generated, the two equivalent ones were the only
pair that was both silent and non-raising; the other sixteen either differed
(2016–5460 cases) or raised.

### Seven mutants disappeared. None of them carried decision logic.

"18 becomes 11" is only good news if the seven that vanished were noise, so they
were enumerated and matched one for one rather than assumed. Every mutant of
both shapes, by the line it mutates:

| Line mutated | Old shape | New shape |
|---|---:|---:|
| the tally (`sizes = …`) | **9** (old 1–9) | **2** (new 1–2) |
| `largest = max(sizes.values())` | 2 (old 10–11) | 2 (new 3–4) |
| `winners = [...]` | 2 (old 12–13) | 2 (new 5–6) |
| `if len(winners) != 1:` | 2 (old 14–15) | 2 (new 7–8) |
| the two `return`s | 3 (old 16–18) | 3 (new 9–11) |

**All nine downstream mutants survive the refactor one for one** — `largest =
None`, `max(None)`, `winners = None`, `size != largest`, `len(winners) == 1`,
`!= 2`, the tie branch returning `True`, `label != winners[0]`, and
`winners[1]`. Those are every mutation that touches what this function
*decides*: the arg-max, the tie posture, and the winner comparison. Not one is
lost.

The net −7 is **8 removed and 1 added**, and the removed eight are all mutations
of `sizes[label] = sizes.get(label, 0) + 1`, a line that no longer exists:

| removed | mutation | differs / raises | |
|---|---|---:|---|
| old 2 | `sizes[label] = None` | 0 / 5436 | killable |
| old 3 | `get(label, 0) - 1` | **3780** / 0 | killable **by behaviour** |
| old 4 | `get(None, 0) + 1` | **3420** / 0 | killable **by behaviour** |
| old 5 | `get(label, None) + 1` | 0 / 5460 | killable |
| old 6 | `get(0) + 1` | 0 / 5460 | killable |
| old 7 | `get(label, ) + 1` | 0 / 5460 | killable |
| old 8 | `get(label, 1) + 1` | **0 / 0** | EQUIVALENT (the target) |
| old 9 | `+ 2` | **0 / 0** | EQUIVALENT (the target) |

The one added is `Counter(None)` (0 / 5460 — `Counter(None)` returns an empty
`Counter`, and `max()` of it raises one line later).

**Say this plainly rather than only counting: six of the eight removed were
killable, and two of those six — old 3 and old 4 — changed the answer rather
than merely raising.** Their test signal was "does some test distinguish
counting up from counting down, and keying by the right label from keying by
`None`". That signal is genuinely gone. It is gone because the code that could
carry those bugs is gone: tally correctness is now delegated to
`collections.Counter`, which is stdlib and not this repository's to test. An
earlier draft of this section said "five were killable" and did not mention that
two differed behaviourally; adversarial review re-derived the table and both
were wrong.

### The first run — the measurement this record said would settle it

CI job **97606765828** (run 32782293773, this pull request, 2026-08-24). The
diff touches exactly one mutatable function, so the scope is exactly it:

```
changed functions in scope:
  *product_app.synthesis_consensus.x__stance_majority_flags
  product_app.synthesis_consensus.x__stance_majority_flags__mutmut_*

mutants scored: 11 killed, 0 survived, 0 timeout (excluded), 0 no-tests
mutation score (killed / (killed+survived)) = 100.0% (threshold 80%)
```

Job wall clock 21:58:19 → 22:02:36 = **257 seconds** against the 1440-second
deadline, with **no truncation**. Three things this settles, none of them by
argument:

* **All 11 mutants of the Counter shape are killed by the suite as it stands.**
  Enumeration had shown them *killable*; this shows them *killed*. That is what
  replaces the "ASSUMED" caveat above, for the shape that shipped.
* **The gate produced a real `mutation score … = N%` line.** Measured over the
  20 `pull_request` runs before this one: **zero** did. That is #337's close
  condition — a real score for a real changed function, inside the deadline —
  met by a run rather than by an assertion.
* **The truncation branch did not fire**, which is why no `reached N of M` line
  appears above. A one-function scope is nowhere near the budget; that path
  stays exercised by `test_a_truncated_run_says_how_much_of_the_scope_it_reached`.
  What scope size *does* exhaust the budget is still unmeasured, and the
  denominator is the instrument that will say.

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

**`Counter(...).most_common()`.** **12** mutants instead of 11, because it
introduces an integer index literal (`ranked[0][1]`) whose mutation is less
obviously killable. Worse on the only metric that matters, though by one mutant
rather than four: an earlier draft carried **15** from a planning pass, and
re-running `mutate_file_contents` on the exact variant gives 12. The 15 could
not be reproduced and is withdrawn.

**(#337) Raise `MUTATION_RUN_DEADLINE_SECONDS`.** There is real headroom — 1454s
of an 1800s job ceiling, so ~1680s is available — and at the derived ~3.1s per
mutant that buys roughly +77 mutants — about **+23%** of the 337 verdicts the
truncated run produced. (An earlier draft said +17%. That is `240/1440`, the
increase in the *deadline*, attached to the wrong quantity: `77/337 = 22.8%`.) Rejected as a first move for the reason ADR-0065 already gave and
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
* **A DECORATOR is now the cheapest way to silence a mutant, and nothing here
  closes it.** Stated plainly because decision 4 must not be read as "the hatch
  is closed" — it closes the *pragma* route only. mutmut skips a decorated
  function entirely (`scope()`'s own `unmutatable()` documents this, and it is
  why #136 exists). Measured 2026-08-25: adding one `@functools.cache` to
  `_stance_majority_flags` took it from **11 mutants to 0**, and the whole file
  from 384 to 373. Decorate every changed function and `scope.txt` is empty, the
  recipe prints *"no MUTATABLE changed functions … nothing to mutate"* and exits
  0. It is not perfectly silent — `scope()` writes a `[decorated]` note per
  function to stderr, which lands in the run log — but **no gate reads that
  note**, and the job is advisory. This is a bigger hole than the one just
  closed and it is deliberately NOT fixed here: refusing decorators under `src/`
  is absurd, so the honest fix is to make the existing `[decorated]` count a
  reported, floored number, which is its own change with its own measurement.
  Filing it is the follow-on this record hands over.
  **Filed as #369 and closed by [ADR-0072](0072-a-decorator-that-removes-a-function-from-the-mutation-surface-is-recorded-in-a-committed-inventory.md)**
  — not by flooring the `[decorated]` note (diff-scoped, advisory, unread) but
  by a merge-blocking inventory of decorator-skipped functions that the tree is
  compared against.
* **Decision 3 is prose with no structural test.** The exit status is
  deliberately unchanged, so there is nothing but the wording to assert on. The
  shipped test pins the string and says in its own docstring that it cannot see
  whether the prose is true.
