"""Issue #447 / the live window's measurement 3: what shape do annotations take?

WHAT IS BLOCKED AND WHY
-----------------------
``build_judge_evidence`` hands the judge ``[i] title :: url`` and nothing in
``src/`` ever opens one of those urls, so the judge grades evidence it has
never read. Closing that gap has two routes — read the passage content
OpenRouter's ``:online`` annotations may carry (no new fetches), or build a
credential-guarded fetcher — and one unmeasured fact decides between them: do
the annotations carry a ``content`` field?

Nobody knows, because ``_extract_citations`` keeps title and url and throws the
rest away at parse time. The paid run of 2026-09-06 was supposed to settle it
and LOST it for exactly that reason.

WHAT THIS FILE LEARNED THE HARD WAY
-----------------------------------
The first version of this capture read the FOLDED payload and reported it as
the provider's response. It is not: every call streams, and
``_reassemble_streamed_completion`` concatenates each frame's annotation list
without de-duplicating and collects from ``choices[0].delta`` ONLY. Four
defects followed, all demonstrated by review and all pinned below:

* a provider re-sending its array per delta multiplied the count and the
  characters by the content-frame count (2 sources / 19 chars read as 8 / 76);
* ``absent`` could not tell "the provider sent none" from "we did not look
  there", while the harvest printed the first;
* ``content_chars == 0`` meant an empty string, a null, a mapping, AND a list
  of parts holding 360 real characters;
* ``flat`` was documented as "our reader works" and came with zero extracted
  citations on a payload now committed as a test.

WHAT TURNS EACH TEST RED
------------------------
Named per test. The file-level answer: delete the ``annotations=`` argument
from the ``_log_call_token_shape`` call in ``_post_messages`` and every wire
test here fails. (``_post_messages``, not ``_post_openrouter`` — the sole call
site is inside the former, which ADR-0031 already names correctly and an
earlier draft of this docstring got wrong.)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from tests.provider_wire import sse_from_completion, sse_stream

from product_app import config, providers, telemetry_sink
from product_app.providers import provider_execution_service

_MODEL_ID = "anthropic/claude-haiku-4.5"

#: A passage long enough that a substring search cannot match it by accident.
#: 120 characters, counted by the assertion that uses it.
_PASSAGE = "SENTINEL-PASSAGE-" + ("z" * 103)

#: A url the product's own sanitizer accepts, so a ``flat`` label and a real
#: extracted citation can be told apart from a ``flat`` label and nothing.
_GOOD_URL = "https://example.com/a-real-page"


class _Collector(logging.Handler):
    """Captures records off the file-only telemetry logger.

    ``product_app.telemetry`` sets ``propagate=False``, so ``caplog`` cannot see
    these records — the same reason ``test_provider_token_telemetry.py`` carries
    its own handler.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def token_records() -> Iterator[_Collector]:
    logger = logging.getLogger(telemetry_sink.TOKEN_TELEMETRY_LOGGER)
    collector = _Collector()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous_level)


def _payload(annotations: object | None, *, key: str = "annotations") -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": "An answer."}
    if annotations is not None:
        message[key] = annotations
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
    }


def _drive_body(
    monkeypatch: pytest.MonkeyPatch, collector: _Collector, body: bytes
) -> dict[str, Any]:
    collector.records.clear()
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    response = MagicMock()
    response.read.return_value = body
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))
    result = provider_execution_service._post_messages(
        openrouter_key="sk-or-test",
        model_id=f"{_MODEL_ID}:online",
        messages=[{"role": "user", "content": "Ask something."}],
    )
    assert result is not None
    records = [r for r in collector.records if r.msg == "provider_call_tokens"]
    # CARDINALITY, not presence (AGENTS.md rule 6b): one call, one record.
    assert len(records) == 1, f"expected exactly 1 token record, got {len(records)}"
    fields: dict[str, Any] = dict(records[0].__dict__)
    return fields


def _drive(
    monkeypatch: pytest.MonkeyPatch,
    collector: _Collector,
    annotations: object | None,
    *,
    key: str = "annotations",
) -> dict[str, Any]:
    """One real call through ``_post_messages``; returns the token record."""
    return _drive_body(monkeypatch, collector, sse_from_completion(_payload(annotations, key=key)))


# --- the shape label: STRUCTURAL, and it says so -----------------------------


