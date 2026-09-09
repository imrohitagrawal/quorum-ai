# ADR-0108: Round 2 is announced when it starts, not when it has finished

## Status

Accepted — 2026-09-09.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture.

## Context

`run_debate_rounds` executes BOTH debate rounds inside one call. The
orchestrator could therefore only move the stage markers around that call: it
marked `debate_round_1` RUNNING, made the call, and on return fired
`debate_round_1` COMPLETED, `debate_round_2` RUNNING and `debate_round_2`
COMPLETED in a burst.

**The burst is `settings.stage_delay_ms` wide — 5 by default
(`config.py`) — against `app.js`'s 750 ms poll interval.** So "round 2 is
running" was not merely reported late; it was a state the UI could essentially
never observe, and on the rare poll that caught it, the round it described had
already finished.

Two corrections to the original report, both from re-verifying it:

- its line numbers were off by ~25 (`query_run_orchestration.py:1304-1410`, and
  the `debate.py` round-1 call site is `:1013`, and round 2 dispatches after the
  skip gate -- grep `_build_peer_round(` rather than trusting a line number,
  which is the standard this very paragraph is holding the report to);
- it proposed choosing between "a callback, splitting the orchestration call,
  or emitting the transition before dispatch" *after* establishing whether the
  UI polls or streams. It polls: `app.js`'s `startPolling` uses
  `setInterval(..., 750)`, and **nothing in `src/` serves SSE to the browser** —
  `grep -rnE "EventSource|text/event-stream|StreamingResponse" src/` returns
  nothing.

  A first draft of this paragraph claimed "no SSE anywhere in `src/`" and cited
  `grep -rn "EventSource|text/event-stream|StreamingResponse|sse"`. Both halves
  were wrong, and review caught them. The claim is false — `providers.py` has a
  full SSE frame parser (`_iter_sse_data`) for the OpenRouter *client* path.
  The command is worse than the claim: basic `grep` treats `|` as a literal, so
  that pattern matches nothing against **any** tree, including one full of
  `EventSource`. It was a check that counts nothing, quoted inside an ADR as
  the proof of its own conclusion — the exact shape AGENTS.md rule 7 forbids,
  shipped in the document arguing for rigour.

## A finding that changes where a fix may usefully land

There are four stage-state surfaces. **Two are dead markup.**

| Surface | Visible? |
|---|---|
| `#live-stage-strip` (4 tiles) | YES |
| `#live-status-text` pill | YES |
| `#progress-list` (aside) | NO — `app.css`: `.layout > aside { display: none }` |
| `.workflow-progress` stepper | NO — `app.css`: `.workflow-progress { display: none }` |

The stepper also maps *both* rounds to one step
(`if (stageName.startsWith("debate")) return "debate"`), so it could not show
this defect even if it were rendered. Nothing in this change touches either
dead surface: fixing copy on markup that never renders is a mistake this repo
has made before.

## Decision

`run_debate_rounds` takes an optional `on_round_two_start` callback and fires it
at the real boundary. The orchestrator moves both markers there.

It is placed **after** `_should_skip_round_two`, not at the end of round 1. A
round 2 that is skipped must never be announced as started — that would report
work the user was never given. This is the reason the callback is not simply
fired when round 1 ends, and it has its own test.

The post-return `debate_round_2` RUNNING write becomes conditional on the
callback not having fired. Re-marking a finished round RUNNING would flip the
strip from complete back to running on the next poll: the same defect in the
other direction.

Nothing passes `allow_terminal=True` from the seam. `update_status`'s F-05
guard silently refuses writes to an already-terminal run, so a cancel that
landed mid-round keeps its own story — which is the behaviour
`test_f05_terminal_status_not_overwritten` pins.

## The bite-proof did not exist and had to be written

**Nothing in the suite observed the ORDER or TIMING of these transitions.**
Every existing assertion reads the run's final state or one seeded snapshot, so
a build that never marked `debate_round_2` RUNNING at all would have been green
everywhere. Verified by grep over `debate_round_1|debate_round_2` across
`tests/`: every hit concerns `missing_steps`/`failed_steps`, terminal-write
refusal, enum membership or cost telemetry.

`tests/integration/test_debate_stage_boundary.py` takes three snapshots from
*inside* the debate call: on entry (round 1 running, round 2 pending), at the
boundary (round 1 completed, round 2 running — the state the old code could not
show), and after (both completed, so the fix does not strand round 2 in
"running").

Proven by mutation, `cp` aside and restored from the copy, `diff -q` byte-exact:

| mutation | result |
|---|---|
| callback deleted from the seam | boundary test RED, skip test green |
| callback moved ABOVE the skip gate | skip test RED, boundary test green |

The two mutations redden different tests, which is what makes them a pair
rather than a duplicate.

**One of those tests was vacuous when first written.** It asserted inside
`if "debate_round_2" in body["missing_steps"]` and drove the skip with the
phrase `"skip round two please"`. The real trigger is `"force debate timeout"`,
gated to `runtime_environment=LOCAL`, so the guard never entered and the test
measured nothing. It asserts unconditionally now and verifies the skip actually
happened as a precondition.
