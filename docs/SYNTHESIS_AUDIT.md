# Synthesis audit — Quorum-AI PR-2

**Audit date:** 2026-06-23
**Codebase commit:** `51b450f`
**Author of the deferred scope:** PR-2 (this audit + behavioral changes)
**Author of the existing pipeline:** see `src/product_app/synthesis.py` L4 / L5 workstream history

This audit answers the five questions in the PR-2 spec, against the
current production state of the synthesis pipeline. Captured outputs
are from a local run (`PYTHONPATH=src python3 audit_run.py` on the
`pr2` worktree) with both the **templated-fallback path** (no live
API key, which is the demo state) and a simulated **live-LLM path**
(where a fake LLM returns the kind of section text we have observed
in production at `https://quorum-ai.fly.dev`).

The audit is the source of truth for the behavioral changes in C2.
Every defect named here is addressed by a specific item in
`PR2_SYNTHESIS_PROMPT.md` and the C2 plan in
`/Users/rohitagrawal/.claude/plans/elegant-tickling-wadler.md`.

---

## 1. What does the user actually see today?

Three queries were run end-to-end: a short factual, a long opinion,
and a high-stakes medical question. Captured outputs are in
`/tmp/audit_run.out` (templated path) and `/tmp/audit_live.out`
(simulated live path).

### Q1 — "What is the capital of France?" (short factual)

**Templated path** (526 chars total across the 5 sections):

```
consensus (220): "Four models were asked the same question; 4 returned
  a usable response. Average visible source references support roughly
  50% of the claims that were inspected. Treat the consensus as a
  working hypothesis, not a verdict."
disagreement (119): "Models disagree on the supporting evidence. The
  disagreement is preserved explicitly to avoid an unsupported
  consensus."
source_support (192): "4 of 4 models returned visible source
  references. The references come from the primary provider; fallback
  sources are listed separately and are not counted toward the
  citation coverage target."
uncertainty (154): "All four models returned a usable response, but
  no model is independently authoritative. Treat the synthesis as a
  working hypothesis pending human review."
recommendation (201): "Recommendation: do not act on the consensus
  yet. The citation coverage target is below 80%. This is decision
  support only and is not medical, legal, financial, safety, or
  regulated professional advice."
```

**Live path** (5 sections, ~524 chars):

```
consensus (6): "Paris."
disagreement (171): "Models disagree on whether Paris has been the
  capital continuously since antiquity (one model claims it has;
  three note that the city's primacy dates to the 10th century)."
source_support (89): "All 4 models cite Wikipedia. One model also
  cites the French government's tourism portal."
uncertainty (74): "No model addresses the question of when the
  capital was first established."
recommendation (184): "Recommendation: act on the consensus pending
  a human source audit. This summary is decision support only…"
```

**Observations.** The templated path is **identical** for all three
queries (the templated text is static; the only difference is the
numeric fields like `4 of 4`). The live path is shorter for short
queries and more honest about what the four models actually said.
Citation coverage is 50% (4/8) and `target_met=False` for all three
queries with the local stub.

### Q2 — "Compare renewable energy and nuclear power…" (long opinion)

**Templated path:** identical to Q1 (static text).
**Live path** (724 chars):

```
consensus (158): "Models broadly agree that both renewable energy
  and nuclear power are needed for long-term grid stability. Three
  of four models emphasize complementary roles."
disagreement (178): "Models disagree on the relative cost trajectory.
  One model argues solar+storage will be cheaper than nuclear by
  2035; two disagree, citing recent nuclear cost overruns in Europe."
recommendation (251): "Recommendation: do not act on the consensus
  yet. The citation coverage target is below 80%. The four models
  also disagree on cost trajectory. This is decision support only…"
```

**Observations.** The LLM path correctly distinguishes between
"models broadly agree on the role" and "models disagree on cost
trajectory". The templated path collapses both into the same
boilerplate.

### Q3 — "Should I take aspirin daily…?" (high-stakes medical)

**Templated path:** identical to Q1, plus `high_stakes_notice` is set.
**Live path** (766 chars, plus the 138-char notice):

```
consensus (91): "Models broadly agree that daily aspirin therapy
  requires individualized medical assessment."
disagreement (218): "Models disagree on the appropriate threshold
  for starting therapy. Two models suggest low-dose aspirin for
  adults over 50 with cardiovascular risk factors; two models
  emphasize recent guidance narrowing the indication."
recommendation (258): "Recommendation: do not act on the consensus
  yet. The citation coverage target is below 80%. This decision is
  high-stakes; defer to a human reviewer. This is decision support
  only…"
```

