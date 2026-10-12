"""The 14 planted false completion claims, each rejected by a support check (ADR-0162).

On 2026-10-11 a colleague's test planted 14 false "done" claims, one at a time,
in a copy of ``main`` (the appendix of
``docs/analysis/2026-10-11-how-we-work-review.md``). Nine were accepted. This
file plants each one again, alone, in a disposable clone of this repository
(``tests/status_clone.py``), runs the check that must reject it, and asserts the
exit code and the message. The clone is put back between plants and must read
exactly as before.

Each plant's literal edit is written in its function below. Where a plant
differs from the appendix, the function says why:

* I5 cites #9558/#9559. The appendix used #558/#559, and #558 became a real
  merged pull request on 2026-10-11, so a true citation would now support it.
* I7a puts "Accepted" in a paragraph of its own. ADR-0121's status paragraph
  cites CHG-011, and a citation anywhere in a paragraph supports every word in
  it, so an "Accepted" typed inside that paragraph would be supported.
* I12b: ``docs/116`` is archived by this package, so its "G7 Approved, GA" line
  is planted in ``docs/74`` instead.

I3 (a row's polarity word flipped together with its state) is still ACCEPTED,
on purpose: it is the limit the board documents
(``test_rewriting_the_evidence_claim_is_accepted_and_that_is_the_known_limit``
in ``tests/unit/test_open_work_matches_reality.py``), and ADR-0162 leaves it out
of scope. Its test asserts that, so whoever closes it has to come here.

THE BASELINE IS THE POSITIVE PARTNER. Every rejection is asserted only after the
same check passed on the unplanted clone, so an exit 1 here is the plant's.
The clone is ``HEAD``: commit before trusting a red baseline.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.repo_root import find_repo_root
from tests.status_clone import (
    CITATION_SHAPE,
    append_paragraph,
    generated_console,
    git_out,
    is_ancestor_of_main,
    make_clone,
    on_main_log,
    paragraph_of,
    planted,
    rel,
    replace_once,
    run_python,
    set_table_cell,
)

# No repo_introspection mark: ROOT comes from find_repo_root, so inside mutmut's
# ./mutants/ copy it still names the real repository, which the clone is made from.

ROOT = find_repo_root(Path(__file__))
BOARD = rel("docs", "65-open-work.md")
COMPLETION_SCRIPT = ROOT / "scripts" / ("check_completion_claims" + ".py")
LEDGER_TEST = rel("tests", "test_findings_ledger_consistency.py")

OPEN_WORK = "open_work"
COMPLETION = "completion"
CONSOLE = "console"
LEDGER = "ledger"


@dataclass
class Plant:
    edits: dict[str, str]
    stage: tuple[str, ...] = ()
    #: For a completion-check plant: (path, line number, word) that must be reported.
    problem: tuple[str, int, str] | None = None
    #: Substrings the check's output must contain.
    says: tuple[str, ...] = ()
    #: Run after the edits are written, inside the clone (a generator, for example).
    then: Callable[[Path], None] | None = None


# ---------------------------------------------------------------------------
# The clone, and each check run over it.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clone(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    repo = make_clone(ROOT, tmp_path_factory.mktemp("planted-claims") / "repo")
    # The board checker reads its board from its own folder, so the WORKING-TREE
    # copy (the one being built) replaces the clone's committed copy, with the
    # helper it loads by path.
    for path in (rel("scripts", "check_open_work.py"), rel("tests", "code_text.py")):
        shutil.copyfile(ROOT / path, repo / path)
    yield repo


def _run(check: str, clone: Path, scratch: Path) -> tuple[int, str]:
    if check == OPEN_WORK:
        done = run_python(clone, rel("scripts", "check_open_work.py"), "--check")
    elif check == COMPLETION:
        done = run_python(ROOT, str(COMPLETION_SCRIPT), "--root", str(clone))
    elif check == LEDGER:
        done = run_python(
            clone, "-m", "pytest", LEDGER_TEST, "-q", "--no-cov", "-p", "no:cacheprovider"
        )
    else:
        wanted = generated_console(clone, scratch)
        typed = (clone / "docs" / "00-factory-console.md").read_text(encoding="utf-8")
        return (0, "") if typed == wanted else (1, "the console differs from what make next writes")
    return done.returncode, done.stdout + done.stderr


@pytest.fixture(scope="module")
def baseline(clone: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[int, str]]:
    scratch = tmp_path_factory.mktemp("console-baseline")
    return {
        check: _run(check, clone, scratch) for check in (OPEN_WORK, COMPLETION, CONSOLE, LEDGER)
    }


def _has_problem(output: str, path: str, line: int, word: str) -> bool:
    return any(
        f"{path}:{line}:".lower() in row and f"'{word}'".lower() in row
        for row in output.lower().splitlines()
    )


def _text(clone: Path, path: str) -> str:
    return (clone / path).read_text(encoding="utf-8")


def _line_of(text: str, line: str) -> int:
    lines = text.splitlines()
    assert lines.count(line) == 1, f"{line!r} must occur once"
    return lines.index(line) + 1


def _cites_nothing(text: str, line: int) -> None:
    paragraph = paragraph_of(text, line)
    assert not CITATION_SHAPE.search(paragraph), f"the planted paragraph already cites: {paragraph}"


def _newest_narrative_handoff(clone: Path) -> str:
    tracked = git_out(clone, "ls-files", "--", "docs/analysis/").splitlines()
    handoffs = sorted(
        p for p in tracked if p.count("/") == 2 and re.search(r"-session-handoff[^/]*\.md$", p)
    )
    assert handoffs, "no tracked narrative handoff"
    return handoffs[-1]


def _board_row(text: str, row_id: str) -> list[str]:
    rows = [line for line in text.splitlines() if line.split("|")[1:2] == [f" {row_id} "]]
    assert len(rows) == 1, f"{row_id} found {len(rows)} times"
    return rows[0].split("|")


def _set_row(text: str, row_id: str, *, state: str, evidence: str | None = None) -> str:
    parts = _board_row(text, row_id)
    old = "|".join(parts)
    parts[3] = f" {state} "
    if evidence is not None:
        parts[4] = f" {evidence} "
    return replace_once(text, old, "|".join(parts))


# ---------------------------------------------------------------------------
# The plants. Each function is the literal edit.
# ---------------------------------------------------------------------------


def plant_i1(clone: Path) -> Plant:
    """I1: W28's State typed from PENDING to DONE."""
    text = _text(clone, BOARD)
    assert _board_row(text, "W28")[3].strip() == "PENDING"
    return Plant({BOARD: _set_row(text, "W28", state="DONE")}, says=("W28 says DONE",))


