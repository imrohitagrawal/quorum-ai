"""W127 (board rows W127 and W49): the page's run-scope functions, under Node.

The functions are lifted out of the served ``app.js`` by brace count with the
late-run suite's harness (``tests/unit/test_late_run_question_rules.py``):
each one runs inside a scope where a name the harness does not provide is a
no-op function, so a test replaces the renderers it watches with counters.
A helper the builder adds and these functions call must be listed in the
test's function list, or it runs as a no-op (memory: JS harnesses extract one
function).

The interface these tests fix, from the work item's plan (revision 2). Where
the plan leaves a detail open, the choice made here is stated, because the
builder may not edit this file:

* ``state.runScope = {id, runId, terminalHandled, closed}``, replaced (never
  mutated back) by ``beginRunScope(runId, question)``; ``question`` is
  optional and an adopted run passes none.
* ``pollRun()`` called with no argument captures ``state.runScope`` when it
  sends its GET, and drops the answer before ANY rendering unless
  ``scope === state.runScope && !scope.closed && !scope.terminalHandled &&
  result.query_run_id === scope.runId``. A rejected poll checks the first
  three; it may be checked in ``startPolling``, ``pollRun`` or
  ``handlePollError`` (all three run for real here).
* ``finishRun(result, scope)``: the terminal branch of ``pollRun``, toasting
  by the status the server returned, once per scope.
* ``renderComposerTotal()`` writes ``#composer-total-estimate``: the amount of
  ``state.currentEstimate`` while the current inputs (trimmed question,
  ``getModelIds()`` in order, ``state.quickMode``, ``state.followUpContext``'s
  two values) equal the priced inputs in ``state.pricedRun``
  (``{queryText, modelIds, quick, context}``, its shape today), else "—".

Every test names what turns it red.
"""

from __future__ import annotations

import json
from typing import Any

from tests.unit.test_late_run_question_rules import APP_JS, _node

RUN = "aaaaaaaa-0000-4000-8000-00000000000a"
OTHER = "bbbbbbbb-0000-4000-8000-00000000000b"

#: Every name whose call is a visible change: what ``pollRun`` and its
#: terminal branch draw, toast or record.
RENDERERS = [
    "updateRunMeta",
    "renderProgress",
    "renderLiveRun",
    "renderModelPanels",
    "renderDebateAndSynthesis",
    "renderNotices",
    "renderResult",
    "setView",
    "toast",
    "finishRun",
    "appendSessionTrailEntry",
    "showError",
    "showProviderFailure",
    "handleError",
    "showNetworkIndicator",
]


def _require(*names: str) -> None:
    source = APP_JS.read_text(encoding="utf-8")
    missing = [name for name in names if f"function {name}(" not in source]
    assert not missing, (
        f"app.js has no function {', '.join(missing)}(): the run scope this test checks "
        "does not exist yet"
    )


def _counters() -> str:
    """JavaScript that replaces each renderer with a counter."""
    return (
        "const calls = [];\n"
        f"for (const name of {json.dumps(RENDERERS)}) "
        "__stubs[name] = function () { calls.push(name); };\n"
    )


_RUNNING = {
    "query_run_id": RUN,
    "status": "initial_answers_running",
    "progress": {"current_stage": "initial_answers", "stages": []},
    "result": {"model_answers": [], "debate_outputs": [], "final_synthesis": None},
    "model_slots": [],
}

#: Replace ``state.runScope`` with a new scope for the SAME run.
_REPLACE_SCOPE = (
    f"state.runScope = {{ id: 2, runId: {json.dumps(RUN)}, "
    "terminalHandled: false, closed: false };"
)

_OPEN_SCOPE = r"""
const pending = [];
api = (path, options) => new Promise((resolve, reject) =>
  pending.push({ path, method: options && options.method, resolve, reject }));
state.currentRunId = __RUN__;
state.isRunning = true;
state.terminalHandled = false;
state.liveSig = { stage: null, debate: null, models: null, fallback: null, notices: null };
const scope = { id: 1, runId: __RUN__, terminalHandled: false, closed: false };
state.runScope = scope;
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
"""


