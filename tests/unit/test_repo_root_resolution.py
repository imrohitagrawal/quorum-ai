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

import ast
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


def test_the_guard_module_resolves_its_root_through_the_helper() -> None:
    """The shipped call site must not go back to a parent count.

    **This is a SOURCE pin, and it is one deliberately.** An earlier version of
    this test asserted only that ``REPO_ROOT`` had a ``pyproject.toml`` and a
    ``src/product_app`` under it and was not named ``mutants``. In an ordinary
    checkout ``Path(__file__).resolve().parents[2]`` satisfies all three — so
    the test was GREEN with the #158 defect fully present, and would only ever
    have gone red under the mutation runner, which is not the runner CI gates
    on. It was a test that passed when the feature was absent: the exact defect
    class this module's own docstring is about. Caught by adversarial review,
    then reproduced.

    A behavioural assertion cannot distinguish the two here, because outside a
    copied tree the correct answer and the buggy answer are the same path. So
    the property that actually differs — which expression computes the root — is
    asserted directly, against the source.

    Turns red if: the guard module computes its root from ``parents[...]`` again,
    or stops importing the resolver.
    """
    from tests.unit import test_mutation_test_set_integrity as guard

    source = Path(guard.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "find_repo_root" in source, (
        "the mutation-test-set guard no longer resolves its root through "
        "tests/repo_root.py; inside the mutation runner's copy it will count the "
        "runner's own generated variants again (#158)"
    )
    # Parsed, not grepped. The module's own docstring quotes ``parents[2]`` while
    # explaining the defect, so a substring search reports the explanation as the
    # bug — measured: it did exactly that on the first attempt at this test.
    parent_indexing = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "parents"
    ]
    assert not parent_indexing, (
        "the guard computes a path from a fixed parent count again (line(s) "
        f"{sorted({n.lineno for n in parent_indexing})}). Inside ./mutants/ that "
        "lands on the copy. Use find_repo_root()."
    )
    # Positive partner: the pin above is about HOW the root is computed; this is
    # that the answer is still usable. Without it, deleting REPO_ROOT entirely
    # would satisfy both assertions above.
    assert (guard.REPO_ROOT / "pyproject.toml").is_file()
    assert (guard.REPO_ROOT / "src" / "product_app" / "__init__.py").is_file()
