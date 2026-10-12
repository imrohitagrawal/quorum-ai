#!/usr/bin/env python3
"""A completion word in a status document must cite its proof (ADR-0162).

A status document here may say "merged", "in production", "approved" and the
other words in :data:`WORDS` only when the same UNIT cites one of:

* a pull request ``#N`` whose squash commit ends its subject with ``(#N)`` on
  ``main`` (an issue number in a commit scope, ``feat(#105): ...``, is not one);
* a commit (7 to 40 hex characters) that is an ancestor of ``main``;
* a ``CHG-NNN`` that is a row of ``docs/19-change-control-log.md``.

UNITS ARE WHAT THE READER SEES. The file is parsed with the CommonMark parser
the project already pins (``markdown-it-py``, ADR-0029; the table rule is
switched on). A unit is one block: a paragraph, one list item's own paragraph,
one heading, or one table row (with or without leading pipes). A citation
supports only the claims in its own unit, so a bullet cannot lend the next
bullet its citation.

THE CLAIM TEXT is the unit's visible text, its line breaks read as spaces, so a
claim wrapped across two lines ("in" / "production") is still one phrase. Inline
code, fenced and indented code blocks, raw HTML (a comment included) and anything
inside double quotes are mentions, not claims. A line opening with inline code
(three backticks, a word, three backticks) is a paragraph, not a fence.

A word is not a claim when a negation sits just before it, in the same clause
("not merged", "has not been merged"): the look-back crosses spaces and a few
filler words (:data:`_FILLERS`: "yet", "been" and the like), never punctuation,
so "no. In production" and "No, merged" are claims.

THE STATUS FIELD is read on the SOURCE LINE that holds the end of the word, not
on the joined text, because a status block is often written one field per line
("Pushed: yes" / "Merged: no" / "In production: no"). The word (after any other
words: "W55 merged: no") is a negated field when ":" follows it and the field
value, which runs to the end of that source line or to the next ".", ";" or
"|", is exactly "no" or "not yet", optionally followed by closing punctuation,
emphasis markers (``**``, ``_``) and one parenthesized remark: "Merged: no.",
"Merged: **no**", "Merged: no (blocked on CI)". "Merged: no doubt." and
"Merged: no -- see below" are claims. A value wrapped onto the next source line
is read per line, so "Merged: no" with "conflicts with main." on the next line
is a negation. The line is read as the reader sees it: markup gone, mentions
blanked. A field value negates nothing on the next line: the look-back does not
cross a line break that follows a line ending in ": no" or ": not yet", so
"Merged: no" with "In production: yes" on the next line claims "in production".
A plain wrapped negation ("has not" / "been merged") still crosses it.

A line break hidden inside an image or an inline link's destination and title
still moves the claims after it to their own source line. A heading that is
exactly a closing-status label (Done, Verified myself, Cleanup, Pending, Next
action) is a label, not a claim.

THE CUT-OFF. A claim is checked when the source line holding its first character
was written after :data:`CUTOFF` (the merge of package A, #558): ``git blame``
names the commit that last wrote each line, and an uncommitted line always
counts. A scoped file that no commit after the cut-off touched, and that has no
uncommitted change, is exempt without a blame. The files touched after the
cut-off come from ONE ``git log --name-only`` plus ``git status --porcelain``,
so only those files are blamed.

The main ref is ``refs/remotes/origin/main`` when it exists, else
``refs/heads/main``: on a pull-request checkout there is no local ``main``. When
an unsupported claim's unit cites a commit that is not on that ref, the message
says so and suggests ``git fetch``: production deploys a merge before a local
clone has fetched it.

GATE CHARTER
------------
WHY THIS EXISTS: on 2026-10-11, 14 false completion claims were planted one at a
time in a copy of ``main``; 9 were accepted by every check, including a handoff
saying two items were merged and in production when neither was.

WHAT IT CANNOT SEE: words outside the list ("done", "shipped", "live"); a false
claim in a unit that also holds a true citation, since a citation anywhere in
the unit supports every word in it; lines written before the cut-off (but an
old line moved without a change is re-dated by blame to the move, and so is
checked); untracked files; a claim typed inside backticks, double quotes, raw
HTML (an HTML comment) or a code block, or in an image's alt text; and whether
the cited pull request did what the sentence says.

FALSE-POSITIVE COST: a new line that uses a listed word in its plain sense ("the
request is accepted") fails until it is quoted, reworded or cited.

WHEN TO REMOVE: when status claims are generated from git and GitHub instead of
written by hand.

Git and ``markdown-it-py``: it runs inside ``make validate``, offline, under
``uv run``, because the system Python lacks the parser.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.rules_inline import image as _image_rule
from markdown_it.rules_inline import link as _link_rule
from markdown_it.rules_inline.state_inline import StateInline
from markdown_it.token import Token

ROOT = Path(__file__).resolve().parent.parent

#: The cut-off commit of ADR-0162: the merge of package A (#558).
CUTOFF = "b66b107f3f36eeaeb943ce93776b4fd4ef72095a"

#: The completion words of ADR-0162, decision 1. Matched case-insensitively,
#: except "GA", which is matched as an upper-case word so "ga" in prose is not it.
WORDS = (
    "merged",
    "in production",
    "complete",
    "completed",
    "verified",
    "approved",
    "accepted",
    "passed",
    "released",
    "GA",
    "production-ready",
    "release-ready",
)

#: A word joined to a letter, digit, underscore or hyphen on either side is part
#: of a longer word ("UNVERIFIED", "auto-merged", "feedback_writes_verified").
_EDGE_BEFORE = r"(?<![\w-])"
_EDGE_AFTER = r"(?![\w-])"


def _pattern(word: str) -> re.Pattern[str]:
    if word == "GA":
        return re.compile(_EDGE_BEFORE + "GA" + _EDGE_AFTER)
    body = r"\s+".join(re.escape(part) for part in word.split(" "))
    return re.compile(_EDGE_BEFORE + body + _EDGE_AFTER, re.IGNORECASE)


_PATTERNS = tuple((word, _pattern(word)) for word in WORDS)

#: A negation just before the word, in the same clause: only spaces may sit
#: between them, and ``yet``, ``been`` and the like may too ("not yet merged",
#: "has not been merged"). Any punctuation stops the look-back, so
#: "no. In production" and "Blocked? No, merged." are claims.
_NEGATIONS = frozenset(
    {
        "not",
        "never",
        "no",
        "nor",
        "cannot",
        "isn't",
        "wasn't",
        "aren't",
        "weren't",
        "hasn't",
        "haven't",
        "hadn't",
        "didn't",
        "doesn't",
        "don't",
        "won't",
        "can't",
        "unverified",
    }
)
_FILLERS = frozenset({"yet", "been", "be", "being", "fully", "ever", "also", "still", "all"})
_WORD_BEFORE = re.compile(r"([\w'’-]+)\s*$")
#: The status-field form right after the word: "Merged: no", "In production: not yet".
#: Matched with ``fullmatch`` against the rest of the word's OWN SOURCE LINE (see
#: :func:`_rest_of_line`), never the unit's joined text: a status block written
#: one field per line must not read the next line's field as part of this value.
#: The value runs to the end of that line or to the next ``.``, ``;`` or ``|``,
#: and must be exactly "no" or "not yet", with optional emphasis markers, closing
#: punctuation and one parenthesized remark. "Merged: no doubt." and
#: "Merged: no -- see below" are claims.
_FIELD_NO = re.compile(
    r"\s*:\s*[*_]*(?:no|not\s+yet)[*_]*[!?,)\]]*(?:\s*\([^()]*\))?[*_!?,]*\s*(?:[.;|].*)?",
    re.IGNORECASE | re.DOTALL,
)
#: A source line that ENDS in a status-field value "no" or "not yet" ("Merged: no").
#: That value negates nothing on the next line: the look-back of :func:`_negated`
#: does not cross such a line break, so "Merged: no" / "In production: yes" is a
#: claim of "in production". A plain wrapped negation ("has not" / "been merged")
#: still crosses it.
_FIELD_VALUE_ENDS_LINE = re.compile(r":\s*[*_]*(?:no|not\s+yet)[*_]*\s*$", re.IGNORECASE)
#: A heading that is exactly one of these (any case) is a closing-status label.
_LABELS = frozenset({"done", "verified myself", "cleanup", "pending", "next action"})

_PR = re.compile(r"(?<![\w&/])#(\d+)\b")
_SHA = re.compile(r"(?<![\w-])([0-9a-f]{7,40})(?![\w-])")
_CHG = re.compile(r"\bCHG-(\d+)\b")
_CHG_ROW = re.compile(r"^\| *CHG-(\d+) *\|", re.MULTILINE)
#: A squash merge ENDS its subject with ``(#N)``; ``feat(#105): ...`` is a scope.
_SQUASH = re.compile(r"\(#(\d+)\)\s*$", re.MULTILINE)

_UNCOMMITTED = "0" * 40
CHANGE_LOG = "docs/19-change-control-log.md"


# ---------------------------------------------------------------------------
# Which files are in scope.
# ---------------------------------------------------------------------------

_SCOPED_DOCS = re.compile(r"(12|17|18|73|74|95)-.*\.md")


def is_scoped(path: str) -> bool:
    """ADR-0162's scoped files, by repository-relative path."""
    folder, _, name = path.rpartition("/")
    if folder == "docs/analysis":
        return re.fullmatch(r".*-session-handoff.*\.md", name) is not None
    if folder == "docs/adr":
        return re.fullmatch(r"0.*\.md", name) is not None
    if folder == "docs":
        return (
            name in ("session-handoff.md", "product-readiness.md")
            or _SCOPED_DOCS.fullmatch(name) is not None
        )
    if folder == "":
        return re.fullmatch(r".*PROMPT.*\.md", name) is not None
    return False


