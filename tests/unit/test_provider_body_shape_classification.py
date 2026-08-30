"""B1: the response BODY decides the outcome, and a dispatched call that
produced no answer leaves evidence.

Every branch in ``_post_messages`` that classifies billing keys on the HTTP
STATUS LINE. Two consequences were measured on ``cb4b6fd`` before this file
existed, by driving the real function through the ``product_app.providers.urlopen``
seam:

    200 JSON: top-level error, no choices    -> LiveProviderResult(text='', usage=None)
                                                and ZERO log records of any kind
    200 JSON: content + finish_reason=error  -> LiveProviderResult(text='half an ans',
                                                usage=40/7/47, trunc=False)
    CONTROL 200 JSON: healthy completion     -> LiveProviderResult(text='hello',
                                                usage=10/5/15, trunc=False)

The second line is indistinguishable from the third. A provider that broke
mid-generation is served as one that finished, so its partial text counts
toward ``live_count``, the agreement tally and the citation-coverage
denominator, and the UI's "(shortened)" marker never paints.

The first line is the only dispatched-failure path in the whole function that
records NOTHING. ``upstream_provider_http_error``, ``upstream_provider_opener_error``,
``upstream_provider_transport_error`` and ``upstream_provider_body_unreadable``
all log; a 200 whose body yields no answer logs nothing at all, so it cannot be
counted in the dataset issue 105 will be settled from.

Both shapes are also exactly what OpenRouter documents for a MID-STREAM
failure: ``object: "chat.completion.chunk"`` carrying a top-level ``error`` and
``choices[0].finish_reason == "error"``. So this file is the classification
half of the streaming work, written against a body shape that is reachable
today rather than against one that needs a parser to exist first.

Every test states what turns it red. Every negative check has a positive
partner. Log assertions walk ``record.__dict__`` and never ``caplog.text`` --
the latter renders with pytest's ``DEFAULT_LOG_FORMAT``, which contains no
``extra`` fields at all, so a leak into ``extra=`` passes it (AGENTS.md rule 8a,
and demonstrated again on this very seam during B1's enumeration).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from tests.provider_wire import sse_from_completion, sse_stream

from product_app import config, telemetry_sink
from product_app.providers import provider_execution_service

_MODEL_ID = "openai/gpt-4o-mini"

#: The provider's OWN statement of what it consumed.
_BILLED = {"prompt_tokens": 40, "completion_tokens": 7, "total_tokens": 47}


class _Body:
    """A 200 whose body read returns ``payload``."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _install(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[int]:
    """Point ``providers.urlopen`` at ``outcome`` and count POSTs issued."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    posts = [0]

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        posts[0] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return posts


def _call() -> Any:
    return provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=_MODEL_ID,
        system_prompt="s",
        user_prompt="u",
    )


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
) -> tuple[Any, list[logging.LogRecord], list[int]]:
    """Run one real provider call against ``body``; return result, records, POSTs."""
    posts = _install(monkeypatch, _Body(body))
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        result = _call()
    return result, list(caplog.records), posts


def _answerless_body(*, usage: bool) -> bytes:
    payload: dict[str, Any] = {"error": {"code": 502, "message": "provider down"}}
    if usage:
        payload["usage"] = _BILLED
    return sse_from_completion(payload)


def _completion(*, content: str, finish_reason: str) -> bytes:
    return sse_from_completion(
        {
            "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
            "usage": _BILLED,
        }
    )


_EMPTY_ANSWER_EVENT = "upstream_provider_empty_answer"


def _events(records: list[logging.LogRecord], name: str) -> list[logging.LogRecord]:
    return [r for r in records if r.msg == name]


# --- group 1: a 200 that yields no answer must leave exactly one record -------


def test_a_200_that_yields_no_answer_records_exactly_one_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the answerless-response log is removed, or fires more than once.

    Measured on ``cb4b6fd``: this body produced ZERO records of ANY kind. The
    count is asserted as an equality, not ``>= 1`` -- a call that logged the
    same failure twice would double-count it in the issue-105 dataset, which
    is the whole reason the record exists.
    """
    _result, records, posts = _drive(monkeypatch, caplog, _answerless_body(usage=False))
    assert posts[0] == 1
    assert len(_events(records, _EMPTY_ANSWER_EVENT)) == 1


