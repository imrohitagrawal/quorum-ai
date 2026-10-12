> **Archived 2026-10-13** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Edits: the Codex script's plugin path is written as `<plugin scripts folder>` on 1 line(s), so the repository's citation check does not read it as a repository file.

# Session prompt: package A ("how we work") and package B ("one status")

Written by the 2026-10-11 session (transcript `c512313e`). This file is the session's wording, and
by the session's account it was reviewed by four read-only agents before the owner received it.

The owner's own words are the `type: user` records in that transcript whose content is a plain
string. Records that begin `<` or `Another Claude session sent a message` are tool output or agent
reports, NOT the owner's words.

## Read first

1. `docs/README.md`.
2. The plan and its evidence: `docs/analysis/2026-10-11-how-we-work-review.md`, on branch
   `docs/how-we-work-review` in worktree `../quorum-ai-wt-howwework`. Read the whole file. The
   section "The plan" is the work, and the appendix lists the 14 planted claims.
3. `docs/analysis/2026-10-11-session-handoff.md`.
4. `AGENTS.md`, `configs/skill-router.json`, `scripts/skill_router.py`, `scripts/factory_next.py`,
   `scripts/validate_publishing_backbone.py`, `scripts/session_handoff.py`,
   `scripts/check_open_work.py`, and ADR-0045.
5. Check `docs/19` and the owner logs before asking anything.

## Owner decisions already given (2026-10-11, transcript `c512313e`)

Record them as the next CHG row in `docs/19` (CHG-040 if still free) in package A's pull request.
Quote the owner's words exactly:

- **10:49:02Z:**
  - *"i more learning since August is that there should be a dedicated Test designer/engineer who
    would test the application from User expectations and behaviour."*
  - The same message asked *"Let us do the reviews finally, and then we can push at one shot. What
    do you say?"* That was a question. The session proposed pushing each pull request once, after
    its reviews.
- **11:35:22Z:** *"Yes, go ahead and close the four issues if they are already done. Do ensure that
  you capture, read each and everything that is mentioned in the issue, and check the application
  behavior by executing it and seeing that these are fixed. Then go ahead and close them."* #447,
  #464, #465 and #469 were checked and closed on 2026-10-11, and each carries an evidence comment.
- **11:46:45Z:** *"yes"*. It answered two questions:
  - approve the plan, as committed at `e5fc79d` (the appendix of 14 claims was added after, in
    `daed304`), and confirm the four points under package A:
    - only the main orchestrator merges;
    - 3 reviewer lenses plus Codex;
    - exactly 2 review rounds, plus a narrow re-check of each fix;
    - at most 8 agents in any workflow;
  - may the session write this prompt.
- **11:24:07Z:** *"the agent-program-supervisor is still work-in-progress, so it should not be
  blindly trusted."* Ideas from the owner's other projects are leads to build and test, not proven
  practice.
- **05:48:33Z:** workflows should be sized *"as per the need and the work, and not just blindly
  call out a large workflow"*.

Never record an approval the owner did not give.

## Ask the owner first, in ONE batch, at the start of the session

Use the question tool, with your recommendation marked on each. Ask at the start, so the answers
are ready when they are needed.

1. **Package B:** which of `docs/17`, `docs/18`, `docs/95`, `docs/factory-status.md`, `docs/74` and
   `docs/116` are archived or bannered, and which are kept current.
2. **Package B:** the wording of the readiness statement.
3. **Package A:** for each prompt file at the repo root, archive it, point it at the skill, or leave
   it exempt. List every file; there were 12 on 2026-10-11, tracked and untracked. Leave out this
   file and `CONTINUE-W55-W56-PROMPT.md`, which "End of session" already handles.
   `R2-S2-S4-ULTRACODE-PROMPT.md` stays where it is, marked as an example, because
   `tests/test_ultracode_prompt_enforcement_contract.py` pins it. Never delete an untracked file;
   archiving means copying it into `docs/archive/` and committing it.

If the owner asks for advice, give it and ask again. **If there is no answer by the time a step
needs it:**

- build every part that needs no decision;
- record the open question in the handoff;
- do not guess.

## What to build

Follow "The plan", packages A and B only, in this order.

**Package A, "how we work":** on the existing branch `docs/how-we-work-review`. Merge `main` into
it first.

