"""Peer critique must be visible from outside the process.

Why this file exists
--------------------
Measured 2026-09-03, on the deploy that turned peer critique ON in production
(``6d13643``): ``/status``, ``/ready``, ``/metrics`` and ``/ui/ops`` reported
NOTHING about ``PEER_CRITIQUE_ENABLED``, and ``scripts/live_posture_check.py``
— the watchdog scheduled every 30 minutes against what production actually
serves — never read it either. So the operator's answer to "is the expensive
debate shape on?" was "read fly.toml and hope the deploy matches".

That is the exact fault ADR-0013 named, one subsystem over: **a paid subsystem
may not be enabled invisibly.** Peer critique replaces 2 moderator calls with
up to 8 critic calls, at four models' prices.

What this is NOT
----------------
Peer critique does not get a per-window ``"peer_critique": true`` declaration
the way the judge does, and that asymmetry is deliberate — see ADR-0097. The
judge needs one because its GET-path spend reaches NO ledger (ADR-0013), so
nothing else binds it. Critique spend is inside the run charge
(``costs.build_measured_breakdown`` keeps it under ``debate_total``, which is
inside ``raw_total``) and every critic call routes through
``_call_debate_model``, which returns ``None`` unless
``openrouter_live_execution_enabled`` is on. So the live-window gate that
already exists binds the money; what was missing was the ability to SEE it.

The contract pinned here
------------------------
* ``/status`` carries a boolean ``peer_critique_enabled``.
* It CANNOT DRIFT from the behaviour it describes: the last test drives the
  real dispatch gate (``_build_peer_round``) and requires the two to agree.

Hermetic: live execution is pinned off throughout, so no test here can dispatch
a paid call even when the flag under test is on.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from product_app.config import settings
from product_app.main import app


def _status(client: TestClient) -> dict[str, object]:
    response = client.get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("enabled", [True, False])
def test_status_reports_whether_peer_critique_is_on(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """RED IF: ``/status`` drops ``peer_critique_enabled``, or hardcodes it.

    What turns it red: delete the key from ``status_snapshot``, or replace the
    settings read with a literal. Both directions are asserted, so a constant
    ``True`` fails on the False case and vice versa.
    """
    monkeypatch.setattr(settings, "peer_critique_enabled", enabled)
    payload = _status(TestClient(app))

    assert "peer_critique_enabled" in payload, (
        "/status no longer reports peer_critique_enabled, so an operator "
        "cannot tell from outside whether the expensive debate shape is on. "
        "ADR-0013: a paid subsystem may not be enabled invisibly."
    )
    assert payload["peer_critique_enabled"] is enabled
    # A boolean, not a truthy string: the watchdog thresholds this.
    assert isinstance(payload["peer_critique_enabled"], bool)


def test_status_reports_the_judge_and_peer_critique_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: the two paid-subsystem flags are wired to one another.

    They are separate switches on separate subsystems and either can be on
    alone. A copy-paste that pointed the new field at ``judge_configured()``
    would pass the test above whenever the two happened to agree.
    """
    monkeypatch.setattr(settings, "peer_critique_enabled", True)
    payload = _status(TestClient(app))

    assert payload["peer_critique_enabled"] is True
    # The judge is NOT configured in the test environment, so if the new field
    # were reading the judge's predicate it would be False here.
    assert payload["judge_enabled"] is False
    assert payload["peer_critique_enabled"] != payload["judge_enabled"]


@pytest.mark.parametrize("enabled", [True, False])
def test_the_reported_state_matches_the_real_dispatch_gate(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    """RED IF: ``/status`` and the real peer-critique gate disagree.

    This is the test that makes the field trustworthy rather than decorative.
    ``_build_peer_round`` is what actually decides whether critic calls are
    dispatched; ``peer_critique_enabled`` is what an operator reads. They must
    be ONE predicate, so a future edit to either goes red here.

    Hermetic by construction: live execution is pinned OFF, so the round can
    reach no provider. That makes ``None`` ambiguous on its own — it is also
    what the flag-off path returns — so the assertion below distinguishes the
    two by patching the dispatch seam and counting whether the gate got as far
    as ASKING for critics.

    What turns it red: flip the sense of the flag in ``_build_peer_round``, or
    report a constant on ``/status``.
    """
    from product_app import debate as debate_module

    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "peer_critique_enabled", enabled)

    asked: list[int] = []
    real_eligible = debate_module.DebateOrchestrationService._eligible_critics

    def _spy(answers: object) -> object:
        # A STATICMETHOD on the real class -- patched as one, because binding it
        # as an instance method changes the arity and the call raises TypeError
        # before the gate is ever reached, which would make this test green for
        # the wrong reason on the flag-off case.
        asked.append(1)
        return real_eligible(answers)  # type: ignore[arg-type]

    monkeypatch.setattr(
        debate_module.DebateOrchestrationService,
        "_eligible_critics",
        staticmethod(_spy),
    )

    reported = _status(TestClient(app))["peer_critique_enabled"]

    debate_module.debate_stub_service._build_peer_round(
        round_number=1,
        system_prompt="s",
        initial_answers=[],
        query_text="q",
        prior_round=None,
        openrouter_key="sk-or-test",
        query_run_id=uuid4(),
        context=None,
        should_stop=None,
    )

    gate_ran = bool(asked)
    assert reported is enabled
    assert gate_ran is enabled, (
        "the /status field and the real dispatch gate disagree: /status says "
        f"{reported!r} but _build_peer_round "
        f"{'did' if gate_ran else 'did NOT'} get past its flag check"
    )
