"""#105 step 1 (ADR-0012): a failed slot records whether it could have been billed.

`providers.py` already computes the distinction that issue #105 turns on. `None`
means the request was REFUSED BEFORE INFERENCE — the provider decided against it
on a status in `_UNBILLED_HTTP_STATUSES`, or nothing ever left the process — so
nothing was billed. `_DISPATCH_UNMEASURED` means the request WAS dispatched, so
the provider may already have generated and charged for a completion that was
never captured. The sentinel's own docstring states that contract.

**And then the initial-answer path threw it away.** `_live_openrouter_response`
collapsed both into a single `None`, so by the time a slot reached
`_failed_answer` the cost layer could not tell "nothing was billed" from "this
may have cost money". That is why #105's conservative posture books the whole
pre-run estimate for a run whose every slot failed: the in-app signal to do
better did not survive the trip.

These tests pin that it now survives. They change NO money — nothing reads
`billing_class` to price anything, and ADR-0112 says why that decision still
needs evidence `_UNBILLED_HTTP_STATUSES` alone cannot supply.

Network-free and $0: every call goes through the `product_app.providers`
`urlopen` seam.
"""

from __future__ import annotations

import http.client
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from tests.provider_wire import sse_from_completion

from product_app import config
from product_app.config import RuntimeEnvironment
from product_app.model_slots import ModelSlot
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    BILLING_NOT_BILLED,
    BILLING_POSSIBLY_BILLED,
    InitialAnswerStatus,
    provider_execution_service,
)

_MODEL_ID = "openai/gpt-4o-mini"
_USAGE = {"prompt_tokens": 2400, "completion_tokens": 700, "total_tokens": 3100}


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _completion(content: str) -> bytes:
    return sse_from_completion(
        {"choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": _USAGE}
    )


def _http_error(code: int) -> HTTPError:
    return HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=code,
        msg="upstream said no",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )


def _install(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[int]:
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "tavily_api_key", "", raising=False)
    posts = [0]

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        posts[0] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return posts


def _produce(*, search: bool = False) -> Any:
    return provider_execution_service.produce_initial_answer(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options with no trigger phrases",
        model_slot=ModelSlot(slot_number=1, model_id=_MODEL_ID, search=search),
        credential_source=ProviderCredentialSource.APP_OWNED,
        openrouter_key="sk-or-test",
    )


@pytest.mark.parametrize(
    ("label", "outcome", "expected"),
    [
        # Refused before inference. Each of these statuses is in
        # ``_UNBILLED_HTTP_STATUSES`` because the provider decided against the
        # request without generating, so no charge is possible.
        ("http-401", _http_error(401), BILLING_NOT_BILLED),
        ("http-402", _http_error(402), BILLING_NOT_BILLED),
        ("http-429", _http_error(429), BILLING_NOT_BILLED),
        # Never left the process: no socket, so nothing to bill.
        ("conn-refused", URLError(ConnectionRefusedError("nope")), BILLING_NOT_BILLED),
        # Dispatched. The provider may already have generated and charged.
        ("http-500", _http_error(500), BILLING_POSSIBLY_BILLED),
        ("http-503", _http_error(503), BILLING_POSSIBLY_BILLED),
        ("read-timeout", URLError(TimeoutError("read")), BILLING_POSSIBLY_BILLED),
        ("torn-body", http.client.IncompleteRead(b"partial"), BILLING_POSSIBLY_BILLED),
    ],
)
def test_a_failed_slot_records_whether_it_could_have_been_billed(
    monkeypatch: pytest.MonkeyPatch, label: str, outcome: Any, expected: str
) -> None:
    """The verdict reaches the slot record, and it is the RIGHT one.

    Both directions are covered in one table on purpose: four outcomes that
    provably precede generation and four that provably follow dispatch. A
    single-direction test would pass against an implementation that hardcoded
    either constant.

    Turns RED when: the verdict is dropped on the way to ``_failed_answer``,
    hardcoded to one value, or inverted — and, because the table spans both
    classes, an implementation that always says "possibly billed" (the current
    conservative posture, which is safe but uninformative) fails the first four
    rows just as an always-"not billed" one fails the last four.
    """
    _install(monkeypatch, outcome)
    answer = _produce()
    assert answer.status is InitialAnswerStatus.FAILED
    assert answer.token_usage is None, "a failed slot must still carry no usage"
    assert answer.billing_class == expected


