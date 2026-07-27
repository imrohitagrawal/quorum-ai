"""F-06 (finding D): the RELOCATED blank-text guard, asserted for all 7 builders.

F-06 moved the "the live output is unusable" decision OUT of
``_call_debate_model`` / ``_call_synthesis_model`` — where returning ``None``
made the templated branch structurally unavoidable — and INTO the seven
builders as ``if not text:``. That guard is now the ONLY thing standing between
a blank provider completion and an empty section shipped to a user, and nothing
in the suite asserted it: three separate mutations that delete it survived the
whole unit + integration run.

There are seven guards (2 debate rounds + 5 synthesis sections) and each is
covered below, because covering one proves nothing about the other six. Every
test drives the REAL orchestrators; only the provider seam is faked.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from product_app import config
from product_app.debate import DebateOutput, DebateRoundStatus, debate_stub_service
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    SourceReference,
    TokenUsage,
    provider_execution_service,
)
from product_app.synthesis import (
    TEMPLATED_FALLBACK_PREFIX,
    SynthesisResult,
    synthesis_stub_service,
)

_USAGE = TokenUsage(prompt_tokens=4000, completion_tokens=700, total_tokens=4700)

#: Whitespace-only and truly-empty both have to be caught: the first is what a
#: model that emitted only a newline before hitting the token cap returns, the
#: second is what ``call_with_prompt`` synthesises for a dispatched-but-
#: unmeasured call (5xx, timeout, torn body).
_BLANK_TEXTS = ["", "   \n  ", "\t"]


def _answers() -> list[InitialModelAnswer]:
    return [
        InitialModelAnswer(
            slot_number=slot,
            model_id=f"vendor/model-{slot}",
            display_name=f"Model {slot}",
            answer_text=f"Answer from model {slot} with a concrete claim.",
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
                material_claim_count=1,
                cited_claim_count=1,
                coverage_ratio=Decimal("1"),
                target_met=True,
            ),
            token_usage=_USAGE,
        )
        for slot in (1, 2, 3, 4)
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


def _sections(result: SynthesisResult) -> list[tuple[str, str]]:
    """The five section texts, labelled, with the synthesis proved non-``None``."""
    synthesis = result.final_synthesis
    assert synthesis is not None, "the synthesis must be built, not skipped"
    return [
        ("consensus", synthesis.consensus),
        ("disagreement", synthesis.disagreement),
        ("source_support", synthesis.source_support),
        ("uncertainty", synthesis.uncertainty),
        ("recommendation", synthesis.recommendation),
    ]


def _blank_live(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Every dispatched call is billed and comes back with no usable text."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(
        provider_execution_service,
        "call_with_prompt",
        lambda **_kwargs: LiveProviderResult(answer_text=text, sources=[], usage=_USAGE),
    )


# --- the 2 debate-round guards ----------------------------------------------


@pytest.mark.parametrize("text", _BLANK_TEXTS)
def test_both_debate_rounds_serve_the_templated_critique_on_blank_live_text(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    _blank_live(monkeypatch, text)
    result = debate_stub_service.run_debate_rounds(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        openrouter_key="sk-or-test-live",
    )
    critiques = [output.critique_text for output in result.debate_outputs]
    assert len(critiques) == 2
    # Guard 1/7 and 2/7: each round's own templated body, not the blank text
    # and not a copy of the other round's.
    assert critiques[0].startswith("Round 1 critique.")
    assert "Disagreement:" in critiques[0]
    assert critiques[1].startswith("Round 2 critique, refining round 1.")
    assert "Refined disagreement:" in critiques[1]
    # ...and the billed calls are still recorded, which is the whole point of
    # returning the result instead of ``None``.
    assert result.live_call_usages == [(1, _USAGE), (2, _USAGE)]


# --- the 5 synthesis-section guards ------------------------------------------


@pytest.mark.parametrize("text", _BLANK_TEXTS)
def test_all_five_synthesis_sections_serve_templated_text_on_blank_live_text(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    _blank_live(monkeypatch, text)
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="sk-or-test-live",
    )
    sections = _sections(result)
    # Guards 3/7 .. 7/7, one assertion pair each.
    for label, section in sections:
        assert section.strip(), f"{label}: an EMPTY section was served to the user"
        assert section.startswith(TEMPLATED_FALLBACK_PREFIX), (
            f"{label}: served without the templated-fallback marker: {section!r}"
        )
    # The recommendation's mandated framing must survive the fallback.
    assert "decision support only" in dict(sections)["recommendation"]
    assert result.failed_steps == []
    assert result.live_call_usages == [_USAGE] * 5


def test_synthesis_with_live_enabled_but_no_key_dispatches_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The credential guard is a NOT-BILLED exit, and must stay one.

    Live execution is ON, so this isolates the second guard in
    ``_call_synthesis_model`` from the operator opt-in above it. No request
    leaves the process, so recording an entry here would be the mirror of the
    F-06 defect: it would downgrade a perfectly measurable run to ``estimated``
    over calls that were never made.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)

    def _never(**_kwargs: object) -> None:
        raise AssertionError("no request may be dispatched without a key")

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _never)

    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="",
    )
    assert result.live_call_usages == []
    for label, section in _sections(result):
        assert section.startswith(TEMPLATED_FALLBACK_PREFIX), f"{label} was not templated"


# --- the honesty consequence of a LONGER usage list --------------------------


def test_a_fully_templated_run_is_never_presented_as_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run whose every section fell back must not read as a live synthesis.

    F-06 makes the usage lists LONGER (a dispatched-but-unusable call now
    records an entry where it previously recorded nothing), so any "was this
    live?" signal derived from ``len(live_call_usages)`` flips to "live" on a
    run that served nothing but templated prose. This pins the collision at the
    unit level — five entries alongside five templated sections — so the count
    can never be mistaken for a liveness signal. The SERVED labels are asserted
    end-to-end in
    ``tests/integration/test_blank_live_run_labelling.py``.
    """
    _blank_live(monkeypatch, "")
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="sk-or-test-live",
    )
    # Five entries recorded (billing honesty) ...
    assert len(result.live_call_usages) == 5
    # ... over five sections that are ALL templated (content honesty).
    sections = [text for _label, text in _sections(result)]
    assert all(section.startswith(TEMPLATED_FALLBACK_PREFIX) for section in sections)
    assert len([s for s in sections if s.startswith(TEMPLATED_FALLBACK_PREFIX)]) == len(
        result.live_call_usages
    ), (
        "entry count and templated-section count coincide here, which is exactly "
        "why entry count must never be read as a liveness signal"
    )


def test_control_usable_live_text_is_served_over_the_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTROL: the guards above must not fire on usable output.

    Without this, deleting the live path entirely would pass every test in
    this file.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr(
        provider_execution_service,
        "call_with_prompt",
        lambda **_kwargs: LiveProviderResult(
            answer_text="A substantive live paragraph.", sources=[], usage=_USAGE
        ),
    )
    debate = debate_stub_service.run_debate_rounds(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        openrouter_key="sk-or-test-live",
    )
    assert [o.critique_text for o in debate.debate_outputs] == ["A substantive live paragraph."] * 2
    synthesis = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="sk-or-test-live",
    )
    for label, section in _sections(synthesis):
        assert "A substantive live paragraph." in section, label
        assert not section.startswith(TEMPLATED_FALLBACK_PREFIX), label
