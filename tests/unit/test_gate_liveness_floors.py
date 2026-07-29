"""Guards on the fail-closed floors that make a gate's verdict falsifiable.

CI runs coverage as `--cov=src`, so nothing under `scripts/` is measured by it.
These floors decide whether four BLOCKING gates are allowed to pass, so they get
their own tests or the machinery policing measurement is itself unmeasured.

THE DEFECT THESE EXIST TO STOP, reproduced on 2026-07-29 before any of this was
written:

    $ uv run diff-cover build/coverage/coverage.xml \
          --compare-branch=origin/main --fail-under=95
    No lines with coverage information in this diff.
    rc=0

with two genuinely uncovered new lines in the diff. A blocking gate named
"Changed-lines coverage >= 95%" exiting 0 having measured nothing. The same
shape as #130 (a green advisory job that had never scored a mutant) and #158
(a red one that had not either).

Every case drives the real functions against synthetic inputs, never against
this repository's live numbers, so none can pass by accident.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from tests.repo_root import find_repo_root

REPO_ROOT = find_repo_root(Path(__file__))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


e2e_floor = _load("check_e2e_executed")
diff_floor = _load("check_diff_cover_measured")


# --------------------------------------------------------------------------
# The Playwright executed-count floor
# --------------------------------------------------------------------------


def _junit(tmp_path: Path, *, tests: int, skipped: int = 0, failures: int = 0) -> Path:
    report = tmp_path / "results.xml"
    report.write_text(
        '<testsuites><testsuite name="l" '
        f'tests="{tests}" failures="{failures}" errors="0" skipped="{skipped}"/></testsuites>',
        encoding="utf-8",
    )
    return report


def test_a_lane_whose_specs_matched_nothing_fails(tmp_path: Path) -> None:
    """Playwright exits 0 when a spec path matches no file.

    Turns red if: the executed-count comparison is dropped or inverted.
    """
    report = _junit(tmp_path, tests=0)

    assert e2e_floor.main(["--report", str(report), "--min", "90", "--lane", "l"]) == 1


def test_a_fully_skipped_lane_fails(tmp_path: Path) -> None:
    """A skipped test still counts as collected; a blocking lane must not be silenced.

    Turns red if: the skipped check is removed — 94 skipped tests would then
    satisfy a floor of 90.
    """
    report = _junit(tmp_path, tests=94, skipped=94)

    assert e2e_floor.main(["--report", str(report), "--min", "90", "--lane", "l"]) == 1


def test_a_missing_report_fails(tmp_path: Path) -> None:
    """No JUnit XML means no evidence the lane ran at all.

    Turns red if: a missing report is treated as "nothing to check" and passes.
    """
    missing = tmp_path / "gone.xml"

    assert e2e_floor.main(["--report", str(missing), "--min", "1", "--lane", "l"]) == 1


def test_a_real_lane_passes(tmp_path: Path) -> None:
    """The positive partner. Without it, a floor that always returned 1 would
    satisfy all three tests above.

    Turns red if: the floor rejects a lane that genuinely executed its tests.
    """
    report = _junit(tmp_path, tests=94)

    assert e2e_floor.main(["--report", str(report), "--min", "88", "--lane", "l"]) == 0


def test_executed_excludes_failures(tmp_path: Path) -> None:
    """A failing test has not measured its invariant, so it must not count toward
    the floor — otherwise a lane could satisfy the floor entirely with failures.

    Turns red if: `counts` returns `tests` rather than tests minus failures/errors.
    """
    executed, _ = e2e_floor.counts(_junit(tmp_path, tests=94, failures=94))

    assert executed == 0


# --------------------------------------------------------------------------
# The changed-lines coverage floor
# --------------------------------------------------------------------------


def _coverage_xml(tmp_path: Path, filenames: list[str]) -> Path:
    classes = "".join(f'<class filename="{name}"/>' for name in filenames)
    report = tmp_path / "coverage.xml"
    report.write_text(
        f"<coverage><sources><source>{tmp_path / 'src'}</source></sources>"
        f"<packages><package><classes>{classes}</classes></package></packages></coverage>",
        encoding="utf-8",
    )
    return report


def test_a_changed_file_absent_from_the_report_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The empty-denominator failure, stated exactly.

    diff-cover scores over the changed lines it could MAP. A changed file the
    report has never heard of contributes nothing, the percentage is computed
    over the rest (or over nothing at all), and the gate exits 0.

    Turns red if: the set difference between changed files and reported files
    stops being treated as a failure.
    """
    monkeypatch.chdir(tmp_path)
    report = _coverage_xml(tmp_path, ["product_app/other.py"])
    monkeypatch.setattr(
        diff_floor, "changed_source_files", lambda base: ["src/product_app/thing.py"]
    )

    args = ["--coverage-xml", str(report), "--json-report", str(tmp_path / "none")]

    assert diff_floor.main(args) == 1


def test_a_changed_file_present_in_the_report_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive partner: the ordinary case must not be blocked.

    Also the guard against the floor becoming a blanket always-fail, which would
    be indistinguishable from a correct floor in the test above.

    Turns red if: the repo-relative path reconstruction from <source> breaks, so
    every file looks absent.
    """
    monkeypatch.chdir(tmp_path)
    report = _coverage_xml(tmp_path, ["product_app/thing.py"])
    monkeypatch.setattr(
        diff_floor, "changed_source_files", lambda base: ["src/product_app/thing.py"]
    )

    args = ["--coverage-xml", str(report), "--json-report", str(tmp_path / "none")]

    assert diff_floor.main(args) == 0


def test_a_docs_only_change_passes_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No src/ Python changed ⇒ an empty denominator is honest, not a failure.

    Without this the floor would fire on every docs pull request and be switched
    off within a week, which is how a gate dies.

    Turns red if: the no-changed-files branch starts failing.
    """
    monkeypatch.chdir(tmp_path)
    report = _coverage_xml(tmp_path, ["product_app/thing.py"])
    monkeypatch.setattr(diff_floor, "changed_source_files", lambda base: [])

    args = ["--coverage-xml", str(report), "--json-report", str(tmp_path / "none")]

    assert diff_floor.main(args) == 0
    assert "nothing to measure" in capsys.readouterr().out


def test_a_missing_coverage_report_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No coverage XML at all is the loudest form of "measured nothing".

    Turns red if: a missing report is skipped rather than failed.
    """
    monkeypatch.chdir(tmp_path)

    assert diff_floor.main(["--coverage-xml", str(tmp_path / "gone.xml")]) == 1


def test_the_worktree_is_included_in_the_changed_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """diff-cover scores "staged and unstaged changes", so the floor must see them.

    Measured while building this floor: with only the three-dot `base...HEAD`
    range, an uncommitted `src/` edit was invisible to the floor while diff-cover
    was scoring it — the floor passed over the exact case it exists to catch.

    Turns red if: the second `git diff HEAD` pass is removed.
    """
    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd: list[str], **kwargs: object) -> _Result:
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(diff_floor.subprocess, "run", _fake_run)
    diff_floor.changed_source_files("origin/main")

    assert any(cmd[-1] == "HEAD" for cmd in calls), (
        f"the working tree is never diffed; only these ran: {calls}"
    )
