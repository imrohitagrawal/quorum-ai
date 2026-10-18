"""W100: the page sends a high-stakes acknowledgement only for a ticked box.

``safetyAcknowledgementsFor(warnings, highStakesTicked)`` in ``app.js`` turns
the final ``POST /v1/query-runs/warnings`` answer into the create's
``safety_acknowledgements`` list, or says the run must be held. The owner's
decisions (CHG-065): the sensitive-data acknowledgement stays automatic (a);
a warning type the page does not know is never acknowledged (c). The tick is
read once, after the final check answers (the plan, revised after the Codex
plan review), so this function takes it as an argument and reads no globals.

The function is sliced out of ``app.js`` by brace count and run alone under
Node, the same harness as ``tests/unit/test_quick_answer_ui.py``; it must
therefore stay self-contained. The browser half is
``e2e/tests/ui-parity/high-stakes-acknowledgement.spec.ts`` and
``e2e/tests/invariants/safety-acknowledgement.spec.ts``.

What turns each test red is stated on the test.
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
FUNCTION = "safetyAcknowledgementsFor"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# Distinct, non-default versions, so a function that writes a constant
# version instead of copying the final check's own is caught.
SD = {"warning_type": "sensitive_data", "version": "sd-v7"}
HS = {"warning_type": "high_stakes", "version": "hs-v3"}
UNKNOWN = {"warning_type": "future_kind", "version": "9"}


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


def _run(cases: list[list[Any]]) -> list[dict[str, Any]]:
    """Run the sliced function once per case; a throw is reported, not raised.

    ``undefined`` cannot travel through JSON, so the literal string
    ``"__undefined__"`` stands for it.
    """
    source = APP_JS.read_text(encoding="utf-8")
    script = (
        _extract_function(source, FUNCTION)
        + "\n\nconst cases = "
        + json.dumps(cases)
        + ";\n"
        + "const fix = (v) => (v === '__undefined__' ? undefined : v);\n"
        + "console.log(JSON.stringify(cases.map((args) => {\n"
        + "  try {\n"
        + f"    return {{ ok: true, value: {FUNCTION}(...args.map(fix)) }};\n"
        + "  } catch (e) {\n"
        + "    return { ok: false, error: String(e && e.message) };\n"
        + "  }\n"
        + "})));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=10, check=True
    )
    out = json.loads(result.stdout)
    assert isinstance(out, list) and len(out) == len(cases)
    return out


def _value(case: list[Any]) -> Any:
    (out,) = _run([case])
    assert out["ok"], f"{FUNCTION}{tuple(case)} threw: {out.get('error')}"
    return out["value"]


# --- the plan's six literal cases ------------------------------------------


def test_sensitive_data_alone_unticked_is_sent_automatically() -> None:
    """Red when: the sensitive-data acknowledgement is filtered out (every run
    would then be refused by the server, failure mode F1), or the function is
    missing from app.js."""
    assert _value([[SD], False]) == {"hold": False, "acknowledgements": [SD]}


def test_high_stakes_unticked_holds_and_sends_nothing() -> None:
    """Red when: an unticked high-stakes warning is acknowledged (today's
    ``warningAcknowledgements`` echoes every warning), or the run is not held,
    or a partial list (sensitive data only) is returned on a hold."""
    assert _value([[SD, HS], False]) == {"hold": True, "acknowledgements": []}


def test_high_stakes_ticked_sends_both() -> None:
    """Red when: a ticked high-stakes acknowledgement is dropped, or a ticked
    box still holds the run (the positive partner of the hold case)."""
    assert _value([[SD, HS], True]) == {"hold": False, "acknowledgements": [SD, HS]}


def test_a_tick_with_no_high_stakes_warning_sends_no_high_stakes_entry() -> None:
    """Red when: a tick left over from an earlier question adds a high-stakes
    acknowledgement the final check did not ask for (failure mode F5)."""
    assert _value([[SD], True]) == {"hold": False, "acknowledgements": [SD]}


@pytest.mark.parametrize("ticked", [False, True])
def test_no_warnings_sends_an_empty_list(ticked: bool) -> None:
    """Red when: an empty final check invents an acknowledgement, or holds."""
    assert _value([[], ticked]) == {"hold": False, "acknowledgements": []}


@pytest.mark.parametrize("ticked", [False, True])
def test_an_unknown_warning_type_is_never_acknowledged(ticked: bool) -> None:
    """Red when: a warning type the page does not know is echoed back as
    acknowledged (CHG-065 (c)), or it causes a hold."""
    assert _value([[SD, UNKNOWN], ticked]) == {"hold": False, "acknowledgements": [SD]}


# --- fail closed on a malformed final check --------------------------------


@pytest.mark.parametrize(
    "warnings",
    [None, "__undefined__", {}, {"warnings": [SD]}, "high_stakes", 3],
    ids=["null", "undefined", "empty-object", "wrapped-object", "string", "number"],
)
def test_a_non_array_warnings_value_throws(warnings: Any) -> None:
    """Red when: a malformed final check (``{}`` or a missing list) is treated
    as "no warnings" and the run goes ahead (failure mode F10)."""
    for ticked in (False, True):
        (out,) = _run([[warnings, ticked]])
        assert out["ok"] is False, f"{warnings!r}, ticked={ticked} returned {out.get('value')!r}"


# --- the shape the server accepts ------------------------------------------


def test_each_entry_is_exactly_type_and_version_copied_from_the_input() -> None:
    """Red when: the version is a constant rather than the final check's own,
    or an extra key reaches the create (W85 refuses extra keys, F3)."""
    sd = {**SD, "title": "Sensitive data", "message": "Do not include ..."}
    hs = {**HS, "title": "Decision support only", "required": True}
    value = _value([[sd, hs], True])
    assert value == {"hold": False, "acknowledgements": [SD, HS]}
    for entry in value["acknowledgements"]:
        assert sorted(entry) == ["version", "warning_type"]


def test_only_a_boolean_true_tick_counts() -> None:
    """Red when: a truthy non-boolean (the string "true", 1) is taken as a
    tick; the agreed interface acknowledges only ``highStakesTicked === true``."""
    outs = _run([[[SD, HS], "true"], [[SD, HS], 1], [[SD, HS], "__undefined__"]])
    assert [o["ok"] for o in outs] == [True, True, True]
    assert [o["value"] for o in outs] == [{"hold": True, "acknowledgements": []}] * 3


def test_the_input_list_is_not_changed() -> None:
    """Red when: the function edits the final check's answer in place (for
    example splicing out the high-stakes entry), which other code still reads."""
    source = APP_JS.read_text(encoding="utf-8")
    script = (
        _extract_function(source, FUNCTION)
        + "\nconst input = "
        + json.dumps([SD, HS, UNKNOWN])
        + ";\nconst before = JSON.stringify(input);\n"
        + f"{FUNCTION}(input, false);\n{FUNCTION}(input, true);\n"
        + "console.log(JSON.stringify(JSON.stringify(input) === before));\n"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=10, check=True
    )
    assert json.loads(result.stdout) is True
