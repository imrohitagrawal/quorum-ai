"""W54 step 2 (ADR-0152 decision 4): the trust note names the pages checked by
their search preview for a reason other than a website's rules.

``verifiedTrustDisclosure(ev, pagesInEffect)`` in ``app.js`` reads
``ev.source_pages_preview_other`` (Q) beside N = ``source_pages_read``,
P = ``source_pages_preview`` and M = ``source_pages_cited``;
R = M - N - P - Q. It is lifted out of ``app.js`` and run under Node by the
harness of ``tests/unit/test_w54_trust_note_sentences.py`` (reused), so the
SERVED source is measured.

``expected`` below is ADR-0152 decision 4's table written as code: the lead,
then the rules part, the previews part and the rest part, joined with single
spaces, with the two whole-sentence cases replacing the parts. The owner's
approved sentences (CHG-029 (b)) are imported as the literals ADR-0150's
tests pin, never rebuilt.

ONE READING OF THE TABLE, stated so a reviewer can overturn it: when N = 0 and
P = M the rules part is ADR-0150's approved all-blocked sentence, which itself
begins "No cited page could be read:", so it REPLACES the N = 0 lead rather
than following it (the alternative prints "No cited page could be read." twice).
With Q present and Q = 0 this gives exactly ADR-0150's sentence for that row.

Failure modes (``docs/analysis/2026-10-08-w54-step2-previews-and-reserve-failure-modes.md``):
6 (a false claim, or the owner's wording lost) and 7 (Q missing keeps
ADR-0150's sentences).

Every test names what turns it red.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from tests.unit.test_w29_trust_note_copy import LEAD, TODAY
from tests.unit.test_w54_trust_note_sentences import (
    _PREVIEW,
    _PREVIEWS,
    APPROVED_ALL_BLOCKED,
    APPROVED_SOME_BLOCKED,
    SINGLE_BLOCKED,
    _needs_node,  # noqa: F401 - autouse: skip without node
    _run,
    harness,  # noqa: F401 - the module-scoped node harness
)
from tests.unit.test_w54_trust_note_sentences import expected as adr_0150_expected

NO_PAGE = "No cited page could be read."
ALL_PREVIEWED = (
    "No cited page could be read. The check used only the titles, addresses and the short "
    "previews the search engine showed."
)
ONE_PREVIEWED = (
    "No cited page could be read. The check used only the title, address and the short "
    "preview the search engine showed."
)


def _ev(n: Any, p: Any, q: Any, m: Any) -> dict[str, Any]:
    """N read, P refused by a website's rules, Q other previews, M cited."""
    return {
        "source_pages_read": n,
        "source_pages_preview": p,
        "source_pages_preview_other": q,
        "source_pages_cited": m,
    }


def _rules(n: int, p: int, m: int) -> str:
    """ADR-0150's blocked sentence for the case, ending at "...showed."."""
    if n > 0 and p == m - n:
        # The approved sentence, plural for P >= 2 (CHG-033 (d), ADR-0152
        # decision 7); it was singular for every P until review round 1.
        return f"For the other one, {_PREVIEW}." if p == 1 else f"For the other {p}, {_PREVIEWS}."
    blocked = _PREVIEW if p == 1 else _PREVIEWS
    if n > 0:
        return f"For {p} of the other {m - n}, {blocked}."
    return f"For {p} of the {m}, {blocked}."


def _previews(p: int, q: int) -> str:
    other = " other" if p > 0 else ""
    if q == 1:
        return (
            f"For 1{other} cited page that could not be read, the check used the short "
            "preview the search engine showed."
        )
    return (
        f"For {q}{other} cited pages that could not be read, the check used the short "
        "previews the search engine showed."
    )


