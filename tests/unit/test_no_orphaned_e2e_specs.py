"""Issue #127 — 42+ e2e tests ran in NO CI workflow at all.

``tests/test_e2e_workflow_covers_all_invariant_specs.py`` only walks
``e2e/tests/invariants/`` and ``e2e/tests/ops/`` and only checks against
``.github/workflows/e2e.yml`` specifically — the right scope for THAT guard,
because a spec under ``invariants/`` must be in the BLOCKING lane or it is not
really gated. That narrower guard cannot see a spec sitting in a sibling
directory (``e2e/tests/workspace/``, ``accessibility/``, ``api-mocking/``,
``navigation/``) that runs in NO workflow whatsoever — advisory or blocking.
That is exactly how ``workspace.spec.ts`` (originally 17 tests; 16 after this
PR deletes one testing dead markup, see its own diff), ``accessibility.
spec.ts`` (16), ``api-mocking.spec.ts`` (9) and ``navigation.spec.ts`` (10)
went uncollected by any CI job: none of them lived under ``invariants/`` or
``ops/``, so the existing guard never looked at them. (The issue that reported
this undercounted by one file: it named three specs, 42 tests; ``navigation.
spec.ts``, 10 more tests, was in exactly the same unrun state and the issue
missed it — re-verified here by scanning every workflow file, not by trusting
the issue text.)

This guard is deliberately WEAKER than the invariants one in one respect and
STRONGER in another:

* Weaker: it accepts a spec named in ANY workflow (advisory or blocking) —
  e.g. ``e2e/tests/csp/csp-smoke.spec.ts`` is invoked only from the advisory,
  cross-engine ``csp-smoke.yml`` by deliberate design (see that workflow's own
  comment: promoting it into the blocking ``e2e.yml`` lane early would trip a
  brand-new firefox/webkit quirk against a production deploy gate before the
  measured 5-green-run bar is met). Requiring every spec to be in the
  BLOCKING lane specifically would force a premature promotion this repo has
  explicitly decided against.
* Stronger: it resolves a DIRECTORY argument (e.g. ``tests/ops``) to the real
  files under it via the same walk Playwright itself performs, rather than a
  raw substring search over the workflow's text — closing the "named only in
  a comment, never actually invoked" blind spot recorded against the sibling
  guard in AGENTS.md.

The property asserted is the minimal one implied by the issue's own title:
every spec runs in at least one CI job, so it cannot sit in the repo
indefinitely, always green locally, and never execute anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E_TESTS_DIR = REPO_ROOT / "e2e" / "tests"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def _playwright_invocations(text: str) -> list[str]:
    """Every ``npx playwright test ...`` command in a workflow, as one string
    each. Mirrors ``tests/unit/test_e2e_flake_policy.py``'s helper of the same
    name (not imported from it deliberately — same convention this repo
    already uses between ``test_golden_fixture_notice_sync.py`` and
    ``test_notice_coverage_spec_sync.py``: two independent, loosely-coupled
    guards rather than one guard's internals reused by another).
    """
    commands: list[str] = []
    starts = [m.start() for m in re.finditer(r"npx playwright test\b", text)]
    for index, start in enumerate(starts):
        rest = text[start:]
        stops = [len(rest)]
        next_step = re.search(r"\n\s{0,8}-\s+[A-Za-z_-]+:", rest)
        if next_step:
            stops.append(next_step.start())
        if index + 1 < len(starts):
            stops.append(starts[index + 1] - start)
        commands.append(rest[: min(stops)])
    return commands


def _spec_arguments(command: str) -> list[str]:
    """The bare path arguments of ONE playwright invocation, comment-free.

    Stops at the first blank line or ``#``-led line after the flags — a real
    YAML folded block scalar ends where indentation returns to the key's own
    level, which is the first such line in every invocation this repo writes.
    """
    arguments: list[str] = []
    for line in command.splitlines()[1:]:  # [0] is "npx playwright test"
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            break
        if stripped.startswith("-"):
            continue  # a flag, e.g. --project=chromium
        arguments.append(stripped)
    return arguments


def _all_spec_files() -> list[Path]:
    return sorted(E2E_TESTS_DIR.rglob("*.spec.ts"))


def _swept_spec_files() -> set[Path]:
    """Every ``.spec.ts`` file actually reachable from SOME workflow's
    playwright invocation — a named file directly, or a directory argument
    resolved the way Playwright itself would walk it.
    """
    swept: set[Path] = set()
    for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        for command in _playwright_invocations(text):
            for argument in _spec_arguments(command):
                target = REPO_ROOT / "e2e" / argument
                if argument.endswith(".spec.ts"):
                    if target.is_file():
                        swept.add(target)
                elif target.is_dir():
                    swept.update(target.rglob("*.spec.ts"))
    return swept


def test_the_repo_has_e2e_specs() -> None:
    """A guard over zero specs proves nothing (the ``all([])`` trap)."""
    assert _all_spec_files(), "no .spec.ts files found under e2e/tests/ — glob is wrong"


def test_at_least_one_workflow_invokes_playwright() -> None:
    swept = _swept_spec_files()
    assert swept, (
        "no .github/workflows/*.yml file's playwright invocation resolved to "
        "any real spec file — the parser or the workflow set is broken, and "
        "the parametrized test below would vacuously pass over nothing"
    )


@pytest.mark.parametrize(
    "spec",
    _all_spec_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_every_e2e_spec_runs_in_at_least_one_workflow(spec: Path) -> None:
    """Turns red if: a new ``*.spec.ts`` is committed under ``e2e/tests/``
    without being named (or swept via a directory argument) in any workflow —
    reproduced directly against ``workspace.spec.ts`` before this guard
    existed, which stayed green under every other check in this repo.
    """
    swept = _swept_spec_files()
    assert spec in swept, (
        f"{spec.relative_to(REPO_ROOT)} is committed under e2e/tests/ but no "
        ".github/workflows/*.yml invokes it, directly or via a directory "
        "argument that sweeps it — issue #127. It would sit in the repo, "
        "pass locally forever, and never execute in CI, advisory or blocking."
    )
