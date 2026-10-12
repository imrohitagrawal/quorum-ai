> **Archived 2026-10-13** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Edits: the Codex script's plugin path is written as `<plugin scripts folder>` on 1 line(s), so the repository's citation check does not read it as a repository file.

# Session prompt: W55 and W56

Written by the 2026-10-11 session (transcript `c512313e`). It is based on the prompt the owner
pasted on 2026-10-06 (the `type: user` record at 2026-10-06T15:03:33Z), which an earlier session
wrote at the owner's request. This file is the session's wording. The owner's own decisions are
the ones quoted in `docs/19`.

## Read first

1. `docs/README.md`.
2. `docs/analysis/2026-10-11-session-handoff.md`.
3. `docs/65-open-work.md`, rows W55 and W56.
4. `docs/19`: CHG-029 (d) and CHG-033 (c).
5. `docs/adr/0144-anonymous-spend-is-counted-per-network.md`, decision 5.
6. `docs/48-data-retention.md`, the rows "The spend key of a signed-in account" and "The spend
   key of an anonymous visitor's network". Both items change the second row.

Check `docs/19` and the owner logs before asking anything.

## What to build

Build these in order. Each gets its own pull request, merged and verified in production before
the next starts.

1. **W55:** wipe the anonymous network's spend key from cost-ledger rows older than 48 hours.
   - Rows and amounts stay.
   - The owner decided 48 hours in CHG-033 (c).
   - Money rules apply (AGENTS.md rule 16e): list the failure modes before any code.
   - Update the `docs/48` row and the board row in the same pull request.
2. **W56:** stop sending the anonymous network's spend key to Sentry in the same event as the
   visitor's address. Today it goes as `account_id` beside `client_ip`, in the event sent when
   a run is switched to simulated answers because the site's daily spend limit was reached
   (`src/product_app/costs.py`, the `cost_guardrail_degraded_to_simulation` branch).
   - The owner's instruction is to stop sending the network key there, so the key is the field
     that goes.
   - Scope is the anonymous network key. What Sentry gets for a signed-in account is a separate,
     still-open row in `docs/48`.
   - If the fix cannot leave signed-in accounts unchanged, ask the owner at the START of the
     session, so the answer is ready when W55 is done:
     - use the question tool with 2 or 3 options and your recommendation marked;
     - if the owner asks for advice, give it and ask again;
     - record the answer as a new CHG row in `docs/19`.
   - Update the `docs/48` row and the board row in the same pull request.

Sending this prompt approves push, pull request, squash-merge (through `make close-guard`) and
deploy for three pull requests: W55, W56 and the end-of-session handoff (docs only). Each merge
needs every required gate green and every reproduced blocker fixed. No other pull request is
approved.

## Roles, for each pull request

You are the main orchestrator. You alone merge and deploy. There is no layer of
sub-orchestrators. The 2026-10-11 session recommended this: W55 must be in production before W56
starts, so nothing runs in parallel except the reviewers, and merge decisions must rest on
commands you ran yourself. Each role below is one agent you start directly.

- **You, first:**
  - write the failure modes in `docs/analysis/`;
  - write the ADR, then regenerate the index with `python3 scripts/generate_adr_index.py`.
- **Test designer (one agent):**
  - writes the acceptance tests and commits them;
  - shows them failing, with the verbatim failure output;
  - gives each test one line saying what change turns it red.
  - Before the builder starts, move any reference implementation the designer wrote out of the
    builder's reach: the scratchpad, the worktree, `/tmp`, or anywhere else it wrote one.
- **Builder (one agent):**
  - makes the tests pass and must not edit tests.
  - Check it: `git diff <test designer's commit> HEAD -- <the test designer's test files>`
    prints nothing. Re-run this after every fix.
  - Later fixes may ADD a new regression test file, but never edit the test designer's files.
