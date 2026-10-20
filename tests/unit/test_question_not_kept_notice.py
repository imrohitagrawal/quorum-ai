"""W87-2 review round 1 (falsification lens, M18): the "question was not
kept" line puts the email in as text, never as markup.

``showQuestionNotKeptNotice`` (``app.js``) writes "You are now signed in as
<email>. ..." above the question box. The email comes from the history
route, so it is data: an email holding ``<b>`` must show the literal
characters, and the line must have no element children.

Run under Node from the served ``app.js`` with the late-run suite's harness
(``tests/unit/test_late_run_question_rules.py``). Node has no DOM, so the
element is a small fake: setting ``textContent`` keeps the text as given;
setting ``innerHTML`` parses tags into children and drops them from the text,
as a browser does.
"""

from __future__ import annotations

import json
from typing import Any

from tests.unit.test_late_run_question_rules import _node

EMAIL = "a<b>x</b>@example.com"

_FAKE_DOM = r"""
function __fakeElement() {
  return {
    _text: "", children: [], className: "", id: "", attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children = []; },
    get innerHTML() { return this._text; },
    set innerHTML(v) {
      const s = String(v);
      this.children = (s.match(/<[a-z][^>]*>/gi) || []).map((t) => ({ tag: t }));
      this._text = s.replace(/<[^>]*>/g, "");
    },
  };
}
const inserted = [];
const field = { parentNode: { insertBefore(node, before) { inserted.push(node); } } };
document = { createElement() { return __fakeElement(); } };
queryTextarea = { value: "", closest() { return field; } };
"""


def _notice(email: Any) -> Any:
    body = (
        _FAKE_DOM
        + f"api = async () => ({{ email: {json.dumps(email)} }});"
        + "await showQuestionNotKeptNotice();"
        + "return inserted.map((n) => ({ text: n.textContent, children: n.children.length,"
        + " id: n.id, role: n.attrs.role }));"
    )
    return _node(["showQuestionNotKeptNotice"], body)


def test_the_email_goes_in_as_text() -> None:
    """Red when: the line is set with ``innerHTML`` (the ``<b>`` becomes an
    element child and leaves the text), or the email is left out."""
    got = _notice(EMAIL)
    assert len(got) == 1, "partner: exactly one line was inserted"
    line = got[0]
    assert line["id"] == "question-not-kept"
    assert line["role"] == "status"
    assert "You are now signed in as " + EMAIL + "." in line["text"]
    assert "<b>" in line["text"]
    assert line["children"] == 0


def test_no_email_inserts_no_line() -> None:
    """Red when: a history answer without an email still inserts a line
    (an empty "signed in as ." sentence)."""
    assert _notice("") == []
