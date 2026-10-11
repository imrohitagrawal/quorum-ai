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
    skills actually used (its own `skill-plan.md` and `skill-execution.md`, in that repository's docs folder);
  - `agent-program-supervisor` (work in progress; read from a stale local branch) designs bounded
    correction waves with a named stop state (`ARCHITECTURE_REDESIGN_REQUIRED`). That is an idea to
    test, not a proven practice.

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
- **Ideas only, not proven practice:**
  - **`agent-program-supervisor`** designs the same split: a delivery state machine, labels for how
    proven each control is, and a `NOT_VERIFIED` result that cannot support "COMPLETED".
    - It is work in progress, and its own traceability table marks 7 controls as `DESIGNED`, meaning
      the runtime is not implemented.
    - The researcher also read a local branch (`governance-warning-strict-contracts`, last commit
      2026-08-20), while GitHub `main` is at "M1 V10" (2026-10-11).
    - Its audit of quorum-ai is that project's claim. Here it agrees with our own measurements, but
      that does not make it evidence.
  - **`narratwin-ai`** rejects "production-ready" claims in pull-request bodies. The line numbers
    came from a researcher's sub-agent and were not re-checked.

  Build and test our own versions; do not copy either project's design as if it were proven.

## Why this session missed the status problem the colleague found

The colleague's point (status that disagrees with itself, and checks that accept false "done"
claims) was not in this document until they raised it. Evidence for it was already in hand:

- the four board rows marked DONE with open issues;
- the "STATUS: COMPLETED" line in `R2-S2-S4`;
- the 12 handoffs that called production "unreachable".

Each was filed as a separate fact, not as one class of problem.

**Why:**

1. **The research asked only the questions the session was given:** practices, repeated work,
   slowness and owner corrections. Nobody asked "are the things we report true, and would a false
   one be caught?"
2. **Every lens read and measured. None experimented.** The colleague's test is a falsification:
   plant a false claim and see whether a check rejects it. It took one researcher about 20 minutes
   to show that 9 of 14 false claims pass.
3. **The session audits other things more readily than its own output.** Handoffs, board rows and
   status reports are what sessions write, so their accuracy was the least examined.
4. **No completeness critic ran.** No final pass asked "which question, and which kind of evidence,
   is missing?"

**How to avoid it** (goes into the process skill):

- **Every research or review fan-out includes:**
  - a falsification lens that plants one false claim, or deletes one guard, and checks whether
    anything goes red;
  - a completeness critic that lists the questions and kinds of evidence not used.
- **When one instance of a problem is found, ask where else the same class occurs before filing
  the instance.**
- **Get outside eyes on any analysis meant to change how we work:** a reviewer outside the session,
  or a session started clean of this project's memory.
- **Evidence from another project is a lead, not proof.** Check its maturity and branch first.

## The plan

Nothing here waits on `stackclimb-skills`. Each package is one concern and one pull request,
reviewed twice and pushed once, then merged and checked in production.

### Package A: "How we work" (pull request 1)

**Goal:** every session follows one process without anyone retyping it.

**What gets built:**

1. **The process skill:** `.agents/skills/work-item-delivery/SKILL.md`.
   - **Roles:**
     - main orchestrator, the only one who merges;
     - test designer;
     - user-journey tester;
     - builder, who may not edit the tests;
     - break-it reviewer;
     - prose auditor working against the transcript;
     - Codex, run against the pull request's worktree;
     - a falsification lens;
     - a completeness critic;
     - one fixer at a time.
   - **The rules it states:**
     - two review rounds plus a narrow re-check of each fix;
     - at most 8 agents in a workflow;
     - failure modes first for money, sign-in and safety;
     - check `docs/19` before asking the owner anything, and batch the questions;
     - record decisions as CHG rows, and never record an approval that was not given;
     - production checks: the Deploy job, `build_sha`, and something visible;
     - cleanup with `df -h .` before and after;
     - status reported before the owner has to ask;
     - a time limit on every wait;
     - the check for other live sessions;
     - a handoff when context runs low.
   - **The four contradictions it settles:** who merges, how many reviewers, how many rounds, and
     how big a workflow may be.
