"""The open-work board is CHECKED against the tree, not trusted.

``docs/65-open-work.md`` is the source of truth for what is open here. Every
previous attempt at a status file in this repository rotted:
``docs/00-factory-console.md`` was 64 first-parent commits behind its own last
touch, and 241 commits behind its content date of 2026-07-23 (188 counting only
first-parent), when that was measured on 2026-08-28. Four test files read it;
two of them are real truthfulness gates, and neither asks whether the work it
announces is the work in flight. ``make next`` rewrites it
wholesale (``scripts/factory_next.py`` is an unconditional ``write_text``), so
the words a session hand-writes there do not survive the next session running
the command ``AGENTS.md`` tells it to run.

This file is the difference: the board's claims are read off disk.

GATE CHARTER
------------
WHY THIS EXISTS: hand-written status rots because nothing compares the sentence
to the tree. Measured 2026-08-28: the factory console still announced work from
PR #91 and quoted ``pytest 1342 passed`` against a suite collecting 3819, and
four open issues (#383, #382, #380, #379) appeared in no planning document at
all. Work was planned across five documents that did not reference each other.

WHAT IT CANNOT SEE: work that lands under a DIFFERENT name than the row's
needle -- if streaming ships without the literal ``"stream": True`` in
``providers.py``, W1 stays satisfiable while being stale; and work that lands by
a different ROUTE under the same name -- W15 is pinned on ``_bound_sniff_time``
being present-and-undefined, so deleting the dangling references flips it but
*defining* the function would not. Four rows carry no needle at all; that number
is pinned so a fifth cannot be added quietly, but the gate genuinely checks
nothing about them. It also cannot judge whether a row SHOULD exist.

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


def test_a_pending_row_goes_red_once_its_claim_stops_holding(tmp_path: Path) -> None:
    """Turns red if: ``check_evidence`` stops enforcing a PENDING row's claim.

    This is the inverted assertion the board is built on. Without it the board
    would stay green through every delivery and only complain about abandonment.
    """
    row = f"| W1 | x | PENDING | `ABSENT {_TARGET_NAME} :: needle-that-is-long` | — | — |\n"
    clean = _content_failures(tmp_path / "a", board=_board_text(row, row_count=1, unpinned=0))
    assert clean == [], f"an absent needle must pass while PENDING: {clean}"

    landed = _content_failures(
        tmp_path / "b",
        board=_board_text(row, row_count=1, unpinned=0),
        target="the work landed and wrote needle-that-is-long into the file",
    )
    assert len(landed) == 1, landed
    assert "is PENDING and claims" in landed[0]
    assert "change the STATE cell to DONE" in landed[0]


def test_flipping_only_the_state_word_turns_the_gate_red(tmp_path: Path) -> None:
    """Turns red if: the State cell stops being coupled to the evidence polarity.

    THE DEFECT THIS CLOSES, demonstrated by adversarial review on this very
    diff. In the first draft, polarity came only from the word the author typed
    in the Evidence cell, so replacing every ``| PENDING |`` on the real board
    with ``| DONE |`` -- changing nothing under ``src/`` -- left the gate green
    and printing "0 PENDING". The board, ADR-0079 and this file's own docstring
    all asserted that could not happen.

    Both directions, because a rule that always fires is as useless as one that
    never does: the PENDING row passes on an unlanded needle, and the SAME row
    with only the state word changed fails.
    """
    evidence = f"`ABSENT {_TARGET_NAME} :: needle-that-is-long`"
    pending = f"| W1 | x | PENDING | {evidence} | — | — |\n"
    done = f"| W1 | x | DONE | {evidence} | — | — |\n"

    ok = _content_failures(tmp_path / "a", board=_board_text(pending, row_count=1, unpinned=0))
    assert ok == [], f"the PENDING row must pass on an unlanded needle: {ok}"

    lying = _content_failures(tmp_path / "b", board=_board_text(done, row_count=1, unpinned=0))
    assert len(lying) == 1, lying
    assert "is DONE, so the gate requires the OPPOSITE" in lying[0]

    # ...and the DONE row passes once the work has actually landed.
    honest = _content_failures(
        tmp_path / "c",
        board=_board_text(done, row_count=1, unpinned=0),
        target="needle-that-is-long is here now",
    )
    assert honest == [], f"a DONE row whose work landed must pass: {honest}"


def test_a_done_row_pinned_on_a_present_line_requires_that_line_to_be_gone(
    tmp_path: Path,
) -> None:
    """Turns red if: the inversion is applied in only one direction.

    Most rows here are pinned on a defect that is PRESENT while the work is
    open (W2, W3, W10, W11, W12, W16, W17). For those, DONE must require the
    line to have GONE. The previous test covers the ABSENT-while-open shape;
    this covers the other one, and a one-directional inversion passes that test
    and fails this one.
    """
    row = f"| W1 | x | DONE | `PRESENT {_TARGET_NAME} :: needle-that-is-long` | — | — |\n"
    still_there = _content_failures(
        tmp_path / "a",
        board=_board_text(row, row_count=1, unpinned=0),
        target="needle-that-is-long is still here",
    )
    assert len(still_there) == 1, still_there
    assert "requires the OPPOSITE" in still_there[0]

    gone = _content_failures(tmp_path / "b", board=_board_text(row, row_count=1, unpinned=0))
    assert gone == [], f"a DONE row whose defect line is gone must pass: {gone}"


def test_a_needle_too_short_to_be_evidence_is_refused(tmp_path: Path) -> None:
    """Turns red if: a needle a COMMENT could satisfy is accepted.

    W7's first needle was the bare word ``google``. Adversarial review satisfied
    it by appending the comment "google sign-in is still TODO" to ``auth.py`` --
    the row would have gone green on prose saying the work was NOT done.
    """
    short = f"| W1 | x | PENDING | `ABSENT {_TARGET_NAME} :: google` | — | — |\n"
    failures = _content_failures(tmp_path / "a", board=_board_text(short, row_count=1, unpinned=0))
    assert len(failures) == 1, failures
    assert "is shorter than" in failures[0]

    # POSITIVE PARTNER: a needle one character over the floor is accepted, so
    # this is a boundary and not a blanket refusal.
    long_enough = "x" * CHECKER.MIN_NEEDLE_CHARS
    ok_row = f"| W1 | x | PENDING | `ABSENT {_TARGET_NAME} :: {long_enough}` | — | — |\n"
    ok_board = _board_text(ok_row, row_count=1, unpinned=0)
    assert _content_failures(tmp_path / "b", board=ok_board) == []


def test_an_evidence_path_that_does_not_exist_is_caught(tmp_path: Path) -> None:
    """Turns red if: a needle against a missing file is treated as satisfied.

    A gate that read a nonexistent file as "needle absent" would mark every
    ``ABSENT`` row green forever by deleting one character of the path.
    """
    row = "| W1 | x | PENDING | `ABSENT no_such_file.txt :: needle-that-is-long` | — | — |\n"
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
    row = "| W1 | x | PENDING | `ABSENT " + _TARGET_NAME + " :: nee`dle-that-is-long` | — | — |\n"
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
    lines = makefile.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("open-work-check:")]
    assert len(starts) == 1, f"expected one open-work-check: recipe, found {starts}"
    # THE RECIPE BODY, not the whole file. `"check_open_work.py" in makefile`
    # was the first version of this assertion and it was worthless: review
    # replaced the recipe with `@true`, left the script name in an adjacent
    # comment, and every test here stayed green while `make open-work-check`
    # checked nothing. A make recipe is the tab-indented run of lines directly
    # under its target.
    body = []
    for line in lines[starts[0] + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    assert body, "open-work-check has an empty recipe -- it would do nothing"
    assert any("check_open_work.py" in line for line in body), (
        "the open-work-check RECIPE no longer runs the checker; it is: " + repr(body)
    )


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


# ---------------------------------------------------------------------------
# The integrated path. Every bite-proof above drives check_structure /
# check_counts / check_evidence directly, so the wiring INSIDE check_all -- the
# function `make validate` actually reaches -- was exercised by nothing that
# could fail. Review demonstrated it: the whole evidence family could be
# deleted from check_all and all bite-proofs stayed green.
# ---------------------------------------------------------------------------


def _integrated(tmp_path: Path, *, board: str, target: str) -> tuple[list[str], str]:
    root = _sandbox(tmp_path, board=board, target=target)
    failures, report = CHECKER.check_all(root, 10**9)
    return list(failures), str(report)


def test_check_all_actually_runs_the_evidence_family(tmp_path: Path) -> None:
    """Turns red if: check_all stops calling check_evidence.

    Both directions over the SAME board, so a check_all that always passes and
    one that always fails are each caught. The evidence floor is stubbed out of
    the way by using enough pinned rows to clear it.
    """
    rows = "".join(
        f"| W{i} | x | PENDING | `ABSENT {_TARGET_NAME} :: needle-that-is-long` | — | — |\n"
        for i in range(1, CHECKER.MIN_EVIDENCE_CLAIMS + 1)
    )
    board = _board_text(rows, row_count=CHECKER.MIN_EVIDENCE_CLAIMS, unpinned=0)

    failures, report = _integrated(tmp_path / "a", board=board, target="nothing here")
    assert failures == [], f"check_all must pass a true board: {failures}"
    assert f"{CHECKER.MIN_EVIDENCE_CLAIMS} evidence claims read from disk" in report

    landed, _ = _integrated(tmp_path / "b", board=board, target="needle-that-is-long landed")
    assert len(landed) == CHECKER.MIN_EVIDENCE_CLAIMS, landed
    assert all("is PENDING and claims" in f for f in landed)


def test_check_all_refuses_a_board_that_pins_nothing(tmp_path: Path) -> None:
    """Turns red if: the evidence floor is removed.

    The empty-TABLE floor does not imply this one, and review proved it: a board
    of entirely unpinned rows parses fine, satisfies every other check, and
    exits 0 having read zero claims off disk. `make validate` would report a
    green gate that measured nothing -- the failure mode most of this repo's
    floors were built after.
    """
    rows = "".join(f"| W{i} | x | PENDING | `—` | — | — |\n" for i in range(1, 4))
    board = _board_text(rows, row_count=3, unpinned=3)
    failures, report = _integrated(tmp_path, board=board, target="nothing here")
    assert len(failures) == 1, failures
    assert "only 0 evidence claims were read off disk" in failures[0]
    assert "0 evidence claims read from disk" in report


def test_check_all_reports_the_rows_it_really_parsed_on_a_structure_failure(
    tmp_path: Path,
) -> None:
    """Turns red if: the report line goes back to claiming 0 rows.

    A board with three well-formed rows and one bad state cell printed
    "0 rows parsed" -- a gate stating a false count of its own measurement, in a
    repository whose rule is that every gate reports what it counted.
    """
    rows = (
        "| W1 | x | PENDING | `—` | — | — |\n"
        "| W2 | x | MOSTLY | `—` | — | — |\n"
        "| W3 | x | PENDING | `—` | — | — |\n"
    )
    failures, report = _integrated(
        tmp_path, board=_board_text(rows, row_count=3, unpinned=3), target="x"
    )
    assert failures, "a bad state cell must fail"
    assert report.startswith("3 rows parsed"), report


def test_the_shipped_drift_limit_is_the_one_that_runs(tmp_path: Path) -> None:
    """Turns red if: MAX_DRIFT_COMMITS stops being check_all's default.

    Every freshness bite-proof injects its own limit, so the value the gate
    actually ships with was pinned by nothing: raising it to a billion disabled
    the stale half of the gate with every test still green.
    """
    assert CHECKER.MAX_DRIFT_COMMITS == 60, (
        "the drift limit moved. That is allowed, but ADR-0079 derives 60 from a "
        "measured ~3.4 first-parent commits a day; re-derive it there in the "
        "same change rather than editing this number alone."
    )
    # And it must be what check_all uses when no limit is passed.
    import inspect

    signature = inspect.signature(CHECKER.check_all)
    assert signature.parameters["max_drift"].default == CHECKER.MAX_DRIFT_COMMITS


def test_a_needle_ending_in_a_backtick_is_refused_not_silently_truncated(
    tmp_path: Path,
) -> None:
    """Turns red if: _cell goes back to stripping a RUN of backticks.

    ``str.strip("`")`` removes every trailing backtick, so a needle whose last
    character was one had it deleted before the refusal could see it -- and the
    gate then verified a shorter string than the row displayed. The interior
    case above does not cover this; only a TRAILING one reaches the strip.
    """
    row = "| W1 | x | PENDING | `ABSENT " + _TARGET_NAME + " :: needle-long`` | — | — |\n"
    parsed = CHECKER.parse_board(_board_text(row, row_count=1, unpinned=0))
    assert parsed.rows[0].evidence.endswith("`"), (
        "the trailing backtick was stripped away before the refusal could see it: "
        + repr(parsed.rows[0].evidence)
    )
    failures = _content_failures(tmp_path, board=_board_text(row, row_count=1, unpinned=0))
    assert len(failures) == 1, failures
    assert "contains a backtick" in failures[0]


def test_freshness_is_skipped_out_loud_where_there_is_no_git_history(
    tmp_path: Path,
) -> None:
    """Turns red if: a tree with no git history either hard-fails or skips silently.

    AGENTS.md rule 12b tells a reviewer to work from a ``git archive`` copy,
    which has no ``.git`` at all, and rule 9a records what a phantom failure
    costs: a session investigating a diff that was never the cause. So the
    freshness family is skipped there -- and the report line SAYS SO, because a
    silent skip is the vacuity this repo's floors exist to prevent.
    """
    rows = "".join(
        f"| W{i} | x | PENDING | `ABSENT {_TARGET_NAME} :: needle-that-is-long` | — | — |\n"
        for i in range(1, CHECKER.MIN_EVIDENCE_CLAIMS + 1)
    )
    board = _board_text(rows, row_count=CHECKER.MIN_EVIDENCE_CLAIMS, unpinned=0)
    root = _sandbox(tmp_path / "nogit", board=board, target="nothing here")
    assert not CHECKER.has_git_history(root)
    failures, report = CHECKER.check_all(root, 10)
    assert failures == [], failures
    assert "freshness SKIPPED" in report, report

    # POSITIVE PARTNER. In a REAL repository the family is not skipped, and its
    # note is absent -- otherwise "skipped" could be the only path this gate
    # ever takes and nothing here would notice.
    assert CHECKER.has_git_history(ROOT)
    _real_failures, real_report = CHECKER.check_all(ROOT)
    assert "freshness SKIPPED" not in real_report, real_report


def test_check_all_actually_runs_the_freshness_family(tmp_path: Path) -> None:
    """Turns red if: check_all stops calling check_freshness.

    Every freshness bite-proof drives ``check_freshness`` directly, so the call
    from ``check_all`` -- the one ``make validate`` reaches -- was pinned by
    nothing: replacing it with ``pass`` left all 30 tests green. This is the
    same wiring gap review found on the evidence family, in the other function.

    Both directions over one sandbox repository: a current anchor passes, and
    the SAME board with a stale anchor fails through ``check_all``.
    """
    repo, _orphan = _sandbox_repo(tmp_path)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    first = git("rev-parse", "HEAD")
    for n in range(3):
        (repo / f"c{n}.txt").write_text(str(n), encoding="utf-8")
        git("add", f"c{n}.txt")
        git("commit", "--quiet", "-m", f"c{n}")
    head = git("rev-parse", "HEAD")

    rows = "".join(
        f"| W{i} | x | PENDING | `ABSENT {_TARGET_NAME} :: needle-that-is-long` | — | — |\n"
        for i in range(1, CHECKER.MIN_EVIDENCE_CLAIMS + 1)
    )
    (repo / _DOCS).mkdir(parents=True, exist_ok=True)
    (repo / _TARGET_NAME).write_text("nothing here", encoding="utf-8")

    def run_with(sha: str, limit: int) -> tuple[list[str], str]:
        (repo / _DOCS / _BOARD_NAME).write_text(
            _board_text(rows, row_count=CHECKER.MIN_EVIDENCE_CLAIMS, unpinned=0, sha=sha),
            encoding="utf-8",
        )
        failures, report = CHECKER.check_all(repo, limit)
        return list(failures), str(report)

    current, report = run_with(head, 10)
    assert current == [], f"an anchor at HEAD must pass: {current}"
    assert "freshness SKIPPED" not in report, report

    stale, _ = run_with(first, 1)
    assert len(stale) == 1, stale
    assert "first-parent commits behind HEAD" in stale[0]


def test_check_evidence_survives_an_unknown_state_instead_of_crashing(tmp_path: Path) -> None:
    """Turns red if: check_evidence indexes _STATES without guarding the key.

    ``check_all`` returns early when ``check_structure`` rejects a state, so
    this branch is unreachable through the CLI -- which is exactly why nothing
    proved it. But ``check_evidence`` is called directly by the bite-proofs in
    this file, and a future caller can do the same. Unguarded, a bad state cell
    raises ``KeyError`` instead of being reported: a gate that crashes and a
    gate that fails look different to a CI log, and only one of them names the
    problem.
    """
    row = f"| W1 | x | MOSTLY | `ABSENT {_TARGET_NAME} :: needle-that-is-long` | — | — |\n"
    root = _sandbox(tmp_path, board=_board_text(row, row_count=1, unpinned=0))
    parsed = CHECKER.parse_board((root / _DOCS / _BOARD_NAME).read_text(encoding="utf-8"))
    failures, checked = CHECKER.check_evidence(parsed, root)
    assert failures == [], failures
    assert checked == 0, "a row whose state is unknown must not be counted as measured"

    # POSITIVE PARTNER: the same row with a KNOWN state IS measured, so
    # "skipped" cannot be the only path this function ever takes.
    good = row.replace("MOSTLY", "PENDING")
    good_root = _sandbox(tmp_path / "ok", board=_board_text(good, row_count=1, unpinned=0))
    good_parsed = CHECKER.parse_board((good_root / _DOCS / _BOARD_NAME).read_text(encoding="utf-8"))
    _f, good_checked = CHECKER.check_evidence(good_parsed, good_root)
    assert good_checked == 1
