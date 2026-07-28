"""The #131 guard must catch a vacuous browser test, and only a vacuous one.

`e2e/tools/check-negative-assertions.mjs` fails a CHANGED spec file whose
negative assertion has no positive partner in the same `test()`. It is the
TypeScript counterpart to the mutation gate, which reads Python only — and a
census of 158 escaped defects found "tests that cannot fail" to be the
second-largest category, with ~28 of 32 living in `e2e/tests/**/*.spec.ts`.

The checker is Node (it needs a real TypeScript parser). These tests drive it
as a subprocess over fixture sources, so its behaviour is pinned by the same
suite as everything else rather than by a second harness nobody runs.

They SKIP when `e2e/node_modules` is absent — a fresh clone that has not run
`npm ci` must not go red. `test_the_guard_is_wired_into_ci` does not skip: an
unregistered gate is not a gate, and that check needs no node.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E = REPO_ROOT / "e2e"
CHECKER = E2E / "tools" / "check-negative-assertions.mjs"
E2E_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "e2e.yml"

pytestmark = pytest.mark.repo_introspection


def _run(source: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    spec = tmp_path / "probe.spec.ts"
    spec.write_text(source, encoding="utf-8")
    return subprocess.run(
        ["node", str(CHECKER), str(spec)],
        cwd=E2E,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def _needs_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    if not (E2E / "node_modules" / "@typescript-eslint" / "parser").is_dir():
        pytest.skip("e2e/node_modules is absent — run `npm ci` in e2e/")


VACUOUS = """\
import { test, expect } from "@playwright/test";

test("a fully live synthesis carries NO badge", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator(".badge-summary")).toHaveCount(0);
});
"""

PARTNERED = """\
import { test, expect } from "@playwright/test";

test("a fully live synthesis carries NO badge", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator("#result-verdict")).toBeVisible();
  await expect(page.locator(".badge-summary")).toHaveCount(0);
});
"""


def test_a_negative_with_no_partner_is_reported(tmp_path: Path) -> None:
    """The real shape: `verdict-band.spec.ts` "carries NO badge".

    Nothing in that test proves the result view rendered, so the assertion holds
    just as well over a blank page.

    Turns red if: the partner requirement is removed from `checkSource`.
    """
    result = _run(VACUOUS, tmp_path)
    assert result.returncode != 0, f"a vacuous test passed:\n{result.stdout}{result.stderr}"
    assert "carries NO badge" in result.stderr, (
        f"the report must name the test, or it is not actionable:\n{result.stderr}"
    )


def test_a_negative_with_a_liveness_partner_passes(tmp_path: Path) -> None:
    """Positive partner: the guard must not fire on an honest test.

    Without this, the assertion above is equally satisfied by a checker that
    rejects every negative assertion — which would be a tax, not a gate.

    Turns red if: liveness assertions stop counting as partners (measured: that
    takes the comment burden from 26% of sites to 70%).
    """
    result = _run(PARTNERED, tmp_path)
    assert result.returncode == 0, (
        f"an honest test with a liveness partner was rejected:\n{result.stdout}{result.stderr}"
    )


EXEMPTED = """\
import { test, expect } from "@playwright/test";

test("no console errors", async ({ page }) => {
  // no-positive-partner: asserting a console error EXISTS would assert the page is broken
  expect(pageErrors).toEqual([]);
});
"""


def test_an_annotated_exemption_is_accepted(tmp_path: Path) -> None:
    """Absence really is the point sometimes — but the reason must be written.

    Deliberately NOT a family allowlist keyed on names like `violations` or
    `pageErrors`: that is gameable by naming a variable, and is the
    "gate on a whole-line substring" antipattern AGENTS.md warns about. Every
    exemption is per-site and carries a reason a reviewer can weigh.

    Turns red if: the exemption comment stops being honoured.
    """
    result = _run(EXEMPTED, tmp_path)
    assert result.returncode == 0, (
        f"an annotated exemption was rejected:\n{result.stdout}{result.stderr}"
    )


BARE_COMMENT = """\
import { test, expect } from "@playwright/test";

