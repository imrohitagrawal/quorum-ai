"""The parked-work check (item 1, ADR-0168): ``scripts/check_parked_work.py``.

The board gains a ``## Parked`` table. The check lists remote branches with no
open pull request and parked items whose resume-when has passed, and fails on
an unparked draft, an unparked STOP or owner row, a malformed entry, and on
reading nothing (no branches, no ``gh``, a possibly truncated list, no entries).

No test here touches the network: ``build_report`` and ``render`` are fed data,
and ``main`` runs only with its two module-level gatherers replaced and with
``subprocess.run`` refusing any ``gh`` or ``git ls-remote`` call.
"""

from __future__ import annotations

import datetime
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))
_SCRIPTS = _ROOT / "scripts"
_BOARD = _ROOT / "docs" / "65-open-work.md"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: dataclasses look their module up in sys.modules (#467).
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _mod() -> ModuleType:
    """A fresh copy per test, so a monkeypatched gatherer never leaks."""
    return _load("check_parked_work_under_test", _SCRIPTS / "check_parked_work.py")


def _open_work() -> ModuleType:
    return _load("check_open_work_for_parked_test", _SCRIPTS / "check_open_work.py")


_D = datetime.date

# --------------------------------------------------------------------------
# parse_parked()
# --------------------------------------------------------------------------

_BOARD_TEXT = """# Board

| Row | Item | State | Evidence | Issue | Depends on |
|---|---|---|---|---|---|
| W13 | Nothing bounds a call's INPUT — **STOP** | UNPINNED | `—` | #268 | — |
| W28 | BYOK | PENDING | `—` | — | owner decision |

## Parked

Text before the table.

| Item | Where | Reason | Owner | Resume when |
|---|---|---|---|---|
| `W13` | #268 | needs a money decision | product owner | on 2026-12-01 |
| `W28` | draft #525, `w28/byok-pr1-plan` | waits | product owner | after W71, W72 |

| Item | Where | Reason | Owner | Resume when |
|---|---|---|---|---|
| `W97` | a second table | never read | nobody | on 2026-12-01 |

## Order

| Item | Where | Reason | Owner | Resume when |
|---|---|---|---|---|
| `W98` | after the section | never read | nobody | on 2026-12-01 |
"""


def test_parse_parked_reads_only_the_first_table_under_the_heading() -> None:
    # Red when: parse_parked() returns a row of the board's main table, a row of a second
    # table under the heading or of a table after the next "## " heading, keeps the backticks
    # on the item, or strips the backticks that name a branch in Where.
    mod = _mod()
    assert mod.parse_parked(_BOARD_TEXT) == [
        mod.ParkedEntry(
            item="W13",
            where="#268",
            reason="needs a money decision",
            owner="product owner",
            resume_when="on 2026-12-01",
        ),
        mod.ParkedEntry(
            item="W28",
            where="draft #525, `w28/byok-pr1-plan`",
            reason="waits",
            owner="product owner",
            resume_when="after W71, W72",
        ),
    ]


def test_parse_parked_needs_the_heading_line_exactly() -> None:
    # Red when: parse_parked() accepts "## Parked later" or "### Parked" as the section.
    for heading in ("## Parked later", "### Parked"):
        text = _BOARD_TEXT.replace("## Parked\n", f"{heading}\n")
        assert _mod().parse_parked(text) == [], heading
    # Positive partner: the exact heading parses (two entries).
    assert len(_mod().parse_parked(_BOARD_TEXT)) == 2


# --------------------------------------------------------------------------
# parse_resume_when() and is_due()
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rows", "on"),
    [
        ("after W71", ("W71",), None),
        ("after W71, W72, W73", ("W71", "W72", "W73"), None),
        ("on 2026-11-01", (), _D(2026, 11, 1)),
        ("after W71 or on 2026-11-01", ("W71",), _D(2026, 11, 1)),
        ("on 2026-11-01 or after W71, W72", ("W71", "W72"), _D(2026, 11, 1)),
        ("on 2028-02-29", (), _D(2028, 2, 29)),
    ],
)
def test_resume_when_grammar_accepts(text: str, rows: tuple[str, ...], on: object) -> None:
    # Red when: parse_resume_when() refuses a valid clause or pair, drops or reorders a row,
    # or misreads the date.
    mod = _mod()
    assert mod.parse_resume_when(text) == mod.ResumeWhen(rows=rows, on=on), text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "soon",
        "after",
        "on 2026-13-01",
        "on 2026-02-30",
        "on 2026-1-01",
        "after W1 W2",
        "after W1, on 2026-01-01",
        "on 2026-01-01 or on 2026-02-01",
        "after W1 or after W2",
        "after W71 and on 2026-11-01",
        "after X71",
    ],
)
def test_resume_when_grammar_refuses(text: str) -> None:
    # Red when: parse_resume_when() accepts anything outside "after W<n>(, W<n>)*" and
    # "on <real date>", joined by " or " with at most one of each kind.
    assert _mod().parse_resume_when(text) is None, text


