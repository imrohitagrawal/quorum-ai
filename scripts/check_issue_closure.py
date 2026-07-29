"""Report issues closed as COMPLETED with no commit that references them.

Issue #139. Issue #130 was closed **COMPLETED** on 2026-07-28 and the change it
asked for was never made — no commit, no branch, nothing. The gate it was about
stayed broken for about a week, silently green, and the next session had to
rediscover it from CI logs (`docs/103-incident-learnings.md`).

`AGENTS.md` already says *"never close an issue whose fix sits on an unmerged
branch"*. Prose did not stop it, and by the durability ladder in
`docs/DAY-ONE-PROMPT.md` §1 only mechanism binds. This is the mechanism.

ADVISORY BY DESIGN. It reports; it does not block a merge. Some issues are
legitimately closed with no commit — a duplicate, a question answered, a
decision recorded. Those should close as NOT_PLANNED, or carry a reason. The
value here is visibility, not enforcement, and a noisy blocking gate on issue
hygiene would be routed around within a week.

The classification is a pure function over data, so it is tested hermetically
(`tests/unit/test_issue_closure_guard.py`) with no network and no `gh`. Only
`main()` touches GitHub.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ClosedIssue:
    number: int
    title: str
    state_reason: str


@dataclass(frozen=True)
class Commit:
    """A commit reduced to what this check needs: its message and its files."""

    message: str
    files: tuple[str, ...]


#: Extensions that carry PROSE only. A commit touching nothing else describes
#: work rather than doing it.
PROSE_SUFFIXES = (".md", ".rst", ".txt")


def references(number: int, message: str) -> bool:
    """True when a commit message mentions `#<number>` as a whole token.

    Whole-token matching matters: `#13` must not be satisfied by `#130`, and a
    bare `130` in prose is not a reference.
    """
    return re.search(rf"#{number}(?!\d)", message) is not None


def is_prose_only(commit: Commit) -> bool:
    """True when the commit changed nothing but prose.

    THE REASON THIS EXISTS. A bare-mention rule would NOT have caught #130 —
    measured against real history. At the moment #130 was closed COMPLETED,
    three commits referenced it, all of them handoff DOCUMENTS that merely
    described the issue. GitHub's own `closedByPullRequestsReferences` was
    satisfied the same way, by the docs pull request.

    So "somebody wrote about it" is not evidence the work landed. Requiring at
    least one referencing commit to touch something other than prose does catch
    #130 at close time, and goes correctly quiet once the real fix lands (also
    measured: 3 referencing commits, 0 non-prose, before; 4 and 1 after).
    """
    # `all(())` is already True, so a commit that changed nothing is prose-only
    # by construction. Stated rather than written as a redundant branch: an
    # earlier version had one, and its test's "turns red if" could not be
    # produced by any edit to it.
    return all(path.endswith(PROSE_SUFFIXES) for path in commit.files)


def unbacked(issues: Sequence[ClosedIssue], commits: Sequence[Commit]) -> list[ClosedIssue]:
    """COMPLETED issues with no SUBSTANTIVE commit behind them, lowest first.

    Substantive = references the issue AND changed something other than prose.

    Deliberately keys off the COMPLETED state reason rather than "closed": a
    duplicate or won't-fix closes as NOT_PLANNED and is not a hygiene problem.
    """
    return sorted(
        (
            issue
            for issue in issues
            if issue.state_reason.upper() == "COMPLETED"
            and not any(
                references(issue.number, commit.message) and not is_prose_only(commit)
                for commit in commits
            )
        ),
        key=lambda issue: issue.number,
    )


def _gh_closed_issues(limit: int) -> list[ClosedIssue]:
    raw = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "closed",
            "--limit",
            str(limit),
            "--json",
            "number,title,stateReason",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [
        ClosedIssue(
            number=row["number"],
            title=row["title"],
            state_reason=row.get("stateReason") or "",
        )
        for row in json.loads(raw)
    ]


#: What counts as "landed": reachable from the integration branch.
DEFAULT_BRANCH = "origin/main"


def _commits(branch: str = DEFAULT_BRANCH, cwd: str | None = None) -> list[Commit]:
    """Every commit reachable from `branch`, as (message, changed files).

    TRAVERSAL CHOICE, and it is the whole correctness of this tool.

    The first version ran `git log --all -m --first-parent`. That is wrong in
    the environment this actually runs in, and RIGHT on a developer machine —
    the worst combination. `--first-parent` walks only first parents, so the
    real work commits of a merged pull request (second parent) are reachable
    only while a ref still points at the branch. A local clone keeps stale
    `refs/remotes/origin/<deleted-branch>` entries and looks fine; a fresh CI
    checkout has only the live heads. Measured on a CI-shaped clone: the old
    traversal saw 157 commits and reported THREE false positives (#111, #114,
    #119, each of whose fixes is plainly on main); this one sees 205 and
    reports the one real finding.

    Using `origin/main` rather than `--all` also closes a false negative worth
    more than the bug it fixes: AGENTS.md's rule is "never close an issue whose
    fix sits on an UNMERGED branch", and `--all` counted exactly those commits
    as evidence. Now only merged work silences the guard.

    `-z` because a commit message may legitimately contain the record
    separators; splitting raw text let a crafted message hide a reference or
    inject a fake filename.
    """

    # Two passes, both delimited by NUL. Git forbids NUL in a commit message,
    # so it is the one separator a crafted message cannot forge — an earlier
    # version split on \x1e/\x1f, which a message containing those bytes could
    # break, hiding a reference or injecting a fake filename.
    def _pass(fmt: str, extra: list[str]) -> list[str]:
        return subprocess.run(
            ["git", "log", branch, f"--format={fmt}", *extra],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        ).stdout.split("\x00")

    messages: dict[str, str] = {}
    chunks = _pass("%x00%H%x00%B", [])
    for index in range(1, len(chunks) - 1, 2):
        messages[chunks[index].strip()] = chunks[index + 1]

    commits = []
    for chunk in _pass("%x00%H", ["--name-only"]):
        lines = [line for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        sha = lines[0].strip()
        commits.append(Commit(message=messages.get(sha, ""), files=tuple(lines[1:])))
    return commits


def main(argv: Sequence[str]) -> int:
    limit = int(argv[1]) if len(argv) > 1 else 200
    issues = _gh_closed_issues(limit)
    offenders = unbacked(issues, _commits())

    completed = [i for i in issues if i.state_reason.upper() == "COMPLETED"]
    print(
        f"issue-closure hygiene: {len(completed)} issue(s) closed COMPLETED, "
        f"{len(offenders)} unbacked"
    )

    if not offenders:
        # Say what was checked. "0 problems" over an empty set is the vacuous
        # green this repo keeps relearning; the count above is the partner.
        print("every COMPLETED issue has at least one non-prose commit behind it.")
        return 0

    print("\nClosed COMPLETED, but no commit references them:\n")
    for issue in offenders:
        print(f"  #{issue.number}  {issue.title}")
    print(
        "\nOne of these is true for each:\n"
        "  * the work never landed          -> reopen it (this is the #130 case);\n"
        "  * it landed without saying so    -> reference the issue in a commit;\n"
        "  * it was never going to land     -> close as NOT_PLANNED, not COMPLETED;\n"
        "  * it was not a code change at all -> e.g. a GitHub setting or an\n"
        "    external action. Say so in a closing comment so the next reader\n"
        "    does not have to re-derive it.\n"
        "\nThis is advisory: it reports, it does not block."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via tests of the pure functions
    raise SystemExit(main(sys.argv))
