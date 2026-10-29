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
import re
import shutil
import subprocess
import sys
import tomllib
import warnings
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from tests.subprocess_env import env_without_coverage

# Deselected under mutmut: this module drives git/make/pytest against the real
# REPO_ROOT, which does not exist inside mutmut's ./mutants/ copy. It still runs
# blocking in the ordinary suite.
pytestmark = pytest.mark.repo_introspection

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Copied by mutmut itself, without an also_copy entry.
IMPLICIT = {"src", "tests", "pyproject.toml"}

# Root entries the suite names but that must NOT be copied, with the reason the
# absence is safe. `.env` is the security one: a developer's real DSN/API key
# must never reach a mutation run.
EXEMPT = {
    ".claude": "gitignored local settings; its specs skip when absent",
    # MUST NOT be copied. Its ABSENCE from ./mutants/ is the mechanism
    # `tests/repo_root.find_repo_root` relies on: the helper walks up to the
    # first ancestor holding a `.git`, so from inside the copy it reaches the
    # REAL repository -- which is the whole point (#158). Copying `.git` here
    # would make the copy look like a repository root and reinstate the bug the
    # helper exists to remove. Read by
    # tests/unit/test_open_work_matches_reality.py, which asserts the module
    # resolved a real root rather than a generated copy.
    ".git": (
        "deliberately absent: find_repo_root resolves past the copy BECAUSE the "
        "copy has no .git; copying it would defeat the helper"
    ),
    ".env": "secrets — deliberately never copied (hermetic, $0)",
    "build": "gate artifacts; the specs that read them skip when absent",
    "mutants": "the copy target itself",
    # `"README.md"` WAS exempt here as a false positive of `_ROOT_FILE_LITERAL`,
    # on the grounds that the only literal in the suite was the right operand of
    # `VENDOR_DIR / "README.md"` (i.e. `src/product_app/static/vendor/README.md`,
    # already copied under `src/`). That entry stated its own cost: *"if a future
    # test really does read the ROOT `README.md`, this gate will now stay silent
    # about it."*
    #
    # Removed 2026-09-01 (W17), because that future arrived.
    # `tests/test_doc_gate_consistency.py` Part G reads the ROOT `README.md` to
    # pin the four default model slot ids it states against
    # `model_slots.DEFAULT_MODEL_IDS`, so the read is now genuine and
    # `README.md` is in `also_copy`. The exemption's own instruction —
    # `grep -rn '"README.md"' tests/` — is what settled it: the literal at
    # `tests/test_doc_gate_consistency.py:2238` is a root read, not a vendor one.
}

# Modules that read REPO_ROOT paths and therefore fail inside ./mutants/ when
# an also_copy entry is missing. Kept explicit so the in-copy run stays fast.
ROOT_READING_MODULES = (
    "tests/test_quality_ledger_consistency.py",
    "tests/test_r2_plan_status_honesty.py",
    "tests/unit/test_makefile_gate_integrity.py",
    "tests/unit/test_skill_router_placeholder.py",
    "tests/test_doc_gate_consistency.py",
    "tests/contract/test_golden_fixture_matches_served_schema.py",
    # Reads e2e/playwright.config.ts and e2e/fixtures/ (W41, ADR-0149). The
    # static check above then saw only the root entry `e2e`, which `e2e/tests`
    # already covered, so it could not see these two were missing: the
    # mutation gate then failed to collect stats on PR #546. Since W116 the
    # static check compares full paths (the same hole let `e2e/servers` through
    # on the #596 probe).
    "tests/unit/test_trust_score_visual_tolerance.py",
)

_ROOT_PATH_LITERAL = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]*(/[^\s]+)+$")

# A root entry named with no directory component at all — `"PRODUCT_IDEA.md"`,
# as `scripts/skill_router.py` and its spec name it. `_ROOT_PATH_LITERAL`
# requires a `/`, so this shape was invisible to the check until a real
# `mutmut run` aborted on it (DEBT-008 handback, 2026-07-20). A suffix is
# required so that bare words which merely collide with a root entry name
# under a case-insensitive filesystem (`"tests"`, `"schemas"`) stay excluded.
_ROOT_FILE_LITERAL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*\.[A-Za-z0-9]+$")


