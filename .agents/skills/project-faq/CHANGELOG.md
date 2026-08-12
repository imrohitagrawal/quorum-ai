# Changelog — project-faq skill

Skill-specific changes. Shared/suite changes live in the root `CHANGELOG.md`. Format follows Keep a
Changelog.

## [1.2.1] — 2026-06-22

Picked up in suite-hardening pass 2 (root `CHANGELOG.md` 1.0.0).

### Fixed
- **`{{today}}` is now documented as a runtime token, not an undefined placeholder.**
  `references/faq-method-and-question-bank.md` used `{{today}}` for `last_reviewed`, but `today` backs
  to no profile key. The reference now points at the new "Runtime tokens" section in
  `project-profile.md` (where `{{today}}` = build date is declared once), and the suite's new
  placeholder-resolution gate confirms every `{{...}}` resolves. (Closes `CROSS-SKILL-FINDINGS.md` F5;
  the shared declaration + the build-time check are recorded in the root changelog.)

## [1.2.0] — 2026-06-20

Rides the suite-hardening pass (root `CHANGELOG.md`). These are the FAQ-generator-specific parts;
the shared verifier/standards changes (secret-PII scan, staleness check, footer-aware readability,
active render-restatement gate) are recorded there and reach every skill.

### Added — make the right thing automatic in `assets/faq_generator.py`
- **First-class `credits` block.** `licensing-and-credits.md` Section 4 wants an About & credits block
  in the doc (the internal variant especially); previously the author hand-composed it from paragraphs.
  Added a `credits` block type (heading, optional intro, and label/value rows) so the About & credits
  panel is one block, not a manual assembly. It carries the attribution line, maintainer, and the
  licence link, is built from profile values (never a hard-coded name), does **not** replace the `©`
  footer, and carries only the short licence line — never the full "AS IS" disclaimer (that stays in
  LICENSE, off the page). Styled `.box-credits` variant added.
- **`last_reviewed` field.** The generator now emits a machine-readable `<meta name="last-reviewed">`
  plus a visible `Last reviewed: YYYY-MM-DD` stamp from a `last_reviewed` field (render-contract.md
  P2). This is what the new suite staleness check reads — so the FAQ's "milestone artifact with a
  last-reviewed date" claim is now enforced, not just stated.

### Changed
- **SKILL.md (Step 4, the licensing paragraph, the self-evaluation checklist).** Document setting
  `last_reviewed`, building the About & credits panel with the `credits` block, and the new secret/PII
  and staleness gates. Version line bumped to v1.2.0.
- **`references/faq-method-and-question-bank.md`.** The generator-driving example now sets
  `last_reviewed` and includes an About & credits tab built with the `credits` block, all using the
  `{{key}}` placeholder convention.
- **Demo (`_demo()`).** Sets `last_reviewed` to today (so the demo stays green and models correct
  usage), adds an About & credits tab with a `credits` block, and gives the overview a representative
  multi-paragraph plain-English answer (a one-line stub was never realistic against the skill's own
  depth bar). The demo verifies clean: 0 FAIL, 0 WARN, reading grade ~7.4, staleness within window,
  secret scan silent.

## [1.1.0] — 2026-06-20

### Fixed — the licensing gate the skill promised but could not meet
- **The generator now renders a `©` licence footer.** `assets/faq_generator.py` previously emitted
  only a decorative watermark, so a FAQ built by following this skill **failed `verify.py`** — the
  internal-set `©` check (the FAQ's `scope_project_faq` is `internal`) and the public per-page `©`
  check both fired, despite the SKILL.md claiming "every page carries the licence footer". Added an
  optional `footer` (alias `licence_footer`) that renders as a `contentinfo` `<footer>` carrying the
  `©` line, spanning the layout, distinct from the watermark. `licensing-and-credits.md` Section 2
  already required this ("the watermark does not satisfy the footer requirement"); the generator now
  complies. The demo `_demo()` carries a compliant internal footer, and `build_faq` prints a stderr
  notice if the rendered page has no `©` (so a missing footer is loud, not silent). Verified: an
  internal-scope page now passes (0 FAIL) where it previously failed (1 FAIL), and a public-scope
  forced run passes the per-page `©` and licence-id checks.

### Added — the operational layer
- **"Before you start" section**: the inputs the FAQ needs (a populated repo + the profile), *when*
  to run it in a Claude-Code build (a milestone artifact — not an empty repo, not per commit;
  refreshed per milestone), and how it sequences with the other six skills (producer/consumer order +
  a use-this-not-that line against each sibling).
- **Description** gained a use-this-not-that boundary: not a concepts course (learning-track), not the
  deep design-rationale doc (architecture-and-decisions), not a single-task how-to (usage-guide), not
  contributor onboarding (onboarding-companion).

### Changed
- **Repo-first made explicit (Step 4 + Step 6).** The verified HTML page is written to the repository
  first (e.g. `docs/faq/index.html`); publishing is a separate, later step; never author in the
  target. Step 4 also wires the licence `footer` from `references/licensing-and-credits.md` (internal
  or public variant by scope, built from profile keys, never a hard-coded name).
- **Licensing paragraph** made concrete for a single HTML page: footer in the page, an About &
  credits block, and a `LICENSE` in the repo, with the disclaimer referenced from the profile
  (`{{licence_disclaimer}}`) — referenced from the shared standard, not restated.
- **Profile-key names aligned** to `scope_project_faq` / `grade_target_project_faq` (the canonical
  keys the verifier resolves from `--skill project-faq`); the legacy short `*_faq` names are gone from
  the prose.
- **Method reference** (`faq-method-and-question-bank.md`): the generator-driving dict example now
  carries `footer: "{{licence_footer}}"`, and the watermark placeholder uses the `{{watermark}}`
  convention instead of an angle-bracket placeholder.

### Resolved — inbound cross-skill finding
- **CROSS-SKILL-FINDINGS.md F1** (the HTML→wiki conversion restated in Step 6). Step 6 now states only
  the reader-facing consequence (the live tabbed widget is unavailable on a wiki) and points to
  `render-contract.md` Section 1a for the per-target degradation; the per-element mapping is no longer
  duplicated here. The suite render-restatement lint goes clean on this skill.

### Unchanged
- No shared file was changed in this pass (the fix was bespoke generator + SKILL.md). The bespoke
  content of the other six skills is untouched.
