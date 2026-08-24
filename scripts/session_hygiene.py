#!/usr/bin/env python3
"""Report what a working session left behind, and split it into the two jobs.

Cleanup is TWO jobs with OPPOSITE verbs, and conflating them is how untracked
work gets destroyed:

  JOB A  residue this session created  -> DELETE, by name
  JOB B  documents the project accrued -> ARCHIVE (git mv + commit), never delete

Applying Job B's caution to Job A leaves scratch files and stale artifacts
forever. Applying Job A's verb to Job B destroys a colleague's untracked handoff,
which has no git history to recover from. Same word, opposite correct action.

Usage
  python3 scripts/session_hygiene.py            report both jobs; change nothing
  python3 scripts/session_hygiene.py --residue  delete Job A by name
  python3 scripts/session_hygiene.py --archive  stage Job B into the archive

Never one flag for both. Never a wildcard: every deletion names its path.

Exit codes follow the "findings are not errors" rule — a report of work to do is
not a failure:
  0  the run did its job (even if it found things to clean)
  1  the run itself could not complete, or a floor found nothing to measure
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs" / "archive"

# --- Job A: residue this repo's work creates. Deleted BY NAME, never by glob. --
RESIDUE_PATHS = [
    "build/mutation",
    "mutants",
    ".mutmut-cache",
    ".data/feedback_events.sqlite3",
]

# --- Job B: where session output accumulates --------------------------------
DOC_DIRS = ["docs/analysis"]
DOC_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")

# A future session RUNS these, so they stay where they are (AGENTS.md).
PROCEDURE = re.compile(r"-ULTRACODE-PROMPT\.md$")

# Hazard 3: a script globs this by a hardcoded directory. Moving it breaks the
# handoff pointer silently — scripts/session_handoff.py prints "None found" and
# still exits 0. Off-limits to any automated mover.
OFFLIMITS = re.compile(r"-session-handoff.*\.md$")

# Hazard 4: gates that assert literal paths. Grepped, not assumed.
REFERENCE_DIRS = ["scripts", "tests", ".github", "configs"]
REFERENCE_FILES = ["pyproject.toml", "Makefile"]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def untracked() -> list[str]:
    out = git("ls-files", "--others", "--exclude-standard")
    return [p for p in out.splitlines() if p]


def is_referenced(rel: str) -> str | None:
    """Hazard 4: is this path asserted by a gate? Returns the first citation."""
    name = Path(rel).name
    targets = [str(ROOT / d) for d in REFERENCE_DIRS if (ROOT / d).is_dir()]
    targets += [str(ROOT / f) for f in REFERENCE_FILES if (ROOT / f).is_file()]
    if not targets:
        return None
    res = subprocess.run(
        ["grep", "-rl", "--", name, *targets], capture_output=True, text=True, check=False
    )
    hit = res.stdout.strip().splitlines()
    return hit[0] if hit else None


def ignored_at(dest: Path) -> bool:
    """Hazard 2: an ignore rule with no directory anchor follows the file in."""
    res = subprocess.run(
        ["git", "check-ignore", "-q", str(dest)], cwd=ROOT, capture_output=True, check=False
    )
    return res.returncode == 0


def classify() -> tuple[list[dict], list[Path]]:
    """Return (job B candidates, job A residue that exists)."""
    docs: list[dict] = []
    for rel in untracked():
        p = Path(rel)
        in_doc_dir = any(rel.startswith(d + "/") for d in DOC_DIRS)
        at_root = p.parent == Path(".")

        if OFFLIMITS.search(p.name):
            verdict, why = "REFUSE", "a script discovers this by globbing a fixed directory"
        elif at_root and PROCEDURE.search(p.name):
            verdict, why = "KEEP", "a procedure a future session RUNS, so it stays at root"
        elif in_doc_dir and DOC_NAME.match(p.name):
            verdict, why = "ARCHIVE", "dated session output — read, never run"
        else:
            verdict, why = "REPORT", "no rule classifies this; a human decides"

        if verdict == "ARCHIVE":
            cited = is_referenced(rel)
            if cited:
                verdict, why = (
                    "REFUSE",
                    (
                        f"a gate mentions this FILENAME ({cited}).\n"
                        "           That is a NAME match, not proof of a dependency — it may be\n"
                        "           a fixture that merely reuses the name. Refusing anyway: a\n"
                        "           human check is cheaper than a broken gate"
                    ),
                )
        docs.append(
            {
                "path": rel,
                "verdict": verdict,
                "why": why,
                "tracked": bool(git("ls-files", "--", rel)),
            }
        )

    residue = [ROOT / r for r in RESIDUE_PATHS if (ROOT / r).exists()]
    return docs, residue


def report(docs: list[dict], residue: list[Path]) -> None:
    print("JOB A — residue this session created (verb: DELETE, by name)")
    if residue:
        for p in residue:
            print(f"  delete   {p.relative_to(ROOT)}")
    else:
        print("  (none present)")
    print("  keep     reusable caches (.venv, node_modules, browsers) — deliberately")

    print("\nJOB B — documents the project accrued (verb: ARCHIVE, never delete)")
    for group in ("ARCHIVE", "KEEP", "REFUSE", "REPORT"):
        rows = [d for d in docs if d["verdict"] == group]
        if not rows:
            continue
        for d in rows:
            flag = "" if d["tracked"] else "  [untracked: will be staged first]"
            print(f"  {group:8} {d['path']}{flag}")
            print(f"           -> {d['why']}")

    print("\nGit state")
    print(f"  unpushed commits : {len(git('log', 'origin/main..HEAD', '--oneline').splitlines())}")
    print(f"  worktrees        : {len(git('worktree', 'list').splitlines())}")
    # "*" marks the current branch and "+" one checked out in ANOTHER worktree.
    # Filtering only "*" let a "+ main" line through as a deletable branch.
    merged = [b.lstrip("*+ ").strip() for b in git("branch", "--merged", "main").splitlines()]
    merged = [b for b in merged if b and b != "main"]
    print(f"  merged branches  : {len(merged)}{' -> ' + ', '.join(merged) if merged else ''}")

    print("\nCounted")
    print(f"  untracked files examined : {len(docs)}")
    print(f"  residue paths present    : {len(residue)}")


def do_residue(residue: list[Path]) -> None:
    for p in residue:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        print(f"deleted {p.relative_to(ROOT)}")


def do_archive(docs: list[dict]) -> int:
    dest_dir = ARCHIVE / date.today().strftime("%Y-%m")
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for d in (x for x in docs if x["verdict"] == "ARCHIVE"):
        dest = dest_dir / Path(d["path"]).name
        if dest.exists():
            print(f"REFUSED {d['path']}: {dest.relative_to(ROOT)} already exists")
            continue
        if ignored_at(dest):
            print(f"REFUSED {d['path']}: an ignore rule follows it into the archive")
            continue
        # Hazard 1: git mv on an untracked file commits NOTHING. Stage first.
        if not d["tracked"]:
            subprocess.run(["git", "add", "--", d["path"]], cwd=ROOT, check=True)
        subprocess.run(["git", "mv", "--", d["path"], str(dest)], cwd=ROOT, check=True)
        print(f"staged  {d['path']} -> {dest.relative_to(ROOT)}")
        moved += 1
    if moved:
        print(f"\n{moved} file(s) staged. Review with 'git status', then commit yourself.")
        print("This tool never commits on your behalf.")
    return moved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--residue", action="store_true", help="delete Job A by name")
    ap.add_argument("--archive", action="store_true", help="stage Job B into the archive")
    args = ap.parse_args()

    if args.residue and args.archive:
        print("ERROR: --residue and --archive are separate jobs with opposite verbs.")
        print("Run them one at a time, on purpose.")
        return 1

    docs, residue = classify()

    # Floor — and note what it does NOT assert. For a gate over a population that
    # must exist (skills, requirements), "measured nothing" means broken. This
    # tool is different: a genuinely clean tree legitimately has nothing to
    # clean, so "found nothing" must NOT be an error. The floor therefore checks
    # that the tool could OBSERVE, not that it FOUND.
    #
    # The first version conflated the two AND was dead code: its condition
    # included "not git('worktree', 'list')", which is never true because git
    # always lists at least the main worktree. A floor that can never fire is
    # exactly the vacuity this tool's own docstring warns about.
    if not git("rev-parse", "--is-inside-work-tree"):
        print(
            "FLOOR: git did not answer — not a repository, or git is unavailable. "
            "This is a broken run, not a clean tree."
        )
        return 1

    if args.residue:
        do_residue(residue)
        return 0
    if args.archive:
        do_archive(docs)
        return 0

    report(docs, residue)
    if not docs and not residue:
        print("\nNothing to clean — no untracked files and no residue present.")
    print("\nNothing was changed. Use --residue or --archive to act, one at a time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
