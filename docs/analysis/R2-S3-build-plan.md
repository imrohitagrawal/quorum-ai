# R2-S3 Build Plan — Trust & Confidence UI (FR-016) + DEBT-012 presentation guard

**Branch:** `feat/r2-s3-trust-ui` (off `main` @ `a1cf546`, which contains S2).
**Status:** EXECUTABLE. Every design decision below is settled; implementers do not
re-open them. Six adversarial lenses were reconciled into this document; where they
disagreed, §1 records the decision and the reason.

Every file path and line number in this plan was read on the S3 branch tip before it
was written. Line numbers drift as commits land — treat them as *locators*, and
confirm the quoted text before editing.

---

## 0. THE ONE-PARAGRAPH SUMMARY

S3 puts the S2 evaluation in front of a user. The blocker is DEBT-012: a run with one
resolving ordinal beside 20 fabricated links is served `faithful` / `low` /
composite 82.5 — statistically indistinguishable from a genuinely faithful run.
The resolution is **not** to change `citation_marker_grounding` (that would need a
calibrated cut, which FS-6 defers to S4). It is to make the laundering shape a
**measurable engine-side fact** (`unverifiable_marker_count`), derive a **cut-free,
monotone-downward** presentation verdict from it (`label_confidence`), and give the
UI a rendering contract so narrow that no arithmetic can leak: **the trust-score
surface renders zero digits and never renders the words `faithful` / `partial` /
`unfaithful` / `low` / `medium` / `high`.** The engine labels stay exactly as they
are; what changes is that they are no longer surfaceable as confident claims.

---

## 1. DECISIONS

Numbered `D-n`. Each records the conflict, the decision, and the reason.

### D-1 — DEBT-012 resolution: engine census + presentation guard. ADOPTED.

**Conflict.** Lens 1 (DEBT-012 design) wants a new engine signal plus a guard.
Lens 2 (OC-5/honesty) wants S3 to simply not render the labels. Lens 4 (docs) wants
a written three-option decision node.

**Decision — BOTH, in this exact shape:**

1. **Engine census.** Refactor the loop in `citation_marker_grounding`
   (`src/product_app/evaluation.py`, the loop at the `total = 0 / resolved = 0`
   block ≈ `:353-370`) into a pure function that returns a frozen census:

   ```python
   class MarkerCensus(BaseModel):
       """Every inline citation marker on a run, classified by what Layer A
       can establish about it with ZERO I/O.

       ``resolved``     — points at a real, non-placeholder row this run holds.
       ``unresolved``   — resolvable-as-FALSE: an ordinal outside its own
                          scope's bibliography, or one pointing at a
                          placeholder row. No I/O needed to know it is wrong.
       ``unverifiable`` — an off-run URL. The engine performs no I/O, so it
                          cannot distinguish an invented URL from a real page
                          a model knew but did not retrieve here. UNKNOWN,
                          not zero — the doctrine DEBT-011 part C established
                          and DEBT-012 records the cost of.
       """
       model_config = ConfigDict(frozen=True)
       resolved: int = Field(ge=0)
       unresolved: int = Field(ge=0)
       unverifiable: int = Field(ge=0)

       @property
       def resolvable(self) -> int:
           return self.resolved + self.unresolved


   def citation_marker_census(*, scopes: list[CitationScope]) -> MarkerCensus: ...
   ```

   `citation_marker_grounding(*, scopes)` keeps its exact signature, docstring and
   **value semantics** and is reimplemented over the census:

   ```python
   census = citation_marker_census(scopes=scopes)
   if not census.resolvable:
       return None
   return census.resolved / census.resolvable
   ```

   The two can then never drift.

2. **Two new signals**, INSIDE `LayerASignals` (never at `RunEvaluation` top level —
   see D-8):

   ```python
   #: Off-run URL markers on this run: cited documents the engine cannot
   #: check without I/O. NOT weighted (see LAYER_A_WEIGHTS) — weighting it
   #: is a calibrated cut, deferred to S4 (FS-6). It exists so a consumer
   #: can tell "1 marker, resolved" from "1 marker resolved + 80 fabricated
   #: links", which grounding alone cannot (DEBT-012).
   unverifiable_marker_count: int = Field(default=0, ge=0)
   #: unverifiable / (resolved + unresolved + unverifiable). ``None`` iff
   #: the run carried no citation markers at all.
   unverifiable_marker_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
   ```

   Both carry defaults, so they render **outside** the OpenAPI `required` set and
   the additive-contract guard stays green (D-9). Populated in `evaluate_layer_a`
   from the single census already built there.

3. **NOT added to `LAYER_A_WEIGHTS`.** Weighting an unverifiable count is a
   calibrated cut. FS-6 defers cuts to S4.

4. **Presentation guard — cut-free and monotone-downward:**

   ```python
   PresentationConfidence = Literal["reportable", "indeterminate"]

   def presentation_confidence(
       signals: LayerASignals,
       *,
       faithfulness_label: FaithfulnessLabel,
       hallucination_risk: HallucinationRisk,
   ) -> PresentationConfidence:
       """Whether this run's ADVISORY labels may be presented at all.

       ``"indeterminate"`` iff the run carries ANY unverifiable marker AND
       its labels sit at the CONFIDENT end. It is monotone-downward by
       construction: a warning label (``unfaithful``/``high``,
       ``partial``/``medium``) is NEVER suppressed, so the guard can only
       ever UNDER-claim. It chooses no constant — zero tolerance at the
       confident end, which is why it does not need the calibrated cut FS-6
       defers to S4.

       MEASURED (see the DEBT-012 row): on the frozen corpus this degrades
       0 of the 2 confident cases — both have unverifiable_marker_count 0.
       """
       if signals.unverifiable_marker_count <= 0:
           return "reportable"
       if faithfulness_label == "faithful" or hallucination_risk == "low":
           return "indeterminate"
       return "reportable"
   ```

   **Why zero-tolerance and not "unverifiable > resolvable".** A dominance cut is
   the rule DEBT-012's own repayment column gestures at, and it is measurably
   wrong: the laundering is total at dose 1. One fabricated link beside one
   resolving ordinal already yields grounding 1.0 → `faithful`/`low`, and its ratio
   is exactly 0.5 — *below* a strict-majority cut. A dominance rule would pass the
   20-link case in the register and fail the 1-link case.

5. **Composite exclusion.** `compute_composite` treats
   `citation_marker_grounding` as UNKNOWN — i.e. excludes it and renormalises,
   reusing the module's existing `None`-is-excluded doctrine — whenever
   `unverifiable_marker_count > 0`. This is not a penalty (a penalty would be an
   uncalibrated constant); it is the same "we could not tell" handling one level up.
   Without it, the laundering run's `layer_a_composite_unverified` stays at 82.5,
   inside the genuine-faithful band (83.50 / 83.38), and the contribution list names
   `citation_marker_grounding` at value 1.0 as the top contributor on a 95%-fabricated
   run.

**Reason.** Lens 2's "just don't render the labels" is necessary but not sufficient:
the composite and the contribution list are equally confident surfaces, and an
engine that cannot *see* the shape gives no consumer — UI or test — anything to key
on. Lens 1's engine work is necessary but not sufficient either: a degraded label
beside an 82.5 is still a falsely confident surface. Both, plus D-2.

### D-2 — The UI rendering contract: ZERO DIGITS, ZERO LABEL WORDS. ADOPTED.

**Conflict.** The ULTRACODE S3 spec says render "band + plain-language why = top
contributing Layer-A signals". Lens 2 says every number in that payload is biased
upward exactly on the runs that deserve least trust, and "top contributors" is a
sell, not a disclosure. Lens 1 says qualify rather than withhold.

**Decision.** The trust-score surface obeys four absolute rules, each mechanically
enforceable and each RED-provable:

| # | Rule | Enforcement |
|---|---|---|
| R1 | **No digits.** `#result-trust-score` innerText must not match `/\d/`. | e2e invariant |
| R2 | **No label words.** innerText must not match `/\bfaithful\b\|\bunfaithful\b\|\bpartial\b\|low risk\|medium risk\|high risk\|hallucination\|confiden\|accurac\|trustworth\|reliab\|\bscore\b\|\bgrade\b/i`. | e2e invariant |
| R3 | **No raw signal identifiers.** innerText must contain none of the seven `LAYER_A_WEIGHTS` keys nor `unverifiable_marker_count`/`ratio`. | e2e invariant |
| R4 | **Standing disclosure.** innerText must contain the exact literal `Not verified — these are automated structural checks, not a fact-check.` | e2e invariant |

R1 makes `layer_a_composite_unverified`, `contributions[].contribution`, coverage
percentages and any ARIA `aria-valuenow` unrenderable **by construction**, and
resolves OC5-3, OC5-10 (two disagreeing coverage numbers) and UI-8 (ARIA meter lie)
in one line each. R2 resolves OC5-2 and OC5-4 (a refused run can no longer read
"low risk"). It is deliberately blunt: a blunt rule that a test can check beats a
nuanced rule a reviewer must remember.

**What the surface DOES render** — app-authored constants only, selected from the
served payload, never interpolating provider prose:

```
Not verified — these are automated structural checks, not a fact-check.

<state line>                       ← exactly one, from the state table below
<up to three "what we could not check" lines>
<the missing-safety-caveat row, when required && !present>
```

**State line, in priority order** (first match wins):

| Condition (all read off `result.evaluation`) | State line |
|---|---|
| `label_confidence !== "reportable"` (incl. `undefined`) | `Some citations on this run point to pages that were never retrieved here, so the structural checks could not be applied.` |
| `signals.citation_marker_grounding === null` | `No citation marker on this run could be checked.` |
| `signals.refusal_detected === true` | `The panel declined. Nothing was asserted, and nothing was verified.` |
| otherwise | `Structural checks passed — citations were not verified against their sources.` |

The fourth branch carries its own epistemic qualifier. This is D12-5: honesty is
satisfied by qualifying the confident branch, not only by degrading the bad one —
because even with `unverifiable_marker_count === 0` a model that invents plausible
SOURCE ROWS and cites `[1]`, `[2]` reaches grounding 1.0 with zero unverifiable
markers, and Layer A with no I/O cannot close that at all.

**"Why" lines** — at most three, selected by **lowest value** (the reasons to
doubt), never by highest contribution. Fixed hand-written English from a hardcoded
JS table keyed on the signal name:

```js
const TRUST_WHY = {
  citation_marker_grounding: "Some citation markers did not point at a source on this run.",
  live_ratio:               "Not every answer came from a live model.",
  citation_coverage_ratio:  "Not every material claim carried a citation.",
  completeness:             "Not every model slot produced a usable answer.",
  disagreement_integrity:   "A polar disagreement was flattened in the synthesis.",
  uncertainty_surfaced:     "The synthesis flagged no open uncertainty.",
  decision_support_framing_present: "The synthesis did not frame itself as decision support.",
};
```

A "why" line is emitted only for a contribution present in `trust.diagnostics.
contributions` (so an EXCLUDED grounding, per D-1.5, is silently absent — it cannot
appear at value 1.0 on a laundered run) whose `value < 1.0`, sorted ascending by
`value`, capped at 3.

**Missing safety caveat** (OC5-5): when `signals.high_stakes_warning_required &&
!signals.high_stakes_warning_present`, render a persistent amber row
`This question needed a safety caveat and the synthesis did not include one.`
independent of `fs.high_stakes_notice`. Today that state renders as literally
nothing (`app.js` `if (fs.high_stakes_notice) { ... }` with no else branch,
≈`:2519`) — the highest-consequence silent state in the payload.

### D-3 — Fail CLOSED on the served string. ADOPTED.

The UI keys on `result.evaluation.label_confidence` with a **whitelist**:

```js
const reportable = ev && ev.label_confidence === "reportable";
```

Anything else — `undefined`, `null`, an unknown future value, a persisted
`s2-eval-v2` row read back — renders the indeterminate treatment. A blacklist
(`if (sig.unverifiable_marker_count > 0)`) evaluates `undefined > 0 === false` and
shows the CONFIDENT treatment on exactly the runs whose provenance is unknown.

On the API side, `QueryRunEvaluationProjection` gets
`label_confidence: PresentationConfidence` **with NO default**, so a projection
constructed without it raises rather than silently serving the confident branch.

### D-4 — The three pinned laundering tests: TWO AMENDED, ONE FLIPPED.

| Test | Verdict | Why |
|---|---|---|
| `test_one_resolving_ordinal_launders_many_off_run_urls_to_maximum_trust` (`tests/unit/test_evaluation_layer_a.py` ≈`:501`) | **AMEND, do not rewrite** | The three existing assertions (`grounding == 1.0`, `faithful`, `low`) stay byte-identical — the engine label is unchanged and still wrong. Append the new assertions and a docstring line. |
| `test_a_run_whose_only_markers_are_off_run_urls_is_unknown_not_zero` (≈`:207`) | **AMEND, do not rewrite** | Same. `None` / `partial` / `medium` stay. |
| `test_a_simulated_stub_cited_BY_URL_does_not_ground_either` (≈`:418`) | **FLIP `is None` → `== 0.0`**, rename | Not a regression: it strengthens. See below. |

**The flip, justified.** A marker citing one of the app's OWN `example.test` stubs
BY URL is currently excluded as "unknown", although `.test` is IANA-reserved and
the run holds the row — it is resolvable-as-FALSE with **no network**, exactly like
an out-of-range ordinal. The test's own docstring already admits this ("A stub URL
is not 'unknown' the way an off-run URL is") and then keeps it excluded anyway. It
also disagrees with `test_fallback_sources_do_not_ground_a_marker` (≈`:314`), which
scores the ORDINAL form of the *identical run* `0.0`. The assertion the old test
protected was "a stub URL can never GROUND anything"; `0.0` is strictly more
punishing than `None`, so the protected property strengthens.

