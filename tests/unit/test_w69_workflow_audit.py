"""W69: ``zizmor``, a GitHub Actions workflow auditor, runs as a blocking check.

The pinning tests in ``test_w69_actions_pinned.py`` hold THIS tree to one rule.
zizmor holds every future workflow edit to that rule and to its other audits
(script injection through ``${{ }}``, credentials left in checkouts, and more),
so a new unpinned action fails CI rather than waiting for the next review.

The contract pinned here:

* ``make workflow-audit`` runs zizmor with ``--offline`` (no network, no token)
  and ``--config .github/zizmor.yml`` over ``.github``, and nothing in the
  recipe can swallow its exit status.
* zizmor comes from ``uv.lock`` through the ``quality`` extra — the same
  install CI already performs — not from ``uvx`` at run time, which would fetch
  whatever version is newest that day.
* The ``validate-and-test`` CI job runs ``make workflow-audit`` as a blocking
  step after it installs the locked dependencies.
* zizmor passes on the real ``.github`` tree.
* Positive partner: with the same config, zizmor FAILS a workflow that uses
  ``actions/checkout@v4`` and reports ``unpinned-uses``, and does not report
  it once that line is pinned to a commit id. That proves the tool really runs
  and the config does not relax pinning for GitHub's own ``actions/*``.
  (zizmor 1.14.2 allowed a tag for ``actions/*`` by default; 1.30.1, measured
  2026-10-14 from the local uv cache, already demands a commit id by default.
  So against a recent zizmor this probe proves the config does not RELAX
  pinning; it cannot prove the config is what demands it.)

The zizmor binary is found next to the running interpreter — the venv ``uv
sync`` built from the lock — never on ``PATH``. A missing binary FAILS: a
skipped audit would be a vacuous pass (AGENTS.md rule 7).

WHAT TURNS THIS FILE RED: delete or rename the ``workflow-audit`` target, drop
``--offline`` or the config from it, run zizmor through ``uvx``, remove zizmor
from the ``quality`` extra or ``uv.lock``, drop the CI step or make it
non-blocking, add a workflow zizmor flags, or relax ``unpinned-uses`` in
``.github/zizmor.yml``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from tests.code_text import code_without_comments
from tests.repo_root import find_repo_root
from tests.unit.test_w68_regressions import _recipe_problems

ROOT = find_repo_root(Path(__file__))
MAKEFILE = ROOT / "Makefile"
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "uv.lock"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CONFIG = ROOT / ".github" / "zizmor.yml"
TARGET = "workflow-audit"
ZIZMOR = Path(sys.executable).parent / "zizmor"

#: zizmor offline reads only local files; 120 s is generous for a few dozen.
_TIMEOUT_SECONDS = 120

_COMMIT_ID = "11d5960a326750d5838078e36cf38b85af677262"


def _recipe_lines(target: str) -> list[str]:
    """``target``'s recipe lines (tab removed), with comments blanked."""
    lines = code_without_comments(MAKEFILE).splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(rf"^{re.escape(target)}\s*:", line)]
    assert len(starts) == 1, f"expected exactly one {target!r} target in the Makefile, got {starts}"
    recipe: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if not line.startswith("\t"):
            break
        if line.strip():
            recipe.append(line[1:])
    return recipe


def _zizmor_args() -> list[str]:
    """The arguments the recipe passes to zizmor (the words after it)."""
    calls = []
    for line in _recipe_lines(TARGET):
        words = shlex.split(line.lstrip("@+"))
        at = [i for i, word in enumerate(words) if Path(word).name == "zizmor"]
        calls += [words[i + 1 :] for i in at]
    assert len(calls) == 1, f"the {TARGET} recipe must call zizmor exactly once: {calls}"
    return calls[0]


def _hermetic_env() -> dict[str, str]:
    """The test's own environment minus every token zizmor could go online with."""
    drop = {"GH_TOKEN", "GITHUB_TOKEN", "ZIZMOR_GITHUB_TOKEN"}
    env = {key: value for key, value in os.environ.items() if key not in drop}
    env["NO_COLOR"] = "1"
    return env