# ---------------------------------------------------------------------------
# git.
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def main_ref(root: Path) -> str | None:
    """``refs/remotes/origin/main`` if it resolves, else ``refs/heads/main``, else None."""
    for ref in ("refs/remotes/origin/main", "refs/heads/main"):
        if _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0:
            return ref
    return None


def _uncommitted_paths(root: Path) -> set[str]:
    """Paths with a staged or unstaged change, the new name of a rename included."""
    done = _git(root, "status", "--porcelain", "--untracked-files=no")
    paths: set[str] = set()
    for line in done.stdout.splitlines():
        entry = line[3:]
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.add(entry.strip().strip('"'))
    return paths


def _blame(root: Path, path: str, after: set[str]) -> list[int] | None:
    """1-based numbers of the lines written after the cut-off or not committed.

    None when git cannot blame the file because ``HEAD`` does not have it (a new
    file, staged): then every line counts.
    """
    done = _git(root, "blame", "--porcelain", "--", path)
    if done.returncode != 0:
        return None
    numbers: list[int] = []
    for line in done.stdout.splitlines():
        if line.startswith("\t"):
            continue
        parts = line.split(" ")
        if len(parts) in (3, 4) and re.fullmatch(r"[0-9a-f]{40}", parts[0]):
            sha, final = parts[0], int(parts[2])
            if sha == _UNCOMMITTED or sha in after:
                numbers.append(final)
    return numbers


