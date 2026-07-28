"""Proves the mutation gate actually blocks (#130), on both of its switches.

`test_mutation_gate_integrity.py` covers the scoring logic going green while
measuring nothing. This module covers the one thing nothing else executes:
whether a below-threshold score reaches make, and reaches GitHub Actions.

There were TWO advisory switches, and the issue named only one. Removing
`continue-on-error: true` from the CI job would have changed nothing on its
own, because the Makefile recipe carried a leading `-` that swallowed every
failure inside the run — mutmut crashing, zero mutants scored, and the
below-threshold report alike. Both are now gone and both are pinned here.

The exit-status plumbing is the subtle half: "the report step already exits
non-zero below threshold" is a claim about *shell exit-status plumbing*, and it
is only true if the report step's status is the one make sees.

The fail-open shape found in review was:

    ... | $(PYTHON) - report ... | tee build/mutation/score.txt

`tee` is the last command of the pipeline, so make sees tee's 0 no matter what
the report exits with. Had that shape survived the promotion, the result would
be a gate that is green at any mutation score, forever, silently. The
status-preserving shape is
`> build/mutation/score.txt; status=$?; cat ...; exit $status`.

So this asserts by *execution*: the real recipe is lifted out of the Makefile
verbatim, pointed at a stub report that fails, and make must exit non-zero.
`_run_recipe` takes the Makefile text as an argument so the same harness can be
pointed at a mutated recipe to show it red — which
`test_the_harness_would_notice_a_recipe_that_cannot_fail` does, by re-adding
the `-` and requiring the same run to pass.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

TARGET = "mutation-baseline:"

# The stub stands in for $(PYTHON): `scope` yields one in-scope function so the
# recipe takes its work branch, `report` fails the way a below-threshold run does.
# The recipe invokes it as `$(PYTHON) - <mode> ...`, where `-` means "script on
# stdin"; the stub is a real file, so it drops that leading argument itself.
STUB_PY = """\
import sys

sys.stdin.read()
args = [arg for arg in sys.argv[1:] if arg != "-"]
if args[0] == "scope":
    print("product_app.stub.x_f__mutmut_*")
else:
    print("mutation score = 10.0% (threshold 90%)")
    print("BELOW THRESHOLD")
    raise SystemExit(1)
"""


def recipe_lines(makefile_text: str) -> list[str]:
    lines = makefile_text.splitlines()
    start = lines.index(TARGET) + 1
    end = start
    while end < len(lines) and lines[end].startswith("\t"):
        end += 1
    body = lines[start:end]
    assert body, "mutation-baseline recipe body not found in the Makefile"
    return body


def _run_recipe(makefile_text: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the SHIPPED recipe verbatim against a failing report.

    Until #130 this harness stripped a leading `-` first, because the shipped
    recipe was advisory and the question was whether promoting it *would* work.
    The recipe is now blocking as shipped, so nothing is stripped: what runs
    here is the real text, and a below-threshold report must fail it.
    """
    body = recipe_lines(makefile_text)
    promoted = list(body)

    (tmp_path / "stub.py").write_text(STUB_PY, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub_python = bin_dir / "stub-python"
    stub_python.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{tmp_path}/stub.py" "$@"\n', encoding="utf-8"
    )
    stub_python.chmod(0o755)
    # `uv run mutmut run ...` must succeed so control reaches the report step.
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)

    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "DIFF_BASE ?= origin/main\n"
        "MUTATION_MIN_SCORE ?= 90\n"
        "MUTMUT_MAX_CHILDREN ?= 8\n"
        "UV_CACHE_DIR ?= .uv-cache\n"
        "export MUTMUT_SCOPE_PY\n"
        f"{TARGET}\n" + "\n".join(promoted) + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["make", "--no-print-directory", "mutation-baseline", f"PYTHON={stub_python}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "MUTMUT_SCOPE_PY": "unused-by-the-stub"},
    )