test("no console errors", async ({ page }) => {
  // this one is fine honestly
  expect(pageErrors).toEqual([]);
});
"""


def test_an_unannotated_comment_is_not_an_exemption(tmp_path: Path) -> None:
    """Any comment must not work — only the marker with a reason.

    Turns red if: the exemption regex is loosened to match any comment.
    """
    result = _run(BARE_COMMENT, tmp_path)
    assert result.returncode != 0, (
        f"a plain comment was accepted as an exemption:\n{result.stdout}{result.stderr}"
    )


POLARITY = """\
import { test, expect } from "@playwright/test";

test("used-by markers are truthful", async ({ page }) => {
  await expect(page.locator("td.used-feeds")).not.toHaveCount(0);
  expect(names).not.toContain("/");
});
"""


def test_a_positive_wearing_a_not_counts_as_a_partner(tmp_path: Path) -> None:
    """The polarity trap. 16 sites in this repo are positives wearing a `not.`.

    `.not.toHaveCount(0)` asserts the locator DOES match something;
    `.not.toBeNull()` asserts presence. A matcher-name check inverts both.

    Turns red if: `classify()` stops special-casing the negated forms — the
    guard then reports this honest test and misses that it had a partner.
    """
    result = _run(POLARITY, tmp_path)
    assert result.returncode == 0, (
        f"`.not.toHaveCount(0)` was read as a negative:\n{result.stdout}{result.stderr}"
    )


LOOP_PARTNER = """\
import { test, expect } from "@playwright/test";

test("openings show friendly names, never a raw slug", async ({ page }) => {
  const names = page.locator(".opening-name");
  await expect(names).toHaveCount(4);
  for (const n of await names.allTextContents()) {
    expect(n).not.toContain("/");
  }
});
"""


def test_a_partner_outside_the_loop_still_counts(tmp_path: Path) -> None:
    """The partner may be a sibling statement, not inside the loop body.

    14 sites in this repo have this shape: the cardinality proof sits above the
    `for`, the negative inside it. A block-scoped search reports every one.

    Turns red if: the partner search is narrowed from the whole `test()` body to
    the enclosing block.
    """
    result = _run(LOOP_PARTNER, tmp_path)
    assert result.returncode == 0, (
        f"a partner outside the loop was not seen:\n{result.stdout}{result.stderr}"
    )


def test_the_guard_is_wired_into_ci() -> None:
    """An unregistered gate is not a gate — the repo's most-repeated lesson.

    Three specs have been committed, green, and named in no workflow
    (`docs/103-incident-learnings.md`). This checker must not become the fourth.
    It runs inside the REQUIRED `e2e axe + parity (chromium)` job, so it blocks
    without needing a branch-protection change.

    Deliberately does not skip when node is missing: the wiring is a text fact.

    Turns red if: the step is deleted from e2e.yml, or the checker is renamed
    without updating the workflow.
    """
    assert CHECKER.is_file(), f"the checker is missing: {CHECKER}"
    workflow = E2E_WORKFLOW.read_text(encoding="utf-8")
    assert "check-negative-assertions.mjs" in workflow, (
        "the #131 guard exists but is named in no workflow — it would be "
        "committed, green locally, and never run in CI"
    )
    assert "fetch-depth: 0" in workflow, (
        "the guard diffs changed specs against the PR base; on a shallow clone "
        "the base ref is absent, the diff is empty, and it checks NOTHING"
    )


def test_the_parser_dependency_is_declared() -> None:
    """The checker imports @typescript-eslint/parser; `npm ci` must install it.

    Turns red if: the dependency is dropped from e2e/package.json while the
    checker still imports it — CI would fail with a module-not-found that reads
    like an infrastructure fault rather than a missing declaration.
    """
    package = (E2E / "package.json").read_text(encoding="utf-8")
    assert "@typescript-eslint/parser" in package, (
        "the checker imports @typescript-eslint/parser but it is not declared"
    )
