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
from tests.code_text import code_without_comments
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
    json_report = tmp_path / "diff-cover.json"
    json_report.write_text('{"total_num_lines": 5}', encoding="utf-8")

    args = ["--coverage-xml", str(report), "--json-report", str(json_report)]

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


def _present_args(tmp_path: Path, *, json_report: Path) -> list[str]:
    """Args for a run where every changed file is already known to be covered.

    Isolates the json-report-reading branch under test from the earlier
    changed/missing-file checks, which already have their own tests above.
    """
    report = _coverage_xml(tmp_path, ["product_app/thing.py"])
    return ["--coverage-xml", str(report), "--json-report", str(json_report)]


def test_a_missing_json_report_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#165: a missing --json-report silently passed with the count omitted.

    Every changed file is present in the coverage XML, so the only thing left
    unmeasured is the changed-lines count itself — exactly the "pass with no
    denominator" shape this floor exists to abolish, this time inside itself.

    Turns red if: a missing json-report file stops being a failure.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        diff_floor, "changed_source_files", lambda base: ["src/product_app/thing.py"]
    )

    assert diff_floor.main(_present_args(tmp_path, json_report=tmp_path / "gone.json")) == 1


def test_a_keyless_json_report_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`{}` has no total_num_lines — the count is just as absent as a missing file.

    Turns red if: a dict without the key is treated as `total is None` and
    falls through to the success message with the count silently omitted.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        diff_floor, "changed_source_files", lambda base: ["src/product_app/thing.py"]
    )
    json_report = tmp_path / "diff-cover.json"
    json_report.write_text("{}", encoding="utf-8")

    assert diff_floor.main(_present_args(tmp_path, json_report=json_report)) == 1


def test_a_null_json_report_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`null` parses without error but is not a dict — same failure, different shape.

    Turns red if: the isinstance(dict) check is dropped and `null.get(...)` is
    trusted to raise instead of being checked explicitly.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        diff_floor, "changed_source_files", lambda base: ["src/product_app/thing.py"]
    )
    json_report = tmp_path / "diff-cover.json"
    json_report.write_text("null", encoding="utf-8")

    assert diff_floor.main(_present_args(tmp_path, json_report=json_report)) == 1


def test_a_malformed_json_report_fails_with_a_message_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A truncated write (crash mid-write, disk full) must not crash the floor too.

    Turns red if: JSONDecodeError is left uncaught, or the failure prints a raw
    traceback instead of a readable message.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        diff_floor, "changed_source_files", lambda base: ["src/product_app/thing.py"]
    )
    json_report = tmp_path / "diff-cover.json"
    json_report.write_text("{not valid json", encoding="utf-8")

    assert diff_floor.main(_present_args(tmp_path, json_report=json_report)) == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_a_valid_json_report_surfaces_the_measured_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Positive partner: a real count must still print and still pass.

    Without this, a floor that failed on every json-report shape would satisfy
    all four tests above.

    Turns red if: a valid report with a real count is rejected.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        diff_floor, "changed_source_files", lambda base: ["src/product_app/thing.py"]
    )
    json_report = tmp_path / "diff-cover.json"
    json_report.write_text('{"total_num_lines": 7}', encoding="utf-8")

    assert diff_floor.main(_present_args(tmp_path, json_report=json_report)) == 0
    assert "7 changed lines measured" in capsys.readouterr().out


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


# --------------------------------------------------------------------------
# The two script-internal floors
#
# These shipped without tests in the first cut of this change, which AGENTS.md —
# edited by the same commit — forbids, naming `scripts/security_scan.py`
# explicitly. Caught by adversarial review. CI runs `--cov=src`, so nothing here
# is measured by the coverage gate; without these the floors guarding two
# BLOCKING gates would themselves be unguarded.
# --------------------------------------------------------------------------


