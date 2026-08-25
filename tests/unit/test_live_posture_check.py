"""#357: the watchdog that notices a money-spending posture nobody declared.

THE VACUITY TRAP THIS FILE IS BUILT AGAINST
    Production reports ``offline_by_config`` today, so a check that asks "is
    live execution on?" against production is trivially green forever and would
    stay green with its entire body deleted. Every "does it alert?" assertion
    here is therefore driven by a FIXTURE, and every one of them is paired with
    a partner proving the quiet path is still quiet. No test in this file
    touches ``quorum-ai.fly.dev``.

    The single check that no hollow implementation can pass is
    ``test_the_verdict_tracks_the_observed_posture``: three distinct inputs,
    three distinct outcomes, including ``None`` (unreadable) as ALERTING rather
    than falsy-quiet.

WHAT TURNS EACH TEST RED is stated in its own docstring, and the mutation
proving it is recorded in ADR-0070's bite table.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "live_posture_check.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "live-posture-watchdog.yml"
SHIPPED_WINDOWS = REPO_ROOT / "configs" / "live-execution-windows.json"

_NOW = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)
_NOW_OPEN = "2026-08-25T09:00:00+00:00"
_NOW_SHUT = "2026-08-25T17:00:00+00:00"
_OLD_OPEN = "2026-08-19T09:00:00+00:00"
_OLD_SHUT = "2026-08-19T17:00:00+00:00"
_FUTURE_OPEN = "2026-09-01T09:00:00+00:00"
_FUTURE_SHUT = "2026-09-01T17:00:00+00:00"
_HOST_A = "https://example.invalid/ready"
_HOST_B = "https://other.invalid/ready"


@pytest.fixture(scope="module")
def posture() -> ModuleType:
    """Load the script by path — ``scripts/`` is not an importable package."""
    spec = importlib.util.spec_from_file_location("live_posture_check_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # BEFORE exec: dataclass field resolution needs the module in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _window(
    posture: ModuleType,
    *,
    opened: str,
    expires: str,
    owner: str = "rohit",
    judge: bool = False,
    issue: int | None = None,
) -> Any:
    return posture.DeclaredWindow(
        owner=owner,
        reason="collect the ADR-0060 sample",
        opened_at=dt.datetime.fromisoformat(opened),
        expires_at=dt.datetime.fromisoformat(expires),
        mode=posture.MODE_TIME_BOXED,
        judge=judge,
        reaffirm_issue=issue,
    )


def _standing(
    posture: ModuleType,
    *,
    opened: str,
    adr: str = "ADR-0099",
    judge: bool = False,
    issue: int | None = None,
) -> Any:
    return posture.DeclaredWindow(
        owner="rohit",
        reason="the GA steady state",
        opened_at=dt.datetime.fromisoformat(opened),
        expires_at=None,
        mode=posture.MODE_STANDING,
        judge=judge,
        adr=adr,
        reaffirm_issue=issue,
    )


def _reaffirmed(
    posture: ModuleType, *, window: Any, hours_ago: float, now: dt.datetime
) -> dict[int, list[Any]]:
    """A re-affirmation map putting ONE human affirmation `hours_ago` on `window`."""
    assert window.reaffirm_issue is not None, "a re-affirmed window must name its issue"
    return {
        window.reaffirm_issue: [
            posture.Reaffirmation(
                at=now - dt.timedelta(hours=hours_ago),
                by="rohit",
                window_opened_at=window.opened_at,
            )
        ]
    }


# --- A. The pure decision --------------------------------------------------


def test_live_execution_on_with_no_declared_window_alerts(posture: ModuleType) -> None:
    """THE defect #357 records: on, and nobody wrote down that it was intended.

    RED IF: the final ``LIVE_UNDECLARED`` return is changed to any non-alerting
    decision, or the live-host filter stops looking at the state.
    """
    result = posture.evaluate_posture(readiness_states={_HOST_A: "live"}, windows=[], now=_NOW)
    assert result.decision is posture.PostureDecision.LIVE_UNDECLARED
    assert result.should_alert is True


def test_live_execution_off_is_quiet(posture: ModuleType) -> None:
    """POSITIVE PARTNER (rule 7). Without it, a script that always alerts passes.

    RED IF: the check starts alerting on a correctly-off production — the
    permanently-red-monitor failure ``test_availability_check_workflow.py``
    records, where a monitor red on every run cannot signal anything.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"}, windows=[], now=_NOW
    )
    assert result.decision is posture.PostureDecision.OFF_AS_DECLARED
    assert result.should_alert is False


@pytest.mark.parametrize("state", ["live", "offline_by_no_key", "offline_by_bad_key"])
def test_every_state_but_offline_by_config_means_the_flag_is_on(
    posture: ModuleType, state: str
) -> None:
    """``readiness.py:445`` is the ``else`` of a four-way, so this is exact.

    ``offline_by_bad_key`` matters most: ``/status.live_execution`` reads FALSE
    in that state while ``providers.py:670`` — which has no probe term — still
    returns True. A check built on ``/status`` would be blind to it.

    RED IF: ``FLAG_OFF_STATE`` is widened to cover any other state, or the
    comparison becomes ``state == "live"``.
    """
    result = posture.evaluate_posture(readiness_states={_HOST_A: state}, windows=[], now=_NOW)
    assert result.should_alert is True


def test_live_execution_inside_a_declared_window_is_quiet(posture: ModuleType) -> None:
    """The crying-wolf answer: a sanctioned window does not alert.

    RED IF: the ``active`` branch is removed, so every legitimate sampling
    window fires an alert and the alert gets muted.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"}, windows=[window], now=_NOW
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_DECLARED_WINDOW
    assert result.should_alert is False


def test_live_execution_past_a_declared_window_alerts(posture: ModuleType) -> None:
    """#357 exactly: three days past a window somebody wrote as one session.

    RED IF: ``covers`` stops comparing against ``expires_at``, so a declaration
    sanctions the posture forever once opened.
    """
    window = _window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"}, windows=[window], now=_NOW
    )
    assert result.decision is posture.PostureDecision.LIVE_PAST_DECLARED_WINDOW
    assert result.should_alert is True


def test_a_window_that_has_not_opened_yet_does_not_sanction_anything(
    posture: ModuleType,
) -> None:
    """A future window is not a licence to be on now.

    RED IF: ``covers`` stops comparing against ``opened_at``, so declaring a
    window for next month silences the check today.
    """
    window = _window(posture, opened=_FUTURE_OPEN, expires=_FUTURE_SHUT)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"}, windows=[window], now=_NOW
    )
    assert result.should_alert is True


def test_the_window_boundaries_are_exact(posture: ModuleType) -> None:
    """Literals on both sides (rule 7a) — never against a shipped constant.

    The window is half-open: it covers its opening instant and not its expiry.

    RED IF: either comparison flips its strictness, so the posture is sanctioned
    one tick before it was declared or one tick after it ended.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    just_before = dt.datetime(2026, 8, 25, 8, 59, 59, tzinfo=dt.UTC)
    at_open = dt.datetime(2026, 8, 25, 9, 0, 0, tzinfo=dt.UTC)
    just_before_expiry = dt.datetime(2026, 8, 25, 16, 59, 59, tzinfo=dt.UTC)
    at_expiry = dt.datetime(2026, 8, 25, 17, 0, 0, tzinfo=dt.UTC)

    assert window.covers(at_open) is True
    assert window.covers(just_before_expiry) is True
    assert window.covers(just_before) is False
    assert window.covers(at_expiry) is False


def test_one_live_host_alerts_even_when_the_other_is_off(posture: ModuleType) -> None:
    """Fail closed across hosts: either host spending is spending.

    RED IF: the live-host filter becomes ``all`` instead of ``any``.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live", _HOST_B: "offline_by_config"},
        windows=[],
        now=_NOW,
    )
    assert result.should_alert is True
    assert _HOST_A in result.detail


def test_the_decisions_are_exhaustively_pinned(posture: ModuleType) -> None:
    """Every enum member is classified alerting or quiet, and both sets exist.

    RED IF: a decision is added without deciding whether it alerts.
    """
    alerting = {d for d in posture.PostureDecision if posture.PostureResult(d, "x").should_alert}
    quiet = {d for d in posture.PostureDecision if not posture.PostureResult(d, "x").should_alert}
    assert alerting and quiet
    assert alerting | quiet == set(posture.PostureDecision)
    assert not (alerting & quiet)


@pytest.mark.parametrize(
    ("observed", "expected_alert"),
    [("live", True), ("offline_by_config", False), (None, True)],
)
def test_the_verdict_tracks_the_observed_posture(
    posture: ModuleType, observed: str | None, expected_alert: bool
) -> None:
    """Three inputs, three outcomes. No implementation ignoring its input passes.

    ``None`` is the load-bearing row: it is FALSY, so a naive
    ``bool(state)``-style implementation would read "I could not tell" as
    "healthy" and be silently green forever against today's production.

    RED IF: an unreadable reading is treated as the off-state, or the verdict
    stops depending on the observed state at all.
    """
    result = posture.evaluate_posture(readiness_states={_HOST_A: observed}, windows=[], now=_NOW)
    assert result.should_alert is expected_alert


# --- B. Unreadable input is LOUD, not silent -------------------------------


def test_no_readable_host_is_unknown_and_alerts(posture: ModuleType) -> None:
    """ "I could not tell" is a failure of the check, not a clean bill of health.

    RED IF: the empty-``readable`` branch is removed, so an outage of both hosts
    falls through to ``OFF_AS_DECLARED``.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: None, _HOST_B: None}, windows=[], now=_NOW
    )
    assert result.decision is posture.PostureDecision.UNKNOWN
    assert result.should_alert is True


def test_an_unrecognised_readiness_state_is_unknown_and_alerts(posture: ModuleType) -> None:
    """Fail closed on a vocabulary this check has never heard of.

    RED IF: the ``KNOWN_READINESS_STATES`` guard is dropped, so a renamed state
    in a future app version reads as "not offline_by_config, therefore live" —
    or worse, a typo'd state reads as off.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_something_new"}, windows=[], now=_NOW
    )
    assert result.decision is posture.PostureDecision.UNKNOWN
    assert result.should_alert is True


def test_an_unreadable_declaration_file_is_unknown_and_alerts(posture: ModuleType) -> None:
    """A declaration that will not parse must never permit anything.

    RED IF: ``windows=None`` is coerced to an empty list, which would route a
    malformed file plus an OFF posture through the QUIET branch — so a file
    broken during a live window would be indistinguishable from a healthy one.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"}, windows=None, now=_NOW
    )
    assert result.decision is posture.PostureDecision.UNKNOWN
    assert result.should_alert is True


def _entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "owner": "x",
        "reason": "y",
        "mode": "time_boxed",
        "judge": False,
        "opened_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-02T00:00:00+00:00",
    }
    entry.update(overrides)
    return entry


@pytest.mark.parametrize(
    "payload",
    [
        [],
        None,
        "a string",
        {"windows": "not a list"},
        {"windows": ["not an object"]},
        {"windows": [_entry(opened_at="nope")]},
        {"windows": [_entry(expires_at="nope")]},
        {"windows": [_entry(owner="")]},
        {"windows": [_entry(reason="   ")]},
        # expiry before opening: covers no instant, so it would read as a
        # declaration while sanctioning nothing.
        {"windows": [_entry(expires_at="2025-01-01T00:00:00+00:00")]},
        # naive timestamps: "00:00" in whose day?
        {"windows": [_entry(opened_at="2026-01-01T00:00:00")]},
        {"windows": [_entry(expires_at="2026-01-02T00:00:00")]},
        # --- ADR-0071 rows. Before it, an unknown key was SILENTLY IGNORED,
        # so `{"mode": "standng"}` parsed and meant nothing. A field that a typo
        # quietly disables is the silently-green shape this package abolishes.
        {"windows": [_entry(mode=None)]},
        {"windows": [_entry(mode="standng")]},
        {"windows": [_entry(mode="Standing")]},
        {"windows": [_entry(mode="time-boxed")]},
        {"windows": [_entry(mode=7)]},
        # `judge` is REQUIRED and must be a real bool. `isinstance(True, int)` is
        # True in Python, so the string and the integer are both near-misses that
        # a lenient parser would accept as "yes".
        {"windows": [_entry(judge=None)]},
        {"windows": [_entry(judge="true")]},
        {"windows": [_entry(judge=1)]},
        # a time_boxed window may not carry an ADR citation it does not need
        {"windows": [_entry(adr="ADR-0099")]},
        # a standing window must not carry an expiry, must cite an ADR, and the
        # citation must resolve — with no authorised set supplied, none does.
        {"windows": [_entry(mode="standing")]},
        {"windows": [_entry(mode="standing", expires_at=None, adr=None)]},
        {"windows": [_entry(mode="standing", expires_at=None, adr="")]},
        {"windows": [_entry(mode="standing", expires_at=None, adr="ADR-99")]},
        {"windows": [_entry(mode="standing", expires_at=None, adr="see ADR-0099")]},
        {"windows": [_entry(mode="standing", expires_at=None, adr="ADR-0099")]},
        # reaffirm_issue must be a positive integer, and `True` is not one
        {"windows": [_entry(reaffirm_issue="105")]},
        {"windows": [_entry(reaffirm_issue=0)]},
        {"windows": [_entry(reaffirm_issue=-1)]},
        {"windows": [_entry(reaffirm_issue=True)]},
    ],
)
def test_a_malformed_declaration_refuses_to_parse(posture: ModuleType, payload: object) -> None:
    """Each row is a way a declaration could be wrong. All must return None.

    The naive-timestamp row matters most: "17:00" in whose day? Accepting it
    could widen a window by hours in the operator's favour.

    RED IF: any validation branch in ``parse_windows`` is deleted.
    """
    assert posture.parse_windows(payload) is None


@pytest.mark.parametrize("missing", ["mode", "judge", "owner", "reason", "opened_at"])
def test_a_declaration_missing_a_required_field_refuses_to_parse(
    posture: ModuleType, missing: str
) -> None:
    """The key is ABSENT, not present-and-wrong — a different mutation entirely.

    ``_entry(judge=None)`` still puts the key in the dict, so it survives
    ``entry.get("judge", False)``. Only a genuinely missing key exercises the
    default. Measured: mutating ``entry.get("judge")`` to
    ``entry.get("judge", False)`` left the whole suite GREEN until this row
    existed — a required money field silently acquiring a default, which is the
    decision-nobody-made shape.

    RED IF: any required field acquires a default in ``_parse_window``.
    """
    entry = _entry()
    del entry[missing]
    assert posture.parse_windows({"windows": [entry]}) is None


