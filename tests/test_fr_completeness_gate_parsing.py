"""Markdown-parsing holes in the requirement traceability-completeness gate.

`tests/test_fr_completeness_gate.py` covers the gate's decision logic; this
file pins the two ways a document can *look* traced while carrying no live
evidence, both of which the gate originally accepted:

1. a row commented out with `<!-- ... -->` — the same class of hole the gate
   already closed for ``` fences, which HTML comments bypassed; and
2. a requirement row living in some *other* table (a legend, a summary) while
   the registry/matrix table itself has no row for it.

Both are blocking-gate false negatives: `make fr-completeness` reported OK
while docs/17 or docs/18 held nothing auditable for the requirement.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_fr_completeness_gate import gate, write_tree

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_row_commented_out_with_html_comment_is_not_evidence(tmp_path: Path) -> None:
    """`<!-- TODO: re-add once evidence exists ... -->` must not trace."""
    root = write_tree(
        tmp_path / "docs",
        matrix_skip="FR-002",
        matrix_extra="\n<!-- TODO: re-add once evidence exists\n"
        "| FR-002 | AC-002 | TEST-FR-002 | `src/b.py` |\n"
        "-->\n",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-002" in problems[0]
    assert "MISSING" in problems[0]
    assert "18-requirement-traceability-matrix.md" in problems[0]


def test_commented_row_does_not_orphan_the_rows_below_it(tmp_path: Path) -> None:
    """Hiding one row must hide exactly that row — not end the table."""
    root = write_tree(
        tmp_path / "docs",
        matrix_skip="FR-001",
        matrix_extra="",
    )
    matrix = root / "18-requirement-traceability-matrix.md"
    lines = matrix.read_text(encoding="utf-8").splitlines(True)
    head, tail = lines[:-1], lines[-1:]
    matrix.write_text(
        "".join(head)
        + "<!-- withdrawn\n| FR-001 | AC-001 | TEST-FR-001 | `src/a.py` |\n-->\n"
        + "".join(tail),
        encoding="utf-8",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-001" in problems[0] and "MISSING" in problems[0]


def test_single_line_html_comment_row_is_not_evidence(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path / "docs",
        registry_skip="FR-001",
        registry_extra="<!-- | FR-001 | Functional | First | TEST-FR-001 | Draft | -->\n",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-001" in problems[0]
    assert "MISSING" in problems[0]


def test_content_after_a_closing_comment_marker_still_counts(tmp_path: Path) -> None:
    """Comment stripping is per-span, not per-line: the live tail survives."""
    root = write_tree(
        tmp_path / "docs",
        registry_skip="NFR-001",
        registry_extra=(
            "<!-- superseded --> | NFR-001 | Non-functional | Latency | TEST-NFR-001 | Draft |\n"
        ),
    )

    assert gate.check(root) == []


def test_row_in_a_decoy_table_does_not_satisfy_the_registry(tmp_path: Path) -> None:
    """A two-column legend mentioning the requirement is not traceability data."""
    root = write_tree(
        tmp_path / "docs",
        registry_skip="FR-002",
        registry_prefix="## Legend\n\n| Req ID | Note |\n|---|---|\n| FR-002 | see below |\n\n",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-002" in problems[0]
    assert "MISSING" in problems[0]
    assert "17-requirement-registry.md" in problems[0]


def test_evidence_table_is_resolved_even_when_a_decoy_follows_it(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path / "docs",
        matrix_skip="FR-001",
        matrix_extra="\n| Req ID | Note |\n|---|---|\n| FR-001 | see above |\n",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-001" in problems[0]
    assert "MISSING" in problems[0]


def test_missing_req_id_table_is_reported_as_a_format_change(tmp_path: Path) -> None:
    """If no `| Req ID | ...` table exists at all, say so instead of 26 MISSINGs."""
    root = write_tree(tmp_path / "docs")
    (root / "18-requirement-traceability-matrix.md").write_text(
        "# Requirement Traceability Matrix\n\nNo table here yet.\n", encoding="utf-8"
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "18-requirement-traceability-matrix.md" in problems[0]
    assert "Req ID" in problems[0]


def test_repository_docs_still_resolve_to_a_real_evidence_table() -> None:
    """Guards the fix itself: the committed docs must still be seen as traced."""
    assert gate.check(REPO_ROOT / "docs") == []