def _poll(mutation: str, answer: dict[str, Any]) -> dict[str, Any]:
    """Send one poll for the open scope, apply ``mutation`` while it is in
    flight, answer it, and report what was drawn."""
    _require("pollRun")
    body = (
        _counters()
        + _OPEN_SCOPE.replace("__RUN__", json.dumps(RUN))
        + "const run = pollRun();\nawait tick();\n"
        + "if (!pending.length) return { sent: [], calls: ['no GET was sent'] };\n"
        + "const sent = pending.map((p) => p.method + ' ' + p.path);\n"
        + mutation
        + "\ncalls.length = 0;\n"
        + f"pending[0].resolve({json.dumps(answer)});\n"
        + "try { await run; } catch (e) { calls.push('threw ' + e); }\n"
        + "await tick();\nreturn { sent, calls };"
    )
    got: dict[str, Any] = _node(["pollRun"], body)
    return got


# --- the poll drop rule: each condition alone ---------------------------------


def test_a_poll_for_the_open_scope_is_drawn() -> None:
    """The positive partner of the four drop tests below: with nothing
    changed, the answer is drawn. RED IF ``pollRun()`` with no argument no
    longer captures ``state.runScope`` (it would then drop everything, and the
    four tests below would pass over a function that never draws)."""
    got = _poll("", _RUNNING)
    assert got["sent"] == [f"GET /v1/query-runs/{RUN}"]
    assert "renderLiveRun" in got["calls"], got


def test_a_poll_answered_after_its_scope_was_replaced_draws_nothing() -> None:
    """RED IF ``pollRun`` draws an answer although ``state.runScope`` was
    replaced while it was in flight (a new run, "Go to run", a restore): on
    ``f10c754`` it checks no scope at all (a late answer for an earlier run)."""
    got = _poll(
        _REPLACE_SCOPE,
        _RUNNING,
    )
    assert got["calls"] == [], f"drawn for a replaced scope: {got['calls']}"


def test_a_poll_answered_after_stop_closed_the_scope_draws_nothing() -> None:
    """RED IF ``pollRun`` draws an answer that arrives after Stop set
    ``scope.closed`` (the pill goes back to Running)."""
    got = _poll("scope.closed = true;", _RUNNING)
    assert got["calls"] == [], f"drawn for a closed scope: {got['calls']}"


def test_a_poll_answered_after_the_scope_finished_draws_nothing() -> None:
    """RED IF ``pollRun`` draws an answer that arrives after the scope's
    terminal answer was handled (``scope.terminalHandled``): on ``f10c754``
    the renders run before the only, page-wide ``terminalHandled`` check."""
    got = _poll("scope.terminalHandled = true;", _RUNNING)
    assert got["calls"] == [], f"drawn for a finished scope: {got['calls']}"


def test_a_poll_answer_for_another_run_draws_nothing() -> None:
    """RED IF ``pollRun`` draws an answer whose ``query_run_id`` is not the
    scope's run, with the scope itself untouched (the answer-side check)."""
    got = _poll("", {**_RUNNING, "query_run_id": OTHER})
    assert got["calls"] == [], f"drawn for another run's answer: {got['calls']}"


# --- a rejected poll ------------------------------------------------------------

_FUNCS_POLLING = ["startPolling", "pollRun", "handlePollError"]


def _rejected(mutation: str) -> list[str]:
    _require(*_FUNCS_POLLING)
    body = (
        _counters()
        + _OPEN_SCOPE.replace("__RUN__", json.dumps(RUN))
        + "window.setInterval = () => 7;\nwindow.clearInterval = () => {};\n"
        + "startPolling();\nawait tick();\n"
        + "if (!pending.length) return ['no GET was sent'];\n"
        + mutation
        + "\ncalls.length = 0;\n"
        + "pending[0].reject(Object.assign(new Error('Failed to fetch'), "
        + "{ code: 'NETWORK_UNREACHABLE', status: 0 }));\n"
        + "await tick();\nawait tick();\nreturn calls;"
    )
    got: list[str] = _node(_FUNCS_POLLING, body)
    return got


def test_a_rejected_poll_for_the_open_scope_raises_the_connection_notice() -> None:
    """The positive partner of the three tests below. RED IF a network
    failure while the run is open no longer raises the connection notice."""
    assert "showNetworkIndicator" in _rejected("")


def test_a_poll_rejected_after_its_scope_was_replaced_is_ignored() -> None:
    """RED IF a rejected poll raises a notice or a toast after
    ``state.runScope`` was replaced."""
    got = _rejected(_REPLACE_SCOPE)
    assert got == [], got


def test_a_poll_rejected_after_stop_is_ignored() -> None:
    """RED IF a rejected poll raises "Connection lost — retrying…" after Stop
    closed the scope (``stopPolling`` had just cleared it)."""
    assert _rejected("scope.closed = true;") == []


