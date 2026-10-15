#!/usr/bin/env python3
"""Run the root prompt check after every tool call that could write a prompt (ADR-0169).

Claude Code runs this as a PostToolUse hook, and as a PostToolUseFailure hook
for a tool call that failed: a shell command can write a prompt and then exit
non-zero, and Claude Code then sends only the failure event. It does NOT trust the tool's
input: a prompt written by a shell command carries no file path, so on every
call the hook lists the root prompt files of each checkout of this repository
(``git worktree list``), takes the SHA-256 digest of each file's bytes, and
compares them with the digests it saved last time in
``<project>/.claude/state/prompt-hook.json``. It runs
``scripts/check_root_prompts.py``'s check only on the checkouts whose prompts
changed, were added or were removed, or on every checkout while the last
result was a failure (and on its first run, with no saved state), so a bad
prompt keeps being reported until it is fixed.

On a failure it prints ``{"decision": "block", "reason": ...}``, which shows
the agent what is wrong; for a PostToolUseFailure event it prints the same
reason as ``hookSpecificOutput.additionalContext``. A checkout with no root
prompt at all is not a failure here. The hook always exits 0 and never
raises: a broken hook must never break the session. That includes an
interpreter without ``markdown_it``: the check is loaded inside ``main``'s
error handler, not at import.

Install it in a checkout's untracked ``.claude/settings.json`` (ADR-0043):

    .venv/bin/python scripts/prompt_write_hook.py --install <checkout>
    .venv/bin/python scripts/prompt_write_hook.py --check-installed <checkout>
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, TextIO

_SCRIPTS = Path(__file__).resolve().parent
_SKILL = Path(".agents") / "skills" / "work-item-delivery" / "SKILL.md"
_NO_PROMPT = "no root prompt file found"

#: The command the settings entry runs. Resolved from the project directory,
#: so it works from any checkout and whatever the session's working directory.
HOOK_COMMAND = (
    '"$CLAUDE_PROJECT_DIR/.venv/bin/python" "$CLAUDE_PROJECT_DIR/scripts/prompt_write_hook.py"'
)
_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|Bash"
_ENTRY: dict[str, Any] = {
    "matcher": _MATCHER,
    "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 30}],
}
#: The events the entry is installed under. A tool call that fails, such as a
#: shell command that writes a prompt and then exits non-zero, is sent as
#: PostToolUseFailure and never as PostToolUse.
_EVENTS = ("PostToolUse", "PostToolUseFailure")
_PYTHON = Path(".venv") / "bin" / "python"


def _load_check() -> ModuleType:
    """Load ``check_root_prompts.py`` from beside this file, by path."""
    name = "_prompt_write_hook_check_root_prompts"
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / "check_root_prompts.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


def _check() -> ModuleType:
    """The check module, loaded on first use and kept as the module attribute
    ``check_root_prompts`` (which tests may replace)."""
    module: ModuleType | None = globals().get("check_root_prompts")
    if module is None:
        module = _load_check()
        globals()["check_root_prompts"] = module
    return module


def __getattr__(name: str) -> ModuleType:
    """``prompt_write_hook.check_root_prompts`` loads the check on first access."""
    if name == "check_root_prompts":
        return _check()
    raise AttributeError(name)


def checkout_roots(project_dir: Path) -> list[Path]:
    """The root of every checkout of this repository: each path ``git worktree
    list`` names that holds the work-item-delivery skill. When git cannot say,
    the project directory alone if it holds the skill, else nothing."""
    try:
        done = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        listed = done.stdout if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        listed = None
    if listed is None:
        return [project_dir] if (project_dir / _SKILL).is_file() else []
    paths = [
        Path(line[len("worktree ") :])
        for line in listed.splitlines()
        if line.startswith("worktree ")
    ]
    return [p for p in paths if (p / _SKILL).is_file()]


def signatures(roots: list[Path]) -> dict[str, str]:
    """Each root prompt file's absolute path, mapped to the SHA-256 hex digest
    of its bytes. Content, not size and time: an edit can keep both."""
    found: dict[str, str] = {}
    for root in roots:
        for path in _check().find_prompt_files(root):
            found[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def _read_state(state_path: Path) -> tuple[dict[str, str] | None, bool]:
    """The saved digests and whether the last result failed. Missing or
    unreadable state reads as (None, True): everything counts as changed."""
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        saved = data["signatures"]
        if not isinstance(saved, dict):
            return None, True
        return {str(k): str(v) for k, v in saved.items()}, bool(data["failing"])
    except Exception:  # noqa: BLE001 — any unreadable state means "check everything"
        return None, True


def _in_root(path: str, root: Path) -> bool:
    return Path(path).parent == root


def run_hook(roots: list[Path], state_path: Path) -> str | None:
    """Check the roots whose prompts changed (all of them while the last
    result failed), save the new state, and return the reason to block, or
    None when nothing failed. A state that cannot be saved is noted on stderr
    and does not lose the reason: the next call then checks everything."""
    check = _check()
    current = signatures(roots)
    saved, failing = _read_state(state_path)
    failures: list[str] = []
    for root in roots:
        if saved is not None and not failing:
            now = {k: v for k, v in current.items() if _in_root(k, root)}
            before = {k: v for k, v in saved.items() if _in_root(k, root)}
            if now == before:
                continue
        found = check.problems(root, check.EXEMPT)
        failures += [f"{root}: {m}" for m in found if not m.startswith(_NO_PROMPT)]
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"signatures": current, "failing": bool(failures)}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"prompt_write_hook: could not save {state_path}: {exc!r}", file=sys.stderr)
    if not failures:
        return None
    lines = "\n".join(f"- {f}" for f in failures)
    return f"A root prompt file fails the root prompt check:\n{lines}\nRun make prompt-check."


def install_status(settings_path: Path) -> str:
    """``installed`` when the settings file carries this hook's entry under
    both events and the checkout (two levels above the file) has the
    ``.venv/bin/python`` the command runs; otherwise ``not installed``, with
    the missing interpreter named."""
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = all(_ENTRY in data["hooks"][event] for event in _EVENTS)
    except Exception:  # noqa: BLE001 — absent or unreadable means not installed
        entries = False
    if not entries:
        return "not installed"
    if not (settings_path.parent.parent / _PYTHON).exists():
        return "not installed: no .venv/bin/python"
    return "installed"


def is_installed(settings_path: Path) -> bool:
    """True when ``install_status`` says ``installed``."""
    return install_status(settings_path) == "installed"


def install(settings_path: Path) -> bool:
    """Add this hook's entry under both events to the settings file, keeping
    everything else. True when the file changed; False when both entries
    were already there."""
    data: dict[str, Any] = {}
    if settings_path.is_file():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = data.setdefault("hooks", {})
    changed = False
    for event in _EVENTS:
        entries = hooks.setdefault(event, [])
        if _ENTRY not in entries:
            entries.append(json.loads(json.dumps(_ENTRY)))
            changed = True
    if not changed:
        return False
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _settings(checkout: Path) -> Path:
    return checkout / ".claude" / "settings.json"


def _event_name(stdin: TextIO) -> str:
    """The ``hook_event_name`` of the tool call's JSON on stdin. Only the event
    is read; the tool's input is deliberately not trusted. Unreadable or
    unparseable input reads as PostToolUse."""
    with contextlib.suppress(Exception):
        name = json.loads(stdin.read()).get("hook_event_name")
        if isinstance(name, str):
            return name
    return "PostToolUse"


def _output(event: str, reason: str) -> dict[str, Any]:
    """What the hook prints for a failure. PostToolUseFailure has no block
    decision, so the reason goes in as context for the agent."""
    if event == "PostToolUseFailure":
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": reason}}
    return {"decision": "block", "reason": reason}


def main(
    argv: list[str] | None = None,
    stdin: TextIO = sys.stdin,
    env: Mapping[str, str] = os.environ,
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install", type=Path, metavar="CHECKOUT")
    group.add_argument("--check-installed", type=Path, metavar="CHECKOUT")
    args = parser.parse_args(argv)
    if args.install is not None:
        changed = install(_settings(args.install))
        print("installed" if changed else "already installed")
        return 0
    if args.check_installed is not None:
        status = install_status(_settings(args.check_installed))
        print(status)
        return 0 if status == "installed" else 1
    try:
        event = _event_name(stdin)
        project = Path(env.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        reason = run_hook(
            checkout_roots(project), project / ".claude" / "state" / "prompt-hook.json"
        )
        if reason is not None:
            print(json.dumps(_output(event, reason)))
    except Exception as exc:  # noqa: BLE001 — a broken hook must never break the session
        print(f"prompt_write_hook: skipped, {exc!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
