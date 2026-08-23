import { test, expect, Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  driveToResult,
  goldenRespWithProviderText,
  goldenRespWithMarkdownShapes,
  PRODUCTION_TABLE,
} from "../../fixtures/golden-run";
import { MARKDOWN_CORPUS, CORPUS_BASELINE_E2A39AA } from "../../fixtures/markdown-corpus";

/**
 * THE MARKDOWN FAILURE CORPUS, DRIVEN THROUGH THE REAL BROWSER.
 *
 * `e2e/fixtures/markdown-corpus.ts` is data: 20 provider strings, what a user
 * must see, and the measured behaviour of the hand-rolled renderer. This is the
 * spec that turns it into a gate, against the vendored parser ADR-0014 chose.
 *
 * WHY IT IS A GATE AND NOT A UNIT TEST. Every leak in #257 reached a real
 * screen while 196 tests were green, because the fixture had never held those
 * shapes. A renderer assertion that never renders proves nothing about a
 * renderer, so each case is driven through the actual app: composer → run →
 * result view, with the case string on the surface it leaked from.
 *
 * THE HALF THAT IS EASY TO MISS. SEVEN of the twenty cases were already
 * CORRECT before this work, and the abandoned branch broke several of them
 * while fixing the others. Those seven are asserted here with exactly as much
 * force as the broken ones — a replacement that fixes every defect and
 * regresses one correct case is a net loss.
 *
 * (This paragraph said "nine" against a corpus the same commit had re-measured
 * to 13 BROKEN / 7 CORRECT. Both review lenses caught it independently, by
 * running the corpus rather than reading it. The split is now asserted, below,
 * so the next drift is a red test rather than a careful reader.)
 *
 * WHAT TURNS THIS FILE RED, per group, is stated on each test.
 */

test.describe.configure({ mode: "default" });

// --- helpers -----------------------------------------------------------------

/** Every visible text node under a selector, excluding verbatim code. */
async function textNodes(page: Page, selector: string): Promise<string[]> {
  return page.evaluate((sel) => {
    const root = document.querySelector(sel);
    if (!root) return [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const out: string[] = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if ((n.parentElement as Element | null)?.closest("code, pre")) continue;
      const t = n.nodeValue || "";
      if (t.trim()) out.push(t);
    }
    return out;
  }, selector);
}

/** The rendered shape of the block surface a corpus case was seeded onto. */
async function blockShape(page: Page) {
  return page.evaluate(() => {
    const el = document.querySelector(".result-verdict-text");
    if (!el) return null;
    return {
      html: el.innerHTML,
      text: (el.textContent || ""),
      tables: el.querySelectorAll("table").length,
      rows: el.querySelectorAll("tbody tr").length,
      headerCells: [...el.querySelectorAll("thead th")].map((c) => (c.textContent || "").trim()),
      bodyCells: [...el.querySelectorAll("tbody td")].map((c) => (c.textContent || "").trim()),
      headings: [...el.querySelectorAll("h1,h2,h3,h4,h5,h6")].map((h) => ({
        tag: h.tagName, text: (h.textContent || "").trim(),
      })),
      strongs: [...el.querySelectorAll("strong")].map((s) => (s.textContent || "").trim()),
      ems: [...el.querySelectorAll("em")].map((s) => (s.textContent || "").trim()),
      pres: [...el.querySelectorAll("pre")].map((p) => p.textContent || ""),
      brs: el.querySelectorAll("br").length,
    };
  });
}

const CASE = Object.fromEntries(MARKDOWN_CORPUS.map((c) => [c.id, c.input]));

/** Drive the result view with one corpus case on the BLOCK surface. */
async function renderBlock(page: Page, id: string) {
  const input = CASE[id];
  expect(input, `corpus case ${id} is missing — the fixture was renamed or deleted`).toBeTruthy();
  await driveToResult(page, goldenRespWithProviderText(input, "block"));
  const shape = await blockShape(page);
  expect(shape, ".result-verdict-text did not render at all").not.toBeNull();
  return shape!;
}

// --- the corpus itself covers what it says it covers --------------------------