def test_a_200_carrying_a_real_answer_records_no_such_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The positive partner for the test above. RED when: the log fires on the
    healthy path, which would turn every successful call into a billing
    warning and drown the file the dataset is read from.

    It asserts the healthy result as well, so it cannot pass over a build that
    simply stopped returning answers.
    """
    result, records, posts = _drive(
        monkeypatch, caplog, _completion(content="hello", finish_reason="stop")
    )
    assert posts[0] == 1
    assert _events(records, _EMPTY_ANSWER_EVENT) == []
    assert result is not None
    assert result.answer_text == "hello"


def test_whitespace_only_text_counts_as_no_answer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the predicate is ``if not content`` rather than the
    ``is_visible`` gate the slot itself is failed by.

    A completion of ``"\\u200b \\ufeff"`` is non-empty as a string and invisible
    as an answer. ``_live_openrouter_response`` already drops it via
    ``is_visible``; if this record used a narrower test the two would disagree
    and the dropped slot would again leave no evidence.
    """
    _result, records, posts = _drive(
        monkeypatch, caplog, _completion(content="​ ﻿", finish_reason="stop")
    )
    assert posts[0] == 1
    assert len(_events(records, _EMPTY_ANSWER_EVENT)) == 1


@pytest.mark.parametrize("finish_reason", ["length", "error", "stop"], ids=str)
def test_an_empty_completion_carrying_a_finish_reason_still_records(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, finish_reason: str
) -> None:
    """RED when: the guard is narrowed to ``not is_visible(content) and not is_truncated``.

    "An empty completion against a tight cap" is the case the shipped comment
    names by hand, and until this test every answerless body in the file was an
    error envelope with NO ``choices`` -- so a guard that skipped the record
    whenever the response also reported truncation would have survived the
    whole suite while silencing precisely the named case.

    Parametrised over all three reasons rather than just ``"length"``, because
    a guard keyed on ``finish_reason == "error"`` instead would leave the same
    hole one value along.
    """
    _result, records, posts = _drive(
        monkeypatch, caplog, _completion(content="", finish_reason=finish_reason)
    )
    assert posts[0] == 1
    assert len(_events(records, _EMPTY_ANSWER_EVENT)) == 1


