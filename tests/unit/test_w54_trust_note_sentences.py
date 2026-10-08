"""W54 pull request 1 (ADR-0150 decision 2): the trust note names pages a
website asks automated tools not to read, in plain English.

``verifiedTrustDisclosure(ev, pagesInEffect)`` in ``app.js`` reads
``ev.source_pages_preview`` (P) beside N = ``source_pages_read`` and
M = ``source_pages_cited``; F = M - N - P. It is lifted out of ``app.js`` and
run under Node exactly as ``tests/unit/test_w29_trust_note_copy.py`` does
(that file's harness is reused), so the SERVED source is measured.

The session's sentences the owner approved (CHG-029 (b), "I approve all your
suggestions", 2026-10-06) are pinned VERBATIM as literals, not rebuilt from
parts. The other rows are the session's wording, recorded in ADR-0150's table;
``expected`` below is that table written as code, and the sweep compares every
reachable (N, P, M) with M from 1 to 12 against it.

Failure modes (``docs/analysis/2026-10-07-w54-blocked-wording-and-passages-failure-modes.md``):
1 and 2 (a false claim about what was checked), 3 (old runs keep today's
sentences; impossible counts fail closed), 4 (posture off unchanged).

Every test names what turns it red.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

import pytest
from tests.code_text import code_without_comments
from tests.unit.test_w29_trust_note_copy import APP_JS, FUNCTION, LEAD, TODAY, _extract_function
from tests.unit.test_w54_judge_source_pages_preview import (
    EXCERPT,
    FakeFetcher,
    _answer,
    _source,
)

from product_app import evaluation, source_fetcher
from product_app.config import settings

#: The session's sentence the owner approved (CHG-029 (b)): "when some pages
#: are blocked", in the plural for P >= 2 as the owner decided in CHG-033 (d)
#: (ADR-0152 decision 7). Until W54 step 2 this pinned the singular wording,
#: "For the other 2, the website asks automated tools not to read its pages,
#: so the check could only use the short preview the search engine showed."
APPROVED_SOME_BLOCKED = (
    "Checked against 3 of 5 cited pages. For the other 2, the websites ask automated tools "
    "not to read their pages, so the check could only use the short previews the search "
    "engine showed."
)
#: The session's sentence the owner approved (CHG-029 (b)), verbatim: "when
#: all are blocked".
APPROVED_ALL_BLOCKED = (
    "No cited page could be read: the websites ask automated tools not to read their pages. "
    "The check used only the titles, addresses and the short previews the search engine "
    "showed."
)
#: ADR-0150 decision 2's row N = 0, P = M = 1: the approved sentence in the
#: singular (the session's wording).
SINGLE_BLOCKED = (
    "No cited page could be read: the website asks automated tools not to read its pages. "
    "The check used only the title, address and the short preview the search engine showed."
)
_PREVIEW = (
    "the website asks automated tools not to read its pages, so the check could only use "
    "the short preview the search engine showed"
)
#: The plural of ``_PREVIEW``, for P >= 2 (ADR-0150 decision 2, review round
#: 2: several blocked pages may be on several websites). Since CHG-033 (d)
#: (ADR-0152 decision 7) the approved F = 0 row uses it too for P >= 2; it
#: kept ``_PREVIEW`` for every P before.
_PREVIEWS = (
    "the websites ask automated tools not to read their pages, so the check could only use "
    "the short previews the search engine showed"
)
#: ADR-0150 decision 2, review round 2 (failure mode 20): a page whose
#: robots.txt could not be read still sends its preview, so the N = 0 rows
#: never say "the titles and addresses" only.
NONE_READ_NO_PREVIEW = (
    "No cited page could be read. The check used only the titles, addresses and any short "
    "previews the search engine showed."
)
NONE_READ_NO_PREVIEW_ONE = (
    "No cited page could be read. The check used only the title, address and any short "
    "preview the search engine showed."
)
_FOR_THE_REST = (
    "for the rest it used the titles, addresses and any short previews the search engine showed"
)


def expected(n: int, p: int, m: int) -> str:
    """ADR-0150 decision 2's table, for whole counts with N + P <= M, M >= 1."""
    if n > 0:
        checked = f"Checked against {n} of {m} cited {'page' if m == 1 else 'pages'}."
        if p == 0:
            return f"{LEAD} {checked}"
        if m - n - p == 0:
            # CHG-033 (d): plural for P >= 2 (was _PREVIEW for every P).
            if p == 1:
                return f"{LEAD} {checked} For the other one, {_PREVIEW}."
            return f"{LEAD} {checked} For the other {p}, {_PREVIEWS}."
        blocked = _PREVIEW if p == 1 else _PREVIEWS
        return f"{LEAD} {checked} For {p} of the other {m - n}, {blocked}."
    if p == m:
        return f"{LEAD} {SINGLE_BLOCKED if m == 1 else APPROVED_ALL_BLOCKED}"
    if p == 0:
        return f"{LEAD} {NONE_READ_NO_PREVIEW_ONE if m == 1 else NONE_READ_NO_PREVIEW}"
    blocked = _PREVIEW if p == 1 else _PREVIEWS
    return f"{LEAD} No cited page could be read. For {p} of the {m}, {blocked}; {_FOR_THE_REST}."


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


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
        ["node", "-e", script], capture_output=True, text=True, timeout=60, check=True
    )
    decoded: list[str] = json.loads(out.stdout)
    return decoded