test("the corpus is the population these tests claim to sweep", () => {
  // A positive partner for every "no offender found" assertion below: they are
  // all trivially true over an empty corpus.
  expect(MARKDOWN_CORPUS.length, "the corpus lost cases").toBe(20);
  const ids = new Set(MARKDOWN_CORPUS.map((c) => c.id));
  expect(ids.size, "two corpus cases share an id, so one is never swept").toBe(20);

  // And the SPLIT, asserted against the constant the corpus exports. Neither
  // was checked by anything before: the corpus header disagreed with its own
  // footer (nine/eight vs eleven/nine), the re-measured split (13/7) was
  // exported and read by NOTHING, and this spec's own prose then repeated the
  // stale number. Three documents, one list, no arithmetic anywhere — the exact
  // shape AGENTS.md rule 1a says to replace with a check.
  const broken = MARKDOWN_CORPUS.filter((c) => c.current === "BROKEN").length;
  const correct = MARKDOWN_CORPUS.filter((c) => c.current === "CORRECT").length;
  expect(
    { broken, correct, total: broken + correct },
    "the corpus's exported baseline no longer matches the cases it exports",
  ).toEqual({
    broken: CORPUS_BASELINE_E2A39AA.broken,
    correct: CORPUS_BASELINE_E2A39AA.correct,
    total: CORPUS_BASELINE_E2A39AA.total,
  });
});

// --- tables: nine cases, zero of which rendered a <table> before this work ----

test.describe("tables (#257 defect 1 — 8 paragraphs of raw |---| on screen)", () => {
  // RED IF: the parser loses table support, or the block surface stops routing
  // through it. Before ADR-0014 every one of these produced ZERO <table>.
  for (const id of [
    "gfm-table-production-shape",
    "gfm-one-dash-separator",
    "gfm-pipe-less-table",
    "gfm-centered-separator",
  ]) {
    test(`${id} renders a real table`, async ({ page }) => {
      const shape = await renderBlock(page, id);
      expect(shape.tables, "a pipe table must render as a <table>").toBe(1);
      expect(shape.headerCells.length, "the header row must have cells").toBeGreaterThan(1);
      expect(shape.rows, "the body row must render").toBeGreaterThan(0);
      // No pipe skeleton may survive as prose alongside the table.
      const raw = (await textNodes(page, ".result-verdict-text")).filter((t) => /\|\s*-{2,}/.test(t));
      expect(raw, "a separator row survived as visible text").toEqual([]);
    });
  }

  test("escaped-pipe-in-cell keeps both cells (the abandoned fix deleted one)", async ({ page }) => {
    const shape = await renderBlock(page, "escaped-pipe-in-cell");
    expect(shape.tables).toBe(1);
    // The abandoned branch split on EVERY pipe, so `\|` ended the cell early and
    // "the pipe char" was dropped outright — content loss, and the reason this
    // case is in the corpus.
    expect(shape.bodyCells, "the escaped pipe must be one cell and the prose another")
      .toEqual(["|", "the pipe char"]);
  });

  test("over-wide-body-row renders a table and keeps its first cells", async ({ page }) => {
    const shape = await renderBlock(page, "over-wide-body-row");
    expect(shape.tables).toBe(1);
    // KNOWN GAP, stated rather than asserted: GFM (and therefore GitHub, and
    // every mainstream renderer) DISCARDS a body cell beyond the header's
    // width, so the "3" in `| 1 | 2 | 3 |` is dropped. ADR-0015 records why
    // this was accepted rather than fixed — deviating means re-implementing
    // table DETECTION, which is the failure mode ADR-0014 exists to end.
    //
    // This deliberately asserts a FIX-COMPATIBLE invariant: the cells that do
    // survive must be right, and no raw pipe row may reach the screen. A test
    // pinning `bodyCells.length === 2` would go red the day someone preserves
    // the third cell — locking in the defect it documents.
    expect(shape.bodyCells.slice(0, 2)).toEqual(["1", "2"]);
    const raw = (await textNodes(page, ".result-verdict-text")).filter((t) => t.includes("|"));
    expect(raw, "no pipe skeleton may survive as prose").toEqual([]);
  });

  test("header-row-no-separator is NOT a table and keeps its words", async ({ page }) => {
    const shape = await renderBlock(page, "header-row-no-separator");
    // Two pipe rows with no separator are not a table in GFM. Inventing one
    // here is what "the line has pipes" detection would do.
    expect(shape.tables, "a header row with no separator is not a table").toBe(0);
    for (const word of ["Option", "Note", "Scale up", "fine"]) {
      expect(shape.text, `the word "${word}" must survive as prose`).toContain(word);
    }
  });

  test("table-in-fenced-code is shown verbatim, not rendered", async ({ page }) => {
    const shape = await renderBlock(page, "table-in-fenced-code");
    expect(shape.tables, "a table inside a fence must NOT be rendered").toBe(0);
    expect(shape.pres.length, "the fence must render as a <pre>").toBe(1);
    // The user asked how to WRITE one, so every row must be there verbatim,
    // separator included — the abandoned fix ate the separator row.
    expect(shape.pres[0]).toContain("| A | B |");
    expect(shape.pres[0]).toContain("|---|---|");
    expect(shape.pres[0]).toContain("| 1 | 2 |");
  });

  test("literal-br-in-cell breaks the line and shows no <br> text", async ({ page }) => {
    const shape = await renderBlock(page, "literal-br-in-cell");
    expect(shape.tables).toBe(1);
    expect(shape.brs, "the literal <br> must become a real line break").toBeGreaterThan(0);
    // 6 of these reached a real screen as the visible text "<br>" (#257 §3).
    const leaked = (await textNodes(page, ".result-verdict-text")).filter((t) => /<br\s*\/?>/i.test(t));
    expect(leaked, "the literal <br> was shown as text").toEqual([]);
    expect(shape.text).toContain("one");
    expect(shape.text).toContain("two");
  });
});

