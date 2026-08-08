"""ADR-0028: spend belongs on the stage the user reads.

The debate stage's own system prompts end "The output is for a human reviewer,
not the user" — its text is never rendered. The synthesis IS the answer. Until
2026-08-08 the debate ran on the most expensive of the three stage models and
the synthesis on the cheapest.

These pins are deliberately LITERAL on both sides (rule 7a): asserting a stage's
model against ``settings.<that stage>_model_id`` would pass against every
allocation, including the one this ADR reversed.

Turns red if: either default is changed without revisiting ADR-0028, or the
workspace info text stops naming the model that actually writes the synthesis.
"""

from __future__ import annotations

import re
from pathlib import Path

from product_app.config import Settings, settings

_TEMPLATE = Path(__file__).resolve().parents[2] / "src/product_app/templates/workspace.html"


def _default(field: str) -> str:
    """The SHIPPED default, not whatever the ambient env happens to set."""
    return str(Settings.model_fields[field].default)


def test_the_debate_runs_on_the_cheap_model_and_synthesis_on_the_better_one() -> None:
    assert _default("debate_model_id") == "openai/gpt-4o-mini"
    assert _default("synthesis_model_id") == "openai/gpt-5-mini"


def test_the_three_stage_models_are_all_distinct_roles() -> None:
    """POSITIVE PARTNER for the pins above: an allocation that collapsed every
    stage onto one id would satisfy a naive "synthesis is not gpt-4o-mini"
    check while destroying the judge's independence.
    """
    # The judge ships UNCONFIGURED — empty model id AND empty key — which is
    # why ``judge_configured()`` is false and ``/status.judge_enabled`` reports
    # false in production. Pinned because this change must not switch it on as
    # a side effect: enabling the judge is an operator decision with its own
    # cost, not something a model-allocation PR does silently.
    assert _default("quorum_eval_judge_model_id") == ""
    assert _default("quorum_eval_judge_api_key") == ""
    # The two stages that DO ship configured must stay on different models, or
    # the ADR-0028 cost argument collapses.
    assert _default("debate_model_id") != _default("synthesis_model_id"), (
        "debate and synthesis are on the same model; the ADR-0028 split is gone"
    )


def test_the_workspace_info_text_names_the_model_that_really_writes_synthesis() -> None:
    """The tooltip tells the user which model wrote what they are reading.

    Turns red if: ``synthesis_model_id`` changes and this string does not — the
    exact drift that made the text false the moment the models were swapped.
    """
    html = _TEMPLATE.read_text(encoding="utf-8")
    pattern = r"The synthesis is written by a single configured model \(currently ([^)]+)\)"
    claimed = re.findall(pattern, html)
    assert len(claimed) == 1, f"expected exactly one synthesis attribution, found {len(claimed)}"
    assert claimed[0] == settings.synthesis_model_id, (
        f"the workspace tells the user the synthesis comes from {claimed[0]!r}, "
        f"but it is actually written by {settings.synthesis_model_id!r}"
    )
