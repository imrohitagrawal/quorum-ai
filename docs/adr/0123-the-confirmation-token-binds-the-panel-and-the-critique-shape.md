# ADR-0123: The confirmation token binds the panel and the critique shape

## Status

Accepted — 2026-09-24. Code and tests. **Authorises nothing**: it flips no
flag, opens no window, moves no money constant, and adds no per-run
toggle. It closes the prerequisite CHG-011 D9 names as the one thing that
must land BEFORE any per-run choice (W5's `mode: "quick"`, BYOK's per-run
shape), and that ADR-0121's Consequences and the BYOK failure-mode page
(row 7) named as a live debt. **Attribution, precisely:** CHG-011 records D9
as PLANNED, in the session's wording (the prompt the owner asked the session
to write on 2026-09-23), and the owner has not separately confirmed that
wording; on 2026-09-24 the owner typed *"Order: W5 first (small, unblocked
now), then W7 as its own package."* — the session's own line of 06:21:09Z
typed back, which the register labels assistant-drafted and reads as "W5
before W7" — and, in the owner's own words, *"BYOK delivery timing: after
all the current features and bugs are worked upon."* (D8); the owner did not
contest the session's sequence that puts this package second (CHG-012 D6). So the prerequisite is
a recorded plan the session proposed and the owner did not object to, not an
owner decision in the owner's words; the design below is the session's.

## Context

The confirmation token is how a visitor accepts a run whose estimate sits in
the `require_confirmation` band. Before this record `_BoundToken` held
`account_id`, `query_run_id`, `estimated_cost_usd` and `expires_at`
(`grep -n "class _BoundToken" -A 8 src/product_app/costs.py` on `main` at
b6213c4), and `_verify_confirmation_token` compared the account, the cost
and the expiry. Nothing recorded WHICH models the estimate had priced, in
what ORDER, with which search flags, or in which critique SHAPE (moderator
or peer). So a token minted for one panel confirmed any other panel at the
same price.

Two facts the design turns on, both measured on `main`:

- **The HMAC digest is a lookup key, not the binding.** `_format_token` puts
  five fields into an HMAC once, at mint; `_verify_confirmation_token` never
  recomputes it (`grep -c compare_digest src/product_app/costs.py` → 0). The
  binding is the stored record and its comparison, so "bind into the HMAC
  input" (the failure-mode page's wording) was never where the check could
  live. This record extends BOTH, and the mutation table below shows the
  record comparison is the term that bites.
- **The cost-equality check hid the hole for most pairs and not for all.**
  A panel of two and a panel of four rarely price alike, so the existing
  `confirmation.estimated_cost_usd != estimate.estimated_cost_usd` refusal
  caught them first. The same four models in REVERSE order price identically
  to the cent, and the estimate's token confirmed the reordered create with
  `202` (the RED run below). Under a per-run shape toggle the same gap would
  have let a moderator-priced token confirm a peer run at up to eight extra
  critic calls (ADR-0121 Consequences).

## Decision

**1. The token binds the ORDERED panel as `(model_id, search)` pairs.**
`panel_key(model_slots)` is the one function both the mint (inside
`estimate()`) and the verifier read. Order is part of the panel because a
reorder is the free equal-price collision; `search` is part of it because
it moves the price on paid models and not on free ones, and both routes
derive it from the same `slot_search` list (`_validated_model_slots`), so
binding it can never wrongly refuse a token minted by `/estimate` for the
same request.

**2. The token binds the shape the ESTIMATE priced, as a string.**
`priced_critique_shape()` returns `"peer"` or `"moderator"` from the same
process-global `settings.peer_critique_enabled` the three pricing reads in
`_cost_components` use. It is deliberately NOT `main._peer_critique_in_effect`
(the copy predicate: flag AND live AND key): a token must bind what its
estimate priced, or a live window opening inside the five-minute TTL would
refuse a correctly priced token. The two strings are now defined in `costs`
and re-exported by `debate`, so the run's recorded `critique_shape` and the
token's bound shape are one vocabulary by construction; a third value
(`"quick"`, W5) fits the same field.

