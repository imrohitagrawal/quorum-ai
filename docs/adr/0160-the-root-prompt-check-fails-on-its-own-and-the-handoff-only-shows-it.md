# ADR-0160: The root prompt check fails on its own, and the handoff only shows it

## Status

Accepted — 2026-10-11, package A of `docs/analysis/2026-10-11-how-we-work-review.md`. It relates
this check to ADR-0045, which it leaves in force. Which root prompts are archived, pointed at the
skill or exempted is CHG-040 (c).

## Context

The review found that each handoff prompt is written fresh, and each one drops part of the agreed
process. ADR-0159 puts the process in one skill. A prompt now needs only one line naming it, and a
check can tell when that line is missing.

Three facts shape where the check runs:

| Fact | Evidence |
|---|---|
| Most root prompts are untracked | On 2026-10-11, 8 of 12 root `*PROMPT*.md` files were untracked (`git ls-files`) |
| `make handoff` must not fail outright | ADR-0045: one value's failure degrades that value and never aborts the file |
| `make validate` is the gate every session runs locally, and CI runs on a clean checkout | `Makefile` `validate`; `.github/workflows/ci.yml` |

If the check ran inside `make validate`, an untracked prompt in the main checkout would turn
`make validate` red on that machine and green in CI. (Two tests,
`tests/test_session_handoff_claims.py` and `tests/test_factory_console_claims.py`, also run
`make validate`, but only when a generated file claims it is red.) That is the trap `AGENTS.md` rule 13a records for
`e2e/tests/review/`.

## Decision

1. **`make prompt-check`** (`scripts/check_root_prompts.py`) reads the root directory itself, so it
   sees tracked and untracked files. It checks every root `.md` whose name contains `PROMPT`, in any
   case. Each must carry a line of the form
   `**Process:** … .agents/skills/work-item-delivery/SKILL.md`, indented at most 3 spaces, and
   not inside a fenced code block, an indented code block or an HTML comment. It exits 1 on any failure. It
   reports how many files it checked and how many were exempt, and it exits 1 when it finds no
   prompt file at all.
2. **Exemptions are by name, with a reason, in the script.** An exemption whose file no longer
   exists is itself a failure. The one exemption is `R2-S2-S4-ULTRACODE-PROMPT.md`: three tests
   pin its shape, and after this change it is the only tracked root prompt, so the check's "no
   prompt file found" floor in CI rests on it.
3. **`make handoff` shows the result as one value** and still writes the file, as ADR-0045 requires.
4. **CI checks the tracked prompts.** A unit test runs the same check over `git ls-files`, so a
   tracked prompt without the line cannot merge.

**This departs from the plan the owner approved,** which said `make handoff` "fails when a root
prompt file does not name the skill". ADR-0045 forbids that, and the session prompt suggested this
split. It is the session's choice (CHG-040 (c)); the owner may reverse it.

## Rejected alternatives

- **Inside `make validate`.** This hits the rule 13a trap described above.
- **`make handoff` exits 1.** This contradicts ADR-0045, and an offline handoff would stop
  writing.
- **A substring check for `work-item-delivery`.** It passes on "do not use work-item-delivery" and on
  a path quoted inside a code block (`AGENTS.md` rule 8).
- **Only `*-ULTRACODE-PROMPT.md`.** That misses `CONTINUE-W55-W56-PROMPT.md` and this session's own
  prompt.

## Consequences

- An untracked prompt without the line is caught by `make prompt-check` and shown in `make handoff`,
  but nothing blocks it. Blocking an untracked file would need a hook on the owner's machine.
- `scripts/session_hygiene.py` still keeps `*-ULTRACODE-PROMPT.md` files at the root as procedures.
  That is unchanged: this check judges what a prompt says, not where it lives.
