# 65 · Open work — the board

**This is the source of truth for what is open, what it is blocked by, and what
proves each row's state.** Issues on GitHub are the mirror; this file is the
original, because a gate and an offline agent can read it and cannot read `gh`.

Verified at: `e115d92ac0703ca3ce6faa6174a13de0edfae1bd`

The board holds **17** rows, **3** of them unpinned.

`scripts/check_open_work.py --check` reads every row's evidence off disk and
refuses if a claim is false. It runs inside `make validate`, and
`tests/unit/test_open_work_matches_reality.py` holds its bite-proofs.

## How a row proves itself

Each row's **Evidence** cell is a claim about *today's* tree:

- `ABSENT <path> :: <needle>` — the needle is not in that file.
- `PRESENT <path> :: <needle>` — it is.
- `—` — unpinned. The gate cannot check this row at all. The number of these is
  itself pinned above, so a fourth cannot be added quietly.

**A `PENDING` row's needle is chosen so that it flips when the work lands.**
That is the whole mechanism: finishing W1 puts `"stream": True` into
`providers.py`, the `ABSENT` claim becomes false, and the gate goes red until
the row is flipped to `DONE` with its evidence inverted. A board that only went
red when work was *abandoned* would stay green through every delivery — which
is exactly how `docs/00-factory-console.md` came to be 64 commits behind its own
last touch while four gates read it — none of which asked whether the work it
announced was the work in flight.

**Marking a row `DONE` is not free either.** A `DONE` row must state the
inverted claim, and that claim is read off disk too, so a row cannot be marked
done over nothing.

**What this cannot see:** work that lands under a different name than the
needle. If streaming ships without that exact literal, W1 stays green while
being stale. The needle is a named contract, not a proof. Review remains the
primary defence — measured here, 0 of 16 `src/` defects were caught by any
automated check and 10 of 16 by adversarial review
(`docs/metrics/defect-discovery-audit.md`).

## The board

| ID | Item | State | Evidence | Issue | Depends on |
|----|------|-------|----------|-------|------------|
| W1 | Stream the provider call (was "B2") | PENDING | `ABSENT src/product_app/providers.py :: "stream": True` | — | — |
| W2 | Peer critique: the answer models critique each other, two rounds | PENDING | `PRESENT src/product_app/debate.py :: model_id=settings.debate_model_id,` | #290 | W1 |
| W3 | Re-set the money constants against a measured bound | PENDING | `PRESENT src/product_app/costs.py :: DAILY_CAP_USD = Decimal("0.20")` | — | W2 |
| W4 | Variable panel size N ∈ {2,3,4} | PENDING | `PRESENT src/product_app/model_slots.py :: if len(model_ids) != EXPECTED_SLOT_COUNT:` | — | — |
| W5 | Quick-answer N=1 mode | PENDING | `—` | — | W4 |
| W6 | A panel of one reports strong consensus | PENDING | `PRESENT src/product_app/synthesis_consensus.py :: if len(sizes) == 1 or max(sizes.values()) >= _required_cluster(len(stance)):` | #383 | — |
| W7 | Google sign-in and logout | PENDING | `ABSENT src/product_app/auth.py :: google` | — | — |
| W8 | `min_machines_running` / demo-live posture | PENDING | `PRESENT fly.toml :: min_machines_running = 0` | — | — |
| W9 | Guard the moderator model overlapping a panel slot | PENDING | `ABSENT src/product_app/model_slots.py :: debate_model_id` | — | — |
| W10 | Consensus certifies a mutual cluster it never checked | PENDING | `PRESENT src/product_app/synthesis_consensus.py :: return sum(1 for partners in counts if partners >= 2) >= 3` | #382 | — |
| W11 | Completeness divides by answers recorded, not slots requested | PENDING | `PRESENT src/product_app/evaluation.py :: slot_count = len(initial_answers)` | #380 | — |
| W12 | `last_live_charge_at` reports a pre-#376 row as a live charge | PENDING | `PRESENT src/product_app/feedback_store.py :: WHERE recorder = 'cost' AND event_type = '{COST_ACCEPTED_EVENT}'` | #379 | — |
| W13 | Nothing bounds a call's INPUT | PENDING | `—` | #268 | — |
| W14 | Close the 5xx possibly-billed premise with data | PENDING | `—` | #105 | production logs |
| W15 | `_bound_sniff_time` is referenced and does not exist | PENDING | `PRESENT src/product_app/providers.py :: _bound_sniff_time` | — | — |
| W16 | The catalog fetcher hardcodes the models URL | PENDING | `PRESENT src/product_app/catalog_fetcher.py :: OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"` | — | — |
| W17 | FR-004 names a model we do not ship | PENDING | `PRESENT docs/10-functional-requirements.md :: deepseek/deepseek-chat-v3.1` | — | — |

## What each row is

**W1 — stream the provider call.** `providers.py` posts a non-streaming request
and reads the whole body. `_read_body_within_budget` is the template for
deadline discipline, not the implementation. `_extract_message_content`,
`_extract_usage`, `_finish_reason_indicates_truncation` and
`_extract_citations` are reused unchanged once deltas are reassembled — streamed
frames carry `choices[0].delta.content`, not `choices[0].message.content`. Keep
the `product_app.providers.urlopen` seam (34 patch sites across 15 test files
depend on it) and keep `openrouter_call_budget_seconds`: keep-alives defeat a
per-`recv` timeout once streaming lands, so the total budget becomes the only
wall-clock brake on a paid call. **W15 rides inside this package** — the same
file. ADR-0029's bar for reaching for an SDK instead is two measured failed
hand-rolled attempts; there are currently **zero**.