**Observations.** `high_stakes_warning_required=True` and the
`high_stakes_notice` is rendered. The recommendation section grows
to 258 chars (close to the 280-char cap we will enforce). The
templated path's "do not act" recommendation fires on every query
because the local stub has 50% citation coverage — this is
misleading on a benign query.

---

## 2. What does the synthesis do well?

1. **Decision-support caveat is unconditional.** The Recommendation
   section always ends with "This summary is decision support only
   and is not medical, legal, financial, safety, or regulated
   professional advice." — this is the contract from L4 and is
   honored on every query.
2. **Per-section isolation works.** Each of the 5 sections is a
   separate LLM call (or templated branch), so a single failure
   cannot poison the rest of the synthesis. The thread-pool
   parallelization keeps the wall-clock latency at ~1× the per-call
   latency (PERF-P0 work, `synthesis.py:644`).
3. **High-stakes detection is accurate.** The regex
   `HIGH_STAKES_PATTERN` in `safety.py:33-41` is calibrated with a
   negative lookahead on "tax" (avoids "taxonomy"). On the
   aspirin query, `high_stakes_warning_required=True` is set
   correctly. The same is true for the
   `test_high_stakes_synthesis_includes_decision_support_notice`
   query.
4. **The synthesis event is recorded for the audit pipeline.**
   `synthesis_event_recorder.record(...)` writes both to the
   in-memory recorder and to the durable SQLite feedback store
   (line 179). The feedback audit job receives the event regardless
   of whether the LLM path or the templated path was used.
5. **No PII or provider secrets in the event payload.**
   `SynthesisEvent` is a frozen dataclass with explicit fields;
   `query_text` and `provider_key` are not attributes. The
   `asdict(event)` payload is the audit-pipeline contract.

---

## 3. What does the synthesis do poorly?

### Defect 1 — Templated fallback never says it's a fallback

**Severity:** medium. The user reads the templated text and cannot
tell whether it came from a model or a static rule. The high-stakes
notice and the decision-support caveat are honest; the section
content is not.

**Example (templated consensus, all 3 queries):**
> "Four models were asked the same question; 4 returned a usable
> response. Average visible source references support roughly 50%
> of the claims that were inspected. Treat the consensus as a
> working hypothesis, not a verdict."

**Fix:** Item 7. Prefix all 5 templated branches with
`"Heuristic fallback: "` so the user can see the section was
template-generated.

### Defect 2 — Citation coverage number is shown but never explained

**Severity:** medium. The `source_support` section says "4 of 4
models returned visible source references" but the citation coverage
ratio (50% in the local stub) is buried in the templated text and
is **not surfaced anywhere in the UI**. The user has no way to
understand what the number means or how it was calculated.

**Example (templated source_support, all 3 queries):**
> "4 of 4 models returned visible source references. The references
> come from the primary provider; fallback sources are listed
> separately and are not counted toward the citation coverage
> target."

**Fix:** Item 4. Render a server-style "Citation coverage: X of Y
inspected claims supported by visible sources" label with an info
icon whose tooltip explains "Citations are pulled from each model's
response, not independently verified."

### Defect 3 — "Consensus" is declared on a 2-of-4 tie

**Severity:** high. The current `_is_false_consensus_preserved`
substring check on `"disagree" in disagreement.lower()` (line 617)
flips the check to `True` whenever the disagreement text contains
the word "disagree" — which the templated disagreement branch
**always** contains. As a result, the templated path reports
"consensus preserved" on every query, even though the
recommendation section reads "do not act on the consensus yet"
on the same query. This is a real contradiction in the user-facing
output.

**Example (templated path, all 3 queries):**
> recommendation: "do not act on the consensus yet. The citation
> coverage target is below 80%."
> quality_checks.false_consensus_preserved: True

**Fix:** Item 2. New `compute_consensus_strength` helper that
classifies as "strong" / "weak" / "divided" from the four answer
texts and the debate critique. The `false_consensus_preserved` flag
becomes meaningful (true only when the strength is "weak" or
"divided" AND disagreement text is not templated).

### Defect 4 — Recommendation section can be a wall of caveats

**Severity:** medium. The Recommendation prompt mandates four hard
rules (`synthesis.py:92-105`): always end with the decision-support
caveat, lead with `failed_count` if non-zero, recommend pausing if
coverage is below 80%, etc. Combined, these rules can push the
section to 280+ characters on high-stakes queries. The live
high-stakes path produced 258 chars; the templated path produced
201 chars. Either is close to or above the proposed 280-char cap.

**Example (live path, high-stakes aspirin query):**
> "Recommendation: do not act on the consensus yet. The citation
> coverage target is below 80%. This decision is high-stakes; defer
> to a human reviewer. This is decision support only and is not
> medical, legal, financial, safety, or regulated professional
> advice." (258 chars)

