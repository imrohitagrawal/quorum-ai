"""RB-5 — hermetic fault-injection lane.

Injects upstream provider faults at the **``providers.urlopen`` seam** and drives
them through the *full* ``produce_initial_answer`` path, then asserts the product
degrades **honestly**: a faulted slot becomes a clearly-labelled local simulation,
is NOT laundered into the served ``live_count``, and — where the fault has a
distinguishable observable — surfaces it in the logs.

Why ``urlopen`` and not a higher seam (corrected twice during planning): at
``_live_openrouter_response`` a 500, a timeout, a JSON-decode failure and an empty
body are all the same value (``None``), so the lane could not tell the faults
apart. ``urlopen`` is the lowest seam at which the four faults are still distinct
Python events. See ``docs/analysis/R2-remaining-stages-build-plan.md`` §317.

Hermetic and $0: ``urlopen`` is monkeypatched to *raise* (or return a crafted
body) — no socket is ever opened. Stage B's egress guard is asserted active here
as a backstop precondition (``test_egress_guard_is_the_precondition``), so even a
mis-wired fault cannot dial out.

Distinguishability, stated honestly (the plan's rule: "if a fault has no
distinguishable observable, say so instead of asserting a difference that does not
exist"): only the ``HTTPError`` family emits the structured
``upstream_provider_http_error`` WARNING carrying its ``status_code``. A timeout, a
JSON-decode failure and an empty body all collapse to a silent ``None`` at the
``urlopen`` seam and are therefore NOT distinguishable from one another at the
observable level — the fault table encodes exactly that (``emits_http_warning`` is
True only for the HTTP-error legs), rather than pretending a difference exists.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from tests.conftest import OutboundSocketBlocked

from product_app import config
from product_app.costs import cost_estimation_service
from product_app.model_slots import ModelSlot
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    InitialAnswerStatus,
    ProviderPath,
    provider_stub_service,
)
from product_app.query_runs import (
    InMemoryQueryRunRepository,
    _result_response,
)

_FAKE_KEY = "sk-or-v1-fault-injection-not-a-real-key"


class _FakeResponse:
    """Minimal ``urlopen`` return stand-in (context manager + ``read()``)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _raise_http_500(request: Any, timeout: float = 0) -> _FakeResponse:
    raise HTTPError(url=request.full_url, code=500, msg="Server Error", hdrs=Message(), fp=None)


def _raise_timeout(request: Any, timeout: float = 0) -> _FakeResponse:
    raise TimeoutError("upstream timed out")


def _return_malformed_json(request: Any, timeout: float = 0) -> _FakeResponse:
    # A 200 whose body is not JSON — json.loads raises JSONDecodeError inside
    # _live_openrouter_response and the call returns None silently.
    return _FakeResponse(b"<html>502 upstream gibberish</html>")


def _return_empty_content(request: Any, timeout: float = 0) -> _FakeResponse:
    # A well-formed JSON envelope carrying no assistant text. ``not content``
    # → the call returns None silently (no warning).
    return _FakeResponse(
        json.dumps({"choices": [{"message": {"content": "", "annotations": []}}]}).encode()
    )


#: The fault table. Each row is one upstream failure mode injected at ``urlopen``.
#: ``emits_http_warning`` records the ONLY observable that distinguishes faults at
#: this seam: the ``upstream_provider_http_error`` WARNING fires for the HTTP-error
#: family and for nothing else. ``status_code`` is asserted only when it fires.
_FAULTS: list[tuple[str, Callable[..., Any], bool, int | None]] = [
    ("http_500", _raise_http_500, True, 500),
    ("timeout", _raise_timeout, False, None),
    ("malformed_json", _return_malformed_json, False, None),
    ("empty_body", _return_empty_content, False, None),
]


