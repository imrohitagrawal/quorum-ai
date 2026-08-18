"""The mutation gate aborts when a spec asks git about the tree it is IN.

`mutmut run` copies the project into `./mutants/` — a directory INSIDE the
repository — and runs the whole suite from in there to collect baseline stats.
A spec that resolves its root as `Path(__file__).resolve().parents[n]` then
points at the copy, and `git ls-files` with that cwd returns **nothing**: git
resolves the enclosing repository fine, but the pathspec is relative to a cwd
that holds no tracked files. Exit status 0, empty output, no error.

Measured 2026-08-19 on `origin/main` at e4c58a2, which is this branch's merge
base. The count is pinned to that ref on purpose: this branch adds an ADR, so
the same command run HERE prints one more, and a bare number would be false of
the tree it ships in. (An earlier draft of this file recorded 289; that figure
was already stale when it was written, which is why the ref is named now.)::

    $ git ls-files "docs/*.md" | wc -l          # from the repo root
    293
    $ mkdir mutants-probe && git archive HEAD | tar -x -C mutants-probe
    $ cd mutants-probe && git ls-files "docs/*.md" | wc -l
    0

An anti-vacuity floor over that empty list fails, `-x` stops mutmut's stats
collection, and the gate exits non-zero having scored zero mutants. Verbatim,
from `make mutation-baseline` and byte-identical to CI run 32057683059::

    FAILED tests/unit/test_docs_numbering_no_collisions.py::
        test_the_scan_sees_a_nonzero_number_of_numbered_docs - assert 0 > 100
    !!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
    failed to collect stats. runner returned 1

WHY THE EXISTING GUARD MISSED IT.
`tests/unit/test_mutation_copy_completeness.py::test_the_real_copy_runs_the_root_reading_specs`
exists for exactly this failure, and did not see it, for two reasons:

1. its `ROOT_READING_MODULES` is a HAND-MAINTAINED tuple of six module paths,
   and neither offending module is in it. A guard whose input is an allowlist
   cannot see a module added after the allowlist was written.
2. it copies into pytest's `tmp_path`, which is OUTSIDE any repository, where
   the same command is `fatal: not a git repository` (exit 128) rather than a
   silent empty success. That models a different failure.

So the discovery here is DERIVED FROM THE TREE, never listed, and the copy here
is NESTED INSIDE a throwaway repository so that the silent-empty shape is the
one under test.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from tests.repo_root import find_repo_root

# Deselected under mutmut: this module drives git and pytest against the real
# repository, and copies it. It kills no mutant of `src/` and cannot: it
# imports nothing from the application. It still runs, blocking, in the
# ordinary suite. (Adding a marker to a module that DOES cover `src/` is the
# evasion `tests/unit/test_mutation_test_set_integrity.py` pins against.)
pytestmark = pytest.mark.repo_introspection

REPO_ROOT = find_repo_root(Path(__file__))
PYPROJECT = REPO_ROOT / "pyproject.toml"

# mutmut copies these itself, without an `also_copy` entry.
#
# `.gitignore` is here for the HARNESS, not because mutmut needs it: the
# throwaway repository below runs `git add -A`, and without the ignore rules it
# indexes files the real repository never tracks. A `.DS_Store` sitting under
# `e2e/tests/` on a developer's Mac is enough to turn
# `test_no_generated_artifacts_tracked.py::test_no_tracked_ds_store` red INSIDE
# the copy, which would fail the execution test below locally while CI — a
# fresh Linux checkout with no such file — stayed green.
_IMPLICIT_COPY = ("src", "tests", "pyproject.toml", ".gitignore")

# Subcommands whose ANSWER depends on the working directory, because their
# pathspec is resolved relative to it. `git diff --name-only` and
# `git rev-parse` are deliberately absent: they report repo-relative paths
# whatever the cwd, so they survive the copy unchanged. Verified by execution —
# `tests/test_day_one_carry_forward_audit.py` and
# `tests/unit/test_cited_paths_resolve.py` both shell out to git with a
# `__file__`-derived cwd and both PASS inside the copy.
_CWD_SCOPED_GIT_SUBCOMMANDS = frozenset({"ls-files", "status", "grep"})

_SUBPROCESS_CALLS = frozenset({"run", "check_output", "check_call", "Popen", "call"})


def _module_roots(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to a path derived from ``__file__``.

    Maps the name to how it was derived: ``"find_repo_root"`` (walks to the
    first `.git` ancestor, so it escapes the copy) or ``"file_relative"``
    (a `parents[n]` hop, which does not).

    Plain assignment, ANNOTATED assignment (``ROOT: Path = ...``) and
    multi-target or tuple-target assignment are all read. An earlier form of
    this function read only single-target `ast.Assign`, so the same defect
    written `ROOT: Path = Path(__file__).resolve().parents[2]` was invisible
    to the whole guard. Nothing in `tests/` uses the annotated form today
    (measured: zero modules), so widening it costs no churn and closes the
    hole before it is used.
    """
    roots: dict[str, str] = {}

    def record(target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                record(element, value)
            return
        if not isinstance(target, ast.Name):
            return
        source = ast.unparse(value)
        if "__file__" not in source:
            return
        roots[target.id] = "find_repo_root" if "find_repo_root" in source else "file_relative"

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record(target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            record(node.target, node.value)
    return roots


def _is_repo_introspection(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = (t.id for t in node.targets if isinstance(t, ast.Name))
        if "pytestmark" in names and "repo_introspection" in ast.unparse(node.value):
            return True
    return False


def _subprocess_aliases(tree: ast.Module) -> frozenset[str]:
    """Bare names bound to a `subprocess` runner by `from subprocess import ...`.

    Without this, `from subprocess import run` then `run([...])` is a call the
    scan never looks at. No module in `tests/` uses that import form today
    (measured: zero), so this only closes a future hole.
    """
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in _SUBPROCESS_CALLS:
                    aliases.add(alias.asname or alias.name)
    return frozenset(aliases)


def _cwd_derivation(cwd: ast.expr | None, roots: dict[str, str]) -> str:
    """How a git call's ``cwd`` is derived — FAIL CLOSED on anything unfamiliar.

    Per ADR-0047, a detector that cannot classify an input resolves toward the
    answer that makes the gate go RED. Three outcomes are offenders and one is
    not:

    * a module-level root bound by `find_repo_root` — the only safe answer.
    * a module-level root bound from `__file__` any other way — `"file_relative"`.
    * NO `cwd=` keyword at all — `"inherited_cwd"`. Under `mutmut run` the
      process working directory IS `./mutants/`, so an inherited cwd produces
      exactly the same silent-empty answer as a `parents[n]` root.
    * an expression naming no known module root — `"unclassified"`. That covers
      `cwd=str(REPO_ROOT)`-shaped wrappers and anything else, including a
      genuinely throwaway directory. A throwaway directory is a legitimate use;
      the escape hatch is `pytest.mark.repo_introspection`, which takes the
      module out of mutmut's selection and out of this scan, and which
      `tests/unit/test_mutation_test_set_integrity.py` already reviews.

    An earlier form dropped every call it could not reduce to a bare root name,
    so `cwd=str(REPO_ROOT)` and a missing `cwd=` were both silently safe.
    Measured on this tree: closing both costs zero new offenders.
    """
    if cwd is None:
        return "inherited_cwd"
    named = {node.id for node in ast.walk(cwd) if isinstance(node, ast.Name)}
    derivations = {roots[name] for name in named & roots.keys()}
    if not derivations:
        return "unclassified"
    if "file_relative" in derivations:
        return "file_relative"
    return "find_repo_root"


def _cwd_scoped_git_calls(tree: ast.Module, roots: dict[str, str]) -> list[str]:
    """How each cwd-scoped git call in the module derives its ``cwd``.

    KNOWN AND UNCLOSED: the subcommand must appear as a string literal in the
    argv. A call that builds its subcommand dynamically — `["git", *args]` —
    is not classified, and seven such calls exist in `tests/` today, all of
    them driving throwaway repositories with a local `cwd`. Failing closed on
    those would make the guard red on seven calls that are correct, so the
    guard does not claim to cover them. This is the guard's honest boundary,
    stated rather than implied.
    """
    aliases = _subprocess_aliases(tree)
    derivations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        qualified = func.startswith("subprocess.") and func.split(".")[-1] in _SUBPROCESS_CALLS
        if not (qualified or func in aliases):
            continue
        if not node.args:
            continue
        argv = node.args[0]
        if not isinstance(argv, (ast.List, ast.Tuple)):
            continue
        literals = [e.value for e in argv.elts if isinstance(e, ast.Constant)]
        if not literals or literals[0] != "git":
            continue
        if not (set(literals[1:]) & _CWD_SCOPED_GIT_SUBCOMMANDS):
            continue
        cwd = next((kw.value for kw in node.keywords if kw.arg == "cwd"), None)
        derivations.append(_cwd_derivation(cwd, roots))
    return derivations


def _specs_that_ask_git_about_their_own_tree() -> dict[str, list[str]]:
    """Every spec mutmut RUNS that asks git a cwd-scoped question, from the tree.

    Derived, never listed. `repo_introspection`-marked modules are excluded
    because mutmut's own selection deselects them (`pyproject.toml`
    `[tool.mutmut].pytest_add_cli_args`), so they cannot abort the baseline.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(REPO_ROOT.joinpath("tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _is_repo_introspection(tree):
            continue
        derivations = _cwd_scoped_git_calls(tree, _module_roots(tree))
        if derivations:
            found[str(path.relative_to(REPO_ROOT))] = derivations
    return found


def test_the_discovery_finds_the_specs_that_are_known_to_ask_git() -> None:
    """Positive partner for the two negative checks below: a scan that found
    nothing would make both of them trivially true.

    Both modules named here shell out to `git ls-files` with a
    `__file__`-derived cwd today; the assertion is that the scan SEES them, not
    that they are the only ones. If a future change removes a module's git call
    entirely, replace the name here rather than deleting the floor.

    Turns red if: `_cwd_scoped_git_calls` stops matching `git ls-files`, or the
    walk over `tests/` stops finding modules.
    """
    found = _specs_that_ask_git_about_their_own_tree()
    assert "tests/unit/test_docs_numbering_no_collisions.py" in found, found
    assert "tests/unit/test_no_generated_artifacts_tracked.py" in found, found


def test_every_spec_the_baseline_runs_resolves_the_real_repository_root() -> None:
    """A cwd-scoped git question answered from inside `./mutants/` is answered
    about a directory with no tracked files, and the empty answer arrives with
    exit status 0.

    Turns red if: any spec mutmut runs derives the cwd of a `git ls-files`
    (or `git status`/`git grep`) from anything other than
    `tests.repo_root.find_repo_root` — a `Path(__file__).resolve().parents[n]`
    hop, no `cwd=` at all, or an expression this scan cannot classify.
    Verified by reverting `tests/unit/test_docs_numbering_no_collisions.py`
    to `parents[2]`.
    """
    offenders = {
        module: derivations
        for module, derivations in _specs_that_ask_git_about_their_own_tree().items()
        if any(derivation != "find_repo_root" for derivation in derivations)
    }
    assert not offenders, (
        "these specs ask git a cwd-scoped question from a working directory "
        "that is not proven to be the real repository root. `mutmut run` runs "
        "them from inside ./mutants/, where such a root holds no tracked files "
        "and git answers EMPTY with exit status 0 — any floor over the result "
        "fails, `-x` stops stats collection, and the gate exits non-zero having "
        "scored nothing (the abort on PR #335). Resolve the root with "
        "`tests.repo_root.find_repo_root(Path(__file__))`, or — if the cwd is a "
        "genuinely throwaway directory — mark the module "
        f"`pytest.mark.repo_introspection`: {offenders}"
    )


# Source fed to the classifier, never imported. Each entry is a shape that an
# earlier form of this guard dropped silently, letting the #338 defect back in
# with all four tests green. Both members of each pair differ only in how the
# root is derived, so a classifier that stopped reading the shape at all would
# fail the SAFE half rather than passing the offending one.
_CLASSIFIER_CASES: tuple[tuple[str, str, str], ...] = (
    (
        "annotated assignment",
        "file_relative",
        "ROOT: Path = Path(__file__).resolve().parents[2]\n"
        'subprocess.run(["git", "ls-files", "docs"], cwd=ROOT)\n',
    ),
    (
        "annotated assignment, resolved properly",
        "find_repo_root",
        "ROOT: Path = find_repo_root(Path(__file__))\n"
        'subprocess.run(["git", "ls-files", "docs"], cwd=ROOT)\n',
    ),
    (
        "cwd wrapped in a call",
        "file_relative",
        "ROOT = Path(__file__).resolve().parents[2]\n"
        'subprocess.run(["git", "ls-files", "docs"], cwd=str(ROOT))\n',
    ),
    (
        "no cwd keyword at all",
        "inherited_cwd",
        'subprocess.run(["git", "ls-files", "docs"])\n',
    ),
    (
        "cwd naming no module-level root",
        "unclassified",
        'subprocess.run(["git", "ls-files", "docs"], cwd=somewhere_else)\n',
    ),
    (
        "tuple-target assignment",
        "file_relative",
        "HERE, ROOT = None, Path(__file__).resolve().parents[2]\n"
        'subprocess.run(["git", "ls-files", "docs"], cwd=ROOT)\n',
    ),
    (
        "runner imported bare from subprocess",
        "file_relative",
        "from subprocess import run\n"
        "ROOT = Path(__file__).resolve().parents[2]\n"
        'run(["git", "ls-files", "docs"], cwd=ROOT)\n',
    ),
)


@pytest.mark.parametrize(("shape", "expected", "source"), _CLASSIFIER_CASES)
def test_the_classifier_never_drops_a_cwd_scoped_git_call(
    shape: str, expected: str, source: str
) -> None:
    """The scan must classify every shape, and classify an unfamiliar one as an
    offender (ADR-0047: a detector that cannot decide resolves toward RED).

    Turns red if: `_module_roots` stops reading annotated or tuple targets,
    `_subprocess_aliases` stops resolving a bare `run`, or `_cwd_derivation`
    goes back to DROPPING a call whose `cwd=` is missing or unrecognised —
    each of which makes a real re-introduction of #338 invisible to the two
    negative checks and to the execution test, because all three are driven by
    this same scan.

    Deliberately NOT parametrized over the classifier's own output (rule 7a):
    every expected value is written here as a literal.
    """
    tree = ast.parse(source)
    derivations = _cwd_scoped_git_calls(tree, _module_roots(tree))
    assert derivations == [expected], f"{shape}: {derivations}"
    assert (expected == "find_repo_root") == (derivations == ["find_repo_root"]), (
        f"{shape}: only find_repo_root may be treated as safe"
    )


def _copy_project(destination: Path) -> None:
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["mutmut"]
    for entry in sorted({*config["also_copy"], *config["source_paths"], *_IMPLICIT_COPY}):
        source = REPO_ROOT / entry
        if not source.exists():
            continue
        target = destination / entry
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, target)
        else:
            shutil.copytree(source, target, dirs_exist_ok=True)


def _build_mutmut_shaped_tree(tmp_path: Path) -> Path:
    """A throwaway repository with a faithful `./mutants/` copy inside it.

    The nesting is the whole point. A copy in a bare `tmp_path` is outside any
    repository, where `git ls-files` is `fatal: not a git repository` (exit
    128) — loud, and NOT the failure mutmut hits. Indexing the outer copy
    before creating the inner one keeps `mutants/` untracked, exactly as
    `.gitignore:54` keeps it in the real tree.
    """
    outer = tmp_path / "repo"
    outer.mkdir()
    _copy_project(outer)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "gate",
        "GIT_AUTHOR_EMAIL": "gate@example.invalid",
        "GIT_COMMITTER_NAME": "gate",
        "GIT_COMMITTER_EMAIL": "gate@example.invalid",
    }
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=outer, check=True, env=env)
    _copy_project(outer / "mutants")
    return outer / "mutants"


def _run_in_copy(mutants: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *argv],
        cwd=mutants,
        capture_output=True,
        text=True,
        # Strip pytest-cov's subprocess hooks: the child would otherwise measure
        # the COPIED src/ and combine that into the parent run's data.
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("COV_CORE", "COVERAGE"))
        },
    )


_SHAPE_PROBE = """
import subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from tests.repo_root import find_repo_root

def count(root):
    done = subprocess.run(["git", "ls-files", "docs/*.md"], cwd=root,
                          capture_output=True, text=True)
    return done.returncode, len([l for l in done.stdout.splitlines() if l])

# Assembled from parts, never written as one literal: this path deliberately
# does NOT exist, and tests/unit/test_cited_paths_resolve.py fails any
# repo-shaped path on an added line that does not resolve. It only has to sit
# two levels below the root, the way a real spec under tests/unit/ does.
stand_in = (Path("tests") / "unit" / "a_spec_that_does_not_exist.py").resolve()
print("file_relative", *count(stand_in.parents[2]))
print("find_repo_root", *count(find_repo_root(stand_in)))
"""


def test_the_copy_reproduces_gits_silent_empty_answer(tmp_path: Path) -> None:
    """The harness must model the REAL failure, not a louder one.

    Inside `./mutants/`, a `parents[n]` root must give git exit status 0 and an
    EMPTY list — a silent wrong answer. `find_repo_root` must give the real
    population. Without this, the execution test below could pass because the
    copy is broken in some other way, or fail for a reason mutmut never hits.

    Turns red if: `_build_mutmut_shaped_tree` stops nesting the copy inside a
    repository (git then exits 128, `fatal: not a git repository`), or stops
    indexing the outer copy (both counts go to 0).
    """
    mutants = _build_mutmut_shaped_tree(tmp_path)
    result = _run_in_copy(mutants, ["-c", _SHAPE_PROBE])
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    measured = dict(
        (line.split()[0], (int(line.split()[1]), int(line.split()[2])))
        for line in result.stdout.splitlines()
        if line.strip()
    )
    assert measured["file_relative"] == (0, 0), (
        "the copy does not reproduce git's silent-empty answer, so the "
        f"execution test below is not measuring the real abort: {measured}"
    )
    real_status, real_count = measured["find_repo_root"]
    assert real_status == 0 and real_count > 100, (
        "`find_repo_root` does not reach the real tree from inside the copy, so "
        f"this harness cannot tell a fixed spec from a broken one: {measured}"
    )

    # The throwaway repository is a SUBSET of the real tree — it holds only
    # `also_copy` + `source_paths` + `_IMPLICIT_COPY`. Measured 2026-08-19:
    # 1114 tracked files against the real tree's 1202, so the `> 1000` floor
    # in `test_no_generated_artifacts_tracked.py` is evaluated here with 114 of
    # margin, not the 202 the real tree has. Without this check, trimming an
    # `also_copy` entry would take the copy under that floor and the execution
    # test below would go red saying `make mutation-baseline` aborts — which
    # would be false, and would name the wrong cause on a blocking context.
    def tracked(root: Path) -> int:
        done = subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
        )
        return len(done.stdout.splitlines())

    copy_tracked, real_tracked = tracked(mutants.parent), tracked(REPO_ROOT)
    assert copy_tracked >= 0.85 * real_tracked, (
        f"the throwaway repository tracks {copy_tracked} files against the real "
        f"tree's {real_tracked}. This harness no longer models the real tree, so "
        "a floor the real suite clears can fail INSIDE the copy and be reported "
        "as a mutation-gate abort. Widen `_copy_project`, or move the floor — "
        "do not silence this."
    )


def test_the_git_reading_specs_pass_inside_a_mutmut_shaped_copy(tmp_path: Path) -> None:
    """The end the static check cannot reach: RUN them where mutmut runs them.

    The static check above enumerates the git subcommands it knows are
    cwd-scoped. This one runs the specs and does not care why they break.

    Turns red if: any discovered spec fails from inside `./mutants/` — which is
    precisely the state that makes `make mutation-baseline` exit non-zero having
    scored zero mutants. Verified by reverting
    `tests/unit/test_docs_numbering_no_collisions.py` to `parents[2]`.
    """
    modules = sorted(_specs_that_ask_git_about_their_own_tree())
    assert modules, "nothing discovered — this test would be vacuous"

    mutants = _build_mutmut_shaped_tree(tmp_path)
    result = _run_in_copy(
        mutants, ["-m", "pytest", *modules, "-q", "--no-cov", "-p", "no:randomly"]
    )
    assert result.returncode == 0, (
        "a spec that mutmut runs fails from inside ./mutants/, so "
        "`make mutation-baseline` aborts with 'failed to collect stats' before "
        f"scoring a single mutant:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
