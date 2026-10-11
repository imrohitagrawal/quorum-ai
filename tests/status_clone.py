"""Shared support for the "one status" tests (ADR-0161, ADR-0162).

Those tests plant false completion claims and check that a support check rejects
them. A plant must never touch the real working tree, so every plant happens in a
disposable ``git clone --shared`` of this repository, made here.

THE CLONE CARRIES COMMITTED HISTORY ONLY. Its files are this repository's
``HEAD``, not the working tree, so an uncommitted edit here is invisible to it.
Commit before trusting a test that uses it, as with ``make diff-cover``
(AGENTS.md rule 15a). The scripts under test are always loaded from the REAL
working tree and pointed at the clone, so a script still being written is the
one measured.

THE MAIN REF. A clone made with ``--shared`` copies the source's LOCAL branches
as its ``origin/*`` refs. On a CI pull-request checkout there is no local
``main`` (HEAD is a detached merge commit), so the clone would have no ``main``
at all. ``make_clone`` therefore sets the clone's ``refs/remotes/origin/main`` to
the source's ``refs/remotes/origin/main``, or to its ``refs/heads/main`` when
there is no remote one: the same order the completion check uses.

Nothing here launches a Python interpreter; ``run_python`` is the one place that
does, and it always strips pytest-cov's variables (``tests/subprocess_env.py``).
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tests.subprocess_env import env_without_coverage

#: ``commit.gpgsign`` and ``protocol.file.allow`` are pinned because a global
#: config setting either kills a sandbox commit or a local-path clone (measured
#: in ``tests/unit/test_open_work_matches_reality.py``).
GIT_PINS = ("-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always")
_IDENTITY = ("Sandbox", "sandbox@example.invalid")

#: The cut-off commit of ADR-0162 (the merge of package A, #558). Literal, not
#: read from the script under test.
CUTOFF = "b66b107f3f36eeaeb943ce93776b4fd4ef72095a"

#: Anything shaped like a citation the completion check accepts: a pull request
#: number, a CHG row, or a 7-40 character hex commit id. Used only to prove a
#: planted paragraph or row cites NOTHING before the plant, so a rejection is
#: about the claim and not about a neighbouring citation.
CITATION_SHAPE = re.compile(r"#\d+|\bCHG-\d+|\b[0-9a-f]{7,40}\b")


def rel(*parts: str) -> str:
    """A repository-relative path, joined at run time.

    Joined rather than written whole so that a path to a file that does not
    exist yet is not read as a citation by ``tests/unit/test_cited_paths_resolve.py``.
    """
    return "/".join(parts)


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """One git command with a fixed sandbox identity and the two pins."""
    env = dict(os.environ)
    env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = _IDENTITY
    env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = _IDENTITY
    done = subprocess.run(
        ["git", *GIT_PINS, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    if check and done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} exited {done.returncode}: {done.stderr}")
    return done


def git_out(cwd: Path, *args: str) -> str:
    return git(cwd, *args).stdout.strip()


def main_sha(repo: Path) -> str:
    """``origin/main`` if this checkout has it, else the local ``main``."""
    for ref in ("refs/remotes/origin/main", "refs/heads/main"):
        found = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        if found.returncode == 0:
            return found.stdout.strip()
    raise AssertionError(f"{repo} has neither refs/remotes/origin/main nor refs/heads/main")


def make_clone(source: Path, dest: Path) -> Path:
    """A clone of ``source``'s HEAD at ``dest``, with ``origin/main`` set as above."""
    head = git_out(source, "rev-parse", "HEAD")
    main = main_sha(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(dest.parent, "clone", "--shared", "--no-checkout", "--quiet", str(source), str(dest))
    git(dest, "update-ref", "refs/remotes/origin/main", main)
    git(dest, "reset", "--hard", "--quiet", head)
    return dest


def status(clone: Path) -> str:
    """``git status --porcelain``, untracked files included."""
    return git(clone, "status", "--porcelain", "--untracked-files=all").stdout


def on_main_log(clone: Path, needle: str) -> int:
    """How many commit subjects on the clone's main contain ``needle`` literally."""
    out = git_out(
        clone,
        "log",
        "refs/remotes/origin/main",
        "--format=%s",
        "--fixed-strings",
        f"--grep={needle}",
    )
    return len([line for line in out.splitlines() if needle in line])


def is_ancestor_of_main(clone: Path, sha: str) -> bool:
    done = git(clone, "merge-base", "--is-ancestor", sha, "refs/remotes/origin/main", check=False)
    return done.returncode == 0


@contextmanager
def planted(clone: Path, edits: dict[str, str], *, stage: tuple[str, ...] = ()) -> Iterator[None]:
    """Write each ``edits`` path, run the body, then put the clone back exactly.

    ``stage`` paths are ``git add``-ed after writing: a new file must be
    tracked, because the completion check reads tracked files only. On exit
    every path the body changed is restored from ``HEAD`` (or deleted when
    ``HEAD`` does not have it), including files a generator rewrote, and the
    clone's status must equal what it was before the plant.
    """
    before = status(clone)
    try:
        for path, text in edits.items():
            target = clone / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for path in stage:
            git(clone, "add", "--", path)
        yield
    finally:
        changed = _changed_paths(clone, before)
        if changed:
            git(clone, "reset", "--quiet", "--", *changed)
        for path in changed:
            in_head = git(clone, "cat-file", "-e", f"HEAD:{path}", check=False).returncode == 0
            if in_head:
                git(clone, "restore", "--source=HEAD", "--worktree", "--", path)
            else:
                (clone / path).unlink(missing_ok=True)
        after = status(clone)
        assert after == before, f"the clone was not restored:\nbefore:\n{before}\nafter:\n{after}"


def _changed_paths(clone: Path, before: str) -> list[str]:
    baseline = set(before.splitlines())
    paths = []
    for line in status(clone).splitlines():
        if line in baseline:
            continue
        paths.append(line[3:].strip())
    return paths


def replace_once(text: str, old: str, new: str) -> str:
    """``text`` with ``old`` replaced; refuses unless ``old`` occurs exactly once."""
    count = text.count(old)
    assert count == 1, f"the plant anchor {old!r} occurs {count} times, not once"
    return text.replace(old, new)


def append_paragraph(text: str, line: str) -> tuple[str, int]:
    """``text`` with ``line`` appended as its own paragraph, and that line's number."""
    new = text.rstrip("\n") + "\n\n" + line + "\n"
    return new, len(new.splitlines())


def set_table_cell(text: str, first_cell: str, index: int, value: str) -> tuple[str, str]:
    """Replace cell ``index`` (as split on ``|``) of the row whose first cell is ``first_cell``.

    Returns the new text and the ORIGINAL row, so a caller can prove the row
    cited nothing before the plant.
    """
    lines = text.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if line.split("|")[1:2] == [f" {first_cell} "]]
    assert len(hits) == 1, f"row {first_cell!r} found {len(hits)} times, not once"
    original = lines[hits[0]]
    parts = original.rstrip("\n").split("|")
    parts[index] = f" {value} "
    lines[hits[0]] = "|".join(parts) + "\n"
    return "".join(lines), original


