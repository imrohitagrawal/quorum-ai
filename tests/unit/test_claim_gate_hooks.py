"""Integrity tests for the H3/H4 evidence hooks in `.claude/settings.json`.

H3 (`PostToolUse`) stamps `.claude/state/last-test-run`; H4 (`Stop`) refuses to
let a turn end on an unbacked "all tests pass" claim unless that marker is
fresh. The pair is only worth anything if the marker means *a test run actually
went green* — the single scenario the gate exists to block is an agent whose
suite just failed declaring it green.

The original coupling failed exactly there. H3 keyed off the *command text*
(`echo pytest` qualified) and `PostToolUse` fires regardless of the command's
exit status, so a pytest that errored out with exit 4 collecting nothing
refreshed the marker and H4 then allowed the claim. Proven in-harness before
this test existed; these cases pin the fix.

The hook commands are read out of the **installed** settings file, not from a
copy, so a regression in the shipped hook fails here. `.claude/` is gitignored
(see `docs/analysis/09-enforcement-hooks.md`), so on a fresh clone / in CI there
is nothing to test and the module skips rather than lying green.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

pytestmark = pytest.mark.skipif(
    not SETTINGS.is_file(),
    reason=".claude/settings.json is gitignored and absent in this checkout",
)

# A real pytest tail, and the shapes that must NOT count as evidence.
GREEN_STDOUT = "...........\n501 passed, 1 skipped, 15 warnings in 14.02s\n"
FAILED_STDOUT = "5 failed, 534 passed, 1 skipped, 15 warnings in 37.09s\n"
COLLECT_ERROR_STDOUT = "ERROR: file or directory not found: tests/nonexistent.py\n"
NO_TESTS_STDOUT = "no tests ran in 0.01s\n"


def _hooks() -> dict[str, Any]:
    hooks: dict[str, Any] = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
    return hooks


def _recorder_command() -> str:
    """H3 — the PostToolUse test-evidence recorder."""
    command: str = _hooks()["PostToolUse"][0]["hooks"][0]["command"]
    return command


def _claim_gate_command() -> str:
    """H4 — the Stop claim gate."""
    command: str = _hooks()["Stop"][0]["hooks"][0]["command"]
    return command


def _run(
    command: str, payload: dict[str, Any], project_dir: Path, **env: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), **env},
    )


def _record(project_dir: Path, command: str, stdout: str = "", stderr: str = "") -> None:
    _run(
        _recorder_command(),
        {
            "tool_input": {"command": command},
            "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False},
        },
        project_dir,
    )


def _marker(project_dir: Path) -> Path:
    return project_dir / ".claude" / "state" / "last-test-run"


def _transcript(project_dir: Path, text: str) -> Path:
    path = project_dir / "transcript.jsonl"
    line = json.dumps(
        {"message": {"role": "assistant", "content": [{"type": "text", "text": text}]}},
        separators=(",", ":"),
    )
    path.write_text(line + "\n", encoding="utf-8")
    return path


def _claim_gate(project_dir: Path, claim: str) -> subprocess.CompletedProcess[str]:
    return _run(
        _claim_gate_command(),
        {"transcript_path": str(_transcript(project_dir, claim))},
        project_dir,
        QUORUM_STOP_HOOK="1",
    )


def _blocked(result: subprocess.CompletedProcess[str]) -> bool:
    if not result.stdout.strip():
        return False
    decision = json.loads(result.stdout).get("decision")
    return bool(decision == "block")


# --- H3: the marker must mean a run went green -----------------------------


@pytest.mark.parametrize(
    ("command", "stdout"),
    [
        ("ls -la", ""),
        ("git commit -m x", ""),
        # Named a test command but ran nothing — the cheapest possible forgery.
        ("echo pytest", "pytest\n"),
        # Ran the suite and it FAILED. This is the scenario the gate exists for.
        ("uv run pytest -q", FAILED_STDOUT),
        # Exit 4: collection error, zero tests, no summary line at all.
        ("uv run pytest tests/nonexistent.py -q", COLLECT_ERROR_STDOUT),
        ("uv run pytest -q -k nothing_matches", NO_TESTS_STDOUT),
        ("make test", "make: *** [test] Error 1\n"),
    ],
)
def test_recorder_refuses_to_stamp_without_a_green_run(
    tmp_path: Path, command: str, stdout: str
) -> None:
    _record(tmp_path, command, stdout=stdout)
    assert not _marker(tmp_path).exists(), (
        f"H3 stamped test evidence for {command!r} whose output was not green"
    )


def test_recorder_stamps_a_green_run_with_its_summary(tmp_path: Path) -> None:
    _record(tmp_path, "uv run pytest -q", stdout=GREEN_STDOUT)
    marker = _marker(tmp_path)
    assert marker.exists()
    contents = marker.read_text(encoding="utf-8")
    timestamp, _, summary = contents.partition("\t")
    assert abs(int(timestamp) - time.time()) < 120
    # The summary is what makes the marker unforgeable-by-accident: H4 requires
    # it, so a bare `date +%s >` no longer satisfies the gate.
    assert "501 passed" in summary


def test_recorder_reads_stderr_too(tmp_path: Path) -> None:
    _record(tmp_path, "make quality", stderr=GREEN_STDOUT)
    assert _marker(tmp_path).exists()


# --- H4: only a hook-written green marker satisfies the claim --------------


def test_claim_gate_blocks_a_hand_written_timestamp_marker(tmp_path: Path) -> None:
    """`echo $(date +%s) > last-test-run` must not buy a green claim (EN-2)."""
    _marker(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    _marker(tmp_path).write_text(f"{int(time.time())}\n", encoding="utf-8")
    assert _blocked(_claim_gate(tmp_path, "All tests pass, the suite is green."))


def test_claim_gate_blocks_when_no_run_was_recorded(tmp_path: Path) -> None:
    assert _blocked(_claim_gate(tmp_path, "All tests pass, the suite is green."))


def test_claim_gate_blocks_a_stale_green_marker(tmp_path: Path) -> None:
    _marker(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    stale = int(time.time()) - 1200
    _marker(tmp_path).write_text(f"{stale}\t501 passed, 1 skipped in 14.02s\n", encoding="utf-8")
    assert _blocked(_claim_gate(tmp_path, "All tests pass, the suite is green."))


def test_claim_gate_allows_a_claim_backed_by_a_fresh_green_run(tmp_path: Path) -> None:
    """End-to-end: H3 writes the marker H4 reads. No hand-made evidence."""
    _record(tmp_path, "uv run pytest -q", stdout=GREEN_STDOUT)
    assert not _blocked(_claim_gate(tmp_path, "All tests pass, the suite is green."))


def test_claim_gate_does_not_block_an_unrelated_turn(tmp_path: Path) -> None:
    assert not _blocked(_claim_gate(tmp_path, "I summarised the file."))


def test_claim_gate_is_disarmed_by_default(tmp_path: Path) -> None:
    result = _run(
        _claim_gate_command(),
        {"transcript_path": str(_transcript(tmp_path, "All tests pass."))},
        tmp_path,
        QUORUM_STOP_HOOK="",
    )
    assert not _blocked(result)
