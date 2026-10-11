"""The root prompt check (ADR-0160, failure modes P1-P5).

Every root ``.md`` whose name contains "prompt" (any case) must carry, outside
a fenced code block, one line of the form
``**Process:** ... .agents/skills/work-item-delivery/SKILL.md ...``.
All roots here are temporary directories except the last test, which checks
the TRACKED prompts of the real repo, because those are what CI can see.
"""

from __future__ import annotations

import functools
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from tests.repo_root import find_repo_root

_ROOT = find_repo_root(Path(__file__))
_SCRIPT = _ROOT / "scripts" / "check_root_prompts.py"

_GOOD = (
    "# Continue the backlog\n\n"
    "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`.\n\n"
    "Items: W55.\n"
)
_NO_LINE = "# Continue the backlog\n\nItems: W55.\n"
_PROSE_ONLY = (
    "# Continue the backlog\n\nDo not use .agents/skills/work-item-delivery/SKILL.md here.\n"
)
_FENCED_ONLY = (
    "# Continue the backlog\n\n"
    "```text\n"
    "**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`.\n"
    "```\n"
)


@functools.lru_cache(maxsize=1)
def _check() -> ModuleType:
    """Load the script by path inside each test, so a missing script fails each
    test on its own rather than erroring the module at collection."""
    spec = importlib.util.spec_from_file_location("check_root_prompts_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _root(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_a_prompt_without_the_line_is_one_problem_and_with_it_none(tmp_path: Path) -> None:
    # Red when: problems() passes a prompt with no **Process:** line, reports more than one
    # problem for it, does not name the file, or refuses a prompt that carries the line.
    bad = _root(tmp_path / "a", {"CONTINUE-X-PROMPT.md": _NO_LINE})
    found = _check().problems(bad, {})
    assert len(found) == 1, found
    assert "CONTINUE-X-PROMPT.md" in found[0], found

    # Positive partner: the same file with the line passes.
    good = _root(tmp_path / "b", {"CONTINUE-X-PROMPT.md": _GOOD})
    assert _check().problems(good, {}) == []


@pytest.mark.parametrize(
    ("label", "text"),
    [("path only in prose", _PROSE_ONLY), ("line only in a fenced block", _FENCED_ONLY)],
    ids=["prose-only", "fenced-only"],
)
def test_the_path_in_prose_or_in_a_code_block_is_refused(
    tmp_path: Path, label: str, text: str
) -> None:
    # Red when: the check becomes a substring search for the skill path (passes "do not use
    # ..."), or stops skipping fenced code blocks (passes the line quoted inside ```).
    root = _root(tmp_path, {"CONTINUE-X-PROMPT.md": text})
    found = _check().problems(root, {})
    assert len(found) == 1, (label, found)
    assert "CONTINUE-X-PROMPT.md" in found[0], (label, found)


def test_a_lower_case_prompt_name_is_found_and_a_plain_note_is_not(tmp_path: Path) -> None:
    # Red when: find_prompt_files() matches only upper-case "PROMPT" (misses x-prompt.md) or
    # picks up a root .md whose name does not contain "prompt".
    root = _root(tmp_path, {"x-prompt.md": _NO_LINE, "notes.md": _NO_LINE})
    names = sorted(p.name for p in _check().find_prompt_files(root))
    assert names == ["x-prompt.md"], names
    found = _check().problems(root, {})
    assert len(found) == 1 and "x-prompt.md" in found[0], found
    assert not any("notes.md" in m for m in found), found


def test_an_exemption_must_name_a_file_that_exists(tmp_path: Path) -> None:
    # Red when: an exempt name that is not in the root is silently accepted (P4), or an exempt
    # file that IS present is still refused for lacking the line.
    root = _root(tmp_path / "a", {"CONTINUE-X-PROMPT.md": _GOOD})
    found = _check().problems(root, {"GONE-PROMPT.md": "archived"})
    assert len(found) == 1 and "GONE-PROMPT.md" in found[0], found

    # Positive partner: a present exempt file without the line is not a problem.
    root = _root(
        tmp_path / "b",
        {"CONTINUE-X-PROMPT.md": _GOOD, "R2-S2-S4-ULTRACODE-PROMPT.md": _NO_LINE},
    )
    assert _check().problems(root, {"R2-S2-S4-ULTRACODE-PROMPT.md": "pinned"}) == []


def test_an_empty_root_fails_and_a_passing_root_reports_its_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Red when: a root with no prompt file at all passes (the check passes over nothing, P5),
    # or main() stops returning 0 / printing "checked 1" for a root with one good prompt.
    check = _check()
    # The real EXEMPT names files that do not exist in a temporary root; empty it so only the
    # files written here count. main() must read EXEMPT when it runs.
    monkeypatch.setattr(check, "EXEMPT", {})

    empty = _root(tmp_path / "empty", {"notes.md": _NO_LINE})
    assert check.problems(empty, {}) != []
    assert check.main(["--root", str(empty)]) == 1

    good = _root(tmp_path / "good", {"CONTINUE-X-PROMPT.md": _GOOD, "notes.md": _NO_LINE})
    capsys.readouterr()
    assert check.main(["--root", str(good)]) == 0
    assert "checked 1" in capsys.readouterr().out


def test_every_tracked_root_prompt_carries_the_line_or_is_exempt(tmp_path: Path) -> None:
    # Red when: a TRACKED root prompt file lacks the **Process:** line and is not named in
    # check_root_prompts.EXEMPT (a tracked prompt without the line must not merge).
    check = _check()
    listed = subprocess.run(
        ["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    tracked = [n for n in listed if "/" not in n and n.endswith(".md") and "prompt" in n.lower()]
    # Partner: there is at least one tracked root prompt to check.
    assert tracked, "no tracked root prompt file found"

    to_check = [n for n in tracked if n not in check.EXEMPT]
    copy = tmp_path / "tracked"
    copy.mkdir()
    for name in to_check:
        (copy / name).write_text((_ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
    if not to_check:
        return
    # Partner: the check sees every copied file.
    assert len(check.find_prompt_files(copy)) == len(to_check)
    assert check.problems(copy, {}) == []
