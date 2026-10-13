"""W56 review rounds 1 and 2: the holes review found in "nothing private reaches Sentry".

Each test here pins one reproduced finding. From round 1 (the W56 pull request):

* incoming ``baggage`` reached Sentry in the ENVELOPE HEADER ``trace``, which
  no hook sees (``sentry_sdk/client.py`` pops ``dynamic_sampling_context``
  out of the event after ``before_send`` has run);
* Sentry metrics (``trace_metric`` items, on by default in sentry-sdk 2.63.0)
  skip both hooks;
* the ceiling-alert test never ran inside a request whose ``request.client.host``
  WAS the visitor's address, so the address could come back under another name;
* a depth limit small enough to strip stack traces passed every test;
* a non-dict ``headers`` value left as-is passed every test;
* no test sent a ``Cookie`` header.

Review round 2 added: the session-limit error's message was the visitor's
address (a 500 raised while refusing a session sent it as a chained exception's
``value``); log forwarding has a second switch, ``_experiments["enable_logs"]``,
that no test saw; and the depth guard had no test.

Unlike ``test_w56_nothing_private_reaches_sentry.py``, the capture transport
here keeps the WHOLE serialised envelope, headers included, because the first
finding lives in the envelope header, not in any item.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from product_app import auth, costs, main
from product_app.feedback_store import configure_for_tests
from product_app.model_slots import DEFAULT_MODEL_IDS
from product_app.safety import WARNING_VERSION, WarningType

FAKE_DSN = "https://abc@o1.ingest.sentry.io/1"
VISITOR_IP = "203.0.113.99"
USER_AGENT = "w56-regressions-agent"
KEY = "sk-or-v1-" + "fedcba9876543210" * 4
INCOMING_TRACE_ID = "771a43a4192642f0b136d5159a501700"
INCOMING_SPAN_ID = "a1b2c3d4e5f60718"
CEILING_EVENT_TYPE = "cost_guardrail_degraded_to_simulation"
#: Inside ``auth.TRUSTED_PROXY_NETWORKS`` (172.16.0.0/12), so
#: ``VisitorAddressMiddleware`` believes its ``Fly-Client-IP``.
TRUSTED_PEER = "172.16.0.9"


class _EnvelopeTransport(Transport):
    """Keep every envelope exactly as it would go on the wire."""

    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)


class _Envelopes:
    def __init__(self, transport: _EnvelopeTransport) -> None:
        self._transport = transport

    def _all(self) -> list[Envelope]:
        sentry_sdk.flush(timeout=5)
        return list(self._transport.envelopes)

    def wire(self) -> str:
        """Every envelope, headers and items, serialised as the SDK sends it."""
        return "\n".join(e.serialize().decode("utf-8", "replace") for e in self._all())

    def items(self, item_type: str) -> list[dict[str, Any]]:
        return [
            cast(dict[str, Any], item.payload.json)
            for envelope in self._all()
            for item in envelope.items
            if item.type == item_type and isinstance(item.payload.json, dict)
        ]

    def item_types(self) -> list[str]:
        return [str(item.type) for envelope in self._all() for item in envelope.items]

    def envelope_headers(self) -> list[dict[str, Any]]:
        return [dict(e.headers) for e in self._all()]


@pytest.fixture
def envelopes() -> Iterator[_Envelopes]:
    """Sentry with production's options, every request sampled, nothing sent."""
    options = {**main._sentry_options(), "traces_sample_rate": 1.0}
    transport = _EnvelopeTransport()
    with sentry_sdk.isolation_scope():
        sentry_sdk.get_isolation_scope().clear_breadcrumbs()
        sentry_sdk.init(dsn=FAKE_DSN, transport=transport, **options)
        try:
            yield _Envelopes(transport)
        finally:
            client = sentry_sdk.get_client()
            client.flush(timeout=5)
            client.close()
            sentry_sdk.get_global_scope().set_client(None)


