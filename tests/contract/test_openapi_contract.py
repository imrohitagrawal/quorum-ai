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
    ``{round_number, focus_areas, critique_text, status}``.
    """
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    debate = spec["components"]["schemas"]["DebateOutput"]
    assert set(debate["properties"]) == {
        "round_number",
        "focus_areas",
        "critique_text",
        "status",
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


def test_debate_round_status_enum_is_current() -> None:
    """DebateRoundStatus is ``{completed, skipped}`` (not ``skipped_timeout``)."""
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    enum = spec["components"]["schemas"]["DebateRoundStatus"]["enum"]
    assert sorted(enum) == ["completed", "skipped"]
    assert "skipped_timeout" not in enum
