# 65 · Open work — the board

**This is the source of truth for what is open, what it is blocked by, and what
proves each row's state.** Issues on GitHub are the mirror; this file is the
original, because a gate and an offline agent can read it and cannot read `gh`.

Verified at: `e115d92ac0703ca3ce6faa6174a13de0edfae1bd`

The board holds **17** rows, **4** of them unpinned.

`scripts/check_open_work.py --check` reads every row's evidence off disk and
refuses if a claim is false. It runs inside `make validate`, and
`tests/unit/test_open_work_matches_reality.py` holds its bite-proofs.

## How a row proves itself

Each row's **Evidence** cell states what the tree looks like **while the work is
still open**:

- `ABSENT <path> :: <needle>` — the needle is not in that file.
- `PRESENT <path> :: <needle>` — it is.
- `—` — unpinned. The gate checks nothing about this row. The number of these is
  itself pinned above, so a fifth cannot be added quietly.

**The State cell decides which way the gate reads that claim.** `PENDING`
asserts the claim as written; `DONE` asserts its **opposite**. So finishing W1
puts `"stream": True` into `providers.py`, the `ABSENT` claim stops holding, and
the gate goes red until someone changes one word — `PENDING` → `DONE` — after
which the gate demands the inverse and is satisfied. **The evidence cell is
never rewritten. Only the State word moves.**

That coupling is the whole mechanism, and it was **not in this file's first
draft**. Adversarial review demonstrated the hole in one command: with polarity
taken only from the word an author typed, replacing every `| PENDING |` with
`| DONE |` left the gate green — printing "0 PENDING" — with zero bytes changed
under `src/`. The board asserted, in three places, that this could not happen.
It could. It cannot now, and the bite-proof for it is
`test_flipping_only_the_state_word_turns_the_gate_red`.

The other half matters as much: a board that only went red when work was
*abandoned* would stay green through every delivery — which is how
`docs/00-factory-console.md` came to be 64 commits behind its own last touch
while four gates read it, none of them asking whether the work it announced was
the work in flight.

### What this cannot see

- **Work that lands under a different name than the needle.** If streaming ships
  without that exact literal, W1 stays satisfiable while being stale. The needle
  is a named contract, not a proof.
- **Work that lands by a different route under the same name.** W15 is pinned on
  `_bound_sniff_time` being present-and-undefined. Deleting the dangling
  references flips it; *defining* the function would not.
- **The four unpinned rows.** Nothing is checked about them.
- **A row that should exist and does not.** A missing item is invisible.

Review remains the primary defence — measured here, 0 of 16 `src/` defects were
caught by any automated check and 10 of 16 by adversarial review
(`docs/metrics/defect-discovery-audit.md`).

## The board

| ID | Item | State | Evidence | Issue | Depends on |
|----|------|-------|----------|-------|------------|
| W1 | Stream the provider call (was "B2") | PENDING | `ABSENT src/product_app/providers.py :: "stream": True` | — | — |
| W2 | Peer critique: the answer models critique each other, two rounds | PENDING | `PRESENT src/product_app/debate.py :: model_id=settings.debate_model_id,` | #290 | W1 |
| W3 | Re-set the money constants against a measured bound — **STOP** | PENDING | `PRESENT src/product_app/costs.py :: DAILY_CAP_USD = Decimal("0.20")` | — | W2 |
| W4 | Variable panel size N ∈ {2,3,4} | PENDING | `PRESENT src/product_app/model_slots.py :: if len(model_ids) != EXPECTED_SLOT_COUNT:` | — | W10 |
| W5 | Quick-answer N=1 mode | PENDING | `—` | — | W4 |
| W6 | A panel of one reports strong consensus | PENDING | `PRESENT src/product_app/synthesis_consensus.py :: if len(sizes) == 1 or max(sizes.values()) >= _required_cluster(len(stance)):` | #383 | — |
| W7 | Google sign-in and logout | PENDING | `—` | — | — |
| W8 | `min_machines_running` / demo-live posture — **STOP** | PENDING | `PRESENT fly.toml :: min_machines_running = 0` | — | — |
| W9 | Guard the moderator model overlapping a panel slot | PENDING | `ABSENT src/product_app/model_slots.py :: debate_model_id` | — | — |
| W10 | Consensus certifies a mutual cluster it never checked | PENDING | `PRESENT src/product_app/synthesis_consensus.py :: return sum(1 for partners in counts if partners >= 2) >= 3` | #382 | — |
| W11 | Completeness divides by answers recorded, not slots requested | PENDING | `PRESENT src/product_app/evaluation.py :: slot_count = len(initial_answers)` | #380 | — |
| W12 | `last_live_charge_at` reports a pre-#376 row as a live charge | PENDING | `PRESENT src/product_app/feedback_store.py :: WHERE recorder = 'cost' AND event_type = '{COST_ACCEPTED_EVENT}'` | #379 | — |
| W13 | Nothing bounds a call's INPUT — **STOP** | PENDING | `—` | #268 | — |
| W14 | Close the 5xx possibly-billed premise with data | PENDING | `—` | #105 | production logs |
| W15 | `_bound_sniff_time` is referenced and does not exist | PENDING | `PRESENT src/product_app/providers.py :: _bound_sniff_time` | — | — |
| W16 | The catalog fetcher hardcodes the models URL | PENDING | `PRESENT src/product_app/catalog_fetcher.py :: OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"` | — | — |
| W17 | FR-004 names a model we do not ship | PENDING | `PRESENT docs/10-functional-requirements.md :: deepseek/deepseek-chat-v3.1` | — | — |