def test_a_standing_window_may_not_also_carry_an_expiry(posture: ModuleType) -> None:
    """Both would leave a reader unable to say which one governs.

    Measured: without this, deleting the ``expires is not None`` refusal left the
    suite green, so a window could be declared ``standing`` — no deadline, no
    pre-merge pressure — while LOOKING in the diff like a bounded one.

    RED IF: the refusal is removed.
    """
    entry = {
        "owner": "rohit",
        "reason": "GA",
        "mode": "standing",
        "judge": True,
        "opened_at": _NOW_OPEN,
        "adr": "ADR-0099",
        "reaffirm_issue": 400,
        "expires_at": _NOW_SHUT,
    }
    assert (
        posture.parse_windows({"windows": [entry]}, authorised_adrs=frozenset({"ADR-0099"})) is None
    )
    # POSITIVE PARTNER: the identical entry WITHOUT the expiry must parse, or
    # this test would pass against a parser that refuses every standing window.
    del entry["expires_at"]
    parsed = posture.parse_windows({"windows": [entry]}, authorised_adrs=frozenset({"ADR-0099"}))
    assert parsed is not None and parsed[0].is_standing


def test_a_wellformed_declaration_parses(posture: ModuleType) -> None:
    """POSITIVE PARTNER for the row above: the negative check is worthless if
    ``parse_windows`` returns None for everything.

    RED IF: ``parse_windows`` starts rejecting a valid declaration — which would
    make the watchdog alert through every sanctioned window and get it muted.
    """
    parsed = posture.parse_windows(
        {
            "windows": [
                {
                    "owner": "rohit",
                    "reason": "ADR-0060 sample",
                    "mode": "time_boxed",
                    "judge": False,
                    "opened_at": "2026-08-19T09:00:00Z",
                    "expires_at": "2026-08-19T17:00:00Z",
                }
            ]
        }
    )
    assert parsed is not None
    assert len(parsed) == 1
    assert parsed[0].owner == "rohit"
    assert parsed[0].covers(dt.datetime(2026, 8, 19, 12, 0, tzinfo=dt.UTC))


def test_the_shipped_declaration_file_parses(posture: ModuleType) -> None:
    """The file this repository ships must be READABLE.

    It deliberately does NOT assert the list is empty. Review found that doing
    so made the mechanism's own escape valve unmergeable: declaring a window is
    exactly what the file, the refusal message and ADR-0070 all instruct, and
    the file's README says expired entries stay as the record — so after the
    first window ever declared there is no state in which it is empty again. A
    guard that goes red on the sanctioned path is a guard somebody deletes.

    Whether the flag and the windows AGREE is a different question, and it is
    asked by test_live_execution_posture_declaration.py against fly.toml.

    RED IF: the shipped file is edited into something unparseable — which would
    make the watchdog alert UNKNOWN on every run and get it muted.
    """
    parsed = posture.parse_windows(json.loads(SHIPPED_WINDOWS.read_text(encoding="utf-8")))
    assert parsed is not None, "the shipped declaration file no longer parses"
    assert isinstance(parsed, list)


def test_the_shipped_declaration_file_declares_no_window_right_now(
    posture: ModuleType,
) -> None:
    """No window may be OPEN in the tree unless the flag is on to match it.

    This is the pair to the test above: parsing is not enough, because a window
    left open sanctions a live posture nobody is attending. It is scoped to
    "covers now", not "is empty", so an expired historical entry is fine — which
    is what the file's README asks for.

    RED IF: a window covering the present is committed while fly.toml has the
    flag off, i.e. a declaration outlives the work it sanctioned.
    """
    parsed = posture.load_windows(posture.DEFAULT_WINDOWS_PATH)
    assert parsed is not None
    now = dt.datetime.now(dt.UTC)
    # PARSE the TOML rather than substring-matching it. The original read
    # `'OPENROUTER_LIVE_EXECUTION_ENABLED = "false"' not in fly`, which a
    # reformat of fly.toml (single quotes, or no spaces around the `=`) would
    # turn True — making this whole assertion vacuously pass over an open
    # window. `_fly_env`-style parsing cannot drift that way.
    env = tomllib.loads((REPO_ROOT / "fly.toml").read_text(encoding="utf-8")).get("env", {})
    assert isinstance(env, dict) and env, (
        "fly.toml has no [env] block — this gate refuses to pass over nothing"
    )
    assert "OPENROUTER_LIVE_EXECUTION_ENABLED" in env, (
        "the flag is no longer in fly.toml [env]; repoint this gate, do not delete it"
    )
    flag_on = str(env["OPENROUTER_LIVE_EXECUTION_ENABLED"]).strip().lower() not in {
        "false",
        "0",
        "no",
        "off",
        "",
    }
    # Scoped to TIME-BOXED windows. A `standing` window covers every instant
    # from the moment it opens — that is what the mode means — so including it
    # here would make the first standing declaration turn this gate red and
    # invite somebody to loosen the assertion, which is how a real gate gets
    # deleted disguised as a fixture update. Standing windows have their own
    # obligations (a resolving ADR citation, and re-affirmation at runtime);
    # they are checked in test_live_execution_posture_declaration.py.
    open_now = [w for w in parsed if w.covers(now) and not w.is_standing]
    assert flag_on or not open_now, (
        f"{len(open_now)} declared time-boxed window(s) cover {now.isoformat()} "
        "while fly.toml has live execution off — close the declaration, or the "
        "next accidental 'true' is silently sanctioned."
    )


# --- The I/O layer, with a REAL body ---------------------------------------
#
# AGENTS.md rule 8a: both of this repo's `_http_error` doubles pass `fp=None`,
# so `.read()` returns `b''` and any "the body does not contain X" assertion
# against them passes vacuously against every implementation. These stubs serve
# a REAL JSON body through a real `file:` URL, so what is asserted is what was
# actually parsed.


def _ready_stub(tmp_path: Path, payload: object, name: str = "ready.json") -> str:
    stub = tmp_path / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    stub.write_text(text, encoding="utf-8")
    return stub.as_uri()


def test_a_ready_body_reporting_live_is_read(posture: ModuleType, tmp_path: Path) -> None:
    """RED IF: ``fetch_readiness_state`` stops descending into
    ``live_readiness``, or hardcodes a state."""
    url = _ready_stub(
        tmp_path,
        {"status": "ready", "live_readiness": {"state": "live", "reasons": []}},
    )
    assert posture.fetch_readiness_state(url, attempts=1) == "live"


def test_a_ready_body_reporting_offline_by_config_is_read(
    posture: ModuleType, tmp_path: Path
) -> None:
    """PARTNER to the row above: two distinct values, both asserted, so an
    implementation hardcoding either one fails the other.

    RED IF: the parser returns a constant.
    """
    url = _ready_stub(
        tmp_path,
        {"status": "ready", "live_readiness": {"state": "offline_by_config", "reasons": ["x"]}},
        name="off.json",
    )
    assert posture.fetch_readiness_state(url, attempts=1) == "offline_by_config"


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "null",
        '"a string"',
        "123",
        "not json at all",
        "<html></html>",
        '{"status":"ready"}',
        '{"status":"ready","live_readiness":"live"}',
        '{"status":"ready","live_readiness":{"reasons":[]}}',
        '{"status":"ready","live_readiness":{"state":""}}',
    ],
)
def test_an_unusable_ready_body_reads_as_none(
    posture: ModuleType, tmp_path: Path, payload: str
) -> None:
    """None means "unknown", which alerts. The two rows with a well-formed
    envelope but no usable ``state`` are the dangerous ones: a
    ``.get("state", "offline_by_config")`` default would turn them into a
    permanent, silent all-clear.

    RED IF: any guard in ``fetch_readiness_state`` is removed, or the missing
    key acquires an off-state default.
    """
    url = _ready_stub(tmp_path, payload, name=f"body{abs(hash(payload))}.json")
    assert posture.fetch_readiness_state(url, attempts=1) is None


def test_an_unreadable_declaration_path_loads_as_none(posture: ModuleType, tmp_path: Path) -> None:
    """RED IF: ``load_windows`` stops catching, so a missing file crashes the
    process before ``$GITHUB_OUTPUT`` is written and the job reports success."""
    assert posture.load_windows(tmp_path / "does-not-exist.json") is None


def test_the_shipped_declaration_path_loads(posture: ModuleType) -> None:
    """POSITIVE PARTNER: ``load_windows`` returning None for everything would
    satisfy the row above.

    RED IF: ``DEFAULT_WINDOWS_PATH`` stops pointing at a real file.
    """
    assert posture.load_windows(posture.DEFAULT_WINDOWS_PATH) is not None


# --- C. It reports what it counted -----------------------------------------


def test_every_decision_reports_what_it_observed(posture: ModuleType) -> None:
    """Each branch must say what it looked at, and every branch must be reached.

    RED IF: any branch's detail is blanked, or a branch is deleted so the loop
    can no longer reach it (``seen == set(...)`` catches the second).
    """
    window_now = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    window_past = _window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)
    # Opened well over the cadence ago and never re-affirmed: the lapse branch.
    window_stale = _window(posture, opened=_OLD_OPEN, expires=_FUTURE_SHUT)
    # Attended, but the judge is on and this window does not declare it.
    window_fresh = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, judge=False)
    window_standing = _standing(posture, opened=_NOW_OPEN)
    cases = [
        ({_HOST_A: "offline_by_config"}, [], None, {}),
        ({_HOST_A: "live"}, [window_now], None, {}),
        ({_HOST_A: "live"}, [], None, {}),
        ({_HOST_A: "live"}, [window_past], None, {}),
        ({_HOST_A: None}, [], None, {}),
        ({_HOST_A: "live"}, None, "malformed", {}),
        ({_HOST_A: "live"}, [window_stale], None, {}),
        ({_HOST_A: "live"}, [window_fresh], None, {_HOST_B: True}),
        ({_HOST_A: "live"}, [window_standing], None, {}),
    ]
    seen = set()
    for states, windows, _, judge in cases:
        result = posture.evaluate_posture(
            readiness_states=states, windows=windows, now=_NOW, judge_states=judge
        )
        assert result.detail.strip()
        assert len(result.detail) > 40, result.detail
        seen.add(result.decision)
    assert seen == set(posture.PostureDecision), (
        "a PostureDecision is unreachable from this case list — add a case that "
        f"reaches it. Missing: {set(posture.PostureDecision) - seen}"
    )


def test_the_detail_names_how_many_hosts_and_windows_it_read(posture: ModuleType) -> None:
    """A gate that reports "nothing found" without saying what it looked at is
    trivially true over nothing.

    RED IF: the ``counted`` sentence stops interpolating the real counts — the
    two cases below differ in both numbers, so a hardcoded string fails one.
    """
    one = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"}, windows=[], now=_NOW
    )
    assert "read 1 of 1 host(s)" in one.detail
    assert "0 window(s) declared" in one.detail

    window = _window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)
    two = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config", _HOST_B: None},
        windows=[window],
        now=_NOW,
    )
    assert "read 1 of 2 host(s)" in two.detail
    assert "1 window(s) declared" in two.detail


