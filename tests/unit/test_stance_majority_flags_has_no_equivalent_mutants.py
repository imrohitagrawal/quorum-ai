"""`_stance_majority_flags` must generate no EQUIVALENT mutant. Issue #365.

An equivalent mutant cannot change behaviour for any input, so no test can kill
it — and the mutation gate reported exactly two of them as survivors it called
DEMONSTRATED test gaps. They were not gaps. The Makefile's survivor message is
now honest about that (ADR-0069), but the durable fix was to stop generating
them: `sizes[label] = sizes.get(label, 0) + 1` carries two mutations that are
strictly increasing in the count (`get(label, 1)` and `+ 2`), and a strictly
increasing transform cannot move an arg-max set. `Counter(stance.values())`
deletes the lines they live on.

**This module is the proof, not a description of one.** It takes the mutant
source mutmut *actually* generates for the file on disk — via
`mutate_file_contents`, the same pure function `mutmut run` calls to write
`mutants/src/...` — executes every mutant, and enumerates 5,460 label
assignments against the original.

Two properties, and the second is what stops the first being vacuous:

1. **No** mutant of this function is unkillable: every one either changes the
   answer for some input or raises.
2. The harness can actually *see* a difference. Eleven mutants are individually
   shown detectable with their measured counts, and a hand-written control that
   mutmut did not author is shown detectable too. A harness that reported "no
   difference" for everything would satisfy (1) vacuously and fail (2).

Turns red if: the tally is hand-rolled again, or the function is changed so a
mutant becomes unkillable. Proven by mutation, twice, each restored
byte-identical afterwards (`cp` aside, mutate, restore, `diff -q`):

* Reverting `Counter(stance.values())` to the `sizes.get(label, 0) + 1` form
  takes the mutant count from 11 back to 18, and
  `test_no_mutant_of_this_function_is_unkillable` fails on its COUNT assertion
  first: ``mutmut now generates 18 mutants for _stance_majority_flags, not 11``.
  Re-pin `EXPECTED_MUTANT_COUNT` to 18 and it then fails on the assertion that
  matters, naming ``x__stance_majority_flags__mutmut_8`` and ``__mutmut_9``.
  (This sentence said it failed naming those two directly. Adversarial review
  ran the revert and it did not — the count guard fires first. Recorded rather
  than quietly corrected, because it is exactly the class of claim AGENTS.md
  rule 11a says ships false.)
* Rewriting `largest = max(...)` as `largest = min(...)` leaves property 1
  intact — monotonicity works just as well under `min` — but collapses the
  hand-written control onto the mutated original, and
  `test_the_control_mutation_is_detected_by_this_harness` fails with ``the
  max->min control differs in 0 of 5460 cases``.

That neither edit bites both tests is why both are here.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mutmut.mutation.file_mutation import mutate_file_contents
from tests.repo_root import find_repo_root

#: This module reads the repository's OWN source and re-runs mutmut's mutator
#: over it. `find_repo_root` already keeps it pointed at the real tree rather
#: than mutmut's `./mutants/` copy (verified: from `mutants/tests/unit/` it
#: walks up to the real `.git` and resolves the real `src/`), but a mutation
#: run has no business re-mutating its own subject, so it is deselected there —
#: which is exactly what `repo_introspection` is declared to mean
#: (`pyproject.toml`). The behavioural oracles for `_stance_majority_flags`
#: live in `test_consensus_requires_stance_evidence.py` and are NOT deselected,
#: so the function still has covering tests under the gate.
pytestmark = pytest.mark.repo_introspection

#: The REAL tree, never mutmut's `./mutants/` copy — inside the copy this file
#: would read source that already carries every generated mutant.
MODULE_PATH = find_repo_root(Path(__file__)) / "src" / "product_app" / "synthesis_consensus.py"
FUNCTION = "_stance_majority_flags"
MUTANT_INFIX = "__stance_majority_flags__mutmut_"

#: Panel sizes 1-6 over 4 distinct position labels. `_stance_majority_flags`
#: reads only `stance.values()`, so the slot keys cannot affect the comparison
#: and only the multiset of labels matters.
#:
#: This is EVIDENCE over a superset of the production panel (four default
#: slots, `config.py`), not the whole of the argument — and it is stated that
#: way deliberately. Searched 2026-08-25 and NOT found: any constant in `src/`
#: bounding panel size, so nothing here can be pinned against one. The
#: underlying argument is size-independent — the tally feeds only `max()` and
#: equality with that max — and the enumeration is what makes it checkable by
#: a machine rather than by reading. The case count is asserted below rather
#: than assumed, so narrowing either bound cannot silently shrink the evidence.
PANEL_SIZES = range(1, 7)
LABELS = "abcd"
EXPECTED_CASE_COUNT = 5460

#: Measured 2026-08-25 against `Counter(stance.values())`. Pinned as a count so
#: a change to mutmut's operator table, or to the function, is visible rather
#: than absorbed.
EXPECTED_MUTANT_COUNT = 11


def _cases() -> list[dict[int, str]]:
    return [
        dict(enumerate(combo))
        for size in PANEL_SIZES
        for combo in itertools.product(LABELS, repeat=size)
    ]


@pytest.fixture(scope="module")
def variants() -> tuple[Callable[..., Any], dict[str, Callable[..., Any]]]:
    """The original function and every mutant mutmut generates for it.

    `mutate_file_contents` is the pure function `mutmut run` calls from
    `write_all_mutants_to_file` (`mutmut/__main__.py`), and
    `mutate_only_covered_lines` defaults to False and is not set in
    `pyproject.toml` — so what is executed here is what the gate would run.
    """
    source = MODULE_PATH.read_text(encoding="utf-8")
    mutated, names = mutate_file_contents(str(MODULE_PATH), source)

    original_ns: dict[str, Any] = {}
    exec(compile(source, str(MODULE_PATH), "exec"), original_ns)  # noqa: S102
    mutant_ns: dict[str, Any] = {}
    exec(compile(mutated, str(MODULE_PATH), "exec"), mutant_ns)  # noqa: S102

    mutants = {name: mutant_ns[name] for name in names if MUTANT_INFIX in name}
    assert mutants, (
        f"mutmut generated no mutants for {FUNCTION} — every assertion below "
        "would pass over an empty set, which proves nothing"
    )
    return original_ns[FUNCTION], mutants


def _detect(
    candidate: Callable[..., Any], original: Callable[..., Any], cases: list[dict[int, str]]
) -> tuple[int, int]:
    """(cases where `candidate` answers differently, cases where it raises).

    A mutant that raises is killable by any test that calls the function at
    all, so raising counts as detectable just as differing does.
    """
    differs = raises = 0
    for case in cases:
        try:
            if candidate(dict(case)) != original(dict(case)):
                differs += 1
        except Exception:  # noqa: BLE001 — a raising mutant is a killable mutant
            raises += 1
    return differs, raises


def test_the_enumeration_is_the_size_it_was_reviewed_at() -> None:
    """Anti-vacuity floor: the proof must actually enumerate something.

    Turns red if: `PANEL_SIZES` or `LABELS` is narrowed, which would shrink the
    evidence behind every claim below without changing a single assertion.
    """
    measured = len(_cases())
    assert measured == EXPECTED_CASE_COUNT, (
        f"the enumerated input space changed from {EXPECTED_CASE_COUNT} to "
        f"{measured} assignments; the proof no longer covers what it was "
        "reviewed against"
    )


def test_no_mutant_of_this_function_is_unkillable(
    variants: tuple[Callable[..., Any], dict[str, Callable[..., Any]]],
) -> None:
    """Property 1, with its detectability partner in the same assertions.

    A mutant is unkillable only if it never differs *and* never raises. Naming
    each detectable mutant with its measured counts is what proves this harness
    is not simply blind: eleven separate positive results, not one.
    """
    original, mutants = variants
    cases = _cases()

    assert len(mutants) == EXPECTED_MUTANT_COUNT, (
        f"mutmut now generates {len(mutants)} mutants for {FUNCTION}, not "
        f"{EXPECTED_MUTANT_COUNT}. Re-derive the equivalence claim before "
        f"updating this number: {sorted(mutants)}"
    )

    unkillable = []
    detectable: dict[str, tuple[int, int]] = {}
    for name, mutant in sorted(mutants.items()):
        differs, raises = _detect(mutant, original, cases)
        if differs == 0 and raises == 0:
            unkillable.append(name)
        else:
            detectable[name] = (differs, raises)

    assert unkillable == [], (
        f"{FUNCTION} generates mutant(s) no test can kill: {unkillable}.\n"
        "The mutation gate reports them as survivors and no test can turn it "
        "green. Change the code so they stop being GENERATED — see ADR-0069 — "
        "rather than recording an exception for them.\n"
        f"detectable mutants, with their (differs, raises) counts: {detectable}"
    )
    assert len(detectable) == EXPECTED_MUTANT_COUNT, (
        "this harness detected a difference for only "
        f"{len(detectable)} of {EXPECTED_MUTANT_COUNT} mutants, so the "
        "'nothing is unkillable' assertion above rests on a harness that may "
        f"not be measuring anything. detected: {detectable}"
    )


def test_the_control_mutation_is_detected_by_this_harness(
    variants: tuple[Callable[..., Any], dict[str, Callable[..., Any]]],
) -> None:
    """Property 2, against a change mutmut did not author.

    The test above proves the harness detects mutmut's own mutants. This proves
    it detects a rewrite from outside mutmut's operator table, so a future
    mutmut release generating a different mutant set could not quietly empty
    the partner evidence.

    3,780 is the figure issue #365 records for this same control; it is
    re-derived here rather than inherited.

    Turns red if: `_detect` stops comparing answers, or the function's own
    `max` becomes `min` — measured, that fails verbatim with ``the max->min
    control differs in 0 of 5460 cases``.
    """
    original, _ = variants

    def control(stance: dict[int, str]) -> dict[int, bool]:
        """`max` -> `min`: a real behaviour change, and not one mutmut makes here."""
        sizes: dict[str, int] = {}
        for label in stance.values():
            sizes[label] = sizes.get(label, 0) + 1
        smallest = min(sizes.values())
        winners = [label for label, size in sizes.items() if size == smallest]
        if len(winners) != 1:
            return dict.fromkeys(stance, False)
        return {slot: label == winners[0] for slot, label in stance.items()}

    differs, raises = _detect(control, original, _cases())
    assert raises == 0, f"the control raised in {raises} cases; it must be a clean rewrite"
    assert differs == 3780, (
        f"the max->min control differs in {differs} of {EXPECTED_CASE_COUNT} "
        "cases, not the 3,780 recorded in issue #365 — either the function's "
        "behaviour changed or this harness is no longer measuring what it measured"
    )


def test_the_counter_rewrite_did_not_change_behaviour(
    variants: tuple[Callable[..., Any], dict[str, Callable[..., Any]]],
) -> None:
    """The refactor must be a refactor. #365 / ADR-0069.

    Pins the pre-#365 implementation as an independent reference and requires
    the shipped function to agree with it everywhere. Without this, "Counter is
    equivalent to the hand-rolled tally" is a claim in a commit message.

    Turns red if: the tie posture flips (`False` -> `True` in the tie branch
    differs on 2,016 of 5,460 cases), or `max` becomes `min` (3,780).
    """
    original, _ = variants

    def pre_365_reference(stance: dict[int, str]) -> dict[int, bool]:
        """`synthesis_consensus.py` as it stood before the Counter rewrite."""
        sizes: dict[str, int] = {}
        for label in stance.values():
            sizes[label] = sizes.get(label, 0) + 1
        largest = max(sizes.values())
        winners = [label for label, size in sizes.items() if size == largest]
        if len(winners) != 1:
            return dict.fromkeys(stance, False)
        return {slot: label == winners[0] for slot, label in stance.items()}

    differs, raises = _detect(pre_365_reference, original, _cases())
    assert (differs, raises) == (0, 0), (
        "the Counter rewrite is NOT behaviour-preserving: it differs from the "
        f"pre-#365 implementation in {differs} of {EXPECTED_CASE_COUNT} cases "
        f"and raises in {raises}. Both were measured at 0 when it shipped."
    )
