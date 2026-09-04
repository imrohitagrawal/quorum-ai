import { test, expect } from "@playwright/test";

/**
 * Issue #222 + the CTA occlusion bug: the landing call-to-action must be
 * REACHABLE on a phone.
 *
 * WHY A HIT TEST AND NOT `toBeInViewport` / `toHaveScreenshot`.
 * Both are structurally blind to paint order. MEASURED on this branch before
 * the fix: with the density rules applied but the trail-panel hide removed,
 * `#landing-run` sits at y=616-660 — inside a 664px fold, so `toBeInViewport`
 * PASSES — while `document.elementFromPoint` over its centre returns
 * `div.session-trail-head`, because `.session-trail-panel` is
 * `position: fixed; bottom: 0; z-index: 100` at this width and covers
 * y=610-664. A real click does nothing. A viewport assertion would have
 * called that a success. This asserts who actually receives the click.
 *
 * WHY NOT A FOLD ASSERTION. PR #238 proposed one and it is not robust.
 * MEASURED with readiness stubbed `live` (the production condition — prod
 * reports `state: live`, so no banner): the CTA clears the 664px fold by
 * exactly **4px** at 390x664, and MISSES it by +37 at 375x667 and +64 at
 * 360x640. A gate with 4px of slack that already fails at two common phone
 * sizes is a flake waiting to happen, so the fold is measured in the
 * `landing density` test below and reported, never gated.
 */

const PHONE = { width: 390, height: 664 };

/** The production readiness condition: live, so no banner. */
async function stubReadinessLive(page: import("@playwright/test").Page) {
  await page.route("**/ready", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ready",
        environment: "test",
        live_readiness: {
          state: "live",
          reasons: [],
          catalog_drift_ids: [],
          checked_at_utc: new Date(0).toISOString(),
        },
      }),
    }),
  );
}