def test_main_prints_every_url_it_probed(
    posture: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """RED IF: ``main`` stops naming its sources, so a reader of a red job
    cannot tell which host reported what."""
    url = _ready_stub(tmp_path, {"live_readiness": {"state": "offline_by_config"}})
    status = _ready_stub(tmp_path, {"judge_enabled": True}, name="probe-status.json")
    posture.main(
        ["--ready-url", url, "--status-url", status, "--windows-file", str(SHIPPED_WINDOWS)]
    )
    printed = capsys.readouterr().out
    assert url in printed
    assert "offline_by_config" in printed
    # It must name the /status source too, and what it read there — the judge is
    # a second paid subsystem and a reader of a green job needs both numbers.
    assert status in printed
    assert "judge_enabled=True" in printed


# --- D. THE WIRE. Deleting the $GITHUB_OUTPUT write must go red ------------


def _run_main(
    posture: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: object,
    windows_payload: object,
    judge: object = False,
    comments: Sequence[object] = (),
    adr_dir: Path | None = None,
) -> tuple[int, str]:
    """Drive ``main`` end to end over ``file:`` fixtures ONLY.

    Every URL is passed explicitly, including ``--status-url``. That is not
    tidiness: ``main``'s defaults are the real production hosts, so a test that
    omitted one would silently reach ``quorum-ai.fly.dev`` — measured, an early
    revision of this file did exactly that and the suite took 103s. No test here
    touches production.
    """
    ready = _ready_stub(tmp_path, body, name="wire-ready.json")
    status = _ready_stub(tmp_path, {"judge_enabled": judge}, name="wire-status.json")
    reaff = _ready_stub(tmp_path, list(comments), name="wire-comments.json")
    windows = tmp_path / "windows.json"
    windows.write_text(json.dumps(windows_payload), encoding="utf-8")
    outputs = tmp_path / "outputs.txt"
    outputs.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    code = posture.main(
        [
            "--ready-url",
            ready,
            "--status-url",
            status,
            "--windows-file",
            str(windows),
            "--adr-dir",
            str(adr_dir if adr_dir is not None else REPO_ROOT / "docs" / "adr"),
            "--reaffirmations-url",
            reaff,
        ]
    )
    return code, outputs.read_text(encoding="utf-8")


def test_main_publishes_the_verdict_and_exits_nonzero_on_an_undeclared_posture(
    posture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end proof that the mechanism FIRES on a live fixture.

    RED IF: the ``_write_outputs`` call is deleted from ``main``, or the
    ``should_alert`` key is renamed — both of which leave the watchdog
    permanently GREEN while production spends, and neither of which any
    decision-only test can see.
    """
    code, written = _run_main(
        posture,
        tmp_path,
        monkeypatch,
        body={"live_readiness": {"state": "live"}},
        windows_payload={"windows": []},
    )
    assert code == 1
    assert "should_alert=true" in written
    assert "decision=live_undeclared" in written


def test_main_publishes_the_verdict_and_exits_zero_when_the_switch_is_off(
    posture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POSITIVE PARTNER: a script that always exits 1 and always writes
    ``true`` would satisfy the test above on its own.

    RED IF: ``main`` hardcodes its exit code or its verdict.
    """
    code, written = _run_main(
        posture,
        tmp_path,
        monkeypatch,
        body={"live_readiness": {"state": "offline_by_config"}},
        windows_payload={"windows": []},
    )
    assert code == 0
    assert "should_alert=false" in written
    assert "decision=off_as_declared" in written


def test_main_stays_quiet_through_a_declared_window(
    posture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anti-crying-wolf path, end to end on a fixture.

    RED IF: the declaration stops being read by ``main``, so every sanctioned
    window fires an alert.
    """
    far_future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat()
    far_past = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
    code, written = _run_main(
        posture,
        tmp_path,
        monkeypatch,
        body={"live_readiness": {"state": "live"}},
        windows_payload={
            "windows": [
                {
                    "owner": "rohit",
                    "reason": "declared sample",
                    "mode": "time_boxed",
                    "judge": False,
                    "opened_at": far_past,
                    "expires_at": far_future,
                    "reaffirm_issue": 105,
                }
            ]
        },
    )
    assert code == 0
    assert "should_alert=false" in written
    assert "decision=live_within_declared_window" in written


def test_main_survives_a_fetcher_that_raises(
    posture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED IF: ``fetch_readiness_state`` stops catching, so an exception kills
    the process before the verdict is written and the continue-on-error step
    leaves the job GREEN."""

    def _boom(url: str, *, attempts: int = 3) -> str | None:
        raise RuntimeError("network on fire")

    monkeypatch.setattr(posture, "fetch_readiness_state", _boom)
    outputs = tmp_path / "outputs.txt"
    outputs.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    status = _ready_stub(tmp_path, {"judge_enabled": False}, name="boom-status.json")
    with pytest.raises(RuntimeError):
        posture.main(
            [
                "--ready-url",
                _HOST_A,
                "--status-url",
                status,
                "--windows-file",
                str(SHIPPED_WINDOWS),
            ]
        )
    # The module-level __main__ net is what converts this into an UNKNOWN
    # verdict plus exit 1; that net is asserted structurally below.
    assert "BaseException" in SCRIPT.read_text(encoding="utf-8")


# --- E. The workflow, structurally -----------------------------------------


def _load_workflow() -> dict[Any, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps() -> list[dict[Any, Any]]:
    return list(_load_workflow()["jobs"]["posture"]["steps"])


def _run_bodies() -> str:
    """Only the steps' ``run:`` bodies. Comments in the file must not be able to
    satisfy these assertions — a header comment carrying a test is a measured
    defect in this repo (``test_availability_check_workflow.py:63-71``)."""
    scripts = [step["run"] for step in _steps() if "run" in step]
    assert scripts, "the posture job has no run step"
    return "\n".join(scripts)


def test_triggers_are_schedule_and_dispatch_only() -> None:
    """RED IF: a ``push``/``pull_request``/``workflow_run`` trigger is added — a
    slow job on the push path once silently stopped every deploy."""
    data = _load_workflow()
    # PyYAML parses the bare key `on:` as boolean True.
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict)
    assert set(triggers) == {"schedule", "workflow_dispatch"}


def test_the_schedule_is_the_declared_cadence() -> None:
    """RED IF: the cadence changes without the latency note in the file and in
    ADR-0070 changing with it."""
    data = _load_workflow()
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict)
    assert [entry["cron"] for entry in triggers["schedule"]] == ["*/30 * * * *"]


def test_the_check_step_runs_the_tested_script() -> None:
    """RED IF: the invocation is replaced by an inline shell block while the
    script name survives only in a comment — which the raw-text version of this
    assertion would not catch."""
    assert "scripts/live_posture_check.py" in _run_bodies()


def test_the_workflow_branches_on_the_key_this_script_writes() -> None:
    """Both sides of the wire, pinned together.

    RED IF: the output key is renamed on either side; if
    ``continue-on-error`` is dropped (the alert step would then be skipped by a
    failing check step); or if the explicit ``exit 1`` is removed, leaving an
    undeclared money posture merely noted in a green job.
    """
    script = SCRIPT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'write(f"should_alert=' in script
    assert "steps.posture.outputs.should_alert" in workflow
    assert "continue-on-error: true" in workflow
    assert "exit 1" in _run_bodies()


#: Every step condition, in full. Asserted by EQUALITY, not by substring.
#:
#: Review broke the substring version two ways, each leaving the whole suite
#: green: typo the fail step's terms (``outputs.shouldAlert`` /
#: ``outcome == 'faliure'``) and the job is GREEN forever on a live posture; or
#: AND an extra ``github.event_name == 'workflow_dispatch'`` into the alert
#: step's condition and no scheduled run ever opens an issue. A substring
#: assertion sees the terms it was told to look for and is blind to what else
#: was joined to them — AGENTS.md rule 8, reappearing inside the new gate.
_ALERT_CONDITION = (
    "always() && (steps.posture.outputs.should_alert == 'true' || "
    "steps.posture.outcome == 'failure')"
)
_RESOLVE_CONDITION = (
    "always() && steps.posture.outcome == 'success' && "
    "steps.posture.outputs.should_alert == 'false' && "
    "steps.posture.outputs.complete == 'true'"
)


def _condition(name: str) -> str:
    step = [s for s in _steps() if name in str(s.get("name", ""))]
    assert len(step) == 1, f"no unique step named like {name!r}"
    return " ".join(str(step[0]["if"]).split())


def test_the_alert_step_fires_on_exactly_these_conditions() -> None:
    """The alert must fire on an alerting verdict AND on a crashed check — a
    crash writes no outputs, so branching on ``should_alert`` alone would skip
    the alert and leave a continue-on-error job green.

    RED IF: either disjunct is dropped, OR any further term is ANDed in (which
    is how a scheduled-run-only condition would silently disarm this).
    """
    assert _condition("Alert on an undeclared") == _ALERT_CONDITION


def test_the_fail_step_fires_on_exactly_the_same_conditions() -> None:
    """The red job is the RECURRING signal — ADR-0070 deliberately does not
    re-comment on the issue, so this is the only thing that repeats.

    Nothing asserted this step's condition until review typo'd it two ways and
    watched the whole suite stay green while the watchdog went permanently OK.

    RED IF: the fail step's condition drifts from the alert step's by so much as
    a character, so the watchdog can alert once and then report success forever.
    """
    assert _condition("Fail the job on an undeclared") == _ALERT_CONDITION


def test_the_resolve_step_fires_on_exactly_these_conditions() -> None:
    """The posture alert closes only on a reading the check actually took, that
    is actually safe, and that saw every host.

    The sibling drift watchdog closes its issue as soon as a deploy succeeds,
    which is why it reported #357's drift RESOLVED at the moment the money
    posture went live.

    RED IF: ``outcome == 'success'`` is dropped (a crashed step writes no
    outputs, and ``should_alert != 'true'`` is true of an empty string); or
    ``complete == 'true'`` is dropped, letting a cycle that read only some hosts
    retire a standing money alert.
    """
    assert _condition("Resolve the posture alert") == _RESOLVE_CONDITION


def test_the_workflow_declares_the_permissions_it_uses() -> None:
    """RED IF: ``issues: write`` is dropped, so the alert step 401s and the
    watchdog goes quiet about the one thing it exists to say."""
    assert _load_workflow()["permissions"]["issues"] == "write"


def test_not_in_the_deploy_gate_required_set() -> None:
    """RED IF: this scheduled monitor is added to the deploy gate, where a red
    posture check would block every deploy including the revert that fixes it."""
    gate = (REPO_ROOT / "scripts" / "deploy_gate.py").read_text(encoding="utf-8")
    assert "live-posture" not in gate
    assert "Live-execution posture" not in gate


# --- F. The alert and resolve steps EXECUTED, with `gh` stubbed ------------
#
# Everything in section E is a structural assertion over parsed YAML. It cannot
# see whether the shell in those steps actually RUNS — a `set -euo pipefail`
# block with an unquoted expansion or a bad `printf` fails at runtime while
# every structural test stays green, and the job is `continue-on-error` right up
# until the fail step, so a broken alert step would lose the alert silently.
# These extract the step bodies and execute them against a stub `gh`, asserting
# on the exit code and on the commands the stub was asked to run.


def _exec_step(name: str, tmp_path: Path, *, open_issue: str = "") -> tuple[int, str]:
    step = [s for s in _steps() if name in str(s.get("name", ""))]
    assert len(step) == 1, f"no unique step named like {name!r}"
    log = tmp_path / "gh.log"
    stub = tmp_path / "gh"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> {log}\n'
        'if [ "$1 $2" = "issue list" ]; then printf "%s" ' + f'"{open_issue}"' + "; fi\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    import subprocess

    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell interpolation of input
        ["/bin/bash", "-c", step[0]["run"]],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "GH_TOKEN": "stub",
            "REPO": "owner/repo",
            "DECISION": "live_undeclared",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, log.read_text(encoding="utf-8") if log.exists() else ""


def test_the_alert_step_opens_an_issue_when_none_is_open(tmp_path: Path) -> None:
    """RED IF: the alert step's shell stops running clean, or stops calling
    ``gh issue create`` — either loses the alert while the structural tests
    above stay green."""
    code, calls = _exec_step("Alert on an undeclared", tmp_path, open_issue="")
    assert code == 0, calls
    assert "issue create" in calls
    assert "--label live-posture" in calls
    # It must say what to do about the money, not merely that something is wrong.
    assert "OPENROUTER_LIVE_EXECUTION_ENABLED" in calls
    assert "live-execution-windows.json" in calls


def test_the_alert_step_does_not_open_a_second_issue(tmp_path: Path) -> None:
    """PARTNER: proves the create above is conditional, not unconditional.

    RED IF: the already-open branch is dropped, so every 30-minute cycle files
    another issue — which over a three-day posture is ~70 of them, and that is
    how an alert gets muted.
    """
    code, calls = _exec_step("Alert on an undeclared", tmp_path, open_issue="4242")
    assert code == 0, calls
    assert "issue create" not in calls


def test_the_resolve_step_closes_an_open_alert(tmp_path: Path) -> None:
    """RED IF: the resolve step's shell breaks, so a posture alert stays open
    after production is safe again and the signal decays into noise."""
    code, calls = _exec_step("Resolve the posture alert", tmp_path, open_issue="4242")
    assert code == 0, calls
    assert "issue close 4242" in calls


def test_the_resolve_step_is_a_no_op_with_nothing_open(tmp_path: Path) -> None:
    """PARTNER: proves the close above is conditional.

    RED IF: the guard is dropped and the step calls ``gh issue close`` with an
    empty issue number on every quiet cycle.
    """
    code, calls = _exec_step("Resolve the posture alert", tmp_path, open_issue="")
    assert code == 0, calls
    assert "issue close" not in calls


# --- G. The vocabulary, and the completeness signal ------------------------


def test_the_known_states_match_the_app_exactly(posture: ModuleType) -> None:
    """The script hardcodes the readiness vocabulary; the app defines it.

    Nothing tied the two together until review pointed out the consequence: a
    rename in ``readiness.py`` makes every reading UNKNOWN, so the watchdog goes
    permanently RED and gets muted — failure mode 9 arriving through a rename.

    RED IF: a state is added, removed or renamed in
    ``src/product_app/readiness.py`` without the script following.
    """
    from typing import get_args

    from product_app.readiness import ReadinessState

    app_states = set(get_args(ReadinessState))
    assert app_states, "ReadinessState has no members — this gate refuses to pass over nothing"
    assert app_states == posture.KNOWN_READINESS_STATES
    assert posture.FLAG_OFF_STATE in app_states


def test_a_full_read_is_complete(posture: ModuleType) -> None:
    """POSITIVE PARTNER: without it, ``complete`` could be hardcoded False and
    the resolve step would never close anything.

    RED IF: ``complete`` stops being computed from the reads.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config", _HOST_B: "offline_by_config"},
        windows=[],
        now=_NOW,
    )
    assert result.complete is True
    assert result.should_alert is False


def test_a_partial_read_is_not_complete_and_says_so(posture: ModuleType) -> None:
    """A cycle that read one host of two may be acted on, but must not RETIRE a
    standing money alert.

    Review found the original code returning OFF_AS_DECLARED here with a detail
    line asserting "Every host reports offline_by_config" over a host it never
    read — reporting health from a value that was never read, which is the
    failure this script exists to prevent.

    RED IF: ``complete`` stops tracking the unread hosts, or the detail goes back
    to claiming something about a host that did not answer.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config", _HOST_B: None},
        windows=[],
        now=_NOW,
    )
    assert result.decision is posture.PostureDecision.OFF_AS_DECLARED
    assert result.complete is False
    assert "did not answer" in result.detail
    assert "may not close a standing alert" in result.detail


def test_main_publishes_completeness_on_the_wire(
    posture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RED IF: the ``complete=`` write is deleted or renamed — the resolve step
    branches on it, and an absent output would make it permanently unable to
    close a resolved alert (or, if the condition were inverted, able to close one
    it never verified)."""
    code, written = _run_main(
        posture,
        tmp_path,
        monkeypatch,
        body={"live_readiness": {"state": "offline_by_config"}},
        windows_payload={"windows": []},
    )
    assert code == 0
    assert "complete=true" in written


def test_the_workflow_branches_on_the_completeness_key_this_script_writes() -> None:
    """Both sides of the second wire, pinned together.

    RED IF: the key is renamed on either side.
    """
    assert 'write(f"complete=' in SCRIPT.read_text(encoding="utf-8")
    assert "steps.posture.outputs.complete" in WORKFLOW.read_text(encoding="utf-8")


def test_a_non_utc_offset_is_normalised_for_display(posture: ModuleType) -> None:
    """Any offset is accepted, and echoed back in UTC.

    RED IF: the normalisation is removed, so an alert body prints an instant in
    a zone the reader has to convert — the misreading that undermines the "a
    far-future expiry is visible in a diff" argument.
    """
    parsed = posture.parse_windows(
        {
            "windows": [
                {
                    "owner": "rohit",
                    "reason": "y",
                    "mode": "time_boxed",
                    "judge": False,
                    "opened_at": "2026-08-25T00:00:00+05:30",
                    "expires_at": "2026-08-26T00:00:00-12:00",
                    "reaffirm_issue": 105,
                }
            ]
        }
    )
    assert parsed is not None
    assert parsed[0].expires_at.isoformat() == "2026-08-26T12:00:00+00:00"
    assert parsed[0].opened_at.isoformat() == "2026-08-24T18:30:00+00:00"


def test_deploy_md_tells_the_operator_to_declare_the_window() -> None:
    """The runbook is the ONE document that turns this flag on.

    Review found it unchanged: an operator following it would trip the watchdog
    every sanctioned time, which is exactly the crying-wolf failure the
    declaration exists to prevent. The quiet path has to be discoverable from
    where the flag is actually set.

    RED IF: the declaration step is dropped from DEPLOY.md, or the file it names
    is renamed without the runbook following.
    """
    deploy = (REPO_ROOT / "DEPLOY.md").read_text(encoding="utf-8")
    assert "configs/live-execution-windows.json" in deploy
    assert "live-posture-watchdog.yml" in deploy
    # The observability monitor table must list it too, or nothing outside
    # ADR-0070 records that this monitor is supposed to be running.
    observability = (REPO_ROOT / "docs" / "80-observability.md").read_text(encoding="utf-8")
    assert "live-posture-watchdog.yml" in observability


def test_overlapping_windows_report_when_cover_actually_ends(posture: ModuleType) -> None:
    """With two active windows, the remaining time is the LATEST expiry.

    Review measured a 24-hour window reported as "0.1h remaining" because a
    shorter sibling was listed first. The verdict was right; the number an
    operator would plan around was not.

    RED IF: the active window is picked by file order again.
    """
    short = posture.DeclaredWindow(
        owner="a",
        reason="short",
        opened_at=dt.datetime(2026, 8, 25, 11, 0, tzinfo=dt.UTC),
        expires_at=dt.datetime(2026, 8, 25, 12, 6, tzinfo=dt.UTC),
    )
    long = posture.DeclaredWindow(
        owner="b",
        reason="long",
        opened_at=dt.datetime(2026, 8, 25, 11, 0, tzinfo=dt.UTC),
        expires_at=dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC),
    )
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"}, windows=[short, long], now=_NOW
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_DECLARED_WINDOW
    assert "'b'" in result.detail
    assert "24.0h remaining" in result.detail


def test_the_alert_title_names_the_decision_and_asserts_no_posture(
    tmp_path: Path,
) -> None:
    """``unknown`` alerts too, and an unparseable declaration file would file an
    issue every 30 minutes titled "Live execution is on" while the flag was OFF.
    That is the repo's own "never report a value that was never read" rule
    pointed the wrong way, and it is how a real alert learns to be ignored.

    RED IF: the title goes back to asserting a posture the check may not have
    established, or stops naming the decision.
    """
    import subprocess

    log = tmp_path / "gh.log"
    stub = tmp_path / "gh"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\n', encoding="utf-8")
    stub.chmod(0o755)
    step = [s for s in _steps() if "Alert on an undeclared" in str(s.get("name", ""))]
    assert len(step) == 1
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell interpolation of input
        ["/bin/bash", "-c", step[0]["run"]],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "GH_TOKEN": "stub",
            "REPO": "owner/repo",
            "DECISION": "unknown",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    calls = log.read_text(encoding="utf-8")
    title = [line for line in calls.splitlines() if "issue create" in line]
    assert title, calls
    assert "--title Live-execution posture needs attention: unknown" in title[0]
    assert "Live execution is on" not in title[0]


# --- H. RE-AFFIRMATION: the attention clock --------------------------------
#
# THE VACUITY PROBLEM, RESTATED FOR THIS SECTION. Production reports
# `offline_by_config`, so nothing below is reachable from the real world today.
# Every alerting assertion here is therefore driven by a fixture AND paired with
# a partner proving the quiet path is still quiet with the same inputs bar one.


def _comment(
    *,
    hours_ago: float,
    window_opened: str,
    kind: str = "User",
    login: str = "rohit",
    body: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """One GitHub issue comment, in the shape the API returns it."""
    at = (now or _NOW) - dt.timedelta(hours=hours_ago)
    return {
        "user": {"login": login, "type": kind},
        "created_at": at.isoformat(),
        "body": body if body is not None else f"REAFFIRM live-execution {window_opened}",
    }


#: A window opened three days ago and running for seven — #105's shape, and the
#: shape #357 actually ran. It is the SAME window in both directions below; only
#: whether anybody re-affirmed it changes.
_LONG_OPEN = "2026-08-22T12:00:00+00:00"
_LONG_SHUT = "2026-08-29T12:00:00+00:00"


def test_a_window_running_past_the_cadence_with_no_reaffirmation_alerts(
    posture: ModuleType,
) -> None:
    """#357 in one line, and the whole reason a maximum LENGTH was rejected.

    This window has three days to run. Nothing has expired. Under ADR-0070 this
    was silent, which is exactly what three unattended days looked like.

    RED IF: the attention check is removed, so a declaration once opened
    sanctions the posture for as long as its expiry allows with nobody watching.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        reaffirmations={105: []},
    )
    assert result.decision is posture.PostureDecision.LIVE_REAFFIRMATION_LAPSED
    assert result.should_alert is True


def test_the_same_window_reaffirmed_inside_the_cadence_is_quiet(
    posture: ModuleType,
) -> None:
    """POSITIVE PARTNER, and #105's seven days made possible.

    Byte-for-byte the same window as the test above. The ONLY difference is one
    human comment. Without this partner, a check that alerted on every long
    window would satisfy the test above while making the legitimate work
    impossible — which is how an alert gets muted.

    RED IF: a re-affirmation stops resetting the clock, so no long window can
    ever be sanctioned.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        reaffirmations=_reaffirmed(posture, window=window, hours_ago=2, now=_NOW),
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_DECLARED_WINDOW
    assert result.should_alert is False


def test_the_cadence_boundary_is_exact(posture: ModuleType) -> None:
    """Literals on both sides (rule 7a) — never parametrized over the constant.

    Pinning "attended if hours < REAFFIRMATION_CADENCE_HOURS" against the
    constant itself would let the constant be raised from 24 to 240 with this
    test still green. The two instants below are written out, so moving the
    cadence moves this test.

    RED IF: the comparison flips its strictness, or the cadence changes without
    this test and the documents changing with it.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    assert posture.REAFFIRMATION_CADENCE_HOURS == 24.0
    just_inside = _reaffirmed(posture, window=window, hours_ago=23.9, now=_NOW)
    just_outside = _reaffirmed(posture, window=window, hours_ago=24.1, now=_NOW)
    assert window.is_attended(_NOW, just_inside[105]) is True
    assert window.is_attended(_NOW, just_outside[105]) is False


def test_a_window_shorter_than_the_cadence_needs_no_reaffirmation(
    posture: ModuleType,
) -> None:
    """Opening a window IS the first act of attention.

    The common case — a short attended session — must cost nothing extra, or the
    mechanism becomes friction on exactly the work it exists to permit.

    RED IF: the attention clock stops starting at ``opened_at``, so every window
    alerts the moment it is declared.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"}, windows=[window], now=_NOW
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_DECLARED_WINDOW
    assert result.should_alert is False


def test_the_lapse_detail_names_the_hours_the_cadence_and_where_to_re_affirm(
    posture: ModuleType,
) -> None:
    """A gate must report what it counted, and an alert must be actionable.

    Two windows differing in BOTH the elapsed hours and the issue number, so a
    hardcoded detail string fails one of them.

    RED IF: the detail stops interpolating the real numbers, or stops telling
    the reader the exact comment that would resolve it.
    """
    stale = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    one = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[stale],
        now=_NOW,
        reaffirmations={105: []},
    )
    assert "its owner 'rohit' has not re-affirmed it for 72.0h" in one.detail
    assert "24h cadence" in one.detail
    assert "on issue 105" in one.detail
    assert f"{posture.REAFFIRM_TOKEN} {_LONG_OPEN}" in one.detail

    older = _window(posture, opened=_OLD_OPEN, expires=_FUTURE_SHUT, issue=268)
    two = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[older],
        now=_NOW,
        reaffirmations={268: []},
    )
    assert "has not re-affirmed it for 147.0h" in two.detail
    assert "on issue 268" in two.detail


# --- H2. Who may re-affirm. The two fields GitHub sets and the caller cannot.


def test_a_bot_comment_is_not_a_reaffirmation(posture: ModuleType) -> None:
    """THE load-bearing property of this whole mechanism.

    A re-affirmation any automation can supply is theatre. The watchdog itself
    holds ``issues: write`` and a workflow token, so it could comment on its own
    alert — and everything posted with a workflow token is typed ``Bot`` by
    GitHub, which is server-set and not forgeable by the commenter. Measured:
    all 11 machine comments on issue #351 are ``"type": "Bot"``.

    RED IF: the ``Bot`` filter is removed, so this watchdog — or any workflow —
    can re-affirm the very posture it exists to police.
    """
    parsed = posture.parse_reaffirmations(
        [_comment(hours_ago=1, window_opened=_LONG_OPEN, kind="Bot", login="github-actions[bot]")],
        now=_NOW,
    )
    assert parsed == []


def test_a_human_comment_is_a_reaffirmation(posture: ModuleType) -> None:
    """POSITIVE PARTNER for the row above, and it is not optional: a parser that
    returned ``[]`` for everything would satisfy that test while making every
    long window permanently un-affirmable.

    The payload is byte-identical to the bot one bar ``user.type``.

    RED IF: ``parse_reaffirmations`` stops recognising a real re-affirmation.
    """
    parsed = posture.parse_reaffirmations(
        [_comment(hours_ago=1, window_opened=_LONG_OPEN, kind="User", login="rohit")],
        now=_NOW,
    )
    assert len(parsed) == 1
    assert parsed[0].by == "rohit"
    assert parsed[0].at == _NOW - dt.timedelta(hours=1)
    assert parsed[0].window_opened_at == dt.datetime.fromisoformat(_LONG_OPEN)


def test_a_forward_dated_comment_is_not_a_reaffirmation(posture: ModuleType) -> None:
    """The set-and-forget cheat, closed.

    ADR-0070's one acknowledged silencer was a far-future ``expires_at``,
    defended only by "it appears in a diff" — which has no mechanical backing
    here (``required_approving_review_count`` on ``main`` is 0). A
    re-affirmation is a record of a PAST act; a future-dated one is a
    contradiction. GitHub cannot produce one, so its only source is a hand-built
    payload.

    RED IF: the future check is removed, so one comment dated 2099 sanctions the
    posture forever.
    """
    parsed = posture.parse_reaffirmations(
        [_comment(hours_ago=-48, window_opened=_LONG_OPEN)], now=_NOW
    )
    assert parsed == []


def test_a_comment_naming_a_different_window_does_not_reaffirm_this_one(
    posture: ModuleType,
) -> None:
    """One comment attends exactly one window.

    Otherwise a single "still fine" covers every open window at once, which is
    the batch rubber-stamp ADR-0069 rejected in the exclusion ledger.

    RED IF: the token stops carrying the window's own ``opened_at``, or the
    match is dropped.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    parsed = posture.parse_reaffirmations(
        [_comment(hours_ago=1, window_opened=_OLD_OPEN)], now=_NOW
    )
    assert len(parsed) == 1, "the comment itself must still parse — see the partner above"
    assert window.is_attended(_NOW, parsed) is False


@pytest.mark.parametrize(
    "body",
    [
        "looks fine to me",
        "REAFFIRM live-execution",
        "REAFFIRM live-execution not-a-timestamp",
        "REAFFIRM live-execution 2026-08-22T12:00:00",
        "reaffirm live-execution 2026-08-22T12:00:00+00:00",
        "",
    ],
)
def test_a_comment_without_a_usable_token_does_not_reaffirm(posture: ModuleType, body: str) -> None:
    """Each row is a near-miss. The naive-timestamp row matters most: "12:00" in
    whose day? — the same refusal every other instant in this file gets.

    RED IF: the token parser gets lenient, so an ordinary conversational comment
    silently resets a money posture's attention clock.
    """
    parsed = posture.parse_reaffirmations(
        [_comment(hours_ago=1, window_opened=_LONG_OPEN, body=body)], now=_NOW
    )
    assert parsed == []


@pytest.mark.parametrize(
    "payload",
    [
        {"not": "a list"},
        "a string",
        None,
        [{"user": "not an object", "created_at": "2026-08-25T11:00:00+00:00", "body": "x"}],
        [{"user": {"login": "rohit"}, "created_at": "2026-08-25T11:00:00+00:00", "body": "x"}],
        [{"user": {"type": "User"}, "created_at": "2026-08-25T11:00:00+00:00", "body": "x"}],
        [{"user": {"login": "rohit", "type": "User"}, "body": "x"}],
        [{"user": {"login": "rohit", "type": "User"}, "created_at": "2026-08-25T11:00:00+00:00"}],
        ["not an object"],
    ],
)
def test_a_malformed_comment_payload_refuses_to_parse(posture: ModuleType, payload: object) -> None:
    """None means "I could not tell", which the caller turns into an alert —
    never into "nobody has re-affirmed", which would route a broken read through
    the LAPSE branch and look like a real finding.

    RED IF: any validation branch in ``parse_reaffirmations`` is deleted.
    """
    assert posture.parse_reaffirmations(payload, now=_NOW) is None


def test_an_empty_comment_list_parses_as_no_reaffirmations(posture: ModuleType) -> None:
    """POSITIVE PARTNER for the rows above: an issue with no comments yet is a
    legitimate, readable state and must be distinguishable from an unreadable
    one. ``[]`` is not ``None``.

    RED IF: the empty list starts returning None, so every freshly-declared
    window alerts UNKNOWN instead of using its own ``opened_at``.
    """
    assert posture.parse_reaffirmations([], now=_NOW) == []


def test_an_unreadable_reaffirmation_issue_is_unknown_and_alerts(
    posture: ModuleType,
) -> None:
    """A window whose attention cannot be established is not a window known to
    be attended. Same posture every other unreadable input in this file gets.

    RED IF: an unreadable issue is coerced to "no re-affirmations" (which would
    report a LAPSE that was never observed) or to "attended" (which would let a
    GitHub outage sanction an unwatched money posture).
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        reaffirmations={105: None},
    )
    assert result.decision is posture.PostureDecision.UNKNOWN
    assert result.should_alert is True
    assert result.complete is False, "a half-blind cycle must not retire a standing alert"
    assert "105" in result.detail


def test_reaffirmations_are_read_over_a_real_body(posture: ModuleType, tmp_path: Path) -> None:
    """The I/O layer, with a REAL body (rule 8a).

    Two rows, one bot and one human, in ONE payload — so an implementation that
    returned everything, or nothing, fails.

    RED IF: ``fetch_reaffirmations`` stops filtering, or stops parsing.
    """
    url = _ready_stub(
        tmp_path,
        [
            _comment(
                hours_ago=1, window_opened=_LONG_OPEN, kind="Bot", login="github-actions[bot]"
            ),
            _comment(hours_ago=3, window_opened=_LONG_OPEN, kind="User", login="rohit"),
        ],
        name="comments.json",
    )
    parsed = posture.fetch_reaffirmations(url, now=_NOW, attempts=1)
    assert parsed is not None
    assert [entry.by for entry in parsed] == ["rohit"]


def test_an_unreadable_reaffirmation_url_reads_as_none(posture: ModuleType, tmp_path: Path) -> None:
    """RED IF: ``fetch_reaffirmations`` stops catching, so a GitHub outage kills
    the process before ``$GITHUB_OUTPUT`` is written and the job reports
    success."""
    assert (
        posture.fetch_reaffirmations((tmp_path / "nope.json").as_uri(), now=_NOW, attempts=1)
        is None
    )


# --- H3. Nothing automated may supply a re-affirmation ---------------------


def _workflow_texts() -> dict[str, str]:
    directory = REPO_ROOT / ".github" / "workflows"
    # BOTH extensions. GitHub accepts `.yaml` as readily as `.yml`, and a gate
    # that globs only one of them is a gate you rename a file to escape.
    paths = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}
    # Empty-input floor: every assertion below is "no workflow does X", which is
    # trivially true over zero workflows.
    assert len(texts) >= 10, (
        f"only {len(texts)} workflow(s) found — this gate refuses to pass over nothing"
    )
    return texts


def test_no_workflow_that_touches_the_declaration_may_write_the_repository() -> None:
    """The mechanical half of "no automation may re-affirm".

    A re-affirmation lives on a GitHub issue precisely because a committed field
    would be forgeable here — but the DECLARATION itself is still a repository
    file, and a workflow holding ``contents: write`` could rewrite a window's
    ``opened_at`` and reset the attention clock that way. Measured 2026-08-25:
    of 14 workflows exactly one holds ``contents: write``
    (``seed-visual-baselines.yml``) and exactly one names the declaration file
    (the watchdog) — and they are not the same file.

    RED IF: the watchdog is granted ``contents: write``, or any workflow that
    can write the repository starts touching the declaration file.
    """
    texts = _workflow_texts()
    naming = {name: text for name, text in texts.items() if "live-execution-windows" in text}
    # POSITIVE PARTNER and floor: the grep string must actually match something,
    # or "no such workflow can write" is true because no such workflow exists.
    assert naming, "no workflow names the declaration file — this gate is watching nothing"
    # STRUCTURE, NOT SUBSTRING (rule 8). The first version of this gate grepped
    # for the literal "contents: write" and went red the moment the watchdog's
    # own header comment EXPLAINED why that permission is dangerous — a gate
    # tripped by the prose describing it. Parse the permissions instead, at both
    # the workflow and the job level, because either can grant it.
    writers: list[str] = []
    for name in sorted(naming):
        data = yaml.safe_load(texts[name])
        if not isinstance(data, dict):
            continue
        scopes: list[Any] = [data.get("permissions")]
        scopes += [(job or {}).get("permissions") for job in (data.get("jobs") or {}).values()]
        for scope in scopes:
            if scope == "write-all" or (
                isinstance(scope, dict) and scope.get("contents") == "write"
            ):
                writers.append(name)
    assert sorted(set(writers)) == [], (
        f"{sorted(set(writers))} both name configs/live-execution-windows.json and "
        "grant contents: write — a workflow that can rewrite a window's opened_at "
        "can reset the attention clock this mechanism exists to measure."
    )


def posture_token() -> str:
    """The re-affirmation token, READ FROM THE SCRIPT rather than restated here.

    A gate that hardcoded the string would keep passing after a rename while
    searching for something that no longer exists — the "no X found" shape that
    is trivially true over nothing.
    """
    spec = importlib.util.spec_from_file_location("live_posture_token_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    token = str(module.REAFFIRM_TOKEN)
    assert token.strip(), "REAFFIRM_TOKEN is empty — this gate refuses to search for nothing"
    return token


#: Ways a workflow step could POST a comment. The alert step legitimately
#: MENTIONS the re-affirmation token — it tells the operator what to type — so a
#: gate keyed on the token alone would refuse the guidance while permitting the
#: forgery. What must never happen is one step doing BOTH.
_COMMENT_POSTING = ("gh issue comment", "gh pr comment", "/comments")


def _posts_a_reaffirmation(body: str) -> bool:
    return posture_token() in body and any(verb in body for verb in _COMMENT_POSTING)


def test_no_workflow_step_posts_a_reaffirmation() -> None:
    """No automation may supply the human act. Keyed on the STEP, not the file.

    The mechanism's real defence is that GitHub types every workflow-token
    comment ``Bot`` and the parser refuses those — proven by
    ``test_a_bot_comment_is_not_a_reaffirmation``. This is the second layer: an
    intent check, so a step that tried would be caught in review rather than
    relied upon to fail at runtime.

    RED IF: any workflow step both names the token and posts a comment.
    """
    offenders = []
    steps_seen = 0
    for name, text in _workflow_texts().items():
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            continue
        for job in (data.get("jobs") or {}).values():
            for step in (job or {}).get("steps", []) or []:
                body = str(step.get("run", ""))
                if not body:
                    continue
                steps_seen += 1
                if _posts_a_reaffirmation(body):
                    offenders.append(f"{name}:{step.get('name')}")
    # Empty-input floor: "no step does X" is trivially true over zero steps.
    assert steps_seen >= 20, (
        f"only {steps_seen} run-step(s) parsed — this gate refuses to pass over nothing"
    )
    assert offenders == [], f"{offenders} post a re-affirmation from CI"


def test_the_reaffirmation_detector_actually_detects() -> None:
    """POSITIVE PARTNER for the gate above — without it, a detector that
    returned False for everything would pass over a workflow that did exactly
    the forbidden thing.

    Three inputs, three outcomes: the guidance text the alert step really
    contains must NOT trip it, a comment-posting step without the token must NOT
    trip it, and the combination MUST.

    RED IF: ``_posts_a_reaffirmation`` stops discriminating.
    """
    token = posture_token()
    guidance = _condition_free_alert_body()
    assert token in guidance, "the alert step no longer tells the operator how to re-affirm"
    assert _posts_a_reaffirmation(guidance) is False
    assert _posts_a_reaffirmation('gh issue comment 1 -b "all fine"') is False
    assert _posts_a_reaffirmation(f'gh issue comment 1 -b "{token} 2026-08-25T09:00:00+00:00"')


def _condition_free_alert_body() -> str:
    step = [s for s in _steps() if "Alert on an undeclared" in str(s.get("name", ""))]
    assert len(step) == 1
    return str(step[0]["run"])


def test_the_operator_facing_token_is_the_one_the_parser_reads() -> None:
    """The instruction and the parser must not drift.

    The alert body and the declaration file both tell a human what to type; the
    script decides what counts. If those diverge, an operator does the ritual
    and the window lapses anyway.

    RED IF: ``REAFFIRM_TOKEN`` is renamed without the alert body and the
    declaration file following.
    """
    token = posture_token()
    assert token in _condition_free_alert_body()
    assert token in SHIPPED_WINDOWS.read_text(encoding="utf-8")


def test_the_permission_gate_detects_a_real_writer() -> None:
    """POSITIVE PARTNER for the gate above — without it, a permissions parser
    that found nothing would pass over a workflow that really could write.

    Three inputs, three outcomes: the watchdog's own shape (read, must not
    trip), a workflow-level `contents: write` (must trip), and a JOB-level one
    (must trip — either scope can grant it).

    RED IF: the parser stops seeing either scope.
    """

    def grants_write(doc: str) -> bool:
        data = yaml.safe_load(doc)
        scopes: list[Any] = [data.get("permissions")]
        scopes += [(job or {}).get("permissions") for job in (data.get("jobs") or {}).values()]
        return any(isinstance(s, dict) and s.get("contents") == "write" for s in scopes)

    assert grants_write("permissions:\n  contents: write\njobs: {}\n") is True
    assert grants_write("jobs:\n  a:\n    permissions:\n      contents: write\n") is True
    assert grants_write("permissions:\n  contents: read\n  issues: write\njobs: {}\n") is False


def test_the_watchdog_workflow_still_declares_only_the_permissions_it_needs() -> None:
    """``contents: read`` is load-bearing, not incidental: it is what stops this
    watchdog from editing the declaration it polices.

    RED IF: the watchdog's ``contents`` permission is widened.
    """
    permissions = _load_workflow()["permissions"]
    assert permissions["contents"] == "read"
    assert permissions["issues"] == "write"


# --- I. `standing`: the abuse surface -------------------------------------


def _adr_dir(tmp_path: Path, records: dict[str, str]) -> Path:
    directory = tmp_path / "adr"
    directory.mkdir(exist_ok=True)
    for name, text in records.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


_MARKER = "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED"

_AUTHORISING = (
    "# ADR-0099: We are permanently live\n\n## Status\n\nAccepted — 2026-09-01.\n\n"
    "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n"
)


def test_an_accepted_marked_adr_authorises(posture: ModuleType, tmp_path: Path) -> None:
    """POSITIVE PARTNER and empty-input floor for every refusal below.

    Without it, ``authorising_adrs`` returning the empty set for everything
    would satisfy all of them while making ``standing`` unusable.

    RED IF: the marker or the Accepted check stops recognising a valid
    authorisation, so the sanctioned path cannot be taken and the mode gets
    deleted for being unusable.
    """
    found = posture.authorising_adrs(_adr_dir(tmp_path, {"0099-live.md": _AUTHORISING}))
    assert found == frozenset({"ADR-0099"})


@pytest.mark.parametrize(
    ("name", "text"),
    [
        # Proposed, not Accepted — it exists on disk and would pass a
        # file-exists check.
        (
            "0098-proposed.md",
            "# ADR-0098: Proposed\n\n## Status\n\nProposed.\n\n"
            "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n",
        ),
        # Superseded.
        (
            "0097-superseded.md",
            "# ADR-0097: Old\n\n## Status\n\nSuperseded by ADR-0099.\n\n"
            "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n",
        ),
        # Accepted, and it NAMES the flag — but it authorises nothing. Measured:
        # 6 of 68 ADRs name this flag and 2 of them (ADR-0022, ADR-0054)
        # authorise nothing at all, which is why a prose grep is not a
        # discriminator and an explicit marker is required.
        (
            "0096-mentions.md",
            "# ADR-0096: Credential removal\n\n## Status\n\nAccepted.\n\n"
            "We removed a key; OPENROUTER_LIVE_EXECUTION_ENABLED is named here.\n",
        ),
        # The marker, but buried in a sentence rather than on a line of its own.
        (
            "0095-inline.md",
            "# ADR-0095: Chatty\n\n## Status\n\nAccepted.\n\n"
            "Something something **Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED maybe.\n",
        ),
        # No Status section at all.
        (
            "0094-no-status.md",
            "# ADR-0094: Headless\n\n**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n",
        ),
    ],
)
def test_these_adrs_do_not_authorise_a_standing_posture(
    posture: ModuleType, tmp_path: Path, name: str, text: str
) -> None:
    """Each row is a way a citation could look right and mean nothing.

    RED IF: any branch of ``authorising_adrs`` is dropped, so a Proposed draft
    or an ADR that merely mentions the flag can authorise a permanent
    money-spending posture.
    """
    assert posture.authorising_adrs(_adr_dir(tmp_path, {name: text})) == frozenset()


def test_no_adr_in_this_repository_authorises_a_standing_posture_yet(
    posture: ModuleType,
) -> None:
    """The marker must not be satisfiable by an ADR that already exists.

    If any current record carried it, the first ``standing`` window could cite a
    document written for another purpose and the citation would carry no
    information. This is a negative check, so it ships with two partners: the
    directory is non-empty, and the same function DOES find a marked record in
    the fixture test above.

    RED IF: an ADR gains the marker without somebody deciding to go permanently
    live — or the marker string drifts, which would make this pass over nothing.
    """
    adr_dir = REPO_ROOT / "docs" / "adr"
    records = sorted(adr_dir.glob("[0-9]*.md"))
    assert len(records) >= 40, (
        f"only {len(records)} ADR(s) found — this gate refuses to pass over nothing"
    )
    assert posture.authorising_adrs(adr_dir) == frozenset()


def test_a_standing_window_needs_a_citation_that_resolves(
    posture: ModuleType,
) -> None:
    """The declaration side of the same property.

    RED IF: ``parse_windows`` stops comparing the citation against the resolved
    set, so ``"adr": "ADR-9999"`` sanctions a permanent posture.
    """
    entry = {
        "owner": "rohit",
        "reason": "GA",
        "mode": "standing",
        "judge": True,
        "opened_at": _NOW_OPEN,
        "adr": "ADR-0099",
        "reaffirm_issue": 400,
    }
    assert posture.parse_windows({"windows": [entry]}, authorised_adrs=frozenset()) is None
    parsed = posture.parse_windows({"windows": [entry]}, authorised_adrs=frozenset({"ADR-0099"}))
    assert parsed is not None and parsed[0].is_standing and parsed[0].adr == "ADR-0099"


@pytest.mark.parametrize("adr", sorted({"ADR-0070", "ADR-0071"}))
def test_the_mechanisms_own_records_cannot_authorise_it(posture: ModuleType, adr: str) -> None:
    """A mechanism may not authorise its own use.

    Without this the first standing window would cite the ADR that INVENTED
    standing mode, and the citation would say nothing at all. Requiring a
    different, future record is the point: going permanently live costs the
    document that says so.

    RED IF: ``MECHANISM_OWN_ADRS`` is emptied or the check is dropped.
    """
    entry = {
        "owner": "rohit",
        "reason": "GA",
        "mode": "standing",
        "judge": True,
        "opened_at": _NOW_OPEN,
        "adr": adr,
        "reaffirm_issue": 400,
    }
    # Even when the citation IS in the authorised set, it is refused.
    assert posture.parse_windows({"windows": [entry]}, authorised_adrs=frozenset({adr})) is None


def test_a_standing_window_is_quiet_but_reports_itself_every_cycle(
    posture: ModuleType,
) -> None:
    """A standing posture that produced SILENCE would be indistinguishable from
    a dead watchdog, so ``standing`` gets its own decision value and a detail
    line naming the ADR, the age and the last re-affirmation.

    RED IF: a standing window collapses into ``LIVE_WITHIN_DECLARED_WINDOW`` or
    into ``OFF_AS_DECLARED``, so the job log stops saying a permanent
    money-spending posture is in force.
    """
    window = _standing(posture, opened=_LONG_OPEN, adr="ADR-0099", issue=400)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        reaffirmations=_reaffirmed(posture, window=window, hours_ago=3, now=_NOW),
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_STANDING_DECLARATION
    assert result.should_alert is False
    assert "STANDING declaration" in result.detail
    assert "ADR-0099" in result.detail
    assert "standing for 72.0h" in result.detail
    assert "last re-affirmed 3.0h ago" in result.detail


def test_a_standing_window_still_lapses_without_reaffirmation(
    posture: ModuleType,
) -> None:
    """THE anti-abuse property, and the reason ``standing`` is not a silencer.

    ``standing`` removes the DEADLINE. It does not remove the ATTENTION. So
    reaching for it to quiet a noisy alert buys 24 hours and no more — which is
    what stops the self-defeating gradient where the cheapest way to stop an
    alarm at 03:00 is to make it permanent.

    RED IF: ``standing`` is exempted from the attention check, at which point it
    becomes exactly the permanent-silence mechanism ADR-0069 rejected.
    """
    window = _standing(posture, opened=_LONG_OPEN, adr="ADR-0099", issue=400)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        reaffirmations={400: []},
    )
    assert result.decision is posture.PostureDecision.LIVE_REAFFIRMATION_LAPSED
    assert result.should_alert is True


def test_a_standing_window_covers_the_far_future(posture: ModuleType) -> None:
    """It has no expiry — that is what the mode MEANS.

    RED IF: ``covers`` starts bounding a standing window, which would make the
    mode indistinguishable from a time-boxed one and quietly break GA.
    """
    window = _standing(posture, opened=_NOW_OPEN)
    assert window.expires_at is None
    assert window.covers(dt.datetime(2099, 1, 1, tzinfo=dt.UTC)) is True
    # ...but it still does not cover the past, before it was opened.
    assert window.covers(dt.datetime(2026, 8, 25, 8, 59, 59, tzinfo=dt.UTC)) is False


def test_a_standing_window_governs_over_a_time_boxed_sibling(
    posture: ModuleType,
) -> None:
    """With both active, the reported window is the one whose cover ends LAST —
    and a standing declaration never ends.

    RED IF: the governing window is picked by file order again, so an operator
    reads "0.1h remaining" while a permanent declaration is in force.
    """
    short = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    standing = _standing(posture, opened=_NOW_OPEN, adr="ADR-0099")
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"}, windows=[short, standing], now=_NOW
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_STANDING_DECLARATION


# --- J. THE JUDGE: the second paid subsystem ------------------------------


def test_the_judge_running_outside_the_declaration_alerts(posture: ModuleType) -> None:
    """The cell ADR-0070's design got wrong, and the one that actually spends.

    A declared, attended live window plus ``judge_enabled: true`` plus a window
    that says ``judge: false``. The judge's GET-path spend reaches no ledger
    (ADR-0013), so ``global_daily_spend_usd`` under-reports by exactly its cost
    precisely while this stands.

    RED IF: the judge comparison is removed, so a live window silently sanctions
    a second paid subsystem nobody declared.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, judge=False)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        judge_states={_HOST_B: True},
    )
    assert result.decision is posture.PostureDecision.LIVE_JUDGE_UNDECLARED
    assert result.should_alert is True
    assert "no ledger" in result.detail