# ---------------------------------------------------------------------------
# Reading the text: CommonMark units.
# ---------------------------------------------------------------------------

_MARKDOWN = MarkdownIt("commonmark").enable("table")
_SOURCE_END = "completion_check_source_end"


_InlineRule = Callable[[StateInline, bool], bool]


def _recording_end(rule: _InlineRule) -> _InlineRule:
    """``rule`` (``link`` or ``image``), noting where its source ends on the token it opens.

    An image's alt text and an inline link's destination and title can hold a
    line break that no child token shows. Recording the end lets
    :func:`_read_inline` move its line counter past them. A reference link ends
    at its own closing bracket: its title lives in the definition.
    """

    def wrapped(state: StateInline, silent: bool) -> bool:
        count = len(state.tokens)
        ok = rule(state, silent)
        if ok and not silent:
            for token in state.tokens[count:]:
                if token.type in ("link_open", "image"):
                    token.meta[_SOURCE_END] = state.pos
                    break
        return ok

    return wrapped


_MARKDOWN.inline.ruler.at("link", _recording_end(_link_rule))
_MARKDOWN.inline.ruler.at("image", _recording_end(_image_rule))
_QUOTES = re.compile(r"\"[^\"]*\"|“[^”]*”")


@dataclass
class Unit:
    """One block the reader sees: a paragraph, a heading or a table row.

    ``first`` and ``last`` are its 0-based source lines (``last`` exclusive).
    ``text`` is its visible text, mentions blanked, and ``lines[i]`` is the
    0-based source line of ``text[i]``.
    """

    first: int
    last: int
    heading: bool = False
    text: str = ""
    lines: list[int] = field(default_factory=list)

    def add(self, piece: str, line: int) -> None:
        self.text += piece
        self.lines.extend([line] * len(piece))


