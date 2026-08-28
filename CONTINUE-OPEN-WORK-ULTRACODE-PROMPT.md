# Continue: work the board

Rewritten 2026-08-28, after the session that shipped the board (ADR-0079),
the mutants-root fix, and W16 (ADR-0080).

**This file is the PROCEDURE. `docs/65-open-work.md` is the STATE.**
This file deliberately carries **no list of work**. Its predecessor did, and the
list was stale inside one session — which is the failure the board exists to end.
Where the two disagree, the board wins: a gate checks it and nothing checks this.

---

## The prompt to paste into a fresh session

> Read `CONTINUE-OPEN-WORK-ULTRACODE-PROMPT.md` at the repo root, then
> `docs/65-open-work.md`, and work the board. Select, plan, build, review,
> merge, verify and close out each package without waiting for me, except at
> the STOP conditions those documents name.
>
> **Treat every claim you inherit as UNVERIFIED.** Re-derive by command before
> acting. Line numbers rot — grep for symbols. Roughly half of what a handoff
> asserts does not survive contact with the tree.
>
> Use the `work-package-protocol` skill. One work package at a time, merged
> before the next starts. **Fan out for review, never for building.**
>
> You may push, open pull requests, merge and deploy.
>
> **SPEND NOTHING.** `OPENROUTER_LIVE_EXECUTION_ENABLED` stays `false`
> everywhere including production. If a question can only be settled by
> spending, mark it UNVERIFIED, name the exact probe, and ask.
>
> You may use `Workflow` for review phases. **Ceiling: 14 agents per workflow,
> one workflow at a time.** Do not turn ultracode on.

---

## Start here, every time

```bash
git -C . fetch origin && git status -sb && git worktree list
python3 scripts/check_open_work.py --check     # the board vs the tree
gh issue list --state open
curl -s https://quorum.stackclimb.com/status | jq '{build_sha, live_execution, judge_enabled}'
```

`main`, `origin/main` and `build_sha` should agree. If they do not, find out why
before starting anything.

## Selecting the next package

