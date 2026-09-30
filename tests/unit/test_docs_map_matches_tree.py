"""The docs map's inventory is DERIVED from the tree, so it is verified, not trusted.

GATE CHARTER
------------
WHY THIS EXISTS: on 2026-09-30, 268 of 538 tracked ``.md`` files were not
reachable within three links of ``AGENTS.md``; a hand-kept list of documents
decays the way ``docs/24-adr-index.md`` did twice. ``docs/README.md`` is the
map; its generated part is written by ``scripts/check_docs_map.py`` and this
file proves the check bites.

WHAT IT CANNOT SEE: whether the hand-written table names the right home for a
kind of information, or whether a file inside a folder is worth reading. A new
doc is invisible until ``git add``ed (enumeration is ``git ls-files``).

FALSE-POSITIVE COST: low, not zero. The script and these tests read tracked
files only (``git ls-files``), so untracked scratch under ``docs/`` trips
neither; the gate does fire when a top-level file's first heading changes or
a folder gains an index file, which is a real change to what the map says.

The first version of this file had two tests that did not bite (measured by a
reviewer on 2026-09-30 with mutations): the floor test also presented a stale
inventory, so disabling the floor survived; and nothing exercised ``--check``,
so a script that always wrote survived -- and would have had ``make validate``
silently rewrite the map. Both are fixed below; the wiring test now also RUNS
``make docs-map-check`` against a stale throwaway tree.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_docs_map.py"
MAP = ROOT / "docs" / "README.md"
MAKEFILE = ROOT / "Makefile"

if (
    subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, cwd=ROOT
    ).returncode
    != 0
):
    pytest.skip(
        "not inside a git work tree (a bare `git archive` copy): the gate enumerates with "
        "`git ls-files`; run `git init && git add -A` in the copy first",
        allow_module_level=True,
    )


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("check_docs_map", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load()


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _tree(tmp_path: Path, names: list[str], *, with_map: bool = True) -> Path:
    """A throwaway git repository with ``docs/<names>`` tracked."""
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in names:
        (docs / name).write_text(f"# Title of {name}\n\nbody\n", encoding="utf-8")
    if with_map:
        (docs / "README.md").write_text(
            "# map\n\nhand-written part\n\n" + CHECKER.BEGIN + "\n" + CHECKER.END + "\n\ntrailer\n",
            encoding="utf-8",
        )
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    return tmp_path


def test_the_map_lists_exactly_the_docs_on_disk() -> None:
    """Turns red if: a tracked top-level docs/*.md or a docs/ folder is added,
    renamed or deleted without running ``python3 scripts/check_docs_map.py``."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, (
        f"docs/README.md's inventory is stale.\n{result.stdout}{result.stderr}"
        "\nFix: python3 scripts/check_docs_map.py"
    )
    # A script that WROTE instead of checking would also exit 0 -- and edit the
    # real map from inside the test suite. The check path announces itself.
    assert result.stdout.startswith("docs map current:"), result.stdout


def test_every_top_level_doc_is_a_row_and_there_are_many() -> None:
    """The positive partner: the check above would also pass over an empty map
    of an empty directory. Turns red if the inventory stops naming every file."""
    files = sorted(p.name for p in CHECKER._top_level_docs(ROOT))
    assert len(files) > 50, f"expected the real docs/ directory, found {len(files)} files"
    text = MAP.read_text(encoding="utf-8")
    generated = text[text.index(CHECKER.BEGIN) : text.index(CHECKER.END)]
    missing = [name for name in files if f"| `{name}` |" not in generated]
    assert not missing, f"top-level docs missing from the map's inventory: {missing}"
    folders = sorted(p.name for p in CHECKER._folders(ROOT))
    assert folders, "docs/ has no folders — wrong root?"
    missing_folders = [name for name in folders if f"| `{name}/` |" not in generated]
    assert not missing_folders, f"folders missing from the map's inventory: {missing_folders}"


def test_a_new_doc_turns_the_check_red_and_a_rewrite_turns_it_green(tmp_path: Path) -> None:
    """The bite-proof. Turns red if: ``check`` stops comparing the generated
    part against the tree (for example, always returns 0)."""
    root = _tree(tmp_path, ["10-a.md", "11-b.md", "UPPER.MD"])
    assert CHECKER.write(root) == 0
    assert CHECKER.check(root) == 0
    text = (root / "docs" / "README.md").read_text(encoding="utf-8")
    assert "| `10-a.md` | Title of 10-a.md |" in text
    assert "| `README.md` | map |" in text
    assert "| `UPPER.MD` | Title of UPPER.MD |" in text, "an upper-case .MD is a doc too"

    (root / "docs" / "12-c.md").write_text("# Title of 12-c.md\n", encoding="utf-8")
    assert CHECKER.check(root) == 0, "an UNTRACKED doc is invisible until git add (by design)"
    _git(root, "add", "-A")
    assert CHECKER.check(root) == 1, "a new tracked top-level doc must make the check fail"

    assert CHECKER.write(root) == 0
    assert CHECKER.check(root) == 0


def test_a_new_folder_turns_the_check_red(tmp_path: Path) -> None:
    """Turns red if: folders drop out of the inventory."""
    root = _tree(tmp_path, ["10-a.md"])
    CHECKER.write(root)
    (root / "docs" / "notes").mkdir()
    (root / "docs" / "notes" / "x.md").write_text("# x\n", encoding="utf-8")
    _git(root, "add", "-A")
    assert CHECKER.check(root) == 1


def test_the_hand_written_parts_survive_a_rewrite(tmp_path: Path) -> None:
    """Turns red if: ``write`` replaces more than the generated section, before
    OR after it."""
    root = _tree(tmp_path, ["10-a.md"])
    CHECKER.write(root)
    CHECKER.write(root)
    text = (root / "docs" / "README.md").read_text(encoding="utf-8")
    assert text.startswith("# map\n\nhand-written part\n\n")
    assert text.endswith(CHECKER.END + "\n\ntrailer\n")
    assert text.count(CHECKER.BEGIN) == 1 and text.count(CHECKER.END) == 1


def test_the_check_refuses_to_pass_over_no_docs(tmp_path: Path) -> None:
    """The floor, in isolation: the inventory MATCHES an empty tree, so only
    the floor can refuse. Turns red if: the floor is removed (then this
    returns 0 with 'docs map current: 0 top-level files')."""
    root = _tree(tmp_path, [], with_map=False)
    elsewhere = tmp_path / "map.md"
    elsewhere.write_text("x\n" + CHECKER.render_inventory(root), encoding="utf-8")
    assert CHECKER.check(root, map_path=elsewhere) == 1


def test_a_missing_or_duplicated_marker_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """Turns red if: a map without markers, or with two generated blocks (the
    second possibly stale), is treated as current."""
    root = _tree(tmp_path, ["10-a.md"], with_map=False)
    (root / "docs" / "README.md").write_text("# map with no markers\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        CHECKER.check(root)
    (root / "docs" / "README.md").write_text(
        (CHECKER.BEGIN + "\n" + CHECKER.END + "\n") * 2, encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        CHECKER.check(root)


def test_a_missing_map_is_red(tmp_path: Path) -> None:
    """Turns red if: a deleted docs/README.md leaves the check green (a
    reviewer's mutation ``return 0`` on the missing-file branch survived the
    second version of this file)."""
    root = _tree(tmp_path, ["10-a.md"], with_map=False)
    assert CHECKER.check(root) == 1
    os.environ["DOCS_MAP_ROOT"] = str(root)
    try:
        assert CHECKER.main(["--check"]) == 1
    finally:
        del os.environ["DOCS_MAP_ROOT"]


def test_a_heading_inside_a_code_fence_is_not_the_title(tmp_path: Path) -> None:
    """Turns red if: ``_title`` stops skipping fenced blocks (no real doc
    exercises that branch today, measured 2026-09-30 over all 128)."""
    doc = tmp_path / "fenced.md"
    doc.write_text("```\n# not the title\n```\n# Real\n", encoding="utf-8")
    assert CHECKER._title(doc) == "Real"
    tilde = tmp_path / "tilde.md"
    tilde.write_text("~~~\n# not the title\n~~~\n# Real\n", encoding="utf-8")
    assert CHECKER._title(tilde) == "Real"


def test_check_flag_checks_and_never_writes(tmp_path: Path) -> None:
    """Turns red if: ``main(["--check"])`` writes instead of checking. A
    reviewer's mutation (``return write()``) survived the first version of
    this file and made the real test suite edit docs/README.md."""
    root = _tree(tmp_path, ["10-a.md"])
    CHECKER.write(root)
    (root / "docs" / "11-b.md").write_text("# b\n", encoding="utf-8")
    _git(root, "add", "-A")
    before = (root / "docs" / "README.md").read_bytes()
    os.environ["DOCS_MAP_ROOT"] = str(root)
    try:
        assert CHECKER.main(["--check"]) == 1
    finally:
        del os.environ["DOCS_MAP_ROOT"]
    assert (root / "docs" / "README.md").read_bytes() == before, "--check must not write"


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


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_make_docs_map_check_fails_on_a_stale_tree(tmp_path: Path) -> None:
    """Executed, not read: ``make docs-map-check`` against a stale throwaway
    tree must exit non-zero. Turns red if: the recipe swallows the exit status
    (``|| true``), runs the script with ``--help``, echoes instead of running,
    or is otherwise gutted -- four shapes a text-only wiring test let through
    (measured 2026-09-30)."""
    root = _tree(tmp_path, ["10-a.md"])
    CHECKER.write(root)
    (root / "docs" / "11-b.md").write_text("# b\n", encoding="utf-8")
    _git(root, "add", "-A")
    env = dict(os.environ, DOCS_MAP_ROOT=str(root))
    result = subprocess.run(
        ["make", "docs-map-check", f"PYTHON={sys.executable}"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    assert result.returncode != 0, f"make docs-map-check passed on a stale tree:\n{result.stdout}"
    assert "inventory is stale" in result.stderr, result.stderr
    # The positive partner: the same target passes on the current tree.
    ok = subprocess.run(
        ["make", "docs-map-check", f"PYTHON={sys.executable}"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_the_gate_is_wired_into_make_validate() -> None:
    """A gate nothing invokes is not a gate. The prerequisite list is read from
    make itself (``make -n validate``), so a ``# docs-map-check`` comment on the
    ``validate:`` line cannot satisfy it (a text check was fooled that way,
    measured 2026-09-30)."""
    dry = subprocess.run(
        ["make", "-n", "validate", f"PYTHON={sys.executable}"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert dry.returncode == 0, dry.stderr
    # A whole line, not a substring: a look-alike target that merely ECHOES
    # the string satisfied a substring check (measured 2026-09-30).
    expected = f"{sys.executable} scripts/check_docs_map.py --check"
    assert expected in dry.stdout.splitlines(), (
        "make validate would not run scripts/check_docs_map.py --check:\n" + dry.stdout
    )
    body = _recipe("docs-map-check")
    for line in body:
        assert not line.lstrip("\t").lstrip("@+").startswith("-"), (
            "the recipe ignores the checker's exit status via make's `-` prefix: " + repr(line)
        )
