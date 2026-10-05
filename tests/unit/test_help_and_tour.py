"""W48 (ADR-0145): help for new users -- the shared help text and the two tour links.

The product owner's words (CHG-027 g): one short hint per new idea (the cost
estimate, the trust score, History), each once per device with "Got it", and an
optional tour opened only from a "Take the tour" link, *sharing its text with
the hints*. ADR-0145 decision 1 puts that text in ONE table in ``app.js``.

The contract this file fixes for the build:

* ``function helpTextTable()`` in ``app.js``, SELF-CONTAINED (it is sliced out
  by brace count and run under Node, like ``composerShapeCopy`` in
  ``tests/unit/test_quick_answer_ui.py``, so it may not call another ``app.js``
  helper or read an outer constant). It returns::

      {
        hints: { estimate: str, trust: str, history: str },
        tour: [ { idea: "ask",      title: str, text: str },
                { idea: "models",   title: str, text: str },
                { idea: "estimate", title: str, text: str },
                { idea: "trust",    title: str, text: str },
                { idea: "history",  title: str, text: str } ],
      }

  and the tour step for each hinted idea has ``text`` equal to that hint.
* The served landing carries two "Take the tour" buttons: ``#landing-tour`` in
  the nav row (``.landing-nav``) and ``#landing-preview-tour`` as the last
  element of the example preview (``.landing-preview``). The board pin for W48
  (``docs/65-open-work.md``) is the literal "Take the tour" in
  ``workspace.html``, so both are server-rendered.

The browser half (hints, the dialog, focus, Escape, storage) is
``e2e/tests/invariants/help-and-tour.spec.ts`` and
``e2e/tests/signed-in/help-history-hint.spec.ts``. What turns each test red is
stated on the test.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.repo_root import find_repo_root

from product_app.main import app

APP_JS = find_repo_root(Path(__file__)) / "src" / "product_app" / "static" / "app.js"

HINTED = ("estimate", "trust", "history")
TOUR_ORDER = ["ask", "models", "estimate", "trust", "history"]

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _extract_function(source: str, name: str) -> str:
    """Slice ``function name(...) { ... }`` out of ``source`` by brace count.

    Same slicer as ``tests/unit/test_quick_answer_ui.py``. Raises ``ValueError``
    (from ``str.index``) when the function does not exist, which is how every
    node test below goes red on today's code.
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


def _help_table() -> dict[str, Any]:
    """Run ``helpTextTable()`` alone under Node and return what it built."""
    source = APP_JS.read_text(encoding="utf-8")
    assert source.count("function helpTextTable(") == 1, (
        "app.js must define helpTextTable() exactly once (ADR-0145 decision 1)"
    )
    script = (
        _extract_function(source, "helpTextTable")
        + "\n\nconsole.log(JSON.stringify(helpTextTable()));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=10, check=True
    )
    table = json.loads(result.stdout)
    assert isinstance(table, dict)
    return table


def _sentences(text: str) -> int:
    """Sentences in ``text``: a ., ! or ? followed by whitespace or the end.

    "$0.50" and "e.g" inside a word do not end a sentence here, because the
    full stop is followed by a digit or a letter, not by whitespace.
    """
    return len(re.findall(r"[.!?](?=\s|$)", text.strip()))


# --- the one table: three hinted ideas and five tour steps ----------------------


@needs_node
def test_the_help_table_has_the_three_hinted_ideas_and_five_tour_steps_in_order() -> None:
    """RED IF: ``helpTextTable`` is missing, not self-contained (Node throws a
    ReferenceError), drops or adds a hinted idea, or the tour is not exactly
    the five steps of ADR-0145 decision 5 in its order (asking a question, the
    models, the estimate, the trust score, History).

    This is also the positive partner of the equality test below: it proves
    there ARE three hints and three matching steps to compare.
    """
    table = _help_table()

    assert sorted(table["hints"]) == sorted(HINTED)
    for idea in HINTED:
        assert isinstance(table["hints"][idea], str)
        assert table["hints"][idea].strip(), f"the {idea} hint is empty"

    tour = table["tour"]
    assert [step["idea"] for step in tour] == TOUR_ORDER
    for step in tour:
        assert isinstance(step["title"], str) and step["title"].strip(), step
        assert isinstance(step["text"], str) and step["text"].strip(), step


@needs_node
def test_the_tour_steps_for_the_hinted_ideas_are_exactly_the_hint_texts() -> None:
    """RED IF: the tour's estimate, trust-score or History step says anything
    other than that idea's hint, character for character (failure mode 9: the
    two texts drift apart; the owner asked the tour to share its text with the
    hints). Rewording one copy and not the other turns this red.
    """
    table = _help_table()
    steps = {step["idea"]: step for step in table["tour"]}
    for idea in HINTED:
        assert steps[idea]["text"] == table["hints"][idea], idea

    # Partner: the two tour-only steps are their own words, not a copy of a
    # hint, so the equality above is not met by one string used everywhere.
    hint_texts = set(table["hints"].values())
    assert len(hint_texts) == 3
    for idea in ("ask", "models"):
        assert steps[idea]["text"] not in hint_texts, idea