@pytest.fixture
def temporary_routes() -> Iterator[FastAPI]:
    """Yield ``main.app``; remove every ``/__w56r_`` route on teardown."""
    app = main.app
    try:
        yield app
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if not str(getattr(r, "path", "")).startswith("/__w56r_")
        ]


# ---------------------------------------------------------------------------
# Finding 1: incoming baggage reached the envelope header ``trace``
# ---------------------------------------------------------------------------


def test_incoming_baggage_does_not_reach_the_envelope_header(
    envelopes: _Envelopes, temporary_routes: FastAPI
) -> None:
    """A visitor's ``baggage`` header must not ride out in the envelope header.

    The SDK copies incoming ``sentry-*`` baggage into
    ``contexts.trace.dynamic_sampling_context``; after both hooks have run,
    ``client.py`` pops that key and sends it as the envelope header ``trace``.

    Red when: the shared scrubber stops removing
    ``contexts.trace.dynamic_sampling_context``, so ``sentry-user_segment=<address>``
    arrives in the envelope header of the transaction and of the event.
    """

    def _report() -> dict[str, bool]:
        sentry_sdk.capture_message("w56r message inside a traced request")
        return {"ok": True}

    temporary_routes.add_api_route("/__w56r_traced__", _report, methods=["GET"])
    baggage = (
        f"sentry-trace_id={INCOMING_TRACE_ID},sentry-public_key=abc,"
        f"sentry-user_segment={VISITOR_IP},sentry-w56_key={KEY}"
    )
    headers = {
        "sentry-trace": f"{INCOMING_TRACE_ID}-{INCOMING_SPAN_ID}-1",
        "baggage": baggage,
        "User-Agent": USER_AGENT,
    }
    with TestClient(main.app) as client:
        assert client.get("/__w56r_traced__", headers=headers).status_code == 200

    wire = envelopes.wire()
    assert VISITOR_IP not in wire, [
        h.get("trace") for h in envelopes.envelope_headers() if "trace" in h
    ]
    assert KEY not in wire
    # Partners: the request really continued the visitor's trace (so the
    # baggage was consumed, not ignored), and both items still arrive.
    transactions = [
        t for t in envelopes.items("transaction") if "/__w56r_traced__" in str(t.get("transaction"))
    ]
    assert len(transactions) == 1
    assert transactions[0]["contexts"]["trace"]["trace_id"] == INCOMING_TRACE_ID
    messages = [
        e
        for e in envelopes.items("event")
        if e.get("message") == "w56r message inside a traced request"
    ]
    assert len(messages) == 1
    assert messages[0]["contexts"]["trace"]["trace_id"] == INCOMING_TRACE_ID


# ---------------------------------------------------------------------------
# Finding 2: metrics skip both hooks
# ---------------------------------------------------------------------------


def test_sentry_options_turn_metrics_off() -> None:
    """``trace_metric`` items pass through neither ``before_send`` hook.

    Red when: ``_sentry_options()`` stops passing ``enable_metrics=False``
    (sentry-sdk 2.63.0 defaults it to True).
    """
    assert main._sentry_options()["enable_metrics"] is False


def test_a_metric_produces_no_envelope_item(envelopes: _Envelopes) -> None:
    """A metric carrying a key in an attribute must not leave the process.

    Red when: metrics are on again AND nothing drops them (``enable_metrics``
    True or absent, and no ``before_send_metric`` hook returning ``None``), so
    a ``trace_metric`` item carrying the key is sent past both event hooks.
    Since round 3 the hook alone keeps this green; the test below pins it.
    """
    sentry_sdk.metrics.count("w56r.metric", 1, attributes={"detail": KEY})
    sentry_sdk.capture_message("w56r metric partner")

    types = envelopes.item_types()
    assert "trace_metric" not in types, types
    assert KEY not in envelopes.wire()
    # Partner: the transport is live and saw the message sent beside the metric.
    assert [e.get("message") for e in envelopes.items("event")] == ["w56r metric partner"]


