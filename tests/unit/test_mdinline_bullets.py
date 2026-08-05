"""Guards on how list and heading markers are rendered on INLINE surfaces.

WHAT CHANGED, AND WHY FIVE TESTS WERE DELETED RATHER THAN EDITED
---------------------------------------------------------------
ADR-0014 replaced the hand-rolled renderer with vendored ``markdown-it``.
``mdInline``, ``applyOutsideTags``, ``decodeBasicEntities``, ``flushList``,
``flushQuote`` and ``MAX_QUOTE_DEPTH`` no longer exist. Five tests in this file
asserted on the SOURCE TEXT of those functions, so they went red on the
deletion. Per this repo's convention each removal is argued individually rather
than silently dropped, and each names the runtime gate that carries the
guarantee now — because a guarantee whose only proof was a substring search was
never as strong as it looked:

* ``test_mdInline_emits_no_block_tag`` — asserted ``"<ul>" not in mdInline``.
  The guarantee ("an inline surface never receives a block child") is REAL and
  is now STRUCTURAL rather than asserted: ``setInlineProse`` calls
  ``renderInline``, which runs the inline rule chain only, so no paragraph,
  list, heading, table or blockquote rule can fire at all. Proven at runtime by
  ``rendering-invariants.spec.ts`` ("no list element is ever a child of a
  <span> or <p>") and by ``markdown-corpus.spec.ts``, which asserts the inline
  surface has ZERO block children on a heading-led answer.
* ``test_the_block_formatter_still_builds_real_lists`` — asserted
  ``'"ol" : "ul"' in app.js``, the exact ternary of a function that is gone.
  Its purpose was a positive partner: "lists must still render at all". That
  partner now lives where it can actually fail —
  ``rendering-invariants.spec.ts`` counts one top-level ``<ul>`` with six
  ``<li>`` and one NESTED list, in a browser.
* ``test_blockquotes_re_enter_the_block_formatter`` — asserted
  ``"formatAnswerText(quoteBuffer.join(" in app.js`` and the presence of
  ``MAX_QUOTE_DEPTH``. Both describe a RECURSIVE implementation. markdown-it is
  iterative and needs no depth cap, so the cap is not "removed", it is
  unnecessary — and the spec that guarded it now proves the stronger thing:
  a six-deep quote renders six real nested ``<blockquote>`` levels ending in a
  genuine ``<li>``, which the capped implementation could not do.
* ``test_a_list_keeps_the_number_the_model_wrote`` — asserted ``'start="'`` and
  ``"firstNumber !== 1"`` appear in ``app.js``. markdown-it emits ``start`` from
  its own ordered-list rule, so no such literal exists. The behaviour is pinned
  in the browser by ``rendering-invariants.spec.ts`` ("a quoted list that opens
  at 4 is not renumbered to 1"), which reads the DOM property, not the source.
* ``test_the_comment_stripper_actually_strips`` — a positive partner for the
  four above. With them gone it partnered nothing, and its own anchor phrase
  lived in a deleted comment. The stripper itself is still used, so its
  self-check moved into the one test that still needs it.

WHAT STAYED, AND WHY
--------------------
``inlineListMarkers`` is the ONE piece of hand-written Markdown handling that
survives ADR-0014, and it survives for a reason a parser cannot address: a
``<span>`` may not contain a ``<ul>``, so an inline surface has to render a
marker rather than build a structure. It now also strips a heading marker,
which is the #257 §2 leak (``"# PostgreSQL Scaling Decision"`` reached a real
screen with its ``#``).

A NOTE ON WHAT THIS FILE CANNOT DO
----------------------------------
The behavioural tests below drive a PYTHON MIRROR of the JavaScript, not the
JavaScript itself. A mirror cannot catch a regression in shipped code — it pins
that the intended semantics are self-consistent. That limitation is
pre-existing and stated rather than implied. The binding runtime proof is
``e2e/tests/invariants/rendering-invariants.spec.ts`` and
``e2e/tests/invariants/markdown-corpus.spec.ts``.
"""

from __future__ import annotations

import pathlib
import re

import pytest

JS_PATH = pathlib.Path(__file__).resolve().parents[2] / "src/product_app/static/app.js"


