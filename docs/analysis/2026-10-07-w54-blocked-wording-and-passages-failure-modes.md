# W54 (PR 1) — blocked-page wording and passage picking, fetching still off: failure modes before the code

Written 2026-10-07, before the change (AGENTS.md rule 16e). This change touches safety (what a page's text puts in the judge's prompt) and a trust claim (what the note says was checked). The judge's price bound is not meant to move; the table says how that is held.

Owner decisions:
- CHG-029 (b): the plain-English wording for pages a website asks tools not to read;
- CHG-029 (c): pages over 4,000 characters keep their most relevant passages, not the first 4,000 characters, and no AI summary;
- CHG-029 (a): the paid run happens after this pull request, on the session's machine.

`quorum_source_fetch_enabled` stays False in code and in `fly.toml`. Design: ADR-0150.

## Mechanism today (read on `7e6c94c`)

- `source_fetcher.extract_text` keeps the visible text of a page (it skips `script`, `style`, `noscript`, `template`, `svg`, `head`), collapses whitespace and cuts it at `max_text_chars`. The judge passes 4,000, so the judge sees the first 4,000 characters, menus included.
- `evaluation.judge_source_pages` gives each distinct address one item: the page text, the search excerpt when robots.txt refused the page, or nothing. It returns `read` (pages fetched and read) and `cited` (distinct addresses).
- The page says "Checked against N of M cited pages" from those two counts. N = 0 says "It worked from the titles, addresses and any search excerpts: no cited page could be read."
- No count says how many items were a search excerpt.
- The two counts live in the judge's in-memory record and the API response only; `to_eval_json` does not store them, so a run read back later (after a restart, or from History) has no counts and shows the sentence that claims no page was read.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | The note says a search preview was used for a page when none existed (robots.txt refused the page and the search returned no excerpt, or the excerpt cleaned to nothing). | A false claim about what was checked. | The new count P counts only refused pages whose excerpt actually reached the judge (non-empty after cleaning, inside the 8-item cap). A refused page with no excerpt falls in "other". |
| 2 | Mixed outcomes (some read, some previews, some failed) make the owner's sentence false. "For the other 2" is only true when every unread page was a preview. | A false claim. | Enumerate every combination of N, P and F (failed or refused without a preview) and give each a sentence that is true. The owner's exact sentences are used where they are exactly true (F = 0); the rest are the session's wording, recorded as calls in ADR-0150. |
| 3 | Old stored runs, or a server that does not send P, are read as P = 0 and shown the new N = 0 sentence. | Changed wording for runs the new count never described. | P missing means the note keeps today's sentences. Impossible counts (N + P > M, not whole numbers) fail closed to the sentence that claims no page was read. |
| 4 | With the setting off, the new field or the new sentences change anything visible. | Breaks the "byte-identical when off" promise of ADR-0148. | P is null when no pages were read, like N and M. The posture predicate stays the one gate. A test compares the off-path API body and page text before and after. |
| 5 | Dropping page furniture drops the article. Many sites wrap the whole page in one `<form>` (ASP.NET Web Forms) or put the article inside `<header>`. | The judge loses the page; it reads "unusable". | Prefer `<main>`, then `<article>`, when they hold enough text. Drop `nav`, `header`, `footer`, `aside`, `form` only while what is left still holds enough text; otherwise keep the full visible text. Tested with a page wrapped in `<form>`. |
| 6 | Passage picking needs the whole page text, so the fetcher no longer cuts at 4,000 characters. | More memory per run, and a bigger string near the prompt. | The fetcher's byte cap (262,144) still bounds the body. Picking runs in the judge's call and the cut to 4,000 characters happens before the text reaches `JudgeEvidence`. Nothing longer than 4,000 characters per item can reach the prompt; a test pins the item length at the boundary. |
| 7 | Separators between picked passages push an item over 4,000 characters. | The reserve in `costs.py` is per item at 4,000 characters plus a fixed overhead: an understated price bound (money). | The joined text, separators included, is at most 4,000 characters. A test drives the boundary (passages that fill to exactly 4,000 with separators, and one character over). |
| 8 | Scoring by shared words is dominated by common words ("the", "and", "of"). | Picks filler, not the claims. | Words are lower-cased Unicode word runs of 3 or more letters, minus a short stop-word list; each distinct word counts once per passage. |
| 9 | Pages in Chinese or Japanese have no spaces between words, so no passage shares a "word" with the answers. | Every score is 0 and the pick is arbitrary. | Ties are broken by page order, so a page with no shared words keeps its first passages: the same as today. A test with a Japanese page pins that. The paid run includes a non-English page. |
| 10 | A page stuffs its text with words copied from the answers so its passage is picked. | An instruction hidden in that passage reaches the judge more often. | The page was already untrusted and fenced (W53). Picking does not add a channel: it chooses among text the page already controls. The v2 system prompt keeps saying page text is untrusted. |
| 11 | Picking only passages that share words with the answers shows the judge text that agrees with them, and hides context that contradicts. | Faithfulness scores drift upward. | Shared words select a topic, not agreement: a passage that contradicts a claim uses the claim's words. Still unmeasured: the extra paid runs compare picked passages against the first 4,000 characters on the same question and pages, and ADR-0150 records the result before switch-on. |
| 12 | The judge reads passages as one continuous text and treats a gap as a sentence. | A claim is "supported" by two halves from different places. | Passages are joined with a visible marker (" … "), in page order, and the v2 system prompt says a PAGE entry may be passages from the page with gaps marked. v2 has no paid golden yet, so its text can still change; the golden is captured after this. |
| 13 | Picking costs CPU inside the run slot (8 pages, 262,144 bytes each). | More slot time. | Measured on the largest allowed page before merge; recorded in ADR-0150. |
| 14 | A page shorter than 4,000 characters changes too (furniture removed). | Changes what the judge reads for pages the owner's decision did not cover. | Pages whose visible text is at most 4,000 characters are kept exactly as today. Furniture is dropped only for longer pages. |
| 15 | The comparison runs need both reading modes on the same pages, so someone adds a production setting for it. | A new switch in production nobody asked for. | No setting. The measurement script fetches the pages once and builds both prompts from the same fetched text. |
| 16 | The page text, the picked passages or the claim words reach a log, a store or a response. | Retention outside `docs/48`. | The same rules as W29: they live in the judge call only. Tests scan responses and logs. |