2. **The skill router routes by the item or the diff:**
   - `make skill-route ITEM=W55` or `DIFF=origin/main`;
   - classes are money, sign-in and session, interface, AI output and judge, CI, privacy and
     retention, and docs only. Each class adds its roles, checks and owner decisions;
   - the 3 routed names that are not skills are removed.
3. **`AGENTS.md`:** a few lines saying every item is built by the skill, plus the rules it lacks:
   - `docs/19` for decisions;
   - `docs/65` needles;
   - the live-session check;
   - cleanup.
4. **`make handoff`:**
   - fails when a root prompt file does not name the skill;
   - lists leftover worktrees, branches and scratch files.
5. **Older files:** `AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md` and the template either point at the
   skill or move to the archive. `R2-S2-S4-ULTRACODE-PROMPT.md` stays, marked as an example,
   because a test pins it.
6. **This review document** goes in the same pull request.

**How we know it works** (each check is a test that must first be shown failing):

- a root prompt file without the skill line makes `make handoff` fail;
- a diff touching money that is routed without the failure-mode role turns a test red, and a
  docs-only diff gets no money roles;
- every routed skill name exists, and every `src/` module falls in a class.

**Owner decisions:** confirm the four settled points (main orchestrator merges; 3 lenses plus Codex;
exactly 2 rounds; at most 8 agents).

### Package B: "One status" (pull request 2)

**Goal:** a fresh reader reaches one status, and a false "done" fails a check.

**What gets built:**

1. **Three kinds of status, each with one home, named in `docs/README.md`:**
   - **delivery:** the board plus GitHub;
   - **product readiness:** a section generated from `/status` and `/ready`, saying what is
     built and what is in effect in production;
   - **decisions:** `docs/19` and the ADRs.
2. **Stale readiness documents:** `docs/95`, `docs/factory-status.md`, `docs/74` and `docs/116` go
   to the archive or get a banner. The status columns in `docs/17` and `docs/18` either become
   true or are marked historical.
3. **A completion-word check.** "merged", "in production", "COMPLETED", "Verified", "Approved" or
   "Accepted" in a handoff, root prompt, `docs/17`, `docs/18`, an ADR or a readiness document must
   cite a PR or commit on `main`, or a CHG row.
4. **A `PRESENT` needle must have been true at a named commit.** This closes the made-up-needle
   hole.
5. **Board and GitHub agree:** a check in `make handoff` (it needs `gh`) that fails on a DONE row
   with an open issue, or an open issue with no row.
6. **The disagreements still open:**
   - give #458 and #459 board rows;
   - correct the peer-critique prose;
   - correct the requirement statuses;
   - add `docs/74` and `docs/116` to the router's placeholder list;
   - put the advisory leftovers from the 2026-10-11 handoff on the board.

   Issues #447, #464, #465 and #469 were checked and closed on 2026-10-11.

**How we know it works:**

- the 14 false claims from the colleague's test are committed as a test, and every one is
  rejected. Today 9 of 14 pass;
- one agent started without this project's memory answers "what is live, what is open, is it
  ready?" from the repository, and gets one consistent answer.

**Owner decisions:**

- which of `docs/17`, `docs/18` and `docs/95` are archived and which are kept current;
- the wording of the readiness statement.

### Package C: W55 and W56 (pull requests 3 and 4)

Built under the skill from package A: the first real use of it. The scope is as in
`CONTINUE-W55-W56-PROMPT.md`, rewritten as a short prompt that names the skill.

### Package D: later, each its own pull request, in this order

1. **One test-suite run per change in CI.** The suite runs up to four times per change today, and
   this is the largest time saving. Measure first how `diff-cover` runs the suite.
2. **Signed-in browser tests of the owner's journeys against the real app,** written from journey
   statements the owner approves. This was proposed by the 2026-09-29 engineering review.
