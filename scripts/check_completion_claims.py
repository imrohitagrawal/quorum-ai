#!/usr/bin/env python3
"""A completion word in a status document must cite its proof (ADR-0162).

A status document here may say "merged", "in production", "approved" and the
other words in :data:`WORDS` only when the same paragraph, or the same table
row, cites one of:

* a pull request ``#N`` whose squash commit, with ``(#N)`` in its subject, is on
  ``main``;
* a commit (7 to 40 hex characters) that is an ancestor of ``main``;
* a ``CHG-NNN`` that is a row of ``docs/19-change-control-log.md``.

A word right after a negation ("not merged", "never merged") is not a claim, and
neither is a word inside backticks or double quotes, which mentions the word
rather than claims it. A quoted or backticked span may run across a line break
inside one paragraph. A fenced code block (a line opening with three backticks
or tildes, to the line that closes it) is quoted output in the same way: the
mechanical handoff prints ``git status`` and the leftover report there.

THE CUT-OFF. Only lines written after :data:`CUTOFF` (the merge of package A,
#558) are checked: ``git blame`` names the commit that last wrote each line, and
an uncommitted line always counts. A scoped file that no commit after the
cut-off touched, and that has no uncommitted change, is exempt without a blame.
The files touched after the cut-off come from ONE ``git log --name-only`` plus
``git status --porcelain``, so only those files are blamed.

The main ref is ``refs/remotes/origin/main`` when it exists, else
``refs/heads/main``: on a pull-request checkout there is no local ``main``.

GATE CHARTER
------------
WHY THIS EXISTS: on 2026-10-11, 14 false completion claims were planted one at a
time in a copy of ``main``; 9 were accepted by every check, including a handoff
saying two items were merged and in production when neither was.

WHAT IT CANNOT SEE: words outside the list ("done", "shipped", "live"); a false
claim in a paragraph that also holds a true citation, since a citation anywhere
in the paragraph supports every word in it; lines written before the cut-off;
untracked files; a claim typed inside backticks, double quotes or a fenced code
block; and whether the cited pull request did what the sentence says.

FALSE-POSITIVE COST: a new line that uses a listed word in its plain sense ("the
request is accepted") fails until it is quoted, reworded or cited.

WHEN TO REMOVE: when status claims are generated from git and GitHub instead of
written by hand.

Stdlib and git only: it runs inside ``make validate``, offline.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

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
    body = r"[ \t]+".join(re.escape(part) for part in word.split(" "))
    return re.compile(_EDGE_BEFORE + body + _EDGE_AFTER, re.IGNORECASE)


_PATTERNS = tuple((word, _pattern(word)) for word in WORDS)

#: A negation just before the word. ``yet``, ``been`` and the like may sit
#: between them: "not yet merged", "has not been merged".
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
_WORD_BEFORE = re.compile(r"([\w'’-]+)\W*$")

_PR = re.compile(r"(?<![\w&/])#(\d+)\b")
_SHA = re.compile(r"(?<![\w-])([0-9a-f]{7,40})(?![\w-])")
_CHG = re.compile(r"\bCHG-(\d+)\b")
_CHG_ROW = re.compile(r"^\| *CHG-(\d+) *\|", re.MULTILINE)
_SQUASH = re.compile(r"\(#(\d+)\)")

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
# Reading the text.
# ---------------------------------------------------------------------------


def _blank(text: str, start: int, end: int) -> str:
    """``text`` with ``[start, end)`` replaced by spaces, line breaks kept."""
    span = "".join("\n" if ch == "\n" else " " for ch in text[start:end])
    return text[:start] + span + text[end:]


_BACKTICKS = re.compile(r"(`+)(?:(?!\1).|\n)+?\1", re.DOTALL)
_QUOTES = re.compile(r"\"[^\"]*\"|“[^”]*”")


def mask_mentions(paragraph: str) -> str:
    """``paragraph`` with every backticked or double-quoted span blanked.

    Backticks first, so a quote inside code is not read as a quote. A span may
    cross a line break: the paragraph is masked as one piece of text.
    """
    for match in list(_BACKTICKS.finditer(paragraph)):
        paragraph = _blank(paragraph, match.start(), match.end())
    for match in list(_QUOTES.finditer(paragraph)):
        paragraph = _blank(paragraph, match.start(), match.end())
    return paragraph


def _negated(before: str) -> bool:
    """Whether the text just before a word ends in a negation."""
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


def claims_in(line: str) -> list[str]:
    """The completion words claimed in one (already masked) line, in order."""
    found: list[tuple[int, str]] = []
    for word, pattern in _PATTERNS:
        for match in pattern.finditer(line):
            if not _negated(line[: match.start()]):
                found.append((match.start(), word))
    return [word for _start, word in sorted(found)]


def _units(lines: list[str]) -> list[tuple[int, int]]:
    """For each line (0-based), the [start, end) of its paragraph or table row."""
    spans: list[tuple[int, int]] = [(i, i + 1) for i in range(len(lines))]
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        start = i
        while i < len(lines) and lines[i].strip():
            i += 1
        for j in range(start, i):
            if not lines[j].lstrip().startswith("|"):
                spans[j] = (start, i)
    return spans


def _fenced(lines: list[str]) -> set[int]:
    """0-based indexes of the lines inside a fenced code block, its fences included."""
    inside: set[int] = set()
    fence: str | None = None
    for i, line in enumerate(lines):
        opener = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if fence is None:
            if opener:
                fence = opener.group(1)
                inside.add(i)
            continue
        inside.add(i)
        if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence):
            fence = None
    return inside


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


def problems_in_text(
    path: str, text: str, numbers: Iterable[int], citations: Citations
) -> tuple[list[str], int]:
    """Problems for the given 1-based lines of ``text``, and how many claims they hold."""
    lines = text.splitlines()
    spans = _units(lines)
    fenced = _fenced(lines)
    masked_units: dict[tuple[int, int], list[str]] = {}
    problems: list[str] = []
    claims = 0
    for number in sorted(set(numbers)):
        index = number - 1
        if not 0 <= index < len(lines) or index in fenced:
            continue
        span = spans[index]
        if span not in masked_units:
            masked_units[span] = mask_mentions("\n".join(lines[span[0] : span[1]])).split("\n")
        words = claims_in(masked_units[span][index - span[0]])
        if not words:
            continue
        claims += len(words)
        if citations.supports("\n".join(lines[span[0] : span[1]])):
            continue
        problems.extend(
            f"{path}:{number}: '{word}' cites no merged pull request, commit on main, or CHG row"
            for word in words
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
            "A completion word needs a cited proof in the same paragraph or table row: "
            "a pull request squash-merged on main (#N), a commit on main, or a CHG row "
            "(ADR-0162). Quote the word if it is a mention, not a claim."
        )
    return 1 if problems or counts["files_scoped"] == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