def expected(n: int, p: int, q: int, m: int) -> str:
    """ADR-0152 decision 4, for whole counts with N + P + Q <= M, M >= 1."""
    r = m - n - p - q
    if n == 0 and p == 0 and q == m:
        return f"{LEAD} {ONE_PREVIEWED if m == 1 else ALL_PREVIEWED}"
    parts: list[str] = []
    if n > 0:
        parts.append(f"Checked against {n} of {m} cited {'page' if m == 1 else 'pages'}.")
    if n == 0 and p == m:
        parts.append(SINGLE_BLOCKED if m == 1 else APPROVED_ALL_BLOCKED)
    else:
        if n == 0:
            parts.append(NO_PAGE)
        if p > 0:
            parts.append(_rules(n, p, m))
    if q > 0:
        parts.append(_previews(p, q))
    if n == 0 and p == 0 and q == 0:
        parts.append(
            "The check used only the title and address."
            if m == 1
            else "The check used only the titles and addresses."
        )
    elif n == 0 and r > 0:
        parts.append(
            "For the rest, it used the title and address."
            if r == 1
            else "For the rest, it used the titles and addresses."
        )
    return f"{LEAD} {' '.join(parts)}"


# ---------------------------------------------------------------------------
# Every row and part of the table, verbatim.
# ---------------------------------------------------------------------------

_P1 = (
    "For 1 cited page that could not be read, the check used the short preview the search "
    "engine showed."
)
_P1_OTHER = (
    "For 1 other cited page that could not be read, the check used the short preview the "
    "search engine showed."
)

_ROWS: list[tuple[int, int, int, int, str]] = [
    # Lead N > 0 with previews only (P = 0): no "other", no rest part.
    (
        3,
        0,
        4,
        7,
        "Checked against 3 of 7 cited pages. For 4 cited pages that could not be read, the "
        "check used the short previews the search engine showed.",
    ),
    (2, 0, 1, 5, f"Checked against 2 of 5 cited pages. {_P1}"),
    # Lead N > 0, M = 1 is singular (Q = 0 here, so ADR-0150's row).
    (1, 0, 0, 1, "Checked against 1 of 1 cited page."),
    # Rules part (P = M - N) is the owner's approved sentence, Q = 0.
    (3, 2, 0, 5, APPROVED_SOME_BLOCKED),
    # Rules part "For P of the other M-N" ends at "showed." with no tail;
    # previews part with "other" (Q = 1, then Q >= 2).
    (
        2,
        1,
        1,
        5,
        f"Checked against 2 of 5 cited pages. For 1 of the other 3, {_PREVIEW}. {_P1_OTHER}",
    ),
    (
        1,
        2,
        2,
        5,
        f"Checked against 1 of 5 cited pages. For 2 of the other 4, {_PREVIEWS}. For 2 other "
        "cited pages that could not be read, the check used the short previews the search "
        "engine showed.",
    ),
    # N > 0 with unread pages that had no preview: no rest part (R > 0, N > 0).
    (2, 1, 0, 5, f"Checked against 2 of 5 cited pages. For 1 of the other 3, {_PREVIEW}."),
    # N = 0: the rules part "For P of the M", the previews part, the rest part.
    (
        0,
        1,
        1,
        4,
        f"{NO_PAGE} For 1 of the 4, {_PREVIEW}. {_P1_OTHER} For the rest, it used the titles "
        "and addresses.",
    ),
    (
        0,
        2,
        1,
        4,
        f"{NO_PAGE} For 2 of the 4, {_PREVIEWS}. {_P1_OTHER} For the rest, it used the title "
        "and address.",
    ),
    # N = 0, P = 0, Q > 0, R > 0: previews part without "other", rest part.
    (0, 0, 1, 2, f"{NO_PAGE} {_P1} For the rest, it used the title and address."),
    (
        0,
        0,
        2,
        5,
        f"{NO_PAGE} For 2 cited pages that could not be read, the check used the short "
        "previews the search engine showed. For the rest, it used the titles and addresses.",
    ),
    # N = 0, P > 0, Q = 0, R > 0: rules part, rest part.
    (
        0,
        1,
        0,
        3,
        f"{NO_PAGE} For 1 of the 3, {_PREVIEW}. For the rest, it used the titles and addresses.",
    ),
    # N = 0, P + Q = M, both > 0: no rest part (R = 0).
    (
        0,
        2,
        2,
        4,
        f"{NO_PAGE} For 2 of the 4, {_PREVIEWS}. For 2 other cited pages that could not be "
        "read, the check used the short previews the search engine showed.",
    ),
    # N = 0, P = M: the approved all-blocked sentence and its singular.
    (0, 4, 0, 4, APPROVED_ALL_BLOCKED),
    (0, 1, 0, 1, SINGLE_BLOCKED),
    # N = 0, P = 0, Q = 0: the titles and addresses only, and the singular.
    (0, 0, 0, 3, f"{NO_PAGE} The check used only the titles and addresses."),
    (0, 0, 0, 1, f"{NO_PAGE} The check used only the title and address."),
    # The two whole-sentence cases.
    (0, 0, 3, 3, ALL_PREVIEWED),
    (0, 0, 1, 1, ONE_PREVIEWED),
]


