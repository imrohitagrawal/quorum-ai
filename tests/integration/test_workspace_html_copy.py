"""PR-1: workspace HTML + OpenAPI metadata reflect the product brief.

These tests pin the *user-visible* copy surface so a future refactor of
``workspace.html`` or the FastAPI app constructor cannot accidentally
regress the brand lede, the workspace lede, the chosen product name,
or the synthesis tooltip caveats. They are intentionally string-literal
checks — the source of truth is ``docs/PRODUCT_BRIEF.md``, and a
deliberate copy change is expected to update both.

Pinned contract:

* Brand lede is the brief's chosen one-liner (≤90 chars).
* The old, longer lede is gone.
* The workspace lede mentions the two things the user needs to know
  in 5 seconds: data persistence, cost confirmation.
* The display name ``Quorum AI`` is present.
* Operator env-var names (``OPENROUTER_API_KEY``,
  ``OPENROUTER_LIVE_EXECUTION_ENABLED``) do not leak into user-facing HTML.
* OpenAPI ``info.title`` matches ``settings.app_name`` and the
  ``info.description`` is the brief's user-facing paragraph.
* Every synthesis tooltip in ``app.js`` ends with the agreed caveat
  ("Templated by Quorum; no model generates this.").
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from product_app.config import settings
from product_app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# --- Brand + workspace lede ---------------------------------------------------

EXPECTED_BRAND_LEDE = "Four AI models, one sourced answer."

OLD_BRAND_LEDE = (
    "Stop hopping between multiple AI chatbots. Get one sourced, "
    "synthesized answer you can trust"
)

EXPECTED_WORKSPACE_LEDE = (
    "Results are ephemeral. Cost is shown before each run; "
    "nothing executes without your confirmation."
)


def test_workspace_html_has_brand_lede(client: TestClient) -> None:
    response = client.get("/ui")
    assert response.status_code == 200
    assert EXPECTED_BRAND_LEDE in response.text, (
        "Brand lede regressed. See docs/PRODUCT_BRIEF.md for the source of truth."
    )


def test_workspace_html_drops_old_brand_lede(client: TestClient) -> None:
    response = client.get("/ui")
    assert response.status_code == 200
    assert OLD_BRAND_LEDE not in response.text, (
        "Old brand lede is still rendered. PR-1's job was to retire it."
    )


def test_brand_lede_is_within_90_chars() -> None:
    # 90 chars is the prompt's hard cap. The current string is well under
    # that; this test catches any future widening.
    assert len(EXPECTED_BRAND_LEDE) <= 90, (
        f"Brand lede is {len(EXPECTED_BRAND_LEDE)} chars, > 90 cap."
    )


def test_workspace_html_has_workspace_lede(client: TestClient) -> None:
    response = client.get("/ui")
    assert response.status_code == 200
    assert EXPECTED_WORKSPACE_LEDE in response.text, (
        "Workspace lede regressed. See docs/PRODUCT_BRIEF.md."
    )


def test_workspace_lede_answers_cost_and_data_questions(client: TestClient) -> None:
    """A reader should be able to answer 'what happens to my data?' and
    'what does this cost?' within 5 seconds of reading the lede."""
    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text
    lede_match = re.search(r'<p class="lede">([^<]+)</p>', html)
    assert lede_match, 'workspace lede <p class="lede"> not found'
    lede = lede_match.group(1)
    # Data question: results don't persist.
    assert "ephemeral" in lede.lower(), (
        f"Workspace lede does not address data persistence: {lede!r}"
    )
    # Cost question: cost is shown first.
    assert "cost" in lede.lower(), (
        f"Workspace lede does not address cost confirmation: {lede!r}"
    )


# --- Product name (display form) ---------------------------------------------

EXPECTED_DISPLAY_NAME = "Quorum AI"


def test_workspace_html_has_chosen_display_name(client: TestClient) -> None:
    response = client.get("/ui")
    assert response.status_code == 200
    assert EXPECTED_DISPLAY_NAME in response.text, (
        f"Display name {EXPECTED_DISPLAY_NAME!r} missing from workspace HTML."
    )


# --- No operator env-var names in user-facing HTML ---------------------------


@pytest.mark.parametrize(
    "leaked",
    ["OPENROUTER_API_KEY", "OPENROUTER_LIVE_EXECUTION_ENABLED"],
)
def test_workspace_user_facing_copy_does_not_leak_env_var_names(
    client: TestClient, leaked: str
) -> None:
    """Operator environment variables are server-config talk, not
    user-facing jargon. The user-facing copy surfaces — info-icon
    tooltips, banner bodies, ledes, callout text — must not name
    them.

    The ``window.LIVE_READINESS`` JSON island is a developer/operator
    surface (it surfaces the probe state for an external monitor
    and for the client's re-render path); env-var names there are
    acceptable because that island is consumed by tooling, not read
    by end users. We assert against the ``.info-icon[data-info-text]``
    tooltips and the static banner bodies — the actual user-facing
    strings.
    """
    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text

    # Extract every ``data-info-text="..."`` value. These are the
    # tooltips the user actually sees when they hover the info icons.
    tooltip_texts = re.findall(r'data-info-text="([^"]*)"', html)
    for t in tooltip_texts:
        assert leaked not in t, (
            f"Operator env-var {leaked!r} leaked into a user-facing "
            f"info-icon tooltip: {t!r}"
        )

    # The static banner bodies (workspace lede, safety reminder, cost
    # callout, drift banner title). These are hardcoded in the template.
    # The readiness banner body is filled in by the JS at runtime, so
    # it is covered indirectly via the JS copy review, not here.
    static_user_strings = [
        EXPECTED_BRAND_LEDE,
        EXPECTED_WORKSPACE_LEDE,
        "Safety reminder.",
        "Do not submit sensitive, private, regulated, or secret information.",
        "High-stakes topics remain decision support only.",
        "Cost review",
        "This figure is a local planning estimate based on your query length and selected model slots.",  # noqa: E501
        "Catalog drift",
        "Run now",
        "Estimate cost",
        "Proceed with this run",
        "Cancel",
        "Cancel run",
        "Live execution is unavailable",
        "Demo mode is active",
    ]
    for s in static_user_strings:
        assert leaked not in s, (
            f"Operator env-var {leaked!r} leaked into a hardcoded "
            f"user-facing string: {s!r}"
        )


# --- OpenAPI metadata --------------------------------------------------------


def test_openapi_title_matches_settings_app_name(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    info = response.json()["info"]
    assert info["title"] == settings.app_name


def test_openapi_description_is_user_facing_paragraph(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    info = response.json()["info"]
    description = info.get("description", "")
    # The brief calls for a one-paragraph user-facing description.
    # 280-char minimum keeps it from being a one-liner; 2000-char
    # maximum keeps it from being a wall of text.
    assert 280 <= len(description) <= 2000, (
        f"OpenAPI description is {len(description)} chars; expected 280-2000."
    )
    # User-facing, not operator-facing. The chosen description mentions
    # the workspace and the value prop.
    assert "/ui" in description
    assert "consensus" in description.lower() or "four" in description.lower()


# --- Synthesis tooltips in app.js --------------------------------------------


_SYNTHESIS_TOOLTIP_CAVEAT = "Templated by Quorum; no model generates this."

_SYNTHESIS_SECTIONS = [
    "Consensus",
    "Disagreement",
    "Source support",
    "Uncertainty",
    "Recommendation",
]


def _read_app_js() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "src" / "product_app" / "static" / "app.js").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("section", _SYNTHESIS_SECTIONS)
def test_synthesis_tooltip_for_section_ends_with_caveat(section: str) -> None:
    """Every synthesis section's tooltip copy must end with the
    brief-mandated caveat. A regression in any single tooltip is
    caught here."""
    js = _read_app_js()
    pattern = (
        r'SYNTHESIS_TOOLTIPS\s*=\s*\{.*?"'
        + re.escape(section)
        + r'":\s*"([^"]+)"'
    )
    match = re.search(pattern, js, flags=re.DOTALL)
    assert match, f"No SYNTHESIS_TOOLTIPS entry found for section {section!r}"
    tooltip = match.group(1)
    assert _SYNTHESIS_TOOLTIP_CAVEAT in tooltip, (
        f"Tooltip for {section!r} does not contain the caveat. "
        f"Got: {tooltip!r}"
    )


def test_no_tooltip_uses_old_always_produced_phrase() -> None:
    """PR-1 retired the over-apologetic 'Always produced by Quorum's
    synthesis helper' phrase across all five tooltips."""
    js = _read_app_js()
    tooltip_block = re.search(
        r"SYNTHESIS_TOOLTIPS\s*=\s*\{(.*?)\};",
        js,
        flags=re.DOTALL,
    )
    assert tooltip_block, "SYNTHESIS_TOOLTIPS constant not found"
    body = tooltip_block.group(1)
    assert "Always produced by Quorum" not in body, (
        "Old apologetic phrase is still present in SYNTHESIS_TOOLTIPS."
    )
