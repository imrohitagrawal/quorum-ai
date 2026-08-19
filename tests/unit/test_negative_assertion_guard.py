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

import json
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


# ---------------------------------------------------------------------------
# #226 (second half) — COMPUTED MEMBER ACCESS.
#
# The checker read a member-expression property as `node.property.name` at
# every member-property read in the file — count them with
# `git show origin/main:e2e/tools/check-negative-assertions.mjs |
#  grep -c '\.property\.name'`, rather than trusting a number written here.
# For a COMPUTED property (`expect(x)["not"]`) the AST node is a
# `Literal`, so `.name` is `undefined` and every one of those reads silently
# produced nothing. One root cause, two opposite failure directions: an evasion
# (a vacuous test passes) and a false positive (an honest test is reported).
#
# These tests assert on the STRUCTURED violation list — `{line, matcher, test}`
# objects — not on the human report's prose, because "is this line reported,
# and with which matcher" is the structural fact under test (AGENTS.md rule 8).
# ---------------------------------------------------------------------------

_VIOLATION_DRIVER = """
import {{ readFileSync }} from "node:fs";
import {{ checkSource }} from "{checker}";
const source = readFileSync(process.argv[2], "utf8");
process.stdout.write(JSON.stringify(checkSource(source, "probe.spec.ts")));
"""

_HEADER = 'import { test, expect } from "@playwright/test";\n\n'


