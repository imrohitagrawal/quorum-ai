# ADR-0169: The next-session prompt is copied from a template, checked by name and sections, committed, and its paste line printed

## Status

Accepted — 2026-10-16, building CHG-052 (the owner's "rule, not a habit"). It extends ADR-0160 and
leaves ADR-0043 and ADR-0045 in force. The mechanism is the session's design. Codex reviewed the
plan before the builder wrote any code. The owner's "yes" covered the template and the name and
section check; the hook, the committed prompt checked by CI and the printed paste line are the
session's additions (CHG-052).

## Context

On 2026-10-15 (UTC) a session wrote the next prompt from memory. It carried the `**Process:**` line, so
`make prompt-check` let it through, but it had another shape and another name, and it restated a plan
that already lived in a handoff. The owner asked how to make the prompt a rule rather than a habit,
and whether the paste line should come from a rule or a skill (CHG-052).

Four facts shaped the design:

| Fact | Evidence |
|---|---|
| `.claude/` is untracked on purpose | `.gitignore:28`; ADR-0043 |
| `make handoff` must still write its file when one value fails | ADR-0045; ADR-0160 rejected `make handoff` exiting 1 |
| CI already checks tracked root prompts | ADR-0160, decision 4 (`tests/unit/test_root_prompt_check.py`) |
| A hook matcher selects tool names, so a `Write` hook never sees a prompt written by a shell command | Codex's plan review, 2026-10-16, citing the Claude Code hook documentation |

## Decision

1. **A template**, `.agents/skills/work-item-delivery/prompt-template.md`, in the shape of
   `CONTINUE-PARKED-WORK-W28-W70-PROMPT.md`: a title, "Written by", the Process line, and four level-2
   sections, `Read first`, `The items, in order`, `Approvals`, `End of session`. The skill's handoff
   contract says to copy it.
2. **`make prompt-check` also refuses** a non-exempt root prompt that lacks any of the four sections as
   a visible top-level `##` heading, or whose name does not fully match
   `CONTINUE-[A-Z0-9]+(-[A-Z0-9]+)*-W[0-9]+(-W[0-9]+)*-PROMPT.md`: capitals, digits and dashes, with at
   least one board row. A heading in a code block, a comment, a list or a block quote does not count.
3. **A hook, on this machine.** `scripts/prompt_write_hook.py` runs after every `Write`, `Edit`,
   `MultiEdit`, `NotebookEdit` and `Bash` call, under both `PostToolUse` and `PostToolUseFailure`: a
   shell command that writes a prompt and then exits non-zero sends only the failure event. It does
   not trust the tool's file path: it lists the root of every checkout of this repository
   (`git worktree list --porcelain`), compares the SHA-256 digest of each root prompt's content with
   the digest it saved last, and runs the check on any root whose prompts changed, were added or were
   removed. It re-checks every root while the last result failed, and on its first run. On a failure
   it returns a `block` decision, which shows the agent the problems; for a failure event, which has
   no block decision, it returns the same problems as context for the agent. The hook's logic is tracked and tested; the one settings entry
   that calls it lives in the untracked `.claude/settings.json`, as ADR-0043 requires, and
   `python scripts/prompt_write_hook.py --install <checkout>` adds it under both events.
   `--check-installed` also needs the checkout's `.venv/bin/python`, which the entry runs. `make handoff` says whether the
   checkout it runs in has it. W81's deny rules go in the same file as a separate entry.
4. **The handoff pull request commits the next prompt at the root**, so CI's check of tracked prompts
   refuses a bad one whichever agent wrote it. The session that runs it moves it to
   `docs/archive/<month>/`.
5. **`make handoff` prints the paste line**, `Read <file> in the repo root and follow it exactly.`, for
   each root prompt whose name matches and that passes the check, to the terminal and into `docs/session-handoff.md`, and says when
   there is none or more than one. A prompt whose name matches but that fails the check gets no
   paste line; the handoff names it as failing `make prompt-check` instead. The skill's closing status block ends with that line under "Next
   action". The template's "End of session" runs `make handoff` last, after the next prompt exists.

## Rejected alternatives

- **A new skill for the paste line.** A second home for the same process; `make handoff` already knows
  the file name.
- **Track `.claude/settings.json`.** ADR-0043 rejected it: a live permission and hook file changes
  through a diff that reads like routine tidying.
- **A hook matched to `Write|Edit` only, keyed on `tool_input.file_path`.** A prompt written by `cat >`
  or `sed` would never be checked (Codex, plan review).
- **A line limit on prompts.** Any number would be arbitrary; the section check and the skill's "do not
  restate the process" cover what a limit would.

## Consequences

- An untracked prompt with a bad shape is shown to the agent at once on a machine with the hook, and
  refused by CI once committed. A session started in a worktree without the hook gets only the CI check
  until it runs `--install`.
- The hook runs on every shell call: one Python start and one `git worktree list`, and the check itself
  only when a root prompt changed, or while the last result failed.
- Advisory leftovers, recorded and not fixed here:
  - While a root prompt in another session's worktree fails the check, the hook reports it on this
    session's tool calls too, until that prompt is fixed.
  - The check reads the rendered page's elements, not its styles. A `<style>h2{display:none}</style>`
    block hides headings that the check still counts.
  - An unfilled copy of the template has the right name and sections, so it gets through the check.
    The check pins the shape, not the content.
- Prompts named in the old free style (`NEXT-SESSION-PROMPT.md`, `CONTINUE-X-PROMPT.md`) are refused at
  the root. Archived prompts are not checked.
