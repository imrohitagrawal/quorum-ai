# Session handoff — 2026-09-30

This session followed `docs/analysis/2026-09-29/NEXT-SESSION-PROMPT.md`: first the
findability map, then the sign-out lockout (board row W34). What merged is in
`git log origin/main`; each pull request body carries its evidence. This page says
only what `git log` does not.

## Merged and running in production

- **#527, the map.** `docs/README.md` (one row per kind of information → its one
  home), checked by `scripts/check_docs_map.py --check` in `make validate`;
  the 2026-09-28..30 notes in `docs/analysis/2026-09-29/`; CHG-026; board rows
  W33–W41. Deploy job succeeded on run 36681024638; `/status` reported
  `build_sha` `d8087d4`.
- **#529, the mutation-run fix.** The two test modules #527 added failed inside
  mutmut's `./mutants/` copy (no `.git`, so `git ls-files` lists nothing);
  they now resolve the real root and are deselected under mutmut. Merged as
  `ca4ff94`.
- **#528, W34 (ADR-0139): a capped network gets a sign-in-only session.**
  Merged as `d173aec`. Deploy: one Deploy job succeeded (run 36695862418) after the E2E run
  36694020309 passed; `/status` reported `build_sha` `d173aec`. Production was
  probed only through `/status` (a capped-page probe would spend this
  network's own daily allowance).

## How W34 was built (the separation the owner asked for, first use)

Failure modes and the ADR first; a test-designer agent wrote the acceptance
tests red (23 of 28); a builder agent made them green without editing them;
review round 1 (a break-it reviewer, a prose auditor against the transcript,
Codex, and a product reviewer driving the real server in Playwright's chromium)
found two required gaps the design had missed (`/ui` has no per-minute limiter;
the warnings route writes durable rows) and one test gap (the in-memory-only
guard); the designer added tests, the builder fixed, round 2 found one more pin
to add and corrected its own size figure. Two rounds, then stop.

## Waiting on the owner

- The trust-score visual flake reached 644 px on a docs-only merge (E2E run
  36677984086); CHG-026 k sized the tolerance at "just above 589". W41's row
  now says 644; the owner may want to re-measure before choosing.
- **The mutation gate cannot measure a change that touches the session code**
  (board row W42): in CI its clean run inside `./mutants/` charged one run
  twice in `test_spend_key`; locally the same run scored 156 killed and 0
  survived but 201 mutants died with a segmentation fault in
  `test_context_carry.py::test_non_string_context_value_is_rejected_not_crashed`
  under mutmut's per-mutant runner, and the test passes when run directly
  with a mutant switched on. Advisory, so nothing blocked; unmeasured is the
  honest word for W34's score.
- Bug 4's second half (show the remaining anonymous allowance before the cap is
  hit) is not built; W33.
- The empty question box is already red with "Question is required." on one
  plain load of `/ui` right after signing in, before anything is typed
  (measured in four browser runs on the final W34 head; board row W43). Not
  W34's; goes with the owner's bugs (W33).
- Two advisory copy points on the capped page (PR #528's review comment):
  when the minute budget is spent the page drops the sign-in control without
  saying "try again in a minute"; the first bullet under the button reads
  oddly for someone who just signed out.

## Traps this session paid for

- **A correction round adds false claims faster than a draft.** Round 2 of the
  map's prose audit found eight wording defects in the round-1 fixes (three
  wrong message attributions among them). Audit the corrections, not only the
  draft.
- **The cited-paths gate reads the COMMITTED diff.** Rewording a phantom path in
  the working tree does not clear it until the commit; and copied notes that
  cite files of ANOTHER repository must be reworded so they are not path-shaped.
- **httpx `cookies.set` adds instead of replacing** after a server `Set-Cookie`;
  a two-tab test fails for every correct implementation. Clear the jar first.
- **The Codex subagent's shell lacks `~/.local/bin`**; "Codex CLI is not
  installed" is a PATH message. Codex cannot execute here (read-only sandbox);
  pair it with an executing reviewer.
- **The board's unpinned count is a pinned number**: adding unpinned rows means
  editing the "N of them unpinned" sentence by hand; `make open-work-write`
  updates the State column only.
- **Adding a folder index file (README.md) inside `docs/<folder>/` turns the
  docs-map gate red** — by design; regenerate with `python3 scripts/check_docs_map.py`.
