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
> **SPEND NOTHING BY DEFAULT.** `OPENROUTER_LIVE_EXECUTION_ENABLED` stays
> `false` for all ordinary work. If a question can only be settled by spending,
> mark it UNVERIFIED, name the exact probe, and ask. **The one exception is the
> W1 measurement window in "The W1 → #290 lane" below. It does not generalise
> to anything else, and it is not yours to open — see that section.**
>
> **W1 is DONE and its measurement window is closed** (2026-08-31). The
> override that used to sit here is spent — select by board ranking again, and
> read "The W1 lane, and what it left behind" below before touching #290.
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
issue-backed defects over the long W1→W2→W3 lane** — that lane ends in a row
formally deferred by ADR-0081 and cannot be validated without spend.

**Do not trust the names in this paragraph — re-derive them.** An earlier
revision listed four rows as available; three (W12/#379, W6/#383, W10/#382)
shipped and the sentence went stale within days, which is the exact failure this
file exists to avoid. Get the live list instead:

```bash
python3 scripts/check_open_work.py --check   # per-row state, derived from the tree
gh issue list --state open
```

As of `5719712` (2026-08-29) that yields **11 PENDING, 4 DONE**, with
**W11 (#380)** the remaining issue-backed row that has no dependency, and
**W20 (#394)** likewise unblocked though its own row records zero live impact
today. (W13/#268 also has no dependency — but it is **STOP**, it moves a cost
guardrail.)

**This ranking is currently OVERRIDDEN: work W1 first.** See "The W1 → #290
lane" below. The rows above are what you return to once that lane is done —
and the override is exactly why it exists, because ranking never reaches W1.

**Club before you select** (rule 17g). Two rows in the same narrow area, one a
direct follow-on of the other, are ONE package with one reviewer and one deploy —
not two. Say which rows are in the cluster and why each belongs.

Open the pull request with one line saying why this outranks the top of the
backlog. If that line cannot be written honestly, the ranking is wrong.

## The W1 lane, and what it left behind — CLOSED 2026-08-31

**W1 (+W15) is merged, deployed and MEASURED.** The override that forced it
ahead of ranking is spent. Do not re-run it; read this for what it settled and
what it cost.

### What the live window settled — these are no longer assumptions

One attended window (`2026-08-31T04:05Z–05:45Z`), two production runs, read off
`/data/telemetry-tokens.jsonl` via `fly ssh console` — the only place
`stream_terminator` is written:

| Question | Verdict |
|---|---|
| Does `usage` arrive with no `stream_options`? | **YES** — `usage_absent: false` on 24 of 24 |
| Is `data: [DONE]` sent? | **YES** — `stream_terminator: "done"` on 24 of 24 |
| Do all four default models honour `stream: true`? | **YES** — 8 of 8 slot calls live, `local_count` 0 |

Six distinct models across those records. `stream_options` stays off the wire on
evidence now, not on a hedge. Ledger delta `0 → 0.0871`; the judge ran and its
spend reaches no ledger, so the true total is higher and is not quotable.

**Unplanned, and the more valuable half:** the same records gave issue #268 its
first real distribution — `injected_tokens_est` 2173–2510 on the eight `:online`
calls, **8 of 8 above `cost_web_search_context_tokens = 2000`**. Recorded on
#268. The constant is NOT moved: money guardrail, ADR-0081 freezes the class,
and n=8 sharing one query shape is a start, not a bound.

### What it cost, so nobody repeats it

**Production served a live posture for ~9.5h, ~8.6h of it past the window's own
expiry.** Zero spend beyond the sanctioned runs — luck, not design. The
watchdog alerted correctly (#406). The revert was *blocked by CI*: the gate
refuses `flag off + window still open`, so flipping the flag alone has no valid
form while the window covers `now`. **Closing a window means flag → `false` AND
`expires_at` → now, in the SAME commit.** **#407 is fixed**: run
`make close-window` (or `python3 scripts/close_live_window.py`) — it performs
both edits atomically and refuses loudly if nothing is currently open. Still
verify `/status.live_execution` yourself afterward.

### #290 (W2) is now unblocked

W1 was the dependency and it is measured. W2 can be BUILT hermetically today;
validating it still needs spend, and W3 stays deferred (ADR-0081).

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
   **On 2026-08-29 the two-round cap FIRED for real** (W12/#379): round 1 found
   a genuine design gap, and round 2 found that the *fix for it* shipped two
   false docstring claims plus a vacuous test that stayed green under the exact
   mutation it existed to catch. Both rounds were unanimous on verification.
   That is the rule working — and the correct response was to STOP and put the
   choice to the human, who chose to correct the prose and the test rather than
   re-cut the design a third time. **Escalating is a normal outcome, not a
   failure.** Do not quietly start a third fix.
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
   a clean tree**: `git archive origin/main | tar -x -C <dir>`. The long-running
   example was `test_the_budget_covers_the_header_phase_not_only_the_body`
   (board row **W19**), which asserted `wall < 4.0` with about 2% of margin and
   flipped with machine load — 10 of 10 failing on unmodified `origin/main` at
   load ~6 when it was finally measured. **That is FIXED as of 2026-09-01
   (ADR-0089) and the advice has inverted: a red there is no longer a load
   flake.** The bound was replaced by an assertion on the budget ARGUMENT
   handed to the body read, which is load-INSENSITIVE (28 reps over load
   3.6–20.9 stayed in 3.762–4.106 s against a 3.0 bound — 25% headroom). Do
   not dismiss it as load. The one non-load red it can give is `this test
   measured nothing`, which means `urlopen` never returned — a dead loopback
   server, not your diff. The technique generalises: when a test drives a
   server that controls the clock, the client's bound shows up in what the
   client COMPUTES, not in how long the exchange took.
7. **A merge fires 3–5 deploy runs; most are `cancelled` by concurrency.**
   Enumerate every run for the SHA and read each Deploy **JOB**, never the rollup.
   `gh run list --commit <SHA>` can return `[]` before runs exist, so assert one exists.
8. **`make close-guard` before every merge**, with the text in the ENVIRONMENT.
   A close keyword next to `#N` closes it, and GitHub cannot read negation.
9. **`make next` overwrites `docs/00-factory-console.md` wholesale**, and
   `make handoff` overwrites `docs/session-handoff.md`. Edit the GENERATORS.
10. **`pytest-timeout` is NOT installed.** `--timeout` makes pytest error out and
    every mutant then looks killed while nothing is tested.
11. **The advisory "Mutation score on changed functions" job fails on any diff
    that touches `src/`, and passes on rerun.** Measured 2026-08-29 on three
    consecutive commits. It is NOT your diff and NOT a required check. Cause,
    reproduced locally: with a non-empty scope mutmut first runs a CLEAN
    baseline of the whole suite inside `./mutants/`, and
    `test_redacting_many_colliding_keys_does_not_take_quadratic_time` is
    load-sensitive — it asserts `elapsed < 0.5` and measured **2.824s** under
    load, so the run aborts with `failed to collect stats` before scoring a
    single mutant. A docs-only diff has an empty scope and passes trivially.
    `gh run rerun <id> --failed` clears it. Read the log for the number before
    attributing it to anything.
12. **A board row can be `PENDING` while its work is merged, closed and in
    production.** Measured 2026-08-29 on W12/#379: the Evidence needle pinned a
    line the fix KEPT (it appended a clause on the next line), so the needle
    never flipped and `make validate` stayed green over a false board. **Pin a
    needle the fix must ADD or must DELETE, never one it will edit around**, and
    check it in genuine code — not a comment or docstring, which is the W7 trap.
    Verify both directions before committing: `grep -c <needle>` on your tree
    AND on the pre-fix commit.

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
