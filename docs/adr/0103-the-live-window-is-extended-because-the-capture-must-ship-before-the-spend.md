# ADR-0103: The live window is extended because the capture must ship before the spend

## Status

Accepted — 2026-09-07.

Extends the time-boxed window declared in `configs/live-execution-windows.json`
on 2026-09-03. Supersedes nothing.

**Authorises nothing new in kind.** It does not widen what may run, which
subsystems may be paid for, or any spend ceiling. It moves ONE date, and this
record exists because moving that date is a money decision.

## Context

The window was declared `2026-09-03T07:51:25Z → 2026-09-08T07:51:25Z` to settle
three measurements only a real run can settle. The 2026-09-06 run
(`$0.0806`) settled two of them and **lost the third**, because nothing in the
product captures it: **0 of the 27 `TELEMETRY_FIELD_NAMES` describe an
annotation**, and `_extract_citations` discards any content field at parse time,
so *"do `:online` annotations carry passage CONTENT?"* is unobservable end to
end.

The remedy is small and free — a bounded `annotation_shape` / `annotation_count`
/ `annotation_content_chars` trio, a label and two counts, never content. But it
has to be built, reviewed, gated, merged **and deployed** before the next paid
run, or that run repeats the same loss.

At the moment of this decision the window had **14.9 hours** left. That is not
enough for a change to `providers.py` and the telemetry sink to go through this
repo's own bar — two adversarial review rounds, plus a round for the fix's own
defect, plus rule 14's gates. The choice was therefore between:

- run inside the old window against a build that cannot answer measurement 3
  (i.e. knowingly repeat the 2026-09-06 loss);
- do not run at all, and leave the cap-4000 timing risk unmeasured in
  production; or
- extend the window.

## Decision

**`expires_at` moves `2026-09-08T07:51:25Z` → `2026-09-11T07:51:25Z`, +72h.**
`opened_at` is deliberately UNCHANGED, so the window keeps its identity and the
re-affirmation token — which quotes `opened_at` — keeps working. The `reason`
field records the extension inline so the declaration explains itself without
this file.

Nothing else moves. `judge` stays `true`, `mode` stays `time_boxed`, the
`reaffirm_issue` stays #290, and `GLOBAL_DAILY_CEILING_USD` stays `5.00`.

### Why an 8-day window is defensible, and what actually controls it

**Not its length.** `configs/live-execution-windows.json`'s own README is
explicit that there is deliberately NO maximum window length, and says why: the
#357 failure ran ~3 days and issue #105 legitimately needs ~7 days of
production logs, so no single number separates a runaway from a long job.
*"Is anybody still watching?"* does.

The control is the **24-hour re-affirmation cadence**, and on this very window
it has already demonstrated it works: attendance lapsed at ~31h on 2026-09-07,
`live_posture_check.py` exited 1 with `live_reaffirmation_lapsed`, the watchdog
opened issue #445, and the window stopped sanctioning anything until a human
re-affirmed. An extension buys calendar time; it buys **no** relaxation of that
cadence.

## Rejected alternatives

**Run inside the existing window, before the capture ships.** Rejected: it
knowingly repeats a loss this repo has already paid $0.0806 to learn. The whole
reason Item 3 precedes Item 4 in the handoff is that a sink which does not
capture what is needed makes the money unrecoverable.

**Let the window expire and declare a fresh one later.** Defensible, and close.
Rejected because a new `opened_at` invalidates the re-affirmation token form
that #290's comment history already uses, and because the reason for running has
not changed — this is the same window doing the same job, not a new decision.

**Extend further than 72h.** Rejected: 72h covers build-review-merge-deploy plus
the run with margin, and an extension should be sized to the work, not to
convenience. If it proves short, extend again deliberately — that is cheaper
than a window nobody is attending.

**Raise `GLOBAL_DAILY_CEILING_USD` at the same time.** Out of scope and not
requested. More calendar time is not more money: the ceiling binds spend
per rolling 24h regardless of how long the window is.

## Consequences

- **The window is 8 days end to end.** That is longer than the ~3-day #357
  incident, and the honest framing is that length alone never distinguished
  those cases — attendance does. Whoever holds this window now owes it a
  re-affirmation every 24h until 2026-09-11T07:51:25Z or until
  `make close-window` closes it early.
- **More calendar time is more opportunity for attendance to lapse.** The
  watchdog runs every 30 minutes and files an issue when it does; that is the
  mitigation, and it is already proven on this window.
- **No spend ceiling moves.** `GLOBAL_DAILY_CEILING_USD` stays `5.00`, and the
  per-account and per-run rails ADR-0102 set stay where they are.
- The extension is recorded in the window's own `reason` as well as here, so a
  reader of the config alone is not left wondering why the dates disagree with
  the original declaration.
