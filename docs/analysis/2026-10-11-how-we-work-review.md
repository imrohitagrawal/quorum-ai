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

**Layer 1: skills** (reusable across all repos, in `stackclimb-skills`):

- `work-package-protocol` covers one item; `multi-work-package-orchestration` covers several.
- Fold in what was learned since August, as generic rules:
  - a test designer separate from the builder;
  - one lens that runs commands;
  - a browser run of the real user journeys;
  - limits on workflow size;
  - disk cleanup;
  - batching questions to the owner;
  - every wait has a time limit;
  - status shown before the owner has to ask.
- Settle the four contradictions:
  - **merges:** the main orchestrator only, under the approval given in the prompt;
  - **reviewers:** 3 lenses plus Codex;
  - **rounds:** exactly 2, plus one narrow re-check of each fix;
  - **workflows:** at most 8 agents.
- Install the latest version, including the multi-item skill.

**Layer 2: the repo profile** (`AGENTS.md`, quorum-ai only). Add one short section,
"How every item is built", that:

- names the two skills and says they apply to every item;
- holds the quorum-specific parts:
  - commands, gates and e2e flags;
  - Codex with `--cwd`, the close-guard and the deploy checks;
  - `docs/19` for decisions;
  - `docs/65` needles;
  - the live-session check.
- Archive LOOP and the template, or change them to point at the skills. Keep R2 where it is,
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

## Order, and where to do it

- **This session:** the research and this document only. Its context has been summarised once, and
  every change below is its own pull request with its own review.
- **Next session 1 (in `stackclimb-skills`):**
  - decide what happens to the unfinished pl5 work;
  - fold Layer 1 into the two skills;
  - install the latest version.
- **Next session 2 (quorum-ai):**
  - the `AGENTS.md` section and check 1;
  - the first real use of the updated skills, so it doubles as a trial.
- **Next session 3:** W55 and W56, with a short prompt that names the skills.
- **Later, each its own item:** checks 2–6.
