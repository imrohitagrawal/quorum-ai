from decimal import Decimal
from typing import cast, get_args
from uuid import uuid4

import pytest

from product_app.debate import DebateOutput, debate_stub_service
from product_app.model_slots import validate_model_slots
from product_app.providers import (
    TokenUsage,
    provider_execution_service,
    provider_stub_service,
)
from product_app.synthesis import (
    SYNTHESIS_MODES,
    SynthesisMode,
    SynthesisStatus,
    synthesis_event_recorder,
    synthesis_stub_service,
)

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
    # #247: both of these were bare substrings that STAYED GREEN while the
    # sentences under them inverted in meaning — "The disagreement is preserved
    # as the dominant signal" became "there is no disagreement to preserve", and
    # "4 of 4 responding models returned visible source references" became "No
    # model returned visible source references". The substring matches both
    # halves of each pair. Asserted on content now, which is what rule 8 asks
    # for and what a reader would assume these lines already did.
    assert "No model was asked this question" in synthesis.disagreement
    assert "Models do not agree" not in synthesis.disagreement
    assert synthesis.source_support == "No model returned visible source references for this query."

    assert synthesis.uncertainty
    assert "decision support only" in synthesis.recommendation
    assert synthesis.synthesis_mode == "simulated"
    # WP-C / F-03: coverage is the share of ANSWERS carrying a primary source.
    # #247: these asserted 4/4 and target-met, on the reasoning quoted from the
    # comment they replace — that "all four local-simulation answers carry a
    # primary source". They do not. Each carries ``example.test/local-demo/N``,
    # a placeholder this product wrote on an IANA-reserved domain, for a slot no
    # model was asked. That is what made a keyless run claim 100% source coverage
    # with every quarter invented.
    #
    # ``answer_count`` stays 4 — the slots did produce text. The WP-C / F-03
    # redefinition this comment used to defend is untouched: coverage is still
    # the share of ANSWERS carrying a primary source, and length still does not
    # move it (pinned in tests/unit/test_citation_coverage_semantics.py). What
    # changed is only which sources count as primary.
    assert synthesis.citation_coverage.answer_count == 4
    assert synthesis.citation_coverage.sourced_answer_count == 0
    assert synthesis.citation_coverage.sourced_answer_ratio == Decimal("0.00")
    assert not synthesis.citation_coverage.target_met
    assert not synthesis.quality_checks.citation_coverage_target_met
    # #247: this asserted ``not ...false_consensus_preserved``, on the reasoning
    # (quoted verbatim from the comment it replaces) that "with all four stub
    # answers being identical, the consensus strength is 'strong'". That
    # reasoning IS the defect: the four stub answers are identical because this
    # product wrote all four from one template, not because four models agreed.
    #
    # ``git log -S`` shows this line read ``assert
    # synthesis.quality_checks.false_consensus_preserved`` until PR-2
    # (``eee93ca``), which flipped it. Restoring it is a revert to the original
    # assertion, not a weakening — the flag is True because the strength is now
    # "divided", which is what a panel nobody asked deserves.
    #
    # The ``docs/SYNTHESIS_AUDIT.md`` citation is kept because Defect 3 was real
    # (the old check substring-matched the templated disagreement text and could
    # never fail). But §5 of that audit prescribes ``true`` only when the
    # strength is weak/divided AND the disagreement came from a live LLM; PR-2
    # implemented the first clause, dropped the second, and asserted the result
    # as correct. The audit does not prescribe False here.
    assert synthesis.quality_checks.false_consensus_preserved
    assert synthesis.quality_checks.decision_support_framing_present
    event = synthesis_event_recorder.list_events()[0]
    assert event.account_id == account_id
    assert event.query_run_id == query_run_id
    assert event.status is SynthesisStatus.COMPLETED
    # #247: same revert as above — ``eee93ca`` flipped this from
    # ``assert event.false_consensus_preserved`` in the same commit. The served
    # flag and the recorded event must agree, so they move together.
    assert event.false_consensus_preserved
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
    assert result.final_synthesis.synthesis_mode == "live"
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
    # #247: this line asserted ``"Four models were asked" in ...consensus``. This
    # run has NO key, so every slot is local simulation and no model was asked —
    # the test was pinning a sentence that is false about its own fixture. It was
    # only ever a marker for "the templated path produced this", and a redundant
    # one: ``called["count"] == 0`` and ``synthesis_mode == "simulated"`` below
    # both say that directly and neither can be true of a live run.
    #
    # Replaced with the templated text this run actually produces, so the
    # consensus section is still pinned exactly rather than left unasserted.
    assert "No model was asked this question" in result.final_synthesis.consensus
    assert "Four models were asked" not in result.final_synthesis.consensus
    # The "visible source references" phrase from the templated source_support
    # is what the existing integration test pins.
    assert "visible source references" in result.final_synthesis.source_support
    # No LLM calls were made; mode reflects the templated path.
    assert called["count"] == 0
    assert result.final_synthesis.synthesis_mode == "simulated"


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