def test_the_same_posture_with_the_judge_declared_is_quiet(posture: ModuleType) -> None:
    """POSITIVE PARTNER: the same inputs bar one boolean.

    Without it, a check that alerted whenever the judge was on would satisfy the
    test above while making every sanctioned judge-bearing window fire — the
    crying-wolf failure the declaration exists to prevent.

    RED IF: declaring the judge stops sanctioning it.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, judge=True)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        judge_states={_HOST_B: True},
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_DECLARED_WINDOW
    assert result.should_alert is False
    assert "judge declared=true" in result.detail


def test_the_judge_on_while_live_is_off_is_reported_and_not_alerted(
    posture: ModuleType,
) -> None:
    """TODAY'S PRODUCTION, exactly: ``live_execution: false``, ``judge_enabled:
    true`` (measured by ``curl`` on 2026-08-25, build 57be5a8).

    The judge cannot spend here — the run-path gate needs a COMPLETED answer on
    an invoked provider path and live-off produces none — so alerting would be
    crying wolf. But ``/status.judge_enabled: true`` READS like activity, so the
    operator is told.

    RED IF: this starts alerting (the watchdog goes permanently red on today's
    production and gets muted), or stops reporting (the operator loses the one
    signal that a second paid subsystem is armed).
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"},
        windows=[],
        now=_NOW,
        judge_states={_HOST_B: True},
    )
    assert result.decision is posture.PostureDecision.OFF_AS_DECLARED
    assert result.should_alert is False
    assert "judge_enabled=true" in result.detail
    assert "cannot spend while live execution is off" in result.detail