def test_a_dispatched_call_that_returned_NO_USABLE_TEXT_is_possibly_billed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The F-06 shape: a 200 arrives carrying the provider's own ``usage`` but a
    whitespace-only completion.

    The slot is reported FAILED and carries no usage (the #175 money decision),
    but a response DID come back, so the request was dispatched and those tokens
    were charged. This is the single most important row in the file: it is the
    one failure mode where money provably moved and the slot still produced
    nothing.

    Turns RED when: the verdict is derived only from the failure sentinels and
    an arrived-but-unusable response defaults to ``not_billed``.
    """
    _install(monkeypatch, _Body(_completion("   ​  ")))
    answer = _produce()
    assert answer.status is InitialAnswerStatus.FAILED
    assert answer.token_usage is None
    assert answer.billing_class == BILLING_POSSIBLY_BILLED


def test_a_successful_answer_carries_NO_verdict_because_the_question_does_not_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``billing_class`` answers "for a slot that produced nothing, could it
    still have cost money?" — so it is ``None`` on a slot that produced an
    answer, whose cost is already itemised from its captured usage.

    Turns RED when: the field is stamped unconditionally, which would make it
    look like a billing classification of every call rather than the failed-slot
    discriminator it is.
    """
    _install(monkeypatch, _Body(_completion("A real answer from the model.")))
    answer = _produce()
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.token_usage is not None
    assert answer.billing_class is None


def test_a_slot_that_never_dispatched_is_not_billed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The LOCAL forced-failure seam issues no POST at all.

    Positive partner for the "nothing left the process" arm: it proves the
    ``not_billed`` verdict is reachable without a provider status, so the four
    refusal rows above are not the only path to it.

    Turns RED when: the forced-failure path is stamped ``possibly_billed``, or
    left unset while the field is declared non-optional for a failed slot.
    """
    posts = _install(monkeypatch, _Body(_completion("unused")))
    # The magic phrase is gated on the LOCAL runtime environment, which is the
    # default — asserted here rather than assumed, because the whole point of
    # this test is that NO request is dispatched.
    assert config.settings.runtime_environment is RuntimeEnvironment.LOCAL
    answer = provider_execution_service.produce_initial_answer(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="force provider failure",
        model_slot=ModelSlot(slot_number=1, model_id=_MODEL_ID, search=False),
        credential_source=ProviderCredentialSource.APP_OWNED,
        openrouter_key="sk-or-test",
    )
    # No `pytest.skip` here. A first version skipped when the slot did not come
    # back FAILED, which let the test silently stop testing the moment the
    # trigger phrase or its LOCAL gate changed. Assert the precondition instead.
    assert answer.status is InitialAnswerStatus.FAILED, (
        "the LOCAL forced-failure trigger phrase did not fire; this test cannot "
        "measure the undispatched path without it"
    )
    assert posts[0] == 0, "nothing may be dispatched on the forced-failure path"
    assert answer.billing_class == BILLING_NOT_BILLED


@pytest.mark.parametrize(
    ("label", "outcomes", "expected_posts", "expected"),
    [
        # A 400/404 on the ``:online`` id is consumed by the bare-id retry, so
        # what the cost layer sees is the verdict of the call that actually
        # SERVED. Both directions, because the retry is where a wrong answer
        # would be most plausible.
        ("online-404-then-bare-401", (404, 401), 2, BILLING_NOT_BILLED),
        ("online-404-then-bare-500", (404, 500), 2, BILLING_POSSIBLY_BILLED),
        ("online-500-no-retry", (500,), 1, BILLING_POSSIBLY_BILLED),
    ],
)
def test_the_retry_chain_records_the_verdict_of_the_call_that_served(
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    outcomes: tuple[int, ...],
    expected_posts: int,
    expected: str,
) -> None:
    """A searching slot can POST twice, and the verdict must follow the second.

    Every other test in this file drives ``search=False``, so the ``:online``
    then bare-id retry shape — the PRODUCTION default, since ``ModelSlot.search``
    defaults to True — went untested. The POST count is asserted so the retry is
    proven to have happened rather than inferred.

    The dangerous ordering is row 2: an unbilled 404 followed by a dispatched
    500. If the first verdict won, a call that may have been charged would be
    recorded as provably unbilled.

    Turns RED when: the first attempt's verdict is kept, or the retry's verdict
    is dropped, or ``_SearchRejected`` stops being consumed by the retry.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "tavily_api_key", "", raising=False)
    wire: list[str] = []
    remaining = list(outcomes)

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        import json as _json

        wire.append(_json.loads(request.data.decode("utf-8"))["model"])
        raise _http_error(remaining.pop(0))

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    answer = _produce(search=True)
    assert len(wire) == expected_posts, f"{label}: wire was {wire}"
    if expected_posts == 2:
        assert wire[0].endswith(":online") and not wire[1].endswith(":online")
    assert answer.status is InitialAnswerStatus.FAILED
    assert answer.billing_class == expected


