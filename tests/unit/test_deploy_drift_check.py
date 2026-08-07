"""Production must be proven to run `main`'s tip, not assumed to.

#245's third failure mode, witnessed 2026-08-07: a merge to `main` produced
**zero** workflow runs. `deploy.yml` is `on.workflow_run`, so with no upstream
run there is no `workflow_run` event, no Deploy run, and nothing to turn red —
no skipped job, no cancelled job, nothing at all. Production sat on the previous
build for 34m31s (merged 08:16:16Z; the first build containing it finished
deploying at 08:50:47Z) while **every passive signal stayed green**: `/ready`
returned 200, `/status` returned a valid `build_sha`, and the scheduled
Availability and Error-rate checks both passed — against the stale build.

Nothing in CI compared `main`'s tip to what production actually serves::

    $ grep -rn build_sha .github/workflows/ scripts/
    .github/workflows/deploy.yml:107:  # ... /status.build_sha below.
    .github/workflows/deploy.yml:151:  # ... /status serves it as ``build_sha``
    .github/workflows/deploy.yml:153:  #   curl -s .../status | jq -r .build_sha

Three comment lines, no check. AGENTS.md rule 18 tells a *human* to make that
comparison; no machine did.

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
        main_tip=_TIP, build_sha=_TIP, tip_age_seconds=99999.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.IN_SYNC
    assert not result.should_alert


def test_a_fresh_mismatch_is_a_deploy_in_flight(drift: ModuleType) -> None:
    """A merge that landed a minute ago has not had time to deploy."""
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, tip_age_seconds=60.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.DEPLOY_IN_FLIGHT
    assert not result.should_alert


def test_a_stale_mismatch_is_drift(drift: ModuleType) -> None:
    """THE defect. Production is not running main's tip and has had time to."""
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, tip_age_seconds=3600.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.DRIFTED
    assert result.should_alert


def test_the_grace_boundary_is_exact(drift: ModuleType) -> None:
    """Literals on BOTH sides, never compared against the shipped constant.

    AGENTS.md rule 7a: asserting a bound against the constant that defines it
    lets the constant itself be changed undetected.
    """
    just_inside = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, tip_age_seconds=599.0, grace_seconds=600.0
    )
    just_outside = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, tip_age_seconds=601.0, grace_seconds=600.0
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
        main_tip=missing, build_sha=_TIP, tip_age_seconds=10.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.UNKNOWN
    assert result.should_alert


@pytest.mark.parametrize("missing", ["", None, "   "])
def test_an_unreachable_build_sha_is_unknown_and_alerts(
    drift: ModuleType, missing: str | None
) -> None:
    """`/status` is a network call; unreachable must not read as healthy."""
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=missing, tip_age_seconds=10.0, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.UNKNOWN
    assert result.should_alert


def test_an_unknown_tip_age_is_unknown_not_silently_in_flight(drift: ModuleType) -> None:
    """If we cannot tell how long they have differed, say so rather than wait.

    Defaulting to DEPLOY_IN_FLIGHT would make a permanent drift invisible for
    as long as the age stayed unreadable.
    """
    result = drift.evaluate_drift(
        main_tip=_TIP, build_sha=_OLD, tip_age_seconds=None, grace_seconds=600.0
    )
    assert result.decision is drift.DriftDecision.UNKNOWN
    assert result.should_alert


def test_comparison_ignores_case_and_surrounding_whitespace(drift: ModuleType) -> None:
    result = drift.evaluate_drift(
        main_tip=f"  {_TIP.upper()}  ",
        build_sha=_TIP,
        tip_age_seconds=99999.0,
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
    assert drift.DEFAULT_GRACE_SECONDS > 2071
    assert drift.DEFAULT_GRACE_SECONDS <= 3600


def test_a_drift_that_outlives_the_shipped_grace_alerts(drift: ModuleType) -> None:
    """Ties the shipped constant to behaviour, not just to a numeric range."""
    result = drift.evaluate_drift(
        main_tip=_TIP,
        build_sha=_OLD,
        tip_age_seconds=drift.DEFAULT_GRACE_SECONDS + 1.0,
        grace_seconds=drift.DEFAULT_GRACE_SECONDS,
    )
    assert result.decision is drift.DriftDecision.DRIFTED


# --- the reporting contract -----------------------------------------------


def test_every_decision_reports_what_it_compared(drift: ModuleType) -> None:
    """A gate must report what it counted.

    Every branch's detail names both SHAs (or says plainly that one was
    unreadable), so the alert is actionable without re-running anything.
    """
    cases = [
        dict(main_tip=_TIP, build_sha=_TIP, tip_age_seconds=1.0),
        dict(main_tip=_TIP, build_sha=_OLD, tip_age_seconds=1.0),
        dict(main_tip=_TIP, build_sha=_OLD, tip_age_seconds=99999.0),
        dict(main_tip=None, build_sha=_TIP, tip_age_seconds=1.0),
        dict(main_tip=_TIP, build_sha=None, tip_age_seconds=1.0),
    ]
    for case in cases:
        result = drift.evaluate_drift(grace_seconds=600.0, **case)
        assert result.detail.strip(), f"empty detail for {case}"
        assert len(result.detail) > 20, f"uninformative detail for {case}: {result.detail!r}"


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
    pairs = re.findall(r'"([^":]+):([A-Za-z0-9._-]+\.yml)"', watchdog)
    assert pairs, 'no "<name>:<file>" dispatch pairs found in the watchdog'

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