def _violations(source: str, tmp_path: Path) -> list[dict[str, Any]]:
    """The checker's own violation objects for `source`, via its exported API.

    Shelling the CLI and reading stderr would assert on prose. This drives
    `checkSource` and returns the objects it actually built.
    """
    spec = tmp_path / "probe.spec.ts"
    spec.write_text(source, encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(_VIOLATION_DRIVER.format(checker=CHECKER.as_uri()), encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(spec)],
        cwd=E2E,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, f"the checker driver failed:\n{result.stdout}\n{result.stderr}"
    parsed: list[dict[str, Any]] = json.loads(result.stdout)
    return parsed


def _matchers(violations: list[dict[str, Any]]) -> list[str]:
    return sorted(v["matcher"] for v in violations)


def _titles(violations: list[dict[str, Any]]) -> set[str]:
    return {v["test"] for v in violations}


def test_a_computed_not_is_not_a_positive_partner(tmp_path: Path) -> None:
    """`expect(x)["not"].toBeVisible()` is a negative, not a liveness proof.

    Measured on the checker as it stood before this change: this source
    reported ZERO violations. The computed `.not` was not seen, so the first
    line classified as a PLAIN `toBeVisible` — a positive partner — and
    silenced the genuine unpartnered negative on the second line.

    Turns red if: `propertyName` loses its string-`Literal` arm, or the `.not`
    walk goes back to reading `cursor.property.name`.
    """
    found = _violations(
        _HEADER + 'test("computed-not", async ({ page }) => {\n'
        '  await expect(page.locator("#a"))["not"].toBeVisible();\n'
        '  await expect(page.locator("#a")).not.toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert _matchers(found) == ["not.toBeVisible", "not.toContainText"], (
        "the computed `.not` was not read as a negation, so a vacuous "
        f"assertion posed as the partner: {found}"
    )

    # POSITIVE PARTNER (rule 7): the same file with a REAL liveness assertion
    # must report nothing, so "two violations" above cannot come from a checker
    # that reports every assertion it sees.
    partnered = _violations(
        _HEADER + 'test("computed-not-partnered", async ({ page }) => {\n'
        '  await expect(page.locator("#a")).toBeVisible();\n'
        '  await expect(page.locator("#a"))["not"].toBeVisible();\n'
        '  await expect(page.locator("#a")).not.toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert partnered == [], f"a genuinely partnered test was reported: {partnered}"


def test_a_parenthesised_optional_chain_is_still_walked(tmp_path: Path) -> None:
    """`await (expect(x)?.not).toBeVisible()` must still reach `expect`.

    Parenthesising an optional member access wraps the chain in a
    `ChainExpression` node, which is neither a `MemberExpression` nor a
    `CallExpression`, so `assertionOf`'s cursor walk falls through to its
    `return null` and the assertion becomes INVISIBLE to the guard — the same
    assertion-invisibility class as the computed matcher this change closes.

    Turns red if: the `ChainExpression` arm is removed from `assertionOf`'s
    cursor walk. Measured before this test existed: mutating that arm to a node
    type that never occurs left the whole module green at 46 passed, so nothing
    held it.
    """
    found = _violations(
        _HEADER + 'test("paren-chain", async ({ page }) => {\n'
        '  await (expect(page.locator("#a"))?.not).toBeVisible();\n'
        '  await expect(page.locator("#a")).not.toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert _matchers(found) == ["not.toBeVisible", "not.toContainText"], (
        "the parenthesised optional chain was not walked back to `expect`, so "
        f"one of the two negatives went unseen: {found}"
    )

    # POSITIVE PARTNER (rule 7): the same two negatives beside a real liveness
    # assertion must report nothing, so the list above cannot come from a
    # checker that simply reports every assertion.
    partnered = _violations(
        _HEADER + 'test("paren-chain-partnered", async ({ page }) => {\n'
        '  await expect(page.locator("#a")).toBeVisible();\n'
        '  await (expect(page.locator("#a"))?.not).toBeVisible();\n'
        '  await expect(page.locator("#a")).not.toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert partnered == [], f"a genuinely partnered test was reported: {partnered}"


def test_a_computed_matcher_is_still_classified(tmp_path: Path) -> None:
    """`expect(b)["toBeHidden"]()` must be seen at all.

    The cleaner evasion of the two: it needs no partner to hide behind, because
    `assertionOf` read the matcher as `undefined` and returned null, so the
    assertion was never classified. Measured before this change: ZERO
    violations for both spellings below.

    Turns red if: `assertionOf` reads the matcher as `node.callee.property.name`
    again, at either the bare-`expect` or the `expect.soft` root.
    """
    plain = _violations(
        _HEADER + 'test("computed-matcher", async ({ page }) => {\n'
        '  await expect(page.locator("#b"))["toBeHidden"]();\n'
        "});\n",
        tmp_path,
    )
    assert _matchers(plain) == ["toBeHidden"], (
        f"a computed absence matcher was invisible to the guard: {plain}"
    )

    soft = _violations(
        _HEADER + 'test("computed-matcher-soft", async ({ page }) => {\n'
        '  await expect.soft(page.locator("#b"))["toBeHidden"]();\n'
        "});\n",
        tmp_path,
    )
    assert _matchers(soft) == ["toBeHidden"], (
        f"a computed absence matcher under expect.soft was invisible: {soft}"
    )

    # POSITIVE PARTNER (rule 7): partner each and the report must empty out.
    for candidate in (
        'await expect(page.locator("#b"))["toBeHidden"]();',
        'await expect.soft(page.locator("#b"))["toBeHidden"]();',
    ):
        partnered = _violations(
            _HEADER + 'test("computed-matcher-partnered", async ({ page }) => {\n'
            '  await expect(page.locator("#a")).toBeVisible();\n'
            f"  {candidate}\n"
            "});\n",
            tmp_path,
        )
        assert partnered == [], f"a partnered computed absence matcher was reported: {partnered}"


def test_a_computed_expect_root_counts_as_a_partner(tmp_path: Path) -> None:
    """The opposite direction: an honest test must NOT be taxed.

    `expect["soft"](b).toBeVisible()` and `expect(b)["toBeVisible"]()` are
    genuine liveness proofs. Measured before this change: each reported ONE
    violation on the real negative beside it, because the computed property hid
    the partner. A guard that invents work for honest authors is how a gate
    gets disabled.

    Turns red if: the `expect.soft`/`expect.poll` root check, or the matcher
    read, stops resolving a computed property.
    """
    for label, partner in (
        ("computed-soft-root", 'await expect["soft"](page.locator("#b")).toBeVisible();'),
        ("computed-matcher-partner", 'await expect(page.locator("#b"))["toBeVisible"]();'),
    ):
        clean = _violations(
            _HEADER + f'test("{label}", async ({{ page }}) => {{\n'
            f"  {partner}\n"
            '  await expect(page.locator("#b")).not.toContainText("gone");\n'
            "});\n",
            tmp_path,
        )
        assert clean == [], (
            "a genuine liveness partner written with computed access was not "
            f"recognised, so an honest test was reported: {clean}"
        )

        # MANDATORY PARTNER: drop the liveness line and the SAME file must be
        # reported. Without this, "zero violations" would also be produced by a
        # checker that reports nothing, and this test would be an inverted gate
        # that goes red once the defect is fixed.
        stripped = _violations(
            _HEADER + f'test("{label}-unpartnered", async ({{ page }}) => {{\n'
            '  await expect(page.locator("#b")).not.toContainText("gone");\n'
            "});\n",
            tmp_path,
        )
        assert _matchers(stripped) == ["not.toContainText"], (
            "the control case is not reported, so the clean result above proves "
            f"nothing: {stripped}"
        )


def test_a_computed_test_modifier_still_opens_a_test(tmp_path: Path) -> None:
    """`test["only"](...)` hides EVERY assertion in its body, not just one.

    `isTestCall` read `node.callee.property.name`, so a computed modifier made
    the whole test body invisible to the walk. Measured before this change:
    ZERO violations. That is a strictly larger evasion than a single computed
    matcher.

    Turns red if: `isTestCall` stops resolving a computed property.
    """
    found = _violations(
        _HEADER + 'test["only"]("computed-modifier", async ({ page }) => {\n'
        '  await expect(page.locator("#b")).toBeHidden();\n'
        "});\n",
        tmp_path,
    )
    assert _matchers(found) == ["toBeHidden"], (
        f"the body of a computed-modifier test was never walked: {found}"
    )
    assert _titles(found) == {"computed-modifier"}, (
        f"the violation is not attributed to the test it sits in: {found}"
    )

    # POSITIVE PARTNER (rule 7): partner it and the same shape reports nothing.
    partnered = _violations(
        _HEADER + 'test["only"]("computed-modifier-partnered", async ({ page }) => {\n'
        '  await expect(page.locator("#a")).toBeVisible();\n'
        '  await expect(page.locator("#b")).toBeHidden();\n'
        "});\n",
        tmp_path,
    )
    assert partnered == [], f"a partnered computed-modifier test was reported: {partnered}"


def test_a_computed_describe_still_associates_its_before_each(tmp_path: Path) -> None:
    """False-positive direction, same root cause, at the describe recogniser.

    `test["describe"](...)` was not recognised, so `collectBeforeEachAssertions`
    never ran and the `beforeEach` partner never reached the tests inside.
    Measured before this change: ONE violation on an honestly-partnered test.

    Turns red if: `isDescribeCall` or `isBeforeEachCall` stops resolving a
    computed property.
    """
    partnered = (
        _HEADER + 'test["describe"]("grp", () => {\n'
        '  test["beforeEach"](async ({ page }) => {\n'
        '    await expect(page.locator("#root")).toBeVisible();\n'
        "  });\n"
        '  test("inner", async ({ page }) => {\n'
        '    await expect(page.locator("#b")).toBeHidden();\n'
        "  });\n"
        "});\n"
    )
    assert _violations(partnered, tmp_path) == [], (
        "a beforeEach partner inside a computed-property describe was lost, so "
        "an honest test was reported"
    )

    # MANDATORY PARTNER: remove the beforeEach assertion and the identical
    # shape must be reported, so the clean result above is not vacuous.
    unpartnered = (
        _HEADER + 'test["describe"]("grp", () => {\n'
        '  test["beforeEach"](async ({ page }) => {\n'
        '    await page.goto("/");\n'
        "  });\n"
        '  test("inner", async ({ page }) => {\n'
        '    await expect(page.locator("#b")).toBeHidden();\n'
        "  });\n"
        "});\n"
    )
    assert _matchers(_violations(unpartnered, tmp_path)) == ["toBeHidden"], (
        "the control case is not reported, so the clean result above proves "
        "nothing about the beforeEach association"
    )


def test_an_interpolation_free_template_property_is_resolved(tmp_path: Path) -> None:
    """A template literal with no interpolation is static text and must resolve.

    ``expect(x)[`not`].toBeVisible()`` is exactly as readable at parse time as
    `expect(x).not.toBeVisible()`. Measured before this change: ZERO violations.
    It must NOT fall into the undecidable bucket, or the guard would report
    `<computed>` for a shape it can read perfectly well.

    Turns red if: `propertyName` drops its zero-interpolation `TemplateLiteral`
    arm.
    """
    found = _violations(
        _HEADER + 'test("template-not", async ({ page }) => {\n'
        '  await expect(page.locator("#a"))[`not`].toBeVisible();\n'
        '  await expect(page.locator("#a")).not.toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert _matchers(found) == ["not.toBeVisible", "not.toContainText"], (
        f"an interpolation-free template property was not resolved: {found}"
    )


def test_an_unresolvable_computed_property_fails_closed(tmp_path: Path) -> None:
    """A property the parser cannot read makes the assertion demand a partner.

    `const k = "not"; expect(x)[k].toContainText(...)` needs dataflow analysis
    this checker does not have and should not grow. ADR-0047 settled the
    direction for this class of detector: resolve an ambiguous case toward a
    RED gate. So such an assertion is classified NEGATIVE (it needs a partner)
    and never counts AS one — both halves lean red.

    Measured before this change: ZERO violations, i.e. it failed OPEN.

    All three directions are asserted here on purpose. Without the second, a
    future "simplification" back to fail-open would be invisible; without the
    first, the test would pass against a checker that reports everything.

    Turns red if: `classify` stops returning "negative" for an unresolved
    assertion, or the fail-closed rule is inverted so an unresolved shape
    counts as a partner.
    """
    unpartnered = _violations(
        _HEADER + 'test("undecidable", async ({ page }) => {\n'
        '  const k = "not";\n'
        '  await expect(page.locator("#a"))[k].toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert len(unpartnered) == 1, (
        f"an unreadable assertion shape did not demand a partner: {unpartnered}"
    )
    assert unpartnered[0]["matcher"] == "<computed>", (
        "the report must name the shape it could not read, or the author "
        f"cannot act on it: {unpartnered}"
    )

    # The cost of failing closed, measured rather than argued: it only bites
    # when the surrounding test has NO positive partner at all.
    partnered = _violations(
        _HEADER + 'test("undecidable-partnered", async ({ page }) => {\n'
        '  const k = "not";\n'
        '  await expect(page.locator("#a")).toBeVisible();\n'
        '  await expect(page.locator("#a"))[k].toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert partnered == [], (
        f"fail-closed must not tax a test that carries a real partner: {partnered}"
    )

    # ...and an unresolvable shape must never SUPPLY the partner.
    posing = _violations(
        _HEADER + 'test("undecidable-posing-as-partner", async ({ page }) => {\n'
        '  const k = "toBeVisible";\n'
        '  await expect(page.locator("#a"))[k]();\n'
        '  await expect(page.locator("#a")).not.toContainText("gone");\n'
        "});\n",
        tmp_path,
    )
    assert _matchers(posing) == ["<computed>", "not.toContainText"], (
        f"an unreadable assertion was accepted as a positive partner: {posing}"
    )


# ---------------------------------------------------------------------------
# #226 — THE ACCEPTANCE PREDICATE. Salvaged from the parked `fix/226-guard-
# classifier` branch, which measured it and then never merged.
#
# THE PROPERTY: an argument shape counts as a positive partner only if
# satisfying it REQUIRES the subject to carry something; and a subject counts
# only if it can reach live application state at all. Both are asserted over an
# enumerated shape space, in BOTH directions, rather than one case per
# discovered evasion.
#
# The runtime verdicts quoted in the comments below were measured in real
# Chromium ON THAT BRANCH and are INHERITED here, not re-measured. What IS
# re-measured on every run is the upstream fact the blank-character rule copies
# — see `test_the_blank_character_rule_is_playwrights_own_normalizer`.
# ---------------------------------------------------------------------------

PLAYWRIGHT_CORE_BUNDLE = E2E / "node_modules" / "playwright-core" / "lib" / "coreBundle.js"


def _require_playwright_core() -> None:
    """Absent playwright-core FAILS in the required lane, and skips elsewhere.

    A bare skip here would re-open exactly the silent-green hole ADR-0058
    closed: the `pytest (Python 3.12)` lane runs `npm ci` in `e2e/` and sets
    `QUORUM_REQUIRE_E2E_NODE_TOOLING=1`, so there an absent package can only
    mean something is broken.
    """
    if PLAYWRIGHT_CORE_BUNDLE.is_file():
        return
    reason = f"playwright-core is not installed — run `npm ci` in e2e/ ({PLAYWRIGHT_CORE_BUNDLE})"
    if os.environ.get(NODE_TOOLING_REQUIRED_ENV) == "1":
        pytest.fail(f"{NODE_TOOLING_REQUIRED_ENV}=1 but {reason}")
    pytest.skip(reason)


def _codepoints_of_strip_class(pattern_body: str) -> frozenset[str]:
    """`\\u200b\\u00ad` (any case) -> {"00ad", "200b"}."""
    return frozenset(m.lower() for m in re.findall(r"\\u([0-9a-fA-F]{4})", pattern_body))


def _guard_strip_class() -> frozenset[str]:
    """The guard's exported `PLAYWRIGHT_STRIPS`, read by RUNNING it.

    Reading the `.mjs` as text would match the header comment that explains the
    rule as well as the rule itself (AGENTS.md rule 8), and `tests/code_text.py`
    blanks `#` comments only, so it cannot help on JavaScript.
    """
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            f'import {{ PLAYWRIGHT_STRIPS }} from "{CHECKER.as_uri()}";'
            "process.stdout.write(PLAYWRIGHT_STRIPS.source);",
        ],
        cwd=E2E,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, (
        f"the guard does not export PLAYWRIGHT_STRIPS:\n{result.stdout}\n{result.stderr}"
    )
    return _codepoints_of_strip_class(result.stdout)


def test_the_blank_character_rule_is_playwrights_own_normalizer() -> None:
    """The guard's "which characters are blank" rule is an UPSTREAM fact.

    AGENTS.md rule 8c: a mitigation gated on an upstream's behaviour is worth
    exactly as much as your measurement of that upstream. An earlier attempt
    reasoned from Unicode instead and produced `[\\u200B-\\u200D\\uFEFF]`, which
    accepted U+00AD SOFT HYPHEN as proof that an element carries content.

    Playwright strips exactly two characters before comparing text:

        text.replace(/[\\u200b\\u00ad]/g, "").trim().replace(/\\s+/g, " ")

    This re-reads that expression out of the INSTALLED playwright-core on every
    run, so an upstream change surfaces as a named failure here rather than as
    a silently wrong predicate.

    Turns red if: the guard's exported strip class is edited away from
    Playwright's, or Playwright changes its own.
    """
    _require_playwright_core()

    upstream = re.findall(
        r'replace\(/\[((?:\\u[0-9a-fA-F]{4})+)\]/g, ""\)',
        PLAYWRIGHT_CORE_BUNDLE.read_text(encoding="utf-8"),
    )
    # FLOOR: a regex that matched nothing would make every assertion below
    # trivially true. The strip call must actually have been found.
    assert upstream, (
        f'no `replace(/[...]/g, "")` strip class found in {PLAYWRIGHT_CORE_BUNDLE} — '
        "this test measured NOTHING and cannot report the guard as correct"
    )
    upstream_sets = {_codepoints_of_strip_class(body) for body in upstream}
    assert len(upstream_sets) == 1, (
        f"playwright-core spells its strip class more than one way: {upstream_sets}"
    )
    upstream_set = upstream_sets.pop()
    assert upstream_set == {"200b", "00ad"}, (
        "playwright-core changed the characters it strips before comparing text, "
        f"from {{200b, 00ad}} to {sorted(upstream_set)}. The guard's blank-character "
        "rule is a copy of that expression and is now wrong; re-measure in a real "
        "browser and update both."
    )
    assert _guard_strip_class() == upstream_set, (
        "the guard's blank-character class has drifted from Playwright's own: "
        f"guard {sorted(_guard_strip_class())} vs playwright-core {sorted(upstream_set)}"
    )


SUBJ = 'page.locator("#a")'
FIXED_NEGATIVE = 'await expect(page.locator("#missing")).toBeHidden();'

#: label -> the ONE candidate assertion under test, plus whether the guard must
#: treat it as a positive partner. True means the guard must let the test
#: through; False means it must still report the fixed negative beside it
#: because the candidate proved nothing.
PARTNER_SHAPES: dict[str, tuple[str, bool]] = {
    # -- plain toHaveText: strings -------------------------------------------
    "plain-toHaveText-word": (f'await expect({SUBJ}).toHaveText("hello");', True),
    "plain-toHaveText-empty": (f'await expect({SUBJ}).toHaveText("");', False),
    # Playwright normalises whitespace, so a blank string is satisfied by an
    # element holding nothing.
    "plain-toHaveText-spaces": (f'await expect({SUBJ}).toHaveText("   ");', False),
    "plain-toHaveText-nbsp": (f'await expect({SUBJ}).toHaveText("\\u00a0");', False),
    "plain-toHaveText-zwsp": (f'await expect({SUBJ}).toHaveText("\\u200b");', False),
    "plain-toHaveText-tab-newline": (f'await expect({SUBJ}).toHaveText("\\t\\n");', False),
    # -- plain toHaveText: the blank-character boundary ----------------------
    # NOT reasoned about: Playwright strips exactly U+200B and U+00AD and then
    # trims/collapses JavaScript `\s`. U+00AD is the one a hand-derived
    # zero-width set got wrong, accepting it as proof of content.
    "plain-toHaveText-soft-hyphen": (f'await expect({SUBJ}).toHaveText("\\u00ad");', False),
    "plain-toHaveText-ideographic-space": (
        f'await expect({SUBJ}).toHaveText("\\u3000");',
        False,
    ),
    "plain-toHaveText-bom": (f'await expect({SUBJ}).toHaveText("\\ufeff");', False),
    "plain-toHaveText-line-separator": (f'await expect({SUBJ}).toHaveText("\\u2028");', False),
    # ...and the other side of the same boundary: neither stripped nor `\s`,
    # so both are genuine content. The hand-derived set rejected both.
    "plain-toHaveText-zwnj": (f'await expect({SUBJ}).toHaveText("\\u200c");', True),
    "plain-toHaveText-word-joiner": (f'await expect({SUBJ}).toHaveText("\\u2060");', True),
    # -- plain toHaveText: template literals ---------------------------------
    "plain-toHaveText-tpl-word": (f"await expect({SUBJ}).toHaveText(`x`);", True),
    "plain-toHaveText-tpl-empty": (f"await expect({SUBJ}).toHaveText(``);", False),
    "plain-toHaveText-tpl-blank": (f"await expect({SUBJ}).toHaveText(`   `);", False),
    # `${v}` contributes NO text knowable at parse time.
    "plain-toHaveText-tpl-interp-only": (f"await expect({SUBJ}).toHaveText(`${{v}}`);", False),
    # ...but a non-blank static part is present whatever `v` turns out to be.
    "plain-toHaveText-tpl-interp-prefixed": (
        f"await expect({SUBJ}).toHaveText(`ok ${{v}}`);",
        True,
    ),
    "plain-toHaveText-tpl-interp-blank-prefix": (
        f"await expect({SUBJ}).toHaveText(` ${{v}} `);",
        False,
    ),
    # -- plain toHaveText: regexes -------------------------------------------
    "plain-toHaveText-regex-word": (f"await expect({SUBJ}).toHaveText(/x/);", True),
    "plain-toHaveText-regex-plus": (f"await expect({SUBJ}).toHaveText(/.+/);", True),
    # Every one of these matches the empty string, so an empty element satisfies it.
    "plain-toHaveText-regex-empty": (f"await expect({SUBJ}).toHaveText(/(?:)/);", False),
    "plain-toHaveText-regex-anchored-empty": (f"await expect({SUBJ}).toHaveText(/^$/);", False),
    "plain-toHaveText-regex-optional": (f"await expect({SUBJ}).toHaveText(/a?/);", False),
    "plain-toHaveText-regex-star": (f"await expect({SUBJ}).toHaveText(/x*/);", False),
    "plain-toHaveText-regex-alt-empty": (f"await expect({SUBJ}).toHaveText(/x|/);", False),
    # -- plain toHaveText: arrays and everything else ------------------------
    "plain-toHaveText-array-empty": (f"await expect({SUBJ}).toHaveText([]);", False),
    "plain-toHaveText-array-word": (f'await expect({SUBJ}).toHaveText(["a"]);', False),
    "plain-toHaveText-number": (f"await expect({SUBJ}).toHaveText(1);", False),
    "plain-toHaveText-object": (f"await expect({SUBJ}).toHaveText({{}});", False),
    "plain-toHaveText-identifier": (f"await expect({SUBJ}).toHaveText(someVar);", False),
    "plain-toHaveText-call": (f"await expect({SUBJ}).toHaveText(makeText());", False),
    "plain-toHaveText-new-regexp": (f'await expect({SUBJ}).toHaveText(new RegExp("x"));', False),
    "plain-toHaveText-null": (f"await expect({SUBJ}).toHaveText(null);", False),
    "plain-toHaveText-no-args": (f"await expect({SUBJ}).toHaveText();", False),
    # -- plain toContainText / toContain -------------------------------------
    "plain-toContainText-word": (f'await expect({SUBJ}).toContainText("hello");', True),
    "plain-toContainText-empty": (f'await expect({SUBJ}).toContainText("");', False),
    "plain-toContainText-blank": (f'await expect({SUBJ}).toContainText("   ");', False),
    "plain-toContainText-regex-empty": (f"await expect({SUBJ}).toContainText(/(?:)/);", False),
    "plain-toContainText-array-word": (f'await expect({SUBJ}).toContainText(["a"]);', False),
    "plain-toContain-word": ('await expect(names).toContain("hello");', True),
    "plain-toContain-empty": ('await expect(names).toContain("");', False),
    # -- plain numeric / presence matchers ------------------------------------
    "plain-toHaveCount-1": (f"await expect({SUBJ}).toHaveCount(1);", True),
    "plain-toHaveCount-0": (f"await expect({SUBJ}).toHaveCount(0);", False),
    "plain-toHaveLength-3": ("await expect(items).toHaveLength(3);", True),
    "plain-toHaveLength-0": ("await expect(items).toHaveLength(0);", False),
    "plain-toBeGreaterThan-0": ("await expect(n).toBeGreaterThan(0);", True),
    "plain-toBeGreaterThanOrEqual-1": ("await expect(n).toBeGreaterThanOrEqual(1);", True),
    "plain-toBeGreaterThanOrEqual-0": ("await expect(n).toBeGreaterThanOrEqual(0);", False),
    "plain-toBeVisible": (f"await expect({SUBJ}).toBeVisible();", True),
    "plain-toBeAttached": (f"await expect({SUBJ}).toBeAttached();", True),
    "plain-toBeEnabled": (f"await expect({SUBJ}).toBeEnabled();", False),
    "plain-toBeHidden": (f"await expect({SUBJ}).toBeHidden();", False),
    "plain-toBeEmpty": (f"await expect({SUBJ}).toBeEmpty();", False),
    "plain-toBeNull": ("await expect(v).toBeNull();", False),
    "plain-toEqual-empty-array": ("await expect(v).toEqual([]);", False),
    "plain-toEqual-empty-string": ('await expect(v).toEqual("");', False),
    # -- tautological subjects, plain direction --------------------------------
    "taut-plain-string-toBeVisible": ('await expect("lit").toBeVisible();', False),
    "taut-plain-template-toHaveText": ('await expect(`lit`).toHaveText("x");', False),
    "taut-plain-array-toBeTruthy": ("await expect([1]).toBeTruthy();", False),
    "taut-plain-object-toBeTruthy": ("await expect({ a: 1 }).toBeTruthy();", False),
    # A blocklist of dead node types is defeated by four characters. These are
    # the same dead literal wearing a TypeScript wrapper, and the shipped
    # comment claimed to close exactly the first one.
    "taut-plain-as-string-toBeTruthy": ('await expect("lit" as string).toBeTruthy();', False),
    "taut-plain-nonnull-literal-toBeTruthy": ('await expect("lit"!).toBeTruthy();', False),
    # Reached FROM a literal, so still nothing about the code under test.
    "taut-plain-member-of-literal": ('await expect("lit".length).toBeGreaterThan(0);', False),
    "taut-plain-call-on-literal": ('await expect("lit".split("")).toHaveLength(3);', False),
    # THE DEFAULT-DENY PROOF. Neither node type here is named anywhere in
    # `isLiveSubject`; each must be rejected BECAUSE it is unrecognised.
    #
    # MEASURED, and NOT what an earlier draft of this comment claimed: DELETING
    # the `default: return false` arm changes nothing at all — control falls out
    # of the `switch` and the function returns `undefined`, which is falsy, so
    # the suite stays fully green (46 passed). That arm is documentation of a
    # fall-through that is already safe. The mutation that BITES is flipping it
    # to `default: return true`, which gives 2 failed: this test and
    # `test_a_tautological_partner_does_not_count`.
    "subject-unenumerated-sequence": ("await expect((0, flag)).toBeTruthy();", False),
    "subject-unenumerated-conditional": ("await expect(a ? b : c).toBeTruthy();", False),
    # `NewExpression` IS enumerated, and argument-driven: live only if some
    # argument can reach live state. Both directions are pinned, because an
    # arm that returned a bare `true` would accept `new Date()` and an arm
    # deleted entirely would reject `new Set(live)`.
    "subject-dead-new-expression-no-args": ("await expect(new Date()).toBeTruthy();", False),
    "subject-dead-new-expression-literal-arg": (
        'await expect(new Set(["a"]).size).toBeGreaterThan(0);',
        False,
    ),
    "subject-live-new-expression-live-arg": (
        "await expect(new Set(backgrounds).size).toBeGreaterThan(0);",
        True,
    ),
    # ...and the positive partner for that arm: default-deny must not become
    # "deny everything". Each of these IS a live subject and must still count.
    "subject-live-as-expression": (f"await expect({SUBJ} as Locator).toBeVisible();", True),
    "subject-live-optional-chain": ('await expect(page?.locator("#a")).toBeVisible();', True),
    "subject-live-logical": ("await expect(first || second).toBeTruthy();", True),
    "subject-live-binary": ("await expect(items.length + 1).toBeGreaterThan(0);", True),
    "subject-live-awaited-call": ('await expect(await page.title()).toContain("Q");', True),
    # -- the .not direction ----------------------------------------------------
    "not-toHaveText-word": (f'await expect({SUBJ}).not.toHaveText("—");', True),
    "not-toHaveText-regex-word": (f"await expect({SUBJ}).not.toHaveText(/x/);", True),
    "not-toHaveText-tpl-word": (f"await expect({SUBJ}).not.toHaveText(`x`);", True),
    "not-toHaveText-empty": (f'await expect({SUBJ}).not.toHaveText("");', False),
    "not-toHaveText-blank": (f'await expect({SUBJ}).not.toHaveText("   ");', False),
    "not-toHaveText-tpl-empty": (f"await expect({SUBJ}).not.toHaveText(``);", False),
    "not-toHaveText-tpl-interp-only": (f"await expect({SUBJ}).not.toHaveText(`${{v}}`);", False),
    "not-toHaveText-regex-empty": (f"await expect({SUBJ}).not.toHaveText(/(?:)/);", False),
    # `regexRejectsEmptyString` asks the ENGINE, so a pattern the TypeScript
    # parser accepts but `new RegExp` rejects lands in its `catch`. That arm
    # fails CLOSED — unevaluable is not proof. Pinned in both directions:
    # flip the `catch` to `return true` and the first row turns accepted,
    # delete the whole predicate and the second row turns rejected.
    "not-toHaveText-regex-uncompilable": (
        f"await expect({SUBJ}).not.toHaveText(/(?<x>a)(?<x>b)/);",
        False,
    ),
    "not-toHaveText-regex-compilable-nonempty": (
        f"await expect({SUBJ}).not.toHaveText(/ab/);",
        True,
    ),
    # THE FATAL CLASS. `.not.toHaveText(["a"])` PASSES against a locator
    # matching zero elements, so it is vacuous. A rejected earlier `.some()`
    # widening accepted all of these.
    "not-toHaveText-array-word": (f'await expect({SUBJ}).not.toHaveText(["a"]);', False),
    "not-toHaveText-array-nested": (f'await expect({SUBJ}).not.toHaveText([[], "a"]);', False),
    "not-toHaveText-array-tpl": (f"await expect({SUBJ}).not.toHaveText([`x`]);", False),
    "not-toHaveText-array-empty": (f"await expect({SUBJ}).not.toHaveText([]);", False),
    "not-toHaveText-identifier": (f"await expect({SUBJ}).not.toHaveText(someVar);", False),
    "not-toHaveCount-0": (f"await expect({SUBJ}).not.toHaveCount(0);", True),
    "not-toHaveCount-1": (f"await expect({SUBJ}).not.toHaveCount(1);", False),
    "not-toBeNull": ("await expect(v).not.toBeNull();", True),
    "not-toBeVisible": (f"await expect({SUBJ}).not.toBeVisible();", False),
    "not-toBeEmpty": (f"await expect({SUBJ}).not.toBeEmpty();", False),
    "not-toHaveClass-regex": (f"await expect({SUBJ}).not.toHaveClass(/x/);", False),
    "not-toContainText-word": (f'await expect({SUBJ}).not.toContainText("x");', False),
    "not-toBeInViewport": (f"await expect({SUBJ}).not.toBeInViewport();", False),
    # -- tautological subjects, .not direction ---------------------------------
    "taut-not-string-toHaveText": ('await expect("lit").not.toHaveText("x");', False),
    "taut-not-string-toBeNull": ('await expect("lit").not.toBeNull();', False),
    "taut-not-array-toHaveCount-0": ("await expect([1]).not.toHaveCount(0);", False),
    "taut-not-as-string-toHaveText": (
        'await expect("lit" as string).not.toHaveText("x");',
        False,
    ),
    "taut-not-member-of-literal-toBeNull": ('await expect("lit".length).not.toBeNull();', False),
    "subject-not-unenumerated-new-expression": (
        "await expect(new Date()).not.toBeNull();",
        False,
    ),
}


def _spec_from_shapes(shapes: dict[str, tuple[str, bool]]) -> str:
    """One `test()` per shape: the candidate partner plus one fixed negative.

    If the guard reports the test, the candidate was NOT accepted as a partner.
    """
    parts = [_HEADER.rstrip("\n")]
    for label, (candidate, _) in shapes.items():
        parts += [
            "",
            f'test("{label}", async ({{ page }}) => {{',
            f"  {candidate}",
            f"  {FIXED_NEGATIVE}",
            "});",
        ]
    return "\n".join(parts) + "\n"


def test_no_vacuous_argument_shape_is_accepted_as_a_positive_partner(tmp_path: Path) -> None:
    """#226: the acceptance predicate, asserted over the whole shape space.

    Every argument spelling the matchers this predicate governs can take —
    string, blank string, non-breaking and zero-width space, template literal
    with and without interpolation, empty-matching and non-empty-matching
    regex, array, number, object, identifier, call, `new RegExp`, `null`, and
    no argument at all — plus every subject shape, is driven through the guard
    in BOTH directions. The reported set must equal the reject set EXACTLY.

    Both directions are asserted in one place on purpose. A predicate that
    accepts everything makes the reported set too small; one that accepts
    nothing makes it too large. Neither degenerate implementation survives.

    Turns red if: `provesNonEmptyContent` reverts to the old
    "any template literal, any regex, any non-empty string" predicate (the
    `soft-hyphen`, `tpl-empty` and `regex-empty` rows), or `isLiveSubject`
    loses its `default: return false` arm (the `subject-unenumerated-*` rows)
    or an accept arm (the `subject-live-*` rows).
    """
    found = _violations(_spec_from_shapes(PARTNER_SHAPES), tmp_path)
    reported = _titles(found)
    expected_rejects = {label for label, (_, accept) in PARTNER_SHAPES.items() if not accept}
    expected_accepts = set(PARTNER_SHAPES) - expected_rejects

    # FLOORS: neither half of the table may be empty, or the equality below is
    # trivially satisfiable by a guard that reports everything or nothing.
    assert expected_rejects, "the reject half of the shape table is empty"
    assert expected_accepts, "the accept half of the shape table is empty"

    wrongly_accepted = sorted(expected_rejects - reported)
    wrongly_rejected = sorted(reported - expected_rejects)
    assert not wrongly_accepted, (
        "these shapes prove nothing about the subject yet were accepted as a "
        f"positive partner: {wrongly_accepted}"
    )
    assert not wrongly_rejected, (
        f"these shapes are genuine liveness proofs yet were rejected: {wrongly_rejected}"
    )


# ---------------------------------------------------------------------------
# THE STANDING CORPUS SWEEP.
#
# Everything above runs on synthetic fixtures. Nothing ran the classifier over
# the specs the repository actually ships, so a change that made the predicate
# stricter would flag real specs and no required gate would notice: the e2e
# workflow runs this guard in `--base` (changed-specs) mode, gated on
# `github.event_name == 'pull_request'`, so a pull request that edits only the
# CHECKER checks zero spec files. Measured on this pull request's own CI run:
# the guard step printed "no changed spec files vs origin/main — nothing to
# check" and exited 0.
#
# This test closes that gap in the required `pytest (Python 3.12)` lane. It is
# offline and needs only the node tooling that lane already installs.
# ---------------------------------------------------------------------------

_CORPUS_DRIVER = """
import {{ readFileSync }} from "node:fs";
import {{ checkSource }} from "{checker}";
const files = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = [];
for (const file of files) out.push(...checkSource(readFileSync(file, "utf8"), file));
process.stdout.write(JSON.stringify(out));
"""


def _tracked_specs() -> list[str]:
    """Every spec file git tracks under `e2e/`.

    TRACKED-ONLY, deliberately: `git ls-files` cannot see the gitignored scratch
    specs under `e2e/tests/review/`, exactly as the checker's own `--all` mode
    cannot. Read every number derived from this list as tracked-only.
    """
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "e2e/**/*.spec.ts"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in listed.stdout.splitlines() if line.strip()]


def _sweep(files: list[str], tmp_path: Path) -> list[dict[str, Any]]:
    manifest = tmp_path / "files.json"
    manifest.write_text(
        json.dumps([str(REPO_ROOT / f) if not Path(f).is_absolute() else f for f in files]),
        encoding="utf-8",
    )
    driver = tmp_path / "corpus_driver.mjs"
    driver.write_text(_CORPUS_DRIVER.format(checker=CHECKER.as_uri()), encoding="utf-8")
    result = subprocess.run(
        ["node", str(driver), str(manifest)],
        cwd=E2E,
        capture_output=True,
        text=True,
        timeout=NODE_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, f"the corpus driver failed:\n{result.stdout}\n{result.stderr}"
    swept: list[dict[str, Any]] = json.loads(result.stdout)
    return swept


def test_no_tracked_spec_is_reported_by_the_classifier(tmp_path: Path) -> None:
    """Every spec this repository ships must still pass its own guard.

    The false-positive direction has no other standing check. A predicate that
    grew stricter would be caught here on the change that made it strict,
    rather than months later when somebody happened to edit an affected spec.

    Turns red if: a subject or argument shape a committed spec genuinely uses
    stops being accepted as a positive partner. Measured — `isLiveSubject` with
    its `MemberExpression` arm changed to `return false` reports 75 assertions
    across 17 tracked specs.

    NOT red on every stricter change, and the limit is worth stating: dropping
    the `NewExpression` arm demotes
    `e2e/tests/ui-parity/parity-behavior.spec.ts:1412` from partner to
    non-partner and this test stays GREEN, because that test carries two other
    partners. A classification change only surfaces here once it removes a
    test's LAST partner. This sweep is a floor under the false-positive
    direction, not a proof that classification is unchanged.
    """
    specs = _tracked_specs()
    # FLOOR: a sweep over nothing reports nothing. The repository has held far
    # more than this for months; the bound is a floor, not the real count, so
    # adding or removing a spec does not touch this test.
    assert len(specs) >= 20, f"the tracked-spec sweep found almost nothing to check: {specs}"

    reported = _sweep(specs, tmp_path)
    assert reported == [], (
        "the classifier reports a spec this repository ships. Either the spec is "
        "genuinely vacuous and needs a partner, or the classifier regressed in "
        f"the false-positive direction: {reported}"
    )


def test_the_corpus_sweep_reports_a_vacuous_spec(tmp_path: Path) -> None:
    """The positive partner for the sweep above (AGENTS.md rule 7).

    `reported == []` is trivially true for a sweep that parses nothing, opens
    no file, or classifies every assertion as `other`. This drives the SAME
    machinery over a real tracked spec with one vacuous test appended, and the
    appended test must come back.

    Turns red if: `_sweep` stops reading the files it is handed, or the
    classifier stops recognising `toBeHidden` as a negative.
    """
    specs = _tracked_specs()
    assert specs, "no tracked specs to build the positive partner from"

    real = (REPO_ROOT / specs[0]).read_text(encoding="utf-8")
    poisoned = tmp_path / "poisoned.spec.ts"
    poisoned.write_text(
        real + '\ntest("sweep-floor-probe", async ({ page }) => {\n'
        '  await expect(page.locator("#definitely-gone")).toBeHidden();\n'
        "});\n",
        encoding="utf-8",
    )

    reported = _sweep([str(poisoned)], tmp_path)
    assert [v["test"] for v in reported] == ["sweep-floor-probe"], (
        "the sweep machinery did not report an unmistakably vacuous test, so a "
        f"clean sweep proves nothing: {reported}"
    )