// --- emphasis: the nine cases that were already CORRECT, plus two that leak ---

test.describe("emphasis and prose (the four broken, the seven that must not regress)", () => {
  // RED IF: a renderer starts inventing emphasis inside a word. Stock
  // markdown-it DOES — CommonMark allows intra-word `*` — so this is the
  // measured proof that ADR-0015's deviation 3 is wired and working.
  test("arithmetic-unspaced invents no emphasis across 3*40 and 2*12", async ({ page }) => {
    const shape = await renderBlock(page, "arithmetic-unspaced");
    expect(shape.ems, "stock CommonMark renders 3<em>40 and 2</em>12 here").toEqual([]);
    expect(shape.text).toContain("3*40");
    expect(shape.text).toContain("2*12");
  });

  test("arithmetic-spaced leaves 5 * 3 alone", async ({ page }) => {
    const shape = await renderBlock(page, "arithmetic-spaced");
    expect(shape.ems).toEqual([]);
    expect(shape.text).toContain("5 * 3");
  });

  // RED IF: the `**` rule gains a neighbour restriction. The abandoned fix's
  // two-sided rule deleted the OPENING `**` and kept the closing one, so its
  // own headline case rendered as "3**x cheaper".
  test("bold-digit-suffix bolds the 3 and leaves no stray asterisks", async ({ page }) => {
    const shape = await renderBlock(page, "bold-digit-suffix");
    expect(shape.strongs).toEqual(["3"]);
    expect(shape.text).toContain("x cheaper");
    expect(shape.text).not.toContain("*");
  });

  // Bold noun + particle is the ordinary shape in Japanese; the same
  // neighbour rule broke it.
  test("cjk-bold-particle bolds the noun and keeps the particle", async ({ page }) => {
    const shape = await renderBlock(page, "cjk-bold-particle");
    expect(shape.strongs).toEqual(["重要"]);
    expect(shape.text).toContain("なポイント");
    expect(shape.text).not.toContain("*");
  });

  test("shell-pipeline keeps its pipes and is not a table", async ({ page }) => {
    const shape = await renderBlock(page, "shell-pipeline");
    expect(shape.tables, "a line with pipes is not a table").toBe(0);
    // The abandoned branch's server-side stripper flattened this to
    // "cat access.log grep 500 wc -l" — the product showing a command that
    // does not do what it says.
    expect(shape.text).toContain("cat access.log | grep 500 | wc -l");
  });

  test("prose-pipes-alternation is prose, not a table", async ({ page }) => {
    const shape = await renderBlock(page, "prose-pipes-alternation");
    expect(shape.tables).toBe(0);
    expect(shape.text).toContain("a|b|c");
  });

  test("varargs-kwargs survives verbatim", async ({ page }) => {
    const shape = await renderBlock(page, "varargs-kwargs");
    // Genuinely ambiguous: `**kwargs` is an unpaired delimiter, so CommonMark
    // leaves it literal — and so must we. Inventing bold here would state
    // something the model did not write.
    expect(shape.text).toContain("*args");
    expect(shape.text).toContain("**kwargs");
    expect(shape.strongs).toEqual([]);
    expect(shape.ems).toEqual([]);
  });

  test("orphan-bold-severed is left verbatim by the renderer", async ({ page }) => {
    const shape = await renderBlock(page, "orphan-bold-severed");
    // ADR-0014 measured this in BOTH candidate parsers: an unpaired `**`
    // renders literally, which is correct CommonMark. The defect is upstream,
    // in `debate._opening_synopsis`, which cuts raw Markdown at 140 chars — no
    // renderer can pair a marker whose partner the cut removed. Asserted as
    // "unchanged", so this stays true after the server-side fix too.
    expect(shape.text).toContain("**this bold span is severed");
    expect(shape.strongs).toEqual([]);
  });

  test("setext-heading renders a heading, not a row of equals signs", async ({ page }) => {
    const shape = await renderBlock(page, "setext-heading");
    // MEASURED on main before this work: `<p>Summary<br>=======<br>Use
    // pgbouncer.</p>` — the underline was on screen. The corpus labelled this
    // case CORRECT; it was not, and the label is corrected in the same commit.
    expect(shape.headings.map((h) => h.text)).toContain("Summary");
    expect(shape.text).not.toContain("===");
  });

  test("heading-led-answer renders a heading with no # in any text node", async ({ page }) => {
    const shape = await renderBlock(page, "heading-led-answer");
    expect(shape.headings.length).toBe(1);
    expect(shape.headings[0].text).toBe("PostgreSQL Scaling Decision");
    // Demoted, never <h1>: `.q-prose` styles h4/h5/h6 and nothing else, and an
    // <h1> mid-document breaks the heading order the axe lane asserts.
    expect(["H4", "H5", "H6"]).toContain(shape.headings[0].tag);
    expect(shape.text).not.toContain("#");
  });

  // KNOWN GAP, deliberately expressed as an expected failure rather than as a
  // passing assertion of the wrong behaviour. `__init__` is valid CommonMark
  // strong emphasis (GitHub renders it the same way), so the parser bolds it
  // and the underscores are lost. That is UNCHANGED from the hand-rolled
  // renderer — measured on main at e2a39aa, which also produced
  // `<strong>init</strong>` — so it is not a regression, and the corpus's
  // "CORRECT today" label for it was wrong.
  //
  // No syntactic rule separates `__init__` from the golden fixture's intended
  // `__not__` and `__underscore__`, so ADR-0015 records it as accepted with
  // its mitigation (backticks). `test.fail()` means this goes RED the day
  // someone fixes it, which is the reminder a passing test could not be.
  test("dunder-identifier survives exactly (known gap, ADR-0015)", async ({ page }) => {
    test.fail(true, "known gap: __init__ is valid CommonMark strong emphasis (ADR-0015)");
    const shape = await renderBlock(page, "dunder-identifier");
    expect(shape.text).toContain("__init__");
    expect(shape.text).toContain("__repr__");
  });
});