def test_a_poll_rejected_after_the_scope_finished_is_ignored() -> None:
    """RED IF a rejected poll raises a notice or toast after the scope's
    terminal answer was handled."""
    assert _rejected("scope.terminalHandled = true;") == []


# --- finishRun -----------------------------------------------------------------

_PANEL_SYNTHESIS = {"status": "completed", "consensus": "C"}
_FINISHED = {
    "completed panel": {
        "status": "completed",
        "mode": "panel",
        "result": {"final_synthesis": _PANEL_SYNTHESIS, "model_answers": []},
    },
    "completed quick": {
        "status": "completed",
        "mode": "quick",
        "result": {
            "final_synthesis": None,
            "model_answers": [{"status": "completed", "answer_text": "The answer."}],
        },
    },
    "partial": {
        "status": "partial",
        "mode": "panel",
        "result": {"final_synthesis": _PANEL_SYNTHESIS, "model_answers": []},
    },
    "failed": {"status": "failed", "mode": "panel", "result": {"final_synthesis": None}},
    "timed_out": {"status": "timed_out", "mode": "panel", "result": {"final_synthesis": None}},
    "cancelled": {"status": "cancelled", "mode": "panel", "result": {"final_synthesis": None}},
}

_FINISH_PAGE = r"""
const toasts = [];
const trail = [];
const views = [];
toast = (o) => toasts.push(o && o.message);
appendSessionTrailEntry = (e) => trail.push(e);
setView = (name) => views.push(name);
liveNoticesHaveContent = () => false;
state.sessionTrail = [];
state.liveQueryText = "The question";
const finish = async (result, scope) => {
  toasts.length = 0; trail.length = 0; views.length = 0;
  await finishRun(result, scope);
  return {
    toasts: [...toasts],
    trail: trail.map((e) => ({ runId: e.runId, status: e.status })),
    result: views.includes("result"),
    terminalHandled: scope.terminalHandled,
  };
};
const scopeFor = (id, runId) => {
  const scope = { id, runId, terminalHandled: false, closed: false };
  state.runScope = scope;
  state.currentRunId = runId;
  state.terminalHandled = false;
  return scope;
};
"""


def _finish(body: str) -> Any:
    _require("finishRun")
    return _node(["finishRun", "resultIsShowable"], _FINISH_PAGE + body)


def test_finish_run_toasts_the_status_the_server_returned() -> None:
    """RED IF ``finishRun(result, scope)`` does not exist (``f10c754``:
    ``cancelRun`` toasts "Run cancelled." whatever the DELETE returned),
    or toasts anything but the poll's own message for a status: a
    completed run is never called cancelled, and only a cancelled one is.
    Each call also writes ONE session-list entry (``cancelRun`` writes none
    today) and marks its scope finished.
    """
    cases = [{**r, "query_run_id": RUN} for r in _FINISHED.values()]
    got = _finish(
        f"const cases = {json.dumps(cases)};\n"
        "const out = [];\n"
        "for (let i = 0; i < cases.length; i++)\n"
        "  out.push(await finish(cases[i], scopeFor(i + 1, cases[i].query_run_id)));\n"
        "return out;"
    )
    by_case = dict(zip(_FINISHED, got, strict=True))
    assert {k: v["toasts"] for k, v in by_case.items()} == {
        "completed panel": ["Run completed. See the synthesis below."],
        "completed quick": ["Run completed. See the answer below."],
        "partial": ["Run finished with partial results — some steps did not complete."],
        "failed": ["Run failed. See the banner above."],
        "timed_out": ["Run timed out. See error banner above."],
        "cancelled": ["Run cancelled."],
    }
    assert {k: v["result"] for k, v in by_case.items()} == {
        "completed panel": True,
        "completed quick": True,
        "partial": True,
        "failed": False,
        "timed_out": False,
        "cancelled": False,
    }
    for name, outcome in by_case.items():
        assert len(outcome["trail"]) == 1, f"{name}: {outcome['trail']}"
        assert outcome["trail"][0]["runId"] == RUN, f"{name}: {outcome['trail']}"
        assert outcome["terminalHandled"] is True, name
    assert by_case["cancelled"]["trail"][0]["status"] == "cancelled"


