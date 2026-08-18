"""The #131 guard must catch a vacuous browser test, and only a vacuous one.

`e2e/tools/check-negative-assertions.mjs` fails a CHANGED spec file whose
negative assertion has no positive partner in the same `test()`. It is the
TypeScript counterpart to the mutation gate, which reads Python only.
`docs/metrics/mutation-gate-study.md` §4 censused 158 escaped defects and found
144 (91%) structurally invisible to that gate, ~46% of them in non-Python files
including the Playwright specs this guard covers.

The checker is Node (it needs a real TypeScript parser). These tests drive it
as a subprocess over fixture sources, so its behaviour is pinned by the same
suite as everything else rather than by a second harness nobody runs.

On a developer machine without node or `e2e/node_modules` the node-driven tests
SKIP, so a fresh clone that has not run `npm ci` does not go red. In the
required `pytest (Python 3.12)` lane the workflow installs both and sets
`QUORUM_REQUIRE_E2E_NODE_TOOLING=1`; there, absent tooling FAILS instead of
skipping. That is deliberate — until ADR-0058 every test in this file was
skipped in that lane, and the lane still reported green.

These need no node tooling — they read repo text, or drive a stub node they
create themselves — so they are marked `no_node_required` and run everywhere:
`test_the_guard_is_wired_into_ci`, `test_the_parser_dependency_is_declared`,
`test_the_required_pytest_lane_installs_the_node_tooling`,
`test_the_lane_wiring_probe_reports_every_missing_piece`,
`test_missing_tooling_is_fatal_only_when_the_lane_demands_it`,
`test_the_two_lanes_pin_the_same_node_version`,
`test_the_node_version_probe_reports_a_disagreement`,
`test_a_hung_node_is_killed_by_a_timeout`,
`test_the_docstring_names_only_tests_that_really_are_node_free`.
`test_the_docstring_names_only_tests_that_really_are_node_free` compares that
list against the markers in both directions, so this sentence cannot drift away
from the code the way its predecessor did.

The gate that this file never goes wholly skipped again lives in a DIFFERENT
file, `tests/unit/test_guard_suite_is_not_skipped.py`. It was here at first,
and a review round proved that worthless: a module-level `pytest.mark.skip`,
or an unguarded skip in the fixture below, silenced the watchdog along with
everything it was watching, and pytest still exited 0.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E = REPO_ROOT / "e2e"
CHECKER = E2E / "tools" / "check-negative-assertions.mjs"
E2E_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "e2e.yml"

#: Set by the required `pytest (Python 3.12)` lane, which installs node and
#: `e2e/node_modules` first. Where it is set, absent tooling is a FAILURE: the
#: lane asked for these tests and a silent skip there is the defect this
#: module's own gate exists to prevent.
NODE_TOOLING_REQUIRED_ENV = "QUORUM_REQUIRE_E2E_NODE_TOOLING"

#: Wall-clock ceiling for one checker subprocess. The whole module takes ~17s
#: on node 22, so this is generous; its job is to turn a wedged `node` into a
#: NAMED test failure instead of a job that burns to `timeout-minutes: 15` and
#: reports only "exceeded the maximum execution time". These tests only started
#: executing in a required lane with ADR-0058, so that risk is new.
NODE_TIMEOUT_SECONDS = 120

pytestmark = pytest.mark.repo_introspection


def _run(source: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    spec = tmp_path / "probe.spec.ts"
    spec.write_text(source, encoding="utf-8")
    return subprocess.run(
        ["node", str(CHECKER), str(spec)],
        cwd=E2E,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )


def _tooling_verdict(node_present: bool, parser_present: bool, required: bool) -> str:
    """What to do about the node tooling: ``run``, ``skip`` or ``fail``.

    Split out as a pure function so the decision can be driven over its whole
    input table without a subprocess, an environment, or a node install.
    """
    if node_present and parser_present:
        return "run"
    return "fail" if required else "skip"


def _missing_tooling() -> list[str]:
    """The pieces of the node tooling that are not present, in install order."""
    missing = []
    if shutil.which("node") is None:
        missing.append("node is not installed")
    if not (E2E / "node_modules" / "@typescript-eslint" / "parser").is_dir():
        missing.append("e2e/node_modules is absent — run `npm ci` in e2e/")
    return missing


@pytest.fixture(autouse=True)
def _needs_node(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("no_node_required") is not None:
        return
    missing = _missing_tooling()
    verdict = _tooling_verdict(
        node_present="node is not installed" not in missing,
        parser_present=not any(m.startswith("e2e/node_modules") for m in missing),
        required=os.environ.get(NODE_TOOLING_REQUIRED_ENV) == "1",
    )
    if verdict == "run":
        return
    reason = "; ".join(missing)
    if verdict == "fail":
        pytest.fail(
            f"{NODE_TOOLING_REQUIRED_ENV}=1 — this lane installs the node "
            f"tooling and these tests must run, but {reason}"
        )
    pytest.skip(reason)


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

    Turns red if: liveness assertions stop counting as partners — the guard
    then reports every absence-is-the-point test in the corpus.
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


TAUTOLOGY = """\
import { test, expect } from "@playwright/test";

