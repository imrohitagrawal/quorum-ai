"""The docs map's inventory is DERIVED from the tree, so it is verified, not trusted.

GATE CHARTER
------------
WHY THIS EXISTS: on 2026-09-30, 268 of 538 tracked ``.md`` files were not
reachable within three links of ``AGENTS.md``; a hand-kept list of documents
decays the way ``docs/24-adr-index.md`` did twice. ``docs/README.md`` is the
map; its generated part is written by ``scripts/check_docs_map.py`` and this
file proves the check bites.

WHAT IT CANNOT SEE: whether the hand-written table names the right home for a
kind of information, or whether a file inside a folder is worth reading.

FALSE-POSITIVE COST: zero. It fires only when the generated part disagrees
with ``docs/`` on disk, and the fix is one command.

What turns the wiring test red: dropping ``docs-map-check`` from ``make
validate``, gutting its recipe, or prefixing the recipe with ``-``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_docs_map.py"
MAP = ROOT / "docs" / "README.md"
MAKEFILE = ROOT / "Makefile"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("check_docs_map", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load()


def test_the_map_lists_exactly_the_docs_on_disk() -> None:
    """Turns red if: a top-level docs/*.md or a docs/ folder is added, renamed
    or deleted without running ``python3 scripts/check_docs_map.py``."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, (
        f"docs/README.md's inventory is stale.\n{result.stdout}{result.stderr}"
        "\nFix: python3 scripts/check_docs_map.py"
    )


def test_every_top_level_doc_is_a_row_and_there_are_many() -> None:
    """The positive partner: the check above would also pass over an empty map
    of an empty directory. Turns red if the inventory stops naming every file."""
    files = sorted(p.name for p in (ROOT / "docs").glob("*.md"))
    assert len(files) > 50, f"expected the real docs/ directory, found {len(files)} files"
    text = MAP.read_text(encoding="utf-8")
    generated = text[text.index(CHECKER.BEGIN) : text.index(CHECKER.END)]
    missing = [name for name in files if f"| `{name}` |" not in generated]
    assert not missing, f"top-level docs missing from the map's inventory: {missing}"
    folders = sorted(p.name for p in (ROOT / "docs").iterdir() if p.is_dir())
    assert folders, "docs/ has no folders — wrong root?"
    missing_folders = [name for name in folders if f"| `{name}/` |" not in generated]
    assert not missing_folders, f"folders missing from the map's inventory: {missing_folders}"


def _tree(tmp_path: Path, names: list[str]) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in names:
        (docs / name).write_text(f"# Title of {name}\n\nbody\n", encoding="utf-8")
    (docs / "README.md").write_text(
        "# map\n\nhand-written part\n\n" + CHECKER.BEGIN + "\n" + CHECKER.END + "\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_new_doc_turns_the_check_red_and_a_rewrite_turns_it_green(tmp_path: Path) -> None:
    """The bite-proof. Turns red if: ``check`` stops comparing the generated
    part against the tree (for example, always returns 0)."""
    root = _tree(tmp_path, ["10-a.md", "11-b.md"])
    assert CHECKER.write(root) == 0
    assert CHECKER.check(root) == 0
    text = (root / "docs" / "README.md").read_text(encoding="utf-8")
    assert "| `10-a.md` | Title of 10-a.md |" in text
    assert "| `README.md` | map |" in text

    (root / "docs" / "12-c.md").write_text("# Title of 12-c.md\n", encoding="utf-8")
    assert CHECKER.check(root) == 1, "a new top-level doc must make the check fail"

    assert CHECKER.write(root) == 0
    assert CHECKER.check(root) == 0


def test_a_new_folder_turns_the_check_red(tmp_path: Path) -> None:
    """Turns red if: folders drop out of the inventory."""
    root = _tree(tmp_path, ["10-a.md"])
    CHECKER.write(root)
    (root / "docs" / "notes").mkdir()
    (root / "docs" / "notes" / "x.md").write_text("# x\n", encoding="utf-8")
    assert CHECKER.check(root) == 1


def test_the_hand_written_part_survives_a_rewrite(tmp_path: Path) -> None:
    """Turns red if: ``write`` replaces more than the generated section."""
    root = _tree(tmp_path, ["10-a.md"])
    CHECKER.write(root)
    CHECKER.write(root)
    text = (root / "docs" / "README.md").read_text(encoding="utf-8")
    assert text.startswith("# map\n\nhand-written part\n\n")
    assert text.count(CHECKER.BEGIN) == 1 and text.count(CHECKER.END) == 1


def test_the_check_refuses_to_pass_over_no_docs(tmp_path: Path) -> None:
    """The floor. Turns red if: an empty docs/ directory and an empty inventory
    are allowed to agree."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text(CHECKER.BEGIN + "\n" + CHECKER.END + "\n", encoding="utf-8")
    # README.md itself is a top-level doc, so the tree is not empty yet.
    CHECKER.write(tmp_path)
    assert CHECKER.check(tmp_path) == 0
    # Move the map somewhere the inventory does not count, then check with it.
    elsewhere = tmp_path / "map.md"
    elsewhere.write_text((docs / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    (docs / "README.md").unlink()
    assert CHECKER.check(tmp_path, map_path=elsewhere) == 1


def test_a_missing_marker_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """Turns red if: a map without markers is treated as current."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# map with no markers\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        CHECKER.check(tmp_path)


def _recipe(target: str) -> list[str]:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(f"{target}:")]
    assert len(starts) == 1, f"expected one {target}: line, found {starts}"
    body = []
    for line in lines[starts[0] + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line)
    return body


def test_the_gate_is_wired_into_make_validate() -> None:
    """A gate nothing invokes is not a gate (same shape as the open-work check's
    wiring test, which review defeated twice before it took this form)."""
    makefile = MAKEFILE.read_text(encoding="utf-8")
    prerequisites = [line for line in makefile.splitlines() if line.startswith("validate:")]
    assert len(prerequisites) == 1, f"expected one validate: line, found {prerequisites}"
    assert "docs-map-check" in prerequisites[0], (
        "make validate no longer depends on docs-map-check: " + prerequisites[0]
    )
    body = _recipe("docs-map-check")
    assert body, "docs-map-check has an empty recipe -- it would do nothing"
    runner = [line for line in body if "check_docs_map.py" in line and "--check" in line]
    assert runner, "the docs-map-check RECIPE no longer runs the checker with --check: " + repr(
        body
    )
    for line in runner:
        assert not line.lstrip("\t").lstrip("@+").startswith("-"), (
            "the recipe ignores the checker's exit status via make's `-` prefix: " + repr(line)
        )
