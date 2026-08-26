# ADR-0075: The moderator's bar is a strict majority of the panel it read; the overlap bar is not

## Status

Accepted — 2026-08-26

## Context

`compute_consensus_strength` has two independent routes to "strong", and both
compared against the literal `3`. Verified on `f3ffb72` before any code was
written:

```
$ grep -n "partners >= 2) >= 3\|max(sizes.values()) >= 3" src/product_app/synthesis_consensus.py
322:        if len(sizes) == 1 or max(sizes.values()) >= 3:
425:    return sum(1 for partners in counts if partners >= 2) >= 3
```

`3` is correct only for a four-slot panel, and the function does not score the
panel that was *requested* — it scores the answers that count as evidence. At
`f3ffb72` it opened with:

```
completed = [answer for answer in initial_answers if counts_as_evidence(answer)]
```

**N=3 is reachable in production today**, by two routes, re-derived here rather
than inherited:

```
$ sed -n '1230,1246p' src/product_app/query_run_orchestration.py
1232:  if _budget_remaining() > 0:
1233:      continue          # worker-raised timeout, run budget left
1241:  except Exception:
1243:      continue          # "Future failed unexpectedly; skip and continue"
1246:  query_run_repository.record_initial_answer(query_run_id, answer)
```

Both `continue` past `record_initial_answer`, so that slot contributes no
answer. Second route: a slot recorded `FAILED` is present but filtered out by
`counts_as_evidence`.

(Issue #380 cites these as `:1236`, `:1244` and `:1247`. **All three numbers are
wrong** — 1236 is an argument inside a call, 1244 is the `_should_stop` test,
1247 is blank — and an earlier draft of this ADR repeated them unchecked.
#380's third path, `_should_stop`, does not belong in the list at all: its
`return` at 1245 is inside `_execute_query_run`, which runs synthesis later in
the same function, so that path ends the run rather than reaching synthesis
short a slot.)

At N=3 the literal `3` demands that **all three** agree — unanimity. On the
stance branch that means a moderator which explicitly read two of three models
as holding the same position was reported as "divided".

## Decision

**1. The stance bar is a strict majority of the slots the moderator read.**

```python
def _required_cluster(panel_size: int) -> int:
    return panel_size // 2 + 1
```

| stance N | required | effect |
|---|---|---|
| 2 | 2 | unchanged (a tie is not a majority; a single group already short-circuits) |
| 3 | 2 | **2 of 3** (was: unanimity) |
| 4 | 3 | **unchanged** |

**2. The overlap bar is left exactly as shipped.** `_has_strong_overlap`,
`_overlap_partner_counts`, `_four_grams` and `_excerpt` are byte-identical to
`origin/main` — verified by AST comparison, not by reading:

```
IDENTICAL to main _has_strong_overlap
IDENTICAL to main _overlap_partner_counts
IDENTICAL to main _four_grams
IDENTICAL to main _excerpt
```

**3. The stance bar is scored on `len(stance)`, not `len(completed)`.** They are
different populations: `_scored_slot_numbers` returns a **set** of slot numbers
while `completed` is a **list** of answers, and `slot_number` is
`Field(ge=1, le=4)` — bounded, but not unique. Measured on four completed
answers with three distinct slots: `len(completed) = 4`, `len(stance) = 3`,
giving required 2 (verdict `strong`) rather than required 3 (verdict `divided`).
Pinned by `test_row11_...`; the `len(completed)` mutant survived an earlier
version of the test file until a reviewer demonstrated it was non-equivalent.

## Rejected alternatives

### Applying the same majority rule to the overlap bar — REJECTED on a measured false acceptance

This was the original plan, and it is wrong. The plan's reasoning was that a
majority cluster forces corroboration: every member needs a partner *and* the
cluster must be a majority, so one spurious edge from shared boilerplate cannot
carry the verdict. **That argument does not hold below N=4.** Measured:

```
N=2 -> cluster 2, partners each 1     <- one edge
N=3 -> cluster 2, partners each 1     <- one edge, IDENTICAL to N=2
N=4 -> cluster 3, partners each 2     <- corroboration begins here
```

At N=2 *and* N=3 a "majority cluster" is a single edge. No second text
corroborates anything. And two answers that reach **opposite** conclusions form
that edge out of shared opening boilerplate — they share six 4-grams, Jaccard
`0.4286`:

```
"Based on the available evidence, I would recommend we approve the merger outright."
"Based on the available evidence, I would recommend we reject the merger outright."
"Vitamin D supplementation shows no mortality benefit in the meta-analysis."

partner counts          -> [1, 1, 0]
_has_polar_disagreement -> False        (nothing downstream catches it)
overlap tested before polar -> True
```