test("gamed with a tautology", async ({ page }) => {
  expect(true).toBeTruthy();
  await expect(page.locator(".badge-summary")).toHaveCount(0);
});
"""


def test_a_tautological_partner_does_not_count(tmp_path: Path) -> None:
    """`expect(true).toBeTruthy()` proves nothing about the code under test.

    This was a real hole, found by adversarial review AFTER the PR body claimed
    it was verified. The claim came from a Python prototype that excluded
    literal subjects; the shipped Node checker classified by matcher name only
    and never looked at the subject. One line silenced a vacuous negative with
    no reason comment and no reviewer signal — strictly MORE gameable than the
    family allowlist this design rejected.

    Turns red if: `isTautologicalSubject` stops being consulted in `classify`.
    """
    result = _run(TAUTOLOGY, tmp_path)
    assert result.returncode != 0, (
        f"a literal-subject assertion served as a partner:\n{result.stdout}{result.stderr}"
    )


SMUGGLED = """\
import { test, expect } from "@playwright/test";

test("a title mentioning // no-positive-partner: smuggled", async ({ page }) => {
  expect(pageErrors).toEqual([]);
});
"""


def test_the_marker_cannot_be_smuggled_in_a_string(tmp_path: Path) -> None:
    """Exemptions are matched against COMMENT TOKENS, not raw line text.

    Matching text meant the marker could arrive inside a `test()` title or any
    string literal on a preceding line.

    Turns red if: the exemption is matched against source lines again.
    """
    result = _run(SMUGGLED, tmp_path)
    assert result.returncode != 0, (
        f"the marker inside a test title exempted an assertion:\n{result.stdout}{result.stderr}"
    )


REUSED = """\
import { test, expect } from "@playwright/test";

test("one reason must not cover two", async ({ page }) => {
  expect(a).toEqual([]); // no-positive-partner: reason for A only
  expect(b).toEqual([]);
});
"""


def test_one_exemption_does_not_cover_a_second_assertion(tmp_path: Path) -> None:
    """Each annotation is consumed once.

    The lookback previously walked up several lines and could reach an
    annotation that belonged to the assertion above.

    Turns red if: the consumed-marker bookkeeping is removed.
    """
    result = _run(REUSED, tmp_path)
    assert result.returncode != 0, (
        f"one reason exempted two assertions:\n{result.stdout}{result.stderr}"
    )
    assert ":5" in result.stderr, (
        f"the SECOND assertion (line 5) should be the one reported:\n{result.stderr}"
    )


SOFT_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("a fully live synthesis carries NO badge", async ({ page }) => {
  await driveWith(page, fixture);
  expect.soft(page.locator(".badge-summary")).toHaveCount(0);
});
"""

SOFT_PARTNERED = """\
import { test, expect } from "@playwright/test";

test("a fully live synthesis carries NO badge", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator("#result-verdict")).toBeVisible();
  expect.soft(page.locator(".badge-summary")).toHaveCount(0);
});
"""


def test_expect_soft_negative_with_no_partner_is_reported(tmp_path: Path) -> None:
    """#148: `assertionOf` bailed on `expect.soft(...)` because the chain root
    is a `MemberExpression` (`expect.soft`) rather than the `Identifier`
    `assertionOf` looked for — so every soft assertion was invisible in BOTH
    directions: a vacuous `expect.soft` negative passed, and a genuine
    `expect.soft` positive partner did not count either.

    Turns red if: the walk in `assertionOf` stops recognizing `expect.soft`.
    """
    result = _run(SOFT_VACUOUS, tmp_path)
    assert result.returncode != 0, (
        f"a vacuous expect.soft negative passed:\n{result.stdout}{result.stderr}"
    )


