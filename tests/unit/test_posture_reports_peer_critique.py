"""The posture watchdog must be able to see the expensive debate shape.

WHAT TURNS EACH TEST RED
------------------------
Named per test.

WHY THIS FILE EXISTS
--------------------
Measured 2026-09-03, on the deploy that turned peer critique on in production
(``6d13643``): ``grep -n peer_critique scripts/live_posture_check.py`` returned
NOTHING. The watchdog scheduled every 30 minutes against production, whose whole
purpose is to notice an unattended paid posture, could not see the flag that
replaces 2 moderator debate calls with up to 8 critic calls at four models'
prices.

REPORTED, NOT ALERTED — and the asymmetry with the judge is deliberate
(ADR-0097). The judge gets its own per-window ``"judge": true`` declaration
because its GET-path spend reaches NO ledger (ADR-0013), so nothing else binds
it. Critique spend is inside the run charge and every critic call routes
through ``_call_debate_model``, which returns ``None`` unless live execution is
on — so the live-window gate that already exists binds the money. Requiring a
new per-window field would also have invalidated the window that was open when
this was written, taking the watchdog red on a CORRECT posture, which is how a
watchdog gets muted.

So: never silent, never crying wolf.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest
from tests.unit.test_live_posture_check import (
    _FUTURE_SHUT,
    _HOST_A,
    _HOST_B,
    _NOW,
    _NOW_OPEN,
    _NOW_SHUT,
    _OLD_OPEN,
    _OLD_SHUT,
    SHIPPED_WINDOWS,
    _ready_stub,
    _standing,
    _window,
    posture,
)

__all__ = ["posture"]


def test_the_posture_names_peer_critique_when_it_is_on(posture: ModuleType) -> None:
    """RED IF: the watchdog stops reporting peer critique.

    What turns it red: drop ``peer_states`` from ``evaluate_posture``, or stop
    appending the note to the detail line. This is the operator's ONE signal
    that the 8-call debate shape is live.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)],
        now=_NOW,
        judge_states={_HOST_B: False},
        peer_states={_HOST_B: True},
    )
    assert "peer_critique_enabled=true" in result.detail


def test_peer_critique_on_is_reported_but_never_alerts_on_its_own(
    posture: ModuleType,
) -> None:
    """RED IF: peer critique starts alerting by itself.

    A watchdog that goes red on a correct, declared, attended posture is a
    watchdog somebody mutes. The money is already bound by the live-window gate
    (ADR-0097), so this field informs and does not escalate.

    POSITIVE PARTNER below: the same call with an UNDECLARED judge DOES alert,
    proving this assertion is not passing over a function that never alerts.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, judge=False)
    quiet = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        judge_states={_HOST_B: False},
        peer_states={_HOST_B: True},
    )
    assert quiet.should_alert is False
    assert "peer_critique_enabled=true" in quiet.detail

    loud = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        judge_states={_HOST_B: True},
        peer_states={_HOST_B: True},
    )
    assert loud.should_alert is True
    assert loud.decision is posture.PostureDecision.LIVE_JUDGE_UNDECLARED
    # THE LINE THIS TEST WAS MISSING. It built this exact result and stopped
    # here, so it stayed green while LIVE_JUDGE_UNDECLARED — the alert about an
    # undeclared paid subsystem on a live money-spending posture — carried no
    # peer state at all. Adversarial review found it by enumerating the return
    # sites; the test that constructed the failing case did not look at it.
    assert "peer_critique_enabled=true" in loud.detail


def test_an_unreadable_peer_state_is_never_reported_as_off(
    posture: ModuleType,
) -> None:
    """RED IF: an unreadable value is coerced to False.

    "off" is a claim about a paid subsystem. Made from a value that was never
    read, it is the exact failure this watchdog exists to prevent — one field
    over from ``fetch_judge_enabled``'s own rule.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)],
        now=_NOW,
        judge_states={_HOST_B: False},
        peer_states={_HOST_B: None},
    )
    assert "peer_critique_enabled=false" not in result.detail
    # POSITIVE PARTNER: it says something, rather than staying silent.
    assert "unreadable" in result.detail


