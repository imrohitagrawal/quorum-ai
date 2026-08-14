#!/usr/bin/env python3
"""Portability validator for `.claude/settings.json` shaped config.

`.claude/settings.json` is untracked and gitignored (see ADR-0043,
`docs/adr/0043-claude-settings-and-memory-stay-untracked.md`) — it stays a
machine-specific permission surface rather than a tracked product artifact.
That decision creates a durability gap the file itself already demonstrated:
`permissions.allow` on one real machine hardcoded
`/Users/rohitagrawal/Documents/Projects/quorum-ai/...`, an absolute path that
was already wrong (the repo does not live under `Documents/Projects`) because
nothing ever re-derives a path baked into an untracked file.

This module pins the portable convention: no string value anywhere in a
Claude settings JSON document may contain an absolute home-directory path
(`/Users/<name>/...` on macOS, `/home/<name>/...` on Linux). Commands and
hooks should reference the project root via `$CLAUDE_PROJECT_DIR` (the
existing idiom — see `tests/unit/test_claim_gate_hooks.py`) or a path
relative to it, never an absolute path baked in for one machine.

Usage:
    python3 scripts/validate_claude_settings.py [path-to-settings.json]

Exits 0 if the file is portable OR absent (absent is normal — the file is
gitignored, so a fresh clone and CI never have one). Exits 1 and prints every
offending value if a violation is found, or if the file exists but is not
valid JSON.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

#: Matches an absolute macOS or Linux home-directory path: /Users/<name>/...
#: or /home/<name>/..., each username followed by at least one path segment
#: so a bare "/home/" or "/Users/" string (no further path) is not flagged.
_HOME_PATH_RE = re.compile(r"/(?:Users|home)/[^/\s\"']+/[^\s\"']*")

DEFAULT_SETTINGS_PATH = Path(".claude") / "settings.json"


def find_absolute_home_paths(settings: Any, _location: str = "$") -> list[str]:
    """Walk a decoded settings document and return every string value that
    contains an absolute home-directory path, prefixed with where it was
    found (e.g. ``"permissions.allow[3]: Bash(node --check /Users/...)"``).

    Walks dicts, lists and tuples recursively; any other JSON leaf type
    (str, int, float, bool, None) is a base case.
    """
    hits: list[str] = []
    if isinstance(settings, dict):
        for key, value in settings.items():
            hits.extend(find_absolute_home_paths(value, f"{_location}.{key}"))
    elif isinstance(settings, (list, tuple)):
        for index, value in enumerate(settings):
            hits.extend(find_absolute_home_paths(value, f"{_location}[{index}]"))
    elif isinstance(settings, str):
        match = _HOME_PATH_RE.search(settings)
        if match:
            hits.append(f"{_location}: {settings}")
    return hits


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else DEFAULT_SETTINGS_PATH

    if not path.is_file():
        # Untracked and gitignored by design (ADR-0043) — absent is normal,
        # not a violation.
        return 0

    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{path}: not valid JSON ({exc})", file=sys.stderr)
        return 1

    violations = find_absolute_home_paths(settings)
    if not violations:
        return 0

    print(f"{path}: {len(violations)} absolute home-directory path(s) found:")
    for violation in violations:
        print(f"  {violation}")
    print(
        "\nUse $CLAUDE_PROJECT_DIR or a path relative to it instead of a "
        "machine-specific absolute path (see ADR-0043)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
