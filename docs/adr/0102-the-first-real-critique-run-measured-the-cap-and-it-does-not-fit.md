# ADR-0102: The first real critique run measured the cap, and 2000 does not fit

## Status

Accepted — 2026-09-06.

Supersedes ADR-0101's severity finding (LATENT) and the dated evidence
statement in its Context, and **supersedes ADR-0081's bound table** (`0081:43`,
`judge OFF | 0.0547 | 0.1043 | ALLOW`) — the point figure is unchanged, the
bound is not. ADR-0101's refutation of the *"seven of eight"*
figure still stands — that figure was, and remains, a measurement of ANSWER
models. This record is the measurement ADR-0101 said was missing.

**Authorises nothing.** No `**Authorises:**` line; it may not be cited to
sanction a live-execution posture. It DOES move a money-adjacent constant, and
the measurement and rejected alternatives for that are below.

## Context

ADR-0101 recorded that `DEBATE_ROUND_MAX_TOKENS = 2000` had never been measured
on a critique, that no critique call had ever run, and that only a paid run
inside the declared window could settle it. On **2026-09-06T10:00:17Z** a
production run did exactly that, for **$0.0806**.

Harvested free from the Fly volume — `fly ssh console -a quorum-ai -C "cat
/data/telemetry-tokens.jsonl"`, 108 records, of which 18 carry the ADR-0093
decision-5 correlator and all belong to one `query_run_id`
(`1cb95597-09e3-4fd8-b3ec-e0ab73158a34`).

**The run was peer-shaped**: `debate_round_1` = 4 rows and `debate_round_2` = 4
rows, i.e. the eight critique calls ADR-0093 predicted, not two moderator calls.

### Measurement 1 — the cap does not fit

| stage | slot | model | completion | `finish_reason` |
|---|---|---|---|---|
| round 1 | 1 | `openai/gpt-4o-mini` | 292 | stop |
| round 1 | 2 | `anthropic/claude-haiku-4.5` | 1645 | stop |
| round 1 | 3 | `google/gemini-2.5-flash` | 930 | stop |
| round 1 | 4 | `nvidia/nemotron-3-nano-30b-a3b` | **2000** | **length** |
| round 2 | 1 | `openai/gpt-4o-mini` | 502 | stop |
| round 2 | 2 | `anthropic/claude-haiku-4.5` | **2000** | **length** |
| round 2 | 3 | `google/gemini-2.5-flash` | **2000** | **length** |
| round 2 | 4 | `nvidia/nemotron-3-nano-30b-a3b` | **2000** | **length** |

**4 of 8 critique calls clipped; 3 of 4 in ROUND 2.** Round 2 is the round
ADR-0096 made carry a critique AND a self-assessment, rationale, sources and a
**revised answer** — and `synthesis` reads those revised answers as its primary
input (`synthesis.py`, `critique.revised_answer`). So the text being cut is the
source-backed answer, on three of four slots, at full price.

**This is the concern ADR-0101 preserved, now measured.** The *figure* that
prompted it was wrong about its population; the *worry* was right.

### Measurement 2 — what eight critique calls cost (unblocks W3/ADR-0094)

| stage | n | prompt tokens | completion tokens |
|---|---|---|---|
| `initial_answers` | 4 | 9,446 | 3,876 |
| `debate_round_1` | 4 | 19,047 | 4,867 |
| `debate_round_2` | 4 | 22,597 | 6,502 |
| `synthesis` | 5 | 22,881 | 9,663 |
| `judge` | 1 | 5,338 | 119 |
| **run total** | **18** | **79,309** | **25,027** |

The eight critique calls carry **41,644 input tokens — 53% of the run's entire
input budget.** Receipt: `$0.0806`.

### What this run did NOT settle

- **Measurement 3 (do `:online` annotations carry passage CONTENT?) is still
  unanswerable.** None of the 22 fields present describes an annotation, and
  `SourceReference` keeps only title/url/provider/is_fallback, so
  `_extract_citations` discards any content field at parse time. The money was
  spent and this question was lost, exactly as predicted before the run. Any
  future spend on it needs the capture shipped FIRST.
