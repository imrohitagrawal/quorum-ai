from typing import cast
from uuid import uuid4

import pytest

from product_app.debate import DebateOutput, debate_stub_service
from product_app.model_slots import validate_model_slots
from product_app.providers import provider_execution_service, provider_stub_service
from product_app.synthesis import SynthesisStatus, synthesis_event_recorder, synthesis_stub_service

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def test_synthesis_stub_returns_required_sections_and_quality_checks() -> None:
    synthesis_event_recorder.clear()
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options with material disagreement",
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options with material disagreement",
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options with material disagreement",
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
    )

    assert result.failed_steps == []
    assert result.missing_steps == []
    assert result.final_synthesis is not None
    synthesis = result.final_synthesis
    assert synthesis.status is SynthesisStatus.COMPLETED
    assert synthesis.consensus
    assert "disagreement" in synthesis.disagreement
    assert "visible source references" in synthesis.source_support
    assert synthesis.uncertainty
    assert "decision support only" in synthesis.recommendation
    # L5d: with the honest heuristic the four ~218-char stub
    # answers each yield 2 material claims → 8 total; 4 cited
    # produces a 0.50 coverage ratio, which is below the 0.80
    # target. Assert the honest ratio rather than the boolean.
    assert synthesis.citation_coverage.material_claim_count >= 4
    assert synthesis.citation_coverage.cited_claim_count == 4
    assert not synthesis.citation_coverage.target_met
    assert not synthesis.quality_checks.citation_coverage_target_met
    # PR-2 Defect 3 fix: with all four stub answers being
    # identical, the consensus strength is "strong", so
    # ``false_consensus_preserved`` is now correctly False.
    # The old substring check on the templated disagreement
    # text was a false positive — see ``docs/SYNTHESIS_AUDIT.md``.
    assert not synthesis.quality_checks.false_consensus_preserved
    assert synthesis.quality_checks.decision_support_framing_present
    event = synthesis_event_recorder.list_events()[0]
    assert event.account_id == account_id
    assert event.query_run_id == query_run_id
    assert event.status is SynthesisStatus.COMPLETED
    assert not event.false_consensus_preserved
    assert not hasattr(event, "query_text")
    assert not hasattr(event, "provider_key")


def test_high_stakes_synthesis_includes_decision_support_notice() -> None:
    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    query_text = "Compare legal contract and financial risk"
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_text,
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_text,
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query_text,
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
    )

    assert result.final_synthesis is not None
    assert result.final_synthesis.quality_checks.high_stakes_warning_required
    assert result.final_synthesis.high_stakes_notice is not None
    assert "not medical, legal, financial, safety, or regulated professional advice" in (
        result.final_synthesis.high_stakes_notice
    )


def test_synthesis_live_path_uses_llm_text_when_key_and_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L4: when a key and the live-execution flag are both set, the
    synthesis orchestrator should call the LLM for each of the five
    sections and use the LLM text in the result.
    """
    from product_app import config
    from product_app.providers import LiveProviderResult

    calls: list[str] = []

    def fake_call(**kwargs: object) -> LiveProviderResult | None:
        calls.append(str(kwargs.get("system_prompt", "")))
        return LiveProviderResult(
            answer_text="Live LLM section text.",
            sources=[],
        )

    monkeypatch.setattr(
        provider_execution_service,
        "call_with_prompt",
        fake_call,
    )
    monkeypatch.setattr(
        config.settings,
        "openrouter_live_execution_enabled",
        True,
        raising=False,
    )

    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
        openrouter_key="sk-or-test-live",
    )

    assert result.final_synthesis is not None
    # All five sections use LLM text (under the cap so the
    # truncation step is a no-op for "Live LLM section text.").
    assert result.final_synthesis.consensus == "Live LLM section text."
    assert result.final_synthesis.disagreement == "Live LLM section text."
    assert result.final_synthesis.source_support == "Live LLM section text."
    assert result.final_synthesis.uncertainty == "Live LLM section text."
    # Recommendation gets the decision-support caveat appended
    # by ``truncate_recommendation`` because the LLM text does
    # not include the verbatim sentence. PR-2 Item 1 + Item 6:
    # the caveat is now always present in the recommendation
    # section, regardless of which path produced the text.
    assert result.final_synthesis.recommendation.startswith("Live LLM section text.")
    assert "decision support only" in result.final_synthesis.recommendation
    # Five section calls total.
    assert len(calls) == 5


def test_synthesis_falls_back_to_template_when_live_execution_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L4: even with a key set, if the operator has explicitly
    disabled live execution, the synthesis orchestrator must fall
    back to the templated text on all five sections.
    """
    from product_app import config

    called = {"count": 0}

    def fake_call(**kwargs: object) -> object:
        called["count"] += 1
        return None

    monkeypatch.setattr(
        provider_execution_service,
        "call_with_prompt",
        fake_call,
    )
    monkeypatch.setattr(
        config.settings,
        "openrouter_live_execution_enabled",
        False,
        raising=False,
    )

    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
    )

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text="Compare source-backed options",
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
        openrouter_key="sk-or-test-live",
    )

    assert result.final_synthesis is not None
    # Templated consensus text mentions "Four models were asked".
    assert "Four models were asked" in result.final_synthesis.consensus
    # The "visible source references" phrase from the templated source_support
    # is what the existing integration test pins.
    assert "visible source references" in result.final_synthesis.source_support
    # No LLM calls were made.
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# Workstream-2: synthesis correctness
# ---------------------------------------------------------------------------


