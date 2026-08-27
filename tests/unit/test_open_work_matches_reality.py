"""The open-work board's State column is DERIVED, so it cannot be declared.

``docs/65-open-work.md`` is the source of truth for what is open here. Every
previous attempt at a status file in this repository rotted:
``docs/00-factory-console.md`` was 64 first-parent commits behind its own last
touch when that was measured on 2026-08-28, while four test files read it and
none asked whether the work it announced was the work in flight. ``make next``
rewrites it wholesale, so hand-written words there do not survive the next
session running the command ``AGENTS.md`` tells it to run.

TWO DESIGNS THIS FILE OUTLIVED. Both were defeated by adversarial review before
merge, and every exploit below is now a regression test in this file:

1. **Polarity typed by the author.** Replacing every ``| PENDING |`` with
   ``| DONE |`` left the gate green, printing "0 PENDING", with zero bytes
   changed under ``src/``.
2. **State coupled to polarity.** A *two*-token edit -- state word and polarity
   word together -- did the same. So did unpinning a row and marking it DONE.
   So did a comment: appending ``# TODO ... "stream": True ...`` to
   ``providers.py`` flipped W1's evidence.

The root cause both share: state and claim were typed by the same hand in the
same file. Nothing writes the state now -- it is generated from the tree, and
``--check`` refuses any disagreement, the shape
``scripts/generate_adr_index.py`` has used here all along.

GATE CHARTER
------------
WHY THIS EXISTS: hand-written status rots because nothing compares the sentence
to the tree. Measured 2026-08-28: the factory console still announced work from
PR #91 and quoted ``pytest 1342 passed`` against a suite collecting 3829, and
four open issues (#383, #382, #380, #379) appeared in no planning document at
all. Work was planned across five documents that did not reference each other.

WHAT IT CANNOT SEE: an author who rewrites the EVIDENCE cell to point at a file
or needle where the claim already holds the other way -- that is a visible change
to the claim, which is what review reads, not a status flip. Nor work that lands
under a different name than the needle, or by a different route under the same
name (defining ``_bound_sniff_time`` rather than deleting its dangling
references would not flip W15). Nor anything about the four unpinned rows. Nor a
row that should exist and does not.

FALSE-POSITIVE COST: low but not zero. A needle is a substring of a real code
line, so a refactor that reformats that line re-derives the row's state and the
board must be regenerated. That is the intended trade: it forces a human to look
at the board. A needle loose enough never to fire checks nothing.

WHEN TO REMOVE: when the board's rows are derived from something with its own
tooling (an issue tracker mirrored into the repo, a generated register). Not
before: the failure it guards -- a status document drifting silently while gates
watch it -- has already happened here at least twice.
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
_NEEDLE = "needle-that-is-long"


def _load_script() -> Any:
    """Load the checker by path, never as ``scripts.check_open_work``.

    ``make type-check`` runs ``mypy src tests`` and follows static imports, so a
    package import would drag an unchecked file into a strict-mode gate. Same
    loader idiom as ``tests/unit/test_adr_index_matches_directory.py``.
    Registration in ``sys.modules`` is required before execution because the
    module defines dataclasses, whose annotations resolve through it.
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


def _row(row_id: str, state: str, evidence: str) -> str:
    return f"| {row_id} | x | {state} | {evidence} | — | — |\n"


def _pinned(row_id: str, state: str, polarity: str = "ABSENT") -> str:
    return _row(row_id, state, f"`{polarity} {_TARGET_NAME} :: {_NEEDLE}`")


def _sandbox(tmp_path: Path, *, board: str, target: str = "nothing here") -> Path:
    """A root the checker can be pointed at: a board plus one target file."""
    (tmp_path / _DOCS).mkdir(parents=True)
    (tmp_path / _DOCS / _BOARD_NAME).write_text(board, encoding="utf-8")
    (tmp_path / _TARGET_NAME).write_text(target, encoding="utf-8")
    return tmp_path


def _run(tmp_path: Path, *, board: str, target: str = "nothing here") -> tuple[list[str], str]:
    """``check_all`` over a sandbox root, with the drift limit out of the way."""
    root = _sandbox(tmp_path, board=board, target=target)
    failures, report = CHECKER.check_all(root, 10**9)
    return list(failures), str(report)


