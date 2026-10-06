# ADR-0150: Blocked pages are named in plain English, and long pages keep their most relevant passages

## Status

Accepted — 2026-10-07, board row W54, first pull request (fetching still off). The product
owner approved the wording and the reading of long pages on 2026-10-06 (CHG-029 (b), (c):
*"I approve all your suggestions"*). The table of sentences for mixed outcomes, the
thresholds and the word rules below are the session's; the owner may overturn any of them.
`quorum_source_fetch_enabled` stays False in code and `fly.toml`. Failure modes, written
before the code: `docs/analysis/2026-10-07-w54-blocked-wording-and-passages-failure-modes.md`.

## Context

ADR-0148 (W29) built page reading behind a default-off setting. Two things the owner asked
for are not built:

- The trust note says nothing about pages a website asks automated tools not to read. When
  every page is refused it says "It worked from the titles, addresses and any search
  excerpts", and "search excerpts" means little to a reader. The owner asked for wording
  without "robots.txt" (CHG-029 (b)).
- A page's text is cut at its first 4,000 characters, menus included. The owner approved
  keeping the most relevant passages instead, with no AI summary (CHG-029 (c)).

## Decision

### 1. A served count of pages checked by their search preview

`judge_source_pages` returns a third count, P: the distinct cited addresses whose page
robots.txt refused and whose search excerpt reached the judge (non-empty after cleaning,
inside the 8-item cap). A refused page with no usable excerpt is not counted. The run's
`evaluation` gains `source_pages_preview`, null whenever `source_pages_read` is null.

Let N = pages read, P = pages checked by preview, M = distinct cited addresses, and
F = M − N − P (failed, refused with no preview, or past the cap).

### 2. The sentences

The lead sentence stays: "An independent judge model checked this answer's citations against
its source list — an automated review, not a human fact-check." Then:

| Case | Sentence after the lead | Source |
|---|---|---|
| Posture off, or counts missing or impossible | Today's: "…The cited pages themselves were not retrieved." | ADR-0148 |
| P missing (a run stored before this change) | Today's W29 sentences, unchanged | ADR-0148 |
| N > 0, P = 0 | "Checked against N of M cited pages." | ADR-0148 |
| N > 0, P > 0, F = 0 | "Checked against N of M cited pages. For the other P, the website asks automated tools not to read its pages, so the check could only use the short preview the search engine showed." | Owner (CHG-029 (b)) |
| N > 0, P > 0, F > 0 | "Checked against N of M cited pages. For P of the other M−N, the website asks automated tools not to read its pages, so the check could only use the short preview the search engine showed." | Session |
| N = 0, P = M | "No cited page could be read: the websites ask automated tools not to read their pages. The check used only the titles, addresses and the short previews the search engine showed." | Owner (CHG-029 (b)) |
| N = 0, 0 < P < M | "No cited page could be read. For P of the M, the website asks automated tools not to read its pages, so the check could only use the short preview the search engine showed; for the rest it used the titles and addresses." | Session |
| N = 0, P = 0 | "No cited page could be read. The check used only the titles and addresses." | Session (today's sentence mentions "search excerpts", which P = 0 shows were not used) |

Singular forms: "cited page" when M is 1 (as today); "For the other one," when P is 1 and
F = 0. Impossible counts (not whole numbers, N + P > M) fail closed to the posture-off
sentence, as today.

### 3. Reading a page longer than 4,000 characters

- A page whose visible text is at most 4,000 characters is read exactly as today.
- Otherwise the fetcher keeps the page's text in blocks (paragraphs, list items, headings,
  table cells), from the main area: `<main>` when it holds at least 1,000 characters, else
  the longest `<article>` when it holds at least 1,000, else the page without `nav`,
  `header`, `footer`, `aside` and `form` when that leaves at least 1,000, else the whole
  visible text. The block text is capped at 262,144 characters (the fetcher's byte cap).
- `pick_passages` splits the blocks into passages of about 500 characters (a block longer
  than that is split at a space), scores each passage by how many distinct words it shares
  with the run's answers, and keeps the highest-scoring passages that fit in 4,000
  characters, ties going to the earlier passage. The kept passages are joined in page order
  with " … " between them, separators counted inside the 4,000.
- Words: lower-cased runs of letters and digits, at least 3 characters, minus a fixed list of
  common English words. Each distinct word counts once per passage.
- A page with no shared words (for example Chinese or Japanese, which has no spaces between
  words) keeps its first passages: the same as today.
- The v2 system prompt says a PAGE entry may be passages from the page with gaps marked
  " … ". v2 has no paid golden capture yet; the paid run captures it after this change.

### 4. No setting for the comparison

The paid comparison (CHG-029 (a)) fetches each page once in a script and builds both
judge prompts from the same fetched text: "first 4,000 characters" with today's
`extract_text`, and "picked passages" with this code. No production switch is added.

### 5. The names this change adds (shared by the tests and the code)

- `source_fetcher.reading_text(body: str, content_type: str, *, limit: int) -> str`: the
  page's visible text exactly as `extract_text(body, content_type, max_chars=limit)` gives it
  when that text is at most `limit` characters; otherwise the main area's blocks (rule 3),
  each with its whitespace collapsed, joined by `"\n"`, at most `READING_TEXT_MAX_CHARS`
  (262,144) characters.
- `fetch_cited_pages(..., long_pages: bool = False)`: with `long_pages=True` a fetched row's
  `text` is `reading_text(..., limit=max_text_chars)` instead of `extract_text(...)`; the
  usable-text minimum applies to it unchanged. Robots.txt reading is unchanged.
- `evaluation.pick_passages(text: str, claims: Sequence[str], *, limit: int) -> str`: `text`
  unchanged when it is at most `limit` characters; otherwise rule 3's passages, at most
  `limit` characters including the `" … "` separators. Pure: no I/O, no logging.
- `judge_source_pages` calls the fetcher with `long_pages=True`, and passes each fetched page
  through `pick_passages(row.text, answer_texts, limit=JUDGE_MAX_SOURCE_PAGE_CHARS)` before the
  cleaning and cut it does today. Excerpts are not passed through it.
- `JudgeSourcePages.preview: int` (P); the judge's memo records `(read, cited, preview)`;
  `RunEvaluation.source_pages_preview: int | None` (null whenever `source_pages_read` is null);
  the same field in `openapi.yaml`.
- The page's `verifiedTrustDisclosure(ev, pagesInEffect)` reads `ev.source_pages_preview` and
  returns the sentences of rule 2.

## Rejected alternatives

- **An AI summary of each page.** A second paid call, more time in the run slot, another
  model's reading of the page, and another model exposed to instructions hidden in it
  (CHG-029 (c)).
- **Embeddings or a ranking model.** A new dependency or a paid call for each page.
- **Counting pages refused by robots.txt whether or not a preview existed.** The sentence
  would then say a preview was used when none was.
- **The owner's sentence "For the other P" in every case.** False when some unread pages
  failed for another reason.

## Consequences

- With the setting off, nothing visible changes; the API gains one null field.
- With it on: the judge reads the most relevant passages of long pages; the trust note says
  when a website asked tools not to read its pages.
- Unmeasured until the paid run: whether picked passages change verdicts compared with the
  first 4,000 characters, how often fetches fail, and the time picking adds in the run slot
  on real pages.