def test_an_unreadable_judge_state_while_live_is_unknown_and_alerts(
    posture: ModuleType,
) -> None:
    """While live execution is ON the judge CAN spend, so "I could not tell" is
    not a clean bill of health.

    RED IF: an unreadable judge state defaults to False, which would be a claim
    that a second paid subsystem is off made from a value that was never read.
    """
    window = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[window],
        now=_NOW,
        judge_states={_HOST_B: None},
    )
    assert result.decision is posture.PostureDecision.UNKNOWN
    assert result.should_alert is True
    assert result.complete is False


def test_an_unreadable_judge_state_while_off_stays_quiet(posture: ModuleType) -> None:
    """PARTNER, and the proof that this revision adds NO new alerting path to
    today's production posture.

    With live execution off the judge is inert, so an unreadable ``/status`` must
    not wake anybody. If this went the other way, a ``/status`` blip would open a
    money alert on a system that cannot spend — and that is how an alert gets
    muted before it ever fires for a real reason.

    RED IF: the judge read becomes load-bearing while the flag is off.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"},
        windows=[],
        now=_NOW,
        judge_states={_HOST_B: None},
    )
    assert result.decision is posture.PostureDecision.OFF_AS_DECLARED
    assert result.should_alert is False
    # ...but it still may not RETIRE a standing alert on a partial view.
    assert result.complete is False
    assert "unreadable" in result.detail


@pytest.mark.parametrize(
    ("live", "judge", "declared_judge", "expected", "alerts"),
    [
        # The four-way matrix, plus the undeclared row. `declared_judge` is None
        # where no window is declared at all.
        ("offline_by_config", False, None, "OFF_AS_DECLARED", False),
        ("offline_by_config", True, None, "OFF_AS_DECLARED", False),
        ("live", False, False, "LIVE_WITHIN_DECLARED_WINDOW", False),
        ("live", True, False, "LIVE_JUDGE_UNDECLARED", True),
        ("live", True, True, "LIVE_WITHIN_DECLARED_WINDOW", False),
        ("live", False, True, "LIVE_WITHIN_DECLARED_WINDOW", False),
        ("live", True, None, "LIVE_UNDECLARED", True),
        ("live", False, None, "LIVE_UNDECLARED", True),
    ],
)
def test_the_live_by_judge_matrix(
    posture: ModuleType,
    live: str,
    judge: bool,
    declared_judge: bool | None,
    expected: str,
    alerts: bool,
) -> None:
    """Every cell of {live on/off} x {judge on/off} x {declared/not}, pinned.

    Eight rows with six distinct outcomes: no implementation that ignores one of
    the three inputs passes them all. The row that matters is
    ``("live", True, False)`` — quiet under ADR-0070, alerting now.

    RED IF: any cell's verdict changes without this table changing with it.
    """
    windows = (
        []
        if declared_judge is None
        else [_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, judge=declared_judge)]
    )
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: live},
        windows=windows,
        now=_NOW,
        judge_states={_HOST_B: judge},
    )
    assert result.decision is getattr(posture.PostureDecision, expected)
    assert result.should_alert is alerts


def test_a_status_body_reporting_the_judge_on_is_read(posture: ModuleType, tmp_path: Path) -> None:
    """RED IF: ``fetch_judge_enabled`` stops reading the field, or hardcodes it."""
    url = _ready_stub(tmp_path, {"app": "Quorum-AI", "judge_enabled": True}, name="j-on.json")
    assert posture.fetch_judge_enabled(url, attempts=1) is True


def test_a_status_body_reporting_the_judge_off_is_read(posture: ModuleType, tmp_path: Path) -> None:
    """PARTNER to the row above: two distinct values, both asserted, so an
    implementation returning a constant fails one.

    RED IF: the parser returns a constant.
    """
    url = _ready_stub(tmp_path, {"app": "Quorum-AI", "judge_enabled": False}, name="j-off.json")
    assert posture.fetch_judge_enabled(url, attempts=1) is False


@pytest.mark.parametrize(
    "payload",
    [
        '{"app":"Quorum-AI"}',
        '{"app":"Quorum-AI","judge_enabled":"true"}',
        '{"app":"Quorum-AI","judge_enabled":1}',
        '{"app":"Quorum-AI","judge_enabled":null}',
        "[]",
        "null",
        "not json at all",
    ],
)
def test_an_unusable_status_body_reads_as_none(
    posture: ModuleType, tmp_path: Path, payload: str
) -> None:
    """None means "unknown". The ``"true"`` and ``1`` rows are the dangerous
    ones: a truthiness check would read both as "the judge is on" and a
    ``.get("judge_enabled", False)`` default would turn the first row into a
    permanent, silent all-clear on a second paid subsystem.

    RED IF: any guard in ``fetch_judge_enabled`` is removed, or the missing key
    acquires a False default.
    """
    url = _ready_stub(tmp_path, payload, name=f"st{abs(hash(payload))}.json")
    assert posture.fetch_judge_enabled(url, attempts=1) is None


def test_the_judge_note_never_reports_a_value_it_did_not_read(
    posture: ModuleType,
) -> None:
    """Three distinct inputs, three distinct sentences.

    RED IF: the note hardcodes a state, or claims one over hosts it never read.
    """
    on = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"},
        windows=[],
        now=_NOW,
        judge_states={_HOST_A: True, _HOST_B: True},
    )
    off = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"},
        windows=[],
        now=_NOW,
        judge_states={_HOST_A: False, _HOST_B: False},
    )
    none = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config"},
        windows=[],
        now=_NOW,
        judge_states={},
    )
    assert "judge_enabled=true (read 2 of 2 /status host(s))" in on.detail
    assert "judge_enabled=false (read 2 of 2 /status host(s))" in off.detail
    assert "judge_enabled was not probed." in none.detail


# --- K. The ADR-0070 truth table, pinned so it cannot silently regress -----


@pytest.mark.parametrize(
    ("label", "state", "windows_kind", "hosts", "expected", "alerts", "complete"),
    [
        ("live | none", "live", "none", 1, "LIVE_UNDECLARED", True, True),
        ("off | none", "offline_by_config", "none", 1, "OFF_AS_DECLARED", False, True),
        ("live | inside", "live", "open", 1, "LIVE_WITHIN_DECLARED_WINDOW", False, True),
        ("live | expired", "live", "expired", 1, "LIVE_PAST_DECLARED_WINDOW", True, True),
        ("off | window open", "offline_by_config", "open", 1, "OFF_AS_DECLARED", False, True),
        ("live | unparseable", "live", "unparseable", 1, "UNKNOWN", True, True),
        ("off | unparseable", "offline_by_config", "unparseable", 1, "UNKNOWN", True, True),
        ("off | one host unread", "offline_by_config", "none", 2, "OFF_AS_DECLARED", False, False),
    ],
)
def test_the_adr_0070_truth_table_still_holds(
    posture: ModuleType,
    label: str,
    state: str,
    windows_kind: str,
    hosts: int,
    expected: str,
    alerts: bool,
    complete: bool,
) -> None:
    """The eight rows ADR-0070 shipped, pinned as a regression gate.

    They were verified by hand on #367 and lived only in that ADR's prose, so
    nothing would have gone red if ADR-0071's rework had changed one. Eight rows
    with four distinct decisions and both values of ``complete``, so no
    implementation ignoring its inputs passes them all.

    RED IF: any of ADR-0070's eight documented outcomes changes.
    """
    windows = {
        "none": [],
        "open": [_window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)],
        "expired": [_window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)],
        "unparseable": None,
    }[windows_kind]
    states: dict[str, str | None] = {_HOST_A: state}
    if hosts == 2:
        states[_HOST_B] = None
    result = posture.evaluate_posture(
        readiness_states=states, windows=windows, now=_NOW, judge_states={_HOST_A: False}
    )
    assert result.decision is getattr(posture.PostureDecision, expected), label
    assert result.should_alert is alerts, label
    assert result.complete is complete, label


# --- L. What adversarial review broke, and what now stops it ---------------
#
# Every test below exists because a reviewer DEMONSTRATED the failure it pins.
# Three of them (L-cadence, L-token, L-wire) are mutants that survived the suite
# as first written: the checks they describe did not exist until a mutation said
# so, which is the whole argument for the mutation step.


def test_the_cadence_boundary_is_exact_at_the_instant_itself(
    posture: ModuleType,
) -> None:
    """SURVIVED MUTATION: `is_attended`'s `<` flipped to `<=` and the suite stayed
    green (204 passed), while `test_the_cadence_boundary_is_exact`'s own docstring
    claimed "RED IF: the comparison flips its strictness". It tested 23.9h and
    24.1h and never the boundary itself.

    RED IF: `<` becomes `<=`, i.e. a window is treated as attended at the exact
    instant its cadence runs out.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    exactly = _reaffirmed(posture, window=window, hours_ago=24.0, now=_NOW)
    a_hair_inside = _reaffirmed(posture, window=window, hours_ago=23.999, now=_NOW)
    assert window.is_attended(_NOW, exactly[105]) is False
    assert window.is_attended(_NOW, a_hair_inside[105]) is True