def _mutmut_config() -> dict[str, Any]:
    config: dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["mutmut"]
    return config


def _copied_paths() -> set[PurePosixPath]:
    config = _mutmut_config()
    return {
        PurePosixPath(entry) for entry in (*IMPLICIT, *config["source_paths"], *config["also_copy"])
    }


def _is_copied(path: str, copied: set[PurePosixPath]) -> bool:
    """``path`` is inside ``./mutants/`` when a copied entry is ``path`` itself
    or one of its parent folders.

    Until W116 this compared first parts only, so ``e2e/tests`` in ``also_copy``
    counted every ``e2e/...`` path as copied, and ``e2e/servers`` was missing
    from the copy on the #596 probe while this check stayed green.

    One allowance, recorded rather than hidden: a FOLDER only part of which is
    copied (``e2e``, when ``e2e/tests`` is) counts as copied. A bare folder
    reference (``E2E = ROOT / "e2e"``, a working directory) says nothing about
    which file under it is read, so this check cannot judge it.
    """
    target = PurePosixPath(path)
    return any(
        entry == target or entry in target.parents or target in entry.parents for entry in copied
    )


def _root_chain(node: ast.AST) -> str | None:
    """The full path of ``ROOT / "a" / "b/c"`` (``"a/b/c"``), or None."""
    parts: list[str] = []
    while (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant)
        and isinstance(node.right.value, str)
    ):
        parts.append(node.right.value)
        node = node.left
    if parts and isinstance(node, ast.Name) and node.id in {"REPO_ROOT", "ROOT"}:
        return "/".join(reversed(parts))
    return None


def _root_paths_in(tree: ast.AST) -> list[str]:
    """Repo-relative paths a module names: each ``ROOT / ...`` chain WHOLE
    (only the outermost ``/`` of a chain, so ``ROOT / "e2e" / "servers"`` is
    one path, not also ``e2e``), and each repo-relative string literal that
    exists in the tree."""
    inner = {
        id(node.left)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    }
    paths: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and id(node) not in inner:
            chain = _root_chain(node)
            if chain is not None:
                paths.append(chain)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.strip()
            if (_ROOT_PATH_LITERAL.match(text) and (REPO_ROOT / text).exists()) or (
                _ROOT_FILE_LITERAL.match(text) and (REPO_ROOT / text).is_file()
            ):
                paths.append(text)
    return paths


def _deselected_markers() -> set[str]:
    """The markers ``[tool.mutmut].pytest_add_cli_args`` deselects with ``-m``
    (``not env_oracle and not repo_introspection``): a module carrying one never
    runs inside ./mutants/, so what it reads cannot stop the mutation run."""
    args = _mutmut_config()["pytest_add_cli_args"]
    expression = args[args.index("-m") + 1]
    return set(re.findall(r"\bnot\s+(\w+)", expression))


