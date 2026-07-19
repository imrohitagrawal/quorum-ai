# Changed-lines coverage gate (diff-cover)

Ledger item: **RB-1 remainder** (R2 Phase 0, enforcement machinery).

## What it enforces

Every line a change **adds or modifies** must be at least **95% covered** by the
test suite. Legacy code is untouched: the repo-wide floor stays **88%**
(`--cov-fail-under=88` in `pyproject.toml`), so nobody is forced to backfill
tests for code they did not write, but nobody can add materially untested code
either.

| Gate | Scope | Threshold | Blocking |
| --- | --- | --- | --- |
| `--cov-fail-under` (pytest) | whole repo | 88% | yes |
| `make diff-cover` | lines changed vs `origin/main` | 95% | yes (PRs only) |

## Why 95, not 100

100% forces coverage of defensive branches that are genuinely hard to exercise
hermetically (unreachable `else` arms, `except` blocks around OS/network
failures) and pushes authors toward coverage-shaped tests rather than
behavioural ones. 95% leaves a small, deliberate allowance while still failing
any change that ships an untested code path of real size.

The measurement below shows the allowance is small in practice, not a loophole:
on a branch with 173 changed lines, **9 or more** uncovered changed lines are
needed to breach 95%. The current branch has 4.

## Measured baseline (evidence)

Measured on the `feat/r2-s1-run-history-persistence` **working tree** (Phase 0 in
progress, so uncommitted tests were present), base `origin/main` (`5f7b1a6`, which
is also the merge-base), full suite, hermetic, $0.

Two things about this block are deliberate. It is labelled with the *tree and the
date*, never with a commit SHA: the changed-line total grows with every
uncommitted line a Phase-0 peer adds, so no SHA can reproduce it. And the
suite/coverage summary lines are kept **out of the fence** — only the diff-cover
section is quoted verbatim, because it is the part that justifies the threshold.
Re-running the command below on a later tree is expected to show a larger
`Total:`; what must hold is `Coverage: >= 95%`.

Captured 2026-07-19; the same run reported `Required test coverage of 88%
reached. Total coverage: 88.35%` and `735 passed, 4 skipped` (a point-in-time
note about that tree, not a number to re-derive):

```
$ make diff-cover
...
-------------
Diff Coverage
Diff: origin/main...HEAD, staged and unstaged changes
-------------
src/product_app/feedback_store.py (100%)
src/product_app/main.py (66.7%): Missing lines 280-281
src/product_app/query_runs.py (89.5%): Missing lines 1415-1416
src/product_app/run_history_store.py (100%)
-------------
Total:   173 lines
Missing: 4 lines
Coverage: 97%
-------------
MAKE_EXIT=0
```

**Measured changed-lines coverage: 97% (173 changed lines, 4 missing).**
The gate **passes** on the current branch — it was not tuned to fit; the
threshold was fixed at 95 first and the branch measured against it.

## Proof the gate bites (RED -> GREEN)

diff-cover needs a real git history, so the RED case was built as a synthetic
repo in scratch (no mutation of this working tree): a `main` commit, a feature
branch adding a 4-line `risky()` function, and a `coverage.xml` marking those
4 new lines `hits="0"`.

RED — new lines uncovered:

```
$ diff-cover coverage.xml --compare-branch=main --fail-under=95
Failure. Coverage is below 95%.
-------------
Diff Coverage
Diff: main...HEAD, staged and unstaged changes
-------------
src/m.py (0.0%): Missing lines 5-8
-------------
Total:   4 lines
Missing: 4 lines
Coverage: 0%
-------------
RED_EXIT=1
```

GREEN — same diff, same 4 lines flipped to `hits="1"`:

```
$ diff-cover coverage.xml --compare-branch=main --fail-under=95
-------------
Diff Coverage
Diff: main...HEAD, staged and unstaged changes
-------------
src/m.py (100%)
-------------
Total:   4 lines
Missing: 0 lines
Coverage: 100%
-------------
GREEN_EXIT=0
```

## The fetch-depth requirement (measured, not assumed)

`actions/checkout` defaults to `fetch-depth: 1`. A shallow clone has no base
ref, and the failure mode was measured on a `--depth 1` clone of the synthetic
repo:

```
$ diff-cover coverage.xml --compare-branch=origin/main --fail-under=95
ValueError:
Could not find the branch to compare to. Does 'origin/main' exist?
SHALLOW_EXIT=1
```

Good news: it **fails loud (exit 1)**, it does not silently score zero changed
lines. Still, a red build for the wrong reason is noise, so the CI job requires
both of:

1. `actions/checkout@v4` with `fetch-depth: 0`;
2. an explicit `git fetch origin ${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}`
   step — `fetch-depth: 0` alone fetches the PR ref, not necessarily the base
   branch under the `origin/<base>` name diff-cover expects.

Applying (2) to the shallow clone fixed it (measured):

```
$ git fetch origin main:refs/remotes/origin/main
 * [new branch]      main       -> origin/main
$ diff-cover coverage.xml --compare-branch=origin/main --fail-under=95
Coverage: 100%
FIXED_EXIT=0
```

`make diff-cover` also guards this itself: it `git rev-parse --verify`s
`$(DIFF_BASE)` before spending 30s on the suite, and prints the fix instead of
a diff-cover traceback.

```
$ make diff-cover DIFF_BASE=origin/does-not-exist
diff-cover: base ref 'origin/does-not-exist' is missing.
  CI needs actions/checkout with fetch-depth: 0 plus an explicit
  'git fetch origin <base>'. Locally: git fetch origin main.
make: *** [diff-cover] Error 1
```

## Reproducing locally

```bash
git fetch origin main            # the gate needs the base ref present
make diff-cover                  # DIFF_BASE defaults to origin/main
```

Overrides:

```bash
make diff-cover DIFF_BASE=origin/release-2   # different base branch
make diff-cover DIFF_COVER_MIN=100           # tighten locally before pushing
```

Artifacts written to `build/` (gitignored):

- `build/coverage/coverage.xml` — the Cobertura report diff-cover consumes
- `build/coverage/diff-cover.md` — per-file changed-lines report; uploaded by CI
  as the `diff-cover-report` artifact on every run (`if: always()`), so a red
  gate can be diagnosed without re-running anything

## CI wiring

Job `diff-cover` in `.github/workflows/ci.yml`, name
*"Changed-lines coverage >= 95% (blocking)"*. It is gated on
`if: github.event_name == 'pull_request'` because `github.base_ref` is empty on
push — **there is therefore no changed-lines gate on a direct push to `main`**;
only the 88% global floor applies there. Hermetic: `OPENROUTER_LIVE_EXECUTION_ENABLED=false`,
`QUORUM_RUNTIME_ENVIRONMENT=ci`, no secrets, $0.

## Known limits

- Not yet observed on a GitHub runner; every command above was executed on
  macOS against the real branch and a synthetic scratch repo.
- diff-cover measures *line* coverage of changed lines. A changed line executed
  by an assertion-free test still counts as covered — the mutation baseline
  (`make mutation-baseline`, advisory) is what probes test strength.
- Changes to non-`src/` code (e.g. `scripts/`) have no coverage data in
  `coverage.xml` (`--cov=src`) and are simply absent from the diff report.
