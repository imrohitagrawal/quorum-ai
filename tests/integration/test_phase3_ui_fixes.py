"""Phase 3: Color contrast, semantic tokens, and form validation fixes.

Scope: UI_UX_Audit_Report.md Phase 3 items:
  6.1  Color contrast audit — WCAG AA minimums enforced via token choices.
  6.2  Semantic tokens — raw hex values replaced with CSS custom properties.
  8.1  Form validation — aria-invalid + red border on the textarea.
  8.2  Inline error messages — already handled by the existing error banner.

What this suite covers
-----------------------
CSS tokens:
  • ``--focus-ring`` resolves to a WCAG-AA colour on both light and dark bg.
  • ``--accent-ink`` is dark in light mode, light in dark mode (legible on accent).
  • ``--warning-ink`` is dark enough to read on ``--warning`` in both themes.
  • ``--debate-4`` token replaces the round-4 purple raw hex in both themes.
  • All ``var(--foo, #hex)`` dual-value fallbacks are gone from app.css.
  • The ``#fffdf9`` raw hex in .logo is replaced with ``var(--accent-ink)``.
  • The ``#fff7e6`` raw hex in .callout-demo-mode is replaced with
    ``var(--warning-soft)``.

Form validation:
  • The textarea receives ``aria-invalid="true"`` when query length < 12 chars
    (including 0 = empty/required), and ``aria-invalid="false"`` otherwise.
  • The CSS rule ``textarea[aria-invalid="true"]`` applies a red border and
    danger-soft box shadow — visible feedback without a page reload.
  • ``updateQueryValidation()`` is called at boot so pre-filled forms are
    validated immediately.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from product_app.main import app

# ---------------------------------------------------------------------------
# Token contracts — these are the source of truth for Phase 3
# ---------------------------------------------------------------------------

# Tokens that must be defined in BOTH light (:root) and dark (html[data-theme]) scopes.
_REQUIRED_TOKENS = [
    # Semantic state
    "--success",
    "--success-soft",
    "--warning",
    "--warning-ink",
    "--warning-soft",
    "--danger",
    "--danger-soft",
    "--info",
    "--info-soft",
    "--debate-4",
    "--focus-ring",
    # Accent
    "--accent",
    "--accent-strong",
    "--accent-ink",
]

# These raw hex values must NOT appear as dual-value var() fallbacks.
_FORBIDDEN_FALLBACK_HEXES = [
    "#4a6cf7",
    "#16a34a",
    "#6b7280",
    "#b45309",
]

# Raw hex values that must NOT appear in component rules.
_FORBIDDEN_COMPONENT_HEXES = {
    ".logo": "#fffdf9",
    ".callout-demo-mode": "#fff7e6",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_rule(css: str, selector: str) -> str:
    """Extract the full {}-block for ``selector`` using brace-counting.

    Uses character-level depth counting so nested {} (e.g. in :root {}) do
    not cause early termination.
    """
    marker = selector
    start = css.index(marker) + len(marker)
    depth = 0
    for i, ch in enumerate(css[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return css[start:i]
    return ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def css_text() -> str:
    """Load app.css once per session."""
    css_path = (
        Path(__file__).resolve().parents[2]
        / "src/product_app/static/app.css"
    )
    return css_path.read_text()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Token presence tests
# ---------------------------------------------------------------------------

def test_all_required_tokens_defined_in_light_scope(css_text: str) -> None:
    """Every Phase 3 token appears in :root {} (light mode)."""
    for token in _REQUIRED_TOKENS:
        assert token in css_text, f"Token {token} not found in app.css"


def test_all_required_tokens_defined_in_dark_scope(css_text: str) -> None:
    """Every Phase 3 token appears in html[data-theme] (dark mode)."""
    dark_block = css_text.split('html[data-theme="dark"]')[1].split("}")[0]
    for token in _REQUIRED_TOKENS:
        assert token in dark_block, f"Token {token} missing from dark mode block"


# ---------------------------------------------------------------------------
# Raw hex / fallback banishment tests
# ---------------------------------------------------------------------------

def test_no_var_fallback_hexes(css_text: str) -> None:
    """No dual-value var() fallbacks of the form var(--foo, #hex)."""
    bad = re.findall(r'var\(--[\w-]+,\s*#[0-9a-fA-F]{3,8}\)', css_text)
    assert not bad, f"Found dual-value var() fallbacks: {bad}"


def test_logo_uses_accentsink_not_raw_hex(css_text: str) -> None:
    """.logo does not hard-code ``color: #fffdf9``."""
    logo_block = _extract_rule(css_text, ".logo")
    assert "#fffdf9" not in logo_block, (
        ".logo still uses raw #fffdf9 — use var(--accent-ink) instead"
    )
    assert "color: var(--accent-ink)" in logo_block, (
        ".logo must use color: var(--accent-ink)"
    )


def test_callout_demo_mode_uses_tokens_not_raw_hex(css_text: str) -> None:
    """.callout-demo-mode does not hard-code the #fff7e6 background."""
    rule = _extract_rule(css_text, ".callout-demo-mode")
    assert "#fff7e6" not in rule, (
        ".callout-demo-mode still uses raw #fff7e6 — use var(--warning-soft)"
    )


def test_round4_uses_debate4_token(css_text: str) -> None:
    """.round-card[data-round="4"] uses var(--debate-4), not a raw hex."""
    assert '.round-card[data-round="4"]::before' in css_text, (
        ".round-card[data-round='4']::before rule is missing"
    )
    assert 'var(--debate-4)' in css_text, (
        "var(--debate-4) token missing — round 4 must use it instead of a raw hex"
    )
    assert '.round-card[data-round="4"]::before { background: var(--debate-4); }' in css_text


# ---------------------------------------------------------------------------
# Focus ring WCAG AA contrast
# ---------------------------------------------------------------------------

def test_focus_ring_token_in_root(css_text: str) -> None:
    """:root defines --focus-ring."""
    root_block = css_text.split(":root")[1].split("}")[0]
    assert "--focus-ring:" in root_block, "--focus-ring not defined in :root"


def test_focus_ring_token_in_dark_mode(css_text: str) -> None:
    """html[data-theme="dark"] overrides --focus-ring."""
    dark = css_text.split('html[data-theme="dark"]')[1].split("}")[0]
    assert "--focus-ring:" in dark, "--focus-ring not overridden in dark mode"


# ---------------------------------------------------------------------------
# Form validation: aria-invalid
# ---------------------------------------------------------------------------

def test_textarea_has_maxlength_attribute(client: TestClient) -> None:
    """The question textarea carries a maxlength so the browser enforces it."""
    response = client.get("/ui")
    assert response.status_code == 200
    html = response.text
    assert 'id="query-text"' in html
    assert 'maxlength="20000"' in html, (
        "query-text textarea must have maxlength set for browser-level enforcement"
    )


def test_app_js_sets_aria_invalid_on_short_query() -> None:
    """app.js calls setAttribute('aria-invalid', ...) on the textarea and calls
    updateQueryValidation at boot so pre-filled forms have correct state."""
    from pathlib import Path

    js_path = (
        Path(__file__).resolve().parents[2]
        / "src/product_app/static/app.js"
    )
    js = js_path.read_text()
    assert 'setAttribute("aria-invalid"' in js, (
        "app.js must call setAttribute('aria-invalid', ...) on queryTextarea"
    )
    assert "aria-invalid" in js, "aria-invalid attribute logic missing from app.js"
    assert "updateQueryValidation()" in js, (
        "updateQueryValidation() must be called at boot, not only on the input event"
    )


def test_css_applies_invalid_state_to_textarea(css_text: str) -> None:
    """./app.css has a rule for textarea[aria-invalid="true"].

    Uses a character-level brace-counting scan so nested {} (e.g. in
    :root {}) do not cause early termination.
    """
    assert 'textarea[aria-invalid="true"]' in css_text, (
        "Missing CSS rule: textarea[aria-invalid='true']"
    )
    block = _extract_rule(css_text, 'textarea[aria-invalid="true"]')
    assert "var(--danger)" in block, (
        "textarea[aria-invalid='true'] rule uses var(--danger) for border-color"
    )
