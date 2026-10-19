"""Every security measure in docs/41-security-controls.md must name tests that exist.

docs/41 lists the security measures SC-01 to SC-103 in tables, one row each. A
row that says a measure is TESTED is worth something only if the test it names
is real.

WHAT IT READS: the tables markdown-it-py renders from docs/41 with its
"gfm-like" preset (GitHub-flavoured tables, raw HTML on), as GitHub's GFM would
show them. That is markdown-it-py, not GitHub's own renderer, and the two can
differ on odd input. Linkify is turned off: it needs a package this repository
does not declare, and it only wraps bare URLs in links. A row inside an HTML
comment, a fenced or indented code block or a ``<script>`` block does not
render, so it is not read, and its id is then reported missing.

A MEASURE TABLE is a rendered table whose header has seven cells, with the text
``Proof`` in the fourth and ``Status`` in the seventh. Its body rows are the
measure rows. The rules:

1. The measure ids are exactly SC-01 to SC-103, each once. They are written out
   by hand below, so the document cannot define its own population. An ID cell
   whose text is not ``SC-`` and two digits, or ``SC-`` and three digits not
   starting with 0 (SC-100 onward, added by W86), is reported.
2. A body row of any other table whose first cell is an SC id (ignoring spaces)
   is reported. That is how a measure table whose header lost its Proof or
   Status column shows up.
3. Measure, Where, Runs in and Status are filled in; a cell holding only spaces
   or dashes counts as empty. The GFM table rules, which markdown-it-py
   follows, pad a short row with empty cells and drop cells beyond the
   header's seven, so a row with too few cells is reported as having an
   empty cell, and extra cells are never seen.
4. The first word of Status, less a trailing full stop, is TESTED, PARTIAL,
   CODE-ONLY, MEASURED or UNKNOWN. In a cell, ``<br>``, ``<br/>`` and
   ``<br />`` (in any case, with no attributes) and soft and hard line breaks
   read as a space. An ID or Status cell holding struck-out text is reported: a
   reader takes it as withdrawn, and the check does not guess what is left.
   Struck-out means ``~~…~~``, or an opening ``<s>``, ``<del>`` or ``<strike>``
   tag in any case, bare or with attributes whose values hold no ``>``.
5. A TESTED or PARTIAL row names at least one pytest test or e2e spec.
6. Every pytest test named is a ``test_`` function in a ``test_*.py`` file
   under ``tests/``, defined at the top level of that file or directly inside a
   ``Test`` class there (found by parsing the file, not by searching its text),
   with no ``@pytest.mark.skip`` decorator. If a name is defined twice, the
   last definition counts, as in Python. ruff's F811, which ``make lint`` runs
   in the ``validate-and-test`` CI job, refuses most redefinitions, but not one
   whose first definition is used in between (``original = test_x`` between
   the two ``def`` lines passes it).
7. Every e2e spec named is an existing ``.spec.ts`` file under ``e2e/tests/``.

Citations are read from the code spans (backticked text) in the Proof cell:
``tests/<path>/test_<x>.py::test_<name>``,
``tests/<path>/test_<x>.py::Test<Class>::test_<name>`` or
``e2e/tests/<path>.spec.ts``. Other code spans are ignored, except that one
starting ``tests/`` or ``e2e/tests/``, holding both ``tests/`` and ``::``, or
holding both ``e2e/tests/`` and ``.spec.ts`` is always read as a citation, so
a mistyped one is reported instead of skipped.

WHAT THIS CANNOT SEE. Read these before trusting a green run.

- Whether a named test really exercises its measure. One unrelated test named
  by every row would pass. Review is the defence.
- Any skip other than a ``@pytest.mark.skip`` or ``@mark.skip`` decorator on
  the test itself. It does not run pytest's collector, so each of these still
  counts as a real test: ``skipif``; a mark on the module or the class; a skip
  by a fixture, at run time or by a conftest hook; ``import pytest as pt`` then
  ``@pt.mark.skip``; a mark bound to a variable first;
  ``test_x = pytest.mark.skip(...)(test_x)``; ``xfail(run=False)``;
  ``unittest.skip``; an empty ``parametrize``; a name deleted or rebound after
  its ``def``; ``__test__ = False``; a fixture whose name starts ``test_``; a
  ``Test`` class with an ``__init__``; a file in a folder pytest skips by
  default, such as ``tests/build/``.
- A citation that is not in a code span.
- A raw HTML ``<table>``: it renders, but only Markdown tables are read.
- A ``<br>`` with attributes, such as ``<br class=note>``, is not read as a
  break: ``TE<br class=note>STED`` reads as TESTED and is accepted, and
  ``TESTED<br class=note>Details`` reads as one word and is refused.
- A strike tag whose attribute holds ``>``, such as ``<s title=">">`` or the same
  with ``<del>``, is not recognised, so the struck text is read as live.
- An empty strike element, such as ``<s></s>TESTED`` or ``<s></s>SC-01``, is
  reported as struck although nothing is struck.
- An e2e citation proves only that the spec file exists, not that the test
  title after it exists in that file, or that anything runs it.
- The Measure, Where and Runs in cells are checked only for being filled in,
  and Decided by not at all. None of them is compared with the code.
- A MEASURED status needs no date, and an UNKNOWN status is accepted as it is.
- Where a measure sits among the measure tables (a sign-in measure under the
  wrong heading, say) is not checked.
- Look-alike letters, such as a Cyrillic "С" for the Latin "C", in the first
  cell of a non-measure table are not read as an id.
- markdown-it-py reads ``\\|`` (an escaped backslash, then a pipe) as an
  escaped pipe and keeps the cell whole. Whether GitHub splits there is not
  checked here.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest
from markdown_it import MarkdownIt
from markdown_it.token import Token

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = "docs/41-security-controls.md"

# Written out by hand on purpose (rule 1). Deriving this from the document
# would let a dropped row shrink the expectation along with it.
_EXPECTED_ID_TEXT = """
SC-01 SC-02 SC-03 SC-04 SC-05 SC-06 SC-07 SC-08 SC-09 SC-10
SC-11 SC-12 SC-13 SC-14 SC-15 SC-16 SC-17 SC-18 SC-19 SC-20
SC-21 SC-22 SC-23 SC-24 SC-25 SC-26 SC-27 SC-28 SC-29 SC-30
SC-31 SC-32 SC-33 SC-34 SC-35 SC-36 SC-37 SC-38 SC-39 SC-40
SC-41 SC-42 SC-43 SC-44 SC-45 SC-46 SC-47 SC-48 SC-49 SC-50
SC-51 SC-52 SC-53 SC-54 SC-55 SC-56 SC-57 SC-58 SC-59 SC-60
SC-61 SC-62 SC-63 SC-64 SC-65 SC-66 SC-67 SC-68 SC-69 SC-70
SC-71 SC-72 SC-73 SC-74 SC-75 SC-76 SC-77 SC-78 SC-79 SC-80
SC-81 SC-82 SC-83 SC-84 SC-85 SC-86 SC-87 SC-88 SC-89 SC-90
SC-91 SC-92 SC-93 SC-94 SC-95 SC-96 SC-97 SC-98 SC-99 SC-100
SC-101 SC-102 SC-103
"""
EXPECTED_IDS = frozenset(_EXPECTED_ID_TEXT.split())

COLUMNS = ("ID", "Measure", "Where", "Proof", "Runs in", "Decided by", "Status")
REQUIRED_CELLS = ("Measure", "Where", "Runs in", "Status")
STATUSES = frozenset({"TESTED", "PARTIAL", "CODE-ONLY", "MEASURED", "UNKNOWN"})
NEEDS_A_PROOF = frozenset({"TESTED", "PARTIAL"})
UNCONDITIONAL_SKIPS = frozenset({"pytest.mark.skip", "mark.skip"})

_MARKDOWN = MarkdownIt("gfm-like", {"linkify": False})
_MEASURE_ID = re.compile(r"SC-(?:[0-9][0-9]|[1-9][0-9][0-9])")
_EMPTY_CELL = re.compile(r"[\s\-\u2013\u2014]*")
_BREAK_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)
_STRIKE_TAG = re.compile(r"<(?:s|del|strike)(?:\s[^>]*)?>", re.IGNORECASE)


@dataclass(frozen=True)
class Cell:
    """A rendered table cell: its text, its code spans, and whether any text is struck out."""

    text: str
    code: tuple[str, ...]
    struck: bool


@dataclass(frozen=True)
class Problem:
    """One broken rule: which rule, which measure, and what was found."""

    rule: str
    measure: str
    detail: str


def rendered_tables(text: str) -> list[list[list[Cell]]]:
    """Every table markdown-it-py renders from *text*, as rows of cells, header first."""
    tables: list[list[list[Cell]]] = []
    row: list[Cell] = []
    in_cell = False
    for token in _MARKDOWN.parse(text):
        if token.type == "table_open":
            tables.append([])
        elif token.type == "tr_open":
            row = []
        elif token.type in ("th_open", "td_open"):
            in_cell = True
        elif token.type in ("th_close", "td_close"):
            in_cell = False
        elif token.type == "inline" and in_cell:
            row.append(_cell(token))
        elif token.type == "tr_close":
            tables[-1].append(row)
    return tables


def _cell(inline: Token) -> Cell:
    children = inline.children or []
    parts: list[str] = []
    for child in children:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak") or (
            child.type == "html_inline" and _BREAK_TAG.fullmatch(child.content)
        ):
            parts.append(" ")
    struck = any(
        child.type == "s_open"
        or (child.type == "html_inline" and _STRIKE_TAG.fullmatch(child.content) is not None)
        for child in children
    )
    code = tuple(child.content.strip() for child in children if child.type == "code_inline")
    return Cell("".join(parts).strip(), code, struck)


def check_security_controls(text: str, root: Path, expected_ids: frozenset[str]) -> list[Problem]:
    """Every rule in the module docstring, applied to *text*.

    *root* is the repository root that test citations are resolved against.
    """
    problems: list[Problem] = []
    seen: set[str] = set()
    for header, *body in rendered_tables(text):
        is_measure_table = (
            len(header) == len(COLUMNS)
            and header[COLUMNS.index("Proof")].text == "Proof"
            and header[COLUMNS.index("Status")].text == "Status"
        )
        for cells in body:
            measure = cells[0].text
            if not is_measure_table:
                squeezed = re.sub(r"\s+", "", measure)
                if _MEASURE_ID.fullmatch(squeezed):
                    problems.append(
                        Problem("row-outside-measure-table", squeezed, "not in a measure table")
                    )
                continue
            if cells[0].struck:
                problems.append(Problem("cell-struck", measure, "the ID holds struck-out text"))
                continue
            if not _MEASURE_ID.fullmatch(measure):
                problems.append(
                    Problem(
                        "id-malformed",
                        measure,
                        "the ID is not SC- and two digits, or three not starting with 0",
                    )
                )
                continue
            if measure in seen:
                problems.append(Problem("id-duplicate", measure, "a second row for this id"))
            seen.add(measure)
            problems.extend(_check_row(dict(zip(COLUMNS, cells, strict=True)), root))
    for missing in sorted(expected_ids - seen):
        problems.append(Problem("id-missing", missing, "no measure row has this id"))
    for extra in sorted(seen - expected_ids):
        problems.append(Problem("id-extra", extra, "not one of the expected measure ids"))
    return problems


def _check_row(row: dict[str, Cell], root: Path) -> list[Problem]:
    measure = row["ID"].text
    problems: list[Problem] = []
    for name in REQUIRED_CELLS:
        if _EMPTY_CELL.fullmatch(row[name].text):
            problems.append(Problem("cell-empty", measure, f"the {name} cell is empty"))
    status = ""
    if row["Status"].struck:
        problems.append(Problem("cell-struck", measure, "the Status holds struck-out text"))
    elif not _EMPTY_CELL.fullmatch(row["Status"].text):
        status = row["Status"].text.split()[0].removesuffix(".")
        if status not in STATUSES:
            problems.append(
                Problem("status-unknown", measure, f"status {status!r} is not a known status")
            )
    citations = 0
    for token in row["Proof"].code:
        if token.startswith("tests/") or ("tests/" in token and "::" in token):
            citations += 1
            problems.extend(_check_pytest_citation(token, root, measure))
        elif token.startswith("e2e/tests/") or ("e2e/tests/" in token and ".spec.ts" in token):
            citations += 1
            problems.extend(_check_spec_citation(token, root, measure))
    if status in NEEDS_A_PROOF and citations == 0:
        problems.append(
            Problem("no-proof", measure, f"{status} but the Proof cell names no test or spec")
        )
    return problems


def _check_pytest_citation(token: str, root: Path, measure: str) -> list[Problem]:
    def found(rule: str, why: str) -> list[Problem]:
        return [Problem(rule, measure, f"`{token}` {why}")]

    file_part, separator, rest = token.partition("::")
    names = rest.split("::")
    if (
        not file_part.startswith("tests/")
        or not separator
        or len(names) > 2
        or not all(name.isidentifier() for name in names)
    ):
        return found("pytest-malformed", "is not tests/<path>/test_<x>.py::[Test<C>::]test_<y>")
    path = PurePosixPath(file_part)
    if ".." in path.parts:
        return found("pytest-outside-tests", "leaves the tests/ folder")
    if not fnmatch.fnmatchcase(path.name, "test_*.py"):
        return found("pytest-file-name", "is not in a test_*.py file")
    *classes, function = names
    if not function.startswith("test_"):
        return found("pytest-function-name", "names a function that does not start test_")
    if classes and not classes[0].startswith("Test"):
        return found("pytest-class-name", "names a class that does not start Test")
    source = root / file_part
    if not source.is_file():
        return found("pytest-file-missing", "names a file that does not exist")
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except SyntaxError:
        return found("pytest-file-unparsable", "names a file Python cannot parse")
    definition = _find_definition(tree, classes, function)
    if definition is None:
        return found("pytest-not-defined", "is not defined where the citation says")
    if any(_is_unconditional_skip(decorator) for decorator in definition.decorator_list):
        return found("pytest-skipped", "is marked @pytest.mark.skip")
    return []


def _find_definition(
    tree: ast.Module, classes: list[str], function: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The last top-level (or direct class member) definition, as Python binds it."""
    body: list[ast.stmt] = tree.body
    for name in classes:
        owners = [node for node in body if isinstance(node, ast.ClassDef) and node.name == name]
        if not owners:
            return None
        body = owners[-1].body
    matches = [
        node
        for node in body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == function
    ]
    return matches[-1] if matches else None


