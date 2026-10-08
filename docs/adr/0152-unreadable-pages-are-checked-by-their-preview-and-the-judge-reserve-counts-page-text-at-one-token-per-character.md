# ADR-0152: Unreadable pages are checked by their preview, and the judge's reserve counts page text at one token per character

## Status

Accepted — 2026-10-08, board row W54, step 2 (page reading still off). The owner decided
the typical judge input, previews for unreadable pages and the recorded production judge on
2026-10-07 (CHG-032 (d), (e), (f)). The sentence composition and the 1-token-per-character
rate are the session's; the owner may overturn either. `quorum_source_fetch_enabled` stays
False in code and `fly.toml`. Failure modes, written before the code:
`docs/analysis/2026-10-08-w54-step2-previews-and-reserve-failure-modes.md`.

## Context

The paid runs of 2026-10-07 (CHG-032 (a), (c)), on the session's machine:

| Measure | Run 1 (English) | Run 2 (Japanese) |
|---|---|---|
| Judge model | `openai/gpt-5-mini` (the local `.env` then) | `openai/gpt-4.1-mini` (production's) |
| Judge input / output tokens | 7,303 / 470 | 8,416 / 130 |
| Characters per token, whole judge prompt | 4.58 (33,453 / 7,303) | 2.14 (18,029 / 8,416; one third Japanese) |
| Pages cited / read | 7 / 3 | 6 / 1 |
| Why the others were not read | 1 PDF, 2 over the per-site limit, 1 timeout | 1 PDF, 4 over the per-site limit |
| Pages a website's rules refused | 0 | 0 |
| Page fetching inside the run slot | 8.0 s (the whole budget) | 2.4 s |
| Time the run held its slot | not measured (the timer was added after run 1; the result arrived after 66.6 s, an upper limit) | 79.6 s |
| Cost | $0.1077, the pre-run estimate; the actual cost is unknown because one answer call timed out and may have been billed | $0.0992 (measured) |

Four judge-only calls with `gpt-4.1-mini` on run 1's evidence cost $0.0127. The clean
comparison (each of run 1's three pages fetched once, read both ways) gave the same verdict,
faithfulness 5 and grounding 5 with low risk, for picked passages (7,304 input tokens) and the
first 4,000 characters (7,474).

Production's judge is `openai/gpt-4.1-mini` (CHG-032 (b), (f)); several earlier records name
`openai/gpt-5-mini` as the shipped judge (for example the "shipped configuration" in
`tests/evals/golden/measured/judge_behaviour_2026-08-07.json`). Those records describe what was
measured then; production's model is `gpt-4.1-mini`, which ADR-0102, 0110, 0113, 0114, 0115,
0120, 0125, 0126 and 0143 already record (ADR-0126 from the 2026-09-10 telemetry, CHG-007);
ADR-0021 calls `gpt-5-mini` the shipped judge.

## Decision

### 1. The reserve counts page text at one token per character

`costs.py` prices the page block (8 items of 4,000 characters and their framing) at 1 token
per character instead of `CHARS_PER_TOKEN` (4). With `gpt-4.1-mini` at $0.40 per million
input tokens, the maximum shown before a panel run rises by $0.0098 (24,624 more tokens: the
8 page items, their framing and the 24 "same page as" lines) when page reading is in effect,
and not at all when it is off. One token per character covers the Japanese rate estimated
above (about 1.07 characters per token, the session's split of a mixed prompt); it is not a
proven ceiling, since rare characters and emoji can take more than one token each. The query and
the source titles are still priced at 4 characters per token, as before this change; text in
those scripts can take more there too (a known limit, not changed here).

### 2. The typical judge input is 8,400 tokens with page reading in effect

A new setting, `cost_judge_input_tokens_with_pages` (8,400), is the typical judge input the
estimate shows when `judge_reads_pages()` is true (CHG-032 (d)); `cost_judge_input_tokens`
(7,300) is used otherwise. The existing clamp still holds: the typical figure never exceeds
the reserve.

### 3. Previews for pages that could not be read for another reason

`judge_source_pages` sends the search excerpt for every distinct cited address whose page was
not read, whatever the reason (CHG-032 (e), overturning ADR-0148 call (iii)), within the same
8-item cap and 4,000-character cut. A new count, Q, is the distinct addresses whose excerpt
reached the judge for any reason other than a website's rules refusing the page: a
`robots_unchecked` page, a fetch failure, a refused content type, a page over the per-site
limit. P is unchanged (`refused_robots` with its excerpt). The run's `evaluation` gains
`source_pages_preview_other`, null whenever `source_pages_read` is null.

The v2 system prompt says a PAGE entry is the page's text or, where the page could not be
read, the short preview the search engine returned.

### 4. The sentences

Let R = M − N − P − Q (pages checked on title and address only). The lead sentence is
unchanged. When Q is missing (a run served before this change), ADR-0150's sentences apply
unchanged. Otherwise the note is built from parts, each true on its own:

| Part | When | Text |
|---|---|---|
| Lead | N > 0 | "Checked against N of M cited pages." ("cited page" when M is 1) |
| Lead | N = 0 | "No cited page could be read." |
| Rules | P > 0 | ADR-0150's blocked sentence for the case, exactly as there: the approved "For the other P, …" when P = M − N (so Q = R = 0); the approved all-blocked sentence (and its singular) when N = 0 and P = M; otherwise "For P of the other M−N, …" (N > 0) or "For P of the M, …" (N = 0), singular or plural as ADR-0150 says, ending at "…the short preview(s) the search engine showed." with no tail about the rest |
| Previews | Q = 1, P > 0 | "For 1 other cited page that could not be read, the check used the short preview the search engine showed." |
| Previews | Q ≥ 2, P > 0 | "For Q other cited pages that could not be read, the check used the short previews the search engine showed." |
| Previews | Q = 1, P = 0 | "For 1 cited page that could not be read, the check used the short preview the search engine showed." |
| Previews | Q ≥ 2, P = 0 | "For Q cited pages that could not be read, the check used the short previews the search engine showed." |
| Rest | N = 0, R > 0, and P > 0 or Q > 0 | "For the rest, it used the titles and addresses." ("the title and address" when R is 1) |
| Rest | N = 0, P = 0, Q = 0 | "The check used only the titles and addresses." ("the title and address" when M is 1) |

Two whole-sentence cases replace the parts:

| Case | Text |
|---|---|
| N = 0, P = 0, Q = M, M > 1 | "No cited page could be read. The check used only the titles, addresses and the short previews the search engine showed." |
| N = 0, P = 0, Q = M = 1 | "No cited page could be read. The check used only the title, address and the short preview the search engine showed." |

"Other" appears in the previews part only after a rules part, which it is set against.
Parts are joined with a single space, in the order of the table. When N = 0 and P = M, the
approved all-blocked sentence begins "No cited page could be read:" itself, so it replaces the
N = 0 lead rather than following it. A null Q counts as missing. Impossible counts (not whole numbers, negative,
N + P + Q > M) show the sentence used when page reading is off, as before.

### 5. The 8-item cap takes read pages first (review round 1)

Every fetched and read page takes a slot before any preview does; previews then fill the slots
left, in source-line order. Review round 1 found the first version filling the cap in line
order: a page over the per-site limit is not an attempt, so its preview could take a slot ahead
of a page fetched further down, which was then dropped, and the note could say "No cited page
could be read" about a page that had been read. At most 8 pages are attempted, so read pages
always fit.

### 6. Four pages per site (CHG-033 (a))

`MAX_PAGES_PER_HOST` rises from 2 to 4. The fetcher still attempts at most 8 pages within the
same 8-second budget, so the reserve and the run-slot bound do not move. In the paid runs, 6 of
13 cited pages were over the limit of 2: 2 web pages the judge could then read, and 4 PDFs.
Of the 9 unread pages, 7 were PDFs (2 refused as not web pages, 4 over the limit, 1 timeout);
reading PDFs is W54 step 3 (CHG-033 (a)).

### 7. The approved sentence in the plural (CHG-033 (d))

When P = M − N and P ≥ 2, the approved sentence reads "For the other P, the websites ask
automated tools not to read their pages, so the check could only use the short previews the
search engine showed." P = 1 keeps "For the other one, the website asks … its pages, … the
short preview …".

## Rejected alternatives

- **Count page text by UTF-8 bytes** (a token never covers less than one byte for the byte-level
  tokenizers measured). It is a true bound, but 4,000 Japanese characters are about 12,000
  bytes, so the reserve would triple again for a risk no measurement has shown.
- **Fold Q into P.** The note would say a website asked tools not to read pages that simply
  failed (ADR-0150's round-1 finding).
- **Keep ADR-0150's "titles, addresses and any short previews" for the rest.** True, but vague
  once Q says exactly which pages had a preview.

## Consequences

- With page reading off, nothing visible changes; the API gains one null field.
- With it on: more cited pages are checked against something (in the paid runs, 9 of 13 pages
  were unread and would now be checked by their preview where the search returned one); the
  maximum shown before a panel run is $0.0098 higher; the judge's typical line is
  priced from 8,400 input tokens plus the question (about $0.0004 more than 7,300 at
  `gpt-4.1-mini`'s price).
- The golden capture for `PR-EVAL-JUDGE-v2` is made after this change, on the final prompt.