def _enough_rows(state: str, *, polarity: str = "ABSENT") -> tuple[str, int]:
    """Enough pinned rows to clear ``MIN_EVIDENCE_CLAIMS``, all in one state."""
    n = CHECKER.MIN_EVIDENCE_CLAIMS
    return "".join(_pinned(f"W{i}", state, polarity) for i in range(1, n + 1)), n


# ---------------------------------------------------------------------------
# The live gate.
# ---------------------------------------------------------------------------


def test_the_real_board_agrees_with_the_real_tree() -> None:
    """Turns red if: the board's State column stops matching what the tree says.

    That happens when work lands (or is reverted) and nobody regenerated the
    column. The fix is ``make open-work-write``, never an edit.
    """
    failures, report = CHECKER.check_all(ROOT)
    assert not failures, "the board disagrees with the tree:\n  " + "\n  ".join(failures)
    # POSITIVE PARTNER. "no failures" is trivially true over an unparsed file.
    parsed = CHECKER.parse_board(CHECKER.BOARD.read_text(encoding="utf-8"))
    assert len(parsed.rows) >= 10, f"only {len(parsed.rows)} rows parsed: {report}"
    pinned = [r for r in parsed.rows if r.pinned]
    assert len(pinned) >= CHECKER.MIN_EVIDENCE_CLAIMS, f"only {len(pinned)} rows carry a needle"


def test_the_real_board_is_already_regenerated() -> None:
    """Turns red if: the checked-in State column is not what --write would emit.

    ``check_all`` compares them too, but through a rendering equality that a
    future refactor could weaken. This drives the WRITER against the file and is
    the assertion a reader can follow.
    """
    text = CHECKER.BOARD.read_text(encoding="utf-8")
    states, failures, read = CHECKER.derive_states(CHECKER.parse_board(text), ROOT)
    assert failures == [], failures
    assert read >= CHECKER.MIN_EVIDENCE_CLAIMS, f"only {read} needles read"
    assert CHECKER.render(text, states) == text, (
        "run `make open-work-write` -- the State column is generated, not written"
    )


def test_the_checker_exits_non_zero_on_a_board_that_disagrees(tmp_path: Path) -> None:
    """Turns red if: ``--check`` stops reporting failure through its exit code.

    Driven as a subprocess because the exit code is what ``make validate`` reads.
    A function returning 1 that ``main`` never propagates would satisfy every
    other test in this file.
    """
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env_without_coverage(),
    )
    assert ok.returncode == 0, f"the real board should pass:\n{ok.stdout}\n{ok.stderr}"
    assert "needles read from disk" in ok.stdout, f"must report what it counted: {ok.stdout!r}"

    rows, n = _enough_rows(CHECKER.DONE)  # a lie: the needle is absent, so it is PENDING
    broken = _sandbox(tmp_path, board=_board_text(rows, row_count=n, unpinned=0))
    (broken / "scripts").mkdir()
    (broken / "scripts" / SCRIPT.name).write_bytes(SCRIPT.read_bytes())
    bad = subprocess.run(
        [sys.executable, str(broken / "scripts" / SCRIPT.name), "--check"],
        cwd=broken,
        capture_output=True,
        text=True,
        # A Python child at a cwd OUTSIDE this repository inherits pytest-cov's
        # subprocess hooks, resolves the relative ``--cov=src`` against the
        # sandbox and records that tree at 0% into the shared coverage data,
        # inflating the denominator of a REQUIRED gate (#368).
        env=env_without_coverage(),
    )
    assert bad.returncode == 1, f"a lying board must exit 1; got {bad.returncode}\n{bad.stderr}"
    assert "the State column disagrees with the tree" in bad.stderr


# ---------------------------------------------------------------------------
# The three exploits that killed the previous designs. Each is now a test.
# ---------------------------------------------------------------------------


