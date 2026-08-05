# ADR-0015: How the vendored Markdown parser is configured

## Status

Accepted — 2026-08-05 (issue #257, implementing ADR-0014)

## Context

[ADR-0014](0014-vendor-a-markdown-parser-instead-of-hand-rolling-one.md) decided
*which* parser to vendor and recorded the measurements behind it. It explicitly
left three things to the implementation, and its "Consequences" section names
them: how the XSS posture is kept now that it is a config flag, what happens to
the visual baselines, and what the invariants fixture must gain.

This ADR records those, plus the deviations from stock `markdown-it` that the
implementation turned out to need. Every one exists because removing it was
MEASURED to break something, and every one is named in `app.js` beside the code.

**Two of ADR-0014's own measurements did not survive re-execution**, which is
why this ADR leads with measurement rather than inheriting:

| ADR-0014 claim | Re-measured on `e2a39aa` | Where |
|---|---|---|
| `markdown-it` passes 4 of 4 emphasis cases, `__init__` among them | `Override __init__ and __repr__` → `<strong>init</strong>` and `<strong>repr</strong>` | node, `markdown-it@14.1.0`, `html:false` |
| `markdown-it` passes 6 of 6 table forms, over-wide body row among them | `\| 1 \| 2 \| 3 \|` under a two-column header renders `<td>1</td><td>2</td>` — the `3` is dropped | same |

Neither is a reason to revisit ADR-0014's choice: the hand-rolled renderer got
`__init__` wrong in exactly the same way (measured on `main`, same output), and
rendered no table at all. But both had to be decided rather than assumed, and
both are decided below.

A third correction, in the other direction: `markdown-it` fixes a case the
corpus had labelled CORRECT. `Summary\n=======` rendered on `main` as
`<p>Summary<br>=======<br>Use pgbouncer.</p>` — the setext underline was on
screen — and now renders a real heading.

## Decision

### 1. `html: false` is pinned by a behavioural test, not a comment

The old renderer escaped every character and re-emitted an allow-list. The new
one escapes raw HTML by CONFIGURATION. That is a one-word flag standing between
a hostile model answer and script execution, so it gets a test that drives the
real browser: `e2e/tests/invariants/markdown-corpus.spec.ts` puts
`<script>alert(1)</script>`, `<img src=x onerror=…>`, `<svg onload=…>`,
`<iframe src="javascript:…">` and `<br onload=…>` through a provider answer and
asserts the rendered DOM contains no script/iframe/object/embed/img/svg element
and no `on*` attribute — with a positive partner asserting the payload text did
reach the surface, so the check cannot pass over a blank page.

**Proven by mutation, not by reading.** Flipping `html: false` to `html: true`
in `app.js` turns **all five** of those tests red. My own run reported four —
`Error: script produced live markup`, `Error: img onerror produced live markup`,
`Error: svg onload produced an event handler`, `Error: iframe produced live
markup` — because I read a truncated grep of the output rather than the count.
A reviewer re-ran the same mutation and got `5 failed`, the fifth being
`a live br with attributes renders inert`. The gate is stronger than I claimed,
and the claim was still wrong. The file was restored from a copy and re-verified
byte-identical.

A cheap source-level companion (`tests/unit/test_mdinline_bullets.py::
test_the_xss_flag_is_configured_off`) also asserts the flag is set, because the
browser check cannot run in the unit lane and the source check cannot see a
second renderer built elsewhere. Neither replaces the other.

### 2. The vendored bytes are pinned by a gate, not by prose

`static/vendor/README.md` has carried a "SHA-256 checksums" block since July.
Measured before this change: `grep -rn "shasum\|sha256" tests/ scripts/ Makefile
.github/workflows/` returned **nothing**. The hashes were documentation, and
ADR-0014 and a handoff both described the arrangement as "pinned", repeating a
property nothing enforced.

`tests/unit/test_vendored_assets_are_pinned.py` now re-computes every hash in
that block, fails on a mismatch, on a pinned file that is missing, and on a
vendored file the block never mentions. It also checks `markdown-it`'s own dist
banner against the version in the provenance table — a checksum proves the bytes
did not change, not that the version number beside them is true.

Proven by mutation: appending one comment line to `markdown-it.min.js` produced
`AssertionError: markdown-it.min.js does not match its pinned checksum` with
both hashes printed. Restored byte-exact from a copy.

### 3. Eight deviations from stock `markdown-it`

Stated as decisions because each one is a place a future reader will ask "why is
it like this?". All live in `buildMarkdownRenderer()` in `app.js`.

| # | Deviation | What removing it does, measured |
|---|---|---|
| 1 | `md.disable(["image"])` | Enables a surface the old renderer never had: remote fetches, `data:` URIs, no CSS, no visual baseline. `![x](u)` degrades to `!` + link — byte-identical to the old link regex on the same input |
| 2 | Headings demoted by 3 (`#` → `<h4>`) | `.q-prose` styles `h4/h5/h6` and nothing else, so an `<h1>` renders at browser-default size inside a card; and an `<h1>` mid-document breaks the heading order the axe lane asserts. The old formatter did exactly this (`h${level + 3}`) |
| 3 | A lone `*` may not emphasise into or out of a word | CommonMark ALLOWS intra-word `*`. Measured on stock: `total 3*40 and 2*12 per year` → `total 3<em>40 and 2</em>12 per year`. The old renderer carried word-boundary guards for this and they survived two review rounds |
| 4 | Literal `<br>` becomes a hard break | With `html: false` it is escaped and shown as the text `<br>`. 6 such occurrences reached a real screen (#257 §3) |
| 5 | `validateLink` delegates to the app's `safeMarkdownHref` | Stock permits some `data:` URLs and has no opinion on protocol-relative `//host`. The `link_open` rule re-emits `rel="noopener noreferrer"`; losing it on a `target="_blank"` link is a silent reverse-tabnabbing regression |
| 6 | A blockquote holding one paragraph keeps its old shape | `markdown-it` always wraps quote bodies in `<p>`, which carries margins and would move pixels in the blocking visual lane. Uses `token.hidden`, `markdown-it`'s own mechanism (the one tight lists use), so no markup is hand-built |
| 7 | A heading whose text starts with a list marker renders the marker | `### - alpha` is, in CommonMark, a heading whose text begins with a hyphen, so a correct parser leaves `- alpha` in the text node — which the BLOCKING gate matches. An `<h*>` may not contain a `<ul>`, so there is no structural answer |
| 8 | A table is wrapped in a focusable, labelled scroll container | A scrollable box that cannot be focused is an axe SERIOUS violation (`scrollable-region-focusable`) — the exact regression the abandoned branch shipped |

Deviation 3 is the one to watch on a version bump: it reaches into
`state.delimiters`, which is `markdown-it` internal API. It must be registered
**before `balance_pairs`**, not before `emphasis` — pairing is decided by
`balance_pairs`, and the emphasis post-processor reads only its result.
Registered in the wrong place the rule runs and changes nothing; that was
measured, and `markdown-corpus.spec.ts` catches it (moving the registration back
to `"emphasis"` turns `arithmetic-unspaced` red).

### 3a. The version is 14.1.1, not the 14.1.0 ADR-0014 named

14.1.0 is covered by a `linkify` ReDoS advisory (GHSA-38c4-r59v-3vqw), fixed in
14.1.1. This app ships `linkify: false`, so it was never reachable — measured on
14.1.0, 40,000 characters of adversarial input took **2,161.8 ms** with
`linkify: true` and **10.9 ms** as configured. The bump is defence in depth
against the day someone decides bare URLs should be clickable.

The consequence worth writing down: **`linkify: false` and `typographer: false`
are SECURITY-relevant settings, not only fidelity ones.** Both were documented
here as rendering choices, and only `html: false` had a pin test. A reviewer
measured the same quadratic blowup for `typographer: true` (746.1 ms vs 14.2 ms).
Treat flipping either as a security change.

Sizes moved with the bump: 123,524 bytes raw / 44,442 gzipped, and
`grep -c "require("` is still 0.

### 4. Two known gaps, accepted rather than papered over

**`__init__` renders as bold `init`.** Valid CommonMark strong emphasis; GitHub
renders it identically. No syntactic rule separates it from the golden
fixture's intended `__not__` and `__underscore__` — both are `__` + `\w+` + `__`
— so any "fix" breaks a real case. Unchanged from `main`, which produced the
same output. The mitigation is backticks. `markdown-corpus.spec.ts` marks the
case `test.fail()`, so it goes RED the day someone does fix it.

**A body row wider than its header loses the excess cell.** GFM behaviour, and
therefore GitHub's and every mainstream renderer's. Deviating means
re-implementing table DETECTION rather than configuring it, which is the exact
failure mode ADR-0014 exists to end — the abandoned branch's `\|`-splitting and
row-truncation defects were both in that code. The spec asserts a
FIX-COMPATIBLE invariant (the surviving cells are right, no pipe skeleton
reaches the screen) rather than pinning the cell count, so a future fix does not
have to fight a test that locked the defect in.

### 5. The visual baselines move, by exactly one nested list

Measured, not predicted — but the FIRST version of this paragraph measured a
SAMPLE and wrote it up as the population, which is the mistake this ADR keeps
warning about. It said "12 of 14 surfaces"; 14 was the list I happened to
enumerate by hand. Two reviewers swept it independently and neither could
reproduce the number: one counted 26 surfaces (25 identical, 1 differing), the
other 50 markdown-bearing provider strings (49 identical, 1 differing). The
counts differ because they enumerated at different granularities; **both agree
on the only thing that matters, and so did my hand sample**:

> Exactly ONE surface of `goldenCompletedResp()` renders differently:
> `result.final_synthesis.disagreement`.

There, the fixture's indented sub-bullet becomes a real NESTED `<ul>` inside the
first `<li>` instead of a flat sibling item. That is the fix, not a regression:
the old code's own comment said "Real nested lists are not built here; a
sub-bullet renders as a flat item."

The second surface the earlier draft named — `QUOTED_ORDERED_AND_BULLETS`,
`&#39;` vs `'` — **is not in `goldenCompletedResp()` at all**. It is set only by
`goldenRespWithBlockStructure()`, which no visual baseline consumes. The
apostrophe difference is real and DOM-equivalent; it just has nothing to do with
the snapshot lane.

Note also that "byte-identical" is after a normalisation that deletes every
newline, which is doing real work: `markdown-it` emits `<br>\n` where the old
formatter emitted `<br>`.

So the Linux baselines need re-seeding via
`.github/workflows/seed-visual-baselines.yml`, and the human-reviewable diff is
one list indent. `--update-snapshots` was NOT used (AGENTS.md 13e — the darwin
baselines are dev-only and fail 8/8 on clean `main` anyway).

### 6. The fixture gains the shapes that leaked

`goldenCompletedResp()` is NOT mutated (AGENTS.md 13d — it feeds the visual
lane). **Two** dedicated builders were added alongside
`goldenRespWithBlockStructure` (an earlier draft said three, counting the string
constants): `goldenRespWithMarkdownShapes()` seeds a production-shaped table, a
table with a literal `<br>`, and a heading-led answer on the INLINE surface it
actually leaked from; `goldenRespWithProviderText()` puts one arbitrary string
on one surface so the whole corpus can be swept without a builder per case.

## Consequences

- **+44 KB gzipped**, accepted in ADR-0014.
- **`app.js` loses 79 lines net**, 8,674 -> 8,595 (`wc -l` on both trees).
  That figure moved twice as this PR was reviewed — it was 142 before review
  round 1 added the comments explaining what the two lenses found. Re-measure
  it rather than quoting this line; the command is in the sentence.
  The five hand-written functions it replaces measured **363 lines** together,
  brace-matched: `formatAnswerText` 234, `mdInline` 92, `inlineListMarkers` 23,
  `applyOutsideTags` 6, `decodeBasicEntities` 8. What goes in is
  `buildMarkdownRenderer` at 163 lines — mostly the comments explaining the
  eight deviations — plus an 11-line `formatAnswerText`, a 16-line
  `setInlineProse` and a 28-line `inlineListMarkers`, the one hand-written
  piece that survives.
  ADR-0014 said "~449 lines" and "`mdInline` plus its inline helpers (**206
  lines**)"; neither reproduces. Measured here by brace-matching each function
  in `git show e2a39aa:src/product_app/static/app.js`, the four inline helpers
  total 129, not 206. Recorded because this ADR's whole point is that inherited
  figures get re-run.
- **The visual-baseline lane must be re-seeded before merge.** That is a CI
  workflow run plus human review of one changed indent; it cannot be done
  locally.
- **A version bump of `markdown-it` needs `markdown-corpus.spec.ts` run**, not
  just the checksum updated: deviation 3 depends on internal API.
- **`inlineListMarkers` survives** as the one piece of hand-written Markdown
  handling, and it must: a `<span>` may not contain a `<ul>`, so an inline
  surface has to render a marker rather than build a structure. It now also
  strips heading markers, which is #257 §2.
- **Five source-text unit tests were deleted**, each argued individually in
  `tests/unit/test_mdinline_bullets.py`'s docstring, because they asserted on
  the text of functions that no longer exist. Each names the browser-level gate
  that carries its guarantee now — and in three cases that gate is strictly
  stronger, because it reads the DOM instead of grepping the source.

### 7. What two adversarial review lenses changed, in one place

Recorded because AGENTS.md rule 11 says to verify every reviewer claim, and
because the pattern is more useful than the list: **every finding below was
found by RUNNING something, and none by any gate in this repo.**

Fixed in the same PR:

| Finding | Why it mattered |
|---|---|
| `md.render()` **deletes** a `[1]: https://…` reference definition | An answer made only of them rendered `""`, so `setProse` showed its "did not return an answer" placeholder — the product stating something false about a model that answered WITH citations. `md.disable(["reference"])` restores `main`'s behaviour exactly |
| The checksum gate used `iterdir()`, not `rglob` | Demonstrated end to end: a hostile `vendor/dist/plugin.min.js` was served 200 same-origin — so `script-src 'self'` permits it — while the gate reported `6 passed` |
| `inlineListMarkers` returned early after a heading marker | `### - alpha bravo` reached an INLINE surface as `- alpha bravo`, which the BLOCKING gate's own bullet pattern matches. Deviation 7 fixed this on the block path only |
| `test_the_checksum_gate_bites` was vacuous | It re-implemented the comparison instead of calling it, so neutering the real assertion left it green. It now drives the shared `_compare` |
| The CDN check had no positive partner | Replacing its regex with one that can never match left it green. It now proves the pattern fires on a synthetic offender |
| A bare `>` painted an empty `<blockquote>` | A visible hollow box. The old formatter dropped it explicitly, and that comment went with the code it described |
| Three files gave three counts for one list | app.js "SIX", README "seven", this ADR "eight". Now checked by `test_doc_gate_consistency.py` Part D3 |

Accepted with the reason written down:

- **A rejected link leaves its raw `[text](url)` on screen.** The old renderer
  degraded it to `text (url)`; `markdown-it` has no hook for a destination its
  `validateLink` refused, so the source stays literal — and the BLOCKING gate's
  `](url)` pattern would match it. Latent: no gated fixture seeds a rejected
  link, and `markdown-corpus.spec.ts` asserts only that no anchor is produced
  and the text survives. Left open rather than answered with more hand-rolled
  parsing at review round 2 (rule 12's two-round cap); the risk is a future
  fixture turning the lane red with no fix to hand.
- **`# of requests: 400` loses its `#` on an inline surface.** That is
  CommonMark — `#` plus a space at a line start IS the heading marker — and the
  block path agrees, rendering `<h4>of requests: 400</h4>`. Both paths treat the
  character as syntax; an inline surface has no heading element to put it in.

Refuted, and worth recording so nobody re-derives them:

- **No exploitable XSS.** One lens ran 9,440 renders (472 payloads × 10 wrappers
  × 2 modes) resolving every emitted `href` with WHATWG `URL()`, plus 8,000 fuzz
  renders: zero dangerous hrefs, zero attribute breakouts, zero unescaped `<`.
  The other ran 27 hand-built vectors independently. Both clean.
- **No reverse-tabnabbing gap.** Every anchor path — inline, reference,
  autolink, relative, `mailto:`, in a table cell, in a heading, in a quote —
  emits `rel="noopener noreferrer"`.
- **No DoS.** The premise that `markdown-it` has no recursion cap is wrong:
  `maxNesting = 100`. `">".repeat(10000)` returns a constant 2,699-byte output
  in 0.5 ms; a 5000×20 table is 88 ms; a 1 MB answer is 5.7 ms.
- **Deviation 3 breaks no legitimate emphasis.** 24 probes; in every case where
  the app diverges from stock `markdown-it`, the OLD renderer produced the
  identical output.

## Rejected alternatives

**Pin `html: false` with a comment and a code review.** Rejected: this repo has
measured 0 of 16 `src/` defects caught by an automated check and 10 of 16 by
review, but a flag guarding script execution is precisely the case where the
cheap mechanical check exists and costs one test.

**Keep the checksum block as prose, like Swagger UI's.** Rejected: the prose had
already been repeated as fact by two documents. AGENTS.md rule 1a — prefer a
check over a corrected sentence.

**Pad over-wide table rows so no cell is lost.** Rejected: it requires
re-implementing table detection to know which lines form a table, escaped pipes
and inline code included. That is the code that produced the abandoned branch's
content-loss defects.

**Set `linkify: true` so bare URLs become links.** Rejected for this PR: the old
renderer did not autolink, the golden fixture contains bare URLs as text, and
turning them into anchors would move the visual baselines for a reason
unrelated to #257. Worth revisiting on its own.

**Render Markdown server-side.** Unchanged from ADR-0014: not evaluated, would
move the problem rather than remove it.
