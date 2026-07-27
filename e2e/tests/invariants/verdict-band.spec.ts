import { test, expect, Page } from "@playwright/test";
import {
  boot,
  goldenCreateResp,
  goldenCompletedResp,
  goldenConsensusResp,
  SLOTS,
} from "../../fixtures/golden-run";

/**
 * PR6 (issues #8/#15) — the verdict band must be AGREEMENT-LED.
 *
 * The reported defect: the band's headline is `final_synthesis.recommendation`
 * verbatim, which is citation-coverage-driven ("do not act on this without…"),
 * while the very next line says "4 of 4 models aligned". Two authorities, one
 * band, reading as a contradiction.
 *
 * The decision recorded in UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md:
 *   1. agreement-led headline;
 *   2. coverage caution as a clearly SEPARATE second line;
 *   3. an "automated summary" badge replacing the leaked
 *      "Heuristic fallback: " / "[Template] " prefix (backend `synthesis_mode`).
 *
 * These assertions pin ORDER and SEPARATION, not just presence — presence alone
 * was already true before the fix and would green a broken band.
 */

const fulfil = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

const costEstimateEnvelope = () => ({
  correlation_id: "corr-verdict-est",
  cost_estimate: goldenCreateResp().cost_estimate,
  model_slots: SLOTS,
  reasons: [],
});

/** Drive to the result view with a caller-shaped completed payload. */
async function driveWith(page: Page, completed: Record<string, unknown>) {
  await boot(page);
  await Promise.all([
    page.route("**/v1/query-runs/estimate", (r) => r.fulfill(fulfil(costEstimateEnvelope()))),
    page.route("**/v1/query-runs/warnings", (r) => r.fulfill(fulfil({ warnings: [] }))),
    page.route("**/v1/query-runs/active", (r) => r.fulfill(fulfil({ query_run_id: null }))),
  ]);
  await page.route(/\/v1\/query-runs\/[0-9a-f-]{36}$/, (r) => r.fulfill(fulfil(completed)));
  await page.route(/\/v1\/query-runs$/, (r) =>
    r.request().method() === "POST" ? r.fulfill(fulfil(goldenCreateResp())) : r.continue(),
  );
  await page.getByRole("textbox").first().fill("What are the key metrics for measuring SaaS retention?");
  await page.locator("#run-now").click();
  await expect(page.locator("#result-verdict[data-consensus]")).toBeVisible({ timeout: 20000 });
}

/** Patch final_synthesis on a copy of the golden completed response. */
function withSynthesis(patch: Record<string, unknown>) {
  const resp = goldenCompletedResp() as Record<string, any>;
  resp.result.final_synthesis = { ...resp.result.final_synthesis, ...patch };
  return resp;
}

/** DOM index of a selector inside the verdict band; -1 when absent. */
async function bandOrder(page: Page, selector: string): Promise<number> {
  return page.evaluate((sel) => {
    const band = document.getElementById("result-verdict");
    if (!band) return -1;
    const kids = Array.from(band.querySelectorAll("*"));
    return kids.findIndex((n) => n.matches(sel));
  }, selector);
}

/**
 * WCAG 2.1 contrast ratio of a node's text against its EFFECTIVE background —
 * the ancestor chain composited, not `background-color` read off the node
 * itself. That distinction is the whole point here: the verdict band's children
 * are transparent, so a naive read returns `rgba(0,0,0,0)` and every check
 * passes vacuously. F-04 is precisely a child inheriting the dark-green band and
 * painting amber/blue text on it at ~1.15:1.
 *
 * Returns -1 when the selector is absent, so a missing element can never be
 * mistaken for a passing contrast.
 */