def test_expect_soft_negative_with_a_soft_partner_passes(tmp_path: Path) -> None:
    """Positive partner, `expect.soft` on both sides — proves the whole chain
    (partner detection AND negative detection) works for the soft form, not
    just one half of it.
    """
    result = _run(SOFT_PARTNERED, tmp_path)
    assert result.returncode == 0, f"a partnered test was rejected:\n{result.stdout}{result.stderr}"


POLL_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("no leftover toast messages", async ({ page }) => {
  await driveWith(page, fixture);
  await expect.poll(() => page.locator(".toast").allTextContents()).toHaveLength(0);
});
"""

POLL_NEGATIVE_PARTNERED = """\
import { test, expect } from "@playwright/test";

test("no leftover toast messages", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator("#result-verdict")).toBeVisible();
  await expect.poll(() => page.locator(".toast").allTextContents()).toHaveLength(0);
});
"""

POLL_POSITIVE_PARTNER = """\
import { test, expect } from "@playwright/test";

test("a fully live synthesis carries NO badge", async ({ page }) => {
  await driveWith(page, fixture);
  await expect.poll(() => page.locator("#result-verdict").count()).toBeGreaterThan(0);
  await expect(page.locator(".badge-summary")).toHaveCount(0);
});
"""


def test_expect_poll_negative_with_no_partner_is_reported(tmp_path: Path) -> None:
    """Same `assertionOf` blind spot, the `expect.poll` form: `toHaveLength(0)`
    on a polled array is exactly as much an emptiness claim as `toHaveCount(0)`
    on a locator.
    """
    result = _run(POLL_VACUOUS, tmp_path)
    assert result.returncode != 0, (
        f"a vacuous expect.poll negative passed:\n{result.stdout}{result.stderr}"
    )


def test_expect_poll_negative_with_a_partner_passes(tmp_path: Path) -> None:
    """Positive partner for the poll negative above."""
    result = _run(POLL_NEGATIVE_PARTNERED, tmp_path)
    assert result.returncode == 0, (
        f"a poll-partnered test was rejected:\n{result.stdout}{result.stderr}"
    )


def test_expect_poll_positive_partner_counts(tmp_path: Path) -> None:
    """`expect.poll(...).toBeGreaterThan(0)` proving liveness must count as a
    real partner — table-confirmed false positive in the issue: this shape
    was REJECTED before the fix.
    """
    result = _run(POLL_POSITIVE_PARTNER, tmp_path)
    assert result.returncode == 0, (
        f"a poll-partnered test was rejected:\n{result.stdout}{result.stderr}"
    )


TO_BE_HIDDEN_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("the loading spinner disappears", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator(".spinner")).toBeHidden();
});
"""

TO_BE_EMPTY_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("the error list is empty", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator("#error-list")).toBeEmpty();
});
"""


def test_to_be_hidden_with_no_partner_is_reported(tmp_path: Path) -> None:
    """#148: `toBeHidden()` is the most idiomatic Playwright absence matcher
    and was absent from `classify()` entirely — an unpartnered one read as
    "other", not "negative", so the guard never even considered it.

    Turns red if: `toBeHidden` is removed from the negative-matcher set.
    """
    result = _run(TO_BE_HIDDEN_VACUOUS, tmp_path)
    assert result.returncode != 0, f"a vacuous toBeHidden() passed:\n{result.stdout}{result.stderr}"


def test_to_be_empty_with_no_partner_is_reported(tmp_path: Path) -> None:
    """Turns red if: `toBeEmpty` is removed from the negative-matcher set."""
    result = _run(TO_BE_EMPTY_VACUOUS, tmp_path)
    assert result.returncode != 0, f"a vacuous toBeEmpty() passed:\n{result.stdout}{result.stderr}"


NOT_TO_HAVE_CLASS_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("the tab loses its active class", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator("#tab-2")).not.toHaveClass(/active/);
});
"""

NOT_TO_HAVE_ATTRIBUTE_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("the button loses aria-disabled", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator("#submit")).not.toHaveAttribute("aria-disabled", "true");
});
"""

NOT_TO_BE_IN_VIEWPORT_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("the banner scrolls out of view", async ({ page }) => {
  await driveWith(page, fixture);
  await expect(page.locator("#banner")).not.toBeInViewport();
});
"""


def test_not_to_have_class_with_no_partner_is_reported(tmp_path: Path) -> None:
    """Turns red if: `toHaveClass` is removed from `NEGATIVE_UNDER_NOT`."""
    result = _run(NOT_TO_HAVE_CLASS_VACUOUS, tmp_path)
    assert result.returncode != 0, (
        f"a vacuous .not.toHaveClass() passed:\n{result.stdout}{result.stderr}"
    )


