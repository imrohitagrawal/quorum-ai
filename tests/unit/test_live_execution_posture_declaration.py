"""#357, pre-merge half: ``fly.toml`` may not commit a money posture nobody declared.

TWO LAYERS, ASKING DIFFERENT QUESTIONS
    ``.github/workflows/live-posture-watchdog.yml`` asks what production is
    DOING, every 30 minutes, by reading ``/ready``. It is the only half a Fly
    secret cannot bypass — ``DEPLOY.md:61,175,230`` instructs operators to set
    this very flag with ``fly secrets set``, which touches no tracked file.

    This file asks what ``main`` is about to ASK production to do. It runs in the
    blocking ``pytest (Python 3.12)`` lane, so it fires before the merge. It is
    the only half that can see a flag flipped in ``main`` but not yet deployed —
    the exact shape of #351, which stranded ADR-0060's merge and is why a
    one-session window ran for three days. The watchdog is correctly silent
    through that gap, because production is not spending yet.

    Neither is sufficient alone. They are blind in opposite directions.

VACUITY
    ``fly.toml`` reads ``"false"`` today, so the real-file test below passes
    trivially. Every branch of the decision is therefore ALSO driven by
    fixtures, including the ``"true"`` cases that the real file cannot reach.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "live_posture_check.py"
FLY_TOML = REPO_ROOT / "fly.toml"
FLAG = "OPENROUTER_LIVE_EXECUTION_ENABLED"

_NOW = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)
_NOW_OPEN = "2026-08-25T09:00:00+00:00"
_NOW_SHUT = "2026-08-25T17:00:00+00:00"
_OLD_OPEN = "2026-08-19T09:00:00+00:00"
_OLD_SHUT = "2026-08-19T17:00:00+00:00"
_FUTURE_OPEN = "2026-09-01T09:00:00+00:00"
_FUTURE_SHUT = "2026-09-01T17:00:00+00:00"


@pytest.fixture(scope="module")
def posture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("live_posture_declaration_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fly_env() -> dict[str, Any]:
    env = tomllib.loads(FLY_TOML.read_text(encoding="utf-8")).get("env", {})
    assert isinstance(env, dict)
    # Empty-input floor: this gate reads a structure, and an empty structure
    # would make every assertion below trivially true.
    assert env, "fly.toml has no [env] block — this gate refuses to pass over nothing"
    return env


def _window(posture: ModuleType, *, opened: str, expires: str) -> Any:
    return posture.DeclaredWindow(
        owner="rohit",
        reason="collect the ADR-0060 sample",
        opened_at=dt.datetime.fromisoformat(opened),
        expires_at=dt.datetime.fromisoformat(expires),
    )


# --- The real repository ---------------------------------------------------


def test_fly_toml_still_declares_the_flag_this_gate_watches() -> None:
    """POSITIVE PARTNER for the gate below, and its empty-input floor.

    Without it, renaming or deleting the key would leave the gate passing over
    a value it no longer finds — a check measuring nothing.

    RED IF: the flag is removed from ``fly.toml``'s ``[env]``, or renamed.
    """
    assert FLAG in _fly_env(), (
        f"{FLAG} is no longer in fly.toml [env]. If the deployment moved it "
        "elsewhere, this gate is watching nothing — repoint it, do not delete it."
    )


def test_the_committed_flag_is_off_or_covered_by_a_declared_window(
    posture: ModuleType,
) -> None:
    """The gate itself, against the tree as it stands.

    RED IF: ``fly.toml`` sets the flag to ``"true"`` in a pull request that does
    not also declare a window covering the merge in
    ``configs/live-execution-windows.json``.
    """
    refusal = posture.refuse_undeclared_flag(
        flag_value=str(_fly_env().get(FLAG)),
        windows=posture.load_windows(posture.DEFAULT_WINDOWS_PATH),
        now=dt.datetime.now(dt.UTC),
    )
    assert refusal is None, refusal


# --- The decision, driven by fixtures the real file cannot reach ------------


def test_an_undeclared_true_is_refused(posture: ModuleType) -> None:
    """THE case this gate exists for, and the one ``fly.toml`` cannot exercise.

    RED IF: the refusal branch is removed, so a pull request may commit a
    money-spending posture with nothing recording that it was intended.
    """
    refusal = posture.refuse_undeclared_flag(flag_value="true", windows=[], now=_NOW)
    assert refusal is not None
    assert FLAG in refusal


def test_a_false_flag_is_allowed(posture: ModuleType) -> None:
    """POSITIVE PARTNER: a gate that refuses everything would satisfy the test
    above while making the repository unmergeable.

    RED IF: the off-value branch is removed.
    """
    assert posture.refuse_undeclared_flag(flag_value="false", windows=[], now=_NOW) is None


@pytest.mark.parametrize("value", ["false", "FALSE", " False ", "0", "no", "off", "", None])
def test_every_off_spelling_is_allowed(posture: ModuleType, value: str | None) -> None:
    """RED IF: the off-value set narrows, so an ordinary ``"FALSE"`` starts
    failing the merge gate — a gate that fires on legitimate work is a gate
    somebody switches off."""
    assert posture.refuse_undeclared_flag(flag_value=value, windows=[], now=_NOW) is None


@pytest.mark.parametrize("value", ["true", "TRUE", " True ", "1", "yes", "on", "trve"])
def test_every_on_spelling_and_any_typo_is_refused_without_a_window(
    posture: ModuleType, value: str
) -> None:
    """Fail closed on a value this gate does not recognise.

    ``"trve"`` is the load-bearing row: an unrecognised value must not read as
    "off". Pydantic would refuse it at startup, but a GATE that treats it as off
    is the silently-green shape, and it would also pass a value some future
    settings parser accepts as true.

    RED IF: the unknown-value case falls through to the allow branch.
    """
    assert posture.refuse_undeclared_flag(flag_value=value, windows=[], now=_NOW) is not None


def test_a_true_inside_a_declared_window_is_allowed(posture: ModuleType) -> None:
    """The escape valve that keeps this gate from blocking legitimate work.

    RED IF: the window lookup is removed, so a sanctioned window can never be
    merged and the gate has to be disabled to do the work it permits.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    assert posture.refuse_undeclared_flag(flag_value="true", windows=[window], now=_NOW) is None


def test_a_true_past_a_declared_window_is_refused(posture: ModuleType) -> None:
    """#357 in one line: the declaration expired and the flag did not follow.

    RED IF: ``covers`` stops bounding the window at ``expires_at``, so one
    declaration sanctions the flag forever.
    """
    window = _window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)
    refusal = posture.refuse_undeclared_flag(flag_value="true", windows=[window], now=_NOW)
    assert refusal is not None


def test_an_unreadable_declaration_is_refused_even_with_the_flag_off(
    posture: ModuleType,
) -> None:
    """A broken declaration file is refused on its own account.

    If it were tolerated while the flag is off, the file could rot unnoticed and
    then be silently unable to sanction the window somebody needs — or, worse,
    the runtime watchdog's UNKNOWN would be the first anyone heard of it.

    RED IF: the ``windows is None`` branch is removed, or moved below the
    off-value branch.
    """
    refusal = posture.refuse_undeclared_flag(flag_value="false", windows=None, now=_NOW)
    assert refusal is not None
    assert "live-execution-windows.json" in refusal
