"""W87-2 review round 1 (journey E49/E66): a question put back after sign-in
is brought into view, and focus is not moved.

At 390 px the question box sat below the fold after the sign-in return, so
the visitor could not see that the question was kept. ``restoreLateRunQuestion``
now scrolls the box into view, and never focuses it: focus stays where the
account panel's return markers (``?account=delete`` / ``?account=switched``)
put it.

Run under Node from the served ``app.js`` with the late-run suite's harness
(``tests/unit/test_late_run_question_rules.py``). Whether the box is really
visible at 390 px in a browser is for the round-2 journey check; this pins
the call.
"""

from __future__ import annotations

import json
from typing import Any

from tests.unit.test_late_run_question_rules import KEY, _node


def _restore(saved: Any) -> Any:
    seed = (
        f"window.sessionStorage.setItem({json.dumps(KEY)}, {json.dumps(json.dumps(saved))});"
        if saved is not None
        else ""
    )
    body = (
        "const scrolls = []; const focuses = [];"
        "queryTextarea = { value: '', dispatchEvent() {},"
        " scrollIntoView(o) { scrolls.push(o); }, focus() { focuses.push(1); } };"
        "state.sessionAccountId = 'A';" + seed + "await restoreLateRunQuestion();"
        "return { value: queryTextarea.value, scrolls, focuses };"
    )
    return _node(["restoreLateRunQuestion", "lateRunQuestionToRestore"], body)


def test_a_restored_question_is_scrolled_into_view_without_focus() -> None:
    """Red when: the ``scrollIntoView`` call after the question is put back
    is removed (0 scrolls), or the box is focused instead of or as well as
    scrolled (a focus would take focus from "Delete my account…")."""
    got = _restore({"account": "A", "question": "the kept question"})
    assert got["value"] == "the kept question", "partner: the question was put back"
    assert got["scrolls"] == [{"behavior": "auto", "block": "center"}]
    assert got["focuses"] == []


def test_nothing_put_back_scrolls_nothing() -> None:
    """Red when: the box is scrolled into view on a load that put no
    question back (no saved entry, or another account's)."""
    assert _restore(None)["scrolls"] == []
    other = _restore({"account": "B", "question": "typed as B"})
    assert other["value"] == ""
    assert other["scrolls"] == []