def test_declaring_every_row_done_is_refused(tmp_path: Path) -> None:
    """Turns red if: a hand-written State is believed. THE round-1 exploit.

    Verbatim, on the first design: replacing every ``| PENDING |`` with
    ``| DONE |`` left the gate exiting 0 and printing "0 PENDING", with zero
    bytes changed under ``src/`` and every bite-proof passing.
    """
    rows, n = _enough_rows(CHECKER.PENDING)
    board = _board_text(rows, row_count=n, unpinned=0)
    assert _run(tmp_path / "a", board=board) == ([], _run(tmp_path / "a2", board=board)[1])

    lying = board.replace(f"| {CHECKER.PENDING} |", f"| {CHECKER.DONE} |")
    assert lying != board, "the fixture must actually contain the word being replaced"
    failures, _ = _run(tmp_path / "b", board=lying)
    assert len(failures) == 1, failures
    assert "the State column disagrees with the tree" in failures[0]
    assert f"says {CHECKER.DONE}, the tree says {CHECKER.PENDING}" in failures[0]


def test_rewriting_the_evidence_claim_is_accepted_and_that_is_the_known_limit(
    tmp_path: Path,
) -> None:
    """Turns red if: someone writes down a stronger guarantee than exists.

    THIS TEST PINS A LIMITATION, DELIBERATELY. Derivation stops a hand writing
    the State column, but the POLARITY word is part of the claim and the author
    writes the claim. Flipping the state word AND the polarity word together is
    still accepted, because the derivation reads the flipped polarity and
    derives the flipped state -- so the file and the tree agree.

    It is asserted rather than merely written down because the two designs
    before this one each shipped a sentence promising more than they delivered,
    and prose is where every false claim in this repository has lived. If a
    future change closes this, THIS TEST GOES RED, and whoever closes it must
    come here and say so.

    Why it is not being closed now, on purpose. Closing it needs the evidence
    text to be immutable between anchor stamps -- comparing each row against
    ``git show <anchor>:docs/65-open-work.md``. That guards against a DELIBERATE
    author, which is not the threat: the failure this board exists to prevent is
    a status document rotting through carelessness, and derivation closes that
    completely. Rewriting a claim and a state together is not carelessness, it
    is a visible change to the claim in the diff, and review is what reads it.
    """
    rows, n = _enough_rows(CHECKER.PENDING, polarity="ABSENT")
    board = _board_text(rows, row_count=n, unpinned=0)

    # The one-token version -- state only -- IS refused. That is the round-1
    # exploit and it is closed.
    one_token = board.replace(f"| {CHECKER.PENDING} |", f"| {CHECKER.DONE} |")
    assert _run(tmp_path / "a", board=one_token)[0], "a state-only flip must be refused"

    # The two-token version is accepted, and this is the documented limit.
    two_token = one_token.replace("`ABSENT ", "`PRESENT ")
    failures, report = _run(tmp_path / "b", board=two_token)
    assert failures == [], (
        "a two-token flip is a KNOWN limit of this design -- if you have closed "
        "it, delete this test and say so in the board's 'What this cannot see' "
        f"list and in ADR-0079. Failures were: {failures}"
    )
    assert f"0 {CHECKER.PENDING}" in report and f"{n} {CHECKER.DONE}" in report

    # And the board must SAY SO, in the words a reader will look for. A limit
    # that is only true in a test is not disclosed.
    disclosed = CHECKER.BOARD.read_text(encoding="utf-8")
    assert "rewrites the Evidence cell" in disclosed, (
        "the board's 'What this cannot see' list no longer discloses that an "
        "author who rewrites the evidence claim is not stopped"
    )


def test_unpinning_a_row_can_never_make_it_read_done(tmp_path: Path) -> None:
    """Turns red if: an unpinned row can carry any state but UNPINNED.

    The second design's other route: set a row's evidence to the em dash, mark
    it DONE, bump the unpinned count. It worked on a **STOP** row.
    """
    rows, n = _enough_rows(CHECKER.PENDING)
    rows += _row("W99", CHECKER.DONE, "`—`")
    failures, _ = _run(tmp_path / "a", board=_board_text(rows, row_count=n + 1, unpinned=1))
    assert len(failures) == 1, failures
    assert f"W99 says {CHECKER.DONE}, the tree says {CHECKER.UNPINNED}" in failures[0]

    # POSITIVE PARTNER: the same row rendered honestly passes, so this is not a
    # blanket refusal of unpinned rows.
    honest = rows.replace(_row("W99", CHECKER.DONE, "`—`"), _row("W99", CHECKER.UNPINNED, "`—`"))
    assert _run(tmp_path / "b", board=_board_text(honest, row_count=n + 1, unpinned=1))[0] == []