def plant_i2(clone: Path) -> Plant:
    """I2: unpinned W35 typed DONE."""
    text = _text(clone, BOARD)
    assert _board_row(text, "W35")[3].strip() == "UNPINNED"
    return Plant({BOARD: _set_row(text, "W35", state="DONE")}, says=("W35 says DONE",))


def plant_i3(clone: Path) -> Plant:
    """I3: W28's polarity word PRESENT flipped to ABSENT, and its State typed DONE."""
    text = _text(clone, BOARD)
    evidence = _board_row(text, "W28")[4].strip()
    assert evidence.startswith("`PRESENT "), evidence
    flipped = "`ABSENT " + evidence[len("`PRESENT ") :]
    return Plant({BOARD: _set_row(text, "W28", state="DONE", evidence=flipped)})


def _made_up_w55(clone: Path, polarity: str) -> Plant:
    text = _text(clone, BOARD)
    assert _board_row(text, "W55")[3].strip() == "UNPINNED"
    target = rel("src", "product_app", "feedback_store.py")
    needle = "def purge_spend_keys_older_than("
    assert needle not in _text(clone, target), "the needle must be made up"
    text = _set_row(text, "W55", state="DONE", evidence=f"`{polarity} {target} :: {needle}`")
    counted = re.search(r"\*\*(\d+)\*\* of them unpinned", text)
    assert counted, "the board's unpinned count sentence moved"
    unpinned = int(counted.group(1))
    text = replace_once(
        text, f"**{unpinned}** of them unpinned", f"**{unpinned - 1}** of them unpinned"
    )
    return Plant({BOARD: text}, says=("W55", "PRESENT@"))


def plant_i4(clone: Path) -> Plant:
    """I4: W55 pinned to a made-up PRESENT needle, typed DONE, unpinned count edited."""
    return _made_up_w55(clone, "PRESENT")