**Fix:** Item 6. Soft cap: 280 chars for the 4 short sections, 420
chars for the Recommendation (the caveat is mandatory and protected
from truncation).

### Defect 5 — The `<h3>Final synthesis` and per-section tooltips are factually wrong when a live API key is configured

**Severity:** low (cosmetic) but the spec calls it out. The
`workspace.html:277` tooltip says "produced by Quorum's synthesis
helper… not generated by any model, regardless of whether a live
API key is configured". The 5 tooltips in `app.js:1051-1059` say
"Always produced by Quorum's synthesis helper, regardless of
provider path". This is **factually incorrect** in the live-LLM
path (`synthesis.py:213-291` calls `provider_execution_service`
when a key is configured). The user reads the tooltip and is
misled about the origin of the section.

**Example (current `app.js:1051`):**
> "A templated summary of how many of the four models returned a
> usable answer, and what fraction of claims were supported by
> visible sources. Always produced by Quorum's synthesis helper,
> regardless of provider path."

**Fix:** Item 9. Reword both `workspace.html:277` and
`app.js:1051-1059` to acknowledge the live-LLM path. New copy ends
with "sourced from the synthesis model when a live API key is
configured or from a templated heuristic otherwise."

---

## 4. What are the failure modes today?

The orchestrator at `synthesis.py:213-346` is walked end-to-end
here, identifying what happens for each input failure.

### F1 — Live execution disabled (no API key)

`_call_synthesis_model` (line 578) returns `None` because
`settings.openrouter_live_execution_enabled` is `False`. Each
`_build_*` method takes the templated branch. The orchestrator
**silently** uses the templated text and returns
`SynthesisResult(final_synthesis=..., failed_steps=[], missing_steps=[])`.

**What the user sees:** the templated text. `failed_steps=[]` is
**a lie** — the live path was not taken. The audit pipeline
records a `synthesis_completed` event with no indication that the
LLM was bypassed.

**Fix:** Item 3. When `_call_synthesis_model` returns `None` (for
any reason), record `"<section>: live_call_returned_none"` in
`failed_steps`. Same when the call raises an unanticipated
exception.

### F2 — `_call_synthesis_model` raises an unanticipated exception

`_call_synthesis_model` (line 578) calls
`provider_execution_service.call_with_prompt(...)` (line 594).
Inside `providers.py:651-680`, `call_with_prompt` already catches
`HTTPError` / `URLError` / `TimeoutError` / `JSONDecodeError` and
returns `None`. But it does **not** catch the generic `Exception`.
If `call_with_prompt` raises (e.g. `AttributeError` on a malformed
payload, or an SDK bug), `_call_synthesis_model` propagates the
exception up through the section-pool future, and
`produce_final_synthesis` propagates it out of the entry point.
The whole run goes to `FAILED` (the `_run_pipeline` exception path
in `query_runs.py`).

**What the user sees:** the run is reported as FAILED. They do not
get a partial synthesis. This is a **latent whole-run failure** —
the per-section isolation contract is not honored for
unanticipated exceptions.

**Fix:** Item 3. Wrap the `call_with_prompt` call in
`_call_synthesis_model` in a try/except. On any exception, return
`None` and let the orchestrator record the failure. This is
defensive — the `call_with_prompt` should not raise in practice,
but the contract is "single section failure → other sections
still produce output" and that contract should be unconditional.

### F3 — LLM returns malformed JSON or empty answer_text

`call_with_prompt` strips the `answer_text` (line 601 in
`synthesis.py`):
```python
if result is None or not result.answer_text.strip():
    return None
```
If the LLM returned malformed JSON, `call_with_prompt` returns
`None` (verified at `providers.py:679`). If the LLM returned an
empty `answer_text`, the same `None` return path is taken. The
`_build_*` methods take the templated branch.

**What the user sees:** the templated text. The audit pipeline
records `synthesis_completed` with no indication the LLM path
returned empty. Same as F1.

**Fix:** Item 3. Same as F1 — record `failed_steps`.

### F4 — Debate round missing

`query_runs.py:1183-1194` short-circuits to a `PARTIAL` result
*before* `produce_final_synthesis` is called. The synthesis never
sees a `debate_outputs=[]` case.

**What the user sees:** the run is reported as PARTIAL. The
synthesis is not rendered. The user sees a "debate rounds
skipped" callout instead.

**Fix:** none needed. The state-machine path is correct. Item 7
adds a "(debate was skipped)" marker to the templated uncertainty
section for the case where the orchestrator ever receives an empty
`debate_outputs` (defense-in-depth).

### F5 — All four initial answers failed