@pytest.mark.parametrize(
    ("n", "p", "q", "m", "sentence"),
    _ROWS,
    ids=[f"N{n}-P{p}-Q{q}-M{m}" for n, p, q, m, _ in _ROWS],
)
def test_each_row_and_part_verbatim(
    harness: str,  # noqa: F811
    n: int,
    p: int,
    q: int,
    m: int,
    sentence: str,
) -> None:
    """ADR-0152 decision 4, one case per row and part, exact text. RED IF:
    any part differs by a character; "other" appears without a rules part;
    the rules part keeps ADR-0150's tail about the rest; a rest part appears
    when R = 0 or N > 0; the owner's approved sentence is used where Q > 0;
    the whole-sentence cases are not used when every cited page had a
    preview; or a singular is wrong."""
    (text,) = _run(harness, [(_ev(n, p, q, m), True)])
    assert text == f"{LEAD} {sentence}"
    assert text == expected(n, p, q, m)


# ---------------------------------------------------------------------------
# Q missing; impossible counts; posture off.
# ---------------------------------------------------------------------------

_ADR_0150_CASES = [(3, 2, 5), (2, 1, 5), (0, 2, 5), (0, 0, 3), (0, 0, 1), (0, 4, 4), (0, 1, 1)]


@pytest.mark.parametrize("missing", ["absent", "null"])
def test_q_missing_keeps_adr_0150s_sentences(harness: str, missing: str) -> None:  # noqa: F811
    """Failure mode 7: a run served without Q (absent, or null as the
    projection serves a missing count, the convention ADR-0150 set for P)
    gets ADR-0150's sentences, unchanged, including the N = 0 tails about
    "any short previews". RED IF: a missing Q is read as 0 (the N = 0 rows
    would then lose their "any short preview(s)" tails). Partner: the same
    counts with Q = 0 present read differently for N = 0, P = 0."""
    cases = []
    for n, p, m in _ADR_0150_CASES:
        ev: dict[str, Any] = {
            "source_pages_read": n,
            "source_pages_preview": p,
            "source_pages_cited": m,
        }
        if missing == "null":
            ev["source_pages_preview_other"] = None
        cases.append((ev, True))
    texts = _run(harness, cases)
    assert texts == [adr_0150_expected(n, p, m) for n, p, m in _ADR_0150_CASES]
    (with_q,) = _run(harness, [(_ev(0, 0, 0, 3), True)])
    assert with_q != adr_0150_expected(0, 0, 3)


@pytest.mark.parametrize(
    "ev",
    [
        _ev(2, 1, 3, 5),  # N + P + Q > M
        _ev(0, 0, 6, 5),  # Q > M
        _ev(2, 1, -1, 5),  # negative Q
        _ev(2, 1, 1.5, 5),  # fractional Q
        _ev(2, 1, "1", 5),  # string Q
        _ev(2, 1, True, 5),  # boolean Q
        _ev(2, -1, 1, 5),  # negative P with Q present
        _ev(-1, 1, 1, 5),  # negative N with Q present
        _ev(2, 1, 1, 4.5),  # fractional M
    ],
    ids=[
        "n-plus-p-plus-q-over-m",
        "q-over-m",
        "negative-q",
        "fractional-q",
        "string-q",
        "boolean-q",
        "negative-p",
        "negative-n",
        "fractional-m",
    ],
)
def test_impossible_counts_show_the_posture_off_sentence(harness: str, ev: Any) -> None:  # noqa: F811
    """Decision 4: "Impossible counts (not whole numbers, negative,
    N + P + Q > M) show the sentence used when page reading is off". RED IF:
    any of these renders a pages sentence -- for example (2, 1, 3, 5), whose
    N + P = 3 <= 5 passes ADR-0150's check, renders "For 3 other cited pages"
    of 2 unread. Partner: (2, 1, 2, 5) one under the limit is a pages
    sentence."""
    (text,) = _run(harness, [(ev, True)])
    assert text == TODAY
    (fits,) = _run(harness, [(_ev(2, 1, 2, 5), True)])
    assert fits == expected(2, 1, 2, 5) != TODAY