async function contrastAgainstBackdrop(page: Page, selector: string): Promise<number> {
  return page.evaluate((sel) => {
    const node = document.querySelector(sel) as HTMLElement | null;
    if (!node) return -1;

    type RGBA = [number, number, number, number];

    /** Parse every colour serialisation Chromium emits — including the
     *  `color(srgb …)` form that `color-mix()` resolves to. */
    const parse = (raw: string): RGBA | null => {
      const s = (raw || "").trim();
      if (!s || s === "transparent") return [0, 0, 0, 0];
      const srgb = s.match(/^color\(srgb\s+([^)]+)\)$/i);
      if (srgb) {
        const p = srgb[1].split(/[\s/]+/).filter(Boolean).map(Number);
        if (p.length < 3 || p.some((n) => !Number.isFinite(n))) return null;
        return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1];
      }
      const rgb = s.match(/^rgba?\(([^)]+)\)$/i);
      if (rgb) {
        const p = rgb[1].split(/[,\s/]+/).filter(Boolean).map(Number);
        if (p.length < 3 || p.some((n) => !Number.isFinite(n))) return null;
        return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
      }
      return null;
    };

    /** `src` painted over `dst` (both premultiplied-free, dst assumed opaque). */
    const over = (src: RGBA, dst: RGBA): RGBA => [
      src[0] * src[3] + dst[0] * (1 - src[3]),
      src[1] * src[3] + dst[1] * (1 - src[3]),
      src[2] * src[3] + dst[2] * (1 - src[3]),
      1,
    ];

    const luminance = ([r, g, b]: RGBA): number => {
      const chan = (v: number) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b);
    };

    // Walk UP compositing every background-color until an opaque one is found.
    // Seed with the document's own background so a fully transparent chain still
    // resolves to a real colour rather than black.
    const rootBg =
      parse(getComputedStyle(document.body).backgroundColor) ||
      ([255, 255, 255, 1] as RGBA);
    let backdrop: RGBA = rootBg[3] === 1 ? rootBg : [255, 255, 255, 1];

    const chain: RGBA[] = [];
    for (let n: HTMLElement | null = node; n; n = n.parentElement) {
      const bg = parse(getComputedStyle(n).backgroundColor);
      if (!bg || bg[3] === 0) continue;
      chain.push(bg);
      if (bg[3] === 1) break;
    }
    // Composite outermost-first.
    for (let i = chain.length - 1; i >= 0; i--) backdrop = over(chain[i], backdrop);

    const fg = parse(getComputedStyle(node).color);
    if (!fg) return -1;
    const text = over(fg, backdrop);

    const l1 = luminance(text);
    const l2 = luminance(backdrop);
    const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
    return (hi + 0.05) / (lo + 0.05);
  }, selector);
}

/**
 * Every text-bearing node inside `root` whose contrast is below `min`.
 *
 * WHY this exists and the per-selector check above does NOT suffice: the
 * recommendation is rendered through the Markdown renderer (`setProse`), so the
 * text a user actually reads lives in `<strong>` / `<li>` / `<a>` / `<code>` /
 * `<blockquote>` descendants — each picking up its own colour from the prose
 * stylesheet (ink, accent, muted), NOT the white the band sets on their parent.
 * Measuring `.result-verdict-text` alone reads the CONTAINER's inherited white
 * and passes while every visible word is dark ink on dark green. A live
 * screenshot caught exactly that after the per-selector gate went green.
 *
 * Only nodes with their own non-whitespace text are measured (a wrapper's
 * colour is irrelevant if no glyph uses it), and hidden nodes are skipped.
 */