def test_the_shipped_recipe_fails_a_below_threshold_run(tmp_path: Path) -> None:
    """The whole point of #130, asserted by execution rather than by reading.

    Turns red if: the leading `-` is put back on the recipe's `if` line — make
    then exits 0 on a below-threshold report and the gate enforces nothing.
    Verified by re-adding it.
    """
    result = _run_recipe(MAKEFILE.read_text(encoding="utf-8"), tmp_path)
    assert "BELOW THRESHOLD" in result.stdout, (
        "the report step never ran; the harness is not exercising the gate:\n"
        f"{result.stdout}{result.stderr}"
    )
    assert result.returncode != 0, (
        "the shipped recipe exits 0 on a below-threshold report — the mutation "
        "gate is green at any score, which is what #130 removed:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_the_harness_would_notice_a_recipe_that_cannot_fail(tmp_path: Path) -> None:
    """Positive partner for the test above: prove the harness can go green.

    A harness that reds no matter what proves nothing about the recipe. Putting
    the advisory `-` back must make the same run pass, so the assertion above
    is measuring the recipe and not an unconditional failure somewhere in the
    stub, the stub PATH, or make itself.

    Turns red if: `_run_recipe` stops actually running make (a typo in the stub
    path, a missing `uv` shim) — then this exits non-zero too and the pair
    above becomes meaningless.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    body = recipe_lines(text)
    demoted = "\n".join(re.sub(r"^\t@if ", "\t-@if ", line) for line in body)
    assert demoted != "\n".join(body), (
        "could not re-add the advisory `-` — the recipe has been restructured "
        f"and this harness no longer models it:\n{body}"
    )
    patched = text.replace("\n".join(body), demoted, 1)
    result = _run_recipe(patched, tmp_path)
    assert result.returncode == 0, (
        "the advisory form ALSO fails, so the blocking test above is not "
        f"measuring the `-`:\n{result.stdout}{result.stderr}"
    )


def test_recipe_carries_no_advisory_dash() -> None:
    """Static twin of the execution test: the switch stays off.

    Turns red if: any line of the recipe regains a leading `-`.
    """
    body = recipe_lines(MAKEFILE.read_text(encoding="utf-8"))
    offenders = [line for line in body if line.startswith("\t-")]
    assert not offenders, (
        "the mutation gate is advisory again — a `-`-prefixed recipe line "
        f"swallows every failure inside the run (#130): {offenders}"
    )


def test_report_step_status_is_not_swallowed_by_a_pipe() -> None:
    """Static twin of the above: the report must not end a pipeline it doesn't own."""
    body = "\n".join(recipe_lines(MAKEFILE.read_text(encoding="utf-8")))
    report = re.search(r"- report .*?(?=;)", body, re.DOTALL)
    assert report, f"no `report` invocation in the recipe:\n{body}"
    assert "|" not in report.group(0), (
        "the report's exit status is discarded by a downstream pipe stage "
        f"(tee/cat): {report.group(0)}"
    )


def _mutation_job_block() -> list[str]:
    """The `mutation-baseline:` job's lines, up to the next job at the same indent."""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "mutation-baseline:")
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith("    ")):
        end += 1
    block = lines[start:end]
    assert len(block) > 10, f"mutation job block looks truncated: {block}"
    return block


def _job_level_lines(block: list[str]) -> list[str]:
    """Only the job's own keys (4-space indent) — never a step's keys."""
    return [line for line in block if re.match(r"^    [a-z]", line)]


def test_the_ci_job_is_advisory_and_says_why() -> None:
    """Advisory is a MEASURED decision here, and must carry its evidence.

    An advisory gate with no recorded reason is how this one drifted: #130
    found it advisory, could not find why, and promoted it on a runtime figure
    that turned out to be an abort. So the flag must be present AND the block
    must name the study justifying it, or the next reader repeats #130.

    Turns red if: `continue-on-error` is removed (promoting the gate without
    re-measuring), or the justifying study reference is deleted.
    """
    block = _mutation_job_block()
    job_level = [line for line in _job_level_lines(block) if "continue-on-error" in line]
    assert job_level, (
        "the mutation job no longer declares itself advisory. Promoting it "
        "needs a fresh measurement, not a runtime figure — measured yield was "
        "6 of 158 escaped defects with a 7% false-abort rate "
        "(docs/metrics/mutation-gate-study.md)"
    )
    assert any("mutation-gate-study.md" in line for line in block), (
        "the advisory status has no recorded justification in the job — "
        "exactly the state #130 found and mis-diagnosed"
    )