def test_posture_off_keeps_todays_sentence_with_q(harness: str) -> None:  # noqa: F811
    """With page reading off the note is today's whatever the counts. RED IF:
    Q present makes the page ignore the posture. Partner: the same counts
    with the posture on read differently."""
    off, on = _run(harness, [(_ev(0, 0, 2, 3), False), (_ev(0, 0, 2, 3), True)])
    assert off == TODAY
    assert on == expected(0, 0, 2, 3) != TODAY


# ---------------------------------------------------------------------------
# The sweep: every (N, P, Q, M), M from 1 to 10.
# ---------------------------------------------------------------------------

_SWEEP = [
    (n, p, q, m)
    for m in range(1, 11)
    for n in range(m + 1)
    for p in range(m - n + 1)
    for q in range(m - n - p + 1)
]


def test_the_sweep_matches_the_table_and_never_says_something_false(
    harness: str,  # noqa: F811
) -> None:
    """Every whole (N, P, Q, M) with N + P + Q <= M and M from 1 to 10: 1,000
    cases. (M = 0 is left out, as in ADR-0150's sweep: the server serves no
    counts when nothing was cited.)
    RED IF, for any of them: the sentence is not the table's; it says a
    website asks tools not to read its pages when P = 0; it says no cited page
    could be read when N > 0; it says "other" when P = 0 (the word is set
    against a rules part); it claims titles and addresses (a rest part) when
    R = 0, or names a rest at all when N > 0; it omits the preview when Q > 0;
    it states a number that is not N, P, Q, M, M - N or R; or its parts are not
    joined by single spaces; or a blocked-page part is singular for P >= 2
    or plural for P = 1 (CHG-033 (d)). Partner: the sweep really covers the
    approved sentences and every part's shape."""
    assert len(_SWEEP) == 1000
    texts = _run(harness, [(_ev(*case), True) for case in _SWEEP])
    shapes: set[str] = set()
    for (n, p, q, m), text in zip(_SWEEP, texts, strict=True):
        case = (n, p, q, m)
        r = m - n - p - q
        assert text == expected(n, p, q, m), case
        after = text.removeprefix(f"{LEAD} ")
        assert after != text, case
        if p == 0:
            assert "automated tools" not in after, case
            assert "other" not in after, case
        # CHG-033 (d), ADR-0152 decision 7: one blocked page is singular, two
        # or more plural, in every sentence including the approved one.
        if p == 1:
            assert "the website asks automated tools not to read its pages" in after, case
            assert "websites" not in after, case
        if p >= 2:
            assert "the websites ask automated tools not to read their pages" in after, case
            assert "the website asks" not in after, case
        if n > 0:
            assert "No cited page could be read" not in after, case
            assert after.startswith(f"Checked against {n} of {m} cited "), case
            assert "the rest" not in after and "addresses" not in after, case
        if r == 0:
            assert "titles and addresses" not in after, case
            assert "title and address" not in after, case
            assert "the rest" not in after, case
        if q > 0:
            assert "could not be read, the check used the short preview" in after or (
                n == 0 and p == 0 and q == m
            ), case
        numbers = {int(x) for x in re.findall(r"\d+", after)}
        assert numbers <= {n, p, q, m, m - n, r}, (case, numbers)
        assert "  " not in text and not text.endswith(" "), case
        assert re.fullmatch(r"(?:[^ .][^.]*\.)(?: [A-Z][^.]*\.)*", after), case
        shapes.add(re.sub(r"\d+", "#", after))
    assert f"{LEAD} {APPROVED_SOME_BLOCKED}" in texts
    assert f"{LEAD} {APPROVED_ALL_BLOCKED}" in texts
    assert texts[_SWEEP.index((0, 1, 0, 1))] == f"{LEAD} {SINGLE_BLOCKED}"
    assert texts[_SWEEP.index((0, 0, 1, 1))] == f"{LEAD} {ONE_PREVIEWED}"
    assert len(shapes) >= 20, sorted(shapes)