def _is_unconditional_skip(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    parts: list[str] = []
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if not isinstance(target, ast.Name):
        return False
    parts.append(target.id)
    return ".".join(reversed(parts)) in UNCONDITIONAL_SKIPS


def _check_spec_citation(token: str, root: Path, measure: str) -> list[Problem]:
    if not token.startswith("e2e/tests/"):
        return [Problem("e2e-malformed", measure, f"`{token}` does not start e2e/tests/")]
    if ".." in PurePosixPath(token).parts:
        return [Problem("e2e-outside", measure, f"`{token}` leaves the e2e/tests/ folder")]
    if not token.endswith(".spec.ts"):
        return [Problem("e2e-not-spec", measure, f"`{token}` is not a .spec.ts file")]
    if not (root / token).is_file():
        return [Problem("e2e-missing", measure, f"`{token}` does not exist")]
    return []


def _report(problems: Sequence[Problem]) -> str:
    missing = [problem.measure for problem in problems if problem.rule == "id-missing"]
    lines = [f"{DOCUMENT}: {len(problems)} problem(s)"]
    if missing:
        lines.append(f"  id-missing ({len(missing)}): {', '.join(missing)}")
    lines.extend(
        f"  {problem.measure} [{problem.rule}] {problem.detail}"
        for problem in problems
        if problem.rule != "id-missing"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The real document
# ---------------------------------------------------------------------------


def test_real_document_names_real_tests_for_every_measure() -> None:
    """docs/41 has exactly SC-01 to SC-103, each in a measure table, each proof real.

    Red when: docs/41 drops, adds or renumbers a measure row, moves one out of a
    measure table, or any row breaks rules 2 to 7 (for example, a cited test is
    renamed, deleted or skipped).
    """
    text = (REPO_ROOT / DOCUMENT).read_text(encoding="utf-8")
    problems = check_security_controls(text, REPO_ROOT, EXPECTED_IDS)
    assert not problems, _report(problems)


def test_the_hand_written_id_list_is_sc01_to_sc103() -> None:
    """The literal expected list has 103 distinct ids, SC-01 to SC-103
    (SC-103 added by W87-2, ADR-0175).

    Red when: an id in _EXPECTED_ID_TEXT is dropped, repeated or mistyped.
    """
    written = _EXPECTED_ID_TEXT.split()
    assert len(written) == 103
    assert len(set(written)) == 103
    assert set(written) == {f"SC-{number:02d}" for number in range(1, 104)}


# ---------------------------------------------------------------------------
# Partner tests: a stand-in repository and small documents, each breaking one rule
# ---------------------------------------------------------------------------

_FAKE_TEST_MODULE = """\
import pytest
from pytest import mark

GHOST_NAME = "test_ghost"  # test_ghost appears only in this comment and the string.
def test_alpha(): pass
async def test_async_alpha(): pass
def check_delta(): pass
class TestGroup:
    def test_beta(self): pass
class Helper:
    def test_gamma(self): pass
def outer():
    def test_nested(): pass
@pytest.mark.skip
def test_skipped_bare(): pass
@pytest.mark.skip(reason="off")
def test_skipped_called(): pass
@mark.skip
def test_skipped_short(): pass
@pytest.mark.skipif(True, reason="only on some machines")
def test_skipif_allowed(): pass
"""

# The stand-in repository's paths are built from these two prefixes on purpose.
# Written out whole, each one reads as a citation of a file in THIS repository
# to tests/unit/test_cited_paths_resolve.py, which fails on a cited path that
# does not exist. These exist only under tmp_path.
_TESTS_DIR = "tests"
_SPECS_DIR = "e2e/tests"
_FAKE = f"{_TESTS_DIR}/unit/test_fake.py"
_HELPER = f"{_TESTS_DIR}/unit/helper_mod.py"
_BROKEN = f"{_TESTS_DIR}/unit/test_broken.py"
_TOP = f"{_TESTS_DIR}/test_top.py"
_GONE = f"`{_TESTS_DIR}/unit/test_gone.py::test_gone`"
_SPEC = f"{_SPECS_DIR}/flow.spec.ts"
_SUPPORT = f"{_SPECS_DIR}/support.ts"

_FAKE_FILES = {
    _FAKE: _FAKE_TEST_MODULE,
    _HELPER: "def test_alpha() -> None:\n    pass\n",
    _BROKEN: "def test_x(:\n",
    _TOP: "def test_top() -> None:\n    pass\n",
    "other/test_outside.py": "def test_alpha() -> None:\n    pass\n",
    _SPEC: "// a stand-in spec\n",
    _SUPPORT: "// a helper, not a spec\n",
}

_SMALL_IDS = frozenset({"SC-01", "SC-02", "SC-03"})

_GOOD_ROWS: tuple[tuple[str, ...], ...] = (
    (
        "SC-01",
        "Sign-in is required",
        "the sign-in route",
        f"`{_FAKE}::test_alpha`",
        "pytest (Python 3.12)",
        "ADR-0001",
        "TESTED",
    ),
    (
        "SC-02",
        "Sessions are owned",
        "the session store",
        f'`{_FAKE}::TestGroup::test_beta`, `{_SPEC}` "signs in"',
        "pytest; e2e",
        "—",
        "PARTIAL. Only the browser half.",
    ),
    ("SC-03", "Keys stay on the server", "the settings", "—", "nothing runs it", "—", "CODE-ONLY"),
)

_HEADER = (
    "| ID | Measure | Where | Proof | Runs in | Decided by | Status |",
    "|---|---|---|---|---|---|---|",
)
_UNRELATED_ROW = "| Scope 1 | everything below |"


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    for relative, body in _FAKE_FILES.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


def _line(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _doc(rows: Iterable[Sequence[str] | str], header: Sequence[str] = _HEADER) -> str:
    """An unrelated table, then a measure table under *header*.

    A row given as a string is inserted verbatim; a sequence becomes cells.
    """
    lines = ["# Security measures", "", "| Setting | State |", "|---|---|", _UNRELATED_ROW, ""]
    lines.extend(header)
    lines.extend(row if isinstance(row, str) else _line(row) for row in rows)
    return "\n".join(lines) + "\n"


def _with_cell(index: int, column: int, value: str) -> list[tuple[str, ...]]:
    """The good rows with one cell replaced."""
    rows = [list(row) for row in _GOOD_ROWS]
    rows[index][column] = value
    return [tuple(row) for row in rows]


def _codes(problems: Iterable[Problem]) -> list[tuple[str, str]]:
    return sorted((problem.rule, problem.measure) for problem in problems)


def _check(document: str, root: Path) -> list[tuple[str, str]]:
    return _codes(check_security_controls(document, root, _SMALL_IDS))


def test_a_good_document_has_no_problems(fake_root: Path) -> None:
    """Positive partner for every rule below.

    The good document has a TESTED row, a PARTIAL row ending "PARTIAL." with a
    class method and an e2e spec plus a quoted title, and a CODE-ONLY row whose
    Proof and Decided by are "—" (both may be empty), under an unrelated table.

    Red when: the checker reports any problem on a document that obeys every
    rule, e.g. it stops removing the trailing "." from the status.
    """
    assert _check(_doc(_GOOD_ROWS), fake_root) == []


# Rule 1 -------------------------------------------------------------------


def test_a_full_size_document_matches_the_real_expected_ids(fake_root: Path) -> None:
    """Rows SC-01..SC-103, generated here independently, satisfy EXPECTED_IDS.

    Red when: EXPECTED_IDS stops being exactly SC-01 to SC-103, or a
    three-digit id (SC-100 to SC-103) is reported as malformed.
    """
    rows = [
        (f"SC-{n:02d}", "a measure", "a module", "—", "nothing runs it", "—", "CODE-ONLY")
        for n in range(1, 104)
    ]
    assert check_security_controls(_doc(rows), fake_root, EXPECTED_IDS) == []
    problems = check_security_controls(_doc(rows[:41] + rows[42:]), fake_root, EXPECTED_IDS)
    assert _codes(problems) == [("id-missing", "SC-42")]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([_GOOD_ROWS[0], _GOOD_ROWS[2]], [("id-missing", "SC-02")]),
        (
            [*_GOOD_ROWS, ("SC-04", "Extra", "a module", "—", "none", "—", "UNKNOWN")],
            [("id-extra", "SC-04")],
        ),
        ([*_GOOD_ROWS, _GOOD_ROWS[0]], [("id-duplicate", "SC-01")]),
        ([*_GOOD_ROWS, ("**SC-01**", *_GOOD_ROWS[0][1:])], [("id-duplicate", "SC-01")]),
    ],
    ids=["missing", "extra", "duplicate", "duplicate in bold"],
)
def test_a_missing_extra_or_repeated_id_is_reported(
    fake_root: Path, rows: list[tuple[str, ...]], expected: list[tuple[str, str]]
) -> None:
    """A bold "**SC-01**" renders as SC-01, so it is a second SC-01.

    Red when: the missing, extra or duplicate check is removed, or the ID is read
    from the Markdown source instead of the rendered text.
    """
    assert _check(_doc(rows), fake_root) == expected


@pytest.mark.parametrize(
    ("id_cell", "expected"),
    [
        ("SC-20", [("id-extra", "SC-20"), ("id-missing", "SC-02")]),
        ("SC-2", [("id-malformed", "SC-2"), ("id-missing", "SC-02")]),
        ("sc-02", [("id-malformed", "sc-02"), ("id-missing", "SC-02")]),
        ("SC 02", [("id-malformed", "SC 02"), ("id-missing", "SC-02")]),
        (f"SC{chr(0x2212)}02", [("id-malformed", f"SC{chr(0x2212)}02"), ("id-missing", "SC-02")]),
        ("", [("id-malformed", ""), ("id-missing", "SC-02")]),
        ("—", [("id-malformed", "—"), ("id-missing", "SC-02")]),
        # W86: three digits are allowed from SC-100 on, but not a padded
        # two-digit id or four digits.
        ("SC-002", [("id-malformed", "SC-002"), ("id-missing", "SC-02")]),
        ("SC-1000", [("id-malformed", "SC-1000"), ("id-missing", "SC-02")]),
    ],
)
def test_a_renumbered_or_malformed_id_is_reported(
    fake_root: Path, id_cell: str, expected: list[tuple[str, str]]
) -> None:
    """Red when: a measure row whose ID is not exactly SC- and two digits, or
    three not starting with 0 (a Unicode minus, a space, lower case, an empty
    cell, a padded ``SC-002``, four digits) is accepted or skipped."""
    assert _check(_doc(_with_cell(1, 0, id_cell)), fake_root) == expected


# Rule 2 -------------------------------------------------------------------


@pytest.mark.parametrize("id_cell", ["SC-02", "SC - 02"])
def test_a_measure_row_in_another_table_is_reported(fake_root: Path, id_cell: str) -> None:
    """Red when: a body row of a non-measure table whose first cell is an SC id,
    ignoring spaces, stops being reported."""
    moved = _line((id_cell, *_GOOD_ROWS[1][1:]))
    document = _doc([_GOOD_ROWS[0], _GOOD_ROWS[2]]).replace(
        _UNRELATED_ROW, _UNRELATED_ROW + "\n" + moved
    )
    assert _check(document, fake_root) == [
        ("id-missing", "SC-02"),
        ("row-outside-measure-table", "SC-02"),
    ]


@pytest.mark.parametrize(
    "labels",
    [
        "| ID | Measure | Where | Runs in | Decided by | Status |",
        "| ID | Measure | Where | Proof | Runs in | Decided by |",
        "| ID | Measure | Where | Status | Runs in | Decided by | Proof |",
        "| ID | Measure | Where | Tests | Runs in | Decided by | Status |",
        "| ID | Measure | Where | Proof | Runs in | Decided by | State |",
        "| ID | Measure | Where | Proof | Runs in | Decided by | Status | Notes |",
    ],
    ids=["no Proof", "no Status", "swapped", "Proof renamed", "Status renamed", "eight columns"],
)
def test_measure_rows_under_a_wrong_header_are_reported(fake_root: Path, labels: str) -> None:
    """Red when: the header's cell count, or its Proof or Status label, stops
    deciding whether a table is a measure table."""
    delimiter = "|" + "---|" * labels.count(" | ") + "---|"
    expected = [
        (rule, f"SC-0{n}")
        for rule in ("id-missing", "row-outside-measure-table")
        for n in (1, 2, 3)
    ]
    assert _check(_doc(_GOOD_ROWS, header=(labels, delimiter)), fake_root) == sorted(expected)


# Rule 3 -------------------------------------------------------------------


@pytest.mark.parametrize("column", [1, 2, 4, 6], ids=["Measure", "Where", "Runs in", "Status"])
@pytest.mark.parametrize("blank", ["", "—", " - "])
def test_an_empty_required_cell_is_reported(fake_root: Path, column: int, blank: str) -> None:
    """Red when: the empty-cell check is removed, or stops treating a dash as empty."""
    assert _check(_doc(_with_cell(2, column, blank)), fake_root) == [("cell-empty", "SC-03")]


def test_a_short_row_is_padded_and_extra_cells_are_dropped(fake_root: Path) -> None:
    """GFM pads a short row with empty cells and drops cells past the seventh.

    Red when: padded cells stop being checked as empty (the short SC-03 has no
    Runs in or Status), or a cell past the seventh is read (SC-01's eighth cell
    names a missing test).
    """
    short = _line(_GOOD_ROWS[2][:3])
    long = _line((*_GOOD_ROWS[0], _GONE))
    document = _doc([long, _GOOD_ROWS[1], short])
    assert _check(document, fake_root) == [("cell-empty", "SC-03"), ("cell-empty", "SC-03")]


# Rule 4 -------------------------------------------------------------------


@pytest.mark.parametrize("status", ["DONE", "tested", "Code-only", "TESTED:"])
def test_an_unknown_status_is_reported(fake_root: Path, status: str) -> None:
    """Red when: the status check is removed or stops being case-sensitive."""
    assert _check(_doc(_with_cell(2, 6, status)), fake_root) == [("status-unknown", "SC-03")]


@pytest.mark.parametrize("status", ["CODE-ONLY.", "MEASURED", "UNKNOWN. Nobody has looked."])
def test_a_row_naming_no_test_may_be_code_only_measured_or_unknown(
    fake_root: Path, status: str
) -> None:
    """Positive partner for rules 4 and 5.

    Red when: one of these statuses is rejected, or a row without a proof is
    reported even though its status does not claim a test.
    """
    assert _check(_doc(_with_cell(2, 6, status)), fake_root) == []


# Rule 5 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "proof"),
    [
        (0, "—"),
        (0, "covered by the suite"),
        (1, "run `make quality` and `pytest -q`"),
        (0, '`grep -rn "USER quorum" tests/`'),
        (0, f"<!-- `{_FAKE}::test_alpha` -->"),
    ],
    ids=["dash", "words", "commands", "a command naming tests/", "commented out"],
)
def test_a_tested_or_partial_row_naming_no_test_is_reported(
    fake_root: Path, index: int, proof: str
) -> None:
    """A citation inside an HTML comment does not render, so it is not a proof.

    Red when: a TESTED or PARTIAL row may name no pytest test and no e2e spec.
    """
    expected = [("no-proof", _GOOD_ROWS[index][0])]
    assert _check(_doc(_with_cell(index, 3, proof)), fake_root) == expected


