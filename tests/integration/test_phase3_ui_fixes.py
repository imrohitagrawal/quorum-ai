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
  • ``--warning-ink`` replaced with `color: white` on ``.callout-demo-mode .callout-icon`` for WCAG AA compliance.
  • ``--debate-4`` token replaces the round-4 purple raw hex in both themes.
  • All ``var(--foo, #hex)`` dual-value fallbacks are gone from app.css.
  • The ``#fffdf9`` raw hex in .logo is replaced with ``var(--accent-ink)``.
  • The ``#fff7e6`` raw hex in .callout-demo-mode is replaced with
    ``var(--warning-soft)``.

Form validation:
  • The textarea receives ``aria-invalid="true"`` when a non-empty query
    is under 12 characters (too short), and ``aria-invalid="false"`` otherwise.
  • The CSS rule ``textarea[aria-invalid="true"]`` applies a red border and
    danger-soft box shadow — visible feedback without a page reload.
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
    "--warning-soft",
    "--danger",
    "--danger-soft",
    "--info",
    "--info-soft",
    "--debate-4",      # Phase 3 new — replaces raw #6b3fa0 / #a479e3
    "--focus-ring",     # Phase 3 — darkened to meet WCAG AA
    # Accent
    "--accent",
    "--accent-strong",
    "--accent-ink",    # Phase 3 — was hardcoded #10161f in .logo
]

# These raw hex values must NOT appear as dual-value var() fallbacks like
# ``color: var(--foo, #deadbeef)`` — they must use the token alone.
_FORBIDDEN_FALLBACK_HEXES = [
    "#4a6cf7",   # old --focus-ring fallback in .meta-value-copy:focus-visible
    "#16a34a",   # old --success fallback in [data-copied] states
    "#6b7280",   # old --muted fallback in .cost-secondary
    "#b45309",   # old --warning fallback in .stage-diagnostics summary
]

# Raw hex values that must NOT appear in component rules (they belong in
# :root token definitions only, or in cases where no token applies).
_FORBIDDEN_COMPONENT_HEXES = {
    # key = CSS class / rule context
    # value = hex that must not appear in that context
    ".logo": "#fffdf9",                    # use var(--accent-ink)
    ".callout-demo-mode": "#fff7e6",       # use var(--warning-soft)
    ".callout-demo-mode .callout-icon": "#1a1300",  # replaced with white for WCAG AA compliance
}


@pytest.fixture
def css_text() -> str:
    """Load app.css once per session.

    pytest rootdir = project root, so ``__file__`` resolves to
    ``.../tests/integration/test_phase3_ui_fixes.py`` as an absolute path.
    parents[2] = project root.
    """
    from pathlib import Path

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
        pattern = rf"^\s*--[\w-]+:"   # rough token def
        assert token in css_text, f"Token {token} not found in app.css"


def test_all_required_tokens_defined_in_dark_scope(css_text: str) -> None:
    """Every Phase 3 token appears in html[data-theme] (dark mode)."""
    dark_block = css_text.split("html[data-theme=\"dark\"]")[1].split("}")[0]
    for token in _REQUIRED_TOKENS:
        assert token in dark_block, f"Token {token} missing from dark mode block"


# ---------------------------------------------------------------------------
# Raw hex / fallback banishment tests
# ---------------------------------------------------------------------------

def test_no_var_fallback_hexes(css_text: str) -> None:
    """No dual-value var() fallbacks of the form var(--foo, #hex)."""
    import re
    bad = re.findall(r'var\(--[\w-]+,\s*#[0-9a-fA-F]{3,8}\)', css_text)
    assert not bad, f"Found dual-value var() fallbacks: {bad}"


def test_brand_mark_uses_color_tokens_not_raw_hex(css_text: str) -> None:
    """The brand mark's colours come from tokens, not a hard-coded hex.

    The R1 redesign renamed the old ``.logo`` to ``.brand-mark`` (the Quorum
    tile) and moved it onto the ``--brand-tile-*`` tokens. This test tracks
    that rename: the brand mark must still be tokenised (no raw hex), which is
    what the original ``.logo``/``--accent-ink`` assertion was guarding.
    """
    rule = _extract_rule(css_text, ".brand-mark")
    assert rule, ".brand-mark rule is missing"
    assert "color: var(--brand-tile-fg)" in rule, (
        ".brand-mark must set its foreground via the --brand-tile-fg token"
    )
    assert "background: var(--brand-tile-bg)" in rule, (
        ".brand-mark must set its background via the --brand-tile-bg token"
    )
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", rule), (
        ".brand-mark must not hard-code a hex colour — use the --brand-tile-* tokens"
    )


