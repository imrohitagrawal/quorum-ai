"""Every production `StrEnum`'s exhaustive membership is pinned to a literal
set of values.

**The gap this closes (#160).** Measured 2026-07-29 by an AST walk over
`src/product_app`: 14 enums declared, 3 exhaustively pinned (`BillableStage`,
`StageBillingState`), 11 not. A same-day correction (issue comment) found the
grep's third "pinned" name, `WarningType`, was wrong — its only test
assertions are single-member comparisons, which a new member would not touch.
**The corrected count was 2 of 14 pinned, 12 unpinned.**

Re-measured here with `grep -rn "class.*StrEnum" src/product_app/`: **17**
`StrEnum` classes exist, not 14 — three more than either prior count, found
because this file counts them itself rather than trusting the issue text
(rule 1). Of the 17: `query_run_orchestration.BillableStage` and
`query_run_orchestration.StageBillingState` are exhaustively pinned via the
whole-dict equality in `tests/unit/test_stage_billing_gate.py:267` (proven by
execution there — adding a third `BillableStage` member turns 6 tests red),
and `providers.ProviderPath` is exhaustively pinned via the
`set(ProviderPath) == NOT_INVOKED_PATHS | INVOKED_PATHS` partition in
`tests/unit/test_not_invoked_is_not_evidence.py`. The other 14, including
`WarningType`, have no exhaustive pin anywhere before this file.

(`BillableStage` and its three siblings originally lived in `query_runs.py`
and are named that way above and in `tests/unit/test_stage_billing_gate.py`,
since that history is what the numbers describe. They moved to
`query_run_orchestration.py` in the `query_runs.py` module split (ADR-0036,
#303), which merged to `main` after this file was first written; `query_runs`
still re-exports all four names for backward compatibility, but the AST walk
below finds a class only where it is actually DEFINED, so `ENUM_MODULES` and
`ENUM_MEMBER_PINS` key off `query_run_orchestration` now — rebasing this
branch onto that merge is what surfaced the mismatch.)

**Why membership matters, proven both directions (issue #160):**

* Pinned set, member added: adding a third `BillableStage` turned 6 tests
  red immediately — the author is forced to decide what the new stage means.
* Unpinned set, member added: adding a 14th `QueryRunStatus` and deliberately
  omitting it from `TERMINAL_STATUSES` left `mypy` green (a
  `dict[QueryRunStatus, ...]` is not exhaustiveness-checked) and the full
  suite green apart from a schema-shape test that regenerating `openapi.yaml`
  would clear — the omission would ship. This is the shape of F-05 ("a
  terminal run is final in EVERY field"), which already cost a 989-line fix.

**Design, following #145's registry pattern**: `_production_enum_classes`
is the "fixed detector" — an AST walk, not a count carried in prose, so it
cannot go stale the way the issue's own "fourteen" and "sixteen" did.
`test_every_production_enum_is_registered` forces every discovered class into
`ENUM_MEMBER_PINS` (or fails naming it), and `ENUM_MEMBER_PINS` values are
typed by hand from the values, independent of the enum's own source, so a
member add/remove/rename actually changes what the pin compares against —
the same reasoning `test_risk_constant_pins.py` uses for bucket A.
"""

from __future__ import annotations

import ast
import pathlib

