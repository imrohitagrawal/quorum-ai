# ADR-0110: The measured receipt can carry a flat per-request fee, keyed on the wire

## Status

Accepted — 2026-09-12.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture or a paid run.

**Ships the mechanism, not the charge.** `cost_web_search_request_fee_usd`
remains `0.0`, so this ADR changes no served figure. Activating it is a
product-owner decision and is deliberately NOT taken here — see
"The activation decision this ADR does not take".

**Supersedes the RATIONALE of CHG-005 / AC-037, not their decision.** The
exclusion still stands; the reason recorded for it in 2026-07-17 is refuted
below. See CHG-006 in `docs/19-change-control-log.md`.

## Context

Issue #105's measurement session reconciled two live runs against the owner's
OpenRouter activity export (`docs/analysis/2026-09-10-openrouter-activity.csv`,
27 generation rows). Recomputed from that CSV for this ADR:

| run | OpenRouter `cost_total` | `cost_web_search` | total − fee | Quorum served, `cost_source="measured"` |
|---|---|---|---|---|
| 5a9c2d63 (18 generations) | $0.121763 | $0.028 | $0.093763 | $0.0938 |
| fcca9510 (9 generations) | $0.067586 | $0.028 | $0.039586 | $0.0396 |

`cost_total − cost_web_search` reproduces Quorum's measured figure to four
decimal places on **both** runs independently. That is the defect stated as an
identity: the "measured" receipt is the token cost with the flat fee omitted.

The 18/9 split is not a timestamp guess — the telemetry rows pin it. Run
5a9c2d63 has 4 initial + 4 debate round 1 + 4 debate round 2 + 5 synthesis + 1
judge = 18; run fcca9510 has 4 initial + 4 debate round 1 + 1 judge = 9 (its
round 2 ran entirely on fallbacks, so it made no LLM calls).

Three further facts, each measured rather than assumed:

- **The fee is $0.007 flat, on exactly the four initial-answer calls per run.**
  Of the 27 ledger rows, **8** carry a non-empty `cost_web_search`, every one of
  them exactly `0.007`, falling in two batches of four — one per answer model.
  The other **19** generations — the twelve debate critiques across the three
  rounds the two runs ran between them, the five synthesis sections, and the two
  judge calls — carry **none**. This matches the code: debate, synthesis and
  judge all go through `call_with_prompt`, which never appends `:online`,
  because a second-pass analysis does not want a fresh web search.
- **`measured_call_cost_usd` is purely linear in tokens** (`costs.py`), two
  terms and no flat component, so it structurally cannot carry a per-request
  fee. There was no flat term anywhere on the measured path.
- **The pre-2026-09-10 rationale for excluding the fee is refuted.** AC-037 and
  CHG-005 accepted the exclusion on the ground that "the pre-run estimate
  already runs at or above the measured **token** cost (measured live run
  2026-07-17: estimate $0.0199 ≥ actual $0.0149)". On 2026-09-10 run 5a9c2d63
  was approved at an estimate of **$0.076** and its measured token cost alone
  was **$0.0938** (`docs/analysis/2026-09-10-live-run-readout-evidence.md:4`
  records `actual $0.094 (approved $0.076)`). The comparison is made on AC-037's
  own terms — token cost against token cost, fee excluded from both — and the
  estimate ran BELOW. Including the fee the true charge was $0.121763. Either
  way the premise that made the exclusion fail-safe no longer holds.

### The hard part: "did this call search?" was not knowable

The fee is owed per `:online` request, so the measured path needs the wire
truth. Every candidate signal already on the answer record was checked and
rejected:

| candidate | why it cannot decide the fee |
|---|---|
| `answer.provider_path` | `OPENROUTER_SEARCH` is stamped for **three** different wire realities: `:online` succeeded, `:online` was rejected and a bare retry succeeded, and search was **disabled** so `:online` was never attempted. `providers.py` says so in-code, and `test_a_search_disabled_slot_never_posts_online_and_is_not_stamped_searched` proves the third case executably. |
| `answer.provider_attempt_order` | a single-element `[OPENROUTER_SEARCH]`, identical on every path that can reach the fee decision. |
| `TokenUsage` | three token counts plus an optional billed `model_id`; no provider-path or searching flag. |
| `ModelSlot.search` | the **intent**. On a rejected `:online` the BARE retry is what served, so an intent-keyed fee charges a slot for a search request that was refused. |

