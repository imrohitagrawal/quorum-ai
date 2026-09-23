"""W4, third pull request (ADR-0120, CHG-011): the copy outside the run path.

The product owner decided the wording on 2026-09-23 (CHG-011, decisions D1
to D6). This file pins the served literals and the two pure JavaScript copy
functions the composer and the transcript read.

What turns each test red is stated on the test. The JavaScript functions are
sliced out of ``app.js`` by brace count and run under Node, the same way
``tests/unit/test_demo_mode_banner_copy.py`` runs
``computeDemoModeBannerCopy``; each must therefore stay self-contained (no
call into another ``app.js`` helper).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from product_app import config
from product_app.main import _peer_critique_in_effect, _render_workspace_html, app

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"

# D1: the headline literal. It is the topbar's brand line, the one the owner
# named when refusing "2 to 4 AI models, 1 sourced answer".
LANDING_HEADLINE = "Four AI models, one sourced answer."
# D6: the landing eyebrow and h1 stay at four (D3: product copy describes the default).
LANDING_EYEBROW = "Four AI models · two debate rounds · one sourced answer"
LANDING_H1 = "Ask once. Let four minds argue it out."
# D2: one muted line, once, no price claim.
PANEL_SUBLINE = (
    "Your panel, your size: four models by default, three or two when that is all you need."
)
# D4: a capability line naming both shapes.
DEBATE_LINE = (
    "Two rounds of debate, by the panel itself or by a moderator model, then one sourced synthesis."
)


def _visible_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    return text


def _landing_view(html: str) -> str:
    """The landing view's markup only (``<div data-view="landing" ...>``)."""
    start = html.index('<div data-view="landing"')
    end = html.index("</section>", html.index("landing-disclaimers", start))
    return html[start:end]


def _readiness_island(html: str) -> dict[str, Any]:
    match = re.search(r"window\.LIVE_READINESS\s*=\s*(\{.*?\});", html)
    assert match is not None, "no LIVE_READINESS island in the rendered workspace"
    island = json.loads(match.group(1))
    assert isinstance(island, dict)
    return island


# --- the served landing (D1, D2, D4) -----------------------------------------


def test_the_served_page_carries_each_decided_literal_exactly_once() -> None:
    """RED IF: the headline, eyebrow, h1, panel subline or debate line is
    reworded, duplicated or dropped (D1, D2, D4, D6).

    Each literal is counted, not searched: D2 says the subline appears ONCE.
    """
    html = TestClient(app).get("/ui").text
    visible = _visible_text(html)
    for literal in (LANDING_HEADLINE, LANDING_EYEBROW, LANDING_H1, PANEL_SUBLINE, DEBATE_LINE):
        assert visible.count(literal) == 1, (
            f"expected exactly one copy of {literal!r}; found {visible.count(literal)}"
        )


def test_the_landing_never_sells_a_range_or_a_saving() -> None:
    """RED IF: the landing headline area reads a range ("2 to 4") or price copy
    says "half" — both are rejected decisions (CHG-011).

    Positive partner first: the landing view is rendered and carries the
    decided lines, so the absences below are asserted over real text.
    """
    html = TestClient(app).get("/ui").text
    landing = _visible_text(_landing_view(html))
    assert PANEL_SUBLINE in landing and DEBATE_LINE in landing and LANDING_H1 in landing
    # D2 says "under the headline": both lines sit inside the hero block.
    hero_start = html.index('<div class="landing-hero">')
    hero = html[hero_start : html.index("</div>", html.index(PANEL_SUBLINE, hero_start))]
    assert LANDING_H1 in hero and DEBATE_LINE in hero and PANEL_SUBLINE in hero
    lowered = landing.lower()
    for banned in ("2 to 4", "2-4", "two to four ai models", "1 sourced answer"):
        assert banned not in lowered, f"the landing reads a range: {banned!r}"
    assert re.search(r"\bhalf\b", lowered) is None, "the landing sells a saving of 'half'"


def test_the_panel_subline_makes_no_price_claim() -> None:
    """RED IF: the subline (D2) gains a cost, price, dollar or percentage."""
    lowered = PANEL_SUBLINE.lower()
    assert "four models by default" in lowered  # positive partner: it is the decided line
    for banned in ("$", "%", "cost", "price", "cheap", "half", "save"):
        assert banned not in lowered, f"D2 forbids a price claim; found {banned!r}"


# --- the readiness island carries the shape predicate (D5) -------------------


def test_the_readiness_island_reports_whether_peer_critique_is_in_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: ``window.LIVE_READINESS`` stops carrying ``peer_critique_in_effect``
    or carries something other than ``_peer_critique_in_effect(settings)``.

    The composer's shape line (D5) reads this key; it must be the SAME
    predicate the landing subhead and ``/status`` read (ADR-0116), never the
    flag alone: the flag-on, live-off posture is production's, and it is False.
    """
    postures = [
        (True, True, "sk-not-a-real-key", True),
        (True, False, "sk-not-a-real-key", False),  # production's posture
        (False, True, "sk-not-a-real-key", False),
        (True, True, "", False),
    ]
    seen: set[bool] = set()
    for flag, live, key, expected in postures:
        monkeypatch.setattr(config.settings, "peer_critique_enabled", flag)
        monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", live)
        monkeypatch.setattr(config.settings, "openrouter_api_key", key)
        island = _readiness_island(_render_workspace_html())
        assert island["peer_critique_in_effect"] is expected
        assert island["peer_critique_in_effect"] is _peer_critique_in_effect(config.settings)
        seen.add(island["peer_critique_in_effect"])
    assert seen == {True, False}, "both postures must be reachable, or the key is a constant"


def test_the_served_island_agrees_with_status() -> None:
    """RED IF: ``/ui``'s island and ``/status`` disagree about the shape."""
    client = TestClient(app)
    island = _readiness_island(client.get("/ui").text)
    status = client.get("/status").json()
    assert isinstance(island["peer_critique_in_effect"], bool)
    assert island["peer_critique_in_effect"] is status["peer_critique_in_effect"]


