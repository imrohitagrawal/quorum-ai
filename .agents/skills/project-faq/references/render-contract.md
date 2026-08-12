# Render contract — how a repo page becomes a visually faithful page on any target

This is the shared standard that lets one repo-first source publish to more than one destination (a
wiki, an educational portal) while keeping the same visual language. Most sources are Markdown; two
skills produce a finished HTML page instead (the FAQ always, and the usage guide when it chooses an
HTML page) — this contract handles both. It sits beside `house-style.md`: the house style governs
*how you write*; this contract governs *how that writing is rendered* when a separate publish step
mirrors it out.

**Read this with two facts in mind.**

1. **The repository is the source. The target is a mirror. Never author in the target.** Every
   authoring skill writes its source to the repo first — Markdown for most, a finished HTML page for
   the FAQ and an HTML usage guide; the `publish-mirror` skill renders it out. This file is what
   `publish-mirror` follows.
2. **The promise is semantic fidelity with declared graceful degradation — not pixel parity.** A
   wiki has expand macros, panels, a layout engine, and status lozenges. A bare portal may have
   none of these. You cannot promise the same picture everywhere. You *can* promise that the meaning
   survives and that every drop is a **named, deliberate fallback**, never a silent loss. Each
   adapter below declares what it renders and what it degrades to. The publish-reviewer checks the
   *degraded* result that actually shipped, not an imagined ideal.

---

## 1. The seam: a small set of source primitives

The authoring skills already emit a fixed, small vocabulary of renderable primitives in Markdown.
That fixed vocabulary is the seam — the publisher renders these and nothing else, so adding a target
never means changing how anything is authored. The primitives:

| # | Source primitive (in Markdown) | What it means |
|---|---|---|
| P1 | `# H1` and heading order | one title, sensible heading levels |
| P2 | Stamp block (blockquote: reading time · last-reviewed) | page freshness furniture |
| P3 | "On this page" one-line table of contents | in-page navigation |
| P4 | Collapsible `details` / `summary` block | optional depth, hidden by default |
| P5 | Bold-label callout blockquote (*Key idea / Tip / Try it / In plain words / Status*) | a highlighted aside |
| P6 | Honesty markers: `[designed, not yet built]`, "proposed, not yet locked", the global honesty panel | built-vs-designed truth |
| P7 | Diagram: themed Mermaid / Structurizr / Excalidraw **source** + exported PNG/SVG + alt text | an explanatory picture |
| P8 | Animated GIF (one per owning topic) + static PNG fallback + alt text | motion where it adds meaning |
| P9 | Comparison table | side-by-side facts |
| P10 | Two-column layout (only where the source marks it) | paired content |
| P11 | Status state (a state word: To Do / In progress / Done) | a single-word state badge |
| P12 | Fenced code block | code or config, verbatim |
| P13 | Relative cross-link to a sibling page | navigation between pages |
| P14 | Licence footer line, optional watermark | required credit + optional decorative credit |

If an authoring skill ever needs a new visual, add a primitive here first, then teach every adapter
to render it. Do not invent target-only formatting inside the publisher.

**Two primitives carry a machine-readable form the verifier reads — keep the exact shape:**

- **P2 last-reviewed stamp (single canonical format).** The freshness stamp carries the last-reviewed
  date as an **ISO `YYYY-MM-DD`** value, surfaced as a `<meta name="last-reviewed" content="YYYY-MM-DD">`
  in an HTML page, or a visible `Last reviewed: YYYY-MM-DD` line in either format. `verify.py` reads
  this for its staleness check and **WARNs** when the date is older than the threshold (CLI
  `--max-age-months` > profile `max_doc_age_months` > 6) or is in the future; an absent stamp is an
  INFO nudge, never a failure. This is the **one** stamp format — do not invent a second.
- **P14 licence footer (a generator-level guarantee, not just an adapter row).** Any tool that emits a
  finished HTML page (the FAQ generator; any future HTML generator) **must render the `©` licence
  footer**, not only the decorative watermark — the watermark never satisfies the footer
  (`licensing-and-credits.md` Section 2). `verify.py` is the deterministic backstop: it **FAILS** a
  public page, or an internal document set, that carries no `©`. So the rule has one written home here
  and one enforcement point in the verifier; a new HTML generator inherits both without restating them.

---

## 1a. Two source kinds: Markdown primitives, or a finished HTML page

A source file is one of two kinds, and `publish-mirror` picks the path from the file extension (an
explicit `source_format` in the manifest overrides it — the file extension is unambiguous, so the
flag is only for forcing a path):

- **Markdown source (`.md`, the default).** Carries the primitives in Section 1. The publisher maps
  each primitive to the target through the adapter in Section 2. This is the path for learning-track,
  architecture-and-decisions, operations-runbook, and onboarding-companion.
- **Finished HTML page (`.html`).** The FAQ (always HTML) and the usage guide (when it chooses an
  HTML page) are already rendered — the primitives are baked into HTML structures (tabs, a sidebar,
  expand/collapse, callouts). Publishing one is **optional**; when the owner wants it, the publisher
  does **not** re-derive primitives. It maps the page to the target like this:
  - **To a portal that hosts HTML — the faithful target.** The page is published close to as-is; its
    structure, styling, and interactivity (tabs, keyboard navigation) survive. This is the natural
    home for an interactive FAQ.
  - **To a wiki such as Confluence — a lossy target, and you say so.** A wiki does not run a page's
    own CSS or JavaScript, so the interactivity does **not** survive. The publisher degrades the page
    to native structure: each tab or section becomes a heading, callouts become panels, comparison
    content becomes tables, and the Q&A text is preserved in full. The meaning survives; the tabbed
    interaction does not. State this on the page so no one expects the live widget on the wiki.