def _after_code_span(content: str, cursor: int, markup: str) -> int:
    """The position just after the code span that ``markup`` opens at or after ``cursor``.

    A backslash-escaped backtick does not open one. If the span cannot be found,
    ``cursor`` is returned unchanged: only the line count of a span that crosses a
    line break depends on this.
    """
    run = len(markup)
    opener = re.compile(rf"(?<![`\\])`{{{run}}}(?!`)")
    closer = re.compile(rf"(?<!`)`{{{run}}}(?!`)")
    found = opener.search(content, cursor)
    if not found:
        return cursor
    closing = closer.search(content, found.end())
    return closing.end() if closing else cursor


def _read_inline(inline: Token, unit: Unit) -> None:
    """Append ``inline``'s visible text to ``unit``, each character with its line.

    ``inline.content`` is the block's source with its line breaks, so the line of
    a character is the block's first line plus the breaks before it. Text tokens
    hold no line break; soft and hard breaks, code spans and raw HTML can, and so
    can an image or an inline link's destination and title, which are skipped to
    the source end :func:`_recording_end` noted.
    """
    content = inline.content
    base = inline.map[0] if inline.map else unit.first
    cursor = 0
    link_ends: list[int] = []

    def line_now() -> int:
        return base + content.count("\n", 0, cursor)

    for child in inline.children or []:
        if child.type == "link_open":
            link_ends.append(child.meta.get(_SOURCE_END, cursor))
        elif child.type == "link_close" and link_ends:
            cursor = max(cursor, link_ends.pop())
        elif child.type == "image":
            cursor = max(cursor, child.meta.get(_SOURCE_END, cursor))
        elif child.type == "text":
            unit.add(child.content, line_now())
        elif child.type in ("softbreak", "hardbreak"):
            line = line_now()
            found = content.find("\n", cursor)
            if found >= 0:
                cursor = found + 1
            unit.add(" ", line)
        elif child.type == "code_inline":
            line = line_now()
            cursor = _after_code_span(content, cursor, child.markup)
            unit.add(" ", line)
        elif child.type == "html_inline":
            line = line_now()
            found = content.find(child.content, cursor)
            if found >= 0:
                cursor = found + len(child.content)
            unit.add(" ", line)


