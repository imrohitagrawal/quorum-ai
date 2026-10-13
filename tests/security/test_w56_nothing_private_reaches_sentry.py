"""W56: nothing private reaches Sentry.

Four private values must never leave the process inside a Sentry payload: the
visitor's address, the anti-forgery token, the account header, and a key
inside an error message. The failure modes and the SDK evidence behind every
test here are in ``docs/analysis/2026-10-13-w56-sentry-privacy-failure-modes.md``
(cited below as "failure mode N"); the two probes these tests grew from are S1
and S2 in ``docs/analysis/2026-10-13-security-review.md``.

How the tests see what would be sent: Sentry is initialised with PRODUCTION's
own options (``main._sentry_options()``) and a transport that keeps every
envelope item instead of sending it, with every request sampled. Each check
then sweeps the WHOLE serialised payload, not one field, because the measured
leaks arrived in places a field-by-field check would not look (failure mode 2:
the alert carried the address twice, once in ``extra`` and once in a header).

Every "absent" check has a partner proving the payload it swept is real
(failure mode 15): a scrubber that deletes everything would pass every
negative check here on its own.

Test trap (failure mode 9): ``TestClient``'s own requests become breadcrumbs in
later events, so no secret is ever put into a URL here. Secrets travel in
headers and exception text only.

The key below is a plain ``sk-or-v1-`` key on purpose. The key pattern in
``logging_config`` has known gaps (a key glued to a word, a percent-encoded
key); those belong to W76, not W56 (failure mode 20).
"""

from __future__ import annotations

import ast
import inspect
import json
import threading
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from product_app import costs, main
from product_app.config import settings
from product_app.costs import CostEstimationService, CostThresholdAction
from product_app.feedback_store import configure_for_tests

FAKE_DSN = "https://abc@o1.ingest.sentry.io/1"

VISITOR_IP = "203.0.113.88"
CSRF_TOKEN = "w56csrftokenvalue7f3a"
CSRF_ALT_TOKEN = "w56csrfaltvalue91c2"
ACCOUNT_HEADER = "5e5e5e5e-0000-4000-8000-0000000c0a56"
UNLISTED_VALUE = "w56unlistedheadervaluec4e1"
USER_AGENT = "w56-probe-agent"
KEY = "sk-or-v1-" + "0123456789abcdef" * 4

#: Every request in this file sends these. The first five values are private;
#: User-Agent is the partner that must still arrive.
PROBE_HEADERS = {
    "Fly-Client-IP": VISITOR_IP,
    "X-CSRF-Token": CSRF_TOKEN,
    "X-CSRF": CSRF_ALT_TOKEN,
    "X-Account-Id": ACCOUNT_HEADER,
    "Forwarded": f"for={VISITOR_IP}",
    "X-Unlisted-Probe": UNLISTED_VALUE,
    "User-Agent": USER_AGENT,
}
PRIVATE_HEADER_VALUES = (VISITOR_IP, CSRF_TOKEN, CSRF_ALT_TOKEN, ACCOUNT_HEADER, UNLISTED_VALUE)

SPEND_KEY = UUID("00000000-0000-0000-0000-0000000005e5")
CEILING_RUN_ID = UUID("00000000-0000-0000-0000-0000000005e6")
CEILING_EVENT_TYPE = "cost_guardrail_degraded_to_simulation"