The held-constant rules in Section 3 (palette, accessibility, honesty markers, the licence footer)
and the publish-reviewer in Section 4 apply to **both** source kinds.

---

## 2. Adapters: how each Markdown primitive renders per target

This section is the **Markdown-source path** (Section 1a covers a finished HTML page). Each target
type is an **adapter** — the only place that knows a target's idiom. Build an adapter when its target
is real; mark the rest `[designed, not yet built]` in the manifest.

### 2a. Confluence adapter (built — this is the proven mapping)

| Primitive | Renders as | Fallback / note |
|---|---|---|
| P1 H1 | the page title (plain-text field) | title uses a literal `&`, never `&amp;` |
| P2 stamp | a short **info panel** at the top | — |
| P3 TOC line | the **Table of Contents** macro | — |
| P4 details | the **Expand** macro | — |
| P5 callout | **info / note / success panel**, with the built-in panel icon | the icon is the non-colour cue |
| P6 honesty | inline text kept verbatim; the global panel becomes a **note panel** | never drop the marker |
| P7 diagram | **export to PNG/SVG and attach as an image**; embed with alt text | Confluence does not reliably render diagram source — image is the faithful fallback |
| P8 GIF | attach and embed, with alt text and the PNG beside it | — |
| P9 table | a native table | — |
| P10 two-column | the Confluence **layout** (two columns) | collapses to stacked on narrow screens |
| P11 status | a **status lozenge** (`status` macro) | needs `content_format: html` — markdown round-trips corrupt the lozenge |
| P12 code | a code block macro | — |
| P13 link | resolved to the target page's URL via the manifest binding | — |
| P14 footer | the licence line as a small footer panel; watermark on exported images only | the © footer is required; the watermark does not replace it |

### 2b. HTML-portal adapter (designed, not yet built — the shape a generic target follows)

A portal usually has no macros and no layout engine. The adapter renders to clean, accessible HTML
and degrades on purpose:

| Primitive | Renders as | Declared degradation |
|---|---|---|
| P2 stamp / P5 callout / P6 panel | a styled `aside`/`div` carrying an **icon + a text label** | if the portal strips classes, the **bold text label still names it** (the non-colour cue) |
| P3 TOC | an anchored list built from the headings | — |
| P4 details | the native HTML `details` element | if unsupported, render open with a bold heading — depth is never hidden-and-lost |
| P7 diagram / P8 GIF | the exported image with `alt` (and the PNG for the GIF) | same image-first rule as the wiki |
| P10 two-column | a CSS grid; **single column on narrow screens** | content order is preserved when it collapses |
| P11 status | a small labelled badge (`text` + shape), never colour alone | a bracketed word if styling is stripped |
| P14 footer | the © footer line in the page body | required; the optional watermark is decorative only |

The rule the portal adapter exists to enforce: **whatever the portal cannot style, the meaning still
reads in plain text.** That is the floor every adapter clears.

---

## 3. What every adapter must hold constant (the visual language)

These come from `house-style.md` Section 7 and travel with the content to *every* target:

- **One palette.** Identity/chrome uses the profile palette (indigo / green / slate). Diagrams use
  colour-with-meaning paired with a label or icon. Categorical data uses a colour-blind-safe palette
  (Okabe–Ito) with direct labels — never the brand palette and never colour alone.
- **Accessibility is not negotiable and not target-specific.** Every diagram and GIF carries alt
  text and a static fallback; contrast passes WCAG 2.2 AA; meaning is never carried by colour alone
  (✓/✗ plus a word); HTML output has one `h1`, a sensible heading order, a `lang` attribute, and
  link text that makes sense out of context.
- **Exported images carry the credit furniture.** The watermark (profile `watermark`, 18–30%
  opacity, in whitespace, never overlapping content) and a thin inset slate border go on the
  *exported* image — never on the diagram source.
- **Honesty markers survive the mirror.** `[designed, not yet built]` and "proposed, not yet locked"
  render verbatim on every target. A mirror that quietly makes an unbuilt thing look shipped has
  failed, regardless of how it looks.

---

## 4. The publish-reviewer (runs after every write, on every target)

A write does not count until the reviewer passes on the artifact that actually shipped:

- Plain-text fields (titles) carry a literal `&` — no `&amp;`, `&lt;`, or other literal entities.
- No banned flowery words; (public scope) no internal-reference or tool-name leaks; no author intent.
- Every macro / panel / element renders; every link resolves; images are attached and showing.
- The artifact landed at the **right coordinates** (the correct space/parent/collection from the
  manifest) and updated the **bound id**, so it is an update, not a duplicate.
- The scope-appropriate licence credit survived the mirror: on a **public** page the `©` licence
  footer is present (a hard failure if it is missing); on an **internal** document the short copyright
  line or credits block is present (`licensing-and-credits.md` Sections 1–2). A watermark never
  satisfies this.

Report PASS/FAIL with the exact line at fault; block the write on FAIL.

---

## 5. The one rule that keeps this scalable

Adding a target is: write one adapter (Section 2) and one `targets` entry in the manifest. The
authoring skills, the source primitives (Section 1), and the held-constant visual language
(Section 3) do not change. If you find yourself editing an authoring skill to make a target look
right, stop — the fix belongs in this contract or in the adapter, not in how the page is written.
