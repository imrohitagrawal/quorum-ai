# ADR-0095: Peer critique ships behind a flag, because the fail-safe bound has to move with it

## Status

Accepted — 2026-09-03. Builds ADR-0093's approved shape. Adds ONE decision that
record does not take: the rollout gate, and why it is a money decision rather
than a feature toggle.

## Context

ADR-0093 decided the SHAPE of #290 (peer critique) and was explicit that
"nothing here is built". This is the build. Decisions 1, 1a, 1b, 2, 3, 4 and 5
are implemented as written; nothing in that record is redesigned here.

One thing ADR-0093 did not enumerate turned up while building, and it is the
reason this record exists.

### The defect the build found

`CostEstimationService._estimate_bound_usd` describes itself, in its own
docstring, as a TRUE CEILING:

> this total is a true ceiling on real cost: the guardrail keying off it can
> only ever over-protect, never wave through a run that then bills more.

It prices exactly **two** debate calls, both on `settings.debate_model_id`.
A peer run makes two calls **per eligible critic** — up to eight, on four
*different* models. Turning peer critique on without the bound following makes
that sentence false, and it fails in the UNSAFE direction: a run waved through
under a quoted ceiling it then bills past.

Measured, on this branch, with four slots all on the moderator's own model so
the multiplier is independent of what any model costs:

| `peer_critique_enabled` | `by_stage.debate_round_1` |
|---|---|
| `false` | `$0.0052` |
| `true` | `$0.0207` |

`0.0207 / 0.0052 = 3.98` — one call per slot, as it should be. Before the fix
both columns read `$0.0052`, which is the defect stated as a number.

On the SHIPPED default mix the same change moves the debate line `$0.0052` ->
`$0.0081`, a ratio of **1.56**, because the four default slots are collectively
cheaper than four Haikus. That number is a fact about the price list, not about
this feature — recorded because the first draft of the test asserted `> 2x` on
the default mix and went red against correct code.

### Why that forces a flag

Two things are true at once:

* the bound MUST price the peer shape, or the guardrail under-protects;
* ADR-0094's 715-mix sweep, and the four money constants derived from it, were
  measured against the MODERATOR shape. Raising the bound unconditionally moves
  how many catalog mixes need a confirmation click, before anyone has measured
  what a peer run actually costs.

ADR-0094 resolves that ordering explicitly: the constants "wait for the
feature", and #290's real cost is what unblocks them. A flag is what lets the
feature be built, tested and reviewed now while the money posture waits for the
measurement — instead of the two blocking each other.

## Decision

### 1. `peer_critique_enabled` defaults to `false`, and the bound reads the same flag

`settings.peer_critique_enabled` (`config.py`, `PEER_CRITIQUE_ENABLED` in the
environment) gates the whole peer path. `costs._cost_components` reads the SAME
setting, so the ceiling is true in both postures — never one without the other.

With the flag off, every figure on the estimate, the receipt's row composition
and the debate's dispatch pattern are what shipped. That is asserted, not
assumed: `test_the_shipped_posture_is_byte_identical` and
`test_the_flag_off_leaves_the_moderator_shape_untouched`.

**Turning this on is a MONEY decision.** It raises the quoted bound, which moves
mixes into the confirmation band. It belongs in the same pull request as a
declared live-execution window, alongside the constants ADR-0094 is holding.

### 2. The telemetry `stage` is the receipt's `by_stage` name, verbatim

ADR-0093 decision 5 asks for "`query_run_id` plus a `stage`/`round` field". It
ships as `query_run_id` + `stage` + `slot_number` + `finish_reason`, with **no
separate `round` field**: `debate_round_1` / `debate_round_2` already carry the
round, and two sources for one fact is how they come to disagree — the same
reasoning ADR-0093 used to reject widening the usage tuple.

Because `stage` is the receipt's own string, a telemetry row joins a receipt
line by equality with no derivation.
`test_the_stage_labels_are_exactly_the_receipt_stage_names` DRIVES
`build_measured_breakdown` and compares, rather than retyping the list.

`finish_reason` is a BOUNDED label (`stop`/`length`/`content_filter`/
`tool_calls`/`error`/`other`/`absent`), never the upstream's raw string: the
durable sink writes shapes and enumerations, never content (ADR-0031).

### 3. The correlator is passed explicitly, never through a context variable

Both the synthesis sections and #290's critics dispatch through a
`ThreadPoolExecutor`, which does not propagate `contextvars` to its workers. A
context-variable correlator would silently empty itself on exactly the fan-out
it exists to disentangle.

### 4. The peer round shape is captured INSIDE `BillingSnapshot`

Which rounds ran the peer shape is copied under the same lock as the usage
list. Reading it off the live `query_run` next to the snapshot would re-open, in
a new place, the exact TOCTOU that class exists to close: the shapes and the
usages would be read at different instants, so a run whose rounds were recorded
in the window could price peer usages against a moderator view — the critics'
dollars folded back into the writer row on a receipt still labelled `measured`.

