"""Slice 2 (03 Cost gate): the itemized by-model / by-stage partition.

The cost gate renders ``cost_estimate.breakdown`` two ways — by model
AND by stage — from the same total. The row-labelling logic lives in the
pure ``costGatePartitions`` helper in ``app.js`` (no DOM, no closures), so
we can exercise it directly via ``node`` the same way
``test_cost_formatter_js.py`` exercises ``formatUsd``.

Pinned contract:

* by_model uses each row's ``display_name``, EXCEPT the
  ``kind === "synthesis"`` row, which renders as "Synthesis writer".
* by_stage maps the server stage enum (``initial_answers`` /
  ``debate_round_1`` / ``debate_round_2`` / ``synthesis``) to the friendly
  labels, and an unknown stage falls back to its raw key.
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

import pytest

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
_BREAKDOWN = {
    "by_model": [
        {"model_id": "openai/gpt-4o-mini", "display_name": "GPT-4o mini", "usd": 0.034, "kind": "model"},
        {"model_id": "anthropic/claude-haiku", "display_name": "Claude Haiku 4.5", "usd": 0.062, "kind": "model"},
        {"model_id": "google/gemini-flash", "display_name": "Gemini 2.5 Flash", "usd": 0.031, "kind": "model"},
        {"model_id": "deepseek/deepseek-v3", "display_name": "DeepSeek V3.1", "usd": 0.039, "kind": "model"},
        {"model_id": "openai/gpt-4o-mini", "display_name": "GPT-4o mini (writer)", "usd": 0.024, "kind": "synthesis"},
    ],
    "by_stage": [
        {"stage": "initial_answers", "usd": 0.078},
        {"stage": "debate_round_1", "usd": 0.044},
        {"stage": "debate_round_2", "usd": 0.044},
        {"stage": "synthesis", "usd": 0.024},
    ],
    "total": 0.190,
}


def _run(breakdown: dict) -> dict:
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
    return json.loads(result.stdout)


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
    # The kind=="synthesis" row renders as the fixed "Synthesis writer"
    # label, NOT its raw display_name.
    assert labels[4] == "Synthesis writer"
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
    out = _run({"by_model": [], "by_stage": [{"stage": "mystery_stage", "usd": 0.01}], "total": 0.01})
    assert out["byStage"][0]["label"] == "mystery_stage"
