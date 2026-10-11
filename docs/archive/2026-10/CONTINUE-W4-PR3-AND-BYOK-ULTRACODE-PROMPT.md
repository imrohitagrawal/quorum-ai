> **Archived 2026-10-11** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Edits: home-directory paths replaced with `~`; the user name in a transcript folder replaced with `<this repo's project folder>`; 2 not-yet-written file names shown as `2026-09-<day>`.

# ULTRACODE — W4 PR 3, the decision record, the BYOK plan, then W5

ultracode. Workflows and subagents for READ-ONLY fan-out only (understanding,
review, verification). Never for building: subagents share one working tree.

I am away. Do NOT wait for me. Work the queue in §5 in order. Every product
decision you need is already written in §4 in my own words; do not re-ask any
of them. Stop only at a §2 hard stop, and then write it in the report.

---

## 0. Read first, in this order, then run the checks

1. `AGENTS.md` — it overrides everything here on every technical rule, with
   ONE exception: §2 and §3 of this file are the explicit human approval that
   AGENTS rule 17b requires (push, open a PR, merge, deploy). Granted for this
   session, bounded by §2.
2. `docs/00-factory-console.md`, `docs/session-handoff.md`.
3. `docs/analysis/2026-09-23-session-handoff.md` — what shipped on
   2026-09-23 (W4 PR 2, #494) and the six traps measured that day.
4. `docs/analysis/2026-09-22-decision-register.md`, `docs/adr/0120-*.md`,
   CHG-010 in `docs/19-change-control-log.md`, board row W4 in
   `docs/65-open-work.md`.
5. `~/.claude/plans/streamed-weaving-bonbon.md` — the W4
   plan; PR 1 and PR 2 are DONE; only "PR 3" remains and §4 below changes
   its copy.

```bash
cd ~/Projects/quorum-ai
git status --porcelain     # expect only CONTINUE-*.md prompts (untracked)
git worktree list          # expect quorum-ai (main) + quorum-ai-wt-268 (parked — do not touch)
git log --oneline -1       # expect 2f60eef or later
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,peer_critique_in_effect}'
ls -lt ~/.claude/projects/<this repo's project folder>/*.jsonl | head -3
```

`live_execution` must be false. A transcript written in the last few minutes
means another session may be live: read its tail before taking work.
Do NOT run `make handoff` here; it belongs at §8 only. The other root
`CONTINUE-*` prompts are partly superseded; this file is the current plan.
Run the commands, not the numbers: if a figure here disagrees with a command,
the command wins and you say so.

---

## 1. What this session is for, in priority order

1. **W4 PR 3** — the copy outside the run path, with the decisions in §4.
   Board row W4 is DONE on its needle; this PR completes the item.
2. **The decision record** — the §4 decisions land in the repo in the SAME
   PR as PR 3 (they are that PR's copy), plus the BYOK principle.
3. **The BYOK plan as a docs-only PR** — a board item, a failure-mode page
   and a PROPOSED ADR. No BYOK code.
4. **W5 (N=1 quick-answer mode)** — only if its decision register entry is
   complete enough to build; otherwise write the scoping and stop.
5. Nothing else. #268 (draft PR #491, worktree `../quorum-ai-wt-268`) stays
   parked. #458, #459, #447 stay gated on owner decisions not taken.

---

## 2. HARD STOPS — stop, write it in the report, do not ask twice

- Any paid API call or live run. `/status`, `/ready`, `/metrics`, `/ui/ops`,
  `/estimate` and the free OpenRouter catalog are fine.
- Opening, extending or re-affirming a live-execution window; flipping
  `OPENROUTER_LIVE_EXECUTION_ENABLED` or `PEER_CRITIQUE_ENABLED`; editing
  `configs/live-execution-windows.json`; any `fly secrets` command.
- Merging any change to a shipped money value (defaults, caps, bands,
  ceilings, rate limits, mint caps). Build it, gate it, DRAFT PR, stop.
- Any merge whose `EXPECT_CLOSE` is non-empty (closing an issue).
- Lowering a threshold, `# pragma: no cover`, deleting or exempting a test.
- Force-push, history rewrite, `git clean`, `git stash`, touching secrets,
  `git add -A` at the repo root (stage named paths only).
- Recording a decision I have not made. §4 is what I decided; anything
  beyond it is `PROPOSED — AWAITING OWNER` in every artefact (ADR Status,
  CHG row, commit body, PR title).
- Writing "half" in price copy, or a range ("2 to 4") in the landing
  headline. Both are rejected decisions.
- Two fix rounds in a row that add a defect: stop, root-cause, re-plan, report.

---

## 3. Standing authority to merge, when ALL hold and the output of each is shown

1. Required contexts re-derived (`gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`, six on 2026-09-23) and each SUCCESS on the PR head SHA.
2. `make quality` and `make validate` exit 0 in the worktree, read as two steps (never through a pipe).
3. `make diff-cover DIFF_BASE=origin/main` green on a COMMITTED tree, run last after a fresh `make quality`; it aborts on any test failure before measuring, so a red diff-cover after a red quality is the same failure, not a coverage number.
4. `make api-contract`, `make openapi-check`, `make security-scan` exit 0; the e2e lanes per §7 if UI, specs or fixtures changed.
5. Review complete: correctness, break-it and prose lenses (rule 11a verbatim in every prompt), every finding reproduced BY YOU and triaged, zero open CRITICAL_BLOCKER or REQUIRED_CONTRACT. Two rounds max.
6. Every behavioural change has a test proven by mutation (cp aside, mutate, clear `__pycache__`, run, restore from the copy, `cmp`), recorded in the commit body. UI changes: the byte-identical proof of the result and transcript views on `goldenCompletedResp()` (rule 13e) and a full-document diff whose hunks all sit in `hidden` views.
7. `make close-guard` with an explicit empty `EXPECT_CLOSE`; write `Refs #N`, never Fixes/Closes/Resolves, in PR title, PR body and merge body.
8. Finish the PR body BEFORE the final push (`ci.yml` fires on `edited`).
9. After merge: every Deploy RUN for the merge SHA enumerated, each Deploy JOB read, exactly one `success`; `/status.build_sha` equals the merge SHA; `/ready` 200.
10. Then `git merge --ff-only origin/main` in the main checkout, delete the branch local and remote, remove the worktree.

---

## 4. The decisions — taken by the product owner on 2026-09-23, in chat, verbatim where quoted

These are DECIDED. Record them (see §5 item A) and build to them.

**D1. Headline.** The landing headline stays exactly
`Four AI models, one sourced answer.` Owner: "We cannot change the main
heading to '2 to 4 AI models, 1 sourced answer.' That is completely wrong,
and I would not approve that."

**D2. Subline.** One muted line under the headline, once, small:
`Your panel, your size: four models by default, three or two when that is all you need.`
No price claim in it, ever.

**D3. The copy rule.** Copy that describes the product describes the DEFAULT
(four). Copy that describes this composer state or this run reads the actual
count (two, three or four) and the actual shape.

**D4. Landing debate line, a capability, both shapes named:**
`Two rounds of debate, by the panel itself or by a moderator model, then one sourced synthesis.`

**D5. Composer shape line**, chosen by the deployment's posture through the
existing predicate `_peer_critique_in_effect` (main.py; ADR-0116) and
count-aware ("four" / "three" / "both"):
- Moderator shape (production today):
  `This run: a moderator model critiques all four answers, in two rounds, then one sourced synthesis.`
  `Peer critique, where each model critiques the others, is available and off on this deployment.`
- Peer shape (flag on AND live execution on):
  `This run: each of the four models critiques the others, in two rounds, then one sourced synthesis.`
Owner: the second sentence is "stated as a fact about this deployment".
Static copy must NEVER claim the models critique each other while the
moderator shape runs; `tests/unit/test_ui_honesty.py` refuses it and stays.

**D6. Where the count and shape change.** The debate panel's pre-run
placeholder (`workspace.html` ~949, "all four answers"), the result-view
tooltips (`app.js` ~6082 "once all four respond", ~6184-6188), and the
landing-to-composer transition message (`app.js` ~8911-8912 "your four
models") become count-aware; the placeholder is also shape-aware per D5.
Landing eyebrow (`workspace.html` ~768 "Four AI models · two debate rounds ·
one sourced answer") and `main.py` 306/337 stay at four (D3). Re-grep every
line number; they were measured on `783fabf` and drift.

**D7. Flags.** Flags stay environment settings. Money flags (live execution,
the judge) stay governed by the committed, watchdog-enforced window. No
admin toggle surface is built. Under the APP-OWNED key there is NO per-run
peer/moderator choice; it is an operator setting, shown honestly (D5).

**D8. Bring-your-own-key (BYOK) — PLANNED, NOT NEXT. Principle:** "the party
paying chooses the flags; the party at risk sets the rails." Under a user
key: live execution on by default; judge and peer critique are user toggles,
on by default, each a priced `by_stage` row in the estimate; the judge runs
on the user's OpenRouter key (same `call_with_prompt` seam, verified);
per-run peer/moderator choice allowed. Rails under a user key: DROP the
global daily ceiling, the per-account envelope and the live window; ADD a
user budget window, $5 default, the existing cost gate asking before a run
crosses it; KEEP the per-run hard cap and one run at a time per session.
Abuse limits under a user key, owner's numbers: about 100 to 200 sessions
per IP per day (not 2: office networks share an IP); about 10 requests per
1 to 2 minutes. Sequencing: own board item; failure-mode page first; then
three PRs (key intake and scoping; rails by credential source plus the
budget window; user toggles and per-run shape). Nothing of this is built now.

**D9. Future-proofing that binds PR 3 and W5 now.**
- One predicate for shape copy (`_peer_critique_in_effect`); BYOK adds one term there.
- "Live execution" is to mean "a key that may be spent" (app or user); the BYOK ADR generalises it; nothing new reads the app flag directly.
- Every optional stage stays a priced `by_stage` row.
- The confirmation token must bind the slot list and the shape BEFORE any per-run toggle exists; W5 must not add a per-run choice first.

---

## 5. The queue

**Parking protocol.** An item that needs a decision not in §4: push the
branch, open a DRAFT PR carrying the evidence, leave the worktree, record it
in §8's Pending, cut the next worktree fresh off `origin/main`. Do not idle.

### Item A + B — one PR: W4 PR 3, the copy, and its decision record

One concern: "the copy outside the run path says what the product does".
Dedicated worktree off fresh `origin/main` (`uv sync --all-extras`;
`cd e2e && npm ci`).

Build:
1. D1, D2, D4 on the landing (`workspace.html`, `main.py` `_landing_subhead`
   if it carries the line). Pin the headline LITERAL in
   `e2e/tests/invariants/landing-cta-reachable.spec.ts` (it already pins
   landing copy; read it first) so it cannot drift to a range.
2. D5 on the composer: a new element, rendered from the seeded readiness
   payload's `peer_critique_in_effect` and the current slot count; re-render
   on remove/add (hook into `applyPanelSelection`). Unit-harness trap: the
   pytest harnesses slice ONE app.js function by brace count and run it under
   node (`computeDemoModeBannerCopy`, `describeSynthesisInput`,
   `initModelSlotSelection`); keep any function they extract self-contained.
3. D6 on the workspace and result views. The result view reads the run's
   `agreement.total` and each round's `critique_shape`, never the default
   panel. Prove the result and transcript views on `goldenCompletedResp()`
   byte-identical to `origin/main` (serve a `git archive origin/main` copy on
   18085, dump `outerHTML`, swap to the branch, dump, `cmp`); tooltip text is
   in attributes, so if a tooltip at four changes by design, say so and show
   the full-document diff instead — do NOT `--update-snapshots`.
4. Tests: a Python test for `_landing_subhead` / the served landing HTML
   (headline literal present, "2 to 4" absent, subline present); the
   negative-assertion classifier counts only `toBeGreaterThan(0)` or
   `toBeGreaterThanOrEqual(<positive literal>)` as a numeric partner — run
   `node e2e/tools/check-negative-assertions.mjs <spec>` before `make
   quality`. Extend `panel-size.spec.ts` (composer shape line at 4/3/2 under
   the moderator posture; `test_ui_honesty` stays green). The e2e floor in
   `e2e.yml` (293) moves only by a re-measured lane count.
5. Docs in the same PR: **CHG-011** "Decided by the product owner
   2026-09-23" with D1-D7 verbatim and D8/D9 as "planned, recorded"; an
   amendment note BELOW `## Status` in ADR-0120 for D1-D6; the decision
   register gets a 2026-09-23 section with D1-D9 and their source (this
   chat, this file). `python3 scripts/generate_adr_index.py` if any ADR is
   added; never hand-edit the index. Board row W4's item text: "shipped in
   three PRs"; its needle and DONE state must not change (polarity in the
   evidence cell describes the OPEN form; never flip ABSENT to PRESENT).
6. Mutation proofs for every copy branch (four-form vs two-form, moderator vs
   peer wording), Python and JavaScript, in the commit body with outcomes.
7. Review, gates, close-guard, merge, deploy verify, cleanup per §3.

### Item C — docs-only PR: the BYOK plan

Dedicated worktree. No code. Deliverables, all `PROPOSED — AWAITING OWNER`
except D8 itself, which is the owner's plan:
- `docs/adr/01NN-*.md` (next free number; ADR-0119 is reserved by draft
  PR #491, ADR-0120 exists): the two-posture rule, the principle in D8, the
  rails table (keep / drop / add), the judge-on-user-key fact, the
  token-binding prerequisite (D9), rejected alternatives (admin toggle
  surface; per-run choice under the app key; keeping the 2/day mint cap for
  BYOK), consequences. Status: `PROPOSED — AWAITING OWNER` (the owner has
  decided the shape, not the delivery); add it to
  `test_only_the_three_genuinely_revoked_adrs_in_this_tree_are_refused`'s
  list with its reason, as ADR-0119 was.
- A failure-mode page `docs/analysis/2026-09-<day>-byok-failure-modes.md`
  (rule 16e): key leak (payload, log, prompt, error, analytics: T-004),
  cross-account reuse (T-006), use after removal, spend runaway on the user's
  key, judge-key ownership, infrastructure abuse through a cheap key, the
  confirmation token not binding slot list or shape, and what each of the
  existing tests FR-011/FR-012 already pins. Reproduce what you can ($0).
- Board row W-next "BYOK: two postures, party-paying chooses" with a needle
  the first BYOK PR must ADD (for example the credential-source resolution
  the orchestrator hard-codes today: `credential_source =
  ProviderCredentialSource.APP_OWNED` at `query_run_orchestration.py` ~1160
  is the line to pin as ABSENT-when-open of its replacement).
- `make validate` green (board header counts, ADR index, doc numbering).

### Item D — W5, the N=1 quick-answer mode

Read the decision register's W5 section first. If it names the mode's
guard, its copy and its price posture, build it as one PR the way PR 2 was
built (TDD, mutation, e2e as CI, two review rounds), respecting D9 (no
per-run toggle; the token-binding debt is not yours to add to). If any of
the three is missing, write `docs/analysis/2026-09-<day>-w5-scoping.md`
naming exactly which decision is owed, and park.

---

## 6. Practices that are not optional

- One concern per PR, dedicated worktree off fresh `origin/main`, merged and
  deployed before the next starts. Merge `main` in before starting.
- TDD with a bite-proof: capture the VERBATIM red output; prove every
  behavioural change by mutation; record each mutation in the commit body.
  Never `git checkout <file>`.
- Fan out for review, never for building. Tell every reviewer IN CAPITALS
  not to write, edit, `git checkout`, `git stash` or `sed -i` anything; a
  reviewer that runs code gets its OWN `git archive HEAD` copy. Never move
  the tree under a running reader or gate: no edits while `make quality`,
  `make diff-cover` or an e2e lane runs.
- Audit prose (rule 11a): every number, superlative and causal claim in
  comments, docstrings, ADRs, commit bodies and PR bodies names the command
  that produces it or says UNVERIFIED. On 2026-09-23 the prose lens found
  five false sentences the code lenses did not.
- Decisions get an ADR or a CHG row in the same PR. PROPOSED unless §4
  says decided.
- Keep `docs/00-factory-console.md` untouched by hand (it is regenerated);
  keep the board true.
- Close out in order: gates → findings resolved → close-guard → squash
  merge with explicit subject and body → every Deploy JOB read and
  `/status.build_sha` checked → ff main → delete branch local and remote →
  remove worktree.

---

## 7. Commands that bite

- Fresh worktree: `uv sync --all-extras` (not `--extra dev`), then
  `cd e2e && npm ci` if you will run e2e. A bare `uv run` builds a venv with
  no pytest and a phantom contract-collection failure.
- e2e exactly as CI, or ~95 phantom failures:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  rm -f .data/feedback_events.sqlite3
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <specs> --project=chromium --workers=1 --retries=0
  ```
  First blocking lane: the 18 specs listed in `.github/workflows/e2e.yml`;
  second lane: axe-all-views, parity-behavior, docs-under-csp,
  real-integration-smoke, degraded-banner, ops-dashboard, ops-navigation.
  The visual lane fails on this Mac by design (darwin baselines are stale);
  never `--update-snapshots`.
- `e2e/tests/review/` is gitignored scratch; anything you put there makes
  `test_no_orphaned_e2e_specs` red until you delete it. Delete your own.
- Never read a gate's exit status through a pipe:
  `make <target> > /tmp/gate.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/gate.log`.
- `timeout` does not exist on this box; use the tool's own timeout.
- Commit before trusting `make diff-cover`; run it after a fresh `make quality`.
- Delete your own `build/mutation` and `mutants/` before `make quality`.
- The advisory CI mutation gate hits its 24-minute deadline on a diff this
  size and reports a truncated prefix; read the artifact's `score.txt` for
  the number, post it on the PR, and do not treat it as a required check.
- A merge produces 3 to 6 Deploy runs; exactly one has a Deploy JOB of
  `success`; read the jobs, never the count.
- `/ui` answers 429 from this machine; `/status`, `/ready`, `/estimate` do not.

---

## 8. Reporting — at the end, and at any hard stop

Post one closing block, in this order, plain English, no jargon:

`Done` (what merged, SHA, and that it is running in production, each with
the command that proved it) / `Verified myself` (what YOU ran, with output;
subagent reports separately) / `Cleanup` (what was deleted, with the
command output; worktrees and branches gone; nothing unpushed) / `Pending`
(anything parked, with its draft PR and the decision owed, in my words) /
`Next action`.

Before the block: `make next`, `make skill-route`, `make handoff`, and a
narrative `docs/analysis/<YYYY-MM-DD>-session-handoff.md` (a second session
the same day appends `-2`), merged as its own docs-only PR, deploy verified.
If nothing is outstanding, end with "nothing pending — safe to close this
session" in those words.