def units(text: str) -> list[Unit]:
    """Every paragraph, heading and table row of ``text``, in source order."""
    found: list[Unit] = []
    row: Unit | None = None
    heading = False
    for token in _MARKDOWN.parse(text):
        if token.type == "tr_open" and token.map:
            row = Unit(token.map[0], token.map[1])
        elif token.type == "tr_close" and row is not None:
            found.append(row)
            row = None
        elif token.type == "heading_open":
            heading = True
        elif token.type == "heading_close":
            heading = False
        elif token.type == "inline" and token.map:
            if row is not None:
                if row.text:
                    row.add(" | ", row.first)
                _read_inline(token, row)
                continue
            unit = Unit(token.map[0], token.map[1], heading=heading)
            _read_inline(token, unit)
            found.append(unit)
    for unit in found:
        unit.text = _blank_quotes(unit.text)
    return found


def _blank_quotes(text: str) -> str:
    """``text`` with every double-quoted span replaced by spaces of the same length."""
    return _QUOTES.sub(lambda m: " " * len(m.group(0)), text)


def _negated(before: str) -> bool:
    """Whether the text just before a word ends in a negation, in the same clause."""
    words: list[str] = []
    rest = before
    for _ in range(3):
        found = _WORD_BEFORE.search(rest)
        if not found:
            break
        words.append(found.group(1).lower().replace("’", "'"))
        rest = rest[: found.start()]
    for word in words:
        if word in _NEGATIONS:
            return True
        if word not in _FILLERS:
            return False
    return False


def _rest_of_line(unit: Unit, end: int) -> int:
    """The index in ``unit.text`` where the source line of ``unit.text[end - 1]`` stops.

    A soft or hard break is read as a space that belongs to the line it ends, so
    the slice ``unit.text[end:stop]`` is the rest of that source line as the
    reader sees it: markup gone, mentions blanked, nothing from the next line.
    """
    line = unit.lines[end - 1]
    stop = end
    while stop < len(unit.text) and unit.lines[stop] == line:
        stop += 1
    return stop


def _look_back_from(unit: Unit, start: int) -> int:
    """Where the negation look-back for a word at ``start`` may begin.

    The start of the word's source line when the line before it ends in a status
    field value ("Merged: no"), else the start of the unit.
    """
    line_start = start
    while line_start > 0 and unit.lines[line_start - 1] == unit.lines[start]:
        line_start -= 1
    if line_start > 0 and _FIELD_VALUE_ENDS_LINE.search(unit.text, 0, line_start):
        return line_start
    return 0


def claims_in(unit: Unit) -> list[tuple[int, str]]:
    """The completion words claimed in ``unit``: (index into its text, word), in order."""
    if unit.heading and " ".join(unit.text.split()).lower() in _LABELS:
        return []
    found: list[tuple[int, str]] = []
    for word, pattern in _PATTERNS:
        for match in pattern.finditer(unit.text):
            if _negated(unit.text[_look_back_from(unit, match.start()) : match.start()]):
                continue
            if _FIELD_NO.fullmatch(unit.text, match.end(), _rest_of_line(unit, match.end())):
                continue
            found.append((match.start(), word))
    return sorted(found)