**STOP** marks a row that cannot be finished without a human decision — a money,
cost or safety guardrail value that only real measurement could justify. Do not
move one of those numbers as a side effect of any other package.

## What each row is

**W1 — stream the provider call.** `providers.py` posts a non-streaming request
and reads the whole body. `_read_body_within_budget` is the template for
deadline discipline, not the implementation. `_extract_message_content`,
`_extract_usage`, `_finish_reason_indicates_truncation` and
`_extract_citations` are reused unchanged once deltas are reassembled — streamed
frames carry `choices[0].delta.content`, not `choices[0].message.content`. Keep
the `product_app.providers.urlopen` seam: it appears on **43 lines across 14
test files** (`grep -rn "product_app.providers.urlopen" tests/`; an inherited
figure of "34 patch sites across 15 test files" matches no reading of the tree
and is not repeated here). Keep `openrouter_call_budget_seconds`: keep-alives
defeat a per-`recv` timeout once streaming lands, so the total budget becomes
the only wall-clock brake on a paid call. **W15 rides inside this package** —
the same file. Whether to reach for an SDK instead is an open design question;
the "two failed hand-rolled attempts" bar that an inherited document attributed
to ADR-0029 is **not in ADR-0029**, which is about the citation grounding score
and never mentions an SDK.