- **Reviewers: exactly two rounds, each with the same four reviewers:**
  - **Break-it reviewer:** tries to make the change fail, and reports only failures it actually
    produced.
  - **Prose audit against the transcript:**
    - for every number, superlative and claim about a cause in the comments, commits, ADR and
      PR body, it names the command that produces it, or marks it UNVERIFIED;
    - it checks every quoted owner decision against a `type: user` record.
  - **Codex:** run it yourself from the main shell (from subagents it sometimes reports "not
    installed"), pointed at the pull request's worktree:
    ```bash
    export PATH="$HOME/.local/bin:$PATH"
    node ~/.claude/plugins/cache/openai-codex/codex/1.0.6/<plugin scripts folder>/codex-companion.mjs \
      adversarial-review --cwd <the PR worktree> --base origin/main --scope branch "<focus>"
    ```
    Without `--cwd`, it reviews the main checkout, an empty diff, and reports nothing.
  - **Browser run:**
    - walks the journeys in `docs/113-user-journeys.md` that the change touches, signed in
      (through the local Google stub the signed-in e2e specs use) and anonymous;
    - uses the local overrides from AGENTS.md rule 13
      (`SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600
      ANONYMOUS_SPEND_PER_SESSION_OVERRIDE=true`). Without them, the third anonymous page load
      is refused and every check after it fails for no real reason.
- **Fixer (one agent at a time):** applies only findings you reproduced yourself first.
- **After round 2:**
  - each fix gets one narrow re-check: one agent re-runs the case that failed;
  - if a reproduced blocker is still open after that, do not merge. List it in the handoff
    and end the session.
- **You, before merging:**
  - run every required gate yourself: AGENTS.md rule 14 lists them;
  - run them one at a time (rule 15), reading each exit code without a pipe (rule 13f);
  - then merge, verify production and clean up, in the order of rule 18a.

**Every reviewer prompt says:**
- IN CAPITALS: DO NOT WRITE, EDIT, `git checkout`, `git stash` OR `sed -i` ANYTHING;
- work in your own `git archive HEAD` copy, with a unique folder prefix and plain `mkdir`;
- reuse the main `.venv`, and delete only the folders you created.

## How many agents

- **Test designer, builder and fixer:** use the Agent tool, one agent at a time. Only one agent
  writes at a time.
- **Workflows:** use one only for a review round, never for building.
  - Use one only when the change to `src/` and `tests/` together is over about 100 lines.
    Otherwise, start the three agent reviewers with the Agent tool.
  - A workflow gets **at most 8 agents**: the break-it, prose and browser reviewers, plus at most
    5 agents that each try to disprove one blocker finding.
  - Check any further blocker findings yourself, including Codex's, rather than adding agents.
  - Never start a workflow for a step one agent can do.
- **Ultracode** is not needed for two small changes. Do not switch it on.

## Rules

- Do not run mutmut on this Mac (board row W44).
- No paid calls. Neither item needs one.
- Never read or print `.env` values.
- **Before starting:** check for other live sessions (transcript times, `ps`,
  `git worktree list`). The session that wrote this file (`c512313e`) has finished. If another
  session has a worktree or branch for W55 or W56, stop and say so; do not build around it.
- **Branches:** use a dedicated worktree for each pull request, and merge `main` into it before
  starting.
- **Background gate runs:** start them with the tool's background mode, never a shell `&`. zsh
  runs `&` jobs at lower priority, which fails the test that checks the PDF reader's priority.
- **Commits and diff-cover:** commit before `make diff-cover`.
- **Don't change files while they're being read:** never edit the tree while a gate or a
  reviewer is reading it.
- **CI outages:** if GitHub Actions jobs are cancelled with "not acquired by Runner", check
  githubstatus and re-run the failed jobs. It is not a code failure.
- **Production checks:**
  - The Deploy job for the merge commit succeeded. Read each Deploy job, because one merge fires
    several runs.
  - `/status` `build_sha` matches the merge.
  - **W55:** inside the machine (`fly ssh console`), read-only, count the anonymous ledger rows
    older than 48 hours that still hold a key. Print the count only, never a key, and expect 0
    once the wipe has run.
  - **W56:** production cannot show it for free. Say so in the closing block and name the test
    that proves it.
- **Disk:** run `df -h .` before making reviewer copies; the disk was 90% full on 2026-10-11.

## End of session

1. Run `make handoff`, and write a short narrative handoff in
   `docs/analysis/<date>-session-handoff.md`.
2. In the handoff pull request, archive this file: it is untracked and only in the main
   checkout. Create `docs/archive/2026-10/`, copy this file there from the main checkout, commit
   it, and after the merge delete the root copy by name.
3. Clean up. The owner asked (2026-10-10T18:53:25Z) that agents leave nothing behind that uses
   disk space.
   - Delete, by name, every reviewer copy, agent scratch file and temporary file this session
     created.
   - Remove merged worktrees, then their branches, local and remote.
   - Show `df -h .` before and after, and list what was deleted.
4. Finish with the closing status block.
   - Say whether each item is pushed, merged and running in production.
   - Keep what you ran separate from what an agent reported.
