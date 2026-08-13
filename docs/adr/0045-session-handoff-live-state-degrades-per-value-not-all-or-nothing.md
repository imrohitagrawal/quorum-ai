# ADR-0045: `make handoff`'s live state degrades per-value, not all-or-nothing

## Status

Accepted — 2026-08-14

## Context

#134 traced a class of stale handoff: a value gets typed into a document by
hand, and the fact it describes moves the moment the document is committed.
Its own example — `GUARDRAILS-THEN-HANDOFF-ULTRACODE-PROMPT.md` said "expect
main `2bba0d1`"; merging that file moved the tip to `c1d20f8`, wrong on
arrival.

`docs/session-handoff.md` (`scripts/session_handoff.py`) already regenerates
its structural sections (branch, git status, skill route) from live git state
on every `make handoff`. What it did not carry was the handful of numbers
handoffs have historically quoted by hand: production's `build_sha` versus
the last commit touching `src/`, how many tests exist, how many issues are
open, which branches are not yet merged. #134 asks for those to be measured
the same way, so a handoff says "run `make handoff` and compare" instead of
quoting a number that starts decaying the instant it's written.

This ADR is about the **posture** of that measurement, not the numbers
themselves — the numbers are read straight off git/gh/`/status` at generation
time and need no design decision. The posture does:

`scripts/deploy_drift_check.py` (ADR-0026) already compares `/status.build_sha`
against `main`'s tip and answers the identical question this file now also
asks. Reusing its comparison logic was straightforward; reusing its **failure
posture** was not, because the two call sites want opposite things from an
unreachable `/status`:

- `deploy_drift_check.py` runs in a scheduled CI job whose only output is a
  pass/fail signal. Unreachable production must be **loud** — it exits 1 and
  pages someone, because "I could not tell" must never read as healthy
  (ADR-0026's `DriftDecision.UNKNOWN`, deliberately in the alerting set).
- `session_handoff.py` runs on a developer's machine, often offline, as one of
  several dozen values in one document. If it adopted the same posture, a
  laptop with no network would make `make handoff` fail outright, and every
  other value in the document — branch name, pytest count, open-issue count,
  none of which need `/status` at all — would be withheld along with it.

## Decision

Every live-state value is fetched independently and degrades to its own
"unavailable: `<reason>`" string on failure, rather than one failure aborting
the whole run. Concretely:

- `run()` (already used for the structural sections) never raises; every
  git/gh subprocess call returns its own `unavailable: ...` string on error.
- `_fetch_prod_build_sha()` wraps `deploy_drift_check.fetch_build_sha` in a
  `try/except` and returns `None` on any failure — import error, network
  error, malformed JSON — never propagating.
- `_build_sha_drift_line()`, `_parse_pytest_collected_count()`, and
  `_parse_unmerged_branches()` all accept a missing/unavailable input and
  return a line that says so, rather than raising or guessing.
- The production probe uses `attempts=1`, not `deploy_drift_check`'s default
  of 3. That default exists to survive a cold Fly machine during a scheduled
  CI check (ADR-0026); paying three attempts' worth of 5s retry sleeps (~15s)
  for a probe most local runs will find unreachable anyway is the wrong trade
  for a command meant to run at the end of every session.
- **Changed-lines coverage is not computed by this file at all.**
  `make diff-cover` shares coverage data (`.coverage` / `coverage.xml`) with
  every pytest-invoking target and races with them if run concurrently
  (AGENTS.md rule 15). Running it inside `make handoff` — itself invoking
  `pytest --collect-only` — would either race a concurrent `make quality`
  run or silently rewrite coverage data underneath one. The generated section
  states this and names the exact command (`make diff-cover
  DIFF_BASE=origin/main`) instead of fabricating a number or omitting the
  topic silently.

## Rejected alternatives

**Adopt `deploy_drift_check`'s all-or-nothing/loud-on-failure posture
wholesale.** Correct for a CI gate whose only job is to alert; wrong for a
document generator whose job is to be maximally useful with whatever it can
read. An offline developer closing a session should still get a
branch/skill-route/pytest-count snapshot; failing the whole run because
`/status` is unreachable would regress `make handoff` from "always works" to
"works when the network does."

**Compute changed-lines coverage live, sequenced to avoid the race (e.g. hold
a lock, or only run when no other gate is active).** Adds real complexity
(the failure mode is a shared file, not a shared lock this script owns) to
answer a question a developer is going to ask CI, or run `make diff-cover`
for, right before opening the pull request anyway. The value this session's
number would add over "run the real command" is low, and the race risk is not.

**Cache the last known `build/coverage/coverage.xml` and report its age.** No
such file exists in a clean checkout (verified: `build/` is absent on this
worktree until a gate target creates it), so this would report "unavailable"
identically to stating the fact outright, with more code to reach the same
answer.

## Consequences

- `make handoff` stays fast and offline-safe: measured 5s end-to-end in this
  worktree (git rev-parse, `git log`, one `/status` probe capped at ~10s
  worst-case with `attempts=1`, `pytest --collect-only --no-cov` at ~3s,
  `gh issue list`, `git branch -r --no-merged`).
- A reader of `docs/session-handoff.md` sees exactly which values were
  readable this run and which were not, per line — not a single boolean
  "live state available: yes/no" that would hide which fact actually failed.
- Changed-lines coverage remains a value nobody can trust from this file by
  design; the alternative was trusting a number this file cannot honestly
  produce.
- `origin/main`'s tip and the branch-list query now resolve
  `refs/remotes/origin/main` explicitly rather than the bare `origin/main`
  shorthand. This worktree's own harness creates a *local* branch literally
  named `origin/main` alongside the identically-named remote-tracking ref;
  `git rev-parse origin/main` then prints an ambiguity warning that corrupts
  the captured SHA instead of failing loud. The fully-qualified ref path
  cannot collide with a local branch name.
