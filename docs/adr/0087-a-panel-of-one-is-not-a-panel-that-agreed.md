# ADR-0087: A panel of one is not a panel that agreed

## Status

Accepted — 2026-09-01

Extends **ADR-0083** ("Consensus strength requires a genuine mutual cluster, and
a panel of one has none") to `panel_agreement()`, the sibling function whose
identical defect ADR-0083 recorded in its closing caveat and filed as a
follow-up. Board row **W20**, GitHub issue **#394**.

## Context

`panel_agreement()` (`src/product_app/synthesis_consensus.py`) decided the
served `agreement.panel_agreement` field with one line:

```python
stance = _usable_stance(initial_answers, debate_outputs)
if stance is None:
    return "undetermined"
return "agreed" if len(set(stance.values())) == 1 else "split"
```

`len(set(...)) == 1` is trivially true whenever the stance dict holds ONE entry.
A genuine one-answer panel therefore read `"agreed"` — a positive claim that a
panel agreed, drawn from a reading with nothing to disagree with.

This is the identical structural pattern ADR-0083 closed in
`compute_consensus_strength` for #383, and ADR-0083 said so in its own
"Rejected: a fourth `ConsensusStrength` literal for N=1" section:

> **Caveat found by a later review round, 2026-08-29: `panel_agreement()` (a
> sibling function, untouched by this ADR) has the identical structural
> pattern** … Left unfixed here — it is a different function serving a different
> field … Filed as a follow-up rather than expanded into this PR.

This ADR is that follow-up.

### It is reachable today, not only once W4 ships

Measured on `ee27c19` before the fix, with a probe built from the shipped
four-slot panel — three slots `FAILED`, one `COMPLETED`, one live moderator
round scoring all four slots:

| Measurement | Value |
|---|---|
| `[a.slot_number for a in answers if counts_as_evidence(a)]` | `[1]` |
| `_usable_stance(answers, debates)` | `{1: 'nrr'}` |
| `panel_agreement(answers, debates)` | **`agreed`** ← the defect |
| `compute_consensus_strength(answers, debates)` | `weak` (already correct, ADR-0083) |

Through the real production entry point, on a clean `git archive origin/main`
copy:

```
answering_slots=1: panel_agreement=agreed aligned=1 total=4
answering_slots=4: panel_agreement=agreed aligned=4 total=4
```

No flag, no spend, no unreleased feature: `counts_as_evidence` excludes a
`FAILED` slot, so any run that loses three of its four slots has a one-slot
scored population. Variable panel size (board row **W4**, N ∈ {2,3,4}) would
widen the exposure; it is not what creates it.

### The user-visible surface was already blocked, and that is not the point

Re-verified by execution rather than inherited from the board's note:

| Panel | `consensus_strength` | `_is_false_consensus_preserved` | `isConsensusResult` conjunct `false_consensus_preserved === false` |
|---|---|---|---|
| N=1 degraded | `weak` | `True` | **BLOCKS** |
| N=2 control | `strong` | `False` | passes |

`isConsensusResult` (`app.js`) requires `panelAgreement === "agreed"` **and**
`fs.quality_checks.false_consensus_preserved === false` as separate conjuncts,
and the degraded run measured above also fails `aligned === total` (1 ≠ 4) —
though that second block is a property of THAT shape, not of every one-slot run,
so the `false_consensus_preserved` conjunct is the one doing the work. The green
"unanimous panel" banner was never reachable for this shape.

What was wrong is the value this product **serves**. `agreement.panel_agreement`
crosses the API boundary (it is in the OpenAPI schema and in the JSON every
client reads), and a second, independent conjunct further downstream is not a
reason to serve a false claim on the first. The `#:` doc-comment on
`PanelAgreement` (`debate.py:185-190` — a `Literal` alias cannot carry a
docstring) says `"agreed"` "is a CLAIM and needs positive evidence"; one scored
slot is not positive evidence about a panel.

## Decision

**A usable reading that covers fewer than two models returns `"undetermined"`.**

```python
stance = _usable_stance(initial_answers, debate_outputs)
if stance is None:
    return "undetermined"
if len(stance) < 2:
    return "undetermined"
return "agreed" if len(set(stance.values())) == 1 else "split"
```

Three choices inside that, each defended:

**1. The value is `"undetermined"`, not a fourth literal and not `"split"`.**
`PanelAgreement = Literal["agreed", "split", "undetermined"]` is unchanged, and
`PANEL_AGREEMENTS` with it — `debate.py`'s own comment records that a fourth
value reaching the browser would fall through `isConsensusResult`'s
`=== "agreed"` test silently, and
`test_the_panel_agreement_values_are_a_closed_set` pins the set. `"undetermined"`
is already documented as "never a claim about the panel; only a statement about
what we know", which is exactly what a one-slot reading is. It is also the value
every consumer already handles routinely — it is the default on
`AgreementSummary`, the value for every run without a live moderator, and what
the fault-injection lane asserts — so no consumer meets a value it has never
seen. `"split"` was rejected outright: it is the opposite false claim, asserting
a disagreement nobody observed. This mirrors ADR-0083's identical call for
`ConsensusStrength`, where `"weak"` was the existing catch-all for thin signal.

**2. The population is the STANCE, not the answer list.** `_scored_slot_numbers`
returns a SET of slot numbers while `initial_answers` is a LIST, so two
`COMPLETED` answers sharing a `slot_number` are two answers and one panel
member. Guarding on `len(initial_answers)` or on the completed-answer count
leaves that shape reporting `"agreed"`; both were written as mutants and both
were killed by `test_two_answers_sharing_one_slot_number_are_still_one_scored_slot`
(see the mutation table below).

**3. One guard is enough here, unlike ADR-0083.** `compute_consensus_strength`
needed a CENTRAL `len(completed) == 1` guard plus a stance residual, because
review found a second route to `"strong"` — `_debate_signals_convergence`, with
no population gate at all — that the stance-only guard did not cover.
`panel_agreement` has a single branch: it consults `_usable_stance` and nothing
else, and every path to a verdict runs through the returned dict. There is no
second route for the guard to miss.

**The bound is `< 2` rather than `== 1`.** They are behaviourally identical
today: `_usable_stance` returns `None` when nothing is scored and otherwise
returns a mapping covering every scored slot, so an empty stance is unreachable
(verified — a panel with four `FAILED` slots gives `_usable_stance` → `None`,
`panel_agreement` → `"undetermined"`). The inequality states the bound the
docstring means and stays correct if that ever changes. It also keeps the
board's evidence needle distinct from ADR-0083's `if len(stance) == 1:`, which
already exists in the same file — an `ABSENT` pin on that string would have read
`DONE` before this change was written.

### N ≥ 2 is untouched, and that is pinned

Two models the moderator placed in one group IS a panel agreeing: there was
something to disagree with and the moderator positively said they did not. The
guard stops at one. `tests/unit/test_panel_agreement_needs_a_panel.py`
parametrises both verdicts over the panel sizes the product ships — N=2, 3 and 4
for `"agreed"` and for `"split"` — so widening the guard to `< 3` fails rather
than being carried along (AGENTS rule 7a: the parametrisation is over panel
sizes, not over the constant `2` the guard tests).

### Bite proof

Baseline green (11 passed) before each mutation; each mutant applied with a
uniqueness-checked anchor, the file restored from a `cp` copy and confirmed with
`diff -q` (never `git checkout`).

| Mutant | Result | Killed by |
|---|---|---|
| Delete the guard entirely | 4 failed | reproduction, both one-slot shapes, the wire |
| `len(stance) < 2` → `< 1` | 4 failed | same |
| `len(stance) < 2` → `< 3` | 2 failed | both N=2 positive partners |
| Guard `len(initial_answers) < 2` instead | 4 failed | reproduction, both one-slot shapes, the wire |
| Guard the completed-ANSWER count instead | 1 failed | the duplicate-slot test, exactly as its docstring predicts |
| Delete the pre-existing `stance is None` guard | 1 failed (`TypeError`) | `test_no_usable_reading_is_still_undetermined_for_its_own_reason` |
| Guard returns `"split"` instead of `"undetermined"` | 4 failed | reproduction, both one-slot shapes, the wire |
| Hardcode `panel_agreement="agreed"` in `build_agreement_and_positions` | 1 failed | the WIRE test |

8 of 8 killed. Two independent reviewers re-ran all eight in their own
`git archive` copies and reproduced every row's failure count exactly.

**Run mutants with `PYTHONDONTWRITEBYTECODE=1`, and this is why.** Measured here
on 2026-09-01, at a cost of one wasted `make quality`: a mutant that only
REORDERS lines (the guard moved below the `return`) leaves the file's byte size
unchanged, and `cp`-restoring it within the same one-second mtime bucket
produces a `.pyc` whose recorded `(mtime, size)` header still matches the
restored source. CPython then treats the cache as valid and keeps executing the
MUTATED bytecode. The next full run reported 4 failures in
`test_panel_agreement_needs_a_panel.py` while `grep` showed the guard correctly
in place and the imported `__file__` was the right one — the check from AGENTS
rule 16b passes and still tells you nothing. Proved rather than guessed:

```
pyc records source mtime=1788232519 size=53444
actual source mtime=1788232519 size=53444
STALE-BUT-CONSIDERED-VALID: True
```

Clearing `__pycache__` restored `11 passed`. The reviewers, who were instructed
to set `PYTHONDONTWRITEBYTECODE=1`, never saw it.

## Rejected alternatives

**Leave it unfixed because the banner is already blocked.** This was the board's
own recorded position ("Confirmed zero live impact"), and it is a reason not to
call it urgent, not a reason to serve a false field. Two independent conjuncts
guarding one surface is defence in depth; treating one of them as licence to
leave the other wrong spends that depth. The field is public API, and W4
(variable panel size) would put more runs through the degenerate shape.

**Fix it inside `_usable_stance` — return `None` for a one-slot reading.** This
would fix `panel_agreement` and `compute_consensus_strength` and
`classify_model_alignment` in one line, which is exactly why it was rejected:
`_usable_stance` answers "is there a usable reading?", and there IS one — a
moderator read the answer and reported where it stands. Collapsing "a reading of
one model" into "no reading at all" would throw that reading away for every
consumer, including `classify_model_alignment`, whose per-slot alignment is
still meaningful at N=1 (measured: the one-slot run reports `aligned=1, total=4`,
unchanged by this fix). The degeneracy is in the *panel-level* claim, so the
guard belongs at the panel-level claim.

**Generalise a `_required_panel(n)` bound the way `_required_cluster` does.**
There is nothing to generalise. `"agreed"` means one position group, at any
size ≥ 2; the only special case is that a group of one is not a group of anyone
agreeing. ADR-0075 and ADR-0083 both warn against transplanting the stance bar's
formula onto a different question, and this is a different question.

## Consequences

- **The only verdict that moves is a one-slot stance population**: `"agreed"` →
  `"undetermined"`. Every N ≥ 2 verdict is byte-identical, pinned at N=2, 3 and 4
  in both directions. The full suite is **3498 passed, 59 skipped, 1
  deselected** with the fix, measured in the branch worktree after
  `uv sync --all-extras --python 3.12`:

  ```
  uv run --python 3.12 python -m pytest tests/unit tests/integration \
    tests/contract tests/resilience -q --no-cov -p no:randomly --deselect \
    tests/unit/test_provider_call_time_budget.py::test_the_budget_covers_the_header_phase_not_only_the_body
  ```

  The deselect is named in full on purpose: board row W19's needle
  (`assert wall < 4.0,`) matches TWO tests in that file, and deselecting the
  other one leaves a red run. W19 was confirmed as pre-existing, not this diff —
  3 of 3 failures isolated on this branch AND 3 of 3 on a clean
  `git archive origin/main` copy. A reviewer running this in a fresh clone
  without a synced `.venv` will see the `make`/`uv` shell-out gate tests fail and
  a skip count of 58 rather than 59; that is the clone, not the diff.
- **No API-schema change.** `PanelAgreement`, `PANEL_AGREEMENTS` and the served
  field's type are untouched; only which of the three existing values a
  degenerate run receives changes. `make openapi-check` is unaffected.
- **The counts are untouched.** `summarize_agreement` takes `panel_agreement` as
  an argument and does not derive the counts from it; measured identical before
  and after — `(aligned, total)` is `(1, 4)` for the one-slot run and `(4, 4)`
  for the four-slot run on both trees.
- **Board row W20's evidence needle was re-pinned.** The open-form needle
  (`PRESENT … :: return "agreed" if len(set(stance.values())) == 1 else "split"`)
  pins a line this fix KEEPS — the guard is a new line added ABOVE it — so the
  row would have stayed `PENDING` forever with the defect closed. That is trap 12
  in `CONTINUE-OPEN-WORK-ULTRACODE-PROMPT.md`, measured on W12/#379, and
  ADR-0083 hit the same thing on W6. Re-pinned to
  `ABSENT … :: if len(stance) < 2:` — verified absent on `origin/main`
  (`grep -c` → 0) and present after.
- **Both N=1 degeneracies this module has FILED are now closed.** #383
  (consensus strength) by ADR-0083; #394 (panel agreement) here. Whoever ships
  W4 inherits both guards rather than re-deriving them. This is not a claim that
  the module has no other degenerate-input behaviour —
  `classify_model_alignment` was not audited for one here, and saying so is
  cheaper than implying a sweep nobody ran.
