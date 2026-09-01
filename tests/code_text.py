"""Read a file's CODE, with comments and docstrings removed.

WHY THIS EXISTS — three tests in one pull request, all the same defect

A guard test asserts something about a file: "the Makefile still passes this
flag", "this module no longer computes its root that way". The obvious way to
write that is ``assert "<literal>" in path.read_text()``.

It is wrong, and it fails in a way that looks exactly like passing. **The literal
matches the prose that EXPLAINS the thing, not the thing.** Measured on PR #164:

* ``assert "parents[" not in source`` matched the module's own docstring, which
  quoted ``parents[2]`` while explaining the defect being guarded against.
* ``assert "--min-requirements" in recipe`` matched a comment added in the SAME
  commit to explain why the flag was there. Deleting the real flag left the test
  green.

Both were caught by human review, not by any gate. This helper is the fix for
the next one: strip what the reader wrote ABOUT the code, then search what the
machine will actually run.

    assert "--min-requirements" in code_without_comments(makefile)

WHAT IT DOES NOT DO
    It is not a lint and does not stop anyone using ``read_text()`` directly.
    A scan of this suite found **62 of 63** substring assertions over file
    contents, most of them against ``app.js`` and ``app.css`` where there is no
    Python parse to fall back on and a substring is the only option. A rule
    banning them would flag almost everything and be switched off within a week,
    so none was written. This is an opt-in tool for the cases where prose and
    code share a file.

    It also cannot help with Markdown, where the prose IS the subject.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path


def code_without_comments(path: Path) -> str:
    """*path*'s text with comments and docstrings blanked out.

    Line and column positions are preserved — removed regions become spaces
    rather than disappearing — so a failure message can still quote a line
    number that matches the real file.

    Python files are tokenized. Anything else is treated as line-oriented and
    only ``#`` comments are removed, which covers Makefiles and YAML. A file
    that cannot be tokenized (a syntax error mid-edit) falls back to the same
    line-oriented handling rather than raising, because a guard test reporting
    "your file does not parse" is less useful than it reporting what it found.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        try:
            return _blank_python(text)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
    return _blank_hash_comments(text)


def _blank_hash_comments(text: str) -> str:
    """Drop everything from an unquoted ``#`` to end of line."""
    out = []
    for line in text.splitlines(keepends=True):
        stripped = line.split("#", 1)[0] if "#" in line else line
        # keep the newline so line numbers survive
        if stripped is not line and not stripped.endswith("\n") and line.endswith("\n"):
            stripped += "\n"
        out.append(stripped)
    return "".join(out)


def _blank_python(text: str) -> str:
    """Blank COMMENT tokens and docstrings, preserving every other character."""
    lines = text.splitlines(keepends=True)
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    depths = _bracket_depths(tokens)

    blank: list[tuple[int, int, int, int]] = []
    for index, token in enumerate(tokens):
        is_comment = token.type == tokenize.COMMENT
        is_docstring = (
            token.type == tokenize.STRING
            and depths[index] == 0
            and _is_docstring(tokens, index)
        )
        if is_comment or is_docstring:
            blank.append((*token.start, *token.end))

    for start_row, start_col, end_row, end_col in blank:
        for row in range(start_row, end_row + 1):
            line = lines[row - 1]
            begin = start_col if row == start_row else 0
            finish = end_col if row == end_row else len(line.rstrip("\n"))
            keep_newline = "\n" if line.endswith("\n") else ""
            body = line.rstrip("\n")
            lines[row - 1] = body[:begin] + " " * (finish - begin) + body[finish:] + keep_newline
    return "".join(lines)


def _bracket_depths(tokens: list[tokenize.TokenInfo]) -> list[int]:
    """The ``(``/``[``/``{`` nesting depth EACH token sits inside, by index.

    Load-bearing for :func:`_is_docstring` (#418, found reusing this helper
    from ``scripts/check_open_work.py``): a dict/list/set/tuple literal
    written one entry per line puts a STRING as the first token on its
    logical line, on every line after the first -- ``tokenize`` emits ``NL``
    for the line break inside brackets, the exact same token
    :func:`_is_docstring` treats as "a docstring follows". Without a depth
    check, ``{"stream": True}`` written multi-line blanked the key
    ``"stream"`` as if it were a module docstring. A real docstring can only
    ever be a top-level expression statement, which is by definition at
    depth 0 -- inside any bracket, a string is a collection element, a call
    argument, or a subscript, never a docstring.
    """
    depth = 0
    depths: list[int] = []
    for token in tokens:
        depths.append(depth)
        if token.type == tokenize.OP:
            if token.string in "([{":
                depth += 1
            elif token.string in ")]}":
                depth -= 1
    return depths


def _is_docstring(tokens: list[tokenize.TokenInfo], index: int) -> bool:
    """A STRING that stands alone as a statement — module, class or function level.

    Detected by what precedes it rather than by parsing: a docstring is the first
    thing on its logical line. A string being assigned, returned or passed as an
    argument has a NAME, OP or KEYWORD before it on the same logical line.

    Callers MUST also check the token's bracket depth is 0 (see
    :func:`_bracket_depths`) — this function alone cannot tell a bracketed
    collection's line-leading string from a real docstring, because both are
    "the first token after an NL" from ``tokenize``'s point of view.
    """
    for previous in reversed(tokens[:index]):
        if previous.type in {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}:
            return True
        if previous.type == tokenize.COMMENT:
            continue
        return False
    return True  # first token in the file
