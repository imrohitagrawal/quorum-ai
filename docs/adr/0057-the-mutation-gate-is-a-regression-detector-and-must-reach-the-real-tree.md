# ADR-0057: The mutation gate is kept as a regression detector, and its root resolution must reach the real tree

## Status

Accepted — 2026-08-19. Addresses defect B of issue #338 (the abort). Defect A of
that issue — the gate reporting success on an empty scope — is deliberately NOT
addressed here and the issue stays open; see Consequences.

Sits on [ADR-0044](0044-mutation-scope-dead-glob-detection-stays-pure-ast.md)
(dead-glob detection in the mutation scope stays pure AST) and
[ADR-0047](0047-gate-detectors-resolve-ambiguity-toward-a-red-gate.md) (a detector
resolves ambiguity toward RED).

## Context

Two separate things, kept separate on purpose.

**(1) What the gate is for.** `docs/metrics/defect-discovery-audit.md` records
**0 of 16** `src/` defects caught by an automated check and **10 of 16** found
by adversarial review. So the mutation gate is not a defect finder here and
never has been. It is kept as a **regression detector**: it exists to notice
when a test stops biting. That framing is the decision, and it is why exactly
one cheap fix ships in this record and nothing else does — no verdict wording,
no Makefile change, no threshold move.

**(2) Why it measured nothing.** `mutmut run` copies the project into
`./mutants/` — a directory *inside* the repository, kept untracked by
`.gitignore:54` — and re-runs the whole suite from in there to collect baseline
statistics. Two specs derived their root as
`Path(__file__).resolve().parents[2]` and handed it to `git ls-files` as a
working directory.

State the cause precisely, because the obvious guess is wrong in a way that
would produce a non-fix. It is **not** that `docs/` was missing from the copy:
`pyproject.toml` lists `"docs"` in `[tool.mutmut].also_copy`, and the copy
really does hold the files. The cause is that a `git ls-files` **pathspec is
resolved relative to the working directory**. Run from a directory that sits
inside the repository but holds no *tracked* files, git exits **0** with
**empty** output — a silent wrong answer, not an error. Outside any repository
the same command is `fatal: not a git repository`, exit 128, which is a louder
and different failure; a reproduction placed in a bare temporary directory
therefore models the wrong thing.

The anti-vacuity floors over that empty list then failed, mutmut's `-x` ended
stats collection, and the gate exited non-zero having scored zero mutants.

## Decision

1. Resolve the root with `tests.repo_root.find_repo_root(Path(__file__))` — it
   walks to the first `.git` ancestor, and `./mutants/` has none, so it reaches
   the real tree — in **both** offending specs. Fixing only one moves the `-x`
   abort down one file rather than removing it.
2. Ship a guard, `tests/unit/test_mutation_gate_root_resolution.py`, that
   **derives** the offender set from the tree by AST rather than listing it,
   and then **runs** the discovered specs inside a nested, mutmut-shaped copy.
   A hand-maintained allowlist is what let this defect through the guard that
   already existed for it.

   The scan is derived, but it is not total, and the difference matters
   because the first draft of it was total-sounding and quietly FAILED OPEN.
   Per [ADR-0047](0047-gate-detectors-resolve-ambiguity-toward-a-red-gate.md)
   it now resolves an input it cannot classify toward RED. Four shapes that a
   review demonstrated were silently dropped are now offenders, each with a
   literal case in `test_the_classifier_never_drops_a_cwd_scoped_git_call`:
   an annotated or tuple-target root binding, a `cwd=` expression naming no
   module-level root (`cwd=str(ROOT)`), **no `cwd=` keyword at all** (under
   `mutmut run` the process working directory already IS `./mutants/`), and a
   runner imported bare with `from subprocess import run`. Measured on this
   tree, closing all four adds **zero** new offenders, so the fail-closed
   posture costs no churn today.

   One hole is left open ON PURPOSE and is written on the function: the
   subcommand must appear as a string literal, so a call that builds its argv
   dynamically (`["git", *args]`) is not classified. There are **seven** such
   calls under `tests/` today, all driving throwaway repositories with a local
   `cwd`; failing closed on them would make the guard red on seven correct
   calls. The guard's honest contract is therefore "every literal-argv
   cwd-scoped git call, classified, with unfamiliar shapes treated as
   offenders" — not "every possible spelling".
3. Change nothing about what the gate says when it finishes. The verdict
   wording is a separate concern and stays on its parked branch.

## Measurements (2026-08-19, macOS/darwin 25.5.0, CPython 3.12.13)