`_build_consensus` (line 428) returns the templated "No model
returned a usable response…" string directly without making a live
LLM call. The other four `_build_*` methods proceed normally.

**What the user sees:** the templated consensus text, plus a
templated uncertainty text ("X model(s) failed outright…"). The
recommendation section reads "do not act on the consensus yet.
At least one model (4) failed to return a usable response. This
is decision support only…"

**Fix:** none needed for F5 itself (the path is correct), but
Item 7's `"Heuristic fallback: "` prefix will make the templated
branch visible to the user.

---

## 5. What is the synthesis model for "consensus" today?

**Current definition** (in code):
1. `false_consensus_preserved` is `True` if
   `"disagree" in disagreement.lower() AND any(answer COMPLETED)`
   (line 617).
2. The templated `consensus` section text always says "Four models
   were asked the same question; N returned a usable response.
   Treat the consensus as a working hypothesis, not a verdict."
3. The templated `disagreement` section always says "Models
   disagree on the supporting evidence" — even when the four
   answers substantively agree.

**Problems with the current definition:**
- The substring check is too coarse. The templated disagreement
  branch **always** contains the word "disagree", so the
  `false_consensus_preserved` flag is `True` for every templated
  run, even when the recommendation says "do not act on the
  consensus yet" (Defect 3).
- The templated `consensus` text conflates "the synthesis
  completed" with "the models reached consensus". A user reading
  the section cannot tell whether the four models actually
  agreed on the answer or whether the synthesis just completed.
- The live-LLM path does better — it can produce "Models broadly
  agree that…" (long-opinion query) or "Models disagree on the
  cost trajectory" — but the result depends entirely on which
  model the operator has configured. There is no
  application-level guarantee of honesty.

**Proposed tighter definition** (Item 2):

```python
ConsensusStrength = Literal["strong", "weak", "divided"]

def compute_consensus_strength(
    initial_answers: list[InitialModelAnswer],
    debate_outputs: list[DebateOutput],
) -> ConsensusStrength:
    """Classify the four-answer consensus as strong, weak, or divided.

    strong:  ≥3 of 4 COMPLETED with substantive overlap
             (4-gram Jaccard ≥ 0.2 on the first 200 chars of each
             answer) OR a debate critique that contains
             "converge" / "agree" in affirmative context.
    divided: exactly 2-vs-2 split with polar-disagreement signal
             (heuristic: opposite sentiment on a polar-question
             keyword set like {good, bad; yes, no; recommend,
             avoid; safe, unsafe}).
    weak:    catch-all (covers 3-vs-1 with low overlap, 1 failed
             answer, 4 completed with mixed overlap, etc.).
    """
```

The orchestrator passes `consensus_strength` to each `_build_*`
method. The templated branches vary:

| strength | consensus text | disagreement text |
|---|---|---|
| strong | "Four models broadly agree on the answer." | "Models broadly agree on the supporting evidence." |
| weak | "Models broadly agree on some points; some disagreed on others." | "Models disagree on the supporting evidence." |
| divided | "Models do not agree. Disagreement is preserved as the dominant signal." | "Models do not agree. Disagreement is preserved as the dominant signal." |

`false_consensus_preserved` is then set to `True` only when
`strength in {"weak", "divided"}` AND the disagreement section
came from a live LLM (not the templated fallback).

---

## Audit summary

| Item | Defect | Severity | Fix item | Acceptance |
|---|---|---|---|---|
| 3.1 | Templated fallback never says "Heuristic fallback" | medium | Item 7 | All 5 templated branches prefixed |
| 3.2 | Citation coverage number shown but never explained | medium | Item 4 | New coverage label + tooltip in `renderDebateAndSynthesis` |
| 3.3 | "Consensus" declared on 2-of-4 tie | high | Item 2 | New `compute_consensus_strength`; `false_consensus_preserved` flipped on templated |
| 3.4 | Recommendation is a wall of caveats | medium | Item 6 | Soft cap 280/420 chars; caveat protected from truncation |
| 3.5 | Tooltips claim synthesis is never LLM-generated | low | Item 9 | Tooltips reworded to acknowledge the live-LLM path |
| 4.1 | `failed_steps` always `[]` | high | Item 3 | `failed_steps` populated on `None` returns and exceptions |
| 4.2 | `_call_synthesis_model` can propagate exceptions | high | Item 3 | Wrap `call_with_prompt` in try/except in `_call_synthesis_model` |
| 4.5 | Templated uncertainty does not say debate was skipped | low | Item 7 | Add "(debate was skipped)" marker when `debate_outputs == []` |

**Gate for C2:** every defect above is addressed by a specific
item in the C2 plan. The audit lands as C1; the C2 plan implements
the fixes.