1. **The process skill:** `.agents/skills/work-item-delivery/SKILL.md`, with every role and rule the
   plan lists.
   - **The review round has 3 lenses plus Codex:** break-it, prose audit against the transcript,
     and falsification. This is the session's reading of the owner's "3 reviewer lenses plus
     Codex".
   - **The completeness critic** runs once, after round 2, to ask which questions and kinds of
     evidence went unused.
   - **Make it load.** The Skill tool lists skills from `.claude/skills/`, which is gitignored and
     holds only local links (a fresh worktree has none), so a new skill under `.agents/skills/` is
     not listed. `AGENTS.md` must say: "before any work item, read
     `.agents/skills/work-item-delivery/SKILL.md`". A test checks that line exists.
   - **Every path the skill names must exist,** because `tests/unit/test_cited_paths_resolve.py`
     reads `.agents/skills/`.
2. **The skill router by item or diff.**
   - Add a NEW function for `make skill-route ITEM=…` and `DIFF=…`.
   - `route()` with no arguments must keep its output byte-for-byte: `scripts/session_handoff.py`
     and `scripts/factory_next.py` (which writes `docs/00`) call it.
     `scripts/validate_publishing_backbone.py` reads `configs/skill-router.json` directly and fails
     if the `study-publish-share` phase is missing.
   - Remove the 3 routed names that are not skills.
   - Run `make next`, `make validate` and `make handoff` before and after, and show their output
     unchanged except where intended.
3. **The `AGENTS.md` lines** from the plan, including the "read the skill" line above.
4. **`make handoff` and prompt files:**
   - it lists leftover worktrees, branches and scratch files;
   - a check refuses a root `*PROMPT*.md` file, tracked or untracked, that does not name the skill,
     except files the owner exempted by name in question 3.
   - ADR-0045 says the handoff degrades per value rather than failing outright. Write an ADR that
     records how this check relates to it. For example, a separate `make prompt-check` that fails,
     with `make handoff` showing its result.
5. **The root prompt files,** as the owner answers question 3.
6. **This review document,** and the CHG row above.

**Package B, "one status":** a new worktree from `main` once A is merged.

1. **The three status homes,** named in `docs/README.md`, with readiness generated from `/status`
   and `/ready`.
2. **The stale readiness documents,** as the owner answers question 1.
3. **The completion-word check.**
   - It applies only to files changed after a named cut-off commit. 153 of 155 ADRs contain
     "Accepted", and all 24 narrative handoffs say "merged" or "in production".
   - Name the commit, and state in the pull request how many files are exempt.
4. **A `PRESENT` needle must have been true at a named commit.** Existing rows that use `PRESENT`
   (10 on 2026-10-11) keep working. `scripts/check_open_work.py` is used by every session, so change it
   narrowly.
5. **The board-to-GitHub check** in `make handoff`. It needs `gh`, so it reports rather than
   blocking when offline.
6. **The open disagreements** listed in the plan.

## Proofs: show each failing before it passes

**Package A:**

- a root prompt file without the skill line makes the prompt check fail;
- a money diff routed without the failure-mode role turns a test red. Use literal paths from real
  money fixes, such as the files commit `ef4a716` touched, never paths read from the class map;
- a docs-only diff gets no money roles;
- every routed skill name exists, and every `src/` module falls in a class;
- the `AGENTS.md` line that makes the skill load exists.

**Package B:**

- **The 14 planted claims in the review document's appendix become a test.**
  - Plant them in a temporary copy, never in the tree.
  - Each in-scope claim must be rejected by a support check, with its expected message. A snapshot
    or freshness check does not count (I7a and I7b today).
  - A TRUE claim that cites a real merged pull request must be accepted.
  - Say whether I3 is in scope and why. If it is ruled out, the test asserts it is accepted and
    names the documented limit.
- **The fresh-reader test, which is the user-journey tester's job for this package:**
  - **Before building:** write the answers the owner expects to "what is live, what is open, is it
    ready?". Save the question word for word.
  - **On `main`:** run one agent started without this project's memory
    (`claude -p --safe-mode`). It is expected to give inconsistent answers.
  - **After package B:** run it again. It must match the expected answers.

## Roles, while the skill does not exist yet

This session builds the skill, so it follows the plan's roles directly:

- **You** are the main orchestrator, and the only one who merges.
- **Failure modes and an ADR** come first for each decision.
- **The test designer** writes failing tests, records the verbatim failure output, and gives each
  test one line saying what turns it red. Before the builder starts, move any reference
  implementation the designer wrote out of the builder's reach.
- **The user-journey tester** writes the owner's expectations before the build and checks them
  after. For package B, that is the fresh-reader test. Neither package changes a page, so there is
  no browser run unless a change touches one; say so in the pull request.
- **The builder** may not edit the tests. Check with
  `git diff <test designer's commit> HEAD -- <the test designer's files>`. A fixer may ADD a new
  regression test file.