def test_a_tested_row_may_name_only_an_e2e_spec(fake_root: Path) -> None:
    """Red when: an e2e spec stops counting as a proof for rule 5."""
    assert _check(_doc(_with_cell(0, 3, f"`{_SPEC}`")), fake_root) == []


# Rule 6 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("citation", "rule"),
    [
        (f"{_TESTS_DIR}/unit/test_missing.py::test_alpha", "pytest-file-missing"),
        (f"{_HELPER}::test_alpha", "pytest-file-name"),
        (f"{_FAKE}::check_delta", "pytest-function-name"),
        (f"{_FAKE}::Helper::test_gamma", "pytest-class-name"),
        (f"{_FAKE}::test_ghost", "pytest-not-defined"),
        (f"{_FAKE}::test_nested", "pytest-not-defined"),
        (f"{_FAKE}::test_beta", "pytest-not-defined"),
        (f"{_FAKE}::TestGroup::test_alpha", "pytest-not-defined"),
        (f"{_FAKE}::TestMissing::test_beta", "pytest-not-defined"),
        (f"{_FAKE}::test_skipped_bare", "pytest-skipped"),
        (f"{_FAKE}::test_skipped_called", "pytest-skipped"),
        (f"{_FAKE}::test_skipped_short", "pytest-skipped"),
        (f"{_FAKE}::test_alpha[1]", "pytest-malformed"),
        (f"{_FAKE}", "pytest-malformed"),
        (f"{_FAKE}:test_alpha", "pytest-malformed"),
        (f"{_FAKE}::TestGroup::Inner::test_beta", "pytest-malformed"),
        (f"./{_FAKE}::test_alpha", "pytest-malformed"),
        (f"src/{_FAKE}::test_alpha", "pytest-malformed"),
        (f"{_TESTS_DIR}/../other/test_outside.py::test_alpha", "pytest-outside-tests"),
        (f"{_BROKEN}::test_x", "pytest-file-unparsable"),
    ],
)
def test_a_bad_pytest_citation_is_reported(fake_root: Path, citation: str, rule: str) -> None:
    """Red when: the check behind *rule* is removed, or a citation with a prefix
    such as "./" stops being read as one. test_ghost appears in the stand-in
    file only in a comment and a string, so a text search would pass it."""
    assert _check(_doc(_with_cell(0, 3, f"`{citation}`")), fake_root) == [(rule, "SC-01")]


