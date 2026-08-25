"""Guards on `tests/repo_root.py` — resolving the real tree, not a copy of it.

The defect this exists to stop is #158, and it is worth stating precisely
because the shape recurs: a check derived the repository root from ``__file__``
with a fixed parent count. That is correct until some tool runs the suite from
inside a generated copy of the project — a mutation runner's ``./mutants/``
tree — at which point the count lands one directory short and the check reads
the copy. The copy's ``src/`` holds one extra decorated function per mutant, so
a census that should have read 40 read 514, the assertion failed, ``-x`` ended
collection, and the mutation gate exited non-zero **having measured nothing**.

Every assertion below is written against a synthetic tree, never against this
repository's own layout, so none of them can pass by accident on the shape they
are meant to detect.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tests.repo_root import find_repo_root
from tests.subprocess_env import env_without_coverage


def _tree(root: Path, *, inside_a_copy: bool) -> Path:
    """A fake checkout; returns the module path a test would pass as __file__.

    With ``inside_a_copy`` the module sits at ``<root>/mutants/tests/unit/`` —
    the layout a mutation runner produces — and ``mutants/`` deliberately has
    no ``.git`` of its own, exactly as the real copy does not.
    """
    (root / ".git").mkdir()
    prefix = root / "mutants" if inside_a_copy else root
    unit = prefix / "tests" / "unit"
    unit.mkdir(parents=True)
    module = unit / "test_something.py"
    module.write_text("", encoding="utf-8")
    return module


def test_it_resolves_out_of_a_copied_tree(tmp_path: Path) -> None:
    """From inside the copy it must return the REAL root, not the copy.

    This is #158 in miniature. ``parents[2]`` from
    ``<root>/mutants/tests/unit/test_something.py`` is ``<root>/mutants``.

    Turns red if: find_repo_root goes back to a fixed parent count, or stops at
    the first ancestor named ``tests``/``mutants`` instead of at ``.git``.
    """
    module = _tree(tmp_path, inside_a_copy=True)

    assert find_repo_root(module) == tmp_path.resolve()
    # Say the failure out loud rather than leaving it to an equality diff: the
    # wrong answer here is a real directory that exists and looks plausible.
    assert find_repo_root(module) != (tmp_path / "mutants").resolve()


def test_it_resolves_an_ordinary_tree(tmp_path: Path) -> None:
    """The positive partner: the normal layout must still resolve.

    Without this, a `find_repo_root` that always returned its argument's
    grandparent-of-grandparent — or simply always returned ``tmp_path`` — would
    satisfy the test above. A check that only proves the copied case does not
    prove the function works.

    Turns red if: find_repo_root walks past the repository to a ``.git`` higher
    up the filesystem, or returns the tests directory.
    """
    module = _tree(tmp_path, inside_a_copy=False)

    assert find_repo_root(module) == tmp_path.resolve()


def test_a_dot_git_FILE_counts_as_the_root(tmp_path: Path) -> None:
    """git worktrees and submodules write ``.git`` as a file, not a directory.

    Turns red if: the check is tightened to ``is_dir()``, which would send every
    worktree checkout walking past its own root.
    """
    (tmp_path / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True)
    module = unit / "test_something.py"
    module.write_text("", encoding="utf-8")

    assert find_repo_root(module) == tmp_path.resolve()


def test_it_fails_loudly_when_there_is_no_repository(tmp_path: Path) -> None:
    """No ``.git`` anywhere above ⇒ raise, never guess.

    A silent fallback to ``parents[n]`` would reinstate #158 at precisely the
    moment the function is supposed to prevent it.

    Turns red if: find_repo_root gains a fallback return instead of raising.
    """
    orphan = tmp_path / "no-repo" / "tests" / "unit"
    orphan.mkdir(parents=True)
    module = orphan / "test_something.py"
    module.write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"no \.git ancestor"):
        find_repo_root(module)


def test_the_guard_module_resolves_out_of_a_copied_tree_FOR_REAL(tmp_path: Path) -> None:
    """Run the guard inside a copied tree and see where its root actually lands.

    **This replaces four failed attempts to pin the source, and the reason it is
    different in kind is the point.** Each earlier version asserted a *description*
    of the fix and was defeated by a different spelling of the defect:

    1. asserted properties ``parents[2]`` also satisfies — green with the bug present;
    2. searched for ``parents[`` — matched the module's own docstring explaining it;
    3. banned any ``.parents`` attribute — evadable by ``.parent.parent.parent``,
       and it false-fired on legitimate use;
    4. pinned ``REPO_ROOT`` to an ``ast.Call`` — evadable two ways, both measured:
       a LATER reassignment (``next()`` takes the first ``Assign``, Python runs the
       last) and a module-local function shadowing the import.

    A description of a defect has unbounded spellings. The defect itself has one
    observable consequence: **inside the mutation runner's copy, the root lands on
    the copy.** So build that copy and look. No spelling can fake this, because it
    is not read from the source at all.

    Turns red if: the guard computes its root from a parent count in ANY spelling,
    reassigns it afterwards, or shadows ``find_repo_root`` with a local definition.
    """
    # A repository with a generated copy inside it, exactly as the runner leaves it:
    # the copy carries pyproject.toml and src/product_app so that a buggy root
    # STILL satisfies every existence check — that is what made attempt 1 vacuous.
    (tmp_path / ".git").mkdir()
    copy = tmp_path / "mutants"
    (copy / "tests" / "unit").mkdir(parents=True)
    (copy / "src" / "product_app").mkdir(parents=True)
    (copy / "src" / "product_app" / "__init__.py").write_text("", encoding="utf-8")
    (copy / "pyproject.toml").write_text("[tool.x]\n", encoding="utf-8")
    (copy / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (copy / "tests" / "unit" / "__init__.py").write_text("", encoding="utf-8")

    real = find_repo_root(Path(__file__))
    shutil.copy2(real / "tests" / "repo_root.py", copy / "tests" / "repo_root.py")
    guard_name = "test_mutation_test_set_integrity"
    shutil.copy2(
        real / "tests" / "unit" / f"{guard_name}.py",
        copy / "tests" / "unit" / f"{guard_name}.py",
    )

    # Import the guard FROM INSIDE THE COPY and ask it where its root is.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            f"from tests.unit.{guard_name} import REPO_ROOT; print(REPO_ROOT)",
        ],
        cwd=copy,
        # #368: the copy carries its own src/product_app/__init__.py.
        env=env_without_coverage(PYTHONPATH=str(copy)),
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, f"the guard did not import inside the copy:\n{probe.stderr}"
    resolved = Path(probe.stdout.strip())

    assert resolved == tmp_path.resolve(), (
        f"the guard resolved its root to {resolved} from inside the copy at {copy}. "
        "It must resolve to the REAL repository root. Landing on the copy is #158: "
        "every census it takes then counts the mutation runner's own generated "
        "variants instead of the real source."
    )
    assert resolved != copy.resolve(), (
        "the guard resolved to the generated copy — this is #158 exactly."
    )
