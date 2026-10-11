# How we work: what slows us, what we redo, and what to change (2026-10-11)

Written by the 2026-10-11 session (transcript `c512313e`) at the owner's request. Four read-only
researchers gathered the evidence; the session re-ran the claims marked **checked**. Everything else
is the researchers' measurement. They ran commands but were not re-checked. Numbers marked
ASSUMED were not measured.

## Answer

The process exists, but in **ten places, and none of them is where a new session starts.**

- **Every session re-types it from memory, and every re-typing drops something:**
  - each handoff prompt is written fresh;
  - 0 of the 8 root prompt files name `R2-S2-S4-ULTRACODE-PROMPT.md` or
    `AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md` (**checked**, `grep -c`);
  - `AGENTS.md` names neither, nor the `work-package-protocol` skill.
- **Writing a lesson down has not stopped it coming back.** Every theme the researchers checked
  came back after its memory note or rule was written. Examples:
  - "concise" was asked for 18 times after the 08-24 note;
  - status was asked for 25 times after the 08-12 note.
- **The feedback loops that would show this stopped in August:**
  - the compliance ledger (`docs/analysis/protocol-compliance.md`) has 3 rows, the last on
    2026-08-25 (**checked**);
  - `docs/103-incident-learnings.md` and `docs/metrics/defect-discovery-audit.md` were last changed
    in July or early August.

So the fix is not a better document. Keep **one** home for the process, make every session load it
automatically, and add a few checks that fail when it is skipped.

## The two prompt files, and the skills

| File | What it is | State |
|---|---|---|
| `R2-S2-S4-ULTRACODE-PROMPT.md` (July) | A worked example of building ONE feature: a precondition, rules for every slice, decisions already made, a code map, the slices, the definition of done, a final report | Marked "STATUS: COMPLETED (2026-07-21/22)" (**checked**). It says 3 review rounds (now 2) and "judge off" (production is on). Pinned by `tests/test_ultracode_prompt_enforcement_contract.py`, so it cannot simply be moved |
| `AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md` (Aug 25) | Roles and authority for running MANY items: a main orchestrator, one sub-orchestrator per item that never merges, 3 planners, 1 builder, 3 different reviewers, a review for every fix, a compliance audit | Its audit stopped after 3 items. It has none of what was learned since August |
| `templates/feature-slice-ultracode-prompt-template.md` | R2's shape with the specifics removed | August; same gaps as R2 |
| `work-package-protocol` skill (`stackclimb-skills`) | The generic version of LOOP for one item: discover, build, review, merge, verify, clean up. It names no project's paths | The installed copy (`~/.claude/skills`, linked to `~/stackclimb-skills` at `4c49e59`, 2026-09-09) is **143 commits behind** GitHub `main` (**checked**) |
| `multi-work-package-orchestration` skill | Several linked items: a main orchestrator, delegated items, merges kept in order, status you can resume from | On GitHub `main` only; **not installed** (**checked**). The repo also has 8 worktrees of unfinished "pl5" work |

**The owner's reading is partly right.** R2 holds the *format* and the engineering principles for
building a feature. LOOP holds the *roles and authority*. They complement each other, but neither
is complete:

- **Only in the newest prompt** (`CONTINUE-W55-W56-PROMPT.md`):
  - a separate test designer, and a builder that may not edit the tests;
  - Codex run against the pull request's worktree;
  - a browser run of the journeys in `docs/113`;
  - limits on workflow size;
  - cleanup of disk space.
- **Only in old prompts or in memory:**
  - never trust a background job's exit code;
  - every wait loop needs a time limit;
  - save `fly logs` to a file at once;
  - Mac sleep needs `caffeinate`;
  - clear `__pycache__` between mutation steps.
- **Nowhere in `AGENTS.md`:**
  - owner decisions in `docs/19` (0 hits, **checked**);
  - board needles in `docs/65`;
  - checking for other live sessions;
  - disk cleanup.
- **The files contradict each other:**
  - **Who merges:** LOOP says only after a grant spoken in the session; other prompts carry a
    standing written grant.
  - **How many reviewers:** 3 lenses, or 4, or 9 to 14 agents.
  - **How many rounds:** 3, N, or 2.
  - **Workflow size:** 8, under 10, or 14 agents.
- **The memory index was over its load limit,** so its last 4 lines were never loaded. This session
  shortened it from 25,947 to 21,203 bytes, keeping all 113 entries.

## What we redo

Measured from 428 commits, 391 pull requests and 24 handoffs since 2026-07-15:

1. **One issue, many pull requests.**
   - #268 and #105 took 10 pull requests each and are still open.
   - #290 took 8.
   - The usual cause is a shipped value changed before the repo was searched for every place that
     states it: `ef4a716` needed 11 review rounds for a one-line fee.
