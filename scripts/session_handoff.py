#!/usr/bin/env python3
"""Generate/update docs/session-handoff.md from current route and git status."""

from __future__ import annotations

import datetime
import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Optional `-N` suffix disambiguates a second same-day narrative handoff
# (review finding: without it, a second session on the same date would
# silently overwrite the first session's file at the exact same path).
_NARRATIVE_HANDOFF_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-session-handoff(?:-(\d+))?\.md$")

#: Production's operator snapshot (rule 18: free to probe, never a paid call).
DEFAULT_STATUS_URL = "https://quorum-ai.fly.dev/status"

#: `git branch -r` prints this alongside real branches; it names the remote's
#: default-branch pointer, not a branch, so it must never be reported as one.
_REMOTE_HEAD_POINTER_RE = re.compile(r"^HEAD\s*->")

#: `N tests collected in Xs` or `N tests collected, M errors in Xs` -- the
#: last line of `pytest --collect-only -q --no-cov`. Collection only: this
#: never executes a test, so it stays cheap enough to run on every handoff.
_PYTEST_COLLECTED_RE = re.compile(
    r"^(?P<n>\d+)\s+tests?\s+collected(?:,\s*(?P<errors>\d+)\s+errors?)?\s+in\s"
)


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, cwd=ROOT, stderr=subprocess.STDOUT, text=True).strip()
    except subprocess.CalledProcessError as e:
        # `e.output` holds whatever the command already printed before it
        # exited non-zero -- for `pytest --collect-only`, that includes the
        # real "N tests collected" summary line even on a collection error.
        # `str(e)` alone throws that away for a generic "returned non-zero
        # exit status" message. Fall back to `str(e)` only when there was no
        # output to begin with.
        return f"unavailable: {e.output.strip() if e.output else e}"
    except Exception as e:
        return f"unavailable: {e}"


def _short(sha: str | None, n: int = 7) -> str:
    return (sha or "")[:n]


def _build_sha_drift_line(*, last_src_commit: str | None, prod_build_sha: str | None) -> str:
    """Compare production's `/status.build_sha` to the last commit touching `src/`.

    This is the relationship AGENTS.md rule 18 asks a human to check by hand
    (`build_sha` == the merged SHA) -- a "relationship" fact in #134's own
    taxonomy, which survives merges instead of going stale like a quoted SHA
    would. Pure comparison: the two values are fetched by the caller so this
    stays a same-process, mockable unit.
    """
    if not last_src_commit and not prod_build_sha:
        return "unavailable: could not read either the last src/ commit or production's build_sha"
    if not last_src_commit:
        return (
            f"unavailable: could not resolve the last commit touching src/ "
            f"(production build_sha is {_short(prod_build_sha)})"
        )
    if not prod_build_sha:
        return (
            f"unavailable: could not reach {DEFAULT_STATUS_URL} "
            f"(last src/ commit is {_short(last_src_commit)})"
        )
    if last_src_commit.strip().lower() == prod_build_sha.strip().lower():
        return f"production build_sha {_short(prod_build_sha)} is in sync with last src/ commit"
    return (
        f"production build_sha {_short(prod_build_sha)} does NOT match "
        f"last src/ commit {_short(last_src_commit)} -- a deploy may be in flight or overdue"
    )


def _parse_pytest_collected_count(raw: str) -> str:
    """Turn `pytest --collect-only -q --no-cov` output into a short count.

    Reads the summary line pytest always prints last on a clean collection;
    anything else (an ImportError before collection finishes, empty output)
    is reported as unavailable rather than guessed at.
    """
    for line in reversed(raw.strip().splitlines()):
        match = _PYTEST_COLLECTED_RE.match(line.strip())
        if match:
            errors = match.group("errors")
            if errors:
                return f"{match.group('n')} ({errors} error{'s' if errors != '1' else ''})"
            return match.group("n")
    return (
        f"unavailable: could not parse a collected-count summary line from: {raw.strip()[:200]!r}"
    )