class Citations:
    """What a citation may point at, read from git once and cached."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ref = main_ref(root)
        self.prs: set[int] = set()
        if self.ref is not None:
            subjects = _git(root, "log", self.ref, "--format=%s").stdout
            self.prs = {int(n) for n in _SQUASH.findall(subjects)}
        log = root / CHANGE_LOG
        text = log.read_text(encoding="utf-8") if log.is_file() else ""
        self.chg = {int(n) for n in _CHG_ROW.findall(text)}
        self._shas: dict[str, bool] = {}

    def _on_main(self, sha: str) -> bool:
        if sha not in self._shas:
            ok = self.ref is not None and (
                _git(self.root, "merge-base", "--is-ancestor", sha, self.ref).returncode == 0
            )
            self._shas[sha] = ok
        return self._shas[sha]

    def supports(self, text: str) -> bool:
        if any(int(n) in self.prs for n in _PR.findall(text)):
            return True
        if any(int(n) in self.chg for n in _CHG.findall(text)):
            return True
        return any(self._on_main(sha) for sha in _SHA.findall(text))

    def fetch_hint(self, text: str) -> str:
        """Advice when ``text`` cites a commit that is not on the local main ref, else ""."""
        missing = [sha for sha in dict.fromkeys(_SHA.findall(text)) if not self._on_main(sha)]
        if not missing:
            return ""
        where = self.ref or "main (no main ref here)"
        return (
            f" ({', '.join(missing)} is not on the local {where}: if it was merged since "
            "this clone last fetched, run `git fetch` and check again)"
        )


def problems_in_text(
    path: str, text: str, numbers: Iterable[int], citations: Citations
) -> tuple[list[str], int]:
    """Problems for the claims starting on the given 1-based lines, and how many there are."""
    wanted = set(numbers)
    source = text.replace("\r\n", "\n").split("\n")
    problems: list[str] = []
    claims = 0
    for unit in units(text):
        here = [
            (unit.lines[start] + 1, word)
            for start, word in claims_in(unit)
            if unit.lines[start] + 1 in wanted
        ]
        if not here:
            continue
        claims += len(here)
        cited = "\n".join(source[unit.first : unit.last])
        if citations.supports(cited):
            continue
        hint = citations.fetch_hint(cited)
        problems.extend(
            f"{path}:{line}: '{word}' cites no merged pull request, commit on main, or CHG row"
            + hint
            for line, word in here
        )
    return problems, claims


# ---------------------------------------------------------------------------
# The check.
# ---------------------------------------------------------------------------


def check(root: Path) -> tuple[list[str], dict[str, int]]:
    """Every unsupported claim under ``root``, and what was counted."""
    counts = dict.fromkeys(
        ("files_scoped", "files_checked", "files_exempt", "lines_checked", "claims"), 0
    )
    tracked = _git(root, "ls-files").stdout.splitlines()
    scoped = sorted(path for path in tracked if is_scoped(path))
    counts["files_scoped"] = len(scoped)
    if not scoped:
        return [f"{root}: no scoped file is tracked here, so nothing was read"], counts
    if _git(root, "cat-file", "-e", f"{CUTOFF}^{{commit}}").returncode != 0:
        return [
            f"the cut-off commit {CUTOFF[:12]} is not in this repository (a shallow "
            "clone?), so no line can be dated. Fetch the full history: "
            "`git fetch --unshallow`."
        ], counts

    log = _git(root, "log", "--name-only", "--format=", f"{CUTOFF}..HEAD").stdout
    touched = {line.strip() for line in log.splitlines() if line.strip()}
    touched |= _uncommitted_paths(root)
    after = set(_git(root, "rev-list", f"{CUTOFF}..HEAD").stdout.split())
    citations = Citations(root)

    problems: list[str] = []
    for path in scoped:
        if path not in touched or not (root / path).is_file():
            counts["files_exempt"] += 1
            continue
        counts["files_checked"] += 1
        text = (root / path).read_text(encoding="utf-8")
        numbers = _blame(root, path, after)
        if numbers is None:
            numbers = list(range(1, len(text.splitlines()) + 1))
        counts["lines_checked"] += len(numbers)
        found, claims = problems_in_text(path, text, numbers, citations)
        problems += found
        counts["claims"] += claims
    return problems, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository to check")
    args = parser.parse_args(argv)
    problems, counts = check(args.root.resolve())
    print(
        "completion claims: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
        + f" (cut-off {CUTOFF[:7]})"
    )
    for problem in problems:
        print(f"  FAIL {problem}")
    if problems:
        print(
            "A completion word needs a cited proof in the same unit (a paragraph, a list "
            "item, a heading or a table row): a pull request squash-merged on main (#N), "
            "a commit on main, or a CHG row (ADR-0162). Quote the word if it is a mention, "
            "not a claim."
        )
    return 1 if problems or counts["files_scoped"] == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