The truth lives in the POST frame, where the model id either ends in `:online`
or does not. (`_call_openrouter_with_optional_search` also knows, since it
chooses between the two ids; the POST frame is the narrower of the two and is
the one used.) The token-shape telemetry already reads precisely that predicate
— `"search_enabled": model_id.endswith(":online")`, with the comment "The suffix
IS the search flag, as it goes on the wire" — but it writes to a JSONL file that
nothing in the APPLICATION reads back (two offline report scripts do:
`scripts/window_measurement_report.py` and
`scripts/telemetry_classification_report.py`), so it was unavailable to the cost
layer at pricing time.

## Decision

**Thread the wire outcome to the cost layer, and add the flat term to the slot
that incurred it.**

1. `LiveProviderResult.searched` is set from `model_id.endswith(":online")` in
   **`_post_messages`** (`providers.py:1851`) — the transport frame that
   `_post_openrouter` delegates to, and the one holding the id actually POSTed.
   Same predicate as the existing telemetry field, for the same reason.
2. `InitialModelAnswer.searched` carries it to the atomic `BillingSnapshot` the
   cost computation already reads, alongside `token_usage` and `shortened`.
3. `_actual_cost` adds `settings.cost_web_search_request_fee_usd` to a slot's
   measured cost when, and only when, that slot's `searched` is true.

**Outcome, never intent.** This is the whole point of (1): a slot whose
`:online` attempt was rejected reports `searched=False` and is charged no fee,
because the bare retry is what served it. Simulated, fallback, failed,
cancelled, deadline-exceeded and search-disabled slots keep the `False` default.

**The suffix, not a colon.** `_MODEL_ID_RE` accepts a colon inside a model id
and the catalog serves `:free` and `:preview` variants, so the predicate must
test the `:online` suffix specifically. A looser colon test would charge a
`:free` slot with search off a fee it never incurred.

**Folded into the slot's own line, not a separate term.** The fee is part of
what that call cost, so it lands in that slot's `by_model` row and in the
`initial_answers` stage total. `build_measured_breakdown` needs no new
parameter and the existing partition reconciliation is untouched.

**The fee cannot be double-counted across paths.** The estimate applies it per
searching *slot* (`costs.py`, keyed on `slot.search`); the measured path applies
it per searching *call* (keyed on `answer.searched`). A run reports one or the
other — `cost_source` is `"estimated"` XOR `"measured"` — and
`reconcile_charge_for_run` REPLACES the booked figure rather than adding to it,
so the two never both land on one number.

## Rejected alternatives

- **Key the measured fee on `ModelSlot.search`.** No plumbing needed, and it is
  what the estimate does. Rejected: it is the intent, so it charges every slot
  whose `:online` attempt was rejected and was served by the bare retry —
  overstatement under a label the UI presents as measured billing, which is the
  dishonesty #99 exists to prevent. Mutation 03 in
  `scripts/proofs/search_fee_measured_mutations.py` **is** this alternative,
  written out, and it is killed.
- **Give `measured_call_cost_usd` a fee parameter.** Rejected: it is the pricing
  primitive and is deliberately linear in tokens; the flat term belongs where
  the wire outcome is known, not inside a token-pricing function used by four
  other call sites that can never carry a fee.
- **Read the fee back from the provider response.** Rejected as **UNVERIFIED
  rather than as undesirable.** The completion body is not known to carry a
  per-call fee breakdown, and OpenRouter's `GET /api/v1/generation` endpoint
  appears nowhere in this repo, so nobody here has measured what it returns.
  AGENTS.md rule 8c is explicit that gating on an upstream's behaviour is worth
  only as much as your measurement of it, and there is none. The check that
  would settle it is one free authenticated `curl` to
  `https://openrouter.ai/api/v1/generation?id=<gen-id>`; until someone runs it,
  this alternative is unassessed, not refuted.