# --- the JavaScript copy functions (D5, D6) ----------------------------------


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _extract_function(source: str, name: str) -> str:
    """Slice ``function name(...) { ... }`` out of ``source`` by brace count."""
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


def _run_js(function_name: str, cases: list[list[Any]]) -> list[str]:
    source = APP_JS.read_text(encoding="utf-8")
    script = (
        _extract_function(source, function_name)
        + "\n\nconst cases = "
        + json.dumps(cases)
        + f";\nconsole.log(JSON.stringify(cases.map((args) => {function_name}(...args))));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=10, check=True
    )
    out = json.loads(result.stdout)
    assert isinstance(out, list)
    return out


MODERATOR_SECOND_SENTENCE = (
    "Peer critique, where each model critiques the others, is available and off on this deployment."
)


def test_composer_shape_copy_reads_the_count_and_the_shape() -> None:
    """RED IF: ``composerShapeCopy`` stops branching on the count or on the
    shape, or either sentence is reworded (D5).

    All six cells are pinned as literals, and the two shapes must differ at
    every count, or a function that ignores its second argument would pass.
    """
    got = _run_js(
        "composerShapeCopy",
        [[4, False], [3, False], [2, False], [4, True], [3, True], [2, True]],
    )
    expected = [
        "This run: a moderator model critiques all four answers, in two rounds, then one sourced "
        "synthesis. " + MODERATOR_SECOND_SENTENCE,
        "This run: a moderator model critiques all three answers, in two rounds, then one sourced "
        "synthesis. " + MODERATOR_SECOND_SENTENCE,
        "This run: a moderator model critiques both answers, in two rounds, then one sourced "
        "synthesis. " + MODERATOR_SECOND_SENTENCE,
        "This run: each of the four models critiques the others, in two rounds, then one sourced "
        "synthesis.",
        "This run: each of the three models critiques the others, in two rounds, then one sourced "
        "synthesis.",
        "This run: both models critique each other, in two rounds, then one sourced synthesis.",
    ]
    assert got == expected
    for moderator, peer in zip(got[:3], got[3:], strict=True):
        assert moderator != peer
        assert "moderator" not in peer, "the peer shape names a moderator that does not run"
        assert "off on this deployment" in moderator


def test_model_card_info_text_reads_the_count_and_the_shape() -> None:
    """RED IF: the transcript's model-card tooltip stops reading the panel size
    or the shape (D6). The four-moderator cell is the pre-change literal, so
    the default panel's transcript view stays byte-identical.
    """
    got = _run_js("modelCardInfoText", [[4, False], [3, False], [2, False], [4, True], [2, True]])
    assert got == [
        "This shows one model's answer. It is the model's only answer — it is not revised. "
        "Once all four respond, a separate moderator model reads all four and writes the debate "
        "critique.",
        "This shows one model's answer. It is the model's only answer — it is not revised. "
        "Once all three respond, a separate moderator model reads all three and writes the debate "
        "critique.",
        "This shows one model's answer. It is the model's only answer — it is not revised. "
        "Once both respond, a separate moderator model reads both and writes the debate critique.",
        "This shows one model's answer. It is the model's only answer — it is not revised. "
        "Once all four respond, each model reads the others and writes its own critique.",
        "This shows one model's answer. It is the model's only answer — it is not revised. "
        "Once both respond, each model reads the other and writes its own critique.",
    ]


def test_landing_handoff_copy_reads_the_panel_size() -> None:
    """RED IF: the landing-to-composer message stops reading the count (D6).

    The four-model cells are the pre-change literals.
    """
    got = _run_js("landingHandoffCopy", [["estimate", 4], ["run", 4], ["estimate", 2], ["run", 3]])
    assert got == [
        "Got your question. Taking you to review your four models and see the itemized cost "
        "before anything runs…",
        "Got your question. Taking you to review your four models, then we'll price it and run "
        "once you approve…",
        "Got your question. Taking you to review your two models and see the itemized cost "
        "before anything runs…",
        "Got your question. Taking you to review your three models, then we'll price it and run "
        "once you approve…",
    ]


def test_the_hidden_debate_panel_no_longer_hard_codes_four() -> None:
    """RED IF: the ``.panel.panel-section`` placeholders name "four" again.

    That section is ``display: none`` on every view (app.css), so it gets
    neutral literals rather than a renderer; this pins that the count-bound
    wording did not come back. Positive partner: the placeholders exist.
    """
    html = (REPO_ROOT / "src/product_app/templates/workspace.html").read_text(encoding="utf-8")
    start = html.index("<h2>Debate and synthesis</h2>")
    end = html.index("</section>", start)
    section = html[start:end]
    assert 'id="debate-output"' in section and 'id="synthesis-output"' in section
    assert "four" not in section.lower(), "the hidden debate panel names a fixed panel size"
