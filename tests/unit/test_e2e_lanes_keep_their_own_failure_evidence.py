"""W121: every browser lane in the E2E job keeps its own failure evidence.

The job runs five ``npx playwright test`` lanes one after another. Playwright
empties its output folder when a run starts, and every lane used the default
``e2e/test-results/``, so each lane deleted the traces and screenshots of the
lane before it. The uploaded artifact held only the last lane's output: the
signed-in lane's failures on 2026-10-29 and 2026-10-30 left nothing to read.
Each lane now writes to its own sibling folder under ``test-results/``, and the
upload, which runs whether or not a lane failed, takes all of them.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import yaml
from tests.repo_root import find_repo_root

ROOT = find_repo_root(Path(__file__))
WORKFLOW = ROOT / ".github" / "workflows" / "e2e.yml"

LANE_OUTPUTS = {
    "test-results/invariants",
    "test-results/parity",
    "test-results/workspace",
    "test-results/signed-in",
    "test-results/visual",
}


def _steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _runs_playwright_test(step: dict[str, Any]) -> bool:
    words = shlex.split(str(step.get("run", "")))
    return any(a == "playwright" and b == "test" for a, b in zip(words, words[1:], strict=False))


def _playwright_steps() -> list[dict[str, Any]]:
    return [s for s in _steps() if _runs_playwright_test(s)]


def _outputs(step: dict[str, Any]) -> list[str]:
    """Every output folder the command names, in either form Playwright reads
    (``--output=DIR`` or ``--output DIR``); the last one wins."""
    words = shlex.split(str(step["run"]))
    found = [w.split("=", 1)[1] for w in words if w.startswith("--output=")]
    found += [after for word, after in zip(words, words[1:], strict=False) if word == "--output"]
    return found


def test_each_lane_writes_its_failure_evidence_to_its_own_folder() -> None:
    """RED-IF a lane has no ``--output`` (it falls back to ``test-results/`` and
    empties the folder holding the other lanes' traces), two lanes share one,
    one folder sits inside another, or a lane runs outside ``e2e/``. A lane
    started another way (``npx --yes playwright test``, ``npm exec --
    playwright test``) is found too. Partner: exactly the five lanes are found."""
    steps = _playwright_steps()
    assert len(steps) == 5, [s.get("name") for s in steps]
    seen = []
    for step in steps:
        outputs = _outputs(step)
        assert len(outputs) == 1, (step.get("name"), outputs)
        assert step.get("working-directory") == "e2e", step.get("name")
        seen.append(outputs[0])
    assert sorted(seen) == sorted(LANE_OUTPUTS)


def test_the_upload_takes_every_lane_folder_even_when_a_lane_failed() -> None:
    """RED-IF the upload runs only on success (a failed lane would upload
    nothing), no longer includes ``e2e/test-results/``, the parent of every
    lane's folder, or excludes anything from it (``!**/trace.zip``). Partner:
    the upload step is found."""
    uploads = [s for s in _steps() if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    report = [s for s in uploads if s.get("with", {}).get("name") == "playwright-report"]
    assert len(report) == 1, [s.get("name") for s in uploads]
    step = report[0]
    assert step.get("if") == "${{ !cancelled() }}"
    paths = str(step["with"]["path"]).split()
    assert "e2e/test-results/" in paths, paths
    assert not [p for p in paths if p.startswith("!")], paths