def test_is_due_by_date_turns_on_the_day_itself() -> None:
    # Red when: is_due() fires before the date, or not on the date (> instead of >=).
    mod = _mod()
    rw = mod.ResumeWhen(rows=(), on=_D(2026, 11, 1))
    assert mod.is_due(rw, {}, _D(2026, 10, 31)) is False
    assert mod.is_due(rw, {}, _D(2026, 11, 1)) is True


def test_is_due_by_rows_needs_every_named_row_done() -> None:
    # Red when: is_due() fires when only some named rows are DONE, when a named row is not on
    # the board, or fails to fire when every named row is DONE.
    mod = _mod()
    rw = mod.ResumeWhen(rows=("W71", "W72"), on=None)
    today = _D(2026, 10, 16)
    assert mod.is_due(rw, {"W71": "DONE", "W72": "PENDING"}, today) is False
    assert mod.is_due(rw, {"W71": "DONE"}, today) is False
    assert mod.is_due(rw, {"W71": "DONE", "W72": "DONE"}, today) is True


def test_is_due_with_both_clauses_fires_on_either() -> None:
    # Red when: is_due() needs both clauses ("and") instead of either ("or").
    mod = _mod()
    rw = mod.ResumeWhen(rows=("W71",), on=_D(2026, 11, 1))
    assert mod.is_due(rw, {"W71": "DONE"}, _D(2026, 10, 1)) is True
    assert mod.is_due(rw, {"W71": "PENDING"}, _D(2026, 11, 1)) is True
    assert mod.is_due(rw, {"W71": "PENDING"}, _D(2026, 10, 31)) is False


def test_is_due_with_nothing_named_is_never_due() -> None:
    # Red when: an empty rows tuple counts as "every named row is DONE" (all() over nothing).
    mod = _mod()
    assert mod.is_due(mod.ResumeWhen(rows=(), on=None), {}, _D(2030, 1, 1)) is False


def test_pr_numbers_and_branch_names() -> None:
    # Red when: pr_numbers() misses a "#<digits>" or returns strings; branch_names() misses a
    # backticked token or returns one with its backticks.
    mod = _mod()
    where = "draft #525 and closed #491, `w28/byok-pr1-plan` `proposal/268-x`"
    assert mod.pr_numbers(where) == {525, 491}
    assert mod.branch_names(where) == {"w28/byok-pr1-plan", "proposal/268-x"}
    assert mod.pr_numbers("no number") == set()
    assert mod.branch_names("no branch") == set()


def test_pr_limit_is_500() -> None:
    # Red when: PR_LIMIT changes from the --limit 500 the gh call asks for.
    assert _mod().PR_LIMIT == 500


# --------------------------------------------------------------------------
# build_report(): a clean baseline, then one change per problem class.
# --------------------------------------------------------------------------

_TODAY = _D(2026, 10, 16)


def _rows() -> dict[str, dict[str, str]]:
    return {
        "W13": {
            "state": "UNPINNED",
            "item": "Nothing bounds a call's INPUT — **STOP**",
            "depends": "—",
        },
        "W28": {"state": "PENDING", "item": "BYOK", "depends": "owner decision"},
        "W71": {"state": "DONE", "item": "Security one", "depends": "—"},
        "W72": {"state": "PENDING", "item": "Security two", "depends": "W71"},
    }


def _entry(mod: ModuleType, item: str, where: str, **over: str) -> Any:
    fields = {
        "reason": "waits for something",
        "owner": "product owner",
        "resume_when": "after W71",
    }
    fields.update(over)
    return mod.ParkedEntry(item=item, where=where, **fields)


def _entries(mod: ModuleType) -> list[Any]:
    return [
        _entry(mod, "W13", "#268", resume_when="on 2026-12-01"),
        _entry(mod, "W28", "draft #525, `w28/byok-pr1-plan`", resume_when="after W71, W72"),
    ]


def _prs() -> list[dict[str, Any]]:
    return [
        {"number": 525, "headRefName": "w28/byok-pr1-plan", "isDraft": True},
        {"number": 600, "headRefName": "feature/ready", "isDraft": False},
    ]


