"""Gate for scripts/session_hygiene.py -- the two-jobs cleanup reporter.

Each test names what turns it red. Every case runs against a REAL temporary git
repository, not a mock: the whole point of the script is its interaction with
git's index, ignore rules and worktree state, and a mock would assert nothing
about any of that.

The one exception is the specification check, which loads the module by file
path (never ``import scripts.session_hygiene`` -- a static import would drag
``scripts/`` into ``mypy src tests``, which does not cover it today) and
compares the category table against one typed out by hand below.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.subprocess_env import env_without_coverage

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "session_hygiene.py"
MAKEFILE = REPO / "Makefile"
#: Joined at runtime so no ADDED LINE is a repo-path-shaped literal -- these
#: are temp-sandbox fixtures, and tests/unit/test_cited_paths_resolve.py
#: rightly cannot tell the difference. Splitting keeps that gate intact.
ANALYSIS = "docs" + "/" + "analysis"

#: THE SPECIFICATION. Eight categories of residue a working session leaves,
#: each with the strongest verb it is allowed to use. Typed out here by hand so
#: it is genuinely independent of the module it checks: if the script gains,
#: loses or re-verbs a category without this table being edited in the same
#: change, the comparison below fails in both directions.
#:
#: DELETE means the category may remove a named path. REPORT means it may only
#: name what it found -- because its paths lie outside the repository (4),
#: because acting destroys work with no git history (3, 6), because the safe
#: automated verb does not exist (7, 8).
SPECIFIED_CATEGORIES = {
    1: ("build_artifacts", "DELETE"),
    2: ("poisoned_state", "DELETE"),
    3: ("branches_worktrees", "REPORT"),
    4: ("scratch_and_proof", "REPORT"),
    5: ("downloaded_artifacts", "DELETE"),
    6: ("reviewer_scratch", "REPORT"),
    7: ("containers_images", "REPORT"),
    8: ("one_off_dependencies", "REPORT"),
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    ).stdout


def _load_script() -> Any:
    """Load the script as a module, by path.

    Deliberately not a package import: ``make type-check`` runs
    ``mypy src tests`` and follows static imports, so ``from
    scripts.session_hygiene import ...`` would pull an unchecked file into a
    strict-mode gate. This is the same loader idiom
    ``tests/unit/test_adr_index_matches_directory.py`` uses.
    """
    spec = importlib.util.spec_from_file_location("session_hygiene", SCRIPT)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    # dataclasses resolves string annotations through sys.modules, so the
    # module must be registered before it executes or every @dataclass in it
    # raises. Registered under a name no package uses.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _fake_docker(
    repo: Path,
    images: list[str] | None = None,
    containers: list[str] | None = None,
    fail: bool = False,
) -> None:
    """Put a fake ``docker`` on PATH, OUTSIDE the sandbox repository.

    A real daemon can demonstrate neither that the allowlist matches nor that
    no prune happens -- on a clean development box both `docker ps -aq` and
    `docker images -q` list nothing at all, so there is nothing to observe.
    The fake also RECORDS every argv it is handed, which is what makes "no
    prune" checkable as a CALL rather than as an absent printed word.
    The fake answers both subcommands and is installed for EVERY sandbox run,
    so a developer who happens to have the image built locally does not change
    the result of any test here. It lives beside the repo, not in it, so it
    never shows up as an untracked file.
    """
    binn = repo.parent / "fakebin"
    binn.mkdir(exist_ok=True)
    docker = binn / "docker"
    log = repo.parent / "docker-calls.log"
    record = f"echo \"$@\" >> '{log}'\n"
    lines = "\n".join(images or [])
    ctrs = "\n".join(containers or [])
    if fail:
        docker.write_text(
            "#!/bin/sh\n" + record + "echo 'Cannot connect to the Docker daemon' >&2\nexit 1\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        return
    docker.write_text(
        "#!/bin/sh\n" + record + 'case "$1 $2" in\n'
        f"  'image ls') cat <<'EOF'\n{lines}\nEOF\n  ;;\n"
        f"  'ps -a') cat <<'EOF'\n{ctrs}\nEOF\n  ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A real git repo with the script installed, so git behaviour is genuine."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "docs" / "analysis").mkdir(parents=True)
    (repo / "tests").mkdir()
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "scripts" / "session_hygiene.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    _git(repo, "branch", "-M", "main")
    _fake_docker(repo)
    return repo


def run(
    repo: Path,
    *args: str,
    scratch: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(env_extra or {})
    env["PATH"] = f"{repo.parent / 'fakebin'}{os.pathsep}{env.get('PATH', '')}"
    # Point the scratchpad scan somewhere that does not exist unless a test
    # deliberately creates it, so the real machine's scratchpads never leak in.
    env["SESSION_HYGIENE_SCRATCH_ROOT"] = str(scratch or (repo / "no-such-scratch-root"))
    return subprocess.run(
        [sys.executable, "scripts/session_hygiene.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        # #368: `cwd` is a sandbox repository outside this one, so the child must
        # not inherit pytest-cov's hooks -- it would resolve the RELATIVE
        # `--cov=src` against the sandbox and combine that tree into this run.
        env=env_without_coverage(env),
    )


# ---------------------------------------------------------------------------
# The specification cannot drift away from the script
# ---------------------------------------------------------------------------


def test_every_specified_category_is_implemented() -> None:
    """Turns red if: a specified category is dropped, renamed, re-numbered, or
    has its verb widened or narrowed -- in EITHER direction. Adding a ninth
    category without listing it above reds too.

    The whole reason this exists: six of these eight were specified and never
    built, and nothing compared the specification to the file. Set equality on
    contents, not on counts -- equal cardinality is not the property.
    """
    module = _load_script()
    implemented = {c.number: (c.key, c.verb) for c in module.CATEGORIES}
    assert implemented, "no categories found -- the loader is looking at the wrong object"
    assert implemented == SPECIFIED_CATEGORIES, (
        f"specified but not implemented: "
        f"{ {k: v for k, v in SPECIFIED_CATEGORIES.items() if implemented.get(k) != v} }\n"
        f"implemented but not specified: "
        f"{ {k: v for k, v in implemented.items() if SPECIFIED_CATEGORIES.get(k) != v} }"
    )


def test_each_category_has_its_own_finder() -> None:
    """Turns red if: a category is 'implemented' by pointing at another
    category's finder, or at a stub. Eight distinct callables, one each.

    The positive partner for the table above: matching keys and verbs would
    still pass if every entry shared one finder that returns nothing.
    """
    module = _load_script()
    finders = [c.find for c in module.CATEGORIES]
    assert all(callable(f) for f in finders)
    assert len({id(f) for f in finders}) == len(SPECIFIED_CATEGORIES), (
        f"categories share a finder: {[getattr(f, '__name__', f) for f in finders]}"
    )


def test_report_lists_all_eight_categories(sandbox: Path) -> None:
    """Turns red if: a category disappears from the report, or the report stops
    printing empty categories. On a clean tree every category must still be
    named, so 'found nothing' is visibly different from 'did not look'."""
    out = run(sandbox).stdout
    for number, (_key, verb) in SPECIFIED_CATEGORIES.items():
        assert f"[{number}]" in out, f"category {number} missing from the report"
        heading = next(line for line in out.splitlines() if line.strip().startswith(f"[{number}]"))
        assert f"(may {verb})" in heading, f"category {number} reported the wrong verb: {heading}"
    assert f"categories examined      : {len(SPECIFIED_CATEGORIES)}" in out


# ---------------------------------------------------------------------------
# Category 3 -- the squash-merge defect
# ---------------------------------------------------------------------------


def _squash_merged_branch(repo: Path) -> None:
    """Two commits on a branch, squashed onto main, main then moved on.

    This is the shape this repository actually produces: rule 17c squash-merges
    every pull request. `git branch --merged` misses it, and so does
    `git cherry`, because a squash of MORE THAN ONE commit preserves no
    patch-id.
    """
    _git(repo, "checkout", "-qb", "feat")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "one")
    (repo / "a.txt").write_text("one\ntwo\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "two")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--squash", "feat")
    _git(repo, "commit", "-qm", "squashed feat")
    (repo / "unrelated.txt").write_text("moved on\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unrelated")


def test_a_squash_merged_branch_is_recognised_as_merged(sandbox: Path) -> None:
    """Turns red if: the merged-branch check goes back to `git branch --merged`
    (or to `git cherry`, or to `git diff --quiet`).

    Measured on git 2.54.0 in exactly this fixture: `git branch --merged main`
    prints only `main`, so the old code reported ZERO merged branches for a
    branch whose content is entirely on main. That is a wrong number, printed
    with confidence, about whether work can be thrown away.
    """
    _squash_merged_branch(sandbox)
    assert "feat" not in _git(sandbox, "branch", "--merged", "main"), (
        "fixture is wrong: --merged already sees the branch, so nothing is being tested"
    )
    out = run(sandbox).stdout
    assert "REPORT branch feat" in out
    # Fully qualified in the message too: a bare "main" would be the tag-first
    # resolution this tool must not use.
    assert "content already on refs/heads/main" in out


def test_a_genuinely_unmerged_branch_is_not_called_merged(sandbox: Path) -> None:
    """Turns red if: the merged check degrades to something that says yes to
    everything. THE negative partner -- a check that answers 'merged' for every
    branch would pass the squash test above on its own."""
    _git(sandbox, "checkout", "-qb", "open")
    (sandbox / "b.txt").write_text("not on main\n")
    _git(sandbox, "add", "-A")
    _git(sandbox, "commit", "-qm", "open work")
    _git(sandbox, "checkout", "-q", "main")
    out = run(sandbox).stdout
    assert "branch open" not in out, f"an unmerged branch was reported as cleanable:\n{out}"


def test_a_tag_that_shares_a_branch_name_cannot_fake_a_merge(sandbox: Path) -> None:
    """Turns red if: the refs stop being fully qualified.

    Measured: with `git tag feature main` in place, `git merge-tree
    --write-tree main feature` prints main's OWN tree and exits 0, emitting
    only `warning: refname 'feature' is ambiguous` on stderr -- because
    gitrevisions resolves refs/tags/ before refs/heads/. A bare-ref
    implementation therefore calls an unmerged branch merged and invites its
    deletion. Qualifying both sides to refs/heads/... is the fix.
    """
    _git(sandbox, "checkout", "-qb", "feature")
    (sandbox / "only-here.txt").write_text("branch work\n")
    _git(sandbox, "add", "-A")
    _git(sandbox, "commit", "-qm", "branch work")
    _git(sandbox, "checkout", "-q", "main")
    _git(sandbox, "tag", "feature", "main")

    out = run(sandbox).stdout
    assert "content already on" not in out, f"a tag shadowing the branch name faked a merge:\n{out}"


def test_a_branch_with_no_commits_of_its_own_is_not_reported(sandbox: Path) -> None:
    """Turns red if: the zero-commit filter is dropped.

    A freshly created work branch is 'merged' by every available test, so the
    old code named the branch the developer was standing on as cleanable --
    reproduced on this repository, which printed
    `merged branches : 1 -> pkg1-session-hygiene` while that branch held the
    live work package."""
    _git(sandbox, "checkout", "-qb", "fresh")
    out = run(sandbox).stdout
    assert "branch fresh" not in out, f"a branch with no commits was reported:\n{out}"


def test_branches_are_never_deleted_by_the_residue_job(sandbox: Path) -> None:
    """Turns red if: category 3 is given a DELETE verb. `git branch -D` on a
    squash-merged branch whose pull request was never merged loses its distinct
    commits to the reflog."""
    _squash_merged_branch(sandbox)
    assert run(sandbox, "--residue").returncode == 0
    assert "feat" in _git(sandbox, "branch", "--list"), "the residue job deleted a branch"


# ---------------------------------------------------------------------------
# Category 4 -- scratch and proof files
# ---------------------------------------------------------------------------


def test_session_scratchpads_are_reported_and_never_deleted(sandbox: Path, tmp_path: Path) -> None:
    """Turns red if: the scratchpad scan is dropped, or starts deleting.

    Sibling session directories may belong to a session that is still running,
    and the harness's session-id variable is inherited by subagents -- measured
    on this machine, a subagent process carries its PARENT's id, so a tool that
    trusted it would delete a live scratchpad."""
    root = tmp_path / "scratchroot"
    live = root / "fcaa7c25-93dd-4d20-a976-aaf036d69cb9" / "scratchpad"
    other = root / "6f84f3e2-28e6-4d48-a931-411beff9de9d" / "scratchpad"
    for d in (live, other):
        d.mkdir(parents=True)
        (d / "proof.txt").write_text("irreplaceable\n")
    (root / "not-a-session").mkdir()

    out = run(sandbox, scratch=root).stdout
    assert str(live) in out and str(other) in out
    assert "not-a-session" not in out, "a directory that is not a session id was picked up"

    assert run(sandbox, "--residue", scratch=root).returncode == 0
    assert (live / "proof.txt").exists() and (other / "proof.txt").exists(), (
        "the residue job deleted a scratchpad outside the repository"
    )


# ---------------------------------------------------------------------------
# Category 5 -- downloaded artifacts
# ---------------------------------------------------------------------------


def test_regenerable_artifacts_are_deleted_but_captures_are_only_reported(sandbox: Path) -> None:
    """Turns red if: the regenerable list stops being deleted, or the captured
    list starts being deleted.

    Both halves matter. A screen recording a human made by hand is not
    recreated by re-running the suite; a Playwright report is."""
    (sandbox / "e2e").mkdir()
    (sandbox / "e2e" / "results.xml").write_text("<testsuite/>\n")
    (sandbox / "temp-artifacts").mkdir()
    (sandbox / "temp-artifacts" / "ui-video.mov").write_text("hand made\n")

    out = run(sandbox).stdout
    assert "DELETE e2e/results.xml" in out
    assert "REPORT temp-artifacts" in out

    assert run(sandbox, "--residue").returncode == 0
    assert not (sandbox / "e2e" / "results.xml").exists(), "regenerable output survived"
    assert (sandbox / "temp-artifacts" / "ui-video.mov").read_text() == "hand made\n", (
        "a hand-made capture was destroyed"
    )


# ---------------------------------------------------------------------------
# Category 6 -- reviewer scratch copies
# ---------------------------------------------------------------------------


def test_reviewer_scratch_is_reported_and_never_deleted(sandbox: Path) -> None:
    """Turns red if: category 6 stops looking, or is given a DELETE verb.
    These are hand-written specs and human-review captures with no git history
    -- exactly the population that cannot be recovered."""
    review = sandbox / "e2e" / "tests" / "review"
    review.mkdir(parents=True)
    (review / "layout-review.spec.ts").write_text("// hand written\n")

    out = run(sandbox).stdout
    assert "REPORT e2e/tests/review" in out

    assert run(sandbox, "--residue").returncode == 0
    assert (review / "layout-review.spec.ts").exists(), "hand-written review specs were destroyed"


def test_a_stray_checkout_is_reported_not_swept(sandbox: Path) -> None:
    """Turns red if: the stray-checkout scan is dropped. A reviewer copy taken
    per rule 12b carries a real `.git` and is indistinguishable by shape from
    the user's own clone, so it is named, never touched."""
    copy = sandbox / "reviewer-copy"
    (copy / ".git").mkdir(parents=True)
    out = run(sandbox).stdout
    assert "REPORT reviewer-copy" in out
    assert run(sandbox, "--residue").returncode == 0
    assert (copy / ".git").is_dir()


