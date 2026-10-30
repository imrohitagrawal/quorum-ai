"""W127, review round 1: what the first round of review found in the run scope.

The functions are lifted out of the served ``app.js`` and run under Node by
the same harness as ``tests/unit/test_w127_run_scope_functions.py`` (a name
the harness does not provide is a no-op function, so every helper a test
relies on is in its function list).

Every test names what turns it red.
"""

from __future__ import annotations

import json
from typing import Any

from tests.unit.test_late_run_question_rules import _node
from tests.unit.test_w127_run_scope_functions import _TOTAL_PAGE, FOUR

# --- the composer total in quick mode ---------------------------------------------

_QUICK_PRICED = {"queryText": "Q1", "modelIds": FOUR, "quick": True, "context": None}
_PANEL_PRICED = {**_QUICK_PRICED, "quick": False}


def _totals(priced: dict[str, Any], cases: dict[str, dict[str, Any]]) -> dict[str, str]:
    body = _TOTAL_PAGE.replace("__CASES__", json.dumps(list(cases.values()))).replace(
        "__PRICED__", json.dumps(priced)
    )
    return dict(zip(cases, _node(["renderComposerTotal"], body), strict=True))


def test_a_quick_total_ignores_the_slots_a_quick_run_does_not_send() -> None:
    """Red when ``renderComposerTotal`` compares every model slot in quick mode,
    although a quick request sends slot 1 alone (``runRequestBody``): changing
    slot 2, which the priced request never contained, turned the amount into
    "—" for a request that would be byte-identical.

    Both directions: a change to slot 1, which a quick request DOES send, still
    reads "—", and so does the same panel with quick mode off."""
    base = {"priced": True, "text": "Q1", "models": FOUR, "quick": True, "context": None}
    got = _totals(
        _QUICK_PRICED,
        {
            "unchanged": base,
            "slot 2 changed": {**base, "models": [FOUR[0], "x/other", *FOUR[2:]]},
            "slot 4 removed": {**base, "models": FOUR[:3]},
            "slot 1 changed": {**base, "models": ["x/other", *FOUR[1:]]},
            "quick switched off": {**base, "quick": False},
        },
    )
    assert got == {
        "unchanged": "USD(0.100)",
        "slot 2 changed": "USD(0.100)",
        "slot 4 removed": "USD(0.100)",
        "slot 1 changed": "—",
        "quick switched off": "—",
    }


def test_a_panel_total_still_compares_every_slot() -> None:
    """Red when the quick-mode narrowing above leaks into panel mode: a panel
    request sends all four slots, so a change to slot 2 must read "—". The
    positive partner is the unchanged panel."""
    base = {"priced": True, "text": "Q1", "models": FOUR, "quick": False, "context": None}
    got = _totals(
        _PANEL_PRICED,
        {
            "unchanged": base,
            "slot 2 changed": {**base, "models": [FOUR[0], "x/other", *FOUR[2:]]},
            "quick switched on": {**base, "quick": True},
        },
    )
    assert got == {"unchanged": "USD(0.100)", "slot 2 changed": "—", "quick switched on": "—"}


# --- beginRunScope: the live view's header and regions ----------------------------

_HEADER_PAGE = r"""
const kebab = (k) => "data-" + String(k).replace(/[A-Z]/g, (m) => "-" + m.toLowerCase());
const emptied = [];
const node = (id) => {
  const attrs = new Map();
  const n = {
    id, hidden: false, disabled: false, textContent: "",
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    removeAttribute: (k) => { attrs.delete(k); },
    replaceChildren() { emptied.push(id); },
  };
  n.dataset = new Proxy({}, {
    get: (t, k) => attrs.get(kebab(k)),
    set: (t, k, v) => { attrs.set(kebab(k), String(v)); return true; },
    deleteProperty: (t, k) => { attrs.delete(kebab(k)); return true; },
  });
  return n;
};
const nodes = {};
el = (id) => (nodes[id] = nodes[id] || node(id));
qsa = () => [];
// The previous run, as it was left on screen.
el("live-status-pill").dataset.state = "completed";
el("live-elapsed").textContent = "41.2s elapsed";
el("live-status-text").textContent = "Completed";
el("live-query").textContent = "the earlier question";
el("live-query").dataset.runId = "OLD";
state.runScope = { id: 5, runId: "OLD", terminalHandled: true, closed: false };
state.restoreToken = 3;
__CALL__;
return {
  pill: el("live-status-pill").dataset.state ?? null,
  elapsed: el("live-elapsed").textContent,
  status: el("live-status-text").textContent,
  query: el("live-query").textContent,
  queryRun: el("live-query").dataset.runId ?? null,
  emptied: [...new Set(emptied)].sort(),
  restoreToken: state.restoreToken,
};
"""


def _header(call: str) -> Any:
    return _node(
        ["beginRunScope", "tagRunRegion", "formatElapsed"],
        _HEADER_PAGE.replace("__CALL__", call),
    )


def test_a_new_scope_shows_a_starting_header_for_its_own_run() -> None:
    """Red when ``beginRunScope`` leaves the previous run's elapsed time, its
    finished pill state or its question on the live view, or writes the
    question line without tagging it with the new run: "Go to run" showed
    "41.2s elapsed" and a "completed" pill under the adopted run until that
    run's first poll answered.

    Positive partner: the page starts with the previous run's header, so a
    reset over nothing cannot pass."""
    adopted = _header('beginRunScope("NEW")')
    assert adopted == {
        "pill": "running",
        "elapsed": "0.0s elapsed",
        "status": "Starting…",
        "query": "—",
        "queryRun": "NEW",
        "emptied": adopted["emptied"],
        "restoreToken": adopted["restoreToken"],
    }
    asked = _header('beginRunScope("NEW", "Q2")')
    assert (asked["query"], asked["queryRun"]) == ("Q2", "NEW")


def test_a_new_scope_empties_every_live_region() -> None:
    """Red when ``beginRunScope`` stops emptying any of the live view's run
    regions (the stage strip, the round cards, the model statuses, the spend
    cap, the notices list or the fallback). "Go to run" then showed the
    finished run's rounds and statuses under the adopted run until its first
    poll answered (the new-run path redraws at once, so only an adopted run
    shows it). Cardinality: each of the six, by name."""
    got = _header('beginRunScope("NEW")')
    assert got["emptied"] == sorted(
        [
            "live-stage-strip",
            "live-debate",
            "live-model-status",
            "live-cap",
            "live-notices-list",
            "live-fallback",
        ]
    )


def test_a_new_scope_abandons_a_session_list_restore_still_waiting() -> None:
    """Red when ``beginRunScope`` does not move ``state.restoreToken`` on: a
    session-list answer that arrives after a new run has started would then
    be drawn over it, replacing its scope. Exactly one step, from the 3 the
    page starts with."""
    assert _header('beginRunScope("NEW")')["restoreToken"] == 4