// --- what adversarial review found, and what now stops it coming back --------

test.describe("content the parser would otherwise swallow (review round 1)", () => {
  // RED IF: the `reference` rule is re-enabled. markdown-it CONSUMES a
  // `[1]: https://…` line and emits nothing for it, so an answer whose
  // citations are written in reference style loses them off the screen. An
  // answer made ONLY of definitions renders to "" — which sends `setProse`
  // down its PLACEHOLDER branch, so the product tells the user the model
  // "did not return an opening answer" when it answered with citations.
  //
  // Found by a review lens, not by any gate, and not present in the corpus:
  // no fixture had ever contained a reference definition.
  test("reference-style citations are not deleted from the screen", async ({ page }) => {
    const answer =
      "Summary of sources for the retention question.\n\n" +
      "[1]: https://arxiv.org/abs/1234\n" +
      "[2]: https://example.com/benchmark";
    await driveToResult(page, goldenRespWithProviderText(answer, "block"));
    const shape = await blockShape(page);
    expect(shape).not.toBeNull();
    expect(shape!.text, "the prose must survive").toContain("Summary of sources");
    // The URLs are the content at risk. Both must still be on screen.
    expect(shape!.text).toContain("https://arxiv.org/abs/1234");
    expect(shape!.text).toContain("https://example.com/benchmark");
  });

  test("an answer of ONLY reference definitions is not shown as no answer", async ({ page }) => {
    // The sharp end of the same defect: this rendered to "" and the surface
    // showed its "no answer" placeholder instead.
    await driveToResult(
      page,
      goldenRespWithProviderText("[1]: https://example.com/paper", "block"),
    );
    const shape = await blockShape(page);
    expect(shape!.text).toContain("https://example.com/paper");
    expect(
      shape!.text.toLowerCase(),
      "the product must not claim the model returned nothing when it returned a citation",
    ).not.toContain("no recommendation was recorded");
  });

  // RED IF: the empty-blockquote branch is removed. `>` alone rendered as a
  // <blockquote> with a left border and nothing in it — a visible hollow box.
  // The old formatter dropped it explicitly and the comment saying so went with
  // the code it described.
  test("a bare > does not paint an empty quote box", async ({ page }) => {
    await driveToResult(page, goldenRespWithProviderText("Before.\n\n>\n\nAfter.", "block"));
    const shape = await blockShape(page);
    const quotes = await page.evaluate(
      () => document.querySelectorAll(".result-verdict-text blockquote").length,
    );
    expect(quotes, "an empty blockquote is a hollow box on screen").toBe(0);
    // Positive partner: the surrounding prose must still render, or "no
    // blockquote" would be true of a page that rendered nothing at all.
    expect(shape!.text).toContain("Before.");
    expect(shape!.text).toContain("After.");
  });

  // RED IF: `inlineListMarkers` returns early after stripping a heading marker.
  // "### - alpha bravo" then reaches an INLINE surface as "- alpha bravo" — a
  // raw bullet in a text node, which the BLOCKING gate's own
  // "bullet marker (- / * )" pattern matches. Same shape as deviation 7 on the
  // block path, one surface over; the block path was fixed and this was not.
  test("a heading whose text is a list item leaks no marker on an inline surface", async ({
    page,
  }) => {
    await driveToResult(page, goldenRespWithProviderText("### - alpha bravo", "inline"));
    const cell = page.locator(".result-verdict-caveat").first();
    await expect(cell).toBeVisible();
    const text = (await cell.textContent()) || "";
    expect(text, "the heading marker must not reach a text node").not.toContain("#");
    expect(text, "the bullet marker must not reach a text node either").not.toMatch(
      /(^|\s)[-*]\s/,
    );
    // Positive partner: the words must survive, rendered.
    expect(text).toContain("alpha bravo");
    expect(text, "the bullet must be RENDERED, not deleted").toContain("•");
  });
});