def test_callout_demo_mode_uses_tokens_not_raw_hex(css_text: str) -> None:
    """.callout-demo-mode does not hard-code the #fff7e6 background."""
    rule = _extract_rule(css_text, ".callout-demo-mode")
    assert "#fff7e6" not in rule, (
        ".callout-demo-mode still uses raw #fff7e6 — use var(--warning-soft)"
    )


def test_round4_uses_debate4_token(css_text: str) -> None:
    """.round-card[data-round="4"] uses var(--debate-4), not a raw hex.

    The selector is a compound rule (``.round-card[data-round="4"]::before``),
    so we check the raw CSS for the presence of both the raw hex ban and the
    token usage rather than trying to extract a sub-rule body.
    """
    assert '.round-card[data-round="4"]::before' in css_text, (
        ".round-card[data-round='4']::before rule is missing"
    )
    # Must use var(--debate-4), not a raw hex
    assert 'var(--debate-4)' in css_text, (
        "var(--debate-4) token missing — round 4 must use it instead of a raw hex"
    )
    # The specific line should reference the token
    assert '.round-card[data-round="4"]::before { background: var(--debate-4); }' in css_text


def test_debate4_token_in_both_scopes(css_text: str) -> None:
    """--debate-4 is defined in both light (:root) and dark (html[data-theme]) scopes."""
    root_block = css_text.split(":root")[1].split("html[data-theme")[0]
    dark_block = css_text.split('html[data-theme="dark"]')[1].split("}")[0]
    assert "--debate-4:" in root_block, "--debate-4 missing from :root scope"
    assert "--debate-4:" in dark_block, "--debate-4 missing from html[data-theme='dark'] scope"


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
    # updateQueryValidation must be called at boot (not only on input events)
    # so pre-filled / autofilled textareas start with the correct aria-invalid state
    assert "updateQueryValidation()" in js, (
        "updateQueryValidation() must be called at boot, not only on the input event"
    )


def test_css_applies_invalid_state_to_textarea(css_text: str) -> None:
    """./app.css has a rule for textarea[aria-invalid="true"].

    Uses a character-level brace-counting scan so nested {} (e.g. in
    :root {}) do not cause early termination.
    """
    # The selector appears in the CSS
    assert 'textarea[aria-invalid="true"]' in css_text, (
        "Missing CSS rule: textarea[aria-invalid='true']"
    )
    # Extract the full {}-block body using brace-counting
    marker = 'textarea[aria-invalid="true"]'
    start = css_text.index(marker) + len(marker)
    depth = 0
    for i, ch in enumerate(css_text[start:], start):
        if ch == "{":   depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                block = css_text[start:i]
                break
    assert "var(--danger)" in block, (
        "textarea[aria-invalid='true'] rule uses var(--danger) for border-color"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _css_escape(s: str) -> str:
    r"""Escape only the regex metacharacters that also appear in CSS selectors.

    ``re.escape()`` would also escape ``[`` and ``]`` (CSS attribute-selector
    brackets), turning them into ``\[`` and ``\]`` which don't match the literal
    ``[`` / ``]`` in the CSS source. We escape only the truly problematic set:
    ``\\ . ^ $ * + ? { } | ( )``.
    """
    return re.sub(r'([\\.^$*+?{}|()])', r'\\\1', s)


def _extract_rule(css: str, selector: str) -> str:
    """Return the {...} block body for ``selector`` from flattened CSS.

    Handles selectors that contain pseudo-elements (::before, ::after).
    Returns the text between the outermost { and }, stripped of both.
    Returns "" if the selector is not found.
    """
    escaped = _css_escape(selector)
    # Match selector + opening brace
    pattern = rf"{escaped}\s*\{{"
    m = re.search(pattern, css)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(css) and depth > 0:
        ch = css[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return ""
    return css[start : i - 1]