def test_not_to_have_attribute_with_no_partner_is_reported(tmp_path: Path) -> None:
    """Turns red if: `toHaveAttribute` is removed from `NEGATIVE_UNDER_NOT`."""
    result = _run(NOT_TO_HAVE_ATTRIBUTE_VACUOUS, tmp_path)
    assert result.returncode != 0, (
        f"a vacuous .not.toHaveAttribute() passed:\n{result.stdout}{result.stderr}"
    )


def test_not_to_be_in_viewport_with_no_partner_is_reported(tmp_path: Path) -> None:
    """Turns red if: `toBeInViewport` is removed from `NEGATIVE_UNDER_NOT`."""
    result = _run(NOT_TO_BE_IN_VIEWPORT_VACUOUS, tmp_path)
    assert result.returncode != 0, (
        f"a vacuous .not.toBeInViewport() passed:\n{result.stdout}{result.stderr}"
    )


TO_STRICT_EQUAL_EMPTY_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("the notice list is empty", async ({ page }) => {
  const notices = await page.locator(".notice").all();
  expect(notices).toStrictEqual([]);
});
"""

TO_EQUAL_EMPTY_STRING_VACUOUS = """\
import { test, expect } from "@playwright/test";

test("the error text clears", async ({ page }) => {
  const text = await page.locator("#error").textContent();
  expect(text).toEqual("");
});
"""


def test_to_strict_equal_empty_array_with_no_partner_is_reported(tmp_path: Path) -> None:
    """Turns red if: `toStrictEqual` is dropped from the empty-array check
    that already covers `toEqual`.
    """
    result = _run(TO_STRICT_EQUAL_EMPTY_VACUOUS, tmp_path)
    assert result.returncode != 0, (
        f"a vacuous toStrictEqual([]) passed:\n{result.stdout}{result.stderr}"
    )


def test_to_equal_empty_string_with_no_partner_is_reported(tmp_path: Path) -> None:
    """Turns red if: the empty-string-literal check is removed from `toEqual`."""
    result = _run(TO_EQUAL_EMPTY_STRING_VACUOUS, tmp_path)
    assert result.returncode != 0, f"a vacuous toEqual('') passed:\n{result.stdout}{result.stderr}"


BEFORE_EACH_PARTNERED = """\
import { test, expect } from "@playwright/test";

test.describe("badge rendering", () => {
  test.beforeEach(async ({ page }) => {
    await driveWith(page, fixture);
    await expect(page.locator("#result-verdict")).toBeVisible();
  });

  test("a fully live synthesis carries NO badge", async ({ page }) => {
    await expect(page.locator(".badge-summary")).toHaveCount(0);
  });
});
"""

BEFORE_EACH_UNRELATED_DESCRIBE_STILL_VACUOUS = """\
import { test, expect } from "@playwright/test";

test.describe("badge rendering", () => {
  test.beforeEach(async ({ page }) => {
    await driveWith(page, fixture);
  });

  test("a fully live synthesis carries NO badge", async ({ page }) => {
    await expect(page.locator(".badge-summary")).toHaveCount(0);
  });
});
"""


def test_a_positive_in_before_each_counts_as_a_partner_for_every_test_in_the_describe(
    tmp_path: Path,
) -> None:
    """#148: `test.beforeEach` is the most common Playwright layout for
    "drive to the screen once, assert per-test" — the guard walked the AST
    flatly and never associated a `beforeEach`'s assertions with the tests
    in its `describe`, so this extremely common shape was a guaranteed false
    positive (measured false-alarm rate 15-25%).

    Turns red if: `beforeEach` assertions stop being attributed to sibling
    tests in the same `describe`.
    """
    result = _run(BEFORE_EACH_PARTNERED, tmp_path)
    assert result.returncode == 0, (
        "a test with its liveness partner in beforeEach was rejected:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_a_before_each_with_no_positive_assertion_still_reports(tmp_path: Path) -> None:
    """Positive partner for the fix above: attributing `beforeEach` assertions
    to sibling tests must not become "any `beforeEach` silences everything in
    its `describe`" — a `beforeEach` with NO positive assertion of its own
    must not manufacture one.
    """
    result = _run(BEFORE_EACH_UNRELATED_DESCRIBE_STILL_VACUOUS, tmp_path)
    assert result.returncode != 0, (
        "a beforeEach with no positive assertion silenced a real violation:\n"
        f"{result.stdout}{result.stderr}"
    )


DESCRIBE_PARALLEL_PARTNERED = """\
import { test, expect } from "@playwright/test";