// --- the XSS posture, which is now a CONFIG FLAG and must be pinned ----------

test.describe("XSS posture (`html: false` is the whole defence)", () => {
  const VECTORS: [string, string][] = [
    ["script", "<script>alert(1)</script>"],
    ["img onerror", '<img src=x onerror="alert(1)">'],
    ["svg onload", "<svg onload=alert(1)>"],
    ["iframe", '<iframe src="javascript:alert(1)"></iframe>'],
    ["br with attributes", '<br onload="alert(1)">'],
  ];

  // RED IF: `html` is set true, or removed from MD_OPTIONS so the parser's own
  // default is used. The OLD renderer escaped every character and re-emitted an
  // allow-list; this one escapes by CONFIGURATION, which is a flag guarding a
  // security property — so it gets a behavioural pin, not a comment.
  for (const [name, payload] of VECTORS) {
    test(`a provider answer containing a live ${name} renders inert`, async ({ page }) => {
      await driveToResult(page, goldenRespWithProviderText(payload, "block"));
      const found = await page.evaluate(() => {
        const el = document.querySelector(".result-verdict-text") as HTMLElement;
        const els = [...el.querySelectorAll("*")];
        return {
          rendered: Boolean(el),
          dangerousElements: els
            .filter((e) => ["SCRIPT", "IFRAME", "OBJECT", "EMBED", "IMG", "SVG"].includes(e.tagName))
            .map((e) => e.tagName),
          handlerAttributes: els.flatMap((e) =>
            [...e.attributes].filter((a) => a.name.startsWith("on")).map((a) => a.name),
          ),
          text: el.textContent || "",
        };
      });
      expect(found.rendered).toBe(true);
      expect(found.dangerousElements, `${name} produced live markup`).toEqual([]);
      expect(found.handlerAttributes, `${name} produced an event handler`).toEqual([]);
      // Positive partner: the payload must actually have reached the surface.
      // Without this the three assertions above are all satisfied by a page
      // that rendered nothing at all — the exact vacuous shape this repo has
      // measured in 13 of its own CI jobs.
      expect(found.text, "the payload never reached the rendered surface").toContain("alert(1)");
    });
  }

  test("a javascript: markdown link never becomes an anchor", async ({ page }) => {
    await driveToResult(
      page,
      goldenRespWithProviderText("See [the fix](javascript:alert(1)) for details.", "block"),
    );
    const anchors = await page.evaluate(() =>
      [...document.querySelectorAll(".result-verdict-text a")].map((a) => a.getAttribute("href")),
    );
    expect(anchors, "a javascript: URL must not be linkable").toEqual([]);
    const text = await page.locator(".result-verdict-text").textContent();
    expect(text, "the text must survive even though the link does not").toContain("the fix");
  });

  // The old renderer stripped every C0 control character from a link
  // destination BEFORE testing its scheme, because a browser strips tab/CR/LF
  // before resolving one — so `java\tscript:` would otherwise smuggle a scheme
  // past a naive check. markdown-it defends differently: it PERCENT-ENCODES
  // them. Whether that is equivalent is a claim about the browser, not about
  // the parser, so it is settled by asking the browser.
  //
  // MEASURED here, on the real page: `java&#9;script:alert(1)` becomes
  // href="java%09script:alert(1)" and resolves to
  // `http://<origin>/java%09script:alert(1)` — `%` is not a legal scheme
  // character, so the whole string is a same-origin path. Same for
  // `%6aavascript:` and for the backslash-folded `/\evil.example/x`.
  //
  // RED IF: any obfuscated destination resolves to a non-http(s) scheme.
  test("obfuscated link schemes resolve to http, never javascript", async ({ page }) => {
    const SOURCES = [
      "[a](java&#9;script:alert(1))",
      "[b](java\tscript:alert(1))",
      "[c](%6aavascript:alert(1))",
      "[d](javascript:alert(1))",
      "[e](&#106;avascript:alert(1))",
      "[f](/\\evil.example/x)",
      "[g](//evil.example/x)",
      "[h](vbscript:msgbox(1))",
      "[i](data:text/html,<script>alert(1)</script>)",
    ];
    await driveToResult(page, goldenRespWithProviderText(SOURCES.join("\n\n"), "block"));
    // The link TEXT is the label, and it is unique per case — so it, not the
    // href, is how an anchor is attributed back to the source that produced it.
    const anchors = await page.evaluate(() =>
      [...(document.querySelector(".result-verdict-text") as HTMLElement).querySelectorAll("a")].map(
        (a) => ({
          label: (a.textContent || "").trim(),
          attr: a.getAttribute("href"),
          protocol: (a as HTMLAnchorElement).protocol,
          rel: a.getAttribute("rel"),
        }),
      ),
    );
    const offenders = anchors.filter((a) => !["http:", "https:", "mailto:"].includes(a.protocol));
    expect(offenders, "an obfuscated scheme became a live anchor").toEqual([]);
    // Every anchor that IS emitted must still carry the pair.
    expect(
      anchors.filter((a) => a.rel !== "noopener noreferrer"),
      "an anchor lost rel=noopener noreferrer",
    ).toEqual([]);
    // Positive partner: at least one must render as an anchor, or "no bad
    // protocol" is trivially true of a page holding no links at all.
    expect(anchors.length, "no anchor rendered at all — this proves nothing").toBeGreaterThan(0);
    // The plainly hostile destinations must produce NO anchor whatsoever —
    // "resolves to http:" is not good enough for these, they must not link.
    //
    // `f` — the backslash-folded `/\evil.example/x` — is in this list because
    // LEAVING IT OUT is exactly how the first version of this spec passed while
    // the pre-existing `parity-behavior.spec.ts` failed on the same input. That
    // gate asserts on the resolved HOST; this one asserted only on the resolved
    // SCHEME, and `/%5Cevil.example/x` resolves to `http:` on our own origin,
    // so it sailed through. A sharper gate already existed and mine was the
    // weaker one.
    const linked = new Set(anchors.map((a) => a.label));
    for (const label of ["d", "e", "f", "g", "h", "i"]) {
      expect(linked.has(label), `[${label}] must not be linkable at all`).toBe(false);
    }
    // And the host check itself, not just the scheme: no anchor may carry the
    // attacker's hostname anywhere in its RESOLVED url, even same-origin.
    const origin = await page.evaluate(() => document.location.origin);
    const evil = anchors
      .map((a) => new URL(a.attr || "", origin).href)
      .filter((h) => /evil\.example/i.test(h));
    expect(evil, "an anchor resolved carrying the attacker host").toEqual([]);
    // ...while their TEXT survives unlinked, rather than the content vanishing.
    const text = (await page.locator(".result-verdict-text").textContent()) || "";
    expect(text).toContain("javascript:alert(1)");
    expect(text).toContain("vbscript:msgbox(1)");
  });

  test("an http markdown link keeps rel=noopener noreferrer", async ({ page }) => {
    await driveToResult(
      page,
      goldenRespWithProviderText("See [the playbook](https://example.com/p) for details.", "block"),
    );
    const link = page.locator('.result-verdict-text a[href="https://example.com/p"]');
    await expect(link).toBeVisible();
    // Losing this on a target=_blank link is a silent reverse-tabnabbing
    // regression; the old renderer set both and the new one re-emits them.
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAttribute("target", "_blank");
  });
});