def test_the_ci_job_name_matches_its_effective_status() -> None:
    """The name must never disagree with the flag, in either direction.

    Turns red if: the job is made blocking but keeps an "advisory" name, or
    stays advisory while the name drops the word.
    """
    lines = _job_level_lines(_mutation_job_block())
    names = [line for line in lines if line.strip().startswith("name:")]
    assert len(names) == 1, f"expected exactly one job-level name: {names}"
    is_advisory = any("continue-on-error" in line for line in lines)
    says_advisory = "advisory" in names[0].lower()
    assert is_advisory == says_advisory, (
        f"the job name and its effective status disagree: name={names[0].strip()!r}, "
        f"continue-on-error={is_advisory}"
    )


def test_no_step_in_the_job_carries_continue_on_error() -> None:
    """The step-level escape hatch is the one that evades the promotion.

    `tests/test_doc_gate_consistency.py` treats ANY downgraded `run:` step as a
    downgraded gate, and deliberately so: loosening it to "all run steps" would
    let a genuinely downgraded gate step hide behind one blocking sibling. So
    the promotion cannot be paid for with a step-level flag anywhere in this
    job — including on the doc-honesty step, which gets its leniency from
    skipping off the hardware profile instead (see
    `tests/test_mutation_baseline_doc.py`).

    Turns red if: `continue-on-error: true` is added to any step here —
    verified by adding it to the doc-honesty step.
    """
    block = _mutation_job_block()
    job_level = set(_job_level_lines(block))
    offenders = [
        line.strip()
        for line in block
        if "continue-on-error" in line
        and not line.strip().startswith("#")
        and line not in job_level  # the JOB-level flag is the deliberate one
    ]
    assert not offenders, (
        "a STEP in the mutation job carries continue-on-error. The job-level "
        "flag is the deliberate, recorded advisory switch; a step-level one is "
        "an evasion that also makes the doc-status guard misreport which steps "
        f"can fail: {offenders}"
    )
    # Positive partner: the job really does contain the steps this is scanning,
    # so an empty/mis-sliced block cannot satisfy the negative above.
    assert any("make mutation-baseline" in line for line in block), (
        f"the job block does not contain the gate step — bad slice: {block}"
    )


def test_the_doc_honesty_artifact_tier_skips_off_the_recorded_hardware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The leniency has to live SOMEWHERE, and this is where it lives now.

    The artifact tier compares macOS-recorded killed/timeout counts against
    whatever the runner produced, and baseline §5 records that split as
    hardware- and load-dependent. With the job blocking and no step-level flag
    available, the tier must decline to compare rather than fail — otherwise
    the promotion turns a documented, accepted hardware difference into a merge
    blocker.

    This asserts the BEHAVIOUR, not the presence of the string "sys.platform".
    An earlier version of this test grepped for that string; adversarial review
    pointed out that flipping `_DOC_HARDWARE_PROFILE` to "linux", or inverting
    the comparison, keeps a grep green while producing exactly the failure the
    test claims to prevent. So the decision function is imported and called.

    Turns red if: the platform guard is removed, inverted, or repointed at the
    CI runner's platform — all three make the Linux case return "" (compare).
    """
    module = importlib.import_module("tests.test_mutation_baseline_doc")
    artifact = tmp_path / "score.txt"
    artifact.write_text(
        "mutants scored: 336 killed, 43 survived, 123 timeout (excluded), 2 no-tests\n"
        "mutation score (killed / (killed+survived)) = 88.7% (threshold 80%)\n",
        encoding="utf-8",
    )

    # NEGATIVE: on the CI runner's platform the tier must decline to compare.
    monkeypatch.setattr(module.sys, "platform", "linux")
    assert module._skip_unless_comparable(artifact), (
        "on Linux the artifact tier still compares counts the doc itself calls "
        "hardware-dependent — inside a job that now blocks"
    )

    # POSITIVE partner: on the profile the doc DOES record, it must compare.
    # Without this the assertion above is satisfied by a function that skips
    # unconditionally, i.e. by a check that never checks anything.
    monkeypatch.setattr(module.sys, "platform", "darwin")
    assert module._skip_unless_comparable(artifact) == "", (
        "the artifact tier skips even on macOS, so it compares nothing anywhere"
    )