test.describe.parallel("badge rendering", () => {
  test.beforeEach(async ({ page }) => {
    await driveWith(page, fixture);
    await expect(page.locator("#result-verdict")).toBeVisible();
  });

  test("a fully live synthesis carries NO badge", async ({ page }) => {
    await expect(page.locator(".badge-summary")).toHaveCount(0);
  });
});
"""

DESCRIBE_SERIAL_PARTNERED = """\
import { test, expect } from "@playwright/test";

test.describe.serial("badge rendering", () => {
  test.beforeEach(async ({ page }) => {
    await driveWith(page, fixture);
    await expect(page.locator("#result-verdict")).toBeVisible();
  });

  test("a fully live synthesis carries NO badge", async ({ page }) => {
    await expect(page.locator(".badge-summary")).toHaveCount(0);
  });
});
"""


def test_describe_parallel_still_associates_its_beforeEach(tmp_path: Path) -> None:
    """Found by adversarial review of the fix above, same file/mechanism,
    self-fixed here rather than filed separately: `isDescribeCall`'s
    three-level chain check only recognized `test.describe.only`/`.skip` —
    two real, documented Playwright modifiers, `.parallel` and `.serial`,
    were not in the allowlist, so a describe using either was invisible as
    a describe at all. `collectBeforeEachAssertions` never fired for it, so
    its `beforeEach`'s positive assertion never reached the test inside —
    the exact false-positive class #148 exists to close, on a different
    modifier. Not live in this repo's corpus today (verified: no spec uses
    either), but a real gap for the next spec author who reaches for one.

    Turns red if: `parallel`/`serial` are dropped from the three-level
    describe-chain allowlist.
    """
    result = _run(DESCRIBE_PARALLEL_PARTNERED, tmp_path)
    assert result.returncode == 0, (
        f"test.describe.parallel's beforeEach partner was not seen:\n{result.stdout}{result.stderr}"
    )


def test_describe_serial_still_associates_its_beforeEach(tmp_path: Path) -> None:
    result = _run(DESCRIBE_SERIAL_PARTNERED, tmp_path)
    assert result.returncode == 0, (
        f"test.describe.serial's beforeEach partner was not seen:\n{result.stdout}{result.stderr}"
    )


NUMERIC_ZERO_TO_BE_FALSE_POSITIVE = """\
import { test, expect } from "@playwright/test";