def _enable_live(monkeypatch: pytest.MonkeyPatch, fake_urlopen: Callable[..., Any]) -> None:
    """Turn live execution ON for the duration of a test and route ``urlopen``
    to the injected fault. The egress guard keeps ``settings`` OFF by default
    (asserted separately); this override is local to the test."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)


def test_egress_guard_is_the_precondition() -> None:
    """Safety precondition (RB-5 depends on Stage B's guard). Two layers:

    1. ``settings.openrouter_live_execution_enabled`` is forced ``False`` for the
       whole suite, so nothing reaches ``urlopen`` unless a test deliberately
       overrides it (as this lane does, with ``urlopen`` already monkeypatched).
    2. A non-loopback ``socket.connect`` raises ``OutboundSocketBlocked`` — so
       even a mis-wired fault that slipped past the ``urlopen`` patch cannot dial
       out to a real provider and incur a paid call.

    Bite proof: remove either guard layer in ``conftest`` → the matching
    assertion reds.
    """
    assert config.settings.openrouter_live_execution_enabled is False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # TEST-NET-3 (RFC 5737) — never routable even absent the guard.
        with pytest.raises(OutboundSocketBlocked):
            sock.connect(("203.0.113.7", 443))
    finally:
        sock.close()


@pytest.mark.parametrize(
    ("name", "fake_urlopen", "emits_http_warning", "status_code"),
    _FAULTS,
    ids=[row[0] for row in _FAULTS],
)
def test_upstream_fault_degrades_slot_honestly(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    name: str,
    fake_urlopen: Callable[..., Any],
    emits_http_warning: bool,
    status_code: int | None,
) -> None:
    """Every injected upstream fault degrades the slot to a clearly-labelled
    local simulation — never a silent live-looking answer.

    Positive (the surface rendered): the slot returns a COMPLETED
    LOCAL_SIMULATION answer whose notice states plainly that it is *not* a
    real-model answer.

    Negative (paired): the slot is NOT an OPENROUTER_SEARCH live answer, so it
    cannot inflate ``live_count``.

    Distinguishing observable: the HTTP-error leg — and only it — logs
    ``upstream_provider_http_error`` with its ``status_code``.

    Bite proof: force ``produce_initial_answer`` to return the live path on a
    None response (e.g. drop the ``if live_response is not None`` guard) → the
    faulted slot reads OPENROUTER_SEARCH → red on the negative assertion.
    """
    _enable_live(monkeypatch, fake_urlopen)
    model_slot = ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True)

    with caplog.at_level("WARNING", logger="product_app.providers"):
        answer = provider_stub_service.produce_initial_answer(
            account_id=uuid4(),
            query_run_id=uuid4(),
            query_text="compare vendor uptime guarantees",
            model_slot=model_slot,
            credential_source=ProviderCredentialSource.APP_OWNED,
            openrouter_key=_FAKE_KEY,
        )

    # Positive: the degraded surface actually rendered, and it is honest.
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.provider_path is ProviderPath.LOCAL_SIMULATION
    assert answer.answer_text.strip()
    assert "not a real-model answer" in (answer.provider_notice or "").lower()
    # (The LOCAL_SIMULATION assertion above IS the paired negative: a fault must
    # never masquerade as a live OPENROUTER_SEARCH answer, and that path is
    # mutually exclusive with LOCAL_SIMULATION.)

    # Distinguishing observable — asserted in BOTH directions.
    http_records = [r for r in caplog.records if r.getMessage() == "upstream_provider_http_error"]
    if emits_http_warning:
        assert http_records, f"{name}: expected an upstream_provider_http_error WARNING"
        assert getattr(http_records[0], "status_code", None) == status_code
    else:
        assert not http_records, (
            f"{name}: this fault has no distinguishable HTTP observable at the "
            "urlopen seam — it must NOT emit upstream_provider_http_error"
        )


def test_one_provider_failure_slot_is_excluded_from_served_live_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end honesty (ties the fault lane to the D3 served-number fix): in a
    4-slot run where exactly one slot suffers a hard *provider failure*, the
    served ``live_count`` reads 3 — the failed slot is NOT counted as live.

    A hard provider failure produces a slot with ``status=FAILED`` **and**
    ``provider_path=OPENROUTER_SEARCH`` (``providers._failed_answer``) — the exact
    shape D3 fixes. (A *transient* urlopen fault degrades to a COMPLETED
    LOCAL_SIMULATION slot instead — covered by
    ``test_upstream_fault_degrades_slot_honestly`` above — so it is the hard
    failure, reached here via the LOCAL-independent ``provider-failure`` model
    marker, that actually exercises the ``live_count`` filter.)

    This is the served-number contract RB-5 protects: a provider failure must not
    inflate the "N of 4" banner.

    Bite proof: revert the D3 ``status is COMPLETED`` clause in
    ``_result_response``'s ``live_count`` → the failed OPENROUTER_SEARCH slot is
    counted → ``live_count`` reads 4 → red (verified by mutation).
    """

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        # The three non-failing slots return a real live answer. The failing
        # slot never reaches urlopen — _should_force_provider_failure short-
        # circuits it to _failed_answer before live execution is attempted.
        return _FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "A grounded live answer [1].",
                                "annotations": [{"title": "Src", "url": "https://live.example/a"}],
                            }
                        }
                    ]
                }
            ).encode()
        )

    _enable_live(monkeypatch, fake_urlopen)
    account_id = uuid4()
    query_text = "compare vendor uptime guarantees"
    # Slot 4 carries the ``provider-failure`` marker → a hard provider failure
    # (FAILED, provider_path=OPENROUTER_SEARCH). The marker path is not
    # LOCAL-gated, so this holds in any runtime.
    model_slots = [
        ModelSlot(slot_number=1, model_id="prov/model-1", search=True),
        ModelSlot(slot_number=2, model_id="prov/model-2", search=True),
        ModelSlot(slot_number=3, model_id="prov/model-3", search=True),
        ModelSlot(slot_number=4, model_id="prov/provider-failure-4", search=True),
    ]

    repository = InMemoryQueryRunRepository()
    estimate = cost_estimation_service.estimate(query_text=query_text, model_slots=model_slots)
    query_run = repository.create(
        account_id=account_id,
        query_text=query_text,
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run.query_run_id,
        query_text=query_text,
        model_slots=model_slots,
        credential_source=ProviderCredentialSource.APP_OWNED,
        openrouter_key=_FAKE_KEY,
    )
    repository.record_initial_answers(query_run.query_run_id, answers)

    response = _result_response(repository.get(query_run.query_run_id))

    # Three genuinely-live slots; the failed slot is excluded from live_count.
    assert response.live_count == 3
    # Positive control: exactly three slots took the OpenRouter path COMPLETED.
    live_slots = [
        a
        for a in response.result.model_answers
        if a.provider_path is ProviderPath.OPENROUTER_SEARCH
        and a.status is InitialAnswerStatus.COMPLETED
    ]
    assert len(live_slots) == 3
    # Paired negative: the failed slot IS on the OpenRouter path but FAILED, so
    # it is exactly the shape that would inflate live_count without the D3 fix.
    failed_slots = [
        a
        for a in response.result.model_answers
        if a.provider_path is ProviderPath.OPENROUTER_SEARCH
        and a.status is InitialAnswerStatus.FAILED
    ]
    assert len(failed_slots) == 1