test.describe("landing CTA is reachable on a phone (#222)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "geometry gate is chromium-only");

  for (const size of [
    { width: 390, height: 664 },
    { width: 375, height: 667 },
    { width: 360, height: 640 },
  ]) {
    test(`a click on the CTA reaches the CTA @ ${size.width}x${size.height}`, async ({ page }) => {
      await stubReadinessLive(page);
      await page.setViewportSize(size);
      await page.goto("/ui");
      await expect(page.locator("#landing-run")).toBeAttached();

      const cta = page.locator("#landing-run");
      await cta.scrollIntoViewIfNeeded();

      const hit = await page.evaluate(() => {
        const el = document.querySelector("#landing-run") as HTMLElement;
        const r = el.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return {
          reaches: Boolean(top && (top === el || el.contains(top))),
          actual: top ? `${top.tagName.toLowerCase()}${top.id ? "#" + top.id : ""}` : "null",
        };
      });

      // RED IF: `[data-active-view="landing"] .session-trail-panel { display: none }`
      // is removed from app.css — `actual` becomes `div.session-trail-head`.
      //
      // MEASURED, and stated because it is a limit of this assertion rather
      // than a property of the fix: removing that rule reddens this test at
      // **390x664 and 375x667 only**. At 360x640 it stays GREEN, because the
      // CTA is 64px below the fold there, so `scrollIntoViewIfNeeded` scrolls
      // it clear of the bottom-pinned panel and it really is reachable — for a
      // different reason than the fix. The 360x640 case therefore proves
      // reachability but does NOT exercise the occlusion. The assertion that
      // bites at every viewport is the `display` check in the next test; this
      // loop is the user-facing property, that one is the mechanism.
      expect(hit.actual).not.toBe("null");
      expect(hit, `a click at the CTA centre landed on ${hit.actual}`).toMatchObject({
        reaches: true,
      });
    });
  }

  test("the trail panel is hidden on landing and SHOWN in the workspace", async ({ page }) => {
    await stubReadinessLive(page);
    await page.setViewportSize(PHONE);
    await page.goto("/ui");
    await expect(page.locator("#landing-run")).toBeAttached();

    const onLanding = await page.evaluate(() => {
      const t = document.querySelector(".session-trail-panel");
      return {
        inDom: Boolean(t),
        display: t ? getComputedStyle(t).display : "absent",
        activeView: document.getElementById("main-content")?.dataset.activeView ?? null,
      };
    });
    expect(onLanding.inDom).toBe(true);
    expect(onLanding.activeView).toBe("landing");
    // RED IF: the hide rule is removed — `display` becomes `flex`.
    expect(onLanding.display).toBe("none");

    // POSITIVE PARTNER. Without this, `display === "none"` would pass just as
    // happily against a panel deleted from the product entirely, or against a
    // blanket `.session-trail-panel { display: none }` that breaks the trail
    // everywhere. The hide must be scoped to the landing view and nothing else.
    await page.locator("#landing-query").fill("Compare two database options");
    await page.locator("#landing-run").click();
    await expect
      .poll(async () =>
        page.evaluate(
          () => document.getElementById("main-content")?.dataset.activeView ?? null,
        ),
      )
      .not.toBe("landing");

    const offLanding = await page.evaluate(() => {
      const t = document.querySelector(".session-trail-panel");
      return t ? getComputedStyle(t).display : "absent";
    });
    expect(offLanding).not.toBe("none");
  });

  test("landing density: the page is not multiples of the fold", async ({ page }) => {
    await stubReadinessLive(page);
    await page.setViewportSize(PHONE);
    await page.goto("/ui");
    await expect(page.locator("#landing-run")).toBeAttached();

    const m = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      fold: window.innerHeight,
      ctaBelowFold: Math.round(
        (document.querySelector("#landing-run") as HTMLElement).getBoundingClientRect().bottom -
          window.innerHeight,
      ),
      horizontalOverflow:
        document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));

    // Reported, never gated — see the file header for why the fold itself is
    // not a safe assertion (4px of slack at this viewport).
    console.log(`landing @390x664: ${JSON.stringify(m)}`);

    // RED IF: the density block in app.css is removed. MEASURED with the
    // readiness banner present, before the fix, the page was 1848px against a
    // 664px fold (2.78x); after, 1422px (2.14x). The bound below is set at 2.4x
    // — comfortably clear of the measured "after" and comfortably below the
    // measured "before", so it is not pinned to either number (rule 7a).
    expect(m.scrollHeight).toBeLessThan(m.fold * 2.4);
    // Never a horizontal scrollbar on a phone.
    expect(m.horizontalOverflow).toBe(false);
  });
});

/**
 * ADR-0032: the landing must describe the pipeline the code actually runs.
 *
 * ADR-0099 INVERTED this gate. Until 2026-09-04 the assertions below required
 * the subhead to name a "moderator model" and banned every phrasing of models
 * critiquing each other — correct while #290 was unbuilt, and FALSE from the
 * moment `PEER_CRITIQUE_ENABLED` went true in production on 2026-09-03. The
 * gate then held the falsehood in place: the copy could not be corrected
 * without this file going red, which is the anti-pattern AGENTS.md forbids in
 * its own words ("Never write a check that goes red when the bug is FIXED").
 *
 * The direction is now reversed. Under `settings.peer_critique_enabled` each
 * ELIGIBLE answer slot critiques the others and may revise its own answer
 * (`debate.py:_build_peer_round`); NO moderator call is made on such a run.
 *
 * These assertions live in THIS file rather than a new spec on purpose:
 * adding a file to `e2e/tests/invariants/` moves the count AGENTS.md pins
 * (17), which `tests/test_doc_gate_consistency.py` turns red.
 */
/**
 * The subhead is pinned WHOLE, not by forbidden substrings.
 *
 * The first draft of this test listed three banned phrasings. Adversarial
 * review broke it in one line: appending "The models review one another's
 * answers and sharpen them." to the subhead contains none of the three, and
 * the test stayed GREEN on a hero that states the exact falsehood the whole
 * change exists to remove. A blacklist over open-ended English cannot work.
 *
 * Pinning the sentence makes any rewrite RED BY DEFAULT, so a future editor
 * has to come back here, read ADR-0032, and re-approve the claim deliberately.
 * That is the point — this is a claim about the system, not decoration.
 */
