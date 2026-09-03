"""OpenAPI contract drift-guard.

The checked-in ``openapi.yaml`` is a generated artifact (see
``scripts/export_openapi.py``). These tests are the self-enforcing guard the
CI ``validate-and-test`` job runs (via ``make test-report``): if the FastAPI
routes/models change without a regen, or the spec is hand-edited, the
checked-in bytes stop matching ``app.openapi()`` and the guard fails.

The suite proves the guard in BOTH directions:

* :func:`test_openapi_yaml_matches_app_openapi` — the committed spec equals a
  fresh render of ``app.openapi()`` (a real regen passes).
* :func:`test_drift_guard_detects_mutation` — a deliberately mutated schema
  renders to something the committed spec does NOT equal (a real drift fails).

It also pins the specific fields the P1A regen corrected so the intent can't
silently regress.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = str(ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from export_openapi import (  # noqa: E402  (path set up above)
    OPENAPI_PATH,
    load_openapi_schema,
    render_current,
    render_openapi_yaml,
)
from validate_openapi_contract import check  # noqa: E402  (path set up above)


def test_openapi_yaml_matches_app_openapi() -> None:
    """The committed openapi.yaml is byte-for-byte a fresh regen."""
    expected = render_current()
    actual = OPENAPI_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "openapi.yaml has drifted from app.openapi(). "
        "Regenerate it with: python scripts/export_openapi.py"
    )


def test_guard_passes_on_faithful_render(tmp_path: Path) -> None:
    """The real guard (``check``) returns 0 for a spec that is a true regen."""
    faithful = tmp_path / "openapi.yaml"
    faithful.write_text(render_current(), encoding="utf-8")
    assert check(faithful) == 0


def test_guard_detects_appended_drift(tmp_path: Path) -> None:
    """The real guard fails when the committed bytes drift from the render.

    Drives ``validate_openapi_contract.check`` — the exact comparison the CI
    step performs — against a tampered copy, so this exercises the guard's
    real logic (not a stand-in), proving the failure direction end-to-end.
    """
    drifted = tmp_path / "openapi.yaml"
    drifted.write_text(render_current() + "\n# unauthorized hand-edit\n", encoding="utf-8")
    assert check(drifted) == 1


def test_guard_detects_unregenerated_schema_change(tmp_path: Path) -> None:
    """A code-side schema change that was NOT regenerated is caught.

    Simulates the real bug class: the app's schema changed (here we re-add the
    phantom ``contributing_models`` field that P1A removed) but ``openapi.yaml``
    was left as the prior render. The guard compares the stale file against the
    live ``render_current()`` and must flag the drift.
    """
    schema = copy.deepcopy(load_openapi_schema())
    debate = schema["components"]["schemas"]["DebateOutput"]
    debate["properties"]["contributing_models"] = {
        "items": {"type": "string"},
        "type": "array",
        "title": "Contributing Models",
    }
    # The file reflects the MUTATED schema, while the live app (what
    # ``check`` renders internally) does not — exactly an un-regenerated drift.
    stale = tmp_path / "openapi.yaml"
    stale.write_text(render_openapi_yaml(schema), encoding="utf-8")
    assert check(stale) == 1
    assert render_openapi_yaml(schema) != render_current()


def test_debate_output_fields_are_current() -> None:
    """Pin the exact DebateOutput contract the P1A regen corrected.

    The stale spec declared ``contributing_models``/``latency_ms``/
    ``provider_notice`` (which do not exist on the model) and a wrong
    ``required`` list; the real model is
    ``{round_number, focus_areas, critique_text, status, debate_mode}``.
    ``debate_mode`` (#171 finding 5) is the per-round structural provenance —
    ``"live"`` or ``"fallback"`` — added so a templated debate round can be
    told apart from a real moderator's output; it carries a default so it
    stays out of ``required``.
    """
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    debate = spec["components"]["schemas"]["DebateOutput"]
    assert set(debate["properties"]) == {
        "round_number",
        "focus_areas",
        "critique_text",
        "status",
        "debate_mode",
        # #354: the moderator's structured reading of where each model stands.
        # Carries a default (``None``) so it stays out of ``required``, same as
        # ``debate_mode``.
        "panel_stance",
        # #290 / ADR-0093 decision 1. Both carry defaults, so both stay out of
        # ``required`` and every existing client keeps parsing unchanged. This
        # is the shape that keeps ONE element per round: the rejected
        # alternative, one row per ``(round, model)``, would have needed no
        # schema change at all and would have told the user a two-round run had
        # eight rounds.
        "critique_shape",
        "slot_critiques",
        # The DENOMINATOR every panel-level claim about a peer round is measured
        # against. Published because a consumer reading `slot_critiques` without
        # it would compute the same two fail-opens adversarial review found —
        # a cancel raising the verdict, and one critic of four carrying the
        # panel. Defaulted 0, so it stays out of `required`.
        "eligible_critic_count",
    }
    for phantom in ("contributing_models", "latency_ms", "provider_notice"):
        assert phantom not in debate["properties"], (
            f"stale phantom field {phantom!r} is back on DebateOutput"
        )
    assert debate["required"] == [
        "round_number",
        "focus_areas",
        "critique_text",
        "status",
    ]


def test_the_slot_critique_schema_is_published_and_additive() -> None:
    """RED WHEN: ``SlotCritique`` stops being published, or gains a required field.

    #290 / ADR-0093. ``DebateOutput`` is a published schema and ``openapi.yaml``
    is byte-compared, so nesting the peer detail adds a component every client
    can see. Three fields are required and three carry defaults — the defaults
    are what let a moderator-shaped round, which is what ships, serialise
    unchanged.

    ``critic_slot_number`` is bounded 1..4 because that is the panel size the
    rest of the model already asserts (``model_slots.EXPECTED_SLOT_COUNT``); a
    fifth critic would be a slot that does not exist.
    """
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    critique = spec["components"]["schemas"]["SlotCritique"]
    assert set(critique["properties"]) == {
        "critic_slot_number",
        "critic_model_id",
        "critique_text",
        "focus_areas",
        "critique_mode",
        "stance",
        # ADR-0096's convergence contract. All four carry defaults, so they stay
        # out of `required` and a moderator-shaped round still serialises.
        #
        # `position_rationale`, NOT `rationale`:
        # `test_evaluation_projection_has_no_judge.py` bans that key at ANY
        # depth of the served response, because a JUDGE's rationale is free text
        # about provider prose and must never reach a client. This is a
        # different thing — a critic's words about its own answer — but the ban
        # is a bare-name one, and a bare-name ban is stronger than a path-aware
        # one. Renaming cost nothing; excepting the guard would have cost the
        # guarantee.
        "self_assessment",
        "position_rationale",
        "cited_sources",
        "revised_answer",
    }
    assert critique["required"] == [
        "critic_slot_number",
        "critic_model_id",
        "critique_text",
    ]
    slot = critique["properties"]["critic_slot_number"]
    assert (slot["minimum"], slot["maximum"]) == (1, 4)
    # The defaulted three are what keep the change additive for a client that
    # has never seen a peer round.
    assert critique["properties"]["critique_mode"]["default"] == "fallback"


def test_debate_round_status_enum_is_current() -> None:
    """DebateRoundStatus is ``{completed, skipped}`` (not ``skipped_timeout``)."""
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    enum = spec["components"]["schemas"]["DebateRoundStatus"]["enum"]
    assert sorted(enum) == ["completed", "skipped"]
    assert "skipped_timeout" not in enum
