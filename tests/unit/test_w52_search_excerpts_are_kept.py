"""W52 (ADR-0146, CHG-028): a search excerpt is kept with its source.

The design: ``SourceReference`` gains ``excerpt: str = ""``. The two search
paths fill it -- OpenRouter's annotation ``content`` (read from the SAME block
its URL came from) and Tavily's result ``content``. Anything that is not a
non-empty string is no excerpt. The text is cleaned (control characters
removed, whitespace collapsed) and THEN cut to
``settings.quorum_source_fetch_max_text_chars``.

Failure modes covered here (``docs/analysis/2026-10-05-w52-search-excerpts-
failure-modes.md``): 3 (unbounded), 5 (wrong page / orphaned), 6 (flat shape,
non-string content), 7 (Tavily shape), 8 (simulated and inline paths).
Rows 1, 2, 9 live in ``tests/integration/test_w52_excerpt_is_never_served_
logged_or_stored.py``; row 9's judge half in
``tests/unit/test_w52_excerpt_never_reaches_the_judge.py``.

Every read of the field goes through :func:`_excerpt`, which uses ``getattr``
so a model WITHOUT the field fails as an assertion, not as a collection error.
Every boundary is pinned with LITERALS on both sides, and the setting is set
in the test, never read back as the expected value (AGENTS.md rules 7a, 8b).
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from tests.provider_wire import sse_from_completion

from product_app import config
from product_app.config import settings
from product_app.model_slots import ModelSlot, validate_model_slots
from product_app.providers import (
    ProviderPath,
    SourceReference,
    _extract_citations,
    _parse_tavily_results,
    provider_execution_service,
    provider_stub_service,
)


class _Missing:
    """What :func:`_excerpt` returns when the model has no ``excerpt`` at all:
    not a ``str``, so no string assertion can pass on it, and its repr says
    WHY in the failure message."""

    def __repr__(self) -> str:
        return "<SourceReference has no `excerpt` attribute>"


_NO_FIELD = _Missing()

#: A sanitiser-approved address (``_sanitize_source_url`` keeps it).
_URL_A = "https://a.example/page-a"
_URL_B = "https://b.example/page-b"

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def _excerpt(source: object) -> object:
    return getattr(source, "excerpt", _NO_FIELD)


def _openrouter(annotations: list[Any], *, content: str = "An answer.") -> dict[str, Any]:
    """A non-streamed completion carrying ``annotations``."""
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content, "annotations": annotations}}
        ]
    }


def _nested(url: str, content: object, *, title: str = "Nested title") -> dict[str, Any]:
    return {
        "type": "url_citation",
        "url_citation": {"url": url, "title": title, "content": content},
    }


@pytest.fixture(autouse=True)
def _page_text_limit_is_4000(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the limit IN the test so a changed default cannot move the
    expected values; every assertion below uses literals, never the setting."""
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 4000)


# ---------------------------------------------------------------------------
# The model.
# ---------------------------------------------------------------------------


def test_source_reference_has_an_optional_excerpt_defaulting_to_empty() -> None:
    # RED IF: SourceReference has no `excerpt` field, it is required, its
    # default is anything but "", or it is not a str.
    assert "excerpt" in SourceReference.model_fields, sorted(SourceReference.model_fields)
    field = SourceReference.model_fields["excerpt"]
    assert field.annotation is str, field.annotation
    assert field.is_required() is False
    source = SourceReference(title="t", url=_URL_A, provider=ProviderPath.OPENROUTER_SEARCH)
    assert _excerpt(source) == ""
    # Positive partner: the field really holds a value when one is given.
    given = SourceReference(
        title="t", url=_URL_A, provider=ProviderPath.OPENROUTER_SEARCH, excerpt="kept text"
    )
    assert _excerpt(given) == "kept text"


# ---------------------------------------------------------------------------
# OpenRouter annotations (failure modes 5, 6).
# ---------------------------------------------------------------------------