@needs_node
def test_every_tour_step_is_one_or_two_sentences() -> None:
    """RED IF: a step grows past two sentences or is not a sentence at all
    (failure mode 15: the owner's "1-minute tour"; ADR-0145 decision 5: five
    steps of one or two sentences). Counted by sentence-ending punctuation.
    """
    table = _help_table()
    counts = {step["idea"]: _sentences(step["text"]) for step in table["tour"]}
    # Positive partner: the counter is not blind -- every step has at least one.
    assert all(count >= 1 for count in counts.values()), counts
    assert all(count <= 2 for count in counts.values()), counts


def test_the_sentence_counter_counts() -> None:
    """Partner for the test above (rule 7): the counter returns 2 for two
    sentences, 1 for one with a price in it, and 3 for three -- so "<= 2" can
    fail. Green on today's code by design.
    """
    assert _sentences("One. Two.") == 2
    assert _sentences("It costs up to $0.50 a run.") == 1
    assert _sentences("One. Two! Three?") == 3


# --- the two "Take the tour" controls on the served landing ---------------------


class _Ancestry(HTMLParser):
    """A small element tree: for every element its tag, id, classes, text,
    children and the classes of every element it sits inside."""

    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.nodes: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        node: dict[str, Any] = {
            "tag": tag,
            "id": attr.get("id", ""),
            "classes": attr.get("class", "").split(),
            "attrs": attr,
            "text": "",
            "children": [],
            "ancestor_classes": [c for n in self.stack for c in n["classes"]],
        }
        if self.stack:
            self.stack[-1]["children"].append(node)
        if attr.get("id"):
            self.by_id[attr["id"]] = node
        self.nodes.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        for node in self.stack:
            node["text"] += data


def _served_landing() -> _Ancestry:
    html = TestClient(app).get("/ui").text
    parser = _Ancestry()
    parser.feed(html)
    # Positive partner for every "not found" below: the landing parsed.
    assert "landing-howitworks" in parser.by_id
    return parser


def test_the_landing_nav_row_has_take_the_tour_beside_how_it_works() -> None:
    """RED IF: ``#landing-tour`` is missing, is not a button reading exactly
    "Take the tour", or is not in the landing's nav row (``.landing-nav``)
    beside "How it works" (ADR-0145 decision 4)."""
    page = _served_landing()
    tour = page.by_id.get("landing-tour")
    assert tour is not None, "no #landing-tour on the served page"
    assert tour["tag"] == "button"
    assert tour["attrs"].get("type") == "button"
    assert " ".join(tour["text"].split()) == "Take the tour"
    assert "landing-nav" in tour["ancestor_classes"]
    # Partner: "How it works" is in the same row, so "beside" is checkable.
    assert "landing-nav" in page.by_id["landing-howitworks"]["ancestor_classes"]


def test_the_example_preview_ends_with_its_own_take_the_tour() -> None:
    """RED IF: ``#landing-preview-tour`` is missing, is not a button reading
    exactly "Take the tour", sits outside ``.landing-preview``, or is not that
    preview's last element (ADR-0145 decision 4: "one at the end of the example
    preview that the landing's 'How it works' scrolls to")."""
    page = _served_landing()
    tour = page.by_id.get("landing-preview-tour")
    assert tour is not None, "no #landing-preview-tour on the served page"
    assert tour["tag"] == "button"
    assert tour["attrs"].get("type") == "button"
    assert " ".join(tour["text"].split()) == "Take the tour"
    assert "landing-preview" in tour["ancestor_classes"]

    previews = [n for n in page.nodes if "landing-preview" in n["classes"]]
    assert len(previews) == 1
    # Every element inside the preview, in document order. Nothing may come
    # after the tour button except what is inside the button itself.
    order: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        for child in node["children"]:
            order.append(child)
            walk(child)

    walk(previews[0])
    inside_button: list[dict[str, Any]] = []
    walk_into = [tour]
    while walk_into:
        node = walk_into.pop()
        inside_button.extend(node["children"])
        walk_into.extend(node["children"])
    after = order[order.index(tour) + 1 :]
    assert [n["tag"] for n in after if n not in inside_button] == []
    # Partner: the preview's own text is still there, BEFORE the button.
    texts = [n for n in order if "landing-preview-text" in n["classes"]]
    assert len(texts) == 1 and order.index(texts[0]) < order.index(tour)


def test_there_are_exactly_two_take_the_tour_controls() -> None:
    """RED IF: a third "Take the tour" appears anywhere on the served page, or
    either of the two is missing. Counted over the whole page, so a copy in a
    hidden template also counts."""
    html = TestClient(app).get("/ui").text
    # Partner: the page rendered (a 429 shell would not contain the landing).
    assert 'data-view="landing"' in html
    assert html.count(">Take the tour<") == 2