#: The e2e lanes gated in `.github/workflows/e2e.yml` (rule: "enumerate the
#: directory rather than trusting this list" -- these are directory names to
#: glob, not a count, so a new lane directory shows up as 0 rather than
#: silently missing.
_E2E_LANE_DIRS = ("invariants", "ops", "degraded")


def _e2e_lane_counts(e2e_tests_dir: Path) -> dict[str, int]:
    """Count `*.spec.ts` files per e2e lane directory, straight off the tree.

    AGENTS.md's own invariant-spec count went stale ("twelve" while the
    directory held 15, later 17) because a sentence was never compared to the
    tree. Counting the tree at generation time instead of writing a number
    down is the fix this file makes generalizable.
    """
    return {
        lane: len(list((e2e_tests_dir / lane).glob("*.spec.ts")))
        if (e2e_tests_dir / lane).is_dir()
        else 0
        for lane in _E2E_LANE_DIRS
    }


def _parse_unmerged_branches(raw: str) -> list[str]:
    """Clean `git branch -r --no-merged origin/main` output to branch names.

    Drops the `origin/` remote prefix, the `origin/HEAD -> origin/main`
    pointer line git always prints alongside real branches, and passes
    through empty/`unavailable: ...` input as an empty list rather than
    misreporting the error text itself as a branch name.
    """
    if not raw.strip() or raw.strip().startswith("unavailable"):
        return []
    branches = []
    for line in raw.splitlines():
        name = line.strip().removeprefix("origin/")
        if not name:
            continue
        if _REMOTE_HEAD_POINTER_RE.match(name):
            continue
        branches.append(name)
    return branches


def _handoff_sort_key(path: Path) -> tuple[str, int]:
    match = _NARRATIVE_HANDOFF_RE.match(path.name)
    assert match is not None
    date_str, suffix = match.group(1), match.group(2)
    return (date_str, int(suffix) if suffix else 0)


def _latest_narrative_handoff(analysis_dir: Path) -> Path | None:
    """The newest hand-authored `docs/analysis/<YYYY-MM-DD>-session-handoff[-N].md`.

    This file (`docs/session-handoff.md`) is purely mechanical -- it never
    knew a narrative handoff existed, which is how it went 17 days stale
    (still naming a merged-and-deleted branch) without anyone noticing,
    because AGENTS.md points every new session here first. Sorting by
    (date, suffix) works because the date prefix is zero-padded ISO
    (YYYY-MM-DD), so lexicographic order equals chronological order, and the
    optional numeric suffix breaks ties within a single date correctly only
    because it's compared as an int, not a string (avoiding "-9" > "-10").
    """
    if not analysis_dir.is_dir():
        return None
    candidates = [
        p for p in analysis_dir.glob("*-session-handoff*.md") if _NARRATIVE_HANDOFF_RE.match(p.name)
    ]
    if not candidates:
        return None
    return max(candidates, key=_handoff_sort_key)


def _narrative_pointer_line(latest: Path | None, today: datetime.date | None = None) -> str:
    if latest is None:
        return "None found — no `docs/analysis/<YYYY-MM-DD>-session-handoff.md` exists yet."
    base = f"`docs/analysis/{latest.name}` — read this for full context before editing."
    match = _NARRATIVE_HANDOFF_RE.match(latest.name)
    if match is None:
        return base
    try:
        handoff_date = datetime.date.fromisoformat(match.group(1))
    except ValueError:
        return base
    age_days = ((today or datetime.date.today()) - handoff_date).days
    if age_days <= 0:
        return f"{base} (today)"
    plural = "s" if age_days != 1 else ""
    return (
        f"{base} **({age_days} day{plural} old** — if a newer session ran since "
        "then and its narrative handoff was archived without a replacement "
        "being written, this may be stale; check `docs/archive/` for a newer one.)"
    )


