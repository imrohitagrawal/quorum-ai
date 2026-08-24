"""#354, the browser half: the green consensus surface needs POSITIVE evidence.

``isConsensusResult`` is the single source of truth for the AC-019 "no false
consensus" rule — it is what sets ``[data-consensus="true"]`` on the verdict
band, the trust card, the transcript chip and the footer. Until #354 its
agreement test was ``aligned === total``, a NUMBER, and a number is reachable by
a detector failing to fire. It was: a panel of two "we recommend adopting
usage-based pricing…" and two "we advise you avoid usage-based pricing…" scored
4 of 4 because both sides share their phrasing.

The served ``agreement.panel_agreement`` carries the evidence the count cannot.
This module drives the REAL served function under Node — lifted out of
``app.js`` by brace count, the same way ``test_agreement_clause_honesty.py``
does — so it measures the shipped source and not a Python restatement of it.
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
    """Slice ``function name(...) { ... }`` out of ``source`` by brace count.

    Same approach as ``test_agreement_clause_honesty._extract_function``.
    """
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
    return _extract_function(APP_JS.read_text(encoding="utf-8"), "isConsensusResult")


def _run(harness: str, cases: list[dict[str, Any]]) -> list[bool]:
    script = (
        harness
        + "\n\nconst cases = "
        + json.dumps(cases)
        + ";\nconsole.log(JSON.stringify(cases.map(isConsensusResult)));\n"
    )
    completed = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    decoded: list[bool] = json.loads(completed.stdout)
    return decoded


def _result(aligned: int, total: int, panel_agreement: str | None) -> dict[str, Any]:
    """A response body that satisfies EVERY other conjunct of the green rule.

    Built this way on purpose: each case below differs from a painting-green
    result in exactly ONE respect, so a failure names the conjunct that moved
    rather than "something in the payload".
    """
    agreement: dict[str, Any] = {"aligned": aligned, "total": total}
    if panel_agreement is not None:
        agreement["panel_agreement"] = panel_agreement
    return {
        "status": "completed",
        "failed_steps": [],
        "result": {
            "agreement": agreement,
            "final_synthesis": {"quality_checks": {"false_consensus_preserved": False}},
        },
    }


def test_the_green_surface_needs_the_verdict_and_not_only_the_count(harness: str) -> None:
    """THE #354 GATE, both directions in one enumeration.

    Row 1 is the reproduction as the browser sees it: the server counted 4 of 4
    on the split panel, and that alone must no longer be enough.
    Row 2 is the POSITIVE PARTNER (rule 7) — a genuine consensus run still
    paints green, so this build has not simply stopped claiming anything.

    What turns it red: delete the ``panelAgreement === "agreed"`` conjunct from
    ``isConsensusResult``; rows 1, 3 and 4 all flip to ``True``.
    """
    cases = [
        _result(4, 4, "split"),  # a moderator SAW the split
        _result(4, 4, "agreed"),  # POSITIVE PARTNER: genuine consensus
        _result(4, 4, "undetermined"),  # no usable moderator reading
        _result(4, 4, None),  # a payload from before the field existed
    ]
    assert _run(harness, cases) == [False, True, False, False]


def test_the_count_still_has_to_agree_too(harness: str) -> None:
    """The new conjunct ADDS to the rule, it does not replace it. A moderator
    saying "agreed" over a tally of 3 of 4 must still not paint green — the two
    are different measurements and both have to hold.

    What turns it red: replace ``aligned === total`` with the verdict instead of
    adding to it; row 1 flips to ``True``.
    """
    cases = [
        _result(3, 4, "agreed"),
        _result(0, 0, "agreed"),  # nothing measured: ``total > 0`` still binds
        _result(4, 4, "agreed"),  # POSITIVE PARTNER
    ]
    assert _run(harness, cases) == [False, False, True]


def test_an_unknown_verdict_value_is_not_agreement(harness: str) -> None:
    """A value the server cannot currently emit must fall to "no green surface",
    never through to it. #206 made ``synthesis_mode`` a closed enum after finding
    nothing stopped a fourth value reaching the client and falling through
    silently; this is the same posture, tested rather than assumed.

    What turns it red: write the conjunct as ``panelAgreement !== "split"``,
    which lets every unknown string paint green.
    """
    cases = [
        _result(4, 4, "AGREED"),  # right word, wrong case
        _result(4, 4, "unanimous"),  # plausible, not a served value
        _result(4, 4, ""),  # empty string
        _result(4, 4, "agreed"),  # POSITIVE PARTNER
    ]
    assert _run(harness, cases) == [False, False, False, True]