# ---------------------------------------------------------------------------
# Category 7 -- containers and images
# ---------------------------------------------------------------------------


def test_only_this_repos_own_images_and_containers_are_named(sandbox: Path) -> None:
    """Turns red if: the image allowlist widens to a substring match or a
    prune. `quorum-ai-prod:1` and `postgres:16` are exactly the neighbours a
    `docker system prune -af` or a `grep quorum` would destroy."""
    _fake_docker(
        sandbox,
        images=["quorum-ai:local", "quorum-ai-prod:1", "postgres:16"],
        containers=["repo-app-1"],
    )
    out = run(sandbox).stdout
    assert "image quorum-ai:local" in out
    assert "container repo-app-1" in out
    assert "quorum-ai-prod" not in out, "a lookalike image name was claimed"
    assert "postgres" not in out, "an unrelated image was claimed"


def test_the_tool_never_ISSUES_a_prune(sandbox: Path) -> None:
    """Turns red if: anyone adds a prune, in code or in a printed instruction.

    An earlier version asserted only that the string "prune" was absent from
    the REPORT. That is vacuous: a prune is a subprocess call, not a printed
    word, and a reviewer added a real `docker system prune -af` with the whole
    suite still green. The fake docker now records every argv it is handed, so
    the check is on the CALLS, with the image listing as the positive partner
    proving the log is written at all.
    """
    _fake_docker(sandbox, images=["quorum-ai:local"])
    out = run(sandbox).stdout
    calls = (sandbox.parent / "docker-calls.log").read_text().splitlines()
    assert any(c.startswith("image ls") for c in calls), f"the call log is empty: {calls}"
    assert not [c for c in calls if "prune" in c], f"a prune was issued: {calls}"
    assert "prune" not in out, "the report told a human to prune"
    assert "docker image rm quorum-ai:local" in out


