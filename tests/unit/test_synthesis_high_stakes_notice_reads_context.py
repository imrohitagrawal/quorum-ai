"""Issue #155, third bullet — the OUTPUT must agree with the enforcement.

``synthesis._high_stakes_required`` scanned ``query_text`` only, so a user
who was FORCED to acknowledge high stakes because of ``context`` wording
still got ``high_stakes_notice: None`` back. The route demanded the ack; the
thing the ack exists to produce then said the run was not high-stakes.

This file exists because correctness review measured that the fix for that
bullet shipped with **zero** coverage: reverting ``context=context`` at
``synthesis.py``'s ``_high_stakes_required(...)`` call left the entire suite
green. A behavioural change with no test that would fail without it is not
finished (AGENTS.md rule 6).

Drives the real ``produce_final_synthesis`` seam rather than the private
predicate, so it fails if the wiring between them is dropped — which is
exactly the line that was untested.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from product_app.debate import DebateOutput, DebateRoundStatus
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
)
from product_app.synthesis import synthesis_stub_service

_BENIGN = "Follow up on the earlier discussion please."
_HOSTILE = "What is the right medical diagnosis and legal contract for my investment loan?"


def _answers() -> list[InitialModelAnswer]:
    return [
        InitialModelAnswer(
            slot_number=n,
            model_id=f"vendor/model-{n}",
            answer_text="An answer.",
            sources=[
                SourceReference(
                    title="s",
                    url="https://example.com",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                )
            ],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.COMPLETED,
            latency_ms=10,
            citation_coverage=CitationCoverage(
                answer_count=1,
                sourced_answer_count=1,
                sourced_answer_ratio=Decimal("1"),
                target_met=True,
            ),
        )
        for n in range(1, 5)
    ]


def _debate_outputs() -> list[DebateOutput]:
    return [
        DebateOutput(
            round_number=n,
            focus_areas=["disagreement"],
            critique_text="critique",
            status=DebateRoundStatus.COMPLETED,
        )
        for n in (1, 2)
    ]


def _notice(query_text: str, context: dict[str, str] | None) -> str | None:
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text=query_text,
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        context=context,
    )
    assert result.final_synthesis is not None, (
        "precondition: the stub service always produces a synthesis; a None "
        "here would make every assertion below vacuous"
    )
    return result.final_synthesis.high_stakes_notice


def test_a_benign_query_with_no_context_carries_no_notice() -> None:
    """The no-false-fire partner. Without it, a synthesis that attached the
    notice unconditionally would satisfy every assertion below."""
    assert _notice(_BENIGN, None) is None


def test_a_hostile_query_text_carries_the_notice() -> None:
    """The pre-existing contract, unchanged — so the context work cannot be
    credited for behaviour that already worked."""
    assert _notice(_HOSTILE, None) is not None


def test_hostile_wording_in_prior_synthesis_carries_the_notice() -> None:
    """The fix. Before it, this run was REFUSED without a high-stakes ack and
    then produced output claiming it was not high-stakes.

    Turns red if: ``context=context`` is dropped from the
    ``_high_stakes_required(...)`` call in ``produce_final_synthesis``.
    """
    assert _notice(_BENIGN, {"prior_synthesis": _HOSTILE}) is not None


def test_hostile_wording_in_prior_question_carries_the_notice() -> None:
    """Both context fields reach a prompt, so both must reach the notice."""
    assert _notice(_BENIGN, {"prior_question": _HOSTILE}) is not None


def test_this_apps_own_caveat_in_context_does_not_trigger_the_notice() -> None:
    """The discriminator has to hold here too, or every ordinary follow-up
    gets a high-stakes notice it did not earn — the same false positive that
    got the first attempt at this issue reverted, one layer down."""
    from product_app.synthesis import HIGH_STAKES_NOTICE_FRAGMENT

    prior = f"The rollout succeeded. {HIGH_STAKES_NOTICE_FRAGMENT}"
    assert _notice(_BENIGN, {"prior_synthesis": prior}) is None