def _security_scan(tmp_root: Path) -> ModuleType:
    """Load security_scan with its ROOT pointed at a synthetic tree.

    `setattr` rather than direct assignment because the module is loaded
    dynamically, so mypy cannot see the attributes it is being given.
    """
    module = _load("security_scan")
    setattr(module, "ROOT", tmp_root)  # noqa: B010
    setattr(module, "REPORT_PATH", tmp_root / "build" / "security" / "security-scan.json")  # noqa: B010
    return module


def test_a_security_scan_that_read_almost_nothing_fails(tmp_path: Path) -> None:
    """Zero findings over zero files is not a clean scan, it is no scan.

    Every check in that script is "no line matches a secret pattern", which is
    trivially true over an empty file list — so a moved root or a broadened
    ignore rule would print "Security scan passed" and exit 0 on a BLOCKING gate.

    Turns red if: the MINIMUM_FILES_SCANNED comparison is removed, or
    `_run_checks` stops returning the count alongside the findings.
    """
    (tmp_path / "only.md").write_text("nothing here", encoding="utf-8")

    assert _security_scan(tmp_path).main() == 1


def test_a_real_security_scan_passes_and_reports_its_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Positive partner: a tree above the floor must pass, and say how many.

    Without this, a floor that always returned 1 would satisfy the test above.
    The printed count is the denominator — a pass with no number is the thing
    this whole family of floors exists to abolish.

    Turns red if: the floor rejects a legitimately-sized tree, or the pass
    message stops naming the file count.
    """
    for index in range(60):
        (tmp_path / f"file{index}.md").write_text("clean", encoding="utf-8")

    assert _security_scan(tmp_path).main() == 0
    assert "60 files scanned" in capsys.readouterr().out


def test_the_security_scan_still_catches_a_real_secret(tmp_path: Path) -> None:
    """Loosening a check must be proven in BOTH directions.

    `mutants` was added to EXCLUDED_DIRS in the same change. This is the partner
    that proves the scan still finds what it must — otherwise "0 findings" above
    could mean the detector was broken rather than the tree clean.

    Turns red if: the env_secret_assignment check stops firing, or the exclusion
    list swallows ordinary source directories.
    """
    for index in range(60):
        (tmp_path / f"file{index}.md").write_text("clean", encoding="utf-8")
    # NB: the literal must not contain the word "placeholder" in any case — the
    # scanner correctly ignores those, and an earlier version of this fixture
    # used "NOTAPLACEHOLDERvalue123", which the check skipped. The test failed
    # for the right reason and the fixture was wrong.
    (tmp_path / "leak.py").write_text('api_key = "hunter2seCretV4lue"\n', encoding="utf-8")

    assert _security_scan(tmp_path).main() == 1


def test_the_generated_mutant_copy_is_excluded_but_real_source_is_not(
    tmp_path: Path,
) -> None:
    """The exclusion must remove the generated copy and nothing else.

    Turns red if: `mutants` is dropped from EXCLUDED_DIRS (the copy's duplicates
    of exempt test files reappear as findings), or if the exclusion is widened
    so that ordinary files stop being read.
    """
    module = _security_scan(tmp_path)
    (tmp_path / "mutants").mkdir()
    (tmp_path / "mutants" / "copy.md").write_text("x", encoding="utf-8")
    (tmp_path / "real.md").write_text("x", encoding="utf-8")

    found = {path.name for path in module._iter_text_files()}

    assert "real.md" in found, "the scan stopped reading ordinary files"
    assert "copy.md" not in found, "the generated mutant copy is being scanned again"


def _valid_requirement_tree(root: Path) -> None:
    """A COMPLETE two-requirement corpus: every check but the floor passes.

    Deliberately valid. The point of the floor is that a *well-formed* corpus
    which has silently shrunk still fails, and only a tree that passes every
    other check can demonstrate that.
    """
    (root / "10-functional-requirements.md").write_text(
        "# Functional Requirements\n\n## FR-001\nThe system shall do one thing.\n"
        "\n## FR-002\nThe system shall do another.\n",
        encoding="utf-8",
    )
    # An NFR section is required too: the gate fails a requirements document
    # that parses to zero sections, independently of the floor.
    (root / "11-non-functional-requirements.md").write_text(
        "# Non-Functional Requirements\n\n## NFR-001\nThe system shall be quick.\n",
        encoding="utf-8",
    )
    header = "| Req ID | Type | Title | Tests | Status |\n|---|---|---|---|---|\n"
    rows = (
        "| FR-001 | Functional | One | TEST-FR-001 | Draft |\n"
        "| FR-002 | Functional | Two | TEST-FR-002 | Draft |\n"
        "| NFR-001 | Non-functional | Quick | TEST-NFR-001 | Draft |\n"
    )
    (root / "17-requirement-registry.md").write_text(
        "# Requirement Registry\n\n" + header + rows, encoding="utf-8"
    )
    (root / "18-requirement-traceability-matrix.md").write_text(
        "# Requirement Traceability Matrix\n\n" + header + rows, encoding="utf-8"
    )


def test_the_requirement_gate_refuses_a_suspiciously_small_corpus(tmp_path: Path) -> None:
    """Parsing 2 requirements where there are 29 must not print OK.

    Every check in that gate is "no requirement lacks a row", vacuously true over
    a corpus that stopped parsing. Measured: truncating the requirements document
    to 2 sections dropped the count from 29 to 14 and the gate still exited 0.

    Turns red if: the --min-requirements comparison is dropped.
    """
    fr = _load("validate_fr_completeness")
    _valid_requirement_tree(tmp_path)

    # The floor must be the ONLY reason this fails. Proven by the partner below:
    # with the floor at 0 the very same tree passes. Measured: the first version
    # of this test used an empty tree, which fails an earlier "no FR sections
    # found" check — so it was green with the floor comparison deleted. A test
    # that fails for the wrong reason is not a test of the thing it names.
    assert fr.main(["--docs-root", str(tmp_path), "--min-requirements", "25"]) == 1
    assert fr.main(["--docs-root", str(tmp_path), "--min-requirements", "0"]) == 0


def test_the_requirement_gate_floor_is_wired_into_the_makefile() -> None:
    """An unregistered floor is not a floor.

    The floor defaults to 0 so the script stays usable against a small synthetic
    document tree; that makes the Makefile the only place it is switched on. This
    repository has already shipped three "blocking gates" that were never named
    in a workflow — the same failure, one layer up.

    Turns red if: `make fr-completeness` stops passing --min-requirements.
    """
    # Comments stripped BEFORE searching. The first version of this test asserted
    # `"--min-requirements" in recipe` and the same commit had added a comment
    # above the recipe explaining the flag — so deleting the real flag left the
    # test GREEN. Anchoring to the invocation fixed that instance; reading only
    # the code fixes the whole class, and is what a future guard should copy.
    recipe = code_without_comments(REPO_ROOT / "Makefile")

    assert "validate_fr_completeness.py --min-requirements" in recipe, (
        "make fr-completeness no longer switches the floor on, so the blocking "
        "gate is back to passing over a corpus that stopped parsing"
    )


def test_the_e2e_floors_are_wired_into_the_workflow() -> None:
    """Same rule for the Playwright lanes: deleting the step must be visible.

    Turns red if: either floor step is removed from e2e.yml, or the script is
    renamed without updating the workflow.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")

    assert workflow.count("scripts/check_e2e_executed.py") == 2, (
        "e2e.yml must invoke the executed-count floor once per blocking lane; "
        f"found {workflow.count('scripts/check_e2e_executed.py')}"
    )


def test_the_diff_cover_floor_is_wired_into_the_makefile() -> None:
    """Turns red if: the diff-cover recipe stops invoking its floor."""
    recipe = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "scripts/check_diff_cover_measured.py" in recipe, (
        "the diff-cover recipe no longer runs its empty-denominator floor"
    )
