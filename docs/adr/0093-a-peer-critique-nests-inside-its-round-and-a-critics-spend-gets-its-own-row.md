# ADR-0093: A peer critique nests inside its round, renderers read the digest, deciders read the critics

## Status

Accepted — 2026-09-01. Decision 3 **signed off by the product owner 2026-09-02**; see "Owner decision" below, which also adds decisions 4 and 5. This record decides a SHAPE — **nothing here is built**, and the build is deliberately not scheduled.

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
| "It needs a usage record carrying `model_id`" | **DONE** | ADR-0037, commit `74063b2`. `TokenUsage.model_id` (`providers.py:340`), stamped at `debate.py:935`, priced at `query_run_orchestration.py:2808` |
| "the measured-cost path prices **every** debate call on `settings.debate_model_id`" | **no longer true for `by_stage`** | `model_id=debate_usage.model_id or settings.debate_model_id` |
| "**Unmeasured.** One deliberate paid probe … settles it" | **MEASURED** 2026-08-26 | 8 paid calls, $0.034170, recorded in issue #290's comment |

The probe's verdict was that peer critique could **not** be built against the
non-streaming call path: worst per-`recv` gap **25.055 s** on
`openai/gpt-4o-mini` against `openrouter_timeout_seconds = 8.0`. That verdict has
since been acted on. Board row W1 streamed the provider call (ADR-0084, accepted
2026-08-30) — `providers.py:1264` sends `"stream": True` unconditionally — and
ADR-0078 added a cumulative `openrouter_call_budget_seconds = 60.0`
(`config.py:110`).

### Measured, and what each number does and does not settle

| Quantity | Value | Source | What it settles |
|---|---|---|---|
| Worst per-`recv` gap, 2000-token critique, **non-streamed** | 25.055 s (`openai/gpt-4o-mini`) | #290 probe, 2026-08-26, 8 paid calls | the old transport could not carry this feature |
| Same model, **streamed** | 0.478 / 0.208 s | B3 probe, quoted in ADR-0084 | the new transport can — *on a paired sample, different token caps* |
| Wall clock, 2000-token critique | 6.385 s – 26.492 s across the four slot models | #290 probe | a single critique fits `openrouter_call_budget_seconds = 60.0` |
| `DEBATE_ROUND_MAX_TOKENS` | 2000 | `debate.py:67`, pinned to `cost_debate_output_tokens_cap = 2000` (`config.py:480`) | the cap the critique is priced and enforced at |
| `SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS` | 8000, `= DEBATE_ROUND_MAX_TOKENS × CHARS_PER_TOKEN` | `synthesis.py:203`, `costs.py:257` | how much critique reaches synthesis — see decision 1 |
| Default run bound, judge-ON | `0.1134` against `SOFT_THRESHOLD_USD = 0.15` | ADR-0081 | ~3.7 cents of headroom before a confirmation click |
| Projected bound with peer critique | `0.1419` – `0.1599` (×1.25 – ×1.41) | ADR-0081, **arithmetic only, not measured** | nothing — it is why W3 is deferred |

**What remains genuinely unsettled is an observation, not a probe.**
`docs/65-open-work.md:651-655` records W1 as *"latent-correct, not observed"*:
with `OPENROUTER_LIVE_EXECUTION_ENABLED` false, nothing exercises the streamed
path in production. The board says the owner-authorised measurement window is
what turns W1 from `"tested"` into `"measured"`. Building peer critique on a
transport that has never carried a real run is what rule 8c forbids.

### The mistake this record made in its first draft, and the rule that follows

The first draft enumerated the **five `app.js` consumers** of `debate_outputs`
and concluded the change was additive. That census was wrong in kind, not in
count: it enumerated *renderers* and stopped. Adversarial review found two
server-side readers of `critique_text` that are not renderers at all —
`_debate_signals_convergence` (`synthesis_consensus.py:641`), which can return
`"strong"` for the whole panel, and the synthesis prompt builder
(`synthesis.py:787`), which slices the critique into every synthesis section.
Both **decide**; neither renders. A design that satisfies the renderers and
ignores the deciders ships silently wrong behaviour, which is what decisions 1
and 1a below now prevent.

## Decision

### 1. `DebateOutput` keeps one element per round; the peer detail nests inside it

