# Review profiles — per doc type

> A profile tells doc-critic which error classes to weight, which axes to run, and the stakes tier,
> for one doc type. The **learning-track** profile is implemented; the rest are stubs to fill when
> the suite reviews that doc type. The method (`review-playbook.md`) is shared; only the emphasis
> differs.

---

## learning-track  *(implemented)*

- **Verifier flag:** `--skill learning-track` · **Scope:** usually `public` · **Doc set:**
  `docs/learning/` (modules `M*.md` + `glossary.md` + `about-and-credits.md`).
- **Stakes tier:** **flagship / public** — run all four axes **plus** the different-vendor pass
  (Step 5). A public learning track is the suite's most-read, most-cited output.
- **Error classes to weight** (all seven apply; these bite hardest here):
  - **2 — analogy-shape + term collisions.** A learning track leans on analogies to carry the
    teaching, so a technically-wrong-but-friendly analogy, or one word meaning two things across
    modules, is the signature failure. Check each analogy for shape *and* direction.
  - **1 — contradictions** across the many modules (a safeguard stated as in-force on one module,
    disowned on another).
  - **4 — term/glossary.** The glossary must genuinely be the single reference: every floor term has
    a beginner-correct entry with direction stated; nothing load-bearing is undefined on first use.
  - **5 — simplification-gone-false.** Beginner-first simplification of technical/AI content is
    exactly where "simple but false" creeps in; the code-grounded axis must check the technical floor.
  - **6 — honesty drift.** The built / `[designed, not yet built]` / measured-vs-illustrative markers
    and any maturity ordering must be exact and consistent across all modules.
  - **7 — broken forward-references.** Modules forward-reference each other heavily ("you meet X in
    module N"); each promise must be kept by the target module.
- **Doc-type-specific hunts:**
  - The two-layer floor: the plain-words layer must stand alone if every optional depth box is
    skipped; depth lives only in the boxes.
  - Self-checks: each must be answerable from what that module actually taught.
  - The worked example threads through and deepens; recaps add a new angle, not a re-run.
- **Axes:** whole-document consistency (over the whole `docs/learning/` set at once) · code-grounded
  correctness · beginner floor · adversarial adjudicator · different-vendor pass.

---

## architecture-and-decisions  *([designed, not yet built])*
Scope public, grade ~11, one technical reader. Would weight **3 (code-vs-doc)** and **6 (honesty:
built-vs-designed in the decision treatments)** highest; analogies are fewer but the
decision-rationale ("why", alternatives, failure modes) must match the ADRs and the code. Diagram
fidelity (C4 levels, the claims each diagram makes) is a doc-type hunt.

## project-faq  *([designed, not yet built])*
Scope internal, grade ~8, HTML. Would weight **4 (term/answer completeness)** and **1 (contradictory
answers across the bank)**; each answer's two worked examples checked for fidelity; the generated
HTML's footer/credits/stamp checked by `verify.py` first.

## usage-guide  *([designed, not yet built])*
Scope public, grade ~2, HTML. Would weight the **beginner floor** axis hardest (the reading grade is
the point) and **3 (do the steps actually work)** via the code-grounded axis running each step.

## operations-runbook  *([designed, not yet built])*
Scope internal, grade ~10. Would weight **3 (code-vs-doc: do the commands/SLOs match reality)** and
**5 (a recovery step simplified into something unsafe)**; the failure-mode-per-entry completeness is
a doc-type hunt.

## onboarding-companion  *([designed, not yet built])*
Scope internal, grade ~7, contributor-facing. Would weight the **beginner floor** (a new joiner) and
**3 (does the setup actually run from a clean machine)**.
