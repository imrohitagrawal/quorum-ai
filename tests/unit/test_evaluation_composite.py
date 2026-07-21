"""A KNOWN grounding is always scored — never renormalised away (DEBT-012, R2-S3).

``compute_composite`` excludes ``citation_marker_grounding`` from the weighted
composite ONLY when it is ``None`` (the run carried no resolvable citation
marker at all), reusing the module's "unknown, not zero" doctrine. It does
**not** drop a *known* grounding because off-run URL markers happen to coexist:
grounding is computed only over resolvable markers, so it is already clean of
those URLs, and dropping a correctly-LOW grounding would INFLATE the composite
of a fabricating run and delete its strongest reason-to-doubt from the
contribution list. The laundering defence lives entirely in
``presentation_confidence`` + the zero-digit UI, which are orthogonal to this
composite (a laundering run is served ``indeterminate``, so its composite and
contributions are never rendered at all).

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


def test_a_known_grounding_is_never_dropped_from_the_composite() -> None:
    """The presence of off-run URL markers must NOT renormalise a known grounding away.

    The laundering run has grounding 1.0 (one resolving ordinal / one resolvable
    marker) and 80 unverifiable off-run URL markers. The composite scores
    grounding exactly as if the URLs were absent — i.e. ``unverifiable_marker_
    count`` has NO effect on the composite. Whatever the composite is, it must
    equal the value computed with the unverifiable count zeroed.
    """
    signals = _laundered_signals()
    assert signals.unverifiable_marker_count == 80

    with_urls, _ = compute_composite(signals)
    without_urls, _ = compute_composite(signals.model_copy(update={"unverifiable_marker_count": 0}))

    # Grounding is scored the same either way — no presence-keyed exclusion.
    assert with_urls == pytest.approx(without_urls)
    # And grounding 1.0 genuinely contributes (this is the honest, if uncalibrated,
    # composite; the laundering run is defended by presentation_confidence, not here).
    assert with_urls == pytest.approx(82.5)


def test_grounding_is_present_in_contributions_whenever_resolvable_markers_exist() -> None:
    """The contribution/"why" surface must carry grounding whenever it is KNOWN.

    On a fabricating run whose grounding is correctly LOW, that grounding is the
    single strongest reason-to-doubt; excluding it (as the old presence-keyed
    rule did) would delete it from the diagnostic. Grounding is present in the
    contribution list whenever the census has any resolvable marker, regardless
    of how many unverifiable off-run URLs coexist.
    """
    signals = _laundered_signals()
    _, contributions = compute_composite(signals)
    names = [c.signal for c in contributions]
    assert "citation_marker_grounding" in names
    # It is present with or without the unverifiable markers — presence is
    # governed by resolvable>0 (grounding is not None), never by the URL count.
    _, contributions_no_urls = compute_composite(
        signals.model_copy(update={"unverifiable_marker_count": 0})
    )
    assert "citation_marker_grounding" in [c.signal for c in contributions_no_urls]


def test_an_unknown_grounding_is_still_excluded_when_there_are_no_resolvable_markers() -> None:
    """The genuine "unknown, not zero" path survives: grounding None (no resolvable
    marker at all) ⇒ excluded and the remaining weights renormalise."""
    signals = _laundered_signals().model_copy(update={"citation_marker_grounding": None})
    _, contributions = compute_composite(signals)
    assert "citation_marker_grounding" not in [c.signal for c in contributions]
