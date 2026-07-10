# PR #7 coordinated follow-ups (deferred from the PR #6 backend review)

**Status:** OPEN — to be picked up when PR #6 is merged and PR #7 (the UI that
consumes these fields) work begins.

**Why these are here and not in PR #6:** each item changes a field or value that
UI PR #7 renders (`agreement`, `position_movements`, `actual_cost_usd`,
`actual_breakdown`). Landing them inside PR #6 in isolation would either break
the contract PR #7 is being built against or force PR #7 to be reworked after
the fact. They are deliberately deferred so the backend semantics/contract and
the UI are aligned in **one coordinated change** rather than two uncoordinated
ones.

**Recommended sequencing (see rationale at the bottom):** do these as the
**first, backend-first commits of the PR #7 workstream** — before the UI is
built against the fields — **not** as a separate pass after PR #7 ships.

---

## Item 1 — `actual_cost_usd` returns the estimate on live runs (contract shape)

- **Where:** `src/product_app/query_runs.py` — `_actual_cost()` and the
  `QueryRunResultResponse.actual_cost_usd` / `actual_breakdown` fields.
- **What:** `_actual_cost()` returns `cost_estimate.estimated_cost_usd` /
  `cost_estimate.breakdown` for **every** run, including live/mixed runs, because
  per-call provider-usage capture is not yet plumbed through the pipeline. The
  field is therefore an estimate labelled "actual" on live runs.
- **PR #6 state:** docstrings corrected to state this honestly (commit on the
  review branch). Value/behavior unchanged. Not a merge blocker.
- **Contract impact on #7:** the honest fix is to make `actual_cost_usd` and
  `actual_breakdown` **nullable** and return `null` for live/mixed runs (or add
  an explicit `cost_source: estimated | measured | unavailable` status). Making
  `actual_cost_usd` `Optional` is a **schema change** — PR #7 must render the
  "unavailable/estimated" state, so it must be decided **before** the UI is built.
- **Proposed fix:** introduce `cost_source` enum (recommended over a bare
  nullable, so the UI can distinguish "estimated" from "unknown"); return the
  estimate only for fully simulated runs; wire real token usage when capture
  lands. Add live-only and mixed-path tests.

## Item 2 — panel-level convergence keyword inflates per-model `revised`/agreement

- **Where:** `src/product_app/synthesis_consensus.py` —
  `_debate_signals_convergence()` + `classify_model_alignment()` (`final_aligned`
  derivation) and `summarize_agreement()`.
- **What:** a single convergence keyword ("converged", "reach agreement", …) in
  any debate critique flips consensus strength to `strong`, which sets
  `final_aligned=True` for **every** completed model regardless of its own
  content — so an unrelated minority answer is reported as aligned/`revised` and
  counted in the `agreement` numerator.
- **Honesty framing already present:** the fields are explicitly documented as
  INFERENCE, `_STANCE_COPY` is bounded copy that never asserts an observed
  mid-debate action, and a banned-verb guard test enforces that. So this is an
  acknowledged-heuristic limitation, not a fabricated observed action.
- **Contract impact on #7:** value-only (no shape change) — the UI renders
  whatever counts/flags it receives. But shipping inflated agreement to real
  users is a mild honesty issue, so correct it before the UI surfaces it widely.
- **Proposed fix (algorithm change):** derive per-model `final_aligned` by
  comparing each model's opening against the **actual `FinalSynthesis`** content,
  rather than blanket-aligning everyone when a panel-level keyword fires. Also
  widen the banned-verb guard (see Item 3's note).

## Item 3 — tie / neutral answers counted as majority in `_polar_split`

- **Where:** `src/product_app/synthesis_consensus.py` — `_polar_split()`
  (majority-side derivation) feeding `_opening_majority_flags()` and the
  agreement numerator.
- **What:** on a 1-1 polar tie the smaller side is chosen arbitrarily, and texts
  on **neither** polar side are counted as majority. A genuinely divided panel
  (e.g. Yes / No / "Maybe later" / "Insufficient evidence") can report
  `agreement = 3/4`.
- **Contract impact on #7:** value-only (no shape change), same as Item 2.
- **Proposed fix:** represent cluster membership as tri-state (majority /
  minority / unclustered) or a cluster id; a tie has **no** majority, and
  neutral/unclassified answers must not default to aligned. Require a unique
  consensus threshold before producing an agreement numerator. Pin tie/neutral
  semantics with a dedicated test (the current suite only pins a clean 2-vs-2).

## Test-quality follow-ups (cheap, can ride along with the above)

- Add a **live/mixed** actual-cost test (current suite only covers a demo run).
- Pin **tie/neutral** agreement semantics (current suite only pins clean 2-vs-2).
- Widen the **banned-verb guard** (`test_agreement_positions.py`) beyond the 5
  literal phrases — it would miss equivalents like "shifted position", "adopted
  the consensus", "revised its view".

## Pre-existing (NOT introduced by PR #6, track separately)

- `openapi.yaml` `DebateOutput` / `DebateRoundStatus` are stale vs the live
  `app.openapi()` (`contributing_models`/`latency_ms`/`provider_notice` and
  `skipped_timeout` do not exist on the model — the model is
  `{round_number, focus_areas, critique_text, status}` with
  `status ∈ {completed, skipped}`). This drift exists on `main`; PR #6 did not
  touch those lines. Fix via a real regen + a CI assertion that the checked-in
  spec equals `app.openapi()` (see `docs/109-contract-and-schema-governance.md`).

---

## Sequencing recommendation: WITH PR #7 (backend-first), not after

Do these at the **start of the PR #7 workstream, backend-first**, then build the
UI against the corrected fields. Reasoning:

1. **Item 1 forces the order.** It is a schema-shape change (nullable / new
   `cost_source`). If PR #7 is built assuming a non-null `actual_cost_usd` and we
   make it nullable afterwards, PR #7 breaks and must be reworked. A shape change
   the consumer depends on must land **before or with** the consumer, never after.
2. **Items 2 & 3 are value-only**, so they *could* technically fast-follow — but
   correcting them after the UI ships means real users see inflated agreement in
   the interim, and the "correct the number later" change still needs UI QA. Bundling
   them with the same backend-first step is cheaper than a second coordinated pass.
3. **"After PR #7" is the weakest option** because it guarantees a second
   round-trip through the UI for at least Item 1, and risks shipping the honesty
   nits to production. Only choose it if PR #7 is explicitly a throwaway/spike.

Net: treat Item 1 as a **backend prerequisite** committed at the top of the PR #7
branch; fold Items 2, 3 and the test follow-ups into that same prerequisite so
the UI is built once, against the final contract.
