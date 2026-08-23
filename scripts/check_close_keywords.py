"""Refuse text that tells GitHub to close an issue while saying it does not.

GitHub closes an issue when a commit message, pull-request title or pull-request
body puts a close keyword (close/closes/closed, fix/fixes/fixed,
resolve/resolves/resolved) immediately before ``#<number>``. **Its parser has no
concept of negation.** "This does NOT close #337" contains "close #337", so the
issue closes — saying the opposite of what the author wrote.

Four occurrences in this repository, all re-verified from the API on 2026-08-24:

======  ===============================================  ==========================
Issue   Text that did it                                 Surface
======  ===============================================  ==========================
#175    ``Filed, not fixed: #175 (whitespace ...``       commit e6c84ea (PR #174)
#268    ``This does **not** close #268.``                PR #282 body
#105    ``does not close #105, #268 or #203``            PR #289 body, caught by hand
#337    ``**This does NOT close #337.**``                commit 4ea57ba (PR #360)
======  ===============================================  ==========================

TWO SURFACES, AND NEITHER CHECK COVERS THE OTHER. For #282 GitHub's own
``closingIssuesReferences`` reported ``[268]`` before the merge and nobody
looked. For #337 it reported ``[]`` — a clean bill of health — because the
sentence lived in the ``gh pr merge --body`` text, which is not part of the pull
request at all. So the authoritative API is necessary and NOT sufficient.

WHAT THIS DELIBERATELY DOES NOT FLAG, and why the distinction is the whole
value: a bare ``Fixes #123`` is the correct, common way to close an issue. A
checker that flags every close keyword next to a number fires on every
legitimate close, becomes noise and is routed around within a week — worse than
no checker, because it also trains people to ignore a red signal. Only the
NEGATED form is reported, because a negated close is never intentional.

``fix(#N)`` — the conventional-commit scope slot — IS NOT FLAGGED, and that is a
measured decision rather than an oversight. It was originally believed to be the
vector that closed #337. It is not:

* ``fix(#N)`` appears in 10 commit subjects on main.
* Three of them (68d8b69 ``fix(#148)``, 5bbe616 and 15c365c ``fix(#226)``)
  contain NO other reference to that issue anywhere in the message, and in none
  of the three did the commit close the issue.
* #148 was closed on 2026-08-02 with ``commit_id: null``; its ``fix(#148)``
  commit landed 2026-08-19, seventeen days LATER.

So the bracket form does not close anything, and flagging it would have produced
ten false positives against real history while missing the sentence that did the
damage. Re-derive with ``--scan-history`` if GitHub's parser ever changes.

The classification is a pure function over text, so it is tested hermetically
(``tests/unit/test_close_keyword_guard.py``) with no network and no ``gh``.
Only ``--premerge-pr`` touches GitHub.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass

#: GitHub's close keywords. Order matters inside the alternation only in that
#: each branch is anchored by ``\b`` on both sides, so ``fix`` cannot swallow
#: the ``fix`` of ``fixes``.
_KEYWORD = r"(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)"

#: A close reference as GitHub reads it: keyword, an optional colon, optional
#: spaces, then ``#<digits>``. A newline between the two does NOT count, which
#: is why only spaces and tabs appear here.
CLOSE_REFERENCE = re.compile(rf"\b({_KEYWORD})\b[ \t]*:?[ \t]*#(\d+)\b", re.IGNORECASE)

#: Words that turn a close into its opposite. ``n't`` is handled by suffix so
#: that doesn't/won't/can't need no enumeration.
NEGATIONS = frozenset(
    {
        "not",
        "no",
        "never",
        "nothing",
        "none",
        "neither",
        "nor",
        "cannot",
        "without",
        "unfixed",
        "unresolved",
        "un-fixed",
    }
)

#: Characters that end the clause the close verb belongs to. A comma is included
#: on purpose: a negation in a PRECEDING clause does not attach to this verb.
#: "With no regressions, closes #123" is a legitimate close and must stay clean,
#: while "Filed, not fixed: #175" still trips because ``not`` is found before the
#: scan reaches the comma.
_CLAUSE_BOUNDARY = frozenset(".!?;:\n\r,")

#: Markdown emphasis is invisible to GitHub's parser and must be invisible here
#: too — the real #282 text was ``This does **not** close #268``.
_EMPHASIS = frozenset("*_`~")

#: How many words back from the keyword a negation may sit. Two intervening
#: words covers "does not yet close" and "will not, however, close" without
#: reaching into an unrelated earlier phrase.
_LOOKBACK_WORDS = 3


@dataclass(frozen=True)
class Finding:
    """One place where the text says "not closed" and GitHub will read "closed"."""

    issue: int
    keyword: str
    negation: str
    excerpt: str

    def describe(self) -> str:
        return (
            f"  #{self.issue}: '{self.negation} ... {self.keyword} #{self.issue}' "
            f"-> GitHub will CLOSE #{self.issue}\n      {self.excerpt}"
        )


def close_references(text: str) -> list[tuple[str, int, int]]:
    """Every (keyword, issue, offset) GitHub would read as a closing reference.

    The positive partner for every "nothing negated here" result: a text with no
    close references at all cannot have a negated one, and the two counts are
    reported separately so an empty measurement is visible rather than green.
    """
    return [(m.group(1), int(m.group(2)), m.start()) for m in CLOSE_REFERENCE.finditer(text)]


def _preceding_negation(text: str, keyword_start: int) -> str | None:
    """The negation attached to the close verb at ``keyword_start``, if any.

    Walks backwards word by word, ignoring markdown emphasis, and stops at the
    first clause boundary. Returns the negating word so the report can quote it.
    """
    words: list[str] = []
    letters: list[str] = []
    index = keyword_start - 1

    while index >= 0 and len(words) < _LOOKBACK_WORDS:
        char = text[index]
        if char in _CLAUSE_BOUNDARY:
            break
        if char.isspace():
            if letters:
                words.append("".join(reversed(letters)))
                letters = []
        elif char not in _EMPHASIS:
            letters.append(char)
        index -= 1

    if letters and len(words) < _LOOKBACK_WORDS:
        words.append("".join(reversed(letters)))

    for word in words:
        stripped = word.lower().strip("()[]{}\"'")
        if stripped in NEGATIONS or stripped.endswith("n't"):
            return stripped
    return None


def _excerpt(text: str, offset: int) -> str:
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    line = text[line_start:] if line_end == -1 else text[line_start:line_end]
    line = line.strip()
    return line if len(line) <= 160 else line[:157] + "..."


def negated_closes(text: str) -> list[Finding]:
    """Close references whose own sentence says they are NOT closing anything."""
    findings = []
    for keyword, issue, offset in close_references(text):
        negation = _preceding_negation(text, offset)
        if negation is not None:
            findings.append(
                Finding(
                    issue=issue,
                    keyword=keyword.lower(),
                    negation=negation,
                    excerpt=_excerpt(text, offset),
                )
            )
    return findings


def _report(label: str, text: str, *, advisory: bool) -> int:
    """Print what was counted, then the findings. Returns the exit code."""
    references = close_references(text)
    findings = negated_closes(text)
    print(
        f"close-keyword guard [{label}]: {len(text)} chars, "
        f"{len(references)} closing reference(s), {len(findings)} negated"
    )

    if not findings:
        if references:
            closing = ", ".join(f"#{issue}" for _, issue, _ in references)
            print(f"  will close: {closing} — none of them negated. OK.")
        else:
            print("  no closing reference of any kind. OK.")
        return 0

    print("\nThis text says an issue is NOT being closed, and closes it anyway:\n")
    for finding in findings:
        print(finding.describe())
    print(
        "\nGitHub's parser has no concept of negation. Rewrite so the keyword is\n"
        "not adjacent to the number — e.g. 'does not close issue 337', or\n"
        "'#337 stays open'. Both read the same and neither closes anything.\n"
    )
    if advisory:
        print("ADVISORY: a commit message is immutable, so this reports and does not block.")
        return 0
    return 1


def _gh_closing_issues(pr: int) -> list[int]:
    """GitHub's OWN parse of the pull request — authoritative, and not enough.

    Necessary because it understands forms this regex does not (cross-repo,
    ``GH-123``, full URLs). Not sufficient because it sees only the pull
    request: for #360 it returned ``[]`` while the merge body closed #337.
    """
    raw = subprocess.run(
        ["gh", "pr", "view", str(pr), "--json", "closingIssuesReferences"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [row["number"] for row in json.loads(raw)["closingIssuesReferences"]]


def _commit_message(ref: str) -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%B", ref],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _scan_history(branch: str) -> int:
    """Yield measurement: run the classifier over every commit on ``branch``.

    This is how the precision claim in the module docstring stays honest. It
    prints the commits it flagged AND the number it examined, so a run that
    measured nothing cannot look like a clean bill of health.
    """
    log = subprocess.run(
        ["git", "log", branch, "--format=%x00%H%x00%B"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\x00")

    examined = 0
    flagged = 0
    for index in range(1, len(log) - 1, 2):
        sha, message = log[index].strip(), log[index + 1]
        examined += 1
        findings = negated_closes(message)
        if findings:
            flagged += 1
            issues = ", ".join(f"#{f.issue}" for f in findings)
            print(f"{sha[:8]}  {issues}  {findings[0].excerpt[:90]}")

    print(f"\nexamined {examined} commit message(s) on {branch}; {flagged} flagged")
    if examined == 0:
        print("MEASURED NOTHING — refusing to report a clean history.")
        return 2
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--env", nargs="+", metavar="VAR", help="read text from these env vars")
    source.add_argument("--commit", metavar="REF", help="vet a commit message")
    source.add_argument("--scan-history", metavar="BRANCH", help="yield measurement over a branch")
    parser.add_argument(
        "--premerge-pr",
        type=int,
        metavar="PR",
        help="also ask GitHub what it thinks this pull request closes",
    )
    parser.add_argument("--advisory", action="store_true", help="report but always exit 0")
    parser.add_argument(
        "--require-nonempty",
        action="store_true",
        help="fail if the input text is empty — a silently unwired gate is not a pass",
    )
    args = parser.parse_args(list(argv[1:]))

    if args.scan_history:
        return _scan_history(args.scan_history)

    if args.env:
        text = "\n\n".join(os.environ.get(name, "") for name in args.env)
        label = "+".join(args.env)
    else:
        text = _commit_message(args.commit)
        label = f"commit {args.commit}"

    if args.require_nonempty and not text.strip():
        print(
            f"close-keyword guard [{label}]: input is EMPTY.\n"
            "Refusing to pass: this gate cannot vet text it was never given.\n"
            "Check the workflow wiring that should have supplied it."
        )
        return 2

    status = _report(label, text, advisory=args.advisory)

    if args.premerge_pr is not None:
        linked = _gh_closing_issues(args.premerge_pr)
        print(f"\nGitHub's own parse of PR #{args.premerge_pr}: closes {linked or 'nothing'}")
        if linked:
            print(
                "  Confirm every one of those SHOULD close. GitHub sees only the\n"
                "  pull request — the merge subject and body above are checked\n"
                "  separately, and for PR #360 this list was empty while the merge\n"
                "  body closed #337."
            )
    return status


if __name__ == "__main__":  # pragma: no cover - exercised via tests of the pure functions
    raise SystemExit(main(sys.argv))
