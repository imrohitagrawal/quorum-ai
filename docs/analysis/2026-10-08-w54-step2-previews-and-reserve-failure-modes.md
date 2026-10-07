# W54 step 2 — previews for unreadable pages, the judge's page reserve and its typical input: failure modes before the code

Written 2026-10-08, before the change (AGENTS.md rule 16e). This change touches money (the judge's price reserve and the typical figure the estimate shows) and a trust claim (what the note says was checked). Page reading stays off (`quorum_source_fetch_enabled` False in code and `fly.toml`). Design: ADR-0152.

Owner decisions (CHG-032, 2026-10-07):
- (d) the typical judge input with page reading on is 8,400 tokens;
- (e) a cited page that could not be fetched for another reason is checked by its search preview too, overturning ADR-0148 call (iii);
- (f) production's judge is `openai/gpt-4.1-mini`.

## What the paid runs measured (2026-10-07)

- Judge input with pages: 7,304 tokens (English, 3 pages read) and 8,416 (Japanese, 1 page read).
- A judge prompt that was one-third Japanese ran at 2.14 characters per token; an English one at 4.58. Splitting the Japanese prompt by script (the session's estimate, not a measurement) gives about 1 character per token for Japanese text.
- 13 cited pages: 4 read, 4 PDFs, 4 skipped by the two-pages-per-site limit, 1 timeout; none refused by a website's rules.

## Mechanism today (read on `de0c4c2`)

- `costs.py` reserves the page block at 4 characters per token (`CHARS_PER_TOKEN`), 8 items of 4,000 characters.
- `settings.cost_judge_input_tokens` (7,300) is the typical judge input shown in the estimate, pages or not.
- `judge_source_pages` sends the excerpt only for `refused_robots` and `robots_unchecked` pages; any other unread page gets its title and address only. P counts `refused_robots` with an excerpt.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | Page text in Chinese, Japanese and similar scripts takes about 1 token per character, not 4 characters per token. | The maximum price shown before a run is too low by up to about $0.0096 with `gpt-4.1-mini` (8 items × 3,000 tokens × $0.40 per million): a money understatement. | Page items are reserved at 1 token per character. This covers the measured Japanese rate; it is not a proven ceiling (rare characters and emoji can take more), which ADR-0152 says. |
| 2 | The typical judge input rises with pages, but the estimate still shows 7,300. | The shown estimate is low by about 15% on the Japanese run. | With page reading in effect, the typical figure is 8,400 (CHG-032 (d)); with it off, 7,300 and every pinned estimate stay byte-identical. |
| 3 | The typical figure is raised above the reserve. | The shown typical exceeds the maximum. | The existing clamp (typical ≤ reserve) applies to the new figure too; a test pins it. |
| 4 | Previews for "other reason" pages are counted in P. | The note says the website asked tools not to read pages that simply failed. | A separate count Q: unreadable pages, other than ones a website's rules refused, whose preview reached the judge. P is unchanged. |
| 5 | Q counts a page whose preview was empty or past the 8-item cap. | The note claims a preview was used when none was. | Q counts only previews that reached the judge (non-empty after cleaning, inside the cap), once per address, as P does. |
| 6 | The sentences for N, P and Q combined say something false, or lose the owner's approved wording. | A false trust claim. | ADR-0152 gives one sentence part per count, each true on its own; the owner-approved sentences are kept exactly where they apply. A sweep over every reachable (N, P, Q, M) checks the table. |
| 7 | Old stored runs, or a response without Q, get the new sentences. | Changed wording for runs the count never described. | Q missing keeps ADR-0150's sentences. |
| 8 | A preview for a page refused for safety (a private address, an unsupported scheme) is sent. | None new: the preview comes from the search engine, not the refused address. | Allowed, like other failures. |
| 9 | More previews reach the judge. | More third-party text in the prompt. | Previews were already untrusted and fenced (W52, W53); the item cap and the 4,000-character cut are unchanged. The `docs/48` row for search excerpts already covers sending them to the judge provider. |
| 10 | The v2 system prompt still says a PAGE entry is a preview only where the site does not allow its page to be read. | The judge misreads what a preview stands for. | The v2 prompt says a PAGE entry may be the page text or, where the page could not be read, the short preview the search engine returned. v2 has no golden capture yet; it is captured after this change. |
| 11 | With page reading off, anything changes. | Breaks the off-path promise. | Off path: prompts, prices, estimate and visible text byte-identical; the API gains one null field. |