**3. Verification compares tuples, and a refused binding CONSUMES the
token.** `record.panel != panel or record.critique_shape != critique_shape`
is checked after the account and the cost. It sits before the expiry check
in the source as a reading aid only: both branches pop the token and return
False, so an expired-and-mismatched token is consumed either way and the
order is unobservable from outside (swapping the two blocks is an
equivalent mutant; nothing pins it, nothing can). On a mismatch the token is
popped: a token that failed its binding must not be
probed again with another panel inside its TTL, and the `402
COST_CONFIRMATION_REQUIRED` the create route answers with carries a fresh
token minted for the panel that request sent, so a legitimate retry loses
nothing. The pre-existing cost and account refusals keep their behaviour
(not consumed) — one concern per record.

**4. `evaluate_confirmation` REQUIRES the panel.** `model_slots` is a keyword
argument with no default; the create route passes the validated slots of
the request it is confirming. A caller that could omit the panel would
re-open the hole this record closes.

**5. What is deliberately NOT bound: the query text.** Two queries of the
same length and the same panel price identically, so a token minted for one
confirms the other. Money is unchanged (same cost, same panel, same shape),
so this is not a bypass of the cost gate; it is stated so that "the token
binds what its estimate priced" is read as the panel and the shape, not
every pricing input. Binding a digest of the query is a possible later
change with its own record.

**6. Nothing on the wire changes.** `CostConfirmation` and `CostEstimate`
are unchanged and the token stays an opaque string, so `openapi.yaml` is
untouched, `make openapi-check` is unaffected, and the `402` body still
carries code, message and a fresh estimate — never the reason, so the
refusal is not an oracle for which field mismatched. The schemathesis lane
excludes `POST /v1/query-runs` and is therefore no evidence either way.

## Measurements

All on the `wp/token-binds-panel-and-shape` worktree at b6213c4 plus this
change; no paid call.

