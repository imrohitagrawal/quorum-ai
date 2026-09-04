"""The shared code-reading helper must strip JavaScript comments.

WHY THIS FILE EXISTS — a hole that made three guard tests decorative.

Until 2026-09-04 ``code_without_comments`` tokenized ``.py`` and treated every
other suffix as ``#``-commented. Called on ``app.js`` it returned text still
containing **2883** ``//`` comments. Three guards were written believing they
read comment-stripped JavaScript. A reviewer defeated two of them by putting a
decoy in a ``//`` comment and shipping the verbatim false UI copy those guards
existed to forbid — 4 passed, and the product told users the judge had
"verified citation support".

The helper's own docstring already warned that "the literal matches the prose
that EXPLAINS the thing, not the thing". It just could not deliver that for JS.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from tests.code_text import code_without_comments

APP_JS = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static" / "app.js"


def _strip(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return code_without_comments(p)


def test_line_comments_are_blanked(tmp_path: Path) -> None:
    """RED without the ``.js`` branch: the decoy survives and any guard
    asserting on it is satisfied by a comment."""
    out = _strip(tmp_path, "a.js", 'const X = "real";\n// const X = "decoy";\n')
    assert "real" in out, "POSITIVE PARTNER: live code must survive"
    assert "decoy" not in out, "a // comment reached the caller"


def test_block_comments_are_blanked(tmp_path: Path) -> None:
    """RED without the ``.js`` branch."""
    out = _strip(tmp_path, "a.js", 'const X = 1;\n/* const Y = "decoy"; */\nconst Z = 2;\n')
    assert "const X" in out and "const Z" in out, "POSITIVE PARTNER"
    assert "decoy" not in out


def test_a_comment_inside_a_string_is_NOT_blanked(tmp_path: Path) -> None:
    """The inverse error. RED if the stripper eats string contents — which
    would make a guard assert against text the browser never runs."""
    out = _strip(tmp_path, "a.js", 'const u = "https://example.com/x"; // trailing\n')
    assert "https://example.com/x" in out, "a URL inside a string was corrupted"
    assert "trailing" not in out


def test_a_regex_literal_is_not_mistaken_for_a_comment(tmp_path: Path) -> None:
    """``app.js`` really contains ``/^https?:\\/\\//``. A stripper that treated
    that as a comment would silently delete live code. RED if regex handling
    is dropped."""
    body = 'const host = String(u).replace(/^https?:\\/\\//, "").split("/")[0]; // c\n'
    out = _strip(tmp_path, "a.js", body)
    assert "replace(/^https?:" in out, "the regex literal was eaten"
    assert "split(" in out, "code after the regex was eaten"
    assert "// c" not in out


def test_line_and_column_positions_are_preserved(tmp_path: Path) -> None:
    """A failure message must be able to quote a line number that matches the
    real file. RED if blanking deletes characters instead of spacing them."""
    body = "const A = 1;\n// comment\nconst B = 2;\n"
    out = _strip(tmp_path, "a.js", body)
    assert len(out) == len(body)
    assert out.count("\n") == body.count("\n")
    assert out.splitlines()[2] == "const B = 2;"


def test_the_real_app_js_is_stripped_and_still_parses() -> None:
    """The end-to-end guarantee, on the actual served file.

    Two halves, both load-bearing: the comments really go (otherwise the guards
    that depend on this are decorative), and the result is still valid
    JavaScript (otherwise the stripper is corrupting live code and the guards
    assert against something the browser never runs).

    RED if the ``.js`` branch is removed: ``//`` count jumps to ~2883.
    """
    stripped = code_without_comments(APP_JS)
    raw = APP_JS.read_text(encoding="utf-8")

    assert len(stripped) == len(raw), "offsets must be preserved"
    # The only survivors are inside string/regex literals (an http:// URL and
    # a scheme-stripping regex), which is correct behaviour, not leakage.
    assert stripped.count("//") <= 4, (
        f"{stripped.count('//')} '//' sequences survived; comments are leaking"
    )
    assert stripped.count("/*") == 0

    # POSITIVE PARTNER: real code and real UI copy must still be there.
    assert "TRUST_DISCLOSURE_VERIFIED" in stripped
    assert "function isStubSource" in stripped

    if not (node := __import__("shutil").which("node")):
        pytest.skip("node not available to verify the blanked output still parses")
    out = Path(__import__("tempfile").mkdtemp()) / "stripped.js"
    out.write_text(stripped, encoding="utf-8")
    proc = subprocess.run([node, "--check", str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"blanking corrupted live JavaScript — node --check failed:\n{proc.stderr}"
    )
