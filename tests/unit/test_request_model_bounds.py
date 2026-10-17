"""W85: what a request body may HOLD, checked on the models themselves.

A body under the 1 MB limit could still cost hundreds of MB through the 422
it provoked (failure mode A1: 500,000 ``field_errors``, a 47 MB response).
W85 bounds the lists, refuses unknown fields, and makes any number of unknown
keys ONE validation error rather than one per key (A2, Codex plan review 2:
85,000 unknown keys gave 85,000 errors). These tests call
``Model.model_validate`` and count ``ValidationError.error_count()``, so they
pin the error CARDINALITY (AGENTS.md rule 6b), not just that validation fails.

Every bound is pinned with literals on both sides (16 accepted, 17 refused;
8 accepted, 9 refused; 20 errors kept, 21 cut to 20), and every refusal has a
positive partner showing the valid body still validates (rule 7).

The valid bodies are the exact shapes the page sends (failure-modes section C:
``runRequestBody``, ``warningsRequestBody``, ``warningAcknowledgements`` and the
cost-confirmation payload in ``app.js``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from product_app.account_deletion import AccountDeleteRequest
from product_app.costs import CostConfirmation
from product_app.invite_links import InviteAcceptRequest
from product_app.main import _format_validation_error
from product_app.model_slots import default_model_slots
from product_app.query_runs import (
    QueryRunCreateRequest,
    QueryRunEstimateRequest,
    QueryRunWarningsRequest,
)
from product_app.safety import WARNING_VERSION, SafetyAcknowledgement, WarningType

DEFAULT_IDS = [slot.model_id for slot in default_model_slots()]
QUERY = "compare managed database options for a small team"
CONTEXT = {"prior_question": "what is a managed database?", "prior_synthesis": "A service."}
ACKS = [
    {"warning_type": WarningType.SENSITIVE_DATA.value, "version": WARNING_VERSION},
    {"warning_type": WarningType.HIGH_STAKES.value, "version": WARNING_VERSION},
]
COST = {"estimated_cost_usd": "0.0123", "confirmation_token": "token-from-the-estimate"}

# One valid body per model: the page's own shapes where the page sends one.
VALID_BODIES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (QueryRunEstimateRequest, {"query_text": QUERY, "model_slots": DEFAULT_IDS}),
    (
        QueryRunCreateRequest,
        {
            "query_text": QUERY,
            "model_slots": DEFAULT_IDS,
            "safety_acknowledgements": ACKS,
            "cost_confirmation": None,
        },
    ),
    (QueryRunWarningsRequest, {"query_text": QUERY}),
    (SafetyAcknowledgement, dict(ACKS[0])),
    (CostConfirmation, dict(COST)),
    (AccountDeleteRequest, {"confirm_email": "someone@example.com"}),
    (InviteAcceptRequest, {"token": "an-invite-token"}),
]
VALID_IDS = [model.__name__ for model, _ in VALID_BODIES]

# The page's real bodies (app.js). Each must still validate after W85.
PAGE_BODIES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (QueryRunEstimateRequest, {"query_text": QUERY, "model_slots": DEFAULT_IDS}),
    (
        QueryRunEstimateRequest,
        {"query_text": QUERY, "model_slots": DEFAULT_IDS[:1], "mode": "quick"},
    ),
    (
        QueryRunEstimateRequest,
        {"query_text": QUERY, "model_slots": DEFAULT_IDS, "context": CONTEXT},
    ),
    (
        QueryRunCreateRequest,
        {
            "query_text": QUERY,
            "model_slots": DEFAULT_IDS,
            "context": CONTEXT,
            "safety_acknowledgements": ACKS,
            "cost_confirmation": COST,
        },
    ),
    (
        QueryRunCreateRequest,
        {
            "query_text": QUERY,
            "model_slots": DEFAULT_IDS[:1],
            "mode": "quick",
            "safety_acknowledgements": [],
            "cost_confirmation": None,
        },
    ),
    (QueryRunWarningsRequest, {"query_text": QUERY}),
    (QueryRunWarningsRequest, {"query_text": QUERY, "context": CONTEXT}),
]


def _error_count(model: type[BaseModel], body: dict[str, Any]) -> int:
    try:
        model.model_validate(body)
    except ValidationError as exc:
        return exc.error_count()
    return 0


def _errors(model: type[BaseModel], body: dict[str, Any]) -> list[Any]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(body)
    return list(caught.value.errors())


@pytest.mark.parametrize(("model", "body"), VALID_BODIES, ids=VALID_IDS)
def test_the_valid_body_of_every_bounded_model_still_validates(
    model: type[BaseModel], body: dict[str, Any]
) -> None:
    """Red when: a W85 bound or the unknown-key check refuses a body that
    holds only real fields (the positive partner of the refusals below)."""
    assert _error_count(model, body) == 0


@pytest.mark.parametrize(("model", "body"), PAGE_BODIES)
def test_every_body_the_page_sends_still_validates(
    model: type[BaseModel], body: dict[str, Any]
) -> None:
    """Red when: ``extra="forbid"`` or a bound refuses a body shape the page
    sends today (failure-modes section C)."""
    assert _error_count(model, body) == 0


@pytest.mark.parametrize(("model", "body"), VALID_BODIES, ids=VALID_IDS)
def test_one_unknown_field_is_refused(model: type[BaseModel], body: dict[str, Any]) -> None:
    """Red when: a model silently ignores an unknown field (Pydantic's default
    ``extra="ignore"``) instead of refusing it."""
    assert _error_count(model, {**body, "unexpected_field": 1}) == 1


@pytest.mark.parametrize(("model", "body"), VALID_BODIES, ids=VALID_IDS)
def test_a_thousand_unknown_fields_are_one_error_not_a_thousand(
    model: type[BaseModel], body: dict[str, Any]
) -> None:
    """Red when: unknown keys are refused one error per key (plain
    ``extra="forbid"``, A2), or ignored. ``AccountDeleteRequest`` and
    ``InviteAcceptRequest`` already forbid extras and give 1,000 today."""
    unknown = {f"unknown_{index}": index for index in range(1_000)}
    assert _error_count(model, {**body, **unknown}) == 1


def test_an_unknown_key_inside_an_acknowledgement_on_create_is_refused() -> None:
    """Red when: a nested ``SafetyAcknowledgement`` ignores an unknown key."""
    body = {
        "query_text": QUERY,
        "model_slots": DEFAULT_IDS,
        "safety_acknowledgements": [{**ACKS[0], "unexpected_field": 1}],
    }
    assert _error_count(QueryRunCreateRequest, body) == 1


def test_an_unknown_key_inside_cost_confirmation_on_create_is_refused() -> None:
    """Red when: a nested ``CostConfirmation`` ignores an unknown key."""
    body = {
        "query_text": QUERY,
        "model_slots": DEFAULT_IDS,
        "cost_confirmation": {**COST, "unexpected_field": 1},
    }
    assert _error_count(QueryRunCreateRequest, body) == 1


@pytest.mark.parametrize("model", [QueryRunEstimateRequest, QueryRunCreateRequest])
def test_model_slots_hold_16_but_not_17(model: type[BaseModel]) -> None:
    """Red when: ``model_slots`` loses its bound of 16, or the bound is set
    below 16 (5 to 16 must still reach the typed ``INVALID_MODEL_SLOT`` check,
    A9)."""
    assert _error_count(model, {"query_text": QUERY, "model_slots": ["m"] * 16}) == 0
    errors = _errors(model, {"query_text": QUERY, "model_slots": ["m"] * 17})
    assert [(e["type"], tuple(e["loc"])) for e in errors] == [("too_long", ("model_slots",))]


def test_a_million_byte_model_slots_list_is_one_error() -> None:
    """Red when: ``model_slots`` is unbounded, so 500,000 wrong items are
    500,000 errors (A1 measured 47.4 MB of 422 for this body)."""
    errors = _errors(QueryRunEstimateRequest, {"query_text": "x", "model_slots": [1] * 500_000})
    assert len(errors) == 1
    assert errors[0]["type"] == "too_long"


@pytest.mark.parametrize("model", [QueryRunEstimateRequest, QueryRunCreateRequest])
def test_slot_search_holds_16_but_not_17(model: type[BaseModel]) -> None:
    """Red when: ``slot_search`` loses its bound of 16 or gets a smaller one."""
    base = {"query_text": QUERY, "model_slots": DEFAULT_IDS}
    assert _error_count(model, {**base, "slot_search": [True] * 16}) == 0
    errors = _errors(model, {**base, "slot_search": [True] * 17})
    assert [(e["type"], tuple(e["loc"])) for e in errors] == [("too_long", ("slot_search",))]


def test_safety_acknowledgements_hold_8_but_not_9() -> None:
    """Red when: ``safety_acknowledgements`` loses its bound of 8 or gets a
    smaller one (A1: 300,000 empty items were 600,000 errors)."""
    base = {"query_text": QUERY, "model_slots": DEFAULT_IDS}
    eight = (ACKS * 4)[:8]
    nine = (ACKS * 5)[:9]
    assert len(eight) == 8 and len(nine) == 9
    assert _error_count(QueryRunCreateRequest, {**base, "safety_acknowledgements": eight}) == 0
    errors = _errors(QueryRunCreateRequest, {**base, "safety_acknowledgements": nine})
    assert [(e["type"], tuple(e["loc"])) for e in errors] == [
        ("too_long", ("safety_acknowledgements",))
    ]


@pytest.mark.parametrize("model", [QueryRunEstimateRequest, QueryRunWarningsRequest])
def test_context_null_is_still_accepted(model: type[BaseModel]) -> None:
    """Red when: the context check stops letting ``None`` through (the
    schema advertises ``context: null``, Codex plan review 3)."""
    body: dict[str, Any] = {"query_text": QUERY, "context": None}
    if model is QueryRunEstimateRequest:
        body["model_slots"] = DEFAULT_IDS
    assert _error_count(model, body) == 0


@pytest.mark.parametrize("model", [QueryRunEstimateRequest, QueryRunWarningsRequest])
def test_a_context_with_80_000_wrong_keys_is_one_error_naming_none_of_them(
    model: type[BaseModel],
) -> None:
    """Red when: unknown context keys are checked value by value (80,000
    ``string_type`` errors, A1) or the one error's message echoes the keys
    sent (a 789 KB echo, A1)."""
    context = {f"sent_key_{index}": index for index in range(80_000)}
    body: dict[str, Any] = {"query_text": QUERY, "context": context}
    if model is QueryRunEstimateRequest:
        body["model_slots"] = DEFAULT_IDS
    errors = _errors(model, body)
    assert len(errors) == 1
    assert "sent_key_" not in str(errors[0].get("msg", ""))
    assert "sent_key_" not in repr(errors[0].get("ctx", {}))


def _validation_error(types: list[str]) -> RequestValidationError:
    return RequestValidationError(
        [
            {"type": kind, "loc": ("body", f"field_{index}"), "msg": f"message {index}"}
            for index, kind in enumerate(types)
        ]
    )


def _field_errors(exc: RequestValidationError) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    response = _format_validation_error(exc)
    detail = json.loads(bytes(response.body))["detail"]
    return detail, list(detail["field_errors"])


def test_twenty_validation_errors_are_all_returned() -> None:
    """Red when: the cap on ``field_errors`` is set below 20."""
    _detail, field_errors = _field_errors(_validation_error(["value_error"] * 20))
    assert [e["field"] for e in field_errors] == [f"field_{i}" for i in range(20)]


def test_twenty_one_validation_errors_are_cut_to_the_first_twenty() -> None:
    """Red when: ``_format_validation_error`` returns every error (A1: 500,000
    of them), a cap above 20, or not the FIRST twenty."""
    _detail, field_errors = _field_errors(_validation_error(["value_error"] * 21))
    assert [e["field"] for e in field_errors] == [f"field_{i}" for i in range(20)]


def test_two_validation_errors_are_both_returned() -> None:
    """Red when: the cap drops errors from a small body (the positive partner
    of the cut above)."""
    _detail, field_errors = _field_errors(_validation_error(["missing", "string_too_short"]))
    assert [e["field"] for e in field_errors] == ["field_0", "field_1"]


def test_the_banner_code_is_picked_from_the_errors_returned() -> None:
    """Red when: the banner code is chosen from errors the response no longer
    shows (a 21st ``string_too_long`` must not make the banner
    ``QUERY_TOO_LONG``), or from fewer than the returned 20."""
    beyond, _ = _field_errors(_validation_error(["value_error"] * 20 + ["string_too_long"]))
    assert beyond["code"] == "VALIDATION_ERROR"
    within, _ = _field_errors(_validation_error(["value_error"] * 19 + ["string_too_long"]))
    assert within["code"] == "QUERY_TOO_LONG"