@pytest.mark.parametrize(
    "citation",
    [
        f"{_FAKE}::test_alpha",
        f"{_FAKE}::TestGroup::test_beta",
        f"{_FAKE}::test_async_alpha",
        f"{_FAKE}::test_skipif_allowed",
        f"{_TOP}::test_top",
    ],
)
def test_a_good_pytest_citation_is_accepted(fake_root: Path, citation: str) -> None:
    """Positive partner for rule 6: module functions, class methods, async tests,
    skipif-marked tests and files directly under tests/ all count.

    Red when: the checker rejects a real, unskipped test in one of these shapes.
    """
    assert _check(_doc(_with_cell(0, 3, f"`{citation}`")), fake_root) == []


# Rule 7 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("citation", "rule"),
    [
        (f"{_SPECS_DIR}/missing.spec.ts", "e2e-missing"),
        (_SUPPORT, "e2e-not-spec"),
        (f"{_SPECS_DIR}/../../other/flow.spec.ts", "e2e-outside"),
        (f"./{_SPEC}", "e2e-malformed"),
    ],
)
def test_a_bad_e2e_citation_is_reported(fake_root: Path, citation: str, rule: str) -> None:
    """Red when: the check behind *rule* is removed, or a spec path with a
    prefix such as "./" stops being read as a citation."""
    document = _doc(_with_cell(1, 3, f'`{citation}` "signs in"'))
    assert _check(document, fake_root) == [(rule, "SC-02")]


