"""A new PRESENT row must name a commit where its needle was in the file (ADR-0162, decision 4).

The hole this closes (claim I4 of the 2026-10-11 review): a ``PRESENT`` needle
states the OPEN form of a fact, so a needle that was never in the file reads
"absent" and derives DONE at once. A made-up needle was a DONE for free.

The new form is ``PRESENT@<sha> <path> :: <needle>``: the commit must be on
``main`` and the needle must be in the file AT that commit. A plain ``PRESENT``
is allowed only for the ten rows that used it on 2026-10-11.

Each case runs ``check_all`` over a small git repository built here, with a
literal board. Eight ``ABSENT`` filler rows clear the checker's floor on needles
read, so the row under test is the only thing that varies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.repo_root import find_repo_root
from tests.status_clone import git, git_out, load_script, rel

ROOT = find_repo_root(Path(__file__))
CHECKER: Any = load_script(ROOT, "check_open_work")

NEEDLE = "def the_needle_under_test("
TARGET = "target.txt"
#: The ten rows ADR-0162 lets keep a plain PRESENT. Literal, not read from the checker.
GRANDFATHERED = ("W3", "W10", "W15", "W16", "W17", "W18", "W22", "W28", "W37", "W47")
#: Not one of the ten.
NEW_ROW = "W60"


def _commit(repo: Path, text: str, message: str) -> str:
    (repo / TARGET).write_text(text, encoding="utf-8")
    git(repo, "add", TARGET)
    git(repo, "commit", "--quiet", "-m", message)
    return git_out(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> dict[str, str]:
    """main: ``before`` (no needle) then ``with_needle``; a side branch commit holds it too.

    HEAD stays on ``main`` at ``with_needle``, so today's file HAS the needle and a
    PRESENT row derives PENDING.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "--quiet", "-b", "main")
    (tmp_path / "filler.txt").write_text("nothing to see\n", encoding="utf-8")
    git(tmp_path, "add", "filler.txt")
    before = _commit(tmp_path, "an empty module\n", "before the needle")
    git(tmp_path, "checkout", "--quiet", "-b", "side")
    side = _commit(tmp_path, f"{NEEDLE}x): pass\n", "the needle, on a branch only")
    git(tmp_path, "checkout", "--quiet", "main")
    with_needle = _commit(tmp_path, f"{NEEDLE}): pass\n", "the needle, on main")
    return {"before": before, "side": side, "with_needle": with_needle}


def _board(row: str, *, sha: str) -> str:
    fillers = "".join(
        f"| W{100 + i} | filler | PENDING | `ABSENT filler.txt :: a-needle-that-is-absent-{i}` "
        "| — | — |\n"
        for i in range(8)
    )
    return (
        "# fixture board\n\n"
        f"Verified at: `{sha}`\n\n"
        "The board holds **9** rows, **0** of them unpinned.\n\n"
        "| ID | Item | State | Evidence | Issue | Depends on |\n"
        "|----|------|-------|----------|-------|------------|\n"
        f"{fillers}{row}"
    )


def _row(row_id: str, evidence: str, state: str = "PENDING") -> str:
    return f"| {row_id} | the row under test | {state} | `{evidence}` | — | — |\n"


def _check(repo: Path, row: str, shas: dict[str, str]) -> list[str]:
    board = repo / rel("docs", "65-open-work.md")
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(_board(row, sha=shas["with_needle"]), encoding="utf-8")
    failures, _report = CHECKER.check_all(repo, 10**9)
    return list(failures)


def _naming(failures: list[str], row_id: str) -> list[str]:
    return [f for f in failures if row_id in f]


def _assert_the_valid_form_is_accepted(repo: Path, shas: dict[str, str]) -> None:
    """PARTNER for every refusal of a PRESENT@ row: the same row at a commit that holds
    the needle passes, so a refusal below is about the commit, not about the form."""
    evidence = f"PRESENT@{shas['with_needle']} {TARGET} :: {NEEDLE}"
    assert _check(repo, _row(NEW_ROW, evidence), shas) == []


def test_a_new_row_with_a_plain_present_needle_is_refused(tmp_path: Path) -> None:
    # Red when: a row outside the ten grandfathered ones may use PRESENT without naming a commit.
    shas = _repo(tmp_path)
    failures = _check(tmp_path, _row(NEW_ROW, f"PRESENT {TARGET} :: {NEEDLE}"), shas)
    named = _naming(failures, NEW_ROW)
    assert len(named) == 1, failures
    assert "PRESENT@" in named[0], f"the message must say to name a commit: {named[0]}"


def test_a_grandfathered_row_keeps_its_plain_present_needle(tmp_path: Path) -> None:
    # Red when: one of the ten rows ADR-0162 keeps working by name is refused for a plain PRESENT.
    shas = _repo(tmp_path)
    for row_id in GRANDFATHERED:
        failures = _check(tmp_path, _row(row_id, f"PRESENT {TARGET} :: {NEEDLE}"), shas)
        assert failures == [], f"{row_id}: {failures}"


def test_present_at_a_main_commit_holding_the_needle_is_accepted(tmp_path: Path) -> None:
    # Red when: a PRESENT@ row whose needle is in the file at a commit on main is refused.
    shas = _repo(tmp_path)
    evidence = f"PRESENT@{shas['with_needle']} {TARGET} :: {NEEDLE}"
    assert _check(tmp_path, _row(NEW_ROW, evidence), shas) == []


def test_present_at_a_commit_without_the_needle_is_refused(tmp_path: Path) -> None:
    # Red when: the needle is not read from the file AT the named commit (made-up needle, I4).
    shas = _repo(tmp_path)
    _assert_the_valid_form_is_accepted(tmp_path, shas)
    evidence = f"PRESENT@{shas['before']} {TARGET} :: {NEEDLE}"
    assert len(_naming(_check(tmp_path, _row(NEW_ROW, evidence), shas), NEW_ROW)) >= 1


def test_present_at_a_commit_not_on_main_is_refused(tmp_path: Path) -> None:
    # Red when: a commit that main does not contain (a branch commit a squash discards) is accepted.
    shas = _repo(tmp_path)
    _assert_the_valid_form_is_accepted(tmp_path, shas)
    shown = git_out(tmp_path, "show", f"{shas['side']}:{TARGET}")
    assert NEEDLE in shown, "the side commit must hold the needle, so only 'not on main' differs"
    evidence = f"PRESENT@{shas['side']} {TARGET} :: {NEEDLE}"
    assert len(_naming(_check(tmp_path, _row(NEW_ROW, evidence), shas), NEW_ROW)) >= 1


def test_a_made_up_present_needle_derives_done_and_is_still_refused(tmp_path: Path) -> None:
    # Red when: claim I4 passes again: a needle that was never in the file, typed DONE, no commit.
    shas = _repo(tmp_path)
    made_up = "def purge_spend_keys_older_than("
    assert made_up not in (tmp_path / TARGET).read_text(encoding="utf-8")
    row = _row(NEW_ROW, f"PRESENT {TARGET} :: {made_up}", state="DONE")
    assert len(_naming(_check(tmp_path, row, shas), NEW_ROW)) >= 1