3. **Large web pages, found 2026-10-11.** A page over 256 KiB whose server states its size is
   refused and never read. For example, Wikipedia's Photosynthesis article (970,143 bytes) stated
   its size on 6 of 6 requests. Decide whether to read the first 256 KiB or keep refusing.
4. **Pull-request template fields with a CI check:**
   - the premise;
   - review rounds;
   - the source of every number;
   - the CHG row;
   - for a bug fix, who found it.
5. **A search script before changing a constant.**
6. **A status line or stop hook listing background jobs.** This changes the owner's settings, so
   the owner decides.
7. **The advisory leftovers in the 2026-10-11 handoff:**
   - the 1,024-open-files limit in the PDF reader's exit wait;
   - `cffi` and `pycparser` unpinned in the image;
   - the flaky signed-in browser tests;
   - the mutation job's time budget.

### Package E: `stackclimb-skills`, any time, separately

Settle the 8 unfinished pl5 worktrees. Then take the generic parts of packages A and B into
`work-package-protocol` and `multi-work-package-orchestration`, and install the latest version.

### Sessions

| Session | Repository | Work | Starts when |
|---|---|---|---|
| 1 | quorum-ai | Packages A then B (two pull requests). If context runs low after A, hand off and start a session for B | now |
| 2 | quorum-ai | Package C | A merged |
| 3 | stackclimb-skills | Package E | any time |

Each session gets a prompt file the owner starts with one line. The prompt states the approvals:
push, merge and deploy for the named pull requests only.

## Appendix: the 14 false completion claims (the colleague's test)

Each claim was planted, one at a time, in a copy of `origin/main` at `c894f78`. Then `make validate`
and the status test files were run. This was measured by a read-only researcher, and the session
has not re-run it. Package B commits these as a test in which every one must be rejected.

| # | Planted claim | Checked by | Result on 2026-10-11 |
|---|---|---|---|
| I1 | W28's State changed from PENDING to DONE on the board | `check_open_work.py` | rejected |
| I2 | Unpinned W35 set to DONE | `check_open_work.py` | rejected |
| I3 | W28's claim word flipped from PRESENT to ABSENT, plus DONE | `check_open_work.py` | accepted (a limit the board already documents) |
| I4 | W55 pinned to a made-up `PRESENT … def purge_spend_keys_older_than(`, with the unpinned count edited | `check_open_work.py` | accepted |
| I5 | Narrative handoff says "W55 and W56 merged in #558/#559, in production, release-ready" | `make validate` and the tests | accepted |
| I6 | Mechanical handoff says "All board rows are DONE … Release 1 is complete" | `test_session_handoff_claims` | accepted |
| I7a | ADR-0121 changed from PROPOSED to Accepted, index regenerated | ADR tests | rejected, but only by a snapshot test that a real acceptance would also fail |
| I7b | The same change, index not regenerated | `generate_adr_index --check` | rejected, by a freshness check, not a support check |
| I7c | A new ADR-0159 "Accepted … owner approved", with no CHG row | `make validate`, ADR and doc tests | accepted |
| I8 | FR-001 "Verified, passed in production"; `docs/18` "CI passed"; AC-001 "Status: PASSED" | `fr-completeness`, `validate_traceability` | accepted |
| I9 | "STATUS: COMPLETED" added to two root prompts | all of the above | accepted |
| I10 | The console phase set to "Released, GA, production-ready" | console tests | accepted |
| I11 | Findings-ledger row RB-6 changed from BUILD to DONE with no proof | `test_findings_ledger_consistency` | rejected |
| I12 | `docs/74` all "Passed"; `docs/116` G7 "Approved, GA"; `docs/95` "GA, live for all users" | all of the above | accepted |

Rejected by a real support check: I1, I2 and I11. Rejected only incidentally: I7a and I7b.
Accepted: I3, I4, I5, I6, I7c, I8, I9, I10 and I12.
