# Next session — start here (written 2026-09-29 by the session that ran W7 part 3)

Read `INDEX.md` in this folder first for the catalog. Then read in order: `AGENTS.md`, `docs/analysis/2026-09-29-session-handoff.md`, then
this file and `ENGINEERING-REVIEW-2026-09-29.md` (same folder as this file:
`/Users/rohitagrawal/Projects/quorum-ai-evidence/2026-09-29/`). Evidence for every
claim is in this folder: `inv-*/probe/` (reproductions of the owner's 9 bugs, with
a signed-in browser harness `harness.py`), `eng-review/` (defect census CSV, probes),
`workflow-reports/` (all review and map reports of 2026-09-28/29).

## The owner's standing instruction (2026-09-29, their words, paraphrased closely)
Act as the autonomous orchestrator and owner's proxy: plan, build, test and review
through fans of subagents, monitor them, and release when everything is green —
without needing the owner in the loop before a release. Think through every angle
of a feature before planning: all corner cases, negative cases, boundary values.
Escalate only what the global CLAUDE.md reserves for the owner (new authority,
spending money, legal/privacy/provenance decisions, destructive actions).

## First task: redesign the engineering harness (plan mode first)
Owner asked for a thorough review and plan covering:
1. The autonomous harness: planning fan → development → testing fan → review fan
   → green → release, with builder/grader separation (the agent that builds never
   writes or edits the acceptance tests it is judged by), and an independent model
   (Codex, via the Codex Claude Code subagent/skill, not the CLI) in review.
2. Acceptance-test-driven development: user journeys and acceptance examples
   written before code (by a test-design fan: happy path, negative, boundary
   values, equivalence classes, decision tables for limits, state transitions,
   multi-tab/multi-device, error messages, accessibility, phone widths), turned into
   real-backend signed-in browser tests that fail first.
3. Exploratory browser audits by agents with charters (Vercel `dogfood` method,
   reviewer-only) after each batch and before each release.
4. Slimming `AGENTS.md` (791 lines, 51 rules): one page of must-dos, the rest moved
   to topic docs or converted to automated checks.
