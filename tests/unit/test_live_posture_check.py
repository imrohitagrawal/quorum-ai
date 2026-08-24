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
import sys
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


def _window(posture: ModuleType, *, opened: str, expires: str, owner: str = "rohit") -> Any:
    return posture.DeclaredWindow(
        owner=owner,
        reason="collect the ADR-0060 sample",
        opened_at=dt.datetime.fromisoformat(opened),
        expires_at=dt.datetime.fromisoformat(expires),
    )


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
    ],
)
def test_a_malformed_declaration_refuses_to_parse(posture: ModuleType, payload: object) -> None:
    """Each row is a way a declaration could be wrong. All must return None.

    The naive-timestamp row matters most: "17:00" in whose day? Accepting it
    could widen a window by hours in the operator's favour.

    RED IF: any validation branch in ``parse_windows`` is deleted.
    """
    assert posture.parse_windows(payload) is None


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


def test_the_shipped_declaration_file_parses_and_declares_nothing(posture: ModuleType) -> None:
    """The file this repository actually ships must be readable, and empty.

    Empty is the safe default: with no window declared, ANY live posture alerts.

    RED IF: the shipped file is edited into something unparseable (which would
    make the watchdog alert on every run and get it muted), or a window is left
    declared in it after its work is done.
    """
    parsed = posture.parse_windows(json.loads(SHIPPED_WINDOWS.read_text(encoding="utf-8")))
    assert parsed == []


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
    assert posture.load_windows(posture.DEFAULT_WINDOWS_PATH) == []


# --- C. It reports what it counted -----------------------------------------


def test_every_decision_reports_what_it_observed(posture: ModuleType) -> None:
    """Each branch must say what it looked at, and every branch must be reached.

    RED IF: any branch's detail is blanked, or a branch is deleted so the loop
    can no longer reach it (``seen == set(...)`` catches the second).
    """
    window_now = _window(posture, opened=_NOW_OPEN, expires=_NOW_SHUT)
    window_past = _window(posture, opened=_OLD_OPEN, expires=_OLD_SHUT)
    cases = [
        ({_HOST_A: "offline_by_config"}, [], None),
        ({_HOST_A: "live"}, [window_now], None),
        ({_HOST_A: "live"}, [], None),
        ({_HOST_A: "live"}, [window_past], None),
        ({_HOST_A: None}, [], None),
        ({_HOST_A: "live"}, None, "malformed"),
    ]
    seen = set()
    for states, windows, _ in cases:
        result = posture.evaluate_posture(readiness_states=states, windows=windows, now=_NOW)
        assert result.detail.strip()
        assert len(result.detail) > 40, result.detail
        seen.add(result.decision)
    assert seen == set(posture.PostureDecision)


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
    posture.main(["--ready-url", url, "--windows-file", str(SHIPPED_WINDOWS)])
    printed = capsys.readouterr().out
    assert url in printed
    assert "offline_by_config" in printed


# --- D. THE WIRE. Deleting the $GITHUB_OUTPUT write must go red ------------


def _run_main(
    posture: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: object,
    windows_payload: object,
) -> tuple[int, str]:
    ready = _ready_stub(tmp_path, body, name="wire-ready.json")
    windows = tmp_path / "windows.json"
    windows.write_text(json.dumps(windows_payload), encoding="utf-8")
    outputs = tmp_path / "outputs.txt"
    outputs.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    code = posture.main(["--ready-url", ready, "--windows-file", str(windows)])
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
                    "opened_at": far_past,
                    "expires_at": far_future,
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
    with pytest.raises(RuntimeError):
        posture.main(["--ready-url", _HOST_A, "--windows-file", str(SHIPPED_WINDOWS)])
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


def test_the_alert_step_also_fires_when_the_check_step_crashed() -> None:
    """A crash writes no outputs, so branching on ``should_alert`` alone would
    skip the alert and leave a continue-on-error job green.

    RED IF: the ``outcome == 'failure'`` disjunct is dropped from the alert
    step's ``if:``. Asserted against the PARSED step, not the file's raw text.
    """
    alert = [s for s in _steps() if "Alert on an undeclared" in str(s.get("name", ""))]
    assert len(alert) == 1
    condition = alert[0]["if"]
    assert "steps.posture.outputs.should_alert == 'true'" in condition
    assert "steps.posture.outcome == 'failure'" in condition


def test_the_resolve_step_requires_an_observed_reading() -> None:
    """The posture alert closes only on a reading the check actually took.

    The sibling drift watchdog closes its issue as soon as a deploy succeeds,
    which is precisely why it reported #357's drift RESOLVED at the moment the
    money posture went live.

    RED IF: the ``outcome == 'success'`` term is dropped — a crashed step writes
    no outputs, and ``should_alert != 'true'`` is true of an empty string, so the
    alert would be closed by a check that measured nothing.
    """
    resolve = [s for s in _steps() if "Resolve the posture alert" in str(s.get("name", ""))]
    assert len(resolve) == 1
    condition = resolve[0]["if"]
    assert "steps.posture.outcome == 'success'" in condition
    assert "steps.posture.outputs.should_alert == 'false'" in condition


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
