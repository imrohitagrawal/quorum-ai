"""A completion word in a status document must cite its proof (ADR-0162, decisions 1 and 2).

The check under test is ``check_completion_claims`` in ``scripts/``. Every case
here runs it over a disposable ``git clone --shared`` of this repository
(``tests/status_clone.py``), because the rule is defined by git history: a line
is checked only when ``git blame`` says it was written after the cut-off commit,
or it is not committed yet, and a citation counts only when it is on ``main``.

Every rejection has an acceptance partner that differs in the one thing the rule
is about (the citation, the negation, the quoting, the age of the line), so a
check that rejects everything, or nothing, fails here.

GATE CHARTER
------------
WHY THIS EXISTS: on 2026-10-11, 14 false completion claims were planted one at a
time in a copy of ``main``; 9 were accepted by every check, including "W55 and
W56 merged ... in production" in a handoff (appendix of the 2026-10-11 how-we-work
review in ``docs/analysis/``).

WHAT IT CANNOT SEE: words outside the list ("done", "shipped", "live"); a false
claim in a paragraph that also holds a true citation, since a citation anywhere
in the paragraph supports every word in it; lines written before the cut-off;
untracked files; and whether the cited pull request did what the sentence says.

FALSE-POSITIVE COST: a new line that uses a listed word in its plain sense ("the
request is accepted") fails until it is quoted, reworded or cited.

WHEN TO REMOVE: when status claims are generated from git and GitHub instead of
written by hand.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.repo_root import find_repo_root
from tests.status_clone import (
    CITATION_SHAPE,
    CUTOFF,
    append_paragraph,
    git,
    git_out,
    is_ancestor_of_main,
    load_script,
    make_clone,
    on_main_log,
    paragraph_of,
    planted,
    rel,
    run_python,
)

# No repo_introspection mark: ROOT comes from find_repo_root, so inside mutmut's
# ./mutants/ copy it still names the real repository, which the clone is made from.

ROOT = find_repo_root(Path(__file__))
SCRIPT_STEM = "check_completion_claims"
COUNT_KEYS = {"files_scoped", "files_checked", "files_exempt", "lines_checked", "claims"}
PROBLEM_TAIL = "cites no merged pull request, commit on main, or CHG row"

#: A narrative handoff last changed before the cut-off, and one of its lines that
#: says "merged" and "verified" with no citation in its paragraph. Picked with
#: ``git blame`` on 2026-10-12: commit c894f78 (#557), an ancestor of the cut-off.
OLD_HANDOFF = rel("docs", "analysis", "2026-10-11-session-handoff.md")
OLD_LINE = "## Shipped (merged, deployed, verified by the Deploy job and `/status` `build_sha`)"


def _checker() -> Any:
    return load_script(ROOT, SCRIPT_STEM)


def _script_path() -> str:
    return str(ROOT / "scripts" / f"{SCRIPT_STEM}.py")


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    yield make_clone(ROOT, tmp_path_factory.mktemp("completion-claims") / "repo")


def _newest_narrative_handoff(clone: Path) -> str:
    tracked = git_out(clone, "ls-files", "--", "docs/analysis/").splitlines()
    handoffs = sorted(
        p for p in tracked if p.count("/") == 2 and re.search(r"-session-handoff[^/]*\.md$", p)
    )
    assert handoffs, "no tracked narrative handoff to plant in"
    return handoffs[-1]


def _problems_at(problems: list[str], path: str, line: int) -> list[str]:
    return [p for p in problems if p.startswith(f"{path}:{line}:")]


def _plant_line(clone: Path, line: str) -> tuple[list[str], dict[str, int], str, int]:
    """Append ``line`` as its own paragraph to the newest narrative handoff and check."""
    path = _newest_narrative_handoff(clone)
    text, number = append_paragraph((clone / path).read_text(encoding="utf-8"), line)
    with planted(clone, {path: text}):
        problems, counts = _checker().check(clone)
    return list(problems), dict(counts), path, number


#: The negated or quoted forms, each with the bare form that IS a claim.
NEGATIONS = {
    "not": ("W55 is not merged yet.", "W55 is merged."),
    "never": ("W55 was never merged.", "W55 was merged."),
    "un-prefix": (
        "UNVERIFIED: W55 holds the hash for 24 hours.",
        "VERIFIED: W55 holds the hash for 24 hours.",
    ),
    "backticks": ("The word `merged` is on the list.", "The word merged is on the list."),
    "double-quotes": ('The word "merged" is on the list.', "The word merged is on the list."),
}


@pytest.fixture(scope="module")
def batch(clone: Path) -> dict[str, Any]:
    """Every single-line case, each its own paragraph, planted together and checked ONCE.

    Support is per paragraph, so the cases cannot lend each other a citation; and
    one run of the check instead of twenty keeps this file fast.
    """
    off_main = git_out(clone, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "off main")[:7]
    lines = {
        "uncited": "W55 and W56 merged in #9558, in production.",
        "cites #556": "W54 step 4 merged in #556.",
        "sha on_main": f"Package A merged at {CUTOFF[:7]}.",
        "sha off_main": f"Package A merged at {off_main}.",
        "sha not_a_commit": "Package A merged at 0decade.",
        "CHG-039": "The retention period was approved (CHG-039).",
        "CHG-999": "The retention period was approved (CHG-999).",
    }
    for name, (negated, bare) in NEGATIONS.items():
        lines[f"negated {name}"] = negated
        lines[f"bare {name}"] = bare
    path = _newest_narrative_handoff(clone)
    text = (clone / path).read_text(encoding="utf-8")
    numbers: dict[str, int] = {}
    for name, line in lines.items():
        text, numbers[name] = append_paragraph(text, line)
    with planted(clone, {path: text}):
        problems, counts = _checker().check(clone)
    return {
        "problems": list(problems),
        "counts": dict(counts),
        "path": path,
        "numbers": numbers,
        "off_main": off_main,
    }


def _reported(batch: dict[str, Any], name: str) -> list[str]:
    return _problems_at(batch["problems"], batch["path"], batch["numbers"][name])


def test_an_uncited_merge_claim_is_reported_once_per_word(
    clone: Path, batch: dict[str, Any]
) -> None:
    # Red when: the check stops reporting a completion word that cites nothing on main.
    assert on_main_log(clone, "(#9558)") == 0, "#9558 must not be a merged pull request"
    here = _reported(batch, "uncited")
    assert len(here) == 2, f"expected one problem for 'merged' and one for 'in production': {here}"
    assert any("'merged'" in p.lower() for p in here), here
    assert any("'in production'" in p.lower() for p in here), here
    assert all(PROBLEM_TAIL in p for p in here), here


def test_a_claim_citing_a_real_squash_merge_is_accepted(clone: Path, batch: dict[str, Any]) -> None:
    # Red when: a citation of a pull request squash-merged on main stops counting as support.
    assert on_main_log(clone, "(#556)") == 1, "#556 must be a squash commit on main"
    assert _reported(batch, "cites #556") == []


@pytest.mark.parametrize(
    ("which", "reported"),
    [("on_main", False), ("off_main", True), ("not_a_commit", True)],
)
def test_a_commit_id_supports_a_claim_only_when_it_is_on_main(
    clone: Path, batch: dict[str, Any], which: str, reported: bool
) -> None:
    # Red when: a commit id off main, or no commit, supports a claim; or one on main does not.
    if which == "on_main":
        assert is_ancestor_of_main(clone, CUTOFF[:7])
    elif which == "off_main":
        # A real commit that main does not contain, made without moving HEAD.
        assert git(clone, "cat-file", "-e", f"{batch['off_main']}^{{commit}}").returncode == 0
        assert not is_ancestor_of_main(clone, batch["off_main"])
    else:
        assert git(clone, "cat-file", "-e", "0decade^{commit}", check=False).returncode != 0
    assert bool(_reported(batch, f"sha {which}")) is reported, batch["problems"]


@pytest.mark.parametrize(("chg", "reported"), [("CHG-039", False), ("CHG-999", True)])
def test_a_chg_row_supports_a_claim_only_when_it_exists(
    clone: Path, batch: dict[str, Any], chg: str, reported: bool
) -> None:
    # Red when: a CHG number with no row in the change log supports a claim, or a real one does not.
    log = (clone / "docs" / "19-change-control-log.md").read_text(encoding="utf-8")
    assert bool(re.search(rf"^\| *{chg} *\|", log, re.MULTILINE)) is not reported
    assert bool(_reported(batch, chg)) is reported, batch["problems"]


@pytest.mark.parametrize("name", list(NEGATIONS))
def test_a_negated_or_quoted_word_is_not_a_claim(batch: dict[str, Any], name: str) -> None:
    # Red when: a negated or quoted word is reported, or the same word bare is not.
    assert _reported(batch, f"negated {name}") == [], NEGATIONS[name][0]
    # PARTNER: the same sentence without the negation or the quotes IS a claim.
    assert _reported(batch, f"bare {name}"), f"{NEGATIONS[name][1]!r} is a claim and cites nothing"


# ---------------------------------------------------------------------------
# The cut-off: only lines written after it are checked.
# ---------------------------------------------------------------------------


def test_a_line_written_before_the_cutoff_is_not_checked(clone: Path) -> None:
    # Red when: a line blame dates before the cut-off is checked once its file changes.
    text = (clone / OLD_HANDOFF).read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines.count(OLD_LINE) == 1, f"{OLD_LINE!r} is no longer in {OLD_HANDOFF} once"
    old_number = lines.index(OLD_LINE) + 1
    assert not CITATION_SHAPE.search(paragraph_of(text, old_number)), (
        "its paragraph must cite nothing"
    )
    blamed = git_out(
        clone, "blame", "--porcelain", "-L", f"{old_number},{old_number}", "--", OLD_HANDOFF
    )
    blamed_sha = blamed.split()[0]
    assert (
        git(clone, "merge-base", "--is-ancestor", blamed_sha, CUTOFF, check=False).returncode == 0
    )

    # The file gets an uncommitted change, so it is checked, line by line.
    changed, _ = append_paragraph(text, "A neutral line added after the cut-off.")
    with planted(clone, {OLD_HANDOFF: changed}):
        problems, _counts = _checker().check(clone)
    assert _problems_at(list(problems), OLD_HANDOFF, old_number) == []

    # PARTNER: the same words written now are reported, in the same file.
    copied, new_number = append_paragraph(text, OLD_LINE)
    with planted(clone, {OLD_HANDOFF: copied}):
        problems, _counts = _checker().check(clone)
    assert _problems_at(list(problems), OLD_HANDOFF, new_number), problems


def test_a_committed_line_after_the_cutoff_is_checked(tmp_path: Path) -> None:
    # Red when: only uncommitted lines are checked, so a committed false claim passes.
    own = make_clone(ROOT, tmp_path / "repo")
    path = _newest_narrative_handoff(own)
    text, number = append_paragraph(
        (own / path).read_text(encoding="utf-8"), "W55 and W56 merged in #9558, in production."
    )
    (own / path).write_text(text, encoding="utf-8")
    git(own, "commit", "--quiet", "-am", "a session commits a false claim")
    assert git_out(own, "status", "--porcelain") == ""
    problems, _counts = _checker().check(own)
    assert len(_problems_at(list(problems), path, number)) == 2, problems


# ---------------------------------------------------------------------------
# What it counted, and refusing to pass over nothing.
# ---------------------------------------------------------------------------


def _scoped(clone: Path) -> list[str]:
    """ADR-0162's scoped files, written out here as globs, over the tracked files."""
    out = []
    for path in git_out(clone, "ls-files").splitlines():
        folder, _, name = path.rpartition("/")
        if (
            (folder == "docs/analysis" and re.fullmatch(r".*-session-handoff.*\.md", name))
            or path == rel("docs", "session-handoff.md")
            or (folder == "" and re.fullmatch(r".*PROMPT.*\.md", name))
            or (folder == "docs" and re.fullmatch(r"(12|17|18|73|74|95)-.*\.md", name))
            or (folder == "docs/adr" and re.fullmatch(r"0.*\.md", name))
            or path == rel("docs", "product-readiness.md")
        ):
            out.append(path)
    return out


