"""The prompt write hook (item 1, ADR-0169): ``scripts/prompt_write_hook.py``.

A PostToolUse hook that does NOT trust the tool's input: on every call it lists
the root prompt files of each checkout of this repository, compares their
SHA-256 of its content with a saved state, and runs the root prompt check only on
roots whose prompts changed (or on every root while the last result failed).
A failure prints ``{"decision": "block", "reason": ...}``; the hook always
exits 0 and never raises.

Every checkout here is a temporary directory; no test reads this repository
through git, and no test touches the network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))
_SCRIPT = _ROOT / "scripts" / "prompt_write_hook.py"

_PROCESS = "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`."
_SECTIONS = (
    "## Read first\n\nx\n\n## The items, in order\n\nx\n\n"
    "## Approvals\n\nx\n\n## End of session\n\nx\n"
)
_GOOD = f"# Continue\n\n{_PROCESS}\n\n{_SECTIONS}"
_NO_PROCESS = f"# Continue\n\nNo process line here at all.\n\n{_SECTIONS}"
_NAME = "CONTINUE-X-W1-PROMPT.md"
_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|Bash"


def _hook(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """A fresh copy per test. The real EXEMPT names a file no temporary checkout holds, so it
    is emptied on the check module the hook uses; this neutralises it, it is not an expected
    value."""
    spec = importlib.util.spec_from_file_location("prompt_write_hook_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.check_root_prompts, "EXEMPT", {})
    return module


def _checkout(path: Path, prompts: dict[str, str] | None = None) -> Path:
    """A directory that looks like a checkout of this repository."""
    skill = path / ".agents" / "skills" / "work-item-delivery" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# skill\n", encoding="utf-8")
    for name, text in (prompts or {}).items():
        (path / name).write_text(text, encoding="utf-8")
    return path


def _count_problems(monkeypatch: pytest.MonkeyPatch, hook: ModuleType) -> list[Path]:
    """Wrap the real problems() so each call is recorded; returns the list of roots checked."""
    calls: list[Path] = []
    real: Callable[..., list[str]] = hook.check_root_prompts.problems

    def counting(root: Path, exempt: dict[str, str]) -> list[str]:
        calls.append(root)
        return real(root, exempt)

    monkeypatch.setattr(hook.check_root_prompts, "problems", counting)
    return calls


# --------------------------------------------------------------------------
# run_hook()
# --------------------------------------------------------------------------


def test_a_bad_prompt_written_by_a_shell_gives_a_reason_and_fixing_it_clears_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: run_hook() relies on a tool's file_path (a plain file write, no tool input,
    # goes unseen), its reason drops the file or the problem or the closing instruction, or
    # it keeps blocking after the prompt is fixed.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})
    state = tmp_path / "state" / "prompt-hook.json"

    reason = hook.run_hook([root], state)
    assert reason is not None
    assert _NAME in reason, reason
    for message in hook.check_root_prompts.problems(root, {}):
        assert message in reason, (message, reason)
    assert reason.rstrip().endswith("Run make prompt-check."), reason

    (root / _NAME).write_text(_GOOD, encoding="utf-8")
    assert hook.run_hook([root], state) is None


def test_a_missing_section_is_named_in_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: the hook runs only the Process-line check and not the section check.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _GOOD.replace("## Approvals\n", "")})
    reason = hook.run_hook([root], tmp_path / "state.json")
    assert reason is not None and "Approvals" in reason, reason


def test_a_passing_prompt_gives_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Red when: run_hook() blocks on a valid prompt.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _GOOD})
    calls = _count_problems(monkeypatch, hook)
    assert hook.run_hook([root], tmp_path / "state.json") is None
    # Partner: the check really ran on the first call (no saved state).
    assert calls == [root]


def test_a_root_with_no_prompt_files_is_not_a_problem_for_the_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: the hook blocks every tool call in a checkout that has no root prompt (it
    # passes on the check's "no root prompt file found" floor).
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {"notes.md": "# notes\n"})
    assert hook.run_hook([root], tmp_path / "state.json") is None


def test_nothing_changed_and_last_result_passing_skips_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: run_hook() re-runs the check on every tool call although no prompt's content
    # changed since a passing result.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _GOOD})
    state = tmp_path / "state.json"
    assert hook.run_hook([root], state) is None
    calls = _count_problems(monkeypatch, hook)
    assert hook.run_hook([root], state) is None
    assert calls == []


def test_while_failing_every_call_rechecks_even_with_no_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: run_hook() goes quiet after reporting a failure once (the next call, with no
    # change, skips the check and returns None while the prompt is still bad).
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})
    state = tmp_path / "state.json"
    assert hook.run_hook([root], state) is not None
    calls = _count_problems(monkeypatch, hook)
    again = hook.run_hook([root], state)
    assert again is not None and _NAME in again, again
    assert calls == [root]


def test_a_removed_prompt_is_a_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Red when: run_hook() notices only changed or added signatures, not a removed one.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _GOOD, "CONTINUE-Y-W2-PROMPT.md": _GOOD})
    state = tmp_path / "state.json"
    assert hook.run_hook([root], state) is None
    (root / "CONTINUE-Y-W2-PROMPT.md").unlink()
    calls = _count_problems(monkeypatch, hook)
    assert hook.run_hook([root], state) is None
    assert calls == [root]


def test_an_unreadable_state_counts_as_everything_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: a corrupt state file raises, or is read as "nothing changed" so a bad prompt
    # goes unchecked; or run_hook() stops writing the state it is documented to write.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})
    state = tmp_path / "state.json"
    state.write_text("{not json", encoding="utf-8")
    calls = _count_problems(monkeypatch, hook)
    assert hook.run_hook([root], state) is not None
    assert calls == [root]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["failing"] is True, saved
    assert str(root / _NAME) in saved["signatures"], saved

    (root / _NAME).write_text(_GOOD, encoding="utf-8")
    assert hook.run_hook([root], state) is None
    assert json.loads(state.read_text(encoding="utf-8"))["failing"] is False


def test_only_the_changed_root_is_checked_and_only_the_bad_file_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: run_hook() checks only the first root, names a passing file as failing, or
    # re-checks a root whose prompts did not change.
    hook = _hook(monkeypatch)
    good = _checkout(tmp_path / "good", {_NAME: _GOOD})
    bad = _checkout(tmp_path / "bad", {"CONTINUE-Z-W3-PROMPT.md": _GOOD})
    state = tmp_path / "state.json"
    calls = _count_problems(monkeypatch, hook)
    assert hook.run_hook([good, bad], state) is None
    assert sorted(calls) == sorted([good, bad])

    calls.clear()
    (bad / "CONTINUE-Z-W3-PROMPT.md").write_text(_NO_PROCESS, encoding="utf-8")
    reason = hook.run_hook([good, bad], state)
    assert reason is not None and "CONTINUE-Z-W3-PROMPT.md" in reason, reason
    assert _NAME not in reason, reason
    assert calls == [bad]


def test_signatures_cover_root_prompt_files_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: signatures() skips a lower-case prompt name, includes a non-prompt file, a
    # non-.md file or a prompt in a subdirectory, or records anything but the SHA-256 hex
    # digest of the file's bytes (Codex, plan re-check: size and mtime can be kept by an edit).
    hook = _hook(monkeypatch)
    root = _checkout(
        tmp_path / "co",
        {_NAME: _GOOD, "x-prompt.md": "short\n", "notes.md": "n\n", "prompt.txt": "t\n"},
    )
    (root / "docs").mkdir()
    (root / "docs" / "CONTINUE-Q-W9-PROMPT.md").write_text(_GOOD, encoding="utf-8")
    found = hook.signatures([root])
    expected = {}
    for name in (_NAME, "x-prompt.md"):
        expected[str(root / name)] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    assert found == expected


def test_an_edit_that_keeps_size_and_mtime_is_still_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: run_hook() compares size and mtime instead of content, so a shell edit that
    # swaps in a bad prompt of the same length and puts the old mtime back goes unchecked.
    hook = _hook(monkeypatch)
    root = _checkout(tmp_path / "co", {_NAME: _GOOD})
    path = root / _NAME
    state = tmp_path / "state.json"
    assert hook.run_hook([root], state) is None
    before = os.stat(path)
    bad = _GOOD.replace("**Process:**", "**Pr0cess:**")
    assert len(bad.encode()) == len(_GOOD.encode()) and bad != _GOOD
    path.write_text(bad, encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = os.stat(path)
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    reason = hook.run_hook([root], state)
    assert reason is not None and _NAME in reason, reason


# --------------------------------------------------------------------------
# checkout_roots()
# --------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_checkout_roots_lists_each_worktree_that_holds_the_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: checkout_roots() returns only the project directory (misses a sibling
    # worktree, so a prompt written there is never checked), or keeps a worktree that does
    # not hold the work-item-delivery skill.
    hook = _hook(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("r\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "first")
    _git(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "old"), "HEAD")
    _checkout(repo)
    _git(repo, "add", ".agents")
    _git(repo, "commit", "-q", "-m", "skill")
    _git(repo, "worktree", "add", "-q", "-b", "side", str(tmp_path / "side"))

    roots = {p.resolve() for p in hook.checkout_roots(repo)}
    assert roots == {repo.resolve(), (tmp_path / "side").resolve()}, roots


def test_checkout_roots_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Red when: checkout_roots() returns nothing for a checkout git cannot read (the hook
    # would then check nothing), or returns a directory that does not hold the skill.
    hook = _hook(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    holds = _checkout(tmp_path / "holds")
    assert hook.checkout_roots(holds) == [holds]
    bare = tmp_path / "bare"
    bare.mkdir()
    assert hook.checkout_roots(bare) == []


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------


def _main(hook: ModuleType, project: Path, stdin_text: str) -> int:
    code: int = hook.main(
        [], stdin=io.StringIO(stdin_text), env={"CLAUDE_PROJECT_DIR": str(project)}
    )
    return code


def test_main_prints_a_block_decision_for_a_bad_prompt_and_nothing_for_a_good_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: main() prints anything but {"decision": "block", "reason": ...} JSON naming the
    # bad file, returns non-zero, keeps its state anywhere but .claude/state/prompt-hook.json,
    # or prints a block for a good prompt.
    hook = _hook(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    project = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})
    tool_call = json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat > x"}})
    capsys.readouterr()
    assert _main(hook, project, tool_call) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["decision"] == "block", printed
    assert _NAME in printed["reason"], printed
    assert (project / ".claude" / "state" / "prompt-hook.json").is_file()

    (project / _NAME).write_text(_GOOD, encoding="utf-8")
    assert _main(hook, project, "") == 0
    assert capsys.readouterr().out.strip() == ""


def test_main_returns_0_when_run_hook_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: an exception inside the hook escapes main() or makes it return non-zero (a
    # broken hook must never break the session), or it is swallowed without a note.
    hook = _hook(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    project = _checkout(tmp_path / "co", {_NAME: _NO_PROCESS})

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(hook, "run_hook", boom)
    capsys.readouterr()
    assert _main(hook, project, "{}") == 0
    captured = capsys.readouterr()
    assert "block" not in captured.out, captured.out
    assert captured.err.strip() != "", "no note on stderr"


# --------------------------------------------------------------------------
# --install and --check-installed
# --------------------------------------------------------------------------

_EXISTING: dict[str, Any] = {
    "permissions": {"deny": ["Bash(git push:*)"], "allow": ["Bash(ls:*)"]},
    "env": {"FOO": "1"},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
        "PostToolUse": [
            {"matcher": "Write", "hooks": [{"type": "command", "command": "echo other"}]}
        ],
    },
}


def _ours(hook: ModuleType) -> dict[str, Any]:
    return {
        "matcher": _MATCHER,
        "hooks": [{"type": "command", "command": hook.HOOK_COMMAND, "timeout": 30}],
    }


def test_hook_command_runs_this_script_from_the_project_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red when: HOOK_COMMAND stops naming the tracked script or stops resolving it from
    # $CLAUDE_PROJECT_DIR (a relative path breaks when the session's cwd moves).
    command = _hook(monkeypatch).HOOK_COMMAND
    assert "scripts/prompt_write_hook.py" in command, command
    assert "$CLAUDE_PROJECT_DIR" in command, command


def test_install_into_a_checkout_with_no_settings_creates_one_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: --install fails without an existing .claude/ directory, writes a different
    # matcher, command or timeout, or --check-installed misreports either state.
    hook = _hook(monkeypatch)
    checkout = _checkout(tmp_path / "co")
    settings = checkout / ".claude" / "settings.json"
    capsys.readouterr()
    assert hook.main(["--check-installed", str(checkout)], stdin=io.StringIO(""), env={}) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1] == "not installed"
    assert hook.is_installed(settings) is False

    assert hook.main(["--install", str(checkout)], stdin=io.StringIO(""), env={}) == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"]["PostToolUse"] == [_ours(hook)], data
    assert hook.is_installed(settings) is True

    capsys.readouterr()
    assert hook.main(["--check-installed", str(checkout)], stdin=io.StringIO(""), env={}) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "installed"


def test_install_keeps_every_other_setting_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: install() drops or rewrites another key or hook (W81's deny rules live in the
    # same file), or a second run adds a second entry or rewrites the file.
    hook = _hook(monkeypatch)
    settings = tmp_path / "co" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps(_EXISTING, indent=2), encoding="utf-8")

    assert hook.install(settings) is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert {k: v for k, v in data.items() if k != "hooks"} == {
        k: v for k, v in _EXISTING.items() if k != "hooks"
    }
    assert data["hooks"]["PreToolUse"] == _EXISTING["hooks"]["PreToolUse"]
    assert data["hooks"]["PostToolUse"] == [*_EXISTING["hooks"]["PostToolUse"], _ours(hook)]

    first = settings.read_bytes()
    assert hook.install(settings) is False
    assert settings.read_bytes() == first
    post = json.loads(first)["hooks"]["PostToolUse"]
    assert sum(1 for entry in post if entry == _ours(hook)) == 1


def test_is_installed_is_false_for_other_hooks_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: is_installed() reports True because SOME PostToolUse hook exists, not ours.
    hook = _hook(monkeypatch)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_EXISTING), encoding="utf-8")
    assert hook.is_installed(settings) is False
    # Positive partner: the same file with our entry added reads as installed.
    with_ours = json.loads(json.dumps(_EXISTING))
    with_ours["hooks"]["PostToolUse"].append(_ours(hook))
    settings.write_text(json.dumps(with_ours), encoding="utf-8")
    assert hook.is_installed(settings) is True
