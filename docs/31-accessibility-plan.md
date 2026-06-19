# Accessibility Plan

## Checks

- Keyboard navigation
- Screen reader labels
- Focus order
- Contrast
- Error messages

## Current Implementation Notes

- The UI now includes a skip link to `#main-content`.
- The main workspace container is focusable so the skip link lands on a meaningful target.
- Related model selectors are grouped in a `fieldset` with a `legend`.
- Dynamic run state, model outputs, debate output, synthesis output, and notices are exposed through polite live regions.

## Evidence

- Local browser verification confirmed the skip link is present and the core workflow remains usable after the accessibility update.
- Automated contract tests cover the skip link, main landmark target, fieldset/legend grouping, and live-region markup.
- Manual browser audit on 2026-06-17 confirmed:
- keyboard order reaches skip link, main content, theme toggle, question field, model selectors, action buttons, and checkbox in a sane sequence;
- the skip link moves focus to the main content container;
- live progress and result regions remain exposed in the accessibility tree during the workflow;
- the previous focus-indicator contrast and primary-button text contrast issues were corrected.

## Remaining Review

- Full screen-reader testing with VoiceOver/NVDA and a broader WCAG 2.2 audit are still needed before making a formal accessibility claim.