class _CaptureTransport(Transport):
    """Keep every envelope item the SDK would have sent."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            self.items.append(
                {
                    "type": item.type,
                    "json": item.payload.json,
                    "raw": item.payload.get_bytes().decode("utf-8", "replace"),
                }
            )


class _Captured:
    def __init__(self, transport: _CaptureTransport) -> None:
        self._transport = transport

    def _payloads(self, item_type: str) -> list[dict[str, Any]]:
        sentry_sdk.flush(timeout=5)
        return [
            cast(dict[str, Any], item["json"])
            for item in self._transport.items
            if item["type"] == item_type and isinstance(item["json"], dict)
        ]

    def events(self) -> list[dict[str, Any]]:
        """Error and message events (``before_send`` path)."""
        return self._payloads("event")

    def transactions(self) -> list[dict[str, Any]]:
        """Transactions (``before_send_transaction`` path)."""
        return self._payloads("transaction")

    def blob(self) -> str:
        """Everything captured, every item type, serialised two ways."""
        sentry_sdk.flush(timeout=5)
        return json.dumps(self._transport.items, default=repr)

    def item_count(self) -> int:
        sentry_sdk.flush(timeout=5)
        return len(self._transport.items)


@pytest.fixture
def sentry_capture() -> Iterator[_Captured]:
    """Initialise Sentry with production's options and a capture transport.

    Teardown closes the client and puts the no-op client back on the global
    scope, so no later test inherits a live client (failure mode 22).
    """
    options = {**main._sentry_options(), "traces_sample_rate": 1.0}
    transport = _CaptureTransport()
    with sentry_sdk.isolation_scope():
        sentry_sdk.get_isolation_scope().clear_breadcrumbs()
        sentry_sdk.init(dsn=FAKE_DSN, transport=transport, **options)
        try:
            yield _Captured(transport)
        finally:
            client = sentry_sdk.get_client()
            client.flush(timeout=5)
            client.close()
            sentry_sdk.get_global_scope().set_client(None)


@pytest.fixture
def temporary_routes() -> Iterator[FastAPI]:
    """Yield ``main.app``; remove every ``/__w56_`` route on teardown."""
    app = main.app
    try:
        yield app
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if not str(getattr(r, "path", "")).startswith("/__w56_")
        ]


def _assert_none_of(values: tuple[str, ...], blob: str) -> None:
    leaked = [v for v in values if v in blob]
    assert leaked == [], f"private values reached the Sentry payload: {leaked}"


def _headers_of(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    assert isinstance(request, dict), f"payload has no request block: {sorted(payload)}"
    headers = request.get("headers")
    assert isinstance(headers, dict), f"request block has no headers dict: {request!r}"
    return {str(k).lower(): v for k, v in headers.items()}


def _exception_values(event: dict[str, Any]) -> list[dict[str, Any]]:
    exception = event.get("exception")
    assert isinstance(exception, dict), f"event has no exception block: {sorted(event)}"
    return [v for v in exception.get("values", []) if isinstance(v, dict)]


def _exception_values_or_empty(event: dict[str, Any]) -> list[dict[str, Any]]:
    exception = event.get("exception")
    if not isinstance(exception, dict):
        return []
    return [v for v in exception.get("values", []) if isinstance(v, dict)]


def _events_with_exception_text(captured: _Captured, text: str) -> list[dict[str, Any]]:
    return [
        e
        for e in captured.events()
        if any(text in str(v.get("value", "")) for v in _exception_values_or_empty(e))
    ]


# ---------------------------------------------------------------------------
# S1: request headers
# ---------------------------------------------------------------------------


def test_a_transaction_carries_no_private_header_value(sentry_capture: _Captured) -> None:
    """S1 / failure modes 1, 5, 6, 14: the transaction path.

    Red when: the shared scrubber stops replacing the value of a header that
    is not on the allow-list (or the transaction hook stops calling it), so
    ``fly-client-ip``, ``x-csrf-token``, ``x-csrf``, ``x-account-id``,
    ``forwarded`` or an unknown header reaches ``request.headers``.
    """
    with TestClient(main.app) as client:
        response = client.get("/health", headers=PROBE_HEADERS)
    assert response.status_code == 200

    transactions = [t for t in sentry_capture.transactions() if "/health" in str(t)]
    # Cardinality, not "any": one sampled request is one transaction.
    assert len(transactions) == 1, [t.get("transaction") for t in transactions]
    _assert_none_of(PRIVATE_HEADER_VALUES, sentry_capture.blob())
    # Partner: the header block is real and the allow-listed value survives.
    assert _headers_of(transactions[0]).get("user-agent") == USER_AGENT


def test_an_error_raised_in_a_request_carries_no_private_header_value(
    sentry_capture: _Captured, temporary_routes: FastAPI
) -> None:
    """S1 (its UNVERIFIED line) / failure mode 2: the error path, inside a request.

    Red when: ``_redact_sentry_event`` (the ``before_send`` hook) stops
    scrubbing request headers, so an error raised while a request is being
    handled ships the visitor's address and token beside the traceback.
    """

    async def _raise() -> None:
        raise RuntimeError("w56 handler failure")

    temporary_routes.add_api_route("/__w56_raise__", _raise, methods=["GET"])
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/__w56_raise__", headers=PROBE_HEADERS)
    assert response.status_code == 500

    errors = _events_with_exception_text(sentry_capture, "w56 handler failure")
    assert len(errors) == 1, f"expected exactly one error event, got {len(errors)}"
    _assert_none_of(PRIVATE_HEADER_VALUES, sentry_capture.blob())
    # Partners: the event is attached to the request, and the safe header survives.
    assert _headers_of(errors[0]).get("user-agent") == USER_AGENT
    assert _exception_values(errors[0])[-1]["type"] == "RuntimeError"


def test_an_error_in_a_thread_started_by_a_request_carries_no_private_header_value(
    sentry_capture: _Captured, temporary_routes: FastAPI
) -> None:
    """Failure mode 4: worker threads inherit the request's scope, headers included.

    Production's run worker is such a thread (``query_runs.py``), so every
    provider or judge error sent after the response is affected.

    Red when: the header scrub is removed from the hook, or limited to events
    captured on the request's own thread.
    """

    def _start_worker() -> dict[str, bool]:
        def _work() -> None:
            try:
                raise RuntimeError("w56 worker failure")
            except RuntimeError as exc:
                sentry_sdk.capture_exception(exc)

        worker = threading.Thread(target=_work)
        worker.start()
        worker.join(timeout=10)
        return {"ok": True}

    temporary_routes.add_api_route("/__w56_worker__", _start_worker, methods=["GET"])
    with TestClient(main.app) as client:
        response = client.get("/__w56_worker__", headers=PROBE_HEADERS)
    assert response.status_code == 200

    errors = _events_with_exception_text(sentry_capture, "w56 worker failure")
    assert len(errors) == 1, f"expected exactly one worker error event, got {len(errors)}"
    _assert_none_of(PRIVATE_HEADER_VALUES, sentry_capture.blob())
    # Partner: the thread really inherited the request (else the sweep above
    # passed over an event with no headers at all).
    assert _headers_of(errors[0]).get("user-agent") == USER_AGENT


def test_mixed_case_header_names_sent_by_a_client_are_still_redacted(
    sentry_capture: _Captured,
) -> None:
    """Failure mode 5: header case, through the real request path.

    Red when: the header allow-list stops matching names case-insensitively in
    a way that lets an upper-case private header through, or the scrub is
    removed.
    """
    shouted = {
        "FLY-CLIENT-IP": VISITOR_IP,
        "x-csrf-TOKEN": CSRF_TOKEN,
        "X-Unlisted-PROBE": UNLISTED_VALUE,
        "USER-AGENT": USER_AGENT,
    }
    with TestClient(main.app) as client:
        assert client.get("/health", headers=shouted).status_code == 200

    transactions = [t for t in sentry_capture.transactions() if "/health" in str(t)]
    assert len(transactions) == 1
    _assert_none_of((VISITOR_IP, CSRF_TOKEN, UNLISTED_VALUE), sentry_capture.blob())
    assert _headers_of(transactions[0]).get("user-agent") == USER_AGENT


@pytest.mark.parametrize(
    "hook", [main._redact_sentry_event, main._redact_sentry_transaction], ids=["event", "txn"]
)
def test_the_hooks_match_header_names_case_insensitively(hook: Any) -> None:
    """Failure mode 5: the matcher itself, with names the SDK did not lowercase.

    The real request path lowercases names before the hook sees them (the
    test above), so only a direct call can show the allow-list is matched
    case-insensitively in both directions.

    Red when: the allow-list or the redaction compares header names
    case-sensitively, so ``FLY-CLIENT-IP`` keeps its value or ``User-Agent``
    loses it; or either hook stops scrubbing headers.
    """
    event = {
        "request": {
            "headers": {
                "FLY-CLIENT-IP": VISITOR_IP,
                "X-Csrf-Token": CSRF_TOKEN,
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            }
        }
    }
    result = hook(event, {})
    assert result is not None
    headers = result["request"]["headers"]
    for name in ("FLY-CLIENT-IP", "X-Csrf-Token"):
        assert headers.get(name, "[REDACTED]") == "[REDACTED]", (name, headers.get(name))
    # Partners: allow-listed values survive whatever their case.
    assert headers["User-Agent"] == USER_AGENT
    assert headers["Content-Type"] == "application/json"


@pytest.mark.parametrize(
    "headers",
    [None, [["fly-client-ip", VISITOR_IP]], "not-a-dict", {"x-n": None}, {"x-n": 12}],
    ids=["none", "list", "string", "none-value", "int-value"],
)
def test_the_header_scrub_survives_odd_header_shapes(headers: object) -> None:
    """Failure mode 16: a scrubber that raises makes the SDK DROP the event.

    That is safe for privacy but silently loses the ceiling alert.

    Red when: the header scrub indexes or calls string methods on
    ``request.headers`` or a header value without a type guard.
    This was a partner at the red commit 18299a0 (the scrubber then never
    touched headers, so it passed while its neighbours failed). Now it
    guards the header scrub's type guards: every odd shape must come back
    without the hook raising.
    """
    for hook in (main._redact_sentry_event, main._redact_sentry_transaction):
        event = {"request": {"headers": headers}, "message": "w56 survives"}
        result = hook(cast(Any, event), {})
        assert result is not None
        assert result["message"] == "w56 survives"


# ---------------------------------------------------------------------------
# S2: a key inside an error message, and every other string in the event
# ---------------------------------------------------------------------------


def test_a_key_in_an_exception_message_does_not_reach_sentry(sentry_capture: _Captured) -> None:
    """S2 / failure mode 8.

    Red when: the scrubber stops passing ``exception.values[].value`` through
    ``logging_config._redact_secrets``.
    """
    try:
        raise RuntimeError(f"upstream rejected {KEY} for run 42")
    except RuntimeError as exc:
        sentry_sdk.capture_exception(exc)

    events = sentry_capture.events()
    assert len(events) == 1
    assert KEY not in sentry_capture.blob()
    # Partner: the type and the safe parts of the message still arrive.
    (value,) = _exception_values(events[0])
    assert value["type"] == "RuntimeError"
    assert "upstream rejected" in value["value"]
    assert "for run 42" in value["value"]


class _InnerError(Exception):
    pass


class _OuterError(Exception):
    pass


def test_a_key_in_a_chained_cause_does_not_reach_sentry(sentry_capture: _Captured) -> None:
    """Failure mode 8: the key sat in the CAUSE while the outer message was harmless.

    Red when: the scrubber cleans only the last (outermost) exception value.
    """
    try:
        try:
            raise _InnerError(f"provider said {KEY} is invalid")
        except _InnerError as inner:
            raise _OuterError("harmless outer message") from inner
    except _OuterError as outer:
        sentry_sdk.capture_exception(outer)

    events = sentry_capture.events()
    assert len(events) == 1
    assert KEY not in sentry_capture.blob()
    # Partners: both links of the chain arrive, with their safe text.
    values = {v["type"]: v["value"] for v in _exception_values(events[0])}
    assert set(values) == {"_InnerError", "_OuterError"}, values
    assert values["_OuterError"] == "harmless outer message"
    assert "provider said" in values["_InnerError"]
    assert "is invalid" in values["_InnerError"]


def _message_text(event: dict[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(event.get("message"), str):
        parts.append(event["message"])
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        parts.extend(str(logentry.get(k, "")) for k in ("message", "formatted"))
    return " ".join(parts)


def test_a_key_in_a_captured_message_does_not_reach_sentry(sentry_capture: _Captured) -> None:
    """Failure mode 8: ``capture_message`` text.

    Red when: the scrubber stops redacting the ``message`` string.
    """
    sentry_sdk.capture_message(f"budget check rejected {KEY} at step 3")

    events = sentry_capture.events()
    assert len(events) == 1
    assert KEY not in sentry_capture.blob()
    text = _message_text(events[0])
    assert "budget check rejected" in text
    assert "at step 3" in text


def test_a_key_in_extra_tags_contexts_or_breadcrumbs_does_not_reach_sentry(
    sentry_capture: _Captured,
) -> None:
    """Interface point 2b: every string anywhere in the event is key-redacted.

    Red when: the scrubber's walk skips ``extra``, ``tags``, ``contexts`` or
    ``breadcrumbs``.
    """
    with sentry_sdk.new_scope() as scope:
        scope.set_extra("w56_detail", f"extra carried {KEY} here")
        scope.set_tag("w56_tag", KEY)
        scope.set_context("w56_ctx", {"note": f"context carried {KEY} here"})
        scope.add_breadcrumb(message=f"crumb carried {KEY} here", category="w56")
        sentry_sdk.capture_message("w56 harmless message")

    events = sentry_capture.events()
    assert len(events) == 1
    assert KEY not in sentry_capture.blob()
    # Partners: each carrier arrived, with its safe text.
    event = events[0]
    assert "extra carried" in event["extra"]["w56_detail"]
    assert "w56_tag" in event["tags"]
    assert "context carried" in event["contexts"]["w56_ctx"]["note"]
    crumbs = [b for b in event["breadcrumbs"]["values"] if b.get("category") == "w56"]
    assert len(crumbs) == 1
    assert "crumb carried" in crumbs[0]["message"]


def test_a_key_in_a_span_description_does_not_reach_sentry(sentry_capture: _Captured) -> None:
    """Interface point 2b: spans travel in transactions, through the other hook.

    Red when: ``_redact_sentry_transaction`` does not key-redact span strings.
    """
    with (
        sentry_sdk.start_transaction(name="w56-transaction", op="w56"),
        sentry_sdk.start_span(op="w56.call", name=f"call carried {KEY} here"),
    ):
        pass

    transactions = [
        t for t in sentry_capture.transactions() if t.get("transaction") == "w56-transaction"
    ]
    assert len(transactions) == 1
    assert KEY not in sentry_capture.blob()
    spans = [s for s in transactions[0].get("spans", []) if s.get("op") == "w56.call"]
    assert len(spans) == 1
    assert "call carried" in spans[0]["description"]


# ---------------------------------------------------------------------------
# The ceiling alert: drop the address, keep the spend key (owner, 2026-10-13)
# ---------------------------------------------------------------------------


def test_the_ceiling_alert_inside_a_request_carries_the_spend_key_and_no_address(
    sentry_capture: _Captured, temporary_routes: FastAPI
) -> None:
    """Failure modes 2 and 3: the real alert, sent with a request attached.

    The real ``create_query_run`` is a sync route that books the charge before
    starting the worker, so the alert leaves with the request's headers.

    Red when: the alert sets a ``client_ip`` extra again, or the header scrub
    is removed (the address then arrives as ``request.headers.fly-client-ip``),
    or the alert stops carrying ``account_id``.
    """

    def _book_degraded_charge() -> dict[str, bool]:
        costs.cost_estimation_service.try_record_run_charge(
            account_id=SPEND_KEY,
            query_run_id=CEILING_RUN_ID,
            estimated_cost_usd=Decimal("0.03"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmed=False,
            global_ceiling_reached=True,
        )
        return {"ok": True}

    temporary_routes.add_api_route("/__w56_ceiling__", _book_degraded_charge, methods=["GET"])
    with configure_for_tests(), TestClient(main.app) as client:
        assert client.get("/__w56_ceiling__", headers=PROBE_HEADERS).status_code == 200

    alerts = [
        e
        for e in sentry_capture.events()
        if (e.get("tags") or {}).get("event_type") == CEILING_EVENT_TYPE
    ]
    assert len(alerts) == 1, f"expected exactly one ceiling alert, got {len(alerts)}"
    alert = alerts[0]
    assert "client_ip" not in alert.get("extra", {})
    _assert_none_of((VISITOR_IP,), sentry_capture.blob())
    # Partners: the operator still gets what the alert is for.
    assert alert["extra"]["account_id"] == str(SPEND_KEY)
    assert "global_daily_ceiling_usd" in alert["extra"]
    assert alert["level"] == "warning"
    assert _headers_of(alert).get("user-agent") == USER_AGENT


@pytest.mark.parametrize("method", ["record_guardrail_event", "try_record_run_charge"])
def test_the_alert_methods_no_longer_accept_an_address(method: str) -> None:
    """Interface point 3: ``client_ip`` is removed, not merely left unused.

    Red when: ``client_ip`` is a parameter of the method again, or (partner)
    ``account_id`` is no longer one.
    """
    parameters = inspect.signature(getattr(CostEstimationService, method)).parameters
    assert "client_ip" not in parameters
    assert "account_id" in parameters


# ---------------------------------------------------------------------------
# The options production passes to sentry_sdk.init
# ---------------------------------------------------------------------------


def test_sentry_options_pin_the_privacy_settings() -> None:
    """Failure modes 11, 12, 17: the settings every test above runs under.

    Red when: ``_sentry_options`` is missing (AttributeError), or
    ``send_default_pii`` / ``include_local_variables`` is turned on, or either
    hook is dropped, or the top-level ``enable_logs`` keyword is true, or
    ``_experiments`` holds a ``trace_lifecycle`` key (span streaming). This
    test does NOT see ``_experiments["enable_logs"]``, the second switch for
    log forwarding; ``test_w56_regressions.py``
    (``test_sentry_options_pin_log_forwarding_off_by_both_switches``) pins
    that one, and ``enable_metrics``.
    """
    options = main._sentry_options()
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["before_send"] is main._redact_sentry_event
    assert options["before_send_transaction"] is main._redact_sentry_transaction
    assert options["traces_sample_rate"] == 0.1
    assert options["sample_rate"] == 1.0
    assert options["environment"] == settings.runtime_environment.value
    assert "dsn" not in options
    assert "transport" not in options
    assert not options.get("enable_logs", False)
    assert "trace_lifecycle" not in (options.get("_experiments") or {})


def test_production_init_passes_only_the_dsn_and_sentry_options() -> None:
    """The options the tests use must be the options production uses.

    Without this, ``_sentry_options`` could be correct while the real
    ``sentry_sdk.init`` call in ``main.py`` passes something else.

    Red when: the ``sentry_sdk.init`` call in ``main.py`` passes any keyword
    other than ``dsn=SENTRY_DSN`` and ``**_sentry_options()``, or there is not
    exactly one such call.
    """
    tree = ast.parse(Path(inspect.getfile(main)).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "init"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sentry_sdk"
    ]
    assert len(calls) == 1, f"expected one sentry_sdk.init call, found {len(calls)}"
    (call,) = calls
    assert call.args == []
    shape = sorted((kw.arg or "**", ast.unparse(kw.value)) for kw in call.keywords)
    assert shape == [("**", "_sentry_options()"), ("dsn", "SENTRY_DSN")], shape
