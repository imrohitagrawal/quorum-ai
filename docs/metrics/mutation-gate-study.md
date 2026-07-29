# Should the mutation gate block a merge? A measured study

**Date:** 2026-07-29 · **Trigger:** issue #130 · **Outcome:** promotion built,
measured, and **reversed**. The gate stays advisory.

This is the evidence pack. Everything below was measured on this repository or
read from a primary source. Where a number is an extrapolation it says so.
Where a lane of research did not finish, it is named as unfinished rather than
filled in from memory.

**Read this before proposing any new CI gate.** The generalisable lessons are
in §7, and are carried into `docs/DAY-ONE-PROMPT.md` §4a for the next project.

---

## 1. What #130 asked for, and what was actually true

Issue #130 asked to remove `continue-on-error: true` from the `mutation-baseline`
job, arguing:

> it finished in **1m 9s** on PR #96 and **passed**.

Both halves are false. That exact job (run `30376617533`, job `90333801913`,
16:06:01Z → 16:07:12Z) ends:

```
FAILED tests/contract/test_golden_fixture_matches_served_schema.py::test_the_shared_fixture_exists
failed to collect stats. runner returned 1
mutation-baseline: mutmut run failed — see build/mutation/run.log
make: [Makefile:322: mutation-baseline] Error 1 (ignored)
```

It finished in ~1m07s because it **aborted before scoring a single mutant**, and
it was green only because the error was ignored. Four sampled pull-request runs
show the same 1m04–1m11s abort.

**The gate had never produced a number in CI.** Not a low score — no score.

### Two advisory switches, not one

#130 found one. There were two:

| Switch | Effect |
|---|---|
| `continue-on-error: true` on the CI job | job reports failure without failing the run |
| a leading `-` on the Makefile recipe line | **swallowed every failure inside the run** — mutmut crashing, zero mutants scored, and a below-threshold score alike |

Removing the workflow flag alone would have changed nothing.

### Why nobody noticed

The scope script printed `"\n".join(globs)`. For an empty scope that is a bare
newline — **one byte** — and the recipe guards its work branch with
`[ -s scope.txt ]`, a *size* test. So the "no changed Python — nothing to
mutate" branch was **unreachable**, and every docs-only pull request invoked
`mutmut run` with zero globs, which aborts. Under the `-`, that abort was green.

---

## 2. The gate, repaired

Before any decision could be measured, the gate had to actually run. Each fix
ships with a test proven to bite by mutation:

| Defect | Fix |
|---|---|
| Empty scope wrote 1 byte → branch unreachable → unscoped mutmut run | `if globs:` guard; empty scope now writes **0 bytes** |
| `e2e/fixtures` missing from `[tool.mutmut].also_copy` | added (removed 13 of 41 copy failures) |
| Suite could not run inside mutmut's `./mutants/` copy | `repo_introspection` marker on 9 repo-driving modules, deselected under mutmut only |
| `killed+survived == 0` reported "the run did not happen" even when everything **timed out** | separate `UNMEASURED` branch, exits 0, prints no score |
| `no_tests` mutants silently left the denominator — a perfect score over nothing | now fails the run and names the cause |
| A decorative `MUTMUT_PATHS` variable disagreed with the real pathspec | deleted |

**Measured result of the repair:** the suite inside the mutant copy went from
**41 failed + 6 errors** (on `origin/main`) to **0 failed**, and
`make mutation-baseline` completed a real run for the first time.

Verified end to end by execution, not by reading:

| Probe | Result |
|---|---|
| Honest change to a tested function (`fence`) | 2 killed, 0 survived, **0 no-tests** → 100% → passes |
| Larger tested function (`evaluate_layer_a`) | **127 mutants, 3m32s** on 10 cores → 100% → passes |
| A new function with **no test** | 0 killed, 0 survived, **6 no-tests** → `make: *** Error 1` |

---

## 3. What the repaired gate actually does to real pull requests

Replayed all **66 commits** on `main` that changed Python under `src/` through
the real scope logic (read-only; `git show`, no checkouts).

### 3.1 Silent passes — 8%

| | |
|---|---|
| Gate runs | 61 |
| **Empty scope → "nothing to mutate" → green** | **5 (8%)** |

The five:

```
9c502398  cost: raise daily cap to $0.20
31b83f84  docs(cost): accept OpenRouter web-search plugin fee
59d48f58  fix(model): update gemini-2.0-flash-lite → gemini-2.5-flash
e0ac7b52  fix(copy): PR-1 brand lede, workspace lede
50c64eae  C16: cleanup — drop dead logger   (pure deletion)
```

**Three of the five are money or model configuration** (the daily cap, the
web-search fee, the model id); the other two are UI copy and a pure deletion.
The blind spot is not only trivia — it includes the spend caps and the pricing
table.

The cause is structural. The scope matches only functions whose *body* overlaps
a changed line. **5,829 lines of `src/product_app` — about 35% — sit outside
every `def`**: `config.py` is 75% module-level, `catalog_fetcher.py` 52%
(the pricing table), `model_slots.py` 40%.

### 3.2 False blocks — 7%

mutmut 3.6.0 skips decorated functions — **except** a single bare
`@staticmethod` or `@classmethod`, which it does handle
(`mutmut/mutation/file_mutation.py:230-235`, read). Of the **40** decorated
functions under `src/product_app`, **34 are unmutatable** and 6 are fine.
Probed live on `@property api_docs_enabled`:

```
AssertionError: Filtered for specific mutants, but nothing matches
```

The scope names the glob, mutmut matches nothing, and the run **aborts** — and
the author sees the recipe's "usually a repo-root file missing from
`[tool.mutmut].also_copy`" message, which is the wrong cause entirely.

The 34 unmutatable ones include every FastAPI route in `main.py` and every
Pydantic validator in `config.py`.

| | of 61 commits with a non-empty scope |
|---|---|
| Scope **entirely** unmutatable → hard abort | **4 (7%)** |
| Scope **partly** unmutatable → those functions silently unmeasured | **23 (38%)** |

This is a live bug and is tracked separately from the blocking decision.

### 3.3 Cost

Scope size, over the 61 commits with a non-empty scope: **median 5 functions,
p90 24, max 56.**

Measured mutant counts: `fence` → 2 mutants; `evaluate_layer_a` → 127 mutants in
3m32s on 10 cores; the recorded baseline → 504 mutants for 21 functions in ~9
minutes. **Extrapolating** (flagged as extrapolation), a p90 scope is ~575
mutants and the top decile is at or over the 30-minute CI timeout on a 2-core
runner — with `MUTMUT_MAX_CHILDREN ?= 8` tuned for a 10-core machine.

**Not measured:** actual p90 runtime on the CI runner. Open.

### 3.4 Net

**Roughly 15% of pull requests would get a wrong answer** — 7% blocked for a
tooling artefact with a misleading message, 8% passed having measured nothing.

---

## 4. Does it catch this project's actual defects? — 4%

A census of **158 distinct escaped / late-caught defects**, drawn from
`docs/metrics/quality-ledger.md` (E-1…E-11), `docs/analysis/R2-plan-review-findings.md`,
`docs/63-technical-debt-register.md`, 40 session records and 211 commit bodies.

| Would a changed-function Python mutation gate catch it? | Count | Share |
|---|---:|---:|
| **Yes** | 6 | **4%** |
| Partial — flags the region as weakly tested, does not identify the bug | 8 | 5% |
| **No** — structurally invisible, or scored green by construction | 144 | **91%** |

And **5 of the 6 "yes" cases are plain uncovered branches**, which the
already-blocking `diff-cover` gate (changed lines ≥ 95%, PR-only, no
`continue-on-error`) catches in seconds. The net new yield of ~9 minutes of
mutation testing is approximately **one defect in 158**.

### The two blind spots

**Language.** ~46% of the defects live in `app.js`, CSS, HTML templates,
Playwright specs, workflow YAML, `Makefile`, `scripts/`, `openapi.yaml` or
Markdown. `only_mutate = ["src/product_app/*.py"]` sees none of it. Independent
corroboration: **35 of 60** recent fix/review commits touched no
`src/product_app` Python at all.

**Shape.** The largest single Python category — 45 defects — is *wrong code with
tests that agree with it*: `all([])` returning `True`; every run billed twice;
the spend cap failing open; `live_count` counting failed slots as live. Every
money bug is in this class. When the suite confidently asserts the buggy
behaviour, every mutant dies and **the score goes up**. Mutation testing cannot
distinguish well-tested-correct from well-tested-wrong.

### The finding already in this repo

`docs/metrics/mutation-baseline.md` §1 — the gate's own founding proof — records:

> mutmut 3.6.0 does **not** generate the guard-deletion mutant… So the mutant
> that actually escaped the old suite is one mutmut would never have produced.
> **The gate is a floor, not a proof of test strength.**

The flagship defect that motivated the whole work item would have scored
**green**.

---

## 5. What the industry does

### 5.1 Google — the only large-scale published deployment

Sources: Petrović & Ivanković, *State of Mutation Testing at Google*, ICSE-SEIP
2018; Petrović, Ivanković, Fraser, Just, *Practical Mutation Testing at Scale*,
IEEE TSE 2021 ([arXiv:2102.11378](https://arxiv.org/abs/2102.11378)); *Does
mutation testing improve testing practices?*, ICSE 2021
([arXiv:2103.07189](https://arxiv.org/abs/2103.07189)).

Scale: 776,740 changelists → 16,935,148 mutants → 2,110,489 surfaced (12.5%).

**They do not block:**

> findings do not need to be resolved by the author before submission, unless a
> human reviewer marks them as mandatory.

**They deliberately do not compute a mutation score:**

> we were unable to find a good way to report it to the developers in an
> actionable way: it is **neither concrete nor actionable**, and it does not
> guide testing.

**Volume control**, three stacked rules — mutants only on covered lines, **one
mutant per line**, and arid-node suppression. Median mutants per changelist:

| Strategy | Median |
|---|---:|
| All mutants | 820 |
| One-per-line | 77 |
| **Arid + one-per-line (production)** | **7** |

Surfacing is capped at ≤7 per file; developers see a **median of 2** live
mutants. Productive-mutant rate went **15% → 89% over six years** and 100+
hand-written suppression rules — *to justify advisory comments*.

### 5.2 Nobody blocks on a mutation score

| Tool | Knob | Default |
|---|---|---|
| StrykerJS | `thresholds.break` | **null** — *"never let your build fail"* |
| PIT | `mutationThreshold` | unset, with an equivalent-mutant warning |
| mutmut | — | **no score gate at all** |

**The 80% threshold in our Makefile is ours, not the tool's.** No published
industrial practice gates a merge on a mutation score.

Meta's *What It Would Take to Use Mutation Testing in Industry* (ICSE-SEIP 2021,
[arXiv:2010.13464](https://arxiv.org/abs/2010.13464)): **>50% of 15,000 mutants
survived** Facebook's full suite — a score gate would have blocked essentially
every diff.

### 5.3 Delivery point beats enforcement strength

Distefano et al., *Scaling Static Analyses at Facebook*, CACM 62(8) 2019: Infer
in **batch mode** achieved a **~0% fix rate** even below 20% false positives.
The **same analysis, same false-positive rate**, delivered as a bot comment at
**diff time**, reached **over 70%**.

*(Verified via two independent secondary reproductions; cacm.acm.org blocks
automated fetch. Confirm before formal citation.)*

### 5.4 The metric itself is a poor cardinal measure

- **Papadakis et al., ICSE 2018:** correlation between mutation score and real
  fault detection is τ = 0.35–0.75 uncontrolled, collapsing to **τ = 0.05–0.20
  once suite size is controlled**.
- **Papadakis et al., ISSTA 2016:** comparing by raw mutation score without
  fixing suite size gives a **~62% Type I error rate**; only **0.4–4.8%** of
  mutants are subsuming.
- **Just et al., FSE 2014** (the pro case): **73% of 357 real faults are coupled
  to a mutant**, and mutation tracks fault detection better than statement
  coverage. The two do not disagree on data, only on interpretation.
- **Chekam et al., ICSE 2017:** fault revelation is **non-linear** — strong
  mutation gives **+17.6%** for top-5% suites vs +4.3% for statement coverage.

**Practical reading:** a mutation score as a cross-suite aggregate with a fixed
threshold is the use the evidence most directly contraindicates. Killing one
specific named mutant to prove one specific test bites is validated.

### 5.5 Cost advice is the opposite of intuition

**Kurtz et al., FSE 2016:** dominator mutants are **0.85%** of all mutants, and
**50× more mutants costs only ~20% more total work**. Redundancy is cheap to run
and expensive to *measure with*. Sampling saves less than expected: 5% sampling
yields **6.54%** of runtime, because generation does not shrink. Uniform random
sampling is the baseline nothing has convincingly beaten.

Our equivalent-mutant rate — 24 of 504 generated = **4.8%** — is normal against
Kushigian et al. (ISSTA 2024): median 2.97%, range 1.84–5.24%, n=1,992
hand-labelled. *(Note the denominator trap: "24 of 43 survivors" is 56% and
describes something else entirely.)*

### 5.6 Risk-tiering: the principle is standard, the mechanism is not

Graduating rigour by criticality is mandated by name in **DO-178C** (Table A-7:
MC/DC Level A only, decision A–B, statement A–C), **ISO 26262-6:2018** (Table 9:
MC/DC "++" at ASIL D only), **Common Criteria** (ATE_DPT.2.3C literally requires
demonstrating that *SFR-enforcing modules* were tested), and **NIST SSDF**
(PW.1.1: *"more rigorous assessments for high-risk areas, such as protecting
sensitive data and safeguarding identification, authentication, and access
control"*).

But: **no standard mandates mutation testing.** The closest is IEC 61508's
"error seeding" (Table B.2, recommended — never highly recommended). And **no
mainstream tool supports per-module mutation thresholds.**

So a criticality-keyed mutation-score gate would be our invention, and it is
precisely the artefact Google tested and discarded. The evidence-supported form
is: use criticality to **widen the mutant budget** on money/auth paths, and
surface surviving mutants as **named test goals**, never a percentage.

---

## 6. Decision

**The gate stays advisory in CI.** `make` still exits non-zero honestly; only
the CI job carries `continue-on-error`. Advisory means *reported, does not block
a merge* — it does **not** mean failures are invisible, which is what the old
double-switch arrangement produced.

Rationale, in one line each:

- measured yield ~4%, of which 5/6 is already covered by a faster blocking gate;
- ~15% of pull requests would get a wrong answer (7% false abort, 8% silent pass);
- it had never produced a number in CI, so there was no baseline to promote on;
- a fixed-threshold score gate is the use of the metric the literature
  specifically contraindicates;
- no published industrial practice does it, and every tool ships the gate off.

**Revisit condition** (written down, per §4a's own rule): fix the
decorated-function abort, then re-measure yield against a fresh defect census.
**Do not promote on runtime alone again.**

---

## 7. Lessons that generalise

1. **A green advisory job is not evidence it ran.** Open the log and confirm it
   produced its number. #130 read a checkmark; the log said `Error 1 (ignored)`.
2. **Every gate must declare what it cannot see.** Ours would have said:
   *cannot see JavaScript, module-level constants, decorated functions, or
   deletions.* #130 would never have been written.
3. **Measure a gate against your own defect history before trusting it.**
   "What would this have done to our last N commits?" is answerable in minutes
   (`scripts/replay_mutation_scope.py`) and it is the question that decided this.
4. **Match the tool to the defect's shape, not just its location.** Constants
   need pinned literal assertions. Browser behaviour needs a rendered fixture and
   a screenshot. Billing needs an independent oracle at the provider seam.
5. **A metric that is a good ordinal signal can be a bad cardinal gate.**
6. **Prefer review-time surfacing to merge-time blocking** when the signal is
   noisy — measured 0% vs >70% fix rate at Facebook for the identical analysis.
7. **Verify by executing, never by reading.** Every substantive finding here came
   from running something. Several confident readings — including the author's —
   were refuted the moment they were executed (§8).

---

## 8. This study is also a record of getting it wrong

Kept deliberately, because the failure mode is the point: **confidence is
uncorrelated with whether anything was run.** This applies to human and AI
contributors alike, and every item below is from this one work package.

| Claim, asserted from reading | What running it showed |
|---|---|
| "The gate passed on PR #96 in 1m 9s" (#130) | the job aborted; green only because the error was ignored |
| "Removing `continue-on-error` makes it blocking" | a second switch in the Makefile swallowed everything |
| "Those 8 test modules test build machinery, so excluding them is safe" | they touch 62% of `src/`; only a real measurement (0 orphaned functions) settled it |
| "The gate is ready to be made blocking" (this author) | ~15% wrong-answer rate; recommendation reversed |
| Two new tests asserting only on printed text | a mutation restoring `SystemExit(1)` left both green |
| A unit test for the `no_tests` path using a mixed case | the real run hit a different branch and printed a false message |
| A guard asserting `"sys.platform" in source` | flipping the constant to `"linux"` kept it green |
| "the gate stayed broken for **months**" — shipped into 4 files | **~7 days**, and measured only after the operator challenged it. The abort is confirmed by log on 22 July and 28 July |
| "#130 sat unfixed a long time" | it lived **71 minutes** and was caught the same evening — a sub-hour detection gap |
| "`_DEFAULT_PRICE_PER_1K_INPUT` is pinned, therefore sound" | pinning makes drift visible; it does not derive the value. Measured later: it under-charges one shipped model by 25% (#151) |

**The sharpest pattern, and it took the operator to name it:** every number
produced by running a command was correct; every number written straight into
prose was wrong. Narrative text was treated as a lower evidence bar than code,
which is backwards — prose is what people read and act on. None of the prose
errors were caught by self-review; all were caught by an adversarial reviewer
or by the operator.

The countermeasure is mechanical, not exhortative: CI, hooks, and tests proven
to bite by mutation. Prose in a rulebook — including this document — is
influence, not enforcement.

---

## 9. Open, and named as open

- **The REPAIRED gate has still never scored a mutant in CI.** Every run so far,
  including this pull request's, took the "nothing to mutate" branch because no
  `src/` Python changed. That branch working is itself the repair — but §7.1
  says a green advisory job is not evidence it ran, and that applies to this
  work too. The first PR touching `src/` Python is the real proof.

  > **Updated 2026-07-29.** That first PR arrived (#157) and the gate **aborted
  > without scoring** — #158. Cause: a guard resolving the repository root from
  > `__file__`, which inside `./mutants/` counts the mutation runner's own
  > generated variants (514 against a bound of 55). Repaired; the same command on
  > the same tree now prints `2 killed, 0 survived, 0 no-tests → 100.0%`, and
  > re-introducing the old resolution reproduces the abort exactly. That pair is
  > recorded as run **P1** in `mutation-baseline.md` §3.
  >
  > **Still open, and it is the same open question one level up:** the repair is
  > proven LOCALLY. It has not yet been proven in CI, because scoring requires a
  > pull request that changes `src/` Python and the repair itself does not.
  > Measured while auditing this: **11 of the last 11 pull-request runs of this
  > job produced no score** — ten reported `success`, one reported `failure`.
  > Neither tick carried information. The job now says so in words on the
  > empty-scope branch, and its charter in `ci.yml` states that it can exit
  > non-zero having measured nothing.
- **The new `no_tests` hard-fail conflicts with the recorded baseline.** §3 of
  `mutation-baseline.md` records `no-tests = 2` on all five baseline runs, and
  §3.2 deliberately deferred fixing them. The gate would now fail that state.
  It is defused only by `continue-on-error`, so promoting the gate without
  first clearing those two would break immediately.
- **`report()` misclassifies several mutmut exit codes.** The
  `killed if code > 0 else "timeout"` fallback treats pytest's
  NO_TESTS_COLLECTED (5) and USAGE_ERROR (4) as *killed*, and mutmut's own
  timeout codes as killed too. The `no_tests` guard only knows 33, so the
  "silence a function's tests" evasion stays open via exit 5. Pre-existing and
  untouched by this work — but the recorded 87.2–88.7% baseline was produced by
  it, so the derived threshold of 80 inherits any inflation.
- **p90 CI runtime unmeasured.** The 30-minute-timeout risk in §3.3 is an
  extrapolation from two local data points.
- **The decorated-function abort is unfixed.** 7% false-block rate; related to
  mutmut issue #387.
- **Risk-based-testing literature not surveyed** (Amland JSS 2000; Felderer &
  Ramler). The specific open question: does that literature contain any
  *measured* benefit from concentrating effort on high-risk components, or is it
  descriptive process guidance? Unanswered — the research lane exhausted its
  search budget.
- **The 158-defect classification is judgement, not execution.** Each defect was
  classified by reading its description against mutmut's operator set and this
  repo's `only_mutate`/marker config. mutmut was **not** re-run against 158
  historical commits. The E-4 verdict is the exception: it is measured, in
  `mutation-baseline.md` §1.

## 10. What held up

Recorded so this reads as an assessment rather than a prosecution. An adversarial
red-team pass tried and **failed** to break these, which is evidence the repaired
plumbing is sound:

- unresolvable base ref → fails loudly, not an empty scope;
- absent or crashed run → cannot score as 100%;
- the report's exit status is not swallowed by a pipe;
- stale `mutants/` metadata is cleared before each run;
- removing an `also_copy` entry aborts non-zero rather than passing;
- hiding new code in a `src/product_app/` subpackage does **not** evade the scope.