def test_a_nested_annotation_content_becomes_the_sources_excerpt() -> None:
    # RED IF: the nested `url_citation.content` is not carried onto the source.
    (source,) = _extract_citations(_openrouter([_nested(_URL_A, "Passage about page A.")]))
    assert source.url == _URL_A
    assert _excerpt(source) == "Passage about page A."


def test_a_flat_annotation_content_becomes_the_sources_excerpt() -> None:
    # RED IF: the flat shape (`url` and `content` at the top level) is not read.
    (source,) = _extract_citations(
        _openrouter([{"url": _URL_A, "title": "Flat", "content": "Flat passage."}])
    )
    assert source.url == _URL_A
    assert _excerpt(source) == "Flat passage."


def test_content_is_read_from_the_same_block_its_url_came_from() -> None:
    """Failure mode 6: "an excerpt from the wrong key".

    RED IF: content is read from a block other than the one that supplied the
    URL -- e.g. nested-first regardless of where the URL was, or top-level
    first regardless."""
    nested_url_wins = {
        "content": "TOP-LEVEL TEXT",
        "url_citation": {"url": _URL_A, "title": "n", "content": "NESTED TEXT"},
    }
    top_url_wins = {
        "url": _URL_B,
        "content": "TOP-LEVEL TEXT",
        "url_citation": {"title": "n", "content": "NESTED TEXT"},
    }
    top_url_no_top_content = {
        "url": "https://c.example/page-c",
        "url_citation": {"title": "n", "content": "NESTED ONLY"},
    }
    sources = _extract_citations(
        _openrouter([nested_url_wins, top_url_wins, top_url_no_top_content])
    )
    assert [(s.url, _excerpt(s)) for s in sources] == [
        (_URL_A, "NESTED TEXT"),
        (_URL_B, "TOP-LEVEL TEXT"),
        # The URL came from the top level, which carries no content: no
        # excerpt, never the nested block's text.
        ("https://c.example/page-c", ""),
    ]


@pytest.mark.parametrize(
    "content",
    [
        None,
        0,
        42,
        True,
        {"text": "a mapping"},
        ["a list of strings"],
        [{"type": "text", "text": "a list of parts"}],
        "",
    ],
    ids=["null", "zero", "int", "bool", "mapping", "list-of-str", "list-of-parts", "empty"],
)
def test_content_that_is_not_a_non_empty_string_is_no_excerpt(content: object) -> None:
    # RED IF: a non-string or empty content becomes anything but "" (or the
    # source is lost / the parser raises). The positive partner in the same
    # payload proves the excerpt path is live, so "" is a decision.
    sources = _extract_citations(
        _openrouter([_nested(_URL_A, content), _nested(_URL_B, "real text")])
    )
    assert [(s.url, _excerpt(s)) for s in sources] == [(_URL_A, ""), (_URL_B, "real text")]


def test_an_annotation_without_a_content_key_has_an_empty_excerpt() -> None:
    # RED IF: the field is missing, or a missing key gives anything but "".
    sources = _extract_citations(
        _openrouter(
            [
                {"type": "url_citation", "url_citation": {"url": _URL_A, "title": "t"}},
                _nested(_URL_B, "present"),
            ]
        )
    )
    assert [_excerpt(s) for s in sources] == ["", "present"]


def test_a_dropped_url_drops_its_excerpt() -> None:
    """Failure mode 5: an excerpt on a source the sanitiser drops is orphaned.

    RED IF: the dropped annotation's text lands on another source, or the kept
    source loses its own excerpt."""
    sources = _extract_citations(
        _openrouter(
            [
                _nested("http://169.254.169.254/latest/meta-data", "METADATA TEXT"),
                _nested("javascript:alert(1)", "SCRIPT TEXT"),
                _nested(_URL_A, "KEPT TEXT"),
            ]
        )
    )
    assert [(s.url, _excerpt(s)) for s in sources] == [(_URL_A, "KEPT TEXT")]


