"""The streamed payload must mean what the non-streamed one meant.

Every call the provider service makes streams (ADR-0084), and the four extractors
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


def test_annotations_survive_and_match_the_non_streamed_bibliography() -> None:
    """RED when: annotations are dropped, re-ordered, de-duplicated, or merged.

    They are the model's OWN sources (``is_fallback=False``). Dropping them
    fires a Tavily search per slot, moves every answer out of the citation
    coverage numerator, and lowers the trust score -- which ``evaluation.py``
    computes excluding fallback sources, so the substitute does not repair the
    metric.

    The DUPLICATE row is the point of this test. ``_extract_citations``
    de-duplicates nothing, so a non-streamed response carrying the same
    annotation twice yields two entries. An earlier version of the reassembler
    de-duplicated, which sounds tidier and silently renumbered a user's
    bibliography relative to the same answer delivered non-streamed -- every
    ordinal after the duplicate shifted by one. The assertion is equality with
    the non-streamed twin, not a hand-written list, so the two paths cannot
    drift apart again.
    """
    annotations = [
        {"url": "https://one.test/a", "title": "One"},
        {"url": "https://one.test/a", "title": "One"},
        {"url": "https://two.test/b", "title": "Two"},
    ]
    streamed = _fold(
        sse_stream(
            _delta("a", annotations=annotations[:1]),
            _delta("b", annotations=annotations[1:]),
            _finish("stop"),
        )
    )
    twin = {"choices": [{"message": {"content": "ab", "annotations": annotations}}]}
    assert _extract_citations(streamed.payload) == _extract_citations(twin)
    assert [r.title for r in _extract_citations(streamed.payload)] == ["One", "One", "Two"]


def test_citations_are_a_fallback_for_annotations_never_a_merge() -> None:
    """RED when: the two keys are merged into one list.

    ``_extract_citations`` reads ``annotations or citations`` -- a SHORT
    CIRCUIT, so a response carrying both yields only the first. Merging them
    would invent a bibliography the non-streamed path never produces. The
    ``citations``-only row is the positive partner: without it, "citations are
    ignored" would pass just as well.
    """
    ann = [{"url": "https://ann.test/1", "title": "ANN"}]
    cit = [{"url": "https://cit.test/1", "title": "CIT"}]

    both = _fold(sse_stream(_delta("x", annotations=ann, citations=cit), _finish("stop")))
    assert [r.title for r in _extract_citations(both.payload)] == ["ANN"]
    assert _extract_citations(both.payload) == _extract_citations(
        {"choices": [{"message": {"content": "x", "annotations": ann, "citations": cit}}]}
    )

    only_cit = _fold(sse_stream(_delta("x", citations=cit), _finish("stop")))
    assert [r.title for r in _extract_citations(only_cit.payload)] == ["CIT"]


def test_a_frame_with_no_index_contributes_to_choice_zero() -> None:
    """RED when: an absent ``index`` is treated as anything but 0.

    A single-choice stream may omit the field entirely. Every other fixture in
    this file sets it explicitly, so without this row the documented default is
    never exercised -- and getting it wrong turns a complete PAID answer into
    an empty one.
    """
    streamed = _fold(
        sse_stream(
            {"choices": [{"delta": {"content": "no index field"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        )
    )
    assert _extract_message_content(streamed.payload) == "no index field"


def test_a_multi_line_data_field_is_one_event_joined_with_newlines() -> None:
    """RED when: the reader dispatches one event per line.

    The SSE specification accumulates ``data:`` values and dispatches at a
    BLANK line, joining with ``\n``. This pins the ACCUMULATION: "one line, one
    event" splits a frame into two halves that neither parse.

    **It deliberately does not pin the join CHARACTER, because nothing can.**
    Replacing ``"\n".join`` with ``"".join`` survives this file and the
    transport file -- verified by running it, not assumed. That is an
    EQUIVALENT mutant rather than a hole: between two JSON tokens a newline is
    whitespace, and a raw newline cannot appear inside a JSON string (it must
    be escaped), so no valid frame can observe which character was used. The
    ``\n`` is kept because the specification says so and because a future
    non-JSON data field would notice; claiming a test proves it would be the
    vacuity this file exists to avoid.
    """
    body = b'data: {"choices":[{"index":0,"delta":\ndata: {"content":"split frame"}}]}\n\n'
    streamed = _fold(body + sse_stream(_finish("stop")))
    assert _extract_message_content(streamed.payload) == "split frame"
    assert streamed.body_error is None


def test_a_line_we_cannot_read_is_never_silently_dropped() -> None:
    """The regression this guard exists for. RED when: an unknown line is ignored.

    Measured before the guard: a leading byte-order mark, one stray leading
    space, or ``Data:`` with a capital D made a real frame fail the ``data:``
    test. It was dropped in silence and the SHORTENED answer was then served as
    complete, priced, and reported ``is_truncated=False`` -- while the
    non-streaming reader this replaced failed loudly on the very same bodies.

    The SSE specification says to ignore an unknown field; on a paid path we
    refuse to, because we cannot tell a field we do not need from a frame we
    failed to parse.
    """
    for corrupted in (b" data: ", b"Data: "):
        body = (
            corrupted
            + b'{"choices":[{"index":0,"delta":{"content":"LOST"}}]}\n\n'
            + sse_stream(_delta(" kept"), _finish("stop"))
        )
        streamed = _fold(body)
        assert streamed.unrecognised_lines == 1, corrupted
        assert "LOST" not in _extract_message_content(streamed.payload)


def test_a_byte_order_mark_does_not_cost_the_first_frame() -> None:
    """RED when: a leading BOM is not stripped.

    The partner for the test above, and the reason a BOM is handled rather than
    refused: the specification says to strip one, so a BOM'd stream is a VALID
    stream whose first frame would otherwise vanish. Refusing it would be
    correct-but-useless; stripping it is correct and keeps the answer.
    """
    streamed = _fold(b"\xef\xbb\xbf" + sse_stream(_delta("first frame"), _finish("stop")))
    assert _extract_message_content(streamed.payload) == "first frame"
    assert streamed.unrecognised_lines == 0


def test_known_sse_fields_are_ignored_without_being_called_unreadable() -> None:
    """The other partner. RED when: the ignore-list is emptied.

    ``event:``, ``id:`` and ``retry:`` are real SSE fields that carry no
    completion data. Counting them as unreadable would refuse every stream from
    a server that sends them -- the mirror of the failure rule 8c warns about,
    where a mitigation gated on unmeasured upstream behaviour collects nothing.
    """
    body = b"event: message\nid: 42\nretry: 3000\n" + sse_stream(_delta("kept"), _finish("stop"))
    streamed = _fold(body)
    assert streamed.unrecognised_lines == 0
    assert _extract_message_content(streamed.payload) == "kept"


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


def test_a_final_frame_without_a_trailing_blank_line_is_still_delivered() -> None:
    """RED when: the reader only dispatches on a blank line and forgets the tail.

    The SSE specification separates events with a blank line, but a server that
    closes immediately after its last frame has still DELIVERED that frame.
    Dropping it would silently lose whichever frame came last -- most often the
    usage frame, which is the one that decides whether the run is ``measured``.
    """
    body = sse_stream(_delta("all of it"), _finish("stop"), done=False)
    assert body.endswith(b"\n\n")
    streamed = _fold(body.rstrip(b"\n"))
    assert _extract_message_content(streamed.payload) == "all of it"
    assert streamed.terminator == "finish_reason"


def test_nothing_after_the_sentinel_can_change_the_answer() -> None:
    """RED when: frames after ``[DONE]`` are processed instead of drained.

    The stream said it was finished, so nothing after it may alter the answer,
    the usage or the finish reason. The frames are still CONSUMED rather than
    abandoned -- draining is what lets the body generator reach its end and
    re-raise ``IncompleteRead`` on a body short of its declared length, which is
    a guarantee an earlier version of this code lost by exiting the loop early.
    """
    streamed = _fold(
        sse_stream(_delta("the real answer"), _finish("stop"))
        + sse_stream(
            _delta(" AND SOME MORE"),
            {
                "choices": [],
                "usage": {"prompt_tokens": 9, "completion_tokens": 9, "total_tokens": 9},
            },
            done=False,
        )
    )
    assert _extract_message_content(streamed.payload) == "the real answer"
    assert _extract_usage(streamed.payload) is None
    assert streamed.terminator == "done"


@pytest.mark.parametrize(
    "frame",
    [42, '"a bare string"', [1, 2, 3], {"choices": [42]}, {"choices": "not a list"}],
    ids=["number", "string", "array", "non-mapping-choice", "choices-not-a-list"],
)
def test_a_malformed_frame_is_skipped_rather_than_fatal(frame: object) -> None:
    """RED when: a frame that is not the expected shape aborts the whole call.

    A malformed frame says nothing, and it is not an end condition either.
    Raising on one would let a single stray keep-alive throw away an otherwise
    complete and already-billed answer -- the understate direction. Skipping it
    keeps the good frames, and the terminator check still decides whether what
    arrived may be served at all.
    """
    streamed = _fold(sse_stream(_delta("good "), frame, _delta("text"), _finish("stop")))
    assert _extract_message_content(streamed.payload) == "good text"
    assert streamed.body_error is None


@pytest.mark.parametrize("chunk", [1, 2, 3, 4, 64], ids=["b1", "b2", "b3", "b4", "b64"])
def test_a_byte_order_mark_is_stripped_however_the_wire_splits_it(chunk: int) -> None:
    """RED when: the BOM decision is made on the first chunk alone.

    Measured before the length guard: a BOM delivered in a 1- or 2-byte chunk
    was never stripped, so its ``data:`` line became unrecognisable and the
    whole PAID call was refused. The outcome depended on how the wire happened
    to split the bytes -- which is precisely what
    ``test_the_result_does_not_depend_on_how_the_bytes_were_split`` exists to
    forbid. ``b1`` and ``b2`` are the rows that were red.
    """
    body = b"\xef\xbb\xbf" + sse_stream(_delta("first frame"), _finish("stop"))
    streamed = _fold(body, chunk=chunk)
    assert _extract_message_content(streamed.payload) == "first frame"
    assert streamed.unrecognised_lines == 0


@pytest.mark.parametrize("tail", [b"\r", b" ", b"  \r", b"\t"], ids=["cr", "sp", "sp-cr", "tab"])
def test_trailing_whitespace_at_end_of_stream_is_not_a_line_we_could_not_read(
    tail: bytes,
) -> None:
    """RED when: the EOF residue is tested for truthiness instead of content.

    The in-loop path has a blank-line guard; the end-of-stream path did not, so
    a trailing bare CR or a single space refused a complete, terminated,
    usage-bearing answer -- measured end to end over a real socket. Whitespace
    is not a frame we failed to parse, and refusing on it throws away an answer
    that was already fully in hand and already paid for.

    Its positive partner is ``test_a_line_we_cannot_read_is_never_silently_
    dropped``: real content must still be refused, or this would be satisfied
    by dropping the guard altogether.

    A ``\r\n`` tail was dropped from this list: it leaves NO residue at all, so
    that row never reached the branch it named and could not fail. A row that
    cannot fail is not coverage.

    ``done=False`` is load-bearing and a first version of this test lacked it.
    With ``[DONE]`` present the reader DRAINS whatever follows, so the residue
    never reaches the end-of-stream branch and the test passed against both the
    guard and its absence -- vacuous, and caught only by mutating the guard.
    Ending on ``finish_reason`` instead is what puts the whitespace on the path
    under test.
    """
    streamed = _fold(sse_stream(_delta("the answer"), _finish("stop"), done=False) + tail)
    assert streamed.unrecognised_lines == 0
    assert _extract_message_content(streamed.payload) == "the answer"


def test_only_one_space_is_stripped_after_the_field_name() -> None:
    """RED when: the value is ``lstrip()``ed instead of losing exactly one space.

    The SSE specification strips ONE optional space. JSON tolerates the
    difference; a sentinel compared with ``==`` does not, and neither does a
    payload whose own first character is a space. Pinning it both ways is what
    stops a well-meaning ``lstrip()``.
    """
    assert list(_iter_sse_data(iter([b"data:  [DONE]\n\n"]))) == [" [DONE]"]
    assert list(_iter_sse_data(iter([b"data: [DONE]\n\n"]))) == ["[DONE]"]


def test_a_body_that_is_not_utf8_raises_rather_than_being_mangled() -> None:
    """RED when: decoding falls back to ``errors="replace"``.

    A replacement decode corrupts a paid answer's text silently while every
    gate stays green -- the shipped code's own docstring predicted exactly that
    hole, and nothing tested it. Raising sends the call to the body handler,
    which classifies it dispatched-but-unmeasured: we cannot read what arrived,
    so we do not claim to.
    """
    with pytest.raises(UnicodeDecodeError):
        list(_iter_sse_data(iter([b'data: {"a": "\xff\xfe"}\n\n'])))


def test_a_byte_order_mark_is_stripped_only_at_the_start_of_the_stream() -> None:
    """RED when: the BOM check runs on every chunk instead of once.

    The specification puts the mark at the start of a stream, not in front of
    an arbitrary frame. A reader that stripped one wherever it appeared would
    silently accept a corrupted mid-stream line as a good frame -- the same
    class of silent repair this parser refuses everywhere else. Counting it
    unrecognised means the call is refused rather than half-read.

    The chunks are handed over EXPLICITLY, with the mark starting the second
    one. That is the only arrangement that separates the two behaviours: the
    check runs once per chunk, so with the whole body in a single chunk a
    reader that re-checks every chunk and one that checks only the first agree,
    and a test built that way pins nothing.
    """
    chunks = [
        sse_stream(_delta("first"), done=False),
        b"\xef\xbb\xbf" + sse_stream(_delta(" second"), _finish("stop"), done=False),
    ]
    streamed = _reassemble_streamed_completion(_iter_sse_data(iter(chunks)))
    assert streamed.unrecognised_lines == 1
    assert _extract_message_content(streamed.payload) == "first"


@pytest.mark.parametrize(
    "body",
    [
        b"\n" + b"\xef\xbb\xbf" + b'data: {"choices":[{"index":0,"delta":{"content":"x"}}]}\n\n',
        b"\r\n" + b"\xef\xbb\xbf" + b'data: {"choices":[{"index":0,"delta":{"content":"x"}}]}\n\n',
        b"\xef\xbb\xbf" + b'data: {"choices":[{"index":0,"delta":{"content":"x"}}]}\n\n',
        b'data: {"choices":[{"index":0,"delta":{"content":"x"}}]}\n\n',
        b"ab",
        b"",
    ],
    ids=["lf-then-bom", "crlf-then-bom", "bom-first", "plain", "shorter-than-a-bom", "empty"],
)
def test_the_same_bytes_classify_the_same_way_at_every_chunk_size(body: bytes) -> None:
    """RED when: any parsing decision depends on how the wire split the bytes.

    This is a PROPERTY, and it is here because prose was not enough. Two
    successive versions of the byte-order-mark handling claimed to be
    split-independent and were not: deciding on the first chunk alone lost a
    BOM delivered in a 1- or 2-byte chunk, and waiting for three bytes still
    lost when the first chunk was a lone newline, because the line loop drained
    the buffer before the decision was taken. Each time the sentence was
    corrected and the mechanism was not.

    A property test over the corpus is what closes that: a reader cannot be
    written that satisfies this and still has a chunk-dependent branch. The
    ``lf-then-bom`` and ``crlf-then-bom`` rows are the ones that were red.
    """
    outcomes = {
        (lambda s: (s.unrecognised_lines, s.frame_count, _extract_message_content(s.payload)))(
            _fold(body, chunk=size)
        )
        for size in (1, 2, 3, 4, 5, 7, 8, 16, 64, 1024)
    }
    outcomes.add(
        (lambda s: (s.unrecognised_lines, s.frame_count, _extract_message_content(s.payload)))(
            _fold(body)
        )
    )
    assert len(outcomes) == 1, f"classification depends on chunking: {outcomes}"
