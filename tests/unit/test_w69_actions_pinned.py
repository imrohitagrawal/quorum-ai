"""W69: every action from outside this repository runs at a fixed commit.

A tag such as ``actions/checkout@v4`` is a MOVING reference: whoever controls
that repository can point the tag at different code, and every workflow here
runs the new code on its next trigger, with this repository's token and
secrets. A 40-character commit id cannot be moved. So W69 pins every outside
``uses:`` to a full commit id, keeps the human-readable version as a trailing
comment, and fixes the two tool installers that fetched "latest" (``uv`` via
``astral-sh/setup-uv`` and ``flyctl`` via ``setup-flyctl``) to exact versions.

How these tests read the files (AGENTS.md rule 8 — structure, not substrings):

* The ``uses:`` values are found by WALKING the parsed YAML: job-level
  ``jobs.<id>.uses`` (a reusable workflow), step-level
  ``jobs.<id>.steps[n].uses``, and ``runs.steps[n].uses`` in composite
  actions under ``.github/actions/*/action.yml``. A comment that mentions
  ``uses:`` is not a step and is never counted.
* The version comment is the one thing YAML throws away, so for that alone the
  test reads the raw line — but only the text AFTER the end of the parsed
  ``uses`` value, located by the parser's own position marks.
* Rule 7: a walk that finds nothing would pass every "all are pinned" check.
  ``test_partner_the_walk_finds_every_uses_line`` compares the walk's count to
  an independent raw-line count and requires it to be non-zero.

WHAT TURNS THIS FILE RED: add (or revert to) a ``uses: owner/repo@<tag>`` line
in any workflow or composite action; drop the ``# vX.Y.Z`` comment from a
pinned line; give the same commit two different version comments; remove or
loosen ``with: version:`` on any ``astral-sh/setup-uv`` or ``setup-flyctl``
step.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.repo_root import find_repo_root

ROOT = find_repo_root(Path(__file__))
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONS = ROOT / ".github" / "actions"

SETUP_UV = "astral-sh/setup-uv"
SETUP_FLYCTL = "superfly/flyctl-actions/setup-flyctl"


# ---------------------------------------------------------------------------
# The rules, as small pure functions (each has its own literal-boundary tests)
# ---------------------------------------------------------------------------

#: ``owner/repo`` or ``owner/repo/sub/path`` (a sub-action or a reusable
#: workflow file), then ``@`` and exactly 40 LOWERCASE hex characters. Git
#: prints commit ids in lowercase; accepting one spelling keeps the
#: same-commit-same-comment check below from treating one commit as two.
_PINNED_OUTSIDE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}")

#: The trailing comment after a pinned value: whitespace, ``#``, then ONLY a
#: version-looking token (optional ``v``, digits, dot-separated).
_VERSION_COMMENT = re.compile(r"\s+#\s*(v?\d+(?:\.\d+)*)\s*")

_EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+")


def is_pinned(uses: str) -> bool:
    """True when ``uses`` is a local action (``./...``, exempt) or an outside
    action pinned to a full 40-character lowercase commit id."""
    if uses.startswith("./"):
        return True
    return _PINNED_OUTSIDE.fullmatch(uses) is not None


def version_comment(after_value: str) -> str | None:
    """The version in the comment that follows a ``uses`` value on its line,
    or None when there is no comment or it is not just a version."""
    match = _VERSION_COMMENT.fullmatch(after_value)
    return match.group(1) if match else None


def is_exact_version(value: object) -> bool:
    """True only for a string of the form ``X.Y.Z`` (all digits)."""
    return isinstance(value, str) and _EXACT_VERSION.fullmatch(value) is not None


def action_name(uses: str) -> str:
    return uses.split("@", 1)[0]


# ---------------------------------------------------------------------------
# Reading the real files
# ---------------------------------------------------------------------------


def _workflow_and_action_files() -> list[Path]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    files += sorted(ACTIONS.glob("*/action.yml")) + sorted(ACTIONS.glob("*/action.yaml"))
    return files


@dataclass(frozen=True)
class UsesEntry:
    path: Path
    line: int  # 0-based, as the parser reports it
    value: str
    after_value: str  # the raw text after the parsed value on the same line
    where: str

    def label(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line + 1} ({self.where}) uses: {self.value}"


def _get(node: yaml.Node | None, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return value_node
    return None


def _entry(path: Path, lines: list[str], node: yaml.Node, where: str) -> UsesEntry:
    assert isinstance(node, yaml.ScalarNode), f"{path}: {where}.uses is not a plain value"
    start, end = node.start_mark, node.end_mark
    assert start.line == end.line, f"{path}:{start.line + 1}: a uses value spans lines"
    return UsesEntry(
        path=path,
        line=start.line,
        value=str(node.value),
        after_value=lines[end.line][end.column :],
        where=where,
    )


def _steps_uses(
    path: Path, lines: list[str], steps: yaml.Node | None, prefix: str
) -> list[UsesEntry]:
    out: list[UsesEntry] = []
    if not isinstance(steps, yaml.SequenceNode):
        return out
    for index, step in enumerate(steps.value):
        uses = _get(step, "uses")
        if uses is not None:
            out.append(_entry(path, lines, uses, f"{prefix}.steps[{index}]"))
    return out


def uses_entries(path: Path) -> list[UsesEntry]:
    """Every ``uses`` value in one workflow or composite-action file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    out: list[UsesEntry] = []
    jobs = _get(root, "jobs")
    if isinstance(jobs, yaml.MappingNode):
        for key_node, job in jobs.value:
            name = f"jobs.{key_node.value}"
            job_uses = _get(job, "uses")
            if job_uses is not None:
                out.append(_entry(path, lines, job_uses, name))
            out += _steps_uses(path, lines, _get(job, "steps"), name)
    out += _steps_uses(path, lines, _get(_get(root, "runs"), "steps"), "runs")
    return out