def test_the_counts_say_what_was_read(clone: Path) -> None:
    # Red when: a count is missing, files_scoped stops matching the tracked files in scope, or
    # nothing is reported exempt.
    _problems, counts = _checker().check(clone)
    assert set(counts) >= COUNT_KEYS, f"missing counts: {COUNT_KEYS - set(counts)}"
    scoped = _scoped(clone)
    assert len(scoped) > 100, f"only {len(scoped)} files in scope; the ADRs alone are 150+"
    assert counts["files_scoped"] == len(scoped), (counts, len(scoped))
    # At the cut-off 155 of 157 ADRs were older than it: most files are exempt.
    assert counts["files_exempt"] > 0, counts


def test_the_claim_count_moves_with_each_planted_word(clone: Path) -> None:
    # Red when: the claim count is not the number of completion words read, supported or not.
    _p, base = _checker().check(clone)
    _p, after, _path, _n = _plant_line(clone, "W54 step 4 merged in #556.")
    assert after["claims"] == base["claims"] + 1, (base, after)
    _p, after, _path, _n = _plant_line(clone, "W55 and W56 merged in #9558, in production.")
    assert after["claims"] == base["claims"] + 2, (base, after)
    assert after["files_checked"] >= 1 and after["lines_checked"] >= 1, after