def test_a_comment_cannot_satisfy_a_needle(tmp_path: Path) -> None:
    """Turns red if: needles are matched against comments as well as code.

    Appending ``# TODO(W1): we still need to send "stream": True here`` to
    ``providers.py`` derived DONE for W1 on the previous design -- a comment
    saying the work was NOT done would have completed the row.
    """
    rows, n = _enough_rows(CHECKER.PENDING)
    board = _board_text(rows, row_count=n, unpinned=0)
    commented = f"nothing here\n# TODO: we still need {_NEEDLE} here.\n"
    failures, _ = _run(tmp_path / "a", board=board, target=commented)
    assert failures == [], f"a needle mentioned only in a comment must not count: {failures}"

    # POSITIVE PARTNER: the same text as CODE does count, so the stripper is not
    # simply ignoring the file.
    as_code = f"x = {_NEEDLE}\n"
    landed, _ = _run(tmp_path / "b", board=board, target=as_code)
    assert len(landed) == 1, landed
    assert "the State column disagrees" in landed[0]


def test_the_comment_rule_requires_whitespace_before_the_marker() -> None:
    """Turns red if: the comment rule cuts at a marker mid-token.

    THE MECHANISM THAT MATTERS, and it is not the one an earlier draft of this
    comment claimed. W16's live needle contains ``https://openrouter.ai/...``,
    and what protects it is the ``(?:^|\s)`` guard -- the marker must start a
    line or follow whitespace. A naive cut at the first ``//`` truncates that
    line to ``URL = "https:`` and the row derives the wrong state against a file
    nobody touched. Measured, both ways, below.

    (The pattern lists only ``#`` because every file the board pins is Python,
    TOML or Markdown, where ``#`` is the comment character. That is scope, not
    a hazard: adding ``//`` behind the same whitespace guard would change
    nothing here.)
    """
    line = 'URL = "https://openrouter.ai/api/v1/models"  # a trailing comment'
    kept = CHECKER.code_text(line)
    assert "https://openrouter.ai/api/v1/models" in kept, kept
    assert "a trailing comment" not in kept, kept

    # A ``#`` mid-token is NOT a comment marker, so it must survive.
    assert CHECKER.code_text('colour = "#ff0000"') == 'colour = "#ff0000"'

    # ...and one that starts a line, or follows whitespace, IS.
    assert CHECKER.code_text("# whole line") == ""
    assert CHECKER.code_text("code = 1  # tail") == "code = 1 "

    # A multi-line body keeps its shape, so a needle spanning lines still works.
    assert CHECKER.code_text("a = 1  # x\nb = 2") == "a = 1 \nb = 2"


# ---------------------------------------------------------------------------
# Derivation, both directions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("polarity", "target", "expected"),
    [
        ("ABSENT", "nothing here", "PENDING"),
        ("ABSENT", f"x = {_NEEDLE}", "DONE"),
        ("PRESENT", f"x = {_NEEDLE}", "PENDING"),
        ("PRESENT", "nothing here", "DONE"),
    ],
)
def test_the_state_is_derived_from_the_tree(
    tmp_path: Path, polarity: str, target: str, expected: str
) -> None:
    """Turns red if: the derivation collapses to a constant in either direction.

    All four combinations, because a derivation that always says PENDING and one
    that always says DONE each satisfy half of them.
    """
    rows, n = _enough_rows(expected, polarity=polarity)
    failures, _ = _run(tmp_path, board=_board_text(rows, row_count=n, unpinned=0), target=target)
    assert failures == [], failures


def test_the_writer_rewrites_a_stale_column(tmp_path: Path) -> None:
    """Turns red if: ``write_states`` stops writing, or writes when current.

    Both directions: a stale column is rewritten and reported changed; a current
    one is left byte-identical and reported unchanged.
    """
    rows, n = _enough_rows(CHECKER.DONE)  # wrong: the needle is absent
    root = _sandbox(tmp_path, board=_board_text(rows, row_count=n, unpinned=0))
    board_file = root / _DOCS / _BOARD_NAME
    before = board_file.read_text(encoding="utf-8")

    assert CHECKER.write_states(root) is True
    after = board_file.read_text(encoding="utf-8")
    assert after != before
    assert f"| {CHECKER.PENDING} |" in after and f"| {CHECKER.DONE} |" not in after
    assert CHECKER.check_all(root, 10**9)[0] == []

    assert CHECKER.write_states(root) is False, "a current column must not be rewritten"
    assert board_file.read_text(encoding="utf-8") == after