def test_a_code_span_that_only_mentions_tests_is_not_a_citation(fake_root: Path) -> None:
    """A command naming the tests/ folder, with no "::", is ordinary text
    (docs/41 has one, in SC-92).

    Red when: any code span containing "tests/" is read as a citation.
    """
    assert _check(_doc(_with_cell(2, 3, '`grep -rn "USER quorum" tests/`')), fake_root) == []


# What renders --------------------------------------------------------------

_SECOND_TABLE = "\n".join([*_HEADER, _line(_GOOD_ROWS[1])])


@pytest.mark.parametrize(
    "unrendered",
    [
        _doc([_GOOD_ROWS[0], _GOOD_ROWS[2]]) + "\n<!--\n" + _SECOND_TABLE + "\n-->\n",
        _doc([_GOOD_ROWS[0], _GOOD_ROWS[2]]) + "\n```\n" + _SECOND_TABLE + "\n```\n",
        _doc([_GOOD_ROWS[0], _GOOD_ROWS[2]]) + "\n~~~\n" + _SECOND_TABLE + "\n~~~\n",
        _doc([_GOOD_ROWS[0], _GOOD_ROWS[2]]) + "\n<script>\n" + _SECOND_TABLE + "\n</script>\n",
        _doc([_GOOD_ROWS[0], _GOOD_ROWS[2]])
        + "\n"
        + "\n".join("    " + line for line in _SECOND_TABLE.splitlines())
        + "\n",
        _doc([_line(_GOOD_ROWS[0]) + chr(0x2028) + _line(_GOOD_ROWS[1]), _GOOD_ROWS[2]]),
        _doc([_line(_GOOD_ROWS[0]) + "\f" + _line(_GOOD_ROWS[1]), _GOOD_ROWS[2]]),
    ],
    ids=["comment", "``` fence", "~~~ fence", "script", "indented code", "U+2028", "form feed"],
)
def test_a_measure_row_that_does_not_render_is_not_read(fake_root: Path, unrendered: str) -> None:
    """SC-02 sits in an HTML comment, a fence, a script block or indented code,
    or is glued to SC-01's line by a character Markdown does not treat as a line
    break, so it does not render as a row and is missing.

    Red when: the document is read line by line instead of as rendered, or raw
    HTML (comments, script blocks) is no longer recognised.
    """
    assert _check(unrendered, fake_root) == [("id-missing", "SC-02")]