@pytest.mark.parametrize(
    "prefix",
    ["", "`", "> ", "- ", "* ", "  ", "• ", "#"],
)
def test_ordinary_markdown_in_front_of_the_token_still_re_affirms(
    posture: ModuleType, prefix: str
) -> None:
    """The alert body renders the instruction in BACKTICKS. A person who copies it
    verbatim, quotes the alert with "> ", or bullets it would otherwise fail to
    re-affirm while believing they had — and the alert would keep firing with no
    explanation, which is exactly how an alarm gets ignored.

    RED IF: the leading-markup strip is removed.
    """
    parsed = posture.parse_reaffirmations(
        [
            _comment(
                hours_ago=1,
                window_opened=_LONG_OPEN,
                body=f"{prefix}REAFFIRM live-execution {_LONG_OPEN}",
            )
        ],
        now=_NOW,
    )
    assert parsed is not None and len(parsed) == 1, prefix


def test_the_token_must_START_the_line(posture: ModuleType) -> None:
    """SURVIVED MUTATION: `startswith(REAFFIRM_TOKEN)` relaxed to
    `REAFFIRM_TOKEN in stripped` and the suite stayed green.

    The negated sentence is the point. Somebody writing "I have NOT re-affirmed
    this" and quoting the token must not thereby re-affirm it — the same shape as
    the merge-body close-keyword trap this repository has been bitten by four
    times.

    RED IF: the match is loosened to a substring search.
    """
    parsed = posture.parse_reaffirmations(
        [
            _comment(
                hours_ago=1,
                window_opened=_LONG_OPEN,
                body=f"I am NOT re-affirming: REAFFIRM live-execution {_LONG_OPEN}",
            )
        ],
        now=_NOW,
    )
    assert parsed == []