def test_two_annotations_for_one_url_each_keep_their_own_excerpt() -> None:
    """Failure mode 5: "an excerpt attached to the wrong page". The annotations
    arm keeps duplicates; each source keeps the text of the annotation it came
    from, paired with that annotation's title.

    RED IF: excerpts are swapped, merged, or the second overwrites the first."""
    sources = _extract_citations(
        _openrouter(
            [
                _nested(_URL_A, "FIRST PASSAGE", title="First"),
                _nested(_URL_A, "SECOND PASSAGE", title="Second"),
            ]
        )
    )
    assert [(s.title, s.url, _excerpt(s)) for s in sources] == [
        ("First", _URL_A, "FIRST PASSAGE"),
        ("Second", _URL_A, "SECOND PASSAGE"),
    ]


def test_the_inline_markdown_fallback_has_no_excerpt() -> None:
    """Failure mode 8: the inline-Markdown path has no passage to keep.

    RED IF: the field is missing, or the anchor / answer text is put in it."""
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "See [Anchor text](https://md.example/p).",
                }
            }
        ]
    }
    (source,) = _extract_citations(payload)
    assert source.url == "https://md.example/p"  # positive partner: the path ran
    assert _excerpt(source) == ""


# ---------------------------------------------------------------------------
# Cleaning and the bound (failure mode 3).
# ---------------------------------------------------------------------------


def test_the_excerpt_is_cleaned_control_characters_out_whitespace_collapsed() -> None:
    """Every control and whitespace character sits between spaces, so
    "remove then collapse" and "replace then collapse" agree on the result
    (the ADR does not say which -- see the W52 test report).

    RED IF: control characters survive, whitespace is not collapsed, or the
    ends are not trimmed."""
    raw = (
        "  Alpha \t beta \n\n gamma \r\n delta \x00 epsilon \x07 zeta \x1b eta "
        "\x7f theta \x85 iota   kappa \x0b\x0c lambda  "
    )
    (source,) = _extract_citations(_openrouter([_nested(_URL_A, raw)]))
    assert _excerpt(source) == "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"


def test_no_control_character_and_no_whitespace_run_survives_anywhere() -> None:
    """Property form over every C0 and C1 control character, embedded
    mid-word where the two cleaning orders disagree. Only properties are
    pinned here, not the exact join.

    RED IF: any Unicode `Cc` character survives, or any run of two whitespace
    characters, or leading/trailing whitespace."""
    controls = [chr(c) for c in range(0x00, 0x20)] + [chr(c) for c in range(0x7F, 0xA0)]
    raw = "start " + "".join(f"w{i}{ch}x" for i, ch in enumerate(controls)) + " end"
    (source,) = _extract_citations(_openrouter([_nested(_URL_A, raw)]))
    excerpt = _excerpt(source)
    assert isinstance(excerpt, str), excerpt
    # Positive partner: the visible text really is there.
    assert excerpt.startswith("start ") and excerpt.endswith(" end"), excerpt
    assert "w0" in excerpt and "w64" in excerpt, excerpt
    survivors = sorted({hex(ord(ch)) for ch in excerpt if unicodedata.category(ch) == "Cc"})
    assert survivors == [], f"control characters survived: {survivors}"
    assert "  " not in excerpt
    assert excerpt == excerpt.strip()


def test_content_that_cleans_to_nothing_is_no_excerpt() -> None:
    # RED IF: an all-whitespace/control content leaves a non-empty excerpt.
    sources = _extract_citations(
        _openrouter([_nested(_URL_A, " \x00 \n\t \x7f "), _nested(_URL_B, "real")])
    )
    assert [_excerpt(s) for s in sources] == ["", "real"]


