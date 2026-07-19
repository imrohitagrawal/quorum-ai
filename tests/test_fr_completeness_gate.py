"""Tests for the requirement traceability-completeness gate (ledger EN-2 / FS-3).

`scripts/validate_fr_completeness.py` lives outside `src/`, so `--cov=src`
never sees it: this file is the only thing that tests the gate itself. It
exercises the gate's own logic in both directions against synthetic doc trees
(a requirement missing from an evidence doc must FAIL; a complete tree must
PASS), plus the non-triviality rules the gate claims to enforce — a row that is
present but malformed or placeholder-empty is not traceability evidence.

It also pins the Markdown-parsing edge cases that decide whether the gate is
trustworthy in both directions: a row inside a fenced code block is an
illustration, not evidence (must not satisfy the gate), while a second table in
the document and a `\\|`-escaped pipe inside a cell are legal Markdown and must
not raise a false MALFORMED failure in a blocking gate.

The last test runs the gate against the repository's real `docs/` so the
committed documents stay green.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_fr_completeness.py"


def _load_gate() -> Any:
    spec = importlib.util.spec_from_file_location("validate_fr_completeness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


REQUIREMENTS = """# Functional Requirements

## FR-001 First requirement

- Tests: TEST-FR-001.

## FR-002 Second requirement

- Tests: TEST-FR-002.
"""

NON_FUNCTIONAL = """# Non-Functional Requirements

## NFR-001 First non-functional requirement

- Tests: TEST-NFR-001.
"""

REGISTRY_HEADER = """# Requirement Registry

| Req ID | Type | Title | Tests | Status |
|---|---|---|---|---|
"""

MATRIX_HEADER = """# Requirement Traceability Matrix