- **Add a `ProviderPath.OPENROUTER_SEARCH_ONLINE` enum member.** Rejected: the
  enum is consumed by the UI, source attribution and the honesty gate; widening
  it to carry a billing fact would couple four surfaces to one cost concern.
- **Restate the historical receipts.** Rejected for now: past runs carry
  under-stated measured figures, and correcting them is a separate decision
  about stored evidence (failure mode 8 of the plan filed at issue #105 comment
  5638578554). Logged as debt in `docs/63-technical-debt-register.md`, not
  resolved.

## Order, and why the ceiling is never under-protected

The plan at issue #105 comment 5638578554 requires an order that never leaves
the daily ceiling under-protected, because over-charging a ceiling is safe and
under-charging it is not. That order is **B (this ADR) → A (activation) → C**:

- B alone moves nothing — the fee is `0.0` on both paths.
- A raises the estimate, which is what the daily cap and the cumulative rail
  book, so the ceiling becomes *more* protective, never less.
- C would LOWER what a failed run books, so it must come last and behind its own
  evidence. It is separately blocked: ADR-0031 sets a documented bar of n≥30 samples
  per status code (prose; `scripts/telemetry_classification_report.py` encodes
  the thresholds but no gate enforces the decision), and the HTTP status is discarded before the cost
  layer sees it, so the in-app signal cannot yet distinguish "rejected before
  generation" from "dispatched, possibly billed".

## The activation decision this ADR does not take

`cost_web_search_request_fee_usd` stays `0.0`, so **no served figure moves in
this change**. Activating it at the measured $0.007 is a product-owner decision,
because CHG-005 recorded the exclusion as one and because the consequences are
user-facing. Measured for this ADR so the decision can be taken on numbers.

**Every figure below is re-derivable, and the posture is part of the figure.**
Run `uv run python scripts/proofs/search_fee_band_sweep.py [--fallback-prices]`;
it prints its posture and price source before any number.

**Production runs peer critique AND the judge ON.** Measured from the live
deployment, not inferred from `fly.toml`: `GET /status` reports
`"peer_critique_enabled": true, "judge_enabled": true`. `fly.toml` sets only the
first; the judge is configured by secrets, and `judge_configured()` — a key AND
a pinned model id — is the single predicate `/status.judge_enabled` reports.
**Both postures move every number below**, which is why an earlier draft of this
ADR published a "production" figure that was measured with the judge off.

Under that real posture, with the offline-reproducible static price table and a
59-character query:

| measure | at fee $0.0 | at fee $0.007 |
|---|---|---|
| point estimate, shipped default mix | $0.0675 | $0.0955 |
| per-account runs admitted (`DAILY_CAP_USD` $0.40) | **5** | **4** |
| shipped-catalog mixes changing guardrail band (of 1820) | — | **62** |
| of those, reaching `block` | — | **2** |
| of those, `allow` → `require_confirmation` | — | **60** |
| `search=False` control lane | — | **0 of 1820** |

So activation costs one run a day off the per-account envelope, moves 60 mixes
into "needs confirmation", and makes **2** of 1820 mixes unrunnable. The control
lane changing nothing is the positive partner proving the fee reaches only
searching slots — it was 0 in every posture measured.

**Other postures give materially different numbers**, and that is the point of
the script rather than a table: with peer critique off the same sweep reports 299
mixes changing band and 64 reaching `block`, and with live-catalog prices instead
of the static table it reports 61 and 43. None of those is production. Do not
quote a band figure without the posture it was measured under.

**Activation is NOT a one-value change.** Eight tests pin the pre-fee arithmetic
and must be re-measured in the activating PR. Measured over exactly these five
files — `test_cost_breakdown.py`, `test_peer_bound_is_a_true_ceiling.py`,
`test_bound_covers_the_judge.py`, `test_estimate_prices_the_judge.py`,
`tests/integration/test_query_run_cost_guardrails.py` — with
`COST_WEB_SEARCH_REQUEST_FEE_USD=0.007` and nothing else changed: **57 passed**
at `0.0`, then `8 failed, 49 passed`:

```
tests/unit/test_cost_breakdown.py::test_exact_partition_pins_the_split
tests/unit/test_peer_bound_is_a_true_ceiling.py::test_the_shipped_posture_is_byte_identical
tests/unit/test_peer_bound_is_a_true_ceiling.py::test_round_twos_prior_critique_is_priced_for_every_critic
tests/unit/test_bound_covers_the_judge.py::test_judge_off_leaves_the_bound_byte_identical
tests/unit/test_bound_covers_the_judge.py::test_the_judge_term_is_pinned_to_exact_literals
tests/unit/test_estimate_prices_the_judge.py::test_the_displayed_estimate_rises_by_the_judge_term
tests/unit/test_estimate_prices_the_judge.py::test_judge_off_leaves_the_displayed_breakdown_byte_identical
tests/integration/test_query_run_cost_guardrails.py::test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for
8 failed, 49 passed
```

None of the eight is wrong; each is doing its job. The guardrail test names the
figure itself: `the pinned static catalog's default-mix price moved to 0.0827;
re-measure the envelope before updating this constant`.

**Other activation consequences:**

- **The fee becomes user-visible**, contradicting AC-037's "never surfaced to
  the user or on the UI": `app.js` renders `<$0.001` below the display quantum,
  and at a $0.007 fee no searching slot can round below $0.001, so the cheapest
  slot's card changes from `<$0.001` to about `$0.007`.
- **A completed run's served receipt would diverge from what was metered.** The
  measured figure is recomputed from live settings on every
  `GET /v1/query-runs/{id}/result`, while the ledger keeps the figure computed at
  completion. Activating mid-day makes already-finished searching runs serve
  $0.028 more than was charged against their cap. This is a pre-existing class
  (catalog prices already float the same way), widened by one term.
- **Confirmation tokens do not survive the deploy at all**, so the estimate
  change is not what invalidates them: the token table is an in-process dict
  (`costs.py`) with a 5-minute TTL, and a deploy restarts the process.
- **AC-037, CHG-005 and `docs/54-ac-to-test-map.md` need revising.** Their
  refuted rationale is annotated in this PR and CHG-006 records the
  supersession; the *decision* is the owner's.
- **No test asserts the default is `0.0` directly.** The change is caught only
  indirectly, by
  `tests/test_doc_gate_consistency.py::test_env_example_values_match_the_real_defaults`,
  which compares `.env.example` values against the live defaults. Nothing
  enforces AC-037's wording: `grep -rn AC-037 tests/ scripts/ e2e/` finds
  nothing.
- **There is no `fly.toml` entry to change.** `COST_WEB_SEARCH_REQUEST_FEE_USD`
  appears in no deploy config, workflow or script — only in `.env.example`. So
  activation means editing the `config.py` default itself, which changes
  production, local and CI together.

## Consequences

- A measured receipt on a searching run is higher by the fee once it is
  activated, and correct rather than understated. At `0.0` it is unchanged.
- `InitialModelAnswer.searched` crosses the API boundary as an additive optional
  boolean defaulting to `false` (`openapi.yaml`), so the fee is auditable from
  the response rather than only inferable from the total. No existing consumer
  reads it and no schema forbids extra fields.