def test_main_reads_re_affirmations_and_they_change_the_verdict(
    posture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE WIRE. SURVIVED MUTATION: `if live_now and windows:` in `main` neutered
    to `if False and ...` and the suite stayed green (204 passed) while the
    verdict flipped from quiet to a money alert. The whole attention feature could
    be severed at the fetch and nothing went red.

    RED IF: `main` stops fetching re-affirmations, or stops passing them to
    `evaluate_posture`.
    """
    opened = (dt.datetime.now(dt.UTC) - dt.timedelta(days=3)).isoformat()
    expires = (dt.datetime.now(dt.UTC) + dt.timedelta(days=4)).isoformat()
    window = {
        "owner": "rohit",
        "reason": "collect #105 production logs",
        "mode": "time_boxed",
        "judge": False,
        "opened_at": opened,
        "expires_at": expires,
        "reaffirm_issue": 105,
    }
    fresh = {
        "user": {"login": "rohit", "type": "User"},
        "created_at": (dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)).isoformat(),
        "body": f"REAFFIRM live-execution {opened}",
    }
    code, written = _run_main(
        posture,
        tmp_path,
        monkeypatch,
        body={"live_readiness": {"state": "live"}},
        windows_payload={"windows": [window]},
        comments=[fresh],
    )
    assert code == 0, written
    assert "decision=live_within_declared_window" in written


def test_main_without_that_re_affirmation_opens_a_money_alert(
    posture: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POSITIVE PARTNER for the wire test: the SAME window, the SAME everything,
    an empty comment list. Without this pair, a `main` that ignored the fetch
    entirely would satisfy one of the two.

    RED IF: the attention verdict stops depending on what was fetched.
    """
    opened = (dt.datetime.now(dt.UTC) - dt.timedelta(days=3)).isoformat()
    expires = (dt.datetime.now(dt.UTC) + dt.timedelta(days=4)).isoformat()
    window = {
        "owner": "rohit",
        "reason": "collect #105 production logs",
        "mode": "time_boxed",
        "judge": False,
        "opened_at": opened,
        "expires_at": expires,
        "reaffirm_issue": 105,
    }
    code, written = _run_main(
        posture,
        tmp_path,
        monkeypatch,
        body={"live_readiness": {"state": "live"}},
        windows_payload={"windows": [window]},
        comments=[],
    )
    assert code == 1, written
    assert "decision=live_reaffirmation_lapsed" in written


# --- L2. Who may re-affirm: the owner, and no GitHub App -------------------


def test_only_the_windows_declared_owner_may_re_affirm(posture: ModuleType) -> None:
    """A public repository's issues can be commented on by anyone with an account.

    Without an owner match, "a human re-affirmed it" means "some account in the
    world said something", which is not a control over a money posture.

    RED IF: the owner comparison is dropped from `attended_since`.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, owner="rohit", issue=105)
    stranger = posture.parse_reaffirmations(
        [_comment(hours_ago=1, window_opened=_LONG_OPEN, login="passer-by")], now=_NOW
    )
    assert stranger is not None and len(stranger) == 1, "the comment itself must parse"
    assert window.is_attended(_NOW, stranger) is False


def test_the_declared_owner_may_re_affirm(posture: ModuleType) -> None:
    """POSITIVE PARTNER: byte-identical to the row above bar the login. Without
    it, an owner check that matched nobody would satisfy that test while making
    every long window un-affirmable.

    RED IF: the owner comparison stops matching the declared owner — including
    for an ordinary "@rohit" or a differently-cased login.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, owner="rohit", issue=105)
    for login in ("rohit", "Rohit", "ROHIT"):
        entries = posture.parse_reaffirmations(
            [_comment(hours_ago=1, window_opened=_LONG_OPEN, login=login)], now=_NOW
        )
        assert entries is not None
        assert window.is_attended(_NOW, entries) is True, login


def test_a_comment_posted_through_a_github_app_is_not_a_re_affirmation(
    posture: ModuleType,
) -> None:
    """`user.type` is the type of the ACCOUNT, not of the actor — so it does not
    catch an App acting under a human-looking identity.

    Measured on this repository's own alert issue: a workflow-token comment
    carries the whole GitHub Actions app object in `performed_via_github_app`
    (`"slug": "github-actions"`). Refusing any non-null value closes every App,
    including one installed with `issues: write` under any name.

    RED IF: the `performed_via_github_app` refusal is removed.
    """
    parsed = posture.parse_reaffirmations(
        [
            _comment(
                hours_ago=1,
                window_opened=_LONG_OPEN,
                login="rohit",
                kind="User",
            )
            | {"performed_via_github_app": {"slug": "some-app"}}
        ],
        now=_NOW,
    )
    assert parsed == []


@pytest.mark.parametrize("kind", ["Bot", "bot", "BOT", "bOt"])
def test_the_bot_refusal_is_case_folded(posture: ModuleType, kind: str) -> None:
    """An exact-case compare let `"bot"` and `"BOT"` through — demonstrated by
    review. The cost of being wrong here is a machine holding a money posture
    open, so the compare is case-folded.

    RED IF: the comparison goes back to `kind == "Bot"`.
    """
    parsed = posture.parse_reaffirmations(
        [_comment(hours_ago=1, window_opened=_LONG_OPEN, kind=kind, login="rohit")],
        now=_NOW,
    )
    assert parsed == []


# --- L3. The governing window decides. A decoy cannot hide it -------------


def test_a_short_fresh_window_cannot_hide_a_long_stale_one(
    posture: ModuleType,
) -> None:
    """DEMONSTRATED EVASION. A five-minute smoke-test window, freshly opened,
    silenced a window running to 2099 that nobody had attended for eight days —
    and the operator-facing detail named only the decoy, reporting "2.0h
    remaining".

    The longest cover is what actually grants the exposure, so it is what must be
    attended.

    RED IF: attention is decided by `any()` over covering windows again.
    """
    decoy = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, owner="bob")
    long_stale = _window(posture, opened=_OLD_OPEN, expires=_FUTURE_SHUT, owner="rohit", issue=105)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[decoy, long_stale],
        now=_NOW,
        reaffirmations={105: []},
    )
    assert result.decision is posture.PostureDecision.LIVE_REAFFIRMATION_LAPSED
    assert result.should_alert is True
    # ...and the detail must name the window that actually governs, not the decoy.
    assert "'rohit'" in result.detail


def test_any_covering_window_may_declare_the_judge(posture: ModuleType) -> None:
    """The judge question is EXISTENTIAL, and getting this wrong cost two rounds.

    Round 1: `any()` over covering windows — a decoy could satisfy it.
    Round 2: narrowed to the governing window — which then ALERTED while a
    covering window DID declare the judge, a manufactured false red one check
    away from the defect the narrowing was meant to fix.

    The resolution is that the two questions have different shapes. "Is anybody
    still watching?" is universal — EVERY covering window must be attended, so
    no decoy helps. "Did somebody declare the judge?" is existential: a window
    saying `"judge": true` IS the record, written by a named owner in a
    reviewable commit, and that is the whole point of the field.

    RED IF: the judge check narrows to one window again.
    """
    short = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, owner="bob", judge=True)
    long_no_judge = _window(
        posture, opened=_NOW_OPEN, expires=_FUTURE_SHUT, owner="rohit", judge=False, issue=105
    )
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[short, long_no_judge],
        now=_NOW,
        judge_states={_HOST_B: True},
        reaffirmations=_reaffirmed(posture, window=long_no_judge, hours_ago=1, now=_NOW),
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_DECLARED_WINDOW
    assert result.should_alert is False


def test_no_covering_window_declaring_the_judge_alerts(posture: ModuleType) -> None:
    """POSITIVE PARTNER: flip the ONE boolean and it must alert.

    RED IF: the judge comparison stops depending on the declarations at all.
    """
    short = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, owner="bob", judge=False)
    long_no_judge = _window(
        posture, opened=_NOW_OPEN, expires=_FUTURE_SHUT, owner="rohit", judge=False, issue=105
    )
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[short, long_no_judge],
        now=_NOW,
        judge_states={_HOST_B: True},
        reaffirmations=_reaffirmed(posture, window=long_no_judge, hours_ago=1, now=_NOW),
    )
    assert result.decision is posture.PostureDecision.LIVE_JUDGE_UNDECLARED
    assert result.should_alert is True


def test_a_secondary_windows_unreadable_issue_does_not_fire_an_alert(
    posture: ModuleType,
) -> None:
    """PARTNER to the two above, and the reason the governing rule is not simply
    "fail closed on everything".

    An earlier draft checked EVERY covering window's issue before deciding, so a
    GitHub blip on a secondary window's issue opened a money alert on a posture
    the governing window fully sanctioned — manufacturing exactly the false red
    this file's prose says gets muted.

    RED IF: the unreadable-issue check widens back to every covering window.
    """
    governing = _window(posture, opened=_NOW_OPEN, expires=_FUTURE_SHUT, owner="rohit", issue=105)
    secondary = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT, owner="bob", issue=111)
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[governing, secondary],
        now=_NOW,
        reaffirmations={
            111: None,
            **_reaffirmed(posture, window=governing, hours_ago=1, now=_NOW),
        },
    )
    assert result.decision is posture.PostureDecision.LIVE_WITHIN_DECLARED_WINDOW
    assert result.should_alert is False