@pytest.mark.parametrize(
    "rendered",
    [
        _doc([_GOOD_ROWS[0], " | ".join(_GOOD_ROWS[1]), _GOOD_ROWS[2]]),
        "\n".join("> " + line for line in _doc(_GOOD_ROWS).splitlines()) + "\n",
        _doc(_GOOD_ROWS, header=(_HEADER[0].strip("| "), _HEADER[1].strip("|"))),
        _doc(_GOOD_ROWS, header=("   " + _HEADER[0], _HEADER[1])),
        _doc(_with_cell(0, 1, "Reads `<!--` and `-->` safely")),
        "```\n| SC-NN | an example row |\n```\n\n" + _doc(_GOOD_ROWS),
        "<!-->\n\n" + _doc(_GOOD_ROWS),
    ],
    ids=[
        "row without outer pipes",
        "in a blockquote",
        "header without outer pipes",
        "header indented",
        "comment markers in code spans",
        "fenced example row",
        "empty comment",
    ],
)
def test_a_measure_table_that_renders_is_read(fake_root: Path, rendered: str) -> None:
    """Positive partner for the renderer: each of these renders all three rows,
    including SC-01, whose citation would otherwise be missing (no-proof).

    Red when: a row without outer pipes, a table in a blockquote, a header
    without outer pipes or indented three spaces, comment markers inside code
    spans, a fenced example row, or an empty comment changes what is read.
    """
    assert _check(rendered, fake_root) == []


