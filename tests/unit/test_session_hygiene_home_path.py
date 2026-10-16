"""W70 item 5: ``make handoff`` writes a worktree under the home folder as ``~``.

``scripts/session_handoff.py`` copies each finding of
``scripts/session_hygiene.py`` (label and reason) into the TRACKED
``docs/session-handoff.md``. Until W70 a worktree was written with its full
path, so every handoff committed the owner's home folder, and once the W70 scan
names home-folder paths (owner decision CHG-045: "Rewrite them to ~") the next
handoff would fail the scan.

The fake home lives under ``tmp_path``, so no line here holds a real home path.
``HOME`` is set rather than ``Path.home`` patched: on POSIX, ``Path.home()``,
``os.path.expanduser("~")`` and ``os.environ["HOME"]`` all read it, so the test
does not dictate which one the script uses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "session_hygiene.py"


def _load_hygiene() -> Any:
    """Load by path, never as a package import (keeps ``scripts/`` out of mypy)."""
    spec = importlib.util.spec_from_file_location("session_hygiene_home_path", _SCRIPT)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "h" / "someone"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home


def _worktree_labels(module: Any, paths: list[str], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    # The first entry is the main worktree, which the finder skips.
    monkeypatch.setattr(module, "worktree_paths", lambda: ["main-checkout", *paths])
    # No trunk: the finder reports worktrees and stops before any branch query.
    monkeypatch.setattr(module, "base_ref", lambda: None)
    return [f.label for f in module.find_branches_and_worktrees() if f.label.startswith("worktree")]


def test_a_worktree_under_the_home_folder_is_labelled_with_a_tilde(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handoff label replaces the home folder with ``~``.

    Red when: ``find_branches_and_worktrees`` labels the worktree with its full
    path (``f"worktree {path}"``), so the home folder reaches the handoff.
    """
    module = _load_hygiene()
    inside = str(fake_home / "Projects" / "wt-a")

    labels = _worktree_labels(module, [inside], monkeypatch)

    assert labels == ["worktree ~/Projects/wt-a"], labels
    assert str(fake_home) not in labels[0]


def test_a_worktree_outside_the_home_folder_is_printed_unchanged(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Partner: only the home folder is rewritten, and only at a folder boundary.

    The sibling folder ``someone-else`` starts with the home folder's text but is
    not inside it, so a plain string-prefix replace would print ``~-else/...``.

    Red when: paths outside the home folder are rewritten, OR the rewrite is a
    bare ``str.replace``/``startswith`` that ignores the folder boundary.
    """
    module = _load_hygiene()
    outside = str(tmp_path / "elsewhere" / "wt-b")
    sibling = str(fake_home.parent / "someone-else" / "wt-c")

    labels = _worktree_labels(module, [outside, sibling], monkeypatch)

    assert labels == [f"worktree {outside}", f"worktree {sibling}"], labels


def test_a_merged_branch_checked_out_under_home_names_its_worktree_with_a_tilde(
    fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason text also reaches the handoff, and it names the worktree too.

    Beyond the label: a merged branch still checked out somewhere gets
    ``CHECKED OUT at <worktree>`` in its reason, and ``session_handoff`` writes
    that reason into the tracked file just as it writes the label.

    Red when: the ``CHECKED OUT at`` note prints the worktree's full path.
    """
    module = _load_hygiene()
    inside = str(fake_home / "Projects" / "wt-a")

    def fake_git(*args: str) -> str:
        if args and args[0] == "for-each-ref":
            return f"refs/heads/feature\t{inside}"
        if args and args[0] == "rev-list":
            return "1"
        return ""

    monkeypatch.setattr(module, "worktree_paths", lambda: ["main-checkout"])
    monkeypatch.setattr(module, "base_ref", lambda: "refs/remotes/origin/main")
    monkeypatch.setattr(module, "merge_tree_supported", lambda: True)
    monkeypatch.setattr(module, "merge_driver_risk", lambda: False)
    monkeypatch.setattr(module, "branch_is_merged", lambda ref, base: True)
    monkeypatch.setattr(module, "git", fake_git)

    findings = module.find_branches_and_worktrees()
    branch = [f for f in findings if f.label == "branch feature"]

    assert len(branch) == 1, [f.label for f in findings]
    assert "CHECKED OUT at ~/Projects/wt-a " in branch[0].why, branch[0].why
    assert str(fake_home) not in branch[0].why
