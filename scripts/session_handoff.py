#!/usr/bin/env python3
"""Generate/update docs/session-handoff.md from current route and git status."""

from __future__ import annotations

import datetime
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, cwd=ROOT, stderr=subprocess.STDOUT, text=True).strip()
    except Exception as e:
        return f"unavailable: {e}"


def load_route():
    spec = importlib.util.spec_from_file_location(
        "skill_router", ROOT / "scripts" / "skill_router.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore
    return mod.route()


def main() -> int:
    r = load_route()
    branch = run(["git", "branch", "--show-current"])
    status = run(["git", "status", "--short"])
    diffstat = run(["git", "diff", "--stat"])
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    text = f"""# Session Handoff

## Date/time
{now}

## Current branch/worktree
{branch or "not a git branch / unavailable"}

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
