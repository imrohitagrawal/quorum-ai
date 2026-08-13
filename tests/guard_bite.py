"""General mechanism for #167: prove a GUARD test can actually fail.

The mutation gate (`MUTMUT_SCOPE_PY` in the Makefile) mutates `src/` and uses
`tests/` as the oracle. Nothing mutates the oracle, so a **guard test** — one
whose subject is repo state (a Makefile recipe, a workflow file, a script, a
constant) rather than `src/` — has no mechanism proving it can go red.
Mutating `tests/` itself was measured and rejected in #167: `src/` alone
generates ~9,370 mutants in 23s (7.32/s), so the same density over `tests/`
(2.9x larger) is on the order of an hour for a one-line change — the exact
failure that stranded merges 2026-07-17..21.

`assert_guard_bites` is the cheap alternative #167 recommends: mutate the
artifact ONE guard asserts about (not the whole test suite), in a throwaway
copy that never touches a tracked file, and confirm the guard's own check
rejects it. Cost is one extra invocation of the guard, not a suite run.

Never mutates the real file on disk, so there is nothing to restore via
`git checkout` (AGENTS.md rule 6 forbids that as a revert mechanism) — the
mutated content only ever exists in a `tempfile.mkdtemp()` scratch directory
that is removed at the end.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path


def assert_guard_bites(
    original: Path,
    mutate: Callable[[str], str],
    run_guard: Callable[[Path], None],
) -> None:
    """Prove `run_guard` fails against a mutated copy of `original`.

    `run_guard(path)` must raise `AssertionError` when `path` holds the
    mutated text, and must NOT raise against a byte-identical, unmutated copy
    of `original` — that positive case is checked first, so a `run_guard`
    that always raises cannot satisfy this function trivially (rule 7: a
    negative check needs a positive partner).

    Operates entirely on throwaway copies under a fresh `tempfile.mkdtemp()`;
    `original` on disk is only ever read, never written.
    """
    scratch = Path(tempfile.mkdtemp(prefix="guard-bite-"))
    try:
        text = original.read_text(encoding="utf-8")

        clean = scratch / original.name
        clean.write_text(text, encoding="utf-8")
        run_guard(clean)  # positive partner: must NOT raise on unmutated content

        mutated_text = mutate(text)
        assert mutated_text != text, (
            f"mutate() produced no change to {original.name} — the bite check "
            "would compare identical content against itself"
        )
        mutated = scratch / f"mutated-{original.name}"
        mutated.write_text(mutated_text, encoding="utf-8")
        try:
            run_guard(mutated)
        except AssertionError:
            return
        raise AssertionError(
            f"run_guard did not fail against a mutated copy of {original.name} "
            "-- this guard cannot bite"
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
