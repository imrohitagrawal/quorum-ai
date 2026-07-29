"""Guards on `tests/code_text.py` — the prose-vs-code separator.

The two defects it exists to prevent both shipped in PR #164 and were caught by
human review, not by any gate:

* a guard searched for ``parents[`` and matched the docstring EXPLAINING the
  defect it was guarding against;
* a guard searched for ``--min-requirements`` and matched a comment added in the
  same commit to explain the flag — deleting the real flag left it green.

Every case below uses a synthetic file, never this repository's own sources, so
none can pass by accident on the shape it is meant to detect.
"""

from __future__ import annotations

from pathlib import Path

from tests.code_text import code_without_comments


def _py(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_literal_only_in_a_comment_is_not_found(tmp_path: Path) -> None:
    """The Makefile defect, in miniature.

    Turns red if: comment tokens stop being blanked.
    """
    path = _py(tmp_path, "# we pass --min-requirements here for a reason\nvalue = 1\n")

    assert "--min-requirements" in path.read_text(encoding="utf-8")
    assert "--min-requirements" not in code_without_comments(path)


def test_a_literal_only_in_a_docstring_is_not_found(tmp_path: Path) -> None:
    """The repo-root defect, in miniature: the docstring quoted ``parents[2]``
    while explaining why ``parents[2]`` is wrong.

    Turns red if: docstring detection is removed.
    """
    path = _py(tmp_path, '"""Never compute the root with parents[2]."""\nvalue = 1\n')

    assert "parents[2]" in path.read_text(encoding="utf-8")
    assert "parents[2]" not in code_without_comments(path)


def test_a_literal_in_real_code_IS_found(tmp_path: Path) -> None:
    """The positive partner. Without it, a function returning "" would satisfy
    both tests above.

    Turns red if: the blanking is too aggressive and eats live code.
    """
    path = _py(tmp_path, "# the root is computed below\nROOT = thing.parents[2]\n")

    assert "parents[2]" in code_without_comments(path)


def test_a_string_that_is_NOT_a_docstring_survives(tmp_path: Path) -> None:
    """An assigned or returned string literal is code, not prose.

    This is the distinction that makes the helper usable at all: blanking every
    string would hide the flags, paths and messages that guards exist to pin.

    Turns red if: docstring detection widens to all STRING tokens.
    """
    path = _py(tmp_path, 'FLAG = "--min-requirements"\n')

    assert "--min-requirements" in code_without_comments(path)


def test_a_function_docstring_is_blanked_but_its_body_is_not(tmp_path: Path) -> None:
    """Docstrings nest — module, class and function level all count.

    Turns red if: only the module docstring is handled.
    """
    path = _py(
        tmp_path,
        'def f():\n    """Do not use parents[2] here."""\n    return call("--flag")\n',
    )
    code = code_without_comments(path)

    assert "parents[2]" not in code
    assert "--flag" in code


def test_line_numbers_are_preserved(tmp_path: Path) -> None:
    """Blanked regions become spaces, not nothing.

    A guard that reports "line 47" must mean line 47 of the real file, or the
    reader is sent to the wrong place — which is the failure mode that made
    #158 expensive in the first place.

    Turns red if: removal starts deleting lines instead of blanking them.
    """
    path = _py(tmp_path, "# one\n# two\nTARGET = 3\n")
    code = code_without_comments(path)

    assert len(code.splitlines()) == 3
    assert code.splitlines()[2] == "TARGET = 3"


def test_a_makefile_style_file_drops_hash_comments(tmp_path: Path) -> None:
    """Not every guarded file is Python. Makefiles and YAML use ``#`` too.

    Turns red if: the non-Python path stops stripping comments.
    """
    path = tmp_path / "Makefile"
    path.write_text(
        "\t@# explains --min-requirements\n\trun --min-requirements 25\n", encoding="utf-8"
    )
    code = code_without_comments(path)

    assert code.count("--min-requirements") == 1


def test_an_unparseable_python_file_still_returns_something(tmp_path: Path) -> None:
    """A guard reporting "your file does not parse" is less useful than a guard
    reporting what it found. Mid-edit syntax errors must not raise.

    Turns red if: the tokenize failure stops being caught.
    """
    path = _py(tmp_path, "def broken(:\n    # --flag\n")

    assert "--flag" not in code_without_comments(path)
