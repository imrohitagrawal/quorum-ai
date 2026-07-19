"""The *declaration* side of the gate must use the same 'live text' rule.

`tests/test_fr_completeness_gate_parsing.py` pins the evidence side: a row that
is fenced or commented out is not evidence. This file pins the mirror image,
which the gate originally got wrong — `declared_requirements()` ran over the
raw document, so a `## FR-0NN` heading inside a ``` fence (a copy-me template)
or inside `<!-- ... -->` (a withdrawn requirement) was counted as a real
declared requirement. The blocking gate then hard-failed `make validate` for
everyone, demanding registry+matrix rows for a requirement that does not
exist — i.e. it pushed authors to fabricate traceability evidence.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_fr_completeness_gate import REQUIREMENTS, gate, write_tree

FENCED_TEMPLATE = """
## Template for new requirements

```markdown
## FR-099 Example placeholder requirement

- **Statement:** copy this block when adding a requirement.
```
"""

COMMENTED_OUT = """
<!--
## FR-098 Withdrawn requirement (kept for history)

- **Statement:** withdrawn before implementation.
-->
"""


def _tree(tmp_path: Path, extra: str) -> Path:
    root = write_tree(tmp_path / "docs")
    (root / "10-functional-requirements.md").write_text(REQUIREMENTS + extra, encoding="utf-8")
    return root


def test_fenced_requirement_heading_is_not_declared(tmp_path: Path) -> None:
    """A `## FR-0NN` inside a ``` fence is a template, not a requirement."""
    text = REQUIREMENTS + FENCED_TEMPLATE

    assert gate.declared_requirements(text) == ["FR-001", "FR-002"]


def test_commented_out_requirement_heading_is_not_declared(tmp_path: Path) -> None:
    """A `## FR-0NN` inside `<!-- ... -->` has been withdrawn."""
    text = REQUIREMENTS + COMMENTED_OUT

    assert gate.declared_requirements(text) == ["FR-001", "FR-002"]


def test_fenced_template_does_not_fail_the_blocking_gate(tmp_path: Path) -> None:
    root = _tree(tmp_path, FENCED_TEMPLATE)

    assert gate.check(root) == []


def test_commented_out_requirement_does_not_fail_the_blocking_gate(tmp_path: Path) -> None:
    root = _tree(tmp_path, COMMENTED_OUT)

    assert gate.check(root) == []


def test_live_heading_after_a_fence_is_still_declared(tmp_path: Path) -> None:
    """Hiding the template must not hide the real requirements that follow."""
    text = REQUIREMENTS + FENCED_TEMPLATE + "\n## FR-003 Third requirement\n"

    assert gate.declared_requirements(text) == ["FR-001", "FR-002", "FR-003"]
