"""#247: the "preserved as disagreement" clause, driven under Node.

On a run where NO answer came from a live provider, the verdict band read
"0 of 4 models aligned — the rest are preserved as disagreement below." Four
models nobody asked, reported as disagreeing. The clause is now gated by
``mayClaimDisagreement`` in ``app.js``.

THREE surfaces make that claim — the verdict band, the Copy summary and the
Markdown export. They carry their own wording, which is fine; what they must not
carry is their own copy of the DECISION. #128 was exactly that, and the file a
user kept disagreed with the screen they exported it from. These tests drive the
one shared predicate and then assert, structurally, that all three call it.

Follows ``tests/unit/test_demo_mode_banner_copy.py``: the function is lifted out
of ``app.js`` by brace count and executed under Node, so this measures the
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
    """Slice ``function name(...) { ... }`` out of ``source`` by brace count.

    Same approach as ``test_demo_mode_banner_copy._extract_function`` — matches
    the parameter-list parens first, then the body's braces.
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
    return _extract_function(APP_JS.read_text(encoding="utf-8"), "mayClaimDisagreement")


def _run(harness: str, cases: list[dict[str, Any]]) -> list[bool]:
    script = (
        harness
        + "\n\nconst cases = "
        + json.dumps(cases)
        + ";\nconsole.log(JSON.stringify(cases.map(mayClaimDisagreement)));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(result.stdout)


def test_the_clause_is_withheld_only_when_no_answer_was_live(harness: str) -> None:
    """The whole input space, enumerated rather than sampled: two booleans, four
    combinations, every one stated.

    What turns it red: change ``mayClaimDisagreement`` to ignore
    ``noLiveAnswers`` — row 2 flips to ``True`` and the fully simulated run tells
    the reader four models disagreed again.
    """
    cases = [
        # isConsensus, noLiveAnswers
        {"isConsensus": False, "noLiveAnswers": False},  # ordinary divided panel
        {"isConsensus": False, "noLiveAnswers": True},  # THE #247 CASE
        {"isConsensus": True, "noLiveAnswers": False},  # consensus: own branch
        {"isConsensus": True, "noLiveAnswers": True},
    ]
    assert _run(harness, cases) == [True, False, False, False]


def test_an_older_payload_without_live_count_keeps_the_clause(harness: str) -> None:
    """``noLiveAnswers`` is derived from ``Number.isInteger(result.live_count)``,
    so a payload missing the field yields ``undefined`` here. That must read as
    "some answers were live" — losing the clause on every historical run would be
    its own silent change.

    What turns it red: derive ``noLiveAnswers`` with a truthiness test such as
    ``!result.live_count``, which is ``true`` for ``undefined``.
    """
    assert _run(harness, [{"isConsensus": False}]) == [True]
    assert _run(harness, [{"isConsensus": False, "noLiveAnswers": None}]) == [True]


def _code_only(path: Path) -> str:
    """``path``'s JS with whole-line ``//`` comments dropped.

    ``tests/code_text.code_without_comments`` cannot serve here: for a non-Python
    suffix it only strips ``#`` comments, so every ``//`` line in ``app.js``
    survives. Needed because the FIRST draft of the test below asserted
    ``source.count("preserved as disagreement") == 3`` and measured **6** — the
    three served strings plus the three comments this change added to explain
    them. That is precisely the substring-matches-the-prose defect
    ``tests/code_text.py`` exists for, reproduced inside the test written to
    guard against it.

    Whole-line only. An inline trailing ``//`` would need real tokenising to tell
    a comment from the ``//`` in a URL, and no assertion here needs that.
    """
    return "".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
        if not line.lstrip().startswith("//")
    )


def test_all_three_surfaces_route_through_the_one_predicate() -> None:
    """The band, the Copy summary and the Markdown export must each ASK, not each
    decide.

    What turns it red: re-inline ``!ctx.isConsensus`` at any of the three sites.
    """
    code = _code_only(APP_JS)

    calls = code.count("mayClaimDisagreement(")
    # 1 declaration + 3 call sites.
    assert calls == 4, f"expected 1 declaration and 3 call sites, found {calls}"

    # Positive partner for the count: the clause itself must still EXIST, or the
    # assertion above would be satisfied by a file that dropped the sentence
    # entirely and asserts nothing about honesty.
    assert code.count("preserved as disagreement") == 3

    # Proves ``_code_only`` actually removed something — otherwise both counts
    # above could be measuring a file whose comments were never stripped, and the
    # helper's failure would be invisible.
    assert APP_JS.read_text(encoding="utf-8").count("preserved as disagreement") > 3

    # BOTH context objects must be handed the field — the verdict band's and the
    # Markdown export's. An export that is not given it evaluates ``undefined``,
    # keeps the sentence the screen has just dropped, and reintroduces the #128
    # screen-vs-file drift.
    #
    # Counted, not tested with ``in``: the first draft asserted
    # ``"noLiveAnswers," in code``, which two occurrences satisfy, so deleting
    # either one left it green. The mutation that removed the export's copy was
    # what exposed it.
    assert code.count("noLiveAnswers,") == 2, "both ctx objects must carry it"
