"""Resolve the REAL repository root, even when the suite runs inside a copy.

A mutation runner copies the whole project into ``./mutants/`` and re-runs the
suite from in there. Any module that derives the root from ``__file__`` — the
idiom this suite uses in 82 places — then points at the **copy** rather than at
the repository.

For most checks that is harmless, because the copy is faithful: ``docs/``,
``Makefile`` and ``tests/`` inside ``mutants/`` are byte-identical to the
originals. It is **not** harmless for a check that *counts* things in the
mutated source. mutmut writes one extra decorated ``x_<name>__mutmut_N``
variant per mutant into the copied source, so a census of decorated functions
under ``src/product_app`` read **514** inside the copy where the real tree has
**40** — the assertion blew up, ``-x`` killed collection, and the gate exited
non-zero having scored nothing at all (#158). A red job that measured nothing
looks exactly like a red job that found something.

``find_repo_root`` walks up to the first ancestor that holds a ``.git`` entry.
The copy has no ``.git``, so from inside ``mutants/`` this returns the real
root — which is what a check about the real source must read.

Use this instead of ``Path(__file__).resolve().parents[n]`` in any check whose
answer would change if it were pointed at a generated copy of the tree.
"""

from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """The nearest ancestor of ``start`` containing ``.git``.

    ``start`` may be a file (pass ``Path(__file__)``) or a directory. ``.git``
    is checked with ``exists()`` rather than ``is_dir()`` because a worktree or
    submodule checkout has it as a *file*.

    Raises ``RuntimeError`` rather than guessing when there is no repository
    above ``start``. Falling back to a ``parents[n]`` count is exactly the
    behaviour this function exists to remove, and a silent fallback would
    reinstate it at the one moment it matters.
    """
    resolved = start.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(
        f"no .git ancestor above {start} — cannot resolve the repository root. "
        "This helper is used by checks that must read the real tree rather than "
        "a generated copy of it; guessing a parent count here is what caused #158."
    )
