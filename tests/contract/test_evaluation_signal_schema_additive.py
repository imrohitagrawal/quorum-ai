"""The S3 evaluation-schema changes are ADDITIVE at the sub-schema level (D-9).

`tests/contract/test_query_run_evaluation_additive.py` pins only the top-level
`QueryRunResultResponse`. A new REQUIRED field on a nested schema
(`LayerASignals`) would be a breaking change for a schema-validating client
with every top-level gate still green. This module freezes the PRE-S3
`required` and `properties` sets of the four evaluation sub-schemas and asserts:

* the two new signals `unverifiable_marker_count` / `unverifiable_marker_ratio`
  are present in `LayerASignals.properties` but ABSENT from its `required` set
  (they carry defaults ⇒ optional ⇒ additive);
* `TrustScore` and `TrustDiagnostics` are wholly unchanged;
* `QueryRunEvaluationProjection` gains exactly one new REQUIRED field,
  `label_confidence`. This is a DELIBERATE, reviewed addition: the projection
  is a new schema shipped in the same release as its only client, and
  `label_confidence` has NO default precisely so a projection can never be
  constructed — or served — without an explicit presentation verdict (D-3,
  fail closed). It is recorded here as intentional, not additive.

Asserted against the live `app.openapi()` render — the same schema the
`openapi.yaml` drift-guard compares against — never against prose.
"""

from __future__ import annotations

from typing import Any

from product_app.main import app

#: PRE-S3 `required` set of `LayerASignals`, read off the live schema, 13
#: fields. `citation_marker_grounding` is already optional (nullable default),
#: so it was never in `required`; the two new signals must likewise stay out.
PRE_S3_SIGNALS_REQUIRED = {
    "agreement_ratio",
    "citation_coverage_ratio",
    "completeness",
    "decision_support_framing_present",
    "disagreement_suppressed",
    "false_consensus_preserved",
    "high_stakes_warning_present",
    "high_stakes_warning_required",
    "live_ratio",
    "polar_disagreement_detected",
    "refusal_detected",
    "run_wholly_refused",
    "uncertainty_surfaced",
}

PRE_S3_SIGNALS_PROPERTIES = PRE_S3_SIGNALS_REQUIRED | {"citation_marker_grounding"}

#: The two new signals, added in S3.
NEW_SIGNALS = {"unverifiable_marker_count", "unverifiable_marker_ratio"}

#: PRE-S3 `required`/`properties` of the trust sub-schemas, unchanged by S3.
TRUST_SCORE_REQUIRED = {"band", "diagnostics", "support_verified"}
TRUST_SCORE_PROPERTIES = TRUST_SCORE_REQUIRED | {"score"}
TRUST_DIAGNOSTICS_REQUIRED = {"contributions", "layer_a_composite_unverified"}
TRUST_DIAGNOSTICS_PROPERTIES = TRUST_DIAGNOSTICS_REQUIRED

#: PRE-S3 `required` set of `QueryRunEvaluationProjection`, 5 fields. S3 adds
#: exactly one new REQUIRED field: `label_confidence`.
PRE_S3_PROJECTION_REQUIRED = {
    "faithfulness_label",
    "hallucination_risk",
    "schema_version",
    "signals",
    "trust",
}


def _schema(name: str) -> dict[str, Any]:
    schema: dict[str, Any] = app.openapi()["components"]["schemas"][name]
    return schema


def test_the_two_new_signals_are_optional_not_required() -> None:
    schema = _schema("LayerASignals")
    required = set(schema["required"])
    properties = set(schema["properties"])

    # The pre-S3 required set is UNCHANGED — nothing new became required.
    assert required == PRE_S3_SIGNALS_REQUIRED, (
        "a signal became required — that is a breaking change, not an additive one"
    )
    # The new signals exist as properties...
    assert properties >= NEW_SIGNALS
    # ...but are ABSENT from required (they carry defaults ⇒ additive).
    assert not (NEW_SIGNALS & required)
    # And no signal other than the two new ones appeared.
    assert properties - PRE_S3_SIGNALS_PROPERTIES == NEW_SIGNALS


def test_trust_score_and_diagnostics_are_unchanged() -> None:
    trust = _schema("TrustScore")
    assert set(trust["required"]) == TRUST_SCORE_REQUIRED
    assert set(trust["properties"]) == TRUST_SCORE_PROPERTIES

    diagnostics = _schema("TrustDiagnostics")
    assert set(diagnostics["required"]) == TRUST_DIAGNOSTICS_REQUIRED
    assert set(diagnostics["properties"]) == TRUST_DIAGNOSTICS_PROPERTIES


def test_label_confidence_is_a_deliberate_new_required_field() -> None:
    """`label_confidence` is a NEW REQUIRED field — deliberate, not additive.

    It has no default so a projection can never be constructed without an
    explicit presentation verdict (D-3, fail closed). The projection is a new
    schema shipped with its only client, so a new required field is safe here;
    this test records the decision so a future reviewer sees it was intended.
    """
    projection = _schema("QueryRunEvaluationProjection")
    required = set(projection["required"])

    assert required == PRE_S3_PROJECTION_REQUIRED | {"label_confidence"}
    assert required - PRE_S3_PROJECTION_REQUIRED == {"label_confidence"}
    # It must NOT be nullable/optional — fail-closed requires it be mandatory.
    assert "label_confidence" in projection["properties"]