5. **Skills audit:** classify all 113 skills in `.agents/skills` as (a) executes and
   checks something (has a runnable script/command with a pass/fail result) vs
   (b) statement-only prose. Evidence per skill. Recommend archive (not delete —
   owner's rule: archive project documents) for the statement-only ones, and list
   them for the owner.
Evidence already gathered: only 7 skill invocations in 26 transcripts (none of them
testing skills); the skill router is stuck in the "operate" phase.

## Owner decisions made 2026-09-28/29 (record them in `docs/19` as decided)
- Session limits: the per-network 2-a-day limit stays for anonymous use only and
  must never stop anyone signing in (a sign-in-only session); signed-in users are
  limited per account only.
- robots.txt: respect it; if disallowed, the judge uses the search excerpt.
- "Sign out everywhere" during a run: ask first; "Yes" stops the run and signs out
  everywhere; "No" signs out everywhere except the session running the run.
- Visual flake: allow just above the largest difference seen (589 px) for the
  trust-score screenshots only.
- Approved values: ADR-0137's four (events 10 / 30 days; sign-in start 5 then 1/min)
  and ADR-0138's two (idle 120 min, warning 5).
- W29: fetch cited pages when allowed; judge on titles when none fetched and say so;
  a $0 receipt row; wording "Checked against N of M cited pages"; turning it on
  only after one measured paid run; quick mode without pages first. Build the
  first piece next.
- BYOK: parked until W29 and the session-limit work are done; then research how
  comparable products secure user keys first; key in server memory only, never in
  logs, pages, cookies, browser storage or the database; per browser session,
  signed-in only, dropped on sign-out; removal mid-run stops the next step.
- Follow-up: send the previous question and final answer as context to **all four**
  models (their 2026-07-23 decision; the page never sent it); the next-question box
  opens empty with "Following up on: …".
- Simulated runs behave exactly like live (the banner already says simulated);
  messages name the limit actually hit and show today's remaining allowance.
- History: store the full result (answers, debate, synthesis) for signed-in
  accounts; keep the last 20 conversations for 30 days; delete one / delete all;
  clicking opens it read-only, with "Continue this conversation" (earlier turns as
  context, trimmed to a size cap, cost shown in the estimate). Check the server disk
  size first. Update `docs/48` and CHG-023.
- Starter questions: six audience groups, four complete questions each (list in
  `workflow-reports/owner-bug-report-investigation-*.md`), shipped with a wider
  high-stakes keyword list (own ADR).

## The owner's 9 bugs (all reproduced; causes in `inv-results.md`)
1 Start fresh wipes the session list · 2 old follow-up stays in the box · 3 block
card names the hard cap instead of the daily cap · 4 limits unclear · 5 follow-up
context never sent · 6 no way home from a result · 7 starter questions · 8 History
stale and not clickable · 9 empty session panel. Plus: the high-stakes detector
misses common medical/money questions and cites a test file that does not exist.

## Still pending with the owner
- Google sign-in: "Testing" does not restrict basic-scope apps (Google help
  15549945) — anyone with a Google account can sign in. Owner to choose: open, or an
  in-app email allow-list.
- #511 retest steps 3–4 (run one question, then sign out).
- A separate GitHub identity for agents (today every PR is authored and merged as the
  owner, 0 required approvals) — proposed; owner's call given the autonomy mandate.

## Traps from this session
See `docs/analysis/2026-09-29-session-handoff.md` and the memory index. Especially:
stop a background gate chain (TaskStop) before editing; no `pkill` by venv path;
signed-in tests that charge need their own Google subject; CI job limits, the deploy
gate wait and the drift grace move together; the visual flake strands deploys until
re-run.

---

## Research conclusions (2026-09-29, after two research runs, each contested by Codex and a Claude sceptic)
Evidence: `approach-research/` (synthesis.md, 7 lens reports, contest-sceptic.md, contest-codex.md) and
`skills-tools-research/` (shortlist.md, 6 lens reports, contest-sceptic.md, contest-codex.md).
Status: PROPOSED — confirm in plan mode before building.

**Approach.** Spec-driven development as the backbone (change-only specs, a permanent decisions log),
with acceptance examples first (Specification by Example / ATDD: negative, boundary, misuse cases;
written by a non-builder agent; mostly API-level plus one signed-in real-backend browser test per
journey path), unit TDD as the inner loop, systematic test design + risk-based testing, product
critique on the running app as an equal partner (exploratory sessions with charters, usability
heuristics, accessibility incl. WCAG 2.2), security by design sized down (per-feature threat model,
OWASP ASVS L1 / L2 for sign-in, money and data, abuse cases paired with the honest journey, LLM risks),
eval-driven development only for AI parts (a labelled pytest corpus for the high-stakes detector now;
stochastic evals when live execution returns), continuous delivery (install from uv.lock, verify the
deployed build, anonymous post-deploy journey check, rollback). Leave out: Spec Kit/Kiro/BMAD installs,
Cucumber glue, canary/blue-green, DORA targets, Pact, sprint contracts, 3 evaluators per change.

**Autonomy.** Delegation charter: the orchestrator decides within the owner's recorded decisions and
principles; escalates only money, legal/privacy, destructive actions, new authority; weekly async
digest to the owner. Independence by separation of duties with separate credentials: builder,
evaluator (Codex verdict on the exact commit, posted as a required check by a separate GitHub App),
release controller. Needs owner actions: a separate GitHub identity/App for agents, and agents run in
a separate OS user/container so the owner's `gh` token is not readable.

**Enforcement (layers).** CI required checks + branch protection (6 checks, admins included — exists);
new: an execution-backed signed-in journey gate (runs, unskipped, real API, criterion-linked, fails on
the known defect), canned-reply realism check, builder-can't-edit-acceptance-tests/gates (root-owned
managed settings sandbox denyWrite locally + CI rule), evaluator verdict check; tracked Claude Code
PreToolUse hooks (exit 2 blocks) for destructive commands as fast feedback; `.claude/settings.json`
is gitignored today — fix; Dependabot + CodeQL + osv-scanner + zizmor + Ruff `S` rules advisory,
promoted on measured yield; judgement duties (exploration quality, threat-model completeness) are a
named review lens, not deleted.

**Order.** 0 owner actions (identity, charter) in parallel → 1 baseline exploratory session on today's
build → 2 signed-in real-backend journey lane + execution-backed gate → 3 the nine bugs as failing
tests first, thin slices → 4 release integrity (lockfile install, deploy verification, alerts) →
5 slim AGENTS.md + tracked hooks + skills audit (archive list) → 6 remaining features through the loop
→ 7 monthly "who found the bugs"; promote checks only on evidence.

