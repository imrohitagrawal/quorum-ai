# Changelog — doc-critic

All notable changes to this skill. Format: [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] — 2026-06-26

### Added
- Initial release. The independent **critic gate** for the documentation suite: the
  human-judgement layer that runs after `scripts/verify.py` (deterministic) and before
  `publish-mirror`, catching the defects a regex/readability verifier cannot — cross-module
  contradictions, analogy-shape errors and term collisions, code-vs-doc mismatches, term/glossary
  gaps, simplifications-gone-false, honesty-posture drift, and broken cross-references.
- Workflow: run `verify.py` first → confirm the registers → spawn a **blind multi-axis critique**
  (whole-document consistency, code-grounded correctness, beginner floor, adversarial adjudicator)
  → emit the different-vendor pass for a flagship gate → write a severity-ranked review register
  to the repo → gate publishing on unresolved BLOCKERs → re-verify.
- References: `review-playbook.md` (the method + the seven-class error taxonomy), `reviewer-prompts.md`
  (blind per-axis templates with `{{key}}` placeholders), `review-profiles.md` (learning-track
  profile implemented; the other five doc types stubbed `[designed, not yet built]`).
- Trigger boundary in the description: distinct from `verify.py` (deterministic), an authoring
  skill's inline critic loop (same-context, prevents during authoring), `per-skill-review-prompt.md`
  (reviews the skills themselves), and `publish-mirror` (publishes).

### Hardened (independent unbiased + expert review, 2026-06-26)
- **Fixed the orphan placeholders** (both reviewers' top finding): the per-run slots
  `[doc_set_path]`, `[audience]`, `[verify_command]` now use the suite's author-fill `[...]`
  convention (filled from the run, like a runbook entry), not `{{...}}` profile tokens; only the real
  profile keys `{{project_name}}` / `{{one_line_summary}}` remain `{{...}}` — closing the suite's
  banned placeholder-does-not-resolve class (the placeholder lint now passes).
- **Register is now mechanically gateable:** every finding gets a stable id (`B1`, `M1`, …) + a
  status, so Step 7 confirms each BLOCKER id is resolved rather than re-reading prose.
- **Systemic findings route outward** to `CROSS-SKILL-FINDINGS.md` (the suite's two-way carry-over
  log) — a whole-document critic is the most likely producer of recurring cross-doc-type defects.
- A consistency fixture for the method's evidence base **ships in the suite's `tests/` golden
  framework** (`run-golden.py`): the learning-track review's three highest-severity findings are each
  locked to the axis the taxonomy obligates to catch them, so the playbook's evidence paragraph and
  its axis-coverage lines cannot drift apart. doc-critic is non-deterministic, so this locks the
  method's docs for consistency — it does not run the critique (`verify.py` stays the deterministic
  gate); it is a suite-level pin, not a per-skill `evals/` dir.
- **Stated the harness dependency, honestly** (a fourth *Honest limitations* item): the blind,
  each-axis-in-its-own-context independence the method relies on is real only in an
  **isolated-subagent** run; in a plain single chat the axes run sequentially in one context and lose
  most of their decorrelation, so such a run is a structured self-review, not an independent gate —
  lean harder on the different-vendor pass, whose decorrelation is from model weights rather than
  context isolation.
- Clarified, per review: auto-chain is via doc-critic's *own* description + an authoring-skill body
  handoff (an authoring skill's description cannot trigger it); reviewers get the *neutralized
  paraphrase* in the shared brief, not the house-style file; the different-vendor pass is "not
  automatable from inside this skill"; class 7 is the *semantic* half (`verify.py` catches
  missing-file links); the description now also names the inline-critic-loop boundary.

### Notes
- Distilled from the suite's own multi-instrument review of a learning track, where the
  highest-severity findings were each caught by exactly one off-axis instrument and none by parallel
  same-model reader personas — the evidence behind the playbook's shape.