test("the page has not scrolled", async ({ page }) => {
  const scrollTop = await page.evaluate(() => document.documentElement.scrollTop);
  expect(scrollTop).toBe(0);
});
"""


def test_a_generic_toBe_zero_is_not_flagged_as_a_negative_assertion(tmp_path: Path) -> None:
    """#148: `expect(scrollTop).toBe(0)` is a legitimate numeric-zero
    assertion — nothing to do with "is this collection empty" — but the old
    rule grouped bare `toBe(0)` with `toHaveCount(0)`/`toHaveLength(0)`,
    flagging an honest, single-assertion test as vacuous. `toHaveCount(0)`
    and `toHaveLength(0)` are specifically about collection/string size and
    stay negative; generic `toBe(0)` does not.

    Turns red if: `toBe` rejoins the zero-matcher set that drives `negative`.
    """
    result = _run(NUMERIC_ZERO_TO_BE_FALSE_POSITIVE, tmp_path)
    assert result.returncode == 0, (
        "a legitimate toBe(0) assertion was flagged as an unpartnered negative:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_to_have_count_zero_is_still_negative_after_the_toBe_narrowing(tmp_path: Path) -> None:
    """Positive partner for the narrowing above: `toHaveCount(0)` must still
    be treated as a real emptiness claim needing a partner — the fix narrows
    which MATCHERS count as zero-checks, it must not narrow away the ones
    that are genuinely about collection size.
    """
    result = _run(VACUOUS, tmp_path)
    assert result.returncode != 0, (
        "toHaveCount(0) stopped being treated as a negative assertion:\n"
        f"{result.stdout}{result.stderr}"
    )


def test_an_unresolvable_base_ref_fails_closed(tmp_path: Path) -> None:
    """A git failure must not read as "no changed specs".

    Swallowing it printed "nothing to check" and exited 0 — indistinguishable
    from a healthy pull request that touched no specs. That is the silent-no-op
    failure this guard exists to prevent elsewhere, in the guard itself.

    Turns red if: the `required` flag is dropped from the base-diff call.
    """
    result = subprocess.run(
        ["node", str(CHECKER), "--base", "origin/definitely-not-a-real-ref"],
        cwd=E2E,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert result.returncode != 0, (
        f"an unresolvable base ref reported success:\n{result.stdout}{result.stderr}"
    )
    assert "unresolvable" in result.stderr.lower() or "failed" in result.stderr.lower(), (
        f"the failure must name its cause:\n{result.stderr}"
    )


@pytest.mark.no_node_required
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


@pytest.mark.no_node_required
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


# --- The tests above must actually RUN in a required lane -------------------
#
# Until this section existed they did not: every test in this module was
# skipped in `pytest (Python 3.12)` and in `validate-and-test`, because the
# autouse fixture needs `e2e/node_modules` and no pytest lane ran `npm ci`.
# See docs/adr/0058-guard-tests-run-in-a-required-pytest-lane.md.

TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
REQUIRED_PYTEST_JOB = "pytest (Python 3.12)"


def _required_pytest_job() -> dict[str, Any]:
    """The parsed job behind the required `pytest (Python 3.12)` context."""
    workflow = yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    for job in jobs.values():
        if job.get("name") == REQUIRED_PYTEST_JOB:
            assert isinstance(job, dict)
            return job
    raise AssertionError(
        f"no job named {REQUIRED_PYTEST_JOB!r} in {TEST_WORKFLOW}; "
        f"found {[j.get('name') for j in jobs.values()]}"
    )


def _runs_npm_ci(step: dict[str, Any]) -> bool:
    """True when this step's ``run`` invokes ``npm ci`` as a command.

    Tokenised, not substring-matched: a step whose script merely mentions
    `npm ci` in a comment must not count (AGENTS.md rule 8).
    """
    return any(
        line.strip().split()[:2] == ["npm", "ci"]
        for line in str(step.get("run") or "").splitlines()
    )


def _runs_make_test(step: dict[str, Any]) -> bool:
    """True when this step's ``run`` invokes ``make test`` as a command."""
    return any(
        line.strip().split()[:2] == ["make", "test"]
        for line in str(step.get("run") or "").splitlines()
    )


def _node_lane_wiring(job: dict[str, Any]) -> set[str]:
    """Names of the wiring pieces MISSING from a job, as a set.

    Empty means the job provisions node, installs `e2e/`'s packages before the
    test step, and tells this module's fixture that missing tooling is fatal
    rather than skippable. Returning the missing NAMES rather than a bool is
    what lets the caller say which piece regressed.
    """
    steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
    setup_at = npm_at = test_at = None
    for index, step in enumerate(steps):
        if setup_at is None and str(step.get("uses") or "").startswith("actions/setup-node@"):
            setup_at = index
        if npm_at is None and step.get("working-directory") == "e2e" and _runs_npm_ci(step):
            npm_at = index
        if test_at is None and _runs_make_test(step):
            test_at = index

    missing: set[str] = set()
    if setup_at is None:
        missing.add("setup-node")
    if npm_at is None:
        missing.add("npm-ci-in-e2e")
    if test_at is None:
        missing.add("make-test-step")
    else:
        # The VALUE, not just the key. The fixture treats only the exact
        # string "1" as "required", so `"0"` — or the `${{ steps.npm.outcome
        # ... }}` expression ADR-0058 rejects by name — silently restores the
        # all-skipped state while every check in the repo stays green.
        flag = (steps[test_at].get("env") or {}).get(NODE_TOOLING_REQUIRED_ENV)
        if flag is None or str(flag) != "1":
            missing.add("require-flag-on-make-test")
        if setup_at is not None and npm_at is not None and not setup_at < npm_at < test_at:
            missing.add("install-before-make-test")
    return missing


@pytest.mark.no_node_required
def test_the_required_pytest_lane_installs_the_node_tooling() -> None:
    """The fix, asserted where it lives: on the required lane's own job.

    Turns red if: the setup-node step, the `npm ci` step, the require flag, or
    the ordering between them is removed from `.github/workflows/test.yml` —
    each of which silently restores the all-skipped state this module was in.
    """
    missing = _node_lane_wiring(_required_pytest_job())
    assert missing == set(), (
        f"{REQUIRED_PYTEST_JOB} is missing {sorted(missing)}; without it every "
        "test in this module skips in a required context"
    )


