# ADR-0029: The grounding score counts the citations the reader can see

## Status

Accepted — 2026-08-09.

Extends [ADR-0020](0020-a-verified-badge-must-not-contradict-the-verdict-behind-it.md),
which governs what the trust surface is allowed to claim. This ADR governs the
input to the largest single term in that claim.

## Context

`citation_marker_grounding` carries weight **0.30** in `LAYER_A_WEIGHTS` — the
largest single term in the composite, ahead of `live_ratio` at 0.20. It answers
"what fraction of this answer's inline citation markers actually point at a
source on this run?"

`extract_citation_markers` read **any** `[<digits>]` as an ordinal citation
marker, including brackets inside fenced code blocks and inline code spans.
Source code is full of them.

### Measured on `8ca6a98`, hermetic, $0

An answer whose only brackets are code — a ```` ```python ```` fence containing
`arr = [1, 2, 3]`, `print(arr[1])`, `data = json.loads(raw)[2]`, plus an inline
`` `[3]` `` — against three real sources:

```
extract_citation_markers(answer) -> ['1', '2', '3', '1', '2', '3']
citation_marker_grounding(...)   -> 1.0
```

**A perfect grounding score from zero citations.** Downstream, with all other
signals held good:

| grounding | composite | faithfulness | risk | workspace state line |
|---|---|---|---|---|
| 1.0 (the defect) | 100.0 | `faithful` | `low` | "Structural checks passed — citations were not verified against their sources." |
| `None` (correct) | 100.0 | `partial` | `medium` | "No citation marker on this run could be checked." |
| 0.0 | 70.0 | `unfaithful` | `high` | "The structural checks did not clear this run…" |

So the defect converted the honest *"No citation marker on this run could be
checked"* into the false *"Structural checks passed"*. It also **laundered
fabrication**: one fabricated ordinal `[9]` beside a code fence scored 0.75
instead of 0.0, because the code ordinals diluted it.

**Live in production.** Measured 2026-08-09: `curl -s .../status` returns
`"build_sha":"8ca6a984…"` (= `main`'s tip) and `"judge_enabled":false`. With the
judge off the numeric score is suppressed but the state line renders regardless,
and ADR-0017/ADR-0027 record that the judge will be permanently ON — so this is
a floor, not a ceiling.

### Two rejected attempts, and what they cost

The obvious fix is to strip code before scanning. **Two hand-rolled versions
were built and both were rejected by adversarial review**, each after passing
every merge gate, 100% changed-line coverage, and a full mutation run.

Neither failed at *recognising* code. Both failed at knowing **where a block
ends** — and every such error DELETES a real citation, which destroys an honest
answer's score and simultaneously hides a fabricated ordinal behind the deletion.

| attempt | what it got wrong | measured cost |
|---|---|---|
| 1: thorough line scanner | container-prefixed fences, unclosed fences, whole-answer span pairing | three laundering channels: fabrications scored **1.0** against baselines of 0.5, 0.286 and 0.5; plus a **quadratic** regex — 6987 ms on 32 KB of leading whitespace, on a path that runs on every GET while holding the GIL |
| 2: conservative subset | list items, headings, table rows and CRLF are block boundaries too | an ordinary bullet list with one forgotten backtick lost its real citation (`['1']` → `[]`); CRLF collapsed the whole answer into one block, re-opening attempt 1's defect and laundering its own test from 0.5 to **1.0**; fence scanning was quadratic in unclosed openers (1915 ms at 24 KB) |

Attempt 2 was written *specifically* to be fail-safe, with an explicit rule that
every undecidable case resolves toward not masking. It still shipped both harms,
because it did not know which cases were undecidable.

The pattern is the diagnosis: **a line scanner guesses at block structure and a
parser knows it.** Meanwhile the workspace has been rendering this same provider
text with a real CommonMark parser all along
(`src/product_app/static/vendor/markdown-it.min.js`, tracked in this repo). The
score and the screen were answering "is this bracket code?" with two different
grammars. That disagreement *is* the defect class.

## Decision

**1. The score counts the markers the reader sees as prose, and a real
CommonMark parser decides which those are — all of them.** `_prose_only` parses
the answer and keeps only `inline` token content; fenced and indented code
blocks emit no `inline` token and so never reach the scan. Within each inline
block, the spans blanked are exactly the parser's own `code_inline` children,
located in the RAW source.

**There is no markdown pairing logic left in this module**, and that is the
point. An earlier draft still re-derived code spans by pairing backtick runs of
equal width, and it was wrong in the laundering direction: markdown-it keeps a
per-width backtick scan cache, so an unclosed `[` earlier in a block can stop a
later run from ever closing a span. MEASURED on ``See [the appendix `[99]` for
the raw numbers, and press ` to quote.`` — the browser's own renderer shows
`[99]` as prose in no `<code>` element, the hand-rolled pass masked it away, and
grounding went **0.667 → 1.0** with a fabricated ordinal deleted from the
denominator. On natural prose containing that shape, 180 of 225 sentences lost a
rendered marker.

Spans are masked inside the raw source rather than rebuilt from tokens because
markdown-it NORMALISES an href: `?filter[status]=open` returns as
`?filter%5Bstatus%5D=open`, which no longer matches the run's own source list.

**2. `markdown-it-py` becomes a RUNTIME dependency**, pinned
`>=3.0.0,<5.0` per the C14 upper-bound convention already documented in
`pyproject.toml`. This is the substance of the decision and its main cost: the
production image grows a markdown parser for one predicate. It is accepted
because the alternative — a second, hand-maintained grammar that must agree with
the first — was attempted twice and failed twice, in the direction that makes
the product lie about its own citations.

**3. The parser is configured to match `app.js` exactly**: the `"default"`
preset with `html=False, breaks=True, linkify=False, typographer=False`, then
`.disable(["image", "reference"])` — mirroring `app.js:5589` and `app.js:5636`.
The preset name is load-bearing and was measured: `markdown-it-py` defaults to
`"commonmark"` (tables **off**), the browser to `"default"` (tables **on**).
Taking the Python default scored a table's cells as one paragraph, pairing
backticks across cells and deleting a real citation. Of the options carried
over, only the preset and `.disable([...])` can change extraction; `breaks`,
`linkify` and `typographer` are renderer-side and were measured to change zero
inline token contents. They are set anyway so the two configurations read as one
object.

**4. Code spans are blanked to U+FFFF, not to a space.** A space is what
`_ORDINAL_MARKER_RE` treats as insignificant filler, so blanking to spaces
*manufactures* ordinals that exist neither before nor after: ``[1 `x` ]`` → `[]`
today and with this mask, but `['1']` with a space mask.

**5. An escaped backtick may CLOSE a code span, it may only not OPEN one.** A
backslash stops a run opening a span; CommonMark still lets it close one, and
both markdown-it implementations agree — ``` `x\` y [1] ``` renders
`<code>x\</code> y [1]`. Treating an escaped run as no delimiter at all moved
the closing boundary and deleted every citation after it: on
``Set `C:\Users\` then [1], [2] and [3].`` the answer was `[]` where the reader,
and `main`, both see three.

**6. Parsing is skipped in two cases, and both are bounds rather than
cleverness.**

*By content:* no backtick, no tilde, no tab and no run of four spaces anywhere
in the text. Plain substring tests, deliberately. The first version anchored to
line starts (`(?m)^(?: {4}|\t)`) and was wrong in two measured ways — it missed
indented code inside a blockquote or list item, where the indent follows the
container marker, and it missed lone-CR line endings, because Python's `^`
matches after `\n` while markdown-it also breaks lines on `\r`. Each miss left
the original defect **fully alive**: an answer whose only brackets were quoted
indented code still scored grounding 1.0.

*By length:* above `_PARSE_LIMIT_CHARS = 16_384` the text is scanned raw, which
is exactly what `main` does — never worse, and the residual over-count is a
consequence recorded below. A parser is not free on hostile input and this runs
on every GET of a run while holding the GIL, so the bound is set from the WORST
shape found rather than a typical one. MEASURED (parse only, min of 3) on
`[[[[1` repeated: 67.3 ms at 4 KB, 136.3 at 8 KB, 274.3 at 16 KB, 557.6 at
32 KB — linear, about 2× per doubling. The app requests 2000 tokens ≈ 8000
characters per answer, so 16,384 leaves 2× headroom over anything real while
holding the worst case near 0.27 s, inside the 0.5 s budget this repo's own
linearity gates use. **An earlier draft set this to 32,768**, chosen from a
gentler shape that measured 0.149 s at 32 KB; the adversarial shape measures
557.6 ms there, over budget. The figure was wrong because it was measured on a
shape other than the one it named.

A content guard alone was **not** enough, and that was measured too: the
pre-existing blocking gate
`test_marker_extraction_stays_linear_in_unterminated_link_openers` feeds 488,000
characters of unterminated link openers containing no code delimiter — but
appending **one backtick** defeats a content-only guard and took that payload to
**10.127 s** against a 0.5 s bound. The length bound is what closes it: the same
payload is now 0.004 s.

**7. Inline blocks are joined with a NONCHARACTER, not a newline.**
`_ORDINAL_MARKER_RE` allows whitespace inside a marker, so a newline join let
``Per [1,`` and ``2] more`` meet across an intervening code block and read as the
pair `['1', '2']` — two citations appearing nowhere on screen, manufactured by
the join itself.

**7. A marker inside code is IGNORED, not counted as unresolved.** It matches
what the reader sees: monospace, not a citation. The alternative marks an honest
answer that quotes `arr[1]` as unfaithful/high-risk. A consequence, stated and
accepted: an answer whose fabricated ordinals sit inside a code block — an
unclosed fence, say — scores higher than it would on `main`, because those
ordinals leave the denominator. Measured: `"- Point one [1].\n\n      Extra
detail [2].\n\nDone `x`."` goes 0.5 on `main` to 1.0 here. That is correct
under this ADR's doctrine, not a defect: the reader sees a code block. It is
recorded because three review rounds reported it as a bug, which means the
decision was being made implicitly.

**8. Above the parse bound this module says NOTHING.** It returns no markers, so
the census resolvable count is zero and the surface reads "No citation marker on
this run could be checked". An earlier draft fell back to the raw scan, and that
handed the original defect straight back: MEASURED, the same code-heavy answer
scored grounding `None` at 16,000 characters and **1.0 at 16,385**, from 546
markers every one of which was `arr = [1]` inside a fence. Reverting to a grammar
known to be wrong, to save CPU, is not a trade a trust surface may make.

**9. There is no "probably no code here, skip the parse" fast path.** One
existed and was removed. It returned the RAW text, which also skipped the block
separator, so `"Key findings [1,\n\n2] were reported."` scored two citations
the reader never sees — and whether an answer got the protection depended on
whether it happened to contain an unrelated backtick. Parsing unconditionally
under the bound costs about 3.5 ms on a 16 KB answer.

**10. `markdown-it-py` is pinned EXACTLY**, deliberately breaking the range
convention documented in `pyproject.toml`. `Dockerfile:10` builds with
`uv pip install .`, which resolves from the range and ignores `uv.lock`, while
CI uses `uv sync` and honours it. A grounding score is a pure function of this
parser's tokenisation, so a range lets the first rebuild after any upstream
release change 0.30 of the served trust score for identical answers, with no
code change and no failing test.

**11. `EVAL_SCHEMA_VERSION` moves to `s3-eval-v4`.** The meaning of
`citation_marker_grounding` changed. Evaluations are written once when a run
turns terminal and recomputed on every read, so without a bump a run completed
before this deploy keeps a stored value from the old grammar while its own
result page serves the new one — two numbers for one run under an identical
stamp.

## Rejected alternatives

**A hand-rolled scanner.** Attempted twice; see the table above. This is the
decision this ADR exists to record, and the evidence is the two rejections.

**Extract link URLs from `link_open` tokens instead of `_scan_links`.** More
faithful still, and it would delete a regex. Rejected for blast radius: roughly
twenty existing tests pin `_scan_links` behaviour (URL length bounds, brackets
inside query strings, off-run URLs, `[[1]](url)`), and re-deciding all of that in
the same change would obscure what this one fixes. Worth doing separately.

**Vendor the parsing rather than depend on it.** A copy is a fork, and a fork
drifts from the browser's parser — which is the exact failure being fixed.

**Return 0.0 rather than `None` for a code-only answer.** 0.0 asserts "these
markers are wrong". There are no markers. `None` — "nothing here could be
checked" — is the honest state and the one the census already uses.

## Consequences

- A code-only answer moves `faithful`/`low` → `partial`/`medium`, and its state
  line becomes "No citation marker on this run could be checked." This is a
  **user-visible change** and it is the point of the fix.
- **The score agrees with the screen for every answer this module parses**, and
  the parse is the renderer's own grammar rather than a hand-enumerated subset.
  The four constructs attempt 2 left over-counted are all handled. It is not an
  unqualified "by construction": the two bounds in decision 6 are exceptions,
  and so are three pre-existing regex limits `main` shares — `\[9\]`,
  `&#91;5&#93;` and `[[15]](url)`.
- **Cost:** a runtime dependency (+1.3 MiB, one transitive package `mdurl`),
  and parsing time on every answer under the bound — 3.5 ms for 16 KB of
  ordinary prose.
- **NOT fixed here, filed instead:** the evaluation is recomputed on every READ
  of a run, across 9 scopes, so this parse is paid per page view — measured
  14 ms to 2.55 s on a hostile 16 KB answer. That recompute-on-read is
  pre-existing; this change only made it expensive. Fixing it means changing
  how evaluations are stored, which is a different concern and a different PR.
- **A worst-case parse costs ~2.3 s on CI-class hardware**, measured on the CI
  runner for this PR, against 0.28 s on the development Mac — roughly 8x, and
  the runner is the closer analogue of the 512 MB production machine. That cost
  is tolerable ONCE per run and intolerable per page view, so it is the same
  concern as the item above and is filed with it. It is recorded here because
  the first version of this PR's own timing gate asserted an absolute wall-clock
  budget calibrated on the Mac, passed locally, and went red on CI — a
  measurement taken on the wrong hardware, which is exactly the failure mode
  this repo's rules warn about. The gate now asserts LINEARITY, which is a
  property of the code rather than of the runner.
- **Answers over 32,768 characters keep the old over-count.** Stated rather than
  hidden; it is `main`'s behaviour, not a new harm.
- **Persisted evaluations are not rewritten.** Every `eval_json` row already
  written keeps its poisoned grounding; a code fix is not a backfill.
- **The calibration corpus still cannot see this class.** `grep -c '```'
  tests/evals/corpus/cases/*` returns 0 in all five, and those corpora contain
  no backticks or tildes at all, so any "identical before and after" claim over
  them measures the early exit. The Layer-A thresholds remain uncalibrated for
  code-bearing answers.
- **`markdown-it-py` and `markdown-it.min.js` are separate implementations** and
  could drift at their edges. Review compared them across 8,103 inputs and found
  **zero disagreements**, so the risk is real but currently unrealised; nothing
  in CI compares them, which is the natural follow-up.

## Verification

- `test_marker_extraction_agrees_with_the_renderer` — 32 shapes, every one that
  broke any of the three attempts, asserted against ordinals read off a
  **rendered** document rather than hand-written. Its rule-7 partner proves the corpus really
  contains code ordinals a raw scan would wrongly count.
- **21 of 22 mutations killed**, each by the test named for it, including preset
  drift, dropping `.disable([...])`, joining blocks with `""` or with a newline,
  the space mask, deleting rather than blanking a span, treating an escaped run
  as no delimiter, reverting the guard to a line-anchored regex, dropping either
  substring arm of the guard, and removing the length bound.
  The 22nd (`breaks=False`) is **provably unobservable** here — measured to
  change zero inline token contents over 11 shapes — and is recorded as such
  rather than papered over with a test that cannot bite.
- Two tests were found **vacuous by that mutation run** — their inputs contained
  no code delimiter, so the early exit returned before the code under test ran,
  and they passed against every parser configuration. Both were given a
  delimiter.
- **A third review round found four defects that every gate above had passed**,
  all in shortcuts taken *around* the parser rather than in the parse: the
  escaped-closer rule, both blind spots in the content guard, the one-backtick
  DoS, and the newline join. Each is now a decision above, a test, and a killed
  mutation. The lesson repeats: the parity gate is the right instrument and its
  CORPUS is what keeps failing, so every shape review finds is added to it.
