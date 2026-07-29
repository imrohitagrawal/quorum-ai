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

from pathlib import Path

import pytest
from tests.repo_root import find_repo_root


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


def test_the_real_module_root_is_this_repository() -> None:
    """The shipped call site resolves to a tree that has the real source in it.

    Deliberately NOT asserted against ``Path(__file__).parents[2]`` — that is
    the expression under repair, and comparing the fix to the bug would pass in
    both worlds. Asserted instead against properties only the real repository
    has, plus the negative that named the defect.

    Turns red if: REPO_ROOT in the mutation-test-set guard is pointed back at a
    copy, or at the tests directory.
    """
    from tests.unit.test_mutation_test_set_integrity import REPO_ROOT

    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "src" / "product_app" / "__init__.py").is_file()
    assert REPO_ROOT.name != "mutants", (
        f"REPO_ROOT resolved to {REPO_ROOT} — a generated copy, not the repository. "
        "Any census of src/ taken here counts the mutation runner's own variants."
    )
