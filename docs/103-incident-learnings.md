# Incident Learnings

Concrete, dated incidents and the durable fix each one earned. Each entry is a
real event with evidence (run ids, commits), not a hypothetical. New entries go
at the top.

## 2026-07-29 — A RED gate that measured nothing, and twelve more that could

**What happened.** The repaired mutation gate met the case it existed for — the
first pull request touching `src/` Python (#157) — and **scored nothing**. It
exited non-zero during test collection, so the tick was red and read as a verdict
on the diff. It was not.

**Root cause, reproduced exactly.** `tests/unit/test_mutation_test_set_integrity.py`
computed `REPO_ROOT = Path(__file__).resolve().parents[2]`. mutmut runs the suite
from inside `./mutants/`, so the root resolved to the copy, and the guard counted
the mutation runner's own generated `x_<name>__mutmut_N` variants:

```
AssertionError: 514 decorated functions under src/product_app; the study measured 40
assert 514 <= 55
!!!! stopping after 1 failures !!!!
failed to collect stats. runner returned 1
```

Real source has 40. Reproduced on 2026-07-29 by re-introducing the `parents[2]`
resolution and re-running `make mutation-baseline`: identical `514` abort. With
the fix (`tests/repo_root.py`, resolving to the nearest `.git` ancestor) the same
command on the same tree printed `2 killed, 0 survived, 0 no-tests → 100.0%`. One
line, and the difference between a number and no number.

**The printed diagnosis was wrong.** It said "usually a repo-root file missing
from `[tool.mutmut].also_copy`". Nothing was missing. The message now names the
copied-tree cause first and states that the exit code is about the gate, not the
diff.

**The wider finding, which is the real content of this entry.** Auditing every
gate for the same question — *can it finish having measured nothing?* — found:

- `mutation-baseline`: **11 of the last 11 pull-request runs produced no score.**
  Ten green, one red.
- **`diff-cover`, a BLOCKING gate, exits 0 on an empty denominator.** Reproduced:
  two genuinely uncovered new lines plus a coverage report with no packages gave
  `No lines with coverage information in this diff.` and `rc=0`.
- **13 of 21 jobs could reach a terminal status having measured nothing; four of
  them blocking.**
- The fix pattern already existed in the repo (`gate-min-collected` / `gate-min-executed` in the `Makefile`) and was wired to two gates.

**Durable fix.** Fail-closed floors on the four blocking gates plus the mutation
gate, each proven RED against an empty input and GREEN against a real one — see
`docs/analysis/03-enforcement-machinery.md` for the table and the evidence. Also
`set -o pipefail` in the two workflows that piped a check into `tee` and thereby
discarded its exit status.

**Rules earned.** A RED advisory job is not evidence it measured — open the log,
same as for a green one. Any check that resolves paths from `__file__` will point
at the copy when a tool re-runs your suite from a generated tree. And the one that
generalises furthest: **a gate that cannot state what it measured has not been
verified, only observed** — ask every gate for its denominator.

## 2026-07-22 — A green Deploy run can mean nothing was deployed

**What happened.** After PR #60 merged, the Deploy workflow produced three runs
for the same commit family. Run `29896840556` reported overall conclusion
**`success`** while its jobs were `Gate: success`, **`Deploy to Fly.io: skipped`**
— it fired when CI had finished but Tests/E2E were still mid-run, so the gate
declined and the deploy job was skipped. Only run `29896903551` (fired after E2E
went green) actually had `Deploy to Fly.io: success` and shipped the image
(`registry.fly.io/quorum-ai:deployment-01KY489JKM682WES32A4J6EBRC`), confirmed by
`/ready` returning `{"state":"live"}`.

**Root cause.** `deploy.yml`'s `deploy` job is guarded by
`if: needs.gate.outputs.proceed == 'true'`. When the gate declines, the deploy
job is *skipped* but the gate job exits 0, so the run's overall conclusion is
`success`. A green Deploy run is therefore indistinguishable at a glance from an
actual deploy. This is the same failure surface as the silent-undeploy incidents
(#21, #37, #44) and the `/health`-200 trap of 2026-07-17..21.

**Durable fix.** Verify deploys by the per-SHA Deploy **job** conclusion, never
the run conclusion or a `/health` 200. **#62 (fixed):** `scripts/deploy_gate.py`
now exits non-zero when a required workflow did not succeed AND the SHA is
still main's tip — a real stranding, since nothing else will ever deploy it —
so the `gate` job itself fails and the whole Deploy run reports failure, not a
green run with a silently skipped `deploy` job. A SHA superseded by a newer
main commit (checked via `gh_fetch_main_tip`) still exits 0 — a quiet skip,
since the newer commit's own Deploy run is the one that verifies deployment.
Pinned by `tests/unit/test_deploy_gate.py` (`test_main_blocked_*`,
`test_gh_fetch_main_tip_*`). The manual one-command check below remains the
right way to verify a *specific* past run; the fix means a future stranding no
longer needs it to be noticed at all — the run itself goes red.

**How to detect next time (one command):**
```bash
gh run view <deploy-run-id> --json jobs \
  --jq '.jobs[] | select(.name|startswith("Deploy to Fly")) | .conclusion'
# must print "success" — "skipped" means NOT deployed even if the run is green.
```

## 2026-07-22 — A follow-up push to main cancelled the merge commit's CI

**What happened.** Immediately after PR #60 squash-merged (`c1028ef`), a docs
commit was pushed straight to `main` (`b729950`). The Deploy workflow triggers on
`workflow_run` of CI/Tests/E2E with a per-SHA concurrency group and
`cancel-in-progress: true`, so the new push **cancelled `c1028ef`'s in-flight
Tests and E2E**. `c1028ef` never deployed; the deploy moved to `b729950`. Benign
here (doc-only, identical app code) but it churned the deploy pipeline and forced
a full re-verification.

**Root cause.** `main` accepts direct pushes with no required checks, so a
follow-up commit can land while a just-merged commit's CI is still running, and
concurrency cancels the older runs.

**Durable fix.** Never push to `main` while a just-merged commit's CI is in
flight — branch + PR for every change, including docs. **Enforced 2026-07-22 via
#61**: `main` branch protection now requires a PR (no direct push, admins
included), requires the six blocking checks (`validate-and-test`, `pytest (Python
3.12)`, `Changed-lines coverage >= 95% (blocking)`, `Schemathesis API contract
(blocking)`, `FR traceability completeness (blocking)`, `e2e axe + parity
(chromium)`), and requires branches be up to date before merge (`strict`) so a
merge cannot race a just-merged commit's CI. Config lives in
`docs/70-ci-cd-plan.md`. Note: the issue text listed the E2E check as `E2E (axe +
parity)`; the name CI actually reports is `e2e axe + parity (chromium)` — the
enforced protection uses the real name so merges aren't blocked on a phantom check.

## 2026-07-17..21 — Merges stranded undeployed; `/health` 200 masked it

**What happened.** Several merges to `main` never reached production while
`GET /health` kept returning 200, so the stale build looked healthy. The deploy
gate's timeout (900s) was shorter than the 30-min mutation job on the push path,
so the gate timed out and skipped; no later trigger re-deployed.

**Durable fix.** Mutation moved to `pull_request`-only (off the push path); the
gate `GATE_TIMEOUT_SECONDS` raised to 1500s (clears the 20-min job ceiling with
headroom); invariant pinned by `tests/unit/test_deploy_gate_no_slow_push_jobs.py`.
Confirm a deploy by the deploy **job** running and prod serving the new build
(grep a served asset / `/ready` build stamp), not by `/health`.

## 2026-07-29 — A CI gate reported green for a week without ever measuring anything

**What happened.** The `mutation-baseline` job aborted at
`failed to collect stats` in ~1m07s on **every** pull-request run, and reported
success because a `-` on the Makefile recipe swallowed the error and
`continue-on-error` swallowed the job. It had **never scored a single mutant in
CI**.

**Duration, measured from job logs — not "months", and not inferred.** The
abort is confirmed by log on a 2026-07-22 pull-request run (`29967598312`,
conclusion **success**, body `failed to collect stats`) and on four runs on
2026-07-28. Its cause is
`tests/contract/test_golden_fixture_matches_served_schema.py`, which reads
`e2e/fixtures/` and landed 2026-07-21 with `e2e/fixtures` absent from
`[tool.mutmut].also_copy`. So the gate was reporting green while measuring
nothing for about **a week**. A first correction said "8 days" from the file
date alone; that was still reasoning, not measurement, and is recorded here
because the distinction is the whole lesson. Issue #130 itself lived **71 minutes** (created 15:39,
closed 16:50 on 2026-07-28). It asked to make the gate blocking, citing the
abort as *"finished in 1m 9s on PR #96 and passed"*, and was closed COMPLETED
with **no commit** — the change was never made.

