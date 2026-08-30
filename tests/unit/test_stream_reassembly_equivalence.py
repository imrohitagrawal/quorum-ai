"""The streamed payload must mean what the non-streamed one meant.

Every paid call streams (ADR-0084), and the four extractors
(``_extract_message_content``, ``_extract_usage``,
``_finish_reason_indicates_truncation``, ``_extract_citations``) are reused
UNCHANGED against a payload reassembled from SSE frames. This file is the
contract that makes that safe: for a given frame sequence, the reassembled
payload must produce what the equivalent non-streamed body produces.

Each test names what turns it red. The rows were not invented -- each closes a
failure mode enumerated before the code was written, and the ones marked
MEASURED were reproduced against this tree.

The accepted DIVERGENCE, stated rather than hidden: a non-streamed
``message.content`` may be a LIST of parts, which ``_extract_message_content``
joins with ``"\\n"``. A stream carries ``delta.content`` as a string and has no
way to say "these were separate parts", so a two-part message arrives as one
run of characters. Byte-equality is impossible for that class; the stream is
the authority for what the model actually sent.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.provider_wire import sse_comment, sse_stream

from product_app.providers import (
    _extract_citations,
    _extract_message_content,
    _extract_usage,
    _finish_reason_indicates_truncation,
    _iter_sse_data,
    _reassemble_streamed_completion,
)

_USAGE = {"prompt_tokens": 4000, "completion_tokens": 700, "total_tokens": 4700}


def _fold(body: bytes, *, chunk: int | None = None) -> Any:
    """Run the real reader over ``body``, optionally in fixed-size chunks."""
    if chunk is None:
        chunks = iter([body])
    else:
        chunks = (body[i : i + chunk] for i in range(0, len(body), chunk))
    return _reassemble_streamed_completion(_iter_sse_data(chunks))


def _delta(content: str, **extra: object) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": {"content": content, **extra}}]}


def _finish(reason: str) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


def test_a_clean_stream_means_what_the_non_streamed_body_meant() -> None:
    """The mandatory positive partner for every negative in this file.

    RED when: the reassembler is absent, or stops concatenating deltas, or
    stops carrying usage to the top level. Measured on ``main`` before this
    package, an SSE body reached ``json.loads`` and returned
    ``_DISPATCH_UNMEASURED`` with ``upstream_provider_body_unreadable`` -- so
    every assertion below is genuinely red without the code.

    Without this test the file's negatives are all satisfied by a reassembler
    that returns an empty payload for everything.
    """
    streamed = _fold(
        sse_stream(
            _delta("Part one. "),
            _delta("Part two."),
            _finish("stop"),
            {"choices": [], "usage": _USAGE},
        )
    )
    twin = {
        "choices": [{"finish_reason": "stop", "message": {"content": "Part one. Part two."}}],
        "usage": _USAGE,
    }
    assert _extract_message_content(streamed.payload) == _extract_message_content(twin)
    assert _extract_message_content(streamed.payload) == "Part one. Part two."
    assert _extract_usage(streamed.payload) == _extract_usage(twin)
    assert _finish_reason_indicates_truncation(streamed.payload) is False
    assert streamed.terminator == "done"
    assert streamed.body_error is None


def test_usage_is_read_from_a_frame_that_carries_no_choices() -> None:
    """RED when: the frame loop skips a frame before checking it for usage.

    OpenRouter's usage-accounting documentation shows the final chunk as
    ``{"choices": [], "usage": {...}}``. A loop written as
    ``frame["choices"][0]`` raises on it -- downgrading a complete, billed,
    fully measurable answer to ``estimated`` -- and one written defensively as
    ``if not frame.get("choices"): continue`` silently drops the usage, which
    downgrades EVERY streamed run for ever.
    """
    streamed = _fold(sse_stream(_delta("hi"), _finish("stop"), {"choices": [], "usage": _USAGE}))
    usage = _extract_usage(streamed.payload)
    assert usage is not None
    assert usage.total_tokens == 4700
    assert streamed.usage_frame_count == 1


def test_a_stream_with_no_usage_frame_reports_no_usage_rather_than_zeros() -> None:
    """The money assertion. RED when: the reassembler seeds a usage dict.

    MEASURED on this tree: ``_extract_usage`` accepts
    ``{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}`` as REAL
    usage and returns ``TokenUsage(0, 0, 0)``. A zero-seeded accumulator would
    therefore make every run read ``measured`` at $0.00 -- and a ``measured``
    receipt is the one thing that OVERWRITES the booked charge on both spend
    rails, so the daily cap and the hard limit would stop binding entirely.
    Absent usage costs the run its ``measured`` label instead, which is the
    honest direction.

    Its positive partner is the test above: without one, "usage is None" is
    satisfied by a reassembler that never reads usage at all.
    """
    streamed = _fold(sse_stream(_delta("hi"), _finish("stop")))
    assert _extract_usage(streamed.payload) is None
    assert streamed.usage_frame_count == 0


def test_usage_is_taken_from_the_last_frame_and_never_summed() -> None:
    """RED when: the accumulator uses ``+=``.

    Summing is wrong under BOTH plausible vendor shapes -- one final total, or
    a running total repeated per frame -- and it overstates a charge, which
    then reconciles the ledger UP and blocks the account early. Taking the last
    is correct under both.
    """
    streamed = _fold(
        sse_stream(
            _delta("hi"),
            {
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            {
                "choices": [],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
            _finish("stop"),
        )
    )
    usage = _extract_usage(streamed.payload)
    assert usage is not None
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (20, 10, 30)
    assert streamed.usage_frame_count == 2


def test_an_unclean_finish_reason_latches_over_a_later_clean_one() -> None:
    """RED when: the reduction is last-wins.

    The documented streaming shape repeats ``finish_reason: "stop"`` on the
    usage chunk. Last-wins would therefore erase ``"length"`` from a truncated
    answer, and with it the user-visible "(shortened)" marker on an answer they
    paid for.
    """
    streamed = _fold(
        sse_stream(
            _delta("cut off here"),
            _finish("length"),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": _USAGE},
        )
    )
    assert _finish_reason_indicates_truncation(streamed.payload) is True
    assert _extract_usage(streamed.payload) is not None


def test_a_clean_stop_is_not_reported_as_truncation() -> None:
    """The partner for the latch. RED when: the latch is made unconditional.

    Without this, "always truncated" passes the test above.
    """
    streamed = _fold(sse_stream(_delta("all of it"), _finish("stop")))
    assert _finish_reason_indicates_truncation(streamed.payload) is False


def test_content_filter_is_still_not_truncation() -> None:
    """RED when: the latch widens ``_UNCLEAN_FINISH_REASONS``.

    ``content_filter`` means the provider refused, which is a different event
    from running out or breaking, and ``tests/unit/test_providers.py`` pins it
    as non-truncation on purpose. Streaming must not quietly change that.
    """
    streamed = _fold(sse_stream(_delta("blocked"), _finish("content_filter")))
    assert _finish_reason_indicates_truncation(streamed.payload) is False


def test_a_top_level_error_frame_marks_the_answer_unclean() -> None:
    """RED when: an error frame is folded in as if the stream ended cleanly.

    OpenRouter documents a mid-stream failure as a top-level ``error`` object
    alongside ``finish_reason: "error"``. When only the first arrives, a
    partial answer would otherwise be served with ``is_truncated=False`` --
    counted in ``live_count``, in the citation-coverage denominator, and priced
    as a whole answer.

    The usage assertion is the other half: the provider's own statement of what
    it charged must survive, which is the F-06 finding-C precedent.
    """
    streamed = _fold(
        sse_stream(
            _delta("half an ans"),
            {"error": {"code": 502, "message": "provider exploded"}},
            {"choices": [], "usage": _USAGE},
            # No ``[DONE]``: an error frame must be a terminator on its own.
            # Without that, a stream that breaks and never sends the sentinel
            # would be reported incomplete and its stated usage discarded --
            # throwing away the provider's own record of what it charged.
            done=False,
        )
    )
    assert _finish_reason_indicates_truncation(streamed.payload) is True
    assert _extract_message_content(streamed.payload) == "half an ans"
    assert _extract_usage(streamed.payload) is not None
    assert streamed.terminator == "error"


def test_reasoning_is_never_folded_into_the_answer() -> None:
    """RED when: the reassembler iterates the delta's keys instead of naming one.

    The judge sends ``reasoning={"effort": "low"}`` and parses the reply as
    STRICT JSON with no fence-stripping and no repair, so a single leaked
    reasoning token turns a PAID call into no verdict at all. ``refusal`` and
    ``tool_calls`` are excluded by the same whitelist and are asserted here so
    a later widening cannot pass.
    """
    streamed = _fold(
        sse_stream(
            {"choices": [{"index": 0, "delta": {"reasoning": "let me think about this"}}]},
            {"choices": [{"index": 0, "delta": {"refusal": "I will not"}}]},
            _delta('{"faithfulness": 3}'),
            _finish("stop"),
        )
    )
    text = _extract_message_content(streamed.payload)
    assert text == '{"faithfulness": 3}'
    assert json.loads(text) == {"faithfulness": 3}


def test_a_second_choice_never_splices_into_the_first() -> None:
    """RED when: the loop appends every choice's delta to one buffer.

    Everything downstream reads ``choices[0]``. A frame carrying ``index: 1``
    must be discarded, not concatenated, or a multi-choice stream would
    interleave two answers into one undetectably.
    """
    streamed = _fold(
        sse_stream(
            _delta("ZERO"),
            {"choices": [{"index": 1, "delta": {"content": "ONE"}}]},
            _finish("stop"),
        )
    )
    assert _extract_message_content(streamed.payload) == "ZERO"


def test_annotations_survive_and_keep_their_arrival_order() -> None:
    """RED when: annotations are dropped, re-ordered, or merged as a set.

    They are the model's OWN sources (``is_fallback=False``). Dropping them
    fires a Tavily search per slot, moves every answer out of the citation
    coverage numerator, and lowers the trust score -- which
    ``evaluation.py`` computes excluding fallback sources, so the substitute
    does not repair the metric. Their ORDER is the bibliography numbering the
    UI renders, so re-ordering renumbers a user's citations.
    """
    streamed = _fold(
        sse_stream(
            _delta("a", annotations=[{"url": "https://one.test/a", "title": "One"}]),
            _delta("b", annotations=[{"url": "https://two.test/b", "title": "Two"}]),
            # A repeat of the first: de-duplicated by identity, not merged.
            _delta("c", annotations=[{"url": "https://one.test/a", "title": "One"}]),
            _finish("stop"),
        )
    )
    refs = _extract_citations(streamed.payload)
    assert [r.title for r in refs] == ["One", "Two"]
    assert [str(r.url) for r in refs] == ["https://one.test/a", "https://two.test/b"]


def test_keep_alive_comments_are_not_answer_text() -> None:
    """RED when: a line beginning ``:`` is treated as data.

    OpenRouter sends these -- 1, 16, 16 and 21 per call across four measured
    streamed calls. Folded in as text they would appear verbatim in a user's
    answer; parsed as JSON they would abort the whole call.
    """
    body = (
        sse_comment()
        + sse_stream(_delta("real answer"), done=False)
        + sse_comment()
        + sse_stream(_finish("stop"))
    )
    streamed = _fold(body)
    assert _extract_message_content(streamed.payload) == "real answer"
    assert "OPENROUTER" not in _extract_message_content(streamed.payload)


@pytest.mark.parametrize("chunk", [1, 3, 7, 64, None], ids=["b1", "b3", "b7", "b64", "whole"])
def test_the_result_does_not_depend_on_how_the_bytes_were_split(chunk: int | None) -> None:
    """RED when: the reader parses per chunk instead of carrying a tail.

    MEASURED: a 68-byte frame cut at byte 40 yields one ``JSONDecodeError`` and
    zero events for a per-chunk parser, and the frame most likely to be torn is
    the LARGEST -- the usage frame -- so the silent cost is a good run dropping
    to ``estimated``.

    ``chunk=1`` also covers the multi-byte case by construction: the em-dash
    and the emoji below are split mid-character at that size, and a per-chunk
    ``.decode()`` raises ``UnicodeDecodeError`` on both halves. That class is
    in ``_EXPECTED_TRANSPORT_ERRORS``, so a healthy PAID answer would have been
    logged at WARNING and thrown away.
    """
    body = sse_stream(
        _delta("café — 😀 "),
        _delta("costs €5"),
        _finish("stop"),
        {"choices": [], "usage": _USAGE},
    )
    streamed = _fold(body, chunk=chunk)
    assert _extract_message_content(streamed.payload) == "café — 😀 costs €5"
    usage = _extract_usage(streamed.payload)
    assert usage is not None
    assert usage.total_tokens == 4700
    assert streamed.terminator == "done"


def test_crlf_separated_frames_parse() -> None:
    """RED when: the reader splits on ``\\n\\n`` instead of handling ``\\r``.

    The SSE specification permits ``\\r\\n``. A ``split("\\n\\n")`` parser merges
    a CRLF frame with the one after it and loses both to a ``JSONDecodeError``.
    """
    body = sse_stream(_delta("hello"), _finish("stop")).replace(b"\n", b"\r\n")
    streamed = _fold(body)
    assert _extract_message_content(streamed.payload) == "hello"
    assert streamed.terminator == "done"


def test_a_stream_that_never_says_it_finished_is_reported_incomplete() -> None:
    """The framing check. RED when: the terminator requirement is removed.

    ``_iter_body_within_budget`` restores an ``IncompleteRead`` guard that
    ``read1`` had silently dropped -- but it reads ``HTTPResponse.length``,
    which is ``None`` under chunked framing, and every streamed response is
    chunked. So a stream that stops part-way raises NOTHING. Without this
    check the prefix is valid, is served as a whole answer, is priced, and
    reports ``is_truncated=False`` -- the exact defect the ``IncompleteRead``
    restore was written to prevent, reached by a different route.
    """
    streamed = _fold(sse_stream(_delta("half an ans"), done=False))
    assert streamed.terminator == "none"
    assert streamed.frame_count == 1


@pytest.mark.parametrize(
    ("frames", "expected"),
    [
        ((_delta("x"), _finish("stop")), "finish_reason"),
        ((_delta("x"),), "none"),
        ((_delta("x"), {"error": {"code": 500}}), "error"),
    ],
    ids=["finish-reason", "nothing", "error-frame"],
)
def test_every_terminator_is_reported_by_name(frames: tuple[Any, ...], expected: str) -> None:
    """RED when: any terminator collapses into another.

    ``[DONE]`` is the OpenAI-compatible sentinel but is measured NOWHERE in
    this repository against this upstream, so requiring it alone would risk
    classifying every healthy call ``_DISPATCH_UNMEASURED`` -- rule 8c's
    failure mirrored. Accepting three and RECORDING which one arrived is what
    lets production data settle it.
    """
    streamed = _fold(sse_stream(*frames, done=False))
    assert streamed.terminator == expected


def test_a_malformed_frame_is_carried_out_as_a_body_error() -> None:
    """RED when: the frame parse failure is raised inside the transport stage.

    ``_log_post_dispatch_failure`` logs an EXPECTED class at WARNING and
    anything else at ERROR. ``JSONDecodeError`` is expected of a body and not
    of a transport, so raising it in the ``urlopen`` block pages an operator
    for an ordinary upstream hiccup and files it under the wrong event.
    """
    streamed = _fold(sse_stream("{not json at all", done=False))
    assert streamed.body_error is not None
    assert type(streamed.body_error).__name__ == "JSONDecodeError"