async function lowContrastTextNodes(
  page: Page,
  root: string,
  min = 4.5,
): Promise<{ tag: string; cls: string; text: string; ratio: number }[]> {
  return page.evaluate(
    ([rootSel, minRatio]) => {
      const rootEl = document.querySelector(rootSel as string) as HTMLElement | null;
      if (!rootEl) return [{ tag: "MISSING", cls: rootSel as string, text: "", ratio: 0 }];

      type RGBA = [number, number, number, number];
      const parse = (raw: string): RGBA | null => {
        const s = (raw || "").trim();
        if (!s || s === "transparent") return [0, 0, 0, 0];
        const srgb = s.match(/^color\(srgb\s+([^)]+)\)$/i);
        if (srgb) {
          const p = srgb[1].split(/[\s/]+/).filter(Boolean).map(Number);
          if (p.length < 3 || p.some((n) => !Number.isFinite(n))) return null;
          return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1];
        }
        const rgb = s.match(/^rgba?\(([^)]+)\)$/i);
        if (rgb) {
          const p = rgb[1].split(/[,\s/]+/).filter(Boolean).map(Number);
          if (p.length < 3 || p.some((n) => !Number.isFinite(n))) return null;
          return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
        }
        return null;
      };
      const over = (src: RGBA, dst: RGBA): RGBA => [
        src[0] * src[3] + dst[0] * (1 - src[3]),
        src[1] * src[3] + dst[1] * (1 - src[3]),
        src[2] * src[3] + dst[2] * (1 - src[3]),
        1,
      ];
      const lum = ([r, g, b]: RGBA): number => {
        const c = (v: number) => {
          const x = v / 255;
          return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
      };
      const backdropOf = (node: HTMLElement): RGBA => {
        let bg: RGBA = [255, 255, 255, 1];
        const chain: RGBA[] = [];
        for (let n: HTMLElement | null = node; n; n = n.parentElement) {
          const c = parse(getComputedStyle(n).backgroundColor);
          if (!c || c[3] === 0) continue;
          chain.push(c);
          if (c[3] === 1) break;
        }
        for (let i = chain.length - 1; i >= 0; i--) bg = over(chain[i], bg);
        return bg;
      };

      const bad: { tag: string; cls: string; text: string; ratio: number }[] = [];
      const ratioOf = (fgRaw: string, node: HTMLElement): number | null => {
        const fg = parse(fgRaw);
        if (!fg) return null;
        const bg = backdropOf(node);
        const text = over(fg, bg);
        const l1 = lum(text);
        const l2 = lum(bg);
        const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
        return (hi + 0.05) / (lo + 0.05);
      };
      const record = (node: HTMLElement, label: string, sample: string, ratio: number | null) => {
        if (ratio === null || ratio >= (minRatio as number)) return;
        bad.push({
          tag: label,
          cls: node.className || "(no class)",
          text: sample.slice(0, 60),
          ratio: Math.round(ratio * 100) / 100,
        });
      };

      const all = [rootEl, ...Array.from(rootEl.querySelectorAll<HTMLElement>("*"))];
      for (const el of all) {
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0) continue;

        // Nodes that render their OWN glyphs.
        const own = Array.from(el.childNodes)
          .filter((n) => n.nodeType === Node.TEXT_NODE)
          .map((n) => n.textContent || "")
          .join("")
          .trim();
        if (own) record(el, el.tagName, own, ratioOf(cs.color, el));

        // PSEUDO-ELEMENTS paint glyphs that have NO text node, so the walk
        // above is blind to them by construction — `getComputedStyle` must be
        // called with the pseudo argument or it silently returns the element's
        // own style. An adversarial review caught this: deleting the
        // `[data-consensus="true"] .q-prose li::marker` override left all 27
        // tests green while the ordered-list numerals rendered at 2.77:1 — the
        // exact defect (and exact ratio) this whole gate exists to catch.
        if (cs.display === "list-item" && cs.listStyleType !== "none") {
          record(el, `${el.tagName}::marker`, "(list marker)", ratioOf(getComputedStyle(el, "::marker").color, el));
        }
        for (const pseudo of ["::before", "::after"]) {
          const ps = getComputedStyle(el, pseudo);
          const content = ps.content;
          if (!content || content === "none" || content === "normal" || content === '""') continue;
          if (ps.display === "none" || ps.visibility === "hidden" || Number(ps.opacity) === 0) continue;
          record(el, `${el.tagName}${pseudo}`, content, ratioOf(ps.color, el));
        }
      }
      return bad;
    },
    [root, min] as [string, number],
  );
}

/** Computed font-size in px for a selector; -1 when absent. */
async function fontSizePx(page: Page, selector: string): Promise<number> {
  return page.evaluate((sel) => {
    const n = document.querySelector(sel);
    if (!n) return -1;
    return parseFloat(getComputedStyle(n).fontSize) || -1;
  }, selector);
}

