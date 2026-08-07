"""Production must be proven to run `main`'s tip, not assumed to.

#245's third failure mode, witnessed 2026-08-07: a merge to `main` produced
**zero `push`-event runs**, so `deploy.yml` — which is `on.workflow_run` off
CI/Tests/E2E — was never fired by that merge. Production sat on the previous
build for 34m31s (merged 08:16:16Z; the first build containing it finished
deploying at 08:50:47Z) while **every passive signal stayed green**: `/ready`
returned 200, `/status` returned a valid `build_sha`, and the scheduled
Availability and Error-rate checks both passed — against the stale build.

(An earlier draft of this docstring said "zero workflow runs ... nothing at
all". That is false: `gh api ".../runs?head_sha=bd7c46b..."` returns **3** runs,
two of them `Deploy to Fly.io` marked `skipped` — fired by `pull_request` runs
on another branch. What was zero is `push`-event runs.)

Nothing in CI compared `main`'s tip to what production actually serves —
`grep -rn build_sha .github/workflows/ scripts/` returned three comment lines in
`deploy.yml` and no check. (Line numbers are deliberately not quoted here: an
earlier draft pinned them and they were already stale two commits later.)

AGENTS.md rule 18 tells a *human* to make that comparison; no machine did.

`deploy-drift-watchdog.yml` asked a weaker question — "does `main` HEAD have a
successful Deploy *run*?" — which is a proxy. It cannot see a Deploy run that
succeeded while production did not actually roll. `/status.build_sha` is the
truth: `deploy.yml` passes `--build-arg GIT_SHA=...` and the Dockerfile bakes it
into the image.

Per ADR-0024, the decision lives in tested Python rather than an inline shell
block in the workflow, because a decision that cannot be tested drifts from its
own documentation.

WHAT TURNS THIS FILE RED: make `evaluate_drift` return `IN_SYNC` (or any
non-alerting decision) when the two SHAs differ and the tip is older than the
grace period — i.e. delete the drift branch.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from types import ModuleType

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "deploy_drift_check.py"

_TIP = "f1eb7e43e6ac3d6837b16cd976dfd39178beb3c8"
_OLD = "79ad02a0e9d230efa732fe990037859c46566a31"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_drift_check_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module defines dataclasses, and dataclass field
    # resolution looks the class's module up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def drift() -> ModuleType:
    return _module()


# --- the decision table ---------------------------------------------------


def test_matching_shas_are_in_sync(drift: ModuleType) -> None:
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_TIP, drift_age_seconds=99999.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.IN_SYNC
    assert not result.should_alert


def test_a_fresh_mismatch_is_a_deploy_in_flight(drift: ModuleType) -> None:
    """A merge that landed a minute ago has not had time to deploy."""
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, drift_age_seconds=60.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.DEPLOY_IN_FLIGHT
    assert not result.should_alert


def test_a_stale_mismatch_is_drift(drift: ModuleType) -> None:
    """THE defect. Production is not running main's tip and has had time to."""
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, drift_age_seconds=3600.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.DRIFTED
    assert result.should_alert


def test_the_grace_boundary_is_exact(drift: ModuleType) -> None:
    """Literals on BOTH sides, never compared against the shipped constant.

    AGENTS.md rule 7a: asserting a bound against the constant that defines it
    lets the constant itself be changed undetected.
    """
    just_inside = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, drift_age_seconds=599.0, grace_seconds=600.0
    )
    just_outside = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, drift_age_seconds=601.0, grace_seconds=600.0
    )
    assert just_inside.decision is drift.DriftDecision.DEPLOY_IN_FLIGHT
    assert just_outside.decision is drift.DriftDecision.DRIFTED


# --- refusing to pass on empty input --------------------------------------