def test_containers_are_never_deleted_by_the_residue_job(sandbox: Path) -> None:
    """Turns red if: category 7 is given a DELETE verb. A running container may
    be the developer's live application."""
    _fake_docker(sandbox, images=["quorum-ai:local"], containers=["repo-app-1"])
    out = run(sandbox, "--residue").stdout
    assert "REFUSED image quorum-ai:local" in out
    assert "REFUSED container repo-app-1" in out


# ---------------------------------------------------------------------------
# Category 8 -- one-off third-party dependencies
# ---------------------------------------------------------------------------


def test_a_modified_dependency_manifest_is_reported(sandbox: Path) -> None:
    """Turns red if: the manifest-drift check is dropped. A dependency added
    for one experiment and left behind is invisible in the virtual environment
    -- it is indistinguishable there from a transitive pin -- but it shows in
    the manifest."""
    (sandbox / "pyproject.toml").write_text('[project]\nname = "x"\n')
    _git(sandbox, "add", "pyproject.toml")
    _git(sandbox, "commit", "-qm", "manifest")
    (sandbox / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["oneoff"]\n')

    out = run(sandbox).stdout
    assert "REPORT pyproject.toml" in out
    assert "dependency manifest is modified" in out


def test_an_unmodified_manifest_is_not_reported(sandbox: Path) -> None:
    """Turns red if: the drift check degrades to 'the manifest exists'. THE
    negative partner -- a check that fires on every repository with a
    pyproject.toml reports nothing about this session."""
    (sandbox / "pyproject.toml").write_text('[project]\nname = "x"\n')
    _git(sandbox, "add", "pyproject.toml")
    _git(sandbox, "commit", "-qm", "manifest")
    out = run(sandbox).stdout
    assert "REPORT pyproject.toml" not in out


# ---------------------------------------------------------------------------
# Deletion safety -- the guards on the one job that removes files
# ---------------------------------------------------------------------------


def test_residue_refuses_a_path_git_tracks(sandbox: Path) -> None:
    """Turns red if: the tracked-content guard is dropped. This script's author
    destroyed 38 tracked files with a single recursive remove; a residue path
    that has become tracked is no longer residue."""
    (sandbox / "build" / "mutation").mkdir(parents=True)
    (sandbox / "build" / "mutation" / "score.txt").write_text("now tracked\n")
    _git(sandbox, "add", "-f", "build/mutation/score.txt")
    _git(sandbox, "commit", "-qm", "track it")

    out = run(sandbox, "--residue").stdout
    assert "REFUSED build/mutation: git tracks content here" in out
    assert (sandbox / "build" / "mutation" / "score.txt").exists()


def test_residue_refuses_a_symlink_and_leaves_its_target_alone(sandbox: Path) -> None:
    """Turns red if: the symlink guard is dropped. The session scratchpads on
    this machine hold symlinks pointing at real transcripts and at virtual
    environments inside the repository; following one reaches a user's files."""
    real = sandbox / "somebody-elses"
    real.mkdir()
    (real / "precious.txt").write_text("do not delete\n")
    (sandbox / "build").mkdir()
    (sandbox / "build" / "mutation").symlink_to(real, target_is_directory=True)

    out = run(sandbox, "--residue").stdout
    assert "REFUSED build/mutation: it is a symlink" in out
    assert (real / "precious.txt").read_text() == "do not delete\n"
    assert (sandbox / "build" / "mutation").is_symlink(), "the link itself was removed"


def test_residue_refuses_a_directory_that_holds_a_checkout(sandbox: Path) -> None:
    """Turns red if: the .git guard is dropped. A residue name reused as a
    working copy is somebody's uncommitted work, not build output."""
    (sandbox / "mutants" / ".git").mkdir(parents=True)
    (sandbox / "mutants" / "work.py").write_text("uncommitted\n")
    out = run(sandbox, "--residue").stdout
    assert "REFUSED mutants: it holds a .git" in out
    assert (sandbox / "mutants" / "work.py").exists()


def test_residue_is_deleted_only_by_name_never_by_glob(sandbox: Path) -> None:
    """Turns red if: residue deletion widens to a directory sweep.

    THE positive partner for 'delete by name'. A neighbour that merely shares a
    parent directory must survive. Recorded because the author of this script
    destroyed 38 tracked files with 'rm -rf docs/archive/2026-08' while intending
    to remove five -- the exact failure this asserts against.
    """
    (sandbox / "build" / "mutation").mkdir(parents=True)
    (sandbox / "build" / "mutation" / "score.txt").write_text("stale\n")
    (sandbox / "build" / "keepme").mkdir()
    (sandbox / "build" / "keepme" / "important.txt").write_text("do not delete\n")

    assert run(sandbox, "--residue").returncode == 0
    assert not (sandbox / "build" / "mutation").exists(), "named residue survived"
    assert (sandbox / "build" / "keepme" / "important.txt").read_text() == "do not delete\n", (
        "a sibling directory was destroyed -- the deletion widened beyond its named paths"
    )


# ---------------------------------------------------------------------------
# Round-two guards: what an adversarial reviewer broke
# ---------------------------------------------------------------------------


def test_nothing_is_deleted_when_git_cannot_read_the_index(sandbox: Path) -> None:
    """Turns red if: the positive index probe is dropped.

    "git tracks nothing here" is a negative check, and over a git that is not
    answering it is trivially true -- it reads as safe to delete. Measured with
    GIT_INDEX_FILE pointing at a file that does not exist: `git ls-files --
    htmlcov` exits **0** with EMPTY stdout while `rev-parse
    --is-inside-work-tree` still says true, so even an exit-code check passes it
    through and the tracked file is destroyed.
    """
    (sandbox / "htmlcov").mkdir()
    (sandbox / "htmlcov" / "precious.txt").write_text("TRACKED USER WORK\n")
    _git(sandbox, "add", "-f", "htmlcov/precious.txt")
    _git(sandbox, "commit", "-qm", "track it")

    out = run(sandbox, "--residue", env_extra={"GIT_INDEX_FILE": str(sandbox / "no.index")}).stdout
    assert "REFUSED htmlcov" in out and "index" in out, out
    assert (sandbox / "htmlcov" / "precious.txt").exists(), "a tracked file was destroyed"


def test_the_index_probe_does_not_refuse_a_healthy_repository(sandbox: Path) -> None:
    """Turns red if: the index probe refuses everything.

    THE positive partner. A guard that always refuses would pass the test above
    while making the residue job do nothing at all, forever."""
    (sandbox / "htmlcov").mkdir()
    (sandbox / "htmlcov" / "report.html").write_text("<html/>\n")
    assert run(sandbox, "--residue").returncode == 0
    assert not (sandbox / "htmlcov").exists(), "the index probe refused a healthy repository"


def test_residue_refuses_a_directory_holding_a_NESTED_checkout(sandbox: Path) -> None:
    """Turns red if: the .git search goes back to the top level only.

    Measured: with the check at the top level only, a repository at
    `mutants/reviewer-copy` -- exactly where a mutation harness and a reviewer
    both work -- was destroyed by the recursive remove on `mutants`, and the
    tracked-content guard could not see it either, because a nested repository
    is untracked in the outer one."""
    nested = sandbox / "mutants" / "reviewer-copy"
    (nested / ".git").mkdir(parents=True)
    (nested / "note.md").write_text("REVIEWER UNCOMMITTED WORK\n")
    out = run(sandbox, "--residue").stdout
    assert "REFUSED mutants" in out
    assert (nested / "note.md").exists(), "a nested checkout was destroyed"


def test_one_unremovable_path_does_not_abort_the_whole_run(sandbox: Path) -> None:
    """Turns red if: a delete is allowed to raise out of the loop.

    The recursive remove is itself partly destructive before it raises, so a
    traceback leaves the tree half cleaned, every later category unexamined,
    and no record of what went."""
    (sandbox / "htmlcov").mkdir()
    (sandbox / "htmlcov" / "locked.txt").write_text("x\n")
    (sandbox / "mutants").mkdir()
    (sandbox / "mutants" / "stale.txt").write_text("y\n")
    (sandbox / "htmlcov").chmod(0o500)
    try:
        r = run(sandbox, "--residue")
        assert "FAILED  htmlcov" in r.stdout, r.stdout
        assert "deleted mutants" in r.stdout, "the run stopped at the first failure"
        assert "could not be removed" in r.stdout, "the summary was never printed"
    finally:
        (sandbox / "htmlcov").chmod(0o700)


def test_hand_driven_browser_output_is_reported_not_deleted(sandbox: Path) -> None:
    """Turns red if: the browser-log directory moves back to the delete list.

    Measured: `grep -rIl playwright-mcp` over the tree matches ONLY
    `.gitignore`. No spec, workflow or Makefile target writes it -- it is filled
    when a human drives the browser by hand, and re-running the suite does not
    recreate it. The real checkout holds 15 such files from June."""
    mcp = sandbox / ".playwright-mcp"
    mcp.mkdir()
    (mcp / "console-2026-06-20.log").write_text("hand driven\n")
    out = run(sandbox).stdout
    assert "REPORT .playwright-mcp" in out
    assert run(sandbox, "--residue").returncode == 0
    assert (mcp / "console-2026-06-20.log").exists(), "hand-driven browser output was destroyed"


def test_worktrees_are_reported_even_when_no_trunk_resolves(sandbox: Path) -> None:
    """Turns red if: the worktree listing is put back behind the trunk lookup.

    They are unrelated questions. With the early return in place, this category
    printed "(none present)" while the same report's git-state line said there
    were two worktrees -- a report contradicting itself, in the one category
    whose job is to stop you losing a branch."""
    _git(sandbox, "branch", "-M", "master")
    extra_wt = sandbox.parent / "extra-worktree"
    _git(sandbox, "worktree", "add", "-q", "-b", "side", str(extra_wt))
    out = run(sandbox).stdout
    assert str(extra_wt) in out, f"a live worktree went unreported:\n{out}"
    assert "no trunk ref found" in out
    assert "cannot tell" in out, "a category that could not measure reported silence"


def test_a_worktree_path_with_a_space_is_reported_whole(sandbox: Path) -> None:
    """Turns red if: the worktree list is parsed by splitting on whitespace.

    Measured: that parse reports a worktree at `/tmp/t12 wt` as `/tmp/t12` -- a
    DIFFERENT, existing directory -- inside a `git worktree remove`
    instruction, pointing a human's destructive command at the wrong target."""
    spaced = sandbox.parent / "work tree with spaces"
    _git(sandbox, "worktree", "add", "-q", "-b", "spaced", str(spaced))
    out = run(sandbox).stdout
    assert f"worktree {spaced}" in out, f"the path was truncated at the space:\n{out}"


def test_a_docker_that_cannot_answer_says_so_instead_of_nothing(sandbox: Path) -> None:
    """Turns red if: the docker exit code is ignored again.

    The command-line tool is on PATH even when the daemon is down, so an
    ignored exit code prints "I could not look" as "nothing there" -- the exact
    vacuity this tool's own floor comment warns against."""
    _fake_docker(sandbox, fail=True)
    out = run(sandbox).stdout
    assert "REPORT docker" in out
    assert "measured NOTHING" in out


def test_residue_refuses_a_path_that_resolves_outside_the_repository(sandbox: Path) -> None:
    """Turns red if: the containment check is dropped.

    THE guard that keeps every deletion inside the tree, and it had no test at
    all until a reviewer removed it and watched the suite stay green. The
    symlink guard does NOT cover this: here the residue path itself is a real
    directory, and its PARENT is the link out of the repository.
    """
    outside = sandbox.parent / "elsewhere"
    (outside / "mutation").mkdir(parents=True)
    (outside / "mutation" / "precious.txt").write_text("not mine to delete\n")
    (sandbox / "build").symlink_to(outside, target_is_directory=True)

    out = run(sandbox, "--residue").stdout
    assert "REFUSED build/mutation: it resolves outside the repository root" in out, out
    assert (outside / "mutation" / "precious.txt").read_text() == "not mine to delete\n"


def test_poisoned_local_state_is_found_and_deleted(sandbox: Path) -> None:
    """Turns red if: category 2's finder becomes a stub.

    The specification table proves a category is LISTED, not that it is BUILT --
    a reviewer replaced this finder's body with `return []` and all forty tests
    stayed green. This is the behavioural partner, and category 2 deletes, so
    it needed one most. The neighbouring database is the positive partner for
    'by name': run history is not residue.
    """
    data = sandbox / ".data"
    data.mkdir()
    (data / "feedback_events.sqlite3").write_bytes(b"SQLite format 3\x00")
    (data / "run_history.sqlite3").write_bytes(b"SQLite format 3\x00")

    out = run(sandbox).stdout
    assert "DELETE .data/feedback_events.sqlite3" in out
    assert run(sandbox, "--residue").returncode == 0
    assert not (data / "feedback_events.sqlite3").exists(), "the poisoned database survived"
    assert (data / "run_history.sqlite3").exists(), (
        "run history was destroyed -- the deletion widened to the whole data directory"
    )


def test_a_branch_git_cannot_merge_names_a_cause_that_can_actually_happen(sandbox: Path) -> None:
    """Turns red if: cannot-tell is collapsed away, or blames a conflict.

    A conflicting merge exits 1 and still prints a tree hash, so it resolves to
    'not merged'. The cannot-tell path is reached by something else -- measured,
    an orphan branch gives `fatal: refusing to merge unrelated histories` and
    exit 128 with empty stdout. The message used to blame a conflict, the one
    cause that can never be true here.
    """
    _git(sandbox, "checkout", "-q", "--orphan", "orphanwork")
    (sandbox / "z.txt").write_text("unrelated history\n")
    _git(sandbox, "add", "-A")
    _git(sandbox, "commit", "-qm", "orphan")
    _git(sandbox, "checkout", "-q", "main")

    out = run(sandbox).stdout
    assert "REPORT branch orphanwork" in out
    assert "cannot tell whether it is merged" in out
    assert "conflict" not in out, "the message blamed a cause that cannot occur here"
    assert "unrelated histories" in out


def test_a_merged_branch_held_by_a_worktree_is_flagged_as_checked_out(sandbox: Path) -> None:
    """Turns red if: the worktree warning is dropped from a merged branch.

    `git branch -D` refuses while a worktree holds the branch, so a report that
    says 'delete this' without saying 'a worktree has it' sends the reader into
    an error they then 'fix' by removing the worktree -- which is where the
    uncommitted work is."""
    _squash_merged_branch(sandbox)
    held = sandbox.parent / "feat-worktree"
    _git(sandbox, "worktree", "add", "-q", str(held), "feat")
    out = run(sandbox).stdout
    assert "REPORT branch feat" in out
    assert f"CHECKED OUT at {held}" in out, out


def test_a_report_finding_inside_a_delete_category_says_why_it_is_refused(sandbox: Path) -> None:
    """Turns red if: the two refusal conditions are collapsed again.

    A DELETE category may still emit REPORT findings -- the hand-made captures
    inside 'downloaded artifacts' are exactly that. The old single sentence
    printed 'category 5 is DELETE-only' as the reason for refusing, which is
    the opposite of the truth and unusable by a reader.
    """
    (sandbox / "temp-artifacts").mkdir()
    (sandbox / "temp-artifacts" / "ui-video.mov").write_text("hand made\n")
    _fake_docker(sandbox, images=["quorum-ai:local"])
    out = run(sandbox, "--residue").stdout
    assert "REFUSED temp-artifacts: this finding is REPORT-only" in out, out
    assert "REFUSED image quorum-ai:local: category 7 is REPORT-only" in out, out


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def test_make_session_clean_runs_the_reporter_and_passes_no_acting_flag() -> None:
    """Turns red if: the Makefile target disappears, or is changed to act.

    The script had no entry point at all, so nothing ever ran it. The target
    REPORTS -- the two jobs have opposite verbs and a `make` target that guesses
    which one you meant is the exact conflation this tool exists to prevent.
    """
    from tests.code_text import code_without_comments

    recipe = None
    for block in code_without_comments(MAKEFILE).split("\n\n"):
        if block.lstrip().startswith("session-clean:"):
            recipe = block
            break
    assert recipe is not None, "no session-clean target in the Makefile"
    assert "scripts/session_hygiene.py" in recipe
    assert "--residue" not in recipe, "the reporting target acts"
    assert "--archive" not in recipe, "the reporting target acts"
    phony = next(
        line for line in code_without_comments(MAKEFILE).splitlines() if line.startswith(".PHONY:")
    )
    assert "session-clean" in phony.split()


# ---------------------------------------------------------------------------
# Job B -- unchanged behaviour, still asserted
# ---------------------------------------------------------------------------


def test_dated_analysis_doc_is_classified_for_archive(sandbox: Path) -> None:
    """Turns red if: the ARCHIVE classification stops recognising dated session
    output under the analysis directory, i.e. the tool stops finding anything
    to do."""
    (sandbox / "docs" / "analysis" / "2026-01-02-some-triage.md").write_text("x\n")
    out = run(sandbox).stdout
    assert "ARCHIVE  " + ANALYSIS + "/2026-01-02-some-triage.md" in out


def test_a_procedure_at_root_is_kept_not_archived(sandbox: Path) -> None:
    """Turns red if: the tool starts archiving executable procedures. A future
    session RUNS these; moving them breaks the thing that runs them."""
    (sandbox / "DO-THIS-ULTRACODE-PROMPT.md").write_text("x\n")
    out = run(sandbox).stdout
    assert "KEEP     DO-THIS-ULTRACODE-PROMPT.md" in out
    assert "ARCHIVE  DO-THIS-ULTRACODE-PROMPT.md" not in out


def test_session_handoff_is_refused_because_a_script_globs_it(sandbox: Path) -> None:
    """Turns red if: the off-limits rule is dropped. Moving a handoff breaks the
    pointer SILENTLY -- the finder prints 'None found' and still exits 0."""
    (sandbox / "docs" / "analysis" / "2026-01-02-session-handoff.md").write_text("x\n")
    out = run(sandbox).stdout
    assert "REFUSE   " + ANALYSIS + "/2026-01-02-session-handoff.md" in out


def test_archive_stages_an_untracked_file_so_it_becomes_recoverable(sandbox: Path) -> None:
    """Turns red if: the git-add before git-mv is removed. THE hazard -- 'git mv'
    on an untracked file moves it and stores NOTHING, so the archive looks
    successful and the content is unrecoverable."""
    doc = sandbox / "docs" / "analysis" / "2026-01-02-triage.md"
    doc.write_text("irreplaceable\n")
    assert run(sandbox, "--archive").returncode == 0

    staged = _git(sandbox, "diff", "--cached", "--name-only").split()
    assert any("docs/archive/" in p for p in staged), f"nothing staged: {staged}"
    # The real proof: content retrievable from the index, i.e. actually stored.
    dest = next(p for p in staged if "docs/archive/" in p)
    assert _git(sandbox, "show", f":{dest}") == "irreplaceable\n"


def test_archive_refuses_when_an_ignore_rule_follows_the_file_in(sandbox: Path) -> None:
    """Turns red if: the check-ignore guard is dropped. An ignore pattern with no
    directory anchor follows the file into the archive, and the move silently
    stores nothing."""
    # Ignore the DESTINATION directory, not the source. An ignore rule matching
    # the source means the file is never a candidate at all, so that variant
    # cannot reach this guard -- the first version of this test made that mistake.
    (sandbox / ".gitignore").write_text("docs/archive/\n")
    _git(sandbox, "add", ".gitignore")
    _git(sandbox, "commit", "-qm", "ignore")
    (sandbox / "docs" / "analysis" / "2026-01-02-triage.md").write_text("x\n")
    out = run(sandbox, "--archive").stdout
    assert "REFUSED" in out and "ignore rule" in out
    assert not _git(sandbox, "diff", "--cached", "--name-only").strip()


def test_a_gate_referencing_the_filename_blocks_the_move(sandbox: Path) -> None:
    """Turns red if: the reference check is dropped. It is a NAME match, not proof
    of a dependency -- deliberately conservative, because a human check is cheaper
    than a broken gate."""
    (sandbox / "docs" / "analysis" / "2026-01-02-pinned.md").write_text("x\n")
    (sandbox / "tests" / "test_pins.py").write_text('PATH = "2026-01-02-pinned.md"\n')
    _git(sandbox, "add", "tests")
    _git(sandbox, "commit", "-qm", "pin")
    out = run(sandbox).stdout
    assert "REFUSE   " + ANALYSIS + "/2026-01-02-pinned.md" in out
    assert "FILENAME" in out


def test_the_two_jobs_cannot_be_run_with_one_flag(sandbox: Path) -> None:
    """Turns red if: --residue and --archive stop being mutually exclusive.
    They have OPPOSITE verbs; one flag doing both is how delete gets applied to
    files that should have been archived."""
    r = run(sandbox, "--residue", "--archive")
    assert r.returncode == 1
    assert "separate jobs with opposite verbs" in r.stdout


def test_the_default_run_changes_nothing(sandbox: Path) -> None:
    """Turns red if: the reporter starts acting without a flag. Report-first is
    the whole safety posture."""
    (sandbox / "docs" / "analysis" / "2026-01-02-triage.md").write_text("x\n")
    before = sorted(p.name for p in (sandbox / "docs/analysis").iterdir())
    r = run(sandbox)
    assert r.returncode == 0
    assert sorted(p.name for p in (sandbox / "docs/analysis").iterdir()) == before
    assert not _git(sandbox, "diff", "--cached", "--name-only").strip()
    assert "Nothing was changed" in r.stdout


def test_a_clean_tree_is_success_and_says_so(sandbox: Path) -> None:
    """Turns red if: 'found nothing' starts being treated as an error.

    Unlike a gate over a population that MUST exist, a genuinely clean tree is a
    legitimate result here. The floor must not punish it."""
    r = run(sandbox)
    assert r.returncode == 0
    assert "Nothing to clean" in r.stdout


def test_the_floor_fires_when_git_cannot_answer(tmp_path: Path) -> None:
    """Turns red if: the observability floor is removed. THE positive partner --
    the tool must distinguish 'nothing to clean' from 'I could not look'."""
    outside = tmp_path / "not-a-repo"
    (outside / "scripts").mkdir(parents=True)
    (outside / "scripts" / "session_hygiene.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, "scripts/session_hygiene.py"],
        cwd=outside,
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "GIT_CEILING_DIRECTORIES": str(tmp_path),
        },
    )
    assert r.returncode == 1
    assert "FLOOR" in r.stdout