def load_route():
    spec = importlib.util.spec_from_file_location(
        "skill_router", ROOT / "scripts" / "skill_router.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore
    return mod.route()


def _fetch_prod_build_sha(status_url: str = DEFAULT_STATUS_URL) -> str | None:
    """Read `/status.build_sha` via `deploy_drift_check`'s existing fetcher.

    `attempts=1`: `deploy_drift_check`'s default of 3 exists to survive a cold
    Fly machine in a CI watchdog; a handoff generated with no network at all
    (the common offline-dev case) would otherwise pay ~15s of retry sleeps
    for nothing. One attempt, and unreachable is reported honestly rather
    than guessed at (rule 17f: never fabricate a number).
    """
    spec = importlib.util.spec_from_file_location(
        "deploy_drift_check", ROOT / "scripts" / "deploy_drift_check.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    try:
        spec.loader.exec_module(mod)  # type: ignore
        return mod.fetch_build_sha(status_url, attempts=1)
    except Exception:
        return None


def _gather_live_state() -> dict:
    """Pull every number this file used to require a human to type by hand.

    Each value is independently best-effort: `run()` and `_fetch_prod_build_sha`
    never raise, so one unreachable source (no network, `gh` not authenticated)
    degrades that one line to "unavailable" instead of failing the whole
    regeneration -- this file must still write *something* useful offline.
    """
    # `refs/remotes/origin/main`, not the bare `origin/main` shorthand: a local
    # branch can be named `origin/main` too (seen in this repo's own worktree
    # harness), and `git rev-parse origin/main` then prints an ambiguity
    # warning on stdout/stderr that corrupts the captured SHA rather than
    # failing loud. The fully-qualified ref path can't collide.
    main_tip = run(["git", "rev-parse", "--verify", "refs/remotes/origin/main"])
    # Scoped to `refs/remotes/origin/main`, not the current checkout's HEAD
    # (#134 residual gap): rule 17a mandates every session work from a
    # dedicated branch/worktree, so HEAD routinely differs from
    # `origin/main` -- an unmerged branch, or a local `main` that hasn't
    # been fast-forwarded yet. Walking from bare HEAD reported whichever of
    # those the current process happened to be sitting in, silently.
    last_src_commit = run(
        ["git", "log", "-1", "--format=%H", "refs/remotes/origin/main", "--", "src/"]
    )
    prod_build_sha = _fetch_prod_build_sha()
    pytest_raw = run(["uv", "run", "pytest", "--collect-only", "-q", "--no-cov"])
    open_issues_raw = run(
        ["gh", "issue", "list", "--state", "open", "--json", "number", "--jq", "length"]
    )
    unmerged_raw = run(["git", "branch", "-r", "--no-merged", "refs/remotes/origin/main"])
    return {
        "main_tip": main_tip,
        "last_src_commit": last_src_commit,
        "prod_build_sha": prod_build_sha,
        "build_sha_drift_line": _build_sha_drift_line(
            last_src_commit=last_src_commit
            if last_src_commit and "unavailable" not in last_src_commit
            else None,
            prod_build_sha=prod_build_sha,
        ),
        "pytest_count": _parse_pytest_collected_count(pytest_raw),
        "e2e_lane_counts": _e2e_lane_counts(ROOT / "e2e" / "tests"),
        "open_issue_count": open_issues_raw
        if open_issues_raw and "unavailable" not in open_issues_raw
        else "unavailable",
        "unmerged_branches": _parse_unmerged_branches(unmerged_raw),
    }


def _live_state_section(state: dict) -> str:
    """Format `_gather_live_state()`'s dict into the doc's "Live state" section."""
    lane_counts = state["e2e_lane_counts"]
    lane_line = ", ".join(f"{lane}: {n}" for lane, n in lane_counts.items())
    branches = state["unmerged_branches"]
    branches_block = (
        "\n".join(f"- `{b}`" for b in branches)
        if branches
        else "- None (every remote branch merges into `main`)"
    )
    return f"""## Live state (measured fresh by this run, not hand-carried)
Run `make handoff` again for current numbers instead of trusting this file
once it ages -- every value below is read from git/gh/`/status` at
generation time, per #134.

- **`origin/main` tip:** `{_short(state["main_tip"], 12) or "unavailable"}`
- **Last commit touching `src/`:** `{_short(state["last_src_commit"], 12) or "unavailable"}`
- **Production vs. last `src/` commit:** {state["build_sha_drift_line"]}
- **pytest collected (no execution):** {state["pytest_count"]}
- **e2e lane spec counts:** {lane_line}
- **Open issues:** {state["open_issue_count"]}
- **Changed-lines coverage:** not computed here -- `make diff-cover` shares
  coverage data with every pytest-invoking target and races with them if run
  concurrently (AGENTS.md rule 15), so this file does not run it. Run
  `make quality && make diff-cover DIFF_BASE=origin/main` for a current number.
- **Remote branches not merged into `origin/main`:**
{branches_block}
"""


def main() -> int:
    r = load_route()
    branch = run(["git", "branch", "--show-current"])
    status = run(["git", "status", "--short"])
    diffstat = run(["git", "diff", "--stat"])
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    latest_narrative = _latest_narrative_handoff(ROOT / "docs" / "analysis")
    narrative_pointer = _narrative_pointer_line(latest_narrative)
    live_state = _live_state_section(_gather_live_state())
    text = f"""# Session Handoff

## Date/time
{now}

## Latest narrative handoff
{narrative_pointer}

This file is a mechanical snapshot (branch/git-status/skill-route/live state) —
regenerated fresh every `make handoff`. The narrative above (what happened,
what's next, the traps) lives in the dated doc it points to, not here.

## Current branch/worktree
{branch or "not a git branch / unavailable"}

{live_state}
## Current phase
{r.get("label")}

## Current driver skill
`{r.get("driver")}`

## Reviewer skills
"""
    reviewers = r.get("reviewers") or []
    text += "\n".join(f"- `{x}`" for x in reviewers) if reviewers else "- None"
    text += """

## Blocking gates
"""
    blockers = r.get("blocking_gates") or []
    text += "\n".join(f"- `{x}`" for x in blockers) if blockers else "- None"
    text += """

## Missing or incomplete evidence
"""
    missing = r.get("missing_or_placeholder_evidence") or []
    text += "\n".join(f"- `{x}`" for x in missing) if missing else "- None"
    text += f"""

## Git status
```text
{status or "clean"}
```

## Diff stat
```text
{diffstat or "no unstaged diff"}
```

## Completed in this session
- Update manually before closing the session.

## Decisions made
- Update manually before closing the session.

## Assumptions recorded
- Update `docs/ASSUMPTIONS.md` when needed.

## Open questions
- Update `docs/13-open-questions.md` when needed.

## Durable records (this file is REGENERATED — it cannot hold session state)
Everything below the "Current phase" line is derived from `make skill-route`,
and this whole file is overwritten by `scripts/session_handoff.py`. Anything a
session needs to survive into the next one lives in a tracked doc instead:
- The narrative handoff linked above — what happened, what's next, the traps.
- `docs/analysis/R2-plan-review-findings.md` — **PHASE STATUS** is the
  authoritative phase, not the "Current phase" line above (which reports the
  factory router's view, overridden for R2 under AGENTS.md precedence #2).
- The current slice's handback, linked from that PHASE STATUS block.
- `docs/63-technical-debt-register.md` — accepted debt and what blocks what.

## Risks/blockers
- Update manually before closing the session.

## Validation run
```bash
make next
make skill-route
make validate
```

## Validation result
- Update after running checks.

## Next best action
{r.get("prompt")}

## Suggested next Codex prompt
```text
Continue from AGENTS.md, docs/00-factory-console.md, and docs/session-handoff.md.
Read the narrative handoff linked at the top of this file first -- it has the
real "what happened, what's next" context this mechanical file cannot hold.
Read the PHASE STATUS block in docs/analysis/R2-plan-review-findings.md and the
slice handback it links: the phase line in this file is the router's view, not
the authoritative one.
Do not redo completed work.
Use the recommended driver skill and reviewer skills from make skill-route.
Before editing, list the files you intend to modify.
```
"""
    (ROOT / "docs" / "session-handoff.md").write_text(text, encoding="utf-8")
    print("Updated docs/session-handoff.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
