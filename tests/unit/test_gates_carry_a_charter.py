"""Every registered gate says why it exists — and when to delete it.

GATE CHARTER
------------
WHY THIS EXISTS: a gate whose rationale is lost becomes either cargo cult or
casualty. A future session hits it red, cannot tell whether it is load-bearing,
and either deletes it (losing the protection) or adds an exemption (losing the
point). This repo already warns against the second — "Never lower a threshold,
add `# pragma: no cover`, or delete a test to go green" — but a warning does not
tell you which gates are safe to retire.

The field that matters most is WHEN TO REMOVE. A gate without a removal
condition is permanent by default, and that is how a gate suite turns into
sludge nobody dares touch. Every charter here must name the condition that
retires it.

WHAT IT CANNOT SEE: quality. It checks the four sections are PRESENT, not that
they are honest — "WHEN TO REMOVE: never" would pass. That is a real limit and
the reason this is a cheap presence check rather than something cleverer;
judging a rationale is a reviewer's job, not a regex's.

FALSE-POSITIVE COST: zero. It fires only on a registered file missing a
section.

WHEN TO REMOVE: when gate rationale lives somewhere with its own tooling (an
ADR per gate, or a register generated from source). Until then this is the
cheapest thing that keeps the four questions answered.

SCOPE, deliberately narrow: `_CHARTERED_GATES` starts with the gates added on
2026-08-03 and grows as gates are added. The ~30 pre-existing entries in
`docs/analysis/03-enforcement-machinery.md` are NOT retrofitted — a meta-gate
that opens red against unrelated history gets deleted, which is the failure
mode this file exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Gates that must carry a charter. Add a gate here when you add the gate.
_CHARTERED_GATES = (
    "tests/unit/test_adr_index_matches_directory.py",
    "tests/unit/test_spend_cap_state_table.py",
    "tests/unit/test_cited_paths_resolve.py",
    "tests/unit/test_gates_carry_a_charter.py",
    "tests/unit/test_no_mutation_pragma_silences_a_survivor.py",
    "tests/unit/test_no_decorator_silences_a_mutation_surface.py",
)

_REQUIRED_SECTIONS = (
    "WHY THIS EXISTS:",
    "WHAT IT CANNOT SEE:",
    "FALSE-POSITIVE COST:",
    "WHEN TO REMOVE:",
)


@pytest.mark.parametrize("gate", _CHARTERED_GATES)
def test_the_gate_answers_all_four_charter_questions(gate: str) -> None:
    """Turns red if: a registered gate drops a charter section.

    The four questions are the ones a future maintainer actually has when a
    gate blocks them: why is this here, what does it miss, what does it cost
    me, and am I allowed to delete it yet?
    """
    path = ROOT / gate
    assert path.exists(), f"{gate} is registered as chartered but does not exist"
    text = path.read_text(encoding="utf-8")

    missing = [s for s in _REQUIRED_SECTIONS if s not in text]
    assert not missing, (
        f"{gate} is missing charter section(s): {missing}. "
        "A gate whose rationale is lost becomes cargo cult or casualty."
    )


def test_the_registry_is_not_empty_and_points_at_real_files() -> None:
    """Anti-vacuity. "No gate is missing a charter" is trivially true over an
    empty registry, which is exactly how this check would rot."""
    assert len(_CHARTERED_GATES) >= 4
    for gate in _CHARTERED_GATES:
        assert (ROOT / gate).exists(), gate


def test_every_removal_condition_says_something() -> None:
    """ "WHEN TO REMOVE" must carry a condition, not a placeholder.

    Cannot judge honesty -- see the charter above -- but it can refuse an
    empty or one-word answer, which is the cheapest form of the failure.
    """
    for gate in _CHARTERED_GATES:
        text = (ROOT / gate).read_text(encoding="utf-8")
        after = text.split("WHEN TO REMOVE:", 1)[1]
        condition = after.split("\n\n", 1)[0].strip()
        assert len(condition) >= 40, (
            f"{gate}: 'WHEN TO REMOVE' is {len(condition)} chars — name the "
            "condition that retires this gate, or it is permanent by default"
        )
