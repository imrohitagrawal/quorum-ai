"""Static guards on how list markers are rendered in ``app.js`` (issue #120).

WHAT CHANGED, AND WHY THIS FILE WAS REWRITTEN RATHER THAN EDITED
---------------------------------------------------------------
Before #120, ``mdInline`` carried a rule that turned "- item" lines into a
``<ul>``. That rule was deleted, because ``mdInline``'s own documented contract
— stated at ``setInlineProse`` — is "inline-only, no block structure", and the
surfaces it renders into are ``<span>`` and ``<p>``, where ``<ul>`` is an
ILLEGAL child. Measured in a real browser on 2ba0519, it produced exactly that:

    .result-source-support (P): "Caveats:\\n<ul><li>verify the cost figure</li>
                                 <li>keep the cap</li></ul>"

The behaviour moved to two places: ``inlineListMarkers`` (renders a marker as
its inline equivalent — "bullet" / "(n)") and ``formatAnswerText``'s blockquote
branch (re-enters the block formatter, so a quoted list becomes a real
``<ol>``/``<ul>``).

Per AGENTS.md's rule on tests, this is a CONTRACT test whose contract
deliberately changed, so each removal is argued individually here rather than
silently dropped:

* ``test_mdInline_bullet_regex_not_mid_word`` — the mid-word protection it
  guarded ("a lone ``*`` in ``x* y`` is never eaten") is a REAL requirement and
  is NOT dropped. It is retargeted onto ``inlineListMarkers``, which is where
  the marker regex now lives. Same guarantee, new address.
* ``test_mdInline_bullet_list_regex_present`` / ``test_mdInline_emits_ul_li_structure``
  — DELETED as written, and the reason matters: both asserted
  ``"<ul>" in app_js_text`` against the WHOLE FILE. Measured: after the bullet
  rule was deleted from ``mdInline`` entirely, **both still passed**, because
  ``<ul>`` occurs elsewhere in ``app.js``. They were vacuous guards of exactly
  the shape AGENTS.md rule 8 names ("assert structure, not substrings"). They
  are replaced by ``test_mdInline_emits_no_block_tag`` below, which scopes to
  the function body, strips comments, and ships a positive partner.

A NOTE ON WHAT THIS FILE CANNOT DO
----------------------------------
The behavioural tests below drive a PYTHON MIRROR of the JavaScript, not the
JavaScript itself. A mirror cannot catch a regression in the shipped code — it
only pins that the intended semantics are self-consistent. That limitation is
pre-existing and is stated here rather than implied. The binding runtime proof
is the e2e gate ``e2e/tests/invariants/rendering-invariants.spec.ts``
("#120 - lists inside blockquotes and inline surfaces"), which drives the real
browser against the real ``app.js`` and was measured RED on 2ba0519.
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
    this file reasons about DISCUSS ``<ul>`` at length (they explain why the
    tag must not be emitted), so a check that did not strip them would match
    the explanation instead of the code and pass no matter what ``app.js`` did.
    String literals are left alone deliberately: the tags under test live in
    template literals, which is exactly what must be found.
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


def test_the_comment_stripper_actually_strips(app_js_text: str) -> None:
    """Positive partner for every stripped-source check below.

    Without this, a stripper that silently returned its input unchanged would
    make each guard below pass by reading prose instead of code.
    """
    stripped = _strip_js_comments(app_js_text)
    assert len(stripped) < len(app_js_text), "stripper removed nothing"
    # A phrase that exists ONLY inside a comment must be gone...
    assert "no block structure" in app_js_text
    assert "no block structure" not in stripped
    # ...while a real identifier must survive.
    assert "function mdInline" in stripped


def test_mdInline_emits_no_block_tag(app_js_text: str) -> None:
    """``mdInline`` must not construct a list.

    RED IF: a ``<ul>``/``<ol>``/``<li>`` construction is reintroduced into
    ``mdInline``. That is the #120 defect — an illegal child inside the
    ``<span>``/``<p>`` surfaces ``setInlineProse`` renders into.
    """
    body = _function_body(_strip_js_comments(app_js_text), "mdInline")
    for tag in ("<ul>", "<ol>", "<li>"):
        assert tag not in body, (
            f"mdInline constructs {tag}, but its contract is inline-only and its "
            f"target surfaces (<span>/<p>) cannot legally contain it (#120)"
        )


def test_the_block_formatter_still_builds_real_lists(app_js_text: str) -> None:
    """Positive partner for the test above.

    Without this, deleting list rendering from the product ENTIRELY would make
    ``test_mdInline_emits_no_block_tag`` pass — a check that goes green when
    the feature is absent is worthless.

    RED IF: ``flushList`` stops emitting a list, or the ordered/unordered tag
    choice is hard-coded to one of them.
    """
    stripped = _strip_js_comments(app_js_text)
    assert "<li>" in stripped, "no <li> is constructed anywhere in app.js"
    assert '"ol" : "ul"' in stripped, (
        "the block formatter no longer chooses between <ol> and <ul>; an "
        "ordered list would render as a bullet list or not at all"
    )


def test_setInlineProse_routes_through_inlineListMarkers(app_js_text: str) -> None:
    """RED IF: ``setInlineProse`` goes back to calling ``mdInline`` on the raw
    text, which is how a raw "1. " reached ``.result-trust-caption`` verbatim.
    """
    body = _function_body(_strip_js_comments(app_js_text), "setInlineProse")
    assert "inlineListMarkers(" in body, (
        "setInlineProse must pre-render list markers; without it an ordered "
        "list reaches an inline surface as literal '1. ' text (#120)"
    )


def test_blockquotes_re_enter_the_block_formatter(app_js_text: str) -> None:
    """RED IF: the blockquote branch goes back to joining ``mdInline`` output
    with ``<br>``, which left every quoted ordered marker as literal text.
    """
    stripped = _strip_js_comments(app_js_text)
    assert "formatAnswerText(quoteBuffer.join(" in stripped, (
        "flushQuote must re-enter formatAnswerText so a quoted list becomes a real <ol>/<ul> (#120)"
    )
    assert "MAX_QUOTE_DEPTH" in stripped, (
        "the blockquote recursion must stay bounded; unbounded, a '>>>>...' "
        "answer recurses once per marker"
    )


def test_inline_marker_regex_anchors_at_line_start(app_js_text: str) -> None:
    """The retargeted home of the old mid-word guarantee.

    RED IF: the anchor is dropped, so a lone ``*`` mid-word is eaten as a
    marker — the exact regression the deleted test existed to prevent.
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