**W2 — peer critique (#290).** Today there is exactly one debate caller and it
always dispatches `settings.debate_model_id`; `debate.py` says so in a comment
next to the usage stamp #290 already added. Blocked on W1 because the #290 spike
measured **7 of 8** probe calls exceeding the 8s timeout on wall clock —
`nvidia/nemotron`'s first rep at 6.385s does not — and 6 of 8 on the per-`recv`
gap. (The approved plan and two session handoffs say "8 of 8"; ADR-0078 and
`docs/analysis/2026-08-26-b3-timeout-probe.md` both correct it against the
probe's own table. The corrected figure is the one used here.) Streaming
collapsed the gap to 0.478 / 0.208 s on a paired sample. Building critique first
ships a feature that pays for discarded tokens and demotes every receipt to
`estimated`.

**W3 — the money constants. STOP.** Blocked on W2 because the approved constant
shape prices a #290 that cannot yet be built. `SOFT_THRESHOLD_USD < DAILY_CAP_USD
< HARD_LIMIT_USD` is mandatory or the confirmation band is dead code. No value
moves without a measurement, and a measurement here costs money.

**W4 — variable panel size.** `Field(ge=1, le=4)` appears at three sites
(`debate.py` twice, `providers.py` once) and they move together. **Blocked on
W10**: #382 ends *"whoever lifts those caps must fix this primitive first"*, and
W4 is the row that lifts them. The CSS is cheaper than feared:
`.model-slot-grid` is `grid-template-columns: 1fr 1fr` with an existing
single-column media query, not a 2×2 `grid-template-areas`, so N=2 and N=3
already reflow (verified 2026-08-28).

**W5 — N=1.** Unreachable while `_validate_model_id_list` rejects any count but
four. Unpinned: no honest needle exists before the shape is chosen.

**W6 — #383.** Reachable today on a degraded four-slot run where three slots
failed. **Not blocked by W4.**

**W7 — Google sign-in.** In `auth.py` and `session_store.py`. The demo plan named
`readiness.py`; that module is the OpenRouter live-execution key probe and holds
no session or account code (verified 2026-08-28) — the plan was wrong. A `users`
or `identities` table goes in a guarded `schema_migrations` block, **never** in
`session_store._SCHEMA`, whose own docstring records that adding a table there
makes the first open of an existing read-only database raise. Unpinned: its
first needle was the bare word `google`, which review satisfied by adding a
*comment* to `auth.py` saying the work was still to do. A needle that a comment
can satisfy is not evidence.

**W8 — the demo-live posture. STOP.** `min_machines_running = 0` with
`auto_stop_machines = "stop"` means a cold start in front of a demo. It trades
money for latency and the human owns that call. It needs an ADR either way.

**W9 — moderator/slot overlap.** `debate_model_id` defaults to
`anthropic/claude-haiku-4.5`, which is also slot 2's default. Nothing forbids
the moderator being a panel member grading its own answer. `model_slots.py`
mentions `debate_model_id` nowhere, which is the absence the needle pins.

**W10 — #382.** `_has_strong_overlap` asks for three answers each with two
partners. Necessary but not sufficient: that admits a shape with no mutually
overlapping trio. Latent at N=4 today, live the moment W4 lifts the bound —
which is why W4 waits on this.

**W11 — #380.** The denominator is answers recorded, so a slot that produced
nothing is absent from both sides and a run that requested four and recorded
three scores 1.0. The product's own copy states the opposite contract.

**W12 — #379.** Unlike the 24h totals it never self-heals.

**W13 — #268. STOP.** Unpinned: the fix's shape is not yet chosen. Marked STOP
because the issue's own subject is a cost guardrail — it identifies
`cost_debate_output_tokens = 400` as a point estimate five times below the
enforced 2000-token cap, and measures **9 of the 495** shipped-catalog four-slot
mixes flipping `CONFIRM` → `BLOCK` on the over-charge alone. `BLOCK` is a hard
refusal, so this is a guardrail move, not a bug fix.

**W14 — #105.** No code. It closes on production evidence, not a diff.

**W15 — a dangling reference.** Two docstrings in `providers.py` point at
`_bound_sniff_time`, which has no definition anywhere. Doc-only.

**W16 — the catalog URL.** `catalog_fetcher.py` hardcodes the models endpoint
instead of honouring `settings.openrouter_api_base_url`, so the two can diverge
and the fetcher cannot be pointed at a local server.

**W17 — FR-004.** `docs/10-functional-requirements.md` and
`docs/12-acceptance-criteria.md` both name `deepseek/deepseek-chat-v3.1` as slot
4's default; `model_slots.py` ships `nvidia/nemotron-3-nano-30b-a3b` and its own
comment says "replaces deepseek". No gate catches it.

## What is deliberately NOT on this board

The archived demo-readiness prompt
(`docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`) ends
*"Stop after F. Items 6–10 need product judgement the human owns."* Item 6 is
W5. Items 7–10 are described only in a plan outside this repository and are not
work a session may select; they are not rows here, and their absence is a
decision rather than an oversight.

## Order and what may run in parallel

**W16 → W1 (+W15) → W2 → W3**, with W6, W9 and W17 as cheap independent
fillers when a lane is blocked. W8 is a filler only in the sense that it is
small; it still needs the human decision above.

Cleanly disjoint: **W1 + W6**. W1 + W4 is nearly parallel — the single overlap
is `Field(ge=1, le=4)` in `providers.py` — but W4 now waits on W10. **W4 and W7
both hold `main.py`, `app.js` and `workspace.html`: sequence them.** W16
collides with W4 only through `tests/unit/test_risk_constant_pins.py`, so
shipping W16 first removes the collision.

Before any parallel dispatch, assign centrally: **ADR numbers, `openapi.yaml`
ownership, the money constants, and the `Field(ge=1, le=4)` bound.** Two
orchestrators here once both created ADR-0072, each green because neither could
see the other. A worktree isolates files; it does not isolate shared namespaces.

## Updating this board

**In the same pull request that changes an item's state.** The gate forces it:
a `PENDING` row whose claim has stopped holding goes red, and so does a `DONE`
row whose claim's opposite does not hold.

To mark a row done, change **only the State word**. Leave the evidence cell
alone — the gate inverts it for you, and rewriting it by hand is how the first
draft of this mechanism was defeated.

When you re-verify the rows, stamp the current commit on the `Verified at:`
line. Do not stamp it without re-reading — the drift limit is deliberately loose
precisely so that re-stamping stays a real act.

Adding or removing a row means editing the count sentence above in the same
change; the gate compares both numbers against the table.