def _ev(n: Any, p: Any, m: Any) -> dict[str, Any]:
    """N read, P checked by preview, M cited -- in the ADR's order."""
    return {"source_pages_read": n, "source_pages_preview": p, "source_pages_cited": m}


# ---------------------------------------------------------------------------
# The session's sentences the owner approved, verbatim.
# ---------------------------------------------------------------------------


def test_the_approved_sentence_when_some_pages_are_blocked(harness: str) -> None:
    """CHG-029 (b), N = 3, P = 2, M = 5 (F = 0), in the plural CHG-033 (d)
    chose for two or more pages. RED IF: the sentence differs from the
    approved one by one character (the singular "the website asks ... its
    pages ... the short preview" is now a failure), or still says
    "robots.txt", or the old W29 sentence is shown (P ignored)."""
    (text,) = _run(harness, [(_ev(3, 2, 5), True)])
    assert text == f"{LEAD} {APPROVED_SOME_BLOCKED}"
    assert "robots" not in text


def test_the_approved_sentence_when_all_pages_are_blocked(harness: str) -> None:
    """CHG-029 (b), N = 0, P = M = 4. RED IF: the sentence differs from the
    approved one by one character, or today's "search excerpts" sentence is shown
    (ADR-0150's context: "search excerpts" means little to a reader)."""
    (text,) = _run(harness, [(_ev(0, 4, 4), True)])
    assert text == f"{LEAD} {APPROVED_ALL_BLOCKED}"
    assert "search excerpts" not in text and "robots" not in text


# ---------------------------------------------------------------------------
# Every row of the table.
# ---------------------------------------------------------------------------

_ROWS = [
    # (N, P, M, the exact sentence after the lead)
    (3, 0, 5, "Checked against 3 of 5 cited pages."),
    (3, 2, 5, APPROVED_SOME_BLOCKED),
    (
        2,
        1,
        5,
        f"Checked against 2 of 5 cited pages. For 1 of the other 3, {_PREVIEW}.",
    ),
    (
        1,
        2,
        5,
        f"Checked against 1 of 5 cited pages. For 2 of the other 4, {_PREVIEWS}.",
    ),
    (0, 4, 4, APPROVED_ALL_BLOCKED),
    (0, 1, 1, SINGLE_BLOCKED),
    (
        0,
        2,
        5,
        f"No cited page could be read. For 2 of the 5, {_PREVIEWS}; {_FOR_THE_REST}.",
    ),
    (
        0,
        1,
        5,
        f"No cited page could be read. For 1 of the 5, {_PREVIEW}; {_FOR_THE_REST}.",
    ),
    (0, 0, 3, NONE_READ_NO_PREVIEW),
    (0, 0, 1, NONE_READ_NO_PREVIEW_ONE),
    (4, 3, 7, APPROVED_SOME_BLOCKED.replace("3 of 5", "4 of 7").replace("other 2", "other 3")),
]