| what | command | result |
|---|---|---|
| RED, the route | `uv run pytest "tests/integration/test_query_run_cost_guardrails.py::test_a_reordered_panel_cannot_reuse_the_estimate_token" -q --no-cov` on `main`'s code | `assert 202 == 402` — the reordered panel confirmed with the estimate's token |
| GREEN | `uv run pytest tests/unit/test_confirmation_token_binds_panel_and_shape.py tests/integration/test_query_run_cost_guardrails.py tests/unit/test_cost_guardrails.py tests/unit/test_debate_orchestration.py tests/unit/test_peer_bound_is_a_true_ceiling.py -q --no-cov` | `55 passed` (13 in the unit file, with an autouse fixture pinning the fallback catalog: prices are a process-global cache, and the wire tests need the fixture panel in the confirmation band) |
| mutation, by hand (cp aside, mutate, purge `__pycache__`, run the three token files `tests/unit/test_confirmation_token_binds_panel_and_shape.py`, `tests/integration/test_query_run_cost_guardrails.py`, `tests/unit/test_cost_guardrails.py` — baseline `40 passed` — restore, `cmp`) | M1 drop the panel comparison | 4 failed |
| | M2 drop the shape comparison | 2 failed |
| | M3 compare the panel as a set (reorder admitted) | 2 failed |
| | M4 `panel_key` drops the search flag | 2 failed (`test_the_panel_key_carries_each_slots_search_flag_in_order` and the search wire test; the first draft had neither and M4 SURVIVED, which is why they exist) |
| | M5 a refused binding leaves the token in the table | 8 failed |
| | M6 `priced_critique_shape` ignores the flag | 3 failed |
| | M7 the verifier ignores the account (pre-existing check, pinned on review round 1) | 1 failed |
| | M8 `evaluate_confirmation` passes a literal shape (the verify end of the shape wire; found by review round 1, which showed the first draft's tests never crossed the wire) | 1 failed |
| | M9 `estimate()` mints with a literal shape (the mint end; SURVIVED the first wire test, which minted under the moderator flag where the literal is indistinguishable — killed by minting under peer on an ALLOW-band panel and verifying directly). On the pinned catalog no route-level request reaches the shape comparison: every panel that sits in the confirmation band under moderator prices into BLOCK under peer (review sweep, 3,393 such cases, 0 exceptions), and a panel that sits in the band under peer prices differently under moderator, so the cost check refuses first. The same-object unit tests are the only path that crosses the shape wire, and are therefore the pin | 1 failed |
| | M10 `evaluate_confirmation` forces every search flag true before comparing (the verify end of the search wire) | 1 failed |
| cardinality (rule 6b) | the unit file asserts `len(service._tokens)` at every step on a fresh `CostEstimationService`; the route test asserts exact deltas on the singleton (+1 on `/estimate`; +1 −1 on the refused create; +1 −1 on the accepted one) | in the GREEN row |

The HMAC term is deliberately not in the mutation table: removing the two
new fields from `_format_token`'s message changes no verdict, because
verification never recomputes the digest (Context). That is a property of
the pre-existing design, stated rather than hidden.

## Consequences

- **W5 and BYOK may add a per-run choice** without reopening this hole:
  the token refuses a shape or panel it was not minted for. CHG-011 D9's
  prerequisite is met.
- **A slot edit after the cost gate now yields a 402 and a re-estimate.**
  `applyPanelSelection` in `app.js` does not clear `state.currentEstimate`,
  so a visitor who changes a slot after confirming sends the old token with
  the new panel; before this record that was accepted at equal price, now it
  is refused and the existing `COST_CONFIRMATION_REQUIRED` handler
  re-estimates. Its toast says the confirmation "expired", which is the
  wrong word for this case; a UI concern, recorded and not changed here.
- **No legacy tokens exist across a deploy.** The table is one process's
  memory (`Dockerfile` runs one worker; `fly.toml` stops idle machines), so
  a deploy empties it and the browser re-estimates on the 402.
- **What this does not change:** the cost-equality and account checks; the
  eviction of the oldest-expiring tokens above 4096 entries (a correctly
  priced token can still be refused by eviction, a machine stop, or the
  TTL); the `402` body; `openapi.yaml`.
- **Prose corrected in the same change:** ADR-0121's Status carries a dated
  amendment (its Consequences bullet is now history); the BYOK failure-mode
  page row 7; the W5 scoping note; board row W28's Blocked-by; the
  `CostEstimationService` docstring, which said the token was "verifiable
  without database access" — it was a table lookup then and is now.

## Rejected alternatives

- **Bind `_peer_critique_in_effect` (the copy predicate).** Would refuse a
  correctly priced token when a live window opens inside the TTL, and the
  estimator does not read that predicate. The token binds what was priced.
- **Bind model ids only, unordered.** A reorder is the measured free
  collision, and `search` moves the price; a set re-admits both.
- **Rely on the cost-equality check.** It accepts every equal-price pair,
  the reorder included (the RED row).
- **Keep a refused token alive for retries.** The 402 already hands the
  client a fresh token for the panel it sent; keeping the old one alive only
  lets it be probed with other panels until the TTL.
- **Add the panel or the shape to the wire (`CostEstimate` fields).** Would
  change `openapi.yaml`, touch 17 `CostEstimate(...)` test constructors in 16
  files (`grep -rn "CostEstimate(" tests | grep -v "CostEstimateResponse\|CostEstimationService"`),
  and give an attacker the field that mismatched. Server-side only.
- **A `mode`-aware token now.** W5 is package 3; this record leaves the
  shape field a string so `"quick"` fits without a second design.

## Related

CHG-011 D9 (the recorded plan, session wording), CHG-012 D6 (the order this
is package 2 of),
ADR-0121 (the debt this closes), ADR-0122 (package 1),
`docs/analysis/2026-09-23-byok-failure-modes.md` row 7,
`tests/unit/test_confirmation_token_binds_panel_and_shape.py`,
`tests/integration/test_query_run_cost_guardrails.py`.
