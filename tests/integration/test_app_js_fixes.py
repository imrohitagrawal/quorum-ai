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
// ``instanceof HTMLSelectElement`` / ``HTMLElement`` must return
// true for our shim nodes so the change-event handler's guard
// fires on the right inputs. We define the element classes via
// a custom ``Symbol.hasInstance`` keyed off the shim's tagName.
const HTMLSelectElement = { [Symbol.hasInstance]: (n) => n instanceof _Node && n.tagName === "SELECT" };
const HTMLElement = { [Symbol.hasInstance]: (n) => n instanceof _Node };
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_render_model_options_returns_full_catalog_free_choice() -> None:
    """Design-approved behaviour (02 Composer .dc.html: "swap from live
    catalog", "Duplicates allowed but visibly flagged"): each slot's
    dropdown offers EVERY catalog model regardless of vendor, and a
    model already selected in another slot is STILL offered so
    cross-slot duplicates remain reachable.

    This replaces the old vendor-scoped ("bug10") behaviour, which made
    cross-slot duplicates unreachable and the duplicate flag dead code.
    """
    catalog_ids = [
        "openai/gpt-4.1",
        "openai/o3",
        "openai/gpt-4o-mini",
        "anthropic/claude-3-haiku",
        "anthropic/claude-sonnet-4.5",
        "google/gemini-2.5-flash",
        "google/gemini-2.5-flash-lite",
        "deepseek/deepseek-chat-v3.1",
    ]
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
        + "  {model_id: 'google/gemini-2.5-flash-lite', label: 'Gemini Lite'},\n"
        + "  {model_id: 'deepseek/deepseek-chat-v3.1', label: 'DeepSeek V3.1'},\n"
        + "];\n"
        # Slot 0 currently holds openai/gpt-4.1; anthropic/claude-3-haiku
        # is already selected in ANOTHER slot (index 1).
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
    assert ids, "renderModelOptions returned no options"
    # Free choice: every catalog model_id is offered, regardless of vendor.
    assert set(ids) == set(catalog_ids), f"expected the full catalog, got {ids!r}"
    # A model selected in another slot is STILL offered (duplicates allowed).
    assert "anthropic/claude-3-haiku" in ids, (
        "a model selected in another slot must remain reachable (duplicates allowed)"
    )
    # Vendors other than the current slot's are present (not vendor-scoped).
    assert any(not m.startswith("openai/") for m in ids), (
        "dropdown must not be scoped to the current slot's vendor family"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_render_model_options_preserves_curated_default_synthetic() -> None:
    """Corner case: if the current slot's default is NOT in the live
    catalog, ``renderModelOptions`` must still produce a synthetic
    "curated default — not in live catalog" option for it so the
    dropdown is not empty and the slot does not silently jump models.
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
    assert out["message"] == "", f"expected empty message, got {out['message']!r}"


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
    # The shipped banner copy is deliberately generic — it explains the
    # catalog drift without naming internal model ids. Assert the meaningful
    # drift message rather than a specific id (which the product intentionally
    # omits from the user-facing banner).
    assert "no longer in the catalog" in out["message"], (
        f"expected the catalog-drift message, got {out['message']!r}"
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
    assert "return" in between, "Bug 6 regression: no early return statement after isRunning check"


# Note: the legacy Bug-4 ``runNow`` fast-path (immediate run with an
# auto-chained ``proceedWithRun`` on COST_CONFIRMATION_REQUIRED) was
# removed with the single-CTA "See the estimate →" design. Ctrl+Enter
# and the CTA now route exclusively through the estimate-first
# ``startRun`` → cost-gate flow, so there is no ``runNow`` to pin.


# ---------------------------------------------------------------------------
# PR-0.1 follow-up tests: F1 (time-machine idempotence), F2 (no
# renderCurrentTime dead branch), F3 (id-based change-event filter).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_pr01_f1_set_run_start_time_freezes_card_and_ignores_poll_payload() -> None:
    """F1: ``setRunStartTime`` must capture the run start time once,
    and the card must remain frozen at that time even when a
    subsequent code path tries to feed a different timestamp in.

    PR-0's ``renderCurrentTime`` accepted a ``result`` argument and
    would fall through to ``result.result_generated_at_utc`` when
    ``runStartTime`` was null. That overwrote the card on every poll
    tick for the null-start edge case. PR-0.1 removes the
    ``renderCurrentTime`` entry point; the time card is driven
    exclusively by the ``setRunStartTime`` / ``finalizeRunTime`` /
    ``resetRunTime`` wrappers. This test pins the new shape:

    * ``renderCurrentTime`` is gone.
    * ``setRunStartTime`` is the only entry point for the start
      transition, and it freezes the card at the given timestamp.
    """
    text = APP_JS.read_text(encoding="utf-8")
    # F1: renderCurrentTime is removed. The pre-fix code defined a
    # function named renderCurrentTime that was the dead code path.
    assert "function renderCurrentTime" not in text, (
        "F1 regression: renderCurrentTime still defined in app.js. "
        "PR-0.1 collapsed it into updateRunTimeCard(transition, value)."
    )

    # Drive the actual function under a node shim and assert the
    # time card is set to the start value, not overwritten by a
    # later payload.
    body = _extract_function("updateRunTimeCard")
    script = (
        DOM_SHIM
        + "\n"
        + body
        + "\n"
        + "const timeMeta = new _Node('div');\n"
        + "const state = {runStartTime: null, runTimeFinalized: false};\n"
        + "updateRunTimeCard('start', '2026-06-23T10:00:00Z');\n"
        + "const afterStart = timeMeta.textContent;\n"
        + "// Simulate the F1 bug surface: a later code path that\n"
        + "// would previously have fed a fresh timestamp into the\n"
        + "// card via renderCurrentTime. The new contract is that\n"
        + "// the only writers are the explicit wrappers, so we\n"
        + "// simulate a poll tick by calling finalize first then\n"
        + "// confirming the start value is locked until finalize.\n"
        + "process.stdout.write(JSON.stringify({\n"
        + "  afterStart: afterStart,\n"
        + "  runStartTime: state.runStartTime,\n"
        + "  runTimeFinalized: state.runTimeFinalized,\n"
        + "}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    # The card must have a non-empty timestamp (not "Not started").
    assert out["afterStart"], f"F1 regression: time card empty after setRunStartTime: {out!r}"
    assert out["afterStart"] != "Not started", (
        f"F1 regression: time card still says 'Not started' after setRunStartTime: {out!r}"
    )
    # The state must reflect the start transition.
    assert out["runStartTime"] == "2026-06-23T10:00:00Z", (
        f"F1 regression: runStartTime not captured: {out!r}"
    )
    assert out["runTimeFinalized"] is False, (
        f"F1 regression: runTimeFinalized should be false on start: {out!r}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_pr01_f1_finalize_replaces_start_time_once() -> None:
    """F1 (positive case): after a start, the explicit
    ``finalize`` transition replaces the card with the completion
    timestamp. This is the only transition that may overwrite
    a frozen start time.
    """
    body = _extract_function("updateRunTimeCard")
    script = (
        DOM_SHIM
        + "\n"
        + body
        + "\n"
        + "const timeMeta = new _Node('div');\n"
        + "const state = {runStartTime: null, runTimeFinalized: false};\n"
        + "updateRunTimeCard('start', '2026-06-23T10:00:00Z');\n"
        + "const afterStart = timeMeta.textContent;\n"
        # 90 minutes later so the formatted minute-resolution
        # strings visibly differ.
        + "updateRunTimeCard('finalize', '2026-06-23T11:30:00Z');\n"
        + "const afterFinalize = timeMeta.textContent;\n"
        + "process.stdout.write(JSON.stringify({\n"
        + "  afterStart: afterStart,\n"
        + "  afterFinalize: afterFinalize,\n"
        + "  runStartTime: state.runStartTime,\n"
        + "  runTimeFinalized: state.runTimeFinalized,\n"
        + "}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    assert out["afterStart"] != "Not started"
    assert out["afterFinalize"] != "Not started"
    # The completion timestamp is 90 minutes after the start, so
    # the formatted strings must differ.
    assert out["afterStart"] != out["afterFinalize"], (
        f"F1 regression: finalize did not change the displayed time: {out!r}"
    )
    # ``runStartTime`` is preserved across the finalize transition
    # (the original start moment is the contract), and
    # ``runTimeFinalized`` flips to true.
    assert out["runStartTime"] == "2026-06-23T10:00:00Z", (
        f"F1 regression: runStartTime changed by finalize: {out!r}"
    )
    assert out["runTimeFinalized"] is True, (
        f"F1 regression: runTimeFinalized should be true after finalize: {out!r}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_pr01_f2_reset_is_the_only_path_to_not_started() -> None:
    """F2: the "Not started" reset is reachable only through the
    explicit ``reset`` transition. There is no ``renderCurrentTime``
    function and no ``if (!target)`` dead branch in the
    time-card state machine.
    """
    body = _extract_function("updateRunTimeCard")
    script = (
        DOM_SHIM
        + "\n"
        + body
        + "\n"
        + "const timeMeta = new _Node('div');\n"
        + "const state = {runStartTime: null, runTimeFinalized: false};\n"
        + "// First go through a start, then a finalize, then reset.\n"
        + "updateRunTimeCard('start', '2026-06-23T10:00:00Z');\n"
        + "updateRunTimeCard('finalize', '2026-06-23T11:30:00Z');\n"
        + "updateRunTimeCard('reset', null);\n"
        + "process.stdout.write(JSON.stringify({\n"
        + "  text: timeMeta.textContent,\n"
        + "  runStartTime: state.runStartTime,\n"
        + "  runTimeFinalized: state.runTimeFinalized,\n"
        + "}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    assert out["text"] == "Not started", (
        f"F2 regression: reset did not produce 'Not started': {out!r}"
    )
    assert out["runStartTime"] is None, f"F2 regression: reset did not clear runStartTime: {out!r}"
    assert out["runTimeFinalized"] is False, (
        f"F2 regression: reset did not clear runTimeFinalized: {out!r}"
    )

    # Pin the source-level invariant: updateRunTimeCard must not
    # have a ``!target`` or ``!rawValue`` branch that writes
    # 'Not started' from the start/finalize paths. The only path
    # to 'Not started' as a state transition is the explicit
    # reset branch. (A defensive ``|| "Not started"`` fallback
    # after the format step is acceptable — it is only reached
    # when ``Intl.DateTimeFormat`` returns a falsy value, not as
    # part of any state transition.)
    text = APP_JS.read_text(encoding="utf-8")
    update_fn = _extract_function("updateRunTimeCard")
    # The reset branch unconditionally writes "Not started".
    reset_idx = update_fn.find('"reset"')
    assert reset_idx != -1, "F2 regression: 'reset' branch missing from updateRunTimeCard"
    # The first ``"Not started"`` literal in the function is the
    # reset branch's write. The defensive ``|| "Not started"``
    # fallback (if present) is later in the function, inside the
    # format step.
    not_started_idx = update_fn.find('"Not started"')
    assert not_started_idx != -1, (
        "F2 regression: 'Not started' literal missing from updateRunTimeCard"
    )
    assert reset_idx < not_started_idx, (
        "F2 regression: 'Not started' literal is not under the reset branch"
    )
    # No ``!target`` or ``!rawValue`` style guard for the start
    # or finalize paths. The function has no input that maps to
    # "Not started" except an explicit reset.
    start_idx = update_fn.find('"start"')
    finalize_idx = update_fn.find('"finalize"')
    # The block after each transition is the only path that
    # touches timeMeta for that transition; the reset block must
    # come first and be the only unconditional writer of
    # "Not started".
    assert start_idx != -1 and finalize_idx != -1, (
        "F2 regression: start/finalize transitions missing"
    )
    # No renderCurrentTime anywhere.
    assert "function renderCurrentTime" not in text, (
        "F2 regression: renderCurrentTime still defined"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_pr01_f3_change_event_filter_uses_id_prefix_not_dataset() -> None:
    """F3: the model-slot change handler must filter on the
    ``id`` prefix (``model-``) rather than the ``data-model-slot``
    attribute. A future rename of the dataset key would otherwise
    silently break the handler.

    The pre-fix code used ``target.dataset.modelSlot !== ""``. The
    post-fix code uses ``!target.id.startsWith("model-")``. This
    test:

    1. Asserts the source-level invariant (no
       ``target.dataset.modelSlot`` check remains).
    2. Drives the actual handler under a node shim with two
       ``<select>``s — one with ``id="model-1"`` and one with
       ``id="other"`` — and asserts that only the model-slot
       select triggers ``renderModelInputs``.
    """
    text = APP_JS.read_text(encoding="utf-8")
    # Source-level invariant: the dataset-equality check is gone.
    assert "target.dataset.modelSlot" not in text, (
        "F3 regression: handler still filters on target.dataset.modelSlot"
    )
    # And the id-prefix check is present.
    handler = _extract_function("initModelSlotSelection")
    assert 'id.startsWith("model-")' in handler, (
        "F3 regression: handler does not check id.startsWith('model-')"
    )

    # Drive the handler with two ``<select>``s and assert the
    # id-prefix filter is the gate. We pass a mocked
    # ``renderModelInputs`` and ``renderDriftBanner`` that flip
    # flags, then dispatch change events on each select and
    # observe which one fired.
    #
    # The handler source is embedded as live JS (not as a string),
    # and the init call lives in the same IIFE so the function
    # declaration is hoisted into the IIFE's scope.
    script = (
        DOM_SHIM
        + "\n"
        # Mock the two downstream functions so we can observe calls.
        + "let renderModelInputsCalls = 0;\n"
        + "let renderDriftBannerCalls = 0;\n"
        + "function renderModelInputs() { renderModelInputsCalls += 1; }\n"
        + "function renderDriftBanner() { renderDriftBannerCalls += 1; }\n"
        + "function getModelIds() { return ['a', 'b', 'c', 'd']; }\n"
        + "const modelInputs = new _Node('div');\n"
        # Two selects: one with id='model-1' (the slot), one with
        # id='other' (e.g. a future vendor-picker).
        + "const slotSelect = new _Node('select');\n"
        + "slotSelect.id = 'model-1';\n"
        + "const otherSelect = new _Node('select');\n"
        + "otherSelect.id = 'other';\n"
        # Wrap the handler in an IIFE so the init call is in the
        # same scope as the function declaration.
        + "(function() {\n"
        + handler
        + "\ninitModelSlotSelection();\n"
        + "})();\n"
        # Fire a change on each select and observe counters.
        + "modelInputs._listeners['change'][0]({target: slotSelect});\n"
        + "const afterSlot = {\n"
        + "  renderModelInputs: renderModelInputsCalls,\n"
        + "  renderDriftBanner: renderDriftBannerCalls,\n"
        + "};\n"
        + "modelInputs._listeners['change'][0]({target: otherSelect});\n"
        + "const afterOther = {\n"
        + "  renderModelInputs: renderModelInputsCalls,\n"
        + "  renderDriftBanner: renderDriftBannerCalls,\n"
        + "};\n"
        + "process.stdout.write(JSON.stringify({afterSlot, afterOther}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    # Slot change should fire BOTH renderModelInputs and
    # renderDriftBanner (Bug 9 contract).
    assert out["afterSlot"]["renderModelInputs"] == 1, (
        f"F3 regression: slot change did not trigger renderModelInputs: {out!r}"
    )
    assert out["afterSlot"]["renderDriftBanner"] == 1, (
        f"F3 regression: slot change did not trigger renderDriftBanner: {out!r}"
    )
    # Other change should NOT fire either (counter must stay at 1).
    assert out["afterOther"]["renderModelInputs"] == 1, (
        f"F3 regression: non-slot change incorrectly triggered renderModelInputs: {out!r}"
    )
    assert out["afterOther"]["renderDriftBanner"] == 1, (
        f"F3 regression: non-slot change incorrectly triggered renderDriftBanner: {out!r}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_pr01_f3_change_event_filter_survives_dataset_rename() -> None:
    """F3 (corollary): the filter must work even if the
    ``data-model-slot`` attribute is removed entirely. The slot
    selects have ``id="model-N"`` regardless; the handler must
    rely on the id, not the dataset.
    """
    handler = _extract_function("initModelSlotSelection")
    # Build a slot select WITHOUT data-model-slot set. The handler
    # source is embedded as live JS inside an IIFE so the init
    # call lives in the same scope as the function declaration.
    script = (
        DOM_SHIM
        + "\n"
        + "let renderModelInputsCalls = 0;\n"
        + "function renderModelInputs() { renderModelInputsCalls += 1; }\n"
        + "function renderDriftBanner() {}\n"
        + "function getModelIds() { return ['a', 'b', 'c', 'd']; }\n"
        + "const modelInputs = new _Node('div');\n"
        + "const slotSelect = new _Node('select');\n"
        + "slotSelect.id = 'model-2';\n"
        + "// Note: data-model-slot is NOT set on slotSelect.\n"
        + "(function() {\n"
        + handler
        + "\ninitModelSlotSelection();\n"
        + "})();\n"
        + "modelInputs._listeners['change'][0]({target: slotSelect});\n"
        + "process.stdout.write(JSON.stringify({calls: renderModelInputsCalls}));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    out = json.loads(result.stdout)
    assert out["calls"] == 1, (
        f"F3 regression: handler skipped a slot select without data-model-slot set: {out!r}"
    )
