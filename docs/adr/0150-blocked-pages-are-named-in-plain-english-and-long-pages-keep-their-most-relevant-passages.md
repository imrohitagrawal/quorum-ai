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

`judge_source_pages` returns a third count, P: the distinct cited addresses whose site's
robots.txt (its rules for automated tools) was read and has a rule that does not allow the
page, and whose search excerpt reached the judge (non-empty after cleaning, inside the 8-item
cap). A refused page with no usable excerpt is not counted.

Review round 1 found that ADR-0148's fail-closed cases were counted too: a robots.txt that
could not be read (no answer, a 3xx or 5xx, a file over the size cap) and an address too long
to check all came out as `refused_robots`, so the note would have said "the website asks
automated tools not to read its pages" about sites that asked nothing. CHG-029 (b) keeps such
pages within "Checked against N of M". The fetcher now reports them as `robots_unchecked`: the
page is still not requested and the judge still reads its excerpt (ADR-0148 decision 4 is
unchanged), but P does not count it.

The run's `evaluation` gains `source_pages_preview`, null whenever `source_pages_read` is null
(the judge was not sent pages: setting off, a quick run, no judge, or no cited source).

Let N = pages read, P = pages a website's rules refused and checked by preview, M = distinct
cited addresses, and F = M − N − P (failed, robots.txt unreadable, refused with no preview, or
past the cap). A page in F whose robots.txt could not be read still sends its preview to the
judge, so no sentence may say the rest were checked on titles and addresses only (review
round 2 found the first wording did).

### 2. The sentences

The lead sentence stays: "An independent judge model checked this answer's citations against
its source list — an automated review, not a human fact-check." Then:

| Case | Sentence after the lead | Source |
|---|---|---|
| Posture off, or counts missing or impossible | Today's: "…The cited pages themselves were not retrieved." | ADR-0148 |
| P missing (a run stored before this change) | Today's W29 sentences, unchanged | ADR-0148 |
| N > 0, P = 0 | "Checked against N of M cited pages." | ADR-0148 |
| N > 0, P > 0, F = 0 | "Checked against N of M cited pages. For the other P, the website asks automated tools not to read its pages, so the check could only use the short preview the search engine showed." | Session wording, approved by the owner (CHG-029 (b)) |
| N > 0, P > 0, F > 0 | "Checked against N of M cited pages. For P of the other M−N, the website asks automated tools not to read its pages, so the check could only use the short preview the search engine showed." | Session |
| N = 0, P = M, M > 1 | "No cited page could be read: the websites ask automated tools not to read their pages. The check used only the titles, addresses and the short previews the search engine showed." | Session wording, approved by the owner (CHG-029 (b)) |
| N = 0, P = M = 1 | "No cited page could be read: the website asks automated tools not to read its pages. The check used only the title, address and the short preview the search engine showed." | Session (the approved sentence in the singular) |
| N = 0, 0 < P < M | "No cited page could be read. For P of the M, the website asks automated tools not to read its pages, so the check could only use the short preview the search engine showed; for the rest it used the titles, addresses and any short previews the search engine showed." | Session |
| N = 0, P = 0, M > 1 | "No cited page could be read. The check used only the titles, addresses and any short previews the search engine showed." | Session (today's meaning, in plainer words than "search excerpts") |
| N = 0, P = 0, M = 1 | "No cited page could be read. The check used only the title, address and any short preview the search engine showed." | Session |

Singular forms: "cited page" when M is 1 (as today); "For the other one," when P is 1 and
F = 0; the N = 0, P = M = 1 and N = 0, P = 0, M = 1 rows above. Impossible counts (not whole numbers, negative,
N + P > M) show the sentence used when page reading is off, which never claims a page was
read, as today. "Posture off" in the table means page reading is switched off.

### 3. Reading a page longer than 4,000 characters

- A page whose visible text is at most 4,000 characters is read exactly as today.
- Otherwise the fetcher keeps the page's text in blocks (paragraphs, list items, headings,
  table cells), from the main area: `<main>` when it holds at least 1,000 characters, else
  the longest `<article>` when it holds at least 1,000, else the page without `nav`,
  `header`, `footer`, `aside` and `form` when that leaves at least 1,000 characters AND at
  least half of the page's visible text, else the whole visible text. The half rule was
  added in review round 1: a page wrapped in one `<form>` with a notice outside it kept only
  the notice. Falling back to the whole text costs little, because picking then chooses the
  relevant passages from it. The block text is capped at 262,144 characters
  (`READING_TEXT_MAX_CHARS`, the same number as the fetcher's default byte cap).
- Each article's blocks are recorded as one range of block positions when its tags open and
  close, so the work grows with the number of tags and blocks, not with their product. Review
  round 1 measured the first version at 15.9 s of CPU and 6 GB of memory on one page of
  26,214 nested `<article>` tags (262,144 bytes); production has 512 MB.
- `pick_passages` splits the blocks into passages of at most 500 characters (a block longer
  than that is split at a space), scores each passage by how many distinct words it shares
  with the run's answers, and keeps the best-scoring passages first, each one if it still
  fits in 4,000 characters, ties going to the earlier passage. The kept passages are joined
  in page order; " … " goes only where passages were skipped between them, and the separators
  count inside the 4,000. Two neighbouring kept passages are joined by the page's own text:
  the line break between two blocks, the space between pieces of a split block, and nothing
  between pieces of a run with no spaces.
- Neighbouring short blocks are joined into one passage while it stays within 500
  characters; the pieces of a split long block are never joined. Plain text (not HTML) longer
  than the limit is split into blocks at blank lines. Text across inline tags inside one block
  is joined with a space, as `extract_text` does today.
- Words: lower-cased runs of letters and digits, at least 3 characters, minus a fixed list of
  71 common English words. Each distinct word counts once per passage.
- A page with no shared words (for example Chinese or Japanese, which have no spaces between
  words) keeps passages from the top in page order; one that does not fit is skipped and a
  later, shorter one may fill the room left. When the page has a main area (`<main>`, an
  `<article>`, or enough text outside menus and forms) it reads that, so menus and footers are
  left out; otherwise it starts from the top of the whole text, as today.
- Picking cuts to the smaller of 4,000 characters and the `quorum_source_fetch_max_text_chars`
  setting, so a lowered setting still keeps whole passages (review round 2 found a later cut
  splitting them).
- Known limit, found in review round 2: an `<article>` that is never closed runs to the end of
  the page, where a browser would close it at its parent's end. A page whose only article is
  an unclosed teaser after the main text can then lose the main text. How often real pages do
  this is not measured.
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
  usable-text minimum applies to it unchanged. Robots.txt is read as before; a page whose
  robots.txt could not be read or checked gets the new outcome `robots_unchecked` instead of
  `refused_robots` (decision 1), and is still not requested.
- `evaluation.pick_passages(text: str, claims: Sequence[str], *, limit: int) -> str`: `text`
  unchanged when it is at most `limit` characters; otherwise rule 3's passages, at most
  `limit` characters including the `" … "` separators. It reads and writes nothing else and
  logs nothing.
- `judge_source_pages` calls the fetcher with `long_pages=True`, and passes each fetched page
  through `pick_passages(row.text, answer_texts, limit=JUDGE_MAX_SOURCE_PAGE_CHARS)` before the
  cleaning and cut it does today. Excerpts are not passed through it.
- `JudgeSourcePages.preview: int` (P), counting `refused_robots` only; the judge's in-memory
  record holds `(read, cited, preview)`;
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
- **The approved sentence "For the other P" in every case.** False when some unread pages
  failed for another reason.
- **Counting every page robots.txt kept us from requesting** (the first version). False when
  robots.txt simply could not be read (decision 1).

## Consequences

- With the setting off, nothing visible changes; the API gains one null field.
- With it on: the judge reads the most relevant passages of long pages; the trust note says
  when a website's rules asked tools not to read its pages.
- Picking can bring third-party text from deep in a page into the judge's prompt that the
  first 4,000 characters would not have reached (for example a reader's comment that repeats
  the answers' words). It stays inside the untrusted block and the v2 prompt still says to
  ignore instructions in it.
- On the synthetic pages measured, reading and picking cost little time in the run slot.
  Measured after review round 1 with `time.process_time` (best of 3, an Apple M4) for 8 pages
  at the 262,144-byte cap and four 4,000-character answers, on the page shapes built: about
  0.5 s of CPU for nested inline tags, and up to 0.9 s for a page of 262,144 bytes of tiny
  `<p>` blocks (review round 2), of which about 0.6 s is the parse today's `extract_text`
  already pays; a memory peak of at most 5.5 MiB for one page (nested `<article>` tags; the
  first version needed about 6 GB for that page). Production runs on a shared CPU (`fly.toml`),
  so its times are not measured here. Script: the session's `time_pick.py`
  (not kept in the repository).
- Unmeasured until the paid run: whether picked passages change verdicts compared with the
  first 4,000 characters, how often fetches fail, and the time picking adds in the run slot
  on real pages.
