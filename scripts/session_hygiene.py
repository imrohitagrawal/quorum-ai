#!/usr/bin/env python3
"""Report what a working session left behind, and split it into the two jobs.

Cleanup is TWO jobs with OPPOSITE verbs, and conflating them is how untracked
work gets destroyed:

  JOB A  residue this session created  -> DELETE, by name
  JOB B  documents the project accrued -> ARCHIVE (git mv + commit), never delete

Applying Job B's caution to Job A leaves scratch files and stale artifacts
forever. Applying Job A's verb to Job B destroys a colleague's untracked handoff,
which has no git history to recover from. Same word, opposite correct action.

Job A is split into eight named CATEGORIES (see ``CATEGORIES`` below). Each one
declares its own verb, and only a DELETE category may ever remove a file. A
REPORT category names what it found and the command a human should run; it never
acts. That split is the whole safety design, and the gate restates the table
independently so the two cannot drift apart.

Usage
  python3 scripts/session_hygiene.py            report both jobs; touch no file
  python3 scripts/session_hygiene.py --residue  delete Job A by name
  python3 scripts/session_hygiene.py --archive  stage Job B into the archive

Never one flag for both. Never a wildcard: every deletion names its path.

The reporting run touches no file, ref, index or working tree. It is not
literally inert: answering "is this branch merged?" writes an unreferenced tree
object into the object store, which ordinary garbage collection reclaims. There
is no variant of that question that answers without writing one.

Exit codes follow the "findings are not errors" rule -- a report of work to do is
not a failure:
  0  the run did its job (even if it found things to clean)
  1  the run itself could not complete, or a floor found nothing to measure
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs" / "archive"

DELETE = "DELETE"
REPORT = "REPORT"

# --- Job B: where session output accumulates --------------------------------
DOC_DIRS = ["docs/analysis"]
DOC_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")

# A future session RUNS these, so they stay where they are (AGENTS.md).
PROCEDURE = re.compile(r"-ULTRACODE-PROMPT\.md$")

# Hazard 3: a script globs this by a hardcoded directory. Moving it breaks the
# handoff pointer silently -- the finder prints "None found" and still exits 0.
# Off-limits to any automated mover.
OFFLIMITS = re.compile(r"-session-handoff.*\.md$")

# Hazard 4: gates that assert literal paths. Grepped, not assumed.
REFERENCE_DIRS = ["scripts", "tests", ".github", "configs"]
REFERENCE_FILES = ["pyproject.toml", "Makefile"]

# --- Job A category inputs. Every path is LITERAL. --------------------------
# Never a sweep derived from the ignore file: all of ``build/`` is ignored, and
# it also holds gate output that the Makefile gate-integrity test writes and
# reads. The local data directory is ignored wholesale too, and holds a run
# history database that is NOT residue.
BUILD_ARTIFACT_PATHS = ["build/mutation", "mutants", ".mutmut-cache", "htmlcov"]
POISONED_STATE_PATHS = [".data/feedback_events.sqlite3"]

# Machine-regenerable: re-running the suite recreates these exactly.
REGENERABLE_ARTIFACT_PATHS = [
    "e2e/test-results",
    "e2e/playwright-report",
    "e2e/results.xml",
]
# A human may have captured these deliberately, so they are reported, not
# deleted. The temporary-artifacts directory holds a hand-made screen recording;
# only its author knows whether it is finished with.
# ``.playwright-mcp`` is in this list, not the one above, and the distinction
# was measured: `grep -rIl playwright-mcp` over the tree matches ONLY
# `.gitignore`. Nothing in the suite, no workflow and no Makefile target writes
# it -- it is filled when a human drives the browser by hand through the
# Playwright MCP server, and re-running the suite does NOT recreate it. On this
# machine it holds 15 console logs and page snapshots from June.
CAPTURED_ARTIFACT_PATHS = ["temp-artifacts", "quorum-final-run.png", ".playwright-mcp"]

# Reviewer scratch: hand-written specs and human-review captures. Reported, not
# deleted -- the local review spec directory is the known cause of a locally RED
# orphaned-spec gate (AGENTS.md rule 13a), so surfacing it is useful, but the
# specs in it are hand-written and have no git history.
REVIEWER_SCRATCH_PATHS = ["e2e/tests/review", "e2e/review-screenshots", "mutants-probe"]

# Reusable caches. Named so the report can promise, in one place, what it will
# never touch.
KEEP_CACHES = [".venv", ".uv-cache", "e2e/node_modules", ".pytest_cache", ".mypy_cache"]

# Category 8: a dependency here is either declared in a manifest or hand
# installed into the virtual environment, where nothing can tell it from a
# transitive pin of a declared one. So the check is manifest DRIFT, which is
# precise and offline.
DEPENDENCY_MANIFESTS = ["pyproject.toml", "uv.lock", "e2e/package.json", "e2e/package-lock.json"]

# Category 7: an explicit allowlist of image names this repo's own tooling
# builds. Never a filter, never a prune, never "dangling".
BUILT_IMAGE_TAGS = ["quorum-ai:local"]

#: Overridable so the gate can point the scratchpad scan at a sandbox.
SCRATCH_ROOT_ENV = "SESSION_HYGIENE_SCRATCH_ROOT"
UUID_DIR = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
#: A git object id. 64 hex digits in a SHA-256 repository, 40 in a SHA-1 one.
OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


@dataclass(frozen=True)
class Finding:
    """One thing a category found, and the verb that applies to it."""

    label: str
    verb: str
    why: str
    path: Path | None = None


@dataclass(frozen=True)
class Category:
    """One named kind of residue.

    ``verb`` is the STRONGEST verb the category may emit. A ``REPORT`` category
    that emits a ``DELETE`` finding is a coding error, and ``refuse_reason``
    catches it rather than trusting the finder.
    """

    number: int
    key: str
    title: str
    verb: str
    find: Callable[[], list[Finding]] = field(repr=False)


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def git_run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


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


# --------------------------------------------------------------------------
# Category finders
# --------------------------------------------------------------------------


def _named(paths: list[str], verb: str, why: str) -> list[Finding]:
    """Findings for whichever of the LITERAL *paths* exist. Never a glob."""
    out = []
    for rel in paths:
        p = ROOT / rel
        if p.exists() or p.is_symlink():
            out.append(Finding(label=rel, verb=verb, why=why, path=p))
    return out


def find_build_artifacts() -> list[Finding]:
    return _named(
        BUILD_ARTIFACT_PATHS, DELETE, "build output -- regenerated by re-running the gate"
    )


def find_poisoned_state() -> list[Finding]:
    return _named(
        POISONED_STATE_PATHS,
        DELETE,
        (
            "poisoned local state -- a stale mint cap makes the UI answer 429 and ~12 "
            "specs fail. The same events table also holds locally seeded audit and "
            "spend-rail events; production keeps its own database elsewhere"
        ),
    )


def worktree_paths() -> list[str]:
    """Every worktree's path, from the porcelain form.

    NOT ``git worktree list`` split on whitespace: measured, a worktree at
    ``/tmp/t12 wt`` is reported by that parse as ``/tmp/t12`` -- a DIFFERENT,
    existing directory -- inside a ``git worktree remove`` instruction. The
    porcelain form puts the path on its own line and is unambiguous.
    """
    return [
        line[len("worktree ") :]
        for line in git("worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    ]


def merge_tree_supported() -> bool:
    """Can this git answer the merged question at all?

    A POSITIVE self-test with a known answer, run once, rather than a version
    comparison: merging HEAD into itself must produce HEAD's own tree. Measured
    -- PASS on git 2.54.0 and on Apple git 2.50.1; on git 2.32.7, which predates
    ``--write-tree`` (added in 2.38), it exits 128 with ``unknown rev
    --write-tree`` and an EMPTY stdout. That failure is indistinguishable
    per-branch from "unrelated histories", which is why the test runs up front
    instead of being inferred from one branch's result.

    It writes no new object: HEAD's tree is already in the store.
    """
    res = git_run("merge-tree", "--write-tree", "HEAD", "HEAD")
    first = _first_oid(res.stdout)
    return bool(res.returncode == 0 and first and first == git("rev-parse", "HEAD^{tree}"))


def merge_driver_risk() -> bool:
    """Is a custom merge driver in play?

    ``merge-tree`` honours ``.gitattributes``. A committed ``*.txt merge=ours``
    plus a ``merge.ours.driver`` config makes a merge resolve silently in the
    base's favour: measured, a branch holding work found nowhere on the base
    reported EXIT 0 and the base's own tree -- a FALSE MERGED, with no warning.
    Neither half is present in this repository today, but a driver can arrive
    from a user's global config, so the answer is checked, not assumed. When it
    is true every verdict is downgraded to "cannot tell".
    """
    if git_run("config", "--get-regexp", r"^merge\..*\.driver").returncode == 0:
        return True
    res = git_run("grep", "--quiet", "-e", "merge=", "HEAD", "--", ".gitattributes")
    return res.returncode == 0


def _first_oid(text: str) -> str:
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    return first if OID.match(first) else ""


def base_ref() -> str | None:
    """The trunk a branch must be on before its content is safe to lose.

    ``refs/remotes/origin/main`` first, because "merged" for a cleanup tool
    means "on the PUBLISHED trunk" -- and this repository's own close-out rule
    records that local ``main`` does not follow the remote after a merge, so it
    is routinely behind. Measured: with local main one commit behind, the same
    branch reports UNMERGED against ``refs/heads/main`` and MERGED against
    ``refs/remotes/origin/main``; the second is the correct answer.

    Always FULLY QUALIFIED. A bare ``main`` resolves ``refs/tags/main`` first
    (gitrevisions), and a tag shadowing a branch name is a measured FALSE
    MERGED: with ``git tag feature main`` in place, ``git merge-tree
    --write-tree main feature`` printed the base's own tree and only a
    ``warning: refname 'feature' is ambiguous`` on stderr.
    """
    for ref in ("refs/remotes/origin/main", "refs/heads/main"):
        if git_run("rev-parse", "--verify", "--quiet", ref).returncode == 0:
            return ref
    return None


def branch_is_merged(branch_ref: str, base: str) -> bool | None:
    """Is every change on *branch_ref* already present on *base*?

    Squash-aware, which is the whole point. This repository squash-merges every
    pull request, and after a squash ``git branch --merged`` reports the branch
    as UNMERGED -- its commits are not ancestors -- while its content is
    entirely on the base. Measured on git 2.54.0, for a two-commit branch
    squashed into one commit with the base then moved on: ``git branch --merged
    main`` printed only ``main``, ``git merge-base --is-ancestor`` said no,
    ``git diff --quiet`` said the trees differ, and ``git cherry`` marked BOTH
    commits unmerged -- a squash of more than one commit preserves no patch-id.

    Returns True/False, or None for "cannot tell". The verdict keys on the
    OUTPUT SHAPE, not the exit code, because the code is overloaded. Measured:

      exit 0, an object id  -> clean merge; compare it with the base's tree
      exit 1, an object id  -> real conflicts; the branch holds changes -> False
      exit 1, EMPTY stdout  -> a ref that could not be merged      -> None
      exit 128/129, empty   -> unrelated histories, or a git too old -> None

    Both arguments must already be fully qualified refs; see ``base_ref``.
    """
    res = git_run("merge-tree", "--write-tree", base, branch_ref)
    first = _first_oid(res.stdout)
    if not first:
        return None
    if res.returncode != 0:
        return False
    base_tree = git("rev-parse", f"{base}^{{tree}}")
    if not OID.match(base_tree):
        return None
    return first == base_tree


def find_branches_and_worktrees() -> list[Finding]:
    """Local branches whose content is already on the trunk, plus extra worktrees.

    REPORT only, deliberately. Deleting a branch whose pull request was never
    merged loses its distinct commits to the reflog, and a branch that has not
    committed yet tests as merged by every available method -- including this
    one, which fixes squash detection and inherits that case. A branch checked
    out in ANY worktree is flagged as checked out, with the worktree named, and
    is never offered for deletion without that warning -- it is NOT hidden,
    because the fact that it is merged is still worth knowing.
    """
    out: list[Finding] = []
    # The worktree list has nothing to do with the trunk, so it is gathered
    # FIRST. An earlier version returned early when no trunk ref resolved and
    # printed "(none present)" for this category while the same report's git
    # state line said there were two worktrees -- a report contradicting itself.
    for path in worktree_paths()[1:]:
        out.append(
            Finding(
                label=f"worktree {path}",
                verb=REPORT,
                why="remove with 'git worktree remove' once its branch is merged",
            )
        )
    base = base_ref()
    if base is None:
        out.append(
            Finding(
                label="merged branches",
                verb=REPORT,
                why=(
                    "cannot tell -- neither refs/remotes/origin/main nor refs/heads/main "
                    "resolves, so there is no trunk to compare against"
                ),
            )
        )
        return out
    unsure = None
    if not merge_tree_supported():
        unsure = "this git cannot answer the question (it has no 'merge-tree --write-tree')"
    elif merge_driver_risk():
        unsure = "a custom merge driver is configured, which can fake a clean merge"
    fmt = "--format=%(refname)%09%(worktreepath)"
    for line in git("for-each-ref", fmt, "refs/heads/").splitlines():
        refname, _, worktree = line.partition("\t")
        refname = refname.strip()
        if not refname.startswith("refs/heads/"):
            continue
        # NOT %(refname:short): that abbreviation is ambiguity-dependent and
        # returns "heads/feature" when a tag shares the name.
        branch = refname[len("refs/heads/") :]
        if refname == base or branch == "main":
            continue
        if git("rev-list", "--count", f"{base}..{refname}") == "0":
            continue  # no unique commits -- nothing was left behind here
        verdict = None if unsure else branch_is_merged(refname, base)
        if verdict is None:
            out.append(
                Finding(
                    label=f"branch {branch}",
                    verb=REPORT,
                    why=(
                        "cannot tell whether it is merged -- "
                        + (
                            unsure
                            or "git could not merge these refs; unrelated histories, "
                            "or a ref it could not read"
                        )
                    ),
                )
            )
        elif verdict:
            note = f"content already on {base}, squash-aware"
            if worktree.strip():
                note += f"; CHECKED OUT at {worktree.strip()} -- remove that worktree first"
            out.append(
                Finding(
                    label=f"branch {branch}",
                    verb=REPORT,
                    why=f"{note}. Delete by hand: git branch -D -- {branch}",
                )
            )
    return out


def scratch_root() -> Path:
    """Where session scratchpads live.

    The agent harness mandates a per-session directory under a per-user
    temporary root, named for the project. Everything under a session's
    directory belongs to that session BY CONSTRUCTION, so no pattern matching
    is needed -- only the directory name.
    """
    override = os.environ.get(SCRATCH_ROOT_ENV)
    if override:
        return Path(override)
    slug = str(ROOT).replace("/", "-")
    return Path("/private/tmp") / f"claude-{os.getuid()}" / slug


def find_scratch_and_proof() -> list[Finding]:
    """Session scratchpads. REPORT only, and deliberately so.

    This is the one category whose paths lie OUTSIDE the repository, and the
    tool holds a hard containment invariant: it never deletes outside its own
    root. A sibling directory may belong to a session that is still running,
    and the harness's session-id variable is INHERITED by subagents -- measured
    on this box, a subagent shell carries the parent's id -- so a child process
    reading it would be naming its PARENT's live scratchpad. The tool names the
    directory; a human runs the command.
    """
    root = scratch_root()
    if not root.is_dir():
        return []
    mine = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    child = os.environ.get("CLAUDE_CODE_CHILD_SESSION", "")
    out: list[Finding] = []
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_dir() or not UUID_DIR.match(entry.name):
            continue
        if mine and entry.name == mine:
            who = (
                "the id this process inherited -- you are a SUBAGENT, so this is the"
                " PARENT session's scratchpad and it is LIVE"
                if child
                else "this session's own scratchpad"
            )
        else:
            who = "another session -- it may still be running"
        out.append(
            Finding(
                label=str(entry / "scratchpad"),
                verb=REPORT,
                why=f"{who}. Delete by hand once that session has ended",
            )
        )
    return out


def find_downloaded_artifacts() -> list[Finding]:
    return _named(
        REGENERABLE_ARTIFACT_PATHS,
        DELETE,
        "test and browser output -- re-running the suite recreates it",
    ) + _named(
        CAPTURED_ARTIFACT_PATHS,
        REPORT,
        "a human may have captured this deliberately; only its author knows",
    )


def find_reviewer_scratch() -> list[Finding]:
    """Reviewer copies and review scratch. REPORT only.

    AGENTS.md rule 12b tells a reviewer that must mutate source to take its own
    copy. Those copies carry a real ``.git`` and are indistinguishable by shape
    from a genuine checkout, so nothing here is ever deleted automatically.
    """
    out = _named(
        REVIEWER_SCRATCH_PATHS,
        REPORT,
        "hand-written review scratch with no git history; delete by hand when done",
    )
    held = {Path(p).resolve() for p in worktree_paths()}
    for entry in sorted(ROOT.iterdir()):
        if entry.is_symlink() or not entry.is_dir() or entry.name == ".git":
            continue
        if (entry / ".git").exists() and entry.resolve() not in held:
            out.append(
                Finding(
                    label=entry.name,
                    verb=REPORT,
                    why="a checkout git does not know as a worktree -- a reviewer copy, or yours",
                )
            )
    return out


def docker_project() -> str:
    """Compose derives its project name from the directory it runs in."""
    return re.sub(r"[^a-z0-9_-]", "", ROOT.name.lower())


def find_containers_and_images() -> list[Finding]:
    """Containers and images this repo's tooling builds. REPORT only.

    Never a system prune, never a "dangling" filter, never a substring match on
    the product name: an unrelated image whose name merely starts the same way
    would match one, and a prune destroys every other project's images too.
    Names are listed explicitly and compared exactly.
    """
    if shutil.which("docker") is None:
        return []
    project = docker_project()
    wanted = set(BUILT_IMAGE_TAGS) | {f"{project}-app"}
    out: list[Finding] = []
    imgs = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if imgs.returncode != 0:
        # "I could not look" must not print as "nothing there". The CLI is on
        # PATH even when the daemon is down, so an ignored exit code turns a
        # broken query into a clean bill of health.
        return [
            Finding(
                label="docker",
                verb=REPORT,
                why="could not be queried, so this category measured NOTHING -- is the daemon up?",
            )
        ]
    for line in imgs.stdout.splitlines():
        name = line.strip()
        if name and (name in wanted or name.split(":")[0] in wanted):
            out.append(
                Finding(
                    label=f"image {name}",
                    verb=REPORT,
                    why=f"built by this repo. Remove by name: docker image rm {name}",
                )
            )
    ps = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if ps.returncode != 0:
        out.append(
            Finding(
                label="docker containers",
                verb=REPORT,
                why="could not be queried, so no container was examined",
            )
        )
        return out
    for line in ps.stdout.splitlines():
        name = line.strip()
        if name:
            out.append(
                Finding(
                    label=f"container {name}",
                    verb=REPORT,
                    why=f"this project's compose container. Remove by name: docker rm {name}",
                )
            )
    return out


def find_one_off_dependencies() -> list[Finding]:
    """Dependency manifests left modified. REPORT only, and it cannot be more.

    A package installed by hand into the virtual environment is
    indistinguishable from a transitive pin of a declared one -- the property
    tests' own dependency reached this repo only transitively for a while, so
    uninstalling "undeclared" packages would have broken them. What IS precise
    and offline is manifest drift: a dependency added for one experiment and
    left behind shows up as a modified manifest.
    """
    out: list[Finding] = []
    present = [m for m in DEPENDENCY_MANIFESTS if (ROOT / m).is_file()]
    if not present:
        return out
    for raw in git("diff", "--name-only", "HEAD", "--", *present).splitlines():
        rel = raw.strip()
        if rel:
            out.append(
                Finding(
                    label=rel,
                    verb=REPORT,
                    why=(
                        "a dependency manifest is modified. If that was a one-off "
                        "experiment, revert it; a full sync then restores the environment"
                    ),
                )
            )
    return out


#: The eight categories, in specification order. ``verb`` is the strongest verb
#: each may emit. The gate restates this table independently and fails if the
#: two ever drift apart, so a category cannot be specified and left unbuilt.
CATEGORIES: tuple[Category, ...] = (
    Category(1, "build_artifacts", "Build/run artifacts", DELETE, find_build_artifacts),
    Category(2, "poisoned_state", "Poisoned local state", DELETE, find_poisoned_state),
    Category(
        3,
        "branches_worktrees",
        "Feature branches and worktrees",
        REPORT,
        find_branches_and_worktrees,
    ),
    Category(4, "scratch_and_proof", "Scratch and proof files", REPORT, find_scratch_and_proof),
    Category(5, "downloaded_artifacts", "Downloaded artifacts", DELETE, find_downloaded_artifacts),
    Category(6, "reviewer_scratch", "Reviewer scratch copies", REPORT, find_reviewer_scratch),
    Category(7, "containers_images", "Containers and images", REPORT, find_containers_and_images),
    Category(
        8,
        "one_off_dependencies",
        "One-off third-party dependencies",
        REPORT,
        find_one_off_dependencies,
    ),
)


def collect() -> list[tuple[Category, list[Finding]]]:
    return [(c, c.find()) for c in CATEGORIES]


# --------------------------------------------------------------------------
# Job B classification
# --------------------------------------------------------------------------


def classify() -> list[dict[str, object]]:
    """Job B candidates: untracked documents the project accrued."""
    docs: list[dict[str, object]] = []
    for rel in untracked():
        p = Path(rel)
        in_doc_dir = any(rel.startswith(d + "/") for d in DOC_DIRS)
        at_root = p.parent == Path(".")

        if OFFLIMITS.search(p.name):
            verdict, why = "REFUSE", "a script discovers this by globbing a fixed directory"
        elif at_root and PROCEDURE.search(p.name):
            verdict, why = "KEEP", "a procedure a future session RUNS, so it stays at root"
        elif in_doc_dir and DOC_NAME.match(p.name):
            verdict, why = "ARCHIVE", "dated session output -- read, never run"
        else:
            verdict, why = "REPORT", "no rule classifies this; a human decides"

        if verdict == "ARCHIVE":
            cited = is_referenced(rel)
            if cited:
                verdict, why = (
                    "REFUSE",
                    (
                        f"a gate mentions this FILENAME ({cited}).\n"
                        "           That is a NAME match, not proof of a dependency -- it may be\n"
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
    return docs


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def report(docs: list[dict[str, object]], found: list[tuple[Category, list[Finding]]]) -> None:
    total = sum(len(f) for _, f in found)
    deletable = sum(1 for _, fs in found for f in fs if f.verb == DELETE)
    print("JOB A -- residue this session created (a verb per category, never a sweep)")
    for cat, findings in found:
        print(f"\n  [{cat.number}] {cat.title}  (may {cat.verb})")
        if not findings:
            print("      (none present)")
            continue
        for f in findings:
            print(f"      {f.verb:6} {f.label}")
            print(f"             -> {f.why}")
    print("\n  keep     reusable caches, deliberately: " + ", ".join(KEEP_CACHES))

    print("\nJOB B -- documents the project accrued (verb: ARCHIVE, never delete)")
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
    print(f"  merged against   : {base_ref() or 'no trunk ref found'}")

    print("\nCounted")
    print(f"  categories examined      : {len(CATEGORIES)}")
    print(f"  residue findings         : {total}")
    print(f"  deletable by --residue   : {deletable}")
    print(f"  untracked files examined : {len(docs)}")


# --------------------------------------------------------------------------
# Acting
# --------------------------------------------------------------------------


def index_unreadable() -> str | None:
    """The POSITIVE partner for the tracked-content guard, or None if git is fine.

    "git tracks nothing here" is a negative check, and a negative check over a
    git that is not answering is trivially true -- it reads as "safe to delete".
    Two measured ways that happens, both with the work-tree floor still green:

      * a corrupt index -- ``git ls-files`` exits 128 with an EMPTY stdout;
      * ``GIT_INDEX_FILE`` pointing at a file that does not exist -- measured,
        ``git ls-files -- htmlcov`` exits **0** with an EMPTY stdout, so even an
        exit-code check would pass it through.

    So the tool proves git can list SOMETHING before it trusts an empty answer
    about anything. When this returns a reason, every deletion is refused.
    """
    res = git_run("ls-files", "--", ".")
    if res.returncode != 0:
        return f"git could not read the index (ls-files exited {res.returncode})"
    if git("rev-parse", "--verify", "--quiet", "HEAD") and not res.stdout.strip():
        return "git listed no tracked file at all though HEAD exists -- the index is unread"
    return None


def holds_a_checkout(p: Path) -> bool | None:
    """Is there a ``.git`` anywhere under *p*? None means the walk failed.

    At ANY depth, not just the top. Measured: with the check at the top level
    only, a repository at ``mutants/reviewer-copy`` -- exactly where a mutation
    harness and a reviewer both work -- was destroyed by ``rmtree`` on
    ``mutants``, and the tracked-content guard could not see it either, because
    a nested repository is untracked in the outer one.

    A walk that cannot complete returns None and the caller refuses: an
    unreadable subtree is a reason to keep, never a reason to delete.
    """
    if not p.is_dir():
        return False
    try:
        for candidate in p.rglob(".git"):
            if candidate.exists() or candidate.is_symlink():
                return True
    except OSError:
        return None
    return False


def refuse_reason(cat: Category, f: Finding) -> str | None:
    """Why this finding must NOT be deleted. None means it is safe to delete.

    Each clause is a measured failure mode, not a hypothetical:

    * a REPORT category emitting DELETE is a coding error, caught here rather
      than trusted;
    * a path outside the root is the containment invariant. The previous
      version called ``relative_to(ROOT)`` AFTER the delete, so an escaping
      path would have been destroyed and then crashed the run without ever
      naming what it destroyed;
    * a symlink is a link into somebody else's tree. The session scratchpads on
      this machine alone hold many of them, pointing at real transcripts and at
      virtual environments inside the repository;
    * a tracked path holds content git is responsible for. This script's own
      author destroyed 38 tracked files with one recursive remove;
    * a path holding a ``.git`` is a checkout, not residue.
    """
    if cat.verb != DELETE:
        return f"category {cat.number} is {cat.verb}-only"
    if f.verb != DELETE:
        # A DELETE category may still emit REPORT findings -- the hand-made
        # captures inside "downloaded artifacts" are the case. Saying "category
        # 5 is DELETE-only" here stated the opposite of the truth.
        return "this finding is REPORT-only, though its category may delete"
    p = f.path
    if p is None:
        return "the finding names no path"
    if p.is_symlink():
        return "it is a symlink -- following it would reach outside this repository"
    try:
        rel = p.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return "it resolves outside the repository root"
    # "git tracks nothing here" is only trustworthy once git has been shown to
    # be answering at all. That proof is ``index_unreadable``, which
    # ``do_residue`` runs BEFORE any of this and which refuses every deletion
    # when it fails -- so there is exactly one place that handles "git could not
    # answer", and it is tested. A second per-path exit-code branch was written
    # here and then removed: no test could turn it red, because the probe stops
    # the run before this line is ever reached.
    if git("ls-files", "--", str(rel)):
        return "git tracks content here -- that is not residue"
    checkout = holds_a_checkout(p)
    if checkout is None:
        return "its contents could not be read, so it cannot be shown to be residue"
    if checkout:
        return "it holds a .git -- that is a checkout, not residue"
    return None


def do_residue(found: list[tuple[Category, list[Finding]]]) -> int:
    """Delete what may be deleted, one named path at a time.

    Every delete is caught. An earlier version let the first unremovable path
    -- one the user lacks permission on, or one that vanished between the check
    and the delete -- raise out of the loop: the tree was left half deleted,
    every later category went unexamined, and the summary line naming what had
    gone was never printed. ``shutil.rmtree`` is itself partly destructive
    before it raises, so "it crashed" and "nothing happened" are not the same.
    """
    blocked = index_unreadable()
    deleted = 0
    failed = 0
    for cat, findings in found:
        for f in findings:
            why = blocked or refuse_reason(cat, f)
            if why is not None:
                print(f"REFUSED {f.label}: {why}")
                continue
            assert f.path is not None
            try:
                if f.path.is_dir() and not f.path.is_symlink():
                    shutil.rmtree(f.path)
                else:
                    f.path.unlink()
            except OSError as exc:
                print(f"FAILED  {f.label}: {exc}")
                failed += 1
                continue
            print(f"deleted {f.label}")
            deleted += 1
    print(f"\n{deleted} path(s) deleted, each named above. {failed} could not be removed.")
    return deleted


def do_archive(docs: list[dict[str, object]]) -> int:
    dest_dir = ARCHIVE / date.today().strftime("%Y-%m")
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for d in (x for x in docs if x["verdict"] == "ARCHIVE"):
        src = str(d["path"])
        dest = dest_dir / Path(src).name
        if dest.exists():
            print(f"REFUSED {src}: {dest.relative_to(ROOT)} already exists")
            continue
        if ignored_at(dest):
            print(f"REFUSED {src}: an ignore rule follows it into the archive")
            continue
        # Hazard 1: git mv on an untracked file commits NOTHING. Stage first.
        if not d["tracked"]:
            subprocess.run(["git", "add", "--", src], cwd=ROOT, check=True)
        subprocess.run(["git", "mv", "--", src, str(dest)], cwd=ROOT, check=True)
        print(f"staged  {src} -> {dest.relative_to(ROOT)}")
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

    # Floor -- and note what it does NOT assert. For a gate over a population
    # that must exist (skills, requirements), "measured nothing" means broken.
    # This tool is different: a genuinely clean tree legitimately has nothing to
    # clean, so "found nothing" must NOT be an error. The floor therefore checks
    # that the tool could OBSERVE, not that it FOUND.
    #
    # The first version conflated the two AND was dead code: its condition
    # included "not git('worktree', 'list')", which is never true because git
    # always lists at least the main worktree. A floor that can never fire is
    # exactly the vacuity this tool's own docstring warns about.
    if not git("rev-parse", "--is-inside-work-tree"):
        print(
            "FLOOR: git did not answer -- not a repository, or git is unavailable. "
            "This is a broken run, not a clean tree."
        )
        return 1

    docs = classify()
    found = collect()

    if args.residue:
        do_residue(found)
        return 0
    if args.archive:
        do_archive(docs)
        return 0

    report(docs, found)
    if not docs and not any(f for _, f in found):
        print("\nNothing to clean -- no untracked files and no residue present.")
    print("\nNothing was changed. Use --residue or --archive to act, one at a time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
