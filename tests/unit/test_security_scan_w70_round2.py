"""W70, review round 2: the rules round 1 widened, narrowed again.

What is pinned here: every line check finishes quickly on a 1 MB adversarial
line (round 1's named-secret rule took time growing with the SQUARE of the
line's length). The W70 split of 2026-10-16 moved that rule to board row W83
and removed its tests from this file (its one character set, the leading
``#``, type annotations and the value window); the adversarial lines written
for it stay, as inputs to the four checks that remain.

The trailing-slash and path-start rule for home folders is pinned in
``tests/unit/test_security_scan_w70_round1.py``, next to the round-1 test it
replaced.

HOW THIS FILE STAYS CLEAN UNDER THE SCAN IT TESTS: every planted value is built
at run time from pieces held in lists.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCANNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "security_scan.py"


def _load_scanner() -> Any:
    spec = importlib.util.spec_from_file_location("security_scan_w70_round2", _SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scanner: Any = _load_scanner()

_HEX32 = "".join(["a1b2c3d4", "e5f6a7b8", "c9d0e1f2", "a3b4c5d6"])
_GENERIC = "".join(["Qm7t", "R2vX", "9kL4", "pW8n", "Z3sB"])
_TOKEN = "".join(["X", "_TOKEN"])
_USERS = "/".join(["", "Users", ""])


def _q(text: str) -> str:
    return "".join(['"', text, '"'])


# --------------------------------------------------------------------------
# Item 1: time on long adversarial lines
# --------------------------------------------------------------------------

_MB = 1_000_000


def _fill(unit: str, tail: str = "") -> str:
    return unit * (_MB // len(unit)) + tail


#: Each one drove a check into time growing with the square of its length,
#: or is a near relative of one that did (measured 2026-10-14 before the fix:
#: 2.97 s at 32 KB for the annotation line, 1.85 s at 32 KB for the gap line,
#: 8.96 s at 200 KB for the repeated name).
_ADVERSARIAL = {
    "repeated-name": _fill(_TOKEN + "="),
    "annotation-then-spaces": _TOKEN + ": str" + " " * _MB + "!",
    "unclosed-quotes": _fill("\"'x"),
    "fragments-then-spaces": _fill(_q("a") + " " * 1000 + "!"),
    "one-long-gap": _q("a") + " " * _MB + "!" + _q("b"),
    "repeated-home-root": _fill(_USERS),
}

#: One planted positive per check, so each timed function is shown to work.
_POSITIVES = {
    "openrouter": "ref = " + _q("".join(["sk-", "or-", "v1-"]) + _HEX32 * 2),
    "shape": "value: " + "".join(["GOC", "SPX-"]) + _GENERIC + _GENERIC[:8],
    "home": "cd " + _USERS + "alice/x",
    "env": "token = " + _q(_GENERIC),
}

#: The child process: times every line check on every adversarial line and
#: runs it on its positive. A child, so a regression fails at the subprocess
#: timeout instead of hanging the suite for minutes (pytest-timeout is not
#: installed here).
_CHILD = """
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("scan_child", sys.argv[1])
s = importlib.util.module_from_spec(spec)
sys.modules["scan_child"] = s
spec.loader.exec_module(s)
checks = {
    "openrouter": s._contains_raw_openrouter_key,
    "shape": s._contains_known_secret_shape,
    "home": s._contains_home_directory_path,
    "env": s._contains_env_secret_assignment,
}
data = json.load(open(sys.argv[2], encoding="utf-8"))
times = {}
for label, line in data["adversarial"].items():
    for name, check in checks.items():
        start = time.perf_counter()
        check(line)
        times[label + "/" + name] = time.perf_counter() - start
hits = {name: bool(checks[name](line)) for name, line in data["positives"].items()}
print(json.dumps({"times": times, "hits": hits}))
"""


def test_every_line_check_finishes_quickly_on_a_1mb_adversarial_line(tmp_path: Path) -> None:
    """Each of the 4 line checks on each of the 6 lines takes under 2 seconds.

    Measured after the fix, 2026-10-14: the slowest pair took 0.28 s on this
    Mac. 2 s leaves room for a slower CI runner. The partner: in the same
    child process, every check names its planted positive, so a check made
    fast by doing nothing is caught.

    Red when: the fragment-gap pattern (``_FRAGMENT_GAP``) or the home-folder
    pattern again has two neighbouring parts that can both take the same
    character (any time over 2 s, or the child killed at 120 s), OR a check
    stops naming its positive.
    """
    data = tmp_path / "lines.json"
    data.write_text(json.dumps({"adversarial": _ADVERSARIAL, "positives": _POSITIVES}))
    child = tmp_path / "child.py"
    child.write_text(_CHILD)
    try:
        run = subprocess.run(
            [sys.executable, str(child), str(_SCANNER_PATH), str(data)],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the line checks did not finish within 120 s on the 1 MB lines")
    result = json.loads(run.stdout)

    assert len(result["times"]) == len(_ADVERSARIAL) * 4, result["times"]
    slow = {pair: round(seconds, 2) for pair, seconds in result["times"].items() if seconds >= 2}
    assert not slow, f"line checks over 2 s: {slow}"
    assert result["hits"] == dict.fromkeys(_POSITIVES, True), result["hits"]