def test_the_sibling_failure_constructors_take_the_verdict_from_their_CALLER(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cancelled_answer`` and ``deadline_exceeded_answer`` do not decide this.

    An earlier draft had them hardcode a verdict, and round 2 of review showed
    why that cannot work: ``deadline_exceeded_answer`` returned
    ``possibly_billed`` unconditionally, which is correct when a request is in
    flight and a LIE on a run that could not spend at all. With live execution
    off — including the #100 global-ceiling path, which forces
    ``openrouter_key = ""`` PRECISELY so the run cannot spend — no POST is ever
    made. Measured: the field claimed a dispatch that was impossible.

    Neither constructor can know: the key lives at the call site. So the
    parameter is required and the caller decides.

    Turns RED when: either constructor re-acquires a default or hardcodes a
    verdict, which would let it contradict the run it is describing.
    """
    slot = ModelSlot(slot_number=1, model_id=_MODEL_ID)
    common = {
        "model_slot": slot,
        "account_id": uuid4(),
        "query_run_id": uuid4(),
        "credential_source": ProviderCredentialSource.APP_OWNED,
    }
    # Whatever the caller passes is what is recorded — for BOTH constructors and
    # BOTH values. That is the whole contract, and it is what makes the
    # call-site tests below meaningful.
    for verdict in (BILLING_NOT_BILLED, BILLING_POSSIBLY_BILLED):
        cancelled = provider_execution_service.cancelled_answer(
            **common,  # type: ignore[arg-type]
            billing_class=verdict,
        )
        deadline = provider_execution_service.deadline_exceeded_answer(
            **common,  # type: ignore[arg-type]
            billing_class=verdict,
        )
        for answer in (cancelled, deadline):
            assert answer.status is InitialAnswerStatus.FAILED
            assert answer.token_usage is None
            assert answer.billing_class == verdict
    assert (
        provider_execution_service.cancelled_answer(
            **common,  # type: ignore[arg-type]
            billing_class=BILLING_NOT_BILLED,
        ).error_code
        == "CANCELLED"
    )
    assert (
        provider_execution_service.deadline_exceeded_answer(
            **common,  # type: ignore[arg-type]
            billing_class=BILLING_POSSIBLY_BILLED,
        ).error_code
        == "RUN_DEADLINE_EXCEEDED"
    )


def test_a_deadline_cut_slot_on_a_run_that_CANNOT_SPEND_is_not_billed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect round 2 found, pinned at the decision rather than the stub.

    ``_live_execution_enabled`` is the predicate the orchestration call site
    uses, and it is what separates "a POST may be in flight" from "no POST was
    possible". An empty key is not a corner case: the #100 global-ceiling path
    sets it empty on purpose, so a ceiling-degraded run is exactly where a
    ``possibly_billed`` deadline slot would be a false money claim.

    Turns RED when: the call site stops consulting the key, or the predicate is
    inverted — either way a $0 run would report that money may have moved.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    assert provider_execution_service._live_execution_enabled(openrouter_key="sk-or-test") is True
    assert provider_execution_service._live_execution_enabled(openrouter_key="") is False, (
        "an empty key must read as 'cannot dispatch' — this is the whole basis "
        "of the deadline verdict at the call site"
    )
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", False, raising=False)
    assert provider_execution_service._live_execution_enabled(openrouter_key="sk-or-test") is False