**Skills/tools.** Use existing tools properly (Playwright signed-in + criterion tags + aria snapshots,
axe WCAG 2.2, schemathesis stateful, Hypothesis state machines). Adopt: Dependabot/CodeQL, osv-scanner,
zizmor, Ruff S rules, v8-to-istanbul coverage for app.js (advisory), the Vercel dogfood checklist as
text (rewritten), an isolated pinned browser for exploratory agents (never the owner's Chrome),
Trail of Bits skills reviewer-only (trial). Defer: Playwright planner/generator (never the healer),
Inspect, claude-security plugin. Reject: superpowers, Spec Kit/Kiro/BMAD installs, paid review bots,
hosted eval platforms. Fix first: `scripts/audit_external_skill.py` passed 3 fake malicious skills;
6 "reviewer-only" skills load live; only 8 of 113 in-house skills ship any non-prose file.

## Added 2026-09-29, end of session (measured, commands in this session)
- **Agent identity is urgent, not optional.** `gh auth status`: the owner token on this Mac has scopes
  `delete_repo, repo, workflow, …`; `gh api repos/:owner/:repo --jq .permissions` → `admin: true`.
  Every agent here can therefore edit branch protection, workflow files, or delete the repo.
  Plan: bot account (Write, not Admin) with a fine-grained token for this repo only; agents run in
  Anthropic's reference dev container (https://code.claude.com/docs/en/devcontainer) with only
  that token; no `~/.config/gh`, `~/.ssh` mounted. Docker 29.7.2 is running. Verify inside the
  container: `gh auth status` shows the bot; editing branch protection returns 403 (negative), opening
  a PR works (positive partner).
- **Skills first pass** (`skills-tools-research/skills-firstpass.csv`, mechanical, NOT the full audit):
  113 folders; 6 are registered externals in `configs/external-skill-registry.json`, 107 unregistered.
  Of the 107: 2 ship a script (systematic-debugging, webapp-testing), 1 names a runnable command
  (subagent-driven-development), 104 are prose only. "Unregistered" ≠ written here — some look copied
  from public sources; the audit must check provenance per skill.
- **TOON:** not used anywhere in the repo; not recommended (Quorum's prompts are prose; independent
  studies arXiv 2603.03306 and 2605.29676 found accuracy costs). Revisit only for large uniform tables.
- **Real end-to-end:** no test today drives a signed-in browser through the real server and database.
  25 of 41 spec files replace server replies. The journey lane (order step 2) closes this, faking only
  Google's token check (tests/google_token_stub.py) and the models (production runs simulated today).

## Agent identity decided in outline (2026-09-29, owner offered `rohitagrawal4u`; PROPOSED)
Use GitHub account `rohitagrawal4u` (exists, created 2020, 0 public repos — `gh api users/rohitagrawal4u`)
as the AGENTS' identity, invited to `imrohitagrawal/quorum-ai` with Write (not Admin). Token: CLASSIC with
`repo` scope only — GitHub docs list "contribute to repositories where the user is an outside or repository
collaborator" as a gap of fine-grained tokens. Without `workflow` scope, agents cannot push changes to
`.github/workflows/`; the owner applies those (or grants the scope deliberately per change).
Order: this Quorum session first (steps 0–2); the starter (`NEW-PRODUCT-STARTER-PROMPT.md`) after, so it
copies only what was proven here.

## Tracker and roles (2026-09-30, PROPOSED)
- Correction: `imrohitagrawal/quorum-ai` is a personal-account repo, so collaborators have ONE level
  (push; cannot change settings, branch protection or delete) — there is no Write/Admin choice (GitHub docs,
  "Permission levels for a personal account repository").
- Track the harness work as rows in `docs/65-open-work.md` (state is derived from the tree by
  `scripts/check_open_work.py`, not typed). Mark rows that the starter should copy. The starter session
  starts when rows for steps 0–2 derive DONE; it copies only DONE rows.
- Roles to build (the missing separation): test designer (writes acceptance examples, not the builder),
  builder, evaluator (runs tests + a user-flow exploratory session with the dogfood checklist, Codex as a
  second model), release controller. Enforce: builder cannot edit acceptance tests (hook + CI rule);
  evaluator verdict is a required check.

## Agent account DONE by the owner (verified 2026-09-30)
- Token in macOS keychain, service `quorum-agent-gh`: `GH_TOKEN=$(security find-generic-password -s quorum-agent-gh -w)`.
  Never print it; never mount the owner's `~/.config/gh` or `~/.ssh` into the agent container.
- `gh api user` → `rohitagrawal4u`; scopes header → `repo` only; repo permissions → push true, admin false;
  collaborator check → 204. Branch-protection read with the agent token → 404 (refused); with the owner
  token → enforce_admins true, 6 required checks. Token expires 2026-12-29 04:55:55 UTC (GitHub `Github-Authentication-Token-Expiration` header) — add a board row.
- Still to do in step 0: the dev container that runs agents with only this token, and proof that a pull
  request opened from inside it works.

## Owner decision 2026-09-30 (their words: "Google sign-in open to anyone.")
- Sign-in stays open to any Google account; no in-app email allow-list. Record in `docs/19` with the others,
  and correct the runbook sentence that says "Testing" restricts sign-in (Google help 15549945: basic-scope
  apps are exempt). Revisit before live execution is turned on.
- #511 (PR, merged 2026-09-25): the query half is confirmed live by the owner's own signed-in runs on
  2026-09-29. Only the sign-out-after-reload check with a real Google account remains (owner, 1 minute).

## Notes and records (2026-09-30)
- `OWNER-DISCUSSION-LOG.md`: every owner message of this session, verbatim, with a status table. Update its
  Status column as rows are done. Read it before planning.
- This evidence folder now has LOCAL git history (`git -C ~/Projects/quorum-ai-evidence log`); not pushed.
  Secret scan of the commit: only fake test keys (sk-or-v1-12345…, a1b2c…, abcde…, 01234…, OPERA…).
- First PR of the next session: copy the durable notes (this file, OWNER-DISCUSSION-LOG.md,
  ENGINEERING-REVIEW-2026-09-29.md, both research syntheses) into `docs/analysis/2026-09-29/` so they live on GitHub.
- Conflict to resolve with the journey lane (step 2): AGENTS.md:587–590 prescribes the golden FIXTURE for UI
  checks; docs/DAY-ONE-PROMPT.md:135 (loaded by no session) says real providers, not mocks; AGENTS.md 17f says $0.
  The owner's position (M18.5, M22): final feature testing uses the real system, no fakes.

## Findability — the next session's FIRST pull request (owner asked 2026-09-30; PROPOSED)
Measured at 7c74b4f (`findability/measure_reachability.py`, run from the repo root): 538 tracked .md
files outside skills (+113 SKILL.md). Following links from AGENTS.md/CLAUDE.md, a new agent reaches 35
in one hop, 96 within two, 268 within three (plus the two starting files); **268 are not reachable within three**. The same kind of
information has several homes: decisions in docs/19, 136 ADR files, 76 analysis files, CONTINUE prompts
(4 tracked + 6 untracked at root), memory, this outside folder; open work in docs/65, GitHub issues,
handoffs. `docs/00-factory-console.md` last changed 2026-08-28.
The PR (small, one concern):
1. `docs/README.md` — the map: one row per KIND of information → its ONE home → how it is kept
   current (generated / checked) → when to read it. Owner product decisions → docs/19 (owner's words
   and date); technical decisions → ADRs; open work → docs/65 only; last session → docs/session-handoff.md;
   owner's words → an owner log per session; lessons → docs/103; how-to → runbooks + Makefile.
2. AGENTS.md line ~5 points to docs/README.md (the full slimming stays at step 5).
3. Copy this folder's durable notes into `docs/analysis/2026-09-29/` (INDEX.md, NEXT-SESSION-PROMPT.md,
   OWNER-DISCUSSION-LOG.md, ENGINEERING-REVIEW, both syntheses); update memory `evidence-folder-catalog`.
4. A check in `make validate`: every top-level docs/*.md is listed in the map or sits in a folder the
   map names with a generated index; RED-IF: a new doc is added without a map row (prove it).
5. A findability test, before and after: a fresh agent gets 10 "where is X?" questions (e.g. "what did
   the owner decide about sign-in?", "what is open?", "why is the mint cap 2?") and is scored on naming
   the right file. Record both scores; the PR states them.
