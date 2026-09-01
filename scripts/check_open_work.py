#!/usr/bin/env python3
"""The open-work board's State column is DERIVED from the tree, never declared.

WHY THIS EXISTS. Work here was planned in five places that did not know about
each other, and the one file ``AGENTS.md`` tells a session to maintain --
``docs/00-factory-console.md`` -- was 64 first-parent commits behind its last
touch and months behind its content date. Four test files read that file and
none asks whether the work it announces is the work in flight. Hand-written
status rots because nothing compares the sentence to the tree.

WHY IT WORKS THE WAY IT DOES -- two failed designs, both defeated by review.

* **Draft 1: polarity typed by the author.** Each row said ``ABSENT`` or
  ``PRESENT`` and the gate checked it. Replacing every ``| PENDING |`` with
  ``| DONE |`` left the gate green, printing "0 PENDING", with zero bytes
  changed under ``src/``.
* **Draft 2: state coupled to polarity.** ``PENDING`` asserted the claim as
  written, ``DONE`` its opposite. A *two*-token edit -- flipping the state word
  and the polarity word together -- did the same thing. Cost went from one word
  to two; the protection claimed went from nothing to total. A second route also
  worked: unpin a row and mark it ``DONE``.

The root cause both drafts share: **the state and the claim were both typed by
the same hand, in the same file.** Coupling two author-controlled fields to each
other cannot make an independent check.

**So no hand writes the state.** The board carries the evidence expression; this
script DERIVES the State column from what it reads off disk and writes it, and
``--check`` refuses when the checked-in column disagrees with what the tree says.
A row cannot be marked done by editing its status. Same shape as
``scripts/generate_adr_index.py`` -- a derived fact is generated and verified,
not trusted -- which ADR-0079 cited from the start and which the first two
drafts did not actually follow.

**What that does and does not buy, stated exactly.** It closes a hand writing
the State column ALONE -- which is what carelessness looks like, and what both
earlier exploits were. It does NOT close an author who rewrites the polarity
word too: the polarity is part of the claim, the author writes the claim, and
the derivation reads it. That residual is asserted by
``test_rewriting_the_evidence_claim_is_accepted_and_that_is_the_known_limit``
rather than only described, because both earlier drafts shipped a sentence
promising more than they delivered.

DERIVATION. For a pinned row, the evidence states the OPEN form of the fact:

    PENDING   the claim holds as written -- the work is still open
    DONE      its opposite holds -- the work landed
    UNPINNED  no needle; nothing is known, and this can never read DONE

MATCHING IGNORES COMMENTS. A needle is searched in the code text only: a ``#``
that starts a line or follows whitespace ends that line. Review demonstrated
why -- appending ``# TODO: we still need to send "stream": True here`` to
``providers.py`` flipped W1's evidence, so a comment saying the work was NOT
done would have derived ``DONE``. The whitespace guard is what keeps a URL
intact; a naive cut at ``//`` would truncate W16's needle at ``https:``.
Verified against all 13 live needles: every one still matches after stripping.

ANTI-VACUITY. Three floors, because every check here passes over nothing: the
table must parse at least one row; at least ``MIN_EVIDENCE_CLAIMS`` needles must
actually be READ OFF DISK; and a needle must be at least ``MIN_NEEDLE_CHARS``
long, because a short one matches prose rather than code.

WHAT IT STILL CANNOT SEE -- stated narrowly, because the first two drafts each
overclaimed here and were wrong:

* **An author who rewrites the EVIDENCE cell** to point at a file or needle
  where the claim already holds the other way. That is not a status flip; it is
  a visible change to the claim itself, and it is what review reads.
* **Work that lands under a different name** than the needle, or by a different
  route under the same name -- defining ``_bound_sniff_time`` rather than
  deleting its dangling references would not flip W15.
* **Unpinned rows.** Nothing is checked about them. Their number is pinned,
  which caps the blindness rather than curing it.
* **A row that should exist and does not.**

Adversarial review remains the primary defence; this repo measured 0 of 16
``src/`` defects caught by any gate against 10 of 16 by review
(``docs/metrics/defect-discovery-audit.md``).

``--check`` exits 1 with every failure listed. Run with no arguments to rewrite
the State column.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "docs" / "65-open-work.md"


def _load_code_text_helper() -> Any:
    """Load ``tests/code_text.py`` BY PATH, not as ``tests.code_text``.

    WHY THIS EXISTS (#418). This script used to strip only ``#`` comment
    tails, line by line, and never tokenize -- so a needle string that
    appeared inside a Python DOCSTRING (prose, not the construct it names)
    still counted PRESENT. ``tests/code_text.py`` already exists to fix
    exactly this class of bug (its own docstring documents two prior
    instances, PR #164), tokenizing Python source and blanking both comments
    and docstrings. Rather than grow a second, weaker implementation here --
    which is how #418 happened in the first place, two parallel strippers of
    different strength -- this script reuses that one module. See
    ADR-0091 for the layering decision and the rejected alternatives.

    Loaded BY PATH, exactly like this script's own tests load *it*
    (``tests/unit/test_open_work_matches_reality.py::_load_script``), for the
    same two reasons stated there: ``tests`` has no ``__init__.py`` and this
    script is run directly (``python3 scripts/check_open_work.py``, no
    ``PYTHONPATH``), so a package import would only work by accident of
    invocation directory; and ``make type-check`` runs ``mypy src tests``,
    which follows static imports, so a real ``import tests.code_text`` here
    would be a route for an unchecked ``scripts/`` file to be dragged into a
    strict-mode gate. ``tests/code_text.py`` depends on nothing but
    ``io``, ``tokenize`` and ``pathlib`` -- stdlib only, no pytest, no
    fixtures -- so it is safe to load from a script that runs inside
    ``make validate``.
    """
    path = ROOT / "tests" / "code_text.py"
    spec = importlib.util.spec_from_file_location("_open_work_code_text", path)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CODE_TEXT = _load_code_text_helper()

#: How many first-parent commits the board may fall behind ``HEAD`` before this
#: gate refuses. DERIVED, not chosen by taste: ``main`` took 308 first-parent
#: commits in the trailing 90 days measured 2026-08-28 (``git log
#: --first-parent main --since="90 days ago" --format=%H | wc -l``), i.e. ~3.4
#: a day, so 60 is about 18 days. The only measured rot point in this
#: repository is the factory console at 64 commits stale, so this fires just
#: below the point staleness has actually been observed at.
#:
#: Deliberately loose: the derived State column is the real freshness signal and
#: it runs on every commit. A tight threshold would turn re-stamping into a
#: ritual performed without re-reading.
MAX_DRIFT_COMMITS = 60

#: Floor on needles actually read off disk. Set below today's 13 so routine
#: edits do not trip it, and above zero so a board that pins nothing passes.
#: Review demonstrated the need: with only an empty-table floor, a board whose
#: every row was unpinned exited 0 having read nothing.
MIN_EVIDENCE_CLAIMS = 8

#: Shortest acceptable needle. A short needle matches prose, not code: review
#: satisfied W7's original one-word needle ``google`` by appending the comment
#: "google sign-in is still TODO" to ``auth.py``. Every live needle is 14+.
MIN_NEEDLE_CHARS = 12

#: The branch this repository merges into, and therefore the only branch a
#: board anchor can safely sit on. Squash-merging discards every commit made on
#: a feature branch, so an anchor stamped there stops existing the moment the
#: branch lands (#402).
MAIN_BRANCH = "main"

_SHA_LINE = re.compile(r"^Verified at: `([0-9a-f]{40})`$", re.MULTILINE)
#: DIGITS, not spelled-out words -- the whole point is that a machine re-reads
#: them, and ``twelve`` is not machine-readable.
_ROW_COUNT = re.compile(
    r"^The board holds \*\*(\d+)\*\* rows, \*\*(\d+)\*\* of them unpinned\.$", re.MULTILINE
)
_ROW = re.compile(r"^\| *(W\d+) *\|(.+)$")
_EVIDENCE = re.compile(r"^(ABSENT|PRESENT) (\S+) :: (.+)$")
#: A ``#`` that starts a line or follows whitespace begins a comment. The
#: WHITESPACE GUARD is the load-bearing part: without it, a cut at the first
#: ``//`` truncates W16's needle line to ``URL = "https:``. Only ``#`` is listed
#: because every file the board pins is Python, TOML or Markdown. Verified
#: against all 13 live needles: each still matches after stripping.
_COMMENT = re.compile(r"(?:^|\s)#")

PENDING = "PENDING"
DONE = "DONE"
UNPINNED = "UNPINNED"
_UNPINNED_CELL = "—"  # em dash


@dataclass(frozen=True)
class Row:
    """One line of the board, as parsed."""

    row_id: str
    item: str
    state: str
    evidence: str
    issue: str
    depends_on: str

    @property
    def pinned(self) -> bool:
        return self.evidence != _UNPINNED_CELL


@dataclass(frozen=True)
class Board:
    sha: str | None
    stated_rows: int | None
    stated_unpinned: int | None
    rows: list[Row]


def _cell(raw: str) -> str:
    """Strip a markdown table cell down to its text, backticks removed.

    Exactly ONE backtick comes off each end, not a run. ``str.strip("`")``
    removes every trailing backtick, so a needle ending in one had it silently
    deleted and the refusal below never saw the character it exists to refuse.
    """
    text = raw.strip()
    if text.startswith("`"):
        text = text[1:]
    if text.endswith("`"):
        text = text[:-1]
    return text.strip()


def code_text(source: str) -> str:
    """``source`` with comment tails removed, so a needle matches code only.

    Line-oriented, whitespace-guarded ``#`` stripping -- correct for
    Markdown and TOML, where there is no Python parser to fall back on. A
    ``.py`` evidence file is NOT read through this function; see
    :func:`_evidence_text`, which routes those through
    ``tests/code_text.py``'s tokenizer instead, because a docstring cannot be
    told apart from code by this kind of line-oriented scan (#418).
    """
    kept = []
    for line in source.splitlines():
        found = _COMMENT.search(line)
        kept.append(line[: found.start()] if found else line)
    return "\n".join(kept)


def _evidence_text(target: Path) -> str:
    """The searchable CODE TEXT of an evidence file -- comments/docstrings out.

    ``.py`` files go through ``tests/code_text.py``'s tokenizer, which blanks
    both comments and docstrings (#418: a needle living only in a docstring
    must not count as the code it describes). Every other file the board pins
    (Markdown, TOML) has no Python parser to use, so it keeps the simpler
    whitespace-guarded ``#`` stripper in :func:`code_text` -- unchanged
    behaviour, verified against all live non-Python needles.
    """
    if target.suffix == ".py":
        return _CODE_TEXT.code_without_comments(target)
    return code_text(target.read_text(encoding="utf-8"))


def parse_board(text: str) -> Board:
    """Pull the anchor SHA, the two stated counts and every ``W`` row out."""
    sha_match = _SHA_LINE.search(text)
    count_match = _ROW_COUNT.search(text)
    rows: list[Row] = []
    for line in text.splitlines():
        row_match = _ROW.match(line)
        if not row_match:
            continue
        cells = [_cell(c) for c in row_match.group(2).split("|")]
        # A malformed row is kept with blanks so the checks below report it
        # rather than silently dropping it -- a dropped row would make both
        # count pins disagree, which is the loud failure we want.
        cells = (cells + [""] * 5)[:5]
        rows.append(
            Row(
                row_id=row_match.group(1),
                item=cells[0],
                state=cells[1],
                evidence=cells[2],
                issue=cells[3],
                depends_on=cells[4],
            )
        )
    return Board(
        sha=sha_match.group(1) if sha_match else None,
        stated_rows=int(count_match.group(1)) if count_match else None,
        stated_unpinned=int(count_match.group(2)) if count_match else None,
        rows=rows,
    )


def derive_states(board: Board, root: Path) -> tuple[dict[str, str], list[str], int]:
    """Work out each row's state FROM THE TREE.

    Returns the states by row id, any failures reading the evidence, and how
    many needles were actually read off disk.
    """
    states: dict[str, str] = {}
    failures: list[str] = []
    read = 0
    for row in board.rows:
        if not row.pinned:
            # An unpinned row can never read DONE. "Unpin it, then call it
            # done" was a demonstrated route past the previous design.
            states[row.row_id] = UNPINNED
            continue
        match = _EVIDENCE.match(row.evidence)
        if not match:
            failures.append(
                f"{row.row_id}: evidence {row.evidence!r} is neither "
                f"{_UNPINNED_CELL!r} nor '<ABSENT|PRESENT> <path> :: <needle>'"
            )
            continue
        polarity, rel_path, needle = match.group(1), match.group(2), match.group(3)
        # A needle cannot contain a pipe -- the row was split on pipes to get
        # here. A BACKTICK can, and breaks the code span a human reads.
        if "`" in needle:
            failures.append(
                f"{row.row_id}: needle contains a backtick, which breaks the "
                "markdown code span -- the rendered row would not say what "
                "this gate checks"
            )
            continue
        if len(needle) < MIN_NEEDLE_CHARS:
            failures.append(
                f"{row.row_id}: needle {needle!r} is shorter than "
                f"{MIN_NEEDLE_CHARS} characters. A short needle matches PROSE: "
                "a one-word needle here was satisfied by adding a comment "
                "saying the work was still TODO. Pin a code line, or leave the "
                f"row unpinned with {_UNPINNED_CELL!r}."
            )
            continue
        target = root / rel_path
        if not target.is_file():
            failures.append(f"{row.row_id}: evidence path {rel_path} does not exist")
            continue
        present = needle in _evidence_text(target)
        read += 1
        open_form_says_present = polarity == "PRESENT"
        states[row.row_id] = PENDING if present == open_form_says_present else DONE
    return states, failures, read


def render(text: str, states: dict[str, str]) -> str:
    """``text`` with every row's State cell replaced by its derived value."""
    out = []
    for line in text.splitlines(keepends=True):
        row_match = _ROW.match(line)
        if not row_match or row_match.group(1) not in states:
            out.append(line)
            continue
        stripped = line.rstrip("\n")
        newline = line[len(stripped) :]
        parts = stripped.split("|")
        # ['', ' W1 ', ' item ', ' STATE ', ' evidence ', ' issue ', ' dep ', '']
        if len(parts) < 5:
            out.append(line)
            continue
        parts[3] = f" {states[row_match.group(1)]} "
        out.append("|".join(parts) + newline)
    return "".join(out)


def check_structure(board: Board) -> list[str]:
    """Ids unique, and the table is not empty.

    The State column is NOT validated here: it is generated, and any value a
    hand typed is caught by the rendering comparison in :func:`check_all`.
    """
    failures: list[str] = []
    # ANTI-VACUITY FLOOR ONE. Every check below loops over ``board.rows`` and
    # all of them are satisfied by nothing.
    if not board.rows:
        failures.append(
            f"{BOARD.name}: no rows parsed. The table moved or the row pattern "
            f"({_ROW.pattern!r}) no longer matches. This gate refuses to pass "
            "over an empty input."
        )
        return failures
    seen: set[str] = set()
    for row in board.rows:
        if row.row_id in seen:
            failures.append(f"{row.row_id}: duplicate row id")
        seen.add(row.row_id)
    return failures


def check_counts(board: Board) -> list[str]:
    """The board's own two numbers against the parsed table."""
    failures: list[str] = []
    actual_rows = len(board.rows)
    actual_unpinned = sum(1 for row in board.rows if not row.pinned)
    if board.stated_rows is None or board.stated_unpinned is None:
        failures.append(
            f"{BOARD.name} no longer states its counts in the form this gate "
            f"checks ({_ROW_COUNT.pattern!r}). Restore the sentence or update "
            "the pattern -- do not delete the check."
        )
        return failures
    if board.stated_rows != actual_rows:
        failures.append(f"{BOARD.name} says {board.stated_rows} rows; the table has {actual_rows}.")
    if board.stated_unpinned != actual_unpinned:
        failures.append(
            f"{BOARD.name} says {board.stated_unpinned} unpinned rows; the table "
            f"has {actual_unpinned}. An unpinned row is one this gate cannot "
            "check at all, so the number is capped on purpose."
        )
    return failures


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def has_git_history(root: Path) -> bool:
    """Whether ``root`` is itself the top of a git working tree.

    ``--show-toplevel``, not ``--git-dir``: the latter walks UP through parents,
    so a ``git archive`` copy unpacked anywhere under a repository answers yes
    and the freshness family then fails against the wrong history -- the exact
    phantom failure this function exists to prevent (AGENTS.md rules 9a, 12b).
    """
    shown = _git(root, "rev-parse", "--show-toplevel")
    if shown.returncode != 0:
        return False
    return Path(shown.stdout.strip()).resolve() == root.resolve()


def anchor_commit_exists(root: Path, sha: str) -> bool:
    """Whether ``sha`` names a commit object in ``root``'s object store.

    Shared by :func:`check_freshness` and :func:`check_all` so the
    squash-survival family below can be skipped on an anchor that was already
    refused here -- rather than being sniffed for out of the other family's
    failure strings.
    """
    return _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def remote_names(root: Path) -> list[str] | None:
    """Every configured remote -- or ``None`` when git could not say.

    ``None`` IS NOT "no remotes", and conflating the two fails OPEN. Measured
    on git 2.54.0: ONE invalid refspec anywhere in the config makes
    ``git remote`` exit 128 with empty stdout, so a checkout holding
    ``refs/remotes/origin/main`` right there on disk read as having neither a
    remote nor a ``main``, skipped, and ACCEPTED a branch-only anchor while
    printing "no remote and no `main` ref here" -- false on both counts.

    Reachable from this gate's own printed remedy: ``git remote set-branches
    --add origin 'mai?'`` exits 0, accepts the typo silently, and leaves
    ``git remote`` broken in that clone from then on.
    """
    result = _git(root, "remote")
    if result.returncode != 0:
        return None
    return result.stdout.split()


def _ref_resolves(root: Path, ref: str) -> bool:
    return _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def _main_refs_for(root: Path, remotes: list[str]) -> list[str]:
    """The ``main`` refs that resolve, given an already-enumerated remote list.

    Remote-tracking refs first, ``origin`` at the head of those because it is
    the one a contributor is most likely to have current. A remote-tracking
    ref is built from a CONFIGURED REMOTE NAME, never matched by suffix, so a
    branch called ``release/main`` is not mistaken for trunk.

    THE LOCAL ``refs/heads/main`` IS A FALLBACK, NOT A PEER. It is consulted
    only when no remote's ``main`` resolves at all. That is what makes a
    ``git clone --bare`` plus ``git worktree add`` layout answerable -- no
    refspec there mentions ``main`` while a complete ``refs/heads/main`` sits
    in the same object store -- but treating it as a peer accepted a commit a
    squash merge will discard: a contributor who runs ``git checkout main &&
    git merge --ff-only feature`` puts the branch commit on the local ``main``,
    and the gate then found it there and passed. Reproduced, then closed by
    this ordering.
    """
    ordered = [name for name in ("origin",) if name in remotes]
    ordered += [name for name in sorted(remotes) if name != "origin"]
    remote_main = [
        ref
        for ref in (f"refs/remotes/{name}/{MAIN_BRANCH}" for name in ordered)
        if _ref_resolves(root, ref)
    ]
    if remote_main:
        return remote_main
    local = f"refs/heads/{MAIN_BRANCH}"
    return [local] if _ref_resolves(root, local) else []


def known_main_refs(root: Path) -> list[str] | None:
    """Every ref in this checkout that IS ``main`` -- ``None`` if unknowable.

    THE WHOLE DESIGN OF #402 IS IN THIS FUNCTION: it asks which refs EXIST,
    never which refspecs are configured. Two earlier designs asked the second
    question and both shipped green while wrong, because git's answer and the
    config's answer disagree in at least four measured ways (git 2.54.0).
    Neither ``refs/heads/main`` with no colon nor ``+*:refs/remotes/origin/*``
    produces ``refs/remotes/origin/main`` -- the first writes only
    ``FETCH_HEAD``, the second writes ``refs/remotes/origin/refs/heads/main``,
    which is a ref but not the one anybody meant. ``+main:refs/remotes/origin/
    main`` looks like it does not track and produces the ref anyway. And a
    refspec holding ``[`` or ``?`` is rejected by git outright. A ref either
    resolves or it does not.
    """
    remotes = remote_names(root)
    if remotes is None:
        return None
    return _main_refs_for(root, remotes)


def _is_shallow(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"


def check_anchor_is_on_main(board: Board, root: Path) -> tuple[list[str], str]:
    """The anchor must live on a ``main`` this checkout can see (#402).

    Returns ``(failures, note)``; the note goes on ``check_all``'s report line
    so a skip is never silent and a pass says which ref answered.

    WHY ANCESTRY AGAINST ``HEAD`` IS NOT ENOUGH. :func:`check_freshness`
    compares the anchor with ``HEAD``. On a feature branch a commit made ON
    that branch IS an ancestor of HEAD, so it passed; this repository
    SQUASH-merges, which discards that commit, and the gate then refused on
    ``main`` after the merge instead of on the pull request before it. PR #399:
    anchor ``2350e59``, squash ``59f402a``, ``main`` red.

    THE THREE ANSWERS, and why the middle one is not the shape that was
    designed on paper:

    * **at least one known ``main`` contains the anchor** -> pass. "At least
      one", not "``origin/main``", is what admits a contributor whose ``origin``
      is a fork that is behind while ``upstream`` is canonical -- with no
      heuristic, because ``upstream/main`` simply answers.
    * **no ``main`` ref at all, but a remote is configured** -> REFUSE. The
      design note this was built from said skip here. Measured afterwards: a
      ``--single-branch --branch <feature>`` clone has no ``main`` ref of any
      kind, so skipping would fail open in the one shape where a branch-only
      anchor is most likely to be typed. It refuses instead, and the message
      names a remedy that was measured to work -- Design A's defect was not
      the refusal, it was printing ``git fetch origin main``, which only writes
      FETCH_HEAD and leaves ``origin/main`` absent.
    * **no ``main`` ref and no remote either** -> skip, out loud. Nothing could
      answer the question and nothing could be fetched; this is a ``git init``
      sandbox. The skip is ignorance, not permission: give that same repository
      a ``main`` and the same anchor is refused at once.

    KNOWN LIMITS, stated rather than hidden. Two of them are false REFUSALS
    and one is a false ACCEPTANCE, and the third is the one worth reading:

    * a ``main`` ref that is behind refuses an anchor that really is on
      ``main``, because a genuine ``main`` commit and a branch commit are both
      just "descendants of the ref" and nothing local separates them.
      ``git fetch`` is the first remedy and does NOT always clear it -- when
      ``origin`` is a fork that is itself behind, fetching it advances nothing.
    * a SHALLOW clone answers "not an ancestor" with exit 1 -- no error -- when
      the graft boundary cuts the link, so a correct anchor is refused. The
      message below says so and names ``git fetch --unshallow``.
    * **a remote whose ``main`` genuinely carries the branch commit is
      believed.** A contributor who pushes their feature onto their own fork's
      ``main`` is accepted here. That is the price of "at least one known
      ``main``" rather than "``origin/main``", which is what admits the
      fork-behind-upstream contributor; the two cannot be separated offline.
      It costs nothing at the merge gate: measured on CI run ``33507457668``,
      a ``pull_request`` build checks out ``refs/remotes/pull/N/merge``
      detached, so ``refs/heads/main`` does not exist there and ``origin`` is
      the canonical repository, not anybody's fork.
    """
    assert board.sha is not None  # guarded by check_all; see anchor_commit_exists
    sha = board.sha
    remotes = remote_names(root)
    if remotes is None:
        return [
            f"{BOARD.name}: `git remote` failed in this checkout, so the remotes "
            "could not be enumerated and the anchor cannot be checked against "
            f"`{MAIN_BRANCH}`. This gate refuses rather than reading that as `no "
            "remotes` -- doing so once accepted a branch-only anchor while "
            "`refs/remotes/origin/main` was on disk. The usual cause is one "
            "invalid refspec in `.git/config`; `git remote` prints which."
        ], ", squash-survival UNANSWERED (git could not list the remotes)"
    refs = _main_refs_for(root, remotes)
    if not refs:
        if not remotes:
            return [], ", squash-survival SKIPPED (no remote and no `main` ref here)"
        return [
            f"{BOARD.name}: this checkout has a remote ({', '.join(remotes)}) but no "
            f"`{MAIN_BRANCH}` ref of any kind, so the anchor cannot be checked against "
            f"`{MAIN_BRANCH}` and this gate will not guess. Measured on git 2.54.0: "
            "`git fetch origin main` does NOT create `refs/remotes/origin/main` here, "
            "it only writes FETCH_HEAD. Run `git remote set-branches --add origin "
            "main && git fetch origin`, or `git fetch origin "
            "main:refs/remotes/origin/main`."
        ], ", squash-survival REFUSED (no `main` ref)"
    unanswered: list[str] = []
    for ref in refs:
        # 0 = ancestor, 1 = not an ancestor, anything else = git could not
        # answer. Collapsing those last two would print "re-stamp your board"
        # at an author whose real problem is a broken invocation.
        code = _git(root, "merge-base", "--is-ancestor", sha, ref).returncode
        if code == 0:
            return [], f", anchor on {ref}"
        if code != 1:
            unanswered.append(f"{ref} (exit {code})")
    if unanswered:
        return [
            f"{BOARD.name}: git could not answer whether anchor commit {sha[:12]} is "
            f"an ancestor of {', '.join(unanswered)}. That is a broken invocation, "
            "not a stale board -- do not re-stamp until it is understood."
        ], ", squash-survival UNANSWERED"
    shallow = (
        " This checkout is SHALLOW: where the graft boundary cuts the link, git answers "
        "`not an ancestor` with exit 1 and no error at all, so run `git fetch --unshallow` "
        "before believing this refusal."
        if _is_shallow(root)
        else ""
    )
    fetchable = ", ".join(remotes) if remotes else "none configured"
    return [
        f"{BOARD.name}: anchor commit {sha[:12]} is not on any `{MAIN_BRANCH}` this "
        f"checkout can see (checked {', '.join(refs)}). This repository SQUASH-merges, "
        "so a commit made on your branch is DISCARDED when the branch lands and the "
        "anchor stops existing at all -- which turns `main` red for everyone after the "
        "merge instead of turning your pull request red before it. Stamp the commit "
        "your branch was cut FROM, or re-stamp after the merge. If you believe the "
        "anchor really is on `main`, those refs may be behind: fetch whichever remote "
        f"carries the canonical `{MAIN_BRANCH}` (configured here: {fetchable}), for "
        "example `git fetch origin main`. A fetch does not always clear this -- when "
        "`origin` is a fork that is itself behind, fetching it advances nothing and "
        f"`git fetch upstream` is what helps.{shallow}"
    ], f", anchor on no known `{MAIN_BRANCH}`"


def check_freshness(board: Board, root: Path, max_drift: int = MAX_DRIFT_COMMITS) -> list[str]:
    """The anchor SHA exists, is behind ``HEAD``, and not by too much."""
    if board.sha is None:
        return [
            f"{BOARD.name} no longer records its anchor commit in the form this "
            f"gate checks ({_SHA_LINE.pattern!r})."
        ]
    if not anchor_commit_exists(root, board.sha):
        return [f"{BOARD.name}: anchor commit {board.sha[:12]} is not in this repository."]
    if _git(root, "merge-base", "--is-ancestor", board.sha, "HEAD").returncode != 0:
        return [
            f"{BOARD.name}: anchor commit {board.sha[:12]} is not an ancestor of "
            "HEAD. Stamp a commit that is on main -- the one your branch was cut "
            "from, or re-stamp after the merge. This repository squash-merges, so "
            "a commit made on your branch is discarded and stops being an ancestor "
            "the moment the branch lands."
        ]
    # No error branch: both revisions were just proved to exist and to be
    # related, so ``rev-list`` cannot fail. An unreachable branch is one no test
    # can prove.
    counted = _git(root, "rev-list", "--count", "--first-parent", f"{board.sha}..HEAD")
    drift = int(counted.stdout.strip())
    if drift > max_drift:
        return [
            f"{BOARD.name}: anchor commit {board.sha[:12]} is {drift} first-parent "
            f"commits behind HEAD (limit {max_drift}). Re-verify every row against "
            "the tree and stamp a NEWER commit that is on main -- not one from your "
            "branch, which a squash merge discards."
        ]
    return []


def check_all(root: Path = ROOT, max_drift: int = MAX_DRIFT_COMMITS) -> tuple[list[str], str]:
    """Run every family. Returns (failures, one-line report of what was counted)."""
    board_path = root / "docs" / "65-open-work.md"
    text = board_path.read_text(encoding="utf-8")
    board = parse_board(text)
    parsed = len(board.rows)
    failures = check_structure(board)
    if failures:
        # Report what was REALLY parsed. Saying "0 rows" over a board with 17
        # well-formed rows and one bad cell is a gate stating a false count of
        # its own measurement.
        return failures, f"{parsed} rows parsed, structure REFUSED"
    failures += check_counts(board)
    states, evidence_failures, read = derive_states(board, root)
    failures += evidence_failures
    # THE POINT OF THE WHOLE SCRIPT. The State column is derived; if the file
    # disagrees with the derivation, the file is wrong -- whether it drifted or
    # somebody typed into it.
    if render(text, states) != text:
        wrong = [
            f"{row.row_id} says {row.state or '(blank)'}, the tree says {states[row.row_id]}"
            for row in board.rows
            if row.row_id in states and row.state != states[row.row_id]
        ]
        failures.append(
            f"{BOARD.name}: the State column disagrees with the tree "
            f"({'; '.join(wrong) if wrong else 'formatting differs'}). "
            "That column is GENERATED -- run `make open-work-write` (or "
            "`python3 scripts/check_open_work.py`) rather than editing it. "
            "No hand marks a row done; the tree does."
        )
    # ANTI-VACUITY FLOOR TWO. The empty-table floor does not imply this one: a
    # board of entirely unpinned rows parses fine and reads nothing off disk.
    if read < MIN_EVIDENCE_CLAIMS:
        failures.append(
            f"{BOARD.name}: only {read} needles were read off disk (floor "
            f"{MIN_EVIDENCE_CLAIMS}). This gate refuses to pass having measured "
            "almost nothing."
        )
    git_note = ""
    if has_git_history(root):
        failures += check_freshness(board, root, max_drift)
        if board.sha is not None and anchor_commit_exists(root, board.sha):
            squash_failures, git_note = check_anchor_is_on_main(board, root)
            failures += squash_failures
        else:
            # No second opinion on an anchor the family above already refused
            # by name; a message about `main` would only bury the real one.
            git_note = ", squash-survival SKIPPED (no anchor commit to check)"
    else:
        git_note = ", freshness SKIPPED (root is not a git working tree)"
    tally = {state: sum(1 for s in states.values() if s == state) for state in (PENDING, DONE)}
    report = (
        f"{parsed} rows ({tally[PENDING]} PENDING, {tally[DONE]} DONE), {read} "
        f"needles read from disk, {sum(1 for r in board.rows if not r.pinned)} "
        f"unpinned{git_note}"
    )
    return failures, report


def write_states(root: Path = ROOT) -> bool:
    """Regenerate the State column. Returns whether the file changed."""
    board_path = root / "docs" / "65-open-work.md"
    text = board_path.read_text(encoding="utf-8")
    states, _failures, _read = derive_states(parse_board(text), root)
    rendered = render(text, states)
    if rendered == text:
        return False
    board_path.write_text(rendered, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the board disagrees with the tree"
    )
    args = parser.parse_args(argv)
    if not args.check:
        changed = write_states()
        print(
            "open-work board: State column "
            + ("rewritten from the tree" if changed else "already agrees with the tree")
        )
        return 0
    failures, report = check_all()
    print(f"open-work board: {report}")
    for failure in failures:
        print(f"  FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
