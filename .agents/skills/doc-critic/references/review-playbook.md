# Review playbook — the method doc-critic executes

> The reusable procedure for critically reviewing documentation a doc-suite skill produced. The
> `SKILL.md` orchestrates this; this file is the method.

## The one rule

**Review the whole set as one object, not page-by-page — and do it earlier.** Documentation's worst
failures span pages (contradictions, term and analogy collisions, broken cross-references, honesty
drift). A page-in-isolation review is structurally blind to them and lets an error on one page
propagate to the next before anyone notices.

## Why a special review (the recurring error taxonomy)

These seven classes recur in doc-suite output. **Review against this list** — and note that five of
the seven are cross-page, which is the whole reason the whole-document axis is the centerpiece:

1. **Internal contradictions** — a claim made on one page, disowned on another (especially a
   safeguard stated as in-force, then admitted not-yet-true elsewhere).
2. **Analogy-shape errors + term collisions** — an analogy teaching the wrong shape; one word used
   in two senses across pages.
3. **Code-vs-doc mismatches** — "the tool does X / built / tested / measured" the source does not support.
4. **Term-definition gaps + glossary incompleteness** — a term used before it is defined; the
   glossary not actually the single reference.
5. **Simplification-gone-false** — a beginner-friendly nuance flattened into something untrue.
6. **Honesty-posture drift** — built / `[designed, not yet built]` / measured-vs-illustrative markers
   inconsistent across pages.
7. **Broken forward/cross-references** — a promise a later page never keeps (the *semantic* half;
   `verify.py` already catches a link to a missing file — this axis catches the unkept promise).

## Governing principles

- **Perspectives don't decorrelate reviewers — *axes of independence* do.** Several critics on the
  same model in one context share blind spots (this is exactly what an authoring skill's inline
  critic loop is). Decorrelate with *off-axis* instruments: a whole-document scope, code-grounding
  (verify, don't recall), different model weights, and an adversarial adjudicator.
- **The whole-document consistency pass is the centerpiece, not one of N equals.**
- **Shift the review left.** Lock the load-bearing decisions before writing (the registers below)
  and check each page against them as authored, so a wrong analogy/term cannot propagate.

## The registers (Phase 0 — prevention, owned by the authoring skill)

Before pages are written, the authoring skill should lock and record (see `house-style.md`
Section 5a):
- **Analogy register** — one analogy per concept, its exact *shape*, and its direction
  (higher/lower-is-better). Test each analogy against the real idea before adopting it.
- **Term register** — the canonical word per concept, and any word reserved to one meaning.
- **Honesty/maturity posture** — the built / `[designed, not yet built]` / measured-vs-illustrative
  markers, owned by one page and cross-linked, never restated verbatim.

doc-critic's Step 3 confirms these exist; their absence is the first finding.

## The review axes (run blind, then adjudicate)

Run each in its own fresh context, blind (the docs + the house-style rules in neutral language —
never prior findings). Size to the stakes tier (the profile says how many).

1. **Whole-document consistency** *(centerpiece — run on the entire set at once)* — internal
   contradictions, term collisions, analogy drift, broken cross-references, honesty drift. Catches
   classes 1, 2, 6, 7.
2. **Code-grounded correctness** — *verify, don't recall*: recompute every stated figure, read the
   source and decision records, run the commands the docs claim, and check each analogy for
   *technical* fidelity (a teaching doc's analogies carry the load, so a friendly-but-wrong analogy
   is a signature failure). Tag each claim VERIFIED / ASSERTED / NEEDS-CODE-CHECK. Catches classes
   3, 5, and the technical half of 2.
3. **Beginner floor** — every term defined on first use; every self-check answerable from the prose;
   every optional depth box skippable without leaving a hole. Catches class 4 and floor clarity.
   *One reader is enough — do not multiply same-model reader personas.*
4. **Adversarial adjudicator** *(runs last, sees 1–3)* — "what did they all miss, where are they
   wrong, which agreement is just shared bias?" Re-verifies load-bearing claims itself, reconciles,
   and produces the single ranked register.

For a flagship/public gate, add a **different-vendor pass** (blind), run by the owner outside the
skill (Step 5), to decorrelate model weights.

## Non-negotiable process rules

- **Blind, then adjudicate.** Never give an independent axis the prior findings, the running
  register, or the house-style file verbatim *before* its own pass — it anchors them and they miss
  what the others missed. Share findings only at the adjudication step.
- **Give reviewers the contract in neutral language**, not the skill-authored rule file (it carries
  the authors' framing and blind spots).
- **Verify, don't recall.** Code-grounding is the single highest-yield axis for any doc with
  checkable claims. Recompute, read source, re-run. Tag VERIFIED / ASSERTED / NEEDS-CODE-CHECK.
- **Merge → edit once.** Gather all independent input before the owner touches the docs.
- **Reconcile reader-vs-expert by layer, never by averaging.** The floor must be simple AND true at
  once; extra precision goes in a box (house-style Section 1/2).

## Severity and the gate

- **BLOCKER** — a reader is left believing something false, or an internal self-contradiction.
  *Blocks publishing.*
- **MAJOR** — needs a second read; a misleading analogy; a missing load-bearing idea; an undefined
  load-bearing term. *Recommended fix.*
- **MINOR** — wording, ordering, a clunky sentence. **NIT** — polish.

After fixes land, re-run `verify.py` and re-check the BLOCKERs specifically before publishing.

## Efficiency — scale to stakes

| Stakes | Axes |
| --- | --- |
| Small edit | code-grounded correctness + whole-document consistency |
| Normal batch | + beginner floor + adversarial adjudicator |
| Flagship / public gate | all four + the different-vendor pass |

Do not run three or four redundant same-model reader personas — that is the lowest-yield spend; one
floor reader is enough.

## Why this shape (the evidence)

The suite's own multi-instrument review of a learning track established it: the highest-severity
findings — a doc claiming report output the code did not emit (code-grounded axis); a page asserting
a safeguard it later disowned (whole-document axis); an analogy teaching the wrong shape for a core
term (whole-document axis) — were each caught by exactly **one off-axis instrument**, and **none** by
parallel same-model reader personas. Correlated reviewers share blind spots; the off-axis
instruments catch the worst items. That is the whole case for this playbook.