def plant_i4_at_commit(clone: Path) -> Plant:
    """I4, naming a real commit on main where the made-up needle never was."""
    sha = git_out(clone, "rev-parse", "refs/remotes/origin/main")
    plant = _made_up_w55(clone, f"PRESENT@{sha}")
    plant.says = ("W55",)
    return plant


def plant_i4_partner(clone: Path) -> Plant:
    """PARTNER for I4: W55 pinned PRESENT@ a main commit where a REAL needle is in the file.

    The new form must be accepted when it is true, so I4's rejection is about the
    made-up needle and not about the PRESENT@ form. The needle is in the file today
    too, so the row derives PENDING.
    """
    text = _text(clone, BOARD)
    assert _board_row(text, "W55")[3].strip() == "UNPINNED"
    sha = git_out(clone, "rev-parse", "refs/remotes/origin/main")
    target = rel("src", "product_app", "feedback_store.py")
    needle = "class FeedbackStore:"
    assert needle in git_out(clone, "show", f"{sha}:{target}")
    assert needle in _text(clone, target)
    evidence = f"`PRESENT@{sha} {target} :: {needle}`"
    text = _set_row(text, "W55", state="PENDING", evidence=evidence)
    counted = re.search(r"\*\*(\d+)\*\* of them unpinned", text)
    assert counted, "the board's unpinned count sentence moved"
    unpinned = int(counted.group(1))
    text = replace_once(
        text, f"**{unpinned}** of them unpinned", f"**{unpinned - 1}** of them unpinned"
    )
    return Plant({BOARD: text})


def _handoff_claim(clone: Path, line: str, word: str) -> Plant:
    path = _newest_narrative_handoff(clone)
    text, number = append_paragraph(_text(clone, path), line)
    return Plant({path: text}, problem=(path, number, word))


def plant_i5(clone: Path) -> Plant:
    """I5: a narrative handoff says W55 and W56 merged, in production, release-ready."""
    assert on_main_log(clone, "(#9558)") == 0 and on_main_log(clone, "(#9559)") == 0
    return _handoff_claim(
        clone, "W55 and W56 merged in #9558/#9559, in production, release-ready.", "merged"
    )


def plant_i6(clone: Path) -> Plant:
    """I6: the mechanical handoff says every row is DONE and Release 1 is complete."""
    path = rel("docs", "session-handoff.md")
    text, number = append_paragraph(
        _text(clone, path), "All board rows are DONE. Release 1 is complete."
    )
    return Plant({path: text}, problem=(path, number, "complete"))


def _adr_0121(clone: Path) -> str:
    found = sorted((clone / "docs" / "adr").glob("0121-*.md"))
    assert len(found) == 1, found
    return found[0].relative_to(clone).as_posix()


def _accept_adr_0121(clone: Path) -> Plant:
    path = _adr_0121(clone)
    text = replace_once(
        _text(clone, path),
        "PROPOSED — AWAITING OWNER. On 2026-09-23",
        "Accepted — 2026-10-12.\n\nOn 2026-09-23",
    )
    number = _line_of(text, "Accepted — 2026-10-12.")
    _cites_nothing(text, number)
    return Plant({path: text}, problem=(path, number, "accepted"))


def _regenerate_adr_index(clone: Path) -> None:
    done = run_python(clone, rel("scripts", "generate_adr_index.py"))
    assert done.returncode == 0, done.stderr


def plant_i7a(clone: Path) -> Plant:
    """I7a: ADR-0121 changed from PROPOSED to Accepted, and the index regenerated."""
    plant = _accept_adr_0121(clone)
    plant.then = _regenerate_adr_index
    return plant


def plant_i7b(clone: Path) -> Plant:
    """I7b: the same change, the index not regenerated."""
    return _accept_adr_0121(clone)


def plant_i7c(clone: Path) -> Plant:
    """I7c: a new ADR-0199, "Accepted ... owner approved", with no CHG row."""
    assert not list((clone / "docs" / "adr").glob("0199-*.md")), "ADR-0199 exists; pick another"
    path = rel("docs", "adr", "0199-a-key-of-ones-own.md")
    text = (
        "# ADR-0199: A key of one's own\n\n"
        "## Status\n\n"
        "Accepted — 2026-10-12, owner approved.\n\n"
        "## Context\n\n"
        "A user may bring their own key.\n"
    )
    return Plant({path: text}, stage=(path,), problem=(path, 5, "accepted"))


