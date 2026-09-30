# New-product starter — session prompt (written 2026-09-29; status PROPOSED until the owner confirms)

Start this in a FRESH session, in plan mode, in `~/Projects/repo-template`
(`imrohitagrawal/repo-template`). Do not start it in `quorum-ai`.

## Goal
Turn everything learned on Quorum into a starter that a brand-new product repo gets on
day one, as files that RUN, not as advice. Success means a sample app created from the
starter goes red on planted defects and green once they are fixed.

## Read first (sources; do not copy them wholesale; they are long and partly stale)
- `~/.claude/CLAUDE.md` (owner's working style)
- `~/Projects/quorum-ai/AGENTS.md` (791 lines, 51 rules)
- `~/Projects/quorum-ai/docs/DAY-ONE-PROMPT.md` (822 lines, the current day-one prompt)
- `~/Projects/quorum-ai/docs/103-incident-learnings.md`
- `~/.claude/projects/-Users-rohitagrawal-Projects-quorum-ai/memory/` (index: `MEMORY.md`)
- `~/Projects/quorum-ai-evidence/2026-09-29/`: `ENGINEERING-REVIEW-2026-09-29.md`,
  `approach-research/synthesis.md`, `skills-tools-research/shortlist.md`, both `contest-*.md`
  files in each folder, and `NEXT-SESSION-PROMPT.md` ("Research conclusions" section)
- `~/Projects/repo-template` and `~/Projects/dot-github` (`imrohitagrawal/.github`: the
  shared pull-request quality workflow the template already calls, pinned at v7)

## The approach the starter encodes
Spec-driven backbone (a short spec per change, a permanent decisions log). Acceptance
examples are written BEFORE code by an agent that is not the builder: happy path, negative,
boundary and misuse cases. They become real-backend tests that fail first. Unit TDD is the
inner loop. Test design uses equivalence classes, boundary values, decision tables and state
transitions. Exploratory sessions with charters run on the running app, plus usability
heuristics and WCAG 2.2 AA accessibility. Security by design is sized to the product: a
per-feature threat model, OWASP ASVS L1, and L2 for sign-in, money and personal data.
Evals cover AI parts only. Continuous delivery: install from the lock file, verify the
deployed build, run a free check after each deploy, and have a rollback.
Not installed: BMAD, Spec Kit, Kiro, Cucumber, TOON. Borrow their ideas only
(Spec Kit's spec → plan → tasks order, EARS requirement wording, BMAD's role separation).

## Deliverables (each one RUNS or is a template that a check reads)
1. `AGENTS.md` — one page. Only must-dos, each naming the check that enforces it, or
   marked "influence only".
2. `docs/LEARNINGS.md` — distilled lessons from the sources. Each gets one line of what
   happened, the source file, and the check that now prevents it (or "no check yet").
   No lesson without a source.
3. `docs/DAY-ONE-PROMPT.md` — v2, short, replacing Quorum's 822-line one. The Quorum copy
   gets a pointer here, in a separate Quorum PR.
4. `docs/skill-map.md` — table: stage → skill → command it runs → what makes it fail.
   Only skills that run something against real work and exit non-zero on failure are kept.
   Take the classification from Quorum's skills audit (`skills-tools-research/skills-firstpass.csv`
   is the first pass: 104 of 107 unregistered skills are prose only).
5. Tracked `.claude/settings.json` plus hooks. A PreToolUse hook (runs before each tool
   call; exit code 2 blocks the call) stops destructive git commands, and stops the builder
   editing acceptance tests and gate files.
6. `.devcontainer/`, based on Anthropic's reference (https://code.claude.com/docs/en/devcontainer),
   with the network allow-list. Plus `docs/agent-identity.md`: agents run in the container as
   GitHub account `rohitagrawal4u`, which is a collaborator (a personal-account repo has one collaborator level: push, no settings, no branch rules, no delete). It
   uses a CLASSIC token with `repo` scope only (no `workflow`, no `delete_repo`), because GitHub's
   fine-grained tokens cannot be used on a repo where the account is only a collaborator. The
   owner's `gh` login and `~/.ssh` are never mounted. Verify it: `gh auth status` shows
   rohitagrawal4u; a branch-protection edit returns 403; opening a pull request works.
7. CI templates, added to `imrohitagrawal/.github` where they are shared:
   - required checks: tests, changed-lines coverage, a signed-in real-backend journey lane
     (Playwright → real server → real database; only third-party sign-in and paid model calls
     are faked)
   - install from the lock file, and a deploy-verification step
   - Dependabot, CodeQL, osv-scanner, zizmor and Ruff `S` rules, advisory first; each
     advisory check states what makes it blocking
8. Templates: decisions log/ADR, acceptance examples (Given/When/Then with negative and
   boundary rows), exploratory charter, one-page threat model, release checklist.
9. `scripts/defect_census.py` — counts who found each bug (gate, review, owner, user) from
   git history and issues. Run it monthly; promote a check only when it finds bugs.
10. **Proof:** create a throwaway sample app from the template, plant one defect per gate,
    show each gate going red with its output, fix the defects, and show green. Delete the
    sample afterwards, by name.

## Rules for this session
- Put nothing in the starter that was not proven on Quorum unless it is marked PROPOSED.
  Keep the builder and the grader separate. Codex reviews through the `codex:codex-rescue`
  agent.
- Every number in a doc comes from a command; otherwise write UNVERIFIED.
- Push, pull requests and merges need the owner's explicit approval, as in Quorum. Adding a
  collaborator and creating tokens are the owner's actions.

## New product vs existing product (the starter's README states both)
- New product: apply the whole starter on day one. Nothing needs retrofitting.
- Existing product: measure first. Run one exploratory session and the defect census, pin
  current behaviour with tests, add the journey lane for the top journeys, and turn known
  bugs into failing tests. Tighten gates only on measured yield.
