# ADR-0120: A panel is two to four models, and a panel of two is described honestly

## Status

Accepted — 2026-09-22. Decided by the product owner in session (CHG-010).
Delivered in three pull requests; this record ships with the first, which
changes no user-visible behaviour: the validator still accepts only four
until the workspace control exists. Refs board row W4.

ADR-0119 is reserved by draft PR #491 (#268); this record takes 0120 so the
two branches cannot collide on a number (ADR-0119 exists on branch
`proposal/268-web-search-context-tokens`).

## Context

`EXPECTED_SLOT_COUNT = 4` was the only panel size the product accepted. The
owner had offered users "two, three, or four" models (owner's message,
2026-08-26) and authorised the build on 2026-08-31, but three product
questions were open: how a user chooses the size, what range, and what a
two-model panel may claim. Every previous session re-asked them
(`docs/analysis/2026-09-22-decision-register.md`).

Two facts about the existing code shaped the design:

- **The green band already requires evidence, at any N.** `app.js` shows the
  green band only when `aligned === total`, `panel_agreement === "agreed"`,
  no false consensus was preserved, no step failed and the run completed. `panel_agreement` is `"agreed"` at
  N=2 exactly when a moderator stance exists and both labels match, and
  `"undetermined"` when there is no stance — the same rule as at N=4. So at
  N=2 the band is green under the same evidence, and only its wording
  changes.
- **Trust and agreement are already separate.** The trust composite's
  weights (`LAYER_A_WEIGHTS`) deliberately exclude `agreement_ratio`, so
  panel size touched the served trust nowhere. The cap below is therefore the
  only place it does.

## Decision

1. **Range 2..4, four by default.** `MIN_SLOT_COUNT = 2`, `MAX_SLOT_COUNT =
   4`, `EXPECTED_SLOT_COUNT = 4` (the default, name kept for its readers).
   Every `Field(ge=1, le=4)` slot bound reads `le=MAX_SLOT_COUNT`.
2. **The user chooses the size with a visible control**: a remove button per
   slot (disabled at two) and an add button (hidden at four). Ships in the
   second pull request, with the `_validate_model_id_list` widening.
3. **At N=2 with both agreeing:** a green band reading "Both models agree
   (2 of 2)", never "The panel's verdict". **Trust is capped at
   `moderate`** (`TRUST_CAP_BELOW_PANEL_SIZE = 3`, applied inside the
   `support_verified` branch of `build_trust_score`; the score is served as
   computed; `TrustDiagnostics.panel_size_cap` says when it fired).
4. **The estimate prices N upstream answers, not four.**
   `costs.py` priced the debate and synthesis prompts as if the moderator
   read four answers whatever the panel; it now uses `len(model_slots)`, and
   the fail-safe bound shares the arithmetic.
5. **Served prose is NOT changed in this pull request.** A first version
   wrote "Four models were asked…" from `len(initial_answers)`; review showed
   that on a run where one slot never records (a worker timeout with budget
   left, `query_run_orchestration.py`), that reads "Three models were asked"
   when four were. The count the prose needs is the REQUESTED panel size,
   which `synthesis.py` and `debate.py` do not receive today. The second
   pull request threads it through and rewrites the prose, the section
   prompts and the round-one system prompt together.
6. **The API edge is not bounded to the range.** A `min_length=max_length=4`
   bound on `model_slots` was tried and turned the typed
   `INVALID_MODEL_SLOT` envelope into Pydantic's generic `VALIDATION_ERROR`
   (measured: `test_create_query_run_with_wrong_slot_count_preserves_typed_envelope`
   RED). The count stays a domain check.

## Measured

Through the shipped estimator, no live call, live catalog prices read on
2026-09-22 (a reviewer re-ran it the same day and every figure reproduced
within 0.0001): `cost_estimation_service.estimate` on the default panel and
on every 2- and 3-model subset of it, under the two postures below.

| posture | N=4 default | N=3 (cheapest .. dearest trio) | N=2 (cheapest .. dearest pair) |
|---|---|---|---|
| peer flag on, judge `openai/gpt-4.1-mini` (production's estimator posture) | 0.1282 | 0.0946 .. 0.1168 (26.2% .. 8.9% below) | 0.0829 .. 0.1027 (**35.3% .. 19.9% below**) |
| peer flag off, judge off | 0.1053 | 0.0901 .. 0.0957 (14.4% .. 9.1%) | 0.0783 .. 0.0857 (**25.6% .. 18.6%**) |

So N=2 is one fifth to one third cheaper, never half: the judge is fixed,
synthesis shrinks little, and the saving depends on which two models remain.
That price copy must not sell N=2 on cost is the session's recommendation,
not an owner instruction; the owner's decision covers the band and the trust
cap.

Trust cap, unit-measured: composite 90 → `high` at N=3, 4 and unknown;
`moderate` at N=2 with `panel_size_cap` true; `unverified` at any N without
a real judge.

Consensus at N=2, read from `synthesis_consensus.py` (not changed):
`compute_consensus_strength` returns `"strong"` when both stance labels
match; without a stance two agreeing models fall through
`_has_strong_overlap` (`n < 3`, ADR-0075) to `"weak"`, and the ring can read
"0 of 2". That is not green today and stays not green: with no moderator
reading there is no evidence of agreement.

## Rejected alternatives

- **Backend only, no control.** Ships a path nothing exercises and pins the
  bounds the real design had to choose. Rejected 2026-09-21 and again here.
- **Range 3..4.** Every consensus primitive was built for three or more, so
  it is the smaller package; but it contradicts what users were told.
- **Never a green band at N=2.** Proposed by the session, overruled by the
  owner: the user chose two, and two agreeing is that panel's unanimity. The
  weaker evidence is carried by the trust cap, not by withholding the band.
- **Bounding `model_slots` at the API edge.** See decision 6.
- **A URL parameter to choose N.** Invisible to the user; not "flexibility
  provided to the user".

## Consequences

- After this record's pull request: nothing user-visible changes; the
  estimate for four is unchanged to the cent (the `Decimal(4)` term equals
  `len(model_slots)` at four; a reviewer diffed both postures, main against
  branch, and only the confirmation token differed); served prose is
  untouched; `openapi.yaml` gains `panel_size_cap` (optional, additive).
- After the second: a two- or three-model run is reachable, priced for its
  size, and described with its size.
- Board row W4 stays `PENDING` until the second pull request: its needle is
  the widened validator message "Between 2 and 4 model slots are required.",
  which only that change adds.