@pytest.mark.no_node_required
def test_the_lane_wiring_probe_reports_every_missing_piece() -> None:
    """Positive/negative partner for the assertion above (AGENTS.md rule 7).

    An `== set()` assertion is trivially satisfied by a probe that always
    returns an empty set, and would then pass over any workflow at all.

    Turns red if: `_node_lane_wiring` stops detecting any one of the pieces, or
    is stubbed to return nothing.
    """
    bare = {"steps": [{"name": "Run tests", "run": "make test"}]}
    assert _node_lane_wiring(bare) == {
        "setup-node",
        "npm-ci-in-e2e",
        "require-flag-on-make-test",
    }

    wired = {
        "steps": [
            {"uses": "actions/setup-node@v4", "with": {"node-version": "22"}},
            {"working-directory": "e2e", "run": "npm ci --no-audit --no-fund"},
            {"run": "make test", "env": {NODE_TOOLING_REQUIRED_ENV: "1"}},
        ]
    }
    assert _node_lane_wiring(wired) == set()

    out_of_order = {
        "steps": [
            {"run": "make test", "env": {NODE_TOOLING_REQUIRED_ENV: "1"}},
            {"uses": "actions/setup-node@v4"},
            {"working-directory": "e2e", "run": "npm ci"},
        ]
    }
    assert _node_lane_wiring(out_of_order) == {"install-before-make-test"}

    wrong_directory = {
        "steps": [
            {"uses": "actions/setup-node@v4"},
            {"run": "npm ci"},
            {"run": "make test", "env": {NODE_TOOLING_REQUIRED_ENV: "1"}},
        ]
    }
    assert _node_lane_wiring(wrong_directory) == {"npm-ci-in-e2e"}

    commented_only = {
        "steps": [
            {"uses": "actions/setup-node@v4"},
            {"working-directory": "e2e", "run": "# npm ci is skipped here\ntrue"},
            {"run": "make test", "env": {NODE_TOOLING_REQUIRED_ENV: "1"}},
        ]
    }
    assert _node_lane_wiring(commented_only) == {"npm-ci-in-e2e"}

    # The flag's VALUE is load-bearing: the fixture reads only the exact
    # string "1" as "required". A one-character edit must be caught.
    for disarmed in ("0", "", "true", "${{ steps.npm.outcome == 'success' }}"):
        wired_but_disarmed = {
            "steps": [
                {"uses": "actions/setup-node@v4"},
                {"working-directory": "e2e", "run": "npm ci"},
                {"run": "make test", "env": {NODE_TOOLING_REQUIRED_ENV: disarmed}},
            ]
        }
        assert _node_lane_wiring(wired_but_disarmed) == {"require-flag-on-make-test"}, (
            f"a require flag of {disarmed!r} disarms the fixture but was accepted"
        )


def _setup_node_versions(workflow: dict[str, Any]) -> set[str]:
    """Every `node-version` pinned by an `actions/setup-node` step, as strings."""
    versions: set[str] = set()
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            if str(step.get("uses") or "").startswith("actions/setup-node@"):
                version = (step.get("with") or {}).get("node-version")
                if version is not None:
                    versions.add(str(version))
    return versions


@pytest.mark.no_node_required
def test_the_two_lanes_pin_the_same_node_version() -> None:
    """The pytest lane and the e2e lane must not disagree about node.

    ADR-0058 says the new setup-node block is "identical to what e2e.yml
    already does, so the two lanes cannot disagree about the node version".
    Those are two independent literals in two files; without this check that
    sentence is a promise, not a property (AGENTS.md rule 1a).

    Turns red if: either file's `node-version` is edited without the other —
    e.g. the pytest lane is dropped to 18 while e2e stays on 22, so the
    checker is exercised on a version the blocking lane never runs.
    """
    both = _setup_node_versions(
        yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))
    ) | _setup_node_versions(yaml.safe_load(E2E_WORKFLOW.read_text(encoding="utf-8")))
    assert both, "neither workflow pins a node-version — the probe is reading the wrong files"
    assert len(both) == 1, f"the two lanes pin different node versions: {sorted(both)}"


