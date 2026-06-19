# UX Design

## 2026-06-17 correction

- `/ui` is the operational workspace, not a landing page.
- The visible Account ID field is removed.
- The top error region, key controls, four model panels, live progress, synthesis, and partial-result notices are first-class states in the current UX.

## Scope

The Release 1 UX is a work-focused query workflow, not a marketing landing page. The first screen for authenticated users should support entering a query, confirming safety/privacy boundaries, selecting four models, reviewing cost, tracking progress, and comparing the final result.

## Information Architecture

| Area | Purpose | Requirements |
|---|---|---|
| Query workspace | Primary query input, four model slots, warnings, cost estimate, submit action. | FR-001 through FR-006 |
| Progress view | Shows orchestration stage, per-model status, fallback usage, elapsed time, and partial-result readiness. | FR-007, FR-010, NFR-001, NFR-010 |
| Results view | Presents model answers, sources, debate rounds, synthesis, cost, elapsed time, and provider notices. | FR-009, FR-013 |
| Provider config | Provider keys are configured in the server environment and never entered in the UI. | FR-011, NFR-006 |
| Authentication boundary | Blocks provider-consuming actions for anonymous visitors. | FR-001, NFR-005 |

## Primary User Flow

1. User signs in.
2. User sees sensitive/private-data warning and high-stakes decision-support boundary near query entry.
3. User enters query.
4. Four model slots load with defaults and can be replaced with OpenRouter-supported model IDs from the live catalog when available.
5. User requests cost estimate.
6. If estimated cost is at or below USD 0.15, submit is available.
7. If estimated cost is above USD 0.15 and at or below USD 0.25, UI requires explicit confirmation.
8. If estimated cost is above USD 0.25, UI blocks execution unless a future approved override exists.
9. Progress view shows initial answers, debate round one, debate round two, and synthesis.
10. Results view separates model outputs, source links, debate outputs, final consensus, disagreement, uncertainty, and recommendation.

## Required UI States

| State | UX Requirement | Trace |
|---|---|---|
| Anonymous | Query execution controls are unavailable and the workspace indicates provider access is not configured for execution. | AC-001 |
| Empty authenticated | Query input, four defaults, warnings, and estimate action are visible. | AC-006, AC-007 |
| Invalid model slot | Field-level error identifies which model ID is invalid. | AC-008 |
| Cost estimate normal | Cost is shown; user can submit. | AC-009 |
| Cost confirmation | Cost is shown with explicit confirmation before submit. | AC-010 |
| Cost blocked | Submit is unavailable; reason is visible. | AC-010 |
| Active query exists | New execution is blocked; link to active run is shown. | AC-003 |
| Running | Stage progress shows provider calls, fallback, debate rounds, synthesis, elapsed time. | AC-027 |
| Partial result | Missing steps are listed and available outputs remain reviewable. | AC-022 |
| Completed | Model answers, source links, debate outputs, synthesis, cost, elapsed time are visible. | AC-027, AC-028 |
| Provider failure | User-safe notice names the failed step without exposing secrets. | AC-015 |
| Wrong-account access | Access denied without leaking whether another user's run exists. | AC-032 |

## Result Layout

- Keep four model answers visibly distinct from debate and final synthesis.
- Source links must appear close to the claim or model answer they support.
- Final synthesis must have separate sections for consensus, disagreement, source support, uncertainty, and recommendation.
- Provider failure notices and partial-result explanations must be visible near the affected sections.
- Cost and elapsed time should be visible but secondary to answer auditability.

## Form Validation

- Query text is required.
- Exactly four model slots are required.
- Duplicate model IDs may be allowed unless later product policy forbids them; if allowed, the UI should make duplicates obvious.
- Safety/privacy warnings must be shown before execution.
- Cost confirmation must be explicit when required; passive visibility is not enough.

## Accessibility Requirements

- Core workflow must meet WCAG 2.2 AA for keyboard operation, focus visibility, labels, warning readability, result navigation, and error messages.
- Progress changes must be announced through accessible status regions.
- Tabs or segmented controls used for model/debate/result navigation must be keyboard operable and preserve visible labels.
- Warnings and errors must not rely on color alone.
- Source links must have discernible text.

## Responsive Behavior

- Desktop: Use a dense workspace layout with query setup and status visible without unnecessary hero content.
- Tablet/mobile: Stack query input, model slots, cost controls, progress, and result sections; keep result navigation sticky only if it does not cover content.
- Long model IDs and URLs must wrap or truncate with accessible full-value disclosure.

## Usability Risks

| Risk | Mitigation |
|---|---|
| Users over-trust a polished synthesis. | Keep disagreement, uncertainty, and decision-support framing visible. |
| Users miss provider failures. | Show per-step notices and partial-result summary. |
| Cost confirmation becomes confusing. | Use explicit estimate, threshold reason, and confirmation state. |
| Four outputs become hard to compare. | Keep model cards/sections stable and label each by slot and model ID. |
| Warnings become ignored copy. | Place warnings near submit and result recommendation, not only in static policy text. |

## Traceability

- FR-001 through FR-013 map to the primary workflow.
- NFR-007, NFR-008, and NFR-009 define warning and accessibility requirements.
- AC-001 through AC-036 define required UI states and validation paths.