The consequence reaches a safety flag. `_is_false_consensus_preserved` is
`consensus_strength in {"weak", "divided"}`, so:

| | consensus_strength | `false_consensus_preserved` |
|---|---|---|
| `origin/main` | `weak` | **True** (safe) |
| majority overlap bar | `strong` | **False** (unsafe) |

A panel saying *approve* and *reject* would be reported as broadly agreeing,
with the false-consensus guard switched off. This is the class of defect #354
exists to prevent, and it is a **regression the change would have introduced** —
`origin/main` does not have it.

This was not caught by the gate set. `make quality` (3690 passed), `make
validate`, `diff-cover` (100% on changed lines), `api-contract`, `openapi-check`
and `security-scan` were **all green** on the rejected design. An adversarial
reviewer found it. That is consistent with
`docs/metrics/defect-discovery-audit.md`: 0 of 16 `src/` defects were caught by
an automated check, 10 of 16 by adversarial review.

It is now pinned the other way — and the first attempt at that pin was itself
too weak, which is worth recording. `test_row7_...` pins one SHAPE, the single
edge `[1, 1, 0]`. A second adversarial pass found a non-equivalent loosening it
misses: moving the DEGREE position from `partners >= 2` to
`partners >= _required_cluster(len(counts)) - 1` left all 13 tests green while
changing the verdict on **7 of the 27** partner-count vectors at panel size 3 —
all False -> True, e.g. the star `[2, 1, 1]`, where the two non-hub answers
share nothing at all.

The general guard is `test_row12_...`, which pins `_has_strong_overlap`'s
decision on **every** reachable partner-count vector at panel sizes 0-5 against
the shipped rule written out in literals. Measured: the degree survivor reddens
it, `partners >= 1` reddens it, and `>= 3` -> `>= 2` reddens it. Changing the
`< 3` floor to `< 2` does NOT redden it, correctly — a sum over two partner
counts cannot reach 3, so that mutant is equivalent (ADR-0069).

### Supporting small panels by raising `_OVERLAP_JACCARD_THRESHOLD` for 2-clusters — REJECTED as unmeasurable

That threshold is a guardrail value. Setting it honestly needs a corpus of real
small panels, which needs live execution, which is off and stays off. Moving it
from a documented-but-unmeasured number is a failure this project has already
recorded.

### Replacing the degree count with a clique test — DEFERRED to #382

`m` texts each having `m-1` partners does not prove one mutual cluster of size
`m`; overlap is symmetric but not transitive. Exhaustively, over every graph:

| N | required | "strong" verdicts | of those, no mutual cluster that big |
|---|---|---|---|
| 4 | 3 | 26 | **3 (11.5%)** |
| 5 | 3 | 793 | **157 (19.8%)** |

The 4-cycle is live today: `A~C, A~D, B~C, B~D` with `A≁B` and `C≁D` gives
every answer 2 partners, so a panel that is really two disjoint pairs reads
"strong". Out of scope here because this change leaves the overlap bar
untouched, so it neither introduces nor worsens it. Filed as **#382**.

### Relaxing the `le=4` slot caps — OUT OF SCOPE

```
$ grep -rn "le=4" src/product_app/
src/product_app/debate.py:209:    slot: int = Field(ge=1, le=4)
src/product_app/debate.py:1268:    slot_number: int = Field(ge=1, le=4)
src/product_app/providers.py:320:    slot_number: int = Field(ge=1, le=4)
```

N>4 is unrepresentable today, so `_required_cluster`'s behaviour above 4 is
latent. Whoever lifts these caps must read #382 first.

## Consequences

- A moderator reading 2-vs-1 on a three-slot panel now yields `strong` rather
  than `divided`. That is the intended change, and it is the only verdict this
  ADR moves.
- **No N=4 verdict moves**, on either branch — which covers every test baseline
  and visual snapshot, all of which render a four-slot fixture.
- The overlap branch is unchanged, so no run that reaches synthesis with a full
  panel, and no run without a live moderator, is affected at all.
- The two branches now deliberately disagree below N=4: the moderator may
  certify a small panel, text overlap may not. That asymmetry is the decision,
  not an oversight — semantic labels are stronger evidence than 4-gram
  similarity.
- The N=1 stance case (`len(sizes) == 1` returns `strong` for a single answer)
  is **left exactly as it was**, and is filed as **#383**.
- `_required_cluster` has exactly one caller. If a second one is ever added,
  read the rejected alternative above first — the helper is safe for semantic
  populations and unsafe for similarity clusters.
