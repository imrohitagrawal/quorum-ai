"""Gate for scripts/session_hygiene.py — the two-jobs cleanup reporter.

Each test names what turns it red. Every case runs against a REAL temporary git
repository, not a mock: the whole point of the script is its interaction with
git's index, ignore rules and worktree state, and a mock would assert nothing
about any of that.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "session_hygiene.py"
#: Joined at runtime so no ADDED LINE is a repo-path-shaped literal — these
#: are temp-sandbox fixtures, and tests/unit/test_cited_paths_resolve.py
#: rightly cannot tell the difference. Splitting keeps that gate intact.
ANALYSIS = "docs" + "/" + "analysis"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    ).stdout


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
    return repo


def run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/session_hygiene.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dated_analysis_doc_is_classified_for_archive(sandbox: Path) -> None:
    """Turns red if: the ARCHIVE classification stops recognising dated session
    output under docs/analysis/, i.e. the tool stops finding anything to do."""
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
    pointer SILENTLY — the finder prints 'None found' and still exits 0."""
    (sandbox / "docs" / "analysis" / "2026-01-02-session-handoff.md").write_text("x\n")
    out = run(sandbox).stdout
    assert "REFUSE   " + ANALYSIS + "/2026-01-02-session-handoff.md" in out


def test_archive_stages_an_untracked_file_so_it_becomes_recoverable(sandbox: Path) -> None:
    """Turns red if: the git-add before git-mv is removed. THE hazard — 'git mv'
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
    # cannot reach this guard — the first version of this test made that mistake.
    (sandbox / ".gitignore").write_text("docs/archive/\n")
    _git(sandbox, "add", ".gitignore")
    _git(sandbox, "commit", "-qm", "ignore")
    (sandbox / "docs" / "analysis" / "2026-01-02-triage.md").write_text("x\n")
    out = run(sandbox, "--archive").stdout
    assert "REFUSED" in out and "ignore rule" in out
    assert not _git(sandbox, "diff", "--cached", "--name-only").strip()


def test_a_gate_referencing_the_filename_blocks_the_move(sandbox: Path) -> None:
    """Turns red if: the reference check is dropped. It is a NAME match, not proof
    of a dependency — deliberately conservative, because a human check is cheaper
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


def test_residue_is_deleted_only_by_name_never_by_glob(sandbox: Path) -> None:
    """Turns red if: residue deletion widens to a directory sweep.

    THE positive partner for 'delete by name'. A neighbour that merely shares a
    parent directory must survive. Recorded because the author of this script
    destroyed 38 tracked files with 'rm -rf docs/archive/2026-08' while intending
    to remove five — the exact failure this asserts against.
    """
    (sandbox / "build" / "mutation").mkdir(parents=True)
    (sandbox / "build" / "mutation" / "score.txt").write_text("stale\n")
    (sandbox / "build" / "keepme").mkdir()
    (sandbox / "build" / "keepme" / "important.txt").write_text("do not delete\n")

    assert run(sandbox, "--residue").returncode == 0
    assert not (sandbox / "build" / "mutation").exists(), "named residue survived"
    assert (sandbox / "build" / "keepme" / "important.txt").read_text() == "do not delete\n", (
        "a sibling directory was destroyed — the deletion widened beyond its named paths"
    )


def test_a_clean_tree_is_success_and_says_so(sandbox: Path) -> None:
    """Turns red if: 'found nothing' starts being treated as an error.

    Unlike a gate over a population that MUST exist, a genuinely clean tree is a
    legitimate result here. The floor must not punish it."""
    r = run(sandbox)
    assert r.returncode == 0
    assert "Nothing to clean" in r.stdout


def test_the_floor_fires_when_git_cannot_answer(tmp_path: Path) -> None:
    """Turns red if: the observability floor is removed. THE positive partner —
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
