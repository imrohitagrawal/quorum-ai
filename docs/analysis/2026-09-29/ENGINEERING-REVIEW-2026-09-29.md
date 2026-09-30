# Quorum engineering review — why the owner keeps finding bugs, and what changes

2026-09-29. Repo `quorum-ai` at `7c74b4f` (also what production runs).
How this was produced: six read-only evidence investigations (defect census,
test anatomy, requirements, rules and skills, industry research, public skills),
one synthesis draft, then two independent contests — Codex (through its Claude
Code subagent) and a separate Claude sceptic — and my own re-checks of the
load-bearing claims. Every figure below names its source. Full evidence:
`/Users/rohitagrawal/Projects/quorum-ai-evidence/2026-09-29/` (probe scripts,
`eng-review/probe_census/census.csv`, workflow reports, the draft and both contests).

---

## 1. The answer in one paragraph

Quorum was built with a great deal of machinery for checking that **the code does
what its author meant** — unit and integration tests written first, mutation
proofs, six required CI checks plus many advisory ones, adversarial code reviews. Almost nothing checked that
**a user can do what you meant**. Your intentions were rarely written down as
testable user outcomes, some that were got archived, the browser tests mostly
talk to a fake server and cannot sign in, and reviews compared each change with
its own description rather than with your intent. The evidence: of 230 recorded
defects, automated gates found 18 — all in the CI plumbing itself — and **none**
of the 39 user-journey or 25 message-accuracy defects; you found 33 of those, and
agents that actually drove a browser found 16. The fix is not more rules or
more skills; it is (1) your intent written as short journey statements you
approve, (2) real-backend browser tests of those journeys, signed in, (3)
regular exploratory browser audits, and (4) a separate identity for the agents
so "owner-approved" means you.

## 2. What we found (evidence)

### 2.1 Who finds defects — the census
Source: `eng-review/probe_census/census.csv` (230 rows, hand-classified by an
agent from git history, 147 GitHub issues, triage docs, ADRs and handoffs;
re-counted by me with Python). Limits: it counts defects that were recorded
or fixed; it cannot see what the gates prevented before merge, and the labels
are judgement.

| Category | You | Code review | Agent audits* | Production runs | **Gates** | Unknown | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| User journey / UI state | **21** | 5 | 10 | 1 | **0** | 2 | 39 |
| Message / copy accuracy | **12** | 6 | 6 | 0 | **0** | 1 | 25 |
| Money / limits | 1 | 13 | 8 | 11 | 0 | 3 | 36 |
| Security / privacy | 1 | 8 | 7 | 0 | 0 | 1 | 17 |
| Data / scoring | 3 | 14 | 13 | 0 | 0 | 1 | 31 |
| Integration / external | 2 | 1 | 4 | 2 | 0 | 1 | 10 |
| CI / infra / gates | 0 | 20 | 25 | 4 | **18** | 4 | 71 |
| Performance | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| **Total** | **40** | 68 | 73 | 18 | 18 | 13 | 230 |