def _report(mod: ModuleType, **over: Any) -> Any:
    kwargs: dict[str, Any] = {
        "entries": _entries(mod),
        "rows": _rows(),
        "remote_branches": ["main", "w28/byok-pr1-plan", "old/closed-branch"],
        "open_prs": _prs(),
        "today": _TODAY,
    }
    kwargs.update(over)
    return mod.build_report(**kwargs)


def test_a_consistent_input_has_no_problems_and_reports_its_counts() -> None:
    # Red when: build_report() finds a problem in a consistent input (the positive partner of
    # every problem test below), lists main or a branch with an open PR as without one, or
    # miscounts what it read.
    report = _report(_mod())
    assert report.problems == []
    assert report.branches_without_pr == ["old/closed-branch"]
    assert report.due == []
    assert report.counts == {
        "remote_branches": 3,
        "open_prs": 2,
        "entries": 2,
        "branches_without_pr": 1,
        "due": 0,
    }


def test_branches_without_pr_are_sorted_and_exclude_main_and_any_open_pr() -> None:
    # Red when: branches_without_pr includes main, a draft's or a ready PR's branch, or is
    # not sorted.
    mod = _mod()
    prs = _prs() + [{"number": 601, "headRefName": "beta", "isDraft": False}]
    report = _report(
        mod, remote_branches=["zeta", "main", "beta", "alpha", "w28/byok-pr1-plan"], open_prs=prs
    )
    assert report.branches_without_pr == ["alpha", "zeta"]
    assert report.counts["branches_without_pr"] == 2


def test_due_lists_entries_whose_resume_when_passed_in_entry_order() -> None:
    # Red when: build_report() marks an entry due a day early, misses one whose date came or
    # whose rows all turned DONE, or reorders them.
    mod = _mod()
    assert _report(mod, today=_D(2026, 11, 30)).due == []
    assert _report(mod, today=_D(2026, 12, 1)).due == ["W13"]
    rows = _rows()
    rows["W72"]["state"] = "DONE"
    assert _report(mod, rows=rows).due == ["W28"]
    both = _report(mod, rows=rows, today=_D(2026, 12, 1))
    assert both.due == ["W13", "W28"]
    assert both.counts["due"] == 2
    # Stale items are a list to act on, not a failure.
    assert both.problems == []


def _with_extra_row(
    row_id: str, item: str, depends: str, state: str = "PENDING"
) -> dict[str, dict[str, str]]:
    rows = _rows()
    rows[row_id] = {"state": state, "item": item, "depends": depends}
    return rows


def _one_change(mod: ModuleType, case: str) -> dict[str, Any]:
    """The keyword overrides that introduce exactly one problem."""
    entries = _entries(mod)
    if case == "no-remote-branches":
        return {"remote_branches": None}
    if case == "empty-remote-branches":
        return {"remote_branches": []}
    if case == "no-gh":
        return {"open_prs": None}
    if case == "empty-owner":
        entries[1] = _entry(mod, "W28", entries[1].where, owner="", resume_when="after W71, W72")
        return {"entries": entries}
    if case == "dash-reason":
        entries[0] = _entry(mod, "W13", "#268", reason="—", resume_when="on 2026-12-01")
        return {"entries": entries}
    if case == "bad-resume-when":
        entries[0] = _entry(mod, "W13", "#268", resume_when="soon")
        return {"entries": entries}
    if case == "unknown-item":
        return {"entries": [*entries, _entry(mod, "W999", "nowhere")]}
    if case == "unknown-resume-row":
        entries[1] = _entry(mod, "W28", entries[1].where, resume_when="after W71, W998")
        return {"entries": entries}
    if case == "unparked-draft":
        prs = [*_prs(), {"number": 700, "headRefName": "w70/secret-scan", "isDraft": True}]
        return {"open_prs": prs}
    if case == "unparked-stop":
        return {"rows": _with_extra_row("W14", "Something — **STOP**", "—")}
    if case == "unparked-owner":
        return {"rows": _with_extra_row("W74", "An attack suite", "Owner approval")}
    raise AssertionError(case)


