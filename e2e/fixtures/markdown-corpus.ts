/**
 * MARKDOWN FAILURE CORPUS — the shapes real models emit that this renderer
 * gets wrong, and the shapes it currently gets RIGHT and must not regress.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * On 2026-08-05 the product was driven through one real paid run against four
 * live models (`qr_415a22cb476c4ee3969ed6ed39f0f6bb`). Thirteen raw-Markdown
 * leaks reached the screen in four shapes while all 196 invariant-lane tests
 * stayed green — the golden fixture had never contained those shapes (#257).
 *
 * A fix was attempted (branch `fix/markdown-renderer`, abandoned). Every gate
 * went green and two independent review lenses then found 23 defects in it.
 * ADR-0014 records the decision that came out of that: vendor `markdown-it`
 * and delete the hand-rolled renderer.
 *
 * This corpus is the knowledge from those two rounds, in a form that outlives
 * the abandoned branch. It is DATA, deliberately — no assertions here, so it
 * can be imported by whatever spec the replacement needs without pre-judging
 * how that spec should be written.
 *
 * THE HALF THAT IS EASY TO MISS
 * -----------------------------
 * Thirteen cases below were BROKEN on `main` and seven were CORRECT — and the
 * abandoned branch broke several of the correct ones while fixing the others.
 * A stripper that "removes Markdown" turned `__init__` into `init`, `**3**x`
 * into `3**x`, and destroyed shell pipelines. So this corpus is as much a
 * regression guard as a to-do list, and a replacement that fixes every BROKEN
 * case while breaking a CORRECT one is a net loss.
 *
 * THREE OF THESE NUMBERS WERE WRONG WHEN THIS FILE WAS WRITTEN, and the way
 * they were wrong is the point of the file:
 *   * this paragraph said "Nine ... Eight" beside a footer saying eleven and
 *     nine — a file that exists to hold measurements disagreeing with itself
 *     about its own row count, in prose that nothing checked;
 *   * `dunder-identifier` was labelled CORRECT. Measured on `e2a39aa` by
 *     executing the renderer, `Override __init__ and __repr__` already gave
 *     `Override <strong>init</strong> and <strong>repr</strong>` — the exact
 *     defect the note blames on the abandoned branch was on `main` all along;
 *   * `setext-heading` was labelled CORRECT, with the note "renders acceptably
 *     today". Measured, it gave `<p>Summary<br>=======<br>Use pgbouncer.</p>`
 *     — the row of `=` its own `expected` field forbids.
 * Both labels were arrived at by reading, in a file whose next paragraph says
 * they were arrived at by executing. They are corrected below, and
 * `e2e/tests/invariants/markdown-corpus.spec.ts` — which drives every case
 * through a real browser — is what stops the next one drifting.
 *
 * HOW THE `current` FIELD WAS PRODUCED
 * ------------------------------------
 * Measured by extracting `formatAnswerText` and its helpers from `app.js` and
 * running each input through them, then walking the output's text nodes for
 * raw markers. Not read off the code, and not inherited from the abandoned
 * branch's own claims — several of those were themselves refuted. First done
 * on `597fc35`; RE-DONE on `e2a39aa` when this file was wired to a spec, which
 * is when two of the labels turned out to be wrong (see above). The re-run is
 * the reason the `current` field is trustworthy now and was not before.
 *
 * Re-derive rather than trusting this file: the whole reason #257 exists is
 * that a green suite is not evidence about a shape it never renders.
 */

export type CorpusCase = {
  /** Stable id, usable as a test title. */
  readonly id: string;
  /** The raw provider text, exactly as a model would emit it. */
  readonly input: string;
  /** What a user must see. Plain English, not an assertion. */
  readonly expected: string;
  /** MEASURED on `e2a39aa` by EXECUTING the hand-rolled renderer, not reading it. */
  readonly current: "BROKEN" | "CORRECT";
  /** Why this case is in the corpus. */
  readonly note: string;
};

/**
 * Tables. NINE cases, and on `e2a39aa` **every one of them renders zero
 * `<table>` elements** — `formatAnswerText` has no table branch at all, so
 * pipe rows fall through to the paragraph buffer. In the live run this put 8
 * paragraphs of raw `|---|` on screen; the page's only `<table>` was app
 * chrome.
 */
