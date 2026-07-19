"""OC-2: trust-vs-truth calibration gate.

The headline S2 claim is not "the evaluation code runs" — it is "the trust
figure a USER SEES is not a lie". This module is the oracle for that, and
it is built around one adversarial pair from the frozen corpus:

* ``faithful-consensus`` — four live answers, three real sources, every
  inline citation marker resolves.
* ``fluent-unfaithful`` — the SAME question, the SAME four models, the
  SAME three real sources attached to the same slots, prose of the same
  length and register, but the inline markers point at ordinals and URLs
  that exist nowhere on the run.

:func:`test_count_only_citation_proxy_cannot_tell_faithful_from_unfaithful`
is the standing proof of why the suppression rule and the new
``citation_marker_grounding`` signal exist. It must stay green forever: the
day it goes red, either the corpus pair stopped being adversarial or the
count-only proxy quietly changed meaning, and the argument underneath the
whole design needs re-making.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from product_app.evaluation import (
    build_trust_score,
    evaluate_layer_a,
)
from product_app.providers import (
    calculate_citation_coverage,
    estimate_material_claim_count,
)

_LOADER_PATH = Path(__file__).resolve().parent / "corpus" / "loader.py"
_spec = importlib.util.spec_from_file_location("s2_corpus_loader", _LOADER_PATH)
assert _spec is not None and _spec.loader is not None
corpus = importlib.util.module_from_spec(_spec)
sys.modules["s2_corpus_loader"] = corpus
_spec.loader.exec_module(corpus)


FAITHFUL = "faithful-consensus"
UNFAITHFUL = "fluent-unfaithful"


def _evaluate(case_id: str) -> Any:
    case = corpus.load_case(case_id)
    return evaluate_layer_a(
        initial_answers=case.initial_answers,
        final_synthesis=case.final_synthesis,
        agreement=case.agreement,
    )


def test_count_only_citation_proxy_cannot_tell_faithful_from_unfaithful() -> None:
    """The documented failure that motivates the whole OC-2 mechanism.

    ``estimate_material_claim_count`` and ``calculate_citation_coverage`` are
    the MVP's only grounding signals. Run them over both members of the
    adversarial pair: every number is identical. A count says a citation is
    present; it says nothing about whether the citation resolves to anything,
    let alone whether it supports the claim.
    """
    faithful = corpus.load_case(FAITHFUL)
    unfaithful = corpus.load_case(UNFAITHFUL)

    faithful_counts = [
        estimate_material_claim_count(a.answer_text) for a in faithful.initial_answers
    ]
    unfaithful_counts = [
        estimate_material_claim_count(a.answer_text) for a in unfaithful.initial_answers
    ]
    assert faithful_counts == unfaithful_counts, (
        "the corpus pair is no longer adversarial: the count-only proxy can now "
        f"separate them by length ({faithful_counts} vs {unfaithful_counts}). "
        "Re-balance the fixtures — this proof depends on them being indistinguishable."
    )

    def _aggregate(case: Any) -> Any:
        return calculate_citation_coverage(
            material_claim_count=sum(
                a.citation_coverage.material_claim_count for a in case.initial_answers
            ),
            cited_claim_count=sum(
                1 for a in case.initial_answers if any(not s.is_fallback for s in a.sources)
            ),
        )

    assert _aggregate(faithful) == _aggregate(unfaithful)

    # Same for every count the result surface already shows a user.
    assert faithful.agreement == unfaithful.agreement
    assert [len(a.sources) for a in faithful.initial_answers] == [
        len(a.sources) for a in unfaithful.initial_answers
    ]


def test_citation_marker_grounding_separates_the_pair_the_counts_cannot() -> None:
    """The new deterministic Layer-A signal is what actually distinguishes them."""
    faithful = _evaluate(FAITHFUL)
    unfaithful = _evaluate(UNFAITHFUL)

    assert faithful.signals.citation_marker_grounding == pytest.approx(1.0)
    assert unfaithful.signals.citation_marker_grounding is not None
    assert unfaithful.signals.citation_marker_grounding < 0.2

    # ...and it drives the raw composite DOWN, with zero I/O.
    faithful_trust = build_trust_score(faithful)
    unfaithful_trust = build_trust_score(unfaithful)
    assert (
        unfaithful_trust.diagnostics.layer_a_composite_unverified
        < faithful_trust.diagnostics.layer_a_composite_unverified
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "faithful-consensus",
        "fluent-unfaithful",
        "preserved-polar-disagreement",
        "refusal",
        "simulated-low-live-ratio",
    ],
)
def test_no_case_is_served_a_confidence_figure_without_a_real_judge(case_id: str) -> None:
    """The binding honesty rule (AC-041), asserted on every corpus case."""
    trust = build_trust_score(_evaluate(case_id))
    assert trust.support_verified is False
    assert trust.band == "unverified"
    assert trust.score is None
    assert trust.served_confidence() is None


def _numeric_leaves(payload: object, path: str = "") -> list[tuple[str, float]]:
    """Every number in a serialized payload, with its full key path."""
    found: list[tuple[str, float]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.extend(_numeric_leaves(value, f"{path}.{key}" if path else str(key)))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_numeric_leaves(value, f"{path}[{index}]"))
    elif isinstance(payload, bool):
        pass
    elif isinstance(payload, (int, float)):
        found.append((path, float(payload)))
    return found


def test_a_consumer_cannot_read_a_high_confidence_number_for_the_unfaithful_case() -> None:
    """Structural, not a comment: walk the serialized payload a consumer gets.

    Every number that survives serialization must either be explicitly
    labeled unverified/advisory by its own key path, or be a per-component
    diagnostic under ``contributions``. There is no key a naive client can
    read as "confidence".
    """
    trust = build_trust_score(_evaluate(UNFAITHFUL))
    payload = trust.model_dump(mode="json")

    assert payload["score"] is None
    assert payload["band"] == "unverified"
    assert payload["support_verified"] is False

    for key_path, _value in _numeric_leaves(payload):
        assert "unverified" in key_path or key_path.startswith("diagnostics.contributions"), (
            f"{key_path} is a bare number in the served trust payload; a consumer could "
            "read it as a verified confidence figure. Every number here must be "
            "explicitly labeled unverified or scoped to a per-component contribution."
        )


def test_the_unfaithful_case_never_outranks_the_faithful_one() -> None:
    """Calibration direction: fluency must not buy trust."""
    faithful = build_trust_score(_evaluate(FAITHFUL))
    unfaithful = build_trust_score(_evaluate(UNFAITHFUL))
    delta = (
        faithful.diagnostics.layer_a_composite_unverified
        - unfaithful.diagnostics.layer_a_composite_unverified
    )
    # The gap is entirely the citation-marker-grounding weight (advisory,
    # FS-6): both cases are identical on every other Layer-A signal, so the
    # measured delta is the weight itself times the grounding delta.
    assert delta > 20.0