def all_entries() -> list[UsesEntry]:
    return [entry for path in _workflow_and_action_files() for entry in uses_entries(path)]


def outside_entries() -> list[UsesEntry]:
    return [entry for entry in all_entries() if not entry.value.startswith("./")]


#: An INDEPENDENT reading of the same files: any line whose first word is
#: ``uses:`` (optionally after a list dash). It knows nothing about YAML.
_RAW_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s'\"#]+)")


def _raw_values() -> list[str]:
    values: list[str] = []
    for path in _workflow_and_action_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _RAW_USES.match(line)
            if match:
                values.append(match.group(1))
    return values


def _steps_of(action: str) -> list[tuple[Path, dict[str, Any]]]:
    """Every step in every workflow / composite action that runs ``action``."""
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in _workflow_and_action_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        step_lists: list[Any] = [job.get("steps") for job in (data.get("jobs") or {}).values()]
        step_lists.append((data.get("runs") or {}).get("steps"))
        for steps in step_lists:
            for step in steps or []:
                uses = step.get("uses") if isinstance(step, dict) else None
                if isinstance(uses, str) and action_name(uses) == action:
                    found.append((path, step))
    return found


def _with_version(step: dict[str, Any]) -> object:
    with_block = step.get("with")
    return with_block.get("version") if isinstance(with_block, dict) else None


def _raw_count_of(action: str) -> int:
    return sum(1 for value in _raw_values() if action_name(value) == action)


# ---------------------------------------------------------------------------
# Partners: the rules themselves, at their exact boundaries (pass now)
# ---------------------------------------------------------------------------

_SHA_39 = "11d5960a326750d5838078e36cf38b85af67726"
_SHA_40 = "11d5960a326750d5838078e36cf38b85af677262"
_SHA_41 = "11d5960a326750d5838078e36cf38b85af6772620"
_SHA_40_UPPER = "11D5960A326750D5838078E36CF38B85AF677262"


def test_partner_the_boundary_literals_have_the_lengths_they_claim() -> None:
    """Partner, passes now.

    Red when: one of the boundary literals below is
    edited to a different length, so the 39/40/41 tests stop testing the
    boundary they are named for."""
    assert (len(_SHA_39), len(_SHA_40), len(_SHA_41), len(_SHA_40_UPPER)) == (39, 40, 41, 40)


@pytest.mark.parametrize(
    "uses",
    [
        "actions/checkout@v4",
        "actions/checkout@v4.2.2",
        "actions/checkout@11d5960",
        f"actions/checkout@{_SHA_39}",
        f"actions/checkout@{_SHA_41}",
        f"actions/checkout@{_SHA_40_UPPER}",
        "owner/repo@main",
        "actions/checkout",
        f"actions/checkout@{_SHA_40} ",
        f"docker://alpine@sha256:{_SHA_40}{_SHA_40[:24]}",
    ],
)
def test_partner_is_pinned_rejects(uses: str) -> None:
    """Partner, passes now.

    Red when: ``is_pinned`` is loosened to accept a tag,
    a branch, a short or over-long id, an uppercase id, or a missing ref."""
    assert not is_pinned(uses)