# Line breaks and struck-out text --------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("TESTED<br>Details", []),
        ("TESTED<br/>Details", []),
        ("TESTED<BR />Details", []),
        ("TE<br>STED", [("status-unknown", "SC-01")]),
        ("TE<BR>STED", [("status-unknown", "SC-01")]),
        ("TE<br />STED", [("status-unknown", "SC-01")]),
    ],
)
def test_a_br_in_a_cell_reads_as_a_word_break(
    fake_root: Path, status: str, expected: list[tuple[str, str]]
) -> None:
    """A ``<br>`` (any spelling, any case) shows as a line break, so the words
    on either side stay apart: "TESTED<br>Details" is TESTED, "TE<br>STED" is not.

    Red when: an HTML ``<br>`` in a cell is dropped instead of read as a space.
    """
    assert _check(_doc(_with_cell(0, 6, status)), fake_root) == expected


@pytest.mark.parametrize("source", ["TE\nSTED", "TE  \nSTED", "TE\\\nSTED"])
def test_a_line_break_token_reads_as_a_space(source: str) -> None:
    """markdown-it-py cannot put a soft or hard line break inside a table cell (a
    newline ends the row), so this drives the cell reader with a paragraph's
    inline token, which holds one.

    Red when: a softbreak or hardbreak token is dropped instead of read as a space.
    """
    inline = next(token for token in _MARKDOWN.parse(source) if token.type == "inline")
    assert [child.type for child in inline.children or []][1] in {"softbreak", "hardbreak"}
    assert _cell(inline).text == "TE STED"