New name: `test_a_simulated_stub_cited_BY_URL_is_resolvable_as_FALSE_not_unknown`.
The old name is recorded in the docstring so a `git log -S` search still finds it.

**ABORT CONDITION (mandatory).** This flip changes a *value*, so it ships as its
own commit (PR-S3-2) and the implementer MUST run
`uv run pytest tests/evals/ tests/unit/test_evaluation_layer_a.py -q` immediately
after. **If any corpus case's label moves, revert this commit and record it as a
DEBT-012 residual instead.** The rest of the plan does not depend on it.

### D-5 — Judge is OUT of S3 scope entirely. ADOPTED (lens 2, OC5-1).

The ULTRACODE S3 text says "when present, the judge's advisory metrics" and asks
for a `judge-present` / `judge-absent` fixture pair. **The served projection has no
judge field and never will** — `QueryRunEvaluationProjection`'s docstring
(`src/product_app/query_runs.py` ≈`:283`) states there is "no path — present or
future — by which a rationale reaches a client". Building a judge-reading code path
manufactures an API shape that does not exist and creates standing pressure to add
it.

**Decision:** no judge branch in `app.js`, no judge fixture. Replace with two
blocking tests (§3, item S3-1e). If a judge surface is ever wanted it is an S4+
decision with its own privacy review.

### D-6 — GREEN RULE guard: token-sourced, both themes, all paint channels. ADOPTED.

