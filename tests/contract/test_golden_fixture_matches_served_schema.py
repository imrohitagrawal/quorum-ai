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

from product_app.query_runs import QueryRunEvaluationProjection

REPO_ROOT = Path(__file__).resolve().parents[2]
VARIANTS_JSON = REPO_ROOT / "e2e" / "fixtures" / "evaluation-variants.json"

#: The six variants the fixture exposes to the e2e suite. EVAL_S2_SHAPED is
#: DELIBERATELY absent from this file and from validation — it is the
#: fail-closed case (``label_confidence`` deleted), invalid by construction
#: under the current required schema, which is its entire purpose.
EXPECTED_VARIANTS = frozenset(
    {
        "EVAL_CLEAN",
        "EVAL_NON_CONSENSUS",
        "EVAL_UNKNOWN_GROUNDING_REFUSAL",
        "EVAL_LAUNDERED",
        "EVAL_MISSING_HIGH_STAKES",
        "EVAL_SUPPRESSED_DISAGREEMENT",
    }
)


def _load() -> dict[str, dict[str, object]]:
    data = json.loads(VARIANTS_JSON.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def test_the_shared_fixture_exists() -> None:
    assert VARIANTS_JSON.is_file(), f"missing shared fixture: {VARIANTS_JSON}"


def test_the_fixture_carries_exactly_the_six_named_variants() -> None:
    assert set(_load()) == EXPECTED_VARIANTS


@pytest.mark.parametrize("name", sorted(EXPECTED_VARIANTS))
def test_each_variant_validates_against_the_served_projection(name: str) -> None:
    payload = _load()[name]
    projection = QueryRunEvaluationProjection.model_validate(payload)
    # The structural suppression the server enforces (OC-2): while support is
    # unverified the band is "unverified" and there is NO confidence number.
    assert projection.trust.support_verified is False
    assert projection.trust.band == "unverified"
    assert projection.trust.score is None


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
