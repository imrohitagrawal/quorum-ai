# Changelog

## Unreleased

### Changed

- **PR-1: copy, lede, and product rename decision.** Brand lede is
  now "One question. Four models. One answer you can verify." (was
  "Stop hopping between multiple AI chatbots..."). Workspace lede is
  now a two-sentence data + cost statement (was the unclear
  "server-configured provider access" copy). The OpenAPI description
  is now a user-facing paragraph pointing at the workspace, health,
  readiness, and status endpoints. **No product rename in this PR**;
  we keep `Quorum-AI`. The decision and full justification are in
  [docs/PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md).
- **PR-1: synthesis tooltips and demo-mode banner copy tightened.**
  All five synthesis tooltips end with the same caveat
  ("Templated by Quorum; no model generates this.") so the AI-honesty
  story is consistent across the surface. The pre-run readiness
  banner and post-run demo-mode banner no longer leak the operator
  env-var names (`OPENROUTER_API_KEY`,
  `OPENROUTER_LIVE_EXECUTION_ENABLED`) into user-facing copy — the
  user sees the outcome, not the config knob.
- **PR-1: copy test contract.** Added
  `tests/integration/test_workspace_html_copy.py` to pin the
  workspace HTML brand/workspace lede strings, the display name, the
  OpenAPI `info.title`/`info.description`, the absence of operator
  env-var names in user-facing HTML, and the per-section synthesis
  tooltip caveat. The next refactor that touches copy will fail this
  suite unless it also updates the brief.

### Fixed

- **Cancel race on completed runs.** DELETE on a run that has
  reached `COMPLETED` no longer overwrites the terminal state with
  `CANCELLED`. The cancel handler now routes through the state
  machine's `transition` helper and returns the existing `COMPLETED`
  result. Idempotent: a DELETE on an already-`CANCELLED` run returns
  the same payload. Added `tests/integration/test_query_run_cancel.py`
  to pin the new contract.

### Added

- **`demo_mode` field on the query-run result endpoint.** New
  boolean field on `QueryRunResultResponse` (and the OpenAPI schema)
  that is `True` when any model answer came from Quorum's local
  simulation helpers rather than a live provider. The UI uses this
  flag to render a prominent demo-mode banner above the model grid
  and to render stub source links as in-app placeholders instead of
  navigable anchors. Not asserted as `False` for live-provider runs
  in this release; the contract is "anytime simulation contributed
  an answer, the flag is `True`".

- **Cost confirmation flow overhaul.** The cost confirmation
  callout now appears after *every* estimate (not only the
  `REQUIRE_CONFIRMATION` band), and the checkbox has been replaced
  with an explicit **Proceed** / **Cancel estimate** button pair.
  Bands above `REQUIRE_CONFIRMATION` also require an explicit
  Proceed, so the flow is uniform across all cost levels.

- **Help tooltips on Model outputs and Final synthesis.** Static
  info icons sit beside the section headings; hovering or focusing
  them shows a shared tooltip explaining what each section
  contains. Escape closes the active tooltip before any other
  Escape handler runs.

### Changed

- **One-time auto-scroll on completion.** The results section now
  auto-scrolls once when a run finishes, but only when the user has
  not scrolled manually in the meantime. User-driven scrolling
  takes precedence over programmatic scrolling thereafter.

- **Sources render as in-app stubs in demo mode.** When
  `demo_mode` is `True`, each cited source becomes a non-clickable
  stub titled "Sample source (demo)" with a `DEMO` tag, instead of
  a clickable anchor. The same DOM shape is preserved so screen
  readers and copy-paste flows are unaffected.

- **Cost estimate quantized to 4 decimal places.** Every
  `CostEstimate.estimated_cost_usd` value that leaves the cost
  service is now rounded to 4 dp using `ROUND_HALF_UP` (single
  source of truth in `CostEstimationService.estimate()`). The
  meta-card, cost-confirmation callout, toast, and notices list
  all read from the same field, so a value like
  `0.01344254000000000000046920801 USD` is now `0.0134 USD`. The
  confirmation-token binding also uses the quantized value, so
  re-issued estimates stay consistent with stored confirmations.

- **Friendly cost-band labels.** The raw enum value
  (`allow` / `require_confirmation` / `block`) no longer leaks
  into the meta-card or notices list. The UI now displays
  "normal band" / "upper band" / "blocked" — the same wording
  the cost confirmation callout already used. Behavior
  comparisons in JS continue to match against the raw enum
  string, so no logic changed.

- **Q logo rotation restored.** The topbar brand mark now spins
  continuously (12s per revolution, linear, infinite) as a
  subtle ambient cue. The motion respects
  `prefers-reduced-motion` via the existing global guard, so
  users who opt out see a static logo.

- **Cancel run pill is hidden until needed.** The legacy
  "Cancel active run" button (always-visible, ghost-styled) is
  replaced by a red-bordered pill that only appears in the
  Run controls panel while a run is in flight. A short hint
  explains that the current stage is marked `skipped` and the
  active-run slot is freed, so the user does not have to guess
  what the button does.

- **Removed the duplicate "Run 4-model workflow" CTA.** The
  hidden `start-run` button has been deleted. Both visible
  CTAs ("Estimate & run" and "Run 4-model workflow") called
  the same `startRun()` function, which only estimated the
  cost — the user clicked "Proceed with this run" in the
  cost callout to actually start the pipeline. The remaining
  primary button is now labeled "Estimate cost" so the
  wording matches its behaviour.

- **Dropped the duplicate "Planning estimate" meta-card.** The
  right-panel meta-card showed the same value as the cost
  callout, the toast, and the notices list — four places
  for one number. The meta-card is gone; the cost callout
  (in the composer, above the Proceed button) is now the
  canonical place, with the toast and notices list as
  supporting surfaces.

- **Friendly "Current time" format.** The value is now
  rendered with `Intl.DateTimeFormat({ dateStyle: "medium",
  timeStyle: "short" })`, e.g. `Jun 18, 2026, 5:08 PM`. The
  previous `timeZoneName: "short"` option threw on some
  runtimes and the `catch` fell back to a raw
  `toISOString()` literal (`2026-06-18T17:08:05.192Z UTC`),
  which has been removed.

- Initial product-factory generated repository.
