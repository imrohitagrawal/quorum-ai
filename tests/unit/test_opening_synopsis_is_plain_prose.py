"""A model's OPENING synopsis must never show Markdown syntax.

The surface this was written for was the "How positions moved" opening cell,
removed in ADR-0063. The synopsis itself still ships — in the Markdown export's
"What each model opened with" section — so the contract below still binds.

WHY THIS EXISTS
---------------
Issue #257 §2. One real paid run (`qr_415a22cb476c4ee3969ed6ed39f0f6bb`,
2026-08-05) put this on screen, verbatim, in the OPENING column:

    Claude Haiku 4.5 -> "# PostgreSQL Scaling Decision for Your B2B SaaS Based
                         on your profile (40-person B2B SaaS, ~400M rows, write
                         timeouts), **you should not sha…"
    Nemotron 3 Nano  -> "## TL;DR | Option | When it makes sense | Rough effort
                         & risk | Typical cost impact | |--------|--------------…"

The surface is NOT bypassing the renderer — `app.js` routes it through
`setInlineProse`. The cause is upstream: `_opening_synopsis` cuts the RAW
answer at 140 characters, and truncating Markdown then rendering it can never
work, because a cut can always sever a span. That live paragraph held exactly
ONE `**` and ended mid-sentence; no renderer can pair a marker whose partner
the cut removed. ADR-0014 measured the same orphan rendering literally in BOTH
candidate parsers — it is correct CommonMark, not a parser bug.

So the synopsis is made PLAIN PROSE **before** it is truncated. After that a cut
cannot sever anything, because there is nothing left to sever.

WHAT MAKES THIS HARD, AND WHY THE RULES ARE SO NARROW
-----------------------------------------------------
A previous attempt (branch `fix/markdown-renderer`, abandoned) wrote a stripper
and two review lenses destroyed it. Its defects are the tests below:

  * it turned `__init__` into `init` — the product stating a fact the model did
    not. So this stripper touches NO underscore, ever.
  * it turned `**3**x cheaper` into `3**x cheaper` — a neighbour rule that
    deleted the opening marker and kept the closing one.
  * it flattened `cat access.log | grep 500 | wc -l` into
    `cat access.log grep 500 wc -l` — the command SHOWN was wrong, because any
    line with pipes was treated as a table.
  * it ate the separator row of a table inside a fenced code block, in an
    answer whose whole point was showing how to write one.

Every one of those is a test here, and each is a case where doing LESS is
correct.
"""

from __future__ import annotations

import pytest

from product_app.debate import _opening_synopsis, _strip_block_markup

# --- the two shapes a real user saw (#257 §2) --------------------------------


def test_a_heading_led_answer_shows_no_hash() -> None:
    """RED IF: the ATX heading marker is not stripped.

    The live string began "# PostgreSQL Scaling Decision for Your B2B SaaS".
    """
    answer = (
        "# PostgreSQL Scaling Decision for Your B2B SaaS\n\n"
        "Based on your profile (40-person B2B SaaS, ~400M rows, write timeouts), "
        "**you should not shard yet** — vertical scaling buys you 18 months."
    )
    out = _opening_synopsis(answer)
    assert not out.lstrip().startswith("#")
    assert "#" not in out
    # Positive partner: the words must survive. A stripper that returned "" or
    # dropped the heading line would satisfy the assertions above.
    assert "PostgreSQL Scaling Decision" in out


def test_a_truncated_bold_span_leaves_no_orphan_marker() -> None:
    """RED IF: truncation happens BEFORE the markers are removed.

    This is the whole defect. The live paragraph held exactly one `**` and
    ended mid-sentence.
    """
    answer = (
        "Based on your profile (40-person B2B SaaS, roughly 400M rows, and "
        "intermittent write timeouts under load), **you should not shard yet** "
        "because vertical scaling still buys you about eighteen months."
    )
    out = _opening_synopsis(answer)
    assert "**" not in out, f"an orphan bold marker survived: {out!r}"
    assert "you should not shard yet" in out


def test_a_table_led_answer_shows_no_separator_skeleton() -> None:
    """RED IF: a GFM separator row survives the flattening.

    The live string was "## TL;DR | Option | When it makes sense | Rough effort
    & risk | Typical cost impact | |--------|------------------…" — the second
    run of pipes is the separator row, which carries no words at all.
    """
    answer = (
        "## TL;DR\n\n"
        "| Option | When it makes sense | Rough effort |\n"
        "|--------|--------------------|--------------|\n"
        "| Scale vertically | CPU headroom exists | Low |\n"
    )
    out = _opening_synopsis(answer)
    assert "|---" not in out and "|--" not in out, f"separator row survived: {out!r}"
    assert "---" not in out, f"a dash run survived: {out!r}"
    # Positive partner: the header row's WORDS must survive. Dropping the whole
    # table would pass the assertions above and tell the user nothing.
    assert "Option" in out
    assert "When it makes sense" in out


