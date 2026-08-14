# ADR-0043: `.claude/` (agent hooks, permissions, and memory) stays untracked, local-only

## Status

Accepted — 2026-08-14 (issue #242)

## Context

Issue #242 asked whether `.claude/settings.json` — the agent's permission
allowlist and enforcement hooks (`PreToolUse`, `PostToolUse`, `Stop`) — and the
agent's cross-session memory (`~/.claude/projects/…/memory/`) should be tracked
in git, so the enforcement they provide survives a machine change and is
shared across contributors.

Both files were inspected directly rather than assumed:

- `.claude/settings.json`, 5,670 bytes, project-level. Contents: a
  `permissions.allow` list (10 entries — shell allowlists such as `make test`,
  `pytest`, `lsof`, a `curl` to the fly.dev host, and 2 `WebFetch` domains);
  `hooks.PreToolUse` (2 hooks — blocks `--no-verify` on a real VCS call, runs
  `make validate` + `pytest` as a pre-commit gate); `hooks.PostToolUse` (1 hook
  — records a green-run marker); `hooks.Stop` (1 hook — the claim gate that
  refuses to end a turn asserting "tests pass" without a fresh green marker,
  gated behind `QUORUM_STOP_HOOK=1`).
- Secret scan on the file: clean.
  `grep -oiE "(sk-…|ghp_…|api[_-]?key|token|secret|password|Bearer )"`
  matched nothing.
- One concrete durability defect found by inspection: `permissions.allow[3]`
  hardcodes `Bash(node --check /Users/rohitagrawal/Documents/Projects/quorum-ai/src/product_app/static/app.js)`
  — an absolute path under `Documents/Projects`, which is not where this repo
  lives on this machine (it lives at `~/Projects/quorum-ai`). The entry is
  already wrong on the machine that wrote it, which is itself evidence for
  what happens when a machine-specific path sits in a file nobody re-derives.
- `.claude/settings.local.json` (859 bytes) also exists, is the intended home
  for per-machine overrides, and is untouched by this decision either way.

## Decision

**`.claude/settings.json`, and the rest of `.claude/` (state, prompts, skills,
worktrees), stay untracked and local-only.** `.gitignore:28` continues to
exclude `.claude/`. The agent's cross-session memory
(`~/.claude/projects/.../memory/`) also stays outside the repo, unchanged —
it already lives outside `.claude/` entirely and this ADR does not move it.

Reasoning:

- `.claude/settings.json` is a **machine-specific permission surface**, not a
  product artifact. It grants shell command execution rights
  (`permissions.allow`) and installs hooks that run arbitrary commands on tool
  use. Tracking it means every contributor who pulls `main` silently inherits
  whatever shell allowlist and hook set the file currently contains.
- The risk is not hypothetical to this file: it is a JSON blob edited by hand
  and by agent sessions, with no schema enforcement today. A routine-looking
  PR — "tidy up the hooks file", "add one more allowed command" — could widen
  the allowlist or change what a hook executes, and a code reviewer scanning a
  diff for product logic is not primed to catch a permission escalation
  sitting in a dotfile.
- Today's blast radius is small (single maintainer, single machine), which is
  exactly why this is the moment to decide deliberately rather than let the
  status quo (`.gitignore`d, undecided) continue by inertia into a point
  where more people depend on it without ever having agreed to it.
- The durability problem #242 raises — a hook config on exactly one laptop —
  is real, but tracking the live, executable file is not the only way to
  answer it. Prose-reviewable export (see "What would change this decision")
  gets the durability without importing a live permission grant through a
  normal merge.

### Rejected alternative: track `.claude/settings.json` in git

**For:** it is the only enforcement layer that fires *while* the agent works,
not after — `AGENTS.md` prose cannot do that, hooks can. Tracking it would
mean a fresh clone or a new machine gets the same enforcement immediately.

**Rejected because:** the failure mode this ADR exists to name is a hook or
an allowlist entry changing via a PR that reads, on its diff, like routine
config tidying — because a JSON settings file has no natural place for prose
explaining *why* an entry exists, unlike a `docs/adr/*.md` decision record or
even a commented shell script. A reviewer approving "config change, +1/-1
lines" does not get the same signal a reviewer approving "grant `curl` to a
new host" would get if that grant were written as reviewed prose instead of a
live file the agent immediately starts obeying merge-side. The stale absolute
path found in this file (see Context) is a small instance of the same root
cause: nothing forces the file to be re-derived when the environment around it
changes, because nothing ever reviews it as content — only as an opaque
dotfile that either exists or does not.

## What would change this decision

- **The team needs a shared baseline permission set.** If more than one
  contributor needs the same enforcement, the answer is not "track the live
  file" — it is to **export** the settings that should be shared into a plain
  file under `docs/` (e.g. `docs/90-agent-permission-baseline.md` or similar),
  written and reviewed as prose describing the allowlist and each hook's
  purpose, the same way ADRs are reviewed. A setup script or onboarding step
  then materializes `.claude/settings.json` from that reviewed document,
  keeping the live file itself out of history while making its *content*
  durable and diffable-as-prose.
- **The hooks stop containing anything sensitive or environment-specific by
  construction** (e.g. every path is resolved at runtime from
  `CLAUDE_PROJECT_DIR` rather than hardcoded, as `tests/unit/test_claim_gate_hooks.py`
  already assumes) — this would remove the specific risk this ADR is about,
  though the general "live executable file merged without prose review" risk
  would remain.
- **CI needs to depend on the file being present** — today
  `tests/unit/test_claim_gate_hooks.py` skips when `.claude/settings.json` is
  absent (true in CI and on a fresh clone). If a future change makes CI
  require the hooks to exist and run, that is itself a reason to track a
  reviewed, sanitized version of the file, not this ADR's untracked default.

## Consequences

- `.claude/settings.json` (and `.claude/` generally) is not present on a fresh
  clone or in CI. `tests/unit/test_claim_gate_hooks.py` continues to skip in
  those environments by design — this is a pre-existing, intentional property
  of that test, not a gap this ADR introduces.
- The durability gap #242 raised for the *content* of the file (a stale
  absolute path, and more generally nothing that checks the file's shape) is
  addressed separately: `scripts/validate_claude_settings.py` and
  `tests/unit/test_claude_settings_portability.py` establish a portable
  convention — no absolute home-directory path may appear in any string value
  — and enforce it against a synthetic fixture, so the check does not depend
  on, or vary with, the actual untracked file on any given machine.
- The cross-session memory question (#242 part B) is resolved as: leave it
  where it is, outside the repo. It is agent-specific working state, not
  product or process documentation; the *traps and lessons* worth keeping are
  already the kind of thing this repo's `docs/` and `AGENTS.md` capture when
  they generalize beyond one session (see rule 18a and the "session output vs
  executable procedure" table in `AGENTS.md`). No new export mechanism is
  built for memory by this ADR — that stays out of scope per the issue's own
  "Out of scope: Building new hooks."
