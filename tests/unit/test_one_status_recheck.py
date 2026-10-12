"""Re-check of package B (one status): the status-field negation is read per source line.

ADR-0162. A narrow re-check at 8c7838d found that the status-field negation
("Merged: no" is a negation, not a claim) was judged on the unit's visible text,
where the line breaks inside a paragraph become spaces. So a status block
written one field per line ("Pushed: yes" / "Merged: no" / "In production: no")
read as "Merged: no In production: no", and the honest "Merged: no" was
refused; "Merged: no (blocked on CI)" was refused too.

A status field is a source-line construct, so it is now decided on the source
line that holds the claim word: the word, then ":", then a field value that
runs to the end of that source line or to the next ".", ";" or "|". The value
must be exactly "no" or "not yet", with optional closing punctuation, emphasis
markers and one parenthesized remark. A value wrapped onto the next source line
is read per line, so "Merged: no" followed by a line "conflicts with main." is
a negation (ADR-0162 says so).

GATE CHARTER
------------
WHY THIS EXISTS: the re-check reproduced the refused status block with an input
that every existing test accepted as a claim.

WHAT IT CANNOT SEE: wordings and Markdown shapes other than the ones here.

FALSE-POSITIVE COST: none beyond the check under test.

WHEN TO REMOVE: with the check under test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root
from tests.status_clone import load_script

ROOT = find_repo_root(Path(__file__))


def _completion() -> Any:
    return load_script(ROOT, "check_completion_claims")


class _NoCitation:
    """A citation source that supports nothing, so every counted claim is reported."""

    def supports(self, _text: str) -> bool:
        return False

    def fetch_hint(self, _text: str) -> str:
        return ""


def _reported(text: str) -> tuple[list[tuple[int, str]], int]:
    """(line, word) for every claim reported anywhere in ``text``, and how many were counted."""
    lines = set(range(1, text.count("\n") + 2))
    problems, claims = _completion().problems_in_text("x.md", text, lines, _NoCitation())
    found = []
    for problem in problems:
        match = re.match(r"x\.md:(\d+): '([^']+)'", problem)
        assert match, problem
        found.append((int(match.group(1)), match.group(2).lower()))
    return sorted(found), claims


@pytest.mark.parametrize(
    "text",
    [
        # One paragraph, one field per source line: the re-check's reproduction.
        "Pushed: yes\nMerged: no\nIn production: no",
        "Merged: no (blocked on CI)",
        "Merged: no.",
        "Merged: not yet",
        "Merged: **no**",
        "Pushed: yes. Merged: no. In production: no.",
        "Merged: no; pushed: yes",
        # A value wrapped onto the next source line is read per line: the field on
        # line 1 is exactly "no", so it is a negation (ADR-0162).
        "Merged: no\nconflicts with main.",
    ],
)
def test_a_status_field_whose_value_on_its_source_line_is_no_is_not_a_claim(text: str) -> None:
    # Red when: the field value is read on the unit's joined text, so the next source line
    # ("In production: no", "conflicts with main.") becomes part of the value, or when a
    # parenthesized remark, emphasis around "no", or a "." / ";" field separator after "no"
    # makes an honest "Merged: no" a claim.
    assert _reported(text) == ([], 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Merged: no doubt.", [(1, "merged")]),
        ("In production: no issues detected.", [(1, "in production")]),
        ("Verified: no regressions in the e2e lane.", [(1, "verified")]),
        ("W55 and W56 merged: no conflicts.", [(1, "merged")]),
        ("Release 1 is complete: no open blockers.", [(1, "complete")]),
        ("Merged: no -- see below", [(1, "merged")]),
        # A comma is not a field separator: the value runs on to the next ".", ";" or "|".
        ("In production: no, apart from the hotfix build.", [(1, "in production")]),
    ],
)
def test_a_status_field_whose_value_only_starts_with_no_is_a_claim(
    text: str, expected: list[tuple[int, str]]
) -> None:
    # Red when: "<word>: no" cancels the word although more of the field value follows "no"
    # on the same source line ("no doubt", "no issues detected", "no -- see below"), or when
    # a comma ends the field value ("no, apart from the hotfix build").
    assert _reported(text) == (expected, len(expected))


def test_a_status_block_one_field_per_line_still_reports_a_yes_field() -> None:
    # Red when: the per-line reading cancels every field in the block, so the "yes" field
    # on line 3 is no longer a claim. Partner of the accepted block above.
    text = "Pushed: yes\nMerged: no\nIn production: yes"
    assert _reported(text) == ([(3, "in production")], 1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Merged: no\nIn production: yes", [(2, "in production")]),
        ("Merged: not yet\nIn production: yes", [(2, "in production")]),
        ("Merged: **no**\nIn production: yes", [(2, "in production")]),
    ],
)
def test_a_field_value_no_does_not_negate_the_next_lines_word(
    text: str, expected: list[tuple[int, str]]
) -> None:
    # Red when: the negation look-back crosses the line break after a status field, so the
    # field value "no" or "not yet" on one line cancels the claim word that opens the next.
    assert _reported(text) == (expected, len(expected))


@pytest.mark.parametrize("text", ["W55 has not\nbeen merged.", "W55 is not\nin production."])
def test_a_plain_negation_wrapped_onto_the_next_line_still_negates(text: str) -> None:
    # Red when: the look-back stops at every line break, so a sentence wrapped between its
    # negation and its word becomes a claim. Partner of the test above.
    assert _reported(text) == ([], 0)