Population figures are measured on `origin/main` at `e4c58a2`, this branch's
merge base, using the main checkout's interpreter (`.venv/bin/python -m
pytest`). This branch adds two tracked files, so the same commands run on the
merged tree print `294` / `111` / `55` / `1202`. The ref is named because a
bare number here would be false of the tree this record ships in.

| Question | Command | Result |
|---|---|---|
| Tracked docs, real root | `git ls-files "docs/*.md" \| wc -l` | `293` |
| …of which `docs/NN-` | `git ls-files "docs/*.md" \| grep -cE '^docs/[0-9]+-'` | `111` |
| …of which `docs/adr/NNNN-` | `git ls-files "docs/*.md" \| grep -cE '^docs/adr/[0-9]+-'` | `54` |
| Tracked files, real root | `git ls-files \| wc -l` | `1200` |
| The same questions from inside a nested copy | the guard's `_SHAPE_PROBE`, asserted by `test_the_copy_reproduces_gits_silent_empty_answer` | exit status `0`, **0** paths |
| The abort in CI | `gh run view 32057683059 --json conclusion,jobs` | run rollup `success`, Mutation **job** conclusion `failure` |
| …and its text | `gh run view 32057683059 --log \| grep -c 'assert 0 > 100'` | `2`; the log also carries `failed to collect stats` |

Rule 2 in the flesh: the run was green and the job was red, because the job is
advisory.

**The guard bites, once per file.** Each offender was reverted on its own (`cp`
aside, mutate, restore from the copy, `diff -q` to confirm), so the record shows
each fix is load-bearing rather than only their union. Both reverts gave
`2 failed, 2 passed`, failing
`test_every_spec_the_baseline_runs_resolves_the_real_repository_root` and
`test_the_git_reading_specs_pass_inside_a_mutmut_shaped_copy`. Before either
fix, the guard was `2 failed, 2 passed`; after both, `4 passed`.

**Cost of the chosen form.** `find_repo_root` raises rather than guessing, and
a module-level raise is a pytest *collection* error, which interrupts the whole
session. Measured with `pytest tests -q --collect-only` in a copy extracted by
`git archive HEAD | tar -x` outside any repository:

| Tree | Collection errors | Outcome |
|---|---|---|
| clean `main` at e4c58a2 | 4 | `3033 tests collected, 4 errors`, `Interrupted` |
| this branch | 7 | `3019 tests collected, 7 errors`, `Interrupted` |

Note what that says: `main` **already** interrupts. Five modules on `main`
import `find_repo_root` (`git grep -l 'from tests.repo_root import find_repo_root'
-- 'tests/*'`), four of them binding it at module level, which is where a raise
becomes a collection error. This change widens an existing hole from four
modules to seven; it does not open it.

## Consequences

- A review copy made with `git archive` cannot run the suite. Use
  `git clone --no-hardlinks`, which keeps a `.git` and therefore a resolvable
  root. `AGENTS.md` rule 12b still prescribes `git archive`; that sentence was
  already wrong before this change (see the table above) and editing the
  rulebook is a second concern, so it is recorded here, recorded on issue #338,
  and left for its own change. It is not theoretical: it bit a reviewer of this
  very branch, who had to fall back to `git clone --no-hardlinks`.
- The guard costs **four** full project copies per suite run, not two: two
  tests each build a mutmut-shaped tree, and each build copies the project
  twice (outer repository, then the nested `mutants/`). Counted by
  instrumenting `_copy_project`. Wall clock on darwin, four reps of
  `pytest tests/unit/test_mutation_gate_root_resolution.py -q --no-cov`:
  **5.2s, 5.4s, 6.1s, 6.0s**. A reviewer on the same box measured 8.4–13.0s,
  and the Linux CI `pytest (Python 3.12)` job moved 236.67s → 255.39s across
  one sample each side — so treat six seconds as this box's figure, not a
  portable one, and the CI delta as unattributed. It carries
  `pytest.mark.repo_introspection` so mutmut deselects it — left selected it
  would build those four copies *per mutant* against the run deadline
  (`Makefile:272`, `MUTATION_RUN_DEADLINE_SECONDS ?= 1440`), recreating "the
  gate produced no number" by a different route — and it is registered in
  `DESELECTED_FROM_THE_MUTANT_RUN` so the deselection is a reviewed decision
  rather than a silent one.
- The guard's throwaway repository now copies `.gitignore`. Without it,
  `git add -A` indexes files the real repository never tracks: a single
  `.DS_Store` under `e2e/tests/` on a developer's Mac turns
  `test_no_tracked_ds_store` red *inside* the copy, failing the guard locally
  while CI — a fresh Linux checkout — stays green. Proved both directions: with
  such a file present the guard passes, and dropping `.gitignore` from the
  harness turns it red naming that exact test.
- The anti-vacuity floors stay as written (`> 100`, `>= 40`, `> 1000`). Their
  populations on the tree this record ships in are **111, 55 and 1202**; at the
  merge base they were 111, 54 and 1200, and they move with every ADR added, so
  the named ref is what makes the sentence checkable rather than the digits.
  The margins are thin and shrink only by deletion. Recorded, not changed:
  moving a floor is its own change and needs its own proof.
- The guard's throwaway repository is a SUBSET of the real tree — it holds only
  `also_copy` + `source_paths` + the implicit set — so it tracks **1114** files
  where the real tree tracks 1202. The `> 1000` floor is therefore evaluated
  inside the copy with 114 of margin, not 202. A trimmed `also_copy` entry
  could take the copy under that floor and make the guard red saying the
  mutation gate aborts, which would be false and would name the wrong cause on
  a blocking context. `test_the_copy_reproduces_gits_silent_empty_answer` now
  asserts the copy tracks at least 85% of the real tree, so that shrink fails
  naming the harness instead. Proved by trimming seven `also_copy` entries:
  `AssertionError: the throwaway repository tracks 965 files against the real
  tree's 1202. This harness no longer models the real tree`.
