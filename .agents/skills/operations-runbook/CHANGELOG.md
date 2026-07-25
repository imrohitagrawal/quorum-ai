# Changelog — operations-runbook skill

All notable changes to this skill are recorded here. Format follows Keep a Changelog; versions follow
Semantic Versioning. This skill is documentation-as-code: it is versioned, and a runbook it produces
should keep its own short changelog too.

## [1.1.1] — 2026-06-22

Picked up in suite-hardening pass 2 (root `CHANGELOG.md` 1.0.0).

### Fixed
- **`SKILL.md` now names the canonical profile keys.** It referred to the legacy stems
  `grade_target_runbook` / `scope_runbook`, which resolved only through the verifier's alias map.
  Aligned to `grade_target_operations_runbook` / `scope_operations_runbook` so the verifier resolves
  the key directly with no alias fallback. Prose-only; behaviour was already correct via the alias.
  (Closes `CROSS-SKILL-FINDINGS.md` F7.)

## [1.1.0] — 2026-06-20

### Added
- **"Before you start (inputs, timing, and where this sits)" section in `SKILL.md`.** The skill had
  no operational framing — the weakest area for the suite. It now states, with no hand-waving:
  - **Inputs:** operable component(s) emitting signal; their failure modes / FMEA; dependencies;
    dashboards and alerts; and the service-level-objective register to **link** (never restate). Plus
    the project profile.
  - **When to run it — per component, as each becomes operable; not on an empty repo, not every
    commit.** A runbook can only be truthful once the component runs, so it is written when the
    component reaches its Definition of Done and then **walked through once** (an untested runbook is
    a guess), refreshed per milestone and after every incident. It starts with the first shippable
    slice; it is not a single pass saved for the end. A recovery procedure **may** be drafted from
    the design early, but the unvalidated parts carry the `[designed, not yet built]` marker and are
    confirmed when the component runs — draft-from-design is allowed, asserting an unwalked path is
    not.
  - **Producer/consumer placement and use-this-not-that:** a consumer of the architecture work (the
    failure modes and dependency map) that links the SLO register; boundaries against usage-guide
    (end-user how-to), architecture-and-decisions (design rationale), project-faq (look-up Q&A), and
    onboarding-companion (contributor ramp).

### Changed
- **Description gains a use-this-not-that boundary** (947/1024 chars): operator-facing, not an
  end-user how-to (usage-guide), design rationale (architecture-and-decisions), or look-up Q&A
  (project-faq). Reciprocal to the pointer architecture-and-decisions already carries.
- **Freshness stamp is now machine-readable.** The runbook's freshness stamp was
  `Last tested: [date …]`, which the shared verifier's staleness check (it reads a
  `Last reviewed: YYYY-MM-DD` stamp, render-contract.md P2) **could not read** — verified: it
  returned "no machine-readable last-reviewed date". `SKILL.md` step 5, the quality-bar bullet, and
  `assets/runbook-entry.template.md` now use the canonical `Last reviewed: YYYY-MM-DD` ISO stamp
  while keeping the runbook meaning (the date it was last *walked through*). The staleness gate now
  fires on runbooks this skill produces. No shared file changed — this skill adopted the existing
  stamp format.
- **References block lists `render-contract.md` and `assets/publish-targets.yaml`**, which the
  repo-first publish step (step 6) already pointed to.

### Fixed
- **CROSS-SKILL-FINDINGS F6 (inbound) resolved.** The entry template used `[...]` square-bracket
  slots — a second placeholder style alongside the suite's `{{key}}`. Resolution (F6 option a):
  `assets/runbook-entry.template.md` now states explicitly that the square-bracket slots are
  **author-fill** (replaced by hand per entry), deliberately distinct from `{{key}}` profile
  placeholders, because a runbook's component / owner / links are per-entry values, not profile keys
  — converting them to `{{…}}` would imply keys that do not exist. The slots are kept as-is, as the
  finding advised. For consistency, the incident-timeline slots in `references/incident-response.md`
  were switched from `<…>` to `[…]` so author-fill uses one style throughout the skill (the suite
  discourages `<…>` placeholders).

## [1.0.0]

- Initial operations-runbook skill: workflow, runbook structure, OPS/CORR failure classes, the
  failure-mode entry template, and the `runbook-method` / `observability-and-slo` /
  `incident-response` references. Shared standards (`house-style.md`,
  `licensing-and-credits.md`, `render-contract.md`, `verify.py`) are copied in at build time.
