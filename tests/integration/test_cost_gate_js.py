"""Slice 2 (03 Cost gate): the itemized by-model / by-stage partition.

The cost gate renders ``cost_estimate.breakdown`` two ways — by model
AND by stage — from the same total. The row-labelling logic lives in the
pure ``costGatePartitions`` helper in ``app.js`` (no DOM, no closures), so
we can exercise it directly via ``node`` the same way
``test_cost_formatter_js.py`` exercises ``formatUsd``.

Pinned contract:

* by_model uses each row's ``display_name``, EXCEPT the
  ``kind === "synthesis"`` row, which renders as "Synthesis".
* by_stage maps the four PIPELINE stage keys (``initial_answers`` /
  ``debate_round_1`` / ``debate_round_2`` / ``synthesis``) to friendly labels,
  and any other stage falls back to its raw key. Those four are no longer the
  whole server enum: since ADR-0064 an estimate also carries a ``"judge"`` row
  when a Layer-B judge is configured, which is exactly the fallback case, and
  it must RENDER rather than be dropped — a dropped row makes the itemized
  lines under-sum the Total shown beside them.
* the slot-card fan-out takes only ``kind === "model"`` rows, so a breakdown
  carrying rows that are not slots cannot shift a price onto a slot card.
* Both partitions carry the SAME ``total`` (the reconciliation invariant),
  so each column's Total row shows the same figure.

If node is unavailable the test is skipped (mirrors the sibling test).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from product_app.costs import WRITER_ROW_DISPLAY_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"


def _extract_function(name: str) -> str:
    """Pull a top-level ``function <name>(...) {...}`` body from app.js.

    Brace-matches from the declaration so the JS source stays the single
    source of truth (the test breaks loudly if the function is renamed).
    """
    text = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"function " + re.escape(name) + r"\(", text)
    assert match is not None, f"{name} not found in app.js — was it renamed?"
    start = match.start()
    depth = 0
    started = False
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth == 0:
                return text[start : i + 1]
    raise RuntimeError(f"{name} braces did not balance in app.js")


# Canonical mock numbers from docs/design-handoff/SLICE_STATE.md §"Canonical
# numbers from the mock (screen 03 / 05)".
_BREAKDOWN: dict[str, Any] = {
    "by_model": [
        {
            "model_id": "openai/gpt-4o-mini",
            "display_name": "GPT-4o mini",
            "usd": 0.034,
            "kind": "model",
        },
        {
            "model_id": "anthropic/claude-haiku",
            "display_name": "Claude Haiku 4.5",
            "usd": 0.062,
            "kind": "model",
        },
        {
            "model_id": "google/gemini-flash",
            "display_name": "Gemini 2.5 Flash",
            "usd": 0.031,
            "kind": "model",
        },
        {
            "model_id": "deepseek/deepseek-v3",
            "display_name": "DeepSeek V3.1",
            "usd": 0.039,
            "kind": "model",
        },
        {
            "model_id": "openai/gpt-4o-mini",
            "display_name": "GPT-4o mini (writer)",
            "usd": 0.024,
            "kind": "synthesis",
        },
    ],
    "by_stage": [
        {"stage": "initial_answers", "usd": 0.078},
        {"stage": "debate_round_1", "usd": 0.044},
        {"stage": "debate_round_2", "usd": 0.044},
        {"stage": "synthesis", "usd": 0.024},
    ],
    "total": 0.190,
}


def _run(breakdown: dict[str, Any]) -> dict[str, Any]:
    body = _extract_function("costGatePartitions")
    script = (
        body
        + "\n"
        + f"const breakdown = {json.dumps(breakdown)};\n"
        + "process.stdout.write(JSON.stringify(costGatePartitions(breakdown)));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_cost_gate_by_model_labels_synthesis_writer() -> None:
    out = _run(_BREAKDOWN)
    labels = [row["label"] for row in out["byModel"]]
    # The four real model rows keep their display names, in slot order.
    assert labels[:4] == [
        "GPT-4o mini",
        "Claude Haiku 4.5",
        "Gemini 2.5 Flash",
        "DeepSeek V3.1",
    ]
    # The kind=="synthesis" row renders as a FIXED label, NOT its raw
    # display_name. Renamed "Debate + synthesis" -> "Synthesis" by #290 /
    # ADR-0093 decision 4: under a fully-eligible peer run that row holds no
    # debate spend at all. The override itself is unchanged and still
    # load-bearing — the fixture below sends "GPT-4o mini (writer)", the #16
    # defect, and it must not reach the receipt.
    assert labels[4] == "Synthesis"
    assert "GPT-4o mini (writer)" not in labels


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_cost_gate_by_stage_friendly_labels() -> None:
    out = _run(_BREAKDOWN)
    labels = [row["label"] for row in out["byStage"]]
    assert labels == [
        "Initial answers × 4",
        "Debate round 1",
        "Debate round 2",
        "Synthesis",
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_cost_gate_both_partitions_share_total() -> None:
    out = _run(_BREAKDOWN)
    # Both columns' Total row draws from the same breakdown.total.
    assert out["total"] == 0.190
    # And each partition's line items re-sum to that total (reconciliation
    # invariant preserved through the labelling map).
    assert round(sum(r["usd"] for r in out["byModel"]), 3) == 0.190
    assert round(sum(r["usd"] for r in out["byStage"]), 3) == 0.190


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_cost_gate_unknown_stage_falls_back_to_raw_key() -> None:
    out = _run(
        {"by_model": [], "by_stage": [{"stage": "mystery_stage", "usd": 0.01}], "total": 0.01}
    )
    assert out["byStage"][0]["label"] == "mystery_stage"


# --- ADR-0064: a breakdown that carries a priced advisory row ---------------

#: ``_BREAKDOWN`` plus the sixth ``by_model`` row and fifth ``by_stage`` row an
#: estimate carries when a Layer-B judge is configured. Deliberately a SEPARATE
#: fixture rather than a change to ``_BREAKDOWN``: the tests above pin the
#: canonical five-row mock and must keep seeing exactly that shape.
_BREAKDOWN_WITH_ADVISORY: dict[str, Any] = {
    "by_model": [
        *_BREAKDOWN["by_model"],
        {
            "model_id": "openai/gpt-5-mini",
            "display_name": "Layer-B judge",
            "usd": 0.033,
            "kind": "judge",
        },
    ],
    "by_stage": [*_BREAKDOWN["by_stage"], {"stage": "judge", "usd": 0.033}],
    "total": 0.223,
}


def _extract_per_model_estimate_chain() -> str:
    """Pull the REAL slot fan-out filter/map chain out of ``app.js``.

    Executing the shipped expression, rather than re-typing it here, is what
    makes this test structural instead of a substring check (rule 8): rewriting
    the predicate in ``app.js`` changes what runs below.
    """
    text = APP_JS.read_text(encoding="utf-8")
    match = re.search(
        r"state\.perModelEstimates = byModel\s*(\.filter\(.*?\.map\(.*?\));",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "the `state.perModelEstimates = byModel...` chain was not found in "
        "app.js — was the slot fan-out renamed or restructured?"
    )
    return match.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_slot_fan_out_ignores_rows_that_are_not_slots() -> None:
    """A non-slot ``by_model`` row must never reach the slot-indexed array.

    ``state.perModelEstimates`` is consumed BY POSITION — index *i* labels slot
    card *i*. The filter used to be a denylist (``kind !== "synthesis"``), i.e.
    "anything that is not the writer row is a slot". ADR-0064 adds a sixth row
    that is also not a slot, so the denylist would let it through; it is
    harmless only while the server happens to emit it last, which is a property
    this code should not depend on.

    WHAT TURNS THIS RED: restoring the denylist ``row.kind !== "synthesis"`` in
    ``app.js`` — the array below then has FIVE entries, one of them the
    advisory row's $0.033, sitting in the slot-indexed array.
    """
    chain = _extract_per_model_estimate_chain()
    script = (
        f"const byModel = {json.dumps(_BREAKDOWN_WITH_ADVISORY['by_model'])};\n"
        f"process.stdout.write(JSON.stringify(byModel{chain}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True, timeout=10
    )
    per_slot = json.loads(result.stdout)

    # POSITIVE PARTNER: the four real slot prices ARE present and in slot
    # order, so this is not "the filter returned nothing" passing vacuously.
    assert per_slot == [0.034, 0.062, 0.031, 0.039], (
        f"the slot fan-out produced {per_slot}; expected exactly the four "
        "kind=='model' rows, in slot order"
    )
    assert len(per_slot) == 4
    assert 0.033 not in per_slot, (
        "the advisory row's price reached the slot-indexed array; a slot card "
        "would show a price that is not that slot's"
    )
    # And the control: with no advisory row present the same chain is unchanged,
    # which is why this fix moves no rendering in the configuration CI runs.
    control_script = (
        f"const byModel = {json.dumps(_BREAKDOWN['by_model'])};\n"
        f"process.stdout.write(JSON.stringify(byModel{chain}));\n"
    )
    control = json.loads(
        subprocess.run(
            ["node", "-e", control_script],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    )
    assert control == [0.034, 0.062, 0.031, 0.039]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_an_unknown_stage_row_still_renders_with_its_raw_key() -> None:
    """The gate must not DROP a stage row it has no friendly label for.

    Both partitions are guaranteed to re-sum to ``total``, and the gate prints
    ``total`` beside the itemized rows. Dropping a row it does not recognise
    would show the user lines that visibly do not add up to the figure they are
    approving.

    WHAT TURNS THIS RED: rendering ``by_stage`` from a fixed list of known
    stage keys instead of from the response rows — the fifth row vanishes and
    the four remaining labels no longer account for ``total``.
    """
    out = _run(_BREAKDOWN_WITH_ADVISORY)
    labels = [row["label"] for row in out["byStage"]]
    # POSITIVE PARTNER: the four known stages still map to friendly labels, so
    # a fallback that swallowed everything would not pass this.
    assert labels[:4] == [
        "Initial answers × 4",
        "Debate round 1",
        "Debate round 2",
        "Synthesis",
    ]
    assert len(labels) == 5, f"a stage row was dropped: {labels}"
    assert labels[4] == "judge", (
        f"the unlabelled stage row rendered as {labels[4]!r}; it must fall back "
        "to its raw server key rather than disappear"
    )
    # The rows still account for the total the gate prints next to them.
    assert sum(row["usd"] for row in out["byStage"]) == pytest.approx(
        _BREAKDOWN_WITH_ADVISORY["total"]
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_the_javascript_writer_label_matches_the_server_constant() -> None:
    """RED WHEN: one of the two spellings of the writer label moves alone.

    ``app.js`` OVERRIDES the writer row's ``display_name`` with a literal, and
    the server emits ``costs.WRITER_ROW_DISPLAY_NAME`` for the same row. Two
    spellings for one label is how an estimate row and its measured row come to
    render as two unpaired half-rows on a money surface -- the same class of
    defect issue #217 fixed for the composite key. Nothing else compares them,
    because the override means the JavaScript never reads the server's string.

    Driven through the real gate rather than by grepping the file, so it pins
    what a browser would actually show.
    """
    out = _run(_BREAKDOWN)
    labels = [row["label"] for row in out["byModel"]]
    assert labels[4] == WRITER_ROW_DISPLAY_NAME, (
        f"app.js renders the writer row as {labels[4]!r} while the server sends "
        f"{WRITER_ROW_DISPLAY_NAME!r}"
    )
