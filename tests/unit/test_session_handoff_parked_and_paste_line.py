"""The mechanical handoff's new sections (item 1, ADR-0168, ADR-0169).

``make handoff`` gains "Parked work and branches" (the parked-work report),
"Next session" (the paste line for the next session's prompt) and, in the root
prompt section, whether this checkout carries the prompt write hook. Like every
other value there it degrades and never aborts the file (ADR-0045), and
``main()`` still returns 0 in every case. No test here touches the network.
"""

from __future__ import annotations

import importlib.util
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
_GOOD = (
    f"# Continue\n\n{_PROCESS}\n\n## Read first\n\nx\n\n## The items, in order\n\nx\n\n"
    "## Approvals\n\nx\n\n## End of session\n\nx\n"
)
_TEMPLATE = ".agents/skills/work-item-delivery/prompt-template.md"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _handoff() -> ModuleType:
    """A FRESH copy per test, so monkeypatched module globals never leak."""
    return _load("session_handoff_parked_under_test", _SCRIPTS / "session_handoff.py")


def _root(tmp_path: Path, names: tuple[str, ...]) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for name in names:
        (root / name).write_text(_GOOD, encoding="utf-8")
    return root


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any gh or git ls-remote call fail the test."""
    real_run = subprocess.run

    def guarded(args: Any, *a: Any, **k: Any) -> Any:
        words = [str(w) for w in (args if isinstance(args, (list, tuple)) else [args])]
        if words and (Path(words[0]).name == "gh" or "ls-remote" in words):
            raise AssertionError(f"network call in a test: {words}")
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", guarded)


# --------------------------------------------------------------------------
# _parked_section()
# --------------------------------------------------------------------------


def test_parked_section_shows_the_report_of_check_parked_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red when: _parked_section() is missing, does not include check_parked_work's render()
    # output (here a FAILED report, because both gatherers read nothing), or calls the
    # network itself instead of the module's gatherers.
    _no_network(monkeypatch)
    handoff = _handoff()
    real_load = handoff._load_script

    def load(name: str) -> object:
        module = real_load(name)
        if name == "check_parked_work":
            module.remote_branches = lambda *a, **k: None
            module.open_pull_requests = lambda *a, **k: None
        return module

    monkeypatch.setattr(handoff, "_load_script", load)
    section = handoff._parked_section()
    assert section.splitlines()[0] == "## Parked work and branches", section
    assert "FAILED" in section, section
    assert "remote branches" in section, section
    assert "pull requests" in section, section
    assert "unavailable" not in section, section


def test_parked_section_degrades_when_the_check_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Red when: an exception from loading or running check_parked_work escapes
    # _parked_section() (aborting the whole handoff, against ADR-0045).
    handoff = _handoff()
    real_load = handoff._load_script

    def load(name: str) -> object:
        if name == "check_parked_work":
            raise RuntimeError("cannot load check_parked_work")
        return real_load(name)

    monkeypatch.setattr(handoff, "_load_script", load)
    section = handoff._parked_section()
    assert section.splitlines()[0] == "## Parked work and branches", section
    assert "unavailable" in section, section
    assert "cannot load check_parked_work" in section, section


# --------------------------------------------------------------------------
# _next_session_section()
# --------------------------------------------------------------------------


def test_one_prompt_gives_its_paste_line_in_a_text_block(tmp_path: Path) -> None:
    # Red when: the section is missing, its paste line changes, or it is not alone in a
    # ```text fence (the owner copies the block as it stands).
    root = _root(tmp_path, ("CONTINUE-EXAMPLE-W1-PROMPT.md", "NEXT-SESSION-PROMPT.md"))
    lines = _handoff()._next_session_section(root).splitlines()
    assert lines[0] == "## Next session", lines
    i = lines.index("```text")
    assert lines[i + 1 : i + 3] == [
        "Read CONTINUE-EXAMPLE-W1-PROMPT.md in the repo root and follow it exactly.",
        "```",
    ], lines


def test_no_validly_named_prompt_points_at_the_template(tmp_path: Path) -> None:
    # Red when: with no validly named root prompt the section prints a paste line, or stops
    # saying there is none and where the template is.
    root = _root(tmp_path, ("NEXT-SESSION-PROMPT.md",))
    section = _handoff()._next_session_section(root)
    assert section.splitlines()[0] == "## Next session", section
    assert "no root prompt" in section, section
    assert _TEMPLATE in section, section
    assert "follow it exactly" not in section, section


def test_two_prompts_list_both_and_say_only_one(tmp_path: Path) -> None:
    # Red when: with two validly named prompts the section shows only one of them, or does
    # not say that only one should be left.
    root = _root(tmp_path, ("CONTINUE-A-W1-PROMPT.md", "CONTINUE-B-W2-PROMPT.md"))
    section = _handoff()._next_session_section(root)
    for name in ("CONTINUE-A-W1-PROMPT.md", "CONTINUE-B-W2-PROMPT.md"):
        assert f"Read {name} in the repo root and follow it exactly." in section, section
    assert "only one" in section, section


# --------------------------------------------------------------------------
# _prompt_check_section(): whether the hook is installed in this checkout.
# --------------------------------------------------------------------------


def test_prompt_check_section_says_whether_the_hook_is_installed(tmp_path: Path) -> None:
    # Red when: the prompt section stops saying whether .claude/settings.json carries the
    # prompt write hook, or says "installed" for a checkout without it.
    handoff = _handoff()
    root = _root(tmp_path, ("CONTINUE-EXAMPLE-W1-PROMPT.md",))
    without = handoff._prompt_check_section(root)
    assert "hook: not installed" in without, without

    hook = _load("prompt_write_hook_for_handoff_test", _SCRIPTS / "prompt_write_hook.py")
    assert hook.install(root / ".claude" / "settings.json") is True
    # The command runs the checkout's .venv/bin/python (review round 1, C6).
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    with_hook = _handoff()._prompt_check_section(root)
    assert "hook: installed" in with_hook, with_hook
    assert "hook: not installed" not in with_hook, with_hook


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------

_LIVE_STATE_STUB: dict[str, object] = {
    "main_tip": "a" * 40,
    "last_src_commit": "b" * 40,
    "prod_build_sha": None,
    "build_sha_drift_line": "unavailable: stub",
    "pytest_count": "unavailable: stub",
    "e2e_lane_counts": {"invariants": 0, "ops": 0, "degraded": 0},
    "open_issue_count": "unavailable",
    "unmerged_branches": [],
}

_ROUTE_STUB: dict[str, object] = {
    "label": "Operate, learn, and improve",
    "driver": "production-feedback-loop",
    "reviewers": [],
    "blocking_gates": [],
    "missing_or_placeholder_evidence": [],
    "prompt": "stub prompt",
}


def _stubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """main() over a temporary root: every network or slow value replaced, the real
    scripts reachable through a link so _load_script still finds them."""
    _no_network(monkeypatch)
    handoff = _handoff()
    (tmp_path / "docs").mkdir()
    (tmp_path / "scripts").symlink_to(_SCRIPTS, target_is_directory=True)
    monkeypatch.setattr(handoff, "ROOT", tmp_path)
    monkeypatch.setattr(
        handoff, "_prompt_check_section", lambda *a, **k: "## Root prompt check\nSTUB\n"
    )
    monkeypatch.setattr(
        handoff, "_parked_section", lambda *a, **k: "## Parked work and branches\nSTUB-PARKED\n"
    )
    monkeypatch.setattr(handoff, "_gather_live_state", lambda *a, **k: dict(_LIVE_STATE_STUB))
    monkeypatch.setattr(handoff, "load_route", lambda *a, **k: dict(_ROUTE_STUB))
    monkeypatch.setattr(handoff, "run", lambda *a, **k: "")
    monkeypatch.setattr(handoff, "_collect_leftovers", lambda *a, **k: [])
    return handoff


def test_main_prints_the_paste_line_and_writes_both_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: main() stops printing the paste line to stdout, or the written handoff loses
    # the "## Next session" or "## Parked work and branches" section, or main() returns
    # non-zero.
    handoff = _stubbed(tmp_path, monkeypatch)
    (tmp_path / "CONTINUE-EXAMPLE-W1-PROMPT.md").write_text(_GOOD, encoding="utf-8")
    line = "Read CONTINUE-EXAMPLE-W1-PROMPT.md in the repo root and follow it exactly."
    capsys.readouterr()
    assert handoff.main() == 0
    assert line in capsys.readouterr().out.splitlines()
    text = (tmp_path / "docs" / "session-handoff.md").read_text(encoding="utf-8")
    assert "## Next session" in text, text[:3000]
    assert line in text, text[:3000]
    assert "## Parked work and branches" in text, text[:3000]
    assert "STUB-PARKED" in text, text[:3000]


def test_main_with_no_prompt_prints_no_paste_line_and_still_returns_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: main() prints a paste line with no validly named prompt, or fails the run
    # (ADR-0045: a missing prompt is shown, never an abort).
    handoff = _stubbed(tmp_path, monkeypatch)
    capsys.readouterr()
    assert handoff.main() == 0
    assert "follow it exactly" not in capsys.readouterr().out
    text = (tmp_path / "docs" / "session-handoff.md").read_text(encoding="utf-8")
    assert "## Next session" in text, text[:3000]
    assert "no root prompt" in text, text[:3000]
