"""The issue-closure guard must detect a real unbacked closure.

Issue #139. #130 was closed COMPLETED with no commit, no branch, nothing — and
the gate it was about stayed broken for months. `AGENTS.md` already forbade it
in prose; prose did not bind.

These tests drive the PURE classification functions over fixture data. No
network, no `gh`, no repository state — so the logic is pinned hermetically and
cannot go red because someone opened an issue.

A simpler rule was written first and REFUTED by history. "Some commit mentions
#130" would NOT have caught it: at `7d03333`, three commits referenced the issue
and all three were handoff documents describing it. GitHub's own
`closedByPullRequestsReferences` was satisfied the same way, by the docs pull
request. The rule therefore requires a referencing commit that changed something
other than prose — measured: 3 referencing commits and 0 non-prose before the
fix landed, 4 and 1 after.

Every "finds nothing" assertion below ships with a partner proving it finds the
real thing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.check_issue_closure import ClosedIssue, Commit, _commits, is_prose_only, unbacked

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_issue_closure.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "issue-hygiene.yml"

#: The real shape: #130 closed COMPLETED, nothing in the log mentioning it.
THE_130_CASE = ClosedIssue(
    number=130,
    title="Make the mutation-score check block, now that its baseline exists",
    state_reason="COMPLETED",
)


#: Two of the commits that referenced #130 at the moment it was closed. All
#: were handoff DOCUMENTS describing the issue; none did the work. Reconstructed
#: from real history at 7d03333.
#: (the handoff-prompt filename is generic here on purpose: naming a real
#: repo-root file in fixture data trips tests/unit/test_mutation_copy_completeness.py,
#: which greps test sources for root paths the suite reads)
DOCS_ONLY_REFERENCES = (
    Commit(
        message="docs: prompt for the two guardrails, then the handoff\n\ncovering #130 and #131",
        files=("A-HANDOFF-PROMPT.md",),
    ),
    Commit(
        message="docs: carry three learnings into the new-project rulebook (#130)",
        files=("docs/DAY-ONE-PROMPT.md",),
    ),
)

#: What actually closed it: a commit that changed the gate itself.
THE_REAL_FIX = Commit(
    message="fix(ci): repair the mutation gate, then record why it stays advisory (#130)",
    files=("Makefile", ".github/workflows/ci.yml", "docs/metrics/mutation-gate-study.md"),
)


def test_it_catches_the_real_130_case() -> None:
    """The case this guard exists for, with the REAL history that fooled a
    simpler rule.

    A bare-mention rule does NOT catch #130: measured against `7d03333`, three
    commits referenced it and every one was a handoff document. GitHub's own
    `closedByPullRequestsReferences` was satisfied the same way. Writing about
    an issue is not evidence the work landed.

    Turns red if: `is_prose_only` stops being consulted — the docs commits then
    count as backing and this goes quiet on the exact defect it exists for.
    """
    assert unbacked([THE_130_CASE], DOCS_ONLY_REFERENCES) == [THE_130_CASE]


def test_a_substantive_commit_silences_it() -> None:
    """Positive partner: the guard must go quiet once the work really lands.

    Without this, the assertion above is equally satisfied by a checker that
    reports every closed issue. Measured on real history: 3 referencing commits
    and 0 non-prose before the fix; 4 and 1 after.

    Turns red if: `references` stops matching, or every commit is treated as
    prose-only.
    """
    assert unbacked([THE_130_CASE], [*DOCS_ONLY_REFERENCES, THE_REAL_FIX]) == []


def test_a_commit_with_no_files_is_prose_only() -> None:
    """An empty commit is not evidence of work either.

    True by construction (`all(())` is True) rather than by a branch — an
    earlier version wrote it as an explicit `if not commit.files`, and review
    showed no edit to that branch could turn its test red. Pinned here as a
    PROPERTY, with the partner below carrying the real bite.

    Turns red if: `is_prose_only` starts treating an unknown suffix as non-prose
    in a way that inverts the empty case.
    """
    assert is_prose_only(Commit(message="chore: empty (#130)", files=()))
    # Partner: a commit that DID change code is not prose-only.
    assert not is_prose_only(Commit(message="fix (#130)", files=("Makefile",)))


def test_a_longer_number_does_not_satisfy_a_shorter_issue() -> None:
    """`#13` must not be closed out by a commit mentioning `#130`.

    Turns red if: the whole-token guard `(?!\\d)` is dropped from `references`.
    """
    thirteen = ClosedIssue(number=13, title="an older issue", state_reason="COMPLETED")
    other = [Commit(message="fix: something about (#130)", files=("Makefile",))]
    assert unbacked([thirteen], other) == [thirteen]
    # ...and the partner: its OWN number does satisfy it.
    assert unbacked([thirteen], [Commit(message="fix: something (#13)", files=("Makefile",))]) == []


def test_a_bare_number_is_not_a_reference() -> None:
    """Prose mentioning 130 is not a claim that this commit closed #130.

    Turns red if: `references` is loosened to a bare-number search.
    """
    bare = [Commit(message="perf: reduce 130 allocations in the hot path", files=("Makefile",))]
    assert unbacked([THE_130_CASE], bare) == [THE_130_CASE]


def test_not_planned_closures_are_not_hygiene_problems() -> None:
    """A duplicate or won't-fix legitimately has no commit.

    Keying off "closed" rather than the COMPLETED state reason would make this
    guard noisy enough to be routed around — which is how a gate becomes
    decoration.

    Turns red if: the COMPLETED filter is removed from `unbacked`.
    """
    duplicate = ClosedIssue(number=99, title="duplicate of #98", state_reason="NOT_PLANNED")
    unrelated = [Commit(message="unrelated commit", files=("Makefile",))]
    assert unbacked([duplicate], unrelated) == []
    # Partner: the SAME issue, closed COMPLETED, IS reported.
    completed = ClosedIssue(number=99, title="duplicate of #98", state_reason="COMPLETED")
    assert unbacked([completed], unrelated) == [completed]


def test_offenders_are_ordered_and_the_filter_is_not_vacuous() -> None:
    """A guard over an empty set proves nothing.

    Turns red if: `unbacked` returns everything, or nothing, regardless of input.
    """
    issues = [
        # Deliberately 5 before 3: an already-sorted fixture made the ordering
        # half of this test decoration — sorting by a constant left it green.
        ClosedIssue(number=5, title="also never landed", state_reason="COMPLETED"),
        ClosedIssue(number=3, title="never landed", state_reason="COMPLETED"),
        ClosedIssue(number=7, title="landed", state_reason="COMPLETED"),
    ]
    result = unbacked(issues, [Commit(message="feat: did the thing (#7)", files=("src/x.py",))])
    assert [issue.number for issue in result] == [3, 5], "expected only the unbacked, sorted"


def test_commits_traversal_sees_work_merged_from_a_deleted_branch(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The one defect the hermetic tests could not see — and it was shipped-shaped.

    The first `_commits()` used `git log --all -m --first-parent`, which walks
    only first parents. A merged pull request's real work commits are the SECOND
    parent, reachable only while a ref still points at the branch. A developer
    clone keeps stale `refs/remotes/origin/<deleted-branch>` entries and looks
    fine; a fresh CI checkout does not. Measured on a CI-shaped clone of this
    repo: the old traversal saw 157 commits and reported THREE false positives
    (#111, #114, #119); the current one sees 205 and reports the one real
    finding.

    Every pure-function test stayed green through all of it, because the bug
    lived in the one function they do not touch. So this test is deliberately
    NOT hermetic: it builds a real repository with a real merge and a deleted
    branch.

    Turns red if: `--first-parent` (or `--all`) returns to `_commits()`.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    (repo / "seed.md").write_text("seed\n", encoding="utf-8")
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-qm", "seed")

    git("checkout", "-q", "-b", "feature")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "fix: do the work (#4242)")

    git("checkout", "-q", "main")
    git("merge", "-q", "--no-ff", "-m", "Merge pull request #99 from feature", "feature")
    git("branch", "-q", "-D", "feature")  # the branch is gone, as after a squash-merge cleanup

    commits = _commits(branch="main", cwd=str(repo))
    assert commits, "no commits parsed — the traversal or the parser is broken"

    issue = ClosedIssue(number=4242, title="the merged work", state_reason="COMPLETED")
    assert unbacked([issue], commits) == [], (
        "work merged from a since-deleted branch was not seen, so the issue "
        "reads as unbacked. This is the false positive that shipped: "
        f"{[c.message.splitlines()[0] for c in commits]}"
    )

    # Positive partner: an issue that genuinely has nothing IS still reported,
    # so the assertion above cannot pass over a traversal that returns garbage.
    absent = ClosedIssue(number=4243, title="never done", state_reason="COMPLETED")
    assert unbacked([absent], commits) == [absent]


def test_the_reporter_is_registered_in_a_workflow() -> None:
    """An unregistered gate is not a gate — the repo's most-repeated lesson.

    Three specs have been committed, green, and named in no workflow
    (`docs/103-incident-learnings.md`). This must not become the fourth.

    Turns red if: the script is renamed, or the workflow stops invoking it.
    """
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert WORKFLOW.is_file(), f"missing {WORKFLOW}"
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "check_issue_closure.py" in workflow, (
        "the issue-closure reporter exists but no workflow runs it"
    )
