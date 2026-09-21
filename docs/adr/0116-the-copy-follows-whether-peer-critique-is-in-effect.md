# ADR-0116: The copy follows whether peer critique is in effect, not whether the flag is set

## Status

Accepted — 2026-09-21. Code only. **Authorises nothing**: it flips no flag,
opens no live window, and licenses no paid run. The product owner approved this
approach in session (#458's flag half, "code only, no flag flipped").

Completes ADR-0099's premise — "the UI describes peer critique because peer
critique is what runs" — which was false in production. Amends ADR-0097's
"ONE predicate, two readers" by naming which predicate each reader uses.

## Context

`PEER_CRITIQUE_ENABLED` has been `"true"` in production since 2026-09-03 while
live execution is off. In that posture, **no run takes the peer path**, and the
landing page said the models critique each other.

The chain, read from the code rather than assumed:

- `debate._build_peer_round` returns `None` unless `peer_critique_enabled`
  **and** `_eligible_critics` is non-empty.
- `_eligible_critics` keeps a slot only if it is `COMPLETED` **and**
  `providers.model_was_invoked(answer)` — that is, its `provider_path` is
  `OPENROUTER_SEARCH`.
- The only site producing `OPENROUTER_SEARCH` is gated on
  `providers.ProviderExecutionService._live_execution_enabled`, whose terms are
  `settings.openrouter_live_execution_enabled and openrouter_key`.

So the live dependency is real but **indirect**: the live flag is not a term in
the peer/moderator decision at all — it acts through `provider_path`. Measured
on a copy of `18396df`: with the flag on and live off, `_eligible_critics` is
empty and `_build_peer_round` returns `None`; relabel the same answers as
invoked and the peer shape runs even with the live flag off.

Production at the time of writing: `/status` reports
`peer_critique_enabled: true`, `live_execution: false`, and `/ready` reports
`live_readiness.state: "offline_by_config"`. The defect was live, not latent.

## Decision

**1. The copy follows a three-term predicate.** `main._peer_critique_in_effect`
returns `peer_critique_enabled AND openrouter_live_execution_enabled AND
bool(openrouter_api_key)`, read off the same `Settings` object the builder is
given. `_landing_subhead` and `_app_description` both use it.

Those are the same three terms the dispatch gate reads — not a re-derivation.

**2. NOT `/status.live_execution`.** That field is
`readiness.report.state == "live"`, which additionally requires a **cached**
key-auth probe verdict that the spending path does not have. Under a refused
key the probe says "not live" while `_live_execution_enabled` still returns
True and up to eight critic calls are dispatched and billed.
`scripts/live_posture_check.py` already documents that drift and refuses to
read that field; reproducing it in the landing copy would be a second instance
of a defect this repo has already named.

**3. The key term is not optional.** With the live flag on and no key,
`query_run_orchestration` fails the whole run ("Live execution is enabled but
no server-side key is configured"). Promising peer critique on a page whose
every run dies is worse than promising it on a page that simulates.

**4. `/status.peer_critique_enabled` keeps meaning the flag, and a second
field is added beside it.** `peer_critique_in_effect` is computed in the same
dict build from the same settings. Both are reported.

**5. The prospective claim is stated as such.** The predicate says a critic
CAN be dispatched, not that one was. Two reachable states still over-promise
and cannot be known when `/ui` is served: every slot failing, and the run's key
being forced empty by the spend ceiling. `app.js` tells the per-run truth from
`critique_shape`; the landing makes the prospective claim.

## Measurements

All on a copy of `18396df`.

| posture (flag / live / key) | peer path taken? | old copy | new copy |
|---|---|---|---|
| on / off / set — **production today** | no | peer | moderator |
| on / on / missing — run fails outright | no | peer | moderator |
| on / on / set | yes | peer | peer |
| off / on / set | no | moderator | moderator |

Redefining `peer_critique_enabled` instead — the alternative — was applied in a
copy and turned three tests in
`tests/integration/test_peer_critique_is_observable.py` red, including
`test_the_reported_state_matches_the_real_dispatch_gate`, the guard written to
prevent exactly this drift.

`scripts/proofs/mechanism_copy_mutations.py` re-run after repointing its
anchor: **10 killed / 10**.

## Consequences

- The landing page and the API description now say "a separate moderator model
  critiques their answers" in production, which is what production runs. The
  peer sentence returns by itself when a live window opens with a key present.
- An operator reading `/status` can tell a configured-but-dormant deployment
  from a running one without cross-reading `/ready`.
- **The standing risk is unchanged and still visible.** Re-opening a live
  window turns peer critique back on with it, at up to eight critic calls per
  run instead of two, and no gate couples the flags. Keeping
  `peer_critique_enabled` as the flag is what keeps that risk legible; a field
  that read `false` while live was off would have hidden it. Coupling the flags
  is a separate change, and `scripts/close_live_window.py` still does not touch
  `PEER_CRITIQUE_ENABLED` (grep: no hits).
- `e2e/tests/invariants/landing-cta-reachable.spec.ts` derives its expected
  sentence from `peer_critique_in_effect`. It previously read the flag — the
  same field the page was built from — so it would have agreed with the
  falsehood rather than catching it. **CI serves flag-off and live-off, where
  both fields are false**, so this difference is never exercised in CI; it is
  pinned in `tests/unit/test_ui_honesty.py` instead.
- `/status`'s response schema is `additionalProperties: true` with no required
  keys, so adding a field does not move `make openapi-check`.

## Rejected alternatives

- **Redefine `peer_critique_enabled` to mean "in effect".** Deletes the only
  labelled signal that the flag is set, makes the posture check's operator line
  a bare `false` (ambiguous between "not configured" and "configured but
  dormant"), re-creates the composite-boolean defect `live_execution` already
  has, and turns the anti-drift guard red. Measured above.
- **Copy follows the flag AND `openrouter_live_execution_enabled` only.**
  Wrong when the key is missing: see decision 3.
- **Copy follows the flag AND `/status.live_execution`.** Adds a cached probe
  term the money path lacks: see decision 2.
- **Couple the two flags so the window script flips both.** The remedy for the
  standing risk, and a different concern: it changes what a live window does,
  which is the product owner's decision, not a copy fix.

## Related

- Issue #458 (this is its flag half; the code half shipped in PR #476).
- ADR-0099 (the copy must describe what runs), ADR-0097 (peer critique's
  observability), ADR-0013 (a paid subsystem may not be enabled invisibly),
  ADR-0093/0095/0096 (the peer shape itself).
