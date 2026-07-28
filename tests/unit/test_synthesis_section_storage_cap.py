"""WP-F — a synthesis section the user is BILLED for is not thrown away.

``SYNTHESIS_SECTION_MAX_TOKENS`` is 3000, and the cost model prices every
section call at that ceiling on both the point estimate and the fail-safe
bound. A 3000-token section is roughly 12_000 characters. The storage cap
``DEFAULT_SECTION_MAX_CHARS`` was 4000, so about two thirds of the output the
account pays for was generated, billed, and then discarded before anyone could
read it — silently, with a "…" as the only trace.

The two numbers describe the same thing and must be derived from one source,
or they drift apart exactly like this again. The cap is now computed from the
generation ceiling and ``CHARS_PER_TOKEN``, the way the excerpt sizes already
are; nothing hardcodes 4000 or 12_000.

This pins a property rather than a number: what the model was paid to produce
survives to the user.

Two limits stated rather than implied:

* ``CHARS_PER_TOKEN`` is the industry ~4-chars/token RULE OF THUMB (see
  ``costs.py``), not a bound. Prose denser than that — long words, heavy
  Markdown — can still exceed 12_000 characters at 3000 tokens and still be
  cut, with the ``…`` as the only trace. The derivation removes drift between
  two literals; it does not make tokens and characters the same quantity.
* The Recommendation section is NOT covered here. It keeps the tighter
  ``RECOMMENDATION_MAX_CHARS`` (2000) that protects the mandatory
  decision-support caveat, while being billed at the same 3000-token ceiling —
  so the "billed then discarded" leak is still live for that one section.
  Filed rather than fixed: raising it means reworking the caveat-protection
  arithmetic, which is a separate change.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from product_app import config
from product_app.debate import debate_stub_service
from product_app.model_slots import DEFAULT_MODEL_IDS, validate_model_slots
from product_app.providers import provider_execution_service, provider_stub_service
from product_app.synthesis import (
    SYNTHESIS_SECTION_MAX_CHARS,
    SYNTHESIS_SECTION_MAX_TOKENS,
    synthesis_stub_service,
)


def test_the_storage_cap_matches_what_the_run_is_billed_to_generate() -> None:
    """The cap is derived, not guessed.

    ``cost_synthesis_output_tokens`` is what each section call is PRICED at,
    so the number of characters that survive must correspond to it.
    """
    from product_app.costs import CHARS_PER_TOKEN

    # Restating the definition (`== int(TOKENS * CHARS_PER_TOKEN)`) would be a
    # tautology — it re-evaluates the right-hand side of the assignment and
    # cannot fail. Assert the PROPERTY instead: the cap must be at least the
    # output the run is billed for, at the documented ratio. That fails if the
    # cap is lowered, hardcoded back to 4000, or decoupled from the ceiling.
    billed_chars = SYNTHESIS_SECTION_MAX_TOKENS * int(CHARS_PER_TOKEN)
    assert billed_chars <= SYNTHESIS_SECTION_MAX_CHARS, (
        f"the storage cap ({SYNTHESIS_SECTION_MAX_CHARS}) is below the output "
        f"each section call is billed for (~{billed_chars} chars)."
    )
    assert config.settings.cost_synthesis_output_tokens == SYNTHESIS_SECTION_MAX_TOKENS


def test_a_full_length_billed_section_is_not_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from product_app.providers import LiveProviderResult

    # A section exactly as long as the run pays to generate. Sentence-shaped,
    # so the soft truncation has natural boundaries to cut at — if it cuts, it
    # is not because the text gave it no choice.
    sentence = "The panel reviewed the evidence and agreed on the sequencing. "
    long_section = (sentence * ((SYNTHESIS_SECTION_MAX_CHARS // len(sentence)) + 2))[
        :SYNTHESIS_SECTION_MAX_CHARS
    ]
    assert len(long_section) == SYNTHESIS_SECTION_MAX_CHARS

    def fake_call(**kwargs: object) -> LiveProviderResult | None:
        return LiveProviderResult(answer_text=long_section, sources=[])

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", fake_call)
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)

    account_id = uuid4()
    query_run_id = uuid4()
    model_slots = validate_model_slots(list(DEFAULT_MODEL_IDS))
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
    for name in ("consensus", "disagreement", "source_support", "uncertainty"):
        stored = getattr(result.final_synthesis, name)
        assert stored == long_section, (
            f"the {name} section was cut from {len(long_section)} to "
            f"{len(stored)} chars. The run is billed for "
            f"{SYNTHESIS_SECTION_MAX_TOKENS} output tokens on this call; "
            "discarding what it paid for is not a length policy, it is a leak."
        )
        assert not stored.endswith("…")