## What ADR-0093 predicted that did NOT happen

ADR-0093 decision 3 says two gates "pin OPPOSITE `by_model` orderings ... one of
them MUST move; say which and why."

**Neither moved.** The conflict does not arise, because **critique rows are
emitted on the MEASURED path only**. The estimate path cannot know which slots
will be eligible, and a row for a call that may not happen is a claim — so the
estimate keeps five rows (six with a judge) and both
`tests/integration/test_cost_gate_js.py:145` (`labels[4]`) and
`tests/unit/test_cost_breakdown.py` (`len == 5`, `by_model[-1]`) still hold.
Both needed their LABEL updated for decision 4's rename; neither needed its
ORDERING changed.

## Consequences

- **The `Synthesis` row understates its contents while the flag is off**, and
  this is knowingly accepted. Decision 4 is owner-approved and unconditional:
  the row is named `Synthesis` in both postures. Under the moderator shape it
  still folds in the two debate rounds, so the name is the #16 defect in
  miniature until peer critique is on. The alternative — a label that changes
  per run — was rejected because `app.js` renders `display_name` as the entire
  visible label and a label that moves between the estimate and the receipt is
  how a money row renders as two unpaired halves.
- **`by_model` and `by_stage` now both carry a line labelled `Synthesis`**, with
  different figures while the flag is off (the `by_model` row folds debate; the
  `by_stage` row does not). Two partitions of one total, under separate
  headings — recorded here so a reader who notices it finds the reason.
- **`EvalJudge.evaluate` gained an optional `query_run_id`.** It is a PARAMETER
  and not a field on `JudgeEvidence`: that dataclass is documented as "the
  untrusted material handed to the judge", and an identifier this product
  generated is neither untrusted nor anything the judge should read.
- **Four internal seams widened** (`_post_messages`, `_post_openrouter`,
  `_live_openrouter_response`, `_call_openrouter_with_optional_search`), so
  several fixed-signature test doubles took a new keyword. `telemetry_labels` is
  forwarded to `_post_messages` only when set, matching the existing rule for
  `response_format`/`reasoning` — measured, not reasoned about: forwarding
  `None` unconditionally turned
  `test_a_non_judge_call_reaches_the_transport_with_an_unchanged_SIGNATURE` red
  while changing no wire payload at all.
- **`openapi.yaml` moved** (+45 lines: two `DebateOutput` properties and a
  `SlotCritique` component), which moves the blocking Schemathesis context.
  Regenerated with `make openapi-export`; `make openapi-check` passes.
- **W3 stays STOP.** Its precondition is unchanged: #290 built AND its cost
  measured. This record ships the first half. The second half needs a declared
  window with the flag ON, and that is the next work package.
- **Two of the tests written for this change were VACUOUS until mutation found
  them**, and both are recorded because the pattern repeats:
  - the row-forgery test used `split("\n")`, which sees only one of the five
    breakers it parametrises over — 4 of 5 parameters passed against an
    implementation with the sanitiser deleted. Fixed to `str.splitlines()`.
  - `_actual_cost`'s critique split had no test at all: every existing test
    called `build_measured_breakdown` with the critique lines already computed,
    so the builder was well covered and its only CALLER was not. Deleting the
    split left the whole suite green.

## Rejected alternatives

**Ship peer critique on, and move the money constants in the same change.**
Rejected: ADR-0094 measured the constants against the moderator shape and says
in as many words that `cost_debate_output_tokens` "would be obsolete the day
#290 ships". Setting a number twice is how a threshold nobody trusts gets made.

**Leave the bound alone and rely on the run deadline.** Rejected on the
docstring: the bound is what the guardrail evaluates, and a ceiling that is not
a ceiling is worse than no ceiling, because it is believed.

**Make the writer row's label depend on the shape.** Rejected — see
Consequences. Decision 4 is owner-approved as an unconditional rename.

**Dispatch the critics through a `ThreadPoolExecutor`.** Rejected for the build,
though the synthesis sections do exactly that. ADR-0093's consequences record
why: with a pool, "no critic is dispatched after the cancel lands" becomes a
race, and the count of un-billed critics stops being assertable. Sequential
dispatch with `should_stop` checked in the SUBMITTING frame makes it
deterministic. The cost is wall-clock latency on a path that is off by default
and, per ADR-0084's streaming figures, bounded per call by
`openrouter_call_budget_seconds`. Revisit with a measurement, not with a guess.

## References

- ADR-0093 — the approved shape this builds
- ADR-0094 — the money constants held until #290's cost is measured
- ADR-0064 — why the judge is not folded into the writer row
- ADR-0075 — a strict majority is this product's bar for a panel-level reading
- ADR-0084 — the streamed provider call peer critique rests on
- ADR-0031 — what the durable telemetry sink may and may not write
- `docs/analysis/2026-09-01-290-peer-critique-failure-modes.md` — the rule-16e
  enumeration the design was built against