test.describe("PR6 — verdict band is agreement-led (#8/#15)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  test("the agreement line precedes the recommendation prose", async ({ page }) => {
    await driveWith(page, goldenCompletedResp());

    const agreement = await bandOrder(page, ".result-verdict-agreement");
    const prose = await bandOrder(page, ".result-verdict-text");

    expect(agreement, ".result-verdict-agreement must exist in the band").toBeGreaterThanOrEqual(0);
    expect(prose, ".result-verdict-text must exist in the band").toBeGreaterThanOrEqual(0);
    expect(
      agreement,
      "the agreement tally must LEAD the band — the recommendation is the supporting detail, not the headline",
    ).toBeLessThan(prose);
  });

  test("the agreement line still carries the real tally", async ({ page }) => {
    await driveWith(page, goldenCompletedResp());
    const text = await page.locator(".result-verdict-agreement").first().textContent();
    expect(text).toContain("3 of 4");
  });

  test("low citation coverage renders a SEPARATE caution line, not a merged headline", async ({ page }) => {
    await driveWith(
      page,
      withSynthesis({
        citation_coverage: {
          answer_count: 4,
          sourced_answer_count: 1,
          sourced_answer_ratio: "0.25",
          target_ratio: "0.80",
          target_met: false,
        },
      }),
    );

    const caution = page.locator(".result-verdict-coverage");
    await expect(caution, "a below-target coverage must surface its own caution line").toHaveCount(1);
    await expect(caution).toContainText("25%");

    // It must be its OWN node, not folded into the agreement line.
    //
    // F-23: this previously read `expect(agreementText || "")`, which passes
    // when the agreement line does not exist at all — i.e. it greened the exact
    // regression it was written to catch. Assert the line EXISTS first, then
    // assert what it does not contain.
    const agreementLine = page.locator(".result-verdict-agreement");
    await expect(agreementLine, "the agreement line must exist for this assertion to mean anything").toHaveCount(1);
    const agreementText = await agreementLine.first().textContent();
    expect(agreementText).toBeTruthy();
    expect(agreementText as string).not.toContain("25%");

    // ...and it must sit between the agreement line and the prose.
    //
    // F-23: `expect(cov).toBeGreaterThan(agreement)` passed when the agreement
    // line was ABSENT (bandOrder → -1). Pin both indices as present first.
    const agreement = await bandOrder(page, ".result-verdict-agreement");
    const cov = await bandOrder(page, ".result-verdict-coverage");
    expect(agreement, "agreement line must be present in the band").toBeGreaterThanOrEqual(0);
    expect(cov, "coverage caution must be present in the band").toBeGreaterThanOrEqual(0);
    expect(cov).toBeGreaterThan(agreement);
  });

  test("coverage at target renders NO caution line", async ({ page }) => {
    // The other direction of the caution-line rule. This used to lean on
    // goldenCompletedResp() being at target, but that fixture is now honestly
    // BELOW target (slot 3 returns no sources -> 3 of 4 = 0.75; review A6), so
    // the at-target shape is supplied explicitly. Keeping this test is the
    // point: without it, "always render the caution" would pass.
    await driveWith(
      page,
      withSynthesis({
        citation_coverage: {
          answer_count: 4,
          sourced_answer_count: 4,
          sourced_answer_ratio: "1.00",
          target_ratio: "0.80",
          target_met: true,
        },
      }),
    );
    await expect(page.locator(".result-verdict-coverage")).toHaveCount(0);
  });

  test("a non-live synthesis_mode renders an automated-summary badge", async ({ page }) => {
    await driveWith(page, withSynthesis({ synthesis_mode: "simulated" }));
    const badge = page.locator(".badge-summary");
    await expect(badge, "a templated synthesis must be badged, not silently presented as model output").toHaveCount(1);
    await expect(badge).toContainText(/Automated summary/i);
  });

  test("a partially-live synthesis_mode is badged distinctly", async ({ page }) => {
    await driveWith(page, withSynthesis({ synthesis_mode: "fallback" }));
    await expect(page.locator(".badge-summary")).toContainText(/Partially automated/i);
  });

  test("a fully live synthesis carries NO badge", async ({ page }) => {
    await driveWith(page, withSynthesis({ synthesis_mode: "live" }));
    await expect(page.locator(".badge-summary")).toHaveCount(0);
  });

  test("the CONSENSUS band actually paints green — the fixture is not a no-op", async ({ page }) => {
    // Guards the whole describe block below: if goldenConsensusResp() ever
    // stops producing data-consensus="true", every [data-consensus="true"]
    // assertion silently becomes vacuous. Fail loudly here instead.
    await driveWith(page, goldenConsensusResp());
    await expect(page.locator('#result-verdict[data-consensus="true"]')).toHaveCount(1);
    await expect(page.locator(".result-verdict-coverage")).toHaveCount(1);
    await expect(page.locator(".badge-summary")).toHaveCount(1);
  });

  // NOTE: the "no internal templating prefix leaks" invariant is deliberately
  // NOT asserted here. Injecting "[Template] " into a MOCKED response and then
  // demanding the client scrub it would test the wrong layer: it would force a
  // client-side text filter that also mangles genuine provider prose which
  // happens to contain those words. The producer is the only place provenance
  // is decided, so the invariant is pinned there instead —
  // tests/unit/test_synthesis.py::test_no_templating_prefix_leaks_into_sections.
});

