# ADR-0148: The judge reads the cited pages, behind a default-off setting

## Status

Accepted — 2026-10-06, board row W29 (#447), wiring only. The product owner decided what
the judge reads and how it is described on 2026-10-04 (CHG-026 (d), (e)) and 2026-10-05
(CHG-028). The design below is the session's; the owner may overturn any of it. Fetching
stays OFF (`quorum_source_fetch_enabled = False` in code; `fly.toml` does not set it).
Switching it on is a separate pull request, after the one paid measured run the owner must
approve first (CHG-027: "ask me before the one paid measured run it needs"), and after the
owner approves the `docs/48` rows for search excerpts and page text. Failure modes, written
before the code: `docs/analysis/2026-10-06-w29-judge-reads-pages-failure-modes.md`.

## Context

The judge (`PR-EVAL-JUDGE-v1`) checks a run's answers against each cited source's title and
address only; it cannot read the page. ADR-0124 built a fetcher (`fetch_cited_pages`) that
pins the address it connects to, bounds time, bytes, pages and characters, and never
raises, but does not read robots.txt and is called by nothing. W52 (ADR-0146) keeps each
search result's excerpt on its source, in memory only. W53 (ADR-0147) makes the
untrusted-text fence catch an altered marker. The owner's decisions:

- fetch cited pages when allowed; when a site's robots.txt disallows it, the judge uses the
  search excerpt (CHG-026 (d), CHG-028);
- judge on titles when none fetched, and say so; a $0 receipt row; the wording "Checked
  against N of M cited pages"; quick mode without pages first (CHG-026 (e));
- live fetching switched on only after one measured paid run (CHG-026 (e), CHG-027).

## Decision

1. **When pages are read.** Only when the judge is configured, the setting is on, and the
   run is a panel run. Quick mode never fetches. With the setting off, every prompt, price
   and visible text is byte-identical to today.
2. **Where.** On the owner branch of the judge's memo (`_memoised_verdict`), once per
   verdict: one fetch call per verdict, never one per reader.
3. **robots.txt.** Read through the fetcher's own pinned path and limits, once per host per
   verdict, inside the same time budget as the pages, and parsed with
   `urllib.robotparser.RobotFileParser.parse` (never `.read`, which opens the URL itself and
   follows redirects). Following RFC 9309: a 4xx answer means fetching is allowed; a
   timeout, a 5xx, an unreadable or oversized file means it is not (fail closed). A 3xx
   answer counts as unreadable: RFC 9309 lets a crawler follow up to five redirects, but
   following one here would need a second pinned fetch; failing closed costs only the
   page, and the excerpt is used instead.
4. **What the judge reads per source**, in this order:
   - the page text, when robots.txt allows it and the page was fetched and usable;
   - the search excerpt (W52), when robots.txt disallows the page and an excerpt exists;
   - otherwise the title and address only, as today.
   A fetch that fails for another reason (timeout, too large, not text) falls back to the
   title and address, not the excerpt: CHG-026 (d) and CHG-028 name the excerpt for pages
   robots.txt disallows only.
5. **Cleaning and fencing.** Page text and excerpts are cleaned the way W52 cleans excerpts
   (control and invisible characters removed, whitespace collapsed, cut to 4,000
   characters) and sit inside the judge's untrusted block, which W53's fence neutralises.
6. **A new prompt.** Page reading uses a new prompt id, `PR-EVAL-JUDGE-v2`, with its own
   system prompt. `PR-EVAL-JUDGE-v1`, its pinned hash and its paid golden capture stay
   byte-identical and are used whenever the setting is off. A stored evaluation records
   the id of the prompt that actually judged it (today `to_eval_json` writes v1 as a fixed
   value).
7. **The judge's input reserve.** When the setting is on, the reserve adds the pages and
   excerpts: at most 8 items (the fetcher's page cap; excerpts replace pages, never add to
   them) of at most 4,000 characters each, both clamped to these LITERAL numbers so a
   larger environment setting cannot outgrow the reserve, plus the v2 system prompt's
   length in place of v1's. When it is off, every pinned bound stays as it is.
8. **The receipt.** A `source_fetch` row at exactly $0 appears in the estimate and the
   measured receipt whenever pages are read, so the step is visible and never priced.
9. **The wording.** With the setting on, a panel run's trust note says "Checked against N
   of M cited pages", N being the sources the judge read a page or excerpt for and M the
   cited sources it saw. When N is 0 it says the judge worked from titles and addresses
   because no cited page could be read. With the setting off, today's wording stays. The
   posture follows ADR-0116: one server-side predicate, served on `/status` and in the
   readiness island, read by the page.
10. **Data.** Page text, like the excerpt, is never served, logged or stored; it lives in the
    judge call only. `docs/48` gains a row for page text sent to the judge provider,
    pending the owner's approval, beside W52's excerpt row.

## Rejected alternatives

- **Fetch after the run's capacity slot is released.** The judge's first call runs before
  the slot is released, so fetching there holds the slot for up to the 8-second budget.
  Moving the judge after the release changes when a verdict exists for every reader, a
  larger change than this one; the slot time is measured in the paid run and recorded
  before switch-on instead.
- **Use the excerpt whenever a fetch fails.** More pages would be "checked", but the owner
  chose the excerpt for pages robots.txt disallows; widening that is the owner's call.
- **`RobotFileParser.read()`.** It opens the robots.txt URL with its own client, outside the
  pinned address and redirect rules.
- **Change `PR-EVAL-JUDGE-v1` in place.** Its hash pin and paid capture would stop
  describing the prompt in use.

## Consequences

- Nothing changes in production until the switch-on pull request.
- With the setting on: up to 8 seconds of fetching in each panel run's slot, robots.txt
  reads included; a larger judge input and a higher price bound; the judge's quality on
  page text unmeasured until the paid run.
- Calls taken by the session (the owner may overturn any of them): (i) fetching on the
  memo's owner branch, inside the slot; (ii) robots.txt fail-closed except 4xx; (iii) no
  excerpt for a failed fetch; (iv) at most 8 page-or-excerpt items; (v) a new prompt id.