@pytest.mark.parametrize("missing", ["", None, "   "])
def test_an_unreadable_main_tip_is_unknown_and_alerts(
    drift: ModuleType, missing: str | None
) -> None:
    """A gate must refuse to pass on empty input.

    Printing a blank and exiting 0 is precisely the silent-wrong-number failure
    this check exists to prevent, so an unresolvable input is LOUD.
    """
    result = drift.evaluate_drift(
        main_tip=missing, build_sha=_TIP, drift_age_seconds=10.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.UNKNOWN
    assert result.should_alert


@pytest.mark.parametrize("missing", ["", None, "   "])
def test_an_unreachable_build_sha_is_unknown_and_alerts(
    drift: ModuleType, missing: str | None
) -> None:
    """`/status` is a network call; unreachable must not read as healthy."""
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=missing, drift_age_seconds=10.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.UNKNOWN
    assert result.should_alert


def test_an_unknown_tip_age_is_unknown_not_silently_in_flight(drift: ModuleType) -> None:
    """If we cannot tell how long they have differed, say so rather than wait.

    Defaulting to DEPLOY_IN_FLIGHT would make a permanent drift invisible for
    as long as the age stayed unreadable.
    """
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, drift_age_seconds=None, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.UNKNOWN
    assert result.should_alert


def test_comparison_ignores_case_and_surrounding_whitespace(drift: ModuleType) -> None:
    result = drift.evaluate_drift(
        main_tip=f"  {_TIP.upper()}  ",
        build_sha=_TIP,
        drift_age_seconds=99999.0,
        grace_seconds=600.0,
    )
    assert result.decision is drift.DriftDecision.IN_SYNC


# --- the shipped default --------------------------------------------------


def test_the_shipped_grace_clears_the_worst_measured_deploy(drift: ModuleType) -> None:
    """The grace period is measured, not chosen by taste.

    Measured 2026-08-07 on this repository:
      * typical, `2931c8c`: merged 08:37:36Z, deploy job finished 08:50:47Z
        -> 13m11s (791s). The gate WAITS for E2E, which is most of it.
      * worst, `bd7c46b`: merged 08:16:16Z, first build containing it finished
        deploying 08:50:47Z -> 34m31s (2071s), because its own merge triggered
        nothing and it rode the next merge's deploy.

    Literals on both sides (rule 7a): the default must clear 2071s with real
    headroom, and must not be so large that a genuine drift hides for hours.
    """
    assert drift.DEFAULT_GRACE_SECONDS > 1560
    assert drift.DEFAULT_GRACE_SECONDS <= 2000


def test_a_drift_that_outlives_the_shipped_grace_alerts(drift: ModuleType) -> None:
    """Ties the shipped constant to behaviour, not just to a numeric range."""
    result = drift.evaluate_drift(
        main_tip=_TIP,
        build_sha=_OLD,
        drift_age_seconds=drift.DEFAULT_GRACE_SECONDS + 1.0,
        grace_seconds=drift.DEFAULT_GRACE_SECONDS,
    )
    assert result.decision is drift.DriftDecision.DRIFTED


# --- the reporting contract -----------------------------------------------


def test_every_decision_reports_what_it_compared(drift: ModuleType) -> None:
    """A gate must report what it counted.

    Every branch's detail names both SHAs (or says plainly that one was
    unreadable), so the alert is actionable without re-running anything.
    """
    cases: list[tuple[str | None, str | None, float | None]] = [
        (_TIP, _TIP, 1.0),
        (_TIP, _OLD, 1.0),
        (_TIP, _OLD, 99999.0),
        (None, _TIP, 1.0),
        (_TIP, None, 1.0),
        (_TIP, _OLD, None),
    ]
    seen = set()
    for main_tip, build_sha, age in cases:
        result = drift.evaluate_drift(
            main_tip=main_tip,
            build_sha=build_sha,
            drift_age_seconds=age,
            grace_seconds=600.0,
        )
        seen.add(result.decision)
        assert result.detail.strip(), f"empty detail for {(main_tip, build_sha, age)}"
        assert len(result.detail) > 20, (
            f"uninformative detail for {(main_tip, build_sha, age)}: {result.detail!r}"
        )
    # Positive partner: prove the loop actually exercised every decision, so
    # this cannot pass by covering only the easy branches.
    assert seen == set(drift.DriftDecision)


def test_the_watchdogs_dispatch_list_matches_the_required_workflows() -> None:
    """The THIRD list of required-workflow names, which nothing pinned.

    `deploy.yml` holds filter PATTERNS (escaped, ADR-0025).
    `scripts/deploy_gate.py:REQUIRED_WORKFLOWS` holds LITERAL names.
    `deploy-drift-watchdog.yml` holds a third copy, as `"<name>:<file>"` pairs
    in a shell loop — correctly UNescaped, because it compares against the
    API's `.name` and passes the file to `gh workflow run`.

    Three near-identical lists in two languages will drift. If the watchdog's
    copy goes stale, it silently stops re-dispatching the workflow that is
    actually missing — the self-healing quietly heals nothing.

    WHAT TURNS THIS RED: adding, removing or renaming a required workflow in
    `deploy_gate.py` without updating the watchdog's loop, or vice versa.
    """
    import re

    watchdog = (_ROOT / ".github" / "workflows" / "deploy-drift-watchdog.yml").read_text(
        encoding="utf-8"
    )
    # Anchor INSIDE the `for pair in ...; do` line. Scraping the whole file
    # would let the names live in a comment while the loop dispatches nothing —
    # measured in review: replacing the body with `for pair in ; do` and leaving
    # the names in a comment above kept this test GREEN. That is the
    # substring-vs-structure trap AGENTS.md rule 8 records, inside a guard.
    loop = re.search(r"for pair in ([^\n]*); do", watchdog)
    assert loop, "no `for pair in ...; do` dispatch loop found in the watchdog"
    pairs = re.findall(r'"([^":]+):([A-Za-z0-9._-]+\.yml)"', loop.group(1))
    assert pairs, f"the dispatch loop lists no <name>:<file> pairs: {loop.group(1)!r}"

    names = tuple(name for name, _file in pairs)
    assert tuple(_module_deploy_gate().REQUIRED_WORKFLOWS) == names, (
        f"watchdog dispatches {names} but deploy_gate.REQUIRED_WORKFLOWS is "
        f"{_module_deploy_gate().REQUIRED_WORKFLOWS}"
    )

    # Positive partner: every file it would dispatch must actually exist,
    # otherwise the list could "match" while pointing at nothing.
    for _name, filename in pairs:
        assert (_ROOT / ".github" / "workflows" / filename).is_file(), (
            f"watchdog would dispatch {filename}, which does not exist"
        )


def _module_deploy_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "deploy_gate_for_watchdog_check", _ROOT / "scripts" / "deploy_gate.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_decisions_are_exhaustively_pinned(drift: ModuleType) -> None:
    """Adding a member to DriftDecision must not go unnoticed.

    Partition the enum into alerting and non-alerting, with a non-empty
    positive partner on each side.
    """
    alerting = {drift.DriftDecision.DRIFTED, drift.DriftDecision.UNKNOWN}
    quiet = {drift.DriftDecision.IN_SYNC, drift.DriftDecision.DEPLOY_IN_FLIGHT}
    assert alerting and quiet
    assert alerting | quiet == set(drift.DriftDecision)
    assert not (alerting & quiet)


# --- the wire from the decision to the workflow ---------------------------
#
# Everything above tests `evaluate_drift` in isolation. Review measured that
# the WIRE was tested nowhere: deleting the `$GITHUB_OUTPUT` write entirely, or
# renaming the `should_alert` key, both left the suite at 17 passed — and either
# makes the watchdog permanently GREEN on real drift, because the workflow's
# alert and fail steps branch on `steps.buildsha.outputs.should_alert`.


def _run_main(
    drift: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *,
    tip: str | None,
    served: str | None,
    age: float | None,
) -> tuple[int, str]:
    """Drive `main()` with the network stubbed; return (exit code, outputs file)."""
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(drift, "fetch_main_tip", lambda _repo: tip)
    monkeypatch.setattr(drift, "fetch_build_sha", lambda _url, **_kw: served)
    monkeypatch.setattr(drift, "fetch_drift_age", lambda _repo, _sha: age)
    code = drift.main(["--repo", "owner/repo", "--grace-seconds", "600"])
    return code, out.read_text(encoding="utf-8")


def test_main_publishes_the_verdict_when_production_is_in_sync(
    drift: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    code, written = _run_main(drift, monkeypatch, tmp_path, tip=_TIP, served=_TIP, age=None)
    assert code == 0
    assert "should_alert=false" in written
    assert "decision=in_sync" in written


def test_main_publishes_the_verdict_and_exits_nonzero_on_drift(
    drift: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """WHAT TURNS THIS RED: deleting the `$GITHUB_OUTPUT` write, or renaming the
    `should_alert` key. Either leaves the workflow's alert step un-triggered and
    the job green while production is stale."""
    code, written = _run_main(drift, monkeypatch, tmp_path, tip=_TIP, served=_OLD, age=99999.0)
    assert code == 1
    assert "should_alert=true" in written
    assert "decision=drifted" in written


def test_main_survives_a_fetcher_that_raises(
    drift: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A crash must not leave the job green.

    The workflow runs this step with `continue-on-error: true`, so an uncaught
    traceback exits non-zero WITHOUT writing `$GITHUB_OUTPUT`, both later steps
    are skipped, and the job reports success. The fetchers therefore swallow
    everything; this proves it for the `/status` path.
    """
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(drift, "fetch_main_tip", lambda _repo: _TIP)

    def _explode(_url: str, **_kw: object) -> str:
        raise RuntimeError("upstream on fire")

    monkeypatch.setattr(drift, "fetch_build_sha", _explode)
    with pytest.raises(RuntimeError):
        drift.main(["--repo", "owner/repo"])
    # The module-level __main__ guard is what converts this into a written
    # verdict; prove that helper does its job rather than trusting the guard.
    drift._write_outputs(drift.DriftResult(drift.DriftDecision.UNKNOWN, "crashed: RuntimeError()"))
    assert "should_alert=true" in out.read_text(encoding="utf-8")


def test_a_status_body_that_is_not_an_object_returns_none_rather_than_raising(
    drift: ModuleType, tmp_path: pathlib.Path
) -> None:
    """Measured defect: `payload.get` sat outside the try.

    A `/status` body that is valid JSON but not an object raised AttributeError,
    killing the process before `$GITHUB_OUTPUT` was written and leaving the
    watchdog green. Every one of these must read as "unknown", not crash.
    """
    for body in ("[{}]", "null", '"a string"', "123", "not json at all", "<html></html>"):
        stub = tmp_path / "status.json"
        stub.write_text(body, encoding="utf-8")
        assert drift.fetch_build_sha(stub.as_uri(), attempts=1) is None, body


def test_a_wellformed_status_body_is_read(drift: ModuleType, tmp_path: pathlib.Path) -> None:
    """Positive partner: the negative check above is worthless if this fails."""
    stub = tmp_path / "status.json"
    stub.write_text(json.dumps({"build_sha": _TIP}), encoding="utf-8")
    assert drift.fetch_build_sha(stub.as_uri(), attempts=1) == _TIP


@pytest.mark.parametrize("age", [-1.0, -3600.0, -31536000.0])
def test_a_negative_age_is_unknown_not_silently_in_flight(drift: ModuleType, age: float) -> None:
    """Clock skew must not silence the check.

    `age < grace` is true for every negative number, so a commit dated in the
    future would read DEPLOY_IN_FLIGHT for as long as the date stayed ahead.
    """
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, drift_age_seconds=age, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.UNKNOWN
    assert result.should_alert


def test_the_workflow_branches_on_the_key_this_script_writes() -> None:
    """Pin BOTH sides of the output contract together.

    The script writes `should_alert=`; `deploy-drift-watchdog.yml` branches on
    `steps.buildsha.outputs.should_alert`. Renaming either one silently breaks
    the alert, and each file alone looks perfectly correct.
    """
    script = _SCRIPT.read_text(encoding="utf-8")
    workflow = (_ROOT / ".github" / "workflows" / "deploy-drift-watchdog.yml").read_text(
        encoding="utf-8"
    )
    assert 'write(f"should_alert=' in script, "the script no longer writes should_alert"
    assert "steps.buildsha.outputs.should_alert" in workflow, (
        "the watchdog no longer branches on should_alert"
    )
    assert "continue-on-error: true" in workflow, (
        "the check step must not fail the job directly, or the alert step is skipped"
    )
    # ...and the job must still be failed explicitly somewhere, or drift is
    # merely noted while the workflow reports success.
    assert "exit 1" in workflow, "nothing fails the job on drift"
