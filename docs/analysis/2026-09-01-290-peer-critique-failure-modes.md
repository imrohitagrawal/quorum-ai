# Rule 16e: failure modes of #290's billing change, listed before any is written

**Date:** 2026-09-01. **Scope:** the money surface of peer critique (#290) only —
`DebateResult.live_call_usages`, the `Debate + synthesis` row at its two sites, and
what renders them. Written before any design, per AGENTS.md rule 16e. Nothing in
this document is implemented.

Every claim below names the command that produced it. Line numbers are against
`bc1f1a1965b15af8fbcf2eff26772899eab0d2c8` (`origin/main` at the time of writing).

## 0. Two premises this work started from turned out to be stale

Recorded first, per rule 3, rather than repaired silently.

**(a) The billing prerequisite is already built and merged.** ADR-0037
(`docs/adr/0037-debate-usage-prices-by-actual-model-timeout-unchanged.md`,
accepted 2026-08-14, commit `74063b2`) added `TokenUsage.model_id` and made
`_actual_cost` price each debate record from it.

```
$ git log --oneline -S "Issue #290: stamp the model actually dispatched" -- src/product_app/debate.py
74063b2 fix(debate): price debate usage by the model actually billed, not the moderator rate (#290)
```

`src/product_app/query_run_orchestration.py:2808` reads
`model_id=debate_usage.model_id or settings.debate_model_id`, and
`src/product_app/debate.py:935` stamps it. So "the measured-cost path prices every
debate call on `settings.debate_model_id`" — the issue's own framing — is no longer
true of `by_stage`.

**(b) The timeout risk is measured, and its verdict has since been acted on.** The
single paid probe the issue calls for was run on 2026-08-26 (8 calls, $0.034170,
recorded in the issue's own comment). It found the worst per-`recv` gap at
**25.055 s** on `openai/gpt-4o-mini` against `openrouter_timeout_seconds = 8.0`,
and concluded peer critique could not be built against the non-streaming call
path. Board row **W1** then streamed the provider call (ADR-0084, accepted
2026-08-30); `src/product_app/providers.py:1259` sends `"stream": True`
unconditionally, and `openrouter_call_budget_seconds = 60.0`
(`src/product_app/config.py:110`) is now a cumulative bound.

```
$ grep -n '"stream": True' src/product_app/providers.py
1259:            "stream": True,
```

What is **still** unsettled is not the probe but the observation: `docs/65-open-work.md`
records W1 as *"latent-correct, not observed"* — with `OPENROUTER_LIVE_EXECUTION_ENABLED`
false, nothing exercises the streamed path in production. That owner-authorised
measurement window, not another latency probe, is the human-gated step between W1
and W2.

## 1. Back-compat: usage records that predate the field

**What happens today.** `DebateResult.live_call_usages` is
`list[tuple[int, TokenUsage | None]]` (`src/product_app/debate.py:528`) and is
handed to the repository verbatim:

```
$ grep -n "debate_call_usages" src/product_app/query_run_orchestration.py
471:    debate_call_usages: list[tuple[int, TokenUsage | None]] = field(default_factory=list)
529:    debate_call_usages: tuple[tuple[int, TokenUsage | None], ...]
799:                query_run.debate_call_usages = live_call_usages
868:                debate_call_usages=tuple(query_run.debate_call_usages),
2793:        for round_number, debate_usage in snapshot.debate_call_usages:
```

**Finding: there is no deserialiser to break.** `record_debate_outputs`
(`query_run_orchestration.py:788-804`) assigns the in-process list onto an
in-memory `QueryRun` under a lock; `billing_snapshot` (line 868) copies it into a
frozen tuple. Nothing writes these records to SQLite or JSON and reads them back.
Verified by absence *and* by a positive partner — the durable stores hold
different things:

```
$ grep -rn "debate_call_usages\|live_call_usages" src/product_app/feedback_store.py src/product_app/run_history_store.py
(no output)
$ grep -c "CREATE TABLE" src/product_app/run_history_store.py
1
```

So "an in-flight run's existing usage records that predate the field" is a
**non-case for the process**: a record and the code that reads it are always from
the same process image. The only surviving back-compat surface is the field's own
default — `TokenUsage.model_id: str | None = None` (`providers.py:335`) — and
`_actual_cost`'s `or settings.debate_model_id` fallback, which ADR-0037 chose
precisely so an unstamped record prices exactly as it did before.

**The residual risk is the opposite one, and it is real.** The fallback makes a
*missing* stamp indistinguishable from a *correct* moderator stamp. Under peer
critique a critic whose stamp was dropped by a future refactor would price
silently at the moderator's rate while the receipt still said `measured` — the
exact defect ADR-0037 fixed, re-entering through the fallback. The mitigation is a
cardinality assertion (rule 6b): under the peer shape, assert that the number of
debate usage records carrying a stamp equals the number of critique calls
dispatched, not merely that the run was billed.

**A verified inaccuracy in ADR-0037's own artefact.** `providers.py:333-334` says
the stamp is applied by *"callers that know the model (`debate.py`,
`synthesis.py`)"*. `synthesis.py` does not stamp it, and never constructs a
`TokenUsage` at all:

```
$ grep -rn 'update={"model_id"' src/product_app/
src/product_app/debate.py:935:                result, usage=result.usage.model_copy(update={"model_id": settings.debate_model_id})
$ grep -n "TokenUsage(" src/product_app/synthesis.py
(no output)
```

No live defect — synthesis prices unconditionally at `settings.synthesis_model_id`
(`query_run_orchestration.py:2818`) and there is one synthesis model — but the
sentence is false as written and is corrected in the same pull request as this
document.

## 2. Cancellation: billing partial critiques

**What `_call_debate_model` guards today.** Three guards, in order
(`src/product_app/debate.py:889-899`): the live-execution flag; a missing key or
empty `debate_model_id`; then

```python
if should_stop is not None and should_stop():
    return None
```

checked **before** `provider_execution_service.call_with_prompt`. A `None` return
appends no usage entry — `run_debate_rounds` appends only inside the truthy
branch (`debate.py:610` for round 1, `debate.py:683` for round 2). So an
undispatched round is un-billed today, exactly as the issue describes.

**Finding: the guard survives a fan-out only if the fan-out re-enters this seam
per critic, and even then it un-bills strictly less than the issue claims.** The
issue says `should_stop` "un-bills up to three undispatched critics on a cancel".
That is true only for a *sequential* fan-out. `synthesis.py` — the pattern the
issue asks peer critique to mirror — dispatches through a shared module-level
pool:

```
$ grep -n "ThreadPoolExecutor(max_workers" src/product_app/synthesis.py
1424:_synthesis_section_pool = ThreadPoolExecutor(max_workers=20, thread_name_prefix="synthesis-section")
```

With `max_workers=20` and at most 4 critics, every critic starts essentially at
once, each re-checking `should_stop` in its own thread (synthesis does the same at
`synthesis.py:1189`). A cancel landing after submission therefore un-bills only
the critics whose thread has not yet reached the check — in practice **zero to
three, and most often zero**, not "up to three". The un-billing guarantee that
does survive is the one already stated in `_call_debate_model`'s docstring: round
1's in-flight calls cannot be un-billed, only a round not yet dispatched.

**Design consequence.** The honest contract for peer critique is per-round, not
per-critic: a cancel between rounds un-bills the whole of the next round's fan-out;
a cancel *within* a round un-bills an unpredictable subset. Any test asserting a
count of un-billed critics inside one round is asserting a race, and would be a
flaky test dressed as a billing guarantee.

## 3. Duplicate model ids

**The issue's framing is refuted for slots.** Two slots cannot hold the same
model id:

```
$ sed -n '378,386p' src/product_app/model_slots.py
        if model_id in seen:
            errors.append(
                ModelSlotError(
                    slot_number=index,
                    model_id=model_id,
                    message="Model IDs must be unique across all four slots.",
                ),
            )
            continue
```

**The genuine duplicate is moderator-versus-slot, and it ships by default.**
`settings.debate_model_id = "anthropic/claude-haiku-4.5"` (`config.py:544`) is
byte-identical to `DEFAULT_MODEL_IDS[1]` (`model_slots.py:69`). The repository
already knows this — `moderator_overlap_slots` / `default_moderator_overlap_slots`
(`model_slots.py:270-300`) report it, and ADR-0086 decided it is *reported, not
refused*.

**Where it would bite the receipt.** The result view pairs each estimate row to
its actual row on a composite key (`app.js:4350`):

```javascript
const modelLineKey = (line) =>
  `${line.kind || "model"} ${line.model_id || line.display_name}`;
```

and looks the partner up with `actualByModel.find(...)` (`app.js:4359`), which
returns the **first** match, while the backfill guard is a `Set` of those keys
(`app.js:4384`). Two rows sharing a `(kind, model_id)` pair therefore collapse:
one actual figure renders twice and the other never renders at all, silently
under-summing the itemized column. Today that is unreachable because slot ids are
unique and the moderator has no row of its own. **Any per-critic breakdown must
keep `(kind, model_id)` unique across `by_model`**, which a `kind="critique"` row
per critic satisfies (a slot model then appears once as `model <id>` and once as
`critique <id>` — distinct keys) and a second `kind="model"` row per critic would
not. This is the constraint, and it is load-bearing.

The per-slot estimate array is keyed by **position**, not id (`app.js:245-258`),
and filters `kind === "model"` (`app.js:6877`), so it is already immune.

## 4. UI rendering: pooled versus per-model

**The cost surface can render only a pooled row today.** `by_model` carries a
fixed `"Debate + synthesis"` label for `kind === "synthesis"`:

```
$ grep -n "Debate + synthesis" src/product_app/costs.py src/product_app/static/app.js
src/product_app/costs.py:1533:        raw_model.append(("synthesis", "synthesis", "Debate + synthesis", inner_call_cost))
src/product_app/costs.py:2220:    raw_model.append(("synthesis", "Debate + synthesis", writer_cost, "synthesis"))
src/product_app/static/app.js:6519:        label: row.kind === "synthesis" ? "Debate + synthesis" : row.display_name,
```

Both sites verified independently: `costs.py:1533` sits in
`CostEstimationService._estimate_breakdown` (def at line 1375) and `costs.py:2220`
in `build_measured_breakdown` (def at line 2157) — the estimate and the measured
path, as the brief stated.

**Finding: the pooled row is a live mislabelling risk the moment critique spend
exists.** `writer_cost = debate_total + synthesis_cost` (`costs.py:2216`) folds
every debate call into a row whose `model_id` is the literal string `"synthesis"`.
Under peer critique the four *slot* models earn that spend, so a slot's money would
render under a row named after the writer — the identical defect ADR-0064 fixed for
the Layer-B judge, whose own comment at `costs.py:1534-1537` says folding it in
"would label spend on a THIRD model as synthesis spend". The `by_stage` partition
is unaffected: `debate_by_round` already sums per-model-priced records into
`debate_round_1` / `debate_round_2` (`query_run_orchestration.py:2793-2811`).

**`app.js:6519` needs no change to render a new kind.** The ternary is
`kind === "synthesis" ? fixed label : row.display_name`, so any other `kind` falls
through to the server-supplied display name. A `kind="critique"` row renders today.
Confirmed by reading the expression; **UNVERIFIED by execution** — settling it
needs the cost-gate integration test extended with a critique row
(`tests/integration/test_cost_gate_js.py:142-145` pins the current five labels).

**The debate *narrative* surface cannot take a per-(round, model) list at all, and
the damage is wider than the issue states.** Five consumers read `debate_outputs`,
each assuming one element per round:

| `app.js` | consumer | what one row per (round, model) does |
|---|---|---|
| 1829 | `new Map(debate.map((r) => [r.round_number, r]))` | keys collide — silently keeps the **last** critic per round |
| 3139 | Markdown export loop | emits four identical `### Round 1` headings |
| 4543 | `renderResultDebate` | four cards per round, all captioned the same |
| 4816 | `` `${debate.length} round${…}` `` | a 2-round run reads **"8 rounds"** |
| 5458-5470 | `renderDebateAndSynthesis` | eight cards; `data-round` clamps to 1-4 so colours repeat |

Only the first fails silently. The other four visibly misreport, and 4816 is an
honesty defect of the same class the product exists to remove.

## Summary of what each class demands of the design

1. **Back-compat** — no persistence to migrate; the risk is the `or` fallback
   masking a dropped stamp. Answer with a cardinality assertion, not a clean-path
   test.
2. **Cancellation** — the un-billing contract is per-round. Do not promise or test
   a per-critic count inside a round.
3. **Duplicate ids** — impossible across slots, real for moderator-versus-slot.
   `(kind, model_id)` must stay unique across `by_model`.
4. **UI** — the debate narrative must stay one element per round (the peer detail
   nests inside it); the cost breakdown must not fold slot-model critique spend
   into the writer row.