@pytest.mark.parametrize(
    ("case", "needles"),
    [
        ("no-remote-branches", ("remote branches",)),
        ("empty-remote-branches", ("remote branches",)),
        ("no-gh", ("pull requests",)),
        ("empty-owner", ("W28", "owner")),
        ("dash-reason", ("W13", "reason")),
        ("bad-resume-when", ("W13",)),
        ("unknown-item", ("W999",)),
        ("unknown-resume-row", ("W998",)),
        ("unparked-draft", ("#700",)),
        ("unparked-stop", ("W14",)),
        ("unparked-owner", ("W74",)),
    ],
)
def test_each_problem_class_is_exactly_one_message_naming_the_thing(
    case: str, needles: tuple[str, ...]
) -> None:
    # Red when: build_report() stops reporting this class of problem, reports it more than
    # once, or its message stops naming the entry, column, row, PR or input it is about.
    mod = _mod()
    report = _report(mod, **_one_change(mod, case))
    assert len(report.problems) == 1, report.problems
    for needle in needles:
        assert needle.lower() in report.problems[0].lower(), (needle, report.problems)


@pytest.mark.parametrize(
    "rows",
    [
        _with_extra_row("W15", "Finished — **STOP**", "—", state="DONE"),
        _with_extra_row("W16", "Waits on a row", "W39"),
        _with_extra_row("W17", "STOP the bleed, no bold", "—"),
        _with_extra_row("W18", "Owner said done", "owner decision", state="DONE"),
    ],
    ids=["stop-but-done", "depends-on-a-row", "unbolded-stop", "owner-but-done"],
)
def test_rows_that_need_no_entry_are_not_problems(rows: dict[str, dict[str, str]]) -> None:
    # Red when: a DONE row marked **STOP** or waiting on the owner, a row waiting on another
    # row, or a row saying STOP without the bold marker, is demanded a Parked entry.
    assert _report(_mod(), rows=rows).problems == []


def test_a_ready_pr_needs_no_entry_and_a_named_draft_is_parked() -> None:
    # Red when: a non-draft PR is demanded an entry, or a draft named in an entry's Where is
    # reported as unparked (the baseline carries both: #600 ready, #525 named).
    mod = _mod()
    prs = [*_prs(), {"number": 701, "headRefName": "ready/two", "isDraft": False}]
    assert _report(mod, open_prs=prs).problems == []


def test_the_last_of_many_prs_is_still_checked() -> None:
    # Red when: build_report() stops looking for unparked drafts after the first PRs (35 PRs,
    # the unparked draft last, from the plan review).
    mod = _mod()
    prs = [{"number": 1000 + i, "headRefName": f"ready/{i}", "isDraft": False} for i in range(34)]
    prs.append({"number": 735, "headRefName": "draft/last", "isDraft": True})
    report = _report(mod, open_prs=prs)
    assert len(report.problems) == 1, report.problems
    assert "#735" in report.problems[0], report.problems


def test_a_pr_list_at_the_limit_is_refused_as_truncated_and_one_below_is_not() -> None:
    # Red when: build_report() accepts 500 open PRs (gh --limit 500 may have cut the list) or
    # refuses 499 (the boundary moved).
    mod = _mod()
    at_limit = [{"number": i, "headRefName": f"b{i}", "isDraft": False} for i in range(500)]
    report = _report(mod, open_prs=at_limit)
    assert len(report.problems) == 1, report.problems
    assert "truncated" in report.problems[0], report.problems

    below = [{"number": i, "headRefName": f"b{i}", "isDraft": False} for i in range(499)]
    assert _report(mod, open_prs=below).problems == []


def test_no_entries_is_refused() -> None:
    # Red when: build_report() passes with zero Parked entries (the check measured nothing).
    mod = _mod()
    rows = {"W1": {"state": "DONE", "item": "done thing", "depends": "—"}}
    prs = [{"number": 600, "headRefName": "feature/ready", "isDraft": False}]
    report = _report(mod, entries=[], rows=rows, open_prs=prs)
    assert len(report.problems) == 1, report.problems
    assert "Parked" in report.problems[0], report.problems
    # Positive partner: the same input with one valid entry passes. The row is not DONE here:
    # a Parked line for a DONE row is itself a problem (review round 1, F5).
    one = [_entry(mod, "W1", "#1", resume_when="on 2026-12-01")]
    pending = {"W1": {**rows["W1"], "state": "PENDING"}}
    assert _report(mod, entries=one, rows=pending, open_prs=prs).problems == []


# --------------------------------------------------------------------------
# render() and main()
# --------------------------------------------------------------------------


def test_render_ends_failed_and_shows_lists_and_problems() -> None:
    # Red when: render() drops a branch, a due item or a problem, or its last line is not
    # FAILED when there are problems.
    mod = _mod()
    report = mod.Report(
        branches_without_pr=["old/closed-branch"],
        due=["W13"],
        problems=["W999 is not a board row"],
        counts={
            "remote_branches": 3,
            "open_prs": 2,
            "entries": 2,
            "branches_without_pr": 1,
            "due": 1,
        },
    )
    text = mod.render(report)
    assert text.rstrip("\n").splitlines()[-1].strip() == "FAILED", text
    for shown in ("old/closed-branch", "W13", "W999 is not a board row"):
        assert shown in text, (shown, text)


