"""Every invariant spec must be NAMED in the e2e workflow, or it never runs.

`.github/workflows/e2e.yml` enumerates spec PATHS explicitly — there is no glob,
no `testDir` run — so a new spec can be committed, pass locally, and silently
never execute in CI (UI-1). This gate globs the invariant spec directory and
asserts each basename appears in the workflow text, so a new blocking spec
cannot be added without wiring it. Snapshot baselines are asserted only for
snapshot dirs that already exist (an advisory visual spec whose baselines a
human has not yet seeded must not red the build).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INVARIANTS_DIR = REPO_ROOT / "e2e" / "tests" / "invariants"
# OD-2 review finding: gate-family dirs added later (e.g. tests/ops/) sat
# outside this guard, recreating the exact silently-never-runs failure mode
# it exists to prevent. Every dir listed here is swept the same way.
GATED_SPEC_DIRS = (
    INVARIANTS_DIR,
    REPO_ROOT / "e2e" / "tests" / "ops",
)
E2E_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "e2e.yml"


def _invariant_specs() -> list[Path]:
    return sorted(p for d in GATED_SPEC_DIRS for p in d.glob("*.spec.ts"))


def test_the_invariants_dir_and_workflow_exist() -> None:
    assert INVARIANTS_DIR.is_dir(), f"missing {INVARIANTS_DIR}"
    assert E2E_WORKFLOW.is_file(), f"missing {E2E_WORKFLOW}"
    assert _invariant_specs(), "no invariant specs found — glob is wrong"


@pytest.mark.parametrize("spec", [p.name for p in _invariant_specs()])
def test_every_invariant_spec_is_named_in_the_e2e_workflow(spec: str) -> None:
    workflow = E2E_WORKFLOW.read_text(encoding="utf-8")
    assert spec in workflow, (
        f"{spec} exists under e2e/tests/invariants/ but is not named in "
        f"e2e.yml — it would be committed, green locally, and never run in CI"
    )


def test_every_existing_snapshot_dir_has_a_chromium_linux_baseline() -> None:
    snapshot_dirs = sorted(INVARIANTS_DIR.glob("*-snapshots"))
    # No snapshot dirs yet (baselines seeded in CI by a human) ⇒ nothing to
    # assert; this must not red before the seeding step runs.
    missing = [
        str(d.relative_to(REPO_ROOT))
        for d in snapshot_dirs
        if not list(d.glob("*-chromium-linux.png"))
    ]
    assert not missing, f"snapshot dirs with no chromium/linux baseline: {missing}"