def _run_zizmor(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    assert ZIZMOR.is_file(), (
        f"zizmor is not installed at {ZIZMOR}. It must come from uv.lock via the "
        "`quality` extra (`uv sync --all-extras`). This test fails rather than "
        "skips: a skipped audit is a vacuous pass."
    )
    return subprocess.run(  # noqa: S603 - fixed binary from our own venv, no shell
        [str(ZIZMOR), *args],
        cwd=cwd,
        env=_hermetic_env(),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _findings(proc: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(proc.stdout)
    except ValueError as exc:
        raise AssertionError(
            f"zizmor did not print JSON (exit {proc.returncode}).\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        ) from exc
    assert isinstance(parsed, list), parsed
    return parsed


# ---------------------------------------------------------------------------
# Makefile, pyproject, lock, CI
# ---------------------------------------------------------------------------


def test_the_workflow_audit_target_runs_zizmor_offline_with_the_config() -> None:
    """Red when: there is no ``workflow-audit`` target, it does not call zizmor
    exactly once, or the call lacks ``--offline``, ``--config
    .github/zizmor.yml`` or the ``.github`` input."""
    args = _zizmor_args()
    assert "--offline" in args, args
    config_given = any(
        (args[i] == "--config" and i + 1 < len(args) and args[i + 1] == ".github/zizmor.yml")
        or args[i] == "--config=.github/zizmor.yml"
        for i in range(len(args))
    )
    assert config_given, f"zizmor is not given --config .github/zizmor.yml: {args}"
    assert ".github" in args, f"zizmor is not pointed at .github: {args}"
    assert CONFIG.is_file(), f"{CONFIG.relative_to(ROOT)} does not exist"


def test_the_workflow_audit_recipe_cannot_swallow_a_failure() -> None:
    """Red when: a ``workflow-audit`` recipe line ignores zizmor's exit status
    (a leading ``-``, ``|| true``, ``; exit 0``, a pipe, a trailing ``&``) or
    starts with a variable that could expand to one."""
    lines = _recipe_lines(TARGET)
    assert lines, f"the {TARGET} recipe is empty"
    problems = {line: _recipe_problems(line) for line in lines if _recipe_problems(line)}
    assert not problems, problems


def test_the_workflow_audit_does_not_fetch_zizmor_at_run_time() -> None:
    """Red when: the recipe runs zizmor through ``uvx`` or ``uv tool run``,
    which installs whatever version is newest that day instead of the
    locked one."""
    words = [word for line in _recipe_lines(TARGET) for word in shlex.split(line.lstrip("@+"))]
    assert any(Path(word).name == "zizmor" for word in words), "the recipe never names zizmor"
    assert "uvx" not in words, words
    pairs = list(zip(words, words[1:], strict=False))
    assert ("uv", "tool") not in pairs, words


def test_zizmor_is_a_locked_quality_dependency() -> None:
    """Red when: zizmor is missing from the ``quality`` extra in
    ``pyproject.toml``, from that extra in ``uv.lock``, or has no locked
    version in ``uv.lock``."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    quality = project["optional-dependencies"]["quality"]
    names = {canonicalize_name(Requirement(spec).name) for spec in quality}
    assert "diff-cover" in names, f"the quality extra did not parse as expected: {names}"
    assert "zizmor" in names, f"zizmor is not in the quality extra: {sorted(names)}"

    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    packages = lock["package"]
    roots = [p for p in packages if p.get("name") == project["name"]]
    assert len(roots) == 1, roots
    locked_extra = {d["name"] for d in roots[0]["optional-dependencies"]["quality"]}
    assert "zizmor" in locked_extra, f"uv.lock's quality extra lacks zizmor: {locked_extra}"
    entries = [p for p in packages if p.get("name") == "zizmor"]
    assert len(entries) == 1 and entries[0].get("version"), entries


def _validate_and_test() -> dict[str, Any]:
    workflow = yaml.safe_load(CI.read_text(encoding="utf-8"))
    job: dict[str, Any] = workflow["jobs"]["validate-and-test"]
    return job


def _step_index(steps: list[dict[str, Any]], run: str) -> int:
    matches = [i for i, s in enumerate(steps) if str(s.get("run", "")).strip() == run]
    assert len(matches) == 1, (run, matches, [s.get("run") for s in steps])
    return matches[0]


def test_ci_runs_the_workflow_audit_as_a_blocking_step_after_the_install() -> None:
    """Red when: the ``validate-and-test`` job has no single step whose run is
    exactly ``make workflow-audit``, the step comes before the locked install
    (``uv sync --locked --all-extras``), or it is made non-blocking
    (``continue-on-error`` on the step or the job, or an ``if:`` on the step)."""
    job = _validate_and_test()
    steps = job["steps"]
    install = _step_index(steps, "uv sync --locked --all-extras")
    audit = _step_index(steps, "make workflow-audit")
    assert audit > install, (install, audit)
    assert not job.get("continue-on-error", False), job.get("continue-on-error")
    assert not steps[audit].get("continue-on-error", False), steps[audit]
    assert "if" not in steps[audit], steps[audit]


# ---------------------------------------------------------------------------
# Running zizmor
# ---------------------------------------------------------------------------


def test_zizmor_is_installed_in_the_test_venv() -> None:
    """Red when: the venv running the tests has no zizmor binary — the
    ``quality`` extra lost it, or the install skipped extras. Fails, never
    skips."""
    assert ZIZMOR.is_file(), f"no zizmor at {ZIZMOR}"
    assert os.access(ZIZMOR, os.X_OK), f"{ZIZMOR} is not executable"


def test_zizmor_passes_on_the_real_github_tree() -> None:
    """Red when: zizmor, run with exactly the arguments the ``workflow-audit``
    recipe passes, reports any finding on ``.github`` or cannot run. (zizmor
    exits 3 when it collects no inputs — measured on 1.30.1 — so exit 0 means
    it audited something.)"""
    proc = _run_zizmor(_zizmor_args(), ROOT)
    assert proc.returncode == 0, (
        f"zizmor exit {proc.returncode}\nstdout:\n{proc.stdout[-4000:]}\n"
        f"stderr:\n{proc.stderr[-2000:]}"
    )


def _probe(tmp_path: Path, uses: str) -> list[dict[str, Any]]:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "probe.yml").write_text(
        "name: probe\n"
        "on: push\n"
        "permissions: {}\n"
        "jobs:\n"
        "  probe:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: {uses}\n"
        "        with:\n"
        "          persist-credentials: false\n",
        encoding="utf-8",
    )
    assert CONFIG.is_file(), f"{CONFIG.relative_to(ROOT)} does not exist"
    proc = _run_zizmor(
        ["--offline", "--config", str(CONFIG), "--format", "json", str(tmp_path)], tmp_path
    )
    findings = _findings(proc)
    flagged = [f for f in findings if f.get("ident") == "unpinned-uses"]
    if flagged:
        assert proc.returncode != 0, f"zizmor reported unpinned-uses but exited 0: {flagged}"
    return flagged


def test_the_config_makes_zizmor_reject_a_tag_pinned_github_action(tmp_path: Path) -> None:
    """Red when: ``.github/zizmor.yml`` relaxes ``unpinned-uses`` so a tag is
    enough for ``actions/*`` (or for everything), the config is missing, or
    zizmor does not actually run."""
    flagged = _probe(tmp_path, "actions/checkout@v4")
    assert flagged, "zizmor with the repo config did not flag actions/checkout@v4 as unpinned"


def test_partner_the_config_accepts_a_commit_pinned_github_action(tmp_path: Path) -> None:
    """Partner for the test above (fails now only because zizmor and the
    config do not exist yet).

    Red when: zizmor flags ``unpinned-uses`` on a commit-pinned
    ``actions/checkout`` too — then the finding above would not be about the
    tag at all."""
    assert _probe(tmp_path, f"actions/checkout@{_COMMIT_ID} # v4.2.2") == []