- **Each review round** has the 3 lenses plus Codex.
  - **Codex:**
    ```bash
    export PATH="$HOME/.local/bin:$PATH"
    node ~/.claude/plugins/cache/openai-codex/codex/1.0.6/<plugin scripts folder>/codex-companion.mjs \
      adversarial-review --wait --cwd <the PR's worktree> --base origin/main --scope branch "<focus>"
    ```
    Without `--cwd`, it reviews the main checkout, an empty diff. The `codex:rescue` skill is also
    acceptable, but it too must review the pull request's worktree.
  - **Every reviewer prompt says:**
    - IN CAPITALS: DO NOT WRITE, EDIT, `git checkout`, `git stash` OR `sed -i` ANYTHING;
    - work in your own `git archive HEAD` copy, with a unique folder prefix and plain `mkdir`;
    - reuse the main `.venv`, and delete only the folders you created.
- **After round 2,** each fix gets one narrow re-check, then the completeness critic runs.
- **One fixer at a time** applies only findings you reproduced yourself first.
- **Workflows:** only for a review round, at most 8 agents, sized to the change. Use the Agent tool
  for single roles.

## Approvals

Sending this prompt approves push, pull request, squash-merge (through `make close-guard`, with
`EXPECT_CLOSE=""` unless an issue is meant to close) and deploy for three pull requests:

- package A;
- package B;
- the end-of-session handoff (docs only).

Each needs every required gate green and every reproduced blocker fixed.

- **Push once:** after round 2's fixes, their re-checks and the completeness critic. Not during the
  reviews.
- **A further push is allowed only** to fix a failing required check or a reproduced blocker. Each
  gets a narrow re-check.
- **Finish the pull-request body before the last push.** Editing it re-runs CI.

Nothing else is approved.

## Size

The plan sizes the router at about 150 lines of JSON, 120 lines of Python and 4 tests. If either
package's code, not counting tests and docs, grows past about twice the plan's size, stop and tell
the owner before going on. Do not add advisory work.

## Rules

- **No mutmut on this Mac (board row W44).** No paid calls. Never read or print `.env` values.
- **Before starting:**
  - check for other live sessions (transcript last-write times, `ps`, `git worktree list`);
  - the session that wrote this file (`c512313e`) should have finished: confirm its transcript has
    stopped changing;
  - if another session owns a worktree you need, stop and say so.
- **Gates:**
  - run every required gate yourself (AGENTS.md rule 14), one at a time (rules 9a and 15), reading
    exit codes without a pipe (rule 13f);
  - commit before `make diff-cover`;
  - start background runs with the tool's background mode, never a shell `&`;
  - never edit the tree while a gate or reviewer reads it.
- **New folders:** creating `docs/archive/2026-10/` may need the docs map regenerated. Run
  `make validate` and follow what it says.
- **CI outages:** if Actions jobs are cancelled with "not acquired by Runner", check githubstatus
  and re-run the failed jobs.
- **Production checks:** the Deploy job for the merge commit succeeded (read every Deploy job,
  because one merge fires several runs), and `/status` `build_sha` matches the merge.
- **Disk:** run `df -h .` before making reviewer copies; the disk was 91% full (20 GiB free) on
  2026-10-11.
- **Status and waits:** report status before the owner has to ask, and give every wait a time
  limit.
- **Plain English:** in every report, short sentences and an example where it helps.
- **Context:** check it before package A's round 2, and again after A merges. If it is low, write a
  prompt file for the remaining work in this same format, and end the session cleanly.

## End of session

1. **Write the next prompt file** for W55 and W56.
   - Copy the existing untracked `CONTINUE-W55-W56-PROMPT.md` to `docs/archive/2026-10/` first;
     it predates the skill.
   - Then write the new one. It should be short:
     - say every item is built by `.agents/skills/work-item-delivery`;
     - list W55 then W56 and the decisions to read (CHG-029 (d), CHG-033 (c), and `docs/48`);
     - state the approvals: W55, W56 and a docs-only handoff pull request.
   - The prompt check must accept it.
2. **Run `make handoff`,** and write a short narrative handoff in
   `docs/analysis/<date>-session-handoff.md`.
3. **Archive this file** in the handoff pull request: copy it into `docs/archive/2026-10/`, commit,
   and after the merge delete the root copy by name.
4. **Clean up.**
   - Delete, by name, every reviewer copy, scratch file and temporary file the session created.
   - Remove merged worktrees, then their branches, local and remote.
   - Show `df -h .` before and after.
5. **Finish with the closing status block.** Say whether each pull request is pushed, merged and
   running in production, and keep what you ran separate from what an agent reported.
