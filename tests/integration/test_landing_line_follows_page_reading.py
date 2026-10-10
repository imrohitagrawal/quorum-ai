"""ADR-0158 (CHG-039): the landing line about sources follows whether pages
are read.

The landing page's last disclaimer chip says "Sources are cited, but aren't
checked against their pages" -- true while no run reads the cited pages. With
page reading in effect (``main.source_pages_in_effect()``: the judge
configured AND ``quorum_source_fetch_enabled``) AND live execution on (the
same two terms ``main._peer_critique_in_effect`` uses for the subhead: the
live flag AND an OpenRouter key; a run with neither never reaches the judge),
the chip says "Answers are checked against the pages and PDFs they cite"
(CHG-039 (b)). It is rendered on the server in ``/ui``, like the subhead, so
the page never shows the wrong line first.

THE HARNESS: ``TestClient`` on ``/ui`` with the settings set per state; the
chip is read from the parsed ``div.landing-disclaimers`` element (rule 8:
structure, not a substring of the page). Each test names what turns it red.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from product_app.config import settings
from product_app.main import app

OLD_LINE = "Sources are cited, but aren't checked against their pages"
NEW_LINE = "Answers are checked against the pages and PDFs they cite"
#: The three chips that never change, in order.
FIXED_CHIPS = [
    "Decision support, not professional advice",
    "Don't paste sensitive or private data",
    "Results vanish when you leave",
]


class _Chips(HTMLParser):
    """The text of each ``span.landing-disclaimer`` inside each
    ``div.landing-disclaimers`` (the landing's row; the composer's row is a
    ``div.composer-disclaimers`` and is not collected)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._div_depth = 0  # depth of nested divs inside the current row
        self._in_row = False
        self._chip: list[str] | None = None
        self._chip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div":
            if self._in_row:
                self._div_depth += 1
            elif "landing-disclaimers" in classes:
                self._in_row, self._div_depth = True, 0
                self.rows.append([])
        if self._in_row and tag == "span":
            if self._chip is None and "landing-disclaimer" in classes:
                self._chip, self._chip_depth = [], 0
            elif self._chip is not None:
                self._chip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._in_row:
            return
        if tag == "span" and self._chip is not None:
            if self._chip_depth == 0:
                self.rows[-1].append(" ".join("".join(self._chip).split()))
                self._chip = None
            else:
                self._chip_depth -= 1
        elif tag == "div":
            if self._div_depth == 0:
                self._in_row = False
            else:
                self._div_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._chip is not None:
            self._chip.append(data)


def _landing_chips(monkeypatch: pytest.MonkeyPatch, **flags: object) -> list[str]:
    """The landing row's chips, served by ``/ui`` under ``flags``."""
    with monkeypatch.context() as mp:
        for name, value in flags.items():
            mp.setattr(settings, name, value)
        response = TestClient(app).get("/ui")
    assert response.status_code == 200, response.status_code
    parser = _Chips()
    parser.feed(response.text)
    parser.close()
    assert len(parser.rows) == 1, f"expected one landing disclaimer row, found {len(parser.rows)}"
    return parser.rows[0]


#: Every term on: judge configured, page reading on, live on, a key.
_ALL_ON: dict[str, object] = {
    "quorum_eval_judge_api_key": "sk-not-a-real-judge-key",
    "quorum_eval_judge_model_id": "openai/gpt-4.1-mini",
    "quorum_source_fetch_enabled": True,
    "openrouter_live_execution_enabled": True,
    "openrouter_api_key": "sk-or-not-a-real-key",
}

STATES: dict[str, tuple[dict[str, object], str]] = {
    "every term on": (_ALL_ON, NEW_LINE),
    "page reading off": ({**_ALL_ON, "quorum_source_fetch_enabled": False}, OLD_LINE),
    "live execution off": ({**_ALL_ON, "openrouter_live_execution_enabled": False}, OLD_LINE),
    "no judge configured": (
        {**_ALL_ON, "quorum_eval_judge_api_key": "", "quorum_eval_judge_model_id": ""},
        OLD_LINE,
    ),
    "no OpenRouter key": ({**_ALL_ON, "openrouter_api_key": ""}, OLD_LINE),
}


@pytest.mark.parametrize("state", list(STATES))
def test_the_landing_line_says_what_a_run_would_check(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """ADR-0158. RED IF: the landing row's last chip is not the line for this
    state (the new line only with page reading in effect AND live execution
    on with a key; the old line otherwise), both lines appear, or a fixed
    chip moves or changes. Partner: the landing disclaimer row is found and
    holds its three fixed chips, so a wrong line is a wrong line, not a
    missing row."""
    flags, expected = STATES[state]
    chips = _landing_chips(monkeypatch, **flags)
    assert chips[:3] == FIXED_CHIPS, chips
    assert chips == [*FIXED_CHIPS, expected], (state, chips)
    other = OLD_LINE if expected == NEW_LINE else NEW_LINE
    assert other not in chips


def test_the_new_line_is_served_only_when_status_says_pages_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The line and ``/status`` agree in the state that serves the new line:
    ``source_pages_in_effect`` is true there, and false with page reading
    off, where the old line is served. RED IF: the template's condition and
    the served predicate diverge (for example the line keyed on the setting
    alone, ignoring the judge)."""
    for flags, line, in_effect in (
        (_ALL_ON, NEW_LINE, True),
        ({**_ALL_ON, "quorum_source_fetch_enabled": False}, OLD_LINE, False),
    ):
        with monkeypatch.context() as mp:
            for name, value in flags.items():
                mp.setattr(settings, name, value)
            status = TestClient(app).get("/status").json()
        assert status["source_pages_in_effect"] is in_effect, status
        assert _landing_chips(monkeypatch, **flags)[-1] == line
