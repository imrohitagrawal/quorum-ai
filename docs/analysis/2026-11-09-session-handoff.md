# Session handoff, 2026-11-05 to 2026-11-09

Written by the session. Decisions are the CHG rows named here, each a plain restatement (CHG-102).

## Shipped

- **#624, W140: the page's start-up requests have a time limit and a way out.** Squash-merged as
  `94cfd2a`. Each start-up request is given up at 15 s and repeated once, only when no HTTP answer
  came; "Still connecting…" shows at 10 s, and at once after "Try again"; at about 31 s a card,
  "Can't reach the server", offers "Try again". ADR-0189 records the design and supersedes two
  clauses of ADR-0178, decision 6. The owner's decisions are CHG-111 (build it first) and CHG-113
  (the words, and the notice at once after "Try again"). Deploy run 42648216061 has the job
  "Deploy to Fly.io" concluded `success` (the other Deploy runs for that merge were skipped or
  cancelled); production `/status` reported `build_sha` `94cfd2a…`, `/ready` answered 200, and the
  served `app.js` holds the new limits. The path where a request gets no answer was proved locally
  only: production cannot be made to hang without touching it.
- **#625, the same notice's stacking test made robust.** A blocking test added by #624 probed
  two points at the notice's rounded corners, just outside the shape, and failed once in CI with
  the page correct. It now probes five points clear of the corners and still fails on the three
  real faults it guards.
- **Recorded, not built:** the owner's page decisions of 2026-10-30 as CHG-112, with board rows
  W136 and W137 updated and W141 to W144 added. W145 records what W140 leaves.

## Open, in order

- **The dependency updates:** the five workflow-action majors #609 to #613 (W122 to W126), then the
  grouped and range updates #603 to #606. Each action update must also regenerate its board row: its
  needle changes state when the pin moves, which is what failed `validate-and-test` and `pytest` on
  them. Re-run after #624, #612's signed-in lane also failed a W140 stacking test that was
  fragile at the notice's rounded corners (fixed by #625), and #613's CSP smoke job timed
  out installing WebKit.
- **The owner's page decisions (CHG-112):** W136, W137, W141, W142, W143 and W144, ahead of the
  queue below (CHG-112). W51 and W129 (CHG-106, CHG-107) follow them; that position is the
  session's, not set by a CHG row.
- **Then:** W117, W118 with W79, the rest of W121, W62, the public-record cleanup, W120, W119, and
  W114's pull request B, W80, W75, W76, W95's code part and W113's redesign.
- **W145**, after the rows above (the session's order): writes after a healthy start-up have no time limit; "Try again" followed by an HTTP
  failure still reloads; and smaller points listed in the row.

## Technical traps

- **`GET /v1/session` is not safe to repeat freely.** Each call replaces the anti-forgery token,
  and a call without a usable cookie counts against the network's daily session limit. ADR-0189
  repeats it once, only after no answer, inside the tab lock.
- **Local e2e lanes start failing after many runs** with `[data-view="composer"]` never visible and
  the next lane's web server timing out: the local record of new sessions, which the daily
  new-session limit counts, has filled up. Delete `.data/feedback_events.sqlite3` in that
  checkout and run the lane again.
- **Playwright's fake clock is shared by a whole browser context.** Advancing it for one tab also
  fires another tab's timers, so boot the second tab before holding the first. Advance in steps
  (run 15 s, wait for the abort, run 1 s, wait for the next request): one long jump can skip a
  request a test means to count.
- **`toBeInViewport`, not `toBeVisible`,** for anything that must be on screen: `toBeVisible`
  passes for an element scrolled away.
- **`make validate`'s completion check reads "in production" as a claim** and needs a cited proof
  in the same paragraph, even inside an ADR's description of a setting.
- **Test files are named by topic.** Tests a review round adds go into the topic file they belong
  to, with helpers in `e2e/fixtures/`, never into a file named after the review.
