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

    Python files are tokenized. ``.js``/``.ts``/``.mjs``/``.css`` get C-style
    (``//`` and ``/* */``) blanking. Anything else is treated as line-oriented
    and only ``#`` comments are removed, which covers Makefiles and YAML. A
    file that cannot be tokenized (a syntax error mid-edit) falls back to the
    same line-oriented handling rather than raising, because a guard test
    reporting "your file does not parse" is less useful than it reporting what
    it found.

    THE ``.js`` BRANCH EXISTS BECAUSE ITS ABSENCE WAS A LIVE HOLE. Until
    2026-09-04 every suffix except ``.py`` fell through to ``#``-stripping, so
    calling this on ``app.js`` returned text still containing **2883** ``//``
    comments. Three guard tests were written believing they read
    comment-stripped JavaScript; a reviewer defeated two of them by putting a
    decoy in a ``//`` comment, restoring the false UI copy the tests existed to
    forbid, and watching them pass. See
    ``tests/unit/test_code_text_strips_js_comments.py``.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        try:
            return _blank_python(text)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
    if path.suffix in _C_STYLE_SUFFIXES:
        return _blank_c_style_comments(text)
    if path.suffix in _BLOCK_ONLY_SUFFIXES:
        return _blank_block_comments(text)
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
            token.type == tokenize.STRING and depths[index] == 0 and _is_docstring(tokens, index)
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


#: Suffixes handled by the JavaScript scanner below.
#:
#: ``.css`` is DELIBERATELY ABSENT: ``//`` is not a comment in CSS, and treating
#: it as one destroyed 94% of ``vendor/swagger-ui.css`` in testing — a base64
#: data URI and any unquoted ``url(https://…)`` both contain ``//``. CSS gets
#: the ``/* */``-only handler instead. ``.ts``/``.tsx``/``.jsx`` are absent too:
#: JSX text like ``don't`` opens a false string literal and leaks the comments
#: after it, and no such file exists here to justify the complexity.
_C_STYLE_SUFFIXES = frozenset({".js", ".mjs", ".cjs"})

#: Suffixes with ``/* */`` block comments and no line comments.
_BLOCK_ONLY_SUFFIXES = frozenset({".css"})

#: Keywords after which a ``/`` begins a REGEX, not a division.
#:
#: Without these the scanner read ``return /^https?:\/\//.test(u)`` as code,
#: and the ``\/\/`` inside the unrecognised regex opened a "line comment" that
#: blanked the rest of the line. That is the very regex this module's docstring
#: cites as the reason regex handling exists — it worked after ``(`` and broke
#: after ``return``. On a minified bundle the same desync ran to end-of-file.
_REGEX_PRECEDING_KEYWORDS = frozenset(
    {
        "return",
        "typeof",
        "instanceof",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "case",
        "do",
        "else",
        "yield",
        "await",
    }
)


def _blank_block_comments(text: str) -> str:
    """Blank ``/* */`` only. For CSS, which has no line comments."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


#: A line longer than this means the file is minified. Measured: hand-written
#: ``app.js`` peaks at 510 characters over 9047 lines; ``swagger-ui-bundle.js``
#: is 814,435 characters over 3 lines.
_MINIFIED_LINE_THRESHOLD = 2000


def _blank_c_style_comments(text: str) -> str:
    """Blank ``//`` and ``/* */`` comments, preserving every line and column.

    String literals, template literals and REGEX literals are left intact.

    WHAT THIS IS NOT: a JavaScript parser. It is a scanner sized for the
    hand-written sources this repo's guard tests read. It is NOT safe on
    minified bundles — regex-vs-division cannot be resolved by lookback alone,
    and one wrong call desyncs the rest of the file. ``vendor/`` is never passed
    to it, and ``test_the_stripper_never_corrupts_a_repo_javascript_file``
    executes ``node --check`` over every non-vendor ``.js`` before and after, so
    a corrupting change fails loudly rather than silently making the guard tests
    that depend on it assert against text the browser never runs.
    """
    # REFUSE rather than corrupt. Regex-vs-division cannot be resolved by
    # lookback, and on minified code one wrong call desyncs to end-of-file: this
    # scanner blanked 46% of ``swagger-ui-bundle.js``. A caller that silently
    # got half a file back would then run NEGATIVE assertions over the wreckage
    # and see them all pass. Nothing passes a bundle to this today; if something
    # ever does, it gets an exception naming the reason, not a clean-looking lie.
    if any(len(line) > _MINIFIED_LINE_THRESHOLD for line in text.splitlines()):
        raise ValueError(
            "code_without_comments: this file looks minified (a line longer than "
            f"{_MINIFIED_LINE_THRESHOLD} chars). The scanner is not a JavaScript "
            "parser and cannot resolve regex-vs-division on minified code — it "
            "would return a corrupted result that makes negative assertions "
            "vacuous. Read the file directly, or parse it properly."
        )

    out = list(text)
    i, n = 0, len(text)
    prev = ""  # "op" -> a '/' here starts a regex; "val" -> it is division.
    word = ""

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = text[i]

        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j == -1 else j
            blank(i, j)
            i, word, prev = j, "", prev
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i, word = j, ""
            continue

        if c in "\"'`":
            quote, j = c, i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            i, prev, word = j, "val", ""
            continue

        if c == "/" and prev == "op":
            j, in_class, ok = i + 1, False, False
            while j < n:
                ch = text[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "\n":
                    break
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    ok, j = True, j + 1
                    break
                j += 1
            if ok:
                i, prev, word = j, "val", ""
                continue

        # Track the identifier under the cursor so a KEYWORD can be recognised.
        if c.isalnum() or c in "_$":
            word += c
            prev = "op" if word in _REGEX_PRECEDING_KEYWORDS else "val"
        elif not c.isspace():
            word = ""
            prev = "op" if c in "([{,;=:?!&|+-*%<>~^" else "val"
        else:
            word = ""
        i += 1
    return "".join(out)
