"""Item 1, review round 2: one regression test per reproduced finding.

D1 to D6 are code defects the round found; D7 and D8 are tests the
falsification lens showed were missing. Every test loads its script by path,
inside the test, and touches no network.
"""

from __future__ import annotations

import datetime
import hashlib
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


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _check() -> ModuleType:
    return _load("check_root_prompts_r2", _SCRIPTS / "check_root_prompts.py")


def _hook() -> ModuleType:
    return _load("prompt_write_hook_r2", _SCRIPTS / "prompt_write_hook.py")


def _parked() -> ModuleType:
    return _load("check_parked_work_r2", _SCRIPTS / "check_parked_work.py")


def _handoff() -> ModuleType:
    return _load("session_handoff_r2", _SCRIPTS / "session_handoff.py")


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


def _count_checks(hook: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record every root the hook asks the check about."""
    check = hook.check_root_prompts
    real = check.problems
    seen: list[Path] = []

    def counted(root: Path, exempt: dict[str, str]) -> list[str]:
        seen.append(root)
        return list(real(root, exempt))

    monkeypatch.setattr(check, "problems", counted)
    monkeypatch.setattr(check, "EXEMPT", {})
    return seen


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# D1: a change to the checker (or the hook) re-checks every root.
# --------------------------------------------------------------------------


def test_d1_a_changed_checker_rechecks_every_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: run_hook() trusts saved prompt digests alone, so a prompt an older checker
    # passed stays "passing" after the checker changes (no re-check, no reason).
    hook = _hook()
    seen = _count_checks(hook, monkeypatch)
    a = _checkout(tmp_path / "a", {_NAME: _NO_PROCESS})
    b = _checkout(tmp_path / "b", {_NAME: _GOOD})
    state = tmp_path / "state.json"
    sources = {
        "checker": "0" * 64,  # what an older checker hashed to
        "hook": _sha(_SCRIPTS / "prompt_write_hook.py"),
    }
    saved = {"signatures": hook.signatures([a, b]), "failing": False, "sources": sources}
    state.write_text(json.dumps(saved), encoding="utf-8")
    reason = hook.run_hook([a, b], state)
    assert seen == [a, b], seen
    assert reason is not None and f"{a}: {_NAME}" in reason, reason


def test_d1_a_changed_or_missing_hook_digest_rechecks_and_a_matching_one_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: the hook's own digest is not compared (a changed hook keeps old results), or
    # a state with no source digests is trusted, or a matching state re-checks anyway.
    hook = _hook()
    seen = _count_checks(hook, monkeypatch)
    a = _checkout(tmp_path / "a", {_NAME: _GOOD})
    state = tmp_path / "state.json"
    assert hook.run_hook([a], state) is None
    assert seen == [a], seen
    # Positive partner: nothing changed, so nothing is re-checked.
    seen.clear()
    assert hook.run_hook([a], state) is None
    assert seen == [], seen
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["failing"] is False, saved
    assert saved["sources"]["checker"] == _sha(_SCRIPTS / "check_root_prompts.py"), saved
    # A different hook digest re-checks.
    saved["sources"]["hook"] = "0" * 64
    state.write_text(json.dumps(saved), encoding="utf-8")
    assert hook.run_hook([a], state) is None
    assert seen == [a], seen
    # A state saved before digests existed re-checks.
    seen.clear()
    del saved["sources"]
    state.write_text(json.dumps(saved), encoding="utf-8")
    assert hook.run_hook([a], state) is None
    assert seen == [a], seen


# --------------------------------------------------------------------------
# D2: a draft is parked when a Where names its number OR its head branch.
# --------------------------------------------------------------------------


def _draft_report(where: str) -> Any:
    mod = _parked()
    entry = mod.ParkedEntry(
        item="W1", where=where, reason="waits", owner="product owner", resume_when="after W2"
    )
    return mod.build_report(
        entries=[entry],
        rows={
            "W1": {"state": "PENDING", "item": "a", "depends": "—"},
            "W2": {"state": "PENDING", "item": "b", "depends": "—"},
        },
        remote_branches=["main", "w28/byok-pr1-plan"],
        open_prs=[{"number": 525, "headRefName": "w28/byok-pr1-plan", "isDraft": True}],
        today=datetime.date(2026, 10, 16),
    )


def test_d2_a_where_naming_only_the_branch_parks_the_draft() -> None:
    # Red when: build_report() matches a draft to a Parked line by "#<number>" only, so a
    # Where cell that names the draft's head branch in backticks still fails the check.
    report = _draft_report("branch `w28/byok-pr1-plan`")
    assert report.problems == [], report.problems
    # Positive partner: the number alone still parks it.
    assert _draft_report("draft #525").problems == []


def test_d2_a_different_branch_does_not_park_the_draft() -> None:
    # Red when: any backticked branch in a Where cell parks every draft, or a near-miss
    # (prefix) of the head branch counts.
    for where in ("branch `w28/other`", "branch `w28/byok-pr1`", "#526"):
        report = _draft_report(where)
        drafts = [p for p in report.problems if "#525" in p and "no line" in p]
        assert len(drafts) == 1, (where, report.problems)


# --------------------------------------------------------------------------
# D3: the hook ignores "is exempt but does not exist" (another checkout's tree).
# --------------------------------------------------------------------------


def test_d3_the_hook_ignores_a_missing_exempt_file_but_prompt_check_reports_it(
    tmp_path: Path,
) -> None:
    # Red when: run_hook() blocks every tool call in a checkout that lacks an EXEMPT file
    # (a tree that is not this session's to fix), or make prompt-check stops reporting it.
    hook = _hook()
    check = hook.check_root_prompts
    assert check.EXEMPT, "the test needs a real EXEMPT entry"
    root = _checkout(tmp_path / "co", {_NAME: _GOOD})
    assert hook.run_hook([root], tmp_path / "state.json") is None
    # Positive partner: the check itself still reports it ...
    assert [m for m in check.problems(root, check.EXEMPT) if "is exempt but does not exist" in m]
    # ... and the hook still reports a failing prompt in the same checkout.
    (root / _NAME).write_text(_NO_PROCESS, encoding="utf-8")
    reason = hook.run_hook([root], tmp_path / "state.json")
    assert reason is not None and _NAME in reason, reason
    assert "is exempt but does not exist" not in reason, reason


# --------------------------------------------------------------------------
# D4: the CI test lists tracked names with -z, so a non-ASCII name is not quoted.
# --------------------------------------------------------------------------


def _git_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for name, text in files.items():
        (path / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "--", *files], check=True)
    return path


def test_d4_the_ci_test_sees_a_tracked_non_ascii_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: test_every_tracked_root_prompt_carries_the_line_or_is_exempt lists names with
    # plain `git ls-files`, which quotes "CONTINUE-Ü-W1-PROMPT.md" as "\"CONTINUE-\303\234...\""
    # so the ".md" filter drops it and a bad tracked prompt escapes CI.
    ci = _load("test_root_prompt_check_r2", _ROOT / "tests" / "unit" / "test_root_prompt_check.py")
    good = _git_repo(tmp_path / "good", {_NAME: _GOOD})
    monkeypatch.setattr(ci, "_ROOT", good)
    (tmp_path / "a").mkdir()
    # Positive partner: a clean tracked set passes.
    ci.test_every_tracked_root_prompt_carries_the_line_or_is_exempt(tmp_path / "a")
    bad = _git_repo(tmp_path / "bad", {_NAME: _GOOD, "CONTINUE-Ü-W1-PROMPT.md": _NO_PROCESS})
    monkeypatch.setattr(ci, "_ROOT", bad)
    (tmp_path / "b").mkdir()
    with pytest.raises(AssertionError):
        ci.test_every_tracked_root_prompt_carries_the_line_or_is_exempt(tmp_path / "b")


# --------------------------------------------------------------------------
# D5: "only one should be left" counts failing named prompts too.
# --------------------------------------------------------------------------


def test_d5_one_passing_and_one_failing_prompt_still_says_only_one(tmp_path: Path) -> None:
    # Red when: _next_session_section() counts only the prompts that pass, so with one
    # passing and one failing validly named prompt it never says only one should be left.
    root = tmp_path / "root"
    root.mkdir()
    (root / "CONTINUE-A-W1-PROMPT.md").write_text(_GOOD, encoding="utf-8")
    (root / "CONTINUE-B-W2-PROMPT.md").write_text(_NO_PROCESS, encoding="utf-8")
    section = _handoff()._next_session_section(root)
    assert "There are 2 validly named root prompts; only one should be left" in section, section
    assert "CONTINUE-B-W2-PROMPT.md fails `make prompt-check`" in section, section
    assert "Read CONTINUE-A-W1-PROMPT.md in the repo root and follow it exactly." in section
    assert "Read CONTINUE-B-W2-PROMPT.md" not in section, section
    # Positive partners: one prompt alone, passing or failing, gets no such warning.
    (root / "CONTINUE-B-W2-PROMPT.md").unlink()
    assert "only one" not in _handoff()._next_session_section(root)
    (root / "CONTINUE-A-W1-PROMPT.md").write_text(_NO_PROCESS, encoding="utf-8")
    alone = _handoff()._next_session_section(root)
    assert "only one" not in alone and "fails `make prompt-check`" in alone, alone


# --------------------------------------------------------------------------
# D6: --install refuses a settings file of an unexpected shape.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        "[]",
        '{"hooks": []}',
        '{"hooks": {"PostToolUse": {}}}',
        '{"hooks": {"PostToolUse": "x"}}',
    ],
)
def test_d6_install_refuses_an_unexpected_shape_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], shape: str
) -> None:
    # Red when: --install on a settings file whose JSON is not {"hooks": {event: [...]}}
    # raises a traceback (or rewrites the file) instead of refusing with exit 1.
    hook = _hook()
    checkout = _checkout(tmp_path / "co")
    settings = checkout / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(shape, encoding="utf-8")
    capsys.readouterr()
    assert hook.main(["--install", str(checkout)], stdin=io.StringIO(""), env={}) == 1
    out = capsys.readouterr().out.strip()
    assert out == f"cannot install: {settings} is not the expected shape", out
    assert settings.read_text(encoding="utf-8") == shape


def test_d6_install_still_adds_to_an_expected_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: the shape check refuses a valid settings file (an empty object, or one that
    # already has a PostToolUse list) or drops what it already held.
    hook = _hook()
    for i, shape in enumerate(("{}", '{"hooks": {"PostToolUse": []}, "model": "x"}')):
        checkout = _checkout(tmp_path / f"co{i}")
        settings = checkout / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(shape, encoding="utf-8")
        capsys.readouterr()
        assert hook.main(["--install", str(checkout)], stdin=io.StringIO(""), env={}) == 0
        assert capsys.readouterr().out.strip() == "installed"
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert len(data["hooks"]["PostToolUse"]) == 1, data
        assert data.get("model") == json.loads(shape).get("model"), data


# --------------------------------------------------------------------------
# D7: main() prints the failing line, and no paste line, for a failing prompt.
# --------------------------------------------------------------------------


def test_d7_main_prints_the_failing_line_and_no_paste_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: main() stops printing "<name> fails `make prompt-check`" to stdout for a
    # validly named failing prompt, or prints a paste line for it.
    real_run = subprocess.run

    def guarded(args: Any, *a: Any, **k: Any) -> Any:
        words = [str(w) for w in (args if isinstance(args, (list, tuple)) else [args])]
        if words and (Path(words[0]).name == "gh" or "ls-remote" in words):
            raise AssertionError(f"network call in a test: {words}")
        return real_run(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", guarded)
    handoff = _handoff()
    (tmp_path / "docs").mkdir()
    (tmp_path / "scripts").symlink_to(_SCRIPTS, target_is_directory=True)
    monkeypatch.setattr(handoff, "ROOT", tmp_path)
    for name, value in (
        ("_prompt_check_section", "## Root prompt check\nSTUB\n"),
        ("_parked_section", "## Parked work and branches\nSTUB\n"),
    ):
        monkeypatch.setattr(handoff, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(
        handoff,
        "_gather_live_state",
        lambda *a, **k: {
            "main_tip": "a" * 40,
            "last_src_commit": "b" * 40,
            "prod_build_sha": None,
            "build_sha_drift_line": "unavailable: stub",
            "pytest_count": "unavailable: stub",
            "e2e_lane_counts": {"invariants": 0, "ops": 0, "degraded": 0},
            "open_issue_count": "unavailable",
            "unmerged_branches": [],
        },
    )
    monkeypatch.setattr(
        handoff,
        "load_route",
        lambda *a, **k: {
            "label": "x",
            "driver": "x",
            "reviewers": [],
            "blocking_gates": [],
            "missing_or_placeholder_evidence": [],
            "prompt": "x",
        },
    )
    monkeypatch.setattr(handoff, "run", lambda *a, **k: "")
    monkeypatch.setattr(handoff, "_collect_leftovers", lambda *a, **k: [])
    (tmp_path / _NAME).write_text(_NO_PROCESS, encoding="utf-8")
    capsys.readouterr()
    assert handoff.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert (
        f"{_NAME} fails `make prompt-check`; fix it first, then run `make handoff` again." in out
    ), out
    assert not [line for line in out if "follow it exactly" in line], out
    # Positive partner: once the prompt passes, its paste line is printed instead.
    (tmp_path / _NAME).write_text(_GOOD, encoding="utf-8")
    assert handoff.main() == 0
    out = capsys.readouterr().out.splitlines()
    assert f"Read {_NAME} in the repo root and follow it exactly." in out, out
    assert not [line for line in out if "fails `make prompt-check`" in line], out


# --------------------------------------------------------------------------
# D8: hook entry present, interpreter missing: the advice is uv sync.
# --------------------------------------------------------------------------


def test_d8_no_venv_python_gets_the_uv_sync_advice(tmp_path: Path) -> None:
    # Red when: _prompt_check_section() tells a checkout that HAS the hook entry but no
    # .venv/bin/python to run --install (which cannot help), instead of `uv sync --all-extras`.
    hook = _hook()
    root = _checkout(tmp_path / "co", {_NAME: _GOOD}, python=False)
    hook.install(root / ".claude" / "settings.json")
    section = _handoff()._prompt_check_section(root)
    hook_lines = [line for line in section.splitlines() if line.startswith("Prompt write hook:")]
    assert len(hook_lines) == 1, section
    assert "no .venv/bin/python" in hook_lines[0], hook_lines
    assert "uv sync --all-extras" in hook_lines[0], hook_lines
    assert "--install" not in hook_lines[0], hook_lines
    # Positive partner: with no hook entry at all the advice is --install.
    bare = _checkout(tmp_path / "bare", {_NAME: _GOOD})
    bare_section = _handoff()._prompt_check_section(bare)
    assert "--install ." in bare_section and "uv sync" not in bare_section, bare_section
