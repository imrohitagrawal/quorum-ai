# ADR-0093: A peer critique nests inside its round, and a critic's spend gets its own row

## Status

Proposed — 2026-09-01. **Nothing in this record is implemented.** It fixes the
shape peer critique (#290, board row W2) must take *before* it is built, so the
build is not designed from defects one at a time. Two of its three decisions are
free; the third moves money and is marked for the product owner.

## Context

#290 asks that each of the four answer models read the other three and write its
own critique, in both rounds, instead of one moderator model
(`settings.debate_model_id`) writing both. `#290` stays open; this record
narrows it, it does not close it.

**Numbering note.** This record was centrally assigned `0092`. That number was
already taken on `origin/main` by
`0092-the-board-anchor-is-checked-against-a-main-this-checkout-can-see.md`
(merged in `bc1f1a1`), so it is filed as `0093`.

### What has already landed since the issue was written

The issue's own text is stale in three places, and the design changes because of
it. Each line below was verified by command; the commands and outputs are in
`docs/analysis/2026-09-01-290-peer-critique-failure-modes.md`.

| The issue says | Status now | Evidence |
|---|---|---|
| "It needs a usage record carrying `model_id`" | **DONE** | ADR-0037, commit `74063b2`. `TokenUsage.model_id` (`providers.py:335`), stamped at `debate.py:935`, priced at `query_run_orchestration.py:2808` |
| "the measured-cost path prices **every** debate call on `settings.debate_model_id`" | **no longer true for `by_stage`** | `model_id=debate_usage.model_id or settings.debate_model_id` |
| "**Unmeasured.** One deliberate paid probe … settles it" | **MEASURED** 2026-08-26 | 8 paid calls, $0.034170, recorded in issue #290's comment |

The probe's verdict was that peer critique could **not** be built against the
non-streaming call path: worst per-`recv` gap **25.055 s** on
`openai/gpt-4o-mini` against `openrouter_timeout_seconds = 8.0`. That verdict has
since been acted on. Board row W1 streamed the provider call (ADR-0084, accepted
2026-08-30) — `providers.py:1259` sends `"stream": True` unconditionally — and
ADR-0078 added a cumulative `openrouter_call_budget_seconds = 60.0`
(`config.py:110`).

### Measured, and what each number does and does not settle

| Quantity | Value | Source | What it settles |
|---|---|---|---|
| Worst per-`recv` gap, 2000-token critique, **non-streamed** | 25.055 s (`openai/gpt-4o-mini`) | #290 probe, 2026-08-26, 8 paid calls | the old transport could not carry this feature |
| Same model, **streamed** | 0.478 / 0.208 s | B3 probe, quoted in ADR-0084 | the new transport can — *on a paired sample, different token caps* |
| Wall clock, 2000-token critique | 6.385 s – 26.492 s across the four slot models | #290 probe | a single critique fits `openrouter_call_budget_seconds = 60.0` |
| `DEBATE_ROUND_MAX_TOKENS` | 2000 | `debate.py:67`, pinned to `cost_debate_output_tokens_cap = 2000` (`config.py:480`) | the cap the critique is priced and enforced at |
| Default run bound, judge-ON | `0.1134` against `SOFT_THRESHOLD_USD = 0.15` | ADR-0081 | ~3.7 cents of headroom before a confirmation click |
| Projected bound with peer critique | `0.1419` – `0.1599` (×1.25 – ×1.41) | ADR-0081, **arithmetic only, not measured** | nothing — it is why W3 is deferred |

**What remains genuinely unsettled is an observation, not a probe.**
`docs/65-open-work.md` records W1 as *"latent-correct, not observed"*: with
`OPENROUTER_LIVE_EXECUTION_ENABLED` false, nothing exercises the streamed path in
production. Building peer critique on a transport that has never carried a real
run is what rule 8c forbids.

## Decision

### 1. `DebateOutput` keeps one element per round; the peer detail nests inside it

```python
#: Discriminator values for ``DebateOutput.critique_shape``.
CRITIQUE_SHAPE_MODERATOR = "moderator"   # today's shape; the default
CRITIQUE_SHAPE_PEER = "peer"


class SlotCritique(BaseModel):
    """One answer model's critique of the other slots, inside one round."""

    critic_slot_number: int = Field(ge=1, le=4)
    critic_model_id: str = Field(min_length=1, max_length=256)
    critique_text: str
    focus_areas: list[str] = Field(default_factory=list)
    #: Per-critic provenance, mirroring ``DebateOutput.debate_mode`` and
    #: defaulting the same conservative way: assume templated unless told.
    critique_mode: str = DEBATE_MODE_FALLBACK


class DebateOutput(BaseModel):
    round_number: int = Field(ge=1, le=2)
    focus_areas: list[str]
    critique_text: str
    status: DebateRoundStatus
    debate_mode: str = DEBATE_MODE_FALLBACK
    panel_stance: PanelStance | None = None
    #: NEW. Which mechanism produced this round. Defaults to the shape that
    #: ships today, so every existing construction site and fixture keeps its
    #: current meaning without editing — the same defaulting ``debate_mode``
    #: and ``panel_stance`` already use.
    critique_shape: str = CRITIQUE_SHAPE_MODERATOR
    #: NEW. Empty under the moderator shape. One entry per ELIGIBLE slot under
    #: the peer shape.
    slot_critiques: tuple[SlotCritique, ...] = ()
```

**`critique_text` stays populated under both shapes.** Under the peer shape it is
a derived digest of `slot_critiques`. This is what keeps the change additive:
five `app.js` consumers read `debate_outputs` and every one of them keeps
rendering something honest with no JavaScript change at all. Round cardinality
stays 2, so the transcript's `` `${debate.length} round${…}` `` (`app.js:4816`)
still reads "2 rounds".

**Eligibility is `model_was_invoked`**, which already exists
(`providers.py:381`), AND `status is COMPLETED`. A simulated slot does not
critique — asking it to would manufacture the exact fake this feature removes.
When zero slots are eligible the moderator path runs unchanged and
`critique_shape` stays `"moderator"`.

### 2. The usage tuple does NOT widen

`DebateResult.live_call_usages` stays `list[tuple[int, TokenUsage | None]]`
(`debate.py:528`). `_call_debate_model` gains a required `model_id` parameter and
stamps *that* onto the record instead of `settings.debate_model_id`
(`debate.py:935`).

This is enough, and reading the pricing loop is what shows it:
`query_run_orchestration.py:2793-2811` iterates the records, prices each at
`debate_usage.model_id or settings.debate_model_id`, and sums into
`debate_by_round[round_number]`. Four critics in round 1 append four records
tagged `1`, each priced at its own model, summing to the correct
`debate_round_1` figure. ADR-0037 predicted exactly this ("without any further
billing-layer change"); this record confirms it against the loop.

### 3. Critique spend gets its own `by_model` row — **this one needs the owner**

`writer_cost = debate_total + synthesis_cost` (`costs.py:2216`) folds every
debate call into one row whose `model_id` is the literal string `"synthesis"`
and whose label is fixed to `"Debate + synthesis"` (`costs.py:1533` on the
estimate path, `costs.py:2220` on the measured path, `app.js:6519` rendering
both). Under peer critique the four **slot** models earn that spend, so a slot's
money would render under a row named after the writer — the identical defect
ADR-0064 fixed for the Layer-B judge, whose own comment at `costs.py:1534-1537`
says folding it in "would label spend on a THIRD model as synthesis spend".

**Emit one `kind="critique"` row per critic**, `model_id` = the critic's model
id, `display_name` = its catalog short name. The `"Debate + synthesis"` row keeps
its name and keeps the *moderator and synthesis* spend only.

The constraint that decides this, and it is load-bearing: the result view pairs
each estimate row to its actual row on the composite key
`` `${line.kind || "model"} ${line.model_id || line.display_name}` ``
(`app.js:4350`), resolves it with `.find()` — first match wins (`app.js:4359`) —
and de-duplicates the backfill with a `Set` of those keys (`app.js:4384`). Two
rows sharing a `(kind, model_id)` pair collapse: one actual figure renders twice
and the other never renders, silently under-summing the itemized column. A
`kind="critique"` row keeps the pair unique (a slot model appears once as
`model <id>` and once as `critique <id>`). `app.js:6519` needs no change — its
ternary falls through to `row.display_name` for any kind that is not
`"synthesis"` — and `app.js:6877`'s `kind === "model"` allowlist already excludes
the new row from the slot cards.

**Why this needs the product owner.** It changes what a receipt shows: six rows
become up to ten. That is a user-visible money surface, and ADR-0081 already
records the owner's decision that nothing about the spend surface moves until
#290 is built and measured.

## Rejected alternatives

**One row per `(round, model)` in `debate_outputs`.** This is the shape the
issue's design notes explicitly warn against, and the warning understates the
damage. The issue names one consumer; there are five, and only one of them fails
silently:

| `app.js` | consumer | what 8 rows for a 2-round run does |
|---|---|---|
| 1829 | `new Map(debate.map((r) => [r.round_number, r]))` | keys collide — silently keeps the **last** critic per round |
| 3139 | Markdown export loop | four identical `### Round 1` headings |
| 4543 | `renderResultDebate` | four identically-captioned cards per round |
| 4816 | `` `${debate.length} round${…}` `` | a 2-round run reads **"8 rounds"** |
| 5458 | `renderDebateAndSynthesis` | eight cards; `data-round` clamps to 1-4, colours repeat |

Rejected. Nesting costs one optional field and one discriminator; flattening
costs five consumers and one outright false statement to the user.

**Widen the tuple to `(round, model_id, usage)`.** Rejected as unnecessary, on
top of ADR-0037's blast-radius reason (13 test files, 101 assertion lines, both
measured there). The pricing loop already reads the model from the record; a
third tuple element would be a second, redundant source for the same fact — and
two sources for one fact is how they disagree.

**Fold critique spend into each slot's existing `kind="model"` row.** Rejected:
it silently redefines an existing row from "what this slot's answer cost" to
"what this slot cost in total", so a number a user has seen before changes
meaning without changing name. It also breaks the `by_stage` ↔ `by_model`
correspondence, since `by_stage` keeps critique under `debate_round_N`.

**One pooled `"Peer critique × N"` row.** Rejected: it keeps the receipt small
but reproduces the original defect in miniature — four different models' spend
under one label attributable to none of them. If the ten-row receipt proves too
long in review, the answer is a collapsed disclosure in the UI, not a lossy
partition on the server.

**Lower `DEBATE_ROUND_MAX_TOKENS` to fit the old 8 s budget.** Rejected: it was
raised 700 → 2000 by WP-D/F-07 because the moderator clipped critiques
mid-sentence and the truncation propagated into synthesis (`debate.py:57-67`).
Streaming (ADR-0084) removed the reason to consider it.

## Consequences

- **Nothing here is built.** No source file changes shape as a result of this
  record. The one code change shipping alongside it is a comment correction, in
  `providers.py`, described below.
- **The next step is human-gated, and it is not another latency probe.** The
  critique-latency question the issue posed was answered on 2026-08-26 and acted
  on by W1. What is required before peer critique is built is the
  **owner-authorised live-execution measurement window** that turns W1 from
  "tested" into "observed" — `docs/65-open-work.md` states this is the step
  between W1 and W2, not an optional follow-up. Decision 3 above additionally
  needs the owner's sign-off in its own right, because it changes a receipt.
- **W3 (the money constants) stays deferred and stays STOP.** ADR-0081's
  condition — "#290 is built and its cost is measured" — is not met by this
  record and is not moved by it. The ×1.25–×1.41 projection remains arithmetic.
- **A cancel's un-billing contract is per-round, not per-critic.** With critics
  dispatched through a pool, `should_stop` (`debate.py:899`) un-bills only the
  critics whose thread has not yet reached the check. The issue's "un-bills up to
  three undispatched critics" holds for a sequential fan-out only. Do not write a
  test that asserts a count of un-billed critics inside one round: it would
  assert a race.
- **Guard the stamp by cardinality, not by outcome.** `_actual_cost`'s
  `or settings.debate_model_id` fallback makes a *dropped* stamp
  indistinguishable from a *correct moderator* stamp. Under the peer shape, assert
  that the number of stamped debate usage records equals the number of critique
  calls dispatched (rule 6b), not merely that the run was billed.
- **`providers.py:333-334` is corrected in the same pull request.** It said the
  stamp is applied by "callers that know the model (`debate.py`,
  `synthesis.py`)". `synthesis.py` does not stamp it and never constructs a
  `TokenUsage`; verified by `grep -rn 'update={"model_id"' src/product_app/`
  (one hit, `debate.py:935`) and `grep -n "TokenUsage(" src/product_app/synthesis.py`
  (no output). No live defect — synthesis prices unconditionally at
  `settings.synthesis_model_id` — but the sentence is false as written.
- **The moderator overlapping slot 2 is unchanged and stays reported, not
  refused.** `settings.debate_model_id` defaults to `anthropic/claude-haiku-4.5`
  (`config.py:544`), which is `DEFAULT_MODEL_IDS[1]` (`model_slots.py:69`).
  ADR-0086 decided that posture; decision 3's `kind="critique"` row keeps the
  composite key unique even when the moderator and a critic are the same model.

## References

- Issue #290 (peer critique), and its 2026-08-26 measurement comment
- ADR-0032 — the copy-vs-mechanism correction that split #290 out
- ADR-0037 — the billing prerequisite, already merged
- ADR-0064 — why the judge is not folded into the writer row
- ADR-0078, ADR-0084 — the call-time budget and streaming
- ADR-0081 — the money constants wait for a measured #290
- ADR-0086 — the moderator grading its own answer is reported, not refused
- `docs/analysis/2026-09-01-290-peer-critique-failure-modes.md` — the rule-16e
  enumeration this record is designed against, with every command and output
- `docs/65-open-work.md` rows W1, W2, W3
