"""#176 surface 2: the transcript view's ``#demo-mode-banner`` (moved out of
the permanently-hidden legacy "Model outputs" panel-section by #115).

``renderModelPanels`` in ``app.js`` used to build the "mixed" banner copy
inline, unconditionally. Two claims in it were false in reachable classes:

* "The synthesis below is also produced by a configured synthesis model" —
  false whenever ``result.result.final_synthesis`` is null, which happens
  both transiently (mid-run, before the synthesis stage) and permanently (a
  run cancelled or deadline-exceeded before reaching synthesis).
* "Ask the operator to enable live execution ..." — false whenever live
  execution is already enabled (a refused key still counts as present since
  #171, so the flag never flips off; ``readinessState`` is ``"live"`` or
  ``"offline_by_bad_key"``).

The fix extracted the decision into a pure function,
``computeDemoModeBannerCopy`` (plus its ``demoModeActionClause`` helper and
the pre-existing ``describePanelShortfall``, reused for the dynamic title),
DOM-free by construction — like ``describePanelShortfall`` already was for
the sibling ``#result-degraded`` banner. This file drives that pure function
for real, under Node, over every reachable input class enumerated before the
fix (see ISSUE-176-CLOSEOUT-RESULT.md), and pins the EXACT served string —
not a substring, and not the internal ``bannerState`` — for each one.

These tests are NOT marked ``repo_introspection``: ``app.js`` lives under
``src``, which mutmut's ``source_paths = ["src"]`` already copies into
``./mutants/`` (the same precedent ``test_mdinline_bullets.py`` relies on).
They DO skip when ``node`` is absent, exactly like
``test_negative_assertion_guard.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _extract_function(source: str, name: str) -> str:
    """Slice ``function name(...) { ... }`` out of ``source`` by brace count.

    Robust to line drift (unlike a fixed line-range slice): finds the
    function's own opening brace, then counts braces verbatim through the
    matching close. Safe here because every brace inside these functions is
    balanced (template-literal ``${...}`` expressions net to zero); there is
    no stray brace inside a string or comment.
    """
    marker = f"function {name}("
    start = source.index(marker)
    # Match the PARAMETER-LIST parens first (some of these functions destructure
    # a ``{ ... }`` object as their single argument, whose brace is not the
    # function BODY's opening brace) — then find the body's ``{`` after them.
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


@pytest.fixture(scope="module")
def harness() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    parts = [
        _extract_function(source, "describePanelShortfall"),
        _extract_function(source, "demoModeActionClause"),
        _extract_function(source, "computeDemoModeBannerCopy"),
    ]
    return "\n\n".join(parts)


def _run(harness: str, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    script = (
        harness
        + "\n\nconst cases = "
        + json.dumps(cases)
        + ";\nconsole.log(JSON.stringify(cases.map(computeDemoModeBannerCopy)));\n"
    )
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"node harness failed:\n{result.stderr}"
    output: list[dict[str, Any]] = json.loads(result.stdout)
    return output


# ---------------------------------------------------------------------------
# Input-class enumeration (measured BEFORE the fix, per the handoff's rule 3
# discipline — see ISSUE-176-CLOSEOUT-RESULT.md for the full before/after
# table). Every case below is a class actually reachable in production,
# except where the docstring says otherwise.
# ---------------------------------------------------------------------------

_ALL_LIVE = {
    "liveCount": 4,
    "localCount": 0,
    "failedCount": 0,
    "total": 4,
    "readinessState": "live",
    "hasFinalSynthesis": True,
}

_PARTIAL_LIVE_SOME_FAILED = {
    "liveCount": 2,
    "localCount": 0,
    "failedCount": 2,
    "total": 4,
    "readinessState": "live",
    "hasFinalSynthesis": True,
}

_ALL_FAILED_LIVE_ON_SYNTHESIS_DONE = {
    "liveCount": 0,
    "localCount": 0,
    "failedCount": 4,
    "total": 4,
    "readinessState": "offline_by_bad_key",
    "hasFinalSynthesis": True,
}

_ALL_FAILED_LIVE_ON_SYNTHESIS_NOT_REACHED = {
    "liveCount": 0,
    "localCount": 0,
    "failedCount": 4,
    "total": 4,
    "readinessState": "offline_by_bad_key",
    "hasFinalSynthesis": False,
}

_ALL_FAILED_LIVE_OFF_CANCELLED = {
    "liveCount": 0,
    "localCount": 0,
    "failedCount": 4,
    "total": 4,
    "readinessState": "offline_by_config",
    "hasFinalSynthesis": False,
}

_ALL_LOCAL_CONFIG_OFF = {
    "liveCount": 0,
    "localCount": 4,
    "failedCount": 0,
    "total": 4,
    "readinessState": "offline_by_config",
    "hasFinalSynthesis": True,
}

_ALL_LOCAL_NO_KEY = {
    "liveCount": 0,
    "localCount": 4,
    "failedCount": 0,
    "total": 4,
    "readinessState": "offline_by_no_key",
    "hasFinalSynthesis": True,
}


def test_the_synthesis_clause_never_appears_when_final_synthesis_is_null(harness: str) -> None:
    """Positive AND negative partner in one call, over the mixed state."""
    [done, not_reached] = _run(
        harness,
        [_ALL_FAILED_LIVE_ON_SYNTHESIS_DONE, _ALL_FAILED_LIVE_ON_SYNTHESIS_NOT_REACHED],
    )
    assert done["bannerState"] == "mixed"
    assert "The synthesis below" in done["message"], done
    assert not_reached["bannerState"] == "mixed"
    assert "The synthesis below" not in not_reached["message"], not_reached
    assert "synthesis" not in not_reached["message"].lower(), not_reached


def test_the_action_clause_never_asks_to_enable_what_is_already_enabled(harness: str) -> None:
    """Positive AND negative partner: readinessState is the only thing that changes."""
    [already_on, genuinely_off] = _run(
        harness,
        [_ALL_FAILED_LIVE_ON_SYNTHESIS_DONE, _ALL_FAILED_LIVE_OFF_CANCELLED],
    )
    # readinessState "offline_by_bad_key" (a refused-but-present key) gets the
    # specific instruction, matching the all-local branch's own conditioning.
    assert "enable live execution" not in already_on["message"], already_on
    assert already_on["message"].endswith(
        "Ask the operator to replace the provider key and restart."
    ), already_on
    assert "enable live execution" in genuinely_off["message"], genuinely_off


def test_partial_live_with_some_failed_does_not_ask_to_enable(harness: str) -> None:
    """The common real class: 2 live, 2 failed, readinessState 'live'."""
    [result] = _run(harness, [_PARTIAL_LIVE_SOME_FAILED])
    assert result["bannerState"] == "mixed"
    assert "enable live execution" not in result["message"], result
    assert "2 returned nothing" in result["message"], result
    assert "The synthesis below" in result["message"], result
    # readinessState "live": the startup probe's key passed, so the missing
    # slots are NOT attributed to "enable live execution" (already on) — but
    # nor is a specific provider cause asserted, since a "live" readiness
    # state says nothing about whether THIS run's gap is a provider issue, a
    # cancel, or the run deadline (round 1 review finding).
    assert result["message"].endswith(
        "Ask the operator to check whether this reflects a provider or account "
        "issue, a cancelled run, or the run's time limit."
    ), result


def test_all_live_is_hidden_with_no_copy(harness: str) -> None:
    [result] = _run(harness, [_ALL_LIVE])
    assert result == {"bannerState": "all-live", "title": "", "message": ""}


def test_all_local_states_are_unchanged_by_the_fix(harness: str) -> None:
    """Negative control: the all-local branch was never part of #176's defect
    and must not move. Pinned exactly, both cause and action clauses.

    Issue #100 §2.7: the vendor list ("GPT, Claude, Gemini, or Deepseek") is
    factually wrong in production (slot 4 has been nvidia/nemotron since
    WP-G1) and is replaced everywhere with "a real AI model provider" — the
    pin below reflects that fix, not a #176 regression.
    """
    [config_off, no_key] = _run(harness, [_ALL_LOCAL_CONFIG_OFF, _ALL_LOCAL_NO_KEY])

    assert config_off["bannerState"] == "all-local"
    assert config_off["title"] == "Demo mode is active"
    assert config_off["message"] == (
        "Live execution is turned off, so all four model answers and the synthesis "
        "below come from Quorum's local simulation helpers. They look like real "
        "output but are not generated by a real AI model provider. Ask the "
        "operator to enable live execution to run against real models."
    )

    assert no_key["bannerState"] == "all-local"
    assert no_key["message"] == (
        "No model provider key is configured, so all four model answers and the "
        "synthesis below come from Quorum's local simulation helpers. They look "
        "like real output but are not generated by a real AI model provider. "
        "Ask the operator to add the provider key and restart."
    )


def test_no_case_ever_mentions_deepseek_or_any_specific_vendor(harness: str) -> None:
    """Issue #100 §2.7 as a standing regression guard, not just a point fix:
    the vendor list goes stale the moment a slot's model changes (it already
    had — slot 4 has been nvidia/nemotron since WP-G1, not Deepseek). No
    served banner may name a specific vendor again."""
    cases = [
        _ALL_LOCAL_CONFIG_OFF,
        _ALL_LOCAL_NO_KEY,
        _PARTIAL_LIVE_SOME_FAILED,
        _ALL_FAILED_LIVE_ON_SYNTHESIS_DONE,
        _ALL_FAILED_LIVE_OFF_CANCELLED,
    ]
    for result in _run(harness, cases):
        for vendor in ("GPT", "Claude", "Gemini", "Deepseek", "nvidia", "nemotron"):
            assert vendor not in result["message"], (vendor, result)


class TestGlobalSpendCeilingBanner:
    """Issue #100 §2.6 — FINAL, operator-approved, exact copy, locked
    2026-08-01. Pinned as an exact string, not a substring: this build ships
    operator-approved copy that must be tested as exact copy."""

    _POST_RUN_TITLE = "Demo mode is active — today's shared budget is used up"
    _POST_RUN_MESSAGE = (
        "This application limits total live AI usage across all visitors combined "
        "to one shared daily budget, which has already been used today. That's "
        "why every model answer and the synthesis below come from Quorum's local "
        "simulation helpers instead of a real AI model provider. This resets "
        "automatically within 24 hours — check back later to see live results."
    )

    def test_ceiling_reached_overrides_the_ordinary_all_local_copy(self, harness: str) -> None:
        case = dict(_ALL_LOCAL_NO_KEY, globalSpendCeilingReached=True)
        [result] = _run(harness, [case])
        assert result["bannerState"] == "all-local"
        assert result["title"] == self._POST_RUN_TITLE
        assert result["message"] == self._POST_RUN_MESSAGE

    def test_ceiling_copy_is_the_same_regardless_of_readiness_state(self, harness: str) -> None:
        """The ceiling is orthogonal to WHY live execution might otherwise be
        off — a deployment that is fully configured (readinessState "live")
        can still trip the ceiling. Same exact copy either way."""
        case = dict(_ALL_LOCAL_CONFIG_OFF, readinessState="live", globalSpendCeilingReached=True)
        [result] = _run(harness, [case])
        assert result["title"] == self._POST_RUN_TITLE
        assert result["message"] == self._POST_RUN_MESSAGE

    def test_ceiling_flag_false_leaves_the_ordinary_copy_untouched(self, harness: str) -> None:
        case = dict(_ALL_LOCAL_NO_KEY, globalSpendCeilingReached=False)
        [result] = _run(harness, [case])
        assert result["title"] == "Demo mode is active"
        assert result["title"] != self._POST_RUN_TITLE

    def test_ceiling_flag_absent_is_treated_as_false(self, harness: str) -> None:
        """Every OLDER caller (before this field existed) must keep behaving
        exactly as before — no crash, no accidental ceiling banner."""
        [result] = _run(harness, [_ALL_LOCAL_NO_KEY])
        assert result["title"] == "Demo mode is active"


def test_mixed_title_is_never_the_fixed_demo_mode_markup(harness: str) -> None:
    """#176: 'the title stops being fixed markup that says Demo mode for a
    non-demo state.' Every 'mixed' case must get a title distinct from the
    all-local one."""
    cases = [
        _PARTIAL_LIVE_SOME_FAILED,
        _ALL_FAILED_LIVE_ON_SYNTHESIS_DONE,
        _ALL_FAILED_LIVE_OFF_CANCELLED,
    ]
    results = _run(harness, cases)
    for case, result in zip(cases, results, strict=True):
        assert result["bannerState"] == "mixed", (case, result)
        assert result["title"] != "Demo mode is active", (case, result)
        assert result["title"], (case, result)

    # And distinguish "no model answered" from "some answered, some missing":
    all_failed_titles = {results[1]["title"], results[2]["title"]}
    assert all_failed_titles == {"No result — no model answered"}
    assert results[0]["title"] == "Incomplete result — not every model answered"