```python
#: Discriminator values for ``DebateOutput.critique_shape``. Closed set, and a
#: test enumerates it — the precedent is ``DEBATE_MODES`` two screens above
#: (``debate.py:180-197``): "the comment is the promise, the test is the
#: guarantee."
CRITIQUE_SHAPE_MODERATOR = "moderator"   # today's shape; the default
CRITIQUE_SHAPE_PEER = "peer"
CRITIQUE_SHAPES = frozenset({CRITIQUE_SHAPE_MODERATOR, CRITIQUE_SHAPE_PEER})


class SlotCritique(BaseModel):
    """One answer model's critique of the other slots, inside one round."""

    critic_slot_number: int = Field(ge=1, le=4)
    critic_model_id: str = Field(min_length=1, max_length=256)
    critique_text: str
    focus_areas: list[str] = Field(default_factory=list)
    #: Per-critic provenance, mirroring ``DebateOutput.debate_mode`` and
    #: defaulting the same conservative way: assume templated unless told.
    #: Read by the deciders in 1a — a templated critic is skipped there, which
    #: is #185's guard applied per critic instead of per round.
    critique_mode: str = DEBATE_MODE_FALLBACK
    #: This critic's own structured reading, when it gave one. Required so the
    #: peer shape has a producer for ``panel_stance`` at all — see 1b.
    stance: PanelStance | None = None


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

**Eligibility is `model_was_invoked`** (`providers.py:386`) AND
`status is COMPLETED`. A simulated slot does not critique — asking it to would
manufacture the exact fake this feature removes. When zero slots are eligible
the moderator path runs unchanged and `critique_shape` stays `"moderator"`.

### 1a. Renderers read `critique_text`; deciders read `slot_critiques`

This is the load-bearing half of the design, and the first draft did not have it.

**`critique_text` is a RENDER-ONLY digest.** It stays populated under both
shapes so the five `app.js` consumers and the Markdown export keep working with
no JavaScript change and round cardinality stays 2 — the transcript's
`` `${debate.length} round${…}` `` (`app.js:4816`) still reads "2 rounds". It is
built by one named function, and it is **bounded and sanitised**:

- **Bounded.** Each critic contributes at most
  `SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS // len(eligible_critics)` characters, so
  the digest's total stays inside the 8000-char slice `synthesis.py:787`
  already takes. This preserves that constant's stated derivation verbatim —
  *"A critique cannot be longer than the debate call that produced it was
  allowed to be"* (`synthesis.py:195-197`) — which an unbounded join would
  falsify, and it is the *"derived critique excerpt cap"* the issue asked for
  and the first draft dropped. Without it, synthesis reads roughly the first
  quarter of the digest — about one critic — and never learns the other three
  were paid for.
- **Sanitised.** The digest is machine-concatenated from up to four untrusted
  outputs and then flows into round 2's prompt raw (`debate.py:997`, which
  appends `prior_round` with no treatment). `_one_line` (`debate.py:265`) is
  today deliberately NOT applied to that text, and its own docstring measures
  that `.replace("\n", " ")` misses `\r`, `U+2028`, `U+0085` and `U+001C` —
  each of which forges a `- Slot N — …` row. One model's output through that
  hole is the risk that was accepted; four concatenated outputs is a different
  risk. **Every `SlotCritique.critique_text` passes `_one_line` before it enters
  the digest**, and the digest labels each contribution by
  `critic_slot_number`.

**Every DECIDER reads `slot_critiques` directly, never the digest.** Two exist
today and both are money- or trust-bearing:

| Decider | Reads today | Must read under the peer shape |
|---|---|---|
| `_debate_signals_convergence` (`synthesis_consensus.py:641`, reached from `:426`, can return `"strong"`) | `round_output.critique_text`, gated on `debate_mode == DEBATE_MODE_LIVE` | `slot_critiques`, skipping any critic whose `critique_mode` is not live, and requiring a **strict majority of eligible critics** to signal convergence |
| `_usable_stance` (`synthesis_consensus.py:117`, reached from `:174`) | `output.panel_stance` | the stance derived in 1b |

