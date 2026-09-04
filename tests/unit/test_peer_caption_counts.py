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
        + ";\nconsole.log(JSON.stringify(cases.map(describePeerCritique)));\n"
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