@pytest.mark.parametrize(
    ("index", "column", "value", "expected"),
    [
        (2, 6, "~~CODE-ONLY~~ TESTED", [("cell-struck", "SC-03")]),
        (2, 6, "<del>CODE-ONLY</del> TESTED", [("cell-struck", "SC-03")]),
        (2, 6, "<s>CODE-ONLY</s> TESTED", [("cell-struck", "SC-03")]),
        (2, 6, "<STRIKE>CODE-ONLY</STRIKE> TESTED", [("cell-struck", "SC-03")]),
        (1, 0, "~~SC-02~~", [("cell-struck", "SC-02"), ("id-missing", "SC-02")]),
        (1, 0, "<del>SC-02</del>", [("cell-struck", "SC-02"), ("id-missing", "SC-02")]),
    ],
)
def test_struck_out_text_in_an_id_or_status_cell_is_reported(
    fake_root: Path, index: int, column: int, value: str, expected: list[tuple[str, str]]
) -> None:
    """A reader sees struck-out text as withdrawn, so "~~CODE-ONLY~~ TESTED" reads
    as TESTED with no test, and "~~SC-02~~" as no SC-02. Rather than guess, the
    check refuses an ID or Status cell holding struck-out text.

    Red when: ``~~…~~``, ``<s>``, ``<del>`` or ``<strike>`` (any case) in an ID or
    Status cell stops being reported.
    """
    assert _check(_doc(_with_cell(index, column, value)), fake_root) == expected


def test_struck_out_text_elsewhere_and_look_alike_tags_are_fine(fake_root: Path) -> None:
    """Positive partner: struck-out text in the Measure cell, and tags that only
    start with "s" (``<small>``, ``<span>``, ``<strong>``, ``<sub>``) in the ID
    and Status cells, are not struck-out ID or Status text.

    Red when: the struck-out check covers other cells, or matches any tag that
    starts with "s".
    """
    rows = _with_cell(0, 1, "~~Old name~~ Sign-in is required")
    rows[0] = (
        "<span>SC-01</span>",
        *rows[0][1:6],
        "<strong>TESTED</strong> <small>a</small><sub>1</sub>",
    )
    assert _check(_doc(rows), fake_root) == []
