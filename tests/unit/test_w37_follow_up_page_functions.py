"""W37 (ADR-0143 decisions 5, 6 and 8): the page's pure functions and served copy.

The JavaScript functions are sliced out of ``app.js`` by brace count and run
under Node -- the harness ``tests/unit/test_quick_answer_ui.py`` already uses --
so EACH FUNCTION NAMED HERE MUST STAY SELF-CONTAINED: no call into another
``app.js`` helper and no read of a module-level constant (the harness runs the
function alone, and such a reference is a ``ReferenceError`` there). Any limit
it needs, such as 60,117, is written inside it.

The contract these tests fix for the build (the ADR names no function; these
names and signatures are the test designer's, and the browser half in
``e2e/tests/invariants/follow-up-context.spec.ts`` checks the same behaviour
on the real page):

* ``runRequestBody(queryText, modelIds, quick, extra, context)`` -- a FIFTH
  argument. When it is an object, the body carries ``context`` equal to it, for
  a panel and a quick body alike; when it is ``null``/absent, the body is
  byte-identical to today's (decision 5: estimate, warnings probe and create
  are built from the same state).
* ``priorAnswerText(result)`` -- ``result`` is the run payload the page polls
  (``{mode, result: {final_synthesis, model_answers}}``). A panel result gives
  the five synthesis sections in the order the page shows them -- Consensus,
  Disagreement, Uncertainty, Recommendation, then Source support (the Sources
  row) -- joined by one blank line, cut to 60,117 characters; a quick result
  gives its answer text; a result with no final answer gives an empty value
  (decision 6, failure-modes rows 9 and 11).
* ``handoffHintParts(slotCount, highStakes)`` -- unchanged signature; its last
  part becomes the owner's wording (decision 8).

Every test names what turns it red.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from fastapi.testclient import TestClient
from tests.unit.test_quick_answer_ui import APP_JS, _run_js, needs_node

from product_app.main import app

#: Decision 8, the owner's wording, verbatim.
LAST_PART = (
    "See the estimate to check the cost first, or Run now to start straight away. "
    "If a run costs more than usual, it asks you first."
)
HINT_FOUR = "Your four models are picked for you — change any if you like. Press " + LAST_PART
HINT_HIGH_STAKES_FOUR = (
    "Your four models are picked for you — change any if you like. First tick I understand "
    "this is not professional advice above, then press " + LAST_PART
)
#: The server's limit on ``context.prior_synthesis``, as a literal (rule 7a).
PRIOR_SYNTHESIS_LIMIT = 60_117

FOUR = ["a/one", "b/two", "c/three", "d/four"]
CONTEXT = {"prior_question": "Which database first?", "prior_synthesis": "Postgres.\n\nSQLite."}


def _prior_answer_text(cases: list[list[Any]]) -> list[Any]:
    """Run ``priorAnswerText``, failing with a readable message, not the
    harness's ``substring not found``, while the function does not exist."""
    assert "function priorAnswerText(" in APP_JS.read_text(encoding="utf-8"), (
        "app.js has no self-contained priorAnswerText(result): the page cannot compose the "
        "previous final answer it must send (ADR-0143 decision 6)"
    )
    return _run_js("priorAnswerText", cases)


def _panel_result(**sections: str) -> dict[str, Any]:
    return {
        "mode": "panel",
        "result": {"final_synthesis": {"status": "completed", **sections}, "model_answers": []},
    }


# --- runRequestBody: one builder, the same context on every body --------------


@needs_node
def test_the_request_body_carries_the_follow_up_context_for_panel_and_quick() -> None:
    """RED IF: ``runRequestBody`` ignores a fifth ``context`` argument (on
    ``a4f1898`` it takes four, so no body ever carries context -- failure-modes
    row 2), or drops it on a quick body (row 12), or the estimate-shaped and
    create-shaped bodies carry different context (row 5: a confirm-band
    follow-up then loops on "the cost changed").
    """
    extra: dict[str, Any] = {"safety_acknowledgements": [], "cost_confirmation": None}
    got = _run_js(
        "runRequestBody",
        [
            ["Q2", FOUR, False, None, CONTEXT],
            ["Q2", FOUR, False, extra, CONTEXT],
            ["Q2", FOUR, True, None, CONTEXT],
            ["Q2", FOUR, True, extra, CONTEXT],
        ],
    )
    for body in got:
        assert body.get("context") == CONTEXT, f"body without the follow-up context: {body}"
        assert body["query_text"] == "Q2"
    panel_estimate, panel_create, quick_estimate, quick_create = got
    assert panel_estimate["model_slots"] == FOUR and quick_estimate["model_slots"] == ["a/one"]
    assert quick_estimate["mode"] == "quick" and quick_create["mode"] == "quick"
    assert panel_create["safety_acknowledgements"] == [] and "cost_confirmation" in panel_create
    assert panel_estimate["context"] == panel_create["context"] == quick_create["context"]