@pytest.mark.no_node_required
def test_the_node_version_probe_reports_a_disagreement() -> None:
    """Positive/negative partner for the assertion above (AGENTS.md rule 7).

    `len(both) == 1` is trivially satisfied by a probe that reads nothing, and
    would then pass over any pair of workflows at all.

    Turns red if: `_setup_node_versions` stops finding setup-node steps, or
    stops distinguishing two different versions.
    """
    agreeing = {
        "jobs": {
            "a": {"steps": [{"uses": "actions/setup-node@v4", "with": {"node-version": "22"}}]}
        }
    }
    disagreeing = {
        "jobs": {"b": {"steps": [{"uses": "actions/setup-node@v4", "with": {"node-version": 18}}]}}
    }
    assert _setup_node_versions(agreeing) == {"22"}
    assert _setup_node_versions(disagreeing) == {"18"}
    assert len(_setup_node_versions(agreeing) | _setup_node_versions(disagreeing)) == 2
    assert _setup_node_versions({"jobs": {"c": {"steps": [{"run": "make test"}]}}}) == set()


@pytest.mark.no_node_required
def test_a_hung_node_is_killed_by_a_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wedged `node` must fail this test by name, not the whole CI job.

    Before ADR-0058 these tests never executed in a required lane, so an
    unbounded `subprocess.run` cost nothing. Now they do: a `node` that never
    returns would burn the job to `timeout-minutes: 15`, and GitHub reports
    only "exceeded the maximum execution time" — no test name, no output.

    Drives a stub `node` that sleeps, so it needs no real node install.

    Turns red if: the `timeout=` argument is dropped from `_run`. The SIGALRM
    below is what makes that red rather than a hang — measured: with `timeout=`
    removed and no alarm, this test did not return in 45s (killed, exit 142).

    POSIX only; `signal.alarm` does not exist on Windows, which this repo does
    not target (CI is ubuntu-latest, development is macOS).
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    stub = fake_bin / "node"
    # Absolute path: PATH is emptied below, so a bare `sleep` would not resolve
    # and the stub would exit immediately instead of hanging.
    stub.write_text("#!/bin/sh\nexec /bin/sleep 600\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    monkeypatch.setattr(sys.modules[__name__], "NODE_TIMEOUT_SECONDS", 1)

    def _alarm(_signum: int, _frame: Any) -> None:
        raise AssertionError(
            "_run did not return within 15s against a `node` that never exits — "
            "the `timeout=` argument is missing, so a wedged node would burn the "
            "whole CI job instead of failing this test by name"
        )

    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(15)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            _run(VACUOUS, tmp_path)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.no_node_required
def test_missing_tooling_is_fatal_only_when_the_lane_demands_it() -> None:
    """Absent tooling skips on a laptop and fails in the lane that installed it.

    The `skip` row is the partner that proves this change does not simply make
    every node-less machine red.

    Turns red if: the required branch goes back to `pytest.skip` — the exact
    regression this work exists to prevent — or if a machine without the
    tooling starts failing when nothing asked it to run these tests.
    """
    assert _tooling_verdict(node_present=True, parser_present=True, required=True) == "run"
    assert _tooling_verdict(node_present=True, parser_present=True, required=False) == "run"
    assert _tooling_verdict(node_present=False, parser_present=True, required=True) == "fail"
    assert _tooling_verdict(node_present=True, parser_present=False, required=True) == "fail"
    assert _tooling_verdict(node_present=False, parser_present=True, required=False) == "skip"
    assert _tooling_verdict(node_present=True, parser_present=False, required=False) == "skip"


@pytest.mark.no_node_required
def test_the_docstring_names_only_tests_that_really_are_node_free() -> None:
    """The prose and the markers are compared, in both directions.

    The predecessor of this module's docstring asserted that
    `test_the_guard_is_wired_into_ci` "does not skip"; a CI log showed it
    skipping with every other test in the file. A corrected sentence would
    have lasted until the next edit (AGENTS.md rule 1a), so it is a check.

    Turns red if: the docstring names a test that has lost the marker, or a
    marked test is missing from the docstring's list.
    """
    module = sys.modules[__name__]
    named = set(re.findall(r"`(test_[a-z0-9_]+)`", module.__doc__ or ""))
    assert named, "the module docstring names no node-free test — the parse is wrong"

    marked = {
        name
        for name, obj in vars(module).items()
        if name.startswith("test_")
        and callable(obj)
        and any(mark.name == "no_node_required" for mark in getattr(obj, "pytestmark", []))
    }
    assert marked, "no test carries the no_node_required marker — the walk is wrong"
    assert named == marked, (
        "the docstring and the markers disagree; named-not-marked="
        f"{sorted(named - marked)}, marked-not-named={sorted(marked - named)}"
    )