def test_the_metric_hook_drops_metrics_even_when_metrics_are_on() -> None:
    """The metric hook holds even on a sentry-sdk that ignores ``enable_metrics``.

    Before W68 production installed sentry-sdk 2.72.0: the CI docker-build log
    of run 38382789055 prints ``+ sentry-sdk==2.72.0`` (the Dockerfile did not
    install from ``uv.lock`` then; since W68, ADR-0164, it does), and 2.72.0
    warns that "The enable_metrics option has no effect". So this test forces
    metrics ON, as 2.72.0 effectively does, and relies on the hook alone.

    Red when: ``_sentry_options()`` stops passing
    ``before_send_metric=_drop_sentry_metric``, or the hook returns the metric,
    so the forced-on metric below leaves as a ``trace_metric`` item.
    """
    options = main._sentry_options()
    assert options["before_send_metric"] is main._drop_sentry_metric
    sample = {"name": "w56r.metric", "type": "counter", "value": 1, "attributes": {}}
    assert main._drop_sentry_metric(sample, {}) is None

    transport = _EnvelopeTransport()
    with sentry_sdk.isolation_scope():
        sentry_sdk.init(dsn=FAKE_DSN, transport=transport, **{**options, "enable_metrics": True})
        try:
            sentry_sdk.metrics.count("w56r.forced", 1, attributes={"detail": KEY})
            sentry_sdk.capture_message("w56r forced metric partner")
            got = _Envelopes(transport)
            types = got.item_types()
            assert "trace_metric" not in types, types
            assert KEY not in got.wire()
            # Partner: the transport is live and saw the message sent beside it.
            assert [e.get("message") for e in got.items("event")] == ["w56r forced metric partner"]
        finally:
            client = sentry_sdk.get_client()
            client.flush(timeout=5)
            client.close()
            sentry_sdk.get_global_scope().set_client(None)


# ---------------------------------------------------------------------------
# Finding 3: the real ceiling alert, inside a request from the visitor's address
# ---------------------------------------------------------------------------


def _run_body(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    body: dict[str, object] = {
        "query_text": "Compare the managed Postgres options for a small team.",
        "model_slots": DEFAULT_MODEL_IDS,
    }
    preview = client.post("/v1/query-runs/estimate", json=body, headers=headers)
    assert preview.status_code == 200, preview.text
    estimate = preview.json()["cost_estimate"]
    assert estimate["global_ceiling_reached"] is True, estimate
    body["safety_acknowledgements"] = [
        {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION}
    ]
    if estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": estimate["estimated_cost_usd"],
            "confirmation_token": estimate["confirmation_token"],
        }
    return body