@needs_node
def test_without_context_the_request_body_is_byte_identical_to_before() -> None:
    """A GUARD (green before and after): a ``null``/absent fifth argument adds
    nothing -- no ``context`` key, no ``null`` value, same key order -- so a
    fresh question's bodies stay what W5 shipped. RED IF the build always
    writes a ``context`` key. Positive partner: the first case with context
    in the test above."""
    got = _run_js(
        "runRequestBody",
        [["Q", FOUR, False, None, None], ["Q", FOUR, True, None], ["Q", FOUR, False, None]],
    )
    serialised = [json.dumps(b, separators=(",", ":")) for b in got]
    assert serialised == [
        '{"query_text":"Q","model_slots":["a/one","b/two","c/three","d/four"]}',
        '{"query_text":"Q","model_slots":["a/one"],"mode":"quick"}',
        '{"query_text":"Q","model_slots":["a/one","b/two","c/three","d/four"]}',
    ]


# --- priorAnswerText: what "the previous final answer" is ----------------------


@needs_node
def test_the_prior_answer_is_the_five_sections_in_display_order_joined_by_blank_lines() -> None:
    """RED IF: ``priorAnswerText`` does not exist (``a4f1898``), or joins the
    sections in the payload's key order instead of the order the page shows
    them (the input below lists them in a DIFFERENT order on purpose), or adds
    headings (row 9: headings push a full answer over the server limit), or
    includes the high-stakes notice, which is not one of the five sections.
    """
    result = _panel_result(
        source_support="SECTION-S",
        recommendation="SECTION-R",
        uncertainty="SECTION-U",
        disagreement="SECTION-D",
        consensus="SECTION-C",
        high_stakes_notice="NOTICE-H",
    )
    (got,) = _prior_answer_text([[result]])
    assert got == "SECTION-C\n\nSECTION-D\n\nSECTION-U\n\nSECTION-R\n\nSECTION-S"


@needs_node
def test_the_prior_answer_is_cut_to_the_server_limit() -> None:
    """RED IF: the composed answer is not cut, or cut somewhere other than the
    server's 60,117-character limit (row 9: one character over is a 422 and the
    follow-up cannot be asked). Five 13,000-character sections join to 65,008.

    Positive partner: an answer under the limit comes back whole, so a function
    that always truncated to some smaller size also goes red.
    """
    letters = "CDURS"
    big = _panel_result(
        consensus="C" * 13_000,
        disagreement="D" * 13_000,
        uncertainty="U" * 13_000,
        recommendation="R" * 13_000,
        source_support="S" * 13_000,
    )
    full = "\n\n".join(ch * 13_000 for ch in letters)
    assert len(full) == 65_008
    small = _panel_result(
        consensus="c" * 100,
        disagreement="d" * 100,
        uncertainty="u" * 100,
        recommendation="r" * 100,
        source_support="s" * 100,
    )
    got_big, got_small = _prior_answer_text([[big], [small]])
    assert len(got_big) == PRIOR_SYNTHESIS_LIMIT
    assert got_big == full[:PRIOR_SYNTHESIS_LIMIT]
    assert got_small == "\n\n".join(ch * 100 for ch in "cdurs")


@needs_node
def test_a_quick_result_gives_its_answer_and_a_result_with_no_final_answer_gives_nothing() -> None:
    """RED IF: a quick result's previous answer is not its answer text (row 12),
    or a result with no final answer -- no ``final_synthesis``, or one whose
    five sections are all empty -- yields text, which would put "Follow up on
    this" on a result with nothing to follow (row 11).

    Positive partner: the quick case returns the real text, so "always empty"
    also goes red.
    """
    quick = {
        "mode": "quick",
        "result": {
            "final_synthesis": None,
            "model_answers": [
                {"slot_number": 1, "status": "completed", "answer_text": "QUICK-ANSWER-TEXT"}
            ],
        },
    }
    stopped = {"mode": "panel", "result": {"final_synthesis": None, "model_answers": []}}
    empty = _panel_result(
        consensus="", disagreement="", uncertainty="", recommendation="", source_support=""
    )
    got_quick, got_stopped, got_empty = _prior_answer_text([[quick], [stopped], [empty]])
    assert got_quick == "QUICK-ANSWER-TEXT"
    assert not got_stopped, f"a result with no final answer gave {got_stopped!r}"
    assert not got_empty, f"a result whose sections are all empty gave {got_empty!r}"