def test_extract_citations_parses_inline_markdown_links() -> None:
    """Workstream-2: when a provider emits sources only as inline
    markdown links inside the message content (no ``annotations``
    block), ``_extract_citations`` must still surface them as
    ``SourceReference`` objects so the synthesis / source-support UI
    can show the citation.
    """
    from product_app.providers import _extract_citations

    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        "Live answer with two inline sources: "
                        "[first reference](https://inline.example/one) "
                        "and [second reference](https://inline.example/two)."
                    ),
                    "annotations": [],
                }
            }
        ]
    }
    refs = _extract_citations(payload)
    urls = [ref.url for ref in refs]
    assert "https://inline.example/one" in urls
    assert "https://inline.example/two" in urls
    # Anchor text becomes the title.
    first = next(ref for ref in refs if ref.url == "https://inline.example/one")
    assert first.title == "first reference"
    # Provider / fallback tagging matches the annotations path.
    assert first.provider == "openrouter_search"
    assert first.is_fallback is False


def test_extract_citations_dedupes_inline_links_overlapping_annotations() -> None:
    """When the same URL appears both in ``annotations`` and as an
    inline markdown link in the content, it must surface exactly once.
    """
    from product_app.providers import _extract_citations

    payload = {
        "choices": [
            {
                "message": {
                    "content": ("Quoting [the docs](https://dup.example/page) for context."),
                    "annotations": [
                        {
                            "title": "the docs",
                            "url": "https://dup.example/page",
                        }
                    ],
                }
            }
        ]
    }
    refs = _extract_citations(payload)
    matching = [ref for ref in refs if ref.url == "https://dup.example/page"]
    assert len(matching) == 1


def test_extract_citations_drops_unsafe_inline_urls() -> None:
    """Inline links with non-http schemes (or loopback hosts) must be
    rejected by the same host denylist the annotations path uses.
    """
    from product_app.providers import _extract_citations

    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        "Bad: [click](javascript:alert(1)). "
                        "Loopback: [meta](http://169.254.169.254/latest)."
                    ),
                    "annotations": [],
                }
            }
        ]
    }
    refs = _extract_citations(payload)
    assert refs == []


def test_extract_citations_returns_empty_when_no_choices() -> None:
    """Defensive contract: a malformed payload still produces an empty
    list rather than raising — this path runs on every live call.
    """
    from product_app.providers import _extract_citations

    assert _extract_citations({}) == []
    assert _extract_citations({"choices": []}) == []


def test_extract_citations_coerces_non_list_annotations_to_empty() -> None:
    """A non-list ``annotations`` value (e.g. a string from a misbehaving
    provider) is silently coerced to ``[]`` rather than short-circuiting
    the function. The inline-link fallback must still run, so a payload
    that has inline markdown links in its content (and a malformed
    annotations value) surfaces the inline links.
    """
    from product_app.providers import _extract_citations

    payload = {
        "choices": [
            {
                "message": {
                    "annotations": "nope",
                    "content": ("Sources: [the docs](https://safe.example/page)."),
                }
            }
        ]
    }
    refs = _extract_citations(payload)
    assert [ref.url for ref in refs] == ["https://safe.example/page"]


def test_extract_citations_skips_inline_fallback_when_annotations_produced_citations() -> None:
    """When the annotations block already produced citations, the
    inline-link fallback is skipped entirely (not just deduped to zero).
    This pins the short-circuit so a future change that re-enables the
    scan-and-dedup path can't silently double the per-call work.
    """
    from product_app.providers import _extract_citations

    payload = {
        "choices": [
            {
                "message": {
                    "annotations": [
                        {"title": "annotated", "url": "https://annotated.example/"},
                    ],
                    "content": ("Inline: [inline-only](https://inline.example/page)."),
                }
            }
        ]
    }
    refs = _extract_citations(payload)
    # Only the annotations URL surfaces; the inline URL is skipped.
    assert [ref.url for ref in refs] == ["https://annotated.example/"]


def test_extract_citations_inline_link_truncates_at_first_paren_in_url() -> None:
    """Pinned behaviour: the inline-link regex captures the URL up to
    the first ``)`` so the markdown-link closing paren matches literally.
    This mirrors most markdown renderers. A Wikipedia-style URL with an
    unbalanced ``)`` will be truncated; if a model emits that, the
    extracted URL is the part before the inner ``)`` and may not
    resolve. The test exists so an accidental regex change (e.g. greedy
    ``\S+`` that captures the markdown closer) is caught.
    """
    from product_app.providers import _extract_citations

    payload = {
        "choices": [
            {
                "message": {
                    "content": (
                        "Quote [Wikipedia entry]"
                        "(https://en.wikipedia.org/wiki/Python_(programming_language))"
                        " here."
                    ),
                    "annotations": [],
                }
            }
        ]
    }
    refs = _extract_citations(payload)
    # The capture stops at the FIRST ')' (the one inside the URL),
    # not at the markdown-link closer.
    assert len(refs) == 1
    assert refs[0].url == "https://en.wikipedia.org/wiki/Python_(programming_language"
    # Title is the anchor text.
    assert refs[0].title == "Wikipedia entry"