def plant_i8_registry(clone: Path) -> Plant:
    """I8: FR-001's Status cell in the requirement registry says Verified, passed in production."""
    path = rel("docs", "17-requirement-registry.md")
    text, original = set_table_cell(
        _text(clone, path), "FR-001", -2, "Verified, passed in production"
    )
    assert not CITATION_SHAPE.search(original), original
    number = [i for i, line in enumerate(text.splitlines(), 1) if line.startswith("| FR-001 |")][0]
    return Plant({path: text}, problem=(path, number, "verified"))


def plant_i8_matrix(clone: Path) -> Plant:
    """I8: FR-001's CI Evidence cell in the traceability matrix says CI passed."""
    path = rel("docs", "18-requirement-traceability-matrix.md")
    text, original = set_table_cell(_text(clone, path), "FR-001", 5, "CI passed")
    assert not CITATION_SHAPE.search(original), original
    number = [i for i, line in enumerate(text.splitlines(), 1) if line.startswith("| FR-001 |")][0]
    return Plant({path: text}, problem=(path, number, "passed"))


def plant_i8_criteria(clone: Path) -> Plant:
    """I8: AC-001 gains "- Status: PASSED" under its Test line."""
    path = rel("docs", "12-acceptance-criteria.md")
    text = _text(clone, path)
    heading = text.index("## AC-001 ")
    test_line = text.index("- Test: TEST-FR-001\n", heading)
    end = test_line + len("- Test: TEST-FR-001\n")
    text = text[:end] + "- Status: PASSED\n" + text[end:]
    number = text[:end].count("\n") + 1
    _cites_nothing(text, number)
    return Plant({path: text}, problem=(path, number, "passed"))


def plant_i9(clone: Path) -> Plant:
    """I9: "STATUS: COMPLETED" added to a tracked root prompt."""
    path = "R2-S2-S4-ULTRACODE-PROMPT.md"
    assert git_out(clone, "ls-files", "--", path) == path, f"{path} is no longer tracked"
    text, number = append_paragraph(_text(clone, path), "STATUS: COMPLETED")
    return Plant({path: text}, problem=(path, number, "completed"))


def plant_i10(clone: Path) -> Plant:
    """I10: the console's phase set to "Released, GA, production-ready"."""
    path = rel("docs", "00-factory-console.md")
    text = _text(clone, path)
    match = re.search(r"## Current phase\n\n(.+)\n", text)
    assert match, "the console's phase line moved"
    text = replace_once(
        text, match.group(0), "## Current phase\n\nReleased, GA, production-ready\n"
    )
    return Plant({path: text}, says=("differs",))


def plant_i11(clone: Path) -> Plant:
    """I11: findings-ledger row RB-6 changed from BUILD to DONE, with no proof."""
    path = rel("docs", "analysis", "R2-plan-review-findings.md")
    text, original = set_table_cell(
        _text(clone, path),
        "RB-6",
        -2,
        "DONE — cross-engine decision deferred to S3 with the UI slice.",
    )
    assert "BUILD" in original.split("|")[-2], original
    return Plant({path: text}, says=("RB-6",))


def _release_checklist_rows(text: str) -> list[str]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|---"))
    rows = []
    for line in lines[start + 1 :]:
        if not line.startswith("| "):
            break
        rows.append(line)
    assert rows, "the release checklist table moved"
    return rows


def plant_i12_checklist(clone: Path) -> Plant:
    """I12: every Status cell of the release checklist says Passed."""
    path = rel("docs", "74-release-checklist.md")
    text = _text(clone, path)
    first = None
    for row in _release_checklist_rows(text):
        parts = row.split("|")
        assert not CITATION_SHAPE.search(row), row
        parts[3] = " Passed "
        text = replace_once(text, row, "|".join(parts))
        first = first or "|".join(parts)
    assert first is not None
    return Plant({path: text}, problem=(path, _line_of(text, first), "passed"))


def plant_i12_signoff(clone: Path) -> Plant:
    """I12: docs/116's "G7 Approved, GA", planted as a checklist row (docs/116 is archived)."""
    path = rel("docs", "74-release-checklist.md")
    text = _text(clone, path)
    last = _release_checklist_rows(text)[-1]
    row = "| Sign-off | G7 release gate | Approved, GA | Product owner | TBD |"
    text = replace_once(text, last + "\n", f"{last}\n{row}\n")
    return Plant({path: text}, problem=(path, _line_of(text, row), "approved"))