The majority bar is not invented here — ADR-0075 already decided that *"the
moderator's bar is a strict majority of the panel it read."* Reading the digest
instead would let **any one of four** critics saying "converge" flip the whole
panel to `"strong"`, a fail-open widening of a user-visible trust claim by
roughly 4× with no code change. It would also bypass #185's guard: a round with
three live critics and one templated one carries a single round-level
`debate_mode`, so this product's own template words would become eligible for
the keyword scan that guard exists to exclude.

### 1b. `panel_stance` under the peer shape is derived, not absent

`panel_stance` is produced today only from the moderator's structured reply
(`debate.py:628` and `debate.py:701`). With no producer, every peer run would
leave it `None` — and `_usable_stance` reads `None` as "no evidence", collapsing
the entire #354 stance channel to "undetermined" on exactly the runs that have
the most evidence. That is a silent product regression, so: each critic returns
its own `SlotCritique.stance`, and `DebateOutput.panel_stance` is the strict
majority of the live critics' stances, by the same ADR-0075 rule as 1a. No
majority means `None`, which is the existing conservative reading.

### 2. The usage tuple does NOT widen

`DebateResult.live_call_usages` stays `list[tuple[int, TokenUsage | None]]`
(`debate.py:528`). `_call_debate_model` gains a required `model_id` parameter and
stamps *that* onto the record instead of `settings.debate_model_id`
(`debate.py:935`).