from product_app import (
    auth,
    config,
    costs,
    debate,
    evaluation,
    feedback_store,
    provider_keys,
    providers,
    query_run_orchestration,
    safety,
    synthesis,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "product_app"

#: Every module known to declare a production `StrEnum`. Verified 2026-08-14:
#: `grep -rln "class.*StrEnum" src/product_app/*.py` names exactly these 11
#: files. If a 12th module adds one, `test_the_registry_is_not_empty`'s floor
#: still passes (nothing here shrinks silently), but the new module's enum
#: would not be discovered until added here — the same known limitation
#: `RISK_TIER_MODULES` in `test_risk_constant_pins.py` documents for itself.
ENUM_MODULES = (
    "auth.py",
    "config.py",
    "costs.py",
    "debate.py",
    "evaluation.py",
    "feedback_store.py",
    "provider_keys.py",
    "providers.py",
    "query_run_orchestration.py",
    "safety.py",
    "synthesis.py",
)

_CLASSES_BY_QUALIFIED_NAME = {
    "auth.AuthError": auth.AuthError,
    "config.RuntimeEnvironment": config.RuntimeEnvironment,
    "costs.CostThresholdAction": costs.CostThresholdAction,
    "debate.DebateRoundStatus": debate.DebateRoundStatus,
    "debate.AlignmentState": debate.AlignmentState,
    "debate.FinalAnswerProvenance": debate.FinalAnswerProvenance,
    "evaluation.JudgeCallOutcome": evaluation.JudgeCallOutcome,
    "feedback_store.ChargeOutcome": feedback_store.ChargeOutcome,
    "provider_keys.ProviderCredentialSource": provider_keys.ProviderCredentialSource,
    "providers.InitialAnswerStatus": providers.InitialAnswerStatus,
    "providers.ProviderPath": providers.ProviderPath,
    "query_run_orchestration.QueryRunStatus": query_run_orchestration.QueryRunStatus,
    "query_run_orchestration.StageState": query_run_orchestration.StageState,
    "query_run_orchestration.BillableStage": query_run_orchestration.BillableStage,
    "query_run_orchestration.StageBillingState": query_run_orchestration.StageBillingState,
    "query_run_orchestration.JudgeSuppressionReason": (
        query_run_orchestration.JudgeSuppressionReason
    ),
    "safety.WarningType": safety.WarningType,
    "synthesis.SynthesisStatus": synthesis.SynthesisStatus,
}


def _production_enum_classes() -> dict[str, int]:
    """`module.ClassName` -> member count, for every `StrEnum` in
    `ENUM_MODULES`.

    AST-based, per file — not a grep over concatenated sources, and not a
    count typed in prose. This is what makes the discovery self-correcting:
    it is re-run on every test session, not re-measured by hand.
    """
    found: dict[str, int] = {}
    for name in ENUM_MODULES:
        path = SRC / name
        if not path.is_file():
            continue
        module = path.stem
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if "StrEnum" not in base_names:
                continue
            count = sum(1 for stmt in node.body if isinstance(stmt, ast.Assign))
            found[f"{module}.{node.name}"] = count
    return found


#: `module.ClassName` -> the exact literal set of member VALUES (a `StrEnum`
#: member's value is what actually crosses the API/DB boundary, not its
#: Python name). Typed by hand from the source, independent of it, so a
#: member add/remove/rename in `src/` actually changes what this compares
#: against — the same reasoning bucket A uses in `test_risk_constant_pins.py`.
#:
#: `providers.ProviderPath`, `query_run_orchestration.BillableStage` and
#: `query_run_orchestration.StageBillingState` are ALSO pinned exhaustively
#: elsewhere (see module docstring) — included here too so this file is a
#: complete, single-purpose record of every production enum's membership,
#: not just the previously-gap ones. Redundancy here is cheap and costs
#: nothing but a few lines.
ENUM_MEMBER_PINS: dict[str, frozenset[str]] = {
    "auth.AuthError": frozenset({"AUTH_REQUIRED", "SESSION_EXPIRED", "CSRF_INVALID"}),
    "config.RuntimeEnvironment": frozenset({"local", "staging", "production"}),
    "costs.CostThresholdAction": frozenset({"allow", "require_confirmation", "block"}),
    "debate.DebateRoundStatus": frozenset({"completed", "skipped"}),
    "debate.AlignmentState": frozenset(
        {
            "not_invoked",
            "no_answer",
            "held_with_consensus",
            "moved_to_consensus",
            "held_minority",
        }
    ),
    "debate.FinalAnswerProvenance": frozenset({"model_authored", "not_model_authored"}),
    "evaluation.JudgeCallOutcome": frozenset(
        {
            "verdict",
            "no_verdict_dispatched",
            "no_verdict_unbilled",
            "no_verdict_error",
        }
    ),
    "feedback_store.ChargeOutcome": frozenset(
        {"recorded", "over_daily_cap", "over_global_ceiling", "metering_unavailable"}
    ),
    "provider_keys.ProviderCredentialSource": frozenset(
        {"app_owned", "not_configured", "byo_openrouter"}
    ),
    "providers.InitialAnswerStatus": frozenset({"completed", "failed"}),
    "providers.ProviderPath": frozenset(
        # "web_search" added by ADR-0098: a page a REAL search returned, split
        # out of "fallback_search" so it is distinguishable from the
        # example.test placeholder this product writes for itself.
        {"local_simulation", "openrouter_search", "fallback_search", "web_search"}
    ),
    "query_run_orchestration.QueryRunStatus": frozenset(
        {
            "draft",
            "cost_review",
            "accepted",
            "initial_answers_running",
            "debate_round_1_running",
            "debate_round_2_running",
            "synthesis_running",
            "completed",
            "partial",
            "failed",
            "timed_out",
            "blocked_by_cost",
            "cancelled",
        }
    ),
    "query_run_orchestration.StageState": frozenset(
        {"pending", "running", "completed", "failed", "skipped"}
    ),
    "query_run_orchestration.BillableStage": frozenset({"debate", "synthesis"}),
    "query_run_orchestration.StageBillingState": frozenset({"not_entered", "entered", "recorded"}),
    "query_run_orchestration.JudgeSuppressionReason": frozenset(
        {"spend_rail_preflight", "inflight_owner_lost", "inflight_timeout"}
    ),
    "safety.WarningType": frozenset({"sensitive_data", "high_stakes"}),
    "synthesis.SynthesisStatus": frozenset({"completed", "failed"}),
}


def test_the_registry_is_not_empty() -> None:
    """A guard over an empty collection proves nothing.

    Turns red if: the discovery regex/`ENUM_MODULES` stops matching.
    """
    discovered = _production_enum_classes()
    assert len(discovered) >= 17, f"only {len(discovered)} StrEnum classes discovered"
    assert ENUM_MEMBER_PINS


def test_every_production_enum_is_registered() -> None:
    """A new `StrEnum` in a listed module must get a membership pin.

    This is the load-bearing test. Without it, a 12th risk-relevant enum
    could be added with no pin and nothing would notice — the exact state
    #160 measured (11+ of 17 with none).

    Turns red if: a `StrEnum` class is added to (or removed from) one of
    `ENUM_MODULES` without updating `ENUM_MEMBER_PINS`.
    """
    discovered = set(_production_enum_classes())
    registered = set(ENUM_MEMBER_PINS)
    missing = sorted(discovered - registered)
    assert not missing, (
        f"StrEnum classes with no membership pin: {missing}. Add an entry to "
        "ENUM_MEMBER_PINS with the exact literal set of member values."
    )
    stale = sorted(registered - discovered)
    assert not stale, f"ENUM_MEMBER_PINS names classes that no longer exist: {stale}"


def test_every_registered_enum_membership_matches_its_pin() -> None:
    """The exhaustive pin itself.

    Turns red if: ANY production `StrEnum` gains, loses, or renames a member
    — because `ENUM_MEMBER_PINS` is typed independently of the enum's own
    source, not derived from it. Proven by execution: adding an 18th member
    to `query_run_orchestration.QueryRunStatus` (`ABANDONED = "abandoned"`) reds this
    test's `query_run_orchestration.QueryRunStatus` assertion; the mutation is reverted
    immediately after, per rule 6.
    """
    for qualified, expected in ENUM_MEMBER_PINS.items():
        enum_class = _CLASSES_BY_QUALIFIED_NAME[qualified]
        actual = frozenset(member.value for member in enum_class)
        assert actual == expected, (
            f"{qualified}: pinned {sorted(expected)}, actual {sorted(actual)}"
        )


def test_every_registered_enum_has_at_least_two_members() -> None:
    """Positive partner (rule 7) for the equality check above: a `StrEnum`
    pinned to an empty or singleton set would make the equality check above
    pass trivially over nothing meaningful. Every enum in this repo models a
    real branch point, so every one has at least two members.

    Turns red if: a pin is added for an enum with fewer than two members
    (which would itself be a modelling smell worth a second look).
    """
    thin = sorted(name for name, values in ENUM_MEMBER_PINS.items() if len(values) < 2)
    assert not thin, f"enums pinned with fewer than two members: {thin}"
