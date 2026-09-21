# ADR-0116: The copy follows whether peer critique is in effect, not whether the flag is set

## Status

Accepted — 2026-09-21. Code only. **Authorises nothing**: it flips no flag,
opens no live window, and licenses no paid run. Scope and approach come from
the product owner's own work order for this session, item 2: *"#458 flag half:
the landing and `/status` say peer critique is in effect only when the flag AND
live execution are both on. Code only, no flag flipped. I have approved this
approach."* Nothing here records an approval beyond that sentence.

Completes ADR-0099's premise — "the UI describes peer critique because peer
critique is what runs" — which was false in production. Amends ADR-0097's
"ONE predicate, two readers" by naming which predicate each reader uses.

## Context

`PEER_CRITIQUE_ENABLED` has been `"true"` in production since 2026-09-03, and
live execution has been off since **2026-09-12** — the flag was set by the same
commit that OPENED a live window (`6d13643`), which `522f8c9` closed nine days
later. So the flag-true/live-off posture dates from 2026-09-12, not from the
flag being set. In that posture **no run takes the peer path**, and the landing
page said the models critique each other.

The chain, read from the code rather than assumed:

- `debate._build_peer_round` returns `None` unless `peer_critique_enabled`
  **and** `_eligible_critics` is non-empty.
- `_eligible_critics` keeps a slot only if it is `COMPLETED` **and**
  `providers.model_was_invoked(answer)` — that is, its `provider_path` is
  `OPENROUTER_SEARCH`.
- The only site producing a **COMPLETED** answer on the `OPENROUTER_SEARCH`
  path is gated on `providers.ProviderExecutionService._live_execution_enabled`,
  whose terms are `settings.openrouter_live_execution_enabled and
  openrouter_key`. (The cancel, failure and deadline constructors stamp the same
  path on FAILED slots; `_eligible_critics` drops those on its COMPLETED
  conjunct. An earlier revision of this bullet said "the only site producing
  `OPENROUTER_SEARCH`", which is literally false.)

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
`readiness.report.state == "live"`, which additionally requires a key-auth
probe verdict the spending path does not have. That verdict is **cached**
(`readiness._key_auth_state`) and neither `providers` nor `debate` reads it, so
the two can disagree in either direction; in the direction that matters, a
rejection recorded earlier keeps `/status.live_execution` false while
`_live_execution_enabled` still returns True and critic calls dispatch and
bill. `scripts/live_posture_check.py` already documents that drift and refuses
to read that field; reproducing it in the landing copy would be a second
instance of a defect this repo has already named.

**A correction this ADR owes its reviewers:** an earlier revision justified
this decision with "under a refused key … up to eight critic calls are
dispatched and billed". That is FALSE, and review demonstrated it: a key that
is refused right now fails every slot, so `_eligible_critics` is empty and
**zero** critic calls are reached. The stale-verdict case above is the real
one.

**3. The key term is not optional.** With the live flag on and no key,
`query_run_orchestration` fails the whole run ("Live execution is enabled but
no server-side key is configured"). Promising peer critique on a page whose
every run dies is worse than promising it on a page that simulates.

**4. `/status.peer_critique_enabled` keeps meaning the flag, and a second
field is added beside it.** `peer_critique_in_effect` is computed in the same
dict build from the same settings. Both are reported.

**5. The prospective claim is stated as such.** The predicate says a critic
CAN be dispatched, not that one was. Three reachable states still over-promise:

- **Every slot failing**, which includes a key that is refused right now. Not
  knowable before the run. The page's readiness island reports
  `offline_by_bad_key` beside the copy.
- **The global spend ceiling** forcing the run's key empty. This one IS
  knowable at serve time — `_render_workspace_html` computes
  `global_spend_ceiling_reached` in the same function that renders the subhead
  — and is deliberately NOT used: the ceiling is transient, the same page
  already reports it, and the sentence describes the configured shape rather
  than this second's capacity. An earlier revision of this ADR claimed the
  ceiling state "cannot be known when the page is served", which review
  refuted by pointing at the line above the call.
- **A caller-supplied panel** whose slots differ from the default.

`app.js` tells the per-run truth from `critique_shape`; the landing makes the
prospective claim.

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
  sentence from `peer_critique_in_effect` rather than the flag, so it no longer
  demands the peer sentence in production's posture. **It cannot catch a wrong
  predicate**, and its comment now says so: both sides read one server-side
  function, so stubbing that function moves both together — review
  demonstrated exactly that. The spec pins the sentences byte-exact and the
  two-field contract; the predicate is pinned by
  `tests/unit/test_ui_honesty.py` and
  `tests/integration/test_peer_critique_is_observable.py`. **CI serves
  flag-off and live-off, where both fields are false.**
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
