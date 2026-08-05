"""The S2 ``evaluation`` field is ADDITIVE, hence backward compatible.

A response field is only backward compatible if an existing client can ignore
it: the field must be optional (nullable, not in ``required``) and it must not
have changed the pre-S2 contract in any other way. Both halves are asserted
against the live ``app.openapi()`` schema — the same render the checked-in
``openapi.yaml`` drift-guard compares against — rather than against prose.
"""

from __future__ import annotations

from typing import Any

from product_app.main import app
from product_app.query_runs import QueryRunResultResponse

#: The exact ``required`` set of ``QueryRunResultResponse`` before S2, read off
#: the live schema at 2026-07-20 (`app.openapi()`), 13 fields. S2 may ADD an
#: optional field; it may not make anything new required and it may not drop
#: or rename any of these.
PRE_S2_REQUIRED = {
    "actual_cost_usd",
    "correlation_id",
    "cost_estimate",
    "elapsed_time_ms",
    "failed_steps",
    "missing_steps",
    "model_slots",
    "progress",
    "provider_failure_notices",
    "query_run_id",
    "result",
    "result_generated_at_utc",
    "status",
}

#: Every property the pre-S2 contract exposed, same source, 20 fields.
#: Issue #100 added ``global_spend_ceiling_reached`` (optional, defaulted)
#: after S2 shipped — folded in here rather than into the S2-specific
#: assertion below, which stays pinned to exactly ``{"evaluation"}`` so it
#: keeps meaning what its name says.
PRE_S2_PROPERTIES = PRE_S2_REQUIRED | {
    "actual_breakdown",
    "cost_source",
    "demo_mode",
    "live_count",
    "local_count",
    "material_claim_count",
    "partial_failure_notice",
    "global_spend_ceiling_reached",
}


def _result_schema() -> dict[str, Any]:
    schema: dict[str, Any] = app.openapi()["components"]["schemas"]["QueryRunResultResponse"]
    return schema


def test_evaluation_field_is_optional_and_nullable() -> None:
    schema = _result_schema()

    assert "evaluation" in schema["properties"], "S2 must expose an evaluation field"
    assert "evaluation" not in schema["required"], (
        "evaluation must be optional: a pre-S2 client that ignores it stays valid"
    )

    # Optional pydantic models render as anyOf[$ref, null]; the field must be
    # nullable so an existing consumer that reads it on a non-terminal run
    # gets an explicit null rather than a schema violation.
    field = schema["properties"]["evaluation"]
    assert any(option.get("type") == "null" for option in field["anyOf"]), field

    # And it is optional on the model itself, so a caller constructing the
    # response without it stays valid.
    assert QueryRunResultResponse.model_fields["evaluation"].is_required() is False


def test_no_pre_s2_field_was_changed_or_made_required() -> None:
    schema = _result_schema()

    assert set(schema["required"]) == PRE_S2_REQUIRED, (
        "the required set changed — that is a breaking contract change, not an additive one"
    )
    assert set(schema["properties"]) >= PRE_S2_PROPERTIES
    # The two assertions above ARE the contract this test is named for, and
    # neither moves: no pre-S2 field changed and the required set is identical.
    # This third one pins the ADDITIVE delta so an unplanned field cannot
    # arrive unnoticed — it still fails for anything not named here.
    #
    # ``spend_metering_unavailable`` joined ``evaluation`` in ADR-0016. It is
    # optional with a ``False`` default, so a pre-S2 client that ignores it
    # stays valid. It is on the wire because without it the demo-mode banner
    # falls through to "live execution is turned off", which is FALSE on that
    # path — live execution is on and a key is configured; the spend LEDGER is
    # what failed.
    assert set(schema["properties"]) - PRE_S2_PROPERTIES == {
        "evaluation",
        "spend_metering_unavailable",
    }, "an unplanned field was added to QueryRunResultResponse"


def test_served_evaluation_never_declares_a_judge_rationale() -> None:
    """Judge prose is metrics-only-excluded by contract, not by convention."""
    schemas = app.openapi()["components"]["schemas"]
    projection = schemas["QueryRunEvaluationProjection"]

    assert "judge" not in projection["properties"]
    assert "rationale" not in projection["properties"]
