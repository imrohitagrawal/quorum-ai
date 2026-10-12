"""The board and GitHub must agree (ADR-0162, decision 5; failure N2).

On 2026-10-11 four DONE rows (W25, W26, W27, W29) cited issues that were still
open, and #458 and #459 were open with no row. ``check_board_github`` in
``scripts/`` lists both kinds of mismatch. It needs ``gh`` and the network, so
without them it says "unavailable" and does not fail (ADR-0045).

``compare`` is tested with literal rows and literal open-issue sets. ``main`` is
tested with a fake ``gh`` placed first on ``PATH``: one that fails, none at all,
and one that answers, which is the partner proving ``main`` is not always 0.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root
from tests.status_clone import load_script

ROOT = find_repo_root(Path(__file__))


def _script() -> Any:
    return load_script(ROOT, "check_board_github")


# ---------------------------------------------------------------------------
# compare(rows, open_issues)
# ---------------------------------------------------------------------------


def test_a_done_row_citing_an_open_issue_is_a_problem() -> None:
    # Red when: a DONE row whose issue is still open passes.
    problems = _script().compare([("W25", "DONE", [464])], {464})
    assert len(problems) == 1, problems
    assert "W25" in problems[0] and "464" in problems[0], problems


def test_an_open_issue_no_row_cites_is_a_problem() -> None:
    # Red when: an open issue with no board row passes.
    problems = _script().compare([("W13", "UNPINNED", [268])], {268, 458})
    assert len(problems) == 1, problems
    assert "458" in problems[0], problems


def test_a_done_row_citing_a_closed_issue_is_fine() -> None:
    # Red when: a DONE row is reported although its issue is closed (not in the open set).
    assert _script().compare([("W25", "DONE", [464])], set()) == []


@pytest.mark.parametrize("state", ["PENDING", "UNPINNED"])
def test_an_open_row_citing_an_open_issue_is_fine(state: str) -> None:
    # Red when: an open issue on a row that is not DONE is reported.
    assert _script().compare([("W28", state, [464])], {464}) == []


def test_a_row_citing_two_issues_is_checked_for_each() -> None:
    # Red when: only the first issue in a row's Issue cell is compared.
    problems = _script().compare([("W29", "DONE", [447, 458])], {458})
    assert len(problems) == 1 and "458" in problems[0] and "W29" in problems[0], problems


# ---------------------------------------------------------------------------
# main(): gh unavailable, gh failing, gh answering.
# ---------------------------------------------------------------------------


def _fake_gh(bin_dir: Path, body: str) -> Path:
    """A ``gh`` that records its arguments to ``gh.args`` and then runs ``body``."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "gh.args"
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n{body}\n', encoding="utf-8")
    gh.chmod(0o755)
    return log


def _run_main(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = _script().main([])
    captured = capsys.readouterr()
    return int(code), captured.out + captured.err


def test_main_reports_unavailable_and_exits_0_when_gh_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: a failing gh (no network, not signed in) fails the caller instead of degrading.
    # It prints a valid empty list AND exits 1: the exit code alone says it failed.
    log = _fake_gh(
        tmp_path / "bin", "echo '[]'\necho 'error connecting to api.github.com' >&2\nexit 1"
    )
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    code, output = _run_main(capsys)
    assert code == 0, output
    assert "unavailable" in output, output
    assert log.is_file(), "the fake gh was never called, so this measured nothing"


def test_main_reports_unavailable_and_exits_0_when_gh_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: a machine without gh gets a crash or a failure instead of "unavailable".
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git_path = shutil.which("git")
    assert git_path, "git must exist for the rest of the suite anyway"
    (bin_dir / "git").symlink_to(git_path)
    monkeypatch.setenv("PATH", str(bin_dir))
    assert shutil.which("gh") is None
    code, output = _run_main(capsys)
    assert code == 0, output
    assert "unavailable" in output, output


def test_main_exits_1_on_a_mismatch_and_asks_gh_for_open_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: main exits 0 over a real mismatch, or stops asking gh for the OPEN issues.
    # 99999 is an open issue no board row can cite.
    log = _fake_gh(tmp_path / "bin", "printf '%s' '[{\"number\": 99999}]'")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    code, output = _run_main(capsys)
    assert code == 1, output
    assert "99999" in output, output
    assert "unavailable" not in output, output
    args = log.read_text(encoding="utf-8")
    assert re.search(r"\bissue list\b", args), f"gh was called with {args!r}"
    assert re.search(r"--state[= ]open\b", args), f"gh was called with {args!r}"
    assert re.search(r"--json[= ]number\b", args), f"gh was called with {args!r}"