def paragraph_of(text: str, line_number: int) -> str:
    """The blank-line separated paragraph holding 1-based ``line_number``."""
    lines = text.splitlines()
    start = end = line_number - 1
    while start > 0 and lines[start - 1].strip():
        start -= 1
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return "\n".join(lines[start : end + 1])


def load_script(root: Path, stem: str) -> Any:
    """Load ``scripts/<stem>.py`` by path, never as a package import.

    Registered in ``sys.modules`` while it executes because a module defining
    dataclasses resolves its annotations through it (as in
    ``tests/unit/test_open_work_matches_reality.py``).
    """
    path = root / "scripts" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_one_status_{stem}", path)
    assert spec and spec.loader, f"cannot load {path}"
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def run_python(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """A Python child with pytest-cov's variables stripped (#368)."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env_without_coverage(PYTHONDONTWRITEBYTECODE="1"),
        check=False,
    )


def generated_console(root: Path, out_dir: Path) -> str:
    """What ``make next`` would write to the factory console for ``root``.

    ``scripts/factory_next.py`` has no pure render function: its
    ``update_console`` writes to ``<ROOT>/docs/``. So it is loaded from
    ``root``, its ``ROOT`` is pointed at ``out_dir`` for the write only, and
    the route still comes from ``root`` (its ``skill_router`` keeps its own
    ``ROOT``).
    """
    module = load_script(root, "factory_next")
    (out_dir / "docs").mkdir(parents=True, exist_ok=True)
    module.ROOT = out_dir
    module.update_console(module.skill_router.route())
    return (out_dir / "docs" / "00-factory-console.md").read_text(encoding="utf-8")