2. **Third and later review rounds.**
   - 9 commit bodies record one: 11, 6 and 4 rounds.
   - In each, rounds 2 and 3 found defects the previous fix had added.
3. **False claims in prose, corrected later:**
   - 13 correction commits, for example "broken for months" that was really 8 days;
   - also counts that were never measured, and an ADR that overstated its reach.
4. **Wrong premise, or a fix too big for the problem:** 4 of 9 pull requests closed unmerged (#239,
   #500, #371, the #369 re-scope).
5. **Issue state out of step with the board.** Issues #447, #464, #465 and #469 are open while
   their board rows say DONE (**checked**). Close-keyword accidents stopped after the close-guard
   (#375).
6. **Production assumed to be in a state it was not in:**
   - 12 handoffs reported production "unreachable" because of a script bug (#478);
   - cost figures taken with the judge off were used while production had it on (#381).
7. **CI time limits set just above the current run time:** raised twice in 4 days (#547, #554).

## Where the time goes

Measured over pull requests and sessions since September:

- **A pull request is not the slow part.** From open to merge takes a median of 0.4 h. The work
  happens before it opens.
- **Waiting is the slow part:**
  - sessions were open 852 h but active about 92 h;
  - owner questions took a median of 50 min to answer, p90 14.6 h;
  - about 0.95 active hours per merge.
- **CI got about 4× slower:**
  - main CI median 5.2 min in early August, 19.4 min in October (**checked**: 19 min over the
    last 20 runs on `main`);
  - the unit-test step alone is 24.8 min of the slowest job.
- **The full test suite runs up to four times per change:**
  - `make test-report` and `make diff-cover` in `ci.yml`, and `make test` in `test.yml`
    (**checked**, grep);
  - then again on `main` before deploy: merge to deploy takes a median of 20.9 min;
  - whether `diff-cover` re-runs the whole suite is ASSUMED from its 20-minute job time.
- **Pull requests are growing:** the median size went from 346 lines changed in July to 1,109 in
  October.
- **Review outweighs building:** 166 review agents against 24 builder agents. How many reviews
  found nothing is not measured.

## Mistakes the owner had to catch

From 217 owner messages, 08-29 to 10-11. The counts come from a keyword search, so they are
approximate.

1. **Handoff prompts drop the agreed practices** (about 31 requests for "the exact prompt").
2. **The owner has to ask for status** (25 times after the 08-12 note).
3. **Jargon with no example** (37 "what do you mean"; 18 "concise").
4. **The product is not tested the way the owner uses it, so defects reach production:**
   - examples: #511, the #290 readout, W33 bugs 1–10;
   - the 09-29 review found that the owner, not the gates, caught 33 of 64 journey and copy
     defects (inherited, not re-measured).
5. **Merge authority misjudged both ways** (about 13): not merging when allowed, and merging on red.
6. **Cleanup not confirmed** (about 11).
7. **Decisions already made were asked again** (about 6). This continued after the decision map
   (`docs/README.md`) landed.
8. **A claim stated without a check** (about 6).

## What to do: one home, loaded every time, with checks

**Layer 1: one process skill, inside this repo first.**

- **The skill:** `.agents/skills/work-item-delivery/`. It holds the full process:
  - the roles, including the two testers;
  - review rounds and workflow limits;
  - who merges;
  - production checks, cleanup, and how to ask the owner.
- **Why here first:** `AGENTS.md` already says a procedure moves to `.agents/skills/` "once
  generalised", so this needs no new mechanism. quorum-ai never waits on `stackclimb-skills`.
- **Contradictions it settles:**
  - **merges:** only the main orchestrator, under the approval given in the prompt;
  - **reviewers:** 3 lenses plus Codex;
  - **rounds:** exactly 2, plus one narrow re-check of each fix;
  - **workflows:** at most 8 agents.
- **Later, as a separate task:** `stackclimb-skills` takes the generic parts into
  `work-package-protocol` and `multi-work-package-orchestration`, and installs the latest version.
  That repo has 8 worktrees of unfinished "pl5" work to settle first.

**A dedicated user-journey tester (owner's direction, 2026-10-11).** This role is separate from the
test designer, who writes failing acceptance tests against the code. The user-journey tester works
from the owner's expectations, never from the pull request's own description:

- **Before the build:**
  - writes what the owner expects to see and do, step by step;
  - works from `docs/113-user-journeys.md` and the owner-approved journey statements;
  - covers both signed-in and anonymous use.
- **After the build:**
  - drives the real running app the way the owner uses it, signed in and anonymous, at desktop and
    phone widths;
  - reports each expectation as met or not, with a screenshot.

This is part (1) and (3) of the fix the 2026-09-29 engineering review proposed
(`docs/analysis/2026-09-29/ENGINEERING-REVIEW-2026-09-29.md`). That review found that agents which
actually drove a browser found 16 defects, while the gates found none of the 39 user-journey defects.

**Layer 2: make the existing mechanisms load it.**

- **`configs/skill-router.json`** (`make skill-route`) picks one skill per product phase, from idea to
  publishing. It came with the template and has been unchanged since 2026-06-20. Its result is the
  same for every item: in the current phase it names one driver skill and 39 reviewer skills.
  It never mentions the delivery process (0 hits for `work-package-protocol` or `journey`). Add a
  route, "deliver one work item", whose driver is the new skill.
- **`AGENTS.md`** loads into every session and every agent. Add a few lines: "every item is
  built by `.agents/skills/work-item-delivery`". They also cover what `AGENTS.md` lacks today:
  - `docs/19` for decisions;
  - `docs/65` needles;
  - the check for other live sessions;
  - disk cleanup.
- Archive LOOP and the template, or change them to point at the skill. Keep R2 where it is,
  because a test pins it, and mark it as an example.

**Layer 3: the handoff prompt** (short, per session): which items, in what order, the decisions to
read, what is approved, and one line naming the skills. No process text.

**Checks that make skipping visible, ranked by value per effort:**

1. **`make handoff` fails or warns** when any of these is true:
   - a root prompt file does not name the skills;
   - an issue's state disagrees with its board row;
   - more than 5 merges have landed since the last compliance-ledger row;
   - leftovers remain: worktrees, branches, scratch files.

   It also prints the production settings from `/status`. One script covers
   redo causes 5 and 6 and mistake themes 1 and 6.
2. **One test-suite run per change in CI,** feeding both the test report and the coverage check, and
   no re-run on `main` when the merged tree was already tested. This is the largest time saving;
   measure first how the suite runs inside `diff-cover`.
3. **Pull-request template fields, checked in CI:**
   - the premise, with the command and its output;
   - review rounds;
   - the source of every number in the prose;
   - the owner decision needed, with its CHG row;
   - for a bug fix, who found it.
4. **A search before changing a constant:** a script lists every file that states the old value,
   and its count goes in the pull request. This targets redo cause 1.
5. **A real-backend, signed-in browser lane for each user journey.** This targets mistake theme 4.
   It is the largest change, so it is its own item.
6. **A status line or stop hook** that lists background jobs and agents with their age. This
   targets mistake theme 2. It changes the owner's Claude Code settings, so it needs the owner's
   approval.

## The skill router (`configs/skill-router.json`)

Measured by a read-only researcher; the run of `python3 scripts/skill_router.py` was repeated by a
second researcher.

- **It never looks at the work item.**
  - It walks the product phases and stops at the first document that is missing or still a
    template. Every document is now filled, so it always lands on "Operate, learn, and improve"
    (`scripts/skill_router.py:166-191`).
  - It decides risk by searching 12 product documents for keywords. Bare words like "ai" and "ui"
    match almost any text, so 7 of 9 risk triggers always fire.
  - The answer is therefore the same for every item: one driver skill and 38 to 39 reviewer
    skills.
- **It has never changed what a session did.**
  - It ran 11 times in 1,339 transcript files, almost always as part of `make handoff`.
  - It routes 85 of the 113 repo skills, and 3 of the names it routes are not skills at all.
  - It leaves out the skills sessions actually read: `e2e-testing-patterns`, `webapp-testing`,
    `systematic-debugging`, `deploy-checklist`, `subagent-driven-development`.
  - None of the lessons in this document appears in it. For example, it has 0 hits for "money",
    "journey", "deploy" and "cleanup".
- **Proposed redesign:**
  - Route on what the change touches: `make skill-route ITEM=W55` reads the board row, and
    `make skill-route DIFF=origin/main` reads the changed paths.
  - Classes by path and identifier: money, sign-in and session, interface copy and layout, AI
    output and judge, CI, privacy and retention, docs only.
  - Each class adds required roles, reviewers, checks and owner decisions. For example, money adds
    failure modes first, the test designer, the break-it reviewer and a `docs/19` CHG row; the
    interface adds the user-journey tester. The output is a checklist, not 39 names.
  - Tests:
    - a money-path diff must route those roles, and a docs-only diff must not;
    - every `src/` module falls in a class;
    - every routed skill exists.
  - Size: about 150 lines of JSON, 120 of Python and 4 tests.
- **From the owner's other projects:**
  - `citevyn` sizes review by blast radius, T0 to T3 (`citevyn/AGENTS.md:93-107`);
  - `aushraya-ai` gives each skill route a verification column and keeps an append-only log of
    skills actually used (`docs/skill-plan.md`, `docs/skill-execution.md`);
  - `agent-program-supervisor` bounds correction waves and names a stop state
    (`ARCHITECTURE_REDESIGN_REQUIRED`).

## One consistent status (a colleague's feedback, tested)

The feedback: *keep status in its authoritative sources; separate delivery status, product readiness
and historical decisions; check whether the validators still accept unsupported completion claims;
proof of improvement is that a fresh reader reaches one status and a deliberately unsupported claim
fails a check.*

**It applies here, and both halves are true today.** A researcher measured this on a copy of
`origin/main` at `c894f78`.

- **A fresh reader does not reach one status.** There are 8 disagreements. These were re-checked by
  the session:
  - W25, W26, W27 and W29 read DONE on the board while issues #464, #469, #465 and #447 are open;
  - #458 and #459 are open with no board row;
  - board prose says peer critique was switched on in production, while `fly.toml:120` and
    `/status` say it is off;
  - `docs/95` says "Decision: **Go**";
  - all 31 rows in `docs/17` read "Draft".

  Not re-checked: `docs/factory-status.md` says "no-go" and "70 tests", and the router reports "no
  placeholders" while `docs/74` and `docs/116` are still templates.
- **Unsupported completion claims mostly pass.** Of 14 deliberately false claims:
  - 3 were rejected by a real support check. The board refused two hand-typed DONEs, and the
    findings ledger refused a DONE with no proof.
  - 2 were rejected only by chance, through a snapshot or a freshness check.
  - **9 were accepted.** These included:
    - "W55 and W56 merged and in production" in a handoff;
    - an ADR marked "Accepted, owner approved" with no CHG row;
    - FR-001 marked "Verified, passed in production";
    - "STATUS: COMPLETED" in root prompts;
    - the console set to "Released, GA, production-ready";
    - readiness documents set to "Approved, GA";
    - a board row pinned to a made-up `PRESENT` needle.
- **The smallest change that makes both goals true:**
  1. **Separate the three kinds of status.**
     - Delivery: the board plus GitHub.
     - Product readiness: one generated section from `/status` and `/ready`, saying what is built
       versus what is in effect in production.
     - Decisions: `docs/19` and the ADRs.

     Name each in `docs/README.md`. Archive or banner `docs/95`, `docs/factory-status.md`,
     `docs/74` and `docs/116`.
  2. **Completion words need a cited proof.** A test that rejects "merged", "in production",
     "COMPLETED", "Verified", "Approved" or "Accepted" in a handoff, root prompt, `docs/17`,
     `docs/18`, an ADR or a readiness document, unless it cites a PR or commit on `main`, or a CHG
     row for a decision. It follows the findings-ledger rule that already works, and it would have
     rejected 7 of the 9.
  3. **A `PRESENT` needle must have been true at a named commit,** which closes the made-up-needle
     hole.
  4. **Board and GitHub agree:** an advisory job that fails on a DONE row with an open issue, or an
     open issue with no row.
  5. **Fix the 8 disagreements found.** Closing #447, #464, #465 and #469 is the owner's decision.
     #464 and #465 say "left open for the owner to close".
- `agent-program-supervisor` already does this. It has one state machine for delivery, labels for
  how proven each control is (DESIGNED / ENFORCED / MEASURED), and a `NOT_VERIFIED` result that
  cannot support "COMPLETED". `narratwin-ai` rejects "production-ready" claims in pull-request
  bodies.

## Order, and where to do it

Nothing waits on `stackclimb-skills`. Each step is one concern, so each is one pull request,
reviewed twice and pushed once.

1. **"How we work"** (on the branch that holds this document):
   - the process skill `.agents/skills/work-item-delivery/`, with both testers;
   - the item-based route in the skill router, with its tests;
   - the `AGENTS.md` lines;
   - `make handoff` checking that a prompt names the skill.
2. **"One status":**
   - the three kinds of status, each named in `docs/README.md`;
   - the completion-word check;
   - the `PRESENT`-needle fix;
   - the board-to-GitHub job;
   - fixes for the 8 disagreements, with the owner deciding which issues to close.
3. **W55 and W56,** built with the new skill. This is the first real use of it.
4. **Later, each its own item:**
   - one test-suite run per change in CI;
   - the signed-in journey test lane against the real app;
   - pull-request template fields;
   - the constant-sweep script;
   - the status hook.
5. **`stackclimb-skills`, any time:** settle the pl5 work, then take in the generic parts of
   steps 1 and 2.

Steps 1 and 2 are built in a fresh session, because this session's context has been summarised
once. This session's research is all in this document.