def test_the_ceiling_alert_from_a_real_run_carries_exactly_the_operator_fields(
    envelopes: _Envelopes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real ``POST /v1/query-runs``, with ``request.client.host`` = the visitor.

    The request comes from a peer inside ``TRUSTED_PROXY_NETWORKS`` with
    ``Fly-Client-IP`` set, so ``VisitorAddressMiddleware`` makes the visitor's
    address ``request.client.host`` — the value ``create_query_run`` used to
    pass down as ``client_ip``. The global ceiling is forced by setting it to
    $0. A store is configured, so the path sets all five of the alert's own
    extras; the sixth, ``sys.argv``, is added to every event by the SDK's
    default ``ArgvIntegration`` (``sentry_sdk/integrations/argv.py``) and holds
    the process command line, not request data.

    Red when: the alert carries any extra beyond ``account_id``,
    ``estimated_cost_usd``, ``query_run_id``, ``global_daily_spend_usd``,
    ``global_daily_ceiling_usd`` and the SDK's ``sys.argv`` (the address
    re-added under any name), or the address reaches any envelope by any route.
    """
    monkeypatch.setattr(costs, "GLOBAL_DAILY_CEILING_USD", Decimal("0"))
    headers = {
        "Fly-Client-IP": VISITOR_IP,
        "X-Account-Id": str(uuid4()),
        "User-Agent": USER_AGENT,
    }
    with configure_for_tests(), TestClient(main.app, client=(TRUSTED_PEER, 1234)) as client:
        created = client.post("/v1/query-runs", json=_run_body(client, headers), headers=headers)
        assert created.status_code == 202, created.text
        run_id = created.json()["query_run_id"]

        alerts = [
            e
            for e in envelopes.items("event")
            if (e.get("tags") or {}).get("event_type") == CEILING_EVENT_TYPE
        ]
        wire = envelopes.wire()

    assert len(alerts) == 1, f"expected exactly one ceiling alert, got {len(alerts)}"
    extra = alerts[0]["extra"]
    assert set(extra) == {
        "account_id",
        "estimated_cost_usd",
        "query_run_id",
        "global_daily_spend_usd",
        "global_daily_ceiling_usd",
        "sys.argv",
    }, sorted(extra)
    assert VISITOR_IP not in wire
    # Partners: the operator's field arrived, the alert went out with the
    # request attached, and the ceiling really was the forced one. (Not
    # ``query_run_id == run_id``: the pre-W56 rule that blanks any extra whose
    # name contains "query" blanks this one too, a separate finding.)
    assert extra["account_id"] == headers["X-Account-Id"], (extra["account_id"], run_id)
    assert extra["global_daily_ceiling_usd"] == "0"
    assert alerts[0]["request"]["headers"]["user-agent"] == USER_AGENT


# ---------------------------------------------------------------------------
# Finding 4: the depth limit must not strip stack traces
# ---------------------------------------------------------------------------


def _w56r_inner_failure() -> None:
    raise RuntimeError("w56r raised two calls deep")


def _w56r_outer_call() -> None:
    _w56r_inner_failure()


def test_an_error_two_calls_deep_keeps_its_stack_frames(
    envelopes: _Envelopes, temporary_routes: FastAPI
) -> None:
    """The key-redaction walk must not replace stack frames with a placeholder.

    Red when: ``_SENTRY_SCRUB_MAX_DEPTH`` is small enough (6 or less) that the
    walk replaces each frame of ``exception.values[].stacktrace.frames``.
    """

    async def _raise() -> None:
        _w56r_outer_call()

    temporary_routes.add_api_route("/__w56r_deep__", _raise, methods=["GET"])
    with TestClient(main.app, raise_server_exceptions=False) as client:
        assert client.get("/__w56r_deep__").status_code == 500

    errors = [
        e
        for e in envelopes.items("event")
        if any(
            v.get("value") == "w56r raised two calls deep"
            for v in (e.get("exception") or {}).get("values", [])
        )
    ]
    assert len(errors) == 1
    frames = errors[0]["exception"]["values"][-1]["stacktrace"]["frames"]
    functions = [f.get("function") for f in frames if isinstance(f, dict)]
    assert "_w56r_inner_failure" in functions, frames
    assert "_w56r_outer_call" in functions, frames


# ---------------------------------------------------------------------------
# Finding 5: a list-shaped headers value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hook", [main._redact_sentry_event, main._redact_sentry_transaction], ids=["event", "txn"]
)
def test_list_shaped_headers_lose_the_address(hook: Any) -> None:
    """A ``headers`` value that is a list of pairs is not known safe.

    Red when: the header scrub leaves a non-dict ``headers`` value as it is,
    so ``[["fly-client-ip", <address>]]`` reaches Sentry.
    """
    event = {
        "request": {"headers": [["fly-client-ip", VISITOR_IP]], "method": "GET"},
        "message": "w56r list headers",
    }
    result = hook(cast(Any, event), {})
    assert result is not None
    assert VISITOR_IP not in json.dumps(result)
    # Partner: the rest of the event survives.
    assert result["message"] == "w56r list headers"
    assert result["request"]["method"] == "GET"


# ---------------------------------------------------------------------------
# Finding 6: a Cookie header
# ---------------------------------------------------------------------------


def test_a_cookie_header_does_not_reach_sentry(
    envelopes: _Envelopes, temporary_routes: FastAPI
) -> None:
    """A cookie is a session credential; it can leave as a header or as ``request.cookies``.

    The request both captures a message (an event, which the SDK gives
    ``request.cookies`` when ``send_default_pii`` is on) and is a sampled
    transaction (which carries the ``cookie`` header only).

    Red when: ``send_default_pii`` is turned on (the event then carries
    ``request.cookies``). Adding ``cookie`` to the header allow-list alone
    stays green: with ``send_default_pii`` off the SDK's own header filter
    removes the ``cookie`` header before the hook runs (measured, W56 round 1).
    """
    cookie_value = "w56rcookievalue5d1e"

    def _report() -> dict[str, bool]:
        sentry_sdk.capture_message("w56r cookie request")
        return {"ok": True}

    temporary_routes.add_api_route("/__w56r_cookie__", _report, methods=["GET"])
    with TestClient(main.app) as client:
        response = client.get(
            "/__w56r_cookie__",
            headers={"Cookie": f"qa_session={cookie_value}", "User-Agent": USER_AGENT},
        )
    assert response.status_code == 200

    assert cookie_value not in envelopes.wire()
    # Partners: both payloads arrived with a real request block, and the
    # allow-listed header survived on each.
    transactions = [
        t for t in envelopes.items("transaction") if "/__w56r_cookie__" in str(t.get("transaction"))
    ]
    events = [e for e in envelopes.items("event") if e.get("message") == "w56r cookie request"]
    assert len(transactions) == 1
    assert len(events) == 1
    for payload in (transactions[0], events[0]):
        headers = {str(k).lower(): v for k, v in payload["request"]["headers"].items()}
        assert headers["user-agent"] == USER_AGENT


# ---------------------------------------------------------------------------
# Review round 2, finding 1: the session-limit error's message WAS the address
# ---------------------------------------------------------------------------


def test_the_session_limit_error_message_holds_no_address() -> None:
    """``str(exc)`` is what Sentry sends as a (chained) exception's ``value``.

    Red when: ``SessionMintCapExceeded`` passes ``client_ip`` to
    ``Exception.__init__`` again, so its message is the visitor's address.
    """
    exc = auth.SessionMintCapExceeded(VISITOR_IP, retry_after_seconds=60)
    assert VISITOR_IP not in str(exc)
    assert VISITOR_IP not in repr(exc)
    # Partner: the message says something, and the wait still travels.
    assert str(exc) == "new-session limit reached for this network"
    assert exc.retry_after_seconds == 60


def test_a_failure_while_refusing_a_session_does_not_send_the_address(
    envelopes: _Envelopes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 500 raised while ``/ui`` handles a refused mint chains the refusal.

    The visitor's address is ``request.client.host`` (a trusted peer sent
    ``Fly-Client-IP``), and the daily cap counts it. Once the cap is spent,
    rendering the 429 page is made to fail, as a missing template would: the
    500's exception chain then carries ``SessionMintCapExceeded``, whose
    message used to be the address.

    Red when: ``SessionMintCapExceeded``'s message is the address again, so
    the chained exception's ``value`` is the address. (The address is never
    written out near this function: Sentry sends a few source lines around
    each stack frame, and a literal here would turn the test red by itself.)
    """

    def _missing_template(*_args: object, **_kwargs: object) -> str:
        raise FileNotFoundError("session-capped.html")

    monkeypatch.delenv("SESSION_MINT_CAP_OVERRIDE", raising=False)
    headers = {"Fly-Client-IP": VISITOR_IP, "User-Agent": USER_AGENT}
    with configure_for_tests():
        client = TestClient(main.app, client=(TRUSTED_PEER, 1234), raise_server_exceptions=False)
        for _ in range(auth.SESSION_MINT_CAP_PER_IP):
            client.cookies.clear()
            assert client.get("/ui", headers=headers).status_code == 200
        monkeypatch.setattr(main, "_render_session_capped_html", _missing_template)
        client.cookies.clear()
        assert client.get("/ui", headers=headers).status_code == 500

    errors = [e for e in envelopes.items("event") if (e.get("exception") or {}).get("values")]
    wire = envelopes.wire()
    assert VISITOR_IP not in wire
    # Partners: exactly one error event arrived, and its chain really holds
    # the refusal and the failure raised while handling it.
    assert len(errors) == 1, [e.get("message") for e in envelopes.items("event")]
    types = [v.get("type") for v in errors[0]["exception"]["values"]]
    assert "SessionMintCapExceeded" in types, types
    assert "FileNotFoundError" in types, types