def _is_deselected(tree: ast.Module, deselected: set[str]) -> bool:
    """True when a module-level ``pytestmark`` names a deselected marker."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            names = {n.attr for n in ast.walk(node.value) if isinstance(n, ast.Attribute)}
            if names & deselected:
                return True
    return False


def _referenced_paths() -> dict[str, str]:
    """Repo-relative paths named by the suite -> the first module naming it.

    Two shapes, both real in this suite: `REPO_ROOT / "Makefile"` (an explicit
    division on the root, kept whole when chained) and the table-driven form —
    `(REPO_ROOT / a).exists()` over `"e2e/tests/invariants/visual-snapshots.spec.ts"`
    — which is picked up as a repo-relative literal. A bare word is
    deliberately NOT: `"schemas"` is an OpenAPI dict key, not the `schemas/`
    directory, and the filesystem here is case-insensitive, so `"Tests"` would
    resolve to `tests/`. A path that does not exist in the tree is skipped:
    mutmut cannot copy it either.
    """
    entries = {entry.name for entry in REPO_ROOT.iterdir()}
    deselected = _deselected_markers()
    found: dict[str, str] = {}
    for path in sorted(REPO_ROOT.joinpath("tests").rglob("test_*.py")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        module = str(path.relative_to(REPO_ROOT))
        if _is_deselected(tree, deselected):
            continue
        for named in _root_paths_in(tree):
            if named.split("/", 1)[0] in entries and (REPO_ROOT / named).exists():
                found.setdefault(named, module)
    return found


def test_every_root_path_the_suite_reads_is_copied_into_mutants() -> None:
    """A path the suite reads but mutmut does not copy aborts the gate.

    Red when: a path the suite names is under no ``also_copy`` entry (on
    ``7f8cf00``: ``e2e/servers/signed_in_server.py``, read by
    ``test_w105_tabs_share_token.py`` and ``test_age_sessions_is_test_only.py``,
    while ``also_copy`` copies only ``e2e/tests``, ``e2e/fixtures`` and
    ``e2e/playwright.config.ts``)."""
    copied = _copied_paths()
    missing = {
        named: module
        for named, module in _referenced_paths().items()
        if not _is_copied(named, copied) and named.split("/", 1)[0] not in EXEMPT
    }
    assert not missing, (
        "these repo paths are read by the suite but are absent inside "
        "./mutants/, so `mutmut run` fails to collect stats and scores zero "
        "mutants — add them to [tool.mutmut].also_copy (or to EXEMPT with the "
        f"reason the absence is safe): {missing}"
    )


def test_a_module_the_mutation_run_deselects_is_not_scanned() -> None:
    """A module marked ``repo_introspection`` or ``env_oracle`` never runs
    inside ./mutants/, so a path only it reads (``e2e/node_modules``, read by
    ``test_negative_assertion_guard.py`` and present only where ``npm ci`` ran,
    as in CI) must not be reported. Partners: the markers are read from the
    real ``[tool.mutmut]`` selection, and an unmarked module is not skipped.

    Red when: the scan stops skipping deselected modules, or reads the markers
    from anywhere but the ``-m`` selection mutmut uses."""
    assert _deselected_markers() == {"env_oracle", "repo_introspection"}
    marked = ast.parse("import pytest\npytestmark = pytest.mark.repo_introspection\n")
    oracle = ast.parse("import pytest\npytestmark = [pytest.mark.env_oracle]\n")
    plain = ast.parse("import pytest\npytestmark = pytest.mark.slow\n")
    deselected = _deselected_markers()
    assert _is_deselected(marked, deselected)
    assert _is_deselected(oracle, deselected)
    assert not _is_deselected(plain, deselected)
    assert not _is_deselected(ast.parse("x = 1\n"), deselected)


def test_a_partly_copied_root_does_not_count_as_copied() -> None:
    """The chain is read whole and compared by folder, not by first part.
    Planted names (``pkg/...``) that exist nowhere, so this module's own
    literals add nothing to the real census above.

    Red when: ``_root_chain`` keeps only the first part of
    ``ROOT / "pkg" / "servers" / ...``, inner links of a chain are reported as
    paths of their own, or ``_is_copied`` goes back to comparing first parts
    (``pkg/checks`` would then cover ``pkg/servers/...``) — the hole that let
    ``e2e/servers`` through on the #596 probe."""
    tree = ast.parse(
        'ROOT / "pkg" / "servers" / "run.py"\n'
        'REPO_ROOT / "pkg/checks" / "x.spec.ts"\n'
        'OTHER / "pkg" / "servers"\n'
    )
    assert sorted(_root_paths_in(tree)) == ["pkg/checks/x.spec.ts", "pkg/servers/run.py"]
    copied = {PurePosixPath("pkg/checks"), PurePosixPath("pkg/fixtures")}
    assert not _is_copied("pkg/servers/run.py", copied)
    assert not _is_copied("pkg/servers", copied)
    assert _is_copied("pkg/servers/run.py", copied | {PurePosixPath("pkg/servers")})
    assert _is_copied("pkg/checks/deeper/x.spec.ts", copied)
    assert _is_copied("pkg/fixtures", copied)
    # The recorded allowance: a folder only part of which is copied.
    assert _is_copied("pkg", copied)
    assert not _is_copied("Makefile", copied)


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
        # The strip lives in ONE place now (#368) -- it was hand-copied to two
        # call sites and missing from five others.
        env=env_without_coverage(),
    )
    assert result.returncode == 0, (
        "the suite fails inside a mutmut-shaped copy of the tree, so "
        "`make mutation-baseline` aborts with 'failed to collect stats' before "
        f"scoring a mutant:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
