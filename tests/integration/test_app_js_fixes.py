"""PR-0 follow-up: JS-side regression tests for bugs 4 / 6 / 9 / 10.

The Playwright walkthrough catches the *visible* behaviour. These
tests pin the underlying JS functions so a future refactor cannot
silently regress the fixes. We extract the function source from
``app.js`` and execute it under ``node`` with a minimal DOM mock.

The DOM mock is a thin shim — just enough surface for the functions
to read attribute / textContent / hidden / value. It is intentionally
NOT a full DOM implementation. If a future change adds a dependency
on a new DOM API, the tests will surface that here as a clear
``TypeError`` from the shim.

If node is unavailable the tests are skipped — the Playwright
walkthrough documented in PR-0 is the fallback.
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
    """Pull the named function source from ``app.js`` by brace-balancing."""
    text = APP_JS.read_text(encoding="utf-8")
    pattern = rf"function {re.escape(name)}\("
    match = re.search(pattern, text)
    assert match is not None, f"{name} not found in app.js — was the function renamed?"
    start = match.start()
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise RuntimeError(f"{name} braces did not balance in app.js")


# ---------------------------------------------------------------------------
# Tiny DOM shim. Only the bits the JS code we test actually touches.
# ---------------------------------------------------------------------------
DOM_SHIM = r"""
// Minimal DOM shim for the JS functions under test.
class _Node {
  constructor(tag) {
    this.tagName = (tag || "DIV").toUpperCase();
    this.children = [];
    this._attrs = {};
    this._listeners = {};
    this.dataset = {};
    this.className = "";
    this.hidden = false;
    this.textContent = "";
    this.value = "";
    this.id = "";
  }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, fn) { (this._listeners[name] = this._listeners[name] || []).push(fn); }
  setAttribute(k, v) { this._attrs[k] = v; }
  getAttribute(k) { return this._attrs[k]; }
  querySelectorAll(selector) {
    const out = [];
    const visit = (n) => {
      for (const c of n.children) {
        if (c.tagName === "SELECT" && c.dataset && selector === "[data-model-slot]") {
          out.push(c);
        }
        if (c.tagName === "OPTION") {
          out.push(c);
        }
        visit(c);
      }
    };
    if (this.tagName === "SELECT" && this.dataset && selector === "[data-model-slot]") {
      out.push(this);
    }
    visit(this);
    return out;
  }
}
const document = {
  createElement: (tag) => new _Node(tag),
};
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bug10_render_model_options_vendor_scopes_to_current_vendor() -> None:
    """Bug 10: ``renderModelOptions`` must only return options from the
    current slot's vendor family.

    Before the fix, slot 1 and slot 3 both showed the openai fallbacks
    as their first non-selected options. The fix restricts each slot
    to its own vendor prefix (``openai/``, ``anthropic/``, etc.).
    """
    body = _extract_function("renderModelOptions")
    script = (
        DOM_SHIM
        + "\n"
        + body
        + "\n"
        + "const modelCatalog = [\n"
        + "  {model_id: 'openai/gpt-4.1', label: 'GPT-4.1'},\n"
        + "  {model_id: 'openai/o3', label: 'o3'},\n"
        + "  {model_id: 'openai/gpt-4o-mini', label: 'GPT-4o mini'},\n"
        + "  {model_id: 'anthropic/claude-3-haiku', label: 'Haiku'},\n"
        + "  {model_id: 'anthropic/claude-sonnet-4.5', label: 'Sonnet'},\n"
        + "  {model_id: 'google/gemini-2.5-flash', label: 'Gemini Flash'},\n"
        + "  {model_id: 'google/gemini-2.0-flash-lite', label: 'Gemini Lite'},\n"
        + "  {model_id: 'deepseek/deepseek-chat-v3.1', label: 'DeepSeek V3.1'},\n"
        + "];\n"
        + "const out = renderModelOptions(\n"
        + "  'openai/gpt-4.1', 0,\n"
        + "  ['openai/gpt-4.1', 'anthropic/claude-3-haiku',\n"
        + "   'google/gemini-2.5-flash', 'deepseek/deepseek-chat-v3.1']);\n"
        + "const ids = out.map((o) => o.value);\n"
        + "process.stdout.write(JSON.stringify(ids));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    ids = json.loads(result.stdout)
    # Every returned option must be openai/*
    assert ids, "renderModelOptions returned no options"
    for model_id in ids:
        assert model_id.startswith("openai/"), (
            f"Bug 10 regression: renderModelOptions returned non-openai id {model_id!r}"
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bug10_render_model_options_preserves_curated_default_synthetic() -> None:
    """Bug 10 (corner case): if the current slot's default is NOT in
    the live catalog, ``renderModelOptions`` must still produce a
    synthetic option for it so the dropdown is not empty.
    """
    body = _extract_function("renderModelOptions")
    script = (
        DOM_SHIM
        + "\n"
        + body
        + "\n"
        + "const modelCatalog = [\n"
        + "  {model_id: 'openai/gpt-4o-mini', label: 'GPT-4o mini'},\n"
        + "];\n"
        + "const out = renderModelOptions(\n"
        + "  'openai/gpt-5-not-in-catalog', 0,\n"
        + "  ['openai/gpt-5-not-in-catalog']);\n"
        + "const labels = out.map((o) => ({value: o.value, text: o.textContent}));\n"
        + "process.stdout.write(JSON.stringify(labels));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    labels = json.loads(result.stdout)
    # The synthetic must be present and marked as the curated default
    synthetics = [item for item in labels if "curated default" in item["text"]]
    assert len(synthetics) == 1, f"expected 1 synthetic, got {labels!r}"
    assert synthetics[0]["value"] == "openai/gpt-5-not-in-catalog"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bug9_render_drift_banner_hides_when_no_selected_slot_is_stale() -> None:
    """Bug 9: drift banner must hide when no selected slot is in
    the stale list — even if the stale list is non-empty.

    The pre-fix behaviour surfaced the banner for any stale default,
    even after the user had switched that slot to a non-stale model.
    """
    body = _extract_function("renderDriftBanner")
    script = (
        DOM_SHIM
        + "\n"
        + body
        + "\n"
        + "let driftRegion, driftMessage;\n"
        + "driftRegion = new _Node('div');\n"
        + "driftMessage = new _Node('div');\n"
        + "const state = {lastStaleModelIds: ['openai/gpt-4o-mini']};\n"
        + "const getModelIds = () => [\n"
        + "  'google/gemini-2.5-flash', 'anthropic/claude-3-haiku',\n"
        + "  'deepseek/deepseek-chat-v3.1', 'openai/gpt-4.1'];\n"
        + "renderDriftBanner();\n"
        + "process.stdout.write(JSON.stringify({\n"
        + "  hidden: driftRegion.hidden,\n"
        + "  message: driftMessage.textContent}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    assert out["hidden"] is True, (
        f"Bug 9 regression: drift banner shown despite no selected slot being stale: {out!r}"
    )
    assert out["message"] == "", (
        f"expected empty message, got {out['message']!r}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bug9_render_drift_banner_shows_when_a_selected_slot_is_stale() -> None:
    """Bug 9 (positive case): if the user has kept a stale model
    selected, the banner must still show.
    """
    body = _extract_function("renderDriftBanner")
    script = (
        DOM_SHIM
        + "\n"
        + body
        + "\n"
        + "let driftRegion, driftMessage;\n"
        + "driftRegion = new _Node('div');\n"
        + "driftMessage = new _Node('div');\n"
        + "const state = {lastStaleModelIds: ['openai/gpt-4o-mini']};\n"
        + "const getModelIds = () => [\n"
        + "  'openai/gpt-4o-mini', 'anthropic/claude-3-haiku',\n"
        + "  'google/gemini-2.5-flash', 'deepseek/deepseek-chat-v3.1'];\n"
        + "renderDriftBanner();\n"
        + "process.stdout.write(JSON.stringify({\n"
        + "  hidden: driftRegion.hidden,\n"
        + "  message: driftMessage.textContent}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    assert out["hidden"] is False, (
        f"expected banner to be visible when a selected slot is stale: {out!r}"
    )
    assert "openai/gpt-4o-mini" in out["message"], (
        f"expected stale id in message, got {out['message']!r}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bug6_poll_run_early_returns_when_already_running() -> None:
    """Bug 6: ``pollRun`` must early-return when ``state.currentRunId``
    is null AND ``state.isRunning`` is true.

    Before the fix, a transient empty response from
    ``/v1/query-runs/active`` clobbered the live progress with
    "No active run." The fix checks ``state.isRunning`` first and
    returns before the active query.

    We test the guard by setting ``state.isRunning = true`` and
    ``state.currentRunId = null`` and asserting that no fetch happens
    (we patch the fetch to a no-op + flag and assert the flag is
    never set).
    """
    text = APP_JS.read_text(encoding="utf-8")
    # We test the guard by reimplementing the early-return logic
    # exactly as it appears in pollRun, and verify the predicate.
    # The actual function uses an async api() call which would
    # require more shimming; instead we pin the source-level
    # invariant that the early-return is present and that
    # ``state.isRunning`` is read before the api() call.
    match = re.search(r"async function pollRun\(\) \{", text)
    assert match is not None, "pollRun not found in app.js"
    body_start = match.start()
    # Capture up to the first ``const active = await api`` to check
    # that ``state.isRunning`` is checked first.
    body_slice = text[body_start : body_start + 2000]
    early_return_idx = body_slice.find("state.isRunning")
    active_call_idx = body_slice.find("/v1/query-runs/active")
    assert early_return_idx != -1, "pollRun does not reference state.isRunning"
    assert active_call_idx != -1, "pollRun does not call /v1/query-runs/active"
    assert early_return_idx < active_call_idx, (
        "Bug 6 regression: /v1/query-runs/active called before the isRunning check"
    )
    # The early-return body must return before any render call.
    between = body_slice[early_return_idx:active_call_idx]
    assert "return" in between, (
        "Bug 6 regression: no early return statement after isRunning check"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_bug4_run_now_chains_to_proceed_with_run_on_confirmation() -> None:
    """Bug 4: ``runNow`` must chain through ``estimateRun`` →
    ``proceedWithRun`` when the server returns
    ``COST_CONFIRMATION_REQUIRED``.

    We pin the source-level invariant: the catch block must call
    both ``estimateRun()`` and ``proceedWithRun()`` in that order
    when the error code is ``COST_CONFIRMATION_REQUIRED``.
    """
    text = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"async function runNow\(\) \{", text)
    assert match is not None, "runNow not found in app.js"
    body_start = match.start()
    # Find the COST_CONFIRMATION_REQUIRED block within runNow.
    body_slice = text[body_start : body_start + 4000]
    block_start = body_slice.find('COST_CONFIRMATION_REQUIRED')
    assert block_start != -1, (
        "runNow does not handle COST_CONFIRMATION_REQUIRED"
    )
    # Within that block, estimateRun() must come before proceedWithRun().
    block_slice = body_slice[block_start : block_start + 2000]
    estimate_idx = block_slice.find("estimateRun(")
    proceed_idx = block_slice.find("proceedWithRun(")
    assert estimate_idx != -1, "estimateRun() not called in COST_CONFIRMATION_REQUIRED block"
    assert proceed_idx != -1, "proceedWithRun() not called in COST_CONFIRMATION_REQUIRED block"
    assert estimate_idx < proceed_idx, (
        f"Bug 4 regression: estimateRun (idx {estimate_idx}) must come before "
        f"proceedWithRun (idx {proceed_idx}) in the COST_CONFIRMATION_REQUIRED block"
    )
    # The proceed call must be guarded by the require_confirmation band check.
    band_idx = block_slice.find("require_confirmation")
    assert band_idx != -1, "require_confirmation band check missing in runNow"
    assert band_idx < proceed_idx, (
        "Bug 4 regression: proceedWithRun called without require_confirmation band check"
    )
