"""ADR-0099: the debate caption counts the critics that actually answered.

Until 2026-09-04 both debate captions read "Each answer model critiqued the
others, in both rounds" whenever ANY round carried ``critique_shape == "peer"``.
FOUR reachable states made that false, and the fourth is why this drives
``critique_mode`` rather than a count of dispatches:

1. round 2 can be skipped entirely (``debate.py::_should_skip_round_two``);
2. the shape is stamped PER ROUND, so round 1 can be peer and round 2 the
   moderator — ``.some()`` reported that as "both rounds";
3. only ELIGIBLE slots critique, so the count is 0-4, never always 4;
4. a critic that returns nothing usable STILL yields a ``SlotCritique`` whose
   ``critique_mode`` stays ``"fallback"`` while the round stays shaped
   ``"peer"``. So a run where every critic fell back rendered "Each answer
   model critiqued the others" directly above rows the same view marks
   "Written by Quorum, not by a model".

WHAT TURNS THIS RED: reverting ``describePeerCritique`` to the old
``rounds.some((r) => r.critique_shape === "peer")`` boolean. Every case below
except the moderator one then returns the single fixed sentence, and the six
distinct expectations collapse.

Follows ``tests/unit/test_agreement_clause_honesty.py``: the function is lifted
out of ``app.js`` by brace count and executed under Node, so this measures the
SERVED source rather than a Python re-implementation of it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.code_text import code_without_comments
from tests.unit.test_ui_honesty import BANNED_EXCHANGE_CLAIMS

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    paren_open = start + len(marker) - 1
    depth = 0
    i = paren_open
    while True:
        ch = source[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    brace_open = source.index("{", i)
    depth = 0
    i = brace_open
    while True:
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


@pytest.fixture(scope="module")
def harness() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    # POSITIVE PARTNER for the extraction itself: if the function is renamed or
    # deleted, this raises here rather than letting every case below compare
    # None to None and pass.
    assert "function describePeerCritique(" in source
    return _extract_function(source, "describePeerCritique")


def _run(harness: str, cases: list[Any]) -> list[Any]:
    script = (
        harness
        + "\n\nconst cases = "
        + json.dumps(cases)
        # An explicit arrow, NOT `cases.map(describePeerCritique)`: `Array.map`
        # passes (element, index, array), so the bare reference fed the array
        # INDEX in as `detailClause` and appended " 1" to case 1's sentence.
        + ";\nconsole.log(JSON.stringify(cases.map((c) => describePeerCritique(c))));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    decoded: list[Any] = json.loads(result.stdout)
    return decoded


@pytest.fixture(scope="module")
def harness_synth() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    assert "function describeSynthesisInput(" in source
    assert "function hasVisibleText(" in source
    # `describeSynthesisInput` calls `hasVisibleText`, which closes over
    # INVISIBLE_OUTLIERS, so all three must be lifted together or the function
    # throws under Node and every case below "fails" for the wrong reason.
    outliers = 'const INVISIBLE_OUTLIERS = new Set(["\\u3164", "\\u2800"]);'
    return (
        outliers
        + "\n"
        + _extract_function(source, "hasVisibleText")
        + "\n"
        + _extract_function(source, "describeSynthesisInput")
    )


def _run_synth(harness: str, cases: list[Any]) -> list[Any]:
    script = (
        harness
        + "\n\nconst cases = "
        + json.dumps(cases)
        + ";\nconsole.log(JSON.stringify(cases.map((c) => describeSynthesisInput(c))));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    decoded: list[Any] = json.loads(result.stdout)
    return decoded


def _critiques(live: int, fallback: int = 0) -> list[dict[str, str]]:
    return [{"critique_mode": "live"} for _ in range(live)] + [
        {"critique_mode": "fallback"} for _ in range(fallback)
    ]


def _round(number: int, shape: str, **kw: Any) -> dict[str, Any]:
    return {"round_number": number, "critique_shape": shape, **kw}


def test_the_caption_reports_what_actually_happened(harness: str) -> None:
    """Every branch, enumerated rather than sampled."""
    full = {"slot_critiques": _critiques(4), "eligible_critic_count": 4}
    three = {"slot_critiques": _critiques(3, 1), "eligible_critic_count": 4}
    none_live = {"slot_critiques": _critiques(0, 4), "eligible_critic_count": 4}

    cases = [
        # 0. no peer round at all -> null, so the caller keeps the moderator copy.
        [_round(1, "moderator"), _round(2, "moderator")],
        # 1. the shape the e2e fixture serves: peer, but no per-critic record.
        [_round(1, "peer"), _round(2, "peer")],
        # 2. every eligible critic answered, both rounds.
        [_round(1, "peer", **full), _round(2, "peer", **full)],
        # 3. one critic fell back -> the count must not say four.
        [_round(1, "peer", **three), _round(2, "peer", **three)],
        # 4. round 2 was the moderator's -> not "both rounds".
        [_round(1, "peer", **full), _round(2, "moderator")],
        # 5. round 2 skipped entirely -> one round in the payload.
        [_round(1, "peer", **full)],
        # 6. THE FOURTH STATE: peer-shaped, every critic templated.
        [_round(1, "peer", **none_live), _round(2, "peer", **none_live)],
    ]
    got = _run(harness, cases)

    assert got[0] is None
    assert got[1] == "The answer models critiqued the others, in both rounds."
    assert got[2] == "Each answer model critiqued the others, in both rounds."
    assert got[3] == "3 of 4 answer models critiqued the others, in both rounds."
    assert got[4] == "Each answer model critiqued the others, in round 1."
    assert got[5] == "Each answer model critiqued the others, in round 1."
    assert got[6] == (
        "No answer model's own critique came back, in both rounds — "
        "the round text below is Quorum's own."
    )

    # The six peer sentences must not all be the same string; that is exactly
    # what the pre-ADR-0099 implementation returned and what a regression to it
    # would restore.
    assert len({s for s in got if s}) == 5


def test_a_claim_is_scoped_to_the_rounds_it_is_true_of(harness: str) -> None:
    """RED WHEN: the sentence is scoped with every peer round rather than the
    rounds whose critics actually answered.

    THE DEFECT THIS PINS, found by adversarial review in the first version of
    ADR-0099's own fix: the "nothing came back" branch fired on `.some()` while
    the scope still said "in both rounds", so a run whose round 1 was fully live
    and round 2 fully templated reported that NO critique came back in both
    rounds — erasing four real critiques directly above a card the same view
    leaves unmarked because its `debate_mode` is "live".

    Mutation that reddens this: `scopeOf(answered)` -> `scopeOf(peer)` on the
    "Each answer model critiqued the others" branch. Proved by
    `scripts/proofs/mechanism_copy_mutations.py` mutation 06, which SURVIVED
    until this test existed.
    """
    full = {"slot_critiques": _critiques(4), "eligible_critic_count": 4}
    none_live = {"slot_critiques": _critiques(0, 4), "eligible_critic_count": 4}
    partial = {"slot_critiques": _critiques(3, 1), "eligible_critic_count": 4}

    cases = [
        # round 1 answered, round 2 entirely templated -> round 1 only.
        [_round(1, "peer", **full), _round(2, "peer", **none_live)],
        # the mirror: only round 2 answered.
        [_round(1, "peer", **none_live), _round(2, "peer", **full)],
        # the cancel shape: round 2 dispatched one critic, which fell back.
        [
            _round(1, "peer", **full),
            _round(2, "peer", slot_critiques=_critiques(0, 1), eligible_critic_count=4),
        ],
        # both answered but with DIFFERENT counts -> no count may be asserted,
        # and the scope is still both rounds because both did answer.
        [_round(1, "peer", **partial), _round(2, "peer", **full)],
    ]
    got = _run(harness, cases)

    assert got[0] == "Each answer model critiqued the others, in round 1."
    assert got[1] == "Each answer model critiqued the others, in round 2."
    assert got[2] == "Each answer model critiqued the others, in round 1."
    assert got[3] == "The answer models critiqued the others, in both rounds."

    # None of these may claim BOTH rounds while one round produced nothing —
    # the exact sentence the pre-fix version emitted.
    for sentence in got[:3]:
        assert "in both rounds" not in sentence
        assert "No answer model" not in sentence


def test_an_invisible_revised_answer_is_not_a_revision(harness_synth: str) -> None:
    """RED WHEN: `hasVisibleText` is replaced by `String(x).trim()`.

    `synthesis.py` gates on `visible_text.is_visible`, which treats text whose
    every character is whitespace or Unicode Cf/Cc as invisible. `.trim()` does
    not: three zero-width spaces are truthy in JS and INVISIBLE to Python, so
    synthesis fed the ORIGINAL answer while the UI credited the debate for a
    revision that was never used.

    Mutation that reddens this: mutation 08 in
    `scripts/proofs/mechanism_copy_mutations.py`, which SURVIVED until this
    test existed.
    """
    zero_width = "\u200b\u200b\u200b"
    cases = [
        # Four live critiques whose revised answers are invisible.
        {
            "model_answers": [1, 2, 3, 4],
            "debate_outputs": [
                {
                    "slot_critiques": [
                        {
                            "critic_slot_number": i,
                            "critique_mode": "live",
                            "revised_answer": zero_width,
                        }
                        for i in range(1, 5)
                    ]
                }
            ],
        },
        # POSITIVE PARTNER: real text on the same shape DOES count, so the
        # assertion above is not passing because nothing ever counts.
        {
            "model_answers": [1, 2, 3, 4],
            "debate_outputs": [
                {
                    "slot_critiques": [
                        {
                            "critic_slot_number": i,
                            "critique_mode": "live",
                            "revised_answer": "a real revision",
                        }
                        for i in range(1, 5)
                    ]
                }
            ],
        },
    ]
    got = _run_synth(harness_synth, cases)
    assert got[0] == "from the four opening answers"
    assert got[1] == "from the four refined answers"


def test_a_zero_eligible_count_never_renders_as_a_number(harness: str) -> None:
    """RED WHEN: the unknown branch is dropped and the numeric one runs anyway.

    ``eligible_critic_count`` DEFAULTS TO 0 (``debate.py``), so every run
    rehydrated from before #290 carries a zero. Rendering "0 of 4 answer models
    critiqued" beside the ``(critique)`` rows on the same receipt would be a
    worse falsehood than the sentence this change removes.
    """
    cases = [
        # No `slot_critiques` key at all, and the schema default for the count.
        [_round(1, "peer", eligible_critic_count=0), _round(2, "peer", eligible_critic_count=0)],
        # Present but empty — the same "we were told nothing" state.
        [_round(1, "peer", slot_critiques=[], eligible_critic_count=0)],
    ]
    got = _run(harness, cases)

    for sentence in got:
        assert sentence is not None
        assert "0 of" not in sentence
        assert sentence.startswith("The answer models critiqued the others")

    # POSITIVE PARTNER: the numeric branch is reachable, so the two assertions
    # above are not passing merely because no case ever produces a number.
    numeric = _run(
        harness,
        [[_round(1, "peer", slot_critiques=_critiques(2, 2), eligible_critic_count=4)]],
    )
    assert numeric[0] == "2 of 4 answer models critiqued the others, in round 1."


# --- the WIRE, not just the decision ----------------------------------------
#
# Review defeated the tests above by leaving `describePeerCritique` in place as
# dead code and reverting BOTH call sites to the pre-ADR-0099 boolean: the
# suite stayed green while every user-visible sentence went back to the
# falsehood. A mutation proof on a function proves nothing about whether the
# render path calls it.
#
# These read the SERVED source with comments stripped (`tests/code_text.py`),
# because `app.js`'s comments around this code spell the call out in prose and
# a raw substring scan would match the explanation instead of the code — the
# trap rule 8 names.


@pytest.fixture(scope="module")
def app_js_code() -> str:
    """`app.js` with its comments blanked, so a prose mention cannot satisfy a
    structural assertion (AGENTS.md rule 8)."""
    stripped = code_without_comments(APP_JS)
    # POSITIVE PARTNER for the stripper itself: if it ever returned an empty or
    # gutted file, every structural assertion below would pass vacuously.
    assert len(stripped) > 100_000, (
        f"comment-stripped app.js is only {len(stripped)} chars; the structural "
        "checks below would be asserted over a corrupted file"
    )
    return stripped


def test_both_debate_captions_are_rendered_from_the_helper(app_js_code: str) -> None:
    """RED WHEN: either caption site goes back to an inline `critique_shape` test.

    Mutation that reddens this: replace either call with
    ``rounds.some((r) => r && r.critique_shape === "peer")`` and a fixed string.
    """
    calls = app_js_code.count("describePeerCritique(")
    # 1 definition + 2 call sites (result view, transcript view).
    assert calls == 3, f"expected 1 definition and 2 call sites, found {calls} occurrences"

    # POSITIVE PARTNER: the old inline predicate is GONE from the render path.
    # Without this the count above passes over code that calls the helper and
    # then ignores it.
    assert 'critique_shape === "peer"' in app_js_code, (
        "the shape literal vanished entirely — the helper itself should still use it"
    )
    assert app_js_code.count('critique_shape === "peer"') == 1, (
        'a second `critique_shape === "peer"` test exists outside the helper; '
        "that is the inline predicate this change removed"
    )


def test_the_synthesis_attribution_is_rendered_from_the_helper(app_js_code: str) -> None:
    """RED WHEN: the attribution goes back to a hard-coded string.

    Mutation that reddens this: replace ``describeSynthesisInput(res || {})``
    with the literal ``"from the four refined answers"``.
    """
    assert app_js_code.count("describeSynthesisInput(") == 2, (
        "expected 1 definition and 1 call site for describeSynthesisInput"
    )
    assert "from the four refined answers" not in app_js_code, (
        "the unconditional attribution is back as a literal outside the helper"
    )


def test_the_transcript_chip_reads_the_servers_panel_reading(app_js_code: str) -> None:
    """RED WHEN: the chip returns to a two-way `isConsensus ? … : "Panel divided"`.

    Mutation that reddens this: delete the `panelReading` lookup and inline
    ``isConsensus ? "Consensus reached" : "Panel divided"``.
    """
    assert "panel_agreement" in app_js_code
    assert '"Not determined"' in app_js_code, (
        "the undetermined state's label is gone; the chip is back to two states"
    )
    # POSITIVE PARTNER: the green attribute is still decided by the shared gate
    # and NOT by the new three-way label, so no new state can paint green.
    assert 'dataset.consensus = isConsensus ? "true" : "false"' in app_js_code


def test_the_helper_makes_no_banned_exchange_claim(app_js_code: str) -> None:
    """RED WHEN: a directed-conversation claim appears in the caption helper.

    Review demonstrated a real hole here: moving the caption OUT of the
    ``mkEl(...)`` literal put it beyond ``test_ui_honesty``'s
    ``_extract_mkel_literals``, so ``BANNED_EXCHANGE_CLAIMS`` stopped covering
    the sentence the product actually serves. A caption reading "Each model
    replied to the others' rebuttals in turn" — three banned phrases, false
    under BOTH shapes — passed on this branch and FAILED on origin/main. This
    restores the cover over the helper.

    Mutation that reddens this: put "rebuttal", "replied" or "in turn" into any
    string ``describePeerCritique`` returns.
    """
    helper = _extract_function(app_js_code, "describePeerCritique").lower()

    # POSITIVE PARTNER (rule 7): the helper was actually located and carries the
    # sentences, so the negatives below are not asserted over an empty slice.
    assert "critiqued the others" in helper, (
        "could not locate the caption text inside describePeerCritique; the "
        "checks below would pass vacuously. Fix the extractor, do not delete this."
    )

    for banned in BANNED_EXCHANGE_CLAIMS:
        assert banned not in helper, (
            f"describePeerCritique emits {banned!r}, which claims one model "
            "answered another model's message. No shape does that."
        )