const EXPECTED_SUBHEAD =
  "Four frontier AI models answer. They critique each other's answers and " +
  "sources, and each can revise its own. A synthesis model writes the one " +
  "answer — where they agree, where they don't, and exactly what to trust.";

test.describe("landing copy describes the real pipeline (ADR-0032)", () => {
  test("the subhead is exactly the approved sentence", async ({ page }) => {
    await stubReadinessLive(page);
    await page.goto("/ui");
    await expect(page.locator(".landing-subhead")).toBeAttached();

    const actual = (
      (await page.locator(".landing-subhead").textContent()) ?? ""
    ).replace(/\s+/g, " ").trim();

    // RED IF: the subhead is reworded AT ALL. Deliberate: the previous version
    // of this assertion was a three-phrase blacklist and review walked a false
    // claim straight past it.
    expect(actual).toBe(EXPECTED_SUBHEAD);

    // Belt and braces on the two claims that matter, so a failure message
    // says WHICH property broke rather than just diffing a long string.
    // RED IF: the subhead reverts to naming a moderator, which no longer runs
    // on a peer run, or drops the synthesis stage.
    expect(actual.toLowerCase()).toContain("critique each other's");
    expect(actual.toLowerCase()).toContain("synthesis model");
    expect(actual.toLowerCase()).not.toContain("moderator");
  });

  test("no landing surface claims a moderator model audits the answers", async ({
    page,
  }) => {
    await stubReadinessLive(page);
    await page.goto("/ui");
    await expect(page.locator(".landing-hero")).toBeAttached();

    const text = (
      (await page.locator("[data-view='landing']").textContent()) ?? ""
    ).toLowerCase();

    // POSITIVE PARTNER FIRST (rule 7). Without this the negatives below are
    // trivially true over an unrendered view — which is not hypothetical: with
    // the per-IP mint cap unraised, /ui serves a 429 page and this locator is
    // empty. That is exactly how a vacuous pass would look.
    expect(text.length).toBeGreaterThan(400);
    expect(text).toContain("critique each other's");

    // RED IF: any moderator phrasing returns to the landing view. ADR-0099:
    // under the peer shape no moderator call is made at all, so a landing that
    // names one describes a pipeline the run does not execute. NOT a
    // completeness claim — the subhead test above is what pins the wording.
    // The h1 "Let four minds argue it out" is deliberately retained
    // (ADR-0032 §5, unchanged by ADR-0099), so "argue" is not among these.
    for (const banned of [
      "moderator",
      "audits them",
      "a separate model reads",
      "planned, not yet built",
      "not yet built",
    ]) {
      expect(text).not.toContain(banned);
    }
  });

  test("the disclaimer row names a REAL current limit, not a stale roadmap", async ({
    page,
  }) => {
    await stubReadinessLive(page);
    await page.goto("/ui");
    await expect(page.locator(".landing-disclaimers")).toBeAttached();

    const text = (
      (await page.locator(".landing-disclaimers").textContent()) ?? ""
    ).toLowerCase();

    // POSITIVE PARTNER: the row rendered and still carries a sibling chip, so
    // a missing phrase below means this chip changed rather than the whole row
    // vanishing.
    expect(text).toContain("decision support");

    // RED IF: the stale roadmap chip returns. ADR-0099: peer critique SHIPPED
    // (#290, ADR-0093/0095/0096) and has been enabled in production since
    // 2026-09-03, so a chip calling it unbuilt is false — and this assertion
    // used to REQUIRE that falsehood.
    expect(text).not.toContain("planned, not yet built");
    expect(text).not.toContain("not yet built");

    // POSITIVE PARTNER for the two negatives above: the slot still carries a
    // truthful current limit rather than being quietly emptied. ADR-0096
    // decision 1 buys L1 only — a source is CITED; that it resolves (L2) or
    // supports the claim (L3) is not attempted — and says in those words that
    // no UI copy may imply otherwise.
    expect(text).toContain("cited");
    expect(text).toContain("aren't checked against their pages");
  });
});
