# Session handoff — 2026-08-19

Three PRs merged, two issues closed, no `src/` code touched. The paid live run
did NOT happen: it is blocked on two Fly secrets only the operator can set.

## What merged

| Issue | PR | Squash SHA | Deploy verified |
|---|---|---|---|
| — | #346 | `5bbe616` | yes — Deploy **job** `success`, `/status.build_sha` matched |
| #338 | #347 | `b528a09` | yes — same three-way check |
| (part of #148) | #348 | `68d8b69` | yes — run 32206112530, gate + Deploy job both `success` |

Final verified production state: `/status.build_sha` == `68d8b69` == `main` tip.

Issues closed: **#338** (auto, on merge) and **#226** (by hand, with evidence —
see the correction below). Still open: **#337, #290, #268, #105**.

ADRs added: **0057** (mutation gate is a regression detector and must reach the
real tree), **0058** (guard tests run in a required pytest lane), **0059** (guard
resolves computed member properties and fails closed).

## The one thing the next session must know

**`fly ssh console` is refused by the sandbox classifier.** Measured twice. No
HTTP endpoint serves the telemetry JSONL — every route in `main.py` was checked
(`/`, `/health`, `/ready`, `/status`, `/v1/session`, `/ui/ops`, `/ui`,
`/v1/models/defaults`, `/feedback/audit`). So an agent in this sandbox **cannot
read `/data/telemetry-*.jsonl`**, and therefore cannot close #268 or #105 on its
own no matter how much traffic runs. That read-back is an operator step:

```bash
fly ssh console -a quorum-ai -C 'wc -l /data/telemetry-billing.jsonl /data/telemetry-tokens.jsonl'
TELEMETRY_LOG_DIR=/data python scripts/telemetry_classification_report.py
```

Good news: `fly.toml` sets `TELEMETRY_LOG_DIR = "/data"`, so production **is**
writing both streams. The sample accrues whether or not anyone reads it.

Whether the streams were empty before today is **INHERITED, NOT VERIFIED** — the
previous session's claim could not be checked for the reason above.

## Corrections to the inherited handoff — roughly half did not survive

Rule 11 held almost exactly. Refuted **by execution**:

1. **`find_repo_root_or_skip` "exists nowhere".** FALSE. It is at
   `f661765:tests/repo_root.py:54`. The orchestrator's `grep` searched only the
   working tree, not history. Issue #338 was right to name it.
2. **`f661765` "is not on the branch".** FALSE. It **is**
   `origin/fix/mutation-gate-measures-nothing`; the LOCAL ref was stale at
   `390ad00`. The same stale-local-ref error was made twice in one session, the
   second time after already being corrected once. **Always compare against
   `origin/`.**
3. **"The copy's `docs/` was never copied."** FALSE, and this one mattered.
   `pyproject.toml` `[tool.mutmut].also_copy` lists `"docs"`; the copy holds the
   files. The real cause is that **`git ls-files` resolves its PATHSPEC relative
   to cwd**, so from an untracked subdirectory it exits 0 listing nothing.
   "Add docs to also_copy" would have been a non-fix.
4. **"28 skipped."** It is **30 of 30** — the handoff read only the first wrapped
   line of pytest progress output; the trailing `ss` is on the next line.
5. **"Leave `test_no_generated_artifacts_tracked.py` alone."** Refuted by
   execution: it carries the identical defect (`assert 0 > 1000`). Fixing only
   the named file moves mutmut's `-x` abort down one file.
6. **#226 has two halves, and this session closes it.** FALSE, and a builder
   agent refused the premise rather than repairing it silently (rule 3). #226 is
   about 20 unpartnered assertions in 8 spec files; its body explicitly excludes
   the guard tool's own classification bugs. PR #336 (`15c365c`) satisfied it.

## What the review fan found that no gate could

Both merged PRs were green on all six required contexts **while carrying a false
guarantee in their ADR**. In each case every code lens passed the diff and only
the prose lens caught it.

- **ADR-0057** claimed the classifier "treats anything unfamiliar as an
  offender". `import subprocess as sp` defeated it entirely — the call was never
  *recognised*, and the fail-closed logic sits downstream of recognition. The
  skeptic isolated it by changing only two spelling tokens, which made the guard
  go red. Fixed in a deliberate round 3.
- **ADR-0058** carried the first draft's figures (`6 passed, 29 skipped`) when the
  truth was `9 passed, 28 skipped`, because the module grew 35 → 37 tests. Its
  header also claimed every row was measured "in a worktree at `e4c58a2`", which
  cannot be true of a post-fix row — that is `main`.
- **ADR-0057** asserted that `grep -rn "from subprocess import \*" tests/` "exits
  1 with no output". It exits **0** and matches **the sentence making the claim**.
  The underlying claim was true, so it was kept and re-evidenced with an `ast`
  sweep, which counts executable code and cannot match prose.
- **ADR-0059** said "75 violations across 17 specs". The 75 reproduces; the file
  count is 15. Per rule 1a the number was **removed, not corrected**.

