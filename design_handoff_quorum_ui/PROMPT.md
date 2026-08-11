# Paste this prompt into Claude Code

---

Implement the approved Release 1 UI for the quorum-ai web app.

**Read first, in this order:**
1. `docs/design-handoff/README.md` — the full handoff: screens, tokens, interactions, state & API mapping, accessibility. It is the implementation contract.
2. `docs/design-handoff/Quorum Final Review.dc.html` — open it in a browser. High-fidelity reference for all screens (01 Landing · 02 Composer · 03 Cost gate · 04 Live run · 05 Result · 06 Transcript · 07 seven edge states · 08 Dark). Dashed tags on screens are spec notes, not UI. Source of truth for any measurement not in the README.
3. Repo specs it was built against: `docs/30-ux-design.md`, `docs/10-functional-requirements.md`, `docs/12-acceptance-criteria.md`, `docs/22-api-contract.md`, `docs/29-state-machines.md`, `docs/33-content-design.md`, `docs/31-accessibility-plan.md`.

**Rules:**
- The HTML file is a design reference, not production code. Recreate it in the existing `/ui` stack and patterns; do not ship the HTML or `support.js`.
- Preserve the already-implemented accessibility scaffolding (skip link, fieldset/legend model slots, polite live regions) and keep WCAG 2.2 AA.
- Screen 02 (workspace) is the R1 entry screen; screen 01 (landing) is its anonymous/empty state — do not build a separate marketing page for R1.
- The green rule is law: green (#0E6B50) only for the brand mark and agreement semantics; exactly one large green surface per journey (the verdict band); money always moves on ink (#14171C) buttons.
- Wire states 1:1 to `docs/29-state-machines.md` and endpoints/errors to `docs/22-api-contract.md`; surface `query_run_id` + `correlation_id` on the receipt and every error state; show current-time context (finished-at UTC) on results per FR-013.
- All warning copy comes verbatim from `docs/33-content-design.md` (COPY-001…006).
- Work in vertical slices: 02→03→04→05 first (the money path), then 06, then the 07 edge states, then 08 dark and 01.
- After each slice, run the repo's accessibility/contract checks and map what you built to its AC IDs (AC-001…036) in the PR description.

---

## Can I reuse this in a design chat?

Yes. This same folder works as design context here (the design tool):
- **Same project (best):** start a new conversation in this project and just mention `docs/design-handoff/README.md` or the review file — I can read project files directly, plus the full design history.
- **Elsewhere:** attach the downloaded zip (or paste README.md) and ask design questions against it.
The README is written to be self-sufficient: any designer or engineer (or Claude) can answer layout, token, and state questions from it alone.