# --- the four things the abandoned stripper broke ----------------------------


def test_dunder_identifiers_are_untouched() -> None:
    """RED IF: the stripper starts touching underscores.

    `__init__` -> `init` is the product stating a fact the model did not. No
    underscore is ever removed, which also protects `snake_case`,
    `retention_flag` and `_private`.
    """
    answer = "Override __init__ and __repr__ in the subclass, and keep retention_flag set."
    out = _opening_synopsis(answer)
    assert "__init__" in out
    assert "__repr__" in out
    assert "retention_flag" in out


def test_python_varargs_survive_because_they_are_unpaired() -> None:
    """RED IF: `**` is stripped unconditionally rather than only in PAIRS.

    `**kwargs` has no closing `**`, so removing it deletes real content — the
    model wrote Python, not emphasis. `*args` is a single `*` and is never
    touched at all.
    """
    answer = "Pass *args and **kwargs straight through to the parent constructor."
    out = _opening_synopsis(answer)
    assert "*args" in out
    assert "**kwargs" in out


def test_a_model_authored_unclosed_bold_marker_is_left_alone() -> None:
    """The one case this fix deliberately does NOT clean up, stated as a test
    so it is a decision rather than an oversight.

    An unpaired ``**`` has exactly two possible origins and they are
    syntactically identical — both are ``**`` followed by a word character:

      * ``**kwargs`` — Python. Removing the marker DELETES content.
      * ``and **this bold span is severed`` — a model that opened bold and
        never closed it.

    The one that mattered was the third origin, a marker severed by
    TRUNCATION, and stripping before truncating removes it entirely: after
    ``_strip_block_markup`` runs on the FULL answer, every pair is already
    resolved, so an orphan that remains is one the model really wrote. Between
    "show a stray ``**`` a model actually emitted" and "delete the ``*`` from
    someone's ``**kwargs``", this product's rule is to never delete content.

    RED IF: someone makes the bold rule unconditional to chase this case. That
    turns ``test_python_varargs_survive_because_they_are_unpaired`` red too,
    which is the point — the two tests are a pair.
    """
    answer = "and **this bold span is severed"
    assert _opening_synopsis(answer) == answer


def test_a_backtick_span_is_verbatim_and_the_bold_rule_never_fires_inside_it() -> None:
    """Inline code is verbatim by contract, so the `**` rule must skip it.

    This is the mitigation the corpus names for `**kwargs` and `__init__`
    ("Protect it inside backticks"), and until this test it was a CLAIM with no
    coverage: `diff-cover` reported the code-span re-insertion branch
    (`out.append(spans[index])`) as the single uncovered changed line, at 96%.
    A claimed protection that nothing exercises is precisely what this repo
    keeps paying for.

    RED IF: the split-on-code-spans logic is dropped, or the re-insertion loop
    stops putting the spans back — that second one DELETES the code span from
    the answer outright, which is content loss.
    """
    # A bold PAIR inside a code span survives with its markers intact...
    assert _strip_block_markup("run `a**b**c` now") == "run `a**b**c` now"
    # ...while a pair OUTSIDE one is still stripped, in the same string.
    assert _strip_block_markup("**Note:** run `a**b**c`") == "Note: run `a**b**c`"
    # Several spans in one line: every one must come back, in order.
    assert (
        _strip_block_markup("use `**kwargs` and `__init__` and `x|y`")
        == "use `**kwargs` and `__init__` and `x|y`"
    )
    # And through the real entry point, which is what a user actually sees.
    out = _opening_synopsis("Pass `**kwargs` through to `__init__` unchanged.")
    assert "`**kwargs`" in out
    assert "`__init__`" in out


def test_a_bold_run_against_a_digit_is_removed_from_both_sides() -> None:
    """RED IF: a neighbour rule is reintroduced.

    The abandoned fix produced `3**x cheaper` — it deleted the opening marker
    and kept the closing one, so its own headline case was still broken.
    """
    answer = "Vertical scaling is **3**x cheaper than sharding for this workload."
    out = _opening_synopsis(answer)
    assert "**" not in out
    assert "3x cheaper" in out


def test_a_shell_pipeline_keeps_its_pipes() -> None:
    """RED IF: "the line has pipes" is used as the table test.

    The abandoned fix flattened this to `cat access.log grep 500 wc -l`. The
    product then SHOWED a command that does not do what it says.
    """
    answer = "Start by counting them: cat access.log | grep 500 | wc -l gives the rate."
    out = _opening_synopsis(answer)
    assert "cat access.log | grep 500 | wc -l" in out


