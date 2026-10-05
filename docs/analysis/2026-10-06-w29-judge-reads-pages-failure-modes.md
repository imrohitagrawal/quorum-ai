# W29 (PR 1) — the judge reads the cited pages, fetching off by default: failure modes before the code

Written 2026-10-06, before the change (AGENTS.md rule 16e). This change touches money (the judge's input reserve and a receipt row) and safety (fetching URLs that come from providers, and putting page text in a prompt).

Owner decisions:
- CHG-026 (d) and (e);
- CHG-028;
- CHG-027: "ask me before the one paid measured run it needs".

This pull request wires everything with `quorum_source_fetch_enabled` still False. Switching it on is PR 2, after the paid run and the owner's approval of the `docs/48` rows. Design: ADR-0148.

## Mechanism today (read on `ceabe46`)

- `source_fetcher.fetch_cited_pages` (ADR-0124) fetches pages and never raises:
  - it pins the address it connects to, so a redirect or a DNS change cannot reach a private network;
  - it has a time budget, a per-read timeout, and limits on bytes, pages and characters;
  - it fetches at most two pages per host;
  - it does not read robots.txt.
- The judge (`PR-EVAL-JUDGE-v1`) reads the question, the answers, the synthesis, and each source's title and address. The quick judge says it "cannot read the page".
- W52 keeps each search result's excerpt on its `SourceReference`, in memory only.
- W53's fence redacts forged markers by their letters.
- The judge's first dispatch runs in `_persist_terminal_run`, before the run's capacity slot is released.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | Fetching runs while the run still holds a capacity slot. | Up to the 8 s budget, plus robots.txt reads, added to every run's slot time. Fewer runs fit. | Fetch only when the setting is on. The budget covers robots.txt and pages together. The slot cost is measured in the paid run before switch-on. ADR-0148 records the cost and the alternative (fetching after release) that was rejected. |
| 2 | Every reader of a run triggers its own fetch. | N× fetches; hammering sites. | Fetch only on the owner branch of `_memoised_verdict`, once per verdict. A test counts calls (cardinality). |
| 3 | robots.txt is read with `urllib.robotparser.read`, which opens the URL itself. | Bypasses the pinned-address protection; follows redirects. | robots.txt is fetched through the same pinned path and limits as pages, then parsed with `RobotFileParser.parse`. |
| 4 | robots.txt cannot be read (timeout, 5xx, too large). | Fetching a page the site forbids, or skipping one it allows. | Fail closed: unreadable robots.txt means no fetch; the excerpt is used instead. A 404 means allowed, by the robots.txt standard (RFC 9309). |
| 4a | A fetch fails for another reason (timeout, too large, not text) while an excerpt exists. | Using the excerpt would go beyond the owner's decision, which names it for robots-disallowed pages only. | Fall back to the title and address. ADR-0148 records it as a session call the owner may overturn. |
| 5 | Page text carries instructions or forged markers. | Prompt injection into the judge. | Page text is cleaned the way W52 cleans excerpts (control and invisible characters, whitespace, the 4,000-character cut), placed inside the judge's untrusted block, and neutralised by W53's fence. |
| 6 | The judge's input grows past its reserve. | The price bound understates the worst case: a money bug. | When fetching is on, the reserve adds a term for pages and excerpts, clamped to LITERAL maxima, not the environment-tunable settings. When it is off, every pinned bound stays byte-identical. |
| 7 | The $0 `source_fetch` row picks up a rounding residue from reconciliation. | The receipt shows money for a free step. | A test pins the row at exactly $0 through `_reconcile_usd_lines`, on several totals. |
| 8 | The copy says pages were checked when none were. | A false trust claim. | "Checked against N of M cited pages" uses the run's own counts. N = 0 says so ("judged on titles and addresses; no page could be read"). With the setting off, today's copy stays. |
| 9 | The excerpt or page text reaches a log, a store or the page. | Retention outside `docs/48`. | The same rules as W52: never served, logged or stored. Tests scan responses and logs. |
| 10 | Quick mode fetches pages. | Against CHG-026 (e) "quick mode without pages first". | Quick mode never fetches. A test counts zero fetcher calls. |
| 11 | The fetcher, or the judge with pages, is slower than readers wait (30 s). | A reader sees no verdict. | The fetch budget (8 s) plus the judge call must fit. Measured in the paid run; recorded. |
| 12 | A changed prompt reuses `PR-EVAL-JUDGE-v1`. | The v1 hash pin and its paid golden capture no longer describe the prompt. | A new prompt id (`PR-EVAL-JUDGE-v2`) for page reading. v1 stays byte-identical and is used when fetching is off. |
| 13 | The setting is turned on without the paid run or the owner's approval. | Money and data retention without consent. | The setting stays False in code and `fly.toml`. PR 2 is the only switch-on, after the owner says yes. |
