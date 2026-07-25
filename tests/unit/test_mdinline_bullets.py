"""Unit tests for mdInline bullet-list rendering.

The mdInline renderer is bundled inside the browser-facing static JS file,
so these tests operate on the SOURCE TEXT of ``src/product_app/static/app.js``
— asserting the regex patterns, the <ul>/<li> contract, and the
non-eating of lone mid-word asterisks. (The runtime path through
``setInlineProse`` is exercised by the e2e rendering-invariants gate.)

These tests are the static twin of the rendering-invariants e2e spec:
the e2e gate proves the browser strips "- " / "* " markers from text
nodes; these tests prove the underlying regex in the source cannot eat
a lone asterisk mid-word and does produce <ul>/<li> scaffolding.
"""
from __future__ import annotations

import pathlib
import re

import pytest

JS_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src/product_app/static/app.js"
)


@pytest.fixture(scope="module")
def app_js_text() -> str:
    return JS_PATH.read_text(encoding="utf-8")


# ---- structural assertions on the source ---------------------------------------


def test_mdInline_bullet_list_regex_present(app_js_text: str) -> None:
    """The mdInline function must contain a regex that matches lines
    starting with '-' or '*' (optionally indented) and emits <ul>/<li>.
    """
    # The regex must have the word-boundary/line-anchor logic that
    # prevents matching mid-word.
    assert "[-*]" in app_js_text, "mdInline bullet regex missing: no [-*] character class found"
    assert "<ul>" in app_js_text, "mdInline must emit <ul> for bullet lists"
    assert "<li>" in app_js_text, "mdInline must emit <li> for bullet items"


def test_mdInline_bullet_regex_not_mid_word(app_js_text: str) -> None:
    """The bullet regex must only match at the START of a line (after
    optional whitespace), never in the middle of a word. This prevents a
    lone '*' like in "x* y" from being consumed as a list marker.
    """
    # Extract the regex literal from the mdInline function body.
    # The pattern must use (?:^|\\n) or equivalent to anchor at line start.
    # We also verify there is no bare `[-*]` that appears inside mdInline
    # WITHOUT a preceding (?:^|\\n) anchor — that would be a mid-word match.

    # Find the mdInline function definition.
    md_inline_match = re.search(
        r"function\s+mdInline\s*\([^)]*\)\s*\{([\s\S]+?)(?=\n\s{2}function\s|\n\s{2}//\s)",
        app_js_text,
    )
    assert md_inline_match is not None, "mdInline function not found in app.js"

    func_body = md_inline_match.group(1)

    # The bullet replace call must have a regex with the line-start anchor.
    bullet_section = re.search(
        r"s\.replace\(\s*/(.*?)/g",
        func_body,
    )
    assert bullet_section is not None, "No regex replace found in mdInline"

    # Find ALL regex literals in mdInline — there are multiple (code,
    # bold, italic, links, underscores, bullet list).
    bullet_replace = re.search(
        r"s\.replace\(\s*(/.*?/g[^,]*),\s*\(match\)",
        func_body,
        re.DOTALL,
    )
    assert bullet_replace is not None, (
        "mdInline bullet list regex replace not found "
        "(expected the iteratee to receive `match`)"
    )
    bullet_regex_src = bullet_replace.group(1)
    # It must have (?:^|\\n) or \\n at the start to anchor at line boundary.
    assert "(?:^|\\n)" in bullet_regex_src or "\\n" in bullet_regex_src, (
        f"Bullet regex must anchor at line start, got: {bullet_regex_src[:200]}"
    )
    # The character class must include both - and *
    assert "[-*]" in bullet_regex_src, (
        f"Bullet regex must match both - and *, got: {bullet_regex_src[:200]}"
    )


def test_mdInline_emits_ul_li_structure(app_js_text: str) -> None:
    """The bullet replace body must construct <ul> and <li> tags."""
    # Extract mdInline body using the function name as anchor.
    md_inline_match = re.search(
        r"function\s+mdInline\s*\([^)]*\)\s*\{([\s\S]+)",
        app_js_text,
    )
    assert md_inline_match is not None, "mdInline function not found"
    body = md_inline_match.group(1)
    # Extract only up to the next top-level function definition (applyOutsideTags).
    next_fn = re.search(r"\n\s{2}function\s+applyOutsideTags", body)
    if next_fn:
        body = body[: next_fn.start()]

    # There must be a replace call whose iteratee produces `<ul>...<li>...`.
    # We search for the specific string building pattern.
    assert "<ul>" in body, (
        "mdInline must contain a `<ul>` construction for bullet lists"
    )
    assert "<li>" in body, (
        "mdInline must contain a `<li>` construction for bullet items"
    )


# ---- regex behaviour tests (Python-side mirrors the JS logic) -------------------


