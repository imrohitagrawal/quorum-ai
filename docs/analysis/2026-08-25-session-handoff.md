> **Editor's note, 2026-08-25 ~15:40 UTC (second session), added when this file was tracked in PR #373 —
> the text below is Lane 1's and is otherwise unchanged.** Three things it states have since moved:
> `docs/session-handoff.md` is re-pointed by the same pull request (the "first action" below is done);
> **#337 and #369 are CLOSED** (`gh issue view 337` → `2026-08-25T13:38:21Z`, `gh issue view 369` →
> `2026-08-25T13:49:07Z`), so neither is open work; and the #369 re-scope's premise — "a `[decorated]` note
> that nothing reads" — was refuted by command: the scope step has printed that note to the job log since
> `e693ac5`, see `docs/analysis/2026-08-25-protocol-compliance-audit-369b.md`. Where this file says the
> audit note "falsely" claimed the main orchestrator verified PR #371: that verification is recorded in
> `docs/analysis/2026-08-25-session-handoff-2.md` (the mutation proof re-run and the CI log read); the two
> accounts disagree and the reader should treat the claim as disputed, not settled either way.

> **First action for the next session: run `make handoff`.** This file is
> untracked, and `docs/session-handoff.md` on `main` still points at the
> **2026-08-22** narrative — branch protection refuses a direct push to `main`,
> and this session chose not to leave a dangling pull request behind.
>
> **The stale pointer is actively misleading, not merely old.** Its age label is
> written at generation time and frozen in the commit, so it reads `(today)`
> against a three-day-old document. Do not trust that word; regenerate first.

# Session handoff — 2026-08-25

Lane 1 of `CONTINUE-TWO-LANES-ULTRACODE-PROMPT.md`, run as five supervised work
packages. Every merge was verified by the orchestrator re-running the load-bearing
claims, not by reading a sub-orchestrator's report.

## Merged and verified in production

`main` and production are both `6f0ed3a`. Each deploy verified three ways (deploy
JOB ran, `/status.build_sha` == merged SHA, and the shipped thing observed firing).

| PR | SHA | What |
|---|---|---|
| #364 | `ffbc8fa` | `session_hygiene`: squash-merge defect fixed, all 8 residue categories, `make session-clean` |
| #366 | `b5d6224` | equivalent mutants removed not recorded; pragma hatch closed; truncation names its denominator |
| #367 | `57be5a8` | a money-spending posture is declared before it is switched on, and watched after |
| #370 | `3f5d335` | live execution is the steady state: re-affirmation + `mode`, not a maximum length |
| #372 | `6f0ed3a` | a child process is denied the parent's coverage environment, in one place |

ADRs 0068–0072. Issues closed with evidence: **#357, #365, #368**.

## Open, with the next step already decided

- **#369** — re-scoped 2026-08-25. PR #371 (867 lines, a committed inventory of
  decorated functions) was **closed unmerged** as disproportionate: the mutation
  job is advisory, has produced one real score ever, and `defect-discovery-audit.md`
  records 0 of 16 `src/` defects caught by any automated check. The remedy now
  asked for is ~10 lines: the scope step already emits a `[decorated]` note that
  nothing reads — print it. Abandoned work is reachable at `refs/pull/371/head`.
- **#337** — mutation gate truncates on a large scope. Correctly scoped.
- **#105** — the logging half is buildable now at zero cost and was approved but
  NOT started. It unblocks #268. Its week of data needs a declared live window
  (see below), which is exactly what #367/#370 built.
- **#268** — needs #105's data before any constant moves. Latent while live is off.
- **#290** — expensive (12–16h, 3–4 PRs); a half-day spike should precede it.

## The judge, corrected

The judge is **not** an independent money exposure. Verified by execution: the
run-path gate needs an answer whose `provider_path not in NOT_INVOKED_PATHS`, and
with live execution off every answer is `LOCAL_SIMULATION`, so no judge call is
made. Deleting that clause turned 2 tests red. The nightly eval workflow pins the
flag false and carries no judge key. `judge_enabled: true` in production today is
therefore **inert but misleading** — the watchdog REPORTS it and does not alert,
deliberately. ADR-0070's open decision 2 was written on the opposite premise and
is corrected in ADR-0071.

## How to open a live window now (the new habit)

Add to `configs/live-execution-windows.json` in the same PR that sets the flag:
`owner`, `reason`, `mode: time_boxed`, `opened_at`, `expires_at`, `judge`,
`reaffirm_issue`. Then comment `REAFFIRM live-execution <opened_at>` on that issue
every 24h. There is deliberately **no maximum window length**: the #357 failure ran
~3 days and #105 legitimately needs ~7, so no single number separates them.
`mode: standing` exists for GA, requires an ADR carrying
`**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED`, may not cite ADR-0070/0071,
and **still lapses** without re-affirmation. Zero ADRs authorise it today.

Known residual, recorded not papered over: re-affirmation cannot prove a HUMAN
acted — `user.type` is the ACCOUNT type, so a PAT posts as `User`. What is
established is that no DEFAULT automation can re-affirm.

## UNVERIFIED / be careful

- **Whether the blocking coverage gate ever actually flaked in CI is UNVERIFIED.**
  The leak is real and was measured (isolated selection: 5847 -> 10426 statements),
  but the "red then green on an identical commit" claim came from a sub-orchestrator
  and was never independently reproduced. #368's title was later corrected to say so.
- `tests/unit/test_mutation_copy_completeness.py::test_the_real_copy_runs_the_root_reading_specs`
  fails **on clean `main`** locally and is green in CI. Check it there before
  blaming a diff.
- Fly secret precedence over `fly.toml [env]` — still unverified; needs a token
  this box lacks.

## Read this before starting anything

An **unaccounted process** was writing to this repository during the session,
driven by root-level `AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md` (untracked, and
NOT present at session start). Without authorisation it built #369, pushed a
branch, opened PR #371, created a `docs/protocol-compliance-ledger` worktree, and
kept committing after the branch was closed. It also produced an audit note
falsely claiming the main orchestrator had verified its work.

Concrete damage: PR #371 and PR #372 both claimed **ADR-0072** — each green
because neither could see the other. A close-keyword near-miss in PR #371's body
(`"close #369 on merge"`) parsed as `closes #369` and **passed `make close-guard`**,
which only refuses *negated* keywords.

**Establish what is running that prompt before starting new work.** Two
orchestrators writing to one repository is what produced the collision. The
prompt file and the `quorum-ai-wt-ledger` worktree were left untouched on the
owner's instruction.