def test_an_undeclared_live_posture_is_not_masked_by_an_unreadable_judge(
    posture: ModuleType,
) -> None:
    """The judge read used to sit ABOVE the covering-window check, so an
    unreadable `/status` turned a genuine `live_undeclared` into `unknown` — and
    the alert body then told the operator "the check could not establish the
    posture" when it had established it perfectly well and real money was
    spendable.

    RED IF: the judge-readability gate moves back above the window check.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "live"},
        windows=[],
        now=_NOW,
        judge_states={_HOST_B: None},
    )
    assert result.decision is posture.PostureDecision.LIVE_UNDECLARED
    assert result.should_alert is True


# --- L4. Reading the declaration and the ADRs -----------------------------


def test_a_duplicate_key_makes_the_declaration_untrusted(
    posture: ModuleType, tmp_path: Path
) -> None:
    """DEMONSTRATED EVASION. `json.loads` silently keeps the LAST duplicate, so a
    declaration reading `"judge": false, ... "judge": true` shows a reviewer one
    value and hands the parser the other — defeating every field-level control
    without breaking any of them.

    RED IF: the `object_pairs_hook` is removed.
    """
    path = tmp_path / "dup.json"
    path.write_text(
        '{"windows":[{"owner":"ops","reason":"r","mode":"time_boxed",'
        '"judge": false,"opened_at":"2026-08-25T09:00:00Z",'
        '"expires_at":"2026-08-25T17:00:00Z","judge": true}]}',
        encoding="utf-8",
    )
    assert posture.load_windows(path, adr_dir=tmp_path) is None


def test_the_same_declaration_without_the_duplicate_loads(
    posture: ModuleType, tmp_path: Path
) -> None:
    """POSITIVE PARTNER: without it, a loader that refused every file would
    satisfy the row above.

    RED IF: `load_windows` starts rejecting a well-formed declaration.
    """
    path = tmp_path / "ok.json"
    path.write_text(
        '{"windows":[{"owner":"ops","reason":"r","mode":"time_boxed",'
        '"opened_at":"2026-08-25T09:00:00Z",'
        '"expires_at":"2026-08-25T17:00:00Z","judge": true}]}',
        encoding="utf-8",
    )
    parsed = posture.load_windows(path, adr_dir=tmp_path)
    assert parsed is not None and len(parsed) == 1 and parsed[0].judge is True


@pytest.mark.parametrize(
    ("name", "text", "why"),
    [
        (
            "0095-reverted.md",
            "# ADR-0095: Turned on, then off\n\n## Status\n\nAccepted — 2026-08-19. "
            "**Reverted — 2026-08-22.**\n\n**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n",
            "a REVERTED ADR — this repo's own ADR-0060 has exactly this status shape",
        ),
        (
            "0094-fenced.md",
            "# ADR-0094: Quoting the marker\n\n## Status\n\nAccepted.\n\n"
            "This ADR authorises nothing; it merely quotes the required line:\n\n"
            "```\n**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n```\n",
            "the marker inside a fenced block — how a document QUOTES it",
        ),
        (
            "0093-html-comment.md",
            "# ADR-0093: Invisible\n\n## Status\n\nAccepted.\n\n"
            "<!--\n**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n-->\n",
            "the marker in an HTML comment — invisible in rendered Markdown",
        ),
        (
            "0092-acceptedish.md",
            "# ADR-0092: Not really\n\n## Status\n\n"
            "Accepted-in-principle-pending-security-review (NOT accepted).\n\n"
            "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n",
            "'Accepted' as a prefix of a word meaning the opposite",
        ),
        (
            "0090-acceptedish.md",
            "# ADR-0090: Almost\n\n## Status\n\nAcceptedish.\n\n"
            "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n",
            "'Acceptedish' — caught ONLY by the word-boundary rule, since it "
            "carries none of the revoked markers. Without this row, deleting the "
            "boundary check leaves the whole suite green",
        ),
        (
            "0091-later-superseded.md",
            "# ADR-0091: Overtaken\n\n## Status\n\n"
            "Accepted 2026-01-01, Superseded by ADR-0100 — DO NOT RELY ON THIS.\n\n"
            "**Authorises:** OPENROUTER_LIVE_EXECUTION_ENABLED\n",
            "superseded in its own status line, after the word Accepted",
        ),
    ],
)
def test_these_documents_do_not_authorise_a_standing_posture(
    posture: ModuleType, tmp_path: Path, name: str, text: str, why: str
) -> None:
    """DEMONSTRATED EVASIONS — every row here authorised a permanent
    money-spending posture before review.

    The first is the sharpest: this repository writes `## Status` as
    "Accepted — <date>. <later history>", so `startswith("Accepted")` is not a
    status check at all, and ADR-0060 — the record that CAUSED #357 — passed it.

    RED IF: any of the revoked-status markers, the fenced-block strip or the
    HTML-comment strip is removed.
    """
    assert posture.authorising_adrs(_adr_dir(tmp_path, {name: text})) == frozenset(), why


def test_a_window_that_can_outlive_the_cadence_must_name_an_issue(
    posture: ModuleType,
) -> None:
    """Otherwise a long window has no re-affirmation channel at all: it lapses
    after a day and the ONLY way to clear the alert is to edit the declaration,
    which is the commit path this design deliberately does not want to depend on.

    NOT a maximum window length — any length is allowed, it just has to say where
    it will be re-affirmed once it outlives a day.

    RED IF: the requirement is dropped.
    """
    long_no_issue = {
        "owner": "rohit",
        "reason": "a week of logs",
        "mode": "time_boxed",
        "judge": False,
        "opened_at": "2026-08-22T12:00:00Z",
        "expires_at": "2026-08-29T12:00:00Z",
    }
    assert posture.parse_windows({"windows": [long_no_issue]}) is None
    # POSITIVE PARTNER 1: the same window WITH an issue parses.
    assert posture.parse_windows({"windows": [long_no_issue | {"reaffirm_issue": 105}]}) is not None
    # POSITIVE PARTNER 2: a SHORT window still needs nothing, or the common case
    # acquires friction it does not need.
    short = long_no_issue | {"expires_at": "2026-08-22T20:00:00Z"}
    assert posture.parse_windows({"windows": [short]}) is not None


def test_the_comment_read_is_bounded_to_the_attention_window(
    posture: ModuleType,
) -> None:
    """MEASURED against the real API: the issue-comments endpoint returns
    OLDEST-FIRST and ignores `direction=desc`, so a page-1-only read on a thread
    past 100 comments would never see the newest re-affirmation — a permanent
    false alert no human action could clear.

    `since` DOES work (11 comments -> 5 with a mid-thread cutoff), and bounding
    the read to the cadence makes pagination irrelevant.

    RED IF: `since` is dropped from the URL, or stops tracking the clock.
    """
    window = _window(posture, opened=_LONG_OPEN, expires=_LONG_SHUT, issue=105)
    urls = posture._reaffirmation_urls(
        [window],
        template=posture.DEFAULT_REAFFIRMATION_URL_TEMPLATE,
        repo="owner/repo",
        since=dt.datetime(2026, 8, 24, 12, 0, tzinfo=dt.UTC),
    )
    assert urls[105].endswith("since=2026-08-24T12:00:00Z")
    assert "/issues/105/comments" in urls[105]


def test_the_partial_sentence_counts_every_endpoint_it_probed(
    posture: ModuleType,
) -> None:
    """`complete` was widened to include `/status`, but the sentence explaining it
    counted only `/ready` — so today's most likely flake (both `/ready` answer,
    one `/status` does not) printed "0 host(s) did not answer" directly above a
    claim that the view was partial.

    RED IF: the count stops covering both maps.
    """
    result = posture.evaluate_posture(
        readiness_states={_HOST_A: "offline_by_config", _HOST_B: "offline_by_config"},
        windows=[],
        now=_NOW,
        judge_states={_HOST_A: True, _HOST_B: None},
    )
    assert result.complete is False
    assert "1 endpoint(s) did not answer" in result.detail


def test_the_alert_body_names_every_verdict_that_alerts() -> None:
    """The body said "Two alerting verdicts … The third" while `_ALERTING` had
    FIVE members, and then explained the two it had just said did not exist.

    RED IF: a decision is added to `_ALERTING` without the operator-facing body
    learning about it.
    """
    spec = importlib.util.spec_from_file_location("live_posture_alerting_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    alerting = {
        d.value for d in module.PostureDecision if module.PostureResult(d, "x").should_alert
    }
    assert len(alerting) >= 5, "this gate refuses to pass over an empty alerting set"
    body = _condition_free_alert_body()
    # WHOLE-TOKEN, not substring. `live_judge_undeclared` is a prefix of
    # `live_judge_undeclaredX`, so a plain `in` check stays green while the body
    # names a verdict that no longer exists — rule 8 reappearing inside the gate
    # that exists to stop the body drifting from the code.
    # `[A-Za-z0-9_]`, not `[a-z_]`: a lowercase-only class stops at the capital
    # in `live_judge_undeclaredX`, so the renamed verdict still matched and the
    # mutation survived. Measured — this exact fix took M32 from SURVIVED to red.
    tokens = set(re.findall(r"[A-Za-z0-9_]+", body))
    missing = sorted(v for v in alerting if v not in tokens)
    assert missing == [], f"the alert body never mentions {missing} as a whole word"


def test_the_posture_step_is_given_a_github_token() -> None:
    """It is the only step in the repository that reads `api.github.com` from
    Python, and it had no token at all while the two `gh` steps beside it both
    did. Unauthenticated `api.github.com` is 60 requests/hour per IP and Actions
    runner IPs are shared, so the re-affirmation read would have failed exactly
    where it is load-bearing — returning UNKNOWN and opening a money alert that
    could never auto-close.

    RED IF: the token is removed from the posture step.
    """
    step = [s for s in _steps() if "money-spending posture" in str(s.get("name", ""))]
    assert len(step) == 1
    assert "GH_TOKEN" in (step[0].get("env") or {})
    # ...and the job must still not be able to WRITE the declaration it polices.
    assert _load_workflow()["permissions"]["contents"] == "read"


# --- M. What ROUND TWO broke in round one's fixes -------------------------
#
# The rulebook says "expect your own fix to introduce a defect — budget a round
# for it". It did. Every test below pins a defect that round one's fix either
# introduced or failed to close.


def test_an_expires_at_tie_cannot_re_arm_the_decoy(posture: ModuleType) -> None:
    """ROUND-1 FIX RE-ARMED. Round one picked `max(active, key=_cover_ends)` as
    the governing window, and `max` returns the FIRST maximal element — so
    giving a decoy the IDENTICAL `expires_at` put it first and silenced an
    eight-day-stale window again. Reordering two objects in a JSON file flipped
    a money alert with nothing else changing.

    Fixed by removing the tie entirely: EVERY covering window must be attended.

    RED IF: attention narrows to one representative window again.
    """
    stale = _window(posture, opened=_OLD_OPEN, expires=_FUTURE_SHUT, owner="rohit", issue=105)
    decoy = _window(posture, opened=_NOW_OPEN, expires=_FUTURE_SHUT, owner="bob")
    for order in ([decoy, stale], [stale, decoy]):
        result = posture.evaluate_posture(
            readiness_states={_HOST_A: "live"},
            windows=order,
            now=_NOW,
            reaffirmations={105: []},
        )
        assert result.decision is posture.PostureDecision.LIVE_REAFFIRMATION_LAPSED, order
        assert result.should_alert is True


def test_two_standing_windows_cannot_shadow_each_other(posture: ModuleType) -> None:
    """The same defect in its worst form: `_cover_ends` is the same sentinel for
    EVERY standing window, so two of them always tied and file order decided
    unconditionally.

    RED IF: a stale standing window can be hidden behind a fresh one.
    """
    stale = _standing(posture, opened=_OLD_OPEN, adr="ADR-0099", issue=105)
    fresh = _standing(posture, opened=_NOW_OPEN, adr="ADR-0099", issue=400)
    for order in ([fresh, stale], [stale, fresh]):
        result = posture.evaluate_posture(
            readiness_states={_HOST_A: "live"},
            windows=order,
            now=_NOW,
            reaffirmations={105: [], **_reaffirmed(posture, window=fresh, hours_ago=1, now=_NOW)},
        )
        assert result.decision is posture.PostureDecision.LIVE_REAFFIRMATION_LAPSED, order


def test_the_verdict_does_not_depend_on_declaration_order(posture: ModuleType) -> None:
    """POSITIVE PARTNER for the two above: when everything IS attended, the
    verdict must be quiet in either order — otherwise "order never matters"
    would be satisfied by a check that always alerts.

    RED IF: the decision becomes order-sensitive in the quiet direction.
    """
    a = _window(posture, opened=_NOW_OPEN, expires=_FUTURE_SHUT, owner="rohit", issue=105)
    b = _window(posture, opened=_NOW_OPEN, expires=_FUTURE_SHUT, owner="bob", issue=400)
    reaff = {
        **_reaffirmed(posture, window=a, hours_ago=1, now=_NOW),
        **_reaffirmed(posture, window=b, hours_ago=1, now=_NOW),
    }
    # _reaffirmed keys by issue, and both windows share an opened_at, so patch
    # the owner on b's entry.
    reaff[400] = [
        posture.Reaffirmation(
            at=_NOW - dt.timedelta(hours=1), by="bob", window_opened_at=b.opened_at
        )
    ]
    for order in ([a, b], [b, a]):
        result = posture.evaluate_posture(
            readiness_states={_HOST_A: "live"}, windows=order, now=_NOW, reaffirmations=reaff
        )
        assert result.should_alert is False, order


@pytest.mark.parametrize(
    "status",
    [
        # The one that made this mechanism refuse ITS OWN record: "pending" is
        # inside "money-spending", which is this package's house vocabulary.
        "Accepted — 2026-08-25. Follows the money-spending posture ADR.",
        "Accepted. Governs live spending.",
        "Accepted — depending on nothing.",
        "Accepted. Replaced nothing.",
        "Accepted — 2026-09-01. Suspending the old rule.",
    ],
)
def test_an_innocent_word_containing_a_revoked_marker_still_authorises(
    posture: ModuleType, tmp_path: Path, status: str
) -> None:
    """A gate that refuses a LEGITIMATE authorisation is a gate somebody deletes.

    Round one matched the revoked-status markers as substrings, so `"pending"`
    inside `"money-spending"` refused ADR-0071 itself — exactly the documents
    that would ever authorise a live posture. AGENTS.md rule 8, inside the gate
    written to enforce it.

    RED IF: the markers go back to substring matching.
    """
    text = f"# ADR-0099: x\n\n## Status\n\n{status}\n\n{_MARKER}\n"
    assert posture.authorising_adrs(_adr_dir(tmp_path, {"0099-x.md": text})) == frozenset(
        {"ADR-0099"}
    ), status


def test_only_the_three_genuinely_revoked_adrs_in_this_tree_are_refused(
    posture: ModuleType,
) -> None:
    """The false-positive floor, measured against the REAL corpus.

    Every ADR here is Accepted except three, and a status check that refuses
    more than those three is refusing legitimate records.

    RED IF: a revoked marker starts matching an ordinary Accepted status — or a
    genuinely revoked one stops being caught.
    """
    import re as _re

    adr_dir = REPO_ROOT / "docs" / "adr"
    records = sorted(adr_dir.glob("[0-9]*.md"))
    assert len(records) >= 40, "this gate refuses to pass over nothing"
    refused = []
    for path in records:
        status = _re.search(r"^## Status\s*\n+([^\n]+)", path.read_text(encoding="utf-8"), _re.M)
        if status and not posture._adr_status_is_live(status.group(1)):
            refused.append(path.name.split("-")[0])
    assert sorted(refused) == ["0001", "0014", "0060"], (
        f"expected exactly ADR-0001 (Superseded), ADR-0014 (Proposed) and "
        f"ADR-0060 (Reverted) to be refused; got {sorted(refused)}"
    )


@pytest.mark.parametrize(
    ("label", "body"),
    [
        # The round-1 HTML-comment evasion, reopened: the flag was set on "<!--"
        # and cleared by ANY "-->" on the same line, so a second comment opened
        # on that line left it clear.
        ("a reopened HTML comment", "<!-- a --> <!-- note\n{marker}\n-->"),
        # A plain tilde fence — the other standard fence marker.
        ("a tilde-fenced block", "~~~\n{marker}\n~~~"),
        # A ``` block "closed" by a stray ~~~ line, or the reverse.
        ("a fence closed by the other marker", "~~~\nx\n```\n{marker}\n```"),
        # The other standard way Markdown quotes a line — and the one that
        # happens by accident.
        ("a four-space indented code block", "    {marker}"),
        ("a tab-indented code block", "\t{marker}"),
        ("a <pre> block", "<pre>\n{marker}\n</pre>"),
    ],
)
def test_the_marker_does_not_authorise_from_a_quoted_region(
    posture: ModuleType, tmp_path: Path, label: str, body: str
) -> None:
    """Five more ways to put the marker's exact bytes in a file while committing
    to nothing. Round one closed two of these shapes and left these five open,
    including the HTML-comment evasion through a different door.

    RED IF: any branch of `_strip_uncommitted_prose` is removed.
    """
    text = f"# ADR-0099: x\n\n## Status\n\nAccepted.\n\n{body.format(marker=_MARKER)}\n"
    assert posture.authorising_adrs(_adr_dir(tmp_path, {"0099-x.md": text})) == frozenset(), label


def test_a_genuine_marker_beside_a_quoted_one_still_authorises(
    posture: ModuleType, tmp_path: Path
) -> None:
    """POSITIVE PARTNER for all five rows above — without it, a stripper that
    deleted the whole file would satisfy every one of them.

    RED IF: the stripper starts swallowing content after a quoted region.
    """
    text = (
        "# ADR-0099: x\n\n## Status\n\nAccepted.\n\n"
        f"Here is what the line looks like:\n\n```\n{_MARKER}\n```\n\n"
        f"And here it is meant:\n\n{_MARKER}\n"
    )
    assert posture.authorising_adrs(_adr_dir(tmp_path, {"0099-x.md": text})) == frozenset(
        {"ADR-0099"}
    )


def test_a_status_that_merely_mentions_acceptance_does_not_authorise(
    posture: ModuleType, tmp_path: Path
) -> None:
    """SURVIVED MUTATION: `startswith("accepted")` relaxed to `"accepted" in
    lowered` left the whole suite green, and the real corpus does not catch it
    because ADR-0014's `Proposed` line contains no "accepted".

    RED IF: the status check stops requiring the line to OPEN with Accepted.
    """
    for status in (
        "Proposed — 2026-09-01. To be accepted after review.",
        "Rejected — 2026-09-01; ADR-0099 was accepted instead.",
    ):
        text = f"# ADR-0098: x\n\n## Status\n\n{status}\n\n{_MARKER}\n"
        assert posture.authorising_adrs(_adr_dir(tmp_path, {"0098-x.md": text})) == frozenset(), (
            status
        )


def test_the_token_must_start_the_line_proven_against_a_real_substring_search(
    posture: ModuleType,
) -> None:
    """SURVIVED MUTATION, AND THE ROUND-1 TEST FOR IT PASSED FOR THE WRONG REASON.

    The earlier test used a body where a substring implementation would slice
    from offset 0 and produce garbage, so it went green against an implementation
    that did exactly what it claimed to forbid. This body is built so a real
    substring search (slice from the token's POSITION) WOULD extract a valid
    instant — so only a genuine "must start the line" rule refuses it.

    RED IF: the token match is loosened to a substring search.
    """
    body = "x" * 23 + " 2026-08-20T12:00:00+00:00 and by the way REAFFIRM live-execution"
    assert posture._reaffirmed_instant(body) is None
    # POSITIVE PARTNER: the same instant, at the start of the line, IS read.
    assert posture._reaffirmed_instant(
        "REAFFIRM live-execution 2026-08-20T12:00:00+00:00"
    ) == dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("owner", "accepted"),
    [
        ("rohit", True),
        ("@rohit", True),
        ("some-user-99", True),
        # A DISPLAY NAME. It parsed, covered, and then lapsed forever: the
        # operator commented exactly as the alert instructed and nothing
        # changed, with no message saying why.
        ("Rohit Agrawal", False),
        ("rohit agrawal", False),
        ("rohit@example.com", False),
        ("-leading-hyphen", False),
        ("trailing-hyphen-", False),
        ("a" * 40, False),
    ],
)
def test_the_owner_must_be_something_a_comment_author_could_match(
    posture: ModuleType, owner: str, accepted: bool
) -> None:
    """`owner` is compared against a GitHub `user.login`, so it has to BE one.

    RED IF: the login shape stops being validated, so a window can be declared
    that no comment can ever re-affirm.
    """
    entry = {
        "owner": owner,
        "reason": "r",
        "mode": "time_boxed",
        "judge": False,
        "opened_at": _NOW_OPEN,
        "expires_at": _NOW_SHUT,
    }
    parsed = posture.parse_windows({"windows": [entry]})
    assert (parsed is not None) is accepted, owner


def test_the_span_that_needs_an_issue_is_pinned_at_the_exact_boundary(
    posture: ModuleType,
) -> None:
    """Rule 7a: literals on both sides, never against the constant.

    The ATTENDANCE boundary was pinned in round one; its twin — the SPAN
    boundary that decides whether a window must name an issue — was not, and
    `>` → `>=` survived.

    RED IF: the span comparison flips its strictness.
    """
    base = {
        "owner": "rohit",
        "reason": "r",
        "mode": "time_boxed",
        "judge": False,
        "opened_at": "2026-08-25T00:00:00+00:00",
    }
    # Exactly 24 hours: no issue needed.
    assert (
        posture.parse_windows({"windows": [base | {"expires_at": "2026-08-26T00:00:00+00:00"}]})
        is not None
    )
    # One second past 24 hours: an issue is required.
    assert (
        posture.parse_windows({"windows": [base | {"expires_at": "2026-08-26T00:00:01+00:00"}]})
        is None
    )
    assert (
        posture.parse_windows(
            {"windows": [base | {"expires_at": "2026-08-26T00:00:01+00:00", "reaffirm_issue": 105}]}
        )
        is not None
    )