def test_extract_citations_accepts_pre_extracted_content() -> None:
    """``_extract_citations`` accepts an optional ``content`` parameter so
    callers that already extracted the message text (i.e.
    ``_post_openrouter``) can pass it in. The inline-link fallback then
    uses the supplied content instead of walking the payload again.
    """
    from product_app.providers import _extract_citations

    payload: dict[str, object] = {
        "choices": [
            {
                "message": {
                    "annotations": [],
                }
            }
        ]
    }
    refs = _extract_citations(
        payload,
        content="See [the spec](https://spec.example/page).",
    )
    assert [ref.url for ref in refs] == ["https://spec.example/page"]


def test_synthesis_section_max_tokens_is_workstream_two_value() -> None:
    """Workstream-2 bumped the per-section token cap from 500 to 800 so
    the model can finish citation-coverage and failed-count sentences
    without truncating mid-sentence. This test pins the new value so
    an accidental revert is caught.
    """
    from product_app.synthesis import SYNTHESIS_SECTION_MAX_TOKENS

    assert SYNTHESIS_SECTION_MAX_TOKENS == 800


def test_user_prompt_includes_full_600_char_excerpt() -> None:
    """Workstream-2 bumped the per-answer excerpt cap from 250 to 600
    chars. The synthesis user_prompt must carry the longer excerpt
    through so the LLM sees the model's actual stance (and any inline
    citation links) instead of a truncated sliver.
    """
    from product_app import synthesis as synth_mod

    # 800 chars of deterministic text so we can prove the slice point.
    long_answer = "x" * 800
    answer = provider_stub_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="dummy",
        model_slots=validate_model_slots(DEFAULT_MODEL_IDS),
    )[0]
    # Override the answer_text with a long slice-friendly string.
    # ``InitialModelAnswer`` is not frozen, so plain attribute
    # assignment works and goes through Pydantic validation (the
    # ``object.__setattr__`` form bypasses validation, so it would
    # silently swallow any future ``Field(max_length=...)`` constraint).
    answer.answer_text = long_answer

    user_prompt = synth_mod.synthesis_stub_service._user_prompt(
        initial_answers=[answer],
        debate_outputs=[],
        failed_count=0,
        coverage_ratio=type("R", (), {"__str__": lambda self: "0.0"})(),
    )
    # 800 chars in, sliced to 600; the prompt must carry the full 600.
    assert ("x" * 600) in user_prompt
    # And must NOT carry the trailing 200 that the old cap would have dropped.
    assert ("x" * 601) not in user_prompt


def test_user_prompt_includes_full_700_char_debate_excerpt() -> None:
    """Workstream-2 bumped the per-round debate excerpt cap from 300 to
    700 chars so the uncertainty section can see the actual claim in
    the critique instead of a truncated prefix.
    """
    from dataclasses import dataclass

    from product_app import synthesis as synth_mod

    long_critique = "y" * 800

    @dataclass(frozen=True)
    class _FakeRound:
        round_number: int
        critique_text: str

    user_prompt = synth_mod.synthesis_stub_service._user_prompt(
        initial_answers=[],
        debate_outputs=cast(
            "list[DebateOutput]",
            [_FakeRound(round_number=1, critique_text=long_critique)],
        ),
        failed_count=0,
        coverage_ratio=type("R", (), {"__str__": lambda self: "0.0"})(),
    )
    assert ("y" * 700) in user_prompt
    assert ("y" * 701) not in user_prompt


def test_recommendation_prompt_enforces_decision_support_caveat_and_gates() -> None:
    """Workstream-2 tightened ``_RECOMMENDATION_PROMPT`` so the model
    cannot omit the decision-support caveat, cannot bury a failed-count,
    and cannot quietly approve action when coverage is below 80%.
    The prompt itself encodes the hard rules; this test pins that
    contract.
    """
    from product_app.synthesis import _RECOMMENDATION_PROMPT

    # The verbatim decision-support caveat sentence is referenced.
    assert "decision support only" in _RECOMMENDATION_PROMPT
    assert "medical, legal, financial, safety" in _RECOMMENDATION_PROMPT
    # Failed-count and coverage gates are spelled out as rules, not
    # buried in prose.
    assert "failed_count > 0" in _RECOMMENDATION_PROMPT
    assert "below 80%" in _RECOMMENDATION_PROMPT
    # "Verbatim" + "lead with that fact" tell the model the caveat and
    # the failure disclosure are non-negotiable.
    assert "verbatim" in _RECOMMENDATION_PROMPT
    assert "first sentence" in _RECOMMENDATION_PROMPT