- **$0.007 is a provider price, not our constant** (failure mode 6 of the plan
  at issue #105 comment 5638578554). It is measured on 8 generations from a
  single export and OpenRouter can change it without notice. It is
  configuration, so it can be corrected without a code change; nothing detects
  it going stale. Logged in `docs/63-technical-debt-register.md`.
- **A bad fee value is NOT uniformly fail-safe, and an earlier draft of this ADR
  said it was.** The setting has no validation. Measured on `_actual_cost` with
  four searching slots and the shipped default mix: `-0.0001` keeps the run
  **`measured`** and serves $0.0191 against a correct $0.0195 — an
  UNDER-report on a receipt labelled measured, which then flows to the ledger
  through `record_actual` → `reconcile_charge_for_run`. Only a magnitude large
  enough to drive a slot's cost negative trips `_actual_cost`'s catch-all
  (`-0.001` and below, on that mix; the boundary moves with the slot's token
  cost, so it is not a single number). NaN and infinity do demote. Separately, a
  bad value present at STARTUP is loud rather than silent — `estimate()` raises,
  so no run begins; the silent case needs the value to change after runs were
  already estimated. What is uniformly true: there is no validation and no log
  line. Logged as DEBT-015 rather than fixed here, to keep this change to one
  concern.
- **A slot that searched but returned no usable text pays no fee, and cannot.**
  Such a slot takes the #171 FAILED path (`_failed_answer`), carries no
  `token_usage`, and fails the honesty gate — so the whole run reports
  `"estimated"`. No measured receipt can under-report this way.
- **A `400` on a `:online` id is treated as a pre-generation refusal, which is
  reasoned rather than measured.** `404 "No endpoints found for model"` plainly
  precedes generation; a `400` might not, and the ledger contains no
  rejected-`:online` instance to check against. The error direction is
  UNDER-count, which is the conservative half under a `measured` label.
- Test doubles that duck-type `LiveProviderResult` must carry `searched`. One
  existed (`tests/unit/test_provider_stubs.py`) and was updated.

## How this is proven

`scripts/proofs/search_fee_measured_mutations.py` — **11 mutations, all
KILLED** against a green 30-test baseline, every restore verified byte-identical
with `diff -q` from a `cp` copy (never `git checkout`), and re-run after
`make format` in case it moved an anchor. Failure counts, in the order the
script runs them (01-06, 08, 09, 10, 11, 07): 2, 3, 1, 7, 6, 6, 3, 1, 5, 3, 7 —
six distinct values across eleven mutations, which is what distinguishes a
discriminating proof from a harness that fails uniformly. Every run reports
`N failed, M passed` with `N + M == 30`, so no kill is a collection error.

Mutations 01-03 cover the wire stamp and the intent-keyed alternative, 04
deletes the fee term outright, and 05-07 are the cardinality defeats (per run,
every slot, and leaking onto synthesis).

**Mutations 08-11 are four defeats adversarial review demonstrated against
earlier versions of this change.** Each was a wrong implementation that kept the
entire suite AND the then-current proof green:

- **08** replaced the config read with a literal `Decimal("0.01")` — a live money
  change at a default that says the fee is off. Killed now by
  `test_the_measured_fee_term_reads_the_SETTING_and_scales_with_it`, which
  measures the DELTA across five fee values at several searching-slot counts.
  The original tests pinned one fee against one total, which cannot tell "reads
  the setting" from "returns that constant".
- **09** replaced the suffix test with `":" in model_id`. It survived because
  every model id in the wire tests was colon-free. Killed now by
  `test_a_colon_bearing_model_id_is_not_mistaken_for_a_search_call`, with a
  positive partner proving a `:free` id still earns a fee when `:online` is
  appended.
- **10** scaled the fee by `len(answer.sources)`. It survived because the
  fixture gave every slot exactly one source. Killed now by unequal source
  counts (`[0, 3, 1, 7]`) — and zero is the common case, since `providers.py`
  records ~0-3% citation coverage on the live `:online` path.
- **11** truncated the fee to whole cents. It survived because **every fee value
  the tests used was a whole number of cents**, so it charged nothing at the
  real $0.007 while staying green across 116 tests. This was the same blind spot
  as 08-10 one level down, and it was caused by a test docstring boasting that
  it avoided the shipped default — which removed the only value the activation
  decision turns on. Killed now by sub-cent rows at $0.007 in the cardinality
  test (`4 → $0.0665`, `2 → $0.0525`) and sub-cent deltas in the SETTING test
  (`4 × $0.007 = $0.028`, the real-world per-run gap the ledger showed).

Cardinality is pinned by test, not by inspection (rule 6b):
`test_measured_total_adds_the_flat_search_fee_once_per_SEARCHING_call` holds 11
priced calls constant and varies only the fee and the NUMBER of searching slots,
with literals on both sides of every assertion (rule 7a).

**Two defeats this change does NOT pin**, both verified not reachable in
production and recorded rather than chased: scaling the fee by
`len(provider_attempt_order)` (always exactly one element on every live slot)
and `"online" in model_id` without the suffix (no id in the 13 static or ~440
live catalog entries contains it). Both are fixture-constant gaps, not money
bugs.