/**
 * WP-B — the regressions the agreement-led restructure itself introduced.
 *
 * Every one of these was invisible to the suite above because the golden
 * fixture is 3-of-4 (a DIVIDED panel) with `target_met: true` and no
 * `synthesis_mode`: it never paints the green band, the caution line, or the
 * badge. `goldenConsensusResp()` paints all three at once.
 */
test.describe("WP-B — verdict band regressions (F-04, F-18, F-21, F-22)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "reference run is chromium-only");

  // ---- F-04: legible on the green band ------------------------------------
  //
  // `.result-verdict-coverage` (amber) and `.badge-summary` (blue-on-blue-tint)
  // have no [data-consensus="true"] override, so on #0E6B50 they land at
  // ~1.15:1. Every sibling in the band DOES have one. Assert the whole family
  // rather than the two known offenders, so the next child added to the band
  // cannot repeat the defect.
  const BAND_TEXT_SURFACES = [
    ".result-verdict-eyebrow",
    ".result-verdict-agreement",
    ".result-verdict-coverage",
    ".result-verdict-text",
    ".result-verdict-caveat",
    ".result-verdict-caption",
    ".badge-summary",
  ];

  for (const sel of BAND_TEXT_SURFACES) {
    test(`consensus band: ${sel} clears 4.5:1 against the green surface`, async ({ page }) => {
      await driveWith(page, goldenConsensusResp());
      await expect(page.locator('#result-verdict[data-consensus="true"]')).toHaveCount(1);

      const ratio = await contrastAgainstBackdrop(page, sel);
      expect(ratio, `${sel} must be present on the consensus band to be measurable`).toBeGreaterThan(0);
      expect(
        ratio,
        `${sel} renders at ${ratio.toFixed(2)}:1 on the dark-green consensus band — WCAG AA needs 4.5:1`,
      ).toBeGreaterThanOrEqual(4.5);
    });
  }

  // The gate that actually matches what a user sees: EVERY glyph in the band,
  // including the Markdown the recommendation renders through setProse.
  for (const theme of ["light", "dark"] as const) {
    test(`consensus band: every rendered glyph clears 4.5:1 [${theme}]`, async ({ page }) => {
      await page.addInitScript(([t]) => {
        try { window.localStorage.setItem("quorum.theme", t as string); } catch (_) {}
      }, [theme]);
      await driveWith(page, goldenConsensusResp());
      await expect(page.locator('#result-verdict[data-consensus="true"]')).toHaveCount(1);
      expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(theme);

      // Anti-vacuity: the band must actually contain rendered prose descendants,
      // otherwise "no low-contrast nodes" is trivially true.
      const proseNodes = await page.locator("#result-verdict .result-verdict-text *").count();
      expect(proseNodes, "the golden recommendation must render Markdown children to measure").toBeGreaterThan(3);

      const bad = await lowContrastTextNodes(page, "#result-verdict");
      expect(
        bad,
        `low-contrast text on the green consensus band:\n${bad
          .map((b) => `  ${b.tag}.${b.cls} @ ${b.ratio}:1 — "${b.text}"`)
          .join("\n")}`,
      ).toEqual([]);
    });
  }

  for (const theme of ["light", "dark"] as const) {
    test(`divided band: every rendered glyph clears 4.5:1 [${theme}]`, async ({ page }) => {
      await page.addInitScript(([t]) => {
        try { window.localStorage.setItem("quorum.theme", t as string); } catch (_) {}
      }, [theme]);
      await driveWith(page, goldenCompletedResp()); // 3 of 4 → neutral surface
      await expect(page.locator('#result-verdict[data-consensus="false"]')).toHaveCount(1);
      const bad = await lowContrastTextNodes(page, "#result-verdict");
      expect(
        bad,
        `low-contrast text on the neutral divided band:\n${bad
          .map((b) => `  ${b.tag}.${b.cls} @ ${b.ratio}:1 — "${b.text}"`)
          .join("\n")}`,
      ).toEqual([]);
    });
  }

  for (const theme of ["light", "dark"] as const) {
    test(`consensus band: the EMPTY-recommendation placeholder is legible [${theme}]`, async ({ page }) => {
      // setProse's placeholder branch swaps `q-prose` for `muted`, escaping every
      // prose override. `recommendation` is a plain required `str`, so "" is a
      // shape the server can emit and this branch is reachable.
      await page.addInitScript(([t]) => {
        try { window.localStorage.setItem("quorum.theme", t as string); } catch (_) {}
      }, [theme]);
      const resp = goldenConsensusResp() as Record<string, any>;
      resp.result.final_synthesis = { ...resp.result.final_synthesis, recommendation: "" };
      await driveWith(page, resp);
      await expect(page.locator('#result-verdict[data-consensus="true"]')).toHaveCount(1);
      // Anti-vacuity: the placeholder must actually be on screen.
      await expect(page.locator(".result-verdict-text")).toContainText("No recommendation was recorded");
      const bad = await lowContrastTextNodes(page, "#result-verdict");
      expect(
        bad,
        `low-contrast placeholder text on the green band:\n${bad
          .map((b) => `  ${b.tag}.${b.cls} @ ${b.ratio}:1 — "${b.text}"`)
          .join("\n")}`,
      ).toEqual([]);
    });
  }

  test("consensus band stays legible in DARK theme", async ({ page }) => {
    // The band surface (--verdict-surface / --verdict-on) is theme-INVARIANT,
    // but --warning and --info are not: they flip to the lighter tonal
    // variants in dark. A fix that only holds in light would be half a fix.
    await page.addInitScript(() => {
      try { window.localStorage.setItem("quorum.theme", "dark"); } catch (_) {}
    });
    await driveWith(page, goldenConsensusResp());
    expect(
      await page.evaluate(() => document.documentElement.dataset.theme),
      "the dark theme must actually be applied for this test to mean anything",
    ).toBe("dark");
    await expect(page.locator('#result-verdict[data-consensus="true"]')).toHaveCount(1);

    for (const sel of BAND_TEXT_SURFACES) {
      const ratio = await contrastAgainstBackdrop(page, sel);
      expect(ratio, `${sel} must be present on the consensus band`).toBeGreaterThan(0);
      expect(ratio, `${sel} at ${ratio.toFixed(2)}:1 on the dark-theme consensus band`).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("divided band: the caution and badge stay legible too", async ({ page }) => {
    // The neutral band was never the defect, but pinning it stops a fix that
    // trades one broken state for the other.
    await driveWith(
      page,
      (() => {
        const r = goldenCompletedResp() as Record<string, any>;
        r.result.final_synthesis = {
          ...r.result.final_synthesis,
          synthesis_mode: "simulated",
          citation_coverage: { answer_count: 4, sourced_answer_count: 3, sourced_answer_ratio: "0.75", target_ratio: "0.80", target_met: false },
        };
        return r;
      })(),
    );
    await expect(page.locator('#result-verdict[data-consensus="false"]')).toHaveCount(1);
    for (const sel of [".result-verdict-coverage", ".badge-summary"]) {
      const ratio = await contrastAgainstBackdrop(page, sel);
      expect(ratio, `${sel} must be present`).toBeGreaterThan(0);
      expect(ratio, `${sel} at ${ratio.toFixed(2)}:1 on the neutral band`).toBeGreaterThanOrEqual(4.5);
    }
  });

  // ---- F-21: the badge is a chip, not a banner ----------------------------
  //
  // Asserted against the badge's OWN max-content width, not an arbitrary
  // fraction of the column. The first version of this test used
  // `< column * 0.6`, which happened to hold at Playwright's 1280px default and
  // then failed at 375px once the column legitimately narrowed to 209px — the
  // badge was correctly shrink-to-fit at its natural 150px the whole time. A
  // threshold that depends on the container measures the container; the defect
  // was "the pill stretched to fill", so compare against what fit-content gives.
  for (const width of [1440, 375] as const) {
    test(`the provenance badge is shrink-to-fit, not full-width @ ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await driveWith(page, goldenConsensusResp());
      const box = await page.evaluate(() => {
        const badge = document.querySelector(".badge-summary") as HTMLElement | null;
        const content = document.querySelector(".result-verdict-content") as HTMLElement | null;
        if (!badge || !content) return null;
        // What the badge WOULD be if sized purely by its own content.
        const probe = badge.cloneNode(true) as HTMLElement;
        probe.style.cssText += ";position:absolute;left:-9999px;top:0;width:max-content;align-self:auto;";
        badge.parentElement!.appendChild(probe);
        const natural = probe.getBoundingClientRect().width;
        probe.remove();
        return {
          badge: badge.getBoundingClientRect().width,
          natural,
          content: content.getBoundingClientRect().width,
        };
      });
      expect(box, "badge and band content must both render").not.toBeNull();
      const { badge, natural, content } = box as { badge: number; natural: number; content: number };
      expect(content).toBeGreaterThan(0);
      expect(natural).toBeGreaterThan(0);
      expect(
        badge,
        `the badge renders ${Math.round(badge)}px wide but its content only needs ${Math.round(natural)}px ` +
          `(column is ${Math.round(content)}px) — a pill stretched into a banner by flex align-items: stretch`,
      ).toBeLessThanOrEqual(natural + 1);
    });
  }

  // ---- F-22: agreement-led in TYPE, not merely in DOM order ---------------
  test("the agreement line is visually dominant over the recommendation prose", async ({ page }) => {
    await driveWith(page, goldenConsensusResp());
    const agreement = await fontSizePx(page, ".result-verdict-agreement");
    const prose = await fontSizePx(page, ".result-verdict-text");
    expect(agreement, "agreement line must render").toBeGreaterThan(0);
    expect(prose, "recommendation prose must render").toBeGreaterThan(0);
    expect(
      agreement,
      `the band is agreement-led in DOM order only: the tally renders at ${agreement}px under a ${prose}px recommendation, so the eye still reads the recommendation as the headline`,
    ).toBeGreaterThanOrEqual(prose);
  });

  // ---- F-18: never fabricate a coverage number ----------------------------
  //
  // `Number("") === 0` and `Number(null) === 0` are both finite, so a MISSING
  // ratio renders "Only 0% of the answers carried a primary source" — a number
  // the data does not support, on the most trust-sensitive line in the product.
  for (const [label, ratio] of [
    ["empty string", ""],
    ["null", null],
    ["whitespace", "   "],
  ] as [string, unknown][]) {
    test(`a ${label} sourced_answer_ratio renders NO fabricated percentage`, async ({ page }) => {
      await driveWith(
        page,
        withSynthesis({
          citation_coverage: {
            answer_count: 4,
            sourced_answer_count: 3,
            sourced_answer_ratio: ratio,
            target_ratio: "0.80",
            target_met: false,
          },
        }),
      );
      const caution = page.locator(".result-verdict-coverage");
      await expect(
        caution,
        `a ${label} ratio must not be coerced to 0 and presented as a measured coverage figure`,
      ).toHaveCount(0);
      await expect(page.locator("#result-verdict")).not.toContainText("Only 0%");
    });
  }

  test("a genuine 0% coverage IS still reported", async ({ page }) => {
    // The other direction of the F-18 guard: rejecting "" must not also reject a
    // real, measured zero.
    await driveWith(
      page,
      withSynthesis({
        citation_coverage: {
          answer_count: 4,
          sourced_answer_count: 0,
          sourced_answer_ratio: "0.00",
          target_ratio: "0.80",
          target_met: false,
        },
      }),
    );
    await expect(page.locator(".result-verdict-coverage")).toContainText("0%");
  });
});
