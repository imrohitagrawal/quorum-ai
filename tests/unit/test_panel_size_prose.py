"""W4, second pull request: a panel of two or three is accepted and described by its size.

ADR-0120 decision 5 deferred the served prose: writing "Four models were asked"
from ``len(initial_answers)`` mis-counts a run whose slot never recorded. The
count the prose needs is the REQUESTED panel size, which the orchestrator
knows (``len(query_run.model_slots)``) and now hands to ``synthesis.py`` and
``debate.py`` as ``panel_size``. At four every string is byte-identical to
what shipped, which the literal pins below prove; at two and three the word
changes and nothing else does.

Every test names what turns it red.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from product_app.debate import (
    ROUND_ONE_SYSTEM_PROMPT,
    ROUND_TWO_SYSTEM_PROMPT,
    debate_stub_service,
    debate_system_prompt_max_chars,
    round_one_system_prompt,
)
from product_app.model_slots import (
    EXPECTED_SLOT_COUNT,
    MAX_SLOT_COUNT,
    MIN_SLOT_COUNT,
    InvalidModelSlotError,
    ModelSlot,
    _validate_model_id_list,
    default_model_slots,
    panel_size_word,
)
from product_app.providers import (
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    provider_execution_service,
)
from product_app.synthesis import (
    _CONSENSUS_PROMPT,
    _DISAGREEMENT_PROMPT,
    _SOURCE_SUPPORT_PROMPT,
    _UNCERTAINTY_PROMPT,
    _consensus_prompt,
    _disagreement_prompt,
    _source_support_prompt,
    _uncertainty_prompt,
    synthesis_stub_service,
)

MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "x-ai/grok-4-fast",
]

RANGE_MESSAGE = "Between 2 and 4 model slots are required."

#: The validator cross-checks ids against the catalog, so the count tests use
#: the curated defaults (accepted even on a catalog outage); the prose tests
#: below only need the provider's demo output and use MODEL_IDS.
CATALOG_IDS = [slot.model_id for slot in default_model_slots()]


# ---------------------------------------------------------------------------
# The validator: the one line PR 1 left at "exactly four"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [2, 3, 4])
def test_two_three_and_four_slots_are_accepted(count: int) -> None:
    """RED before this change at 2 and 3: ``_validate_model_id_list`` raised
    "Exactly four model slots are required."."""
    _validate_model_id_list(CATALOG_IDS[:count])


@pytest.mark.parametrize("count", [0, 1, 5])
def test_outside_two_to_four_is_refused_with_the_range_message(count: int) -> None:
    """RED if the range check is dropped (5 accepted) or the message keeps
    saying "Exactly four". Board row W4 pins the literal message."""
    ids = (CATALOG_IDS + ["mistralai/mistral-small"])[:count]
    with pytest.raises(InvalidModelSlotError) as exc_info:
        _validate_model_id_list(ids)
    first = exc_info.value.errors[0]
    assert first.slot_number == 0
    assert first.message == RANGE_MESSAGE


def test_the_range_message_is_derived_from_the_shipped_bounds() -> None:
    """Literals on both sides (rule 7a): the message names 2 and 4, and those
    are the shipped bounds. RED if either constant moves without the copy."""
    assert (MIN_SLOT_COUNT, MAX_SLOT_COUNT) == (2, 4)
    expected = f"Between {MIN_SLOT_COUNT} and {MAX_SLOT_COUNT} model slots are required."
    assert expected == RANGE_MESSAGE


def test_duplicate_message_no_longer_names_four() -> None:
    """RED while the uniqueness message says "across all four slots" — false
    on a panel of two."""
    with pytest.raises(InvalidModelSlotError) as exc_info:
        _validate_model_id_list([CATALOG_IDS[0], CATALOG_IDS[0]])
    messages = [error.message for error in exc_info.value.errors]
    assert "Model IDs must be unique across all slots." in messages
    assert not any("four" in message for message in messages)


# ---------------------------------------------------------------------------
# The word map
# ---------------------------------------------------------------------------


def test_panel_size_word_is_a_literal_table() -> None:
    """RED if the map is generated (``str(n)``) or a word is misspelt.
    Byte-identical at four is the whole contract: "Four" is what shipped."""
    assert panel_size_word(2) == "Two"
    assert panel_size_word(3) == "Three"
    assert panel_size_word(4) == "Four"
    assert panel_size_word(EXPECTED_SLOT_COUNT) == "Four"


def test_panel_size_word_refuses_a_size_outside_the_range() -> None:
    """A size the validator never admits must not silently become "5" in
    served prose. RED if the helper falls back to ``str(n)``."""
    with pytest.raises(ValueError, match="panel size"):
        panel_size_word(5)
    with pytest.raises(ValueError, match="panel size"):
        panel_size_word(1)


# ---------------------------------------------------------------------------
# Synthesis: served prose and section prompts
# ---------------------------------------------------------------------------


def _live_answers(count: int) -> list[InitialModelAnswer]:
    """``count`` answers from the real provider (no key), relabelled live so the
    templated prose reaches the strength branches, as
    ``test_not_invoked_is_not_evidence`` does."""
    slots = [
        ModelSlot(slot_number=index + 1, model_id=model_id, search=True)
        for index, model_id in enumerate(MODEL_IDS[:count])
    ]
    answers = provider_execution_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="What is the capital of France?",
        model_slots=slots,
        openrouter_key="",
    )
    return [
        answer.model_copy(update={"provider_path": ProviderPath.OPENROUTER_SEARCH})
        for answer in answers
    ]


def _synthesis(count: int, **kwargs: object):  # type: ignore[no-untyped-def]
    result = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="What is the capital of France?",
        initial_answers=_live_answers(count),
        debate_outputs=[],
        **kwargs,  # type: ignore[arg-type]
    )
    assert result.final_synthesis is not None
    return result.final_synthesis


def test_synthesis_prose_at_four_is_byte_identical_to_what_shipped() -> None:
    """Positive partner for every N=2/3 assertion below: with no ``panel_size``
    given, the prose still opens exactly as it did on ``12b1e51``. RED if the
    default moves off four or the sentence is reworded."""
    synthesis = _synthesis(4)
    assert "Four models were asked the same question;" in synthesis.consensus
    assert "Four models were asked the same question;" in _synthesis(4, panel_size=4).consensus


def test_synthesis_prose_names_the_requested_panel_size() -> None:
    """RED before the change: every branch said "Four models were asked" no
    matter how many were requested."""
    two = _synthesis(2, panel_size=2)
    assert "Two models were asked the same question;" in two.consensus
    assert "Four models" not in two.consensus
    three = _synthesis(3, panel_size=3)
    assert "Three models were asked the same question;" in three.consensus


def test_synthesis_prose_counts_the_requested_size_not_the_recorded_answers() -> None:
    """ADR-0120 decision 5: a run that requested four and recorded three says
    four were asked. RED if the prose reads ``len(initial_answers)``."""
    synthesis = synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="What is the capital of France?",
        initial_answers=_live_answers(3),
        debate_outputs=[],
        panel_size=4,
    ).final_synthesis
    assert synthesis is not None
    assert "Four models were asked the same question; 3 returned" in synthesis.consensus


def test_uncertainty_prose_says_both_at_two() -> None:
    """ "All two models" is not English. RED if the N=2 branch says it, or if
    the four-form is reworded (positive partner)."""
    assert "All four models returned a usable response" in _synthesis(4).uncertainty
    assert "Both models returned a usable response" in _synthesis(2, panel_size=2).uncertainty
    assert "All three models returned a usable response" in _synthesis(3, panel_size=3).uncertainty


def test_section_prompts_at_four_are_the_shipped_constants() -> None:
    """The five module constants are what ``test_untrusted_text_fencing`` and
    ``test_usage_threading`` compare against. RED if the four-form generated
    prompt drifts from them by a byte."""
    assert _consensus_prompt(4) == _CONSENSUS_PROMPT
    assert _disagreement_prompt(4) == _DISAGREEMENT_PROMPT
    assert _source_support_prompt(4) == _SOURCE_SUPPORT_PROMPT
    assert _uncertainty_prompt(4) == _UNCERTAINTY_PROMPT
    assert "Given the four model answers below" in _CONSENSUS_PROMPT


def test_section_prompts_name_the_panel_size() -> None:
    """RED if a section prompt keeps "four" at N=2."""
    assert "Given the two model answers below" in _consensus_prompt(2)
    assert "Given the three model answers below" in _disagreement_prompt(3)
    assert "For each of the two model answers" in _source_support_prompt(2)
    assert "Given the two model answers and the debate rounds" in _uncertainty_prompt(2)
    for prompt in (
        _consensus_prompt(2),
        _disagreement_prompt(2),
        _source_support_prompt(2),
        _uncertainty_prompt(2),
    ):
        assert "four" not in prompt


def test_synthesis_user_prompt_labels_the_evidence_block_by_panel_size() -> None:
    """The "Four model answers (model name, status, first N chars):" line is
    the forgery anchor ``test_context_carry`` pins. RED if it stays "Four" at
    N=2, or if the four-form changes (positive partner)."""
    from decimal import Decimal

    prompt_two = synthesis_stub_service._user_prompt(
        initial_answers=_live_answers(2),
        debate_outputs=[],
        failed_count=0,
        coverage_ratio=Decimal("1"),
        coverage_target_met=True,
        panel_size=2,
    )
    assert "Two model answers (model name, status, first" in prompt_two
    prompt_four = synthesis_stub_service._user_prompt(
        initial_answers=_live_answers(4),
        debate_outputs=[],
        failed_count=0,
        coverage_ratio=Decimal("1"),
        coverage_target_met=True,
    )
    assert "Four model answers (model name, status, first" in prompt_four


# ---------------------------------------------------------------------------
# Debate: the round-one system prompt, the user prompt and the ceiling
# ---------------------------------------------------------------------------


def test_round_one_system_prompt_at_four_is_the_shipped_constant() -> None:
    """``ROUND_ONE_SYSTEM_PROMPT`` is compared by identity of text in three
    test modules and priced by the cost layer. RED if the generated four-form
    differs from it by a byte, or the constant no longer opens with "Four"."""
    assert round_one_system_prompt(4) == ROUND_ONE_SYSTEM_PROMPT
    assert ROUND_ONE_SYSTEM_PROMPT.startswith(
        "Four models were asked the same question independently."
    )


def test_round_one_system_prompt_names_the_panel_size() -> None:
    """RED before the change: the moderator was always told four models."""
    assert round_one_system_prompt(2).startswith(
        "Two models were asked the same question independently."
    )
    assert round_one_system_prompt(3).startswith(
        "Three models were asked the same question independently."
    )
    # Only the opening word moves.
    assert round_one_system_prompt(2)[len("Two") :] == ROUND_ONE_SYSTEM_PROMPT[len("Four") :]


def test_debate_prompt_ceiling_covers_every_panel_size() -> None:
    """ "Three" is one character longer than "Four". The ceiling the cost layer
    prices from must cover the longest reachable prompt. RED if the ceiling is
    computed from the four-form only AND round one ever overtakes round two."""
    longest_round_one = max(
        len(round_one_system_prompt(n)) for n in range(MIN_SLOT_COUNT, MAX_SLOT_COUNT + 1)
    )
    assert longest_round_one == len(ROUND_ONE_SYSTEM_PROMPT) + 1
    assert debate_system_prompt_max_chars(peer=False) >= longest_round_one
    assert debate_system_prompt_max_chars(peer=False) >= len(ROUND_TWO_SYSTEM_PROMPT)


def test_debate_user_prompt_labels_the_evidence_block_by_panel_size() -> None:
    """RED if ``_debate_user_prompt`` keeps "Four model answers" at N=3."""
    prompt = debate_stub_service._debate_user_prompt(
        query_text="What is the capital of France?",
        initial_answers=_live_answers(3),
        prior_round=None,
        panel_size=3,
    )
    assert "Three model answers (model name, status, first" in prompt
    assert "the three model answers are in the evidence block" in prompt
    default = debate_stub_service._debate_user_prompt(
        query_text="What is the capital of France?",
        initial_answers=_live_answers(4),
        prior_round=None,
    )
    assert "Four model answers (model name, status, first" in default
    assert "the four model answers are in the evidence block" in default


def test_weak_support_line_says_both_at_two() -> None:
    """The templated critique's "All four models returned at least one source
    reference" is served. RED if it stays "four" at N=2."""
    sourced = [
        answer.model_copy(update={"sources": answer.sources or [_a_source()]})
        for answer in _live_answers(2)
    ]
    line = debate_stub_service._extract_weak_support(initial_answers=sourced, panel_size=2)
    assert line.startswith("Both models returned at least one source reference")
    four = [
        answer.model_copy(update={"sources": answer.sources or [_a_source()]})
        for answer in _live_answers(4)
    ]
    assert debate_stub_service._extract_weak_support(initial_answers=four).startswith(
        "All four models returned at least one source reference"
    )


def _a_source() -> SourceReference:
    return SourceReference(
        title="A source", url="https://example.com/a", provider=ProviderPath.OPENROUTER_SEARCH
    )
