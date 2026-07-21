"""Composite arithmetic under the DEBT-012 grounding exclusion (D-1.5).

When a run carries any unverifiable off-run URL marker,
``compute_composite`` EXCLUDES ``citation_marker_grounding`` — treating it
as unknown and renormalising, reusing the module's ``None``-is-excluded
doctrine — rather than scoring it. This is not a penalty (a penalty would
be an uncalibrated constant); it is the same "we could not tell" handling
one level up, so a 95%-fabricated run can never name grounding at value 1.0
as its top contributor.

Every test here is hermetic and performs zero I/O.
"""

from __future__ import annotations

import pytest
from tests.unit.test_evaluation_layer_a import REAL_URL, _answer, _source

from product_app.debate import AgreementSummary
from product_app.evaluation import LayerASignals, compute_composite, evaluate_layer_a


def _laundered_signals() -> LayerASignals:
    """The DEBT-012 laundering run: 1 resolving ordinal + 20 off-run links / slot."""
    fabricated = " ".join(
        f"[claim{i}](https://fabricated-{i}.example.org/paper)" for i in range(20)
    )
    evaluation = evaluate_layer_a(
        initial_answers=[
            _answer(
                slot=slot,
                text=f"Therapy reduces mortality by 42% [1]. {fabricated}",
                sources=[_source(REAL_URL)],
            )
            for slot in (1, 2, 3, 4)
        ],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=4, total=4),
    )
    return evaluation.signals


def test_grounding_is_EXCLUDED_from_the_composite_when_unverifiable_markers_exist() -> None:
    """The laundering run's composite moves off the falsely-confident 82.5.

    MEASURED: with grounding INCLUDED (the pre-S3 behaviour, reproduced here
    by zeroing ``unverifiable_marker_count``) the composite is **82.5**, which
    sits with the genuine-faithful band (``faithful-consensus`` **83.50**,
    ``preserved-polar-disagreement`` **83.38**). With the exclusion active it
    drops to **75.0** — grounding 1.0 no longer props it up — so a
    95%-fabricated run no longer scores like a faithful one.
    """
    signals = _laundered_signals()
    assert signals.unverifiable_marker_count == 80

    excluded_composite, _ = compute_composite(signals)
    included_composite, _ = compute_composite(
        signals.model_copy(update={"unverifiable_marker_count": 0})
    )

    # The pre-S3 (no-exclusion) value is the falsely-confident 82.5.
    assert included_composite == pytest.approx(82.5)
    # The exclusion moves it off 82.5 and clear of the genuine-faithful band.
    assert excluded_composite == pytest.approx(75.0)
    assert excluded_composite < 83.38  # below both faithful-band composites


def test_the_contribution_list_omits_grounding_on_an_indeterminate_run() -> None:
    """The "why"/contribution surface can never name grounding at 1.0 here.

    On the 95%-fabricated run, ``citation_marker_grounding`` is absent from
    the contribution list entirely (excluded, not scored), so it can never
    appear as the top contributor at value 1.0.
    """
    signals = _laundered_signals()
    _, contributions = compute_composite(signals)
    names = [c.signal for c in contributions]
    assert "citation_marker_grounding" not in names
    # ...but it IS included when there are no unverifiable markers.
    _, contributions_clean = compute_composite(
        signals.model_copy(update={"unverifiable_marker_count": 0})
    )
    assert "citation_marker_grounding" in [c.signal for c in contributions_clean]
