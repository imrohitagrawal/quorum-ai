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
   the setting meant for the fetcher's page text (W29's wiring passes it to the fetcher;
   today only this cut reads it). In order: Unicode control
   characters (category Cc) other than whitespace are removed, whitespace runs collapse
   to one space and the ends are trimmed, then the text is cut (so a cut can end on a
   space). Invisible formatting characters (category Cf: zero-width, direction controls,
   the tag block) are removed too, after review round 1 showed a forged fence marker
   with a zero-width character inside it passing the existing fence. Removing the
   zero-width joiner splits joined emoji, which is harmless because the excerpt is never
   shown. Before any of this, the raw text is cut to eight times the limit (32,000
   characters), so cleaning work does not grow with a huge input; visible text behind
   more than about 28,000 removable characters is lost, which no measured excerpt
   comes near. Only these two categories are removed. This does not make the fence safe:
   `neutralize_delimiters` matches the delimiter exactly, so a marker altered any other way
   (a combining mark such as U+034F, a variation selector, a look-alike letter, a space)
   still passes it, and removing more characters cannot close that. Making the fence
   match an altered marker is board row W53, due before W29 puts an excerpt in a prompt.
3. It is never serialised to a client: excluded from the run's response models and the
   OpenAPI schema (the field is `exclude=True`, and `repr=False` so a log line that prints
   a source does not carry it). It lives only in the run held in memory, for as long as
   the run does.
4. It is never logged and never stored: telemetry keeps counting only the raw OpenRouter
   text's length, as before, and nothing of Tavily's; no store gains a field.
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
- About 80,000 characters more per run if each of 4 answers carries the 5 annotations
  measured and every excerpt reaches the 4,000-character cut; the measured excerpts
  were about 2,000 characters, so about 40,000. The number of annotations per answer is
  not capped in code, so this is an estimate at the measured count, not a bound. A Python
  string takes 1, 2 or 4 bytes per character, set by its widest character, so the worst
  case at that count is about 4 × 80,000 = 320 KB.
- Calls taken by the session (the owner may overturn any of them): (i) the excerpt rides
  on `SourceReference`; (ii) the 4,000-character limit shared with fetched pages; (iii)
  never served to the page; (iv) Tavily's `content` is kept though its size is unmeasured.
