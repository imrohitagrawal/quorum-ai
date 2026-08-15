"""#209 — no test may read a process-global event recorder unscoped.

``provider_event_recorder`` and its five siblings are process-global ring
buffers. A background query-run worker thread from an EARLIER test can still
be in flight and append to one of them AFTER the next test's ``clear_state``
fixture has emptied it, so a read of ``list_events()`` that a count, an index
or an ``all(...)`` depends on is coupled to every other writer in the process.
#104 measured it: 1 of 14 sequential runs of one test saw
``len(provider_events) == 6`` where the test expected 4.

The fix was applied site by site. This guard is what keeps it applied: it
parses every file under ``tests/`` and fails on a NEW ``list_events()`` call
that neither goes through ``tests.helpers.scoped_events`` nor carries a
written ``# unscoped-ok: <reason>`` waiver.

The waiver is deliberate rather than a hard ban. One read in this suite MUST
span every writer — ``tests/security/test_release_security_redaction.py``
proves no provider secret reaches ANY recorded event, and narrowing it to one
account would delete exactly the coverage it exists for. See
``docs/adr/0047-annotated-waiver-for-unscoped-event-recorder-reads.md``.

WHAT THIS CANNOT SEE — read before citing it as proof
    - It matches on the CALL ``<x>.list_events()``. An aliased read
      (``read = recorder.list_events`` then ``read()``) or a
      ``getattr(recorder, "list_events")()`` is invisible to it. Neither shape
      exists in this suite today; both would be caught by review, not by this.
    - The waiver comment is matched against the physical lines of the enclosing
      statement, so a string LITERAL containing ``# unscoped-ok:`` on a line
      inside that same statement would satisfy it. That is the one way to fool
      the guard without writing a real waiver, and it is not accidental-looking
      code.
    - It says nothing about whether a scoped read is scoped to the RIGHT id.
      ``scoped_events(recorder, account_id=someone_elses_id)`` passes here.

What turns each test here red is stated on the test itself.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: A waiver must name a reason, and a reason must be long enough to be a
#: sentence rather than a shrug. Pinned with literals on both sides in the
#: assertions below so raising this constant cannot silently pass a
#: one-word waiver (AGENTS.md rule 7a).
_ANNOTATION = re.compile(r"#\s*unscoped-ok:\s*(?P<reason>\S.*?)\s*$")

#: Every event recorder exposes exactly this read method.
_READ_METHOD = "list_events"

#: The shared filter that makes a read safe.
_SCOPING_HELPER = "scoped_events"


@dataclass(frozen=True)
class RecorderRead:
    """One ``x.list_events()`` call found in a test file."""

    path: str
    lineno: int
    waiver_reason: str | None
    statement: str

    @property
    def is_waived(self) -> bool:
        return self.waiver_reason is not None


def _statement_span(tree: ast.AST) -> dict[int, tuple[int, int]]:
    """Map every node's ``id()`` to the line span of its enclosing statement.

    The waiver comment is searched over the WHOLE statement that performs the
    read, not just the call's own line: a read inside a multi-line list
    literal or comprehension would otherwise have nowhere legible to put it.
    """
    spans: dict[int, tuple[int, int]] = {}

    def walk(node: ast.AST, current: tuple[int, int] | None) -> None:
        if isinstance(node, ast.stmt) and node.end_lineno is not None:
            current = (node.lineno, node.end_lineno)
        if current is not None:
            spans[id(node)] = current
        for child in ast.iter_child_nodes(node):
            walk(child, current)

    walk(tree, None)
    return spans


def find_recorder_reads(source: str, path: str) -> list[RecorderRead]:
    """Every ``<something>.list_events()`` call in ``source``.

    Comments are invisible to ``ast``, so the waiver is matched against the
    physical lines of the enclosing statement. That is the point of parsing
    rather than grepping: a ``list_events()`` mentioned in a docstring or a
    comment is not a read and must not be flagged.
    """
    tree = ast.parse(source)
    spans = _statement_span(tree)
    lines = source.splitlines()
    reads: list[RecorderRead] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != _READ_METHOD:
            continue
        start, end = spans.get(id(node), (node.lineno, node.lineno))
        reason: str | None = None
        for line in lines[start - 1 : end]:
            match = _ANNOTATION.search(line)
            if match:
                reason = match.group("reason")
                break
        reads.append(
            RecorderRead(
                path=path,
                lineno=node.lineno,
                waiver_reason=reason,
                statement="\n".join(lines[start - 1 : end]).strip(),
            )
        )
    return reads


def count_scoping_helper_calls(source: str) -> int:
    """How many ``scoped_events(...)`` calls ``source`` makes."""
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == _SCOPING_HELPER
    )


def _scan_test_suite() -> tuple[list[RecorderRead], int, int]:
    """Returns (reads, scoped_events call count, files parsed)."""
    reads: list[RecorderRead] = []
    scoped_calls = 0
    files = 0
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(TESTS_ROOT.parent))
        reads.extend(find_recorder_reads(source, relative))
        scoped_calls += count_scoping_helper_calls(source)
        files += 1
    return reads, scoped_calls, files


def test_the_scanner_finds_a_planted_unscoped_read_and_clears_a_waived_one() -> None:
    """The positive partner for the whole guard.

    Everything else here is a negative check ("no unwaived read"), which is
    trivially true over nothing. This proves the scanner really recognises the
    shape it is supposed to reject, and really honours a waiver — on source it
    controls, so it cannot pass by the suite happening to be clean.

    What turns it red: make ``find_recorder_reads`` return ``[]``, or stop
    matching the ``# unscoped-ok:`` comment.
    """
    planted = (
        "def t():\n"
        "    assert len(provider_event_recorder.list_events()) == 4\n"
        "    waived = [\n"
        "        repr(debate_event_recorder.list_events()),\n"
        "        # unscoped-ok: this sweep must span every writer in the process\n"
        "    ]\n"
        '    """A docstring mentioning provider_event_recorder.list_events() only."""\n'
        "    # A comment mentioning synthesis_event_recorder.list_events() only.\n"
    )

    reads = find_recorder_reads(planted, "planted.py")

    # Two real calls; the docstring and the comment mentions are NOT calls.
    assert len(reads) == 2
    assert [read.lineno for read in reads] == [2, 4]
    assert [read.is_waived for read in reads] == [False, True]
    assert reads[1].waiver_reason == "this sweep must span every writer in the process"
    assert "provider_event_recorder" in reads[0].statement


def test_the_scanner_counts_calls_to_the_shared_scoping_helper() -> None:
    """Positive partner for the ``scoped_events`` floor below.

    What turns it red: make ``count_scoping_helper_calls`` return 0.
    """
    planted = (
        "def t():\n"
        "    a = scoped_events(provider_event_recorder, account_id=x)\n"
        "    b = scoped_events(debate_event_recorder, query_run_id=y)\n"
        "    c = not_scoped_events(provider_event_recorder)\n"
    )

    assert count_scoping_helper_calls(planted) == 2


def test_no_test_reads_a_process_global_recorder_unscoped_without_a_waiver() -> None:
    """The gate itself.

    What turns it red: add ``assert len(provider_event_recorder.list_events())
    == 4`` to any test file without routing it through ``scoped_events`` and
    without an ``# unscoped-ok: <reason>`` comment in the same statement.
    Demonstrated by planting exactly that during development.
    """
    reads, _, files = _scan_test_suite()

    # Floors: refuse to pass having measured nothing (AGENTS.md).
    assert files >= 200, f"only parsed {files} files under {TESTS_ROOT}"
    assert len(reads) >= 4, (
        f"the scanner found {len(reads)} list_events() calls under {TESTS_ROOT}; "
        "expected at least the shared helper plus the security-redaction sweep"
    )

    unwaived = [read for read in reads if not read.is_waived]
    assert unwaived == [], "unscoped process-global event-recorder reads (#209):\n" + "\n".join(
        f"  {read.path}:{read.lineno}\n    {read.statement.splitlines()[0]}" for read in unwaived
    )


def test_every_waiver_names_a_real_reason_and_the_known_one_is_the_security_sweep() -> None:
    """A waiver is a written argument, not an escape hatch.

    What turns it red: shorten any ``# unscoped-ok:`` reason to a word, or
    scope the security-redaction sweep to one account (which would delete the
    coverage that proves no secret reaches ANY event).
    """
    reads, _, _ = _scan_test_suite()
    waived = [read for read in reads if read.is_waived]

    assert len(waived) >= 2, f"expected the helper plus the security sweep, found {len(waived)}"
    for read in waived:
        reason = read.waiver_reason or ""
        assert len(reason) >= 20, (
            f"{read.path}:{read.lineno} waiver reason is too short: {reason!r}"
        )

    waived_files = {read.path for read in waived}
    assert "tests/security/test_release_security_redaction.py" in waived_files
    assert "tests/helpers.py" in waived_files


def test_the_suite_actually_routes_its_recorder_reads_through_the_shared_helper() -> None:
    """The fix is applied, not merely available.

    A guard that only forbids the bad shape passes just as well over a suite
    that stopped reading recorders at all. This pins that the scoped idiom is
    in real use.

    What turns it red: revert the #209 per-site fixes back to bare
    ``list_events()`` reads (which would also turn the gate above red).
    """
    _, scoped_calls, _ = _scan_test_suite()

    assert scoped_calls >= 20, f"only {scoped_calls} scoped_events() call sites found"