// --- the shapes that leaked, on the surfaces they leaked from -----------------

test.describe("#257 production shapes, seeded into the fixture", () => {
  // RED IF: the fixture stops carrying a table, or the block surface stops
  // rendering one. This is the shape whose ABSENCE from the fixture let 13
  // leaks ship while 196 tests were green.
  test("the seeded production table renders as a table on the result view", async ({ page }) => {
    await driveToResult(page, goldenRespWithMarkdownShapes());
    const verdict = page.locator(".result-verdict-text");
    await expect(verdict.locator("table").first()).toBeVisible();
    const counts = await verdict.evaluate((el) => ({
      tables: el.querySelectorAll("table").length,
      headers: [...el.querySelectorAll("thead th")].map((c) => (c.textContent || "").trim()),
      brs: el.querySelectorAll("br").length,
    }));
    expect(counts.tables, "both seeded tables must render").toBe(2);
    expect(counts.headers).toContain("When it makes sense");
    expect(counts.brs, "the literal <br> in the second table must be a break").toBeGreaterThan(0);
    const raw = (await textNodes(page, ".result-verdict-text")).filter(
      (t) => /\|\s*-{2,}/.test(t) || /<br\s*\/?>/i.test(t),
    );
    expect(raw, "raw table or <br> syntax reached a text node").toEqual([]);
  });

  // #257 §2: an INLINE surface showed a raw `# ` because
  // the answer was flattened onto an INLINE surface, which has no heading rule
  // (an <h*> has no inline equivalent).
  test("a heading-led answer on the INLINE surface leaks no # or *", async ({ page }) => {
    await driveToResult(page, goldenRespWithMarkdownShapes());
    const cell = page.locator(".result-verdict-caveat").first();
    await expect(cell).toBeVisible();
    const shape = await cell.evaluate((el) => ({
      text: el.textContent || "",
      blockChildren: el.querySelectorAll("p,div,ul,ol,h1,h2,h3,h4,h5,h6,table,blockquote").length,
      strongs: [...el.querySelectorAll("strong")].map((s) => s.textContent),
    }));
    expect(shape.text, "the heading marker must not reach a text node").not.toContain("#");
    expect(shape.text).not.toContain("**");
    expect(shape.text).toContain("PostgreSQL Scaling Decision");
    // An inline surface is a <span>; a block child there is invalid markup the
    // browser silently relocates. `renderInline` cannot produce one — this is
    // the assertion that proves the inline path really uses it.
    expect(shape.blockChildren, "an inline surface may not gain block children").toBe(0);
    expect(shape.strongs, "inline emphasis must still work").toEqual(["3"]);
  });

  // The existing axe gate runs on `goldenCompletedResp()`, which has NO table,
  // so it cannot see a table's accessibility at all. The abandoned branch
  // shipped `scrollable-region-focusable` (SERIOUS) for exactly this reason: it
  // added an overflow scroller with no way to reach it from a keyboard.
  test("a rendered table is accessible, scroll container included", async ({ page }) => {
    await driveToResult(page, goldenRespWithProviderText(PRODUCTION_TABLE, "block"));
    await expect(page.locator(".result-verdict-text table")).toBeVisible();
    const results = await new AxeBuilder({ page })
      .include("#main-content")
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(
      serious.map((v) => `${v.id} (${v.impact}): ${v.nodes.length} node(s)`),
      "a table rendered on the result view must not introduce a serious a11y violation",
    ).toEqual([]);
    // Positive partner: the scroll container must actually exist and be
    // focusable, or "no violation" would be true of a page with no table.
    // `.first()`: the recommendation renders on three surfaces of the result
    // view, so a bare locator is a strict-mode violation rather than an
    // assertion. Every one carries the same attributes.
    const scroller = page.locator(".q-table-scroll").first();
    await expect(scroller).toHaveAttribute("tabindex", "0");
    await expect(scroller).toHaveAttribute("role", "group");
    await expect(scroller).toHaveAttribute("aria-label", /.+/);
  });

  // RED IF: a wide table pushes the page sideways instead of scrolling inside
  // its own box. `rendering-invariants` asserts this on a fixture with no
  // table, so it has never been exercised on the one shape that can cause it.
  test("a wide table does not make the page scroll horizontally", async ({ page }) => {
    // 12 columns. `.q-table th/td` carries a 7rem (112px) readability floor, so
    // 12 columns need >=1344px while the result card's prose box measured
    // 1009px at this viewport — comfortably over, without being so far over
    // that a small layout change silently makes this test vacuous.
    const COLUMNS = 12;
    const wide =
      "| " + Array.from({ length: COLUMNS }, (_, i) => `Column heading number ${i + 1}`).join(" | ") + " |\n" +
      "|" + "---|".repeat(COLUMNS) + "\n" +
      "| " + Array.from({ length: COLUMNS }, (_, i) => `a fairly long cell value ${i + 1}`).join(" | ") + " |";
    await driveToResult(page, goldenRespWithProviderText(wide, "block"));
    await expect(page.locator(".result-verdict-text table")).toBeVisible();
    const overflow = await page.evaluate(() => {
      // VISIBLE scrollers only. The recommendation also renders into the
      // model-card grid, which measures 0x0 on the result view (see the golden
      // fixture's own note) — a box with no width can neither scroll nor burst
      // a card, so asserting on it would fail for a reason no user can see.
      const boxes = ([...document.querySelectorAll(".q-table-scroll")] as HTMLElement[])
        .filter((b) => b.clientWidth > 0);
      return {
        pageScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        // EVERY scroller, not the first: the recommendation renders on three
        // result-view surfaces with different flex ancestry, and the
        // `min-width: 0` chain has to hold on all of them.
        boxes: boxes.map((b) => ({
          scrolls: b.scrollWidth > b.clientWidth,
          scrollWidth: b.scrollWidth,
          clientWidth: b.clientWidth,
          // The card the box sits in must not be burst open by its content.
          // This is the failure the page-level check CANNOT see: measured, a
          // flex ancestor reported clientWidth 905 against scrollWidth 1377
          // while the page itself stayed at 1440.
          ancestorOverflow: (() => {
            for (let el = b.parentElement; el; el = el.parentElement) {
              if (el.scrollWidth > el.clientWidth + 1) return el.className || el.tagName;
            }
            return null;
          })(),
        })),
      };
    });
    expect(overflow.pageScroll, "the page must not scroll sideways").toBeLessThanOrEqual(0);
    expect(overflow.boxes.length, "no table scroll container rendered").toBeGreaterThan(0);
    // Positive partner: a table narrow enough to fit would satisfy the line
    // above without the scroll container doing anything at all.
    for (const box of overflow.boxes) {
      expect(
        box.scrolls,
        "the seeded table must actually be wider than its box, or this proves " +
          `nothing (scrollWidth ${box.scrollWidth} vs clientWidth ${box.clientWidth})`,
      ).toBe(true);
      expect(
        box.ancestorOverflow,
        "the table burst its own card open instead of scrolling inside it",
      ).toBeNull();
    }
  });
});