This is enough **for `by_stage`**, and reading the pricing loop is what shows it:
`query_run_orchestration.py:2793-2811` iterates the records, prices each at
`debate_usage.model_id or settings.debate_model_id`, and sums into
`debate_by_round[round_number]`. Four critics in round 1 append four records
tagged `1`, each priced at its own model, summing to the correct
`debate_round_1` figure. ADR-0037 predicted exactly this ("without any further
billing-layer change"); this record confirms it against the loop.

**A `model_id` parameter is not on its own sufficient.** Three
`settings.debate_model_id` couplings survive it inside the same forty lines, and
each must move in the same change:

- `debate.py:891` — `if not openrouter_key or not settings.debate_model_id`
  makes peer critique silently not run whenever an unrelated moderator setting
  is blank;
- `debate.py:919` — `response_format=MODERATOR_RESPONSE_FORMAT` asks every
  critic for the moderator's four-slot envelope, which is not `SlotCritique`'s
  shape;
- `debate.py:769` and `debate.py:831` — `parse_moderator_output(author_model_id=settings.debate_model_id)`
  attributes every critic's stance to the moderator.

### 3. Critique spend gets its own `by_model` row — **APPROVED 2026-09-02**

`writer_cost = debate_total + synthesis_cost` (`costs.py:2216`) folds every
debate call into one row whose `model_id` is the literal string `"synthesis"`
and whose label is fixed to `"Debate + synthesis"` (`costs.py:1533` on the
estimate path, `costs.py:2220` on the measured path, `app.js:6519` rendering
both). Under peer critique the four **slot** models earn that spend, so a slot's
money would render under a row named after the writer — the identical defect
ADR-0064 fixed for the Layer-B judge, whose own comment at `costs.py:1534-1537`
says folding it in "would label spend on a THIRD model as synthesis spend".

**Emit one `kind="critique"` row per critic.** Three things this record must
specify, because leaving any of them open makes the row unbuildable:

- **`model_id`** = the critic's model id. This keeps the composite key
  `` `${line.kind || "model"} ${line.model_id || line.display_name}` ``
  (`app.js:4350`) unique — a slot model appears once as `model <id>` and once as
  `critique <id>`. Uniqueness is load-bearing: the pairing resolves with
  `.find()`, first match wins (`app.js:4359`), and the backfill de-duplicates
  with a `Set` of those keys (`app.js:4384`), so two rows sharing a pair would
  render one actual figure twice and the other never, silently under-summing the
  itemized column. It stays unique even when the moderator and a critic are the
  same model, which ships by default.
- **`display_name`** = the catalog short name **plus a critique marker**, e.g.
  `"Claude Haiku 4.5 (critique)"`. `app.js:6519` and `app.js:4364` both use
  `display_name` as the entire visible label, so a bare short name would print
  the same string twice on one receipt with two different figures — a
  user-visible money surface that cannot be read. This is the reason
  "`app.js:6519` needs no change" is true and insufficient.
- **Position: critique rows go LAST**, after the judge row. Slot rows stay at
  indices 0-3 and the writer row at index 4, which `costs.py:1544-1549` records
  as deliberate defence in depth and which `tests/integration/test_cost_gate_js.py:145`
  pins (`labels[4] == "Debate + synthesis"`). This choice knowingly moves
  `tests/unit/test_cost_breakdown.py:129-133`, whose `len(...) == 5` and
  `by_model[-1]` assertions require the writer row to be last, and
  `tests/unit/test_estimate_prices_the_judge.py:207` / `:329`. Those two gates
  pin **opposite** orderings, so one of them must move whatever is chosen; the
  index-4 pin is the one shared with the JavaScript consumer, so it is the one
  kept.

**`build_measured_breakdown` must widen too**, and decision 2 does not cover it.
Its `debate_by_round: dict[int, Decimal]` parameter (`costs.py:2160`) is
round-keyed, so it structurally cannot express a per-critic figure even though
the loop that fills it knew the model. Decision 2's "no widening" is about the
**usage tuple**, not about this boundary.

**Why this needs the product owner.** It changes what a receipt shows: six rows
under a judge-ON production run (four slots, the writer row, the judge) become up
to ten. That is a user-visible money surface, and the owner has been the decider
on this product's money surfaces throughout.

## Owner decision, 2026-09-02

Decision 3 is **approved as written**: one `kind="critique"` row per critic,
`model_id` = the critic's model id, `display_name` carrying a critique marker,
critique rows LAST. Two further decisions were taken at the same time.

**The question that settled it.** The owner's framing was that peer critique
changes who does the work — a debate that used to be one moderator becomes four
models actually debating — so the spend should sit with the models that earn it.
That is decision 3. But it admits two spellings, and the choice is not
cosmetic:

| | Receipt | Critique cost isolable? |
|---|---|---|
| **A — separate `critique` rows** (chosen) | 6 rows → up to 10 | **yes** |
| B — fold critique into each model's existing row | stays 6 | **no** |

B satisfies "the spend goes to the models" and still loses the thing that
matters, because `docs/65-open-work.md` freezes **W3** until *"#290 is built and
its cost is measured"*. Under B a critique's cost is summed into the same figure
as its answer and can never be separated from the receipt, so W3 could not be
unblocked by the very feature it waits on. B is also a one-way door: once merged
into one number the split is unrecoverable without new telemetry. **A was chosen
for that reason, not for the display.**

Worth stating plainly: this fixes a NUMBER, not a label. Today
`_actual_cost` prices every debate call at `settings.debate_model_id`, so under
peer critique four different models would be charged at one model's rate while
the receipt still says `measured`.

### 4. The writer row is renamed `Synthesis`

Under peer critique the debate half moves to the four slot models and only
synthesis remains with the writer. §Consequences already states the sharper
version: **under a fully-eligible peer run that row holds NO debate spend at
all**, because no moderator call is made — so the name does not merely drift,
it becomes false. That section logged the rename as deferred "to decision 3's
owner review"; this is that review, and it is now decided. It moves with
decision 3, in the same change, because the two touch the same two sites
(`costs.py:1533`, `costs.py:2220`) and the same `app.js:6519` ternary.

The #16 relabel is the precedent in the opposite direction: "Synthesis writer"
was renamed BECAUSE it hid what the row contained. Keeping
`"Debate + synthesis"` on a row with no debate in it repeats that defect
mirrored.

### 5. The telemetry record gains a correlator, IN THE SAME WORK PACKAGE

`TELEMETRY_FIELD_NAMES` (`telemetry_sink.py`) has **no** `query_run_id`, `stage`,
`round`, `slot_number`, `finish_reason` or elapsed field — each verified absent
by `grep`, zero hits. Two consequences, both measured against the shipped list
rather than assumed:

- a telemetry row **cannot be joined to a receipt**, and round 1 cannot be told
  from round 2. The only grouping available is file order plus `model_id`, which
  is guesswork and breaks whenever two runs overlap.
- peer critique makes this materially worse: **8 critique calls per run** instead
  of one, from four models that also appear as answerers, all unattributable.

So `query_run_id` plus a `stage`/`round` field ships **with** #290, not after it.
Without it, "cost per model per phase" and "is a critic using its 2000-token
budget" are answerable and "per-model per-round" is not.

**Candidates recorded, not decided**, with the reason each is worth the field:

- **`finish_reason`** — the #290 probe measured **seven of eight** calls
  returning `"length"`, i.e. the 2000-token cap genuinely reached and the reply
  clipped. That is a QUALITY signal no cost row can carry: full price for a
  truncated critique, on a receipt that looks healthy. (Distinct from the *other*
  seven-of-eight in `docs/analysis/2026-08-26-b3-timeout-probe.md:87`, which
  counts wall-clock timeout exceedance. Two different measurements that happen to
  share a ratio — do not merge them.)
- **per-call elapsed time** — `stream_terminator` and `stream_frames` exist,
  elapsed does not. One debate call becomes eight; without timing the tail model
  is invisible.
- **eligibility outcome** — decision 1 gates critique on "completed *and*
  actually invoked". Record WHY a slot did not critique, or "3 critiques, not 4"
  is unexplainable afterwards.

### What is NOT decided

The build is **not scheduled**. #290 stays open and W2 stays PENDING because it
is unbuilt. No critique call has ever run, so every per-model number this design
would expose is **UNVERIFIED**; the first live run after #290 ships is what
produces them, and that same run is what unblocks W3.

The correlator in decision 5 is a **recommendation inferred from the absent
field list**, not a measured requirement. The `finish_reason` and timeout ratios
above are measured.

## Rejected alternatives

**One row per `(round, model)` in `debate_outputs`.** This is the shape the
issue's design notes explicitly warn against, and the warning understates the
damage. The issue names one consumer; there are five renderers, and only one of
them fails silently:

| `app.js` | consumer | what 8 rows for a 2-round run does |
|---|---|---|
| 1829 | `new Map(debate.map((r) => [r.round_number, r]))` | keys collide — silently keeps the **last** critic per round |
| 3139 | Markdown export loop | four identical `### Round 1` headings |
| 4543 | `renderResultDebate` | four identically-captioned cards per round |
| 4816 | `` `${debate.length} round${…}` `` | a 2-round run reads **"8 rounds"** |
| 5458 | `renderDebateAndSynthesis` | eight cards; `data-round` clamps to 1-4, colours repeat |

Rejected. Nesting costs one optional field and one discriminator; flattening
costs five consumers and one outright false statement to the user.

**An unbounded, unsanitised `critique_text` digest.** This is what the first
draft of this record proposed, and it is rejected on measurement: it falsifies
`SYNTHESIS_DEBATE_EXCERPT_MAX_CHARS`' stated derivation, drops roughly three of
four paid critics out of synthesis with no banner, hands `_debate_signals_convergence`
a 4× fail-open path to `"strong"`, and widens the `- Slot N —` row-forgery
surface at `debate.py:997` fourfold. Decisions 1a and 1b are what replace it.

**Widen the tuple to `(round, model_id, usage)`.** Rejected as unnecessary for
pricing, on top of ADR-0037's blast-radius reason. ADR-0037 measured 13 files and
101 matching lines on 2026-08-14; re-derived at `bc1f1a1` the same two commands
give **14 files and 103 matching lines**, of which 50 contain `assert`. The
pricing loop already reads the model from the record; a third tuple element
would be a second, redundant source for the same fact — and two sources for one
fact is how they disagree.

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
mid-sentence and the truncation propagated into synthesis (`debate.py:55-67`).
Streaming (ADR-0084) removed the reason to consider it.

## Consequences

- **Nothing here is built.** No source file changes shape as a result of this
  record. The one code change shipping alongside it is a comment correction, in
  `providers.py`, described below.
- **The next step is human-gated, and it is not another latency probe.** The
  critique-latency question the issue posed was answered on 2026-08-26 and acted
  on by W1. What is required before peer critique is built is the
  **owner-authorised live-execution measurement window** that the board says
  turns W1 from `"tested"` into `"measured"` — `docs/65-open-work.md:651-655`
  states this is the step between W1 and W2, not an optional follow-up.
  Decision 3 additionally needs the owner's sign-off in its own right, because
  it changes a receipt.
- **W3 (the money constants) stays deferred and stays STOP.** ADR-0081's
  decision is about four *constants* — `SOFT_THRESHOLD_USD`, `HARD_LIMIT_USD`,
  `DAILY_CAP_USD`, `GLOBAL_DAILY_CEILING_USD` — and its condition, "#290 is
  built and its cost is measured", is not met by this record and is not moved by
  it. ADR-0081 says nothing about the receipt's row composition; decision 3's
  need for the owner rests on it being a money surface, not on ADR-0081.
- **Decision 1 moves `openapi.yaml`, which is generated and byte-compared.**
  `DebateOutput` is a published schema (`openapi.yaml:585`); adding
  `critique_shape` and `slot_critiques` adds two properties plus a
  `SlotCritique` component. That requires `make openapi-export` and moves
  `make openapi-check` and the **blocking** `Schemathesis API contract` merge
  context. The first draft called the change "one optional field and one
  discriminator" and did not name this.
- **Decision 3 moves a blocking visual lane.** `e2e/fixtures/golden-run.ts`'s
  `BY_MODEL` feeds `goldenCompletedResp()`, which `visual-snapshots.spec.ts`
  screenshots full-page. Per rule 13d the fixture must not be grown in place;
  the critique rows need a dedicated builder.
- **A cancel's un-billing contract is per-round for COUNTS, and a stronger
  monotone invariant is still available.** With critics dispatched through a
  pool, `should_stop` (`debate.py:898`) un-bills only the critics whose thread
  has not yet reached the check, so a test asserting *how many* critics were
  un-billed inside one round asserts a race. What is NOT a race, and what the
  build should assert instead: **no critic is dispatched after `should_stop()`
  first returns `True`** — deterministic if the fan-out checks `should_stop` in
  the submitting thread before each `submit()`, rather than only inside the
  worker as `_call_debate_model` does today.
- **Guard the stamp by cardinality, not by outcome.** `_actual_cost`'s
  `or settings.debate_model_id` fallback makes a *dropped* stamp
  indistinguishable from a *correct moderator* stamp. Under the peer shape, assert
  that the number of stamped debate usage records equals the number of critique
  calls dispatched (rule 6b), not merely that the run was billed.
- **`providers.py:333-334` (pre-diff numbering) is corrected in the same pull
  request.** It said the stamp is applied by "callers that know the model
  (`debate.py`, `synthesis.py`)". `synthesis.py` does not stamp it and never
  constructs a `TokenUsage`; verified by
  `grep -rn 'update={"model_id"' src/product_app/` (one hit, `debate.py:935`)
  and `grep -n "TokenUsage(" src/product_app/synthesis.py` (no output). No live
  defect — synthesis prices unconditionally at `settings.synthesis_model_id`
  (`query_run_orchestration.py:2816`) — but the sentence is false as written.
- **The moderator overlapping slot 2 is unchanged and stays reported, not
  refused.** `settings.debate_model_id` defaults to `anthropic/claude-haiku-4.5`
  (`config.py:544`), which is `DEFAULT_MODEL_IDS[1]` (`model_slots.py:69`), and
  production reports it (`/status.moderator_slot_overlap` is `[2]`). ADR-0086
  decided that posture; decision 3's `kind="critique"` row keeps the composite
  key unique even when the moderator and a critic are the same model.
- **Under a fully-eligible peer run the `"Debate + synthesis"` row holds no
  debate spend**, because no moderator call is made. The #16 relabel exists
  because the old "Synthesis writer" name hid what the row contained; this is
  the mirror image. **DECIDED 2026-09-02** — the owner approved the rename to
  `Synthesis`; see decision 4 under "Owner decision".

## References

- Issue #290 (peer critique), and its 2026-08-26 measurement comment
- ADR-0032 — the copy-vs-mechanism correction that split #290 out
- ADR-0037 — the billing prerequisite, already merged
- ADR-0064 — why the judge is not folded into the writer row
- ADR-0075 — a strict majority is this product's bar for a panel-level reading
- ADR-0078, ADR-0084 — the call-time budget and streaming
- ADR-0081 — the money constants wait for a measured #290
- ADR-0086 — the moderator grading its own answer is reported, not refused
- `docs/analysis/2026-09-01-290-peer-critique-failure-modes.md` — the rule-16e
  enumeration this record is designed against, with every command and output
- `docs/65-open-work.md` rows W1, W2, W3
