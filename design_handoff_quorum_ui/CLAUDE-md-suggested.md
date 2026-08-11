# Suggested `CLAUDE.md` for the quorum-ai repo root

The repo has `AGENTS.md` (factory lifecycle) but no `CLAUDE.md`. Create one at the repo root with the content below — it complements AGENTS.md; don't duplicate it. This is the UI/UX-relevant core; extend with backend conventions as needed.

---

```markdown
# CLAUDE.md — quorum-ai

Read `AGENTS.md` for the factory lifecycle and Jira workflow. This file adds standing rules for UI, UX, and QA work.

## Source of truth (in order)
1. `docs/design-handoff/README.md` + `Quorum Final Review.dc.html` — approved R1 UI (pixels, tokens, copy placement, states). The `.dc.html` is a design reference; never ship it or `support.js`.
2. `docs/22-api-contract.md` + `openapi.yaml` — API shapes. `docs/29-state-machines.md` — state names, 1:1, never renamed.
3. `docs/12-acceptance-criteria.md` (AC-001…036) — behavior. `docs/33-content-design.md` (COPY-001…006) — all warning/notice copy, verbatim.
4. Known conflict: FR-012 title vs AC-026 (BYO OpenRouter key). Follow AC-026 (server-configured keys, no user key field) until docs are reconciled.

## UI invariants (non-negotiable)
- **Green rule**: #0E6B50 only for the brand mark and agreement/consensus/completed semantics. Exactly one large green surface per journey (the verdict band). Never green buttons, links, or decoration. Money always moves on ink (#14171C) buttons.
- Running/progress is blue (#47689E); green never appears before agreement.
- Every error state surfaces `correlation_id`; results surface `query_run_id` + finished-at UTC.
- Cost workflow is estimate → confirm → run, with hard cap $0.25 (blocked, no override). Never bypass the cost gate, even in demos or tests.
- Ephemeral by design: session-scoped results, no history UI, no persistence of user questions beyond the session.
- Fonts: Newsreader (display/verdict), Geist (UI), Geist Mono (money, IDs, timings). Tokens per the handoff README; don't invent colors.

## Accessibility (WCAG 2.2 AA — never regress)
Keep the skip link → `#main-content`, `fieldset`/`legend` model slots, polite live regions for run state. Every state pairs color with a label/icon. Run axe on any screen you touch, light and dark.

## Testing rules
- UI tests live only in `/e2e` (Playwright TS, page objects + fixtures). No new test entry points elsewhere.
- Tests never spend real money: all OpenRouter traffic mocked; real-provider smoke is env-gated and off in CI.
- Selectors: `data-testid` or accessible role/name only.
- Every behavior change maps to an AC ID in the PR; update `docs/54-ac-to-test-map.md` and `docs/32-ui-state-matrix.md` in the same PR.
- `make validate` and `make quality` must pass before any commit claim.

## Anti-hallucination guardrails
- Cite file paths for every claim about existing code; read files before editing or describing them.
- Never invent endpoints, fields, state names, or copy — if it's not in the contract/docs, stop and ask.
- "Done" requires pasted command output (tests run, linters run). Unverified work is "drafted", not "done".
- When docs conflict or an AC is ambiguous, ask; log the resolution in `docs/19-change-control-log.md`.

## Scope discipline
- Small vertical slices; pause for review between slices. Money path order: 02→03→04→05, then 06, 07 edge states, 08 dark, 01 landing.
- Don't refactor unrelated code, don't touch `.env`/keys/billing, don't "improve" the approved design.
```