def test_rendering_touches_only_the_state_cell() -> None:
    """Turns red if: ``render`` rewrites a cell it has no business rewriting.

    The evidence, issue and depends-on cells are hand-authored; a generator that
    reformatted them would make every regeneration a reviewable diff and the
    gate would be turned off within a week.
    """
    row = "| W1 | an item |  whatever  | `ABSENT f.txt :: n` | #12 | W2 |\n"
    out = CHECKER.render(row, {"W1": CHECKER.DONE})
    assert out == "| W1 | an item | DONE | `ABSENT f.txt :: n` | #12 | W2 |\n"
    # A row the derivation says nothing about is passed through untouched.
    assert CHECKER.render(row, {}) == row


# ---------------------------------------------------------------------------
# Floors, refusals and counts.
# ---------------------------------------------------------------------------


def test_the_gate_refuses_to_pass_over_an_empty_table(tmp_path: Path) -> None:
    """Turns red if: the empty-table floor is removed.

    Every other check is a loop over rows and every one is satisfied by zero
    rows. A moved heading or a broken row pattern would otherwise leave this
    gate reporting success while measuring nothing.
    """
    failures, _ = _run(tmp_path, board=_board_text("", row_count=0, unpinned=0))
    assert len(failures) == 1, failures
    assert "refuses to pass over an empty input" in failures[0]


def test_the_gate_refuses_a_board_that_pins_nothing(tmp_path: Path) -> None:
    """Turns red if: the evidence floor is removed.

    The empty-TABLE floor does not imply this one: a board of entirely unpinned
    rows parses fine, renders consistently, and reads zero needles off disk.
    """
    rows = "".join(_row(f"W{i}", CHECKER.UNPINNED, "`—`") for i in range(1, 4))
    failures, report = _run(tmp_path, board=_board_text(rows, row_count=3, unpinned=3))
    assert len(failures) == 1, failures
    assert "only 0 needles were read off disk" in failures[0]
    assert "0 needles read from disk" in report


def test_a_needle_too_short_to_be_evidence_is_refused(tmp_path: Path) -> None:
    """Turns red if: a needle a COMMENT could satisfy is accepted.

    W7's first needle was the bare word ``google``. Review satisfied it by
    appending "google sign-in is still TODO" to ``auth.py``.
    """
    rows, n = _enough_rows(CHECKER.PENDING)
    short = rows + _row("W99", CHECKER.PENDING, f"`ABSENT {_TARGET_NAME} :: google`")
    failures, _ = _run(tmp_path / "a", board=_board_text(short, row_count=n + 1, unpinned=0))
    assert any("is shorter than" in f for f in failures), failures

    # POSITIVE PARTNER: a needle exactly at the floor is accepted, so this is a
    # boundary and not a blanket refusal.
    at_floor = "x" * CHECKER.MIN_NEEDLE_CHARS
    ok = rows + _row("W99", CHECKER.PENDING, f"`ABSENT {_TARGET_NAME} :: {at_floor}`")
    assert _run(tmp_path / "b", board=_board_text(ok, row_count=n + 1, unpinned=0))[0] == []


def test_a_needle_ending_in_a_backtick_is_refused_not_silently_truncated(
    tmp_path: Path,
) -> None:
    """Turns red if: ``_cell`` goes back to stripping a RUN of backticks.

    ``str.strip("`")`` removes every trailing backtick, so a needle whose last
    character was one had it deleted before the refusal could see it -- and the
    gate then verified a shorter string than the row displayed.
    """
    row = _row("W1", CHECKER.PENDING, f"`ABSENT {_TARGET_NAME} :: {_NEEDLE}``")
    parsed = CHECKER.parse_board(_board_text(row, row_count=1, unpinned=0))
    assert parsed.rows[0].evidence.endswith("`"), (
        "the trailing backtick was stripped before the refusal saw it: "
        + repr(parsed.rows[0].evidence)
    )
    failures, _ = _run(tmp_path, board=_board_text(row, row_count=1, unpinned=0))
    assert any("contains a backtick" in f for f in failures), failures


