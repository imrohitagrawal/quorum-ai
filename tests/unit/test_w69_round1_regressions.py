"""W69 round 1 review: regressions for the holes the reviewers reproduced.

The workflow audit (``make workflow-audit``, ADR-0166) is only as strong as
what it is allowed to see and report. Four ways to quietly weaken it passed
every first-round test:

1. an inline ``# zizmor: ignore[...]`` comment in a workflow suppresses a
   finding without touching ``.github/zizmor.yml``, where every suppression is
   meant to live with its reason;
2. a flag on the Makefile recipe (``--no-exit-codes``, ``--min-severity``,
   ``--min-confidence``, ``--persona``, ``--collect``) makes zizmor exit 0 or
   report less, while the recipe still "runs zizmor offline with the config";
3. ``disable:`` on a rule in ``.github/zizmor.yml`` turns the whole audit off;
4. ``.github/zizmor.yml`` ignores ``dangerous-triggers`` for ALL of
   ``deploy.yml``, so a new trigger added to that file (a
   ``pull_request_target``, say) would raise no finding.

WHAT TURNS THIS FILE RED: an inline ``zizmor: ignore`` anywhere under
``.github``; any of those flags on the ``workflow-audit`` recipe; a
``disable:`` key under any rule in ``.github/zizmor.yml``; a trigger in
``deploy.yml`` other than ``workflow_run`` and ``workflow_dispatch``, or
either of those removed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.repo_root import find_repo_root
from tests.unit.test_w69_workflow_audit import _zizmor_args

ROOT = find_repo_root(Path(__file__))
GITHUB = ROOT / ".github"
CONFIG = GITHUB / "zizmor.yml"
DEPLOY = GITHUB / "workflows" / "deploy.yml"

#: zizmor's inline suppression is a YAML comment ``# zizmor: ignore[rule]``.
#: Matched loosely (any spacing, any case) so a near-miss spelling that zizmor
#: might still accept is refused too.
_INLINE_IGNORE = re.compile(r"zizmor\s*:\s*ignore", re.IGNORECASE)

#: Flags that make zizmor exit 0 on a finding, report fewer findings, or
#: audit fewer inputs. ``--persona`` is refused whatever its value: any
#: persona but the default changes what is reported.
_WEAKENING_FLAGS = (
    "--no-exit-codes",
    "--min-severity",
    "--min-confidence",
    "--persona",
    "--collect",
)


def _inline_ignores(text: str) -> list[int]:
    """1-based line numbers of ``text`` that carry an inline zizmor ignore."""
    return [n for n, line in enumerate(text.splitlines(), 1) if _INLINE_IGNORE.search(line)]


def _weakening(args: list[str]) -> list[str]:
    """The arguments in ``args`` that are, or set, a weakening flag."""
    return [
        word
        for word in args
        if any(word == flag or word.startswith(flag + "=") for flag in _WEAKENING_FLAGS)
    ]


def _github_files() -> list[Path]:
    return sorted(p for p in GITHUB.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# 1. No inline suppression under .github
# ---------------------------------------------------------------------------


def test_no_file_under_github_carries_an_inline_zizmor_ignore() -> None:
    """Red when: any file under ``.github`` contains ``zizmor: ignore`` (an
    inline suppression that bypasses ``.github/zizmor.yml``)."""
    read = _github_files()
    hits = {
        str(p.relative_to(ROOT)): lines
        for p in read
        if (lines := _inline_ignores(p.read_text(encoding="utf-8", errors="replace")))
    }
    assert not hits, f"inline zizmor suppressions (put them in .github/zizmor.yml): {hits}"


def test_partner_the_inline_ignore_walk_reads_the_workflows() -> None:
    """Red when: the walk reads no files, or misses a workflow, the composite
    action or the config it must cover (so the negative check above would be
    true over nothing)."""
    read = {str(p.relative_to(GITHUB)) for p in _github_files()}
    expected = {
        "workflows/ci.yml",
        "workflows/deploy.yml",
        "workflows/test.yml",
        "workflows/e2e.yml",
        "actions/bound-apt-waits/action.yml",
        "zizmor.yml",
    }
    assert expected <= read, f"not read: {sorted(expected - read)}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("run: echo hi  # zizmor: ignore[template-injection]\n", [1]),
        ("a: 1\n- uses: x/y@v1 #zizmor:ignore[unpinned-uses]\n", [2]),
        ("a: 1\nb: 2 # ZIZMOR: IGNORE[artipacked]\n", [2]),
        ("a: 1\n# zizmor configuration\nignore:\n  - deploy.yml\n", []),
    ],
)
def test_partner_the_inline_ignore_matcher_finds_a_planted_comment(
    text: str, expected: list[int]
) -> None:
    """Red when: the matcher misses a planted ``# zizmor: ignore[...]`` (in any
    spacing or case), or flags a config-file ``ignore:`` key that is not one."""
    assert _inline_ignores(text) == expected


# ---------------------------------------------------------------------------
# 2. The recipe passes no flag that weakens the audit
# ---------------------------------------------------------------------------


def test_the_workflow_audit_recipe_passes_no_weakening_flag() -> None:
    """Red when: the ``workflow-audit`` recipe gives zizmor ``--no-exit-codes``,
    ``--min-severity``, ``--min-confidence``, ``--persona`` or ``--collect``
    (in either the ``--flag value`` or the ``--flag=value`` form)."""
    args = _zizmor_args()
    assert "--offline" in args, f"did not read the real recipe's arguments: {args}"
    assert not _weakening(args), f"workflow-audit weakens zizmor: {_weakening(args)}"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--offline", "--no-exit-codes", ".github"], ["--no-exit-codes"]),
        (["--min-severity", "high", ".github"], ["--min-severity"]),
        (["--min-confidence=high", ".github"], ["--min-confidence=high"]),
        (["--persona", "regular", ".github"], ["--persona"]),
        (["--persona=auditor", ".github"], ["--persona=auditor"]),
        (["--collect=actions", ".github"], ["--collect=actions"]),
        (["--offline", "--config", ".github/zizmor.yml", ".github"], []),
    ],
)
def test_partner_the_flag_matcher_finds_each_weakening_flag(
    args: list[str], expected: list[str]
) -> None:
    """Red when: the matcher misses a weakening flag in either form, or flags
    the recipe's own harmless arguments."""
    assert _weakening(args) == expected


