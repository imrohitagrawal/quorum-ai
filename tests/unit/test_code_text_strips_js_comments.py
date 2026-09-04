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

import re
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


def test_a_regex_after_a_KEYWORD_is_not_mistaken_for_a_comment(tmp_path: Path) -> None:
    """The defect that shipped, and the case the repo-wide sweep cannot see.

    A ``/`` after ``(`` was already handled; a ``/`` after ``return`` was not.
    So ``return /^https?:\\/\\//.test(u)`` — the very regex this module's
    docstring cites — had its ``\\/\\/`` read as a line comment, blanking the
    rest of the line. On a minified bundle the same desync ran to end-of-file
    and destroyed 763,871 characters.

    This test exists SEPARATELY from the repo-wide ``node --check`` sweep
    because that sweep passed with the defect present: no file this repo owns
    happens to write a regex after a keyword, so the sweep was clean over a
    population that could not contain the bug. A negative sweep needs a
    positive case, and this is it.

    RED if ``_REGEX_PRECEDING_KEYWORDS`` is emptied or the lookup is dropped."""
    for kw in ("return", "typeof", "case", "throw", "yield", "in", "of", "do", "else"):
        body = f"function f(u){{ {kw} /^https?:\\/\\//.test(u); }} const KEEP = 1;\n"
        out = _strip(tmp_path, f"{kw}.js", body)
        assert "const KEEP = 1;" in out, (
            f"a regex after `{kw}` desynced the scanner and ate live code: {out!r}"
        )
        assert out == body, f"after `{kw}` the line must be untouched: {out!r}"


def test_a_regex_after_a_keyword_followed_by_a_real_comment(tmp_path: Path) -> None:
    """POSITIVE PARTNER: recognising the regex must not stop the REAL comment
    after it being blanked. RED if the regex scan swallows the rest of the
    line, which is the opposite over-correction."""
    body = "function f(u){ return /a\\/b/.test(u); } // decoy here\n"
    out = _strip(tmp_path, "kwc.js", body)
    assert "return /a\\/b/.test(u); }" in out, "live code was eaten"
    assert "decoy" not in out, "the real comment after the regex survived"


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
    # EXACT, not a bound with slack. A ``<= 4`` bound was here first and had
    # room for two silently-leaked line comments. The two survivors are named
    # so a change to either is a deliberate edit, not absorbed headroom.
    survivors = [stripped[m.start() - 50 : m.start() + 12] for m in re.finditer("//", stripped)]
    assert len(survivors) == 2, (
        f"expected exactly 2 '//' survivors (both inside literals); got "
        f"{len(survivors)}: {survivors}"
    )
    assert any("RESULT_SVG_NS" in s for s in survivors), "the XML-namespace URL string"
    assert any("https?" in s for s in survivors), "the scheme-stripping regex"

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


def test_the_stripper_never_corrupts_a_repo_javascript_file() -> None:
    """THE TRIPWIRE. Runs the stripper over every non-vendor ``.js`` in the repo
    and asserts ``node --check`` still parses the result.

    This one test would have caught both corruptions found in review: a regex
    after ``return`` desynced the scanner and blanked 763,871 characters of
    ``vendor/swagger-ui-bundle.js``, and ``//`` inside a CSS data URI blanked
    94% of ``vendor/swagger-ui.css``. Neither was caught by any assertion about
    ``app.js``, because both files are ones nothing happened to pass to it.

    ``vendor/`` is EXCLUDED and stays excluded: those are minified bundles where
    regex-vs-division cannot be resolved by lookback, the scanner is documented
    as unsafe on them, and nothing passes them to it. The exclusion is written
    here rather than left implicit so that adding a vendor call site is a
    deliberate act that has to argue with this comment.

    RED if a future change to the scanner corrupts any source this repo owns."""
    node = __import__("shutil").which("node")
    if not node:
        pytest.skip("node not available to parse the blanked output")

    repo = Path(__file__).resolve().parents[2]
    targets = [
        f
        for f in repo.rglob("*.js")
        if "node_modules" not in f.parts
        and "vendor" not in f.parts
        and ".venv" not in f.parts
        and "build" not in f.parts
    ]
    # FLOOR (rule 7): a clean sweep over nothing proves nothing.
    assert len(targets) >= 1, "no repo JavaScript found to check — the sweep is vacuous"

    tmp = Path(__import__("tempfile").mkdtemp())
    corrupted: list[str] = []
    checked = 0
    for f in targets:
        before = subprocess.run([node, "--check", str(f)], capture_output=True)
        if before.returncode != 0:
            continue  # not parseable to begin with; nothing to preserve
        checked += 1
        out = tmp / "s.js"
        out.write_text(code_without_comments(f), encoding="utf-8")
        after = subprocess.run([node, "--check", str(out)], capture_output=True, text=True)
        if after.returncode != 0:
            corrupted.append(f"{f.relative_to(repo)}: {after.stderr.splitlines()[:2]}")

    assert checked >= 1, "every candidate was unparseable — the sweep measured nothing"
    assert not corrupted, (
        "the stripper turned valid JavaScript into invalid JavaScript, so any "
        "guard test reading these files is asserting against text the browser "
        "never runs:\n" + "\n".join(corrupted)
    )


def test_a_minified_file_is_REFUSED_not_silently_corrupted(tmp_path: Path) -> None:
    """RED if the minified guard is removed.

    The scanner blanked 46% of ``vendor/swagger-ui-bundle.js`` and turned valid
    JavaScript into invalid JavaScript. A caller that got that back would run
    its negative assertions over the wreckage and watch them all pass. Refusing
    is the only honest failure mode for a scanner that cannot parse.
    """
    minified = tmp_path / "bundle.js"
    minified.write_text("var a=1;" + ("x".join(["/*c*/"] * 400)) + "\n", encoding="utf-8")
    assert len(minified.read_text().splitlines()[0]) > 2000, "precondition: one long line"

    with pytest.raises(ValueError, match="minified"):
        code_without_comments(minified)


def test_a_normal_file_is_NOT_refused(tmp_path: Path) -> None:
    """POSITIVE PARTNER: the guard must not fire on ordinary source. RED if the
    threshold is lowered far enough to reject hand-written files — ``app.js``
    peaks at 510 characters."""
    ok = tmp_path / "fine.js"
    ok.write_text("const a = 1; // c\n" + ("const b = 2;\n" * 50), encoding="utf-8")
    out = code_without_comments(ok)
    assert "const a = 1;" in out and "// c" not in out
    assert code_without_comments(APP_JS), "the real app.js must still be accepted"