That is four stale-or-false prose claims in one session, on top of the four the
rulebook already records. **The prose lens is the highest-yield reviewer here and
should never be dropped from a fan.**

## Defects found beyond what was asked for

Planning for #348 (rule 16e, failure modes before code) found three cases nobody
had reported, all sharing the known root cause:

- `test["only"]("t", fn)` is unrecognised, so **the entire test body is never
  walked**. Strictly worse than the known evasions, which hide one assertion each.
- `test["describe"]` / `test["beforeEach"]` lose their `beforeEach` partners the
  same way — a false-positive direction.
- Template-literal properties (`expect(x)[\`not\`]`) are statically resolvable and
  were being dropped.

It also caught that the salvaged Playwright-normalizer test does a bare
`pytest.skip` when `playwright-core` is absent. Now that PR #346 makes that module
run in the required lane, a bare skip would have re-created the exact silent-green
hole ADR-0058 had just closed.

## Traps confirmed still live

- **A stale worktree makes an adjudicator confidently wrong.** Two "surviving
  blockers" on PR #346 were reproduced against an archive taken before the fix
  round pushed. Both were already fixed. **Always `git fetch` and archive
  `origin/<branch>` before adjudicating**, and say which tip you tested.
- **A bare `uv run` in a worktree** built a CPython 3.14.5 venv with no ruff;
  `make quality` died at `format-check` in a way that reads like a diff
  regression. Fix: `UV_PROJECT_ENVIRONMENT=/Users/rohitagrawal/Projects/quorum-ai/.venv`.
- **A merge fires three deploy runs**; the two earlier ones are `cancelled` by
  concurrency dedupe and the newest succeeds. Re-resolve by `createdAt` every time.
- **Parallel packages collide on `docs/24-adr-index.md`.** It is generated —
  resolve by running `scripts/generate_adr_index.py`, never by hand.
- The advisory mutation job passed in **19s having measured nothing**
  (`no MUTATABLE changed functions under src/`). Its own output says so. Open the
  log; never read the tick.

## Branches

- `fix/226-guard-classifier` — superseded by PR #348. Its ADR-0053 became 0059.
  Safe to delete; 0053 stays a permanent gap, which ADR-0050 says is not a defect.
- `fix/226-vacuous-e2e-negative-assertions` — superseded by merged PR #336.
- **`fix/mutation-gate-measures-nothing` — KEEP.** Only its abort fix shipped. It
  still holds the unshipped verdict-honesty work and **ADR-0052**, so 0052 stays
  reserved. That work's central claim ("every terminal state stamps exactly one
  verdict") went false twice running; it needs a fresh look, not a rebase.

## What is left, and what it is blocked on

**Phases D–G of the live-run plan did not run.** `judge_enabled` is `false`
because the two Fly secrets are unset:

```bash
fly secrets set -a quorum-ai \
  QUORUM_EVAL_JUDGE_API_KEY='sk-or-v1-...' \
  QUORUM_EVAL_JUDGE_MODEL_ID='<openrouter-model-slug>'
```

Both are required (`evaluation.py:1827` is an AND; `config.py:140` gives the model
id no default on purpose). Setting them **spends nothing** — live execution is a
separate AND at `providers.py:670` and is still `false`. It is a free checkpoint:
if `judge_enabled` stays false afterwards, one of the two names is wrong.

The traffic plan is written and budget-bounded at **~$0.40** by the caps
themselves (2 session mints per IP/24h × `DAILY_CAP_USD` $0.20/account), well
under the $5.00 global ceiling. It deliberately drives the per-account cap to
exercise the at-cap refusal branch, which #216 added, #342 fixed, and **nobody has
ever watched execute**.

Honest expectations for the remaining issues:

- **#337** cannot close on this work. The abort fix converts "aborts having done
  nothing" into "runs to the 24-minute deadline". That is the information #337
  needs, not its answer.
- **#268** needs `n >= 50` `:online` calls. Read its positive partner FIRST: for
  `search_enabled == false`, `injected_p95` must be **under 500**, or
  `CHARS_PER_TOKEN = 4` is wrong and the whole measurement is void.
- **#105 will probably not close.** It needs `n >= 30` **5xx**, and 5xx arrive on
  OpenRouter's schedule. Collect opportunistically; leave it open. If
  `unknown/n > 0.20`, STOP — ADR-0012's `error.metadata.provider_name` schema is
  ASSUMED and a dominant null refutes it.
- **#290** needs a raw OpenRouter call at a chosen token cap. The key is a Fly
  secret and no product endpoint exposes that shape, so the quote-passages half is
  likely unanswerable from here.

## One thing this session did not do

The closing adversarial pass over "the money path, security, concurrency" was
**not** run, deliberately. This session touched no `src/` code at all — only test
infrastructure, one CI workflow and ADRs. A fan over the money path would have
reviewed code nobody changed. The genuinely new risk is coupling a required merge
gate to `npm ci`, and that drew dedicated SRE and devops lenses. Stated here so
the choice is visible rather than silent.