- **A deadline-truncated run now reads as GREEN, and nothing marks it.** This
  is the honest cost of the change and it is not fixed here. `run_with_deadline`
  exits **0** on its own deadline by design, so the recipe falls through to
  `report()`, which skips every mutant whose `exit_code_by_key` value is `None`
  (`if code is None: continue`) — exactly the state a killed run leaves for the
  mutants that never ran. A run that finished 2 of 500 mutants, both killed,
  prints `mutation score ... = 100.0%` and exits 0. The deadline message does
  reach the job log through `tail -40 build/mutation/run.log`, but neither
  `score.txt` nor the job conclusion carries a partial marker. So this change
  moves the gate's dominant failure from a LOUD red at second zero to a QUIET
  green. Marking a truncated run is the parked verdict/UNMEASURED work and the
  first thing issue 337 will need. Verified by feeding `report()` a
  hand-written `.meta` holding three `None` exit codes: `mutants scored: 2
  killed, 0 survived` / `mutation score ... = 100.0%` / exit 0.
- **This record does not produce a mutation score, and says so.** The fix
  converts "aborts having done nothing" into "runs until the deadline". That is
  the information issue 337 asks for; it is not issue 337's close condition,
  which is one pull-request run producing a real score line for a real changed
  function inside the deadline. Issue 337 is named in prose only, with no
  closing keyword — a merge body containing even a negated reference closes an
  issue, measured on PR #174.
- Issue #338 is two defects and stays open. Its titled half — the gate
  reporting success on an empty scope — is untouched here, and this very change
  demonstrates it: the mutation scope is *changed functions under `src/`*, this
  change touches only `tests/` and `docs/`, so the scope is empty and the
  advisory mutation job will report green having measured nothing. The in-CI
  evidence that the abort is gone is therefore the guard test, not the mutation
  job.

## Rejected alternatives

1. **`find_repo_root_or_skip`** (it exists, on the unmerged branch
   `origin/fix/mutation-gate-measures-nothing`; the claim that it exists
   nowhere is false). It skips instead of raising when there is no `.git`, so a
   `git archive` copy runs. Rejected because it converts previously
   unskippable repository-introspection modules into silently skippable ones
   with no floor asserting they ran — issue #338 records that worry itself. A
   skipped gate and a passing gate look identical, and this repository has paid
   for that confusion more than once.
2. **Lazy resolution inside a helper, or `try`/`except` with a `parents[2]`
   fallback.** Either keeps the archive copy alive. Both defeat the guard: its
   discovery inspects top-level assignments, so a function-local or
   try-wrapped binding makes the module invisible to the scan and takes the
   positive partner red, and a `parents[2]` fallback is the very derivation the
   guard exists to forbid. Adopting one means rewriting the guard's discovery —
   a larger diff bought for a reviewer-workflow convenience.
3. **Marking both offenders `repo_introspection`.** They would stop running
   inside mutmut entirely. That hides the abort instead of fixing it, and it is
   precisely the evasion `tests/unit/test_mutation_test_set_integrity.py`
   exists to pin against.
4. **Adding `docs` to `[tool.mutmut].also_copy`.** A non-fix: it is already
   there and the copy already holds the files. The cause is pathspec-versus-
   working-directory, not a missing directory.
5. **Deleting or loosening the anti-vacuity floors to stop the abort.**
   Rejected outright. The floors are the only thing between this gate and a
   green run over nothing, which is the other half of #338.
6. **Retiring the mutation gate.** Considered and rejected on the evidence in
   Context: it is a poor defect finder here, which is an argument about what to
   expect from it, not an argument for deleting the one instrument that checks
   whether a test still bites.

## Related

- [ADR-0044](0044-mutation-scope-dead-glob-detection-stays-pure-ast.md) — dead-glob detection stays pure AST.
- [ADR-0047](0047-gate-detectors-resolve-ambiguity-toward-a-red-gate.md) — ambiguity resolves toward RED.
- [ADR-0050](0050-duplicate-adr-numbers-are-refused-at-both-discovery-points.md) — why this file's number is checked in two places.
- `docs/metrics/defect-discovery-audit.md` — the 0-of-16 / 10-of-16 measurement.
- `docs/metrics/mutation-gate-study.md` — why the gate is advisory.
- `tests/repo_root.py` and `tests/unit/test_repo_root_resolution.py` — the helper and its own tests.
