# ADR-0129: The quick answer's judge verifies, and shows the claims it checked

## Status

Accepted — 2026-09-25, W5's fourth and last pull request. The product owner
decided, on 2026-09-24 (`docs/analysis/2026-09-24-w5-parked.md`, their
words): *"how the judge's verdict should display for single-model answers:
Judge: well supported/partly supported/not supported along with reasons and
artifacts to support why well supported/partly supported/not supported."*
(18:26:23Z), and, to the session's recommendation of verification only,
*"On the judge: I agree with your recommendation that is verification only"*
(18:39:08Z).

Those words are the owner's. **Everything else below is the session's
design**, listed under "Decisions the owner did not make". In particular,
reading "artifacts to support why" as per-claim evidence (a sentence of the
answer, the source it cites, and whether that source supports it) is the
session's reading; the owner has not confirmed it.

## Context

ADR-0127 made a finished quick answer serve `quick_verdict`: a level from the
judge's scores, reasons the app writes from them, and the sources the judge
was shown. It served no judge-written text (decision D-5), because the
judge's `rationale` is model-written text a cited page can steer, and two
review rounds showed that cleaning it with a pattern does not converge. The
judge was still the panel's: its prompt says "You score one multi-model
answer" and asks whether disagreement survived "in the synthesis", neither of
which a quick answer has. ADR-0128 put the verdict on the page. What was left
was the judge the owner chose (verification only) and the evidence behind
its verdict.

Failure modes were listed before the code:
`docs/analysis/2026-09-25-w5-quick-judge-failure-modes.md` (14 rows).

## Decision

1. **A separate prompt for quick runs**, `PR-EVAL-JUDGE-QUICK-v1`
   (`JUDGE_QUICK_PROMPT_ID` in `evaluation.py`). It checks the one answer
   against the sources it cites, says not to answer the question, not to add
   facts and not to judge truth from the model's own knowledge, and says the
   SOURCES lines show a page's title and address only. It carries the panel
   prompt's injection rules as the same paragraph (`_JUDGE_UNTRUSTED_RULES`,
   extracted from the panel prompt without changing a byte of it) and the
   same fence (`_fenced_user_prompt`). The user prompt is the question, the
   numbered SOURCES block and `ANSWER:`. **The panel prompt, its id, its
   schema and its parser are untouched**; a panel prompt change would need a
   paid golden re-capture.
2. **A strict quick schema**, `EvalJudgeQuickVerdict` (`strict=True`,
   `extra="forbid"`): `faithfulness`, `grounding`, `hallucination_risk`,
   `rationale`, `model_id`, and `claims`, at most 8
   (`JUDGE_QUICK_MAX_CLAIMS`) of `{quote (at most 300 characters,
   JUDGE_QUICK_MAX_QUOTE_LEN), source (int or null), support ("supported" |
   "contradicted" | "unsourced")}`. A response breaking any rule, including 9
   claims or a 301-character quote, is no verdict and reads `not_checked`,
   the posture the panel schema already has.
3. **`disagreement_preserved` is dropped for quick.** It asks whether model
   disagreement survived into the synthesis; one model has none. It is not
   asked and not accepted (a response carrying it is non-conforming), and
   the quick verdict never enters the panel evaluation engine, whose record
   needs it: the request path's memo judge hands the engine no judge for a
   quick run (a quick answer serves no panel evaluation anyway, ADR-0126),
   and `build_quick_verdict` reads the quick verdict from the memo.
4. **Wiring.** `EvalJudgeService.evaluate_quick` shares one dispatch with
   `evaluate` (the same gate, provider call, `max_tokens`, `response_format`,
   `reasoning`, usage and outcome capture); only the prompt builder and the
   parser differ. `_MemoisedRunJudge` is told the run's mode by
   `_request_path_judge` and calls `evaluate_quick` for `mode: "quick"`
   only. The memo, the money rails and the billing path are unchanged.
5. **Only the answer's own words are served.** A claim is served only if its
   quote, reduced to the text a reader sees (Markdown rendered to plain text
   by the workspace's own parser configuration, `displayed_text_blocks`;
   whitespace collapsed), is non-empty, at most 300 characters, and part of
   ONE block of the answer's displayed text; its `source` is null or one of
   `sources_checked` (1-based, the same list that numbers the prompt's
   SOURCES block); and "unsourced" goes with a null source and the other two
   words with a number. Only the first 8 claims are read. The served quote is
   the displayed text, never the raw Markdown. `QuickVerdict` gains `claims`
   and `claims_dropped` (how many the judge gave that are not served). The
   `rationale` is still never served.
6. **A served "contradicted" claim caps the level at partly supported**, so
   the page never reads "Well supported" above a claim it shows as
   contradicted. The level otherwise follows `verdict_level` and
   `verdict_supports_verification` exactly as for ADR-0127.
7. **The page.** Under the reasons: "Claims the judge checked", each the
   quote as text (`textContent`, never markup) and a line "Supported ·
   source N", "Contradicted · source N" or "No source cited", where N is the
   number of the entry in "Sources the judge checked"; then "The judge saw
   each source's title and address, not the page itself."; then, when any
   were dropped, how many claims are not shown and why. A support word the
   page does not know is not shown. Copy and Export carry the same claim
   lines (Export escapes each quote as untrusted inline text).
8. **Money: nothing moves.** `quorum_eval_judge_max_tokens` (1024),
   `cost_judge_output_tokens` (150), `cost_judge_input_tokens` (7300) and the
   bound's judge reserve are unchanged.