def test_an_evidence_path_that_does_not_exist_is_caught(tmp_path: Path) -> None:
    """Turns red if: a needle against a missing file is treated as satisfied.

    Reading a nonexistent file as "needle absent" would derive a state for every
    row by deleting one character of the path.
    """
    rows, n = _enough_rows(CHECKER.PENDING)
    bad = rows + _row("W99", CHECKER.PENDING, f"`ABSENT no_such_file.txt :: {_NEEDLE}`")
    failures, _ = _run(tmp_path, board=_board_text(bad, row_count=n + 1, unpinned=0))
    assert any("does not exist" in f for f in failures), failures


def test_a_malformed_evidence_cell_is_caught(tmp_path: Path) -> None:
    """Turns red if: an unparseable evidence cell is silently skipped."""
    rows, n = _enough_rows(CHECKER.PENDING)
    bad = rows + _row("W99", CHECKER.PENDING, "`something else entirely`")
    failures, _ = _run(tmp_path, board=_board_text(bad, row_count=n + 1, unpinned=0))
    assert any("is neither" in f for f in failures), failures


def test_a_wrong_row_count_is_caught(tmp_path: Path) -> None:
    """Turns red if: the stated row count stops being compared to the table."""
    rows, n = _enough_rows(CHECKER.PENDING)
    failures, _ = _run(tmp_path, board=_board_text(rows, row_count=n + 1, unpinned=0))
    assert len(failures) == 1, failures
    assert f"says {n + 1} rows" in failures[0] and f"has {n}" in failures[0]


def test_a_wrong_unpinned_count_is_caught(tmp_path: Path) -> None:
    """Turns red if: an unpinned row can be added without editing the sentence.

    The unpinned count is the cap on how much of the board this gate is blind
    to. Unchecked, a future session could unpin every row and stay green.
    """
    rows, n = _enough_rows(CHECKER.PENDING)
    rows += _row("W99", CHECKER.UNPINNED, "`—`")
    failures, _ = _run(tmp_path, board=_board_text(rows, row_count=n + 1, unpinned=0))
    assert len(failures) == 1, failures
    assert "says 0 unpinned rows" in failures[0] and "has 1" in failures[0]


def test_a_deleted_count_sentence_is_caught(tmp_path: Path) -> None:
    """Turns red if: removing the sentence removes the check with it."""
    rows, n = _enough_rows(CHECKER.PENDING)
    board = _board_text(rows, row_count=n, unpinned=0).replace(
        f"The board holds **{n}** rows, **0** of them unpinned.", "gone"
    )
    failures, _ = _run(tmp_path, board=board)
    assert any("no longer states its counts" in f for f in failures), failures


def test_a_duplicate_row_id_is_caught(tmp_path: Path) -> None:
    """Turns red if: two rows can share an id, making one unreferenceable."""
    rows, n = _enough_rows(CHECKER.PENDING)
    rows += _pinned("W1", CHECKER.PENDING)
    failures, _ = _run(tmp_path, board=_board_text(rows, row_count=n + 1, unpinned=0))
    assert any("duplicate row id" in f for f in failures), failures


def test_check_all_reports_the_rows_it_really_parsed_on_a_structure_failure(
    tmp_path: Path,
) -> None:
    """Turns red if: the report line goes back to claiming 0 rows.

    A board with three well-formed rows and a duplicate id printed "0 rows
    parsed" -- a gate stating a false count of its own measurement.
    """
    rows = _pinned("W1", CHECKER.PENDING) + _pinned("W1", CHECKER.PENDING)
    _failures, report = _run(tmp_path, board=_board_text(rows, row_count=2, unpinned=0))
    assert report.startswith("2 rows parsed"), report


# ---------------------------------------------------------------------------
# Freshness.
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


def _sandbox_repo(tmp_path: Path) -> tuple[Path, str]:
    """A throwaway repo whose HEAD has one commit, plus an ORPHAN commit's SHA.

    Built rather than borrowed: the first attempt used the empty-tree object,
    which ``git cat-file -e <sha>^{commit}`` rejects one check EARLIER -- so
    deleting the ancestor check left the test green. Only a real commit on a
    disjoint history reaches the ancestor check at all.
    """
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)

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


