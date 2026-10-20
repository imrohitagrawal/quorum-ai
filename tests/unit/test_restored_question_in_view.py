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


def _restore(saved: Any, *, failure_notice: bool = False) -> Any:
    """Run ``restoreLateRunQuestion`` with ``saved`` in the tab's storage.
    ``failure_notice``: the page has the server's ``#sign-in-notice``."""
    seed = (
        f"window.sessionStorage.setItem({json.dumps(KEY)}, {json.dumps(json.dumps(saved))});"
        if saved is not None
        else ""
    )
    body = (
        "const scrolls = []; const focuses = [];"
        f"el = (id) => (id === 'sign-in-notice' && {json.dumps(failure_notice)}) ? {{ id }} : null;"
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
    assert got["scrolls"] == [{"behavior": "auto", "block": "nearest"}]
    assert got["focuses"] == []


def test_nothing_put_back_scrolls_nothing() -> None:
    """Red when: the box is scrolled into view on a load that put no
    question back (no saved entry, or another account's)."""
    assert _restore(None)["scrolls"] == []
    other = _restore({"account": "B", "question": "typed as B"})
    assert other["value"] == ""
    assert other["scrolls"] == []


def test_a_restore_under_the_sign_in_failure_notice_does_not_scroll() -> None:
    """W87-2 review round 2 (journey E37/E48): on ``/ui?sign_in=failed`` the
    server renders ``#sign-in-notice``, and the scroll pushed it off screen.
    Red when: the guard on ``#sign-in-notice`` is removed (1 scroll)."""
    got = _restore({"account": "A", "question": "the kept question"}, failure_notice=True)
    assert got["value"] == "the kept question", "partner: the question was put back"
    assert got["scrolls"] == []
    assert got["focuses"] == []


def test_a_restore_without_the_failure_notice_scrolls_only_as_needed() -> None:
    """The partner of the test above. Red when: a restore with no failure
    notice stops scrolling, or scrolls further than needed (anything but
    ``block: "nearest"``)."""
    got = _restore({"account": "A", "question": "the kept question"}, failure_notice=False)
    assert got["scrolls"] == [{"behavior": "auto", "block": "nearest"}]