| Req ID | Acceptance Criteria | Tests | Code/PR |
|---|---|---|---|
"""

REGISTRY_ROWS = {
    "FR-001": "| FR-001 | Functional | First | TEST-FR-001 | Draft |\n",
    "FR-002": "| FR-002 | Functional | Second | TEST-FR-002 | Draft |\n",
    "NFR-001": "| NFR-001 | Non-functional | Latency | TEST-NFR-001 | Draft |\n",
}
MATRIX_ROWS = {
    "FR-001": "| FR-001 | AC-001 | TEST-FR-001 | `src/a.py` |\n",
    "FR-002": "| FR-002 | AC-002 | TEST-FR-002 | `src/b.py` |\n",
    "NFR-001": "| NFR-001 | AC-021 | TEST-NFR-001 | `src/c.py` |\n",
}


def write_tree(
    root: Path,
    *,
    registry_extra: str = "",
    matrix_extra: str = "",
    registry_skip: str | None = None,
    matrix_skip: str | None = None,
    registry_prefix: str = "",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "10-functional-requirements.md").write_text(REQUIREMENTS, encoding="utf-8")
    (root / "11-non-functional-requirements.md").write_text(NON_FUNCTIONAL, encoding="utf-8")
    registry = (
        registry_prefix
        + REGISTRY_HEADER
        + "".join(row for fr, row in REGISTRY_ROWS.items() if fr != registry_skip)
    )
    matrix = MATRIX_HEADER + "".join(row for fr, row in MATRIX_ROWS.items() if fr != matrix_skip)
    (root / "17-requirement-registry.md").write_text(registry + registry_extra, encoding="utf-8")
    (root / "18-requirement-traceability-matrix.md").write_text(
        matrix + matrix_extra, encoding="utf-8"
    )
    return root


def test_complete_tree_passes(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "docs")

    assert gate.check(root) == []
    assert gate.main(["--docs-root", str(root)]) == 0


def test_missing_registry_row_fails_and_names_the_requirement(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "docs", registry_skip="FR-002")

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-002" in problems[0]
    assert "MISSING" in problems[0]
    assert "17-requirement-registry.md" in problems[0]
    assert gate.main(["--docs-root", str(root)]) == 1


def test_missing_matrix_row_fails(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "docs", matrix_skip="FR-001")

    problems = gate.check(root)

    assert [p for p in problems if "FR-001" in p and "18-requirement" in p]
    assert gate.main(["--docs-root", str(root)]) == 1


def test_missing_from_both_docs_reports_one_problem_per_file(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "docs", registry_skip="FR-002", matrix_skip="FR-002")

    problems = gate.check(root)

    assert len(problems) == 2
    assert {"17-requirement-registry.md" in p for p in problems} == {True, False}


def test_row_present_but_short_is_malformed(tmp_path: Path) -> None:
    """Artifact-present is not artifact-valid: a truncated row must fail."""
    root = write_tree(
        tmp_path / "docs",
        registry_skip="FR-002",
        registry_extra="| FR-002 | Functional |\n",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "MALFORMED" in problems[0]
    assert "FR-002" in problems[0]


def test_row_present_but_placeholder_empty_cells_fails(tmp_path: Path) -> None:
    root = write_tree(
        tmp_path / "docs",
        matrix_skip="FR-001",
        matrix_extra="| FR-001 |  | TEST-FR-001 |  |\n",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "EMPTY" in problems[0]
    assert "FR-001" in problems[0]


def test_missing_document_exits_non_zero(tmp_path: Path) -> None:
    root = tmp_path / "empty-docs"
    root.mkdir()

    with pytest.raises(SystemExit) as excinfo:
        gate.check(root)

    assert excinfo.value.code == 1


def test_requirements_doc_without_fr_sections_fails(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "docs")
    (root / "10-functional-requirements.md").write_text("# No sections\n", encoding="utf-8")

    problems = gate.check(root)

    assert len(problems) == 1
    assert "10-functional-requirements.md" in problems[0]
    assert "no `## FR-0NN`" in problems[0]


def test_declared_requirements_ignores_prose_mentions() -> None:
    text = "Prose mentioning FR-014 and FR-999.\n\n## FR-014 Real section\n"

    assert gate.declared_requirements(text) == ["FR-014"]


def test_declared_requirements_finds_nfr_sections() -> None:
    text = "## NFR-011 Determinism\n\n## FR-014 History\n"

    assert gate.declared_requirements(text) == ["FR-014", "NFR-011"]


def test_missing_nfr_row_fails(tmp_path: Path) -> None:
    """The S1 escape was FR-014 *and* NFR-011/012 — the NFR half must fire too."""
    root = write_tree(tmp_path / "docs", registry_skip="NFR-001", matrix_skip="NFR-001")

    problems = gate.check(root)

    assert len(problems) == 2
    assert all("NFR-001" in p and "MISSING" in p for p in problems)
    assert gate.main(["--docs-root", str(root)]) == 1


def test_row_inside_fenced_code_block_is_not_evidence(tmp_path: Path) -> None:
    """An illustrative row in a ``` fence documents the format, it does not trace."""
    root = write_tree(
        tmp_path / "docs",
        registry_skip="FR-002",
        registry_extra="\nExample row format (illustrative only):\n\n"
        "```\n| FR-002 | x | x | x | x |\n```\n",
    )

    problems = gate.check(root)

    assert len(problems) == 1
    assert "FR-002" in problems[0]
    assert "MISSING" in problems[0]
    assert "17-requirement-registry.md" in problems[0]


def test_second_table_before_the_registry_table_is_not_malformed(tmp_path: Path) -> None:
    """A legend table ahead of the registry must not redefine the column count."""
    root = write_tree(
        tmp_path / "docs",
        registry_prefix="| Symbol | Meaning |\n|---|---|\n| x | done |\n\n",
    )

    assert gate.check(root) == []


def test_escaped_pipe_inside_a_cell_is_not_malformed(tmp_path: Path) -> None:
    """`low\\|high` is one cell in legal Markdown, not two."""
    root = write_tree(
        tmp_path / "docs",
        registry_skip="FR-001",
        registry_extra="| FR-001 | Functional | Cost band `low\\|high` | TEST-FR-001 | Draft |\n",
    )

    assert gate.check(root) == []


def test_repository_docs_are_complete() -> None:
    """The committed docs/ tree must satisfy the gate."""
    assert gate.check(REPO_ROOT / "docs") == []