- **The right cap.** A clipped reply reports *exactly* the cap, so this run
  proves only that three models wanted **≥ 2000**. It cannot say whether 4000
  is enough. That is stated here so the next reader does not mistake 4000 for a
  measured sufficiency.
- **Timing.** No per-call elapsed time exists — ADR-0093 listed it as a
  candidate and did not adopt it. See Consequences.

Free confirmations from the same harvest: `usage_absent` **0 of 18** and
`stream_terminator: "done"` **18 of 18**, re-confirming ADR-0084 on the
peer-critique path, which had never been exercised live before.

## Decision

### Raise `DEBATE_ROUND_MAX_TOKENS` 2000 → 4000, and `cost_debate_output_tokens_cap` with it

The two MUST move together or the fail-safe bound stops being a ceiling
(`debate.py`'s own comment, and
`test_estimate_token_model.py::test_bound_cap_assumptions_match_the_enforced_caps`).
Both are now 4000.

### 4000, and the whole threshold ladder with it

**The first version of this record measured the wrong thing, and shipped a
false sentence into `src/`.** It reported a sweep labelled *"judge ON —
production's posture"* whose numbers were taken with `peer_critique_enabled`
left at the config default, **False**. `fly.toml:84` sets it `true`, `/status`
reports it `true`, and this record's own Measurement 1 is a peer-shaped run.
Adversarial review caught it. The corrected sweep, varying only the cap, at the
posture production actually runs:

| cap | bound, peer OFF (what the first draft measured) | bound, peer ON (production) | rail at the OLD ladder |
|---|---|---|---|
| 2000 | 0.1172 | **0.1415** | ALLOW — by $0.0085 |
| 3000 | 0.1307 | 0.1621 | REQUIRE_CONFIRMATION |
| 4000 | 0.1442 | **0.1827** | REQUIRE_CONFIRMATION |
| 5000 | 0.1577 | 0.2033 | REQUIRE_CONFIRMATION |

**EVERY FIGURE IN THIS RECORD IS AT ONE SET OF CONDITIONS**, named here because
the first draft quoted a bound table and a transition sweep taken under
different ones and review caught the mismatch: the four default slots with
`search=True`, `peer_critique_enabled=True`, judge `openai/gpt-4.1-mini`, and
the query `"Compare transparent model answers"` (33 characters). The bound
moves with query length; a figure without its query is not reproducible.

At production's posture the old `SOFT_THRESHOLD_USD` of `0.15` left **$0.0085**
of head-room. There was no cap raise that fitted under it. So "4000 avoids the
confirmation click" was never available; the real choice was between accepting
the click and moving the line.

Worse than a click. Sweeping all **425** catalog models four-up, under the same
conditions, **raising the cap alone** would have done this:

| transition, cap 2000 → 4000, ladder unchanged | count |
|---|---|
| ALLOW → ALLOW | 183 |
| ALLOW → **REQUIRE_CONFIRMATION** | **42** |
| REQUIRE_CONFIRMATION → REQUIRE_CONFIRMATION | 37 |
| REQUIRE_CONFIRMATION → **BLOCK** | **32** |
| BLOCK → BLOCK | 131 |

BLOCK mints no confirmation token, so those **32** model choices become
unrunnable — a hard refusal, not a prompt.

**The operator's decision, taken on that evidence: move the ladder.**

| constant | before | after |
|---|---|---|
| `SOFT_THRESHOLD_USD` | 0.15 | **0.30** |
| `DAILY_CAP_USD` | 0.20 | **0.40** |
| `HARD_LIMIT_USD` | 0.25 | **0.50** |
| `GLOBAL_DAILY_CEILING_USD` | 5.00 | **5.00 — unchanged, by instruction** |

`DAILY_CAP_USD` is not optional. `costs.py` records that its value comes from
an ORDERING constraint — `SOFT < DAILY < HARD`, or the confirmation band is
unreachable and the confirmation flow becomes dead code — and says in its own
words that changing the envelope "has to move the whole three-threshold ladder,
not this constant alone". Two tests assert that ordering.