def _strip_js_comments(source: str) -> str:
    """Remove ``//`` and ``/* */`` comments from JavaScript source.

    ``tests/code_text.py`` only strips ``#`` comments, so JavaScript needs its
    own stripper — and here it is load-bearing rather than tidy. The comments
    this file reasons about DISCUSS the markers at length (they explain why each
    rule exists), so a check that did not strip them would match the
    explanation instead of the code and pass no matter what ``app.js`` did.
    String literals are left alone deliberately: the patterns under test live in
    regex and template literals, which is exactly what must be found.
    """
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        two = source[i : i + 2]
        if two == "//":
            j = source.find("\n", i)
            i = n if j == -1 else j
        elif two == "/*":
            j = source.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(source[i])
            i += 1
    return "".join(out)


@pytest.fixture(scope="module")
def app_js_text() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    """Return the source of ``function <name>`` up to the next top-level
    ``function`` at the same two-space indentation."""
    start = re.search(rf"\n  function\s+{re.escape(name)}\s*\(", source)
    assert start is not None, f"{name} not found in app.js"
    rest = source[start.end() :]
    nxt = re.search(r"\n  function\s+\w+\s*\(", rest)
    return rest[: nxt.start()] if nxt else rest


# ---- structural guards on the SHIPPED source ---------------------------------


def test_setInlineProse_routes_through_inlineListMarkers(app_js_text: str) -> None:
    """RED IF: ``setInlineProse`` hands raw text straight to ``renderInline``.

    ``renderInline`` runs the INLINE chain only, so a line-start "1. " or "# "
    is not a marker to it — it is text, and it reaches the surface verbatim.
    That is how a raw "1. " landed in ``.result-trust-caption`` (#120) and how a
    raw "# " landed in the "How positions moved" opening cell (#257 §2).

    Positive partner for the stripped-source read: the stripper must actually
    strip, or this test would be satisfied by a COMMENT mentioning the call.
    """
    stripped = _strip_js_comments(app_js_text)
    assert len(stripped) < len(app_js_text), "the comment stripper removed nothing"
    # A phrase that exists ONLY inside a comment must be gone...
    assert "pure syntax" in app_js_text
    assert "pure syntax" not in stripped
    # ...while the identifier under test must survive.
    assert "function inlineListMarkers" in stripped

    body = _function_body(stripped, "setInlineProse")
    assert "inlineListMarkers(" in body, (
        "setInlineProse must pre-render block markers; without it an ordered "
        "list reaches an inline surface as literal '1. ' (#120) and a heading "
        "as literal '# ' (#257)"
    )
    assert "renderInline(" in body, (
        "setInlineProse must use renderInline, not render — render() emits "
        "<p>/<ul>/<h*>, which are illegal children of the <span> surfaces it "
        "targets"
    )


def test_the_xss_flag_is_configured_off(app_js_text: str) -> None:
    """``html: false`` is the entire XSS posture, so it must be SET, explicitly.

    RED IF: the flag is flipped, or deleted so markdown-it's own default is
    relied on. This is a cheap source-level companion, not the real proof — the
    real proof is behavioural and lives in ``markdown-corpus.spec.ts``, which
    feeds a live ``<script>`` through a provider answer and reads the DOM. Both
    exist because a source check cannot see a second renderer being constructed
    somewhere else, and a browser check cannot run in the unit lane.
    """
    stripped = _strip_js_comments(app_js_text)
    assert "html: false" in stripped, (
        "MD_OPTIONS no longer sets `html: false`. That flag is what escapes raw "
        "HTML in provider text; without it `<script>alert(1)</script>` in a "
        "model answer renders live (ADR-0014 measured exactly that)."
    )
    assert "html: true" not in stripped, "a markdown-it instance is configured with html: true"