@pytest.mark.parametrize(
    "uses",
    [
        f"actions/checkout@{_SHA_40}",
        f"superfly/flyctl-actions/setup-flyctl@{_SHA_40}",
        f"owner/repo/.github/workflows/build.yml@{_SHA_40}",
        "./.github/actions/x",
    ],
)
def test_partner_is_pinned_accepts(uses: str) -> None:
    """Partner, passes now.

    Red when: ``is_pinned`` is tightened so it refuses a
    40-character lowercase commit id, a sub-path action, a reusable workflow,
    or a local ``./`` action."""
    assert is_pinned(uses)


@pytest.mark.parametrize(
    ("after_value", "expected"),
    [
        (" # v4.4.0", "v4.4.0"),
        (" # 1.6", "1.6"),
        ("  #v6", "v6"),
        (" # v4.4.0   ", "v4.4.0"),
        ("", None),
        (" # pinned", None),
        (" # v4.4.0 latest", None),
        (" # v4.", None),
        ("#v4.4.0", None),
    ],
)
def test_partner_version_comment_reads_only_a_version(
    after_value: str, expected: str | None
) -> None:
    """Partner, passes now.

    Red when: ``version_comment`` accepts a missing
    comment, a comment that is not a version, or a comment not separated from
    the value by whitespace (YAML would read that as part of the value)."""
    assert version_comment(after_value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.13.0", True),
        ("10.2.33", True),
        ("latest", False),
        ("0.13", False),
        (0.13, False),
        ("0.13.x", False),
        (">=0.13.0", False),
        ("v0.13.0", False),
        ("0.13.0.1", False),
        (None, False),
    ],
)
def test_partner_is_exact_version(value: object, expected: bool) -> None:
    """Partner, passes now.

    Red when: ``is_exact_version`` accepts ``latest``,
    a two-part version, a range, a wildcard, a non-string, or a missing value."""
    assert is_exact_version(value) is expected


def test_partner_the_walk_finds_every_uses_line() -> None:
    """Partner, passes now.

    Red when: the YAML walk misses ``uses`` entries the
    raw text has (a new place a ``uses`` can sit that the walk does not visit),
    or finds none at all — either would let the pinning tests pass over
    nothing."""
    walked = all_entries()
    raw = _raw_values()
    outside_walked = [e.value for e in walked if not e.value.startswith("./")]
    outside_raw = [v for v in raw if not v.startswith("./")]
    assert len(outside_walked) > 0, "the YAML walk found no outside uses: entries"
    assert sorted(outside_walked) == sorted(outside_raw), (
        f"YAML walk found {len(outside_walked)} outside uses:, raw lines show {len(outside_raw)}"
    )
    local_walked = [e.value for e in walked if e.value.startswith("./")]
    assert len(local_walked) > 0, "the walk found no local ./ action, so the exemption is untested"
    assert len(local_walked) == len(raw) - len(outside_raw)
    read = _workflow_and_action_files()
    assert any(p.name == "action.yml" for p in read), "no composite action.yml is being read"
    assert any(p.parent == WORKFLOWS for p in read), "no workflow file is being read"


