# Handoff — 2026-08-11

Read `AGENTS.md` in full first. It overrides anything here.

> **This file is the continuation plan, and it is TRACKED deliberately.**
>
> It lived at the repo root as `HANDOFF-2026-08-11-NEXT-SESSION.md`, where `.gitignore:31`
> (`HANDOFF-*.md`) kept it out of git. That made it unrecoverable, absent from a fresh clone,
> and a member of the group `REPO-HOUSEKEEPING-ULTRACODE-PROMPT.md` marks as safe to delete
> locally — so a cleanup run could have destroyed the only record of where to continue.
>
> Moved here and committed so git holds it. **Do not move it back under a `HANDOFF-*` name.**
> That ignore pattern has no directory anchor, so it silently un-tracks the file at *any*
> path, including inside `docs/`.

## State when this session ended

- `main` = `origin/main` = production `build_sha` = **`5d9eec8`**. All three equal — verify with
  `git rev-parse origin/main` and `curl -s https://quorum-ai.fly.dev/status`.
- **No open PRs. No branches but `main`. No worktrees but the main checkout.**
- **Live execution is OFF** (`/ready` → `state: "offline_by_config"`). This is deliberate —
  the OpenRouter key had **$0.1065 of a $0.50 limit** left and a run costs **$0.0767**, so
  unattended traffic would exhaust it in one or two visits. `fly.toml:27` commits `false`
  and the secret override was **unset**, so the committed config now governs.

## What merged today

| SHA | What |
|---|---|
| `f7128b1` | #285 + #284 — anchored citations count again; the evaluation is computed once, not per page view |
| `ab4296c` | #105 + #268 + #203 — durable JSONL telemetry on the Fly volume. **Closed none of the three** |
| `fa3541a` | The debate copy correction + ADR-0032 + FR-008 status line |
| `e9643c5` | Corrected ADR-0032's own overstated claim about where the API description is served |
| `5d9eec8` | Deploy smoke test now distinguishes deliberate offline from broken offline |

## Start here

**#290 — peer critique between the four models.** Filed today, fully scoped, the largest
open item. The four answer models are called once each and never read each other; one
moderator call reads all four. FR-008 is marked `PARTIALLY MET` and points at it.

The plan from this session is at `~/.claude/plans/lovely-scribbling-liskov.md` (outside the
repo). Its remaining steps, in order:

1. **Step 2 — the synthesiser sees the question.** `$0`, pure code + hermetic tests.
   `query_text` reaches `produce_final_synthesis` (`synthesis.py:401`, param `:406`) but
   **never enters `_user_prompt`** (`:678`, sole call site `:459`). Meanwhile `costs.py:1538-1544`
   already includes `query_tokens` in `synthesis_prompt_tokens` **× 5 sections**.
   **Users are already billed for a query the prompt never contains.** Adding it costs
   nothing; adding a cap makes the estimate go *down*. Two traps the review found: the
   directive at `synthesis.py:704` tells the model not to repeat a question it never
   receives, and `prior_question` (a *previous* run's query) already reaches synthesis via
   the system prompt — so on a follow-up the synthesiser sees the **wrong** question.

2. **Step 3 — #180, the false-consensus defect.** `synthesis.py`'s own comment: *"four
   unrelated answers that merely open with the disclaimer are served as 'strong consensus,
   4 of 4'."* Violates AC-019. **Reframed as measure-first**: the issue records three prior
   fixes killed in review and refuses a guessed threshold.
   **This does NOT need live runs** — `docs/validation/live-run-2026-07-14.json` and
   `repro-live-2026-07-14-issue16.json` each carry four complete model answers
   (2,200–5,100 chars) plus debate and synthesis prose. That is the corpus.
   The defective code is `synthesis_consensus.classify_model_alignment` (the
   `elif opening_majority: final_aligned = True` short-circuit) and `_overlap_partner_counts`
   — **not** the files the first draft of the plan cited, which were only comments about it.

3. **#290 — peer critique.** Needs a **~$0.017 paid probe first**: `openrouter_timeout_seconds`
   is 8.0 and non-streaming; a 2000-token critique at ~50 tok/s is ~40s, and peer critique
   makes that eight calls. Unsettled, and it could invalidate the design.

## Blocked until live execution returns

- **#105** (5xx billing premise) — needs organic 5xx traffic. Cannot be forced.
- **#268** (input token bound) — needs ~50 search-enabled calls.

Both telemetry files exist on the Fly volume at **0 bytes**. Read with
`fly ssh console -a quorum-ai -C "cat /data/telemetry-billing.jsonl"`. The exact query and
decision rule for each is in the issue comments and ADR-0031.

## #203 — answerable now, nobody has closed it

Measured today, four independent signals: no proxy or WAF on the egress path.
No `HTTP(S)_PROXY` env; egress IP `152.233.48.132` is AS60068 Datacamp (Fly's transit);
the same OpenRouter request from inside the machine returns a byte-identical envelope;
and the TLS cert is genuine (`Google Trust Services WE1`, `CN=openrouter.ai`) — an
intercepting proxy would have to present its own CA.

So #203 is closeable as **not-a-problem on this deployment**, ideally with a threat-model
row recording that egress is unfiltered and why that is accepted (no SSRF surface: every
outbound URL is a hardcoded constant or env var; three destinations only).

## Traps this session paid for

- **`.data/feedback_events.sqlite3` poisons local e2e.** It accumulates the durable per-IP
  mint cap until `/ui` 429s. **`SESSION_MINT_CAP_OVERRIDE=600` does NOT prevent it** —
  measured: 61 failed / 180 passed, then a webServer timeout, then `32 passed` after
  deleting the file with no other change. **Delete it before a long verification sweep**,
  not only after the failure. It is gitignored local state.
- **The visual e2e lane is flaky in CI.** `trust-score — light @ 1440` and
  `result view — verdict + trust triangle` failed with an 8353px (6%) diff on a branch that
  changed only `deploy.yml` and a test file, then **passed on re-run**. One fail / one pass
  observed — not a measured rate. Re-run before believing it.
- **Do not grep-and-trust `make quality`.** A filtered grep hid a failing `make type-check`
  here. **Check the exit code.**
- **`gh pr view <N> --json closingIssuesReferences`** is GitHub's own parse of what a PR
  will close — `[]` means nothing. Use it as the gate; the "does not close #N" phrasing
  auto-closes anyway because GitHub ignores negation.
- **A merge fires THREE deploy runs**, not two as `AGENTS.md` rule 18a says. Two are
  cancelled by concurrency. Resolve the **newest by `createdAt`**, then read the **job**.
  Rule 18a's count is stale; its guidance is right.

## Working-tree state — yours to decide, untouched by this session

`git status` shows one modified file and ~25 untracked ones that **predate this session**:

- `docs/00-factory-console.md` — modified
- ~20 `*-ULTRACODE-PROMPT.md` / `*-RESULT.md` / `HANDOFF-*.md` at the repo root
- 5 `docs/analysis/*.md`
- `e2e/tests/review/` — 7 gitignored scratch specs. **These make `make quality` RED locally
  and green in CI** (AGENTS.md rule 13a). Check `ls e2e/tests/review/` before blaming a diff.

None were created or deleted by this session. Untracked files have no git history, so they
were left alone deliberately — `git ls-files` before deleting any (rule 16c).

## Verification recipe

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
uv sync --all-extras && make quality && make validate      # CHECK THE EXIT CODE
make openapi-check && make security-scan && make api-contract
git commit                                                  # BEFORE diff-cover (rule 15a)
make diff-cover DIFF_BASE=origin/main

rm -f .data/feedback_events.sqlite3                          # before any e2e sweep
lsof -ti tcp:18085 | xargs -r kill -9
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
  npx playwright test <specs> --project=chromium --workers=1 --retries=0
```

Never the visual lane locally (rule 13e — 8/8 fail on a Mac on clean `main`).
