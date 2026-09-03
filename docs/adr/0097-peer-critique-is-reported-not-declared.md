# ADR-0097: Peer critique is REPORTED, not declared

## Status

Accepted — 2026-09-03 (follow-on to the #290 live window; issue #290)

## Context

Peer critique went live in production on 2026-09-03 (`6d13643`), and it was
invisible from outside the process. Measured that day, on that build:

**1. No endpoint reported it.** `/status`, `/ready`, `/metrics` and `/ui/ops`
were fetched from production and none carried `peer_critique_enabled`. The only
way to answer "is the expensive debate shape on?" was to read `fly.toml` and
read `fly.toml` at the SHA `/status.build_sha` reports. That narrows the
guess but does not remove it: the deployed environment can still differ from
the file at that commit, and nothing served the runtime value.

**2. The posture watchdog could not see it.**
`grep -n peer_critique scripts/live_posture_check.py` returned NOTHING. That
script is scheduled every 30 minutes against what production actually serves
(GitHub throttles scheduled workflows; that workflow records its own measured
gaps as min 21.7 / median 53.4 / max 129.4 minutes), and it is
the mechanism this repo built precisely so a paid posture cannot run
unattended. It read `judge_enabled` and not this.

**3. It is a real multiplier.** Peer critique replaces 2 moderator debate calls
with up to 8 critic calls, at four models' prices — the reason ADR-0095 shipped
it behind a flag and made the fail-safe bound follow that flag.

This is the fault ADR-0013 named one subsystem over, in its own title: **a paid
subsystem may not be enabled invisibly.** The judge got `judge_enabled` on
`/status` for exactly this reason. Peer critique shipped without the equivalent.

## Decision

**Report it everywhere the judge is reported. Do NOT give it a per-window
declaration.**

1. **`/status` carries a boolean `peer_critique_enabled`**, read straight from
   the setting `debate._build_peer_round` gates on. ADR-0013's rule, applied
   again: ONE predicate, two readers, so the operator-visible signal cannot
   drift from the behaviour that spends the money. State only — no model ids,
   no prices, following `error_tracking`'s refusal to name its vendor.

2. **The watchdog probes it and names it on every posture line**, alongside
   `judge_enabled`. An unreadable value is reported as unreadable, never as
   `false` — `fetch_judge_enabled`'s rule, and for its reason: `false` would be
   a claim about a paid subsystem made from a value nobody read.

   That sentence was FALSE when first written, and the correction is the
   interesting part. The note was appended to `judge_note`, which is built
   after three early returns and then omitted from three more f-strings, so
   **6 of the 12 `return PostureResult` sites carried nothing** — including
   `LIVE_JUDGE_UNDECLARED` (the alert about an undeclared paid subsystem on a
   live money-spending posture) and the branch that fires when this very
   declaration file cannot be parsed. Every test at the time exercised one of
   the six branches that happened to work, and a code comment asserted the
   opposite of the truth. It is now appended in a wrapper around the decision
   function, so it is total by construction rather than by remembering twelve
   sites, and `test_every_posture_decision_names_peer_critique` enumerates
   `PostureDecision` to keep a thirteenth from being added silently.

   The wording is HEDGED for a second reason review demonstrated: the flag is a
   STATE, not a promise. A run whose slots all fell back to simulation has no
   eligible critic, so `_build_peer_round` returns `None` and the moderator
   shape runs with the flag still true — and the watchdog counts that host as
   live. "would dispatch, on a run that has eligible critics" is true;
   "dispatches" was not. On a flag-off posture the note says no critic call can
   be dispatched at all, rather than asserting spend one sentence after the
   same line says the money switch is off.

3. **It never alerts on its own.**

## Why no per-window declaration, when the judge has one

This is the asymmetry a future reader will ask about, so it is recorded rather
than left to look like an oversight.

The judge needs `"judge": true` in the window because **its spend reaches no
ledger**. ADR-0013 §3 measured it: no GET or DELETE route reaches any ledger
writer, so while the judge is on, `global_daily_spend_usd` under-reports by an
amount that scales with reads, and the $5.00/day global ceiling does not bind
that spend at all. Nothing else was watching it, so the declaration had to.

Peer critique is the opposite on both counts, measured on this tree:

| | judge | peer critique |
|---|---|---|
| Spend reaches the ledger | NO (ADR-0013 §3) | YES — inside `debate_total`, which is inside `raw_total` (`costs.py:2329-2330`) |
| Gated on live execution | no (fires on a GET) | YES — every critic call routes through `_call_debate_model`, which returns `None` unless `openrouter_live_execution_enabled` (`debate.py:1699`) |

So the live-window gate that already exists binds peer critique's money, and
the ceiling binds its cost. What was missing was not authorisation; it was
sight.

**Rejected: add a required `"peer_critique"` boolean to every window.** It would
have invalidated the window that was open when this was written — the whole
file becomes untrusted on an unparseable entry, deliberately — and taken the
watchdog RED on a correct, declared, attended posture. A watchdog that goes red
on a correct posture is a watchdog somebody mutes, which costs more than the
field is worth. If peer critique ever escapes the run charge, this decision
changes and the field goes in.

## Consequences

- `peer_critique_enabled` is a new key on a public payload. `/status`'s schema
  is `additionalProperties: true` with no `required` keys, so `make
  openapi-check` does not move — the same note ADR-0013 recorded for
  `judge_enabled`, re-derived here rather than inherited.
- The watchdog now makes a second `/status` fetch per host per cycle. Deliberate:
  the judge probe already fetches that payload separately, and halving the reads
  by sharing one fetch would diverge the two paths for no measured gain.
- Every posture line is longer by one sentence, including the quiet ones. That
  is the point — a field reported on only some branches is a field an operator
  cannot rely on.
- **The two booleans come from two different HTTP responses.** `main()` fetches
  `/status` once for `judge_enabled` and again for `peer_critique_enabled`, so a
  deploy landing between them yields a line mixing pre- and post-change state.
  Transient, self-correcting next cycle, and it cannot move `should_alert`.
  Recorded rather than fixed: sharing one fetch would diverge this path from the
  judge's for no measured gain.
- **Peer state deliberately does not feed `complete`.** `complete` gates whether
  the workflow may RETIRE a standing alert, and peer state never enters the
  verdict. Including it would have made `complete` false on every cycle until
  this change deploys — and on any rollback, since the old build's `/status` has
  no such key — which would stop the watchdog retiring alerts it should retire.
  That is a worse failure than the one it would document.
- **What this does not do:** it does not make peer critique's cost *visible*,
  only its STATE. What eight critique calls actually cost is what the #290 live
  window is open to measure; ADR-0094's constants wait on that number.