def test_inline_marker_regex_anchors_at_line_start(app_js_text: str) -> None:
    """The retargeted home of the old mid-word guarantee.

    RED IF: the anchor is dropped, so a lone ``*`` mid-word is eaten as a
    marker — the exact regression the original deleted test existed to prevent.
    """
    body = _function_body(_strip_js_comments(app_js_text), "inlineListMarkers")
    # The function splits on newline and anchors each line with ^, rather than
    # using one (^|\n) pattern over the whole blob. Either shape gives the same
    # guarantee; this asserts the one that is actually there.
    assert 'split("\\n")' in body, f"inlineListMarkers must process line by line, got: {body[:300]}"
    assert "/^([ \\t]*)" in body, (
        f"marker regex must anchor at the start of a LINE, got: {body[:300]}"
    )
    assert "[-*]" in body, "marker regex must match both - and *"
    assert "\\d{1,2}\\." in body, (
        "marker regex must match a 1-2 digit ordinal, and ONLY 1-2 digits — a "
        "4-digit year at a line start ('2025. Nobody revisited...') is prose"
    )
    assert "#{1,6}" in body, (
        "the heading marker must be handled too; without it '# Decision' reaches "
        "an inline surface with its '#' intact (#257 §2)"
    )


def test_an_ordered_marker_may_only_interrupt_prose_at_one(app_js_text: str) -> None:
    """CommonMark's interrupt rule, which the first version of this fix lacked.

    RED IF: the ``interruptsProse`` guard is removed. Without it,
    "…cut the estimate from 15 to\\n12. Nobody revisited it since." renders as
    "(12) Nobody revisited it since." — prose rewritten into a list item, while
    the BLOCK path correctly leaves it alone. Found by adversarial review, not
    by any gate.
    """
    body = _function_body(_strip_js_comments(app_js_text), "inlineListMarkers")
    assert "interruptsProse" in body, (
        "inlineListMarkers must not convert an ordered marker that interrupts "
        "running prose unless it opens the list at 1"
    )


# ---- behavioural mirror -------------------------------------------------------
#
# See the module docstring: this is a PYTHON MIRROR of inlineListMarkers, so it
# pins intended semantics only. The runtime proof is the e2e gate — and review
# measured exactly how far that goes: an implementation that DELETES every
# ordinal passed this whole file and every e2e test in the first round. The
# `#120 round 2` specs are what actually catch that; these stay useful for the
# line-classification rules, which are fiddly and worth pinning cheaply.
#
# TWO THINGS CHANGED WITH ADR-0014, and the mirror changed with them:
#   * it takes and returns RAW text, not HTML-escaped text. markdown-it escapes
#     downstream, so escaping first would double-encode.
#   * it no longer emits `<br>` between items. `breaks: true` turns the
#     surviving newline into the `<br>`, so emitting one here would be escaped
#     into visible "&lt;br&gt;".

_ITEM = re.compile(r"^([ \t]*)([-*]|\d{1,2}\.)[ \t]+")
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+")
_BULLET = "• "


def _inline_list_markers_python(raw: str) -> str:
    """Mirror of ``inlineListMarkers``: line-based, heading markers stripped,
    list markers rendered, with CommonMark's rule that an ordered marker may
    only interrupt prose when it opens at 1."""
    lines = raw.split("\n")
    out: list[str] = []
    in_list = False
    for i, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading:
            in_list = False
            out.append(line[heading.end() :])
            continue
        m = _ITEM.match(line)
        if not m:
            in_list = False
            out.append(line)
            continue
        marker = m.group(2)
        bullet = marker in ("-", "*")
        interrupts_prose = i > 0 and not in_list and lines[i - 1].strip() != ""
        if not bullet and interrupts_prose and marker != "1.":
            in_list = False
            out.append(line)
            continue
        in_list = True
        rendered = _BULLET if bullet else f"({marker[:-1]}) "
        out.append(rendered + line[m.end() :])
    return "\n".join(out)


def test_bullets_become_a_rendered_bullet_character() -> None:
    """A <span> may not contain a <ul>, so the marker becomes its rendered form.

    The newline SURVIVES now rather than becoming a literal ``<br>`` here: with
    ``breaks: true`` markdown-it renders it as the break, and a ``<br>`` emitted
    at this stage would be escaped into visible text.
    """
    out = _inline_list_markers_python("Caveats:\n- verify the cost\n- keep the cap")
    assert out == f"Caveats:\n{_BULLET}verify the cost\n{_BULLET}keep the cap"