def test_finish_run_runs_once_per_scope() -> None:
    """RED IF a second ``finishRun`` for the same scope toasts or records
    again (a double "Run cancelled." from a late poll or a second Stop), or if a NEW scope is
    blocked by the previous one's guard (the page-wide ``terminalHandled``
    left over from an earlier run is W49).

    Cardinality, not presence (rule 6b): exactly one toast and one entry per
    scope.
    """
    done = {**_FINISHED["completed panel"], "query_run_id": RUN}
    again = {**_FINISHED["cancelled"], "query_run_id": OTHER}
    got = _finish(
        f"const first = scopeFor(1, {json.dumps(RUN)});\n"
        f"const a = await finish({json.dumps(done)}, first);\n"
        f"const b = await finish({json.dumps(done)}, first);\n"
        f"const c = await finish({json.dumps(again)}, scopeFor(2, {json.dumps(OTHER)}));\n"
        "return [a, b, c];"
    )
    first, repeat, fresh = got
    assert (len(first["toasts"]), len(first["trail"])) == (1, 1), first
    assert (repeat["toasts"], repeat["trail"]) == ([], []), repeat
    assert fresh["toasts"] == ["Run cancelled."], fresh
    assert [e["runId"] for e in fresh["trail"]] == [OTHER], fresh


# --- renderComposerTotal ---------------------------------------------------------

FOUR = ["a/one", "b/two", "c/three", "d/four"]
CONTEXT = {"prior_question": "Which database first?", "prior_synthesis": "Postgres."}
PRICED = {"queryText": "Q1", "modelIds": FOUR, "quick": False, "context": CONTEXT}

_TOTAL_PAGE = r"""
const totalEl = { textContent: "stale" };
composerTotalEstimate = totalEl;
el = (id) => (id === "composer-total-estimate"
  ? totalEl
  : { textContent: "", dataset: {}, hidden: false });
gateUsd = (v) => `USD(${v})`;
formatUsd = (v) => `USD(${v})`;
let currentIds = [];
getModelIds = () => currentIds.slice();
const out = [];
for (const c of __CASES__) {
  state.currentEstimate = c.priced ? { cost_estimate: { estimated_cost_usd: "0.100" } } : null;
  state.pricedRun = c.priced ? __PRICED__ : null;
  queryTextarea.value = c.text;
  currentIds = c.models;
  state.quickMode = c.quick;
  state.followUpContext = c.context;
  totalEl.textContent = "stale";
  renderComposerTotal();
  out.push(totalEl.textContent);
}
return out;
"""


def test_the_composer_total_is_derived_from_the_current_inputs() -> None:
    """RED IF ``renderComposerTotal()`` does not exist (``f10c754``: the total
    is written once by ``estimateRun`` and reset only by
    ``holdForHighStakesAck``), or shows the amount when any
    ONE part of the priced inputs differs: the question, the order or number
    of models, quick mode, either follow-up value, or the context dropped.

    Positive partners: the unchanged inputs, and the same question with
    surrounding spaces (it is priced trimmed), show the amount, so "always —"
    is red too; and with no estimate it is "—", not the stale text.
    """
    _require("renderComposerTotal")
    base = {"priced": True, "text": "Q1", "models": FOUR, "quick": False, "context": CONTEXT}
    cases = {
        "unchanged": base,
        "same text with spaces": {**base, "text": "  Q1  "},
        "question edited": {**base, "text": "Q1 and churn?"},
        "models reordered": {**base, "models": [FOUR[1], FOUR[0], *FOUR[2:]]},
        "a model removed": {**base, "models": FOUR[:3]},
        "quick switched on": {**base, "quick": True},
        "context question differs": {**base, "context": {**CONTEXT, "prior_question": "Other?"}},
        "context answer differs": {**base, "context": {**CONTEXT, "prior_synthesis": "MySQL."}},
        "context dropped": {**base, "context": None},
        "nothing priced": {**base, "priced": False},
    }
    body = _TOTAL_PAGE.replace("__CASES__", json.dumps(list(cases.values()))).replace(
        "__PRICED__", json.dumps(PRICED)
    )
    got = dict(zip(cases, _node(["renderComposerTotal"], body), strict=True))
    assert got == {
        "unchanged": "USD(0.100)",
        "same text with spaces": "USD(0.100)",
        "question edited": "—",
        "models reordered": "—",
        "a model removed": "—",
        "quick switched on": "—",
        "context question differs": "—",
        "context answer differs": "—",
        "context dropped": "—",
        "nothing priced": "—",
    }


# --- beginRunScope ----------------------------------------------------------------

