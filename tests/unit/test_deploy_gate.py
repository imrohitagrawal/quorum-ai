"""Guard the deploy-gate decision logic in ``scripts/deploy_gate.py``.

The gate decides whether a Fly deploy may proceed for a commit. Its contract is
fail-safe: deploy IFF every required workflow concluded ``success`` for the SHA,
and — critically — it must **wait** for still-pending workflows rather than
skip them. The bug this replaces skipped when a slow workflow (E2E ≈ 3 min) was
still running, so a merge could be silently never deployed. These tests lock the
wait-and-verify behaviour and every stop condition, with zero network and zero
real sleeping (injected ``sleep`` / ``monotonic``).

``scripts/`` is not on ``--cov=src``, so this suite is the only thing guarding
the gate; a regression here is invisible to the main coverage gate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_GATE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "deploy_gate.py"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_gate_under_test", _GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so ``@dataclass`` can resolve the module's string
    # annotations (``from __future__ import annotations`` makes them strings,
    # and dataclasses looks the module up in ``sys.modules`` to resolve them).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


class _Clock:
    """Fake monotonic clock; ``sleep`` advances it so ``timeout`` is deterministic."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _fetcher(schedule: dict[str, list[str | None]]) -> Callable[[str], str | None]:
    """Build a fetch_conclusion that pops the next scripted value per workflow.

    Once a workflow's schedule is exhausted, its last value repeats — so a
    workflow that is scheduled ``["success"]`` stays green on every later poll.
    """
    state = {k: list(v) for k, v in schedule.items()}

    def fetch(workflow: str) -> str | None:
        values = state[workflow]
        if len(values) > 1:
            return values.pop(0)
        return values[0]

    return fetch


ALL = ("CI", "Tests", "E2E (axe + parity)")


def test_waits_through_pending_then_proceeds() -> None:
    """The regression: a slow workflow pending for several polls must be WAITED
    for, not skipped. E2E is pending for 3 rounds, then turns green."""
    clock = _Clock()
    fetch = _fetcher(
        {
            "CI": ["success"],
            "Tests": ["success"],
            "E2E (axe + parity)": [None, None, None, "success"],
        }
    )
    result = gate.evaluate_gate(
        fetch,
        timeout=900,
        poll=15,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        log=lambda _m: None,
    )
    assert result.proceed is True
    assert result.decision is gate.GateDecision.PROCEED
    # It genuinely waited (3 pending rounds → 3 sleeps) instead of giving up.
    assert clock.sleeps == [15, 15, 15]


def test_empty_required_workflows_refuses() -> None:
    """A vacuous gate (no required workflows) must NOT pass — fail-safe."""
    result = gate.evaluate_gate(
        lambda _wf: "success",
        required_workflows=(),
        sleep=lambda _s: None,
        monotonic=lambda: 0.0,
        log=lambda _m: None,
    )
    assert result.proceed is False
    assert result.decision is gate.GateDecision.BLOCKED_FAILURE


def test_all_green_immediately_proceeds_without_waiting() -> None:
    clock = _Clock()
    fetch = _fetcher({wf: ["success"] for wf in ALL})
    result = gate.evaluate_gate(
        fetch, sleep=clock.sleep, monotonic=clock.monotonic, log=lambda _m: None
    )
    assert result.proceed is True
    assert clock.sleeps == []  # no pending → no waiting


def test_failure_blocks_immediately() -> None:
    clock = _Clock()
    fetch = _fetcher({"CI": ["success"], "Tests": ["failure"], "E2E (axe + parity)": [None]})
    result = gate.evaluate_gate(
        fetch, sleep=clock.sleep, monotonic=clock.monotonic, log=lambda _m: None
    )
    assert result.proceed is False
    assert result.decision is gate.GateDecision.BLOCKED_FAILURE
    assert "Tests" in result.reason
    assert clock.sleeps == []  # terminal failure short-circuits — no waiting


@pytest.mark.parametrize(
    "bad",
    [
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
        "stale",
        # Fail-safe: a COMPLETED-but-not-success conclusion outside any known
        # fail-list must still block (the old block-list logic let these deploy).
        "skipped",
        "neutral",
        "some_future_conclusion_string",
    ],
)
def test_any_non_success_conclusion_blocks(bad: str) -> None:
    clock = _Clock()
    fetch = _fetcher({"CI": ["success"], "Tests": ["success"], "E2E (axe + parity)": [bad]})
    result = gate.evaluate_gate(
        fetch, sleep=clock.sleep, monotonic=clock.monotonic, log=lambda _m: None
    )
    assert result.proceed is False, f"{bad!r} must NOT deploy (fail-open regression)"
    assert result.decision is gate.GateDecision.BLOCKED_FAILURE
    assert bad in result.reason


def test_slow_workflow_that_eventually_fails_blocks_after_waiting() -> None:
    """Mirror of the wait regression on the FAILURE side: a slow workflow that
    is pending for several rounds and then fails must block, not deploy."""
    clock = _Clock()
    fetch = _fetcher(
        {"CI": ["success"], "Tests": ["success"], "E2E (axe + parity)": [None, None, "failure"]}
    )
    result = gate.evaluate_gate(
        fetch,
        timeout=900,
        poll=15,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        log=lambda _m: None,
    )
    assert result.proceed is False
    assert result.decision is gate.GateDecision.BLOCKED_FAILURE
    assert "E2E (axe + parity)" in result.reason
    assert clock.sleeps == [15, 15]  # waited two pending rounds, then the failure landed


