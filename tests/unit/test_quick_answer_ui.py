"""W5, third of four pull requests (ADR-0128): the workspace UI for a quick answer.

The owner decided the copy on 2026-09-24 (CHG-012 D1): the control reads
"Quick answer — one model, no debate" and an info line reads "four models by
default, 2 debates and 1 sourced answer". The rest of this surface is the
session's design, recorded in ADR-0128.

The pure JavaScript functions are sliced out of ``app.js`` by brace count and
run under Node, the same way ``tests/unit/test_w4_copy_outside_run_path.py``
runs ``composerShapeCopy``; each must therefore stay self-contained (no call
into another ``app.js`` helper). The browser half, the toggle driving the real
request bodies and the quick result view, is
``e2e/tests/invariants/quick-answer.spec.ts``.

What turns each test red is stated on the test.
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

from product_app.evaluation import EvalJudgeVerdict
from product_app.main import app
from product_app.quick_verdict import QuickVerdict, reasons_for, verdict_level

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"
QUICK_VARIANTS_JSON = REPO_ROOT / "e2e" / "fixtures" / "quick-verdict-variants.json"

#: The owner's words, CHG-012 D1. The dash is U+2014.
QUICK_LABEL = "Quick answer — one model, no debate"
QUICK_INFO_LINE = "four models by default, 2 debates and 1 sourced answer"

#: The panel's cost-gate meta line at four models, as it shipped before W5.
PANEL_META_FOUR = "4 models · 2 debate rounds · synthesis · sourced answers where search succeeds"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


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


def _run_js(function_name: str, cases: list[list[Any]]) -> list[Any]:
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


def _composer_view(html: str) -> str:
    start = html.index('<div data-view="composer">')
    end = html.index('<div data-view="cost-gate"', start)
    return html[start:end]


def _landing_view(html: str) -> str:
    start = html.index('<div data-view="landing"')
    end = html.index("</section>", html.index("landing-disclaimers", start))
    return html[start:end]


# --- the served composer carries the owner's two sentences -------------------


def test_the_composer_carries_the_owners_two_sentences_once_each() -> None:
    """RED IF: the control label or the info line is reworded (including the
    em dash becoming a hyphen), duplicated, dropped, or moved out of the
    composer's model-slot fieldset.

    Counted in the whole served page, not searched, so a second copy anywhere
    (the landing, a hidden template) also goes red.
    """
    html = TestClient(app).get("/ui").text
    assert html.count(QUICK_LABEL) == 1
    assert html.count(QUICK_INFO_LINE) == 1
    composer = _composer_view(html)
    fieldset_start = composer.index('<fieldset class="field-group">')
    fieldset = composer[fieldset_start : composer.index("</fieldset>", fieldset_start)]
    assert QUICK_LABEL in fieldset and QUICK_INFO_LINE in fieldset
    # The info line ships hidden: the panel composer shows nothing new.
    note = re.search(r'<p id="quick-mode-note"[^>]*>', fieldset)
    assert note is not None and " hidden" in note.group(0)
    # The control is a real checkbox, labelled by the owner's words.
    assert re.search(r'<input type="checkbox" id="quick-mode-input"', fieldset)


def test_the_landing_never_gains_the_info_line() -> None:
    """RED IF: "1 sourced answer" (or the whole info line) reaches the landing
    view, which the owner refused (CHG-011 D1) and
    ``landing-cta-reachable.spec.ts`` bans.

    Positive partner: the same slice of the page does contain the landing's
    own headline, so an empty slice cannot pass.
    """
    html = TestClient(app).get("/ui").text
    landing = _landing_view(html)
    assert "Ask once. Let four minds argue it out." in landing
    assert "1 sourced answer" not in landing
    assert QUICK_LABEL not in landing


# --- the request bodies --------------------------------------------------------


@needs_node
def test_a_panel_request_body_is_unchanged_and_a_quick_one_carries_the_mode() -> None:
    """RED IF: a panel body gains ``mode`` (or any key) or changes key order;
    a quick body stops sending ``mode: "quick"``, sends more than one model,
    or ever sends ``context`` (refused server-side, ADR-0126 5a).

    Key ORDER is pinned by comparing the serialised JSON, which is what reaches
    the wire, so the panel body stays byte-identical to the pre-W5 one.
    """
    four = ["a/one", "b/two", "c/three", "d/four"]
    extra = {"safety_acknowledgements": [], "cost_confirmation": None}
    got = _run_js(
        "runRequestBody",
        [
            ["Q", four, False, None],
            ["Q", four, True, None],
            ["Q", four, False, extra],
            ["Q", four, True, extra],
        ],
    )
    serialised = [json.dumps(body, separators=(",", ":")) for body in got]
    assert serialised[0] == '{"query_text":"Q","model_slots":["a/one","b/two","c/three","d/four"]}'
    assert serialised[1] == '{"query_text":"Q","model_slots":["a/one"],"mode":"quick"}'
    assert serialised[2] == (
        '{"query_text":"Q","model_slots":["a/one","b/two","c/three","d/four"],'
        '"safety_acknowledgements":[],"cost_confirmation":null}'
    )
    assert serialised[3] == (
        '{"query_text":"Q","model_slots":["a/one"],"mode":"quick",'
        '"safety_acknowledgements":[],"cost_confirmation":null}'
    )
    assert all("context" not in body for body in got)


# --- the cost gate --------------------------------------------------------------


@needs_node
def test_the_cost_gate_meta_line_has_a_quick_sentence_and_the_panel_one_is_unchanged() -> None:
    """RED IF: the panel sentence changes at any size, or the quick sentence
    stops naming one model and no debate, or claims a judge check the estimate
    did not price.
    """
    got = _run_js(
        "costGateMetaText",
        [[4, False, False], [3, False, True], [2, False, False], [1, True, True], [1, True, False]],
    )
    assert got[0] == PANEL_META_FOUR
    assert got[1] == PANEL_META_FOUR.replace("4 models", "3 models")
    assert got[2] == PANEL_META_FOUR.replace("4 models", "2 models")
    assert got[3] == "1 model · no debate · judge check · sourced answer where search succeeds"
    assert got[4] == (
        "1 model · no debate · no judge configured · sourced answer where search succeeds"
    )


@needs_node
def test_the_cost_gate_stage_row_names_one_answer_on_a_quick_estimate() -> None:
    """RED IF: a quick estimate's stage table reads "Initial answers × 4", or
    the panel label changes."""
    source = APP_JS.read_text(encoding="utf-8")
    breakdown = {
        "by_model": [{"model_id": "a/one", "display_name": "One", "usd": "0.01", "kind": "model"}],
        "by_stage": [{"stage": "initial_answers", "usd": "0.01"}],
        "total": "0.01",
    }
    script = (
        _extract_function(source, "costGatePartitions")
        + f"\nconst b = {json.dumps(breakdown)};\n"
        + "console.log(JSON.stringify([costGatePartitions(b), costGatePartitions(b, true)]));\n"
    )
    out = json.loads(
        subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=10, check=True
        ).stdout
    )
    assert out[0]["byStage"][0]["label"] == "Initial answers × 4"
    assert out[1]["byStage"][0]["label"] == "The answer"


# --- the degraded banner at one model ---------------------------------------


@needs_node
def test_the_shortfall_copy_reads_sensibly_at_one_model_and_the_panel_copy_is_unchanged() -> None:
    """RED IF: a quick shortfall reads "None of the 1 models", mentions a
    debate or a synthesis, or a panel string changes.

    Both quick states a server can emit at one model are pinned whole: the
    answer simulated, and no answer at all.
    """
    got = _run_js(
        "describePanelShortfall",
        [
            [{"live": 0, "simulated": 1, "missing": 0, "total": 1, "quick": True}],
            [{"live": 0, "simulated": 0, "missing": 1, "total": 1, "quick": True}],
            [{"live": 0, "simulated": 0, "missing": 4, "total": 4}],
            [{"live": 0, "simulated": 4, "missing": 0, "total": 4}],
        ],
    )
    assert got[0] == {
        "title": "Simulated result — not from a real model",
        "message": (
            "Live execution was unavailable, so this answer comes from Quorum's local "
            "simulation, not from a real provider. Treat it as a demo, not a real model's answer."
        ),
    }
    assert got[1] == {
        "title": "No result — the model did not answer",
        "message": "The model returned no answer, so there is nothing below to rely on.",
    }
    for quick in got[:2]:
        text = (quick["title"] + quick["message"]).lower()
        assert "1 models" not in text and "debate" not in text and "synthesis" not in text
    # The panel strings, pinned as they shipped.
    assert got[2]["message"].startswith("None of the 4 models returned an answer")
    assert got[3]["message"].startswith(
        "Live execution was unavailable, so this whole result — the answers, the debate,"
    )


# --- the judge's heading -----------------------------------------------------------


@needs_node
def test_the_judge_heading_names_each_level_and_falls_back_to_not_checked() -> None:
    """RED IF: a level maps to the wrong words, or an absent/unknown level is
    shown as anything but "Not checked" (a level the judge did not give,
    ADR-0127 failure mode 2).
    """
    got = _run_js(
        "quickVerdictHeading",
        [
            ["well_supported"],
            ["partly_supported"],
            ["not_supported"],
            ["not_checked"],
            [None],
            ["excellent"],
        ],
    )
    assert got == [
        "Judge: Well supported",
        "Judge: Partly supported",
        "Judge: Not supported",
        "Judge: Not checked",
        "Judge: Not checked",
        "Judge: Not checked",
    ]


# --- the Copy summary never carries an agreement figure ----------------------


@needs_node
def test_the_quick_copy_summary_has_the_answer_and_the_verdict_and_no_agreement() -> None:
    """RED IF: the quick Copy summary drops the question, the model, the
    answer, the judge's heading or the run id, or prints an agreement figure
    ("N of M", "Opening positions", "aligned") — the owner decided a quick
    answer shows none.
    """
    got = _run_js(
        "quickCopySummary",
        [
            [
                {
                    "question": "Why?",
                    "modelLabel": "GPT-4o mini",
                    "answerText": "Because.",
                    "heading": "Judge: Well supported",
                    "correlationId": "qr_1",
                }
            ]
        ],
    )
    assert got[0] == (
        "Why?\n\nQuick answer (one model, no debate) from GPT-4o mini:\nBecause.\n\n"
        "Judge: Well supported\nRun: qr_1"
    )
    assert re.search(r"\b\d+ of \d+\b", got[0]) is None
    assert "Opening positions" not in got[0] and "aligned" not in got[0]


# --- which terminal runs open the result view ----------------------------------


@needs_node
def test_a_finished_quick_answer_opens_the_result_view_without_a_synthesis() -> None:
    """RED IF: a completed quick run (no synthesis, by design) stays on the
    live view, a quick run with no answer opens an empty result view, or a
    panel run's rule changes (it opens only with a synthesis).
    """
    answer = {"slot_number": 1, "answer_text": "x"}
    got = _run_js(
        "resultIsShowable",
        [
            [{"mode": "quick", "result": {"final_synthesis": None, "model_answers": [answer]}}],
            [{"mode": "quick", "result": {"final_synthesis": None, "model_answers": []}}],
            [{"mode": "panel", "result": {"final_synthesis": None, "model_answers": [answer]}}],
            [{"result": {"final_synthesis": {"status": "completed"}, "model_answers": []}}],
            [{}],
        ],
    )
    assert got == [True, False, False, True, False]


# --- the e2e quick-verdict fixture is a shape the server can serve -------------


def _variants() -> dict[str, dict[str, Any]]:
    data = json.loads(QUICK_VARIANTS_JSON.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def test_the_quick_verdict_fixtures_validate_against_the_served_model() -> None:
    """RED IF: a hand-written ``quick_verdict`` in the e2e fixture drifts from
    ``QuickVerdict`` (a key the server never emits, a level outside the enum),
    or its reasons stop being exactly the sentences ``reasons_for`` writes for
    its scores, so the browser gate would pass on a payload production cannot
    produce.

    Positive partner: both named variants are present and one of them carries
    reasons, so the loop below is not over nothing.
    """
    variants = _variants()
    assert set(variants) == {"WELL_SUPPORTED", "NOT_CHECKED"}
    for name, raw in variants.items():
        verdict = QuickVerdict.model_validate(raw)
        assert verdict.model_dump(mode="json") == raw, name
        if verdict.faithfulness is None:
            assert verdict.level == "not_checked" and verdict.reasons is None
            continue
        judge = EvalJudgeVerdict(
            faithfulness=verdict.faithfulness,
            grounding=verdict.grounding,
            disagreement_preserved=True,
            hallucination_risk=verdict.hallucination_risk,
            rationale="(not served)",
            model_id="fixture/judge",
        )
        assert verdict.level == verdict_level(judge)
        assert verdict.reasons == reasons_for(judge, source_count=len(verdict.sources_checked))
    assert variants["WELL_SUPPORTED"]["reasons"]
