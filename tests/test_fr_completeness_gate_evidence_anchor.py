"""The evidence table must be anchored, not inferred from table width.

The gate originally resolved the `| Req ID | ... |` evidence table by picking
the WIDEST such table anywhere in the document. That is a blocking-gate false
negative waiting to happen: a wider `| Req ID |` table elsewhere in docs/17 or
docs/18 — a changelog, a summary, or simply the day someone adds a column to a
secondary table — silently becomes "the evidence", so the real registry/matrix
table can hold ZERO requirement rows while `make fr-completeness` still exits 0.

The evidence table is now anchored structurally: it is the first
`| Req ID | ... |` table inside the document's `# Title` section (the span from
the H1 to the next heading), which is where the registry and the matrix live.
A table under a later `##` heading is commentary, whatever its width.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_fr_completeness_gate import gate, write_tree

DECOY_COLUMNS = 12
DECOY_HEADER = "| Req ID | " + " | ".join(f"C{i}" for i in range(DECOY_COLUMNS - 1)) + " |\n"
DECOY_SEPARATOR = "|" + "---|" * DECOY_COLUMNS + "\n"


def _decoy_table(requirements: tuple[str, ...]) -> str:
    rows = "".join("| " + req + " |" + " x |" * (DECOY_COLUMNS - 1) + "\n" for req in requirements)
    return "\n## Changelog\n\n" + DECOY_HEADER + DECOY_SEPARATOR + rows


def _empty_registry(root: Path) -> None:
    """Strip every requirement row from the real registry table."""
    registry = root / "17-requirement-registry.md"
    kept = [
        line
        for line in registry.read_text(encoding="utf-8").splitlines(True)
        if not gate.REQ_ID.match(gate._cells(line)[0] if line.strip().startswith("|") else "")
    ]
    registry.write_text("".join(kept), encoding="utf-8")


def test_wider_decoy_table_cannot_stand_in_for_an_empty_registry(tmp_path: Path) -> None:
    """The exact escape: real table emptied, wide decoy appended — must FAIL."""
    root = write_tree(tmp_path / "docs")
    _empty_registry(root)
    registry = root / "17-requirement-registry.md"
    registry.write_text(
        registry.read_text(encoding="utf-8") + _decoy_table(("FR-001", "FR-002", "NFR-001")),
        encoding="utf-8",
    )

    problems = gate.check(root)

    assert len(problems) == 3
    assert all("MISSING" in p and "17-requirement-registry.md" in p for p in problems)
    assert gate.main(["--docs-root", str(root)]) == 1


def test_wider_decoy_does_not_hijack_an_otherwise_complete_registry(tmp_path: Path) -> None:
    """Non-adversarial half: a 12th column elsewhere must not re-target the gate."""
    root = write_tree(tmp_path / "docs", registry_skip="FR-002")
    registry = root / "17-requirement-registry.md"
    registry.write_text(
        registry.read_text(encoding="utf-8") + _decoy_table(("FR-002",)),
        encoding="utf-8",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-002" in problems[0] and "MISSING" in problems[0]


def test_evidence_table_is_the_one_in_the_title_section(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "docs")
    text = (root / "17-requirement-registry.md").read_text(encoding="utf-8")

    table = gate.evidence_table(text + _decoy_table(("FR-001",)))

    assert table is not None
    assert len(table.header) == 5
    assert sorted(key for key in table.rows if gate.REQ_ID.match(key)) == [
        "FR-001",
        "FR-002",
        "NFR-001",
    ]


def test_req_id_table_only_outside_the_title_section_is_a_format_change(tmp_path: Path) -> None:
    """Loud failure beats silently tracing against commentary."""
    root = write_tree(tmp_path / "docs")
    (root / "18-requirement-traceability-matrix.md").write_text(
        "# Requirement Traceability Matrix\n\n" + _decoy_table(("FR-001", "FR-002", "NFR-001")),
        encoding="utf-8",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "Req ID" in problems[0]
    assert "18-requirement-traceability-matrix.md" in problems[0]


def test_repository_docs_still_resolve_to_their_title_section_table() -> None:
    """Guards the fix: the committed docs must still be seen as traced."""
    root = Path(__file__).resolve().parents[1] / "docs"

    for doc, columns in (
        ("17-requirement-registry.md", 11),
        ("18-requirement-traceability-matrix.md", 7),
    ):
        table = gate.evidence_table((root / doc).read_text(encoding="utf-8"))
        assert table is not None and len(table.header) == columns
    assert gate.check(root) == []