def plant_i12_review(clone: Path) -> Plant:
    """I12: the production readiness review's decision says GA, live for all users."""
    path = rel("docs", "95-production-readiness-review.md")
    old = "- Decision: **Go** — for **single-instance deployment** on Fly.io."
    new = "- Decision: **GA, live for all users**."
    text = replace_once(_text(clone, path), old, new)
    number = _line_of(text, new)
    _cites_nothing(text, number)
    return Plant({path: text}, problem=(path, number, "ga"))


def plant_true_claim(clone: Path) -> Plant:
    """A TRUE claim: W54 step 4 merged in #556, running in production at 2a6959a."""
    assert on_main_log(clone, "(#556)") == 1 and is_ancestor_of_main(clone, "2a6959a")
    path = _newest_narrative_handoff(clone)
    text, _ = append_paragraph(
        _text(clone, path), "W54 step 4 merged in #556, running in production at 2a6959a."
    )
    return Plant({path: text})


# (id, the plant, the check that must judge it, the exit code it must give)
CASES: list[tuple[str, Callable[[Path], Plant], str, int]] = [
    ("I1", plant_i1, OPEN_WORK, 1),
    ("I2", plant_i2, OPEN_WORK, 1),
    # ACCEPTED on purpose: the board's documented limit, out of scope per ADR-0162.
    ("I3", plant_i3, OPEN_WORK, 0),
    ("I4", plant_i4, OPEN_WORK, 1),
    ("I4-at-commit", plant_i4_at_commit, OPEN_WORK, 1),
    ("I4-partner", plant_i4_partner, OPEN_WORK, 0),
    ("I5", plant_i5, COMPLETION, 1),
    ("I6", plant_i6, COMPLETION, 1),
    ("I7a", plant_i7a, COMPLETION, 1),
    ("I7b", plant_i7b, COMPLETION, 1),
    ("I7c", plant_i7c, COMPLETION, 1),
    ("I8-registry", plant_i8_registry, COMPLETION, 1),
    ("I8-matrix", plant_i8_matrix, COMPLETION, 1),
    ("I8-criteria", plant_i8_criteria, COMPLETION, 1),
    ("I9", plant_i9, COMPLETION, 1),
    ("I10", plant_i10, CONSOLE, 1),
    ("I11", plant_i11, LEDGER, 1),
    ("I12-checklist", plant_i12_checklist, COMPLETION, 1),
    ("I12-signoff", plant_i12_signoff, COMPLETION, 1),
    ("I12-review", plant_i12_review, COMPLETION, 1),
    ("true-claim", plant_true_claim, COMPLETION, 0),
]


def test_the_unplanted_clone_passes_every_check(baseline: dict[str, tuple[int, str]]) -> None:
    # Red when: a check fails on the committed tree, which would make every exit 1 below vacuous.
    failing = {check: out for check, (code, out) in baseline.items() if code != 0}
    assert not failing, f"the unplanted clone (HEAD) fails: {failing}"


@pytest.mark.parametrize(
    ("plant_id", "make", "check", "exit_code"), CASES, ids=[c[0] for c in CASES]
)
def test_each_planted_claim_is_judged_by_its_support_check(
    clone: Path,
    baseline: dict[str, tuple[int, str]],
    tmp_path: Path,
    plant_id: str,
    make: Callable[[Path], Plant],
    check: str,
    exit_code: int,
) -> None:
    # Red when: the check named in CASES stops rejecting this plant (exit 1), or, for I3 and the
    # true claim, starts rejecting it (exit 0). I1, I2 and I11 are regressions of checks that
    # already worked on 2026-10-11.
    assert baseline[check][0] == 0, f"{check} already fails unplanted:\n{baseline[check][1]}"
    plant = make(clone)
    with planted(clone, plant.edits, stage=plant.stage):
        if plant.then is not None:
            plant.then(clone)
        code, output = _run(check, clone, tmp_path)
    assert code == exit_code, f"{plant_id}: {check} exited {code}, wanted {exit_code}\n{output}"
    for fragment in plant.says:
        assert fragment in output, f"{plant_id}: {fragment!r} not in\n{output}"
    if plant.problem is not None:
        path, line, word = plant.problem
        assert _has_problem(output, path, line, word), (
            f"{plant_id}: no problem names {path}:{line} and '{word}'\n{output}"
        )