def test_synthesis_section_max_tokens_matches_the_priced_cap() -> None:
    """WP-D (F-07) raised the per-section token cap from 800 to 3000.

    The value is pinned here so an accidental revert is caught, and it is
    pinned *against ``settings.cost_synthesis_output_tokens``* rather than
    against a bare literal alone: the enforced cap and the cap the cost
    bound prices must move together, or ``max_cost_usd`` stops being a
    true ceiling. Deriving the second assertion from config is what makes
    this test catch the real failure mode (the two drifting apart) and not
    merely a typo.

    Bite proof: set either value to 800 and this reds.
    """
    from product_app.config import settings
    from product_app.synthesis import SYNTHESIS_SECTION_MAX_TOKENS

    assert SYNTHESIS_SECTION_MAX_TOKENS == 3000
    assert settings.cost_synthesis_output_tokens == SYNTHESIS_SECTION_MAX_TOKENS


def test_user_prompt_carries_the_answer_up_to_the_derived_cap() -> None:
    """WP-D (F-08) replaced the hardcoded 600-char per-answer excerpt with
    ``SYNTHESIS_ANSWER_EXCERPT_MAX_CHARS``, derived from the token cap on the
    call that produced the answer.

    This asserts BOTH directions against the derived constant rather than a
    literal, so it keeps biting when the cap moves:

    * everything up to the cap survives — a regression back to 600 (or any
      smaller slice) reds the first assertion;
    * the cap is still enforced — deleting the slice entirely reds the second.

    The old version of this test pinned 600 as a *feature* (``"x" * 601 not
    in prompt``), which is exactly what F-08 set out to remove.
    """
    from product_app import synthesis as synth_mod
    from product_app.config import settings
    from product_app.synthesis import SYNTHESIS_ANSWER_EXCERPT_MAX_CHARS as CAP

    # Deliberately longer than the cap so the slice point is observable.
    long_answer = "x" * (CAP + 200)
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
    # Everything up to the derived cap reaches the model...
    assert ("x" * CAP) in user_prompt
    # ...and the cap is still a cap.
    assert ("x" * (CAP + 1)) not in user_prompt
    # The behavioural invariant, not the tautology `CAP == max_tokens * 4`
    # (which merely restates the definition and rescales with it): an answer of
    # the longest length a slot is allowed to produce must reach synthesis
    # whole. This reds if the excerpt is ever hardcoded below the answer cap.
    longest_possible = "w" * (settings.initial_answer_max_tokens * 4)
    answer.answer_text = longest_possible
    prompt2 = synth_mod.synthesis_stub_service._user_prompt(
        initial_answers=[answer],
        debate_outputs=[],
        failed_count=0,
        coverage_ratio=type("R", (), {"__str__": lambda self: "0.0"})(),
    )
    assert longest_possible in prompt2, (
        "a full-length initial answer is being truncated on its way into "
        "synthesis — the excerpt cap is smaller than what a slot can emit"
    )


def test_user_prompt_carries_the_critique_up_to_the_debate_derived_cap() -> None:
    """WP-D (F-08): the per-round critique excerpt is now
    ``SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS``, derived from
    ``DEBATE_ROUND_MAX_TOKENS`` — a critique cannot be longer than the debate
    call that produced it was allowed to be.

    The derivation is the contract, and the last assertion is what makes this
    test worth having: pinning the literal 8000 would keep passing if someone
    changed the debate cap without changing this excerpt, which is the exact
    drift the derived form exists to prevent. (At the pre-F-07 cap of 700
    tokens the correct value here was 2800, not 8000.)
    """
    from dataclasses import dataclass

    from product_app import synthesis as synth_mod
    from product_app.debate import DEBATE_ROUND_MAX_TOKENS
    from product_app.synthesis import SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS as CAP

    long_critique = "y" * (CAP + 200)

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
    assert ("y" * CAP) in user_prompt
    assert ("y" * (CAP + 1)) not in user_prompt

    # The assertion that actually bites. `CAP == DEBATE_ROUND_MAX_TOKENS * 4`
    # would be a tautology — it restates the definition, so reverting F-07's
    # cap to 700 rescales CAP, the fixture and both assertions above together
    # and the test still passes. State the BEHAVIOURAL invariant instead: a
    # critique of the longest length the debate is allowed to emit must reach
    # the synthesis UNTRUNCATED. That reds if this excerpt is ever hardcoded
    # (to 700, 2800 or 8000) while the debate cap says otherwise — which is
    # the real defect, and the reason the plan ordered #3 before #4.
    longest_possible = "z" * (DEBATE_ROUND_MAX_TOKENS * 4)
    prompt2 = synth_mod.synthesis_stub_service._user_prompt(
        initial_answers=[],
        debate_outputs=cast(
            "list[DebateOutput]",
            [_FakeRound(round_number=1, critique_text=longest_possible)],
        ),
        failed_count=0,
        coverage_ratio=type("R", (), {"__str__": lambda self: "0.0"})(),
    )
    assert longest_possible in prompt2, (
        "a full-length debate critique is being truncated on its way into "
        "synthesis — the excerpt cap is smaller than what the debate can emit"
    )


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