**Root cause of the silence.** `scope()` printed `"\n".join([])`, a bare
newline. The recipe guards its work branch with `[ -s scope.txt ]`, a **size**
test, so one byte made the "nothing to mutate" branch unreachable and every
docs-only PR invoked `mutmut` unscoped, which aborts.

**Durable fix.** Gate repaired (empty scope writes 0 bytes; `e2e/fixtures` added
to `also_copy`; repo-driving modules deselected under mutmut via a pinned
`repo_introspection` marker; all-timeout and `no_tests` states reported
distinctly instead of as "the run did not happen"). The suite inside mutmut's
copy went from **41 failed to 0**, and the gate completed a real run for the
first time.

**Decision.** The promotion was then measured and **reversed** — yield ~4% of
158 enumerated escaped defects, ~15% of PRs would get a wrong answer, and no
published industrial practice blocks a merge on a mutation score. Evidence:
`docs/metrics/mutation-gate-study.md`. Carry-forward rules:
`docs/DAY-ONE-PROMPT.md` §4a-bis.

**Rules earned.** A green advisory job is not evidence it ran — open the log.
Every gate ships a charter naming what it cannot see. Replay a gate over real
history (`scripts/replay_mutation_scope.py`) before trusting it. Never close an
issue whose fix has no commit.

## Cross-cutting rule

**"Green" is a claim, not a proof.** A green local test run can pass on stale
`build/` artifacts a previous run left behind (this hid a Stage A critical: the
suite read 1185 passed while a fresh CI checkout would have gone red). A green
Deploy run can hide a skipped deploy job. Before trusting any green, control the
inputs: simulate a fresh checkout (`mv build /tmp/b && uv run pytest -q`) for
anything that reads generated files, and check the per-SHA **job** conclusion for
anything that deploys. See `docs/59-backend-engineering-practices.md` — CI/CD and
deploy verification.