Measured outcome of the ladder move, same sweep, same conditions — cap 2000 on
the old ladder versus cap 4000 on the new one:

| transition | count |
|---|---|
| ALLOW → ALLOW | 225 |
| REQUIRE_CONFIRMATION → **ALLOW** | **57** |
| BLOCK → **REQUIRE_CONFIRMATION** | **36** |
| REQUIRE_CONFIRMATION → REQUIRE_CONFIRMATION | 12 |
| BLOCK → BLOCK | 95 |
| **to a WORSE band** | **0** |

- the default mix returns to **ALLOW** (0.1827 against the new 0.30 line);
- **all 32** models that raising the cap alone would have made unrunnable are
  rescued;
- 57 mixes that ask for confirmation today would just run, and 36 currently
  refused become runnable with confirmation;
- **nothing moves to a worse band** — no ALLOW→CONFIRM, no ALLOW→BLOCK, no
  CONFIRM→BLOCK. Independent review re-derived this at query lengths from 33 to
  9,000 characters and found 0 worse-band transitions at every one, so it is
  the one claim here that does not depend on the query.

### Raise the run deadline 360s -> 720s

**Operator decision, and it changes a PUBLISHED REQUIREMENT.**
`quorum_run_deadline_seconds` is not merely a constant: it is NFR-001 ("hard
timeout at 360 seconds"), NFR-004 ("within 360 seconds"), AC-021, two rows of
the traceability matrix, and a line on the operator dashboard. All seven sites
moved together; a value that lived in the code and disagreed with the published
target would be worse than either number alone.

The engineering reason it needs to move at all is the one ADR-0078's
arithmetic could not have anticipated. That ADR set 360 from *"five sequential
legs, each bounded by `openrouter_call_budget_seconds`, so 5 x 60 = 300s"* —
**one call per leg**. Peer critique broke that assumption: `_build_peer_round`
dispatches critics SEQUENTIALLY, so each debate leg is bounded by FOUR call
budgets, not one. The five-leg model no longer describes the worst case, and
this change makes those calls longer still.

**What this costs the user:** a run may now take up to twelve minutes before
the safety net cuts it, where six was promised. That is a real product change,
not a side effect, which is why NFR-001 and the dashboard move with the
constant rather than being left to drift.

**`DEBATE_HARD_TIMEOUT_MS` is deliberately NOT moved here.** The round-1 gate
stays at 180s until a live run measures what round 1 actually takes at cap
4000. Raising the run deadline first is what makes a larger gate *possible*
without the gate consuming the entire run budget — at 360s a six-minute gate
would have equalled the whole deadline, leaving nothing for round 2, synthesis
and the judge.

## Rejected alternatives

**5000.** Rejected in favour of 4000 on cost: at production's posture 5000
bounds at 0.2033 against 4000's 0.1827, and the run measured nothing that
requires the larger value — three replies stopped at exactly 2000, which puts a
floor under the requirement and no ceiling on it.

**Cap 4000 while leaving the ladder alone.** Rejected by the operator on the
sweep above: it ships a confirmation click on every run AND makes 33 model
choices unrunnable. This alternative is recorded because it was the plan for
two review rounds, and only the corrected posture measurement ruled it out.

**Leaving the cap at 2000 and moving nothing.** Rejected: the clipping is real,
measured, and lands on the source-backed revised answer that synthesis reads
first. Doing nothing preserves a defect the run has now demonstrated.

**Leave the cap at 2000 until timing is measured.** Rejected, but it was close.
Clipping is happening now, in production, on the source-backed answer — and the
timing risk is bounded by `openrouter_call_budget_seconds` failing safe rather
than overspending. Recorded as the live risk in Consequences.

**Derive the new cap from the run.** Impossible, and worth saying: a clipped
reply reports exactly the cap. 4000 is a judgement bounded by the confirmation
rail, not a measured sufficiency.

## Consequences

- **`SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS` doubles, 8000 → 16000**, because it is
  DERIVED (`DEBATE_ROUND_MAX_TOKENS × CHARS_PER_TOKEN`) and its comment is
  emphatic that the derivation is the point. Twice as much critique text now
  reaches synthesis — the stage already carrying 29% of run input.
- **The global race bound doubles, $4.00 → $8.00.**
  `GLOBAL_DAILY_CEILING_USD`'s docstring bounds an accepted race at
  `_MAX_CONCURRENT_RUNS` (16) x `HARD_LIMIT_USD`; doubling the hard limit
  doubles the worst-case overshoot ABOVE the $5.00 rail. The ceiling itself is
  unchanged by instruction. This is a DERIVED consequence of the ladder, not a
  decision taken on its own evidence, and it is the reason to leave the ceiling
  where it is. Recorded in `costs.py` beside the constant.
- **The fail-safe bound rises**, judge-OFF `0.1043 → 0.1313` on the default
  slots. Every re-measured literal below was taken by the method its own test
  docstring prescribes, never adjusted to fit:
  - `test_peer_bound_is_a_true_ceiling`: bound `0.1043 → 0.1313`; the fixed-price
    bound `1.8086 → 2.5326`, counterfactual `1.7466 → 2.4086`. **The shortfall
    doubled, `$0.0620 → $0.1240`, exactly as the cap doubled** — that test's
    docstring predicted the shortfall "is a function of the round-2 critique
    cap", so the prediction is what validates the re-measure.
  - `test_bound_covers_the_judge`: four-stage bound `0.2249 → 0.2669`, judge-on
    `0.2583 → 0.3003`, and **the judge term `on - off` is byte-identical at
    `0.0334`** — a debate-cap change must not move it, and did not.
  - The POINT estimate is **unchanged at `0.0548`**: the cap prices the ceiling,
    not the typical run. That asymmetry is the sanity check.
- **TIMING: the magnitude is unmeasured, but three facts about it are not.**
  ADR-0093 concluded a 2000-token critique "fits `openrouter_call_budget_seconds
  = 60.0`" from wall-clock measurements of 6.385–26.492s, on models generating
  right up to the cap. This change doubles the tokens on exactly those 8 calls
  and no per-call elapsed time is recorded anywhere, so the magnitude stays
  **UNMEASURED**. What is NOT unknown, and what the first draft of this record
  omitted:
  - **Dispatch is SEQUENTIAL.** `_build_peer_round` says so in its own
    docstring and the code is a plain `for critic in critics:` with a blocking
    call. So one peer round is bounded by *four* call budgets, not one.
  - **`config.py`'s run-deadline arithmetic assumes one call per leg** — "five
    sequential legs, each bounded by `openrouter_call_budget_seconds`, so
    5 x 60 = 300s". Under peer critique the worst case is far larger. This is
    PRE-EXISTING and not introduced here, but this change makes those calls
    longer.
  - **Round 2 is gated on round 1's elapsed time** by
    `DEBATE_HARD_TIMEOUT_MS = 180_000`. If it fires, `missing_steps` includes
    `debate_round_2` AND `synthesis` — and round 2 is precisely the round this
    change exists to protect.
  - **"Fail-safe, not overspend" was wrong**, and the first draft said it. A
    cut stream returns `_DISPATCH_UNMEASURED` and logs
    `billing_class: possibly_billed` with the usage deliberately discarded, and
    a possibly-billed unpriced call demotes the whole run's receipt from
    `measured` to `estimated`. What a user observes is a slot that produced
    nothing, a degraded banner, an `estimated` receipt — **and money that may
    have been spent**. The honest phrasing is "may pay and return nothing".
  The cheapest way to measure it is the `finish_reason` neighbour ADR-0093
  named and did not adopt: add per-call elapsed to the token stream and read it
  off the next live run at no cost.
- ADR-0101 is superseded on severity only. Its refutation stands: the
  *"seven of eight"* figure measured answer models on a cap-filling prompt, and
  nothing here makes it a critique measurement.