def test_partner_the_walk_visits_job_level_and_composite_steps(tmp_path: Path) -> None:
    """Partner, passes now.

    Red when: ``uses_entries`` stops visiting a
    reusable-workflow ``jobs.<id>.uses``, a ``jobs.<id>.steps[n].uses``, or a
    composite action's ``runs.steps[n].uses`` — the real tree has no
    job-level or composite outside ``uses`` today, so only this synthetic
    file proves those places are read — or stops returning the text after
    the value."""
    workflow = tmp_path / "w.yml"
    workflow.write_text(
        "on: push\n"
        "jobs:\n"
        "  reuse:\n"
        f"    uses: o/r/.github/workflows/x.yml@{_SHA_40} # v1.2.3\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      # uses: not/a-step@v1\n"
        "      - run: |\n"
        "          uses: not/a-step@v1\n"
        "      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    action = tmp_path / "action.yml"
    action.write_text(
        "name: x\n"
        "runs:\n"
        "  using: composite\n"
        "  steps:\n"
        f'    - uses: "actions/cache@{_SHA_40}"  # 4.2\n',
        encoding="utf-8",
    )
    found = [(e.where, e.value, version_comment(e.after_value)) for e in uses_entries(workflow)]
    found += [(e.where, e.value, version_comment(e.after_value)) for e in uses_entries(action)]
    assert found == [
        ("jobs.reuse", f"o/r/.github/workflows/x.yml@{_SHA_40}", "v1.2.3"),
        ("jobs.build.steps[1]", "actions/checkout@v4", None),
        ("runs.steps[0]", f"actions/cache@{_SHA_40}", "4.2"),
    ]


# ---------------------------------------------------------------------------
# The contract (fail until W69 is built)
# ---------------------------------------------------------------------------


def test_every_outside_action_is_pinned_to_a_full_commit_id() -> None:
    """Red when: any workflow or composite action names an outside action by a
    tag, a branch or a short id instead of a full 40-character commit id."""
    unpinned = [entry.label() for entry in outside_entries() if not is_pinned(entry.value)]
    assert not unpinned, (
        f"{len(unpinned)} outside actions are not pinned to a commit id:\n" + "\n".join(unpinned)
    )


def test_every_pinned_outside_action_names_its_version_in_a_comment() -> None:
    """Red when: a ``uses: owner/repo@<commit id>`` line has no trailing
    ``# vX.Y.Z`` comment, so a reader cannot tell which release it is."""
    entries = outside_entries()
    assert entries, "no outside uses: entries found"
    missing = [entry.label() for entry in entries if version_comment(entry.after_value) is None]
    assert not missing, (
        f"{len(missing)} outside uses: lines carry no trailing version comment:\n"
        + "\n".join(missing)
    )


def test_one_commit_id_carries_one_version_and_one_version_one_commit_id() -> None:
    """Red when: the same action at the same commit id is labelled with two
    different versions, or the same action and version label point at two
    different commit ids (one of the two is a typo or a stale label)."""
    labelled = [
        (action_name(e.value), e.value.split("@", 1)[1], version_comment(e.after_value), e)
        for e in outside_entries()
        if is_pinned(e.value) and version_comment(e.after_value) is not None
    ]
    assert labelled, "no pinned, version-labelled outside uses: entries to compare"
    by_commit: dict[tuple[str, str], set[str | None]] = defaultdict(set)
    by_version: dict[tuple[str, str | None], set[str]] = defaultdict(set)
    for action, commit, version, _ in labelled:
        by_commit[(action, commit)].add(version)
        by_version[(action, version)].add(commit)
    two_versions = {k: v for k, v in by_commit.items() if len(v) > 1}
    two_commits = {k: v for k, v in by_version.items() if len(v) > 1}
    assert not two_versions, f"one commit, several version labels: {two_versions}"
    assert not two_commits, f"one version label, several commits: {two_commits}"


def test_every_setup_uv_step_installs_one_exact_uv_version() -> None:
    """Red when: any ``astral-sh/setup-uv`` step has no ``with: version:``, or
    sets ``latest``, a range or a two-part version, or two steps set
    different versions."""
    steps = _steps_of(SETUP_UV)
    assert len(steps) > 0, "no setup-uv step found"
    assert len(steps) == _raw_count_of(SETUP_UV), "the step walk missed a setup-uv line"
    versions = [
        (f"{path.relative_to(ROOT)}:{step.get('name') or step['uses']}", _with_version(step))
        for path, step in steps
    ]
    loose = [(where, v) for where, v in versions if not is_exact_version(v)]
    assert not loose, f"{len(loose)} setup-uv steps without an exact X.Y.Z version: {loose}"
    distinct = {str(v) for _, v in versions}
    assert len(distinct) == 1, f"setup-uv steps disagree on the uv version: {sorted(distinct)}"


def test_the_setup_flyctl_step_installs_an_exact_flyctl_version() -> None:
    """Red when: the ``superfly/flyctl-actions/setup-flyctl`` step has no
    ``with: version:``, or sets ``latest`` or anything but an exact X.Y.Z."""
    steps = _steps_of(SETUP_FLYCTL)
    assert len(steps) > 0, "no setup-flyctl step found"
    assert len(steps) == _raw_count_of(SETUP_FLYCTL), "the step walk missed a setup-flyctl line"
    loose = [
        (f"{path.relative_to(ROOT)}:{step.get('name')}", _with_version(step))
        for path, step in steps
        if not is_exact_version(_with_version(step))
    ]
    assert not loose, f"setup-flyctl steps without an exact X.Y.Z version: {loose}"