def test_not_probing_peer_critique_says_so_rather_than_claiming_off(
    posture: ModuleType,
) -> None:
    """RED IF: an unprobed field reads as a measurement.

    Callers that pass nothing (every existing test in the suite) must not get a
    sentence asserting peer critique is off.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)],
        now=_NOW,
        judge_states={_HOST_B: False},
    )
    assert "peer_critique_enabled=true" not in result.detail
    assert "peer_critique_enabled=false" not in result.detail
    assert "peer_critique_enabled was not probed" in result.detail


def test_fetch_peer_critique_enabled_never_invents_a_value(
    posture: ModuleType, monkeypatch: object
) -> None:
    """RED IF: a missing or non-boolean field becomes ``False``.

    Mirrors ``fetch_judge_enabled``'s contract exactly: None, never False.
    """
    payloads: dict[str, object] = {}

    def _fake(url: str, *, attempts: int = 1) -> object:
        return payloads[url]

    monkeypatch.setattr(posture, "_fetch_json", _fake)  # type: ignore[attr-defined]

    payloads["a"] = {"peer_critique_enabled": True}
    assert posture.fetch_peer_critique_enabled("a") is True
    payloads["b"] = {"peer_critique_enabled": False}
    assert posture.fetch_peer_critique_enabled("b") is False
    # The three ways it must refuse rather than guess.
    payloads["c"] = {"peer_critique_enabled": "true"}
    assert posture.fetch_peer_critique_enabled("c") is None
    payloads["d"] = {}
    assert posture.fetch_peer_critique_enabled("d") is None
    payloads["e"] = ["not", "an", "object"]
    assert posture.fetch_peer_critique_enabled("e") is None


def test_main_actually_probes_peer_critique(
    posture: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """THE WIRE. RED IF: ``main`` never calls ``fetch_peer_critique_enabled``.

    Every other test in this file drives ``evaluate_posture`` directly, so all
    of them stay green if the fetcher is defined and never invoked — a fetcher
    nobody calls is a field the watchdog still cannot see. This test drives
    ``main`` end to end over a ``file:`` fixture and requires the probe line in
    its output.

    What turns it red: delete the ``peer_states = {...}`` comprehension in
    ``main``, or stop passing it to ``evaluate_posture``.

    Every URL is passed explicitly: ``main``'s defaults are the real production
    hosts, and a test that omitted one would reach quorum-ai.fly.dev.
    """
    ready = _ready_stub(tmp_path, {"live_readiness": {"state": "offline_by_config"}})
    status = _ready_stub(
        tmp_path,
        {"judge_enabled": False, "peer_critique_enabled": True},
        name="peer-status.json",
    )
    posture.main(
        ["--ready-url", ready, "--status-url", status, "--windows-file", str(SHIPPED_WINDOWS)]
    )
    printed = capsys.readouterr().out

    assert status in printed
    # HALF ONE: main probed it. Python's repr, capital T.
    assert "peer_critique_enabled=True" in printed, (
        "main did not probe peer_critique_enabled; the watchdog is blind to "
        "the expensive debate shape again"
    )
    # HALF TWO: the probed value reached the POSTURE, which is what becomes the
    # alert and the issue body. The note lower-cases it, so this cannot be
    # satisfied by the probe print above.
    #
    # Both halves are needed and neither is redundant: replacing
    # `peer_states=peer_states` with `peer_states=None` in main leaves the probe
    # line intact and SURVIVED an earlier version of this test that asserted
    # only half one. main would have gone on printing the value it had just
    # read while the posture said "not probed".
    assert "peer_critique_enabled=true" in printed, (
        "main probed peer critique but did not pass it to evaluate_posture, so "
        "the posture detail — the text that becomes the alert — never carries it"
    )
    # POSITIVE PARTNER: the judge probe still happens too, so this is not
    # passing over a main() that prints everything or nothing.
    assert "judge_enabled=False" in printed


def test_every_posture_decision_names_peer_critique(posture: ModuleType) -> None:
    """RED IF: any posture branch drops the peer note.

    THE TOTALITY CHECK. The first version of this change appended the note to
    ``judge_note``, which is built after three early returns and omitted from
    three more f-strings — so 6 of 12 return sites carried nothing while a
    comment claimed "EVERY posture line carries it". Every test at the time
    exercised one of the six branches that happened to work.

    This enumerates ``PostureDecision`` and fails if a case list stops reaching
    one, so a NEW branch cannot be added silently either. It is the structural
    partner to the per-branch tests above.

    What turns it red: move the append back inside ``_evaluate_posture_core``,
    or add a ``return PostureResult`` that bypasses the wrapper.
    """
    window_now = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    window_past = _window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)
    window_stale = _window(posture, opened=_OLD_OPEN, expires=_FUTURE_SHUT)
    window_fresh = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, judge=False)
    window_standing = _standing(posture, opened=_NOW_OPEN)
    cases = [
        ({_HOST_A: "offline_by_config"}, [], {}),
        ({_HOST_A: "live"}, [window_now], {}),
        ({_HOST_A: "live"}, [], {}),
        ({_HOST_A: "live"}, [window_past], {}),
        ({_HOST_A: None}, [], {}),
        ({_HOST_A: "live"}, None, {}),
        ({_HOST_A: "live"}, [window_stale], {}),
        ({_HOST_A: "live"}, [window_fresh], {_HOST_B: True}),
        ({_HOST_A: "live"}, [window_standing], {}),
    ]
    seen = set()
    for states, windows, judge in cases:
        result = posture.evaluate_posture(
            readiness_states=states,
            windows=windows,
            now=_NOW,
            judge_states=judge,
            peer_states={_HOST_B: True},
        )
        seen.add(result.decision)
        assert "peer_critique_enabled=true" in result.detail, (
            f"{result.decision.value} carries no peer state. A field reported "
            "on only some branches is a field an operator cannot rely on."
        )
    assert seen == set(posture.PostureDecision), (
        "a PostureDecision is unreachable from this case list, so this test no "
        f"longer proves totality. Missing: {set(posture.PostureDecision) - seen}"
    )


def test_the_flag_off_line_does_not_claim_calls_are_being_dispatched(
    posture: ModuleType,
) -> None:
    """RED IF: the note asserts dispatch while live execution is off.

    This is the STEADY-STATE line — the one an operator sees every cycle. The
    first version said "the debate leg therefore dispatches up to 8 critic
    calls" one sentence after the same line said "the money switch is off and
    no visitor can spend". Two sentences contradicting each other on one line
    are worse than silence.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: posture.FLAG_OFF_STATE},
        windows=[],
        now=_NOW,
        judge_states={_HOST_B: False},
        peer_states={_HOST_B: True},
    )
    assert result.decision is posture.PostureDecision.OFF_AS_DECLARED
    assert "peer_critique_enabled=true" in result.detail
    assert "No critic call can be dispatched while live execution is off" in result.detail
    # The claim that must NOT be here, with a positive partner above so this is
    # not a negative check over an empty string.
    assert "would dispatch" not in result.detail