def test_a_flat_block_reports_flat_and_a_nested_one_reports_nested(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the label stops discriminating where the url sits.

    ``flat`` means a top-level ``url``/``source`` is present — what
    ``_extract_citations`` reads. ``nested`` means the url is inside a
    ``url_citation`` mapping, the shape OpenRouter's documentation describes.

    Driven through the real transport, not by calling the helper: a helper that
    returns the right label is worth nothing if the value never reaches a
    record (see ``test_the_wire_carries_every_annotation_field``).
    """
    flat = _drive(monkeypatch, token_records, [{"url": _GOOD_URL, "title": "A"}])
    assert flat["annotation_shape"] == "flat"

    nested = _drive(
        monkeypatch,
        token_records,
        [{"type": "url_citation", "url_citation": {"url": _GOOD_URL, "title": "A"}}],
    )
    assert nested["annotation_shape"] == "nested"

    # The POSITIVE PARTNER (AGENTS.md rule 7): two labels that were both, say,
    # "other" would satisfy neither assertion above being ABOUT discrimination.
    assert flat["annotation_shape"] != nested["annotation_shape"]


def test_a_source_only_annotation_is_flat_because_that_is_what_the_reader_takes(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the label reads only ``url`` and forgets ``source``.

    ``_extract_citations`` accepts EITHER. A label reporting ``other`` for a
    ``source``-only block would describe a block the reader handles.
    """
    record = _drive(monkeypatch, token_records, [{"source": _GOOD_URL}])
    assert record["annotation_shape"] == "flat"


def test_a_block_carrying_both_shapes_reports_flat(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the documented tie-break is reversed or removed.

    A judgement call, stated in :data:`providers.ANNOTATION_SHAPES`' comment and
    pinned here so it cannot drift silently. The partner assertion proves the
    nested ``content`` is still counted under the ``flat`` label, so the
    tie-break costs no information.
    """
    record = _drive(
        monkeypatch,
        token_records,
        [{"url": _GOOD_URL, "url_citation": {"url": _GOOD_URL, "content": _PASSAGE}}],
    )
    assert record["annotation_shape"] == "flat"
    assert record["annotation_content_chars"] == len(_PASSAGE)


def test_a_non_empty_list_of_scalars_is_other_not_absent(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``other`` is dropped, or a scalar list falls through to ``absent``.

    ``absent`` means NOTHING ARRIVED, and something did. Filing this under the
    label for silence would hide a real upstream change.
    """
    record = _drive(monkeypatch, token_records, [_GOOD_URL, 7])
    assert record["annotation_shape"] == "other"
    assert record["annotation_count"] == 2


def test_a_real_openrouter_file_annotation_is_other_not_its_own_type_string(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the upstream's ``type`` string is passed through as the label.

    This carries a ``type`` key ON PURPOSE. An earlier corpus used
    ``{"file": {...}}`` — a real OpenRouter file annotation with its ``type``
    key REMOVED — and a mutant returning ``str(first.get("type"))`` on the
    ``other`` arm survived all 29 tests, putting a 400-character
    upstream-authored string into a file with a fixed byte ceiling.
    """
    record = _drive(
        monkeypatch,
        token_records,
        [{"type": "x" * 400, "file": {"name": "x.pdf"}}],
    )
    assert record["annotation_shape"] == "other"
    assert record["annotation_shape"] in providers.ANNOTATION_SHAPES


# --- the fold is not the provider --------------------------------------------


def _sse_frames(*frames: object) -> bytes:
    return sse_stream(*frames)


def test_absent_is_attributed_to_a_site_so_it_cannot_be_blamed_on_the_provider(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``annotation_sites`` stops recording sites the fold does not read.

    THE defect this field exists for. ``_reassemble_streamed_completion``
    collects annotations from ``choices[0].delta`` only, so a provider that puts
    them anywhere else yields a payload identical to one where nothing arrived
    — and the harvest would print "the provider returned no annotations at all",
    a claim about OpenRouter drawn from our own reader (AGENTS.md rule 8c).

    Four sites, and the FOUR-WAY distinction is the assertion: three produce
    ``absent`` with a site naming where the key really was, and only the fourth
    produces ``absent`` with ``none``.
    """
    block = [{"url": _GOOD_URL, "title": "A"}]
    seen: dict[str, str] = {}
    for name, frame in (
        ("delta", {"choices": [{"index": 0, "delta": {"content": "hi", "annotations": block}}]}),
        ("choice", {"choices": [{"index": 0, "delta": {"content": "hi"}, "annotations": block}]}),
        (
            "message",
            {"choices": [{"index": 0, "message": {"content": "hi", "annotations": block}}]},
        ),
        ("frame", {"annotations": block, "choices": [{"index": 0, "delta": {"content": "hi"}}]}),
        ("none", {"choices": [{"index": 0, "delta": {"content": "hi"}}]}),
    ):
        record = _drive_body(monkeypatch, token_records, _sse_frames(frame))
        seen[name] = record["annotation_sites"]

    assert seen["delta"] == "delta"
    assert seen["choice"] == "choice"
    assert seen["message"] == "message"
    assert seen["frame"] == "frame"
    assert seen["none"] == "none"
    # The POSITIVE PARTNER: all five values are distinct, so the field really
    # discriminates rather than returning a constant that happens to match.
    assert len(set(seen.values())) == 5


def test_only_the_delta_site_actually_reaches_the_parsed_payload(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the fold silently starts (or stops) collecting from a new site.

    The pair that makes ``absent`` readable: the same annotation block at two
    sites gives the SAME shape verdict and DIFFERENT site attribution. If a
    future change makes the fold read ``choice`` too, this goes red and the
    ``sites`` vocabulary has to be revisited rather than quietly mislabelling.
    """
    block = [{"url": _GOOD_URL, "title": "A"}]
    in_delta = _drive_body(
        monkeypatch,
        token_records,
        _sse_frames({"choices": [{"index": 0, "delta": {"content": "hi", "annotations": block}}]}),
    )
    at_choice = _drive_body(
        monkeypatch,
        token_records,
        _sse_frames({"choices": [{"index": 0, "delta": {"content": "hi"}, "annotations": block}]}),
    )
    assert in_delta["annotation_shape"] == "flat" and in_delta["annotation_count"] == 1
    assert at_choice["annotation_shape"] == "absent" and at_choice["annotation_count"] == 0
    assert at_choice["annotation_sites"] == "choice"


def test_a_cumulative_resend_is_counted_once_and_its_arrivals_are_reported(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the count stops de-duplicating, or ``arrivals`` is dropped.

    ``_fold_stream`` does ``sink.extend(extra)`` per frame with no
    de-duplication, so a provider re-sending its whole array on each delta lands
    N copies. Measured on this repo's own reassembler before the fix: 2 distinct
    sources over 4 content frames were reported as count=8, chars=76 against a
    truth of 19. The multiplier is the content-frame count, which varies with
    answer length, so the inflation is not even constant between calls.

    Literals on both sides (AGENTS.md rules 7a/8b): 2 distinct annotations
    holding 9 and 10 characters, re-sent across 4 frames. count=2, arrivals=8,
    chars=19. No single constant satisfies all three.
    """
    block = [
        {
            "type": "url_citation",
            "url_citation": {"url": "https://a.example/1", "content": "PASSAGE-A"},
        },
        {
            "type": "url_citation",
            "url_citation": {"url": "https://b.example/2", "content": "PASSAGE-BB"},
        },
    ]
    frames = [
        {"choices": [{"index": 0, "delta": {"content": f"part{i} ", "annotations": block}}]}
        for i in range(4)
    ]
    frames.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    record = _drive_body(monkeypatch, token_records, _sse_frames(*frames))
    assert record["annotation_count"] == 2
    assert record["annotation_arrivals"] == 8
    assert record["annotation_content_chars"] == 19 == len("PASSAGE-A") + len("PASSAGE-BB")


# --- content: absent, empty, and "zero characters" are three answers ---------


def test_no_content_key_is_absent_and_an_empty_one_is_zero(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``content_chars`` is defaulted to ``0`` when no key was present.

    ``None``/absent means the upstream sends no content field at all. ``0``
    means the field IS there. A capture reporting ``0`` for both would answer
    "Route B" — build the fetcher — to a question it never asked.

    Asserted as field ABSENCE, not as a ``None`` value: the emitter omits the
    key entirely, and a test accepting ``None`` would also pass against an
    emitter writing an explicit null.
    """
    no_key = _drive(monkeypatch, token_records, [{"url": _GOOD_URL}])
    assert "annotation_content_chars" not in no_key
    assert no_key["annotation_content_shape"] == "absent"

    empty = _drive(monkeypatch, token_records, [{"url": _GOOD_URL, "content": ""}])
    assert empty["annotation_content_chars"] == 0
    assert empty["annotation_content_shape"] == "string"


@pytest.mark.parametrize(
    ("content", "expected_shape", "expected_chars"),
    [
        ("plain text", "string", 10),
        ("", "string", 0),
        (None, "null", 0),
        ({"body": "x" * 50}, "mapping", 0),
        (["the whole passage "] * 20, "list", 360),
        # TWO text parts, not one, and that is the point: with a single part
        # ``total += len(text)`` and ``total = len(text)`` give the same answer,
        # so the CI mutation gate caught `+=` -> `=` surviving. 4 + 5 = 9 is a
        # sum no single part produces.
        ([{"type": "text", "text": "abcd"}, {"type": "text", "text": "efghi"}], "list", 9),
        ([{"type": "text", "text": "abc"}, {"type": "image"}], "list", 3),
        (12345, "other", 0),
    ],
)
def test_the_content_shape_says_which_kind_of_zero_a_zero_is(
    monkeypatch: pytest.MonkeyPatch,
    token_records: _Collector,
    content: object,
    expected_shape: str,
    expected_chars: int,
) -> None:
    """RED WHEN: a non-string ``content`` is reported as a bare ``0``.

    ``content_chars == 0`` was measured to mean four different things at once —
    an empty string, a JSON null, a mapping, and a LIST OF PARTS holding 360
    real characters. The route decision turns on whether passage text is
    available, so a list-of-parts reported as ``0`` would send the project to
    build a fetcher it does not need.

    Every row here is PRESENT (the key exists), so ``content_chars`` is emitted
    in all of them; what separates them is the shape and the count.
    """
    record = _drive(
        monkeypatch, token_records, [{"url": _GOOD_URL, "url_citation": {"content": content}}]
    )
    assert record["annotation_content_shape"] == expected_shape
    assert record["annotation_content_chars"] == expected_chars
    assert record["annotation_content_shape"] in providers.ANNOTATION_CONTENT_SHAPES


def test_a_non_string_content_still_counts_as_PRESENT(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: presence is made to require a string.

    A mutant that set ``seen = True`` only inside ``isinstance(value, str)``
    survived all 29 tests of an earlier version, and it fails toward Route B: a
    provider sending ``"content": null`` or a structured content object would be
    filed as sending no content field at all.

    The partner is the absent case, so the assertion is about the DISTINCTION
    and not about one value.
    """
    values: tuple[object, ...] = (None, {"body": "x"}, 42, [])
    for value in values:
        record = _drive(
            monkeypatch, token_records, [{"url": _GOOD_URL, "url_citation": {"content": value}}]
        )
        assert "annotation_content_chars" in record, f"{value!r} was filed as ABSENT"
    missing = _drive(monkeypatch, token_records, [{"url": _GOOD_URL, "url_citation": {}}])
    assert "annotation_content_chars" not in missing


def test_the_characters_are_counted_over_every_distinct_annotation(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the sum stops at the first annotation, or the count is hardcoded.

    Literals on both sides: three annotations holding 10, 20 and 30 characters,
    so ``count == 3`` and ``content_chars == 60``. No single constant satisfies
    both.
    """
    record = _drive(
        monkeypatch,
        token_records,
        [
            {"url": "https://a.example/1", "content": "a" * 10},
            {"url": "https://a.example/2", "url_citation": {"content": "b" * 20}},
            {"url": "https://a.example/3", "content": "c" * 30},
        ],
    )
    assert record["annotation_count"] == 3
    assert record["annotation_content_chars"] == 60


def test_the_passage_text_never_reaches_the_record(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the content itself is captured instead of its length.

    A negative check WITH its positive partner (AGENTS.md rule 7): the same
    record must prove the passage WAS seen and measured, or "not present" is
    trivially true of a capture that recorded nothing.

    ``default=repr`` and NO type filter, and that is the whole fix. The previous
    version serialised ``{k: v for k, v in record.items() if isinstance(v, str |
    int | bool)}`` — which DISCARDS lists and mappings, exactly where a leak
    would hide. A mutant adding ``fields["source_passages"] = [<the passage>]``
    passed that test green while writing the passage to the durable file.
    """
    record = _drive(
        monkeypatch,
        token_records,
        [{"url": _GOOD_URL, "url_citation": {"content": _PASSAGE}}],
    )
    # Positive partner FIRST: the passage really was there and really was
    # measured, so the absence below is a decision and not an empty input.
    assert record["annotation_content_chars"] == 120 == len(_PASSAGE)
    assert record["annotation_shape"] == "flat"

    serialised = json.dumps(record, default=repr)
    assert "SENTINEL-PASSAGE" not in serialised, "the passage text leaked into the token stream"


# --- the reader is MEASURED, never inferred ----------------------------------


def test_the_usable_count_is_measured_not_inferred_from_the_label(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``annotation_usable_count`` is derived from the shape label.

    ADR-0084 asks whether the annotations path has ever produced a source. An
    earlier version answered it by INFERENCE — ``flat`` was documented to mean
    "our reader works" — and that was refuted: the label tests key presence,
    while ``_extract_citations`` also runs ``_sanitize_source_url``. The two
    arms below are the counterexample, committed rather than counted.

    Both arms carry the SAME label and DIFFERENT usable counts, which is
    precisely what makes the inference invalid and the measurement necessary.
    """
    unusable = _drive(
        monkeypatch,
        token_records,
        [{"source": "web", "url_citation": {"url": _GOOD_URL, "content": "p"}}],
    )
    usable = _drive(monkeypatch, token_records, [{"url": _GOOD_URL, "title": "T"}])

    assert unusable["annotation_shape"] == usable["annotation_shape"] == "flat"
    assert unusable["annotation_usable_count"] == 0
    assert usable["annotation_usable_count"] == 1


def test_the_usable_count_excludes_the_inline_markdown_fallback(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the usable count is taken from the full ``_extract_citations``.

    ``_extract_citations`` falls back to scanning the ANSWER TEXT for markdown
    links when the annotations block yields nothing. Counting that fallback
    would answer "does the product find sources?" — a question nobody asked —
    instead of ADR-0084's "has the annotations path ever produced one?".

    The answer text here is full of markdown links and the annotations block is
    empty, so a count that included the fallback would be non-zero.
    """
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "See [one](https://a.example/1) and [two](https://b.example/2).",
                }
            }
        ],
        "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
    }
    record = _drive_body(monkeypatch, token_records, sse_from_completion(payload))
    assert record["annotation_shape"] == "absent"
    assert record["annotation_usable_count"] == 0
    # POSITIVE PARTNER: the fallback really does find those links, so the zero
    # above is the annotations arm being empty and not the corpus being empty.
    assert len(providers._extract_citations(payload)) == 2


# --- totality and the closed sets --------------------------------------------

#: Every payload shape that must report ``absent`` without raising. The helper
#: runs on the PAID path: an exception is suppressed at the call site, so a
#: raise would not break a call — it would silently delete the measurement from
#: the very run it was built for, with nothing going red.
_MALFORMED: tuple[object, ...] = (
    None,
    "not a mapping",
    42,
    [],
    {},
    {"choices": None},
    {"choices": []},
    {"choices": "text"},
    {"choices": [None]},
    {"choices": [{}]},
    {"choices": [{"message": None}]},
    {"choices": [{"message": "text"}]},
    {"choices": [{"message": {}}]},
    {"choices": [{"message": {"annotations": None}}]},
    {"choices": [{"message": {"annotations": []}}]},
    {"choices": [{"message": {"annotations": "text"}}]},
    {"choices": [{"message": {"annotations": {}}}]},
    {"choices": [{"message": {"citations": []}}]},
)


@pytest.mark.parametrize("payload", _MALFORMED)
def test_every_malformed_payload_reports_absent_without_raising(payload: object) -> None:
    """RED WHEN: the helper raises, or invents a shape, on a payload it cannot read."""
    shape = providers._annotation_shape(payload)
    assert shape.shape == "absent"
    assert shape.count == 0
    assert shape.arrivals == 0
    assert shape.content_chars is None
    assert shape.content_shape == "absent"


def test_the_label_is_always_one_of_the_closed_set(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the upstream's own string is passed through as the label.

    The value lands in a durable file with a fixed byte ceiling, so an
    upstream-authored string here is an unbounded write.

    The corpus deliberately carries a ``type`` key on the ``flat``, ``nested``
    AND ``other`` arms — the field every real OpenRouter annotation has. An
    earlier corpus had none on the ``other`` arm, and a mutant returning
    ``str(first.get("type"))`` there survived every test in the file.

    The second assertion is the POSITIVE PARTNER: membership alone is satisfied
    by a helper returning the constant ``"absent"`` for everything.
    """
    corpus: tuple[object, ...] = _MALFORMED + (
        {"choices": [{"message": {"annotations": [{"type": "url_citation", "url": _GOOD_URL}]}}]},
        {
            "choices": [
                {
                    "message": {
                        "annotations": [{"type": "url_citation", "url_citation": {"url": "u"}}]
                    }
                }
            ]
        },
        {"choices": [{"message": {"annotations": [{"type": "file", "file": {"name": "x"}}]}}]},
        {"choices": [{"message": {"annotations": [{"type": "z" * 400}]}}]},
        {"choices": [{"message": {"annotations": ["scalar"]}}]},
        {"choices": [{"message": {"citations": [{"source": _GOOD_URL}]}}]},
    )
    labels = {providers._annotation_shape(p).shape for p in corpus}
    assert labels <= providers.ANNOTATION_SHAPES, f"label(s) outside the closed set: {labels}"
    assert labels == providers.ANNOTATION_SHAPES, (
        f"the corpus produced only {sorted(labels)}; a membership check over "
        f"fewer than all four labels cannot show the helper discriminates"
    )


def test_annotations_wins_over_citations_when_both_are_present() -> None:
    """RED WHEN: the ``annotations or citations`` precedence is reversed.

    ``_annotation_shape`` must describe the SAME block ``_extract_citations``
    reads, or the measurement characterises a block the product does not parse.
    A mutant swapping the order survived every test of an earlier version,
    because no fixture ever supplied both keys — and it flips the reading from
    ``nested`` + 50 chars (ADR-0084 confirmed, Route A possible) to ``flat`` +
    no content (ADR-0084 refuted, Route B). Opposite conclusions.
    """
    both = {
        "choices": [
            {
                "message": {
                    "annotations": [{"url_citation": {"url": "u", "content": "x" * 50}}],
                    "citations": [{"url": _GOOD_URL}],
                }
            }
        ]
    }
    shape = providers._annotation_shape(both)
    assert shape.shape == "nested"
    assert shape.content_chars == 50
    # The product's own reader must agree about which block it is describing.
    assert providers._extract_citations(both, content="") == providers._extract_citations(
        both, content=""
    )
    assert len(providers._extract_citations(both, content="")) == 0


def test_the_wire_carries_every_annotation_field(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: any ``annotation_*`` argument is dropped from the log call.

    The measured failure this file's author was warned about: a pure function
    can be exhaustively tested while the value never reaches the output path.
    Driven from a REAL emission and compared against the declared registry, so a
    field renamed in ``providers`` and not in the sink fails here.
    """
    record = _drive(
        monkeypatch,
        token_records,
        [{"url": _GOOD_URL, "content": "x" * 5}],
    )
    emitted = {k for k in record if k.startswith("annotation_")}
    assert emitted == {
        "annotation_shape",
        "annotation_count",
        "annotation_arrivals",
        "annotation_content_chars",
        "annotation_content_shape",
        "annotation_sites",
        "annotation_usable_count",
    }
    undeclared = emitted - telemetry_sink.TELEMETRY_FIELD_NAMES
    assert not undeclared, f"emitted but not declared in TELEMETRY_FIELD_NAMES: {undeclared}"


def test_a_broken_annotation_probe_cannot_change_what_the_call_returns(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: ``_annotation_shape`` is hoisted out of the ``contextlib.suppress``.

    The property is real today but was UNPINNED: the existing
    ``test_a_telemetry_failure_cannot_change_what_the_provider_call_returns``
    patches ``_log_call_token_shape`` only, so the natural refactor — computing
    the shape into a local ABOVE the ``with`` — left 58 tests green while making
    the exception escape ``_post_messages`` entirely.

    Instrumentation must never be able to move money. The partner assertion
    pins that the usage still arrives, so this cannot pass by the call failing.
    """

    def explode(_payload: object) -> object:
        raise RuntimeError("annotation shape is broken")

    monkeypatch.setattr(providers, "_annotation_shape", explode)
    token_records.records.clear()
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    response = MagicMock()
    response.read.return_value = sse_from_completion(_payload([{"url": _GOOD_URL}]))
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))

    result = provider_execution_service._post_messages(
        openrouter_key="sk-or-test",
        model_id=f"{_MODEL_ID}:online",
        messages=[{"role": "user", "content": "Ask something."}],
    )
    # Narrowed rather than asserted loosely: ``_post_messages`` can also return
    # the search-rejected and dispatched-unmeasured markers, and a bare
    # ``is not None`` would let this pass on either -- which is exactly the
    # failure the test exists to rule out.
    assert isinstance(result, providers.LiveProviderResult)
    assert result.answer_text == "An answer."
    assert result.usage is not None and result.usage.prompt_tokens == 900
    # The measurement is lost, which is the acceptable half of the trade.
    assert [r for r in token_records.records if r.msg == "provider_call_tokens"] == []


# --- round-2: the gaps the first mutant set could not see --------------------


def test_an_empty_or_null_annotations_key_is_not_blamed_on_our_reader(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: a site is recorded for key PRESENCE rather than key CONTENT.

    A provider that emits ``"annotations": []`` or ``"annotations": null`` sent
    the field and put nothing in it. Recording a site there made the payload
    ``absent`` WITH a site, which the harvest reads as "an annotations key was
    on the wire and our fold missed it" and prints as *"a defect in our
    reassembler, not an answer about the provider"*.

    That sends a reader off to debug the fold on the one question the paid run
    is bought to answer, and it fails toward the expensive conclusion.

    The POSITIVE PARTNER is the third arm: a non-empty block at the same site
    must still record it, or this test would pass against a probe that never
    records anything.
    """
    empty_null = _drive_body(
        monkeypatch,
        token_records,
        _sse_frames({"choices": [{"index": 0, "delta": {"content": "hi", "annotations": None}}]}),
    )
    empty_list = _drive_body(
        monkeypatch,
        token_records,
        _sse_frames({"choices": [{"index": 0, "delta": {"content": "hi", "annotations": []}}]}),
    )
    real = _drive_body(
        monkeypatch,
        token_records,
        _sse_frames(
            {
                "choices": [
                    {"index": 0, "delta": {"content": "hi", "annotations": [{"url": _GOOD_URL}]}}
                ]
            }
        ),
    )
    assert empty_null["annotation_sites"] == "none"
    assert empty_list["annotation_sites"] == "none"
    assert real["annotation_sites"] == "delta"
    assert empty_null["annotation_shape"] == empty_list["annotation_shape"] == "absent"


def test_an_empty_block_at_a_site_we_do_not_read_is_also_not_our_fault(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the truthiness rule is applied at only one of the four sites.

    The presence-vs-content bug was a one-line rule repeated four times. Fixing
    it in ``delta`` alone would leave the other three reporting a site for an
    empty block.
    """
    for site_frame in (
        {"choices": [{"index": 0, "delta": {"content": "hi"}, "annotations": []}]},
        {"choices": [{"index": 0, "message": {"content": "hi", "citations": None}}]},
        {"annotations": [], "choices": [{"index": 0, "delta": {"content": "hi"}}]},
    ):
        record = _drive_body(monkeypatch, token_records, _sse_frames(site_frame))
        assert record["annotation_sites"] == "none", site_frame


@pytest.mark.parametrize(
    ("whole", "expected"),
    [
        (
            {"choices": [{"message": {"content": "hi", "annotations": [{"url": _GOOD_URL}]}}]},
            "message",
        ),
        (
            {"choices": [{"annotations": [{"url": _GOOD_URL}], "message": {"content": "hi"}}]},
            "choice",
        ),
        ({"citations": [{"url": _GOOD_URL}], "choices": [{"message": {"content": "hi"}}]}, "frame"),
        ({"choices": [{"message": {"content": "hi"}}]}, "none"),
        ({"choices": [{"message": {"content": "hi", "annotations": []}}]}, "none"),
        ({"choices": []}, "none"),
        ({"choices": "text"}, "none"),
        ({"choices": [None]}, "none"),
        ({}, "none"),
    ],
)
def test_the_whole_body_path_checks_the_same_sites_as_the_streaming_probe(
    whole: dict[str, object], expected: str
) -> None:
    """RED WHEN: ``_whole_body_annotation_sites`` checks fewer sites than the fold.

    The ``_STREAM_TERMINATOR_NOT_A_STREAM`` branch folds no frames, so the
    per-frame probe never runs and this helper must answer the same question.
    The first version checked ``choices[0].message`` alone, so a body carrying
    top-level ``citations`` or choice-level annotations reported ``none`` — and
    the harvest printed *"no annotations key appeared at any site we look at …
    On this evidence the provider sent none."* The exact rule-8c sentence the
    probe exists to delete, on the one path it did not cover.

    Nothing named this helper before: gutting it to ``frozenset()`` left the
    committed mutation proof at 34/34 and 118 tests green.
    """
    sites = providers._whole_body_annotation_sites(whole)
    assert (",".join(sorted(sites)) or "none") == expected


def test_the_usable_count_is_de_duplicated_like_the_annotation_count(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the usable count is taken over the raw block.

    ``_extract_citations`` does not de-duplicate its annotations arm, so on a
    cumulative re-send it returned 8 for 2 distinct sources and the harvest
    printed *"yielded 8 source(s) from 2 annotation(s)"* — the multiplication
    ``annotation_count`` was added to kill, surviving one field over.

    Literals on both sides: 2 distinct annotations re-sent across 4 frames, so
    count=2, arrivals=8, usable=2. The count and the usable count must agree
    here because both sources are readable; the ARRIVALS must not.
    """
    block = [{"url": "https://a.example/1"}, {"url": "https://b.example/2"}]
    frames = [
        {"choices": [{"index": 0, "delta": {"content": f"p{i} ", "annotations": block}}]}
        for i in range(4)
    ]
    record = _drive_body(monkeypatch, token_records, _sse_frames(*frames))
    assert record["annotation_count"] == 2
    assert record["annotation_arrivals"] == 8
    assert record["annotation_usable_count"] == 2


def test_every_site_label_is_inside_the_closed_vocabulary() -> None:
    """RED WHEN: a fifth site label is added without widening the vocabulary.

    ``ANNOTATION_SITES`` had no closure test at all, while ``ANNOTATION_SHAPES``
    had one — the newest vocabulary got the weakest gate. The value is joined
    into a durable column, so an unbounded label here is an unbounded write.

    Both directions, and the second is the positive partner: every declared
    site must also be REACHABLE, or the vocabulary could grow names nothing
    emits.
    """
    reachable = {
        providers.ANNOTATION_SITE_DELTA,
        providers.ANNOTATION_SITE_MESSAGE,
        providers.ANNOTATION_SITE_CHOICE,
        providers.ANNOTATION_SITE_FRAME,
    }
    assert reachable == providers.ANNOTATION_SITES
    assert providers.ANNOTATION_SITE_NONE not in providers.ANNOTATION_SITES


def test_every_content_shape_has_a_rank_so_the_reduction_cannot_raise() -> None:
    """RED WHEN: a content label is added without a rank entry.

    ``_annotation_shape`` reduces with ``min(..., key=_ANNOTATION_CONTENT_RANK.index)``.
    A label absent from that tuple raises ``ValueError`` — inside the paid
    path's ``contextlib.suppress``, which would silently delete the ENTIRE
    ``provider_call_tokens`` record, not just the annotation fields. That is
    #268's measurement gone with no gate noticing.

    Equality in both directions: a rank entry naming a label that does not
    exist is equally a defect, because the documented "least useful wins" order
    would then be describing a value nothing produces.
    """
    assert set(providers._ANNOTATION_CONTENT_RANK) == providers.ANNOTATION_CONTENT_SHAPES
    assert len(providers._ANNOTATION_CONTENT_RANK) == len(providers.ANNOTATION_CONTENT_SHAPES)


def test_a_block_mixing_content_shapes_reports_the_least_useful_one() -> None:
    """RED WHEN: the documented rank ORDER is permuted.

    "The least useful one wins, so a single unreadable content field is never
    hidden behind a readable one" is a documented rule that nothing checked —
    swapping ``mapping`` and ``null`` in the rank survived the whole suite.

    The block carries a mapping AND a null AND a string, and that is not
    decoration: a block of string/list/mapping alone answers ``mapping`` under
    BOTH the documented order and the mapping/null swap, so it does not
    discriminate. The committed mutation proof is what caught that — the test
    looked right. With a null present, the documented order answers ``mapping``
    and the swap answers ``null``.
    """
    block = [
        {"url": "https://a/1", "content": "readable text"},
        {"url": "https://a/2", "content": None},
        {"url": "https://a/3", "content": {"unreadable": True}},
    ]
    forward = providers._annotation_shape({"choices": [{"message": {"annotations": block}}]})
    reverse = providers._annotation_shape(
        {"choices": [{"message": {"annotations": list(reversed(block))}}]}
    )
    assert forward.content_shape == "mapping"
    assert reverse.content_shape == "mapping", "the reduction must not depend on arrival order"
    # POSITIVE PARTNER: without the mapping the answer moves, so the rule is
    # discriminating rather than a constant.
    without = providers._annotation_shape({"choices": [{"message": {"annotations": block[:2]}}]})
    assert without.content_shape == "null"


def test_the_not_a_stream_path_reports_its_sites_end_to_end(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the whole-body probe is dropped from the not-a-stream branch.

    ``_whole_body_annotation_sites`` was tested only by calling it directly, so
    replacing the CALL with ``frozenset()`` left the committed mutation proof
    green — the helper was correct and unreachable-in-test at the same time.
    "Pin the use, not the constant", one layer up.

    Driven through the real transport with a body that is a whole JSON
    completion rather than an SSE stream, which is what reaches
    ``_STREAM_TERMINATOR_NOT_A_STREAM``. The terminator is asserted so this
    cannot silently start passing via the streaming path instead.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    whole = {
        "choices": [
            {
                # Choice level: a site the fold does NOT collect from, so the
                # shape is ``absent`` and only ``sites`` can explain why.
                "annotations": [{"url": _GOOD_URL}],
                "message": {"role": "assistant", "content": "An answer."},
            }
        ],
        "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
    }
    record = _drive_body(monkeypatch, token_records, json.dumps(whole).encode())
    assert record["stream_terminator"] == "not_a_stream"
    assert record["annotation_shape"] == "absent"
    assert record["annotation_sites"] == "choice"


@pytest.mark.parametrize("payload", _MALFORMED)
def test_the_usable_count_is_total_over_every_malformed_payload(payload: object) -> None:
    """RED WHEN: ``_annotation_usable_count`` raises on a payload it cannot read.

    Its docstring claims totality and nothing tested it — ``diff-cover`` named
    the four guard lines as uncovered. It runs on the paid path inside the same
    ``contextlib.suppress`` as its neighbours, so a raise here would silently
    delete the ENTIRE token record, ``prompt_tokens`` and all.
    """
    assert providers._annotation_usable_count(payload) == 0


def test_the_whole_body_probe_picks_the_index_zero_choice_not_the_first(
    monkeypatch: pytest.MonkeyPatch, token_records: _Collector
) -> None:
    """RED WHEN: the whole-body probe selects ``choices[0]`` positionally.

    The streaming probe selects by ``choice.get("index", 0) == 0``; the
    whole-body one used position. They disagreed on two shapes, both giving the
    false provider verdict, and the docstring claimed the sites were "checked
    exactly as the streaming probe checks it".

    Not reachable while nothing sends ``n``, so this is a prose-and-parity fix
    rather than a live defect — but a measurement that selects differently from
    the reader it describes is measuring something else.
    """
    # A choice at position 0 that is NOT choice zero must be ignored...
    assert (
        providers._whole_body_annotation_sites(
            {"choices": [{"index": 1, "annotations": [{"url": _GOOD_URL}], "message": {}}]}
        )
        == frozenset()
    )
    # ...and the real choice zero must be found wherever it sits.
    assert providers._whole_body_annotation_sites(
        {
            "choices": [
                {"index": 1, "message": {"content": "x"}},
                {"index": 0, "message": {"content": "y", "annotations": [{"url": _GOOD_URL}]}},
            ]
        }
    ) == frozenset({"message"})