# ---------------------------------------------------------------------------
# 3. The config disables no rule
# ---------------------------------------------------------------------------


def _rules() -> dict[str, Any]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    rules = config.get("rules") if isinstance(config, dict) else None
    assert isinstance(rules, dict) and rules, f"{CONFIG.name} has no rules mapping: {config!r}"
    return rules


def test_the_zizmor_config_disables_no_rule() -> None:
    """Red when: any rule in ``.github/zizmor.yml`` carries a ``disable:`` key
    (``disable: true`` turns that audit off everywhere)."""
    rules = _rules()
    assert "unpinned-uses" in rules, f"did not read the real config: {sorted(rules)}"
    disabled = [
        name for name, body in rules.items() if isinstance(body, dict) and "disable" in body
    ]
    not_mappings = [name for name, body in rules.items() if not isinstance(body, dict)]
    assert not disabled, f"rules disabled in {CONFIG.name}: {disabled}"
    assert not not_mappings, f"rules whose body is not a mapping: {not_mappings}"


# ---------------------------------------------------------------------------
# 4. deploy.yml's triggers are exactly the two the dangerous-triggers ignore
#    was written for
# ---------------------------------------------------------------------------


def _deploy_triggers() -> set[str]:
    workflow = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) reads the bare key ``on`` as the boolean True.
    on = workflow.get(True, workflow.get("on"))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    assert isinstance(on, dict), f"deploy.yml has no readable on: block: {on!r}"
    return set(on)


def test_deploy_triggers_are_exactly_workflow_run_and_workflow_dispatch() -> None:
    """Red when: ``deploy.yml`` gains a trigger (which the whole-file
    ``dangerous-triggers`` ignore in ``.github/zizmor.yml`` would hide) or
    loses ``workflow_run`` or ``workflow_dispatch``."""
    assert _deploy_triggers() == {"workflow_run", "workflow_dispatch"}