def test_the_script_exits_1_when_nothing_is_in_scope(tmp_path: Path) -> None:
    # Red when: the script passes a tree with no scoped file, having read nothing.
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "--quiet", "-b", "main")
    (empty / "notes.md").write_text("Nothing here is in scope.\n", encoding="utf-8")
    git(empty, "add", "notes.md")
    git(empty, "commit", "--quiet", "-m", "one unscoped file")
    done = run_python(ROOT, _script_path(), "--root", str(empty))
    assert done.returncode == 1, f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"


def test_the_script_exits_0_on_the_committed_tree_and_prints_its_counts(clone: Path) -> None:
    # Red when: the committed tree holds an unsupported claim, or the script stops printing counts.
    # This is the positive partner of every exit-1 case in this file and in the planted-claims
    # test. The clone is HEAD: commit first.
    done = run_python(ROOT, _script_path(), "--root", str(clone))
    output = done.stdout + done.stderr
    assert done.returncode == 0, f"exit {done.returncode}\n{output}"
    for key in COUNT_KEYS:
        assert key in output, f"{key} not printed:\n{output}"
    # And the planted case through the same entry point: exit 1, naming the file.
    path = _newest_narrative_handoff(clone)
    text, number = append_paragraph(
        (clone / path).read_text(encoding="utf-8"), "W55 and W56 merged in #9558, in production."
    )
    with planted(clone, {path: text}):
        bad = run_python(ROOT, _script_path(), "--root", str(clone))
    assert bad.returncode == 1, f"exit {bad.returncode}\n{bad.stdout}\n{bad.stderr}"
    assert f"{path}:{number}:" in bad.stdout + bad.stderr