*Agent audits: agents that found the defect while doing something else —
several of them (07-01 UI/UX audit; 07-28 #111, #115–#118, #126) by using the app
in a real browser.

- Your 40 finds land only on the days you used the product: 07-15 (6), 07-23 (14),
  07-29 (1), 09-03 (3), 09-09 (5), 09-25 (2), 09-29 (9). 18 of the 40 repeat a class
  already on record.
- The repo's own "0 of N" audit (`docs/metrics/defect-discovery-audit.md`), re-run
  unchanged: 84 `src/` Python fix commits; 1 found by a gate, and that one was a test
  disagreeing with correct code. The same method on `.js` finds 38 fix commits —
  where your bugs live — and Python-only coverage (`pyproject.toml:125
  --cov=src`) does not measure the 10,473-line `app.js` at all.
- Caveat from Codex: commits are not defects, and this measures escapes, not
  what gates are worth. Gates do catch a developer's own slips before merge. The
  finding is narrower and still decisive: **gates have never caught the class of
  defect you keep finding.**

### 2.2 What the tests exercise
Source: test-anatomy lens; counts re-run by the sceptic.
- 5,378 pytest tests; 34 browser specs with 398 tests.
- Roughly 22–28 of the 34 browser specs replace the server with canned replies
  (`page.route` / fixtures). One of those canned replies (a blocked estimate with
  total $0.300) is exactly the state where the block card lies — and no test reads
  the card's words (`grep "no override exists|Over the hard cap"` over tests: 0).
- **No browser test can sign in** (grep `addCookies|storageState|/auth/`: 0). The
  e2e server starts with no sign-in settings (`e2e/playwright.config.ts:31-32`).
  Yet a loopback fake-Google sign-in already exists for Python tests and worked in
  a real browser this session — it was simply never wired into the browser suite.
- `page.goBack`: 0 uses. The empty "This session" panel: checked only for presence.
- Some journeys *are* tested (Codex's correction): `session-trail.spec.ts:171`
  (result → follow-up → second result), `parity-behavior.spec.ts:1513`, AC-051. So
  the diagnosis is **specific outcomes you wanted were never written and never
  checked**, not "zero journeys".
- One blocking test requires a behaviour you call a bug: `session-trail.spec.ts:132`
  ("Start fresh" must wipe the list; run in a required lane). Others were
  overstated in the draft: `parity-behavior.spec.ts:568` checks a different box
  from the one in defect 2.

### 2.3 Requirements and your decisions
Source: requirements lens; re-checked by me.
- Acceptance criteria stop at **AC-052** (sign-in and sign-out). History, account
  deletion, sign-out everywhere, the idle reminder, follow-up context, the limits
  and their messages, the landing page — **no acceptance criterion**. The W7 PRs
  edited no requirement document (`gh pr view` on #518, #519, #521, #522).
- The traceability gate accepts any file containing one AC number (sceptic
  replaced all 52 criteria with two lines: "all validation gates passed").
- **Your decisions have no permanent home.** Your 2026-07-23 decision — follow-ups
  send "prior question + final synthesis" — lives only in
  `docs/archive/2026-08/UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md:42-44`, moved there
  by the housekeeping commit `aba4a0c` (2026-08-11, "clear the repo root"). The
  server half was built; the page never sends it (`app.js:96-100`).
- A safety gap the review surfaced: the medical/legal/financial warning detector
  (`safety.py:35-42`, an 18-word list) returns False for "How do I read this lab
  result?", "…pay off my student loans early?" and "What dose of ibuprofen is safe
  for my child?", although AC-005 requires the warning for medical topics. Its
  comment cites a test file `test_high_stakes_keyword_uses_word_boundaries` under
  tests/unit that does not exist (`ls`) — since the first commit.

### 2.4 Rules, prompts and skills
Source: process and skills lenses; re-checked by the sceptic.
- `AGENTS.md`: 791 lines, 51 numbered rules, 7,057 words; about 11,800 words of
  instructions load at every session start. Much of it is incident narrative. The
  words "journey" and "exploratory" appear **0** times in the rule documents.
  Anthropic's Claude Code guidance: "Bloated CLAUDE.md files cause Claude to
  ignore your actual instructions!" (code.claude.com/docs/en/best-practices).
- The merge checklist in the prompt you sent (`CONTINUE-2026-09-25-ULTRACODE-PROMPT.md:92-93`)
  required correctness, break-it and prose reviews and "the e2e lanes if UI
  changed" — no journey review, no signed-in test, no acceptance walk-through.
  An earlier session wrote that prompt.
- The UI rule in `AGENTS.md:583-586` is "influence, not enforcement" and triggers
  only for `app.js`, `app.css`, `workspace.html`; the History panel is built in
  `main.py`.
- **113 skills, barely used.** Across 26 Claude Code transcripts (30,284 tool
  calls) there were 7 skill invocations in total (`work-package-protocol` 4,
  `workflow-authoring` 3); no testing skill was ever invoked. The skill router
  (`scripts/skill_router.py:166-190`) is stuck in the "operate" phase and never
  looks at what a change touches; `e2e-testing-patterns` and `webapp-testing` are
  not even in its config. Your repo's own `e2e-testing-patterns` skill lists
  "Critical user journeys" and "Authentication flows" as must-test.
- Your global triage rule (`~/.claude/CLAUDE.md:110`) blocks only an "executable
  violation of an explicit accepted requirement"; with no requirement written,
  "no e2e lane can sign in" was classed advisory and merged (#519 body line 38,
  #522 body line 42).

### 2.5 Governance — found by the sceptic, verified by me
- Branch protection: `required_approving_review_count: 0`, no code-owner review.
- Every PR (#517–#526) is authored and merged by `imrohitagrawal` — the agents act
  on GitHub **as you**, with `repo`, `workflow` and `delete_repo` token scopes.
- So any "owner-approved" label, PR section or column can be self-certified by an
  agent, and an agent can edit the gate in the same PR. The only real boundary is a
  separate agent identity plus required review by you on the files that define
  intent.

### 2.6 A product fact behind defect 3
Production `/status`: `live_execution: false`, real spend `$0`, simulated spend
`$0.4645`. Simulated runs count against the $0.40 daily cap by design (ADR-0074),
so a user is blocked after about 3 practice questions — then shown the wrong
limit. (You have since decided simulated runs should behave exactly like live,
with clear messages.)

## 3. Your questions, answered

**"Functional" means every level — UI, app, API, integration, user behaviour.**
Agreed. The complete set of angles for this product, and where we stand:

| Angle | Today | Missing |
|---|---|---|
| Unit | Strong (TDD, mutation proofs) | — |
| API / contract | Strong (schemathesis, openapi) | — |
| Integration, real backend | Python TestClient only | Browser ↔ real server; most browser tests use fakes |
| End-to-end user journeys | A few, anonymous | Signed-in; written from your intent; real server |
| Acceptance (your outcomes) | AC-001…052 | Everything after sign-in; your decisions as tests |
| Exploratory (unscripted use) | Occasional agent audits | Scheduled, with charters |
| Message / copy accuracy | Partial | Every limit and error message checked against the real state |
| Security (user level) | Strong on server | Signed-in browser flows |
| Privacy / data lifecycle | Designed per feature | End-to-end retention and deletion checks |
| State and multi-device | Server races tested | Reload, sign-in/out, two tabs, two devices in a browser |
| Safety classification | One pinned word | A list of real medical / legal / money questions |
| Accessibility | axe lane | Signed-in pages |
| Cross-browser / phone | CSP smoke in 3 engines; some widths | Journeys on Safari/Firefox and phone widths |
| Performance / cost | Estimates, budgets | Time-to-answer from the user's side |
| Post-deploy verification | Build SHA, /ready | A journey check that doesn't consume users' limits |
| Observability | Logs, /status, ops page | — (adequate for now) |

**Why didn't TDD catch these?** TDD as practised here writes a failing test for
the function or route the developer is about to change, then makes it pass. It
checks the developer's design, and it is only as good as what the developer
thought of. It cannot catch "the owner wanted the History to update" unless that
outcome is written as a test first — that is acceptance-test-driven development
(Agile Alliance glossary; Dan North's BDD), a different practice. Research on
AI-written tests says the same: they tend to "capture the actual program
behaviour rather than the expected one" (Konstantinou et al., arXiv 2410.21136).

**"They reviewed the code, not the product" — but the product is the code.**
True, and that is the point. A reviewer reading a diff checks whether the change
does what the PR says. Nobody checked whether the PR said what you wanted. The
History PR was internally correct — it deliberately built History without a way
to refresh it (ADR-0135: "no separate endpoint") — so a correctness reviewer had
nothing to flag. Software engineering calls these verification ("built right")
and validation ("the right thing"). Our reviews did verification, thoroughly, in
parallel subagent fans (#522 had four lenses, #521 three), and almost no
validation. And note #518 *was* driven in a real browser at two widths — it
still shipped a stale History, because the reviewer was checking layout, not
your journey.

**Should we download more skills?** No skill is missing; use is. The repo already
has `e2e-testing-patterns`, `webapp-testing`, `test-architecture`,
`accessibility-testing` and ~10 more that cover these defects; they were invoked
0 times. One public method is worth adopting, as a reviewer-only practice per
the repo's own onboarding policy: Vercel's `dogfood` skill (vercel-labs/agent-browser,
Apache-2.0; ~43k stars; shipped inside `agent-browser`, ~895k installs,
checked 2026-09-29). It explores the running app as a user without reading the
source, and its issue checklist names "Dead ends (no way to go back)", "stale
data", "Missing or unhelpful empty states" and "Unclear error messages" — four of
your nine. Take the method and checklist; don't install its separate command-line
tool (the policy rejects broad shell plus network access). The popular
obra/superpowers TDD and verification skills repeat rules the repo already has.

**Is there a flaw in the prompt or workflow?** Yes, five, each with a source:
1. No place for your intent: no acceptance criteria past AC-052; your decisions
   archived by housekeeping (`aba4a0c`).
2. The merge checklist (`CONTINUE-2026-09-25-ULTRACODE-PROMPT.md:92-93`) names
   code-risk reviews and existing test lanes only.
3. The UI rule is advisory and scoped to three files (`AGENTS.md:583-586`).
4. The triage rule can't block a missing test when no requirement exists
   (`~/.claude/CLAUDE.md:110`).
5. No separate agent identity: "owner-approved" is self-certifiable (branch
   protection: 0 approvals).
Plus one of mine: I wrote "no e2e lane can sign in" as a footnote instead of
stopping and telling you.

## 4. What the contests changed

The first draft proposed about 15 new automated checks. Both contests rejected
that as contradicting its own evidence (gates have caught 0 journey defects) and
as gameable by agents that act as you. Specifically:
- **Dropped:** a check banning the phrase "no e2e lane can sign in" (it would teach
  agents to hide gaps); screenshot-as-proof checks (#518 had screenshots and still
  shipped the bug); fixing the unused skill router; a word-count gate on the rules;
  a production watchdog that loads `/ui` (it would mint sessions against the
  daily cap and trip its own alarm).
- **Changed:** signed-in browser tests need no production change — a small test
  launcher reuses the existing fake-Google seam; defect 3's root cause is a missing
  field in the server's reply (`CostEstimate` has only prose reasons for four
  different blocks), not the fake data; not every limit reaches the block card
  (the $5 ceiling and the session cap have their own paths); a "must fail on the
  base commit" rule is necessary but gameable (a test for a new element id fails
  on base and checks nothing a user does).
- **Promoted:** exploratory browser audits (the best-evidenced lever); a
  permanent home for your decisions; a separate agent identity.
- **Added by Codex:** "reopen History" is a product and privacy decision (you've
  now made it: store full results), not a missing click handler; quick mode must
  keep refusing follow-up context (AC-051).

## 5. The plan (ordered; each with how it's enforced and how we'll know it works)

1. **Your intent, written and owned by you.**
   - A never-archived "Owner decisions" section in `docs/19`, and ~15 one-sentence
     journey statements for today's product ("A signed-in user can reopen any of
     their last 20 questions with its full answer"), which you approve.
   - Enforced by: #5 below (only you can approve changes to these files).
   - Measure: every journey statement maps to a passing browser test.
2. **Real-backend, signed-in journey tests.**
   - A test launcher that signs in with the fake Google account; a fresh database
     per test; assertions read the words on screen, written from your sentences,
     never from the code. First: the nine defects, each as a red test before its fix.
   - Enforced by: a required CI lane; journey specs in a folder only you can approve.
3. **Exploratory browser audits.**
   - After each batch of UI merges, an agent uses the app as a user with a charter
     ("hit every limit", "use it on a phone", "sign out mid-run"), using the
     dogfood checklist; findings become red tests. And a 15-minute session by you
     before each release.
   - Measure: defects found by audits rise; defects found by you fall.
4. **Fix the nine defects and the gaps found** — including a `block_reason` field
   and a limit-to-message table, the safety detector tested against a list of real
   questions, and the missing test file.
5. **A separate agent identity on GitHub** (a bot account or GitHub App) and
   required review by you on `docs/12`, the owner-decisions section and the
   journey specs. This is the only step that makes "owner-approved" real. It is
   your action (account and branch-protection settings); cost: you approve those
   PRs.
6. **Two review lenses always in the fan-out:** acceptance/journey (use it like the
   owner against the journey statements, not the PR's own description) and test
   adequacy (every statement has a test that can fail; no fake the server can't
   produce; no test keeps a reported bug).
7. **Planning:** every plan starts with a test-plan table — journey statement ×
   angle (§3) × test × lane — before code; "can't test X" is a stop you hear about
   before merge, never a footnote.
8. **Slim the rules.** Keep a one-page list of must-dos in `AGENTS.md`; move
   incident history to docs. No new gate for this.
9. **Measure, then decide.** After one month: owner-found vs audit-found vs
   test-found defects per week. Add a check only where the numbers show a hole.

Deliberately not in the plan: more skills beyond the dogfood method; more
standing reviewers; checks on PR-body wording.

## 6. Using this product as the roadmap for new products

1. Before code, write the product as 10–20 plain-sentence user journeys; the owner
   approves them. Keep a decisions log that is never archived.
2. Build in thin slices — each slice is one journey end to end (page + API + data),
   demoed by using it.
3. Each journey gets a real-backend browser test (signed in where relevant) that
   fails first, written from the journey sentence.
4. Unit TDD for logic, contract tests for the API — but they don't count as proof
   the journey works.
5. After every batch: an exploratory session in a browser, by an agent with a
   charter and by the owner.
6. Agents use their own identity; the owner approves the journeys and their tests.
7. Keep the rules short; turn repeated rules into automated checks or delete them.
8. Use the testing-angles table (§3) as the checklist for every feature.
9. Measure who finds the bugs; move effort to whatever finds them.

## 7. Learnings

- Precision about code is not the same as fidelity to intent. We had a lot of the
  first and little of the second.
- A test that the agent writes and can edit is weak evidence of what the user
  wants; the user must own the examples.
- Fakes in browser tests hide exactly the states users hit.
- Decisions that live in session notes get lost; decisions need a permanent home
  and a test.
- More rules made the important ones less visible; unused skills don't help.
- Gates prevent regressions; they don't find new product defects. Using the product
  does.
- "I couldn't test this" must stop the merge and reach the owner.
- Agents acting as the owner make every approval step self-certifiable.

## 8. Open questions the evidence could not settle
- How many defects the gates prevented before merge (the census can't see them).
- Whether the scheduled exploratory audits keep finding defects over time (to be
  measured, §5.9).
- The server disk size for storing full results (not in `fly.toml`).
- Note on project age: the repo's history starts 2026-06-20 (475 commits).

## Sources
Repository evidence: file:line and commands above; census and probes in this folder.
- Fowler, Test Pyramid — https://martinfowler.com/bliki/TestPyramid.html
- Vocke, The Practical Test Pyramid — https://martinfowler.com/articles/practical-test-pyramid.html
- Google Testing Blog, "Just Say No to More End-to-End Tests" — https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html
- Kent C. Dodds, The Testing Trophy — https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications ; Write tests — https://kentcdodds.com/blog/write-tests
- Spotify, Testing of Microservices — https://engineering.atspotify.com/2018/01/testing-of-microservices
- Agile Alliance, ATDD — https://www.agilealliance.org/glossary/atdd/ ; Definition of Done — https://www.agilealliance.org/glossary/definition-of-done/
- Dan North, Introducing BDD — https://dannorth.net/blog/introducing-bdd/
- Fowler, Specification by Example — https://martinfowler.com/bliki/SpecificationByExample.html ; Gojko Adzic — https://gojko.net/books/specification-by-example/
- Exploratory testing: Cem Kaner — https://kaner.com/?p=46 ; Hendrickson, Explore It! — https://pragprog.com/titles/ehxta/explore-it/ ; James Bach — https://www.satisfice.com/blog/archives/856
- Testing quadrants: Brian Marick — http://www.exampler.com/old-blog/2003/08/21/ ; Lisa Crispin — https://lisacrispin.com/2011/11/08/using-the-agile-testing-quadrants/
- Contract testing: Fowler — https://martinfowler.com/articles/consumerDrivenContracts.html ; Pact — https://docs.pact.io/
- Testing in production: Fowler, QA in production — https://martinfowler.com/articles/qa-in-production.html ; Synthetic monitoring — https://martinfowler.com/bliki/SyntheticMonitoring.html ; Cindy Sridharan — https://copyconstruct.medium.com/testing-in-production-the-safe-way-18ca102d0ef1
- AI-written tests capture actual behaviour: Konstantinou, Degiovanni, Papadakis — arXiv 2410.21136
- Reward hacking / test tampering: ImpossibleBench — arXiv 2510.20270; SWE-Bench+ — arXiv 2410.06992; "Are 'Solved Issues' in SWE-bench Really Solved Correctly?" — arXiv 2503.15223; SWE-bench Verified — https://www.swebench.com/verified.html ; Baker et al. — arXiv 2503.11926
- Anthropic, Claude Code best practices — https://code.claude.com/docs/en/best-practices ; "Effective harnesses for long-running agents" (26 Nov 2025) and "Building effective agents" (19 Dec 2024), anthropic.com
- Skills: vercel-labs/agent-browser (dogfood) — https://github.com/vercel-labs/agent-browser ; obra/superpowers — https://github.com/obra/superpowers ; anthropics/skills — https://github.com/anthropics/skills
