"""Guards on the mutation gate's own scoring logic (`MUTMUT_SCOPE_PY`).

`test_makefile_gate_integrity.py` covers gates that go green while running the
*wrong* tests. This module covers the mutation gate going green while running
*nothing at all* — the three fail-open paths found in review:

1. `changed_lines()` read only git's stdout, so a bad/absent base ref (fork PR,
   renamed default branch, transient fetch failure) produced an empty scope and
   the recipe reported "nothing to mutate" and succeeded.
2. `report()` scored `100.0` when zero mutants had metadata, so an absent or
   crashed run looked perfect.
3. The recipe piped `mutmut run` into `tail`, discarding its exit status, and
   never cleaned the gitignored `mutants/` tree, so a crashed run was scored
   against stale metadata from an earlier one.

The scoring code is extracted from the Makefile's `define` block and executed,
so a regression in the real recipe fails here rather than in a prose assertion.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

SCOPE_BLOCK = re.compile(r"^define MUTMUT_SCOPE_PY\n(.*?)^endef$", re.DOTALL | re.MULTILINE)


@pytest.fixture(scope="module")
def scope_script(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The Makefile's MUTMUT_SCOPE_PY block, on disk and runnable."""
    match = SCOPE_BLOCK.search(MAKEFILE.read_text(encoding="utf-8"))
    assert match, "MUTMUT_SCOPE_PY define block not found in the Makefile"
    script = tmp_path_factory.mktemp("mutscope") / "mutscope.py"
    script.write_text(match.group(1), encoding="utf-8")
    return script


def _run(script: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _write_meta(cwd: Path, name: str, exit_codes: dict[str, int | None]) -> None:
    meta = cwd / "mutants" / "src" / "product_app" / f"{name}.py.meta"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({"exit_code_by_key": exit_codes}), encoding="utf-8")


def test_report_fails_when_no_mutants_were_scored(scope_script: Path, tmp_path: Path) -> None:
    """No `mutants/` tree at all means the run did not happen — not a 100%."""
    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert result.returncode != 0, (
        "an absent mutation run scored as a pass; promoting the gate to "
        f"blocking would ship a gate that cannot fail:\n{result.stdout}"
    )
    assert "no mutants were scored" in result.stdout + result.stderr


def test_report_fails_when_every_mutant_is_unrun(scope_script: Path, tmp_path: Path) -> None:
    """Metadata exists but every exit code is null — a crashed/aborted run."""
    _write_meta(tmp_path, "query_runs", {"xǁRunsǁsave__mutmut_1": None})
    result = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert result.returncode != 0, result.stdout
    assert "no mutants were scored" in result.stdout + result.stderr


def test_report_still_scores_a_real_run(scope_script: Path, tmp_path: Path) -> None:
    """The fail-closed guard must not swallow a genuine measurement."""
    _write_meta(
        tmp_path,
        "query_runs",
        {"a__mutmut_1": 1, "b__mutmut_2": 1, "c__mutmut_3": 0},
    )
    result = _run(scope_script, tmp_path, "report", "origin/main", "60")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 killed, 1 survived" in result.stdout
    assert "66.7%" in result.stdout

    below = _run(scope_script, tmp_path, "report", "origin/main", "90")
    assert below.returncode != 0
    assert "BELOW THRESHOLD" in below.stdout


def test_scope_fails_loudly_on_a_bad_base_ref(scope_script: Path) -> None:
    """A base ref git cannot resolve must be a hard error, not an empty scope."""
    result = _run(scope_script, REPO_ROOT, "scope", "origin/does-not-exist-xyz", "90")
    assert result.returncode != 0, (
        "an unresolvable base ref produced an empty scope; the recipe would "
        f"print 'nothing to mutate' and pass:\n{result.stdout}"
    )
    assert "origin/does-not-exist-xyz" in result.stdout + result.stderr


@pytest.fixture(scope="module")
def mutation_recipe() -> str:
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "mutation-baseline"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.replace("\\\n", " ")


def test_recipe_does_not_pipe_mutmut_into_tail(mutation_recipe: str) -> None:
    """A pipe reports the exit status of `tail`, so a mutmut crash looks clean.

    `||` is fine — that is the explicit failure branch — but a single `|`
    between `mutmut run` and the next command separator is the fail-open shape.
    """
    run = re.search(r"mutmut run.*?(?=;)", mutation_recipe, re.DOTALL)
    assert run, f"no `mutmut run` invocation in the recipe:\n{mutation_recipe}"
    assert not re.search(r"(?<!\|)\|(?!\|)", run.group(0)), (
        f"mutmut's exit status is discarded by the pipe: {run.group(0)}"
    )
    assert "|| {" in run.group(0), f"mutmut run has no failure branch: {run.group(0)}"


def test_recipe_clears_stale_mutant_metadata(mutation_recipe: str) -> None:
    """`mutants/` is gitignored, so a stale tree survives across runs."""
    assert "rm -rf mutants" in mutation_recipe, (
        "the recipe does not clear mutants/; a crashed run would be scored "
        f"against a previous run's metadata:\n{mutation_recipe}"
    )
