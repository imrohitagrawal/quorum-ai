# ADR-0121: A user key changes who chooses the flags and who sets the rails

## Status

PROPOSED — AWAITING OWNER. The product owner decided the SHAPE of this on
2026-09-23 (CHG-011 D8, "planned, not next": the principle, the toggles, the
rails and the sequencing below are the owner's words). The owner has NOT
decided its delivery: no pull request is authorised, nothing is scheduled,
and no code in this repository implements any of it. This record exists so
that the first BYOK pull request builds to the recorded shape instead of
re-asking it, and so that the one prerequisite it has (the token binding in
"Consequences") is visible before anyone adds a per-run toggle.

ADR-0119 is reserved by draft PR #491 (#268); ADR-0120 is the panel-size
record. This takes 0121.

## Context

Today every paid call runs on the app's own key. `query_run_orchestration.py`
hard-codes it:

```
credential_source = ProviderCredentialSource.APP_OWNED
openrouter_key = settings.openrouter_api_key or ""
```

(`grep -n "credential_source = ProviderCredentialSource" src/product_app/query_run_orchestration.py`).
`ProviderCredentialSource.BYO_OPENROUTER` exists in `provider_keys.py` and is
assigned nowhere (`grep -rn BYO_OPENROUTER src/` hits the enum only). FR-012
is titled "Required bring-your-own OpenRouter key" while its Behavior line
says the first cut uses server keys only, and the traceability matrix cites
two BYO test files that do not exist (`tests/unit/test_provider_keys.py`,
`tests/integration/test_provider_key_endpoints.py`; `ls` on each: no such
file). So the repository already half-promises BYOK and delivers none of it.

Because the app pays, the app also decides: the money flags (live execution,
the judge, peer critique) are environment settings governed by the
committed, watchdog-enforced window (`configs/live-execution-windows.json`,
`scripts/live_posture_check.py`, ADR-0071), and there is deliberately no
admin toggle surface and no per-run choice (CHG-011 D7). That is the right
posture for the app's money and the wrong one for a user's.

## Decision (the owner's shape, D8)

**Principle: the party paying chooses the flags; the party at risk sets the
rails.** Two postures, keyed on the credential source of the run:

| | App-owned key (today) | User key (BYOK) |
|---|---|---|
| Live execution | the committed window; off by default | on by default: a user key IS a key that may be spent |
| Judge (Layer B) | operator setting, watchdog-declared | a user toggle, on by default, a priced `by_stage` row; runs on the USER's OpenRouter key through the same `call_with_prompt` seam |
| Peer critique | operator setting, shown honestly (D5) | a user toggle, on by default, a priced `by_stage` row; per-run peer/moderator choice allowed |
| Global daily ceiling (`GLOBAL_DAILY_CEILING_USD`) | keeps the app's spend bounded | DROPPED: it bounds the app's money, not the user's |
| Per-account 24h envelope (`DAILY_CAP_USD`) | keeps one visitor from draining the app | DROPPED, replaced by the user budget window |
| Live-execution window | governs | DROPPED for this run's dispatch |
| User budget window | — | ADDED: $5 default; the existing cost gate asks before a run would cross it |
| Per-run hard cap (`HARD_LIMIT_USD`) | keeps | KEEPS: a runaway single run is the same risk on any key |
| One run at a time per session | keeps | KEEPS |

Abuse limits under a user key, the owner's numbers: about 100 to 200 session
mints per IP per day (today's `SESSION_MINT_CAP_PER_IP = 2` exists because the
app pays; office networks share an IP), and about 10 requests per 1 to 2
minutes. The exact constants are for the rails pull request to measure and
propose.

"Live execution" generalises from "the app's flag is on" to "this run holds
a key that may be spent" (D9). `_live_execution_enabled` gains a term for the
credential source; `_peer_critique_in_effect` gains one term for the same
reason, and stays the single predicate every piece of shape copy reads.
Nothing new reads `openrouter_live_execution_enabled` directly.

## Sequencing (the owner's, D8)

1. A board row (W28) and the failure-mode page
   (`docs/analysis/2026-09-23-byok-failure-modes.md`) — this pull request.
2. PR 1: key intake and scoping — the session holds the key server-side,
   never the browser; `credential_source` is RESOLVED per run instead of
   hard-coded; removal mid-run is defined (EDGE-013).
3. PR 2: rails by credential source plus the budget window.
4. PR 3: the user toggles and the per-run shape — ONLY after the
   confirmation token binds the slot list and the shape (below).

## Rejected alternatives

- **An admin toggle surface for the app-owned money flags.** Rejected in D7:
  the window plus the watchdog is the control, and a toggle that a page can
  flip is the invisible enablement ADR-0013 forbids.
- **A per-run peer/moderator choice under the app key.** Rejected in D7: the
  app pays, so the operator chooses; a per-run choice would also make the
  cost gate's "this run" copy depend on a control the token does not bind.
- **Keeping the 2-per-day mint cap for BYOK visitors.** Rejected in D8: the
  cap protects the app's key; a user spending their own key behind an office
  NAT would be locked out after the second colleague.
- **Running the judge on the app's judge key for BYOK runs.** Rejected: it
  moves the user's chosen spend back onto the app, outside the window, and
  the judge already has its own seam (`call_with_prompt(openrouter_key=...)`,
  `evaluation.py`) so the user key can be passed as-is.

## Consequences

- **Prerequisite, and a live debt today (D9):** the confirmation token binds
  `account_id | query_run_id | estimated_cost_usd | expires_at | nonce`
  (`costs.py::_format_token`) and NOT the slot list or the shape
  (`docs/analysis/2026-09-23-session-handoff.md` §3). Under the app key the
  cost gate hides this (equal-cost mixes only). Under a user key with a
  per-run shape toggle it would let a token minted for a moderator run
  confirm a peer run at up to eight extra critic calls. The binding lands
  BEFORE any per-run toggle; W5 must not add a per-run choice first.
- Every optional stage stays a priced `by_stage` row; a stage that can be
  toggled and is not priced is a hidden charge.
- The threat model's T-004 (key leak) and T-006 (cross-account read) widen
  from the app's key to the user's; the failure-mode page enumerates what
  the existing tests already pin and what they do not (no test today asserts
  the key is absent from a model PROMPT).
- `docs/10-functional-requirements.md` FR-012 and the traceability rows for
  TEST-FR-011/012 are repaired by the first BYOK pull request, not here.