def test_a_list_keeps_the_number_the_model_wrote(app_js_text: str) -> None:
    """RED IF: ``flushList`` stops emitting ``start`` on a list that opens above 1.

    An <ol> with no `start` renumbers from 1, so a quoted procedure opening at
    "4." is shown as "1." — the product stating a number its input never
    contained, and invisible to every text-node gate because it lives in
    ::marker.
    """
    stripped = _strip_js_comments(app_js_text)
    assert 'start="' in stripped, (
        "no <ol start> is emitted anywhere; a list opening above 1 is renumbered"
    )
    assert "firstNumber !== 1" in stripped, (
        "the start attribute must be omitted only for a list that really does open at 1"
    )


# ---- behavioural mirror -------------------------------------------------------
#
# See the module docstring: this is a PYTHON MIRROR of inlineListMarkers, so it
# pins intended semantics only. The runtime proof is the e2e gate — and review
# measured exactly how far that goes: an implementation that DELETES every
# ordinal passed this whole file and every e2e test in the first round. The
# `#120 round 2` specs are what actually catch that; these stay useful for the
# line-classification rules, which are fiddly and worth pinning cheaply.

_ITEM = re.compile(r"^([ \t]*)([-*]|\d{1,2}\.)[ \t]+")
_BULLET = "\u2022 "


def _inline_list_markers_python(escaped: str) -> str:
    """Mirror of ``inlineListMarkers``: line-based, with CommonMark's rule that
    an ordered marker may only interrupt prose when it opens at 1, and ``<br>``
    between items."""
    lines = escaped.split("\n")
    out: list[str] = []
    in_list = False
    for i, line in enumerate(lines):
        m = _ITEM.match(line)
        if not m:
            in_list = False
            out.append(("\n" if i else "") + line)
            continue
        marker = m.group(2)
        bullet = marker in ("-", "*")
        interrupts_prose = i > 0 and not in_list and lines[i - 1].strip() != ""
        if not bullet and interrupts_prose and marker != "1.":
            in_list = False
            out.append("\n" + line)
            continue
        in_list = True
        rendered = _BULLET if bullet else f"({marker[:-1]}) "
        out.append(("<br>" if i else "") + rendered + line[m.end() :])
    return "".join(out)


def test_bullets_become_a_rendered_bullet_character() -> None:
    """Items are joined with <br>, not a bare newline: these surfaces compute
    white-space:normal, so a newline collapses and the items run together."""
    out = _inline_list_markers_python("Caveats:\n- verify the cost\n- keep the cap")
    assert out == f"Caveats:<br>{_BULLET}verify the cost<br>{_BULLET}keep the cap"


def test_ordinals_are_rendered_not_deleted() -> None:
    """The ordinal must survive. Stripping it renders cleanly and silently
    loses the sequence — the rejected alternative, recorded in ADR-0011.
    """
    out = _inline_list_markers_python("Open items:\n1. cohort definition\n2. export gate")
    assert out == "Open items:<br>(1) cohort definition<br>(2) export gate"
    assert "1" in out and "2" in out, "the ordinal was deleted rather than rendered"


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
    assert out == "Open items:<br>(1) first<br>(2) second"


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
    assert out == f"{_BULLET}indented<br>{_BULLET}tabbed"


def test_no_markdown_marker_survives_the_mirror() -> None:
    """The mirror's own version of the e2e sweep: after rendering, none of the
    gate's marker patterns may still match.
    """
    raw = "Steps:\n1. instrument\n2. export\n- side note"
    out = _inline_list_markers_python(raw)
    assert re.search(r"(?:^|\n)[ \t]*1\.[ \t]", out) is None
    assert re.search(r"(?:^|\n)[ \t]*[-*][ \t]", out) is None
    # Positive partner: those same patterns DO match before rendering.
    assert re.search(r"(?:^|\n)[ \t]*1\.[ \t]", raw) is not None
    assert re.search(r"(?:^|\n)[ \t]*[-*][ \t]", raw) is not None