@pytest.mark.parametrize(
    ("raw_len", "kept_len"),
    [(3999, 3999), (4000, 4000), (4001, 4000)],
)
def test_the_excerpt_is_cut_at_4000_characters(raw_len: int, kept_len: int) -> None:
    """The boundary with literals on both sides (AGENTS.md rule 8b). The text
    starts with A and ends with Z, so a cut from the wrong end, or no cut,
    shows.

    RED IF: no cut, a cut at another length, or a cut that keeps the END."""
    raw = "A" + "x" * (raw_len - 2) + "Z"
    (source,) = _extract_citations(_openrouter([_nested(_URL_A, raw)]))
    excerpt = _excerpt(source)
    assert isinstance(excerpt, str), excerpt
    assert len(excerpt) == kept_len
    assert excerpt == raw[:kept_len]
    assert excerpt.startswith("A")
    assert excerpt.endswith("Z") is (raw_len <= 4000)


def test_the_cut_follows_the_setting_not_a_hard_coded_4000(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RED IF: the cut is a literal 4000 (or any constant) instead of
    # `settings.quorum_source_fetch_max_text_chars`.
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 37)
    (source,) = _extract_citations(_openrouter([_nested(_URL_A, "0123456789" * 10)]))
    assert _excerpt(source) == "0123456789012345678901234567890123456"
    assert len("0123456789012345678901234567890123456") == 37


def test_the_text_is_cleaned_before_it_is_cut() -> None:
    """ADR-0146 decision 2 and failure mode 3: cut AFTER collapsing.

    RED IF: the raw text is cut first (it would keep only 1,950 b's)."""
    raw = "a" * 2000 + " " * 50 + "b" * 2000
    (source,) = _extract_citations(_openrouter([_nested(_URL_A, raw)]))
    assert _excerpt(source) == "a" * 2000 + " " + "b" * 1999


def test_a_hundred_kilobyte_passage_is_bounded() -> None:
    # RED IF: an oversized provider passage is kept whole.
    (source,) = _extract_citations(_openrouter([_nested(_URL_A, "y" * 100_000)]))
    assert _excerpt(source) == "y" * 4000


# ---------------------------------------------------------------------------
# The streamed wire: the excerpt survives reassembly.
# ---------------------------------------------------------------------------


def test_the_streamed_call_keeps_the_excerpt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every call streams (ADR-0084). Through the real `_post_messages`.

    RED IF: the streamed reassembly or the live result drops the excerpt."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    payload = _openrouter([_nested(_URL_A, "Streamed  passage\ntext.")])
    payload["usage"] = {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12}
    response = MagicMock()
    response.read.return_value = sse_from_completion(payload)
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("product_app.providers.urlopen", MagicMock(return_value=response))
    result = provider_execution_service._post_messages(
        openrouter_key="sk-or-test",
        model_id="anthropic/claude-haiku-4.5:online",
        messages=[{"role": "user", "content": "Ask something."}],
    )
    sources = getattr(result, "sources", None)
    assert sources is not None, f"no live result: {result!r}"
    assert [(s.url, _excerpt(s)) for s in sources] == [(_URL_A, "Streamed passage text.")]


# ---------------------------------------------------------------------------
# Tavily (failure mode 7).
# ---------------------------------------------------------------------------


def test_a_tavily_result_content_becomes_the_sources_excerpt() -> None:
    # RED IF: Tavily's `content` is not carried onto the source.
    (source,) = _parse_tavily_results(
        {"results": [{"title": "T", "url": _URL_A, "content": "Tavily passage."}]}
    )
    assert source.url == _URL_A
    assert _excerpt(source) == "Tavily passage."