def test_no_templating_prefix_leaks_into_sections() -> None:
    """PR6/#8/#15: templated provenance must NOT ride in the prose.

    The old code prepended "Heuristic fallback: " (later "[Template] ") to
    every templated section, so internal jargon surfaced verbatim in the
    user-facing recommendation. Provenance now travels structurally as
    ``FinalSynthesis.synthesis_mode`` and is rendered as a badge.

    This pins the PRODUCER, not the renderer: a client-side scrub would also
    mangle genuine provider prose that happens to contain these words.
    """
    account_id = uuid4()
    query_run_id = uuid4()
    query = "Compare source-backed options with material disagreement"
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query,
        model_slots=model_slots,
    )
    debate_result = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query,
        initial_answers=initial_answers,
    )
    # No openrouter_key => every section takes the TEMPLATED path, which is
    # exactly the path that used to carry the prefix.
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=query,
        initial_answers=initial_answers,
        debate_outputs=debate_result.debate_outputs,
    )
    synthesis = result.final_synthesis
    assert synthesis is not None

    banned = ("[Template]", "Heuristic fallback", "Template]")
    sections = {
        "consensus": synthesis.consensus,
        "disagreement": synthesis.disagreement,
        "source_support": synthesis.source_support,
        "uncertainty": synthesis.uncertainty,
        "recommendation": synthesis.recommendation,
    }
    for name, text in sections.items():
        for token in banned:
            assert token not in (text or ""), f"{name} leaked internal jargon {token!r}: {text!r}"

    # ...and the provenance the prefix used to convey is still available,
    # structurally. Without a key no live call happens, so this is templated.
    assert synthesis.synthesis_mode == "simulated"


def test_synthesis_mode_reports_usable_live_text_not_merely_a_billed_call() -> None:
    """``synthesis_mode`` is the PROVENANCE channel. It must say "live" only
    when the user is actually reading live model prose.

    This is a defect the WP-D <- main merge created, present in neither side
    alone. F-06 deliberately returns a non-``None`` live result even when the
    completion is BLANK, so the billed usage is recorded and a charged call
    cannot vanish from the receipt — correct, and it must stay. But
    ``live_call_usages`` is built from those results, so ``live_count`` counts
    calls that were DISPATCHED, not calls that produced text. Meanwhile WP-A
    moved provenance out of the prose (``TEMPLATED_FALLBACK_PREFIX`` is now
    "") and into ``synthesis_mode``.

    Inputs -> wrong output: all five synthesis calls return HTTP 200 with an
    empty completion. Every section falls back to templated text, yet
    ``live_count == 5`` so the run is labelled ``synthesis_mode == "live"`` —
    the product presents templated prose as live model output. That is the
    exact failure the degraded-banner contract exists to prevent.

    Bite proof: compute ``synthesis_mode`` from ``len(live_call_usages)`` and
    this reds.
    """
    from product_app import config
    from product_app.providers import LiveProviderResult

    def blank_but_billed(**kwargs: object) -> LiveProviderResult:
        # A billed call whose completion came back empty.
        return LiveProviderResult(
            answer_text="   ",
            sources=[],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(provider_execution_service, "call_with_prompt", blank_but_billed)
        mp.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
        account_id, query_run_id = uuid4(), uuid4()
        slots = validate_model_slots(DEFAULT_MODEL_IDS)
        answers = provider_stub_service.produce_initial_answers(
            account_id=account_id,
            query_run_id=query_run_id,
            query_text="Compare source-backed options",
            model_slots=slots,
        )
        result = synthesis_stub_service.produce_final_synthesis(
            account_id=account_id,
            query_run_id=query_run_id,
            query_text="Compare source-backed options",
            initial_answers=answers,
            debate_outputs=[],
            openrouter_key="sk-or-test-live",
        )

    assert result.final_synthesis is not None
    # The billed usage is still recorded — F-06's contract is untouched.
    assert len(result.live_call_usages) == 5
    # ...but the user is reading TEMPLATED prose, so it is not a live run.
    assert result.final_synthesis.synthesis_mode != "live", (
        "templated sections were labelled as live model output"
    )


def test_synthesis_modes_frozenset_matches_the_closed_literal_type() -> None:
    """#206: ``SYNTHESIS_MODES`` (the runtime set) and ``SynthesisMode`` (the
    Pydantic field's closed type) are two independent spellings of the same
    three values — mypy cannot check that a runtime `frozenset` literal and a
    `Literal[...]` type alias agree, so nothing stops them drifting apart if a
    mode is ever added to one and not the other.

    What turns it red: add a 4th string to ``SYNTHESIS_MODES`` (or remove one)
    without touching ``SynthesisMode``, or vice versa — the two sets stop
    being equal and this fails, forcing whoever adds a mode to update BOTH
    instead of shipping a value the Pydantic field would silently reject (or
    a Literal member `SYNTHESIS_MODES` never covers).
    """
    assert set(get_args(SynthesisMode)) == SYNTHESIS_MODES, (
        f"SYNTHESIS_MODES {sorted(SYNTHESIS_MODES)} and SynthesisMode's Literal "
        f"args {sorted(get_args(SynthesisMode))} have drifted apart"
    )