def test_a_current_anchor_passes_and_a_stale_one_does_not() -> None:
    """Turns red if: the drift limit stops being enforced.

    Both directions: a limit that never fires and one that always fires are
    equally useless, and only the pair distinguishes them.
    """
    five_back = _head_ancestor(5)
    assert CHECKER.check_freshness(_board_at(five_back), ROOT, 10) == []
    stale = CHECKER.check_freshness(_board_at(five_back), ROOT, 2)
    assert len(stale) == 1, stale
    assert "first-parent commits behind HEAD" in stale[0]


def test_an_anchor_that_is_not_an_ancestor_is_caught(tmp_path: Path) -> None:
    """Turns red if: a real commit from some other history is accepted.

    Without it the drift count is computed against a commit this branch never
    contained, which ``git rev-list`` answers happily.
    """
    repo, orphan = _sandbox_repo(tmp_path)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    # POSITIVE PARTNER, or "rejected" is indistinguishable from "rejects every
    # sandbox".
    assert CHECKER.check_freshness(_board_at(head), repo, 10) == []
    failures = CHECKER.check_freshness(_board_at(orphan), repo, 10)
    assert len(failures) == 1, failures
    assert "is not an ancestor of" in failures[0]


def test_an_anchor_that_names_a_non_commit_object_is_caught() -> None:
    """Turns red if: a tree or blob SHA is accepted as the anchor.

    The empty tree exists in every git repository. This is a DIFFERENT check
    from the ancestor one -- conflating the two hid a surviving mutant once.
    """
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    failures = CHECKER.check_freshness(_board_at(empty_tree), ROOT, 10)
    assert len(failures) == 1, failures
    assert "not in this repository" in failures[0]


def test_an_abbreviated_anchor_is_not_parsed_as_one() -> None:
    """Turns red if: the anchor pattern stops demanding a full 40-hex SHA.

    An abbreviation resolves today and becomes ambiguous as the object store
    grows; the failure then reads as "anchor not in this repository" on a board
    nobody changed.
    """
    full = "0" * 40
    assert CHECKER.parse_board(f"Verified at: `{full}`\n").sha == full
    assert CHECKER.parse_board("Verified at: `0000000`\n").sha is None


def test_a_missing_anchor_line_is_caught() -> None:
    """Turns red if: deleting ``Verified at:`` disables the freshness check."""
    failures = CHECKER.check_freshness(_board_at(None), ROOT, 10)
    assert len(failures) == 1, failures
    assert "no longer records its anchor commit" in failures[0]


