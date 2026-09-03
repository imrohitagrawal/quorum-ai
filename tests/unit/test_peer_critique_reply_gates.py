"""The gates on ONE critic's reply, and the filter on what counts as a source.

WHAT TURNS EACH TEST RED
------------------------
Named per test. Every assertion here was written against a mutant that survived
the ADR-0096 branch's mutation run (CI run 33732492831) — i.e. against a change
to shipped code that no existing test noticed.

WHY THIS FILE EXISTS
--------------------
The mutation gate scored 271 of 377 mutants on the changed functions and 15
survived. Seven were proved EQUIVALENT by measurement (see
``test_the_peer_ceiling_prices_the_worst_directive`` below). The other eight
were real holes, all of them in code ADR-0096 had just added:

* ``live is None`` — a critic whose call returned NOTHING — was reached by no
  test at all. Replacing the empty string it substitutes with any visible text
  makes that critic read as a ``live`` critique carrying that text, because
  ``parse_moderator_output`` returns a non-JSON reply as prose verbatim
  (measured: ``parse_moderator_output("XXXX")`` -> ``("XXXX", None)``). A slot
  that produced nothing would be reported as one that answered.
* the fallback notice's ``round_number`` could be replaced by ``None`` and
  nothing compared the sentence.
* ``focus_areas=list(FOCUS_AREAS)`` could be deleted on all three return paths;
  the field defaults to ``[]``, so the critique simply lost its focus areas.
* the source filter's ``and`` could become ``or``, which admits a
  whitespace-only string AS A CITED SOURCE and raises ``TypeError`` on a
  non-string (measured, both).

That last one is the one that matters most. ADR-0096 makes sources the currency
of the debate: a position change must cite one. A filter that counts ``"   "``
as a citation is a filter that lets a model buy a position change with nothing.
"""

from __future__ import annotations

from decimal import Decimal

from product_app.debate import (
    DEBATE_MODE_LIVE,
    FOCUS_AREAS,
    ROUND_ONE_SYSTEM_PROMPT,
    ROUND_TWO_SYSTEM_PROMPT,
    DebateOrchestrationService,
    debate_stub_service,
    debate_system_prompt_max_chars,
    parse_peer_convergence,
)
from product_app.model_slots import EXPECTED_SLOT_COUNT
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    LiveProviderResult,
    ProviderPath,
    TokenUsage,
)


def _critic(slot: int) -> InitialModelAnswer:
    return InitialModelAnswer(
        slot_number=slot,
        model_id=f"prov/model-{slot}",
        display_name=f"Model {slot}",
        answer_text=f"Answer from slot {slot}.",
        sources=[],
        provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
        provider_path=ProviderPath.OPENROUTER_SEARCH,
        fallback_used=False,
        status=InitialAnswerStatus.COMPLETED,
        latency_ms=1,
        citation_coverage=CitationCoverage(
            answer_count=1,
            sourced_answer_count=1,
            sourced_answer_ratio=Decimal("1"),
            target_met=True,
        ),
    )


