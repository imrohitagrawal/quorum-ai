# Changelog — architecture-and-decisions skill

All notable changes to this skill are recorded here. Format follows Keep a Changelog; versions
follow Semantic Versioning. This skill is documentation-as-code: it is versioned, and an architecture
walkthrough it produces should keep its own short changelog too.

## [1.3.0] — 2026-06-20

### Added
- **`references/failure-mode-method.md` — "prove your own invariant, not the framework's."** The
  "prove each resilience guarantee" section had one worked example (kill the process mid-run, assert
  resume), and that example is a trap: when an orchestration framework already persists state and
  resumes from the last completed step, that test mostly re-checks *the framework's* behaviour, so on
  its own it proves the least. The section now says to aim the injection at the guarantee the project
  actually owns, and adds a second, separate injection — a *poison* item that fails deterministically
  — asserting it retries only to the cap, is parked in dead-letter / quarantine, and does **not**
  loop. That is what pins the "every item reaches exactly one terminal state" invariant (recovery
  mechanism 3, *bounded resume / quarantine*) the runtime does not hand you. The guidance is
  framework-agnostic ("an orchestration framework", no product name) and grounded in the ADR-0017
  failure-mode source note's second-injection step.

### Changed
- **Version → 1.3.0.** `description` unchanged (still 950/1024, no angle brackets): the addition is
  depth behind the existing triggers ("architecture doc", "technical deep-dive", "explain the design
  decisions", "the failure modes"), not new trigger surface, so no description edit was needed.

## [1.2.0] — 2026-06-20

### Added
- **`references/design-note-method.md` (new)** — the method the skill was missing: the deep design
  note for *one significant component*, the artifact the richest source material already is (a
  security/isolation note; a failure-mode note). It teaches selectivity (a note only for high-stakes
  components — a trust boundary, the highest-blast-radius store/gateway, a non-obvious trade-off, not
  every box), a **fixed design-dimension checklist** applied to every note so a gap is visible rather
  than forgotten (mark each dimension covered / referenced / Phase-N / not-applicable, never silently
  omit), a **threat/risk-model-first** structure, values **referenced by key** and a named invariant,
  **component-level NFRs single-sourced with the NFR/SLO register** (the note owns its local targets;
  the register references them, and vice versa), a **per-component FMEA-lite** that regenerates as
  components are added (the local counterpart to the system-wide blast-radius map in
  `failure-mode-method.md` — linked, not duplicated), and a **phased build by temporal decomposition**
  with the forward-compatibility seam and a written deferral trigger.
- **`SKILL.md` — a new Workflow Step 4** ("write a deep design note for each significant component")
  pointing to the new method, plus a `design-notes/` entry in the document-structure block, a
  quality-bar bullet, and a References entry. The new step shifts the later steps by one: failure
  modes is now **Step 5**, NFR posture **Step 6**, mental model **Step 7**, verify **Step 8**, publish
  **Step 9**. Step 5 now states explicitly that it is the *system-wide* failure map and that the
  *per-component* table lives in the design note (Step 4) — link, do not duplicate.
- **`references/nfr-posture-method.md` — two grounded additions.** (1) The error-budget mode now says
  to **derive burn-rate alert tiers arithmetically from the budget definition** and show the working,
  so a threshold is verifiable rather than invented (a fabricated threshold is the same honesty
  failure as a fabricated SLO). (2) The scaling-trigger rule now says to **write the trigger down as a
  concrete forcing condition**, so "scale it later" cannot quietly become "never."

### Changed
- **Version → 1.2.0.** `description` unchanged (still 950/1024, no angle brackets); no trigger-surface
  change — the new method is depth behind the existing triggers ("architecture doc", "design doc",
  "technical deep-dive", "explain the design decisions", "write the technical overview"), so no
  description edit was needed.

### Notes
- **One shared file changed this pass: `shared/verify.py`** (so it touches all seven skills). A new
  low-false-positive **WARN** flags a non-canonical built-vs-designed marker — anything bracketed that
  carries "designed" plus "built"/"yet" but is not the exact token `[designed, not yet built]`
  (a dropped comma, "[designed but not yet built]", "[designed, not built]"). The render contract
  requires that marker to survive every publish target verbatim, and the suite was already 100%
  canonical, so the check adds no noise today and guards the convention against drift. It is
  fence-stripped (a documented example is exempt) and a WARN, never a FAIL. Recorded in the root
  `CHANGELOG.md`. The other shared files (`house-style.md`, `licensing-and-credits.md`,
  `render-contract.md`, `project-profile.md`, `publish-targets.yaml`, `ci/`) were left untouched.
- The licensing gate was re-confirmed against a **non-default** resolution (grade-target and scope
  resolved from the profile and printed as `(profile)`, scope flipped to `internal`): a public page
  with no `©` FAILs, an internal *set* with no `©` anywhere FAILs at set level, and `--license` FAILs
  a dropped warranty disclaimer and an unnamed content licence — so no silent public/internal flip can
  disguise a pass.

## [1.1.0] — 2026-06-20

### Added
- **Operational guidance in `SKILL.md`** — a "Before you start" section answering the three questions
  a new project raises, inverted for this skill's role as the *first producer* the rest of the suite
  builds on:
  - *What this skill needs* — the inputs (filled profile; a designed architecture, at least the
    context and container views plus the worked example; the accepted ADRs with their reasoning; the
    decision log to link to; the contracts and their versioning rule; the stack-with-the-why; any
    failure-mode/runbook material and the live status source). The natural stop is the inverse of the
    consumer skills': you cannot write a decision treatment before the decision is made and recorded —
    if you cannot give the alternatives and the trade-off, read the ADR and the code first.
  - *When to run it* — at design time, per accepted ADR and per milestone; explicitly not per-commit
    and not end-only. Context/container views are authored; component/code views are generated from
    code and kept in lockstep (they drift fastest). Failure-mode and NFR sections are revisited each
    phase. The link-back rule (reference volatile specifics, do not copy) is stated as the
    anti-staleness mechanism.
  - *Where it fits* — this skill runs first/in lockstep with design; use-this-not-that boundaries
    against learning-track (audience and arc), operations-runbook (design-resilience understanding vs
    operator steps), project-faq (narrative vs look-up Q&A), usage-guide, and onboarding-companion.
- **`references/nfr-posture-method.md` (new)** — the non-functional posture told honestly: the
  control-mode distinction (error budget vs spend ceiling vs correctness/regression gate, with
  correctness-as-a-budget called out as a category error); name each SLI's measurement signal;
  provisional-then-ratify with labels; built-vs-designed (no live SLO on an unbuilt component); a
  single-source ownership matrix; scalability by temporal decomposition (name the seam now, build at
  its trigger; a trigger needs metric + source + threshold + owner; validate each limit with a
  scheduled test); and the isolation SLI as a hard regression gate, not a budget. `SKILL.md` Step 5
  and the References now point to it.
- **The reference-tunable-values-by-key rule** — added to the sourcing note in `SKILL.md` and to
  `references/decision-treatment.md`. The single-source rule now covers not just ADR numbers and
  status but every tunable value (a threshold, an `N`, a pixel ratio, a timeout): name the key and
  link the ADR/config that owns it, never paste the figure, because a pasted value drifts the first
  time its source changes.
- **`references/architecture-method.md` additions** — the ≤8-node-per-view cap with split-into-themed
  sub-views for crowded container levels; the authored-vs-generated split (context/container authored
  at design time, component/code generated from code and kept in lockstep, Level 3 hand-drawn only as
  a marked snapshot); marking trust boundaries where untrusted input crosses into the system (the
  prompt-injection path for AI components — ingested text is data, not instructions); semantic
  colour-with-meaning paired with labels (and Okabe–Ito for categorical data); and an optional
  evolution view that shows staged growth while linking live status rather than restating it.
- **`references/failure-mode-method.md` additions** — lead with a blast-radius/dependency map (what
  stops vs what degrades); bounded resume/quarantine as a recovery mechanism (so a poison item cannot
  resume forever); a sharper OPS/CORR split (a retry cannot fix a correctness failure) with the two
  detection clocks (gate-caught vs the slower shift-right clock); the detection-layer's own failure
  (the dead-man's-switch that pages on the *absence* of a heartbeat); and proving each resilience
  guarantee with one targeted fault-injection test rather than a full chaos suite.
- **`--license LICENSE` added to the prescribed verifier command** (`SKILL.md` Step 7), so an author's
  own pre-present pass confirms the LICENSE carries the warranty disclaimer and names the content
  licence — the check the shipped CI gate already runs.
- **`ci/` added to the References**, a version stamp in `SKILL.md`, a **Versioning** section, and this
  `CHANGELOG.md`.

### Changed
- **`description`** — added a use-this-not-that boundary (for one technical reader who can already use
  the system; not a newcomer course → learning-track, not operator recovery → operations-runbook, not
  a look-up Q&A → project-faq). Trimmed to 950/1024 characters, no angle brackets.
- **`SKILL.md` Step 1** now names the canonical profile keys (`grade_target_architecture_and_decisions`,
  `scope_architecture_and_decisions`) instead of the legacy short stems; the quality bar gained the
  newly captured methods (node cap, blast-radius map lead, control modes, value-by-reference, the
  `--license` check).

### Notes
- **No shared file was changed** in this pass. `references/house-style.md`,
  `references/licensing-and-credits.md`, `assets/project-profile.md`, `scripts/verify.py`, and `ci/`
  are shared across the suite and were left untouched, so nothing ripples to the other five skills.
  The verifier was confirmed against this skill (the © footer is a hard fail on public pages;
  `--license` fails a dropped disclaimer or a missing content-licence id) under a profile whose scope
  was flipped to `internal`, so the public/internal resolution is genuinely profile-driven.

## [1.0.0] — 2026-06-18
- Initial architecture-and-decisions skill: workflow, document structure, the C4 architecture method,
  the five-line decision treatment, the failure-mode method, the project profile, and the verifier.
