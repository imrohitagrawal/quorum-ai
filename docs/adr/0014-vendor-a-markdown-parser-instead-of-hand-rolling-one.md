# ADR-0014: Vendor `markdown-it` instead of hand-rolling the renderer

## Status

Proposed — 2026-08-05 (live-validation session; issue #257)

## Context

`app.js` renders provider Markdown with a hand-written renderer: `formatAnswerText`
(**243 lines**) for block structure and `mdInline` plus its inline helpers
(**206 lines**). It was built incrementally, each round fixing what the previous
round's real output revealed.

On 2026-08-05 the product was driven through one real paid run against four live
models (`qr_415a22cb476c4ee3969ed6ed39f0f6bb`). **13 raw-Markdown leaks reached
the screen in 4 distinct shapes** while all 196 invariant-lane tests stayed
green — the golden fixture had never contained those shapes. Worst of them:
Markdown **tables were not rendered at all**. There were 8 paragraphs of raw
`|---|` on the page and exactly one `<table>`, which was app chrome. The
question invited a cost comparison; two of four models answered with a table.

A fix was written (branch `fix/markdown-renderer`, unmerged). It added a table
branch, a plain-text synopsis stripper and a `<br>` rule; every gate went green;
and **two independent adversarial review lenses then found 23 defects in it** —
content loss (`\|` escapes dropped, over-wide rows truncated, shell pipelines
destroyed), an `axe` *serious* accessibility regression, two vacuous assertions
in one new test, and the fix's own headline case still broken
(`**3**x cheaper` → `3**x cheaper`).

That is the third session to fight this renderer. AGENTS.md rule 12 says: *"if
two fixes in a row add defects, change the approach."* Both of this session's
packages came back with double-digit self-inflicted defects (13, then 23). The
trigger has fired.

The defects are not carelessness. They are Markdown's long tail — GFM one-dash
separators, pipe-less tables, `\|` escapes, CJK emphasis boundaries, setext
underlines, fenced blocks, unpaired delimiters. A regex renderer meets that tail
one production incident at a time.

## Decision

**Vendor `markdown-it` (MIT), configured `html: false`, and delete the
hand-rolled block/inline renderer.**

Vendoring follows a pattern this repo already has. `src/product_app/static/vendor/`
holds Swagger UI under a documented policy: a provenance table (upstream,
version), pinned SHA-256 checksums, a refresh script, unit tests asserting
same-origin URLs, and an e2e spec (`tests/docs/docs-under-csp.spec.ts`) proving
it renders under the real CSP with zero violations. A parser gets the same
treatment. The CSP is `script-src 'self' 'unsafe-inline'`, so a same-origin
vendored file needs no policy change; there is no build step, and the `dist`
UMD build is self-contained (**0 `require(` calls** — it ran in the spike with
no module resolution at all).

## Measurements (2026-08-05)

Every candidate was driven against the shapes that actually failed in
production, plus the cases review found in the attempted fix. Sizes measured
with `wc -c` / `gzip -c`; behaviour measured by executing each parser.

| | tables (6 forms) | emphasis edge cases (4) | XSS (3 vectors) | raw / gzip |
|---|---|---|---|---|
| hand-rolled (the attempted fix) | **3 of 6 fail** | **4 of 4 fail** | safe | — |
| `snarkdown` 2.0.0 | **0 of 6** — no table support | pass | **UNSAFE** — live `<script>` | 2.1 KB / 1.1 KB |
| `marked` 15.0.6 | **6 of 6** | **4 of 4** | **UNSAFE** — live `<script>`, `<img onerror>`, `javascript:` href | 39 KB / 12 KB |
| **`markdown-it` 14.1.0 (`html:false`)** | **6 of 6** | **4 of 4** | **safe on all 3** | 124 KB / 44 KB |

The six table forms: production shape, one-dash separator (`|--|--|`), pipe-less
GFM (`Name | Age`), centered (`|:-:|`), an escaped pipe in a cell, and an
over-wide body row. The four emphasis cases: `**3**x cheaper`, `**重要**な…`
(bold + particle, ordinary in Japanese), `__init__`, and a shell pipeline
(`cat access.log | grep 500 | wc -l`).

**Two findings the measurement produced that reasoning would not have:**

1. **`marked` is not safe by default.** It is a third the size and passes every
   correctness case — and renders `<script>alert(1)</script>` live, plus
   `<img src=x onerror=…>` and `[click](javascript:alert(1))`. Adopting it
   would require vendoring a sanitiser (DOMPurify) alongside, costing more than
   the size difference and adding a second dependency to the security-critical
   path. `markdown-it` with `html: false` escapes all three by configuration.
2. **A parser does NOT fix the opening synopsis.** An orphan `**` from a
   severed span renders literally in **both** parsers — that is correct
   CommonMark, not a bug. `debate._opening_synopsis` cuts the raw answer at 140
   chars, and truncating Markdown then rendering it can never work, because a
   cut can always sever a span. That fix is server-side, independent of this
   decision, and still required.

## Consequences

- **+44 KB gzipped** on the workspace payload. Accepted: it replaces ~449 lines
  of security-relevant hand-written parsing whose defect rate is measured, not
  speculated.
- **The security posture changes shape.** Today's renderer escapes everything
  and re-emits an allowlist. `markdown-it` with `html: false` escapes raw HTML
  by configuration instead. That is a config flag guarding XSS, so it must be
  pinned by a test that fails if the flag is removed — not left to a comment.
- **Some output will change.** The blockquote-unwrapping and list-`start`
  behaviours in `formatAnswerText` were built for the BLOCKING visual-snapshot
  lane, whose Linux baselines can only be seeded in CI (AGENTS.md 13d/13e).
  Expect to re-seed; prove the diff deliberately rather than
  `--update-snapshots`.
- **The existing gates keep their job.** `rendering-invariants.spec.ts` walks
  the rendered DOM and is agnostic about what produced it, so it guards the
  replacement unchanged — and its fixture must gain the shapes that leaked
  (table, `<br>`, heading-led answer), or it will be as blind to the next
  renderer as it was to this one.
- **`fix/markdown-renderer` is abandoned, not merged.** Its 23 findings are
  recorded in #257 so nothing is lost.
- **New maintenance obligation:** a pinned third-party dependency to refresh and
  watch for advisories, in a repo that currently vendors exactly one.

## Rejected alternatives

**Patch the 23 findings on `fix/markdown-renderer`.** Rejected: it needs a third
review round, breaking rule 12's two-round cap, and would ship a user-facing
renderer with open findings. It also treats the symptom — the next unusual
answer finds the next gap.

**`marked` + DOMPurify.** Rejected: two dependencies instead of one, with the
sanitiser on the security-critical path, to save ~32 KB gzipped. `html: false`
is one flag and one test.

**`snarkdown`.** Rejected outright: 1.1 KB, but no table support at all — it
fails the defect that motivated this — and it renders `<script>` live.

**Keep hand-rolling, but add the missing branches.** Rejected on measured
grounds: 3 sessions, 23 defects in the latest attempt alone, and the failures
are in Markdown's long tail rather than in anything specific to this product.
The renderer has no product-specific behaviour worth preserving that
`markdown-it` cannot express.

**Render Markdown server-side in Python.** Not evaluated. It would move the
problem rather than remove it, and the client already owns every other
rendering concern. Worth revisiting only if the payload cost proves
unacceptable.