# ---------------------------------------------------------------------------
# Review round 2, finding 2: log forwarding has two switches
# ---------------------------------------------------------------------------


def test_sentry_options_pin_log_forwarding_off_by_both_switches() -> None:
    """sentry-sdk 2.63.0 forwards logs when ``enable_logs`` OR
    ``_experiments["enable_logs"]`` is true (``utils.has_logs_enabled``).

    Red when: ``_sentry_options()`` drops ``enable_logs=False``, or passes
    ``_experiments`` holding ``enable_logs``, ``enable_metrics`` or
    ``trace_lifecycle``.
    """
    opts = main._sentry_options()
    assert opts["enable_logs"] is False
    experiments = opts.get("_experiments", {})
    assert isinstance(experiments, dict)
    for name in ("enable_logs", "enable_metrics", "trace_lifecycle"):
        assert name not in experiments, (name, experiments)


def test_a_log_record_produces_no_log_item(envelopes: _Envelopes) -> None:
    """A ``log`` item passes through neither ``before_send`` hook.

    Red when: log forwarding is on by either switch (for example
    ``_experiments={"enable_logs": True}``), so the warning below leaves as a
    ``log`` item carrying the address.
    """
    logging.getLogger("w56r.logs").warning("w56r visitor %s", VISITOR_IP)
    sentry_sdk.capture_message("w56r log partner")

    types = envelopes.item_types()
    assert "log" not in types, types
    # Partner: the transport is live and saw the message sent beside the log.
    assert [e.get("message") for e in envelopes.items("event")] == ["w56r log partner"]