def test_arithmetic_and_alternation_are_untouched() -> None:
    """A lone `*` is multiplication far more often than emphasis here, and a
    pipe is alternation. Neither is markup."""
    for answer in (
        "Budget roughly 5 * 3 reviewer-hours per cohort for this.",
        "Rerunning it costs 3*40 per cohort and 2*12 per quarter, which is fine.",
        "Use the a|b|c delimiter form for the export filter.",
    ):
        assert _opening_synopsis(answer) == answer


def test_a_table_inside_a_fenced_block_keeps_its_separator_row() -> None:
    """RED IF: the separator-row rule ignores fenced code.

    The abandoned fix ate the separator inside a fence, in an answer whose
    whole point was showing the user how to write a table.
    """
    answer = "Write it like this:\n```\n| A | B |\n|---|---|\n| 1 | 2 |\n```\n"
    out = _opening_synopsis(answer, limit=400)
    assert "|---|---|" in out, f"the fenced separator row was eaten: {out!r}"


def test_a_dash_rule_outside_a_table_is_not_mistaken_for_a_separator() -> None:
    """A separator row is only a separator when a HEADER row precedes it.

    Without that guard a thematic break, or a line of dashes a model uses as a
    divider, would be treated as table syntax.
    """
    answer = "Summary of the options.\n\n---\n\nVertical scaling wins here."
    # Asserted on the STRIPPER, not the synopsis: `_opening_synopsis` returns
    # the FIRST SENTENCE when one fits, so it would stop at "Summary of the
    # options." no matter what the dash rule did — the test would have proved
    # nothing about the behaviour it names.
    stripped = _strip_block_markup(answer)
    assert "Summary of the options." in stripped
    assert "Vertical scaling wins here." in stripped
    assert "---" in stripped, "a thematic break outside a table is not table syntax"


# --- properties that must hold for EVERY input --------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "# Heading only",
        "**bold** at the start",
        "| A | B |\n|---|---|\n| 1 | 2 |",
        "```\n| A |\n|---|\n```",
        "*",
        "**",
        "***",
        "`",
        "#",
        "#no space",
        "plain prose with nothing special in it at all",
        "a" * 500,
        "**" + "a" * 500 + "**",
        "\n\n\n",
        "   ",
    ],
)
def test_the_synopsis_is_always_non_empty_and_bounded(answer: str) -> None:
    """Deterministic, always non-empty, never longer than the limit + ellipsis.

    RED IF: any input path returns "" or overruns the bound. The docstring on
    `_opening_synopsis` already promised non-empty; nothing checked it against
    the shapes the stripper now handles.
    """
    out = _opening_synopsis(answer)
    assert out, f"empty synopsis for {answer!r}"
    assert len(out) <= 141, f"{len(out)} chars for {answer!r}: {out!r}"
    # Determinism: same input, same output.
    assert _opening_synopsis(answer) == out


def test_no_gate_marker_survives_any_corpus_shape() -> None:
    """The synopsis, swept with the same marker patterns the BLOCKING e2e gate
    uses on rendered text nodes.

    The synopsis lands on an INLINE surface, where a heading cannot be built and
    a `**` cannot be paired, so these are precisely the markers that reach a
    text node and fire that gate.
    """
    import re

    shapes = [
        "# PostgreSQL Scaling Decision\n\nDo not shard yet.",
        "## TL;DR\n\n| Option | Effort |\n|---|---|\n| Vertical | Low |",
        "**Bottom line:** do not shard yet, vertical scaling is enough.",
        "### Recommendation\n\n**Proceed** with the phased rollout.",
        # The #257 shape, in full: a long answer whose bold span sits ACROSS the
        # 140-character cut. This is the case the whole change exists for, and
        # the one an orphan marker used to come from.
        "Based on your profile (40-person B2B SaaS, roughly 400M rows, and "
        "intermittent write timeouts under sustained load), **you should not "
        "shard yet** because vertical scaling still buys about eighteen months.",
    ]
    for shape in shapes:
        out = _opening_synopsis(shape)
        assert "**" not in out, f"bold marker survived {shape!r}: {out!r}"
        assert re.search(r"(^|\s)#{1,6}\s", out) is None, f"heading marker survived: {out!r}"
        assert "|--" not in out, f"separator row survived: {out!r}"
        # Positive partner: every one of those shapes DOES carry a marker before
        # the strip, so "no marker found" is not true over an empty input.
        assert ("**" in shape) or re.search(r"(^|\n)#{1,6}\s", shape) or "|--" in shape


def test_an_empty_or_invisible_answer_still_gets_the_stand_in() -> None:
    """The pre-existing contract, kept: a failed answer yields a fixed string.

    RED IF: the stripper runs before the visibility check and turns an
    all-markup answer into "" that then reads as a real (blank) answer.
    """
    for answer in ("", "   ", "\n\n", "\u200b", "# \n"):
        assert _opening_synopsis(answer) == "No usable answer was returned for this model."
