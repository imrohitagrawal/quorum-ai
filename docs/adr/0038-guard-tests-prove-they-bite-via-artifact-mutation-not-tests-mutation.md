# ADR-0038: A guard test proves it bites by mutating the artifact it asserts about, not by mutating `tests/`

## Status

Accepted — 2026-08-14 (#143, #167)

## Context

The mutation gate (`MUTMUT_SCOPE_PY` in the Makefile) mutates `src/` and uses
`tests/` as the oracle. That leaves a **guard test** — one whose subject is
repo state (a Makefile recipe, a workflow file, a script, a constant) rather
than `src/` — with no mechanism proving it can fail. #167 measured the cost of
that gap on PR #164 alone: three vacuous guard tests shipped and were caught
only by human review, all the same shape — a substring assertion over a file
that matches the prose explaining the thing, not the thing.

#143 is the concrete case this ADR was written against:
`scripts/replay_mutation_scope.py`'s own docstring claimed it "Mirrors
MUTMUT_SCOPE_PY exactly," and that equivalence was quoted as evidence
throughout `docs/metrics/mutation-gate-study.md` (the 8% silent-pass rate, the
scope-size distribution) — unpinned by any test. It was false: the replay
script had no `unmutatable()`/decorated-function exclusion at all, so it could
name a mutant glob the Makefile's real gate would never generate, and could
silently drift further at any time. Confirmed with a differential run over the
last 60 real commits on `main`: **14 of 51 examined commits mismatched**
between the two implementations before the fix in this PR.

## Decision

**A guard test proves it can fail by mutating a throwaway copy of the specific
artifact it asserts about, never by mutating `tests/` itself.**
`tests/guard_bite.py::assert_guard_bites` is the reusable mechanism: it copies
the named file into a fresh `tempfile.mkdtemp()`, proves the guard passes
unmutated (the positive partner), applies a caller-supplied mutation to the
copy, proves the guard now raises, then discards the scratch directory. The
tracked file on disk is only ever read.

Demonstrated on #143's fix: `scripts/replay_mutation_scope.py` now ports
`unmutatable()` and the decorated-class `frozen` propagation from the
Makefile's `MUTMUT_SCOPE_PY` byte-for-byte, and
`tests/unit/test_replay_scope_matches_makefile_scope.py` has two tests —

1. a differential test that extracts the real `MUTMUT_SCOPE_PY` block from the
   Makefile, runs it (via a disposable `git clone --local` + per-commit
   `git checkout`, since it reads files off disk) alongside the real
   `replay_mutation_scope.scope()` (via `git show`, no checkout) over the last
   60 real commits touching `src/**.py`, and asserts the glob sets are
   identical for every one — with an anti-vacuity floor (`examined > 0`);
2. a guard-bite test that reverts exactly the fix above (deletes
   `unmutatable()`, makes every matched function glob unconditionally) inside
   a throwaway copy via `assert_guard_bites`, and proves test (1)'s comparison
   logic goes red against that reversion, on a purpose-built decorated-function
   fixture.

Both were run RED (against the pre-fix `scripts/replay_mutation_scope.py`,
restored via `git show origin/main:... > file` / copy-aside, never
`git checkout`) and GREEN (post-fix), per rule 6.

## Rejected alternatives

- **Mutate `tests/` itself and run the mutation gate over it.** #167 measured
  this directly: `src/` alone (16,686 lines) generates 9,370 mutants in 23.4s
  (7.32/s); `tests/` is 47,969 lines — 2.9× larger — so the same density
  extrapolates to ~27,000 mutants, on the order of an hour, for a one-line
  guard change. That is the exact failure that stranded every merge
  2026-07-17..07-21 (`docs/metrics/mutation-gate-study.md` §3.3), and it
  contradicts published practice cited in the same study: nobody blocks a
  merge on a mutation score; Facebook measured 0% fix rate at merge-time vs
  >70% at review-time for the identical analysis.
- **A lint flagging bare `<literal> in <file-contents>` assertions in
  `tests/`** (#167's cheapest-listed option). Rejected for THIS PR on blast
  radius: several existing, already-reviewed guard tests
  (`test_mutation_gate_integrity.py`'s `mutation_recipe` substring checks
  among them) are exactly that shape by design, over `make -n` output rather
  than a parsed structure, and a repo-wide lint would need per-test triage to
  avoid false positives on patterns already accepted. Left as a follow-up
  (#167 still open for it), not built here — this ADR closes the
  paired-mutation mechanism (#167's option 2) and its first real instance
  only.
- **Mutate the real tracked file in place and restore from a backup path.**
  Rejected: a crash between mutate and restore leaves the tracked file
  corrupted, and it adds nothing over a throwaway copy — `assert_guard_bites`
  never writes to the artifact's real path at all, so there is no restore step
  that can fail.

## Consequences

- Any future guard test can call `assert_guard_bites` to prove it bites,
  cheaply (one extra guard invocation, not a suite run), without inventing its
  own copy-aside/mutate/restore scaffolding each time.
- `scripts/replay_mutation_scope.py`'s glob output changed for any commit
  whose changed lines land only in decorated (mutmut-unmutatable) functions —
  those commits no longer glob a mutant name the real gate would never
  generate. Re-running the replay tool over the last 200 commits on `main`
  measures a 13% blind-spot rate (14/109), not the study's original 8% (5/61)
  — the study's number predates this fix and was produced by a version of the
  tool with no decorator awareness at all. `docs/metrics/mutation-gate-study.md`
  is not re-derived in this PR (out of scope — one concern per PR, #167/#143
  only); its §3.1/§3.2 figures should be treated as stale pending a dedicated
  re-run.
- The differential test requires real `origin/main` history at test time
  (`git log ... --first-parent origin/main -- src`) and a full, unshallowed
  fetch to walk it meaningfully; the repo's `test.yml` CI job already checks
  out with `fetch-depth: 0` for this reason (shared with `diff-cover` and other
  `DIFF_BASE=origin/main` consumers), so no new CI configuration was needed.

## Related

- #143, #167
- `tests/guard_bite.py`, `tests/unit/test_replay_scope_matches_makefile_scope.py`
- `scripts/replay_mutation_scope.py`, `Makefile` (`MUTMUT_SCOPE_PY`)
- `docs/metrics/mutation-gate-study.md` §3 (figures predate this fix — see
  Consequences)