def test_check_all_actually_runs_the_freshness_family(tmp_path: Path) -> None:
    """Turns red if: ``check_all`` stops calling ``check_freshness``.

    Every freshness bite-proof drives the function directly, so the CALL from
    ``check_all`` -- the one ``make validate`` reaches -- was pinned by nothing:
    replacing it with ``pass`` left every test green. Found by mutation, not by
    reading.
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

    rows, count = _enough_rows(CHECKER.PENDING)
    (repo / _DOCS).mkdir(parents=True, exist_ok=True)
    (repo / _TARGET_NAME).write_text("nothing here", encoding="utf-8")

    def run_with(sha: str, limit: int) -> list[str]:
        (repo / _DOCS / _BOARD_NAME).write_text(
            _board_text(rows, row_count=count, unpinned=0, sha=sha), encoding="utf-8"
        )
        return list(CHECKER.check_all(repo, limit)[0])

    assert run_with(head, 10) == [], "an anchor at HEAD must pass"
    stale = run_with(first, 1)
    assert len(stale) == 1, stale
    assert "first-parent commits behind HEAD" in stale[0]


def test_freshness_is_skipped_out_loud_where_the_root_is_not_a_working_tree(
    tmp_path: Path,
) -> None:
    """Turns red if: a non-repository root hard-fails or skips silently.

    AGENTS.md rule 12b tells a reviewer to work from a ``git archive`` copy,
    which has no ``.git``; rule 9a records what a phantom failure costs. So the
    family is skipped there -- and the report line SAYS SO, because a silent
    skip is the vacuity this repo's floors exist to prevent.
    """
    rows, n = _enough_rows(CHECKER.PENDING)
    board = _board_text(rows, row_count=n, unpinned=0)
    root = _sandbox(tmp_path / "nogit", board=board)
    assert not CHECKER.has_git_history(root)
    failures, report = CHECKER.check_all(root, 10)
    assert failures == [], failures
    assert "freshness SKIPPED" in report, report

    # POSITIVE PARTNER: a real working tree is NOT skipped.
    assert CHECKER.has_git_history(ROOT)
    assert "freshness SKIPPED" not in CHECKER.check_all(ROOT)[1]


def test_a_directory_merely_INSIDE_a_repository_is_not_treated_as_one(
    tmp_path: Path,
) -> None:
    """Turns red if: ``has_git_history`` goes back to ``rev-parse --git-dir``.

    ``--git-dir`` walks UP through parents, so an unpacked ``git archive`` copy
    sitting anywhere under a repository answers yes -- and the freshness family
    then runs against the WRONG history, producing the exact phantom failure the
    skip exists to prevent. ``--show-toplevel`` compared against the root is the
    fix.
    """
    repo, _orphan = _sandbox_repo(tmp_path)
    inner = repo / "unpacked-copy"
    inner.mkdir()
    assert CHECKER.has_git_history(repo), "the repository root itself must qualify"
    assert not CHECKER.has_git_history(inner), (
        "a subdirectory is inside a repository but is not its working tree root"
    )


# ---------------------------------------------------------------------------
# The wiring. A gate nothing invokes is not a gate.
# ---------------------------------------------------------------------------


def _recipe(target: str) -> list[str]:
    """The tab-indented recipe lines directly under ``target``."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(f"{target}:")]
    assert len(starts) == 1, f"expected one {target}: line, found {starts}"
    body = []
    for line in lines[starts[0] + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    return body


def test_the_gate_is_wired_into_make_validate() -> None:
    """Turns red if: the target is dropped, gutted, or has its exit code ignored.

    ``"check_open_work.py" in makefile`` was the first version of this assertion
    and it was worthless: review replaced the recipe with ``@true``, left the
    script name in an adjacent comment, and every test stayed green. Review then
    defeated the recipe-body version too, with a leading ``-`` -- make's "ignore
    errors" prefix, which discards the gate's exit status.
    """
    makefile = MAKEFILE.read_text(encoding="utf-8")
    prerequisites = [line for line in makefile.splitlines() if line.startswith("validate:")]
    assert len(prerequisites) == 1, f"expected one validate: line, found {prerequisites}"
    assert "open-work-check" in prerequisites[0], (
        "make validate no longer depends on open-work-check: " + prerequisites[0]
    )

    body = _recipe("open-work-check")
    assert body, "open-work-check has an empty recipe -- it would do nothing"
    runner = [line for line in body if "check_open_work.py" in line]
    assert runner, "the open-work-check RECIPE no longer runs the checker: " + repr(body)
    for line in runner:
        # Strip the tab, then make's recipe prefixes. `-` means "ignore the exit
        # status", which silently converts this gate into a no-op.
        assert not line.lstrip("\t").lstrip("@+").startswith("-"), (
            "the recipe ignores the checker's exit status via make's `-` prefix: " + repr(line)
        )
    assert "--check" in " ".join(runner), "the recipe must run the checker in --check mode"


def test_a_writer_target_exists_so_nobody_hand_edits_the_column() -> None:
    """Turns red if: the only way to regenerate the column is to know the script.

    The board and the failure message both tell a reader to run
    ``make open-work-write``. A named command that does not exist sends them
    back to editing the column by hand, which is the thing this design removes.
    """
    body = _recipe("open-work-write")
    assert any("check_open_work.py" in line for line in body), repr(body)
    assert "--check" not in " ".join(body), "the writer must not run in check mode"


@pytest.mark.parametrize("doc", ["docs/session-handoff.md", "docs/00-factory-console.md"])
def test_the_board_is_reachable_from_the_docs_a_session_must_read(doc: str) -> None:
    """Turns red if: a mandatory-reading document stops pointing at the board.

    ``AGENTS.md`` names both as required reading for a new session. A board
    nothing links to is the fifth uncoordinated plan, not a replacement for the
    other four.
    """
    assert _BOARD_NAME in (ROOT / doc).read_text(encoding="utf-8"), (
        f"{doc} does not link to the open-work board"
    )