# ---------------------------------------------------------------------------
# Review round 2, finding 7: the depth guard
# ---------------------------------------------------------------------------


def test_a_self_referencing_extra_does_not_make_the_hook_raise() -> None:
    """A hook that raises makes the SDK drop the event (failure mode 16).

    Red when: the depth guard in ``_redact_secret_strings`` is deleted, so a
    cycle recurses until ``RecursionError``.
    """
    loop: dict[str, Any] = {"name": "w56r loop"}
    loop["self"] = loop
    event = {"message": "w56r cycle", "extra": {"loop": loop}}
    result = main._redact_sentry_event(cast(Any, event), {})
    assert result is not None
    # Partner: the rest of the event survives.
    assert result["message"] == "w56r cycle"
    assert cast(dict[str, Any], result["extra"])["loop"]["name"] == "w56r loop"


def test_a_key_nested_past_the_depth_limit_does_not_come_back() -> None:
    """Past the depth limit the container is replaced, not returned as it is.

    Red when: the guard returns the container unchanged past the limit, so the
    key 40 levels down is sent unredacted.
    """
    deep: dict[str, Any] = {"secret": KEY}
    for _ in range(40):
        deep = {"inner": deep}
    event = {"message": "w56r deep", "extra": {"deep": deep, "shallow": "w56r kept"}}
    result = main._redact_sentry_event(cast(Any, event), {})
    assert result is not None
    blob = json.dumps(result)
    assert KEY not in blob
    # Partners: the cut-off is a placeholder, and a shallow value survives.
    assert "[REDACTED]" in blob
    assert result["extra"]["shallow"] == "w56r kept"
    assert result["message"] == "w56r deep"
