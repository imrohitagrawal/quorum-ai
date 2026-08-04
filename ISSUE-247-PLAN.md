# Issue #247 — plan (Phase 1). Nothing built until this is agreed.

All numbers below are MEASURED on `fix/247-simulated-slots-not-agreement` @ `9981bab`.
Commands and verbatim output are in §5.

---

## 1. The defect, reproduced (RED-proven)

Driven through the real `ProviderExecutionService`, not a hand-written template:

```
slot 1..4 path=local_simulation status=completed
pairwise 4-gram Jaccard   0.500 – 0.579
_OVERLAP_JACCARD_THRESHOLD 0.1
_overlap_partner_counts   [3, 3, 3, 3]
_has_strong_overlap       True
compute_consensus_strength strong
RENDERED                  "4 of 4 models aligned"
```

Reproduces identically on the `fallback_search` path.

---

## 2. A FALSE PREMISE in the handoff prompt — corrected

The prompt (§5.2, §4) and issue #247 both say:

> "`provider_path is LOCAL_SIMULATION` … is not sound as written — `providers.py:546`
> shows that branch can carry `live_response.answer_text`."

**This is false.** `providers.py:546` sits inside the `use_fallback` branch, which
stamps `provider_path=ProviderPath.FALLBACK_SEARCH` (line 559) — not
`LOCAL_SIMULATION`. Across all of `src/`, `provider_path=ProviderPath.LOCAL_SIMULATION`
is assigned in exactly ONE place, `providers.py:573`, whose `answer_text` (line 571)
is unconditionally `self._local_simulation_text(...)` with no live-text arm.

The real hole is the OPPOSITE one, and the prompt misses it: **`FALLBACK_SEARCH` also
emits `_local_simulation_text`** (line 549). A `LOCAL_SIMULATION`-only discriminator
would fix only half the defect. Measured: a fallback-forced demo run also renders
"4 of 4 models aligned".

---

## 3. Input-class table — MEASURED, both directions

`aligned` is the verdict-ring numerator; `strength` is `compute_consensus_strength`.
"after" = a probe that removes not-invoked answers from the scored population.

| # | class | before | after | note |
|---|---|---|---|---|
| 1 | all-simulated (`local_simulation`) | strong, **4 of 4** | 0 of 4 | THE DEFECT |
| 2 | all-simulated (`fallback_search`) | strong, **4 of 4** | 0 of 4 | missed by a path-only-LOCAL_SIMULATION fix |
| 3 | all-live-aligned | strong, 4 of 4 | **strong, 4 of 4** | unchanged — no false negative |
| 4 | all-live-unrelated | weak, 0 of 4 | weak, 0 of 4 | unchanged |
| 5 | 2 live aligned + 2 simulated | weak, **4 of 4** | 2 of 4 | worse than the headline: ring says 4 while strength says weak |
| 6 | 3 live aligned + 1 simulated | strong, 3 of 4 | **strong, 3 of 4** | unchanged — no false negative |
| 7 | 1 live + 3 simulated | **strong, 3 of 4** | 0–1 of 4 | simulation MANUFACTURES the consensus and excludes the one real model |
| 8 | simulated slot carrying live text | strong, 4 of 4 | 3 of 4 | **proved unreachable** — see §4 |
| 9 | zero completed (all failed) | divided, 0 of 4 | divided, 0 of 4 | unchanged |
| 10 | 2 live polar-split + 2 simulated | divided, 0 of 4 | divided, 0 of 4 | unchanged |
| 11 | 3 live aligned + 1 live failed | strong, 3 of 4 | strong, 3 of 4 | unchanged |

Every genuine-agreement class (3, 6, 11) is untouched. Only the simulated-inflation
classes (1, 2, 5, 7) move.

---

## 4. Discriminator decision, with evidence

**Chosen: `provider_path in {LOCAL_SIMULATION, FALLBACK_SEARCH}`, behind ONE shared
predicate.** Not text-matching, not a new API field.

Evidence:

1. **The path is sound**, because the only arm that could put live text under a
   non-live path is dead. Proved by execution, not by reading the comment that
   claims it: replacing that arm with `raise AssertionError(...)` and running the
   full suite gave **2279 passed, 0 failed** — it never fired. Statically it is
   also unreachable: `providers.py:445` returns whenever
   `live_response is not None and live_response.answer_text`, and `live_response`
   is not reassigned before line 546, so the condition there is provably `False`.
   This is what makes class 8 unreachable.
2. **The repo already ships this exact definition.** `query_runs.py:2663-2671`
   computes `demo_mode` and `local_count` from
   `provider_path in {LOCAL_SIMULATION, FALLBACK_SEARCH}`. Adding a second,
   different definition is the "two matchers built from one constant drift" failure
   `_scoring_text`'s own docstring already warns about.
3. **Text-matching rejected**: builds a second matcher from the same template
   constant; drifts the moment the template is reworded, and silently.
4. **New field on `InitialModelAnswer` rejected for now**: `InitialModelAnswer`
   crosses the API boundary, so it costs an OpenAPI change, a schemathesis contract
   change and a migration, to express something the path already determines.

**Implementation guard**: one predicate, one place, plus a test that fails if a new
`ProviderPath` member is added without being classified — so the set cannot silently
go stale.

---

## 5. Verbatim evidence

See `ISSUE-247-RESULT.md` (written at the end). Key runs:

- baseline suite: `2279 passed, 56 skipped, 1 deselected` (0 failed)
- probe applied: `13 failed, 2266 passed` — the prompt's 13, re-derived, same files
- dead-arm mutation: `2279 passed, 0 failed` (the `raise` never fired)
- tree restored clean after every probe (`git diff` = 0 lines, `diff -q` exit 0)