@pytest.mark.parametrize(
    ("n", "p", "m", "sentence"),
    _ROWS,
    ids=[
        "read-no-preview",
        "read-preview-no-failure",
        "read-preview-and-failure",
        "read-two-previews-and-failures",
        "none-read-all-preview",
        "none-read-one-of-one-preview",
        "none-read-some-preview",
        "none-read-one-preview-of-several",
        "none-read-no-preview",
        "none-read-no-preview-one-cited",
        "approved-row-plural-for-three",  # CHG-033 (d); was singular
    ],
)
def test_each_row_of_the_table_verbatim(
    harness: str, n: int, p: int, m: int, sentence: str
) -> None:
    """ADR-0150 decision 2, one row each, exact text. RED IF: any row's
    sentence differs by a character, a row is swapped with another (for
    example the approved "For the other P" used when some unread pages failed
    for another reason, which is false), or a row's numbers are wrong."""
    (text,) = _run(harness, [(_ev(n, p, m), True)])
    assert text == f"{LEAD} {sentence}"
    assert text == expected(n, p, m)


def test_singulars(harness: str) -> None:
    """Decision 2: "cited page" when M is 1; "For the other one," when P is 1
    and F = 0. RED IF: "1 of 1 cited pages", "For the other 1,", or the
    singular used when F > 0 ("For 1 of the other 2" must stay)."""
    one_of_one, other_one, one_of_other = _run(
        harness, [(_ev(1, 0, 1), True), (_ev(2, 1, 3), True), (_ev(1, 1, 3), True)]
    )
    assert one_of_one == f"{LEAD} Checked against 1 of 1 cited page."
    assert other_one == f"{LEAD} Checked against 2 of 3 cited pages. For the other one, {_PREVIEW}."
    assert one_of_other == (
        f"{LEAD} Checked against 1 of 3 cited pages. For 1 of the other 2, {_PREVIEW}."
    )


# ---------------------------------------------------------------------------
# P missing, posture off, impossible counts.
# ---------------------------------------------------------------------------


def test_p_missing_keeps_todays_w29_sentences(harness: str) -> None:
    """Failure mode 3: a run whose evaluation carries no ``source_pages_preview``
    key (stored or served before this change) keeps today's W29 sentences,
    unchanged. RED IF: a missing P is read as 0 (N = 0 would then show the new
    "titles and addresses" sentence, and N = 2 would be unaffected, so this
    pair catches it), or as anything else."""
    none_read, two_read = _run(
        harness,
        [
            ({"source_pages_read": 0, "source_pages_cited": 4}, True),
            ({"source_pages_read": 2, "source_pages_cited": 4}, True),
        ],
    )
    assert none_read == (
        f"{LEAD} It worked from the titles, addresses and any search excerpts: "
        "no cited page could be read."
    )
    assert two_read == f"{LEAD} Checked against 2 of 4 cited pages."


def test_posture_off_keeps_todays_sentence_whatever_the_counts(harness: str) -> None:
    """Failure mode 4: with the setting off the note is today's, even if
    counts are present. RED IF: the posture is ignored once P is present.
    Partner: the same counts with the posture on read differently."""
    off, on = _run(harness, [(_ev(3, 2, 5), False), (_ev(3, 2, 5), True)])
    assert off == TODAY
    assert on != TODAY


@pytest.mark.parametrize(
    "ev",
    [
        _ev(3, 3, 5),
        _ev(0, 6, 5),
        _ev(2, -1, 5),
        _ev(-1, 2, 5),
        _ev(2, 1.5, 5),
        _ev(2, "1", 5),
        _ev(2, True, 5),
        _ev(None, 2, 5),
        _ev(2, 1, None),
    ],
    ids=[
        "n-plus-p-over-m",
        "p-over-m",
        "negative-p",
        "negative-n",
        "fractional-p",
        "string-p",
        "boolean-p",
        "n-null",
        "m-null",
    ],
)
def test_impossible_counts_fail_closed_to_the_posture_off_sentence(harness: str, ev: Any) -> None:
    """Decision 2: "Impossible counts (not whole numbers, N + P > M) fail
    closed to the posture-off sentence." RED IF: any of these renders a
    pages sentence (for example "For 3 of the other 2", or "For the other
    -1"). The boolean is not a whole number in JSON; JavaScript's
    ``Number.isInteger(true)`` is false."""
    (text,) = _run(harness, [(ev, True)])
    assert text == TODAY


# ---------------------------------------------------------------------------
# The sweep: every reachable (N, P, M), M from 1 to 12.
# ---------------------------------------------------------------------------