def test_the_answerless_record_states_the_billing_class_and_whether_usage_arrived(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the record omits ``billing_class``, or reports ``usage_absent``
    the wrong way round.

    Both directions are pinned in one test, because a field that is constant
    across every input is not evidence -- it is decoration.
    """
    _r1, records_without, _p1 = _drive(monkeypatch, caplog, _answerless_body(usage=False))
    caplog.clear()
    _r2, records_with, _p2 = _drive(monkeypatch, caplog, _answerless_body(usage=True))

    without = _events(records_without, _EMPTY_ANSWER_EVENT)[0].__dict__
    with_usage = _events(records_with, _EMPTY_ANSWER_EVENT)[0].__dict__

    assert without["billing_class"] == "possibly_billed"
    assert with_usage["billing_class"] == "possibly_billed"
    assert without["model_id"] == _MODEL_ID
    assert without["usage_absent"] is True
    assert with_usage["usage_absent"] is False


def test_a_stated_charge_survives_the_new_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the answerless branch returns a sentinel instead of the result.

    F-06 finding C: the provider's own statement of what it charged is
    extracted BEFORE any emptiness guard and must survive it. Collapsing this
    path to ``_DISPATCH_UNMEASURED`` would look tidier and would throw away a
    known charge, forcing ``estimated`` on a call whose cost is measured.
    """
    result, _records, posts = _drive(monkeypatch, caplog, _answerless_body(usage=True))
    assert posts[0] == 1
    assert result is not None
    assert result.usage is not None
    assert (
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        result.usage.total_tokens,
    ) == (40, 7, 47)


def test_the_providers_error_message_is_never_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the error envelope's ``message`` is folded into the record.

    A provider error string is upstream-controlled text of unbounded length,
    and the repo's standing rule is that no body content reaches a log. The
    ``record.__dict__`` walk is load-bearing: ``caplog.text`` renders without
    ``extra`` fields, so asserting on it alone passes against a real leak.

    The record-count assertion below is the positive partner -- without it the
    walk would be trivially satisfied by emitting no record at all.
    """
    body = sse_from_completion({"error": {"code": 502, "message": "MARKER-DO-NOT-LOG-THIS-STRING"}})
    _result, records, _posts = _drive(monkeypatch, caplog, body)
    assert len(_events(records, _EMPTY_ANSWER_EVENT)) == 1
    assert "MARKER-DO-NOT-LOG-THIS-STRING" not in caplog.text
    for record in records:
        for value in record.__dict__.values():
            assert "MARKER-DO-NOT-LOG-THIS-STRING" not in str(value)


# --- group 2: every dispatched failure states the class it returns ------------


@pytest.mark.parametrize(
    ("body", "event"),
    [
        # Not a stream at all: no ``data:`` line ever arrives, so no frame is
        # parsed and no terminator is seen. Before streaming both rows below
        # were ``upstream_provider_body_unreadable``; a body that never
        # becomes a stream is now reported as one that stopped without
        # finishing, which is what it is.
        (b"not json at all", "upstream_provider_stream_incomplete"),
        # A real stream whose FRAME is unparseable. This is the row that keeps
        # ``upstream_provider_body_unreadable`` reachable, and it is why the
        # frame-level parse error is carried out of the transport stage
        # instead of being raised there -- raised there it would be logged as
        # a transport failure at ERROR rather than a body failure at WARNING.
        (sse_stream('{"choices": [', done=False), "upstream_provider_body_unreadable"),
        # A well-formed stream that simply stops. Chunked framing cannot see
        # this, so nothing below the reassembler raises.
        (
            sse_stream({"choices": [{"index": 0, "delta": {"content": "half"}}]}, done=False),
            "upstream_provider_stream_incomplete",
        ),
    ],
    ids=["not-a-stream", "torn-frame", "stream-cut-short"],
)
def test_a_post_dispatch_failure_record_states_its_billing_class(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
    event: str,
) -> None:
    """RED when: ``_log_post_dispatch_failure`` stops emitting ``billing_class``.

    Measured on ``cb4b6fd``: this field was ABSENT from both
    ``upstream_provider_transport_error`` and ``upstream_provider_body_unreadable``,
    though the caller returns ``_DISPATCH_UNMEASURED`` on each. The two paths
    that DO carry it (``http_error``, ``opener_error``) are the positive
    partner, and the next test pins their agreement.
    """
    _result, records, posts = _drive(monkeypatch, caplog, body)
    assert posts[0] == 1
    matched = _events(records, event)
    assert len(matched) == 1
    assert matched[0].__dict__["billing_class"] == "possibly_billed"


def test_the_unbilled_path_still_reports_not_billed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The positive partner for the parametrised test above. RED when: a change
    makes ``billing_class`` the constant ``"possibly_billed"`` everywhere.

    A 401 is refused before inference, so its record must say ``not_billed``
    and the call must return ``None``. Without this, a mutation that hard-codes
    the string would satisfy every other assertion in this file.
    """
    from urllib.error import HTTPError

    _install(
        monkeypatch,
        HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=401,
            msg="no",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        ),
    )
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        result = _call()
    matched = _events(list(caplog.records), "upstream_provider_http_error")
    assert len(matched) == 1
    assert matched[0].__dict__["billing_class"] == "not_billed"
    assert result is None