**W2 — peer critique (#290).** Today there is exactly one debate caller and it
always dispatches `settings.debate_model_id`; `debate.py` says so in a comment
next to the usage stamp #290 already added. Blocked on W1 because the #290 spike
measured **8 of 8** probe calls exceeding the 8s timeout on wall clock and 6 of 8
on the per-`recv` gap; streaming collapsed the gap to 0.478 / 0.208 s on a paired
sample. Building critique first ships a feature that pays for discarded tokens
and demotes every receipt to `estimated`.

**W3 — the money constants.** Blocked on W2 because the approved constant shape
prices a #290 that cannot yet be built. `SOFT_THRESHOLD_USD < DAILY_CAP_USD <
HARD_LIMIT_USD` is mandatory or the confirmation band is dead code.
**This row is a STOP condition**: no value moves without a measurement, and a
measurement here costs money.

**W4 — variable panel size.** `Field(ge=1, le=4)` appears at three sites
(`debate.py` twice, `providers.py` once) and they move together. The CSS is
cheaper than feared: `.model-slot-grid` is `grid-template-columns: 1fr 1fr`
with an existing single-column media query, not a 2×2 `grid-template-areas`, so
N=2 and N=3 already reflow (verified 2026-08-28).

**W5 — N=1.** Unreachable while `_validate_model_id_list` rejects any count but
four. Unpinned: no honest needle exists before the shape is chosen.

**W6 — #383.** Reachable today on a degraded four-slot run where three slots
failed. **Not blocked by W4.**

**W7 — Google sign-in.** In `auth.py` and `session_store.py`. The demo plan named
`readiness.py`; that module is the OpenRouter live-execution key probe and holds
no session or account code (verified 2026-08-28) — the plan was wrong. A `users`
or `identities` table goes in a guarded `schema_migrations` block, **never** in
`session_store._SCHEMA`, whose own docstring records that adding a table there
makes the first open of an existing read-only database raise.

**W8 — the demo-live posture.** `min_machines_running = 0` with
`auto_stop_machines = "stop"` means a cold start in front of a demo.
**This row is a STOP condition**: it trades money for latency and the human owns
that call. It needs an ADR either way.

**W9 — moderator/slot overlap.** `debate_model_id` defaults to
`anthropic/claude-haiku-4.5`, which is also slot 2's default. Nothing forbids
the moderator being a panel member grading its own answer. `model_slots.py`
mentions `debate_model_id` nowhere, which is the absence the needle pins.

**W10 — #382.** `_has_strong_overlap` asks for three answers each with two
partners. Necessary but not sufficient: that admits a shape with no mutually
overlapping trio. Latent at N=4 today, live the moment W4 lifts the bound.

**W11 — #380.** The denominator is answers recorded, so a slot that produced
nothing is absent from both sides and a run that requested four and recorded
three scores 1.0. The product's own copy states the opposite contract.

**W12 — #379.** Unlike the 24h totals it never self-heals.

**W13 — #268.** Unpinned: the fix's shape is not yet chosen.

**W14 — #105.** No code. It closes on production evidence, not a diff.

**W15 — a dangling reference.** Two docstrings in `providers.py` point at
`:func:`_bound_sniff_time``, which has no definition anywhere. Doc-only.

**W16 — the catalog URL.** `catalog_fetcher.py` hardcodes the models endpoint
instead of honouring `settings.openrouter_api_base_url`, so the two can diverge
and the fetcher cannot be pointed at a local server.

**W17 — FR-004.** `docs/10-functional-requirements.md` and
`docs/12-acceptance-criteria.md` both name `deepseek/deepseek-chat-v3.1` as slot
4's default; `model_slots.py` ships `nvidia/nemotron-3-nano-30b-a3b` and its own
comment says "replaces deepseek". No gate catches it.

## Order and what may run in parallel

**W16 → W1 (+W15) → W2 → W3**, with W6, W8, W9 and W17 as cheap independent
fillers when a lane is blocked.

Cleanly disjoint: **W1 + W6 + W8**. W1 + W4 is nearly parallel — the single
overlap is `Field(ge=1, le=4)` in `providers.py`. **W4 and W7 both hold
`main.py`, `app.js` and `workspace.html`: sequence them.** W16 collides with W4
only through `tests/unit/test_risk_constant_pins.py`, so shipping W16 first
removes the collision.

Before any parallel dispatch, assign centrally: **ADR numbers, `openapi.yaml`
ownership, the money constants, and the `Field(ge=1, le=4)` bound.** Two
orchestrators here once both created ADR-0072, each green because neither could
see the other. A worktree isolates files; it does not isolate shared namespaces.

## Updating this board

**In the same pull request that changes an item's state.** The gate forces it:
a `PENDING` row whose needle has appeared goes red, and so does a `DONE` row
whose needle has not.

When you re-verify the rows, stamp the current commit on the `Verified at:`
line. Do not stamp it without re-reading — the drift limit is deliberately loose
precisely so that re-stamping stays a real act.

Adding or removing a row means editing the count sentence above in the same
change; the gate compares both numbers against the table.