def test_ordinals_are_rendered_not_deleted() -> None:
    """The ordinal must survive. Stripping it renders cleanly and silently
    loses the sequence — the rejected alternative, recorded in ADR-0011.
    """
    out = _inline_list_markers_python("Open items:\n1. cohort definition\n2. export gate")
    assert out == "Open items:\n(1) cohort definition\n(2) export gate"
    assert "1" in out and "2" in out, "the ordinal was deleted rather than rendered"


def test_a_heading_marker_is_stripped_and_its_words_kept() -> None:
    """#257 §2, pinned.

    A ``#`` is pure SYNTAX — an inline surface has no heading to build, and no
    content is lost by dropping it. That is why it is treated differently from
    an ordinal, which is content.

    RED IF: the heading branch is removed. The words then survive but the "#"
    goes with them, which is what a real user saw:
    ``"# PostgreSQL Scaling Decision for Your B2B SaaS Based on your profile…"``
    """
    out = _inline_list_markers_python("# PostgreSQL Scaling Decision")
    assert out == "PostgreSQL Scaling Decision"
    assert "#" not in out
    # Every level, and the indented form.
    assert _inline_list_markers_python("###### deep") == "deep"
    assert _inline_list_markers_python("  ## indented") == "indented"


def test_a_hash_without_a_space_is_not_a_heading() -> None:
    """Positive partner for the test above — a rule that stripped EVERY leading
    "#" would also eat a hashtag or an issue reference, which is content.
    """
    for raw in ("#hashtag stays", "#257 is the issue", "####### seven hashes is not a heading"):
        assert _inline_list_markers_python(raw) == raw


def test_an_ordered_marker_above_one_does_not_interrupt_prose() -> None:
    """The F2 regression, pinned.

    A sentence that soft-wraps onto a 1-2 digit number is PROSE. The first
    version of this fix rewrote it into a list item; the block formatter never
    did. Both paths now agree.
    """
    raw = "The panel cut the estimate from 15 to\n12. Nobody revisited it since."
    assert _inline_list_markers_python(raw) == raw


def test_but_a_marker_that_opens_at_one_still_starts_a_list() -> None:
    """Positive partner for the test above — without it, a rule that refused
    EVERY ordinal would pass, and no inline ordered list would ever render."""
    out = _inline_list_markers_python("Open items:\n1. first\n2. second")
    assert out == "Open items:\n(1) first\n(2) second"


def test_a_four_digit_year_at_a_line_start_is_left_alone() -> None:
    """A soft-wrapped sentence landing on a year is PROSE, not a list.

    This codebase already paid for the opposite once: a wrap onto "2025." was
    parsed as a list marker and the year DELETED.
    """
    raw = "...first proposed in\n2025. Nobody has revisited it since."
    assert _inline_list_markers_python(raw) == raw


def test_a_lone_asterisk_mid_word_is_never_eaten() -> None:
    """The guarantee inherited from the deleted mdInline test."""
    raw = "foo*bar\nbaz*qux\ncost * qty"
    assert _inline_list_markers_python(raw) == raw


def test_a_marker_mid_line_is_not_a_list() -> None:
    raw = "see also - the appendix"
    assert _inline_list_markers_python(raw) == raw


def test_an_indented_marker_still_renders() -> None:
    out = _inline_list_markers_python("  - indented\n\t* tabbed")
    assert out == f"{_BULLET}indented\n{_BULLET}tabbed"


def test_no_markdown_marker_survives_the_mirror() -> None:
    """The mirror's own version of the e2e sweep: after rendering, none of the
    gate's marker patterns may still match.
    """
    raw = "# Steps\n1. instrument\n2. export\n- side note"
    out = _inline_list_markers_python(raw)
    assert re.search(r"(?:^|\n)[ \t]*1\.[ \t]", out) is None
    assert re.search(r"(?:^|\n)[ \t]*[-*][ \t]", out) is None
    assert re.search(r"(^|\n)#{1,6}\s", out) is None
    # Positive partner: those same patterns DO match before rendering.
    assert re.search(r"(?:^|\n)[ \t]*1\.[ \t]", raw) is not None
    assert re.search(r"(?:^|\n)[ \t]*[-*][ \t]", raw) is not None
    assert re.search(r"(^|\n)#{1,6}\s", raw) is not None