The plan text "computed `color` ≠ `#0E6B50`" is **vacuous in dark mode**:
`src/product_app/static/app.css` sets `--c-green: #0E6B50` at `:74` (light) and
`#4EC28C` at `:219` (dark). A fully green trust surface passes the specified check
on the dark theme. The ULTRACODE variant ("never carries the consensus/green
class") is worse — any CSS rename or attribute selector evades it.

**The guard, as it must be written:**

1. Resolve the expected greens **at runtime from the token source** —
   `getComputedStyle(document.documentElement).getPropertyValue('--c-green' |
   '--success' | '--verdict-surface')` — never a retyped literal.
2. Walk `#result-trust-score` **and every descendant**, plus `::before`/`::after`.
3. Inspect **every paint channel**: `color`, `background-color`,
   `background-image`, all four `border-*-color`, `outline-color`, `box-shadow`,
   `text-decoration-color`, `caret-color`, `accent-color`, `fill`, `stroke`.
   (`color` alone misses five: `--success`, `--success-soft`, `--success-border`,
   `--verdict-surface`, `--shadow-verdict`; and the existing ring paints via SVG
   `stroke`.)
4. Parse to RGBA; fail on (a) exact match to any resolved token green, OR (b) any
   colour with `alpha > 0` whose hue lands in 120–175° at saturation ≥ 15%. The
   hue-band rule is what survives a new or edited green token.
5. **Structural belt-and-braces:** no descendant carries `data-consensus` or
   `data-accent="agreement"` or a class matching `/consensus|agreement/`.
6. Run in **both** `data-theme="light"` and `data-theme="dark"`, at 375 / 768 /
   1440.

### D-7 — `EVAL_SCHEMA_VERSION` → `s3-eval-v3`. ADOPTED.

`src/product_app/evaluation.py:63` is `"s2-eval-v2"`. The signal set changes and the
composite arithmetic changes, so persisted rows and feedback events become
mixed-version. Bump to `"s3-eval-v3"` and add a test that an old-shaped payload
(missing the new signal keys) is presented as **indeterminate** (D-3).

**Note the split, and write it into the plan:** the SERVED projection is recomputed
on every read (`_evaluation_projection` → `_evaluate_terminal_run`,
`src/product_app/query_runs.py` ≈`:1575-1602`), so the UI is never stale. Only the
durable `run_history` `eval_json` rows and the `run_evaluated` feedback events are
mixed-version; any later analytics read of them must filter on `schema_version`.

### D-8 — Field placement, so no exact-key-set assertion breaks. ADOPTED.

- `unverifiable_marker_count` / `unverifiable_marker_ratio` → **inside `signals`**.
  `tests/integration/test_query_run_evaluation_endpoint.py` ≈`:112-119` asserts
  `set(row.eval_json) == {"schema_version","signals","faithfulness_label",
  "hallucination_risk","judge"}`, and `tests/unit/test_evaluation_judge.py`
  ≈`:503-509` asserts the same shape. A top-level addition breaks both.
- `label_confidence` → **projection top level ONLY**
  (`QueryRunEvaluationProjection`). It is a derived presentation fact, not a
  persisted signal, so `set(row.eval_json)` is untouched.

### D-9 — Contract guard extended to the sub-schemas. ADOPTED.

`tests/contract/test_query_run_evaluation_additive.py` ≈`:75-81` pins only
`QueryRunResultResponse`. A new REQUIRED field on `LayerASignals` would be a
breaking change for any schema-validating client with every gate green. New file
pins the frozen PRE-S3 `required` sets of `LayerASignals`,
`QueryRunEvaluationProjection`, `TrustScore` and `TrustDiagnostics`. Both new
signals carry defaults ⇒ optional ⇒ additive. `label_confidence` has no default ⇒
it IS a new required field on `QueryRunEvaluationProjection`, which is a **new**
schema shipped in the same release as its only client; record that explicitly in
the new contract test's docstring as a deliberate, reviewed addition.

### D-10 — `query_runs.py:1478` is coverable TODAY. Ledger row is WRONG. ADOPTED.

The ledger says the uncovered non-terminal early `return` in
`_persist_run_evaluation` needs "FR-016's second writer". It does not:
`_persist_run_evaluation` is module-level (≈`:1460`) and tests already reach it
directly (`tests/integration/test_query_run_evaluation_endpoint.py` ≈`:233`
`real_persist_evaluation = qr._persist_run_evaluation`).

**But the obvious test does not bite.** Deleting the guard makes
`result.eval_json()` raise `AttributeError` on `None`, swallowed by the broad
`except Exception` ≈`:1503` → `logger.warning(...)`. Net observable effect is
identical (zero store writes, zero feedback events) unless the test **asserts on
the log**. Written correctly in §3 (S3-1g); ledger row corrected in §6.

### D-11 — CSP is NOT a control here. ADOPTED.

`src/product_app/main.py` ≈`:311-318` sets `script-src 'self' 'unsafe-inline'` and
`style-src 'self' 'unsafe-inline'`. The premise "the new surface must not need any
inline style/script — the CSP forbids it" is **false**, and existing code already
writes inline style via CSSOM (`app.js` ≈`:2074`). Drop the CSP claim from the S3
narrative. The band treatment carries its colour via a CSS custom property in
`app.css` so the D-6 guard can audit it.

### D-12 — Container: a SIBLING, not a fourth trust card. ADOPTED.

`renderTrustTriangle` (`app.js` ≈`:2539`) does `trust.textContent = ""` then appends
exactly three cards into `#result-trust`, which is
`role="group" aria-label="Trust signals"` with a 3-up grid
(`app.css` `.result-trust { grid-template-columns: repeat(3, 1fr) }` ≈`:2717`).
A fourth child breaks the ARIA group semantics and the grid.

New sibling `<section id="result-trust-score">` immediately after the
`#result-trust` div in `src/product_app/templates/workspace.html` (≈`:502`), inside
`#main-content` so the rendering-invariants walker covers it with no spec change.

**`renderResult` is NOT called once.** The comment at `app.js` ≈`:2143` describes
intent; the function has three call sites (≈`:5422`, `:5504`, `:5686`). So
`renderTrustScore` MUST reset (`textContent = ""`, `hidden = true`)
**unconditionally, before** the `evaluation == null` early return — mirroring
`trust.textContent = ""` at ≈`:2542`. Otherwise a re-render shows a STALE band.

### D-13 — Fixture placement: `goldenCompletedResp()` stays evaluation-free. ADOPTED.

`goldenCompletedResp()` (`e2e/fixtures/golden-run.ts` ≈`:213`) is consumed by the
degraded, invariants, visual, a11y and ui-parity specs. Adding an `evaluation` key
to it silently changes all of them AND makes the currently-exercised ABSENT path
untested — the exact path the "hide, don't render `—`" rule is about.

**Decision:** `goldenCompletedResp()` keeps no `evaluation` key; it IS the canonical
ABSENT case. Add `goldenEvaluation(overrides)` + `withEvaluation(resp, ev)` and six
named variants (§3, S3-4b).

### D-14 — "Absent ⇒ `—`" is REPLACED by "absent ⇒ hidden, zero text". ADOPTED.

In a trust panel an em-dash reads as "nothing wrong found", not "we did not
evaluate this". And the absent path is not exotic: `_evaluation_projection`
swallows every exception and serves `null` (`query_runs.py` ≈`:1589-1594`), so any
internal evaluation bug lands there. Rule: an absent / `null` / malformed
`evaluation` ⇒ the entire `#result-trust-score` surface is `hidden` and emits zero
text. The `—` convention stays confined to the existing numeric trust cards.

### D-15 — The no-raw-markdown claim on the new surface is honestly VACUOUS. ADOPTED.

The projection is metrics-only; every string the new surface renders is an
app-authored constant, so the raw-markdown invariant can never go red there. **Do
not claim the markdown gate covers this surface.** Instead:

- All new surface text uses `textContent` / `mkEl`, **not** `setProse` /
  `setInlineProse` — routing app-authored constants through the markdown renderer
  gives a future provider-derived string a silent path in. This deliberately
  contradicts the ULTRACODE "ALL prose via setProse" line; the reason is that the
  rule's purpose (escape provider prose) does not apply and its side effect
  (normalising a provider-text path onto this surface) is harmful.
- **A hard prohibition, enforced by test:** no server-side `reason` / `why` /
  `explanation` / free-text string may be added to `QueryRunEvaluationProjection`,
  to `eval_json`, or to the `run_evaluated` feedback payload.
- The markdown gate's real S3 work is elsewhere — see D-16.

### D-16 — A raw-markdown leak already exists on the trust TRIANGLE. FIX IT. ADOPTED.

`app.js` ≈`:2598` does `truncateText(uncertaintyText, 180)` and feeds the result to
`buildTrustCard({caption})`, which renders via `setInlineProse` (≈`:2105`).
`truncateText` slices raw characters. A cut inside a `**bold**` run leaves a
dangling `**` in a text node — `RAW_MARKDOWN_PATTERNS[0]` is `/\*\*/`
(`e2e/fixtures/golden-run.ts` ≈`:40`). This is a **bug on `main` today** and the
golden fixture's uncertainty string is simply too short to hit it.

Fix: do not truncate provider prose before rendering — render in full and clamp
with CSS (`-webkit-line-clamp`). Ships as its own tiny PR with a RED-first fixture.

### D-17 — Agreement card must lose green when disagreement was suppressed. ADOPTED.

`buildTrustCard({accent:"agreement", consensus: isConsensus})` derives `isConsensus`
from `result.agreement` — **not** from the evaluation signals. So a run where polar
disagreement was detected and then flattened still renders the GREEN consensus card
(e.g. 3/4) with an evaluation payload sitting beside it that says otherwise. That is
the AC-019 false-consensus failure the green rule exists to prevent.

Rule: when `signals.disagreement_suppressed === true`, the Agreement card gets
`data-consensus="false"` (losing green) and a line "Disagreement was flattened in
the synthesis." Its own commit (S3-4f) because it edits an existing surface.

### D-18 — What is IN S3 and what is SPLIT OUT.

| Item | Placement | Reason |
|---|---|---|
| DEBT-012 engine + guard | **IN S3**, first | Hard precondition; the register's expiry is literally this slice. |
| FR-016 trust surface | **IN S3** | The slice. |
| OC-5 misleading-output gate | **IN S3** | The laundering fixture is the strongest possible case for it; one deliverable, not two. |
| RB-4b (measure the NEW specs N≥10×) | **IN S3** | A spec that does not exist yet cannot be measured. |
| RB-4a (flake *mechanism*) | **SPLIT OUT, BEFORE S3** | The new S3 e2e step must inherit the policy. `retries: process.env.CI ? 2 : 0` in `e2e/playwright.config.ts:11` is disarmed only by per-step `--retries=0` discipline in `e2e.yml` (`:109`, `:126`, `:142`); a copied step that forgets it silently gets 2 masking retries. |
| DEBT-009 publication half | **SPLIT OUT, FIRST** | It starts a wall-clock sampling process. Every day it is delayed is a day the budget decision slips. |
| DEBT-009 *closure* | **NOT an S3 exit criterion** | Needs N≥20 ubuntu samples across ≥5 calendar days. Conflating publication with closure would block S3 on a 3-week window. |
| RB-6 cross-engine CSP | **SPLIT OUT, BEFORE S3** | A new CI job + one narrow spec. Must NOT run `visual-snapshots.spec.ts` (per-engine font/AA rendering can never match a chromium-seeded `*-linux.png` baseline). |
| RB-5 fault injection | **SPLIT OUT, AFTER S3** | Its most valuable assertion — "a degraded run visibly degrades the trust surface, and never gains a number" — cannot be written until the S3 surface exists. |

---

## 2. WORK ORDER

Each row is one reviewable PR. `⟶` = hard ordering dependency.

| # | PR | Scope | Blast radius |
|---|---|---|---|
| 0 | **PR-INFRA-A** — DEBT-009 publication + nightly sampler | `Makefile` (`-s` on perf-gate), `tests/perf/test_workflow_latency_percentiles.py` (`_publish`), `.github/workflows/ci.yml` (2 steps + `workflow_dispatch`), new `.github/workflows/perf-sample.yml`, new `tests/unit/test_perf_percentiles_artifact.py`, `tests/unit/test_perf_gate_runs_clean.py` (+1 test), `docs/63` DEBT-009 | CI YAML + one perf module |
| 1 | **PR-INFRA-B** — RB-4a flake mechanism ⟶ must precede PR-4 | `e2e/playwright.config.ts:11`, new `.github/workflows/flake-scan.yml`, new `tests/unit/test_e2e_flake_policy.py`, new `e2e/fixtures/stabilize.ts` (extracted), `e2e.yml` comment refresh | e2e config + new advisory job |
| 2 | **PR-INFRA-C** — ledger/doc-gate plumbing for a TypeScript slice | `tests/test_findings_ledger_consistency.py` (`ts`/`tsx` in both regexes, `S3_ARTIFACTS`, both parametrize lists), new `tests/test_e2e_workflow_covers_all_invariant_specs.py` | test-only |
| 3 | **PR-INFRA-D** — RB-6 cross-engine CSP smoke | `.github/workflows/e2e.yml` (new `csp-cross-engine` job), new `e2e/tests/invariants/csp-smoke.spec.ts` | one CI job |
| 4 | **PR-FIX-1** — D-16 truncation markdown leak (bug on `main`) | `app.js` (drop `truncateText` on the caption), `app.css` (line-clamp), `e2e/fixtures/golden-run.ts` (long uncertainty with a straddling bold run) | tiny |
| 5 | **PR-S3-1** — DEBT-012 engine | `src/product_app/evaluation.py`, `src/product_app/query_runs.py`, 4 test modules, `openapi.yaml` | backend only, no UI |
| 6 | **PR-S3-2** — D-4 stub-URL reclassification (separable, abort-gated) | `evaluation.py` census only, 1 test renamed | backend only |
| 7 | **PR-S3-3** — docs-before-code, **one atomic commit** | `docs/10`, `docs/12`, `docs/17`, `docs/18`, `docs/54`, `docs/61`, `docs/64`, `docs/40`, `docs/42`, `docs/20`, `docs/21` | docs only |
| 8 | **PR-S3-4** — the trust surface + gates | `workspace.html`, `app.js`, `app.css`, `e2e/fixtures/golden-run.ts`, `e2e/pages/WorkspacePage.ts`, 4 e2e specs, `.github/workflows/e2e.yml`, `.github/workflows/seed-visual-baselines.yml` | the slice |
| 9 | **PR-S3-5** — ledger flips + RB-4b measured rows | `docs/analysis/R2-plan-review-findings.md`, `docs/63`, `docs/00`, `docs/metrics/flake-rate.md` | docs only |
| 10 | **PR-POST-A** — RB-5 fault-injection lane | new `tests/integration/test_fault_injection_lane.py`, `degraded-banner.spec.ts` +1 | backend + 1 spec |
| 11 | **PR-POST-B** — DEBT-009 re-promotion | gated on N≥20 ubuntu samples; **not** on the S3 calendar | budget constants |

Ordering rationale: 0 first (starts the clock), 1–3 before 8 (the S3 specs must
inherit the flake policy, the ledger must be able to cite a `.ts` file, and a new
spec must be provably wired), 7 before 8 (`make fr-completeness` is in the
`make validate` chain — see D-19 below), 10 after 8 (needs the surface).

### D-19 — docs/10 + docs/17 + docs/18 + docs/12 land in ONE commit.

`Makefile:63` — `validate: check-python fr-completeness`; `Makefile:72-73` runs
`scripts/validate_fr_completeness.py`. It fails the instant `## FR-016` exists in
`docs/10` without a complete row in **both** `docs/17` and `docs/18`. Splitting the
doc work across commits leaves the tree red.

**Also:** both evidence rows must sit INSIDE the title section.
`docs/17-requirement-registry.md:33` is `## Registry Notes` and
`docs/18-requirement-traceability-matrix.md:33` is `## Traceability Notes`;
`evidence_table()` slices `title_section(text)` (H1 → next heading), so a row
appended after those headings is invisible to the gate and the build stays red with
a confusing MISSING message.

---

## 3. PER-ITEM SPEC

Format per item: **files** · **tests + names + assertions** · **RED proof** (what
must fail before the change) · **BITE proof** (the source mutation that must turn
each test red).

---

### PR-INFRA-A — DEBT-009 publication + nightly sampler

**Root cause, mechanically identified:** the two `[PERF] …` lines are ordinary
`print()` calls in `tests/perf/test_workflow_latency_percentiles.py` (≈`:268`,
`:297`) and `make perf-gate` (`Makefile:173`) runs pytest with `-q --no-cov` and no
`-s`/`-rP`, so capture swallows them on every PASSING run. The numbers surface only
inside a failure report — i.e. exactly when the gate is already red.

**Files.**
1. `Makefile:173` — add `-s` to the perf-gate pytest invocation. Do **not** touch
   `PERF_MIN_TESTS` (`:30`), `PERF_REQUIRED_SPECS` (`:43`), `PERF_MIN_EXECUTED`
   (`:162`), or the `perf collects 11 (tests/perf 10 + tests/performance 1)`
   comment (`:18-19`).
2. `tests/perf/test_workflow_latency_percentiles.py` — module-level
   `_publish(section: str, payload: dict) -> None` that merge-writes
   `build/gates/perf-percentiles.json` (mkdir-p, read-if-exists, update, write) with
   `sequential.{n,min,p50,p95,max}`, `concurrent.{n,p50,p95,max}` and a `meta` block
   (`platform.platform()`, `os.cpu_count()`, `sys.version`, `GITHUB_RUN_ID`,
   `GITHUB_SHA`, `RUNNER_OS`, UTC timestamp). Called from the two **existing**
   tests, **before** their budget asserts, so an over-budget sample is still
   published.
3. `.github/workflows/ci.yml` perf-gate job — two new steps, both
   `if: always()`: cat the JSON to stdout + `$GITHUB_STEP_SUMMARY`; then
   `actions/upload-artifact@v4`, name
   `perf-percentiles-${{ github.run_id }}-${{ github.run_attempt }}`,
   `if-no-files-found: error`. **`if: always()` is mandatory** — the job's
   `continue-on-error: true` is job-level, so a budget failure fails the
   `make perf-gate` STEP and would skip every following step, losing precisely the
   over-budget sample that matters most. Add `workflow_dispatch:` to `on:`.
4. New `.github/workflows/perf-sample.yml` — `perf-sample`, cron `0 4 * * *` +
   `workflow_dispatch`, `continue-on-error: true`, runs `make perf-gate` and
   uploads the same JSON. Separate file so the cron never appears as a PR check.

**CRITICAL — do not add a test under `tests/perf/`.** `PERF_MIN_TESTS ?= 11`
(`Makefile:30`) is asserted for **equality** by
`tests/unit/test_perf_gate_collection_floor.py` (`assert floor == perf_collected`),
the Makefile prose is re-parsed by the same module, `PERF_MIN_EXECUTED` is derived
as `PERF_MIN_TESTS - 1`, and `PERF_REQUIRED_SPECS` pins
`tests/perf/test_workflow_latency_percentiles.py:2` as a per-file count. One new
test there reds three unit tests at once.

**CRITICAL — do not touch the honest-baseline docstring.**
`tests/perf/test_perf_baseline_is_honest.py` parses it with
`_ENVELOPE_RE = ^\s{4}(p50|p95|max)\s*:\s*([\d.]+)\s*-\s*([\d.]+) ms` and a
`_BUDGET_RE` over `^\s{4}(NAME_BUDGET_MS) = N   ~Mx worst observed …`, slicing
`text[start:start+600]` from the **first** `text.index(heading)`; and it asserts
`set(budgets)` is an **exact** three-element set, so a fourth matching line fails.
`tests/test_findings_ledger_perf_numbers.py` re-imports that parser and cross-checks
the RB-2 ledger cell. So: change no budget constant, add no 4-space-indented
`pNN : a - b ms` line inside the first 600 chars after either section heading, add
no 4-space-indented `NAME_BUDGET_MS = N  ~Mx …` line, and do not repeat either
section heading above the real block.

**Tests.**
- New `tests/unit/test_perf_percentiles_artifact.py` (deliberately **outside**
  `PERF_TEST_PATHS`):
  - `test_publish_merges_both_sections_into_one_json` — two `_publish` calls into
    `tmp_path` round-trip with all required keys and a `meta` block.
  - `test_both_latency_tests_publish` — text/AST assert that both existing test
    functions reference `_publish`.
  - `test_ci_uploads_the_percentiles_artifact_even_on_failure` — `ci.yml`'s
    perf-gate job contains an upload step for
    `build/gates/perf-percentiles.json` with `if: always()`.
  - `test_the_perf_gate_job_is_still_advisory` — the job still carries
    `continue-on-error: true` (the mechanism ships OFF).
- `tests/unit/test_perf_gate_runs_clean.py` — add
  `test_make_perf_gate_reaches_the_measurement_stage` with **no** `skipif`: runs
  `make perf-gate` once; asserts `perf-gate: 11 tests collected` and `0 skipped`
  appear; asserts **both** `[PERF] sequential` and `[PERF] concurrent` appear in
  stdout; asserts `build/gates/perf-percentiles.json` parses with the required keys;
  and asserts that a non-zero exit code contains `regressed:` — a budget assertion
  is the only tolerated failure, anything else is a hard red. Keep the existing
  `test_make_perf_gate_is_green_on_a_clean_tree` `skipif`'d; delete the skipif and
  the `regressed:` escape hatch together in PR-POST-B.
  *Why this matters:* the existing clean-tree test is **unreachable in every lane**
  — it skips unless `QUORUM_RUN_PERF_BUDGET` is set, `make test` never sets it, and
  `make perf-gate` sets it only for `PERF_TEST_PATHS`, which excludes `tests/unit`.
  The one guard that executes the recipe end-to-end currently protects nothing.

**RED proof.** Before the `-s` change:
`QUORUM_RUN_PERF_BUDGET=1 uv run pytest tests/perf/test_workflow_latency_percentiles.py -q --no-cov | grep 'PERF\]'`
returns nothing (measured). After: two lines.
`test_make_perf_gate_reaches_the_measurement_stage` fails on `[PERF] sequential`
before the change.

**BITE proof.** Remove `-s` from `Makefile:173` ⇒ the `[PERF]` assertion reds.
Delete one `_publish` call ⇒ `test_both_latency_tests_publish` and the JSON-key
assertion red. Change `if: always()` to nothing ⇒ the upload test reds.

**Budget derivation rule for PR-POST-B — write it into `docs/63` now.**
Budgets are NOT derived from the macOS envelope (seq p50 40.3–44.1 / p95 42.2–82.3 /
conc p95 394.3–648.0 ms) nor from the single `423.6 ms` figure — both are recorded
as EXCLUDED, with the reasons "wrong target" and "n=1, unsourced" (grep for
`423.6` finds it only in prose, with no run id, no n, no artifact).
1. N ≥ 20 ubuntu-latest samples from `perf-percentiles.json` artifacts, spanning
   ≥ 5 calendar days and both weekday and weekend buckets (runner contention is
   diurnal). Publish **all** raw samples in a table in `docs/63` — none discarded,
   outliers kept and annotated.
2. `candidate = round_up_to_next_50ms(1.5 × max(observed))`. The multiplier is a
   recorded decision; the max is a measurement.
3. Prove the candidate BITES on CI: re-run the existing injection method (a
   throwaway pytest plugin sleeping inside `produce_initial_answer`) at +150 ms and
   +300 ms per call on the ubuntu runner and record which budgets catch which. If
   sequential p50 no longer catches +150 ms/call, the budget is too loose — grow N,
   do not grow the multiplier.
4. Ship the mechanism OFF: land the candidates as a non-asserting
   `[PERF-CANDIDATE] p95=X vs candidate=Y (would PASS/FAIL)` print + JSON field; run
   ≥ 10 consecutive nightly samples with zero "would FAIL"; **then** flip
   `continue-on-error` off in a separate PR.
5. Human sign-off recorded in `docs/63` with the raw table and the artifact run ids.

---

### PR-INFRA-B — RB-4a flake mechanism

**Files.**
- `e2e/playwright.config.ts:11` → `retries: Number(process.env.PW_RETRIES ?? 0)`.
  Zero is now the default; masking is explicit opt-in. Update the stale comment at
  `.github/workflows/e2e.yml` ≈`:36-38` to describe the config, not the flags.
- New `.github/workflows/flake-scan.yml` — job `flake-scan`,
  `name: Flake scan N=10 (advisory)`, `schedule: cron '0 5 * * *'` +
  `workflow_dispatch`, `continue-on-error: true`, matrix over the timing-sensitive
  specs (`tests/invariants/rendering-invariants.spec.ts` — it asserts a *monotonic*
  elapsed timer, the one genuinely timing-dependent contract;
  `tests/invariants/real-integration-smoke.spec.ts`; plus the S3 trust specs added
  in PR-S3-4). Command:
  `npx playwright test ${{ matrix.spec }} --project=chromium --retries=0 --repeat-each=10 --reporter=junit`.
  `--repeat-each` is the built-in vehicle; do not roll a bash loop.
- New `e2e/fixtures/stabilize.ts` — extract the duplicated `FREEZE` constant +
  `stabilize(page)` + `masks(page)` from
  `e2e/tests/invariants/visual-snapshots.spec.ts` ≈`:22-42` and
  `e2e/tests/accessibility/axe-all-views.spec.ts` ≈`:120-126`; both existing specs
  import it unchanged. A divergent freeze between a new spec and the baseline it
  compares against is itself a flake source.

**Tests.** New `tests/unit/test_e2e_flake_policy.py` (Python, in the default
blocking suite — same text-assertion pattern as
`tests/unit/test_makefile_gate_integrity.py`):
- `test_playwright_default_retries_is_zero`
- `test_every_playwright_invocation_in_e2e_yml_passes_retries_zero`
- `test_a_flake_scan_workflow_exists_with_repeat_each_at_least_ten`
- `test_the_cross_engine_job_never_runs_visual_snapshots` (also pins D-18's
  no-cross-engine-screenshots rule for PR-INFRA-D)

**RED proof.** Point the third test at the repo before `flake-scan.yml` exists ⇒
fails. **BITE proof.** Restore `retries: process.env.CI ? 2 : 0` ⇒ test 1 reds. Drop
`--retries=0` from one `e2e.yml` step ⇒ test 2 reds.

**Flake policy, recorded under RB-4 in the ledger as a table**
(`spec | runs | failures | rate | date | run id`): `>0/10` failures ⇒ the spec is
**QUARANTINED** (moved behind a `@flaky` tag excluded from the blocking steps) with
a ledger row and an owner. Never a retry. Never a widened timeout.

---

### PR-INFRA-C — ledger/doc-gate plumbing for a TypeScript slice

**Files.** `tests/test_findings_ledger_consistency.py`:
1. `_PROOF_POINTER_RE` (`:142`) — add `ts|tsx`:
   `re.compile(r"`([^`]+?\.(?:py|md|toml|json|ya?ml|ts|tsx))`")`.
   Today it cannot match a `.ts` file, so **every S3 ledger row that flips to DONE
   citing only TypeScript artifacts fails the build.**
2. `_DEBT_PROOF_PATH_RE` (`:355`) — add `ts|tsx` alongside the existing
   `js|css|html`. Today a `docs/63` row citing a `.ts` file fails **open** (silently
   unchecked).
3. New `S3_ARTIFACTS: dict[str, tuple[str, ...]]` mapping
   `OC-5` → the misleading-output spec; `RB-4` → `flake-scan.yml` +
   `docs/metrics/flake-rate.md`; `RB-5` → the fault-injection lane; `RB-6` → the
   cross-engine spec (or the ADR). Merge into `_registered_proofs()` (`:150`).
4. **Both** `@pytest.mark.parametrize("item", sorted(PHASE0_ARTIFACTS | S2_ARTIFACTS))`
   decorators (`:191`, `:248`) → `| S3_ARTIFACTS`, and the `built = …` expression
   (`:195`) and baseline probe (`:260`) likewise. Without this S3 rows get only the
   weakest of the four ledger rules — which is how a DONE-without-artifact row ships
   green.

**Tests.** New `tests/test_e2e_workflow_covers_all_invariant_specs.py`:
- `test_every_invariant_spec_is_named_in_the_e2e_workflow` — glob
  `e2e/tests/invariants/*.spec.ts`, assert each basename appears in
  `.github/workflows/e2e.yml`. **This is the structural fix for UI-1:** `e2e.yml`
  enumerates spec PATHS (`:102-109`, `:124`, `:140`) — there is no glob, no
  `testDir` run — so a new spec is committed, green locally, and **never executed
  in CI**.
- `test_every_snapshot_dir_has_at_least_one_linux_baseline` — each
  `*-snapshots` dir under `e2e/tests/invariants/` holds ≥1 `*-chromium-linux.png`.

**RED proof.** Add a stub `e2e/tests/invariants/zz-unwired.spec.ts` ⇒ the first test
fails naming it; delete the stub ⇒ green. For the regex: point an S3 DONE row at
`e2e/tests/invariants/does-not-exist.spec.ts` ⇒
`test_done_rows_cite_an_existing_proof_pointer` fails; point it at the real spec ⇒
green.

**Anti-vacuity.** Run
`uv run pytest tests/test_findings_ledger_consistency.py -q --collect-only` and
confirm `OC-5`, `RB-4`, `RB-5`, `RB-6` actually appear as parametrized cases.

---

### PR-INFRA-D — RB-6 cross-engine CSP smoke

**Restated correctly.** The ledger row says "Chromium-only E2E", which mis-locates
the defect: `e2e/playwright.config.ts` already defines `chromium`, `firefox`,
`webkit` and `mobile` projects. The constraint is entirely in the workflow —
`e2e.yml` ≈`:92` installs chromium only, and `:109`/`:125`/`:141` pin
`--project=chromium`. **The fix is a workflow job, not new projects.**

**Files.** `.github/workflows/e2e.yml` — new BLOCKING job `csp-cross-engine`,
`name: Cross-engine CSP smoke (webkit + firefox)`,
`strategy: matrix: browser: [webkit, firefox]`,
`npx playwright install --with-deps ${{ matrix.browser }}`, running **only**
`tests/docs/docs-under-csp.spec.ts` and the new
`e2e/tests/invariants/csp-smoke.spec.ts` with
`--project=${{ matrix.browser }} --retries=0`. Blocking from day one — CSP
conformance is deterministic, not timing-sensitive.

**HARD EXCLUSION.** The job MUST NOT run `visual-snapshots.spec.ts` and MUST NOT
contain any `toHaveScreenshot` call. The committed `*-linux.png` baselines were
seeded in the chromium container; font/antialiasing/scrollbar rendering differs per
engine, so a webkit/firefox screenshot can never match. Pinned by
`tests/unit/test_e2e_flake_policy.py::test_the_cross_engine_job_never_runs_visual_snapshots`.

**New spec** `e2e/tests/invariants/csp-smoke.spec.ts`: load `/ui`, drive
`driveToResult` with the golden fixture, assert zero CSP-violation console errors,
assert the primary landmark and `#result-trust` render. No pixel comparison.

**RED proof.** Run it locally under `--project=webkit` against a deliberately broken
CSP directive ⇒ fails. **BITE proof.** Add `style-src 'self'` (dropping
`'unsafe-inline'`) to `main.py` ⇒ the console-error assertion reds on webkit.

**If cross-engine is declined instead**, record the accepted risk plus the
compensating control in `docs/adr/0003-chromium-only-e2e.md` and cite that path in
the RB-6 ledger flip. Either way the cited path must exist and be non-empty.

---

### PR-FIX-1 — the truncation markdown leak (D-16)

**Files.**
- `src/product_app/static/app.js` ≈`:2596-2600` — remove the
  `truncateText(uncertaintyText, 180)` call; pass the full string to
  `buildTrustCard({caption})`.
- `src/product_app/static/app.css` — add `-webkit-line-clamp: 4; display: -webkit-box;
  -webkit-box-orient: vertical; overflow: hidden;` to `.result-trust-caption`.
- `e2e/fixtures/golden-run.ts` — lengthen `goldenSynthesis().uncertainty` past 180
  characters with a `**bold**` run **straddling character 180**.

**Test.** No new spec: the existing
`e2e/tests/invariants/rendering-invariants.spec.ts` no-raw-markdown walk over
`#main-content` catches it once the fixture reaches the defect.

**RED proof.** Commit the fixture change alone on `main` ⇒
`rendering-invariants.spec.ts` fails on `bold asterisks (**)` inside
`.result-trust-caption`. **BITE proof.** Reinstate `truncateText(..., 180)` ⇒ red
again.

---

### PR-S3-1 — DEBT-012 engine

**Files.**

`src/product_app/evaluation.py`
- `MarkerCensus` model + `citation_marker_census(*, scopes)` extracted from the loop
  at ≈`:353-370` (the `total = 0 / resolved = 0` block, whose off-run branch is the
  bare `# else: an off-run URL. UNKNOWN, not zero` comment).
- `citation_marker_grounding` reimplemented over the census. **Value semantics
  unchanged.**
- `unverifiable_marker_count` / `unverifiable_marker_ratio` added to `LayerASignals`
  (≈`:645`), populated in `evaluate_layer_a` from the one census (≈`:845`, replacing
  `grounding = citation_marker_grounding(scopes=scopes)` with a census call and a
  derivation).
- `PresentationConfidence` + `presentation_confidence(...)` per D-1.4.
- `compute_composite` (≈`:1314`) excludes `citation_marker_grounding` from `values`
  when `unverifiable_marker_count > 0`, per D-1.5.
- `EVAL_SCHEMA_VERSION` (`:63`) → `"s3-eval-v3"`.
- No change to `classify_faithfulness` or `classify_hallucination_risk`. No change to
  `LAYER_A_WEIGHTS`.
- Export the new names in `__all__`.

`src/product_app/query_runs.py`
- `QueryRunEvaluationProjection` (≈`:283`) gains
  `label_confidence: PresentationConfidence` **with no default**.
- `_evaluation_projection` (≈`:1575`) populates it from `presentation_confidence(...)`.
- `openapi.yaml` regenerated (`make openapi-export`).

**Test modules.**

`tests/unit/test_evaluation_layer_a.py` (RED-first, then AMEND):
- `test_the_marker_census_separates_resolved_unresolved_and_unverifiable` — the
  laundering shape (1 resolving ordinal + 20 off-run links per slot × 4 slots) gives
  `resolved=4, unresolved=0, unverifiable=80`.
- `test_unverifiable_marker_ratio_is_None_when_the_prose_has_no_markers_at_all`.
- `test_one_off_run_url_beside_one_resolving_ordinal_is_already_indeterminate` —
  **dose 1**, ratio exactly 0.5, measured today as `faithful`/`low`. This is the
  case a dominance cut misses; it is why D-1.4 is zero-tolerance.
- `test_the_corpus_confident_cases_keep_their_reportable_presentation` — asserts
  `unverifiable_marker_count == 0` for the `faithful-consensus` and
  `preserved-polar-disagreement` corpus cases, quoting today's measured censuses
  (17 resolved / 3 unresolved / 0 unverifiable, and 11 / 2 / 0) in the docstring,
  same pattern as `test_the_measured_separation_comment_quotes_todays_measurement`.
  **This is the under-claim-cost measurement, gated so it cannot rot.**
- **AMEND** `test_a_run_whose_only_markers_are_off_run_urls_is_unknown_not_zero`
  (≈`:207`) — keep all three existing assertions; append
  `assert evaluation.signals.unverifiable_marker_count == 4` and a
  `presentation_confidence(...) == "reportable"` assertion (labels are
  `partial`/`medium`, i.e. already a warning — the guard must NOT suppress it).
  Append to the docstring: *"the ENGINE label is unchanged and still wrong; what
  closes the S3 exposure is the presentation guard asserted below."*
- **AMEND** `test_one_resolving_ordinal_launders_many_off_run_urls_to_maximum_trust`
  (≈`:501`) — keep all three existing assertions; append
  `assert evaluation.signals.unverifiable_marker_count == 80`,
  `assert evaluation.signals.unverifiable_marker_ratio == pytest.approx(80 / 84)`,
  `assert presentation_confidence(...) == "indeterminate"`, and the same docstring
  line.

New `tests/unit/test_evaluation_presentation_confidence.py`:
- `test_presentation_is_indeterminate_whenever_any_unverifiable_marker_exists_and_the_labels_are_confident`
- `test_a_warning_label_is_NEVER_suppressed` — `unfaithful`/`high` with 80
  unverifiable markers still returns `"reportable"`.
- `test_no_marker_mix_can_present_confidently_while_unverifiable_markers_exist` —
  hypothesis strategy over `(n_resolving_ordinals 0..10, n_out_of_range 0..10,
  n_off_run_urls 0..30)`; every draw with `off_run_urls > 0` whose labels are
  `faithful` or `low` must be `"indeterminate"`.
- `test_the_signal_strategy_reaches_the_confident_region` — anti-vacuity guard,
  driving the strategy itself (order-, selection- and randomisation-independent),
  the pattern already used in `tests/unit/test_evaluation_refusal_decoupling.py`.
- `test_the_guard_is_monotone_downward` — over the same strategy, the presented
  state is never more confident than the raw label.

New/extended composite tests (`tests/unit/test_evaluation_composite.py` or the
existing composite module):
- `test_grounding_is_EXCLUDED_from_the_composite_when_unverifiable_markers_exist` —
  the laundering run's composite moves off today's measured **82.5** and no longer
  sits inside the genuine-faithful band (measured **83.50** / **83.38**). Quote all
  three numbers in the docstring.
- `test_the_contribution_list_omits_grounding_on_an_indeterminate_run` — the "why"
  surface can never name citation grounding at value 1.0 on a 95%-fabricated run.

`tests/unit/test_evaluation_refusal_decoupling.py` — **INV-5**:
- `test_inv5_the_unverifiable_marker_count_is_built_independently_of_the_refusal_booleans_and_of_the_labels`
  — hypothesis property over generated scopes: `unverifiable_marker_count` equals a
  straight recount of off-run URL markers, unaffected by refusal text or by any
  classifier output. **Prove it bites** by monkeypatching a refusal-keyed
  suppression of the census into `evaluate_layer_a`.
  *Why:* INV-1/2/3 constrain the classifiers only, and DEBT-011 round 3 measured that
  a refusal-keyed override moved one level upstream (into signal construction)
  re-opened the laundering with the entire suite green. A guard reading only
  classifier outputs repeats that exact shape.

`tests/integration/test_query_run_evaluation_endpoint.py`:
- Extend the served-projection test: `assert served["label_confidence"] in
  {"reportable", "indeterminate"}`.
- `test_a_laundered_run_is_served_as_indeterminate`.
- `test_the_persisted_eval_json_key_set_is_unchanged_by_the_new_signals` — guards
  ≈`:112-119`.
- `test_an_s2_eval_v2_row_missing_the_new_signals_is_presented_as_indeterminate` —
  D-3 / D-7, across the persistence boundary (nothing re-validates on read:
  `run_history_store.py` ≈`:380` is a bare `json.loads`).
- **D-10, written so it bites:**
  `test_a_non_terminal_run_writes_nothing_and_logs_no_warning` — call
  `qr._persist_run_evaluation(query_run=<non-terminal run>, agreement=<summary>)`
  with monkeypatched spies on `qr._update_run_evaluation` and
  `qr._record_feedback_event`; assert **(a)** both spies got 0 calls **and (b)**
  `caplog` at WARNING contains **no** record matching
  `run evaluation persistence failed`. Assertion (b) is load-bearing: without it the
  test is green on both source and mutant.

New `tests/contract/test_evaluation_signal_schema_additive.py` (D-9):
- Freeze the PRE-S3 `required` and `properties` sets of `LayerASignals`,
  `QueryRunEvaluationProjection`, `TrustScore`, `TrustDiagnostics` read off
  `app.openapi()["components"]["schemas"]`; assert the two new signals are absent
  from `required`. Mirror
  `tests/contract/test_query_run_evaluation_additive.py` ≈`:75-81`.
- **Raise `CONTRACT_MIN_TESTS` (`Makefile:31`, currently 18)** to the new collected
  count, or the `api-contract` min-collected gate under-counts.

New `tests/integration/test_evaluation_carries_no_prose.py` (D-15, PII):
- Drive a terminal run whose `query_text` and every answer/synthesis body embed a
  unique sentinel; assert the sentinel is absent from (a) the serialized
  `evaluation` field of the `/result` response, (b) the persisted
  `eval_json`/`trust_json`, (c) the captured `run_evaluated` feedback payload.

**RED proof (PR-S3-1 as a whole).** On `a1cf546`: the census test fails
(`citation_marker_census` does not exist); the dose-1 test fails
(`presentation_confidence` does not exist); the composite test fails (laundering
composite is 82.5, inside the faithful band); the projection test fails
(`label_confidence` absent).

**BITE proofs.**
| Mutation | Reds |
|---|---|
| `unverifiable` never incremented in the census | census test, both amended tests, INV-5 |
| `presentation_confidence` returns `"reportable"` unconditionally | the hypothesis property, both amended tests, the endpoint test |
| Drop the `hallucination_risk == "low"` disjunct | the dose-1 test (a run can be `partial`/`low`) |
| Add a `> 0.5` dominance cut | the dose-1 test (ratio exactly 0.5) |
| Remove the `compute_composite` exclusion | the composite test and the contribution-list test |
| Declare a new signal as `int` (no default) | `test_evaluation_signal_schema_additive` |
| Add `"query": query_run.query_text` to the feedback payload (`query_runs.py` ≈`:1491`) | `test_evaluation_carries_no_prose` |
| Delete the non-terminal guard (`query_runs.py` ≈`:1477-1478`) | the caplog assertion in the D-10 test |
| Monkeypatch a refusal-keyed census suppression into `evaluate_layer_a` | INV-5 |

---

### PR-S3-2 — stub-URL reclassification (D-4, abort-gated)

**File.** `src/product_app/evaluation.py` — in `citation_marker_census`, a URL
marker that normalises to a **placeholder** source present on this run is counted as
`unresolved` (denominator), not `unverifiable`. Everything else unchanged.

**Test.** `tests/unit/test_evaluation_layer_a.py` ≈`:418` — rename
`test_a_simulated_stub_cited_BY_URL_does_not_ground_either` →
`test_a_simulated_stub_cited_BY_URL_is_resolvable_as_FALSE_not_unknown`; flip
`is None` → `== pytest.approx(0.0)`; keep the second half (a real Tavily page cited
by URL still resolves 1.0) byte-identical. Docstring records the old name and the
symmetry restored with `test_fallback_sources_do_not_ground_a_marker` (≈`:314`),
which already scores the ORDINAL form of the identical run 0.0.

**RED proof.** Flip the assertion first ⇒ fails on `a1cf546`. **BITE proof.** Revert
the census change ⇒ red.

**ABORT.** Immediately run
`uv run pytest tests/evals/ tests/unit/test_evaluation_layer_a.py tests/unit/test_evaluation_composite.py -q`.
If **any** corpus label moves, revert this PR and record the stub-URL asymmetry as a
DEBT-012 residual line instead. Nothing downstream depends on it.

---

### PR-S3-3 — docs-before-code (see §4 for the literal text)

One atomic commit: `docs/10`, `docs/12`, `docs/17`, `docs/18`, `docs/54`, `docs/61`,
`docs/64`, `docs/40`, `docs/42`, `docs/20`, `docs/21`.

**Gate proof.** Run `make fr-completeness` **before** and **after**; record both
counts (it currently reports the pre-FR-016 total; FR-016 adds one). Then update the
quoted count in `docs/00-factory-console.md` ≈`:137` and in the ledger's EN-2 row
≈`:102` to the **re-measured** value. Do not hand-edit `docs/00` as a durable
record — `make next` regenerates it; the ledger PHASE STATUS block is authoritative.

---

### PR-S3-4 — the trust surface + gates

**`src/product_app/templates/workspace.html`** — immediately after the
`#result-trust` div (≈`:502`), as a **sibling**:

```html
<section
  id="result-trust-score"
  class="result-trust-score"
  role="group"
  aria-label="What was and was not checked"
  hidden
></section>
```

No `role="meter"`, no `role="progressbar"`, no `aria-valuenow`. No inline `style=`
attribute. Any decorative graphic is `aria-hidden="true"`, mirroring the existing
ring (`app.js` ≈`:2058`).

**`src/product_app/static/app.js`** — `renderTrustScore(result)`, called from
`renderResult` alongside `renderTrustTriangle` (≈`:2201`):

```js
function renderTrustScore(result) {
  const box = el("result-trust-score");
  if (!box) return;
  box.textContent = "";          // reset UNCONDITIONALLY, before any early return
  box.hidden = true;             // (D-12: renderResult has three call sites)
  box.removeAttribute("data-state");

  const ev = result && result.evaluation;
  if (!ev || typeof ev !== "object") return;     // D-14: absent ⇒ hidden, zero text
  const sig = ev.signals && typeof ev.signals === "object" ? ev.signals : null;
  if (!sig) return;

  const reportable = ev.label_confidence === "reportable";   // D-3: WHITELIST
  // ... state line, why lines, missing-caveat row — all via textContent/mkEl
  box.hidden = false;
}
```

Rules already fixed by §1: D-2 (R1–R4 + the state table + `TRUST_WHY`), D-3
(whitelist), D-5 (no `judge` identifier anywhere in `app.js`), D-14, D-15
(`textContent`, never `setProse`/`setInlineProse`).

**`src/product_app/static/app.css`** — `.result-trust-score*` classes; band colour
via a CSS custom property so the D-6 guard can audit it; light + dark; **no new
green token** and no reference to `--c-green` / `--success` / `--verdict-surface` /
`--shadow-verdict` anywhere under `result-trust-score`.

**D-17 (own commit within this PR).** `renderTrustTriangle`: when
`result.evaluation && result.evaluation.signals.disagreement_suppressed === true`,
pass `consensus: false` to the Agreement card and append the line
`Disagreement was flattened in the synthesis.`

**`e2e/fixtures/golden-run.ts`** (D-13):
- `goldenEvaluation(overrides = {})` returning the exact
  `QueryRunEvaluationProjection` shape — `schema_version: "s3-eval-v3"`, all
  sixteen `signals` fields, `faithfulness_label`, `hallucination_risk`,
  `label_confidence`, and
  `trust: { support_verified: false, band: "unverified", score: null,
  diagnostics: { layer_a_composite_unverified: 73.4,
  contributions: [{signal: "live_ratio", weight: 0.2, value: 1.0,
  contribution: 21.5}, …] } }`. **The distinctive 73.4 / 21.5 are deliberate** —
  they are what the no-digits invariant searches for.
- `withEvaluation(resp, ev)`.
- Six named variants: `EVAL_CLEAN`, `EVAL_NON_CONSENSUS`,
  `EVAL_UNKNOWN_GROUNDING_REFUSAL` (`citation_marker_grounding: null`,
  `refusal_detected: true`, `run_wholly_refused: true`, `hallucination_risk: "low"`,
  `faithfulness_label: "partial"`), `EVAL_LAUNDERED` (grounding 1.0,
  `unverifiable_marker_count: 80`, ratio `80/84`, `faithful`, `low`,
  `label_confidence: "indeterminate"`), `EVAL_MISSING_HIGH_STAKES`
  (`required: true, present: false`), `EVAL_SUPPRESSED_DISAGREEMENT`
  (`disagreement_suppressed: true`, run agreement `{aligned: 3, total: 4}`), plus a
  raw `EVAL_S2_SHAPED` payload with `label_confidence` **deleted** (the fail-closed
  case). `goldenCompletedResp()` gains **no** `evaluation` key.

**`e2e/pages/WorkspacePage.ts`** — add `trustScoreSurface()`, `trustStateLine()`,
`trustWhyLines()`, `missingHighStakesWarning()`. **Deliberately no numeric
`trustScore()` accessor** — the page object must not be able to express a
confidence number.

**New `e2e/tests/invariants/trust-score-invariants.spec.ts` (BLOCKING).**
Parameterised over viewports `[375, 768, 1440]` × themes `["light", "dark"]`
(set via `document.documentElement.setAttribute("data-theme", t)`, the pattern at
`axe-all-views.spec.ts` ≈`:128`; CI passes `--project=chromium` only, so the
`mobile` project never runs — viewports must be driven in-spec via
`page.setViewportSize`, as `visual-snapshots.spec.ts` ≈`:48` already does):
1. `no digits anywhere in the trust-score surface` — innerText `!~ /\d/`, for all
   six fixture variants. (R1)
2. `no confident label words` — the R2 regex, all six variants.
3. `no raw signal identifiers` — the R3 list.
4. `the standing disclosure is present` — the R4 literal.
5. `GREEN RULE — no green paint anywhere in the trust-score subtree, in either theme`
   — the full D-6 guard.
6. `no ARIA value-widget lie` — no descendant has a role in
   `{meter, progressbar, slider}` and no `aria-valuenow`/`aria-valuetext`
   anywhere in the subtree.
7. `computed style matches the token source` — font-family/size/weight and text
   colours compared to values resolved from `:root` via a new
   `e2e/fixtures/tokens.ts` `readTokens(page, names[])` helper. **Retyped hex
   literals are rejected in review.**
8. `no overlap inside #main-content` — pairwise `boundingBox()` intersection
   `<= 1px²` across the visible direct children of `#result-verdict`,
   `#result-trust` and `#result-trust-score`; skip `position: absolute|fixed`
   elements only if explicitly id-allow-listed. (The only existing layout invariant
   is a **document-level** `scrollWidth > clientWidth + 1` check —
   `rendering-invariants.spec.ts` ≈`:183-189`, which by construction cannot catch a
   clipped or overlapping CHILD. At 375px `.result-trust` has already collapsed to
   one column at the 760px breakpoint, `app.css` ≈`:2786`, so the cards stack and the
   new surface is appended beneath them.)
9. `no clipping or truncation` — `scrollWidth <= clientWidth + 1` **and**
   `scrollHeight <= clientHeight + 1` on `#result-trust-score` and each
   `.result-trust-card`; and the rendered state line equals the fixture's expected
   string exactly (a `text-overflow` ellipsis leaves the full text in the node, so
   the scrollWidth check is the one that bites).
10. `an absent evaluation renders nothing` — three payloads (`evaluation: null`, key
    omitted, `evaluation: {}`): `#result-trust-score` is hidden and `#main-content`
    innerText matches none of `/unverified|faithful|low risk|checked/i`.
11. `the fail-closed case degrades` — `EVAL_S2_SHAPED` (no `label_confidence`)
    renders the indeterminate state line.

**New `e2e/tests/invariants/trust-score-visual.spec.ts` (BLOCKING).**
`expect(page.locator("#result-trust-score")).toHaveScreenshot(
"trust-score-{light,dark}-{375,768,1440}.png", { maxDiffPixels: N })`, importing the
shared `stabilize()`/`masks()` from PR-INFRA-B. **`maxDiffPixels`, not a ratio:**
the existing `maxDiffPixelRatio: 0.01` (`visual-snapshots.spec.ts` ≈`:54`) with
`fullPage: true` tolerates **42,379 changed pixels** on the result view (measured:
`result-verdict-chromium-linux.png` is 1440×2943 = 4,237,920 px), so a 240×80 chip
can render completely wrong — or not at all — and the gate stays green. `N` is set
by the plan's own baseline-then-set rule from an N≥10× re-run of the unchanged spec
in the CI container. Also assert non-visually that the surface `toBeVisible()` and
its innerText is non-empty, so a **vanished** surface fails deterministically rather
than statistically. **This is the first dark-theme pixel coverage in the repo** —
`visual-snapshots.spec.ts` never sets `data-theme`.

**`e2e/tests/degraded/degraded-banner.spec.ts`** — append
`test.describe("misleading-output gate (OC-5)")` reusing the existing
`driveWithCompleted(page, completed)` helper (≈`:30`):
- `a fully-LIVE unfaithful run renders the caution treatment` — `demo_mode: false,
  live_count: 4, local_count: 0` (so the existing simulated path **cannot** fire) +
  `faithfulness_label: "unfaithful", hallucination_risk: "high"`. This is what makes
  the gate a genuinely NEW faithfulness-driven one rather than a rename.
- `the laundered evaluation renders the degraded treatment and no confident token` —
  `EVAL_LAUNDERED`; surface state is indeterminate and innerText contains no `100`,
  no `82`, no standalone `faithful`.
- `a refusal renders a neutral state, never a trust word` —
  `EVAL_UNKNOWN_GROUNDING_REFUSAL`; text matches
  `/could not be checked|declined/i` and NOT
  `/low risk|verified(?! —)|trustworth|confidence/i`.
- `a missing mandatory safety caveat is surfaced` — `EVAL_MISSING_HIGH_STAKES` with
  no `fs.high_stakes_notice` ⇒ the amber row is visible; **paired negative**
  (`required && present`) ⇒ hidden, so the assertion is not vacuous.
- `a suppressed disagreement loses the green Agreement treatment` —
  `EVAL_SUPPRESSED_DISAGREEMENT` with agreement `{aligned: 3, total: 4}` ⇒
  `#result-trust [data-accent="agreement"]` has `data-consensus="false"` and its
  computed colour is not a token green; **paired positive**
  (`disagreement_suppressed: false`) keeps green.

**`e2e/tests/invariants/real-integration-smoke.spec.ts`** — after the unmocked sim
run reaches the result view, assert `#result-trust-score` is visible, its innerText
is non-empty, and it matches no `/\d/`. **This is the only spec with zero
`page.route`**, so it is the only thing proving the SERVER's projection reaches the
DOM rather than that the mock does.

**`e2e/tests/accessibility/axe-all-views.spec.ts`** — scoped scan
`new AxeBuilder({ page }).include("#result-trust-score")` in both themes, failing on
critical/serious `violations` **AND** on any `incomplete` entry whose id is
`color-contrast`. The current filter (≈`:136-140`) inspects `results.violations`
only and never looks at `results.incomplete` — which is exactly where contrast lands
for the alpha-tinted tokens this surface reuses (`--warning-soft: rgba(138,95,22,.10)`,
`--info-soft: rgba(71,104,158,.10)`). Additionally compute contrast deterministically
in-spec: walk ancestors for the first non-transparent background, composite the alpha
layers, assert ≥ 4.5:1 body / ≥ 3:1 for ≥18.66px bold. **"axe could not tell" must
never read as "pass".**

**New `tests/contract/test_golden_fixture_matches_served_schema.py`** — export the
fixture's evaluation blocks to a shared JSON both sides import, and validate each
with `QueryRunEvaluationProjection.model_validate(...)`. A hand-authored fixture
encoding an impossible shape (`trust.score: 72` on an `unverified` band, forbidden
by the structural suppression in `evaluation.py` ≈`:1288-1303`) then fails in
Python, so the mocked e2e suite cannot go green on a payload the server can never
emit.

**New `tests/unit/test_evaluation_projection_has_no_judge.py`** (D-5) —
`QueryRunResultResponse.model_json_schema()` resolves `evaluation` to a shape with
no `judge`/`rationale` key at any depth; and `src/product_app/static/app.js`
contains no occurrence of the identifier `judge`.

**`.github/workflows/e2e.yml`** — add `tests/invariants/trust-score-invariants.spec.ts`
and `tests/invariants/trust-score-visual.spec.ts` to blocking steps with
`--retries=0`. Add both to the `flake-scan.yml` matrix (RB-4b).

**`.github/workflows/seed-visual-baselines.yml`** — change the generate step
(≈`:62-66`) from the single hardcoded spec to
`tests/invariants/ --update-snapshots --project=chromium` (glob-driven), and **drop
the `|| true`** on `git add e2e/tests/invariants/*-snapshots/` (≈`:73`) so a path
miss fails loudly instead of silently committing zero files.

**RED proof (PR-S3-4).** Author every spec before the `app.js`/`workspace.html`
change: all eleven invariants, all five degraded cases, the smoke assertion and the
visual spec fail (no `#result-trust-score` in the DOM).

**BITE proofs.**
| Mutation | Reds |
|---|---|
| Replace `renderTrustScore`'s body with `box.textContent = "—"` | invariants 4, 9, 11; degraded cases 1–4 (case 5 asserts on the #result-trust Agreement card, which this mutation does not touch) |
| Move the `box.textContent = ""` reset **below** the `evaluation == null` early return | invariant 10 (stale band on re-render) |
| Change the whitelist to `ev.label_confidence !== "indeterminate"` | invariant 11 (fail-closed) |
| Render `trust.diagnostics.layer_a_composite_unverified` | invariant 1 (73.4) |
| Tint the surface with `var(--c-green)` | invariant 5, in BOTH themes |
| Retype `#0E6B50` as a literal in the guard instead of reading the token | invariant 5 goes green in dark — caught in review, and the hue-band rule still bites |
| Add `role="meter"` | invariant 6 |
| Delete the missing-caveat branch | degraded case 4 |
| Delete the D-17 `disagreement_suppressed` branch | degraded case 5 |
| Return `None` unconditionally from `_evaluation_projection` (`query_runs.py` ≈`:1575`) | the real-integration-smoke assertion, while every mocked spec stays green |
| Delete the faithfulness branch from the render path | degraded case 1, while the three existing degraded-banner tests stay green |

**Anti-vacuity, mandatory.** The absence-shaped assertions ("no digits", "no green")
are trivially satisfied by an EMPTY surface. So each of them is paired with a
**discriminating positive**: two fixtures in the same family
(`EVAL_CLEAN` with top contributor `live_ratio`, and
`EVAL_UNKNOWN_GROUNDING_REFUSAL`) must produce **different** state lines and
**different** why-line sets in the same spec. Any proposed S3 test that stays green
under the `box.textContent = "—"` mutation must be strengthened before it is
written.

---

### PR-POST-A — RB-5 fault-injection lane (after S3)

**Files.** New `tests/integration/test_fault_injection_lane.py` — hermetic,
monkeypatching the provider seam (`ProviderExecutionService` in
`src/product_app/providers.py`, whose `produce_initial_answer` is already the
injection point used for the perf sensitivity table) per case: timeout, HTTP 500,
partial slot. Assert: the run reaches a TERMINAL status within the 180 s NFR-004
bound; the status is `partial` (not `failed`) where a partial answer exists; the
fallback is recorded via `InMemoryProviderEventRecorder`; and the served projection's
`evaluation.signals.live_ratio` drops accordingly.

`e2e/tests/degraded/degraded-banner.spec.ts` — a low-`live_ratio` fixture asserting
**both** the degraded banner **and** that the S3 trust surface renders its
indeterminate/amber state with `score` still `null`, no digits and no green token —
i.e. a degraded run never *gains* a number. Add to the flake-scan matrix.

---

## 4. DOC CHANGES — literal text to copy

### 4.1 `docs/10-functional-requirements.md` — append after the FR-015 block

```markdown
## FR-016 Trust and confidence result surface

- Actor: Browser-session user (the run's owner).
- Trigger: The user views the result view of a terminal query run whose `GET /v1/query-runs/{id}` response carries the optional `evaluation` field added by FR-015.
- Behavior: The workspace result view renders a **trust summary surface** (`#result-trust-score`) as a sibling of the existing three-card trust triangle, reading `result.evaluation` read-only and computing nothing of its own. **The surface renders no digit of any kind** — not the `layer_a_composite_unverified` diagnostic, not a `contributions[].contribution` magnitude, not a percentage, not a width/stroke-dashoffset/rotation derived from any of them — **and it never renders the advisory label words** `faithful`, `partial`, `unfaithful`, `low`, `medium` or `high`. It renders instead: a standing disclosure that these are automated structural checks and not a fact-check; exactly one plain-language state line describing what was and was not checkable; at most three "why" lines selected by the LOWEST signal value (the reasons to doubt, never the highest contribution) from a fixed app-authored label table; and, when `high_stakes_warning_required` is true and `high_stakes_warning_present` is false, a persistent amber row stating that the question needed a safety caveat and the synthesis did not include one. **The presentation guard is binding and is inherited, not re-derived:** the API serves `label_confidence`, and the surface treats any value other than the exact literal `reportable` — including an absent or unknown value — as indeterminate, because a run carrying an unverifiable off-run URL marker may never present a confident structural verdict (DEBT-012). **The honesty rule is binding:** while `trust.support_verified` is False the API serves `score: null` and `band: "unverified"`, and the surface renders no numeric confidence of any kind; an absent, `null` or malformed `evaluation` hides the surface entirely and emits zero text, never a fabricated value and never an em-dash that could read as "nothing wrong found". **The GREEN RULE is binding:** no element of the trust-score surface resolves to the consensus green token in any paint channel, in either theme — green belongs to the Agreement card alone; qualitative states use ink, amber and blue. A run whose polar disagreement was detected and then suppressed loses the green Agreement treatment. Every string on the surface is an app-authored constant written with `textContent`, never provider prose and never routed through the Markdown renderer.
- Outcome: A run's evaluation is visible to its owner in a form that cannot overstate what was verified, and a judge-OFF run — every run in the default deployment — displays an honest, number-free account of what was and was not checkable rather than a confidence figure.
- Source: `docs/09-roadmap.md` (Release 2), `docs/30-ux-design.md`, `docs/32-ui-state-matrix.md`, `docs/42-ai-safety-grounding.md`, `docs/63-technical-debt-register.md` (DEBT-012).
- Owner: Frontend engineer.
- Priority: Must.
- Rationale: FR-015 computes an honest per-run evaluation that no user can see; rendering it naively would reintroduce exactly the overstated-confidence failure (OC-2) the suppression rule was built to prevent, and would surface a composite that is arithmetically biased UPWARD on precisely the runs that deserve least trust.
- Acceptance criteria: AC-044, AC-045, AC-046.
- Tests: TEST-FR-016 (`e2e/tests/invariants/trust-score-invariants.spec.ts`, `e2e/tests/invariants/trust-score-visual.spec.ts`, `e2e/tests/degraded/degraded-banner.spec.ts`, `e2e/tests/invariants/rendering-invariants.spec.ts`, `e2e/tests/accessibility/axe-all-views.spec.ts`, `e2e/fixtures/golden-run.ts`).
- Jira: Not created.
```

### 4.2 `docs/12-acceptance-criteria.md` — append after AC-043

```markdown
## AC-044 The trust surface renders no number and no confident label

Given a completed run whose result payload carries an `evaluation` — which in the default judge-OFF deployment always has `trust.support_verified` False, `trust.score` null and `trust.band` `unverified` — when the owner opens the result view, then the trust summary surface renders a standing "Not verified" disclosure, exactly one plain-language state line and at most three "why" lines; and its rendered text contains no digit of any kind, none of the words `faithful`, `partial`, `unfaithful`, `low risk`, `medium risk`, `high risk`, `confidence`, `accuracy`, `trustworthy`, `reliable`, `score` or `grade`, and no raw Layer-A signal identifier; and no descendant carries an ARIA `meter`, `progressbar` or `slider` role or an `aria-valuenow` attribute. And given the payload has no `evaluation`, or a `null` one, or a malformed one, then the surface is hidden and emits zero text.

- Requirement: FR-016, NFR-011
- Test: TEST-FR-016 (`e2e/tests/invariants/trust-score-invariants.spec.ts` no-digits / no-label-words / no-identifiers / disclosure-present / no-ARIA-value-widget / absent-renders-nothing; `e2e/tests/invariants/real-integration-smoke.spec.ts` the same no-digit assertion against the REAL server projection with no mocks)

## AC-045 A run whose citations could not be checked never presents a confident verdict

Given a run carrying at least one unverifiable off-run URL citation marker whose engine labels sit at the confident end — the DEBT-012 laundering shape, one resolving ordinal beside many fabricated links, which the engine still labels `faithful` / `low` — when the result view is rendered, then the API serves `label_confidence: "indeterminate"` and the surface renders the indeterminate state line stating that some citations point to pages never retrieved on this run; and a payload from which `label_confidence` is absent altogether renders the same indeterminate treatment, so the guard fails closed; and a warning-labelled run is never suppressed, so the guard can only ever under-claim. And given `high_stakes_warning_required` is true while `high_stakes_warning_present` is false, then a persistent amber row states that the question needed a safety caveat and the synthesis did not include one, independent of whether the synthesis carries its own notice.

- Requirement: FR-016, NFR-008
- Test: TEST-FR-016 (`e2e/tests/degraded/degraded-banner.spec.ts` misleading-output gate: laundered / refusal / missing-high-stakes / suppressed-disagreement / fully-live-unfaithful, each with its paired negative; `tests/unit/test_evaluation_presentation_confidence.py` the monotone-downward property; `tests/integration/test_query_run_evaluation_endpoint.py` the fail-closed s2-eval-v2 case)

## AC-046 The trust surface is never green, is accessible, and does not clip or overlap

Given every evaluation shape in the golden fixture, when the result view is rendered at 375, 768 and 1440 px in the pinned Linux CI browser in both the light and the dark theme, then no element of the trust-score surface or any of its descendants or pseudo-elements resolves to a green token in `color`, `background-color`, `background-image`, any `border-*-color`, `outline-color`, `box-shadow`, `text-decoration-color`, `caret-color`, `accent-color`, `fill` or `stroke` — where the expected greens are read from the CSS token source at runtime in each theme, never retyped — and no descendant carries `data-consensus` or a consensus/agreement class; a run whose disagreement was suppressed loses the green Agreement treatment; an axe-core scan scoped to the surface reports no critical or serious violation and no `color-contrast` incomplete result; no two elements' bounding boxes intersect inside `#main-content`; the surface and each trust card neither clip nor truncate; and the human-reviewed element-scoped screenshot baselines match in both themes at all three viewports.

- Requirement: FR-016, NFR-009
- Test: TEST-FR-016 (`e2e/tests/invariants/trust-score-invariants.spec.ts` GREEN-RULE / token-source computed style / overlap / clipping, parameterised over 3 viewports × 2 themes; `e2e/tests/accessibility/axe-all-views.spec.ts` scoped scan failing on violations AND on color-contrast incompletes; `e2e/tests/invariants/trust-score-visual.spec.ts` element-scoped `maxDiffPixels` baselines)
```

### 4.3 `docs/17-requirement-registry.md` — insert as the LAST row of the title-section table (after the NFR-012 row on line 31, BEFORE `## Registry Notes` on line 33). 11 columns, no empty cell.

```
| FR-016 | Functional | Trust and confidence result surface — number-free, judge-OFF-safe, DEBT-012-guarded evaluation rendering (R2) | `docs/09-roadmap.md`; `docs/30-ux-design.md`; `docs/32-ui-state-matrix.md`; `docs/42-ai-safety-grounding.md`; `docs/63-technical-debt-register.md` | Frontend engineer | Must | AC-044, AC-045, AC-046 | TEST-FR-016 | Not created | Not published | Draft |
```

### 4.4 `docs/18-requirement-traceability-matrix.md` — insert as the LAST row of the title-section table (after the NFR-010 row on line 31, BEFORE `## Traceability Notes` on line 33). 7 columns, no empty cell — use explicit non-claims, never blanks.

```
| FR-016 | AC-044, AC-045, AC-046 | TEST-FR-016 | `src/product_app/static/app.js` (`renderTrustScore`); `src/product_app/static/app.css` (`result-trust-score*`); `src/product_app/templates/workspace.html` (`#result-trust-score`); `src/product_app/evaluation.py` (`citation_marker_census`, `presentation_confidence`); `src/product_app/query_runs.py` (`label_confidence` projection); `e2e/fixtures/golden-run.ts`; `e2e/pages/WorkspacePage.ts`; `e2e/tests/invariants/trust-score-invariants.spec.ts`; `e2e/tests/invariants/trust-score-visual.spec.ts`; `e2e/tests/degraded/degraded-banner.spec.ts` | Pending — the R2-S3 e2e blocking steps have not run yet | `docs/73-release-evidence.md` (R2-S3, pending) | Share of result views rendering the indeterminate state; trust-surface render errors |
```

### 4.5 `docs/54-ac-to-test-map.md` — append three rows after the AC-043 row. 11 columns, `N/A` where deliberately not applicable, never blank.

```
| AC-044 | FR-016, NFR-011 | TEST-FR-016-U1 the served projection carries `label_confidence` and no judge key | TEST-FR-016-I1 a laundered run is served as indeterminate | TEST-FR-016-C1 the golden fixture's evaluation blocks validate against `QueryRunEvaluationProjection` | TEST-FR-016-E1 no digit, no label word, no raw identifier, disclosure present, absent evaluation hides the surface | N/A | TEST-FR-016-S1 no numeric confidence reaches any text node while `support_verified` is False | TEST-FR-016-A1 no ARIA meter/progressbar/slider role and no `aria-valuenow` | TEST-FR-016-EVAL1 the judge-OFF fixture is the default-deployment case | Not available until the R2-S3 e2e job runs |
| AC-045 | FR-016, NFR-008 | TEST-FR-016-U2 `presentation_confidence` is monotone-downward and never suppresses a warning | TEST-FR-016-I2 an `s2-eval-v2` row missing the new signals is presented as indeterminate | N/A | TEST-FR-016-E2 misleading-output gate: laundered, refusal, missing high-stakes, suppressed disagreement, fully-live unfaithful — each with its paired negative | N/A | TEST-FR-016-S2 the DEBT-012 laundering shape cannot present a confident verdict | N/A | TEST-FR-016-EVAL2 the corpus confident cases keep their reportable presentation (measured 0 of 2 degrade) | Not available until the R2-S3 e2e job runs |
| AC-046 | FR-016, NFR-009 | N/A | N/A | N/A | TEST-FR-016-E3 GREEN RULE across all paint channels, both themes, 375/768/1440; overlap and clipping | TEST-FR-016-P1 the trust surface adds no measurable render regression to the result view | N/A | TEST-FR-016-A2 axe-core scoped scan clean on violations AND on color-contrast incompletes, both themes | N/A | Not available until the R2-S3 e2e job runs |
```

### 4.6 `docs/61-vertical-slice-plan.md` — append THREE rows after `| SLICE-012 Release hardening | … |`. 6 columns. (The file has **no** R2 rows at all; the S2 spec's own "SLICE R2-S2 row → Done" deliverable was never landed. Flag the first two as a recovered S2 miss in the ledger, not as new S3 scope.)

```
| SLICE R2-S1 Durable run history | FR-014, NFR-011, AC-038, AC-039, AC-040 | `src/product_app/run_history_store.py`; `src/product_app/query_runs.py` (`_persist_terminal_run`) | TEST-FR-014 unit/integration/security tests | Durable per-run trust/cost/agreement metrics | Unset store config ⇒ persistence off, no behaviour change. **Done.** |
| SLICE R2-S2 Per-run evaluation engine | FR-015, NFR-011, NFR-012, AC-041, AC-042, AC-043 | `src/product_app/evaluation.py`; `run_history_store.update_evaluation`; `QueryRunEvaluationProjection` | TEST-FR-015, TEST-NFR-011, TEST-NFR-012 unit/integration/eval/security tests | TrustScore band distribution and `unverified` share | Judge key unset ⇒ Layer B dormant; unconfigured store ⇒ eval persistence off. **Done.** |
| SLICE R2-S3 Trust and confidence result surface | FR-016, NFR-008, NFR-009, AC-044, AC-045, AC-046 | `src/product_app/evaluation.py` (`citation_marker_census`, `presentation_confidence`); `src/product_app/query_runs.py` (`label_confidence`); `src/product_app/static/app.js` (`renderTrustScore`); `app.css` (`result-trust-score*`, no new green token); `templates/workspace.html` (`#result-trust-score`) | TEST-FR-016 blocking e2e: `trust-score-invariants.spec.ts`, `trust-score-visual.spec.ts`, extended `degraded-banner.spec.ts`, `axe-all-views.spec.ts`; plus `tests/unit/test_evaluation_presentation_confidence.py` | Share of result views rendering the indeterminate state; trust-surface render errors | `FLAG-008 trust_surface_enabled` off ⇒ surface hidden; a null/absent/malformed `evaluation` self-hides, so the surface is safe to ship progressively. |
```

### 4.7 `docs/64-feature-flag-plan.md` — append after FLAG-007 (line 15). **The next id is FLAG-008, not FLAG-007.** 8 columns.

```
| FLAG-008 `trust_surface_enabled` | Renders the FR-016 trust summary surface in the result view. Presentation-only: it gates rendering of data the owner-scoped API already returns, so it is explicitly NOT security-sensitive behaviour under the server-side rule below; the account boundary is enforced by `GET /v1/query-runs/{id}` (AC-043), never by this flag. | Off | Internal accounts after the R2-S3 e2e invariants, axe and visual baselines pass | Internal with the golden messy fixture at 1440px light+dark, then beta, then public | Turn the flag off to hide the trust summary; the existing trust triangle and result view are unaffected | Trust-surface render count, indeterminate-state share, e2e invariant failures | Frontend engineer |
```

### 4.8 `docs/42-ai-safety-grounding.md` — two edits, BOTH before any `app.js` change

1. Add a row to the eval-set table (≈`:75-80`):

```
| Trust-surface honesty set | Ensure no digit and no advisory label word is rendered while `support_verified` is False, and an absent evaluation hides the surface rather than rendering a fabricated or ambiguous value. | FR-016, AC-044 |
```

2. New subsection after the Layer A / Layer B split section (≈`:98`):

```markdown
### What the trust surface claims — and does not claim

The served `unverified` band is a statement that citation SUPPORT was never
verified. It is not a low-confidence score, and the surface never renders it as
one: it renders **no digit at all**, so `layer_a_composite_unverified` and every
per-signal contribution are structurally unrenderable.

The advisory `faithfulness_label` and `hallucination_risk` are **not rendered as
words** in any branch. Two reasons, both measured. First, DEBT-012: one resolving
ordinal carries any number of fabricated URL citations to `faithful` / `low`, and
there is no dilution at any dose — a single fabricated link beside one good ordinal
already scores 1.0. Second, `layer_a_composite_unverified` is biased UPWARD exactly
on the runs that deserve least trust, because when grounding is unknown the largest
weight (0.30) is dropped and the remainder renormalised, so an un-checkable run is
scored purely on liveness, coverage, completeness and framing and can out-score a
run whose grounding was measured bad.

What closes the S3 exposure is the presentation guard, not a label change. The
engine serves `label_confidence`; a run carrying any unverifiable off-run URL marker
whose labels sit at the confident end is `indeterminate` and can never present a
confident verdict. The guard is cut-free (it chooses no constant) and
monotone-downward (it never suppresses a warning), so it can only under-claim.

Even on the reportable branch the surface qualifies itself — "Structural checks
passed — citations were not verified against their sources" — because a model that
invents plausible SOURCE ROWS and then cites `[1]`, `[2]` reaches grounding 1.0 with
zero unverifiable markers, and Layer A with zero I/O cannot detect that at all.

The Layer-B judge is not surfaced in S3 and has no client-visible field. The served
projection has no `judge` key at any depth, and that is asserted by
`tests/unit/test_evaluation_projection_has_no_judge.py`.
```

### 4.9 `docs/40-threat-model.md`

Threat table, after T-012 (≈`:59`):

```
| T-013 | Tampering / AI safety | Attacker-influenced provider prose (query text or a retrieved page) is rendered on the trust surfaces. | Raw Markdown, script-shaped or spoofed-UI content on the highest-trust surface in the product. | The FR-016 trust-score surface renders app-authored constants only, written with `textContent` — no provider string reaches it, and it deliberately does NOT route through the Markdown renderer, so no provider-text path is normalised onto it. The trust TRIANGLE, which does carry provider prose, renders it in full through `setInlineProse` and clamps with CSS rather than slicing raw characters — slicing could cut inside a `**bold**` run and leave a dangling marker. The blocking `rendering-invariants.spec.ts` gate walks `#main-content` and fails on any surviving raw Markdown, and the golden fixture carries an uncertainty string whose bold run straddles the old truncation point so the gate actually covers it. |
```

Abuse table, after AB-008 (≈`:72`):

```
| AB-009 | A run engineered so that one resolving citation ordinal sits beside many fabricated URL markers renders as high trust (DEBT-012); there is no dilution at any dose. | Numeric trust stays structurally suppressed; the surface renders no digit and no advisory label word in any branch; and the engine serves `label_confidence`, which is `indeterminate` for any run carrying an unverifiable marker whose labels are confident. The residual — invented SOURCE ROWS cited by ordinal, which Layer A cannot detect with zero I/O — is recorded in DEBT-012 and owned by S4. |
```

Test-evidence list (≈`:83-86`):

```
- TEST-FR-016 (`e2e/tests/invariants/rendering-invariants.spec.ts`): no raw Markdown survives on any trust surface for any golden evaluation shape (T-013).
- TEST-FR-016 (`e2e/tests/degraded/degraded-banner.spec.ts`): the DEBT-012 laundering shape renders the degraded treatment and no confident token (AB-009).
```

### 4.10 `docs/20-architecture.md`

Evaluation component table, after the `Result projection` row (≈`:132`):

```
| Trust surface (`app.js` / `app.css` / `workspace.html`) | Renders the served `evaluation` projection read-only: a standing disclosure, one state line, up to three "why" lines, and the missing-safety-caveat row. Computes no score, re-derives no arithmetic, holds no threshold, and renders no digit — every honesty decision is made server-side and inherited via `label_confidence`. Absent / `null` / malformed ⇒ hidden with zero text. | `QueryRunResultResponse.evaluation` only. |
```

Failure-mode table (≈`:142`):

```
| The `evaluation` field is absent, null, or partially populated (including a persisted `s2-eval-v2` row) | The trust surface hides, or renders the indeterminate state — never the confident one. The existing trust triangle and result view are unaffected. | FR-016, AC-044, AC-045 |
```

### 4.11 `docs/21-domain-model.md` — add to the invariant list (≈`:64-65`)

```
- No presentation surface renders a numeric confidence, percentage or score derived from a `TrustScore` while `support_verified` is False, and no presentation surface renders the advisory `FaithfulnessLabel` or `HallucinationRisk` vocabulary as a user-facing word at all. The rule is enforced server-side by structural suppression (`score` IS `None`) and client-side by the FR-016 no-digit / no-label-word e2e gate; the client re-derives nothing. Trace: FR-016, AC-044.
- A `RunEvaluation` carrying any unverifiable citation marker whose labels sit at the confident end is presented as `indeterminate`. The guard is monotone-downward: it never raises a presented state above its raw label. Trace: FR-016, AC-045, DEBT-012.
```

---

## 5. GATE PLAN

### 5.1 Per-PR local sequence (run in this order; stop on the first red)

```bash
cd /Users/rohitagrawal/Projects/quorum-ai

# 1. Docs/traceability — cheap, stdlib-only, and the one that reds the whole chain.
make fr-completeness                 # record the count BEFORE and AFTER PR-S3-3
make validate

# 2. Static quality.
make format-check
make lint
make type-check                      # runs mypy over src AND tests

# 3. The blocking Python suite (coverage floor 88).
uv run pytest -q

# 4. Contract, after any model change.
make openapi-export
make openapi-check
make api-contract                    # raise CONTRACT_MIN_TESTS if the count grew

# 5. Slice-diff coverage (>= 95%).
make diff-cover                      # record the number in docs/metrics/diff-cover.md

# 6. Advisory perf (never gates S3).
make perf-gate

# 7. Doc/ledger consistency — run after ANY docs/63 or ledger edit.
uv run pytest tests/test_findings_ledger_consistency.py \
              tests/test_findings_ledger_perf_numbers.py \
              tests/test_r2_plan_status_honesty.py \
              tests/test_doc_gate_consistency.py \
              tests/test_ultracode_prompt_enforcement_contract.py -q --no-cov
```

### 5.2 E2E, locally (all $0, sim backend, no paid call)

```bash
cd e2e
npx playwright test tests/invariants/trust-score-invariants.spec.ts \
                    tests/invariants/trust-score-visual.spec.ts \
                    tests/degraded/degraded-banner.spec.ts \
                    tests/invariants/rendering-invariants.spec.ts \
                    tests/accessibility/axe-all-views.spec.ts \
                    tests/invariants/real-integration-smoke.spec.ts \
                    --project=chromium --retries=0
```

### 5.3 Visual-baseline seeding — the exact five-step order

`seed-visual-baselines.yml` currently hardcodes both the spec path it runs
(≈`:62-66`) and the snapshot directory it commits (≈`:73`, with a `|| true` that
swallows a path miss). A naive PR self-blocks on a missing baseline or silently
commits an unreviewed baseline of a broken layout. Do this instead:

1. Land the S3 UI code (`app.js` / `app.css` / `workspace.html`) + the fixture +
   the new visual spec on `feat/r2-s3-trust-ui`, with the new spec **not yet** in
   `e2e.yml`'s blocking list.
2. Edit `seed-visual-baselines.yml`: run `tests/invariants/ --update-snapshots
   --project=chromium` (glob-driven) and **drop the `|| true`** on the `git add`.
3. `gh workflow run seed-visual-baselines.yml --ref feat/r2-s3-trust-ui`. (The
   workflow file already exists on `main`, so dispatch on the branch works.)
4. Pull the bot commit and **HUMAN-REVIEW every new and changed PNG**.
   `result-verdict-chromium-linux.png` **will** change — the new surface shifts a
   2943px-tall page. A baseline reseed is not evidence of correctness; it is a
   record of what a human accepted.
5. Only then add the spec paths to the blocking steps in `e2e.yml`.

### 5.4 RB-4b — measure the new specs before S3 is Done

```bash
gh workflow run flake-scan.yml --ref feat/r2-s3-trust-ui
```
Paste the resulting rate (expected 0/10) per spec, **with the GitHub run id**, into
the RB-4 table in the ledger and into `docs/metrics/flake-rate.md`. This is a hard
S3 exit criterion — roughly 15 minutes of wall clock, not new engineering, because
PR-INFRA-B already built the job.

### 5.5 Manual drive-and-look — required by AGENTS.md, recorded in `docs/analysis/R2-S3-manual-verification.md`

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
UV_CACHE_DIR=.uv-cache PYTHONPATH=src SENTRY_DSN='' \
  OPENROUTER_LIVE_EXECUTION_ENABLED=false \
  uv run uvicorn product_app.main:app --host 127.0.0.1 --port 18085
```

Then: open `http://127.0.0.1:18085/ui` at exactly 1440×1200; run
`localStorage.setItem('quorum.workspaceSeen','1')`; submit a question; let the sim
run complete. At 1440 **light**, screenshot the full result view and confirm the
trust-score surface shows a state line and "why" lines with **no digit**, reads as
ink/amber/blue with zero green, the three trust cards keep their green-only-on-
consensus behaviour, and nothing overlaps or truncates. Click the header
"Switch to dark theme" button and repeat — specifically confirm **no `#4EC28C`**
appears on the surface. Repeat at 375×812 and 768×1024 via device emulation;
confirm the cards stack at the 760px breakpoint and the surface neither clips nor
overlaps. Attach all six screenshots.

This is a **second, human channel**. The automated dark-theme element baseline
(§3, PR-S3-4) remains the binding gate — a manual spot-check has previously given a
false all-clear because CSP and rendering differ per browser.

### 5.6 CI order of authority

`make validate` / `make fr-completeness` / `uv run pytest` / `make api-contract` /
`make diff-cover` are BLOCKING. `make perf-gate`, `mutation-baseline`,
`flake-scan` and `perf-sample` are ADVISORY and stay advisory through S3. Any new
gate identifier must be registered in `tests/test_doc_gate_consistency.py::GATES`
(new e2e spec identifiers appended to the `e2e-invariants` Gate; a new `Gate` for
any new CI job), and any advisory/PR-only qualification recorded in
`docs/analysis/03-enforcement-machinery.md` — the doc test requires a line
containing both the job name and the status string. If any doc or the ULTRACODE
prompt names a new `make` target, define it in the Makefile **and** add it to
`.PHONY` in the **same commit**, or
`tests/test_ultracode_prompt_enforcement_contract.py::test_every_named_make_target_exists`
reds.

---

## 6. RESIDUALS — ledger-row wording

### 6.1 `docs/63-technical-debt-register.md` — rewrite the DEBT-012 row

Status column → **PARTIALLY REPAID (R2-S3)**. Repayment-plan cell:

> **S3 closed the SURFACING half.** An engine-side census
> (`citation_marker_census` → `MarkerCensus`) now separates resolved,
> resolvable-as-false and unverifiable markers; `citation_marker_grounding` is
> derived from it so the two cannot drift, and its VALUE semantics are unchanged.
> Two new signals — `unverifiable_marker_count` and `unverifiable_marker_ratio` —
> carry the laundering shape as a measurable fact, deliberately unweighted (a
> weight is a calibrated cut, deferred to S4 by FS-6). A cut-free,
> monotone-downward guard `presentation_confidence` serves `label_confidence` on
> the projection: any run carrying an unverifiable off-run URL marker whose labels
> sit at the confident end is `indeterminate`, and a warning label is never
> suppressed, so the guard can only under-claim. `compute_composite` additionally
> excludes `citation_marker_grounding` whenever an unverifiable marker exists —
> reusing the module's "None is unknown, excluded and renormalised" doctrine rather
> than inventing a penalty constant — so the laundered run's composite no longer
> sits inside the genuine-faithful band (measured: 82.5 vs 83.50 / 83.38 before;
> re-measured value pinned by the composite test). The UI cannot re-derive any of
> it: it renders **no digit and no advisory label word in any branch**, and it keys
> on the served `label_confidence` with a strict `=== "reportable"` whitelist, so an
> absent field (a persisted `s2-eval-v2` row, a future projection change) fails
> CLOSED to the indeterminate treatment. **Measured under-claim cost on the frozen
> corpus: 0 of the 2 confident cases degrade** — `faithful-consensus` census
> 17/3/0 and `preserved-polar-disagreement` 11/2/0, both `unverifiable_marker_count`
> 0; the fabricating case is already `unfaithful`/`high`. Pinned by
> `tests/unit/test_evaluation_layer_a.py::test_the_corpus_confident_cases_keep_their_reportable_presentation`.
>
> **The DETECTION half is NOT repaid, and is not repayable in Layer A.** With zero
> I/O the engine still cannot distinguish an invented URL from an un-retrieved real
> one, so a URL-only fabricating run remains UNKNOWN rather than detected. And the
> laundering vector MIGRATES: a model that emits invented SOURCE ROWS under
> plausible real-looking hosts and then cites `[1]`, `[2]` scores grounding 1.0,
> `unverifiable_marker_count` 0, `faithful`/`low`, and the guard correctly says
> `reportable` — because there is nothing for it to see. Only real
> support-verification closes these: the key-gated Layer-B judge
> (`verifies_support = True`) or an explicit fetch step, calibrated against the S4
> golden set (FS-6). A second S4 task: measure the unverifiable-marker rate over the
> golden set and decide whether the zero-tolerance guard should become a calibrated
> cut — never before that measurement, because on live runs models routinely link
> pages they did not retrieve on this run and the false-degrade rate is genuinely
> unknown. Owner: backend engineer. Slice: **S4**.

Review-date cell → `**Surfacing half repaid in R2-S3 (2026-07-21). Detection half: S4 golden-set calibration.**`

Evidence cell — append (the regex must accept `.ts` first, PR-INFRA-C):
`tests/unit/test_evaluation_presentation_confidence.py`;
`tests/unit/test_evaluation_refusal_decoupling.py` (INV-5);
`e2e/tests/degraded/degraded-banner.spec.ts`.

### 6.2 `docs/analysis/R2-plan-review-findings.md` — row updates

Each flip must cite a backticked repo path that is **registered for that item** in
`S3_ARTIFACTS`, is **non-empty on disk**, and is **absent at**
`S1_BASELINE_SHA = 5ccd6f9`.

- **OC-5** (≈`:95`) `BUILD (S3)` → `**DONE (S3)** — the misleading-output gate now
  exists: a fully-LIVE `unfaithful`/`high` run and the DEBT-012 laundering shape
  both render the degraded/low-trust treatment, and the surface carries no
  confident token. Pinned by `e2e/tests/degraded/degraded-banner.spec.ts`
  (misleading-output describe block) and the six evaluation variants in
  `e2e/fixtures/golden-run.ts`. RED-proven: the block fails on <pre-fix SHA> while
  the three original count-driven degraded tests stay green, so it is a genuinely
  new faithfulness-driven gate, not a rename.`
- **RB-4** (≈`:116`) → `**DONE (measured, S3)** — `retries` now defaults to 0 in
  `e2e/playwright.config.ts` (masking is explicit opt-in via `PW_RETRIES`);
  `.github/workflows/flake-scan.yml` runs the timing-sensitive specs
  `--repeat-each=10 --retries=0` nightly and on dispatch; the policy is enforced by
  `tests/unit/test_e2e_flake_policy.py`. Measured rates published in
  `docs/metrics/flake-rate.md` with run ids. Over-budget specs are QUARANTINED, not
  retried.`
- **RB-5** (≈`:117`) → keep `BUILD` until PR-POST-A lands, then
  `**DONE (post-S3)** — hermetic fault-injection lane
  `tests/integration/test_fault_injection_lane.py`: terminal-by-180s, partial
  surfaced not failed, fallback recorded, `live_ratio` drops, degraded banner
  fires, and the trust surface stays number-free under fault.`
- **RB-6** (≈`:118`) → `**DONE (S3)** — the config already declared four projects;
  CI installed and ran only chromium. New blocking `csp-cross-engine` job runs
  `tests/docs/docs-under-csp.spec.ts` and `e2e/tests/invariants/csp-smoke.spec.ts`
  on webkit and firefox. Pixel baselines stay chromium/linux-only by design, pinned
  by `tests/unit/test_e2e_flake_policy.py`.` (Or the WONTFIX variant citing
  `docs/adr/0003-chromium-only-e2e.md`.)
- **DEBT-009** (≈`:254`) → `**PUBLICATION HALF DONE; CLOSURE STILL DEFERRED.**
  `make perf-gate` now runs with `-s` so the `[PERF]` lines survive capture on a
  PASSING run (measured: they were absent before), and both latency tests publish
  `build/gates/perf-percentiles.json` with a provenance `meta` block, uploaded
  `if: always()` so an over-budget sample is not lost to the job's
  `continue-on-error`. `.github/workflows/perf-sample.yml` accrues one ubuntu sample
  per night, because `ci.yml` has no `schedule` trigger and one sample per PR would
  gate the budget decision on ~20 unrelated PRs. **Not closed:** budgets stay
  macOS-derived and the job stays advisory until N ≥ 20 ubuntu samples across ≥ 5
  calendar days exist, the candidate is proven to bite on CI by injected delay, and
  ≥ 10 consecutive nightly "would PASS" runs are recorded. The macOS envelope and
  the unsourced 423.6 ms figure are recorded as EXCLUDED. **Not an S3 exit
  criterion.** Owner: backend engineer. Slice: **post-S3, measurement-gated.**`
- **`query_runs.py:1478`** (≈`:261`) → `**CORRECTED AND COVERED (S3).** The claim
  that this line needed "FR-016's second writer" was wrong: `_persist_run_evaluation`
  is module-level and tests already call it directly. It is now covered by
  `tests/integration/test_query_run_evaluation_endpoint.py::test_a_non_terminal_run_writes_nothing_and_logs_no_warning`,
  which asserts on the LOG as well as the spies — without the caplog assertion the
  test is green on both source and mutant, because the broad `except Exception` at
  `query_runs.py` swallows the `AttributeError` the deleted guard would raise and
  the net observable effect is identical.`
- **DEBT-012** (≈`:262`) → mirror the §6.1 wording; slice cell becomes
  `**Surfacing half: S3 (done). Detection half: S4.**`
- **EN-2 row** (≈`:102`) → update the quoted `26 requirements` to the value
  `make fr-completeness` actually prints after FR-016 lands.
- **PHASE STATUS block** (≈`:35-79`) → add a Phase-2 (S3) line in the same shape as
  the Phase-1 line: branch, HEAD SHA, real gate numbers from a re-run, and the FR
  count from `make fr-completeness`.
- **New residual row — invented source rows:**
  `| **NEW — the invented-SOURCE-ROW vector** | **OPEN, recorded so a green S3 is
  not mistaken for closure** — a model that emits fabricated bibliography rows under
  plausible real-looking hosts and then cites them by ordinal scores grounding 1.0,
  `unverifiable_marker_count` 0, `faithful`/`low`, and `label_confidence`
  `reportable`. Layer A with zero I/O cannot see it at all; the reportable branch's
  standing qualifier ("citations were not verified against their sources") is the
  only mitigation, and it is a disclosure, not a detection. Owner: backend engineer.
  Slice: **S4** (support-verification, with the golden set). |
  `docs/63-technical-debt-register.md` DEBT-012 |`
- **New residual row — R1 blunt rule:**
  `| **NEW — the no-digit rule is blunt by design** | **ACCEPTED (S3).** The trust
  surface renders zero digits, which forecloses legitimate future numbers (a source
  count, a slot count) on that surface. The trade is deliberate: a blunt rule a test
  can check beats a nuanced rule a reviewer must remember, and the existing trust
  cards still carry their numbers. Revisit only alongside real support-verification.
  Owner: frontend engineer. Slice: **S4**. | `e2e/tests/invariants/trust-score-invariants.spec.ts` |`
- **New residual row — SLICE table recovery:**
  `| **RECOVERED S2 MISS — `docs/61` had no R2 rows** | **FIXED (S3)** — the S2 DoD
  required a "SLICE R2-S2 row → Done" that was never landed, so the vertical-slice
  table claimed R2 stopped at SLICE-012. R2-S1, R2-S2 and R2-S3 rows added in the
  S3 docs commit. Recorded as a recovered S2 escape, not as new S3 scope. |
  `docs/61-vertical-slice-plan.md` |`

### 6.3 What S3 explicitly does NOT close

| Residual | Owner | Slice |
|---|---|---|
| URL liveness / citation-support verification (the DEBT-012 detection half) | backend engineer | S4 |
| The invented-SOURCE-ROW vector | backend engineer | S4 |
| Whether the zero-tolerance guard should become a calibrated cut (needs the live-run unverifiable-marker rate) | backend engineer | S4 |
| DEBT-009 budget re-promotion (needs N≥20 ubuntu samples) | backend engineer | post-S3, measurement-gated |
| OC-1 real captured + human-labelled runs | operator | S4 |
| OC-3 self-referential golden bands | backend engineer | S4 |
| PERF-010 eval-batch latency baseline | engineering lead | S4 |
| `docs/54` has no gate behind it (nothing checks column count or per-AC rows) | engineering lead | S4 — add a `validate_fr_completeness.py`-shaped checker, or record it as deliberately unenforced |
```
