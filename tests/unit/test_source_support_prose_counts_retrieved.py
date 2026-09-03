"""The source-support prose must not report zero while sources are on screen.

MEASURED DEFECT (2026-09-04), four live answers each carrying one real
Reuters-shaped page retrieved by web search::

    source_support : "No model returned visible source references for this query."
    summary        : "Roughly 0% of those answers carried at least one visible
                      source reference."

Four chips were rendered on the page at that moment. The word *visible* is the
contradiction: they were visibly there. ADR-0098 keeps the coverage ARITHMETIC
unchanged (a retrieved page is still not the model's own citation) and fixes the
sentence, which conflated "no model cited its own sources" with "there is no
evidence here".
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from product_app.config import settings
from product_app.debate import debate_stub_service
from product_app.model_slots import validate_model_slots
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    CitationCoverage,
    LiveProviderResult,
    SourceReference,
    TokenUsage,
    _parse_tavily_results,
    provider_event_recorder,
    provider_execution_service,
)
from product_app.synthesis import synthesis_stub_service

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]
QUERY = "Does the evidence support the proposal?"


def setup_function() -> None:
    provider_event_recorder.clear()


def _retrieved(n: int) -> list[SourceReference]:
    return _parse_tavily_results(
        {
            "results": [
                {"title": f"Reuters investigation {n}", "url": f"https://reuters.example/a{n}"}
            ]
        }
    )


def _run(
    *, attach_retrieved: bool, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, CitationCoverage]:
    """Drive a whole run through production code and return (source_support, coverage)."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    slots = validate_model_slots(MODEL_IDS)
    account_id, query_run_id = uuid4(), uuid4()
    answers = []
    for i, slot in enumerate(slots):
        live = LiveProviderResult(
            answer_text=f"Model {i}: a real live answer with no inline citations.",
            sources=[],
            usage=TokenUsage(prompt_tokens=100, completion_tokens=200, total_tokens=300),
        )
        with (
            patch.object(provider_execution_service, "_post_openrouter", return_value=live),
            patch.object(
                provider_execution_service, "_tavily_enabled", return_value=attach_retrieved
            ),
            patch.object(provider_execution_service, "_tavily_search", return_value=_retrieved(i)),
        ):
            answers.append(
                provider_execution_service.produce_initial_answer(
                    account_id=account_id,
                    query_run_id=query_run_id,
                    query_text=QUERY,
                    model_slot=slot,
                    credential_source=ProviderCredentialSource.APP_OWNED,
                    openrouter_key="sk-test",
                )
            )
    debate = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=QUERY,
        initial_answers=answers,
    )
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=QUERY,
        initial_answers=answers,
        debate_outputs=debate.debate_outputs,
    )
    fs = result.final_synthesis
    assert fs is not None, "precondition: the run produced a synthesis"
    return fs.source_support, fs.citation_coverage


def test_prose_does_not_claim_zero_sources_while_sources_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED without the fix: the section reads 'No model returned visible source
    references for this query.' on a run displaying four retrieved pages."""
    support, coverage = _run(attach_retrieved=True, monkeypatch=monkeypatch)

    assert coverage.sourced_answer_count == 0, (
        "precondition (ADR-0098): retrieved pages still do not count as the model's own citations"
    )
    assert "No model returned visible source references" not in support, (
        f"prose claims there are no visible sources while four are shown: {support!r}"
    )
    assert "search" in support.lower(), (
        f"the prose must say where the references actually came from: {support!r}"
    )


def test_prose_still_says_nothing_when_there_really_is_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSITIVE PARTNER (rule 7). The fix above is worthless if it simply
    removed the honest sentence: with NO sources at all the run must still say
    so plainly. RED if a fix claimed retrieved evidence that does not exist."""
    support, coverage = _run(attach_retrieved=False, monkeypatch=monkeypatch)

    assert coverage.sourced_answer_count == 0
    assert "No model returned visible source references" in support, (
        f"a genuinely source-free run must still say so: {support!r}"
    )


def test_prose_does_not_credit_web_search_for_quorum_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DEFECT THIS FIX INTRODUCED, and the gate that caught it.

    The first draft counted "any answer with sources", not "any answer with a
    WEB_SEARCH source. The ``example.test`` placeholders Quorum writes for a
    simulated run ARE sources, so a keyless demo run announced *"4 of 4
    responding models had references attached by web search"* — a worse
    falsehood than the sentence being replaced, and one three existing tests
    caught only because they pinned the old string.

    RED if the condition is loosened back to ``answer.sources``."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    slots = validate_model_slots(MODEL_IDS)
    account_id, query_run_id = uuid4(), uuid4()

    answers = [
        provider_execution_service.produce_initial_answer(
            account_id=account_id,
            query_run_id=query_run_id,
            query_text=QUERY,
            model_slot=slot,
            credential_source=ProviderCredentialSource.APP_OWNED,
            openrouter_key="",
        )
        for slot in slots
    ]
    # Precondition (rule 7's positive half): these answers DO carry sources, so
    # the assertion below is not trivially true over an empty list.
    assert all(answer.sources for answer in answers), "precondition: placeholders exist"

    debate = debate_stub_service.run_debate_rounds(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=QUERY,
        initial_answers=answers,
    )
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=account_id,
        query_run_id=query_run_id,
        query_text=QUERY,
        initial_answers=answers,
        debate_outputs=debate.debate_outputs,
    )
    fs = result.final_synthesis
    assert fs is not None
    assert "web search" not in fs.source_support, (
        "a simulated run's example.test placeholders were credited to a web "
        f"search that never ran: {fs.source_support!r}"
    )
