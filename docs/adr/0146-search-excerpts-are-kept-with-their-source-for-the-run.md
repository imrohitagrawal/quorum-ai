# ADR-0146: Search excerpts are kept with their source for the run

## Status

Accepted — 2026-10-05, board row W52. The product owner chose on 2026-10-05 (CHG-028)
that the judge reads a search excerpt for a cited page that robots.txt says not to fetch;
this keeps the excerpt so W29's wiring can use it. The design is the session's. Failure
modes, written before the code:
`docs/analysis/2026-10-05-w52-search-excerpts-failure-modes.md`.

## Context

The app reads past the text each search result carries: OpenRouter's annotation `content`
and Tavily's `content`. It keeps a source's title and address only. W29's fallback for a
page that may not be fetched needs that text.

## Decision

1. `SourceReference` gains an optional `excerpt` (empty by default), filled by the two
   search paths: OpenRouter's annotation `content`, read from the same block as its URL,
   and Tavily's `content`. Anything that is not a non-empty string is no excerpt.
2. The excerpt is cleaned (control characters removed, whitespace collapsed) and cut to
   the fetcher's page-text limit, `quorum_source_fetch_max_text_chars` (4,000 characters),
   so an excerpt and a fetched page are bounded alike. In order: Unicode control
   characters (category Cc) other than whitespace are removed, whitespace runs collapse
   to one space and the ends are trimmed, then the text is cut (so a cut can end on a
   space). Invisible formatting characters (category Cf, such as zero-width or
   direction marks) are kept; W29's judge fence must allow for them.
3. It is never serialised to a client: excluded from the run's response models and the
   OpenAPI schema (the field is `exclude=True`, and `repr=False` so a log line that prints
   a source does not carry it). It lives only in the run held in memory, for as long as
   the run does.
4. It is never logged and never stored: telemetry keeps counting its length only; no
   store gains a field.
5. Nothing else changes: no request, prompt, price or judge evidence. W29 decides how the
   judge reads it.

## Rejected alternatives

- **A separate excerpt map beside the sources.** Two structures to keep in step; the
  excerpt belongs to its source.
- **Serve it to the page.** No one asked to see it, and it would make every result larger.
- **Its own size limit.** A second number for the same kind of text; the page-text limit
  already bounds what the judge may read per page.

## Consequences

- New data kept: the excerpt text, per run, in memory only. `docs/48` gains a row,
  pending the owner's approval.
- About 80 KB more per run at most (4 answers × 5 annotations measured × 4,000
  characters), held as long as the run.
- Calls taken by the session (the owner may overturn any of them): (i) the excerpt rides
  on `SourceReference`; (ii) the 4,000-character limit shared with fetched pages; (iii)
  never served to the page; (iv) Tavily's `content` is kept though its size is unmeasured.