def test_render_ends_passed_and_shows_every_count() -> None:
    # Red when: render() says anything but PASSED last for a clean report, or leaves out a
    # count (a check that read nothing must not look like one that read everything).
    mod = _mod()
    counts = {
        "remote_branches": 17,
        "open_prs": 23,
        "entries": 31,
        "branches_without_pr": 41,
        "due": 53,
    }
    text = mod.render(mod.Report(branches_without_pr=[], due=[], problems=[], counts=counts))
    assert text.rstrip("\n").splitlines()[-1].strip() == "PASSED", text
    for value in (17, 23, 31, 41, 53):
        assert re.search(rf"\b{value}\b", text), (value, text)


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any gh or git ls-remote call fail the test."""
    real_run = subprocess.run

    def guarded(args: Any, *a: Any, **k: Any) -> Any:
        words = [str(w) for w in (args if isinstance(args, (list, tuple)) else [args])]
        if words and (Path(words[0]).name == "gh" or "ls-remote" in words):
            raise AssertionError(f"network call in a test: {words}")
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", guarded)


@pytest.mark.parametrize(
    ("branches", "prs", "needle"),
    [(None, [], "remote branches"), (["main", "x"], None, "pull requests")],
    ids=["no-branches", "no-gh"],
)
def test_main_exits_1_when_a_gatherer_read_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    branches: Any,
    prs: Any,
    needle: str,
) -> None:
    # Red when: main() exits 0, or prints anything but FAILED last, when git or gh could not
    # be read (the empty-input floor), or calls the network itself.
    _no_network(monkeypatch)
    mod = _mod()
    monkeypatch.setattr(mod, "remote_branches", lambda *a, **k: branches)
    monkeypatch.setattr(mod, "open_pull_requests", lambda *a, **k: prs)
    capsys.readouterr()
    assert mod.main([]) == 1
    out = capsys.readouterr().out
    assert out.rstrip("\n").splitlines()[-1].strip() == "FAILED", out
    assert needle in out, out


# --------------------------------------------------------------------------
# The real board (no git, no network).
# --------------------------------------------------------------------------


def test_the_real_board_parked_table_parses_and_names_real_rows() -> None:
    # Red when: docs/65-open-work.md loses its ## Parked table, an entry's resume-when does
    # not parse, or an entry (or a row its resume-when waits for) is not a board row.
    mod = _mod()
    text = _BOARD.read_text(encoding="utf-8")
    entries = mod.parse_parked(text)
    assert len(entries) >= 1, "no Parked entry parsed from the real board"
    row_ids = {row.row_id for row in _open_work().parse_board(text).rows}
    assert len(row_ids) > 50, f"only {len(row_ids)} board rows parsed"
    for entry in entries:
        rw = mod.parse_resume_when(entry.resume_when)
        assert rw is not None, entry
        assert entry.item in row_ids, entry
        assert set(rw.rows) <= row_ids, entry


def test_main_passes_on_the_real_board_with_consistent_github_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: the real board has a STOP or owner-waiting row with no Parked entry, or an
    # entry the check refuses, or main() exits 1 on an input with no problem. The GitHub side
    # is built FROM the board's own entries, so only the board can make this red.
    _no_network(monkeypatch)
    mod = _mod()
    entries = mod.parse_parked(_BOARD.read_text(encoding="utf-8"))
    assert entries, "no Parked entry parsed from the real board"
    numbers = sorted({n for e in entries for n in mod.pr_numbers(e.where)})
    branches = ["main", *sorted({b for e in entries for b in mod.branch_names(e.where)})]
    prs = [{"number": n, "headRefName": f"pr-{n}", "isDraft": True} for n in numbers]
    monkeypatch.setattr(mod, "remote_branches", lambda *a, **k: list(branches))
    monkeypatch.setattr(mod, "open_pull_requests", lambda *a, **k: list(prs))
    capsys.readouterr()
    code = mod.main([])
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.rstrip("\n").splitlines()[-1].strip() == "PASSED", out


@pytest.mark.repo_introspection
def test_make_parked_check_runs_the_script() -> None:
    # Red when: the Makefile has no parked-check target, or it stops running
    # scripts/check_parked_work.py.
    proc = subprocess.run(
        ["make", "-n", "parked-check"], cwd=_ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert "scripts/check_parked_work.py" in proc.stdout, proc.stdout
