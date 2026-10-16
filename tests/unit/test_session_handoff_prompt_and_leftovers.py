"""The mechanical handoff shows the root prompt check and the leftovers.

ADR-0160: ``make handoff`` shows the prompt check as ONE value and still writes
the file when the check fails (ADR-0045: one value's failure degrades that
value and never aborts the file). The leftovers section lists what
``session_hygiene.collect()`` found, under each category's title.
"""

from __future__ import annotations

import functools
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))

# The four sections every root prompt must carry (item 1, ADR-0169), in good and bad
# fixtures alike, so the bad one lacks ONLY the Process line.
_SECTIONS = (
    "\n## Read first\n\nx\n\n## The items, in order\n\nx\n\n"
    "## Approvals\n\nx\n\n## End of session\n\nx\n"
)
_GOOD = (
    "# P\n\n**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`.\n"
    + _SECTIONS
)
_NO_LINE = "# P\n\nItems: W55.\n" + _SECTIONS


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: session_hygiene's dataclasses look their module up
    # in sys.modules (the #467 failure).
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _handoff() -> ModuleType:
    """A FRESH copy per test, so monkeypatched module globals never leak."""
    return _load("session_handoff_prompt_under_test", _ROOT / "scripts" / "session_handoff.py")


@functools.lru_cache(maxsize=1)
def _hygiene() -> ModuleType:
    return _load("session_hygiene_under_test", _ROOT / "scripts" / "session_hygiene.py")


@functools.lru_cache(maxsize=1)
def _exempt_names() -> tuple[str, ...]:
    """The real exemptions, so a temporary root can hold them and they do not
    fail as "exempt file missing". This neutralises EXEMPT; it is not an
    expected value."""
    check = _load(
        "check_root_prompts_for_handoff_test", _ROOT / "scripts" / "check_root_prompts.py"
    )
    return tuple(check.EXEMPT)


def _prompt_root(tmp_path: Path, prompt_text: str) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    (root / "CONTINUE-X-W1-PROMPT.md").write_text(prompt_text, encoding="utf-8")
    for name in _exempt_names():
        (root / name).write_text(_NO_LINE, encoding="utf-8")
    return root


def test_prompt_check_section_says_failed_and_names_the_file(tmp_path: Path) -> None:
    # Red when: _prompt_check_section() reports a root with a prompt lacking the line as
    # anything but FAILED, drops the failing file's name, or calls a good root FAILED.
    section = _handoff()._prompt_check_section(_prompt_root(tmp_path / "bad", _NO_LINE))
    assert "## Root prompt check" in section, section
    assert "FAILED" in section, section
    assert "CONTINUE-X-W1-PROMPT.md" in section, section
    assert "PASSED" not in section, section

    # Positive partner: a good root says PASSED.
    good = _handoff()._prompt_check_section(_prompt_root(tmp_path / "good", _GOOD))
    assert "PASSED" in good, good
    assert "FAILED" not in good, good


def test_prompt_check_section_degrades_when_the_root_is_missing(tmp_path: Path) -> None:
    # Red when: _prompt_check_section() raises (aborting the whole handoff, against ADR-0045)
    # when the root it is given does not exist, instead of returning a section.
    section = _handoff()._prompt_check_section(tmp_path / "does-not-exist")
    assert isinstance(section, str)
    assert "## Root prompt check" in section, section


def _categories() -> tuple[object, object]:
    hygiene = _hygiene()
    worktrees = hygiene.Category(
        3, "branches_worktrees", "Merged branches and worktrees", hygiene.REPORT, lambda: []
    )
    scratch = hygiene.Category(4, "scratch", "Scratch and proof files", hygiene.DELETE, lambda: [])
    return worktrees, scratch


def test_leftovers_section_lists_each_finding_under_its_category(tmp_path: Path) -> None:
    # Red when: _leftovers_section() drops a finding's label, drops its category title, or
    # prints the label before the title it belongs to.
    hygiene = _hygiene()
    worktrees, scratch = _categories()
    finding = hygiene.Finding(
        "../quorum-ai-wt-old", hygiene.REPORT, "its branch is merged into origin/main"
    )
    section = _handoff()._leftovers_section([(worktrees, [finding]), (scratch, [])])
    assert "Merged branches and worktrees" in section, section
    assert "../quorum-ai-wt-old" in section, section
    assert section.index("Merged branches and worktrees") < section.index("../quorum-ai-wt-old")


def test_leftovers_section_says_none_found_when_every_category_is_empty() -> None:
    # Red when: _leftovers_section() prints nothing recognisable (or a stale label) when
    # collect() found nothing in any category.
    worktrees, scratch = _categories()
    section = _handoff()._leftovers_section([(worktrees, []), (scratch, [])])
    assert "None found" in section, section
    assert "../quorum-ai-wt-old" not in section, section


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


def test_main_still_writes_the_handoff_when_the_prompt_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Red when: main() stops writing docs/session-handoff.md (or returns non-zero) because the
    # prompt check failed, or the written file loses the "## Root prompt check" or
    # "## Leftovers" section.
    handoff = _handoff()
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(handoff, "ROOT", tmp_path)
    monkeypatch.setattr(
        handoff,
        "_prompt_check_section",
        lambda *a, **k: (
            "## Root prompt check\nFAILED -- CONTINUE-X-W1-PROMPT.md has no **Process:** line\n"
        ),
    )
    monkeypatch.setattr(handoff, "_gather_live_state", lambda *a, **k: dict(_LIVE_STATE_STUB))
    monkeypatch.setattr(handoff, "load_route", lambda *a, **k: dict(_ROUTE_STUB))
    monkeypatch.setattr(handoff, "run", lambda *a, **k: "")
    # The leftovers source is empty. The real formatter still renders it, so this checks that
    # main() includes the section, whatever it is fed. If main() gathers findings through a
    # helper named `_collect_leftovers`, that helper is replaced too (no real hygiene scan).
    real_leftovers = handoff._leftovers_section
    monkeypatch.setattr(handoff, "_leftovers_section", lambda *a, **k: real_leftovers([]))
    monkeypatch.setattr(handoff, "_collect_leftovers", lambda *a, **k: [], raising=False)
    # The parked-work section (item 1) reads git and gh; stubbed so no test reaches the
    # network. raising=False: the stub is harmless where main() has no such helper.
    monkeypatch.setattr(
        handoff,
        "_parked_section",
        lambda *a, **k: "## Parked work and branches\nstub\n",
        raising=False,
    )

    assert handoff.main() == 0
    written = tmp_path / "docs" / "session-handoff.md"
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert "## Root prompt check" in text, text[:2000]
    assert "FAILED" in text, text[:2000]
    assert "## Leftovers" in text, text[:2000]
    # Positive partner: the rest of the file is still there.
    assert "## Current phase" in text
    assert "Operate, learn, and improve" in text