export const TABLE_CASES: readonly CorpusCase[] = [
  {
    id: "gfm-table-production-shape",
    input:
      "| Option | When it makes sense |\n" +
      "|--------|--------------------|\n" +
      "| Scale vertically | CPU headroom exists |",
    expected: "a real <table> with one header row and one body row",
    current: "BROKEN",
    note: "the exact shape two of four live models emitted for a comparison question",
  },
  {
    id: "gfm-one-dash-separator",
    input: "| A | B |\n|--|--|\n| 1 | 2 |",
    expected: "a real <table>",
    current: "BROKEN",
    note: "GFM requires only ONE dash; the abandoned fix demanded three and missed this",
  },
  {
    id: "gfm-pipe-less-table",
    input: "Name | Age\n--- | ---\nAda | 36",
    expected: "a real <table>",
    current: "BROKEN",
    note: "leading/trailing pipes are optional in GFM; the abandoned fix required a leading one",
  },
  {
    id: "gfm-centered-separator",
    input: "| A | B |\n|:-:|:-:|\n| 1 | 2 |",
    expected: "a real <table>, alignment need not be honoured",
    current: "BROKEN",
    note: "the `:-:` alignment forms are common and were also missed",
  },
  {
    id: "escaped-pipe-in-cell",
    input: "| Op | Meaning |\n|---|---|\n| \\| | the pipe char |",
    expected: "a <table> whose first body cell contains a literal | and whose second reads 'the pipe char'",
    current: "BROKEN",
    note: "the abandoned fix split on every pipe, dropping 'the pipe char' entirely — CONTENT LOSS",
  },
  {
    id: "over-wide-body-row",
    input: "| A | B |\n|---|---|\n| 1 | 2 | 3 |",
    expected: "no cell is silently discarded",
    current: "BROKEN",
    note: "the abandoned fix padded short rows but TRUNCATED long ones, deleting '3' — CONTENT LOSS",
  },
  {
    id: "header-row-no-separator",
    input: "| Option | Note |\n| Scale up | fine |",
    expected: "not a table; the words survive as ordinary prose, with no raw pipe skeleton on screen",
    current: "BROKEN",
    note: "ungated in the abandoned fix — its only table spec always supplied a separator",
  },
  {
    id: "table-in-fenced-code",
    input: "Here is the syntax:\n```\n| A | B |\n|---|---|\n| 1 | 2 |\n```\nDone.",
    expected: "the table syntax is shown VERBATIM — the user asked how to write one",
    current: "BROKEN",
    note: "there is no fenced-code branch at all; the abandoned fix made this worse by eating the separator row",
  },
  {
    id: "literal-br-in-cell",
    input: "| A |\n|---|\n| one <br> two |",
    expected: "a line break inside the cell, and no visible '<br>' text",
    current: "BROKEN",
    note: "6 occurrences reached the screen live; models use <br> to get two lines into one cell",
  },
] as const;

/**
 * Emphasis and prose. FOUR are BROKEN on `main` (`orphan-bold-severed`,
 * `varargs-kwargs`, `dunder-identifier`, `setext-heading` — the last two were
 * mislabelled CORRECT until they were re-measured); the other seven are
 * CORRECT and **were broken by the abandoned fix**. Treat those seven as a
 * regression guard with at least as much weight as the fixes above.
 */