_SWEEP = [(n, p, m) for m in range(1, 13) for n in range(m + 1) for p in range(m - n + 1)]


def test_the_sweep_matches_the_table_and_never_says_something_false(harness: str) -> None:
    """Every (N, P, M) with 0 <= N, P, N + P <= M and M from 1 to 12: 454 of
    them. (M = 0 is left out: the server never serves counts with nothing
    cited, and two rows of the table would both match it.)
    RED IF, for any of them: the sentence is not the table's; it says a
    website asked tools not to read its pages when P = 0, or mentions a
    preview at all when P = 0 and N > 0; it says no cited page could be read when N > 0; it
    states a number that is not N, P, M or M - N; or it omits N and M when
    pages were read; the singular all-blocked sentence is not used for
    (0, 1, 1); a sentence with N = 0 says the check used "the titles and
    addresses" only (false when a robots.txt could not be read but its preview
    was sent, failure mode 20); any sentence says "the website asks" for two
    or more previews, or "the websites ask" for one (CHG-033 (d) made the
    approved F = 0 row plural for P >= 2 too).
    Partner: the sweep really covers the approved sentences, the singular
    one, and every row (each row's shape appears)."""
    assert len(_SWEEP) == 454
    texts = _run(harness, [(_ev(n, p, m), True) for n, p, m in _SWEEP])
    shapes: set[str] = set()
    for (n, p, m), text in zip(_SWEEP, texts, strict=True):
        case = (n, p, m)
        assert text == expected(n, p, m), case
        after = text.removeprefix(f"{LEAD} ")
        assert after != text, case
        if p == 0:
            assert "automated tools" not in after, case
            if n > 0:
                assert "preview" not in after, case
        else:
            assert "automated tools not to read" in after, case
        if n > 0:
            assert "No cited page could be read" not in after, case
            assert after.startswith(f"Checked against {n} of {m} cited "), case
        assert "titles and addresses." not in after, case
        if n == 0:
            assert "any short preview" in after or p == m, case
        if p >= 2:
            assert "the websites ask automated tools not to read their pages" in after, case
            assert "the website asks" not in after, case
        if p == 1:
            assert "the website asks automated tools not to read its pages" in after, case
            assert "websites" not in after, case
        numbers = {int(x) for x in re.findall(r"\d+", after)}
        assert numbers <= {n, p, m, m - n}, (case, numbers)
        shapes.add(re.sub(r"\d+", "#", after))
    assert f"{LEAD} {APPROVED_SOME_BLOCKED}" in texts
    assert f"{LEAD} {APPROVED_ALL_BLOCKED}" in texts
    assert texts[_SWEEP.index((0, 1, 1))] == f"{LEAD} {SINGLE_BLOCKED}"
    assert len(shapes) >= 12, sorted(shapes)


# ---------------------------------------------------------------------------
# Why the N = 0 sentences mention previews (failure mode 20).
# ---------------------------------------------------------------------------


def test_a_preview_sent_for_an_unreadable_robots_file_is_not_denied_by_the_sentence(
    harness: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review round 2. One cited page whose robots.txt answered 503: the
    judge reads its search preview, yet P = 0, because the website asked
    nothing. The sentence for the counts ``judge_source_pages`` returns must
    not say the check used the title and address only. RED IF: the (0, 0, 1)
    sentence says "titles and addresses" or "title and address" only.
    Partners: the preview really is in what the judge reads, and P really is
    0 for it, so the sentence below is the one this page gets."""
    monkeypatch.setattr(settings, "quorum_source_fetch_max_text_chars", 4000)
    monkeypatch.setattr(settings, "quorum_source_fetch_max_pages", 8)
    url = "https://unreadable-robots.example/page"
    monkeypatch.setattr(
        source_fetcher, "fetch_cited_pages", FakeFetcher({url: ("robots_unchecked", "")})
    )
    reading = evaluation.judge_source_pages([_answer([_source(url, EXCERPT)])])
    assert reading.pages == (EXCERPT,)
    counts = (reading.read, reading.preview, reading.cited)
    assert counts == (0, 0, 1)
    (text,) = _run(harness, [(_ev(*counts), True)])
    assert text == f"{LEAD} {NONE_READ_NO_PREVIEW_ONE}"
    assert "short preview" in text
