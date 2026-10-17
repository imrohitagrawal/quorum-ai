"""W85: a body under 1 MB must not buy a huge 422, through the real routes.

Failure mode A1 (measured on ``main`` at ``a2af06c`` with one anonymous
cookie): a 1,000,034-byte estimate body of ``model_slots: [1, 1, ...]`` was
answered 422 with 500,000 ``field_errors``, a 47.4 MB response, a 521 MB peak
and 7.3 s on the event loop. ``[{}]*N`` acknowledgements, an 80,000-key
context and (once unknown fields are refused) 111,000 unknown keys do the
same. Each case here is posted to the route a client would use, its own
length asserted under 1,048,576 so the 413 cannot be what answers it, and the
answer must be a 422 with at most 20 ``field_errors`` and a small body.

Positive partners (rule 7): a two-error body still returns both errors, the
page's real bodies are still accepted by ``/estimate`` and ``/warnings``, and
``context: null`` still works.

No run is created. The create-route calls send no CSRF token: validation runs
BEFORE the handler, so the W85 refusal answers 422 first, and without W85 the
handler's CSRF check answers 403 and nothing is started.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from product_app.main import app
from product_app.model_slots import default_model_slots
from product_app.safety import WARNING_VERSION, WarningType

DEFAULT_IDS = [slot.model_id for slot in default_model_slots()]
QUERY = "compare managed database options for a small team"
CONTEXT = {"prior_question": "what is a managed database?", "prior_synthesis": "A service."}
ACKS = [
    {"warning_type": WarningType.SENSITIVE_DATA.value, "version": WARNING_VERSION},
    {"warning_type": WarningType.HIGH_STAKES.value, "version": WARNING_VERSION},
]
#: A small 422 holds at most 20 short field errors; 10,000 bytes is generous
#: for that and about 1/4,700 of A1's 47.4 MB.
SMALL_RESPONSE_BYTES = 10_000


def _compact(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode()


_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _short_keys(count: int) -> list[str]:
    """``count`` distinct keys of one to three letters or digits, shortest
    first, so many keys fit under 1 MB. None can be a real field name: every
    field name is longer than three characters."""
    keys: list[str] = []
    width = 1
    while len(keys) < count:
        for index in range(len(_ALPHABET) ** width):
            if len(keys) == count:
                break
            word = ""
            for _ in range(width):
                index, digit = divmod(index, len(_ALPHABET))
                word += _ALPHABET[digit]
            keys.append(word)
        width += 1
    assert len(set(keys)) == count and max(len(key) for key in keys) <= 3
    return keys


def _client_with_session(*, csrf: bool = True) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    response = client.get("/v1/session")
    assert response.status_code == 200, response.text
    headers = {"Content-Type": "application/json"}
    if csrf:
        headers["X-CSRF-Token"] = cast(str, response.json()["csrf_token"])
    return client, headers


def _assert_small_422(response: Any, *, max_errors: int = 20) -> list[dict[str, Any]]:
    assert response.status_code == 422, response.text[:500]
    assert len(response.content) < SMALL_RESPONSE_BYTES, f"{len(response.content):,} bytes"
    field_errors = cast(list[dict[str, Any]], response.json()["detail"]["field_errors"])
    assert 1 <= len(field_errors) <= max_errors
    return field_errors


def test_a_million_byte_model_slots_list_gets_a_small_422() -> None:
    """Red when: ``model_slots`` is unbounded and every error is returned
    (A1: 500,000 ``field_errors``, 47.4 MB)."""
    client, headers = _client_with_session()
    body = _compact({"query_text": "x", "model_slots": [1] * 500_000})
    assert 1_000_000 < len(body) < 1_048_576
    response = client.post("/v1/query-runs/estimate", content=body, headers=headers)
    _assert_small_422(response)


def test_three_hundred_thousand_empty_acknowledgements_get_a_small_422() -> None:
    """Red when: ``safety_acknowledgements`` is unbounded and every error is
    returned (A1: 600,000 ``field_errors``, 58.3 MB, 651 MB peak)."""
    client, headers = _client_with_session(csrf=False)
    body = _compact(
        {"query_text": QUERY, "model_slots": DEFAULT_IDS, "safety_acknowledgements": [{}] * 300_000}
    )
    assert 900_000 < len(body) < 1_048_576
    response = client.post("/v1/query-runs", content=body, headers=headers)
    _assert_small_422(response)


def test_an_80_000_key_context_gets_one_error() -> None:
    """Red when: context values are checked before its keys (80,000
    ``string_type`` errors, 7.3 MB, A1)."""
    client, headers = _client_with_session()
    context = dict.fromkeys(_short_keys(80_000), 0)
    body = _compact({"query_text": QUERY, "model_slots": DEFAULT_IDS, "context": context})
    assert 500_000 < len(body) < 1_048_576
    response = client.post("/v1/query-runs/estimate", content=body, headers=headers)
    field_errors = _assert_small_422(response)
    assert len(field_errors) == 1


def test_111_000_unknown_top_level_keys_get_one_error() -> None:
    """Red when: unknown fields are ignored (today: 200), or refused one error
    per key (plain ``extra="forbid"``: 111,000 errors, 9.5 MB, A2)."""
    client, headers = _client_with_session()
    payload: dict[str, Any] = {"query_text": QUERY, "model_slots": DEFAULT_IDS}
    payload.update(dict.fromkeys(_short_keys(111_000), 0))
    body = _compact(payload)
    assert 800_000 < len(body) < 1_048_576
    response = client.post("/v1/query-runs/estimate", content=body, headers=headers)
    field_errors = _assert_small_422(response)
    assert len(field_errors) == 1


@pytest.mark.parametrize("path", ["/v1/account/delete", "/v1/invite"])
def test_85_000_unknown_keys_to_the_already_strict_routes_get_one_error(path: str) -> None:
    """Red when: ``AccountDeleteRequest`` / ``InviteAcceptRequest`` keep
    building one ``extra_forbidden`` error per unknown key (Codex plan review
    2: 85,000 keys, 85,000 errors). A cap of 20 alone still leaves this red:
    the answer must be ONE error."""
    client, headers = _client_with_session()
    field = "confirm_email" if path == "/v1/account/delete" else "token"
    payload: dict[str, Any] = {field: "value"}
    payload.update(dict.fromkeys(_short_keys(85_000), 0))
    body = _compact(payload)
    assert 600_000 < len(body) < 1_048_576
    response = client.post(path, content=body, headers=headers)
    field_errors = _assert_small_422(response)
    assert len(field_errors) == 1


def test_more_than_twenty_errors_are_cut_to_twenty() -> None:
    """Red when: the 422 returns every error. 16 wrong ``model_slots`` items,
    16 wrong ``slot_search`` items and a missing ``query_text`` are 33 errors
    inside every W85 bound, so only the cap of 20 can cut them."""
    client, headers = _client_with_session()
    body = _compact({"model_slots": [1] * 16, "slot_search": ["not-a-bool"] * 16})
    response = client.post("/v1/query-runs/estimate", content=body, headers=headers)
    field_errors = _assert_small_422(response)
    assert len(field_errors) == 20


def test_a_two_error_body_still_returns_both_errors() -> None:
    """Red when: the error cap (or the unknown-key check) drops a real error
    from a small body. The positive partner of every ``<= 20`` above."""
    client, headers = _client_with_session()
    response = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": "", "model_slots": []},
        headers=headers,
    )
    field_errors = _assert_small_422(response)
    assert sorted(e["field"] for e in field_errors) == ["model_slots", "query_text"]


def test_a_context_with_one_900_kb_unknown_key_is_refused_without_echoing_it() -> None:
    """Red when: the context error message interpolates the unknown keys sent
    (today it does: a 1 MB key came back as a 2 MB response, Codex plan
    review 5), or the refusal is more than one error."""
    client, headers = _client_with_session()
    key = "K" * 900_000
    body = _compact({"query_text": QUERY, "model_slots": DEFAULT_IDS, "context": {key: "v"}})
    assert 900_000 < len(body) < 1_048_576
    response = client.post("/v1/query-runs/estimate", content=body, headers=headers)
    field_errors = _assert_small_422(response)
    assert len(field_errors) == 1
    assert "KKKKKKKKKK" not in response.text


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/v1/query-runs/estimate",
            {"query_text": QUERY, "model_slots": DEFAULT_IDS, "unexpected_field": 1},
        ),
        ("/v1/query-runs/warnings", {"query_text": QUERY, "unexpected_field": 1}),
    ],
    ids=["estimate", "warnings"],
)
def test_an_unknown_top_level_field_is_refused(path: str, payload: dict[str, Any]) -> None:
    """Red when: ``/estimate`` or ``/warnings`` silently ignores an unknown
    field (today: 200)."""
    client, headers = _client_with_session()
    response = client.post(path, json=payload, headers=headers)
    field_errors = _assert_small_422(response)
    assert len(field_errors) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"unexpected_field": 1},
        {"safety_acknowledgements": [{**ACKS[0], "unexpected_field": 1}]},
        {
            "cost_confirmation": {
                "estimated_cost_usd": "0.0123",
                "confirmation_token": "token",
                "unexpected_field": 1,
            }
        },
    ],
    ids=["top-level", "in-acknowledgement", "in-cost-confirmation"],
)
def test_an_unknown_field_on_create_is_refused_before_the_handler(extra: dict[str, Any]) -> None:
    """Red when: create ignores an unknown field at the top level, inside an
    acknowledgement or inside ``cost_confirmation``. Without W85 the request
    reaches the handler and its CSRF check answers 403 (no token is sent), so
    no run is ever started by this test."""
    client, headers = _client_with_session(csrf=False)
    payload = {"query_text": QUERY, "model_slots": DEFAULT_IDS, **extra}
    response = client.post("/v1/query-runs", json=payload, headers=headers)
    field_errors = _assert_small_422(response)
    assert len(field_errors) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"query_text": QUERY, "model_slots": DEFAULT_IDS},
        {"query_text": QUERY, "model_slots": DEFAULT_IDS[:1], "mode": "quick"},
        {"query_text": QUERY, "model_slots": DEFAULT_IDS, "context": CONTEXT},
        {"query_text": QUERY, "model_slots": DEFAULT_IDS, "context": None},
    ],
    ids=["panel", "quick", "follow-up", "context-null"],
)
def test_the_page_estimate_bodies_are_still_accepted(payload: dict[str, Any]) -> None:
    """Red when: a W85 bound or the unknown-key check refuses an estimate body
    the page sends (``runRequestBody`` in app.js), or ``context: null``."""
    client, headers = _client_with_session()
    response = client.post("/v1/query-runs/estimate", json=payload, headers=headers)
    assert response.status_code == 200, response.text[:500]


@pytest.mark.parametrize(
    "payload",
    [
        {"query_text": QUERY},
        {"query_text": QUERY, "context": CONTEXT},
        {"query_text": QUERY, "context": None},
    ],
    ids=["fresh", "follow-up", "context-null"],
)
def test_the_page_warnings_bodies_are_still_accepted(payload: dict[str, Any]) -> None:
    """Red when: a W85 change refuses a warnings body the page sends
    (``warningsRequestBody`` in app.js), or ``context: null``."""
    client, headers = _client_with_session()
    response = client.post("/v1/query-runs/warnings", json=payload, headers=headers)
    assert response.status_code == 200, response.text[:500]


@pytest.mark.parametrize("count", [5, 16])
def test_five_to_sixteen_slots_still_get_the_typed_slot_envelope(count: int) -> None:
    """Red when: the ``model_slots`` bound is set below 16, turning a wrong
    count into the generic envelope (ADR-0120 decision 6, A9)."""
    client, headers = _client_with_session()
    ids = (DEFAULT_IDS * 4)[:count]
    response = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": QUERY, "model_slots": ids},
        headers=headers,
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"]["code"] == "INVALID_MODEL_SLOT"


def test_seventeen_slots_are_refused_at_the_edge() -> None:
    """Red when: ``model_slots`` has no bound of 16, so 17 reach the slot check
    (today: the typed ``INVALID_MODEL_SLOT``)."""
    client, headers = _client_with_session()
    ids = (DEFAULT_IDS * 5)[:17]
    assert len(ids) == 17
    response = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": QUERY, "model_slots": ids},
        headers=headers,
    )
    assert response.status_code == 422, response.text[:500]
    assert response.json()["detail"]["code"] != "INVALID_MODEL_SLOT"
    field_errors = _assert_small_422(response)
    assert [(e["field"], e["type"]) for e in field_errors] == [("model_slots", "too_long")]
