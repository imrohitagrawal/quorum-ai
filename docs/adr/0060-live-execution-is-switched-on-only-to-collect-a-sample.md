# ADR-0060: Live execution is switched on only to collect a sample, and switched back off

## Status

Accepted — 2026-08-19. **Time-boxed by design**: this ADR records a posture that
is expected to be reverted in the same session it was adopted.

## Context

`#268` and `#105` have been blocked for weeks on the same thing: neither can be
decided without real production traffic. Both were deliberately left open rather
than guessed at, per this repo's rule that a guardrail or a classification never
moves on an unmeasured number.

Measured 2026-08-19 on the production volume, via
`fly ssh console -a quorum-ai -C 'ls -la /data'`:

```
-rw-r--r-- 1 quorum quorum      0 Aug 10 15:24 telemetry-billing.jsonl
-rw-r--r-- 1 quorum quorum      0 Aug 10 15:24 telemetry-tokens.jsonl
```

Both streams exist and are **zero bytes**, created when `ab4296c` shipped the
telemetry on 2026-08-10 and untouched for nine days. The sink is wired correctly
— it created the files — but no record has ever been written, because
`telemetry-tokens.jsonl` fires on a successful PROVIDER call and
`OPENROUTER_LIVE_EXECUTION_ENABLED` has been `"false"` throughout, so every run
was `local_simulation`. **The baseline sample size for both issues is zero.**

There is no way to collect that sample without spending real money.

## Decision

Set `OPENROUTER_LIVE_EXECUTION_ENABLED = "true"` in `fly.toml`'s `[env]` block,
collect the sample, and **set it back to `"false"` in a second PR** as soon as the
traffic plan has run.

Three things this decision deliberately does NOT do:

1. **No guardrail constant moves.** `HARD_LIMIT_USD` ($0.25/run),
   `DAILY_CAP_USD` ($0.20/account/day) and `GLOBAL_DAILY_CEILING_USD` ($5.00)
   are untouched (`costs.py:49,116,150`). Issue #180 cost three broken attempts
   learning that a guardrail value never moves on a guess. The budget for this
   exercise is whatever the existing rails allow, and the rails do the bounding.
2. **No Fly secret is used to carry the flag.** Whether a secret of the same name
   overrides an `[env]` value in `fly.toml` is **UNVERIFIED**, and the way to find
   out is not on the path to a paid run. The file is changed, which is
   unambiguous and reviewable in a diff.
3. **The judge is enabled separately and first.** `QUORUM_EVAL_JUDGE_API_KEY` and
   `QUORUM_EVAL_JUDGE_MODEL_ID` were set as secrets by the operator before this
   change. That ordering is deliberate: `evaluation.py:1827` needs both, and
   `providers.py:670` is `openrouter_live_execution_enabled and openrouter_key`,
   so setting the judge secrets alone spends nothing. It is a free checkpoint
   proving the two env names are right BEFORE money can move. It passed —
   `/status` reported `judge_enabled: true, live_execution: false`.

## Measured

Every row measured 2026-08-19 unless marked.

| Question | Command | Result |
|---|---|---|
| Baseline telemetry sample | `fly ssh console -a quorum-ai -C 'ls -la /data'` | both JSONL streams **0 bytes**, created 2026-08-10 |
| Is the judge on before this change? | `curl -s .../status` | `judge_enabled: true`, `live_execution: false` |
| Is spending still zero? | same | `global_daily_spend_usd: 0` |
| What does readiness say today? | `curl -s .../ready` | `state: offline_by_config`, reason names this exact variable |
| What actually gates spending? | `providers.py:670` | `bool(settings.openrouter_live_execution_enabled and openrouter_key)` |
| Is the key already deployed? | `fly secrets list -a quorum-ai` | `OPENROUTER_API_KEY` — `Deployed` |
| Per-account bound | `costs.py:116` | `DAILY_CAP_USD = Decimal("0.20")` |
| Global bound | `costs.py:150` | `GLOBAL_DAILY_CEILING_USD = Decimal("5.00")` |
| Session mint bound | `auth.py:65` | `SESSION_MINT_CAP_PER_IP = 2` per IP / 24h |
| Cost of one 4-slot run | issue #268's worked example | ~$0.026 — **INHERITED, not re-measured**; the live `/estimate` is read before spending |

**Exposure while this reads `"true"`:** every visitor to `/ui` spends real money,
not just the operator. The bound is `GLOBAL_DAILY_CEILING_USD` = $5.00/day, and
that ceiling is the actual protection — not the intention to be quick.

## Rejected alternatives

1. **Leave it on permanently.** Rejected: nothing in the product needs it
   continuously, and the failure mode is silent — an unattended `/ui` visitor
   spends money for no measurement. The whole value here is a bounded sample.
2. **Set a Fly secret `OPENROUTER_LIVE_EXECUTION_ENABLED=true` instead of editing
   `fly.toml`.** Rejected: whether a secret overrides an `[env]` value is
   UNVERIFIED, and testing that theory on the way to a paid run risks either
   spending unexpectedly or believing spending is enabled when it is not.
3. **Raise a guardrail so more samples fit in one window.** Rejected outright —
   see Decision (1). If the sample is short, the honest report is a short sample.
4. **Simulate the traffic instead.** Rejected: it is precisely simulation that
   produced a zero-byte telemetry file. `local_simulation` makes no provider
   call, so it can never populate `telemetry-tokens.jsonl`.
5. **Enable live execution before the judge secrets.** Rejected: it would spend
   money while the judge was off, paying for runs that cannot produce the judge
   measurement, and would skip the free name-verification checkpoint.

## Consequences

- Real money is spent, bounded by the existing rails. Expected total ~$0.40
  (2 session mints per IP x $0.20/account/day), against a $5.00 ceiling.
- `/ready.live_readiness.state` moves from `offline_by_config` to ready.
- The at-cap refusal branch — added by #216, fixed by #342 — becomes reachable,
  and the traffic plan deliberately drives the per-account cap to exercise it.
  It has never been observed executing.
- **This ADR is not complete until its revert lands.** The revert PR should cite
  this ADR and state what the sample actually yielded, including what it did NOT
  settle. A follow-on ADR is not needed for the revert; it is the second half of
  this decision.
- **Revert condition, stated so it is not a judgement call:** revert as soon as
  the traffic plan has run to completion, OR immediately if the global ceiling is
  reached, an unexpected error class appears, or spend moves faster than the
  estimate predicted.

## Related

- ADR-0031 — the durable telemetry these streams come from, and the reading that
  settles each issue.
- ADR-0012 — records `error.metadata.provider_name` as ASSUMED, which #105's
  reading can refute.
- ADR-0051 — the judge checks the spend rails rather than billing from a read path.
- Issues #268, #105, #290, #216, #342, #180.
