"""Item 1, review round 1: one regression test per reproduced finding.

C1 to C9 are code defects the round found; F1 to F5 are tests the
falsification lens showed were missing (a mutation stayed green). Every test
loads its script by path, inside the test, and touches no network.
"""

from __future__ import annotations

import datetime
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))
_SCRIPTS = _ROOT / "scripts"

_PROCESS = "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`."
_SECTIONS = (
    "## Read first\n\nx\n\n## The items, in order\n\nx\n\n"
    "## Approvals\n\nx\n\n## End of session\n\nx\n"
)
_GOOD = f"# Continue\n\n{_PROCESS}\n\n{_SECTIONS}"
_NO_PROCESS = f"# Continue\n\nNo process line here.\n\n{_SECTIONS}"
_NAME = "CONTINUE-X-W1-PROMPT.md"
_ALL = ["Read first", "The items, in order", "Approvals", "End of session"]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _check() -> ModuleType:
    return _load("check_root_prompts_r1", _SCRIPTS / "check_root_prompts.py")


def _hook(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load("prompt_write_hook_r1", _SCRIPTS / "prompt_write_hook.py")
    monkeypatch.setattr(module.check_root_prompts, "EXEMPT", {})
    return module


def _parked() -> ModuleType:
    return _load("check_parked_work_r1", _SCRIPTS / "check_parked_work.py")


def _handoff() -> ModuleType:
    return _load("session_handoff_r1", _SCRIPTS / "session_handoff.py")


def _checkout(path: Path, prompts: dict[str, str] | None = None, *, python: bool = True) -> Path:
    skill = path / ".agents" / "skills" / "work-item-delivery" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# skill\n", encoding="utf-8")
    if python:
        venv = path / ".venv" / "bin" / "python"
        venv.parent.mkdir(parents=True)
        venv.write_text("", encoding="utf-8")
    for name, text in (prompts or {}).items():
        (path / name).write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# C1: a failed shell call is a PostToolUseFailure event, not PostToolUse.
# --------------------------------------------------------------------------


def test_c1_install_adds_the_entry_for_failed_tool_calls_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: --install writes the entry only under PostToolUse, so a prompt written by a
    # shell call that then exits non-zero (PostToolUseFailure) is never checked; or
    # is_installed() reads True with only one of the two entries present.
    hook = _hook(monkeypatch)
    checkout = _checkout(tmp_path / "co")
    settings = checkout / ".claude" / "settings.json"
    assert hook.install(settings) is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    post = data["hooks"]["PostToolUse"]
    failure = data["hooks"]["PostToolUseFailure"]
    assert len(post) == 1 and failure == post, data
    assert hook.is_installed(settings) is True
    del data["hooks"]["PostToolUseFailure"]
    settings.write_text(json.dumps(data), encoding="utf-8")
    assert hook.is_installed(settings) is False


def test_c1_a_failure_event_gets_additional_context_not_a_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: main() answers a PostToolUseFailure event with {"decision": "block"} (which
    # that event does not read), or stops answering PostToolUse (and unreadable input) with it.
    hook = _hook(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    project = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})
    env = {"CLAUDE_PROJECT_DIR": str(project)}

    capsys.readouterr()
    event = json.dumps({"hook_event_name": "PostToolUseFailure", "tool_name": "Bash"})
    assert hook.main([], stdin=io.StringIO(event), env=env) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == {"hookSpecificOutput"}, printed
    assert printed["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure", printed
    assert _NAME in printed["hookSpecificOutput"]["additionalContext"], printed

    # Positive partners: PostToolUse and unparseable stdin still get the block decision.
    for stdin in (json.dumps({"hook_event_name": "PostToolUse"}), "{not json"):
        assert hook.main([], stdin=io.StringIO(stdin), env=env) == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["decision"] == "block" and _NAME in printed["reason"], printed


# --------------------------------------------------------------------------
# C2: a self-closing NON-void tag stays open in a browser.
# --------------------------------------------------------------------------


def test_c2_self_closing_div_hides_the_headings_after_it() -> None:
    # Red when: missing_sections() treats "<div hidden />" as closed at once, so the four
    # headings a browser hides inside it count as visible.
    check = _check()
    hidden = f"# C\n\n{_PROCESS}\n\n<div hidden />\n\n{_SECTIONS}\n</div>\n"
    assert check.missing_sections(hidden) == _ALL
    # Positive partner: a void self-closing tag ("<hr />") hides nothing.
    shown = f"# C\n\n{_PROCESS}\n\n<hr />\n\n{_SECTIONS}"
    assert check.missing_sections(shown) == []


def test_c2_self_closing_div_hides_the_process_line_after_it() -> None:
    # Red when: has_process_line() treats "<div hidden />" as closed at once, so a Process
    # line a browser hides inside it counts as visible.
    check = _check()
    assert check.has_process_line(f"# C\n\n<div hidden />\n\n{_PROCESS}\n\n</div>\n") is False
    # Positive partner: after a void "<br />" block the line still counts.
    assert check.has_process_line(f"# C\n\n<br />\n\n{_PROCESS}\n") is True


# --------------------------------------------------------------------------
# C3 and C7/F5: the parked-work check.
# --------------------------------------------------------------------------

_BOARD = """# Board

| Row | Item | State | Evidence | Issue | Depends on |
|---|---|---|---|---|---|
| W90 | Unreadable | PENDING | `ABSENT no/such/file_r1.py :: a needle that is long enough` | — | — |
| W91 | Readable | PENDING | `ABSENT scripts/check_parked_work.py :: no such text here zq` | — | — |
"""


def _entry(mod: ModuleType, item: str, resume_when: str) -> Any:
    return mod.ParkedEntry(
        item=item, where="#1", reason="waits", owner="product owner", resume_when=resume_when
    )


def _build(mod: ModuleType, entries: list[Any], rows: dict[str, dict[str, Any]]) -> Any:
    return mod.build_report(
        entries=entries,
        rows=rows,
        remote_branches=["main"],
        open_prs=[{"number": 1, "headRefName": "x", "isDraft": True}],
        today=datetime.date(2026, 10, 16),
    )


def test_c3_a_row_whose_evidence_cannot_be_read_is_a_problem() -> None:
    # Red when: board_rows() drops derive_states() failures, so a resume-when naming a row
    # whose evidence cannot be read is silently "not due" and the check passes.
    mod = _parked()
    rows = mod.board_rows(_BOARD)
    report = _build(mod, [_entry(mod, "W91", "after W90")], rows)
    named = [p for p in report.problems if "W90" in p]
    assert len(named) == 1 and "no/such/file_r1.py" in named[0], report.problems
    # Positive partner: the readable row derives a state and raises no problem.
    assert rows["W91"]["state"] == "PENDING", rows
    assert not [p for p in report.problems if "W91" in p], report.problems


def _clean_rows() -> dict[str, dict[str, Any]]:
    return {
        "W1": {"state": "PENDING", "item": "a", "depends": "—"},
        "W2": {"state": "PENDING", "item": "b", "depends": "—"},
        "W3": {"state": "DONE", "item": "c", "depends": "—"},
    }


def test_f5_a_duplicate_parked_line_is_a_problem() -> None:
    # Red when: build_report() accepts two Parked lines for the same row.
    mod = _parked()
    twice = _build(
        mod, [_entry(mod, "W1", "after W2"), _entry(mod, "W1", "after W2")], _clean_rows()
    )
    assert [p for p in twice.problems if "W1" in p and "more than once" in p], twice.problems
    # Positive partner: one line for the row is clean.
    once = _build(mod, [_entry(mod, "W1", "after W2")], _clean_rows())
    assert once.problems == [], once.problems


def test_f5_a_resume_when_naming_its_own_row_is_a_problem() -> None:
    # Red when: build_report() accepts "after W1" on W1's own Parked line (it can only come due
    # once the parked work itself is done).
    mod = _parked()
    report = _build(mod, [_entry(mod, "W1", "after W1")], _clean_rows())
    assert [p for p in report.problems if "W1" in p and "its own row" in p], report.problems


def test_f5_a_parked_line_for_a_done_row_is_a_problem() -> None:
    # Red when: build_report() keeps a Parked line for a row that already reads DONE.
    mod = _parked()
    report = _build(mod, [_entry(mod, "W3", "after W2")], _clean_rows())
    assert [p for p in report.problems if "W3" in p and "DONE" in p], report.problems


# --------------------------------------------------------------------------
# C4: a failed state write must not lose the reason.
# --------------------------------------------------------------------------


def test_c4_a_state_write_that_fails_still_returns_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: run_hook() lets an OSError from writing its state escape, so the bad prompt's
    # reason is lost in main()'s generic handler.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})
    blocker = tmp_path / "state-is-a-file"
    blocker.write_text("x", encoding="utf-8")
    reason = hook.run_hook([root], blocker / "prompt-hook.json")
    assert reason is not None and _NAME in reason, reason


# --------------------------------------------------------------------------
# C5: no paste line for a prompt that fails the check.
# --------------------------------------------------------------------------


def test_c5_a_failing_prompt_gets_no_paste_line(tmp_path: Path) -> None:
    # Red when: paste_lines() or the handoff's "Next session" section offers a paste line for
    # a validly named prompt that fails the check, or stops saying it must be fixed first.
    root = tmp_path / "root"
    root.mkdir()
    (root / _NAME).write_text(_NO_PROCESS, encoding="utf-8")
    assert _check().paste_lines(root) == []
    section = _handoff()._next_session_section(root)
    assert "follow it exactly" not in section, section
    assert f"{_NAME} fails `make prompt-check`" in section, section
    # Positive partner: once fixed, the paste line is back.
    (root / _NAME).write_text(_GOOD, encoding="utf-8")
    assert _check().paste_lines(root) == [
        "Read CONTINUE-X-W1-PROMPT.md in the repo root and follow it exactly."
    ]


# --------------------------------------------------------------------------
# C6: the hook command needs the checkout's .venv/bin/python.
# --------------------------------------------------------------------------


def test_c6_check_installed_needs_the_venv_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: --check-installed says "installed" for a checkout whose .venv/bin/python is
    # missing (the hook command would fail on every tool call).
    hook = _hook(monkeypatch)
    checkout = _checkout(tmp_path / "co", python=False)
    hook.install(checkout / ".claude" / "settings.json")
    capsys.readouterr()
    assert hook.main(["--check-installed", str(checkout)], stdin=io.StringIO(""), env={}) == 1
    assert capsys.readouterr().out.strip() == "not installed: no .venv/bin/python"
    # Positive partner: with the interpreter present it reads as installed.
    (checkout / ".venv" / "bin").mkdir(parents=True)
    (checkout / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    assert hook.main(["--check-installed", str(checkout)], stdin=io.StringIO(""), env={}) == 0
    assert capsys.readouterr().out.strip() == "installed"


# --------------------------------------------------------------------------
# C8: the CI test's tracked-prompt filter must match find_prompt_files().
# --------------------------------------------------------------------------


def test_c8_the_ci_filter_sees_an_upper_case_md_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: test_every_tracked_root_prompt_carries_the_line_or_is_exempt filters tracked
    # names with a case-sensitive ".md", so a committed NEXT-PROMPT.MD escapes CI.
    ci = _load("test_root_prompt_check_r1", _ROOT / "tests" / "unit" / "test_root_prompt_check.py")
    fake = tmp_path / "repo"
    fake.mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (fake / _NAME).write_text(_GOOD, encoding="utf-8")
    listed = [_NAME]

    def ls_files(*a: Any, **k: Any) -> subprocess.CompletedProcess[str]:
        # NUL-separated, as `git ls-files -z` prints (review round 2, D4).
        return subprocess.CompletedProcess(a[0], 0, stdout="\0".join(listed) + "\0", stderr="")

    monkeypatch.setattr(ci, "_ROOT", fake)
    monkeypatch.setattr(ci.subprocess, "run", ls_files)
    # Positive partner: a clean tracked set passes.
    ci.test_every_tracked_root_prompt_carries_the_line_or_is_exempt(tmp_path / "a")
    (fake / "NEXT-PROMPT.MD").write_text(_NO_PROCESS, encoding="utf-8")
    listed.append("NEXT-PROMPT.MD")
    with pytest.raises(AssertionError):
        ci.test_every_tracked_root_prompt_carries_the_line_or_is_exempt(tmp_path / "b")


# --------------------------------------------------------------------------
# C9: the hook never raises, even without markdown_it.
# --------------------------------------------------------------------------


def test_c9_the_hook_imports_and_exits_0_without_markdown_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: prompt_write_hook.py loads check_root_prompts (and so markdown_it) at import,
    # outside main()'s try, so an interpreter without markdown_it raises instead of exiting 0.
    monkeypatch.setitem(sys.modules, "markdown_it", None)  # makes the import raise
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    project = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})
    hook = _load("prompt_write_hook_r1_no_md", _SCRIPTS / "prompt_write_hook.py")
    capsys.readouterr()
    code = hook.main([], stdin=io.StringIO("{}"), env={"CLAUDE_PROJECT_DIR": str(project)})
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out == "", captured.out
    assert "skipped" in captured.err and "markdown_it" in captured.err, captured.err


# --------------------------------------------------------------------------
# F1 to F4: tests the falsification lens found missing.
# --------------------------------------------------------------------------


def test_f1_gh_pr_list_is_asked_for_500(monkeypatch: pytest.MonkeyPatch) -> None:
    # Red when: open_pull_requests() drops "--limit 500" (gh then returns 30 at most, and a
    # draft past the 30th goes unseen while the truncation floor never fires).
    mod = _parked()
    seen: list[list[str]] = []

    def fake(args: list[str], *a: Any, **k: Any) -> subprocess.CompletedProcess[str]:
        seen.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    assert mod.open_pull_requests() == []
    assert len(seen) == 1, seen
    args = seen[0]
    assert args[:3] == ["gh", "pr", "list"], args
    assert args[args.index("--limit") + 1] == "500", args
    assert args[args.index("--state") + 1] == "open", args


def test_f2_a_hidden_span_inside_a_heading_does_not_count() -> None:
    # Red when: missing_sections() reads the text of a heading whose words sit in a hidden
    # <span>, so "## <span style=...>Approvals</span>" counts as the Approvals section.
    check = _check()
    hidden = _GOOD.replace("## Approvals", '## <span style="display:none">Approvals</span>')
    assert check.missing_sections(hidden) == ["Approvals"]
    # Positive partner: the plain heading counts.
    assert check.missing_sections(_GOOD) == []


def test_f3_section_names_match_case_exactly() -> None:
    # Red when: missing_sections() matches section names without regard to case.
    check = _check()
    assert check.missing_sections(_GOOD.replace("## Approvals", "## approvals")) == ["Approvals"]


def test_f4_the_parked_report_sits_in_a_text_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    # Red when: _parked_section() stops fencing the report in a ```text block (ADR-0162 reads
    # a fence as quoted tool output; unfenced, "PASSED" is a bare completion word).
    handoff = _handoff()

    class Fake:
        @staticmethod
        def report() -> str:
            return "r"

        @staticmethod
        def render(_r: str) -> str:
            return "Parked work check: counts\nPASSED\n"

    monkeypatch.setattr(handoff, "_load_script", lambda name: Fake)
    lines = handoff._parked_section().splitlines()
    i = lines.index("```text")
    assert lines[i + 1 :] == ["Parked work check: counts", "PASSED", "```"], lines