# --- handoffHintParts: the owner's wording (decision 8) ------------------------


def _joined(parts: list[dict[str, Any]]) -> str:
    return "".join(p["text"] for p in parts)


def _strong(parts: list[dict[str, Any]]) -> list[str]:
    return [p["text"] for p in parts if p.get("strong")]


@needs_node
def test_the_hint_ends_with_the_owners_wording() -> None:
    """RED IF: the hint's last part is not the owner's wording, verbatim --
    on ``a4f1898`` every variant ends "(it still asks first if the cost needs
    your approval)." -- or the bold parts stop being the button names.
    """
    four, three, two, one, high_four = _run_js(
        "handoffHintParts", [[4, False], [3, False], [2, False], [1, False], [4, True]]
    )
    assert _joined(four) == HINT_FOUR
    assert _joined(three) == HINT_FOUR.replace("Your four models", "Your three models")
    assert _joined(two) == HINT_FOUR.replace("Your four models", "Your two models")
    assert _joined(high_four) == HINT_HIGH_STAKES_FOUR
    # One model: the lead is the existing one; the ending is the owner's. The
    # joint between them ("Press" / "then press") is not pinned for this case.
    one_text = _joined(one)
    assert one_text.startswith("Your model is picked for you — change it if you like. ")
    assert one_text.endswith(LAST_PART)
    for parts in (four, three, two, one):
        assert _strong(parts) == ["See the estimate", "Run now"]
    assert _strong(high_four) == [
        "I understand this is not professional advice",
        "See the estimate",
        "Run now",
    ]
    for text in map(_joined, (four, three, two, one, high_four)):
        assert "it still asks first" not in text


# --- the served page ------------------------------------------------------------


def test_the_landing_button_reads_choose_models() -> None:
    """RED IF: the landing's ``#landing-run`` button still reads "Run the
    debate →" (decision 8), or the new label appears anywhere else on the
    served page. Positive partner: the button itself is found."""
    page = TestClient(app).get("/ui").text
    match = re.search(r'<button id="landing-run"[^>]*>(.*?)</button>', page, re.S)
    assert match is not None, "no #landing-run button on the served page"
    label = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    assert label == "Choose models →", label
    assert "Run the debate" not in html.unescape(page)


# --- review round 2: the cut never splits a character ----------------------------


def _lone_surrogates(text: str) -> list[int]:
    """Positions of UTF-16 surrogates left unpaired. ``json.loads`` joins a
    valid pair into one code point, so any surrogate left in a Python ``str``
    is a lone half."""
    return [i for i, ch in enumerate(text) if 0xD800 <= ord(ch) <= 0xDFFF]


def _utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


@needs_node
def test_the_cut_at_the_limit_never_leaves_half_a_character() -> None:
    """RED IF: ``priorAnswerText`` cuts at 60,117 UTF-16 units with a plain
    ``slice``, so 60,116 letters and an emoji end with a lone high surrogate
    (``\\ud83d``) -- text no server or model can read as written.

    Asserted for a panel answer and a quick answer: no lone surrogate, still at
    most 60,117 UTF-16 units (the server's limit). Positive partner: an answer
    under the limit keeps its emoji whole, so "drop every emoji" also goes red.
    """
    emoji = "\U0001f600"
    over = "a" * 60_116 + emoji + "tail"
    under = "a" * 100 + emoji
    panel = _panel_result(
        consensus=over, disagreement="", uncertainty="", recommendation="", source_support=""
    )
    quick = {
        "mode": "quick",
        "result": {
            "final_synthesis": None,
            "model_answers": [{"slot_number": 1, "status": "completed", "answer_text": over}],
        },
    }
    small = _panel_result(
        consensus=under, disagreement="", uncertainty="", recommendation="", source_support=""
    )
    got_panel, got_quick, got_small = _prior_answer_text([[panel], [quick], [small]])
    for got in (got_panel, got_quick):
        assert _lone_surrogates(got) == [], f"lone surrogate at {_lone_surrogates(got)}"
        assert _utf16_units(got) <= PRIOR_SYNTHESIS_LIMIT
        assert got.startswith("a" * 60_116)
    assert got_small == under
