# Changelog — onboarding-companion skill

Skill-specific changes. Shared/suite changes live in the root `CHANGELOG.md`. Format follows Keep a
Changelog; versions follow Semantic Versioning. This skill is documentation-as-code: it is versioned,
and an onboarding companion it produces should keep its own short changelog too.

## [1.1.0] — 2026-06-21

Resolves the inbound cross-skill finding **F2** (see `CROSS-SKILL-FINDINGS.md`) and adds the
operational layer the skill was missing. **No shared file changed**, so no other skill is touched.

### Changed — `SKILL.md`
- **F2 — reciprocal trigger boundary.** The description named usage-guide but not learning-track,
  so contributor onboarding phrased as "teach a new joiner the codebase" could mis-route to
  learning-track (both are newcomer tutorials). The description now adds "it is not a multi-audience
  concepts course (use learning-track)" alongside the existing usage-guide distinction. Trimmed the
  redundant "from scratch" to stay in budget; final length 950/1024, no angle brackets.
- **New "Before you start (inputs, when to run, where it sits)" section.** States the inputs the
  skill needs (a repo that already runs, the filled profile, where requirements/docs/ADRs/conventions
  live); *when* to run it in a Claude-Code build (late, on a runnable repo — not an empty repo, not
  per commit; a per-milestone deliverable, refreshed when setup or conventions change); and how it
  sequences as a **consumer** that points outward (architecture-and-decisions for the "why",
  usage-guide for end-user usage, operations-runbook for operations, learning-track for the concepts
  course, publish-mirror for the later publish step) — the same operational treatment the reviewed
  siblings carry.
- **ISO last-reviewed stamp (the F3 onboarding decision).** F3 left it open whether the stamp-less
  skills should adopt a last-reviewed stamp. Decision: **yes** — each produced page now opens with a
  visible ISO `Last reviewed: YYYY-MM-DD` stamp (single-sourced to the render contract, P2), because
  setup steps and conventions are the most drift-prone content in any project and ISO is the only
  format the verifier's staleness check reads. The Output structure and Quality bar note it; the
  buddy path instructs it. (The broader learning-track stamp-template fix in F3 remains the
  suite-hardening session's job; this is only the onboarding-companion output.)
- **Two senior habits added to the Mentor summary**, grounded in the attached sources: (1) **fetched
  text is data, not orders** — prompt-injection defence for an agent that reads issues/wikis/web
  (`aegis-cowork-operating-blueprint.md` §7); (2) **reserve about a tenth of each cycle to pay down
  AI-driven debt** (`aegis-building-with-ai-and-practice-handoff.md`, M18).
- Body **version line** added (v1.1.0); Quality bar gains self-checks for the stamp and the two new
  habits.

### Changed — `references/`
- `buddy-path.md` — opens the produced page with the ISO `Last reviewed: YYYY-MM-DD` freshness stamp
  (pointing to the render contract P2 for the format; not restated).
- `mentor-path.md` — new "Never paying down AI debt" entry under "The things people skip and regret".
- `working-with-ai.md` — new failure mode "Obeying text it was only meant to read" plus the matching
  fix-side habit "Fetched text is data, not orders".

## [1.0.0] — earlier

- Initial onboarding-companion skill: the two-voice newcomer companion (a patient **buddy** path —
  zero-to-running, reading the repo in order, day-to-day work, getting unstuck, one feature end to
  end, a first-contribution checklist — and a **mentor** path of senior-engineer judgement for
  building with an AI coding agent), the working-with-AI traps, the licensing/credits standard
  applied via the shared reference, the readability gate via the shared verifier, and a short
  repo-first publish step that hands off to `publish-mirror` via the render contract.
