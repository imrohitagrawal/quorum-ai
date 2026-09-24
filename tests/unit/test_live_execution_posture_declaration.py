"""#357, pre-merge half: ``fly.toml`` may not commit a money posture nobody declared.

TWO LAYERS, ASKING DIFFERENT QUESTIONS
    ``.github/workflows/live-posture-watchdog.yml`` asks what production is
    DOING, on a schedule declared every 30 minutes (in practice hours apart;
    #459, see the workflow's header note), by reading ``/ready``. It is the only half a Fly
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
        mode=posture.MODE_TIME_BOXED,
        judge=False,
    )


def _standing(posture: ModuleType, *, opened: str) -> Any:
    return posture.DeclaredWindow(
        owner="rohit",
        reason="the GA steady state",
        opened_at=dt.datetime.fromisoformat(opened),
        expires_at=None,
        mode=posture.MODE_STANDING,
        judge=True,
        adr="ADR-0099",
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


# --- ADR-0071: what `standing` does to this layer, stated rather than found --


def test_a_standing_window_makes_this_gate_quiet_and_that_is_the_trade(
    posture: ModuleType,
) -> None:
    """The consequence of `mode: standing`, pinned so it is a DECISION and not a
    discovery.

    ADR-0070 made the expiry a deadline: once a declared window expired with the
    flag still committed ``"true"``, the required ``pytest (Python 3.12)``
    context went red on main and on every open pull request until somebody
    acted. That was "the mechanical form of ADR-0060's revert condition".

    A ``standing`` window has no expiry, so that pressure is gone — deliberately.
    At GA there is nothing to revert TO; the steady state is the destination.
    The pressure moves to the runtime attention check, which is the only layer
    that can see whether anybody is still watching, and which alerts within the
    hour once a re-affirmation lapses.

    This test exists so that trade is visible in the suite. It is not a claim
    that the trade is free.

    RED IF: someone re-adds a deadline to `standing` here without recording the
    decision, or `standing` stops sanctioning a committed flag at all — which
    would make GA unmergeable and get the mode deleted.
    """
    window = _standing(posture, opened=_OLD_OPEN)
    assert posture.refuse_undeclared_flag(flag_value="true", windows=[window], now=_NOW) is None


def test_this_gate_still_refuses_a_true_with_only_an_expired_time_boxed_window(
    posture: ModuleType,
) -> None:
    """POSITIVE PARTNER for the row above: the deadline is removed for
    ``standing`` ONLY. A time-boxed window that has expired must still refuse,
    or ADR-0070's whole pre-merge layer would have been deleted by the addition
    of a second mode.

    RED IF: the expiry stops binding time-boxed windows.
    """
    window = _window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)
    assert posture.refuse_undeclared_flag(flag_value="true", windows=[window], now=_NOW) is not None


def test_the_refusal_names_every_field_the_operator_must_now_write(
    posture: ModuleType,
) -> None:
    """The refusal is the only instruction most operators will read, and the
    declaration gained two required fields. A refusal naming the old shape sends
    somebody to write a window that will not parse.

    RED IF: a required field is added to the declaration without the refusal
    message following it.
    """
    refusal = posture.refuse_undeclared_flag(flag_value="true", windows=[], now=_NOW)
    assert refusal is not None
    for field in ("owner", "reason", "mode", "judge", "opened_at", "expires_at"):
        assert field in refusal, f"the refusal does not tell the operator about {field!r}"


def test_the_shipped_declaration_resolves_every_standing_citation(
    posture: ModuleType,
) -> None:
    """A `standing` window in the shipped file must cite an ADR that RESOLVES.

    ``load_windows`` returns None when it does not, so this asserts on the
    resolved load rather than on the raw text — a citation naming a missing,
    un-Accepted, unmarked or self-referential record makes the whole file
    untrusted, and that must never be the state ``main`` ships in.

    POSITIVE PARTNER, because "every standing window resolves" is trivially true
    over zero standing windows: the file must still parse, and the parse must
    still be a list.

    RED IF: a standing window is committed whose ADR citation does not resolve —
    which would take the watchdog to UNKNOWN on every cycle and get it muted.
    """
    parsed = posture.load_windows(posture.DEFAULT_WINDOWS_PATH)
    assert parsed is not None, (
        "the shipped declaration no longer loads — if a standing window was "
        "added, its ADR citation does not resolve"
    )
    assert isinstance(parsed, list)
    standing = [window for window in parsed if window.is_standing]
    for window in standing:
        assert window.adr is not None
        assert window.adr not in posture.MECHANISM_OWN_ADRS


# --- #458: the peer-critique flag may not outlive the live flag -------------

PEER_FLAG = "PEER_CRITIQUE_ENABLED"


def test_fly_toml_still_declares_the_peer_flag_this_gate_watches() -> None:
    """POSITIVE PARTNER for the coupling gate below, and its empty-input floor.

    RED IF: ``PEER_CRITIQUE_ENABLED`` is removed from ``fly.toml``'s ``[env]``
    or renamed — the gate below would then be comparing nothing to something.
    """
    assert PEER_FLAG in _fly_env(), (
        f"{PEER_FLAG} is no longer in fly.toml [env]. If the deployment moved it "
        "elsewhere, the coupling gate is watching nothing — repoint it, do not delete it."
    )


def test_the_committed_peer_flag_never_outlives_the_live_flag(posture: ModuleType) -> None:
    """The coupling, against the tree as it stands (#458, ADR-0122).

    Peer critique is a money multiplier that is only ever meant to be on
    INSIDE a live-execution window, and the window mechanism is its only
    writer. So a committed ``fly.toml`` may not carry ``PEER_CRITIQUE_ENABLED``
    on while ``OPENROUTER_LIVE_EXECUTION_ENABLED`` is off: that is a stranded
    flag, and re-opening a window would turn it back on unread, at up to
    eight critic calls per run instead of two.

    RED IF: ``fly.toml`` sets the peer flag to an on-spelling while the live
    flag reads off (the shape production shipped from 2026-09-12 to this
    change), or if ``refuse_peer_without_live`` is removed from the checker.
    """
    env = _fly_env()
    refusal = posture.refuse_peer_without_live(
        peer_value=_flag_text(env.get(PEER_FLAG)),
        live_value=_flag_text(env.get(FLAG)),
    )
    assert refusal is None, refusal


def _flag_text(value: Any) -> str | None:
    """An absent key stays ``None`` (an off-spelling), never the string
    ``'None'`` (which is not); any other TOML value — a bare boolean ``true``
    included — is passed as its text, which is an on-spelling the gate refuses
    with the coupling message rather than an ``AttributeError``."""
    return None if value is None else str(value)


def test_no_two_env_keys_collide_case_insensitively() -> None:
    """The app's ``Settings`` is ``case_sensitive=False``, so a lower-case
    ``peer_critique_enabled`` (or ``openrouter_live_execution_enabled``) line
    in ``[env]`` would set the flag while both gates above read only the
    upper-case key. Refuse the collision rather than guess which wins.

    RED IF: ``fly.toml``'s ``[env]`` carries two keys that differ only by case.
    """
    env = _fly_env()
    folded: dict[str, list[str]] = {}
    for key in env:
        folded.setdefault(key.upper(), []).append(key)
    collisions = {upper: keys for upper, keys in folded.items() if len(keys) > 1}
    assert not collisions, f"fly.toml [env] keys collide case-insensitively: {collisions}"
    # Positive partner: both coupled keys are present in their canonical case.
    assert FLAG in env and PEER_FLAG in env


def test_both_coupled_flag_lines_have_the_shape_the_closer_can_edit() -> None:
    """``make close-window`` rewrites the flag lines with a regex that matches
    exactly ``KEY = "value"`` (a basic double-quoted string). TOML also allows
    ``KEY = true``, ``KEY = 'true'`` and ``KEY = \"\"\"true\"\"\"``, all of which
    the app would read as on and the closer could not revert (or, for the
    triple-quoted form, would report as already off). Refuse those spellings
    pre-merge so a window opened by hand can always be closed by the script.

    RED IF: either flag line in ``fly.toml`` stops being a basic-string
    assignment, or appears more than once (case-insensitively).
    """
    spec = importlib.util.spec_from_file_location(
        "close_live_window_under_test", REPO_ROOT / "scripts" / "close_live_window.py"
    )
    assert spec is not None and spec.loader is not None
    closer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = closer
    spec.loader.exec_module(closer)
    text = FLY_TOML.read_text(encoding="utf-8")
    for key in (closer.FLAG, closer.PEER_FLAG):
        matches = closer._flag_line(key).findall(text)
        assert len(matches) == 1, (
            f'{key}: expected exactly one `{key} = "..."` line, found {len(matches)}'
        )


@pytest.mark.parametrize(
    ("peer_value", "live_value"),
    [
        ("false", "false"),
        ("true", "true"),
        ("", "false"),
        ("0", "off"),
        (None, "false"),
        ("false", "true"),
    ],
)
def test_a_peer_flag_that_does_not_outlive_the_live_flag_is_allowed(
    posture: ModuleType, peer_value: str | None, live_value: str
) -> None:
    """The allowed rows, driven by fixtures the real file cannot reach.

    RED IF: the coupling gate refuses a peer flag that is off, or one that is
    on beside a live flag that is also on (the inside-a-window shape).
    """
    assert posture.refuse_peer_without_live(peer_value=peer_value, live_value=live_value) is None


@pytest.mark.parametrize("peer_value", ["true", "True", "1", "yes", "on", "tru", "enabled"])
@pytest.mark.parametrize("live_value", ["false", "0", "off", "", None])
def test_a_peer_flag_on_while_live_is_off_is_refused_and_the_refusal_names_both(
    posture: ModuleType, peer_value: str, live_value: str | None
) -> None:
    """THE case the gate exists for, in every on-spelling and any typo.

    A typo is refused too, for the same reason the live gate refuses one:
    ``config.py`` parses the value, and this gate must not be the one place
    that guesses what a misspelling meant.

    RED IF: any on-spelling of the peer flag is accepted beside an off live
    flag, or the refusal fails to name the two keys an operator must now edit.
    """
    refusal = posture.refuse_peer_without_live(peer_value=peer_value, live_value=live_value)
    assert refusal is not None
    assert PEER_FLAG in refusal
    assert FLAG in refusal
    assert "make close-window" in refusal
