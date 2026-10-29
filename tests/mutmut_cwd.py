"""Make a folder that mutmut can run in, for tests that leave the tree's folder.

mutmut 3.6.0 finds its source by a path RELATIVE to the current folder. Read in
``.venv/lib/python3.12/site-packages/mutmut/``:

* ``configuration.py:20`` reads ``Path("pyproject.toml")`` from the current
  folder; with none there, ``_guess_source_paths`` (``:68-93``) looks for a
  ``lib`` or ``src`` folder in the current folder and otherwise raises
  "Could not figure out where the code to mutate is".
* ``__main__.py:120`` runs ``[p.resolve(strict=True) for p in
  Config.get().source_paths]`` at each hit the trampoline records, and during
  the stats run it records one on EVERY call of a mutated function
  (``mutation/trampoline.py:59-60``), so a missing ``src`` raises
  ``FileNotFoundError: 'src'`` there even after a clean start.
* ``__main__.py:446`` and ``:449-451`` run the suite from ``./mutants/``, and
  every mutated ``src/product_app`` file imports the trampoline, whose import
  reads the config (``utils/safe_setproctitle.py:15``).

So a test that calls ``src`` code after moving the process to a temp folder, or
starts a Python child there that imports ``src``, fails inside ``./mutants/``
and stops the mutation job before it scores anything (W116; measured on the
discovery probe, #596, run 40753467337).

``mutmut_can_run_in(folder)`` makes an EMPTY ``src`` in ``folder`` and returns
``folder``. Empty on purpose: nothing in it can be imported, so the test still
runs the code it meant to run, and the folder still lacks whatever the test
needs it to lack (``.env``, ``.data``). Outside mutmut the empty folder changes
nothing. ``tests/unit/test_w116_tests_run_inside_the_mutation_copy.py`` (G1a)
requires every such ``chdir`` and child ``cwd=`` to go through this helper.
"""

from __future__ import annotations

from pathlib import Path


def mutmut_can_run_in(folder: Path) -> Path:
    """Make an empty ``folder/src`` (if it is not there yet) and return ``folder``."""
    (folder / "src").mkdir(exist_ok=True)
    return folder
