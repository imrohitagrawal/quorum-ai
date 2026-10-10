# ADR-0158: The landing line about sources follows whether pages are read

## Status

Accepted — 2026-10-10, board row W54 (before the switch-on, ADR-0156). The product owner chose
the wording (CHG-039 (b)); when the line changes is the session's call, following ADR-0099's
#458 precedent. The owner may change either.

## Context

The landing page's disclaimers include the fixed line "Sources are cited, but aren't checked
against their pages" (`templates/workspace.html`). ADR-0099 put it there as a real current limit,
and ADR-0096 says no UI copy may imply otherwise. W54 makes the judge read the cited pages when
page reading is in effect; the switch-on's browser review found that, once switched on, the line
becomes false for every live run, and a committed spec (`landing-cta-reachable.spec.ts`)
requires it unconditionally.

The judge reads pages only on a run where at least one answer came from a real model
(`query_run_orchestration._request_path_judge`); with live execution off, no run reaches the
judge and nothing is read. Production's live execution is off today (`/status`,
2026-10-10).

The landing subhead already follows what a run would do, not a bare flag: peer-critique copy
shows only while peer critique is in effect (the flag AND live execution AND a key;
`main._landing_subhead`, ADR-0099's #458 update).

## Decision

The landing line follows whether page reading would run:

| Page reading in effect (`/status` `source_pages_in_effect`) and live execution on | Landing line |
|---|---|
| Yes | "Answers are checked against the pages and PDFs they cite" (CHG-039 (b)) |
| No (page reading off, no judge, or live execution off) | "Sources are cited, but aren't checked against their pages" (unchanged) |

It is chosen on the server when `/ui` is rendered, as the subhead is, so the page never shows
the wrong line first.

## Rejected alternatives

- **Follow the page-reading setting alone.** It would claim checking while every run is
  simulated and nothing is read.
- **Hide the line when page reading is on.** Offered; the owner asked instead for a line that
  says what is checked (CHG-039 (a)).
- **"Cited web pages and PDFs are read to check answers, where sites allow it."** The session's
  recommendation; the owner chose the shorter line, knowing it overstates for pages a site
  refuses or the 8-second budget does not reach (CHG-039 (b)). The trust note on each result
  says which pages were read and which were checked by preview only.

## Consequences

- With production as it is today (live execution off), the landing line does not change.
- In a live window with page reading on, the landing says answers are checked against the
  pages and PDFs they cite; the result's trust note gives the per-run detail.
- `landing-cta-reachable.spec.ts` asserts the line that matches what the server reports, in
  both states.
