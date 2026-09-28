# Session handoff — 2026-09-29

The session ran the rest of the queue in `CONTINUE-2026-09-25-ULTRACODE-PROMPT.md`
§5 from the point `docs/analysis/2026-09-28-session-handoff.md` left it. What
merged is in `git log origin/main`; each pull request body carries its
evidence. This page says only what `git log` does not.

## Merged and running in production

W7 part 3: #521 (sign out everywhere, sign-in events, a sign-in start limit;
ADR-0137), #522 (idle expiry with a keep-active reminder; ADR-0138), and
#524 (the `pytest` job gets 20 minutes). W7's board row now reads DONE.
`/status` reported `build_sha` `05c5f0d…` after #524's deploy (one Deploy
job succeeded, run 36484662263). #522 merged at 2026-09-28 19:49Z but reached
production only with #524: its Tests job hit the old 15-minute limit twice.

## Parked as drafts, waiting on the owner

- **#523, W29** (the judge reads the cited pages, part 2): four pull
  requests; with the fetch setting off no shipped money value moves, turning
  it on is the money decision. The decisions owed are in the draft's body.
- **#525, W28 (BYOK)**: the first pull request's plan; six decisions owed
  before a code draft is useful. ADR-0121 stays PROPOSED — AWAITING OWNER.

## Waiting on the owner (new this session)

- **The lockout after an idle expiry** (ADR-0137 and ADR-0138, measured): a
  replacement session after expiry or sign-out still counts against the
  per-address daily cap of 2, so the second in a day gives the address a
  429 and sign-in cannot start. Changing who the cap counts is the owner's
  decision.
- PROPOSED values: ADR-0137's four and ADR-0138's two (idle 120 minutes,
  warning 5); the reminder's wording.
- The visual flake (the `trust-score` dark-theme screenshots; 589, 589 and
  234 pixels) failed a required run three times in this session — #521's
  pull request, then `main` at `633a727` and at `05c5f0d` — each time on a
  change that did not touch the page, and each cleared on a re-run. On
  `main` it strands the deploy until someone re-runs it. Its tolerance is
  the owner's decision.

## Traps this session paid for

- **CI time limits are at the edge.** The `pytest` job took up to 14m50s and
  was killed twice at 15 minutes with the suite complete; #524 gives it 20.
  `validate-and-test` has about 3.5 minutes left under its 20. Going higher
  also moves the deploy gate's wait (1500 s) and the drift alarm's grace
  (1800 s, ADR-0026, sized against it): measure and change the three
  together.
- **A background gate chain outlives its useful result.** Stop it by task
  before editing or starting another; never `pkill` by the venv path while
  a mutation proof in a copy shares that venv (it kills the proof's pytest).
- **`make diff-cover` was red on a branch that had never finished a run**
  (W7 3a, 82%): failure paths in new store code had no tests.
- **Tests that sign in share one stub Google subject**, so a charge in one
  file reaches the process-global spend total another file reads; give a
  test that charges its own subject.
- **A page script's click listeners have no automated test** (no e2e lane
  can sign in); the idle reminder's were driven in a browser only.
