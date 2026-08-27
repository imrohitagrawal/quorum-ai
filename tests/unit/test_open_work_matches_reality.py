"""The open-work board is CHECKED against the tree, not trusted.

``docs/65-open-work.md`` is the source of truth for what is open here. Every
previous attempt at a status file in this repository rotted:
``docs/00-factory-console.md`` was 64 commits behind its own last touch and 241
behind its content date when that was measured (2026-08-28). Four test files
read it; two of them are real truthfulness gates, and neither asks whether the
work it announces is the work in flight. ``make next`` rewrites it
wholesale (``scripts/factory_next.py`` is an unconditional ``write_text``), so
the words a session hand-writes there do not survive the next session running
the command ``AGENTS.md`` tells it to run.

This file is the difference: the board's claims are read off disk.

GATE CHARTER
------------
WHY THIS EXISTS: hand-written status rots because nothing compares the sentence
to the tree. Measured 2026-08-28: the factory console still announced work from
PR #91 and quoted ``pytest 1342 passed`` against a suite of 3730+, and four open
issues (#383, #382, #380, #379) appeared in no planning document at all. Three
separate files each claimed to be the authoritative phase.

WHAT IT CANNOT SEE: work that lands under a DIFFERENT name than the row's
needle. If streaming ships without the literal ``"stream": True`` in
``providers.py``, W1 stays green while being stale. Three rows carry no needle
at all -- that number is pinned so a fourth cannot be added quietly, but the
gate genuinely checks nothing about them. It also cannot judge whether a row
SHOULD exist; a missing row is invisible to it.

FALSE-POSITIVE COST: low but not zero. A needle is a substring of a real source
line, so an unrelated refactor that reformats that line turns this red. That is
the intended trade: it forces a human to look at the board, which is the whole
point. The alternative -- a needle loose enough never to fire -- checks nothing.

WHEN TO REMOVE: when the board's rows are derived from something with its own
tooling (an issue tracker mirrored into the repo, a generated register). Not
before: the failure it guards -- a status document drifting silently while
gates watch it -- has already happened here at least twice.

Bite-proofs below drive the checker's own functions with mutated input rather
than editing the real board, the same shape ``tests/test_doc_gate_consistency.py``
Part D uses.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.subprocess_env import env_without_coverage

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_open_work.py"
MAKEFILE = ROOT / "Makefile"
#: Assembled from segments so no ADDED LINE here is a repo-path-shaped literal
#: pointing into a temporary sandbox -- ``tests/unit/test_cited_paths_resolve.py``
#: cannot tell a fixture path from a citation, and rightly fails on one that
#: does not resolve.
_DOCS = "docs"
_BOARD_NAME = "65-open-work.md"
_TARGET_NAME = "target.txt"


def _load_script() -> Any:
    """Load the checker by path, never as ``scripts.check_open_work``.

    ``make type-check`` runs ``mypy src tests`` and follows static imports, so a
    package import would drag an unchecked file into a strict-mode gate. Same
    loader idiom as ``tests/unit/test_adr_index_matches_directory.py`` and
    ``tests/unit/test_session_hygiene.py``. Registration in ``sys.modules`` is
    required before execution because the module defines dataclasses, whose
    string annotations resolve through ``sys.modules``.
    """
    spec = importlib.util.spec_from_file_location("check_open_work", SCRIPT)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


CHECKER = _load_script()


def _board_text(rows: str, *, row_count: int, unpinned: int, sha: str = "0" * 40) -> str:
    """The minimum board shape the checker parses, with a caller-chosen table."""
    return (
        "# fixture board\n\n"
        f"Verified at: `{sha}`\n\n"
        f"The board holds **{row_count}** rows, **{unpinned}** of them unpinned.\n\n"
        "| ID | Item | State | Evidence | Issue | Depends on |\n"
        "|----|------|-------|----------|-------|------------|\n"
        f"{rows}"
    )


def _sandbox(tmp_path: Path, *, board: str, target: str = "nothing here") -> Path:
    """A root the checker can be pointed at: a board plus one target file."""
    (tmp_path / _DOCS).mkdir(parents=True)
    (tmp_path / _DOCS / _BOARD_NAME).write_text(board, encoding="utf-8")
    (tmp_path / _TARGET_NAME).write_text(target, encoding="utf-8")
    return tmp_path


def _content_failures(tmp_path: Path, *, board: str, target: str = "nothing here") -> list[str]:
    """Every non-git check, run over a sandbox root."""
    root = _sandbox(tmp_path, board=board, target=target)
    parsed = CHECKER.parse_board((root / _DOCS / _BOARD_NAME).read_text(encoding="utf-8"))
    failures: list[str] = CHECKER.check_structure(parsed)
    if failures:
        return failures
    failures += CHECKER.check_counts(parsed)
    evidence_failures, _checked = CHECKER.check_evidence(parsed, root)
    more: list[str] = list(evidence_failures)
    return failures + more


# ---------------------------------------------------------------------------
# The live gate.
# ---------------------------------------------------------------------------


def test_the_real_board_matches_the_real_tree() -> None:
    """Turns red if: any row's evidence claim stops being true.

    A ``PENDING`` row whose needle APPEARS turns this red -- that is the design.
    Finishing the work is what fires the gate, so the row cannot be left saying
    the work is open. A ``DONE`` row whose needle has gone turns it red too, so
    a row cannot be marked done over nothing.
    """
    failures, report = CHECKER.check_all(ROOT)
    assert not failures, "docs board disagrees with the tree:\n  " + "\n  ".join(failures)
    # POSITIVE PARTNER. Every assertion above is "no failures", trivially true
    # over an unparsed file. This pins that the run actually read something.
    parsed = CHECKER.parse_board(CHECKER.BOARD.read_text(encoding="utf-8"))
    assert len(parsed.rows) >= 10, f"only {len(parsed.rows)} rows parsed: {report}"
    pinned = [row for row in parsed.rows if row.pinned]
    assert len(pinned) >= 10, f"only {len(pinned)} rows carry a checkable needle"


def test_the_checker_exits_non_zero_on_a_bad_board(tmp_path: Path) -> None:
    """Turns red if: ``--check`` stops reporting failure through its exit code.

    Driven as a subprocess because the exit code is what ``make validate`` reads,
    and a function returning 1 that ``main`` never propagates would satisfy every
    other test in this file.
    """
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert ok.returncode == 0, f"the real board should pass:\n{ok.stdout}\n{ok.stderr}"
    assert "rows" in ok.stdout, f"the gate must report what it counted; got {ok.stdout!r}"

    broken = _sandbox(
        tmp_path,
        board=_board_text("| W1 | x | PENDING | `—` | — | — |\n", row_count=99, unpinned=1),
    )
    (broken / "scripts").mkdir()
    (broken / "scripts" / SCRIPT.name).write_bytes(SCRIPT.read_bytes())
    bad = subprocess.run(
        [sys.executable, str(broken / "scripts" / SCRIPT.name), "--check"],
        cwd=broken,
        capture_output=True,
        text=True,
        # A Python child at a cwd OUTSIDE this repository inherits pytest-cov's
        # subprocess hooks, resolves the relative ``--cov=src`` against the
        # sandbox, and records that tree at 0% into the shared coverage data --
        # inflating the denominator of a REQUIRED gate (#368).
        env=env_without_coverage(),
    )
    assert bad.returncode == 1, f"a wrong count must exit 1; got {bad.returncode}\n{bad.stderr}"
    assert "says 99 rows" in bad.stderr


# ---------------------------------------------------------------------------
# Bite-proofs: evidence polarity.
# ---------------------------------------------------------------------------


def test_a_pending_row_goes_red_once_its_needle_appears(tmp_path: Path) -> None:
    """Turns red if: ``check_evidence`` stops enforcing ``ABSENT``.

    This is the inverted assertion the board is built on. Without it the board
    would stay green through every delivery and only complain about abandonment.
    """
    row = f"| W1 | x | PENDING | `ABSENT {_TARGET_NAME} :: needle` | — | — |\n"
    clean = _content_failures(tmp_path / "a", board=_board_text(row, row_count=1, unpinned=0))
    assert clean == [], f"an absent needle must pass: {clean}"

    landed = _content_failures(
        tmp_path / "b",
        board=_board_text(row, row_count=1, unpinned=0),
        target="the work landed and wrote needle into the file",
    )
    assert len(landed) == 1, landed
    assert "is ABSENT" in landed[0] and "it is there" in landed[0]


def test_a_done_row_goes_red_when_its_needle_is_missing(tmp_path: Path) -> None:
    """Turns red if: ``check_evidence`` stops enforcing ``PRESENT``.

    Without this half, a row could be marked ``DONE`` over nothing at all.
    """
    row = f"| W1 | x | DONE | `PRESENT {_TARGET_NAME} :: needle` | — | — |\n"
    ok = _content_failures(
        tmp_path / "a",
        board=_board_text(row, row_count=1, unpinned=0),
        target="needle is here",
    )
    assert ok == [], f"a present needle must pass: {ok}"

    lying = _content_failures(tmp_path / "b", board=_board_text(row, row_count=1, unpinned=0))
    assert len(lying) == 1, lying
    assert "is PRESENT" in lying[0] and "it is gone" in lying[0]


def test_an_evidence_path_that_does_not_exist_is_caught(tmp_path: Path) -> None:
    """Turns red if: a needle against a missing file is treated as satisfied.

    A gate that read a nonexistent file as "needle absent" would mark every
    ``ABSENT`` row green forever by deleting one character of the path.
    """
    row = "| W1 | x | PENDING | `ABSENT no_such_file.txt :: needle` | — | — |\n"
    failures = _content_failures(tmp_path, board=_board_text(row, row_count=1, unpinned=0))
    assert len(failures) == 1, failures
    assert "does not exist" in failures[0]


def test_a_needle_containing_a_backtick_is_refused(tmp_path: Path) -> None:
    """Turns red if: a needle may contain a backtick.

    ``_cell`` strips only the OUTER backtick pair, so an interior one survives
    into the needle. The gate would then check a string the rendered markdown
    does not show, which is the one thing a board must never do: display one
    claim and verify another.
    """
    row = "| W1 | x | PENDING | `ABSENT " + _TARGET_NAME + " :: nee`dle` | — | — |\n"
    failures = _content_failures(tmp_path, board=_board_text(row, row_count=1, unpinned=0))
    assert len(failures) == 1, failures
    assert "contains a backtick" in failures[0]


def test_a_malformed_evidence_cell_is_caught(tmp_path: Path) -> None:
    """Turns red if: an unparseable evidence cell is silently skipped."""
    row = "| W1 | x | PENDING | `something else entirely` | — | — |\n"
    failures = _content_failures(tmp_path, board=_board_text(row, row_count=1, unpinned=0))
    assert len(failures) == 1, failures
    assert "is neither" in failures[0]


# ---------------------------------------------------------------------------
# Bite-proofs: the count pins and the anti-vacuity floor.
# ---------------------------------------------------------------------------


def test_a_wrong_row_count_is_caught(tmp_path: Path) -> None:
    """Turns red if: the stated row count stops being compared to the table."""
    row = "| W1 | x | PENDING | `—` | — | — |\n"
    failures = _content_failures(tmp_path, board=_board_text(row, row_count=2, unpinned=1))
    assert len(failures) == 1, failures
    assert "says 2 rows" in failures[0] and "has 1" in failures[0]


def test_a_wrong_unpinned_count_is_caught(tmp_path: Path) -> None:
    """Turns red if: an unpinned row can be added without editing the sentence.

    The unpinned count is the cap on how much of the board this gate is blind
    to. Unchecked, a future session could unpin every row and stay green.
    """
    row = "| W1 | x | PENDING | `—` | — | — |\n"
    failures = _content_failures(tmp_path, board=_board_text(row, row_count=1, unpinned=0))
    assert len(failures) == 1, failures
    assert "says 0 unpinned rows" in failures[0] and "has 1" in failures[0]


def test_a_deleted_count_sentence_is_caught(tmp_path: Path) -> None:
    """Turns red if: removing the sentence removes the check with it."""
    board = _board_text("| W1 | x | PENDING | `—` | — | — |\n", row_count=1, unpinned=1)
    board = board.replace("The board holds **1** rows, **1** of them unpinned.", "gone")
    failures = _content_failures(tmp_path, board=board)
    assert len(failures) == 1, failures
    assert "no longer states its counts" in failures[0]


def test_the_gate_refuses_to_pass_over_an_empty_table(tmp_path: Path) -> None:
    """Turns red if: the anti-vacuity floor is removed.

    Every other check here is a loop over rows and every one of them is
    satisfied by zero rows. A moved heading or a broken row pattern would
    otherwise leave this gate reporting success while measuring nothing --
    the exact failure mode most of this repo's gates were built after.
    """
    failures = _content_failures(tmp_path, board=_board_text("", row_count=0, unpinned=0))
    assert len(failures) == 1, failures
    assert "refuses to pass over an empty input" in failures[0]


def test_an_unknown_state_is_caught(tmp_path: Path) -> None:
    """Turns red if: any word can be written in the State column."""
    row = "| W1 | x | MOSTLY | `—` | — | — |\n"
    failures = _content_failures(tmp_path, board=_board_text(row, row_count=1, unpinned=1))
    assert len(failures) == 1, failures
    assert "is not one of" in failures[0]


def test_a_duplicate_row_id_is_caught(tmp_path: Path) -> None:
    """Turns red if: two rows can share an id, making one of them unreferenceable."""
    rows = "| W1 | x | PENDING | `—` | — | — |\n| W1 | y | PENDING | `—` | — | — |\n"
    failures = _content_failures(tmp_path, board=_board_text(rows, row_count=2, unpinned=2))
    assert len(failures) == 1, failures
    assert "duplicate row id" in failures[0]


# ---------------------------------------------------------------------------
# Bite-proofs: freshness. Driven against the REAL repository, because the whole
# check is about this history.
# ---------------------------------------------------------------------------


def _board_at(sha: str | None) -> Any:
    return CHECKER.Board(sha=sha, stated_rows=1, stated_unpinned=0, rows=[])


def _head_ancestor(distance: int) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"HEAD~{distance}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_a_current_anchor_passes_and_a_stale_one_does_not() -> None:
    """Turns red if: the drift limit stops being enforced.

    Both directions in one test on purpose: a limit that never fires and a
    limit that always fires are equally useless, and only the pair distinguishes
    them.
    """
    five_back = _head_ancestor(5)
    assert CHECKER.check_freshness(_board_at(five_back), ROOT, 10) == [], (
        "an anchor 5 commits back must pass a limit of 10"
    )
    stale = CHECKER.check_freshness(_board_at(five_back), ROOT, 2)
    assert len(stale) == 1, stale
    assert "first-parent commits behind HEAD" in stale[0]


def _sandbox_repo(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway repo whose HEAD has one commit, plus an ORPHAN commit's SHA.

    Built rather than borrowed from this repository: the first attempt at this
    test used the empty-tree object, which ``git cat-file -e <sha>^{commit}``
    rejects one check EARLIER -- so deleting the ancestor check entirely left
    the test green. The mutation survived and the test was named for something
    it did not exercise. Only a real commit on a disjoint history reaches the
    ancestor check at all.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "--quiet", "-b", "main")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    git("add", "a.txt")
    git("commit", "--quiet", "-m", "on main")
    git("checkout", "--quiet", "--orphan", "sidetrack")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    git("add", "b.txt")
    git("commit", "--quiet", "-m", "disjoint history")
    orphan = git("rev-parse", "HEAD")
    git("checkout", "--quiet", "main")
    return repo, orphan


def test_an_anchor_that_is_not_an_ancestor_is_caught(tmp_path: Path) -> None:
    """Turns red if: a real commit from some other history is accepted.

    Without the ancestor check the drift count is computed against a commit this
    branch never contained. ``git rev-list --count A..HEAD`` answers that
    happily -- it reports everything reachable from HEAD and not from A, which
    across disjoint histories is the whole branch, so a board anchored to a
    stranger's commit would fail LOUDLY at some arbitrary later date instead of
    immediately, or pass forever on a short history.
    """
    repo, orphan = _sandbox_repo(tmp_path)
    # POSITIVE PARTNER. The sandbox's own HEAD must pass, or "rejected" below
    # would be indistinguishable from "this checker rejects every sandbox".
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert CHECKER.check_freshness(_board_at(head), repo, 10) == []

    failures = CHECKER.check_freshness(_board_at(orphan), repo, 10)
    assert len(failures) == 1, failures
    assert "is not an ancestor of" in failures[0]


def test_an_anchor_that_names_a_non_commit_object_is_caught() -> None:
    """Turns red if: a tree or blob SHA is accepted as the anchor.

    The empty tree exists in every git repository, so this is stable across
    clones. It is a DIFFERENT check from the ancestor one above -- see that
    test's docstring for why conflating the two hid a surviving mutant.
    """
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    failures = CHECKER.check_freshness(_board_at(empty_tree), ROOT, 10)
    assert len(failures) == 1, failures
    assert "not in this repository" in failures[0]


def test_an_anchor_that_is_not_a_commit_at_all_is_caught() -> None:
    """Turns red if: a SHA-shaped string that names nothing is accepted."""
    failures = CHECKER.check_freshness(_board_at("f" * 40), ROOT, 10)
    assert len(failures) == 1, failures
    assert "not in this repository" in failures[0]


def test_an_abbreviated_anchor_is_not_parsed_as_one() -> None:
    """Turns red if: the anchor pattern stops demanding a full 40-hex SHA.

    An abbreviation resolves today and becomes ambiguous as the object store
    grows, and the failure then reads as "anchor not in this repository" on a
    board nobody changed. The anchor is stamped by a machine; there is no reason
    to accept a short one.
    """
    full = "0" * 40
    parsed_full = CHECKER.parse_board(f"Verified at: `{full}`\n")
    assert parsed_full.sha == full, "the full-length form must still parse"

    parsed_short = CHECKER.parse_board("Verified at: `0000000`\n")
    assert parsed_short.sha is None, "an abbreviated SHA must not be accepted"


def test_a_missing_anchor_line_is_caught() -> None:
    """Turns red if: deleting the ``Verified at:`` line disables the freshness check."""
    failures = CHECKER.check_freshness(_board_at(None), ROOT, 10)
    assert len(failures) == 1, failures
    assert "no longer records its anchor commit" in failures[0]


# ---------------------------------------------------------------------------
# The wiring. A gate nothing invokes is not a gate.
# ---------------------------------------------------------------------------


def test_the_gate_is_wired_into_make_validate() -> None:
    """Turns red if: the target is dropped from ``validate``'s prerequisites.

    ``docs/00-factory-console.md`` had four gates reading it and none that asked
    whether the work it announced was the work in flight, which is how a status
    file goes 64 commits stale while every check reports green. This asserts the
    invocation exists, not merely that the recipe is written down somewhere.
    """
    makefile = MAKEFILE.read_text(encoding="utf-8")
    prerequisites = [line for line in makefile.splitlines() if line.startswith("validate:")]
    assert len(prerequisites) == 1, f"expected one validate: line, found {prerequisites}"
    assert "open-work-check" in prerequisites[0], (
        "make validate no longer depends on open-work-check: " + prerequisites[0]
    )
    recipe = [line for line in makefile.splitlines() if line.startswith("open-work-check:")]
    assert len(recipe) == 1, f"expected one open-work-check: recipe, found {recipe}"
    assert "check_open_work.py" in makefile, "the target no longer runs the checker"


@pytest.mark.parametrize("doc", ["docs/session-handoff.md", "docs/00-factory-console.md"])
def test_the_board_is_reachable_from_the_docs_a_session_must_read(doc: str) -> None:
    """Turns red if: a mandatory-reading document stops pointing at the board.

    ``AGENTS.md`` names ``docs/00-factory-console.md`` and
    ``docs/session-handoff.md`` as required reading for a new session. A board
    nothing links to is the fifth uncoordinated plan, not a replacement for the
    other four.
    """
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert _BOARD_NAME in text, f"{doc} does not link to the open-work board"
