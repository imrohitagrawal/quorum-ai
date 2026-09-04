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

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from product_app.config import settings
from product_app.debate import debate_stub_service
from product_app.model_slots import validate_model_slots
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
    _parse_tavily_results,
    provider_event_recorder,
    provider_execution_service,
)
from product_app.synthesis import (
    _with_retrieved_note,
    count_answers_with_retrieved_sources,
    synthesis_stub_service,
)

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]
QUERY = "Does the evidence support the proposal?"
#: The suite's own trigger phrase for the forced-fallback path.
_FORCE_FALLBACK = "force fallback"


def _live_answers(
    *, attach: list[bool], monkeypatch: pytest.MonkeyPatch
) -> list[InitialModelAnswer]:
    """Four COMPLETED live answers; ``attach[i]`` decides if slot i gets a page."""
    slots = validate_model_slots(MODEL_IDS)
    account_id, query_run_id = uuid4(), uuid4()
    out = []
    for i, slot in enumerate(slots):
        live = LiveProviderResult(
            answer_text=f"Model {i}: a real live answer with no inline citations.",
            sources=[],
            usage=TokenUsage(prompt_tokens=100, completion_tokens=200, total_tokens=300),
        )
        with (
            patch.object(provider_execution_service, "_post_openrouter", return_value=live),
            patch.object(provider_execution_service, "_tavily_enabled", return_value=attach[i]),
            patch.object(provider_execution_service, "_tavily_search", return_value=_retrieved(i)),
        ):
            out.append(
                provider_execution_service.produce_initial_answer(
                    account_id=account_id,
                    query_run_id=query_run_id,
                    query_text=QUERY,
                    model_slot=slot,
                    credential_source=ProviderCredentialSource.APP_OWNED,
                    openrouter_key="sk-test",
                )
            )
    return out


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
    # CARDINALITY (rule 6b). Without this, hardcoding the count wrong survives:
    # a reviewer mutated the builder to `retrieved = 1` against a truth of 4 and
    # 209 tests passed. A fraction is exactly the accounting shape rule 6b names.
    assert "4 of 4 answers on this run" in support, (
        f"the prose must report the REAL count, not a shape: {support!r}"
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


def test_the_prose_count_is_a_real_fraction_not_the_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED if the numerator is hardcoded, or silently equals the denominator.

    The sibling test above asserts "4 of 4", which a builder that simply prints
    `total` twice would also satisfy. This drives a run where only TWO of four
    answers carry a retrieved page and pins "2 of 4" — so numerator and
    denominator are constrained independently (rule 7a's shape: never let one
    term define the other)."""
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
        attach = i < 2  # only the first TWO get a retrieved page
        with (
            patch.object(provider_execution_service, "_post_openrouter", return_value=live),
            patch.object(provider_execution_service, "_tavily_enabled", return_value=attach),
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

    # Precondition: exactly two answers carry a source, two carry none.
    assert [bool(a.sources) for a in answers] == [True, True, False, False]

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
    assert "2 of 4 answers on this run" in fs.source_support, (
        f"the numerator must count retrieved answers, not the total: {fs.source_support!r}"
    )


# ---------------------------------------------------------------------------
# THE LIVE PATH. `base` above is used ONLY when the live synthesis call returns
# nothing, so on the configuration this defect was measured in the section is
# written by the MODEL. Two mutations survived the whole suite until these two
# tests existed — the fix had no gate on the path that actually ships.
# ---------------------------------------------------------------------------


def test_the_live_synthesis_prompt_names_the_retrieved_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED without the note: the model writing the "Source support" section is
    told "Source coverage: 0% ... carried at least one primary source" and
    nothing about the retrieved pages listed right below it, so the honest
    sentence never reaches a live run."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    answers = _live_answers(attach=[True, True, True, True], monkeypatch=monkeypatch)

    noted = _with_retrieved_note("BASE PROMPT", answers)

    assert "web search this product ran supplied the references" in noted, (
        f"the note must name the retrieved sources: {noted!r}"
    )
    assert "4 of the answers cited no source of their own" in noted, (
        "the note must carry the real count (rule 6b)"
    )
    assert "NOT the models' own citations" in noted, (
        "the note must preserve the distinction the coverage metric makes"
    )


def test_the_retrieved_note_reaches_ONLY_the_source_support_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED if the note is appended to the shared ``directives`` block again.

    ``_user_prompt`` is built once and passed to all five sections. The note
    ends "do not describe the run as having no sources at all"; a reviewer
    found an earlier version of it landing in the RECOMMENDATION prompt, beside
    the safety rule that steers "pause for human review" when coverage is under
    80%. Scope, not wording, is what keeps it out of there."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    answers = _live_answers(attach=[True, True, True, True], monkeypatch=monkeypatch)

    shared = synthesis_stub_service._user_prompt(
        initial_answers=answers,
        debate_outputs=[],
        failed_count=0,
        coverage_ratio=Decimal("0.00"),
    )
    assert "web search this product ran supplied" not in shared, (
        "the retrieved-sources note leaked into the SHARED prompt, so it now "
        f"reaches consensus, disagreement, uncertainty and recommendation: {shared[:400]!r}"
    )
    # POSITIVE PARTNER: it must still be there once scoped.
    assert "web search this product ran supplied" in _with_retrieved_note(shared, answers)


def test_the_note_is_absent_when_nothing_was_retrieved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSITIVE PARTNER (rule 7): the note must not be a constant.

    RED if the ``if not retrieved`` early return is removed — which would tell
    the synthesis model a web search supplied references on a run where none
    ran. The first version of this test asserted absence from the SHARED
    prompt, which went vacuous the moment the note was scoped out of it; a
    mutation proof caught that. It now drives the helper itself."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    answers = _live_answers(attach=[False, False, False, False], monkeypatch=monkeypatch)

    noted = _with_retrieved_note("BASE PROMPT", answers)
    assert noted == "BASE PROMPT", f"claimed a web search on a run that had none: {noted!r}"


def test_the_source_support_section_really_receives_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED if the call site stops passing ``_with_retrieved_note``.

    A mutation proof showed the previous tests pinned the HELPER and never its
    USE: deleting ``_with_retrieved_note(...)`` from the call site left every
    one of them green. This captures the prompt the section is actually handed,
    which is the only thing that reaches a model."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    answers = _live_answers(attach=[True, True, True, True], monkeypatch=monkeypatch)
    debate = debate_stub_service.run_debate_rounds(
        account_id=uuid4(), query_run_id=uuid4(), query_text=QUERY, initial_answers=answers
    )

    seen: list[tuple[str, str]] = []

    def spy(*, system_prompt: str, user_prompt: str, **kw: object) -> None:
        seen.append((system_prompt, user_prompt))
        return None

    monkeypatch.setattr(synthesis_stub_service, "_call_synthesis_model", spy)
    synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text=QUERY,
        initial_answers=answers,
        debate_outputs=debate.debate_outputs,
    )

    assert seen, "precondition: the synthesis sections were dispatched"
    support = [u for sysp, u in seen if "list the sources it cited" in sysp]
    assert support, "precondition: the Source-support section was among them"
    assert "web search this product ran supplied" in support[0], (
        "the Source-support section was handed a prompt with no word for the "
        "retrieved pages listed in it"
    )

    # NEGATIVE PARTNER, same run: every OTHER section must NOT get it.
    others = [u for sysp, u in seen if "list the sources it cited" not in sysp]
    assert others, "precondition: other sections were dispatched too"
    assert not any("web search this product ran supplied" in u for u in others), (
        "the note leaked into another section's prompt — including the "
        "Recommendation, which carries the pause-for-human-review rule"
    )


def _answer(*, provider_path: ProviderPath, sources: list[SourceReference]) -> InitialModelAnswer:
    """One COMPLETED answer with an explicit provider path and source set."""
    return InitialModelAnswer(
        slot_number=1,
        model_id="openai/gpt-4o-mini",
        display_name="GPT-4o mini",
        answer_text="Some answer text.",
        sources=sources,
        provider_attempt_order=[provider_path],
        provider_path=provider_path,
        status=InitialAnswerStatus.COMPLETED,
        fallback_used=provider_path is ProviderPath.FALLBACK_SEARCH,
        latency_ms=120,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=0,
            sourced_answer_ratio=Decimal("0.00"),
            target_met=False,
        ),
    )


def test_a_simulated_answer_is_counted_but_never_called_a_responding_model() -> None:
    """The design decision a guard got wrong, pinned so it is not re-added.

    With a Tavily key and live execution OFF, real retrieved pages attach to a
    SIMULATED answer. A ``model_was_invoked`` guard was added here to stop
    "crediting" them, and measurably made things worse: the chip row and the
    transcript still showed the linked "web search" pages while the prose,
    counting zero, said "No model returned visible source references" — the
    contradiction ADR-0098 exists to remove, recreated by its own fix.

    The objection was about the SENTENCE's subject, not the count. So the count
    describes exactly what the surfaces render, and the sentence says "answers
    on this run" rather than "responding models".

    RED if a ``model_was_invoked`` condition is put back into the counter."""
    retrieved = _retrieved(1)
    simulated = _answer(provider_path=ProviderPath.FALLBACK_SEARCH, sources=retrieved)

    assert count_answers_with_retrieved_sources([simulated]) == 1, (
        "the count must match what the chip row and transcript render, or prose "
        "and pixels disagree by construction"
    )
    # ...and the wording must not claim a model responded.
    note = _with_retrieved_note("BASE", [simulated])
    assert "responding model" not in note


def test_an_invoked_answer_with_a_quorum_stub_is_not_web_search_evidence() -> None:
    """RED if the counter is loosened from ``WEB_SEARCH`` to "has any sources".

    Both guards in ``count_answers_with_retrieved_sources`` are load-bearing and
    neither subsumes the other. ``model_was_invoked`` alone does NOT cover this:
    an INVOKED answer carrying a Quorum-authored stub source would be counted as
    web-search evidence.

    This case was found by enumerating provider-path x source-shape and
    comparing the real counter against the loosened one, after an equivalence
    argument claimed the state was unreachable and the enumeration refuted it.
    Not reachable through ``produce_initial_answer`` today — the live arm never
    attaches a stub — so this pins the invariant rather than a live defect, and
    keeps the second guard from being deleted as redundant."""
    stub = SourceReference(
        title="Local demo evidence for slot 1",
        url="https://example.test/local-demo/1",
        provider=ProviderPath.LOCAL_SIMULATION,
        is_fallback=True,
    )
    invoked_with_stub = _answer(provider_path=ProviderPath.OPENROUTER_SEARCH, sources=[stub])
    assert count_answers_with_retrieved_sources([invoked_with_stub]) == 0, (
        "a Quorum-authored placeholder was counted as a web-search reference"
    )

    # POSITIVE PARTNER: the same INVOKED answer with a real retrieved page does
    # count, so the zero above is the provider check working.
    invoked_with_page = _answer(provider_path=ProviderPath.OPENROUTER_SEARCH, sources=_retrieved(1))
    assert count_answers_with_retrieved_sources([invoked_with_page]) == 1


def test_the_live_note_reports_a_real_fraction_not_the_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED if the live note's count is hardcoded or reads the total.

    Rule 7a, on the artefact that actually reaches production. The sibling test
    drives ``attach=[True] * 4``, where numerator == denominator — so replacing
    ``retrieved`` with ``len(initial_answers)`` or the literal ``4`` survived
    it, and a mutation proof caught that. This drives TWO of four so the two
    terms are constrained independently."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    answers = _live_answers(attach=[True, True, False, False], monkeypatch=monkeypatch)

    noted = _with_retrieved_note("BASE PROMPT", answers)
    assert "2 of the answers cited no source of their own" in noted, (
        f"the note must carry the REAL count, not the total: {noted!r}"
    )
    assert "4 of the answers" not in noted


def test_a_failed_slot_is_in_neither_term_of_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED if the ``answer_count`` guard is dropped from the counter.

    A mutation proof found that deleting it survived the whole suite. A slot
    that produced no text is not an answer, and must not be counted as one that
    'cited no source of its own'."""
    retrieved = _retrieved(1)
    completed = _answer(provider_path=ProviderPath.OPENROUTER_SEARCH, sources=retrieved)
    failed = completed.model_copy(
        update={
            "status": InitialAnswerStatus.FAILED,
            "citation_coverage": CitationCoverage(
                answer_count=0,
                sourced_answer_count=0,
                sourced_answer_ratio=Decimal("0.00"),
                target_met=False,
            ),
        }
    )
    assert failed.sources, "precondition: the failed slot still carries the sources"

    assert count_answers_with_retrieved_sources([failed]) == 0, (
        "a slot that produced no text was counted as an answer"
    )
    # POSITIVE PARTNER: the identical shape that DID produce text still counts.
    assert count_answers_with_retrieved_sources([completed]) == 1