def _reply(text: str) -> LiveProviderResult:
    return LiveProviderResult(
        answer_text=text,
        sources=[],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


def test_a_critic_that_returned_nothing_is_never_reported_as_a_live_critique() -> None:
    """RED when: `text = "" if live is None` substitutes any visible string.

    This is the ``live is None`` path — the critic's call came back with
    nothing. It must read templated and stay at the ``fallback`` mode. With a
    visible substitute the reply survives both ``is_visible`` gates and returns
    ``critique_mode="live"`` with that text as the critique, so a slot that
    produced NOTHING is presented to the reader as one that spoke.

    Also RED when the notice's ``round_number`` argument is replaced by
    ``None``: the sentence is compared verbatim, round number included.
    """
    critique = debate_stub_service._critique_from_reply(
        critic=_critic(3), live=None, round_number=2
    )

    assert critique.critique_text == ("Slot 3 did not return a usable critique for debate round 2.")
    assert critique.critique_mode != DEBATE_MODE_LIVE
    assert critique.critique_mode == "fallback"
    assert critique.stance is None
    assert critique.self_assessment is None
    assert critique.revised_answer == ""
    assert critique.cited_sources == ()
    # The focus areas are carried even on the fallback path, and are not the
    # field's `[]` default.
    assert critique.focus_areas == list(FOCUS_AREAS)
    assert critique.focus_areas != []

    # POSITIVE PARTNER (rule 7): the same call with a real reply DOES produce a
    # live critique, so the assertions above are not passing over a function
    # that always returns a fallback.
    live = debate_stub_service._critique_from_reply(
        critic=_critic(3), live=_reply("Slot 1 overstates the cost figure."), round_number=2
    )
    assert live.critique_mode == DEBATE_MODE_LIVE
    assert live.critique_text == "Slot 1 overstates the cost figure."
    assert live.focus_areas == list(FOCUS_AREAS)


def test_the_round_number_in_the_fallback_notice_is_the_round_that_failed() -> None:
    """RED when: the notice is built with a fixed or `None` round number.

    Two rounds, two different sentences. A reader told a critic failed in
    "round 2" when it failed in round 1 is being told something false about
    which half of the debate is missing.
    """
    one = debate_stub_service._critique_from_reply(critic=_critic(1), live=None, round_number=1)
    two = debate_stub_service._critique_from_reply(critic=_critic(1), live=None, round_number=2)

    assert one.critique_text.endswith("debate round 1.")
    assert two.critique_text.endswith("debate round 2.")
    assert one.critique_text != two.critique_text


def test_a_reply_that_parses_to_nothing_showable_reads_templated_with_focus_areas() -> None:
    """RED when: `focus_areas=list(FOCUS_AREAS)` is dropped from the second
    fallback return (the one taken after `parse_moderator_output`).

    Distinct path from the test above: here the critic DID reply, and the reply
    parsed to nothing showable. `focus_areas` defaults to `[]`, so deleting the
    argument is silent.
    """
    # A reply that is VISIBLE as raw text but parses to empty prose. `"   "`
    # would not do: it is caught by the FIRST is_visible gate and returns from
    # the path the test above already covers, leaving this one green over the
    # wrong branch. Measured: parse_moderator_output('{"critique": ""}')
    # -> ('', None).
    critique = debate_stub_service._critique_from_reply(
        critic=_critic(2), live=_reply('{"critique": ""}'), round_number=1
    )

    assert critique.critique_text == ("Slot 2 did not return a usable critique for debate round 1.")
    assert critique.focus_areas == list(FOCUS_AREAS)
    assert critique.focus_areas != []


def test_a_blank_string_is_not_a_cited_source() -> None:
    """RED when: the source filter's `and` becomes `or`.

    Measured on the mutant: `isinstance("   ", str) or is_visible("   ")` is
    True, so a whitespace-only string is admitted as a citation; and
    `isinstance(5, str) or is_visible(5)` raises TypeError, so a provider
    returning a number in `sources` takes the whole parse down.

    This is the evidence path. ADR-0096 lets a model change its position only
    by citing a source; a blank that counts as a source is a position change
    bought with nothing.
    """
    parsed = parse_peer_convergence(
        '{"self_assessment": "changed", "rationale": "The figure was stale.",'
        ' "sources": ["   ", "", "https://example.org/report", "\\t\\n"],'
        ' "revised_answer": "Pick option B."}'
    )

    # POSITIVE PARTNER: the real URL survives, so this is not asserting
    # emptiness over a parser that drops everything.
    assert parsed.sources == ("https://example.org/report",)
    assert parsed.self_assessment == "changed"
    assert parsed.revised_answer == "Pick option B."

    # A non-string in the list is skipped, not raised on.
    mixed = parse_peer_convergence('{"sources": [5, null, {"url": "x"}, "https://example.org/ok"]}')
    assert mixed.sources == ("https://example.org/ok",)


def test_the_peer_directive_tells_a_critic_to_assess_its_own_answer() -> None:
    """RED when: the sentence's wording or emphasis changes.

    ADR-0096 replaced "Do not defend or restate your own answer" — which
    forbade the one behaviour that lets a panel converge — with this. The
    capitalisation is load-bearing instruction emphasis, not decoration: it is
    what distinguishes "assess the others" from "assess the others AND
    yourself". Pinned verbatim because this string IS the behaviour change; the
    negative check below is the assertion that the old instruction is gone.
    """
    directive = DebateOrchestrationService._peer_critic_directive(slot_number=2, round_number=1)

    assert "Apply the lens above to the OTHER answers AND to your own." in directive
    assert "Do not simply restate your answer; assess it." in directive
    assert "You are the model that wrote Slot 2's answer." in directive
    # The instruction ADR-0096 removed, and its partner above proving the
    # replacement is present (rule 7 — a negative check alone is trivially true).
    assert "Do not defend or restate your own answer" not in directive


def test_the_peer_ceiling_prices_the_worst_directive() -> None:
    """RED when: the ceiling stops covering the longest directive.

    Also the RECORD of why seven mutants on `debate_system_prompt_max_chars`
    survived and are not defects. Measured 2026-09-03 on this tree:

        round 1: every slot 0..5 -> 152 chars
        round 2: every slot 0..5 -> 1106 chars
        round 3: every slot 0..5 -> 1106 chars

    The directive's length does not vary with the slot number at all (the panel
    is single-digit), and any round other than 1 takes the round-2 branch. So
    every mutation of the slot `range(...)` bounds, and of the round tuple that
    keeps a non-1 member, computes the SAME maximum. They are equivalent
    mutants: no test can kill them, and this file does not pretend to.

    The `max(...)` is kept rather than replaced by a single call, because it is
    what keeps the ceiling correct if the panel ever grows past nine slots.
    These two assertions are the invariant that makes the equivalence true, so
    the day it stops being true, this goes red rather than the ceiling silently
    under-pricing.
    """
    d = DebateOrchestrationService._peer_critic_directive
    slots = range(1, EXPECTED_SLOT_COUNT + 1)
    round_one_lengths = {len(d(slot_number=s, round_number=1)) for s in slots}
    round_two_lengths = {len(d(slot_number=s, round_number=2)) for s in slots}

    # Slot-invariant across the whole reachable panel...
    assert len(round_one_lengths) == 1
    assert len(round_two_lengths) == 1
    # ...and round 2 is strictly the longer, because it carries the convergence
    # contract. This is the ordering the ceiling depends on.
    assert round_two_lengths.pop() > round_one_lengths.pop()
    # The panel is single-digit, which is WHY the slot number cannot change the
    # length. If this ever fails, the equivalence argument above dies with it.
    assert EXPECTED_SLOT_COUNT < 10

    # And the ceiling itself covers prompt + worst directive, not prompt alone.
    longest_prompt = max(len(ROUND_ONE_SYSTEM_PROMPT), len(ROUND_TWO_SYSTEM_PROMPT))
    peer = debate_system_prompt_max_chars(peer=True)
    assert peer == longest_prompt + len(d(slot_number=1, round_number=2))
    assert peer > debate_system_prompt_max_chars(peer=False) == longest_prompt
