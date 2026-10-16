"""Regressions from the narrow re-check of item 1's round 2 fixes (ADR-0169).

The prompt hook ignores two messages from the root prompt check: the floor for
a checkout with no root prompt, and an exemption whose file another checkout
no longer holds. It must ignore those exact messages only, never a message
that merely contains their words, because a prompt's FILE NAME appears inside
the check's messages (Codex re-check, 2026-10-16).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _hook(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    name = "prompt_write_hook_recheck_under_test"
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / "prompt_write_hook.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


def _checkout(path: Path, files: dict[str, str]) -> Path:
    skill = path / ".agents" / "skills" / "work-item-delivery"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    for name, text in files.items():
        (path / name).write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "name",
    [
        "is exempt but does not exist-PROMPT.md",
        "no root prompt file found-PROMPT.md",
    ],
)
def test_a_prompt_named_with_an_ignored_phrase_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # Red when: the hook ignores a message because it CONTAINS (or starts with) the words of an
    # ignored message, so a prompt whose file name holds those words is never reported.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {name: "# Continue\n"})
    state = tmp_path / "state.json"
    first = hook.run_hook([root], state)
    assert first is not None and name in first, first
    again = hook.run_hook([root], state)
    assert again is not None and name in again, again


def test_the_exact_ignored_messages_are_still_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: narrowing the filter stops ignoring the two real messages, so a checkout with no
    # root prompt, or another checkout's missing exempt file, blocks every tool call.
    hook = _hook(monkeypatch)
    empty = _checkout(tmp_path / "empty", {"notes.md": "# notes\n"})
    assert hook.run_hook([empty], tmp_path / "s1.json") is None
    check = hook.check_root_prompts
    gone = sorted(check.EXEMPT)[0]
    good = _checkout(tmp_path / "good", {})
    found = check.problems(good, check.EXEMPT)
    assert f"{gone} is exempt but does not exist; remove it from EXEMPT" in found, found
    assert hook.run_hook([good], tmp_path / "s2.json") is None


def _parked(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    name = "check_parked_work_recheck_under_test"
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / "check_parked_work.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


def test_an_unread_pull_request_list_reads_unknown_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red when: with `gh` unreadable the report still says "0 open pull requests" and lists a
    # branch that has an open draft as a branch with no pull request (completeness critic).
    import datetime

    mod = _parked(monkeypatch)
    entry = mod.ParkedEntry("W1", "draft #5, `b1`", "why", "product owner", "on 2026-01-01")
    rows = {"W1": {"state": "PENDING", "item": "x", "depends": "owner decision"}}
    unread = mod.build_report(
        entries=[entry],
        rows=rows,
        remote_branches=["main", "b1"],
        open_prs=None,
        today=datetime.date(2026, 10, 16),
    )
    text = mod.render(unread)
    assert "0 open pull requests" not in text, text
    assert "unknown open pull requests" in text, text
    assert unread.branches_without_pr == [], unread
    assert text.rstrip().endswith("FAILED"), text
    # Positive partner: with the list read, the same branch with no pull request IS listed.
    read = mod.build_report(
        entries=[entry],
        rows=rows,
        remote_branches=["main", "b1"],
        open_prs=[],
        today=datetime.date(2026, 10, 16),
    )
    assert read.branches_without_pr == ["b1"], read
    assert "0 open pull requests" in mod.render(read)
