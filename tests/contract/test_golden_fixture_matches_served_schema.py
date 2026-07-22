"""The e2e evaluation fixtures must encode ONLY shapes the server can serve.

The mocked Playwright suites drive the trust-score surface from
``e2e/fixtures/evaluation-variants.json``. If a hand-authored fixture drifts
from the real ``QueryRunEvaluationProjection`` — a key the server never emits, a
``score`` on an ``unverified`` band, a missing required field — the mocked specs
could go green on a payload production can never produce, exactly the
"simulated data hides real bugs" failure mode. This gate validates every shared
variant against the real Pydantic model, so a drift fails in Python (cheap,
blocking) rather than shipping a green-but-wrong UI gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from product_app.evaluation import RunEvaluation, build_trust_score
from product_app.query_runs import QueryRunEvaluationProjection

REPO_ROOT = Path(__file__).resolve().parents[2]
VARIANTS_JSON = REPO_ROOT / "e2e" / "fixtures" / "evaluation-variants.json"

#: The verified variant(s) — P1 / FR-015 judge wiring. Their trust object is
#: NOT hand-authored: ``test_the_verified_variant_is_exactly_what_the_engine_emits``
#: recomputes it through ``build_trust_score(support_verified=True)``, so a
#: fabricated score or band cannot ride into the e2e suite.
VERIFIED_VARIANTS = frozenset({"EVAL_VERIFIED_HIGH"})

#: The six unverified variants the fixture exposes to the e2e suite.
#: EVAL_S2_SHAPED is DELIBERATELY absent from this file and from validation —
#: it is the fail-closed case (``label_confidence`` deleted), invalid by
#: construction under the current required schema, which is its entire purpose.
UNVERIFIED_VARIANTS = frozenset(
    {
        "EVAL_CLEAN",
        "EVAL_NON_CONSENSUS",
        "EVAL_UNKNOWN_GROUNDING_REFUSAL",
        "EVAL_LAUNDERED",
        "EVAL_MISSING_HIGH_STAKES",
        "EVAL_SUPPRESSED_DISAGREEMENT",
    }
)

EXPECTED_VARIANTS = UNVERIFIED_VARIANTS | VERIFIED_VARIANTS


def _load() -> dict[str, dict[str, object]]:
    data = json.loads(VARIANTS_JSON.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def test_the_shared_fixture_exists() -> None:
    assert VARIANTS_JSON.is_file(), f"missing shared fixture: {VARIANTS_JSON}"


def test_the_fixture_carries_exactly_the_named_variants() -> None:
    assert set(_load()) == EXPECTED_VARIANTS


@pytest.mark.parametrize("name", sorted(UNVERIFIED_VARIANTS))
def test_each_unverified_variant_validates_against_the_served_projection(name: str) -> None:
    payload = _load()[name]
    projection = QueryRunEvaluationProjection.model_validate(payload)
    # The structural suppression the server enforces (OC-2): while support is
    # unverified the band is "unverified" and there is NO confidence number.
    assert projection.trust.support_verified is False
    assert projection.trust.band == "unverified"
    assert projection.trust.score is None


@pytest.mark.parametrize("name", sorted(VERIFIED_VARIANTS))
def test_the_verified_variant_is_exactly_what_the_engine_emits(name: str) -> None:
    """The verified fixture may carry ONLY an engine-derived trust object.

    Both directions of the loosened gate: the six unverified variants still
    fail on any score-on-unverified drift (test above), AND the verified
    variant cannot fabricate a number — its whole trust payload must equal
    ``build_trust_score(support_verified=True)`` recomputed from its own
    signals, byte for byte.
    """
    payload = _load()[name]
    projection = QueryRunEvaluationProjection.model_validate(payload)
    assert projection.trust.support_verified is True

    recomputed = build_trust_score(
        RunEvaluation.model_validate(
            {
                "signals": payload["signals"],
                "faithfulness_label": payload["faithfulness_label"],
                "hallucination_risk": payload["hallucination_risk"],
            }
        ),
        support_verified=True,
    )
    assert projection.trust.model_dump(mode="json") == recomputed.model_dump(mode="json")
    assert recomputed.score is not None and recomputed.band in {"low", "moderate", "high"}


def test_the_laundered_variant_is_indeterminate_and_the_clean_one_reportable() -> None:
    variants = _load()
    assert variants["EVAL_LAUNDERED"]["label_confidence"] == "indeterminate"
    assert variants["EVAL_CLEAN"]["label_confidence"] == "reportable"


def test_no_variant_carries_a_free_text_field() -> None:
    """D-15: the projection is metrics only — no reason/why/explanation/rationale
    string may exist at any depth, so the no-markdown claim on the surface stays
    honestly vacuous (there is nothing provider-derived to escape)."""
    banned = {"reason", "why", "explanation", "rationale", "note", "notes", "text"}

    def walk(obj: object, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in banned, f"free-text key {path}.{k} is forbidden"
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    for name, payload in _load().items():
        walk(payload, name)
