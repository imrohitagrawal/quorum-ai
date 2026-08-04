# ADR-0011: block structure belongs to the block renderer, and an inline surface renders the marker instead

## Status

Accepted — 2026-08-04 (issue #120).

## Context

`app.js` has two prose renderers with different contracts:

- `setProse` → `formatAnswerText` — block content, for `<div>` containers.
  Handles headings, paragraphs, blockquotes and lists.
- `setInlineProse` → `mdInline` — documented at the call site as
  "INLINE-only … no block structure … for single-line span/cell/caption
  surfaces where block tags would be invalid."

Issue #120 reported that the blockquote path and the inline path had no list
handling. Both halves were confirmed by driving the real browser against the
real `app.js` at `2ba0519`, whose bundle is **byte-identical to the deployed
one** (`curl https://quorum-ai.fly.dev/static/app.js` → 388209 bytes,
`diff -q` clean). The defect was LIVE, not latent.

### Measured on `2ba0519`, before any change

Input is markdown a provider emits routinely — a quoted set of steps, and a
caveat list in a caption.

| Surface | Input class | Rendered before |
|---|---|---|
| `blockquote` | ordered list | `Steps to follow:<br>1. Instrument…<br>2. Then enable…` — **`ol: 0`**, both markers survive as literal text |
| `blockquote` | 2 consecutive bullets | **`ul: 2, li: 2`** — one single-item `<ul>` per line |
| `.result-source-support` (`<p>`) | bullet list | `Caveats:\n<ul><li>verify the cost figure</li><li>keep the cap</li></ul>` — **a `<ul>` inside a `<p>`** |
| `.result-trust-caption` | ordered list | `Open items:\n1. cohort definition\n2. export gate` — raw markers, raw newlines |
| whole `#main-content` | — | **4** text nodes matched the blocking gate's own `ordered-list marker (1. )` pattern |

### After

| Surface | Rendered after |
|---|---|
| `blockquote` (the FIRST one — the counts below are per-blockquote, where the Before rows were whole-answer) | `<p>Steps to follow:</p><ol><li>…</li><li>…</li></ol><ul><li>…</li><li>…</li></ul>` — **`ol: 1, ul: 1, li: 4`**; whole-answer after round 2 is `ol 2, ul 1, li 6`, the second `<ol>` being the `start="4"` quote |
| `.result-source-support` | `Caveats:<br>• verify the cost figure<br>• keep the cap` |
| invalid nesting (`ul`/`ol` inside `span`/`p`) | `["UL inside <p> (result-source-support)"]` → **`[]`** |
| raw ordered-marker text nodes | **4 → 0** |
| quoted list opening at `4.` | `<ol start="4">` — `ol.start === 4`, not renumbered to 1 |
| prose soft-wrapping onto `12.` | left as prose on BOTH paths (was rewritten to `(12)` by the first version of this fix) |

### The gate was green because nothing exercised it

`e2e/fixtures/golden-run.ts` said so out loud, and it was right:

> "the blockquote and inline-prose paths have no ordered-list handling at all
> (issue #120), so a numbered list in a blockquote would fire this with no fix
> available. **The fixture seeds none — that, and not the pattern, is why this
> is green there.**"

Measured: no inline-surface fixture constant contained a list marker. This is
the vacuous-guard shape AGENTS.md rule 7 names — a negative check that is
trivially true over an input nobody supplied.

## Decision

### 1. A blockquote's body is block content, so it re-enters the block renderer

`flushQuote` calls `formatAnswerText` on the quote's lines instead of joining
`mdInline` output with `<br>`. Quoted lists become real `<ol>`/`<ul>`, whose
numbers live in `::marker` where no text-node walker can see them — which is
precisely why the gate's ordered-marker pattern becomes greenable there.

### 2. The recursion is bounded at 4 levels

`MAX_QUOTE_DEPTH = 4`. Each pass strips one `> ` marker, so an answer of
`">".repeat(n)` would otherwise recurse once per marker. Past the cap the
remaining lines render as inline prose, with any leftover `> ` markers
flattened, so deep nesting degrades instead of overflowing the stack.
An earlier draft called that fallback "the pre-#120 behaviour"; it is not, and
the difference mattered — stripping one level per pass leaves a single `> `,
which the gate's `(^|\n)>\s` pattern matches, where main's `>>>>>` did not.
Measured on a 6-deep quote: 3 gate hits before the flattening, 0 after. Four is chosen as "deeper
than any real quoted exchange, shallow enough to be obviously safe"; it is not
measured against a corpus, and that is stated rather than implied.

### 3. `mdInline` stops emitting a block tag, honouring its own contract

The `<ul>`-emitting rule is deleted. `mdInline` has **five** callers
(`grep -n "mdInline(" app.js`), and each needed checking:

| caller | why it is safe |
|---|---|
| `flushList` | strips the marker before calling |
| `flushParagraph` | can never see a list line — `listMarker` claims it first |
| `flushQuote` | re-enters `formatAnswerText` |
| `setInlineProse` | pre-renders via `inlineListMarkers` |
| **heading branch** | now pre-renders too — an `<h*>` may not hold a `<ul>` either |
| **`flushQuote`'s capped fallback** | now pre-renders, after flattening `> ` |

An earlier draft listed the first four and claimed "no caller lost anything".
Review demonstrated the last two were left leaking a raw marker into a text
node that the blocking gate's own patterns match — `### - alpha` gave a literal
`- `, where main had produced an (illegal but marker-free)
`<h6><ul><li>alpha</li></ul></h6>`. **A superlative hid two live defects**, and
the golden fixture seeds neither shape, so no gate could have caught them.

### 4. An inline surface renders the marker rather than the structure

New `inlineListMarkers()` replaces a leading marker with its rendered
equivalent — `•` for a bullet, `(n)` for a 1–2 digit ordinal — and separates
items with `<br>`. A block renderer moves the marker into presentation
(`::marker`); this does the same thing where `::marker` is unavailable. No raw
markdown reaches a text node, and no ordinal is lost.

It runs **after** `escapeHtml`, not before. Escaping cannot disturb a marker,
and the `<br>` only survives if it is inserted post-escape.

An ordered marker converts only when it opens a list at `1.` or continues one
already open — CommonMark's "may only interrupt a paragraph at 1" rule, the
same one `formatAnswerText` applies.

Only 1–2 digit ordinals match. **This is narrower than the block formatter's own
marker test (`/^\s*\d+\.\s+/`, unbounded digits) and wider than the gate's
pattern (`1.` only) — three different widths.** An earlier draft of this ADR
said it "mirrored both"; review refuted that by execution and the sentence is
corrected rather than softened.

### 5. A list keeps the number the model wrote

`flushList` emits `<ol start="N">` when the first item is not `1.`. An `<ol>`
with no `start` always numbers from 1, and `.q-prose ol` is
`list-style: decimal`, so a procedure the model opened at "4." was **renumbered
on screen** — the product asserting a fact its input never contained, invisible
to every text-node gate because the number lives in `::marker`.

This was latent before #120 (a quoted list never reached `flushList`); making
blockquotes recurse is what exposed it, and adversarial review is what caught
it. Measured: `> 2. Configure the exporter. / > 3. Verify the cap.` rendered as
`1. Configure… / 2. Verify…`.


## Rejected alternatives

**Strip the markers entirely on inline surfaces.** Renders cleanly and is the
smallest change. Rejected because it silently deletes the sequence, and this
codebase has already paid for exactly that failure once — a soft wrap onto
`2025.` was parsed as a list marker and the year deleted. Deleting content that
no raw-marker gate can see is the worst available outcome.

**And the suite could not tell the difference.** Adversarial review built this
rejected alternative — plus a stricter one that deletes bullets too — and
measured that **all four of the first round's e2e tests and all 17 unit tests
stayed green against both**. The suite asserted that no RAW marker survives and
nothing asserted that a RENDERED one appears: a negative check with no positive
partner, inside the gate written to close a rendering issue. The three
`#120 round 2` tests are that partner, and each was proved to kill the mutant
it exists for.

**Change the inline containers to `<div>` and use `setProse`.** This is
arguably the *correct* product answer: `.result-source-support` being a `<p>`
is what makes legal list markup impossible. Rejected for this PR because it is
a template + CSS change that would move rendered pixels, and the blocking
visual-snapshot lane's **Linux baselines can only be seeded in CI**
(`.github/workflows/seed-visual-baselines.yml`) — so it cannot be verified
locally. Recorded here as the better long-term shape.

**Add the new shapes to `goldenCompletedResp()`.** Rejected for the same
reason: that builder feeds the visual lane. A dedicated
`goldenRespWithBlockStructure()` gives the rendering gate the shapes while
leaving every baseline pixel untouched.

**Teach `mdInline` to emit `<ol>` as well as `<ul>`.** Rejected: it doubles
down on emitting a tag that is illegal in the target container. The bug was not
"the wrong list tag", it was "a list tag at all".


## Consequences

- Inline surfaces now read `• item` / `(1) item`, one item per line via `<br>`.
  **Correction to an earlier draft**, which claimed the previous appearance
  "came from invalid markup the browser relocated". Review refuted that: the
  `<ul>`'s `parentElement` genuinely was the `<p>` (Chromium's fragment parser
  has no open `<p>` to close during an `innerHTML` assignment), so the markup
  was invalid but rendered correctly as a stacked list. The first version of
  this fix therefore shipped a real appearance regression — 88px stacked down
  to 20px run-on, now 61px — because a bare newline collapses under
  `white-space: normal`. The `<br>` separator restores stacking, so the markup
  is fixed *and* the appearance is kept.
- `tests/unit/test_mdinline_bullets.py` was rewritten. Two of its tests asserted
  `"<ul>" in app_js_text` over the **whole file**; measured, both still passed
  after the rule was deleted from `mdInline` entirely. They were replaced with
  function-scoped, comment-stripped checks that ship positive partners.
- A JavaScript comment stripper now lives in that test file. `tests/code_text.py`
  strips `#` comments only, and the comments here discuss `<ul>` at length, so
  an unstripped check would match the explanation instead of the code.
- The fenced-code gap is **not** fixed here and is not in #120's scope:
  `formatAnswerText` has no fence branch, so list-shaped lines inside a
  ``` fence are consumed as real list items. `<pre>` is constructed nowhere in
  `app.js`. Filed separately rather than folded into this diff.