def test_timeout_when_a_workflow_never_resolves() -> None:
    """A workflow stuck pending past the timeout must NOT deploy (fail-safe)."""
    clock = _Clock()
    fetch = _fetcher({"CI": ["success"], "Tests": ["success"], "E2E (axe + parity)": [None]})
    result = gate.evaluate_gate(
        fetch,
        timeout=30,
        poll=15,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        log=lambda _m: None,
    )
    assert result.proceed is False
    assert result.decision is gate.GateDecision.BLOCKED_TIMEOUT
    assert "E2E (axe + parity)" in result.reason
    # Polled at t=0 and t=15 (both < 30), gave up at t=30.
    assert clock.sleeps == [15, 15]


def test_transient_api_lag_then_success_still_proceeds() -> None:
    """A ``None`` from a transient ``gh api`` blip is 'pending', not 'failed' —
    the gate re-polls and proceeds once the real conclusion appears."""
    clock = _Clock()
    fetch = _fetcher(
        {
            "CI": [None, "success"],
            "Tests": ["success"],
            "E2E (axe + parity)": ["success"],
        }
    )
    result = gate.evaluate_gate(
        fetch,
        timeout=900,
        poll=15,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        log=lambda _m: None,
    )
    assert result.proceed is True
    assert clock.sleeps == [15]


# --- _select_conclusion: the security filter + latest-run-wins selection ------

REPO = "owner/quorum-ai"


def _run(
    *,
    name: str = "CI",
    branch: str = "main",
    event: str = "push",
    repo: str = REPO,
    status: str = "completed",
    conclusion: str | None = "success",
    started: str = "2026-07-17T10:00:00Z",
    run_id: int = 1,
) -> dict[str, object]:
    return {
        "name": name,
        "head_branch": branch,
        "event": event,
        "head_repository": {"full_name": repo},
        "status": status,
        "conclusion": conclusion,
        "run_started_at": started,
        "id": run_id,
    }


def test_select_returns_success_for_a_genuine_main_push() -> None:
    assert gate._select_conclusion([_run()], workflow="CI", repo=REPO) == "success"


def test_select_latest_run_wins_rerun_recovery() -> None:
    """A failed run followed by a newer successful re-run resolves to success."""
    old = _run(conclusion="failure", started="2026-07-17T10:00:00Z", run_id=1)
    new = _run(conclusion="success", started="2026-07-17T10:05:00Z", run_id=2)
    assert gate._select_conclusion([old, new], workflow="CI", repo=REPO) == "success"
    # ...and the reverse ordering in the list must not change the outcome.
    assert gate._select_conclusion([new, old], workflow="CI", repo=REPO) == "success"


def test_select_excludes_fork_pr_named_main() -> None:
    """SECURITY: a fork PR whose branch is literally 'main' must NOT count.

    It reports head_branch='main' but event='pull_request' and a fork
    head_repository — excluded, so it can never green the gate."""
    spoof = _run(event="pull_request", repo="attacker/quorum-ai", conclusion="success")
    assert gate._select_conclusion([spoof], workflow="CI", repo=REPO) is None


def test_select_excludes_non_main_branch() -> None:
    assert gate._select_conclusion([_run(branch="feature/x")], workflow="CI", repo=REPO) is None


def test_select_excludes_other_workflow_names() -> None:
    assert gate._select_conclusion([_run(name="Some Other WF")], workflow="CI", repo=REPO) is None


def test_select_in_progress_is_pending() -> None:
    assert (
        gate._select_conclusion(
            [_run(status="in_progress", conclusion=None)], workflow="CI", repo=REPO
        )
        is None
    )


def test_select_no_matching_run_is_pending() -> None:
    assert gate._select_conclusion([], workflow="CI", repo=REPO) is None


# --- gh_fetch_conclusion: raw-JSON transport → _select_conclusion -------------


def _fake_proc(stdout: str) -> object:
    class _P:
        def __init__(self, out: str) -> None:
            self.stdout = out

    return _P(stdout)


def test_gh_fetch_parses_json_and_selects(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps([_run(conclusion="success")])
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _fake_proc(body))
    assert gate.gh_fetch_conclusion(REPO, "sha", "CI") == "success"


def test_gh_fetch_empty_array_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _fake_proc("[]"))
    assert gate.gh_fetch_conclusion(REPO, "sha", "CI") is None


def test_gh_fetch_bad_json_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: _fake_proc("not json"))
    assert gate.gh_fetch_conclusion(REPO, "sha", "CI") is None


def test_gh_fetch_api_error_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> object:
        raise gate.subprocess.SubprocessError("gh 502")

    monkeypatch.setattr(gate.subprocess, "run", boom)
    assert gate.gh_fetch_conclusion(REPO, "sha", "CI") is None


# --- main(): dispatch escape hatch + missing-config fail-safe ------------------


def test_main_dispatch_proceeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert gate.main() == 0
    assert "proceed=true" in out.read_text()


def test_main_missing_sha_refuses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_run")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("REPO", "o/r")
    monkeypatch.delenv("SHA", raising=False)
    assert gate.main() == 0
    assert "proceed=false" in out.read_text()
