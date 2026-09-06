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

### 4000, not the 5000 first proposed

Measured by driving `_estimate_bound_usd` directly and varying ONLY the cap,
judge ON — production's posture, using the four slot models the harvested run
actually used:

| cap | bound | rail |
|---|---|---|
| 2000 (before) | 0.1172 | ALLOW |
| 4000 | **0.1442** | **ALLOW** |
| 4500 | 0.1510 | REQUIRE_CONFIRMATION |
| 5000 | 0.1577 | REQUIRE_CONFIRMATION |

`SOFT_THRESHOLD_USD` is `0.15`. **5000 would put a confirmation click on every
production run** — a product behaviour change, not merely a cost one. It
crosses on the generic test slot list too (there, by 3500). 4000 is the largest
value measured that keeps production inside the no-confirmation band.

The method reproduces the repo's documented judge-OFF figure exactly (`0.1043`
at cap 2000), which is the evidence that these numbers are real and not an
artefact of the probe.

## Rejected alternatives

**5000, as first proposed.** Rejected on the measurement above: it crosses
`SOFT_THRESHOLD_USD` and changes the UX of every run. Recorded because the
proposal was explicit and the reason for departing from it must be too.

**5000 plus a higher `SOFT_THRESHOLD_USD`.** Rejected: moving a spend guardrail
to preserve a UX, on the strength of ONE run, is the pattern ADR-0094 exists to
prevent. The threshold is a money decision that deserves its own evidence.

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
- **UNMEASURED RISK, stated rather than hidden: per-call time.** ADR-0093
  concluded a 2000-token critique "fits `openrouter_call_budget_seconds = 60.0`"
  from wall-clock measurements of 6.385–26.492s. At 4000 that headroom shrinks,
  and eight such calls sit inside `quorum_run_deadline_seconds` — which is
  NFR-001/AC-021, a published requirement. **No per-call elapsed time is
  recorded anywhere**, so this could not be checked. The failure mode is a call
  budget expiring (fail-safe, not overspend), but a run could return short. The
  cheapest fix is the `finish_reason` neighbour ADR-0093 already named and did
  not adopt: add per-call elapsed to the token stream, and read it off the next
  live run at no cost.
- **`0.1043` is now stale in 27 files, and they are deliberately NOT rewritten.**
  It is PROSE in every one — `grep -rn "0\.1043" . | grep assert` returns no
  assertion, which is why nothing went red. This repo measured that exact
  pattern before (21 files on 2026-08-26) and PR #378 set the precedent:
  correct the canonical statement, leave the repetitions. The canonical
  statement is ADR-0081's table, superseded above. Rewriting 27 files of
  commentary would be churn on a diff whose concern is the cap (rule 17), and
  the repetitions are already known-unreliable by their own record.
  Two of the 27 are NOT stale and must not be "fixed":
  `docs/18-requirement-traceability-matrix.md` and `CHANGELOG.md` state
  `0.0771 -> 0.1043` as DATED HISTORY of what ADR-0028 did on 2026-08-09,
  which remains true.
  Re-derive rather than trust that count:
  `grep -rl "0\.1043" --exclude-dir=.git --exclude-dir=.venv . | wc -l`
- ADR-0101 is superseded on severity only. Its refutation stands: the
  *"seven of eight"* figure measured answer models on a cap-filling prompt, and
  nothing here makes it a critique measurement.