## Measurements

On `wp/w5-quick-judge`, based on `1fc3b45`; no network except localhost, no
paid call; the judge seam is stubbed in every test.

| what | result |
|---|---|
| RED before the change | the two new unit files failed to import (`cannot import name 'JUDGE_QUICK_MAX_CLAIMS'`, `'EvalJudgeQuickClaim'`); the integration files: 18 failed, 9 passed (a quick-shaped verdict read `not_checked`; `'QuickVerdict' object has no attribute 'claims'`; `'PR-EVAL-JUDGE-QUICK-v1' in '...PR-EVAL-JUDGE-v1...'` false; the quick ledger case); `quick-answer.spec.ts` against the ADR-0128 `app.js`: 3 failed, 7 passed |
| the panel is unchanged | a dump of the panel system prompt, three user prompts, eight parse results, the prompt id, the provider-call arguments and the service's verdict, usage and outcome, taken on `1fc3b45` before any edit and again on the final tree: identical, 15 of 15 lines. The panel prompt's SHA-256 (`4df96bff…479e`) is pinned in `tests/unit/test_quick_judge.py` |
| mutation proofs | 26 Python mutations, each killed by the test named for it (cp aside, mutate, `__pycache__` cleared, run, restore, `cmp`), plus 3 JavaScript mutations killed by the Node-run unit tests; baseline of the same files green (97 passed). One UI mutation is NOT caught: writing a quote with `innerHTML` instead of `textContent` survives the e2e spec, because the fixture's quotes carry no markup; the server's plain-text rule is what stands behind that line |
| the bound covers the quick judge | quick run, one slot, judge priced at $0.001/$0.005 per 1k: the bound's judge reserve is $0.0273; the largest quick judge call (the 2,197-character quick system prompt, an 8,000-character answer, 32 source lines at their caps, 29,832 characters in all, and 1,024 output tokens) costs $0.0126. The reserve still counts five synthesis sections a quick run never sends. Pinned by `test_the_quick_bound_covers_the_quick_judges_worst_case_call` |
| e2e | `quick-answer.spec.ts` (10 tests, two new) run 10 times: 100 passed. The first blocking lane (19 specs) as CI runs it plus the two local overrides: 308 passed (6.2m); its floor moves 306 -> 308 in `e2e.yml` |
| full suite and gates | recorded in the pull request |

**Not measured, and stated as such:**

- **The prompt's quality on real answers.** No live window has run it and no
  paid call was made, so whether a real judge follows "copy exactly",
  numbers sources correctly, or stays out of its own knowledge is unknown.
  A quote it paraphrases is dropped, which the page counts.
- **The quick judge's output length.** The point estimate prices 150 output
  tokens, measured on the PANEL judge (ADR-0114). A claim list is longer, so
  the displayed estimate may under-state a quick judge call. The bound prices
  the 1,024-token cap, so it covers any quick judge answer.
- **How often the cap truncates.** A reasoning model spends part of the 1,024
  tokens thinking, and 8 claims of 300 characters is roughly 600 more. A
  truncated answer is billed and reads `not_checked`, never a false level.

## Decisions the owner did not make (the session's)

- Reading "artifacts to support why" as per-claim evidence (not confirmed by
  the owner).
- A separate prompt for quick runs rather than a changed panel prompt; its
  wording; telling the judge it sees titles and addresses only.
- The schema: 8 claims, 300 characters, three support words, a null source
  for "unsourced"; a breach being no verdict rather than a trimmed one.
- Dropping `disagreement_preserved` for quick and keeping the quick verdict
  out of the panel engine.
- The serving rule: displayed text, one block, the first 8 claims; serving
  the displayed text rather than the raw Markdown; serving a drop count.
- A served contradicted claim capping the level at partly supported.
- The page copy: "Claims the judge checked", "Supported · source N",
  "Contradicted · source N", "No source cited", the titles-and-addresses
  sentence, the dropped-claims sentence, and the order (claims above the
  sources they number).
- No minimum quote length (failure mode 13 stays open).

## Rejected alternatives

- **Changing the panel prompt for both modes.** Every production panel run's
  judge would change, and a prompt change needs a paid golden re-capture.
- **Serving the judge's quotes after cleaning them.** ADR-0127 recorded two
  review rounds that did not converge on cleaning judge text; a substring of
  the answer needs no cleaning.
- **Matching against the raw answer.** The page shows rendered Markdown, so a
  raw quote would show `**` and `##` the page never shows, and a quote of the
  rendered sentence would not match. Matching displayed text against
  displayed text serves exactly what the page already shows.
- **Trimming an over-long claim list instead of refusing it.** Every other
  schema breach is no verdict; a verdict silently cut would be one the judge
  did not give. The serving filter still reads only the first 8, for a
  verdict the schema did not build.
- **A fourth support word ("cannot tell").** Closer to what a judge that sees
  only titles can say, but outside the three the session proposed and the
  page's three-way reading; left for a measured prompt revision.

## Consequences

- W5 is complete: board row W5 derives DONE from `JUDGE_QUICK_PROMPT_ID`.
- In production today nothing changes for users: live execution is off, so
  quick answers are local simulations, which are never judged, and read
  `not_checked` (ADR-0127).
- When #447's wiring hands the judge the fetched page text, the prompt's
  "title and address only" paragraph and the page's sentence "The judge saw
  each source's title and address, not the page itself." must change in the
  same pull request.
- The quick prompt is registered in `docs/46-prompt-registry.md` as
  advisory and uncalibrated, like the panel's.
