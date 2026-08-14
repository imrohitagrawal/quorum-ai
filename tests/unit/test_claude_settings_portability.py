"""Portability checks for `.claude/settings.json` shaped config (issue #242).

`.claude/settings.json` is untracked and gitignored (ADR-0043) — it exists on
whatever machine wrote it and nowhere else, so a test asserting on the real
file would itself be machine-dependent and would skip everywhere but one
laptop. These tests instead pin a portable CONVENTION — no string value in a
Claude settings file may contain an absolute home-directory path
(`/Users/<name>/...` or `/home/<name>/...`) — against small synthetic
fixtures built in this file, and prove the validator that enforces it via
`scripts/validate_claude_settings.py`.

What turns each test red: reverting
`scripts/validate_claude_settings.py::find_absolute_home_paths` to a stub
that always returns `[]` (or deleting the module) makes every "detects"
test below fail, because the offending path in the fixture is never
reported. The clean-fixture test is the negative partner (rule 7): it proves
the same function does not fire on a portable file, so "detects" tests cannot
be satisfied by a validator that flags everything.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validate_claude_settings.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_claude_settings import find_absolute_home_paths  # noqa: E402

# --- synthetic fixtures — never the real, untracked settings file ----------

PORTABLE_SETTINGS: dict[str, object] = {
    "permissions": {
        "allow": [
            "Bash(make test)",
            "Bash(uv run pytest)",
            "Bash(node --check src/product_app/static/app.js)",
            "WebFetch(domain:github.com)",
        ]
    },
    "hooks": {
        "PostToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/record.sh',
                    }
                ],
            }
        ]
    },
}

# The real, measured defect from issue #242: an absolute path under
# /Users/<name>/... that is also stale (Documents/Projects, not the repo's
# actual location) — but staleness isn't what makes it invalid; the absolute
# home path is.
_STALE_STATIC_PATH = (
    "/Users/rohitagrawal/Documents/Projects/quorum-ai/src/product_app/static/app.js"
)

SETTINGS_WITH_MAC_HOME_PATH: dict[str, object] = {
    "permissions": {
        "allow": [
            "Bash(make test)",
            f"Bash(node --check {_STALE_STATIC_PATH})",
        ]
    },
    "hooks": {},
}

SETTINGS_WITH_LINUX_HOME_PATH: dict[str, object] = {
    "permissions": {"allow": ["Bash(cat /home/ci-runner/workspace/notes.txt)"]},
    "hooks": {},
}

SETTINGS_WITH_NESTED_HOME_PATH: dict[str, object] = {
    "hooks": {
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "bash /Users/alice/scripts/claim-gate.sh",
                    }
                ]
            }
        ]
    }
}


def test_portable_settings_flag_nothing() -> None:
    assert find_absolute_home_paths(PORTABLE_SETTINGS) == []


def test_detects_absolute_macos_home_path() -> None:
    hits = find_absolute_home_paths(SETTINGS_WITH_MAC_HOME_PATH)
    assert len(hits) == 1
    assert "/Users/rohitagrawal/Documents/Projects/quorum-ai" in hits[0]


def test_detects_absolute_linux_home_path() -> None:
    hits = find_absolute_home_paths(SETTINGS_WITH_LINUX_HOME_PATH)
    assert len(hits) == 1
    assert "/home/ci-runner/workspace/notes.txt" in hits[0]


def test_detects_home_path_nested_inside_hook_command() -> None:
    """The offending value lives three levels deep (hooks.Stop[0].hooks[0].command) —
    the validator must walk the structure, not just top-level keys."""
    hits = find_absolute_home_paths(SETTINGS_WITH_NESTED_HOME_PATH)
    assert len(hits) == 1
    assert "/Users/alice/scripts/claim-gate.sh" in hits[0]


def test_does_not_flag_a_relative_or_env_relative_path() -> None:
    """`$CLAUDE_PROJECT_DIR`-relative and plain relative paths are the portable
    idiom this repo's own hooks use (see tests/unit/test_claim_gate_hooks.py) —
    they must never be flagged."""
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "command": (
                                '"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard.sh --path src/app.js'
                            )
                        }
                    ]
                }
            ]
        }
    }
    assert find_absolute_home_paths(settings) == []


def test_multiple_offending_values_all_reported() -> None:
    settings = {
        "permissions": {
            "allow": [
                "Bash(node --check /Users/bob/repo/app.js)",
                "Bash(cat /home/carol/notes.txt)",
            ]
        }
    }
    assert len(find_absolute_home_paths(settings)) == 2


# --- CLI behaviour: exit code is the enforceable contract -------------------


def _run_cli(fixture: dict[str, object], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(fixture), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATOR), str(settings_path)],
        capture_output=True,
        text=True,
    )


def test_cli_exits_zero_on_a_portable_settings_file(tmp_path: Path) -> None:
    result = _run_cli(PORTABLE_SETTINGS, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_exits_nonzero_and_names_the_path_on_a_violation(tmp_path: Path) -> None:
    result = _run_cli(SETTINGS_WITH_MAC_HOME_PATH, tmp_path)
    assert result.returncode != 0
    assert "/Users/rohitagrawal/Documents/Projects/quorum-ai" in result.stdout


def test_cli_exits_zero_when_the_file_is_absent(tmp_path: Path) -> None:
    """`.claude/settings.json` is untracked (ADR-0043) — absent is the normal
    case on a fresh clone and in CI, and must not be treated as a violation."""
    missing = tmp_path / "settings.json"
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(missing)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        '{"unterminated": ',
    ],
)
def test_cli_exits_nonzero_on_malformed_json(raw: str, tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(raw, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(settings_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