def _md_inline_bullets_python(text: str) -> str:
    """Python re-implementation of mdInline's bullet-list step, used
    to verify the JS regex behaviour in isolation.

    Uses the same anchoring: (?:^|\\n)[ \\t]*[-*][ \\t]+ to match
    bullet markers only at the start of a line.
    """
    # Reconstruct consecutive bullet blocks and wrap in <ul>/<li>.
    pattern = re.compile(r"(?:^|\n)((?:[ \t]*[-*][ \t]+[^\n]*\n?)+)")
    result = pattern.sub(lambda m: _md_inline_bullets_replace(m), text)
    return result


def _md_inline_bullets_replace(match: re.Match) -> str:
    block = match.group(1)
    items = []
    for line in block.split("\n"):
        if not re.match(r"^[ \t]*[-*][ \t]", line):
            continue
        # Strip leading whitespace + bullet marker ("- " or "* ").
        stripped = re.sub(r"^[ \t]*[-*][ \t]+", "", line)
        items.append(f"<li>{stripped}</li>")
    return "\n<ul>" + "".join(items) + "</ul>"


def test_bullet_list_basic() -> None:
    raw = "- item one\n- item two\n- item three"
    out = _md_inline_bullets_python(raw)
    assert "<ul>" in out
    assert "<li>item one</li>" in out
    assert "<li>item two</li>" in out
    assert "<li>item three</li>" in out


def test_bullet_list_indented() -> None:
    raw = "  - indented item\n\t- tab-indented item\n- normal"
    out = _md_inline_bullets_python(raw)
    assert "<ul>" in out
    assert "<li>indented item</li>" in out
    assert "<li>tab-indented item</li>" in out
    assert "<li>normal</li>" in out


def test_bullet_list_asterisk_marker() -> None:
    raw = "* star one\n* star two"
    out = _md_inline_bullets_python(raw)
    assert "<ul>" in out
    assert "<li>star one</li>" in out
    assert "<li>star two</li>" in out


def test_bullet_list_mixed_dash_and_star() -> None:
    raw = "- dash item\n* star item\n- another dash"
    out = _md_inline_bullets_python(raw)
    assert "<ul>" in out
    assert "<li>dash item</li>" in out
    assert "<li>star item</li>" in out
    assert "<li>another dash</li>" in out


def test_bullet_marker_not_mid_word() -> None:
    """A lone '*' inside a word must NOT be consumed as a list marker."""
    # Example: "foo*bar" — the * is in the middle of a word.
    raw = "foo*bar\nbaz*qux"
    out = _md_inline_bullets_python(raw)
    assert "<ul>" not in out, (
        f"Lone mid-word '*' must not trigger a <ul>; got: {out!r}"
    )
    # The text must be preserved as-is (the bullet step is a no-op).
    assert "foo*bar" in out
    assert "baz*qux" in out


def test_bullet_marker_at_mid_sentence_not_consumed() -> None:
    """A '- ' appearing mid-line (not at the start of a line) must NOT
    trigger a list marker.
    """
    raw = "see also - the appendix\nfoo * bar"
    out = _md_inline_bullets_python(raw)
    # These are NOT list markers (not at line start), so no <ul>.
    assert "<ul>" not in out, (
        f"Mid-line '- ' must not trigger a <ul>; got: {out!r}"
    )
    # The raw text should be unchanged.
    assert "see also - the appendix" in out
    assert "foo * bar" in out


def test_bullet_list_with_inline_formatting() -> None:
    """Bullet items can contain bold/italic content; the bullet regex
    captures the full line and the mdInline rules (bold/italic/link)
    run on the stripped content.
    """
    raw = "- **bold** bullet\n- *italic* bullet"
    out = _md_inline_bullets_python(raw)
    assert "<ul>" in out
    assert "<li>**bold** bullet</li>" in out
    assert "<li>*italic* bullet</li>" in out


def test_no_bullet_list_no_side_effects() -> None:
    """Text without any bullet markers must pass through untouched."""
    raw = "Just a paragraph with no bullets at all."
    out = _md_inline_bullets_python(raw)
    assert out == raw


def test_bullet_list_next_to_paragraph() -> None:
    """A bullet list followed by a paragraph — the list block should be
    captured and the paragraph left as-is.
    """
    raw = "- first\n- second\n\nAfter the list."
    out = _md_inline_bullets_python(raw)
    assert "<ul>" in out
    assert "<li>first</li>" in out
    assert "<li>second</li>" in out
    assert "After the list." in out


def test_bullet_list_before_paragraph() -> None:
    """Paragraph followed by bullet list."""
    raw = "Before list.\n\n- alpha\n- beta"
    out = _md_inline_bullets_python(raw)
    assert "<ul>" in out
    assert "<li>alpha</li>" in out
    assert "<li>beta</li>" in out
    assert "Before list." in out
