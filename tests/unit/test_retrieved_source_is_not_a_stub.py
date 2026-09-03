"""A really-retrieved web page must be distinguishable from a Quorum placeholder.

MEASURED DEFECT (2026-09-04). With live execution ON, a live model that answers
with no citation annotations triggers a REAL web search (the ``_tavily_search``
call inside ``produce_initial_answer``'s live-answer arm)
whose results are attached to that live answer. Those results were emitted as
``provider=FALLBACK_SEARCH``/``is_fallback=True`` — byte-identical on the wire to
the ``example.test`` placeholder Quorum writes itself. The UI therefore could not
tell them apart and rendered a real Reuters URL as a non-clickable chip badged
"fallback stub", exported as "fallback stub, not a real source".

Probe output before the fix, four live answers with four real pages attached::

    citation coverage : answer_count=4 sourced_answer_count=0 ratio=0.00
    source_support    : "No model returned visible source references for this query."
    DEBATE prompt contains 'reuters.com': True

WHAT TURNS EACH TEST RED is stated on the test.

DELIBERATELY NOT CHANGED — the coverage arithmetic. ``is_fallback`` keeps its
documented meaning ("not the model's OWN citation") and a
retrieved page still does not count toward ``citation_coverage``. See ADR-0098.
``test_a_retrieved_source_still_does_not_count_as_a_model_citation`` is the gate
that keeps that decision from being reversed by accident.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from tests.code_text import code_without_comments

from product_app.config import settings
from product_app.model_slots import validate_model_slots
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
    _parse_tavily_results,
    provider_event_recorder,
    provider_execution_service,
)

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def setup_function() -> None:
    provider_event_recorder.clear()


@pytest.fixture
def live_execution_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)


def _retrieved(n: int) -> list[SourceReference]:
    """What a REAL web search returns, built through the production mapper."""
    return _parse_tavily_results(
        {
            "results": [
                {"title": f"Reuters investigation {n}", "url": f"https://reuters.example/a{n}"}
            ]
        }
    )


def _live_answer_with_retrieved_sources(slot_index: int) -> InitialModelAnswer:
    """One COMPLETED live answer whose sources came from a real web search.

    Driven through ``produce_initial_answer`` rather than constructed, so the
    classification under test is the one production computes.
    """
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    live = LiveProviderResult(
        answer_text=f"Model {slot_index}: a real live answer carrying no inline citations.",
        sources=[],
        usage=TokenUsage(prompt_tokens=100, completion_tokens=200, total_tokens=300),
    )
    with (
        patch.object(provider_execution_service, "_post_openrouter", return_value=live),
        patch.object(provider_execution_service, "_tavily_enabled", return_value=True),
        patch.object(
            provider_execution_service, "_tavily_search", return_value=_retrieved(slot_index)
        ),
    ):
        return provider_execution_service.produce_initial_answer(
            account_id=uuid4(),
            query_run_id=uuid4(),
            query_text="Does the evidence support the proposal?",
            model_slot=slots[slot_index],
            credential_source=ProviderCredentialSource.APP_OWNED,
            openrouter_key="sk-test",
        )


# ---------------------------------------------------------------------------
# The discriminator itself.
# ---------------------------------------------------------------------------


def test_a_retrieved_page_is_not_classified_as_a_quorum_stub() -> None:
    """RED without the fix: ``_parse_tavily_results`` stamps FALLBACK_SEARCH,
    the same provider as the ``example.test`` placeholder, so the UI cannot
    distinguish a real page from one Quorum invented."""
    refs = _parse_tavily_results({"results": [{"title": "Real", "url": "https://a.example/x"}]})
    assert refs, "precondition: the mapper must return the well-formed result"
    assert all(r.provider is ProviderPath.WEB_SEARCH for r in refs), (
        "a really-retrieved page must carry its own provider path, not the "
        f"placeholder's: got {[r.provider for r in refs]}"
    )


def test_the_quorum_authored_placeholder_still_says_it_is_one() -> None:
    """POSITIVE PARTNER (rule 7) for the test above: the discriminator is only
    meaningful if the OTHER shape still classifies as a stub. RED if a fix
    relabelled every source as retrieved."""
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    with patch.object(provider_execution_service, "_tavily_enabled", return_value=False):
        stub = provider_execution_service._fallback_sources(
            model_slot=slots[0], query_text="anything"
        )
    assert len(stub) == 1, f"precondition: one placeholder, got {len(stub)}"
    assert stub[0].provider is ProviderPath.FALLBACK_SEARCH
    assert "example.test" in stub[0].url, (
        "precondition: the placeholder points at the IANA-reserved domain"
    )


def test_the_local_simulation_placeholder_is_untouched() -> None:
    """POSITIVE PARTNER: the third source shape must keep its own path."""
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    sim = provider_execution_service._local_simulation_sources(model_slot=slots[0])
    assert [s.provider for s in sim] == [ProviderPath.LOCAL_SIMULATION]


# ---------------------------------------------------------------------------
# The decision that must NOT move.
# ---------------------------------------------------------------------------


def test_a_retrieved_source_still_does_not_count_as_a_model_citation(
    live_execution_on: None,
) -> None:
    """ADR-0098: the coverage metric measures the model's OWN citations, so a
    page Quorum retrieved must still NOT count toward it.

    RED if someone "fixes" the coverage arithmetic to count retrieved sources —
    which would silently move the number the verdict band leans on. Asserts
    CARDINALITY (rule 6b), not just a clean-path outcome."""
    answer = _live_answer_with_retrieved_sources(0)
    assert answer.sources, "precondition: the retrieved page must be attached"
    assert answer.citation_coverage.answer_count == 1, "precondition: the answer completed"
    assert answer.citation_coverage.sourced_answer_count == 0, (
        "a retrieved page is not the model's own citation and must not raise coverage"
    )


def test_the_retrieved_source_is_still_flagged_not_the_models_own(
    live_execution_on: None,
) -> None:
    """POSITIVE PARTNER: ``is_fallback`` keeps its documented meaning. RED if the
    discriminator were implemented by flipping this flag instead of adding a
    path — which is the change that WOULD move the coverage number."""
    answer = _live_answer_with_retrieved_sources(1)
    assert [s.is_fallback for s in answer.sources] == [True], (
        "is_fallback must still mean 'not the model's own citation'"
    )
    assert [s.provider for s in answer.sources] == [ProviderPath.WEB_SEARCH]


def test_the_retrieved_source_rides_a_genuinely_live_answer(live_execution_on: None) -> None:
    """The reachability premise this whole file rests on, asserted rather than
    assumed: the supplement path attaches to a LIVE answer, not a fallback one.
    RED if ``produce_initial_answer``'s live-execution guard ever stops returning
    a FAILED slot before the ``use_fallback`` branch, which would
    mean these sources ride simulated text instead."""
    answer = _live_answer_with_retrieved_sources(2)
    assert answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    assert answer.fallback_used is False


# ---------------------------------------------------------------------------
# The BROWSER-side predicate.
#
# Added because the mutation proof found two survivors here: the only gate on
# `isStubSource` was a Playwright spec, which `pytest` does not run, so both
# "key the badge on isFallback again" and "drop the fail-safe clause" survived
# the whole Python suite. `e2e/tests/invariants/source-expander.spec.ts` proves
# the RENDERED behaviour; these two prove the predicate itself, in the lane that
# runs on every commit.
# ---------------------------------------------------------------------------

APP_JS = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static" / "app.js"


def test_both_source_surfaces_actually_CALL_the_shared_predicate() -> None:
    """RED if either call site is reverted to the pre-fix inline predicate.

    The first version of this file asserted only the TEXT of ``isStubSource``.
    A reviewer measured the hole: revert both call sites, leave the helper
    defined as dead code, and all five assertions still passed while a real
    Reuters URL was badged "fallback stub, not a real source" again. Pinning a
    helper's body proves nothing about whether anything calls it.

    Read over COMMENT-STRIPPED code (rule 8), so the comments this change added
    — which name the predicate repeatedly — cannot green it."""
    code = code_without_comments(APP_JS)

    assert code.count("isStubSource(") == 4, (
        "expected one definition and three call sites (chip row, Markdown "
        f"export, transcript list); found {code.count('isStubSource(')}"
    )
    assert "if (isStubSource(s)) {" in code, "the Markdown export must use the predicate"
    assert "const isStub = isStubSource(s);" in code, "the chip row must use the predicate"
    assert "if (isStubSource(source)) {" in code, "the transcript list must use the predicate"
    assert "STUB_SOURCE_PROVIDERS.has(s.provider) || s.isFallback === true" not in code, (
        "the pre-fix inline predicate is back at a call site"
    )


def test_the_shared_predicate_excludes_the_known_real_providers() -> None:
    """RED if ``REAL_SOURCE_PROVIDERS`` stops covering the retrieved path.

    ``is_fallback`` is True for a really-retrieved page too — deliberately, so
    the coverage metric does not move — so keying the "not a real source" badge
    on it is precisely the defect ADR-0098 fixes."""
    code = code_without_comments(APP_JS)
    assert '"web_search"' in code, "web_search must be a recognised real-source provider"
    assert "!REAL_SOURCE_PROVIDERS.has(s.provider)" in code, (
        "the predicate must exclude the known-real providers, not fire on is_fallback alone"
    )


def test_the_shared_predicate_still_fails_safe_on_an_unknown_provider() -> None:
    """POSITIVE PARTNER, and RED if the fail-safe clause is dropped.

    Deleting it would render an UNRECOGNISED provider carrying ``is_fallback``
    as a real citation — a future source path could launder itself into
    evidence by omission, which is the #247 failure mode."""
    code = code_without_comments(APP_JS)
    assert "if (STUB_SOURCE_PROVIDERS.has(s.provider)) return true;" in code, (
        "the Quorum-authored stub providers must still be caught by provider"
    )
    assert "return fallback && !REAL_SOURCE_PROVIDERS.has(s.provider);" in code, (
        "the fail-safe clause is gone: an unknown provider with is_fallback "
        "would now be presented as a real source"
    )


def test_the_predicate_reads_both_wire_shapes() -> None:
    """RED if the predicate reads only one casing.

    The chip row and export pass a camelCase projection; the transcript list
    passes the RAW snake_case server object. Reading one silently evaluates
    ``undefined === true`` on the other surface and drops the fail-safe clause
    with no test noticing."""
    code = code_without_comments(APP_JS)
    assert "s.isFallback === true || s.is_fallback === true" in code, (
        "the shared predicate must accept both the camelCase projection and the "
        "raw snake_case server object"
    )


def test_a_retrieved_page_is_marked_as_retrieved_not_left_bare() -> None:
    """RED if the neutral origin tag is dropped.

    Un-badging a retrieved page without marking it replaces one contradiction
    with another: four real chips render indistinguishable from model-cited
    ones directly beneath a trust card that still reads "0 sources cited",
    because ADR-0098 Decision 2 deliberately freezes that count."""
    code = code_without_comments(APP_JS)
    assert 'RETRIEVED_SOURCE_TAG_TEXT = "web search"' in code
    assert "result-source-origin-tag" in code, "the chip must carry the origin tag"
    assert '" — via web search"' in code, "the export must say where the page came from"
