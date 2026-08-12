# Templates

Project-agnostic patterns extracted from real, completed work in this repo,
written so they can be copied into a **different** project and filled in —
unlike the documents they're extracted from, which stay full of quorum-ai's
specific branch names, commit SHAs, file paths, and feature IDs.

## Why this is separate from `.agents/skills/`

`.agents/skills/` holds executable skill bundles vendored wholesale from a
separate private skills repository (see `configs/external-skill-registry.json`
— each entry there is independently versioned and gets replaced as a complete
folder on sync). Files here are plain reference documents, not runnable skill
bundles: nothing in `templates/` is loaded, executed, or synced by any script
in this repo. Copy what you need by hand.

## What's here

- `feature-slice-ultracode-prompt-template.md` — the methodology (evidence-first
  execution, TDD RED→GREEN, bounded adversarial review, hermetic $0 CI,
  docs-before-code, a Definition-of-Done that names exact gate commands)
  distilled from `R2-S2-S4-ULTRACODE-PROMPT.md`, a real, completed execution
  of this pattern in this repo (Release 2: Trust & Evaluation, slices S2-S4,
  shipped 2026-07-21/22). Read that file for the fully-worked, project-specific
  example this template was extracted from.