def test_the_live_line_hedges_because_the_flag_is_a_state_not_a_promise(
    posture: ModuleType,
) -> None:
    """RED IF: the live wording promises 8 calls unconditionally.

    ``peer_critique_enabled`` is a state. A run whose slots all fell back to
    simulation has no eligible critic, so ``_build_peer_round`` returns None and
    the MODERATOR shape runs with the flag still true — a reachable state the
    watchdog counts as live (``offline_by_bad_key`` is not the flag-off state).
    "dispatches" would be a behaviour claim the code does not honour.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)],
        now=_NOW,
        judge_states={_HOST_B: False},
        peer_states={_HOST_B: True},
    )
    assert "would dispatch" in result.detail
    assert "falls back to the moderator shape" in result.detail
    assert "therefore dispatches" not in result.detail


def test_a_posture_that_could_not_be_read_is_never_reported_as_live_off(
    posture: ModuleType,
) -> None:
    """RED IF: "could not tell" collapses into "live execution is off".

    ``any(())`` is ``False``, so the first version of the wrapper turned ZERO
    readable readiness hosts into a positive claim that live execution was off —
    on the branch whose own text is "refusing to report a money posture from a
    value that was never read", which ALERTS, and which the workflow's issue
    tells the operator to go and read.

    Three inputs, one rule: none of them may produce either claim.
      * nothing readable at all;
      * a state outside the vocabulary (the core itself says an unheard-of
        state "is not evidence that live execution is off");
      * a partial view where every host that ANSWERED is off, because an unread
        host could be live.
    """
    cases = {
        "nothing readable": {_HOST_A: None},
        "unknown vocabulary": {_HOST_A: "banana"},
        "partial view, answered host off": {_HOST_A: posture.FLAG_OFF_STATE, _HOST_B: None},
    }
    for label, states in cases.items():
        result = posture.evaluate_posture(
            readiness_states=states,
            windows=[],
            now=_NOW,
            judge_states={},
            peer_states={_HOST_B: True},
        )
        # POSITIVE PARTNER: the flag IS still reported on every one of them, so
        # these negatives are not passing over a note that went silent.
        assert "peer_critique_enabled=true" in result.detail, label
        # Scoped to the NOTE, not the whole line. The core's own text for the
        # unknown-vocabulary branch correctly contains "is not evidence that
        # live execution is off"; asserting over the whole detail would match
        # the core's honest sentence and fail for the wrong reason.
        note = "peer_critique_enabled" + result.detail.split("peer_critique_enabled")[-1]
        assert "is UNKNOWN on this line" in note, label
        # Neither claim may appear IN THE NOTE.
        assert "live execution is off" not in note, label
        assert "would dispatch" not in note, label

    # POSITIVE PARTNER for the whole test: a host that positively reports a
    # live state DOES get the dispatch wording, so the rule above is a real
    # discrimination and not a blanket suppression.
    live = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)],
        now=_NOW,
        judge_states={},
        peer_states={_HOST_B: True},
    )
    assert "would dispatch" in live.detail
    assert "is UNKNOWN on this line" not in live.detail


def test_one_live_host_settles_it_even_when_another_went_unread(
    posture: ModuleType,
) -> None:
    """RED IF: the live verdict stops failing closed.

    A partial view is "cannot tell" ONLY when nothing contradicts "off". One
    host positively reporting a live state settles the question, because one
    host spending money is enough — reporting that as UNKNOWN would be the
    fail-open direction.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live", _HOST_B: None},
        windows=[_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)],
        now=_NOW,
        judge_states={},
        peer_states={_HOST_B: True},
    )
    assert "would dispatch" in result.detail
    assert "is UNKNOWN on this line" not in result.detail
    # And the core's own partial-view hedge is still there, unshadowed.
    assert result.complete is False


def test_the_note_begins_a_new_sentence_on_every_branch(posture: ModuleType) -> None:
    """RED IF: the note is run on to the end of a detail that has no full stop.

    Three core details end without terminal punctuation, so joining with a bare
    space produced "...that was never read peer_critique_enabled=true..." — and
    on one branch the swallowed clause was itself about liveness.
    """
    window_now = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    window_fresh = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, judge=False)
    cases = [
        ({_HOST_A: "offline_by_config"}, [], {}),
        ({_HOST_A: "live"}, [window_now], {}),
        ({_HOST_A: "live"}, [], {}),
        ({_HOST_A: None}, [], {}),
        ({_HOST_A: "live"}, None, {}),
        ({_HOST_A: "live"}, [window_fresh], {_HOST_B: True}),
    ]
    for states, windows, judge in cases:
        result = posture.evaluate_posture(
            readiness_states=states,
            windows=windows,
            now=_NOW,
            judge_states=judge,
            peer_states={_HOST_B: True},
        )
        before = result.detail.split("peer_critique_enabled")[0].rstrip()
        assert before.endswith((".", "!", "?")), (
            f"{result.decision.value}: the note runs on to "
            f"...{before[-70:]!r} instead of starting a sentence"
        )