def test_every_possibly_billed_event_reaches_the_durable_billing_file() -> None:
    """RED when: an event that classifies a possible charge is emitted but not
    admitted by the billing-file allowlist.

    ``telemetry_sink`` filters the durable billing stream to an allowlist of
    event names. Two of the four dispatched-failure events were outside it, so
    the most expensive live failure mode -- a healthy but slow chunked
    response abandoned by the per-``recv`` socket timeout, which surfaces as
    ``upstream_provider_transport_error`` -- was invisible in the very file
    issue 105 is to be settled from.

    The names are written as literals here rather than imported from the
    constant under test (rule 7a), and the last assertion is the positive
    partner proving the allowlist still excludes something.
    """
    for name in (
        "upstream_provider_http_error",
        "upstream_provider_opener_error",
        "upstream_provider_transport_error",
        "upstream_provider_body_unreadable",
        "upstream_provider_empty_answer",
    ):
        assert name in telemetry_sink.BILLING_EVENTS, name
    # The positive partner, and the first version of it was worthless: it named
    # ``upstream_provider_call_token_shape``, a string that occurs NOWHERE in
    # this repository, so the exclusion constrained nothing and the allowlist
    # could have been widened to admit every event the process emits with this
    # test still green. The real high-volume event is ``provider_call_tokens``
    # (``providers.py``, the issue-268 stream), which is emitted roughly once
    # per provider call and must stay out of the 1 MiB billing file.
    assert "provider_call_tokens" not in telemetry_sink.BILLING_EVENTS


# --- group 3: a provider that did not finish cleanly is not shown as one that did


def test_a_partial_answer_whose_provider_errored_is_marked_shortened(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: ``finish_reason == "error"`` is not treated as an unclean stop.

    Measured on ``cb4b6fd``: this body returned ``trunc=False``, byte-identical
    in that respect to the healthy control, so a broken generation was served
    as the model's complete view. This is the exact frame OpenRouter documents
    for a mid-stream provider failure.

    The usage assertion rides along deliberately: the fix must mark the answer,
    never discard the charge.
    """
    result, _records, posts = _drive(
        monkeypatch, caplog, _completion(content="half an ans", finish_reason="error")
    )
    assert posts[0] == 1
    assert result is not None
    assert result.answer_text == "half an ans"
    assert result.is_truncated is True
    assert result.usage is not None
    assert result.usage.completion_tokens == 7


def test_a_clean_stop_is_not_marked_shortened(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The positive partner. RED when: the widening is written so that anything
    other than ``"length"`` reports truncation, which would stamp
    "(shortened)" on every normal answer the product serves.
    """
    result, _records, posts = _drive(
        monkeypatch, caplog, _completion(content="a whole answer", finish_reason="stop")
    )
    assert posts[0] == 1
    assert result is not None
    assert result.is_truncated is False


def test_the_token_ceiling_case_still_reports_shortened(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the fix REPLACES ``"length"`` instead of joining it.

    ``finish_reason == "length"`` is the case the field was built for (F-07).
    A widening written as ``== "error"`` would pass the error test above and
    silently drop the one already in production.
    """
    result, _records, posts = _drive(
        monkeypatch, caplog, _completion(content="cut off mid-", finish_reason="length")
    )
    assert posts[0] == 1
    assert result is not None
    assert result.is_truncated is True


def test_content_filter_is_still_not_reported_as_shortened(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RED when: the widening sweeps in ``"content_filter"`` too.

    That value means the provider REFUSED, not that it ran out or broke, and
    ``tests/unit/test_providers.py`` already pins it as non-truncation on
    purpose. This test exists so a later reader who widens the set again has
    to make that decision deliberately rather than by accident.
    """
    result, _records, posts = _drive(
        monkeypatch, caplog, _completion(content="refused", finish_reason="content_filter")
    )
    assert posts[0] == 1
    assert result is not None
    assert result.is_truncated is False
