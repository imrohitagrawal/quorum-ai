"""Guards on `[tool.mutmut].also_copy` — the mutation gate's *input* tree.

`test_mutation_gate_integrity.py` covers the gate scoring nothing. This module
covers the failure one level earlier: the gate never running at all.

mutmut copies the project into `./mutants/` and runs the suite from there, so
every file the suite reads from `REPO_ROOT` must be in `also_copy` (mutmut
copies only `source_paths`, `tests` and `pyproject.toml` by itself). When one
is missing, the stats-collection run fails — measured on this tree with the
`Makefile` absent:

    FileNotFoundError: [Errno 2] No such file or directory: '.../mutants/Makefile'
    FAILED tests/test_quality_ledger_consistency.py::test_ledger_describes_...
    failed to collect stats. runner returned 1

and mutmut aborts before scoring a single mutant. Nothing else in the suite
sees that: the mutation-gate specs all stub the engine out, and the recipe's
advisory `-` plus CI's `continue-on-error` turn the abort into a green job.
So the check has to live here.

The second test performs the real copy and runs the repo-root-reading modules
inside it, which is what actually goes wrong; the first is the cheap static
mirror that names the offending path.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Copied by mutmut itself, without an also_copy entry.
IMPLICIT = {"src", "tests", "pyproject.toml"}

# Root entries the suite names but that must NOT be copied, with the reason the
# absence is safe. `.env` is the security one: a developer's real DSN/API key
# must never reach a mutation run.
EXEMPT = {
    ".claude": "gitignored local settings; its specs skip when absent",
    ".env": "secrets — deliberately never copied (hermetic, $0)",
    "build": "gate artifacts; the specs that read them skip when absent",
    "mutants": "the copy target itself",
}

# Modules that read REPO_ROOT paths and therefore fail inside ./mutants/ when
# an also_copy entry is missing. Kept explicit so the in-copy run stays fast.
ROOT_READING_MODULES = (
    "tests/test_quality_ledger_consistency.py",
    "tests/test_r2_plan_status_honesty.py",
    "tests/unit/test_makefile_gate_integrity.py",
)

_ROOT_PATH_LITERAL = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]*(/[^\s]+)+$")


def _mutmut_config() -> dict[str, Any]:
    config: dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["mutmut"]
    return config


def _copied_roots() -> set[str]:
    config = _mutmut_config()
    roots = set(IMPLICIT)
    roots.update(Path(entry).parts[0] for entry in config["source_paths"])
    roots.update(Path(entry).parts[0] for entry in config["also_copy"])
    return roots


def _referenced_roots() -> dict[str, str]:
    """Repo-root entries named by a string literal in the suite -> its module.

    Two shapes, both real in this suite: `REPO_ROOT / "Makefile"` (an explicit
    division on the root) and the table-driven form — `(REPO_ROOT / a).exists()`
    over `"e2e/tests/invariants/visual-snapshots.spec.ts"` — which is picked up
    as a repo-relative literal. A bare word is deliberately NOT: `"schemas"` is
    an OpenAPI dict key, not the `schemas/` directory, and the filesystem here
    is case-insensitive, so `"Tests"` would resolve to `tests/`.
    """
    entries = {entry.name for entry in REPO_ROOT.iterdir()}
    found: dict[str, str] = {}
    for path in sorted(REPO_ROOT.joinpath("tests").rglob("test_*.py")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        module = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(tree):
            head = ""
            if (
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Div)
                and isinstance(node.left, ast.Name)
                and node.left.id in {"REPO_ROOT", "ROOT"}
                and isinstance(node.right, ast.Constant)
                and isinstance(node.right.value, str)
            ):
                head = node.right.value.split("/", 1)[0]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip()
                if _ROOT_PATH_LITERAL.match(text) and (REPO_ROOT / text).exists():
                    head = text.split("/", 1)[0]
            if head in entries:
                found.setdefault(head, module)
    return found


def test_every_root_path_the_suite_reads_is_copied_into_mutants() -> None:
    """A root entry the suite reads but mutmut does not copy aborts the gate."""
    copied = _copied_roots()
    missing = {
        head: module
        for head, module in _referenced_roots().items()
        if head not in copied and head not in EXEMPT
    }
    assert not missing, (
        "these repo-root entries are read by the suite but are absent inside "
        "./mutants/, so `mutmut run` fails to collect stats and scores zero "
        "mutants — add them to [tool.mutmut].also_copy (or to EXEMPT with the "
        f"reason the absence is safe): {missing}"
    )


def test_exempt_entries_are_not_also_copied() -> None:
    """EXEMPT is a claim about what must stay out — hold `also_copy` to it."""
    also_copy = {Path(entry).parts[0] for entry in _mutmut_config()["also_copy"]}
    leaked = sorted(also_copy & set(EXEMPT))
    assert not leaked, f"also_copy copies entries documented as excluded: {leaked}"


def test_the_real_copy_runs_the_root_reading_specs(tmp_path: Path) -> None:
    """Do what mutmut does — copy, then run the specs that read REPO_ROOT.

    The static check above only knows about paths spelled as literals; this one
    fails for any reason the real copy is incomplete.
    """
    config = _mutmut_config()
    for entry in sorted(set(config["also_copy"]) | IMPLICIT | set(config["source_paths"])):
        source = REPO_ROOT / entry
        if not source.exists():
            continue
        destination = tmp_path / entry
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, destination)
        else:
            shutil.copytree(source, destination, dirs_exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *ROOT_READING_MODULES,
            "-q",
            "--no-cov",
            "-p",
            "no:randomly",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        # Strip pytest-cov's subprocess hooks: the child would otherwise measure
        # the *copied* src/ and its data would be combined into the parent run,
        # dropping total coverage from 88% to 63% and failing --cov-fail-under.
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("COV_CORE", "COVERAGE"))
        },
    )
    assert result.returncode == 0, (
        "the suite fails inside a mutmut-shaped copy of the tree, so "
        "`make mutation-baseline` aborts with 'failed to collect stats' before "
        f"scoring a mutant:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
