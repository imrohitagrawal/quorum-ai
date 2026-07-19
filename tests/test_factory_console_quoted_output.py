"""Truthfulness gate for *quoted command output* in `docs/00-factory-console.md`.

The console's "Validation status (measured)" block pastes a fenced, verbatim-looking
tail of `make validate`. A pasted transcript is the strongest evidence claim a doc can
make, and it is the one thing `tests/test_factory_console_claims.py` never checked: the
console shipped `OK: FR traceability completeness — 14 FRs present in docs/17 and
docs/18.` while `scripts/validate_fr_completeness.py` can only ever print
`OK: requirement traceability completeness — N requirements (FR + NFR) present ...`.

Once a "captured" block is allowed to contain a line no tool can emit, every other
captured block in the repo loses its evidence value. So: every `OK: ...` line quoted
inside a console code fence must be *producible* by some script under `scripts/` —
matched against the actual string literals those scripts print, with f-string
placeholders treated as wildcards.

Neither the console nor `scripts/` is under `src/`, so `--cov=src` never sees them;
this file is the only mechanical check.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

CONSOLE = REPO_ROOT / "docs" / "00-factory-console.md"
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Fences may be indented (they often sit inside a list item), so allow leading space.
FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.MULTILINE | re.DOTALL)

# A quoted success line from a validation script, e.g. "OK: docs validation passed".
OK_LINE_RE = re.compile(r"^\s*(OK:.*)$", re.MULTILINE)


def _template_to_regex(node: ast.expr) -> str | None:
    """Render a str literal / f-string as a regex, placeholders becoming wildcards."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return re.escape(node.value)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(re.escape(value.value))
            else:
                parts.append(r".*")
        return "".join(parts)
    return None


@pytest.fixture(scope="module")
def emittable_ok_patterns() -> list[tuple[str, str]]:
    """(script name, regex) for every `OK: ...` string literal any script can print."""
    patterns: list[tuple[str, str]] = []
    for script in sorted(SCRIPTS_DIR.rglob("*.py")):
        try:
            tree = ast.parse(script.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive; scripts are importable
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Constant, ast.JoinedStr)):
                continue
            pattern = _template_to_regex(node)
            if pattern is None:
                continue
            # Only success lines are quoted as evidence; skip everything else.
            if not pattern.startswith(re.escape("OK:")):
                continue
            patterns.append((script.name, pattern))
    return patterns


@pytest.fixture(scope="module")
def quoted_ok_lines() -> list[str]:
    text = CONSOLE.read_text(encoding="utf-8")
    return [line.strip() for fence in FENCE_RE.findall(text) for line in OK_LINE_RE.findall(fence)]


def test_scripts_expose_ok_lines_to_match_against(
    emittable_ok_patterns: list[tuple[str, str]],
) -> None:
    """Guard the gate itself: an empty pattern set would make the check vacuous."""
    assert emittable_ok_patterns, (
        "No `OK: ...` output literals found under scripts/; the quoted-output gate "
        "would pass vacuously. Fix the extraction before trusting it."
    )


def test_quoted_ok_lines_are_producible_by_a_script(
    quoted_ok_lines: list[str], emittable_ok_patterns: list[tuple[str, str]]
) -> None:
    """A fenced `OK: ...` line in the console must be output some script can emit."""
    for line in quoted_ok_lines:
        assert any(re.fullmatch(pattern, line) for _, pattern in emittable_ok_patterns), (
            f"docs/00-factory-console.md quotes {line!r} as captured output, but no "
            "script under scripts/ can print that line. Re-run the command and paste "
            "the real tail — fabricated transcripts destroy the evidence value of "
            "every other captured block."
        )
