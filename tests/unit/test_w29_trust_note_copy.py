"""W29 (ADR-0148 decision 9, failure mode 8): the trust note says what the
judge actually read.

With the setting in effect (the page reads ``source_pages_in_effect`` from the
readiness island, ADR-0116), a verified panel run's note says "Checked
against N of M cited pages", N and M being the run's own served counts
(``evaluation.source_pages_read`` / ``evaluation.source_pages_cited``). When N
is 0 it says no cited page could be read. With the setting off, or with no
counts served, today's ``TRUST_DISCLOSURE_VERIFIED`` is shown unchanged; its
exact text stays pinned by ``tests/unit/test_judge_disclosure_is_honest.py``.

THE FUNCTION UNDER TEST (named by this test, not by ADR-0148):
``verifiedTrustDisclosure(ev, pagesInEffect)`` in ``app.js`` returns the
disclosure string for the verified branch. It is lifted out of ``app.js`` by
brace count and run under Node, as ``test_receipt_attribution_note.py`` does,
so the SERVED source is measured. The harness supplies the one constant it may
read, ``TRUST_DISCLOSURE_VERIFIED``, taken from the comment-stripped source;
any other helper it calls must be inlined, or this harness raises
ReferenceError (the same constraint ``composerShapeCopy`` documents).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.code_text import code_without_comments

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"
FUNCTION = "verifiedTrustDisclosure"

#: Today's verified disclosure, as ``test_judge_disclosure_is_honest.py`` pins it.
TODAY = (
    "An independent judge model checked this answer's citations against its "
    "source list — an automated review, not a human fact-check. The cited "
    "pages themselves were not retrieved."
)
NOT_RETRIEVED = "The cited pages themselves were not retrieved."


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    assert marker in source, f"app.js has no `{marker}` — the W29 copy function is missing"
    start = source.index(marker)
    i = source.index("(", start)
    depth = 0
    while True:
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    brace = source.index("{", i)
    depth = 0
    i = brace
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


@pytest.fixture(scope="module")
def harness() -> str:
    code = code_without_comments(APP_JS)
    constant = re.findall(r'const TRUST_DISCLOSURE_VERIFIED\s*=\s*\n?\s*"([^"]+)";', code)
    assert constant == [TODAY], constant
    return f"const TRUST_DISCLOSURE_VERIFIED = {json.dumps(TODAY)};\n" + _extract_function(
        code, FUNCTION
    )


def _run(harness: str, cases: list[tuple[Any, bool]]) -> list[str]:
    script = (
        harness
        + "\n\nconst cases = "
        + json.dumps(cases)
        + f";\nconsole.log(JSON.stringify(cases.map(([ev, on]) => {FUNCTION}(ev, on))));\n"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    decoded: list[str] = json.loads(out.stdout)
    return decoded


def _ev(read: Any, cited: Any) -> dict[str, Any]:
    return {"source_pages_read": read, "source_pages_cited": cited}


def test_the_note_states_the_runs_own_counts(harness: str) -> None:
    """RED IF: the counts are not the run's (a constant, or the two swapped),
    or the "not retrieved" sentence survives on a run whose pages WERE read
    (a false statement beside the true one)."""
    three_of_five, one_of_eight = _run(harness, [(_ev(3, 5), True), (_ev(1, 8), True)])
    assert "Checked against 3 of 5 cited pages" in three_of_five, three_of_five
    assert "Checked against 1 of 8 cited pages" in one_of_eight, one_of_eight
    assert NOT_RETRIEVED not in three_of_five
    assert NOT_RETRIEVED not in one_of_eight


#: Today's sentence without its last sentence: what every pages sentence
#: starts with (``lead`` in ``app.js``).
LEAD = (
    "An independent judge model checked this answer's citations against its "
    "source list — an automated review, not a human fact-check."
)


def test_no_page_read_says_so(harness: str) -> None:
    """Decision 9 (review round 1): N = 0 says no cited page could be read and
    the judge worked from the titles, addresses and any search excerpts. Exact
    text. RED IF: the N = 0 sentence differs by a character (for example the
    round-0 "titles and addresses only", which hid that excerpts were read), or
    N = 0 renders today's sentence. Partner: N = 2 does not say it."""
    none_read, two_read = _run(harness, [(_ev(0, 4), True), (_ev(2, 4), True)])
    assert none_read == (
        f"{LEAD} It worked from the titles, addresses and any search excerpts: "
        "no cited page could be read."
    )
    assert "no cited page could be read" not in two_read


def test_one_cited_page_is_singular_and_more_are_plural(harness: str) -> None:
    """Decision 9: "cited page" when M is 1. Exact text. RED IF: the singular
    is wrong ("1 of 1 cited pages"), or the plural is dropped for M >= 2."""
    one_of_one, one_of_two, three_of_five = _run(
        harness, [(_ev(1, 1), True), (_ev(1, 2), True), (_ev(3, 5), True)]
    )
    assert one_of_one == f"{LEAD} Checked against 1 of 1 cited page."
    assert one_of_two == f"{LEAD} Checked against 1 of 2 cited pages."
    assert three_of_five == f"{LEAD} Checked against 3 of 5 cited pages."


def test_setting_off_keeps_todays_sentence_even_with_counts(harness: str) -> None:
    """With the setting off today's wording stays (decision 9), whatever the
    evaluation carries. RED IF: the posture argument is ignored. Partner: the
    same evaluation with the setting on reads differently."""
    off, on = _run(harness, [(_ev(3, 5), False), (_ev(3, 5), True)])
    assert off == TODAY
    assert on != TODAY


@pytest.mark.parametrize(
    "ev",
    [_ev(None, None), {}, None, _ev(None, 5), _ev(3, None)],
    ids=["both-null", "absent", "no-evaluation", "read-null", "cited-null"],
)
def test_no_counts_keeps_todays_sentence(harness: str, ev: Any) -> None:
    """Counts are ``None`` when pages were not read. RED IF: a missing count
    renders a pages sentence (for example "Checked against null of 5")."""
    (text,) = _run(harness, [(ev, True)])
    assert text == TODAY


@pytest.mark.parametrize(
    "ev",
    [_ev("3", "5"), _ev(3.5, 5), _ev(-1, 5), _ev(6, 5)],
    ids=["strings", "fraction", "negative", "read-above-cited"],
)
def test_impossible_counts_fail_closed_to_todays_sentence(harness: str, ev: Any) -> None:
    """Fail closed, like every other verified-branch guard in
    ``renderTrustScore``: a count that is not a whole number from 0 to M
    cannot be stated as a check. RED IF: any of these renders a pages
    sentence. (The session's reading of failure mode 8, not ADR text.)"""
    (text,) = _run(harness, [(ev, True)])
    assert text == TODAY


def test_the_verified_branch_renders_through_the_function_and_reads_the_island() -> None:
    """The node tests above prove the function; this proves the page uses it.
    RED IF: ``renderTrustScore`` still hands the bare constant to the
    disclosure line, or nothing in the page reads the island's
    ``source_pages_in_effect`` (the posture would then be assumed, not served).
    """
    code = code_without_comments(APP_JS)
    render = _extract_function(code, "renderTrustScore")
    assert f"{FUNCTION}(" in render
    assert not re.search(
        r'mkEl\(\s*"p",\s*"result-trust-score-disclosure",\s*TRUST_DISCLOSURE_VERIFIED\s*\)', render
    )
    assert re.search(r"\.source_pages_in_effect\b", code), "the page never reads the posture"