@pytest.mark.parametrize(
    "result_extra",
    [
        {},
        {"content": None},
        {"content": 7},
        {"content": ["x"]},
        {"content": {"t": "x"}},
        {"content": ""},
    ],
    ids=["missing", "null", "int", "list", "mapping", "empty"],
)
def test_a_tavily_result_without_string_content_has_no_excerpt(
    result_extra: dict[str, object],
) -> None:
    # RED IF: a missing or non-string Tavily `content` becomes anything but ""
    # (or crashes). The second result is the positive partner.
    sources = _parse_tavily_results(
        {
            "results": [
                {"title": "T", "url": _URL_A, **result_extra},
                {"title": "U", "url": _URL_B, "content": "present"},
            ]
        }
    )
    assert [(s.url, _excerpt(s)) for s in sources] == [(_URL_A, ""), (_URL_B, "present")]


def test_a_tavily_excerpt_is_cleaned_and_cut_like_an_openrouter_one() -> None:
    # RED IF: the Tavily path skips the cleaning or the 4,000-character cut.
    sources = _parse_tavily_results(
        {
            "results": [
                {"title": "T", "url": _URL_A, "content": "  one \n\n two \x00 three  "},
                {"title": "U", "url": _URL_B, "content": "A" + "x" * 3999 + "Z"},
            ]
        }
    )
    assert _excerpt(sources[0]) == "one two three"
    assert _excerpt(sources[1]) == "A" + "x" * 3999


def test_a_tavily_duplicate_url_keeps_the_first_results_excerpt() -> None:
    """The Tavily parser keeps the first of two results for one URL (its
    title, pinned in test_tavily_search.py). Its excerpt must come from the
    same result.

    RED IF: the kept source carries the duplicate's text, or none."""
    (source,) = _parse_tavily_results(
        {
            "results": [
                {"title": "One", "url": _URL_A, "content": "FIRST"},
                {"title": "Dup", "url": _URL_A, "content": "SECOND"},
            ]
        }
    )
    assert (source.title, _excerpt(source)) == ("One", "FIRST")


def test_a_dropped_tavily_url_drops_its_excerpt() -> None:
    # RED IF: a denylisted result's text lands on another source.
    sources = _parse_tavily_results(
        {
            "results": [
                {"title": "Meta", "url": "http://169.254.169.254/x", "content": "META"},
                {"title": "Good", "url": _URL_A, "content": "GOOD"},
            ]
        }
    )
    assert [(s.url, _excerpt(s)) for s in sources] == [(_URL_A, "GOOD")]


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_the_tavily_request_is_unchanged_and_the_wire_result_keeps_the_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 9: no request changes. The request BYTES are pinned to
    what `24e3099` sends (recorded by this double before W52), and the
    response's content reaches the source through the real JSON path.

    RED IF: the Tavily request body changes in any byte (a new key such as
    `include_raw_content`, a changed key, a changed order), or the wire path
    drops the excerpt."""
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(settings, "tavily_max_results", 3)
    sent: list[bytes] = []

    def fake_urlopen(request: Any, timeout: object = None) -> _FakeResponse:
        sent.append(request.data)
        body = {"results": [{"title": "Real", "url": _URL_A, "content": "Wire passage."}]}
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    sources = provider_stub_service._fallback_sources(
        model_slot=ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini"),
        query_text="compare vector databases",
    )
    # CARDINALITY: one request, byte-identical to the pre-W52 request.
    assert sent == [b'{"query": "compare vector databases", "max_results": 3}']
    assert [(s.url, _excerpt(s)) for s in sources] == [(_URL_A, "Wire passage.")]


# ---------------------------------------------------------------------------
# The simulated path (failure mode 8).
# ---------------------------------------------------------------------------


def test_simulated_sources_carry_an_empty_excerpt(monkeypatch: pytest.MonkeyPatch) -> None:
    # RED IF: the field is missing, or the simulated path invents an excerpt.
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "tavily_api_key", "")
    answers = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="a plain research question",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )
    sources = [s for answer in answers for s in answer.sources]
    assert len(sources) >= 4, sources  # positive partner: there are sources to check
    assert [_excerpt(s) for s in sources] == [""] * len(sources)
