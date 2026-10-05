# W52 — keep the search excerpts: failure modes before the code

Written 2026-10-05 before the change (AGENTS.md rule 16e: this keeps new text and feeds a
paid call later). Board row W52. Decision: CHG-028 — the owner chose that the judge reads a
search excerpt for a cited page that robots.txt says not to fetch, which needs the excerpt
kept first. W29's wiring, which hands excerpts to the judge, is the next pull request; this
one only keeps them. Design: ADR-0146.

## Mechanism today (read on `24e3099`)

- `SourceReference` has four fields: `title`, `url`, `provider`, `is_fallback`
  (`providers.py`); `tests/unit/test_judge_disclosure_is_honest.py` pins that set.
- OpenRouter's `:online` annotations carry `content` (nested under `url_citation`); the
  parser reads past it on purpose ("Passage `content` is deliberately not carried here").
  Telemetry records only its length (`annotation_content_chars`), never the text.
- The Tavily parser reads `url` and `title` only; the request sends `query` and
  `max_results` only.
- Sources travel with each answer in the run held in memory, and are served to the page in
  the run's result.

## Measured size

`docs/analysis/2026-09-10-telemetry-tokens.jsonl`: 8 searching calls each returned 5
annotations carrying 9,993 to 10,253 characters of `content` in all, about 2,000 characters
per annotation. Tavily's `content` size is unmeasured here (no call was made).

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | The excerpt is served to the page or to an API client. | New text on the wire nobody asked for; a larger response. | The excerpt is never serialised: excluded from every response model and the OpenAPI schema; a test reads the result JSON and finds no excerpt. |
| 2 | The excerpt is written to a log, telemetry, the run-history store or the account history. | Text kept where `docs/48` does not say. | Telemetry keeps its length only, as today; no store gains a field; a test scans the logs of a run for the excerpt text. |
| 3 | An excerpt is unbounded (a provider sends 100 KB). | Memory, and a later judge input that blows its reserve. | Each excerpt is cut to the fetcher's page-text limit (`quorum_source_fetch_max_text_chars`, 4,000 characters), after collapsing whitespace and removing control characters. |
| 4 | Excerpt text carries instructions or forged delimiters. | Prompt injection when W29 hands it to the judge. | It is untrusted text: kept as plain text and fenced by the judge's existing fence when W29 uses it; this change never puts it in a prompt. |
| 5 | Two annotations for one URL, or an excerpt on a source the sanitiser drops. | An excerpt attached to the wrong page, or orphaned. | The excerpt goes on the same `SourceReference` as its URL, after the URL is sanitised; a dropped URL drops its excerpt. |
| 6 | The flat annotation shape (no `url_citation` block) or a non-string `content`. | A crash, or an excerpt from the wrong key. | Read `content` from the same block the URL came from; anything not a non-empty string is no excerpt. |
| 7 | Tavily returns no `content`, or a different shape. | A crash or a false excerpt. | Optional: a non-empty string is kept, anything else is none. |
| 8 | The simulated and inline-Markdown paths have no excerpt. | A judge later assuming one exists. | `excerpt` is optional and empty there; W29 falls back to title and address. |
| 9 | A cost, a request or the judge's input changes now. | Money moves without the owner's paid-run decision. | Nothing is sent anywhere new: no request changes, no prompt changes, no price changes; the judge evidence is byte-identical. |
| 10 | Memory held per run grows. | More memory per run held in memory. | About 80,000 characters per run at the 5 annotations measured if every excerpt reached the cut (about 40,000 at the measured 2,000 each); the annotation count is not capped, so this is an estimate, not a bound. Held only as long as the run is, and gone with it. |
