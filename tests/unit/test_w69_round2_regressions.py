"""W69 round 2 review: regressions for the holes the reviewers reproduced.

1. The round-1 tests read the ``workflow-audit`` recipe as TEXT, so three
   ways of weakening the audit passed them: another output flag
   (``--format=sarif`` and ``--fix=all`` both make zizmor exit 0 with a
   finding present), a second recipe for the same target written through a
   variable (make runs the LAST one and only warns "overriding"), and a flag
   smuggled in through a variable the text check cannot expand. The test
   below takes the exact command ``make -n workflow-audit`` prints, runs it
   against a planted finding, and requires a non-zero exit. Its partner runs
   the same command on a clean workflow and requires exit 0, so it cannot
   pass by the command always failing.
2. zizmor honours a ``.gitignore`` inside the directory it audits: a
   ``.github/.gitignore`` naming ``workflows/ci.yml`` hid that file from the
   audit. (Measured with zizmor 1.30.1: ``.ignore``, ``.fdignore`` and
   ``.rgignore`` there are NOT honoured, and neither is a ``.gitignore`` in
   the directory above ``.github``.)
3. ``deploy_gate.main()`` compares ``GITHUB_REF`` case-sensitively; nothing
   pinned that, so ``(ref or "").lower()`` let ``refs/heads/MAIN`` proceed
   with every test green.

WHAT TURNS THIS FILE RED: any change to the ``workflow-audit`` target that
makes the command make runs exit 0 on a template-injection finding, or
non-zero on a clean workflow; a second recipe for that target; a
``.gitignore`` anywhere under ``.github``; ``deploy_gate.main()`` proceeding
on a manual dispatch from ``refs/heads/MAIN`` or ``refs/heads/Main``.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.repo_root import find_repo_root
from tests.unit.test_w69_manual_deploy_main_only import _dispatch_env, _outputs, gate
from tests.unit.test_w69_workflow_audit import _hermetic_env

ROOT = find_repo_root(Path(__file__))
GITHUB = ROOT / ".github"
CONFIG = GITHUB / "zizmor.yml"

#: ``make -n`` reads the Makefile and prints; ``uv run zizmor`` offline over
#: one file takes seconds. Generous so a loaded CI runner does not time out.
_TIMEOUT_SECONDS = 180

_COMMIT_ID = "11d5960a326750d5838078e36cf38b85af677262"

#: GNU make 3.81 says "overriding commands" / "ignoring old commands"; 4.x
#: says "overriding recipe" / "ignoring old recipe".
_OVERRIDE_WARNING = re.compile(r"warning: (overriding|ignoring old) (commands|recipe) for target")

_WORKFLOW = """\
name: x
on: push
permissions: {{}}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{commit}
        with:
          persist-credentials: false
      - run: {run}
"""
_CLEAN_RUN = "echo hello"
_INJECTION_RUN = 'echo "${{ github.event.pull_request.title }}"'


def _make_env() -> dict[str, str]:
    """No inherited MAKEFLAGS: ``make test`` may be the test's parent."""
    drop = {"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES"}
    return {key: value for key, value in _hermetic_env().items() if key not in drop}


def _audit_command() -> str:
    """The one command ``make -n workflow-audit`` says make would run."""
    printed = subprocess.run(
        ["make", "-n", "workflow-audit"],  # noqa: S607 - make from PATH, as CI runs it
        cwd=ROOT,
        env=_make_env(),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert printed.returncode == 0, printed.stderr
    overrides = [line for line in printed.stderr.splitlines() if _OVERRIDE_WARNING.search(line)]
    assert not overrides, f"a second recipe overrides workflow-audit: {overrides}"
    lines = [line for line in printed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"workflow-audit must run exactly one command: {lines}"
    words = shlex.split(lines[0])
    calls = [word for word in words if Path(word).name == "zizmor"]
    assert len(calls) == 1, f"workflow-audit must call zizmor exactly once: {lines[0]}"
    return lines[0]


def _run_audit_on(tree: Path) -> subprocess.CompletedProcess[str]:
    """Run make's exact command with its input ``.github`` swapped for ``tree``'s.

    Run from the repository root, so ``--config .github/zizmor.yml`` still
    resolves to the real config."""
    words = shlex.split(_audit_command())
    inputs = [i for i, word in enumerate(words) if word == ".github"]
    assert len(inputs) == 1, f"the command does not audit .github exactly once: {words}"
    words[inputs[0]] = str(tree / ".github")
    return subprocess.run(  # noqa: S603 - make's own recipe, run as make would
        ["/bin/sh", "-c", shlex.join(words)],
        cwd=ROOT,
        env=_make_env(),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _tree(tmp_path: Path, run: str) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "x.yml").write_text(_WORKFLOW.format(commit=_COMMIT_ID, run=run), encoding="utf-8")
    shutil.copyfile(CONFIG, tmp_path / ".github" / "zizmor.yml")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. The command make runs fails on a finding
# ---------------------------------------------------------------------------


def test_the_command_make_runs_fails_on_a_planted_injection(tmp_path: Path) -> None:
    """Red when: the command ``make -n workflow-audit`` prints exits 0 on a
    workflow with a template injection (``--format=sarif``, ``--fix=all``,
    ``--no-exit-codes`` or ``|| true`` on the recipe, directly or through a
    variable), or a second recipe overrides the target."""
    result = _run_audit_on(_tree(tmp_path, _INJECTION_RUN))
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"the audit passed a planted injection:\n{output}"
    assert "template-injection" in output, output


def test_partner_the_command_make_runs_passes_a_clean_workflow(tmp_path: Path) -> None:
    """Red when: the same command fails on a clean, pinned workflow (so the
    test above could pass because the command always fails)."""
    result = _run_audit_on(_tree(tmp_path, _CLEAN_RUN))
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# 2. No .gitignore under .github hides a workflow from zizmor
# ---------------------------------------------------------------------------


def _github_walk() -> list[Path]:
    return sorted(Path(d) / f for d, _, files in os.walk(GITHUB) for f in files)


def test_no_gitignore_under_github() -> None:
    """Red when: a ``.gitignore`` exists anywhere under ``.github`` (zizmor
    skips the files it names, so the audit passes without reading them)."""
    found = [str(p.relative_to(ROOT)) for p in _github_walk() if p.name == ".gitignore"]
    assert not found, f"zizmor would skip what these ignore: {found}"


def test_partner_the_gitignore_walk_reads_the_workflows() -> None:
    """Red when: the walk misses ``.github/workflows/ci.yml`` (so the check
    above would be true over nothing)."""
    assert GITHUB / "workflows" / "ci.yml" in _github_walk()


# ---------------------------------------------------------------------------
# 3. The manual-dispatch ref check is case-sensitive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["refs/heads/MAIN", "refs/heads/Main"])
def test_a_dispatch_from_main_in_another_case_fails_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str
) -> None:
    """Red when: ``deploy_gate.main()`` compares ``GITHUB_REF`` ignoring case,
    so a branch named ``MAIN`` or ``Main`` deploys on a manual dispatch."""
    out = _dispatch_env(monkeypatch, tmp_path, ref)
    assert gate.main() == 1
    assert _outputs(out) == ["proceed=false"]