export const EMPHASIS_CASES: readonly CorpusCase[] = [
  {
    id: "orphan-bold-severed",
    input: "and **this bold span is severed",
    expected: "no raw ** on screen",
    current: "BROKEN",
    note:
      "MEASURED: a real parser does NOT fix this — an unpaired ** renders literally in both " +
      "markdown-it and marked, which is correct CommonMark. The defect is upstream, in " +
      "debate._opening_synopsis, which cuts raw Markdown at 140 chars so a cut can sever a span. " +
      "Fix it there, not in the renderer (ADR-0014).",
  },
  {
    id: "varargs-kwargs",
    input: "Pass *args and **kwargs straight through.",
    expected: "'*args' and '**kwargs' survive verbatim — they are Python, not emphasis",
    current: "BROKEN",
    note: "leaks ** today; genuinely ambiguous, and a parser leaves it literal too. Protect it inside backticks.",
  },
  {
    id: "bold-digit-suffix",
    input: "Vertical scaling is **3**x cheaper than sharding here.",
    expected: "bold '3', then 'x cheaper' — and NO stray **",
    current: "CORRECT",
    note: "the abandoned fix's two-sided neighbour rule deleted the opening ** and kept the closing one → '3**x cheaper'",
  },
  {
    id: "cjk-bold-particle",
    input: "**重要**なポイントは接続プールです。",
    expected: "bold 重要 followed by the particle, no stray **",
    current: "CORRECT",
    note: "bold noun + particle is the normal shape in Japanese; the abandoned fix broke it the same way as above",
  },
  {
    id: "dunder-identifier",
    input: "Override __init__ and __repr__ in the subclass.",
    expected: "'__init__' and '__repr__' survive EXACTLY",
    current: "BROKEN",
    note:
      "MEASURED on e2a39aa: `main` ALREADY gives '<strong>init</strong>' and '<strong>repr</strong>'. " +
      "This case was labelled CORRECT and blamed on the abandoned fix; both halves were wrong. " +
      "It is valid CommonMark strong emphasis (GitHub renders it identically), and no syntactic " +
      "rule separates it from the golden fixture's intended `__not__` / `__underscore__`. " +
      "ADR-0015 accepts it, with backticks as the mitigation; markdown-corpus.spec.ts marks it " +
      "`test.fail()` so it goes RED the day someone fixes it.",
  },
  {
    id: "arithmetic-spaced",
    input: "Costs 5 * 3 dollars per node.",
    expected: "'5 * 3' survives; no emphasis is invented",
    current: "CORRECT",
    note: "a deliberate CommonMark deviation already argued through review — do not regress it",
  },
  {
    id: "arithmetic-unspaced",
    input: "total 3*40 and 2*12 per year",
    expected: "no emphasis is invented across the two asterisks",
    current: "CORRECT",
    note: "measured previously as 'total 3<em>40 and 2</em>12' before the word-boundary guards were added",
  },
  {
    id: "prose-pipes-alternation",
    input: "Use the a|b|c delimiter form.",
    expected: "ordinary prose; NOT a table",
    current: "CORRECT",
    note: "'the line has pipes' is not a table test — this is what that mistake would break",
  },
  {
    id: "shell-pipeline",
    input: "run: cat access.log | grep 500 | wc -l",
    expected: "the command survives with its pipes intact",
    current: "CORRECT",
    note: "the abandoned fix's server-side stripper flattened it to 'cat access.log grep 500 wc -l' — the command shown was WRONG",
  },
  {
    id: "setext-heading",
    input: "Summary\n=======\nUse pgbouncer.",
    expected: "a heading, or plain text — but no row of '=' on screen",
    current: "BROKEN",
    note:
      "MEASURED on e2a39aa: '<p>Summary<br>=======<br>Use pgbouncer.</p>' — the underline IS on " +
      "screen, so the 'renders acceptably today' label was wrong. No marker pattern covers setext, " +
      "which is why nothing caught it. FIXED by ADR-0014's parser, which renders a real heading.",
  },
  {
    id: "heading-led-answer",
    input: "# PostgreSQL Scaling Decision\n\nBased on your profile, do not shard yet.",
    expected: "a heading element; no '#' in any text node",
    current: "CORRECT",
    note:
      "correct in the BLOCK renderer. It leaked live via the INLINE path instead: " +
      "debate._opening_synopsis flattens this answer to one line and app.js routes it " +
      "through setInlineProse, which has no heading rule because an <h*> has no inline equivalent.",
  },
] as const;

/** Every case, for a spec that wants to sweep the lot. */
export const MARKDOWN_CORPUS: readonly CorpusCase[] = [
  ...TABLE_CASES,
  ...EMPHASIS_CASES,
] as const;

/**
 * Counts RE-MEASURED on `e2a39aa` by executing the renderer, not by reading it.
 * Stated as data rather than prose so a reader can check them:
 * `MARKDOWN_CORPUS.filter(c => c.current === "BROKEN").length`.
 *
 *   20 cases: 13 BROKEN, 7 CORRECT.
 *
 * The constant was renamed from `CORPUS_BASELINE_597FC35` because the numbers
 * in it changed: two cases labelled CORRECT were not (see the header). Keeping
 * the old name over new values would have made the SHA in it a lie.
 *
 * Zero `<table>` elements are produced for any of the nine table cases.
 */
export const CORPUS_BASELINE_E2A39AA = {
  total: 20,
  broken: 13,
  correct: 7,
  tablesRendered: 0,
} as const;