The board's `Depends on` column is binding. Beyond that, **prefer independent,
issue-backed defects over the long W1→W2→W3 lane.** As of 2026-08-28 that lane
ends in a row formally deferred by ADR-0081 and cannot be validated without
spend, while **W12 (#379), W11 (#380), W6 (#383) and W10 (#382)** carry open
issues with no dependencies at all. (A fifth issue row, W13/#268, also has no
dependency — but it is marked **STOP**, because it moves a cost guardrail.)

**Club before you select** (rule 17g). Two rows in the same narrow area, one a
direct follow-on of the other, are ONE package with one reviewer and one deploy —
not two. Say which rows are in the cluster and why each belongs.

Open the pull request with one line saying why this outranks the top of the
backlog. If that line cannot be written honestly, the ranking is wrong.

## Two decisions are already made — do not re-open them

The product owner settled both on 2026-08-28. They are not open questions and
they are not yours to revisit:

- **The per-call money constants do not move** until #290 is built and its cost
  is measured. `SOFT_THRESHOLD_USD = 0.15`, `HARD_LIMIT_USD = 0.25`,
  `DAILY_CAP_USD = 0.20`, `GLOBAL_DAILY_CEILING_USD = 5.00` stay as they are.
  Board row **W3**, **ADR-0081**. An earlier archived plan says to raise them —
  **that plan is superseded on this point.**
- **`min_machines_running` stays `0`.** The app keeps scaling to zero.
  **ADR-0082**. This is no longer a board row.

If you believe either should change, bring the measurement and ask. Do not
change a number and explain afterwards.

## STOP — do not guess these

- Any **money, cost or safety guardrail value** that is not measured. The board
  marks these **STOP**. Moving one as a side effect of another package is the
  failure mode, not the exception.
- **A published requirement.** Before moving any number:
  `grep -rn "<value>" docs/ src/product_app/templates/`. `quorum_run_deadline_seconds`
  looked like a knob and turned out to be NFR-001, NFR-004 and AC-021, published
  in six places including the operator dashboard. No gate covers that prose.
- Anything needing **spend**.
- **A briefed premise turns out false** and the package's shape depends on it.
  Say so loudly; never repair it silently and carry on.
- **Review hits its cap with findings open.** `AGENTS.md` rule 12, verbatim:
  *"Cap review at TWO rounds, then STOP and escalate with open findings listed.
  If two fixes in a row add defects, change the approach. Expect your own fix to
  introduce a defect — budget a round for it."* Quoted rather than paraphrased,
  because a first draft of this file narrowed it and dropped the two-round cap.
- **The mechanism is wrong, not just the implementation.** Two fixes that fail
  to close the *same* hole means the approach is wrong, not the code. Stop, do
  the root-cause analysis, and put the change of approach to the human — do not
  patch a third time. This happened on the board itself; the third design is
  what shipped.
- **The item is bigger than it looked.** Say so and stop; do not file and continue.

## The board is generated — never edit the State column

```bash
make open-work-write     # regenerate from the tree
```

`PENDING` / `DONE` / `UNPINNED` are DERIVED. Editing that column fails
`--check` immediately. Add a row and you must edit the count sentence in the
same change. Update the board **in the same pull request that changes an item's
state** — `make validate` forces it. ADR-0079 has the reasoning and the two
designs that were defeated before this one.

## Gates

Read every exit status **directly, never through a pipe** (rule 13f):

```bash
uv sync --all-extras --python 3.12          # a fresh worktree needs this FIRST
make quality  > /tmp/q.log 2>&1; echo "EXIT=$?"
make validate > /tmp/v.log 2>&1; echo "EXIT=$?"
make diff-cover DIFF_BASE=origin/main       # COMMIT first — rule 15a
make api-contract && make openapi-check && make security-scan
# e2e per rule 13 if UI, specs or fixtures move
```

Re-derive the required checks from branch protection, never from a list:
`gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`

**Mutation-prove every new test** against a green unmutated baseline: `cp` the
file aside, mutate, restore from the copy, confirm with `diff -q`. Never
`git checkout` — it discards uncommitted work. A mutant whose anchor did not
match never ran; count it as neither killed nor survived.

## Review

| Phase | Shape | Agents |
|---|---|---|
| Failure-mode enumeration — money/auth/transport only (rule 16e) | 4 lenses + 1 synthesiser | 5 |
| Docs-only or a few lines | solo | 0 |
| A normal code diff | 3–4 finders + top-3 × 2 refuters | 9–10 |
| Money / auth / transport | 4 finders + top-5 × 2 refuters | 14 |

Rules that earn the fan its cost, all paid for:

1. **Severity-sort before applying the cap**, and `log()` what was dropped.
2. **A finding dies only if BOTH refuters refute it.**
3. **Verify every surviving finding yourself** before acting. Refuters kill real
   noise *and* uphold real defects; neither outcome substitutes for running the
   command yourself (`AGENTS.md` rule 11).
4. **Budget a fix round** — `AGENTS.md` rule 12 says to expect your own fix to
   introduce a defect. In the 2026-08-28 session every package needed one,
   including the docs-only ones. That is a session observation, not a repo
   measurement; the graded evidence for review yield is
   `docs/evidence/2026-07-30-engineering-practice.md` row 2.1.
5. Tell every agent **IN CAPITALS**: read-only; no `git checkout` / `git stash` /
   `sed -i`; its own clone for anything it executes; no pytest in the shared tree;
   `PYTHONDONTWRITEBYTECODE=1`; a unique scratch dir.
6. **Tell every reviewer to audit the diff's PROSE** (rule 11a). Every false claim
   this repo has shipped lived in prose, and reviewers not asked to look do not look.
7. **Never edit the tree while a reviewer or a gate is running** (rule 9a).

## Traps — measured, and the newest ones bit this session

1. **A fresh worktree: run `uv sync --all-extras --python 3.12` BEFORE any
   `uv run`.** A bare `uv run` builds a 3.14 venv with no pytest, and every
   shell-out then reports a false failure.
2. **A test that reads the repo must use `tests/repo_root.find_repo_root`, never
   `Path(__file__).parents[n]`.** mutmut re-runs the suite inside `./mutants/`,
   where a parent count points at the copy. This shipped in #390 and reddened
   the mutation gate with a job that **measured nothing**.
3. **A red gate is not evidence it measured; a green one is not evidence it ran.**
   Open the log and find the number. A gate can be green because nothing was in
   scope — its own log says so.
4. **`gh pr merge` refused while `gh pr checks` shows all green** usually means
   duplicate in-flight check runs. Look for `conclusion: null`:
   `gh api repos/:owner/:repo/commits/<SHA>/check-runs --jq '.check_runs[] | select(.conclusion==null) | .name'`
   Wait them out; `gh pr view <n> --json mergeStateStatus` flips `BLOCKED` → `CLEAN`.
5. **`make diff-cover` runs pytest first**, so it exits non-zero when ANY test
   fails, coverage notwithstanding. Read which failed before blaming coverage.
6. **A local failure your diff cannot explain is a phantom until you re-run it on
   a clean tree**: `git archive origin/main | tar -x -C <dir>`. The known example
   is `test_the_budget_covers_the_header_phase_not_only_the_body` (board row
   **W19**), which asserts `wall < 4.0` with about 2% of margin and flips with
   machine load — measured 2026-08-28 on one box: **5 of 5 failing at 4.13–4.18s
   under concurrent load, 6 of 6 passing at 3.92–3.96s idle**, and 11 of 11
   passing for an independent reviewer. **Do not dismiss a red result there as
   W19 without re-running it isolated on an idle machine** — a real regression
   would look identical.
7. **A merge fires 3–5 deploy runs; most are `cancelled` by concurrency.**
   Enumerate every run for the SHA and read each Deploy **JOB**, never the rollup.
   `gh run list --commit <SHA>` can return `[]` before runs exist, so assert one exists.
8. **`make close-guard` before every merge**, with the text in the ENVIRONMENT.
   A close keyword next to `#N` closes it, and GitHub cannot read negation.
9. **`make next` overwrites `docs/00-factory-console.md` wholesale**, and
   `make handoff` overwrites `docs/session-handoff.md`. Edit the GENERATORS.
10. **`pytest-timeout` is NOT installed.** `--timeout` makes pytest error out and
    every mutant then looks killed while nothing is tested.

## Done means shipped

Merged **and** verified running in production: the Deploy **job** reports
`success` (not the run rollup), `/status.build_sha` equals the merged SHA, and
the thing you built actually fires. **Where the third is impossible, say so
plainly** — with live execution off, most provider-path work is latent-correct,
covered by tests and mutants and by nothing observable. That is an honest report.

Then close out, in this order: local `main` fast-forward
(`git merge --ff-only origin/main` from the main checkout), **worktree first**,
then delete the branch local and remote. Report cleanup with command output.

## Closing report

```
## Done
## Verified myself      (the command, and what it printed)
## Cleanup              (each line confirmed by a command)
## Pending              (nothing tidied away)
## Next action          (or the decision now owed by the human)
```

Say explicitly whether work is pushed, merged, and running in production. Keep
what YOU ran separate from what a subagent reported.