_SCOPE_PAGE = r"""
const kebab = (k) => "data-" + String(k).replace(/[A-Z]/g, (m) => "-" + m.toLowerCase());
const node = (runId) => {
  const attrs = new Map([["data-run-scope", ""]]);
  if (runId) attrs.set("data-run-id", runId);
  const n = {
    attrs, hidden: false, textContent: "", children: [],
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    hasAttribute: (k) => attrs.has(k),
    setAttribute: (k, v) => { attrs.set(k, String(v)); },
    removeAttribute: (k) => { attrs.delete(k); },
    replaceChildren() {}, append() {}, appendChild() {}, querySelector: () => null,
    querySelectorAll: () => [],
  };
  n.dataset = new Proxy({}, {
    get: (t, k) => attrs.get(kebab(k)),
    set: (t, k, v) => { attrs.set(kebab(k), String(v)); return true; },
    deleteProperty: (t, k) => { attrs.delete(kebab(k)); return true; },
    has: (t, k) => attrs.has(kebab(k)),
  });
  return n;
};
const tagged = [node("OLD"), node("OLD"), node(null)];
document = {
  documentElement: node(null),
  querySelectorAll: (sel) => (String(sel).includes("data-run-scope") ? tagged : []),
  querySelector: () => null,
  getElementById: () => node(null),
};
qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
qs = () => null;
el = () => node(null);
const old = { id: 5, runId: "OLD", terminalHandled: true, closed: true };
state.runScope = old;
state.terminalHandled = true;
state.liveQueryText = "the earlier question";
state.lastLiveStatus = "Completed";
state.liveSig = { stage: "s", debate: "d", models: "m", fallback: "f", notices: "n" };
state.lastResult = { query_run_id: "OLD" };
state.lastResultSummary = "summary";
state.lastResultMarkdown = "markdown";
state.lastResultRunId = "OLD";
state.lastDemoMode = "all-local|0|4|0";
__CALL__;
const s = state.runScope;
return {
  tags: tagged.map((n) => n.getAttribute("data-run-id")),
  scope: {
    id: s && s.id, runId: s && s.runId,
    terminalHandled: s && s.terminalHandled, closed: s && s.closed,
  },
  replaced: s !== old,
  newer: !!s && typeof s.id === "number" && s.id > old.id,
  old,
  terminalHandled: state.terminalHandled,
  liveQueryText: state.liveQueryText ?? null,
  lastLiveStatus: state.lastLiveStatus ?? null,
  liveSig: state.liveSig,
  last: [
    state.lastResult, state.lastResultSummary, state.lastResultMarkdown,
    state.lastResultRunId, state.lastDemoMode,
  ].map((v) => v ?? null),
};
"""


def _begin(call: str) -> Any:
    _require("beginRunScope")
    return _node(["beginRunScope"], _SCOPE_PAGE.replace("__CALL__", call))


def test_begin_run_scope_untags_every_region_and_starts_a_fresh_scope() -> None:
    """RED IF ``beginRunScope`` does not exist (``f10c754``: each way into a
    run resets its own hand-picked fields, and ``goToActiveRun`` resets none,
    W49), or leaves a ``data-run-id`` on any ``[data-run-scope]`` region, or
    reuses or mutates the old scope instead of replacing it, or keeps any of
    the earlier run's state: ``terminalHandled``, the question, the live
    status, ``liveSig``, the ``lastResult*`` fields or ``lastDemoMode``.

    Positive partner: two of the three regions carry a tag before the call,
    so "no tags" is not true over nothing.
    """
    got = _begin('beginRunScope("NEW", "Q2")')
    assert got["tags"] == [None, None, None]
    assert got["scope"] == {
        "id": got["scope"]["id"],
        "runId": "NEW",
        "terminalHandled": False,
        "closed": False,
    }
    assert got["replaced"] is True and got["newer"] is True
    assert got["old"] == {"id": 5, "runId": "OLD", "terminalHandled": True, "closed": True}
    assert got["terminalHandled"] is False
    assert got["liveQueryText"] == "Q2"
    assert got["lastLiveStatus"] is None
    assert got["liveSig"] == {
        "stage": None,
        "debate": None,
        "models": None,
        "fallback": None,
        "notices": None,
    }
    assert got["last"] == [None, None, None, None, None]


def test_begin_run_scope_without_a_question_leaves_none() -> None:
    """RED IF an adopted run ("Go to run", the boot path), whose answer
    carries no question, keeps the earlier run's question (W49: the live view
    and the result then pair the PREVIOUS question with this run). The
    positive partner is the test above, where a passed question is kept."""
    got = _begin('beginRunScope("NEW")')
    assert got["liveQueryText"] in ("", None)
    assert got["scope"]["runId"] == "NEW"
