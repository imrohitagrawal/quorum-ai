# User Journeys

## Journey J-001: Cross-Validate An Important Answer

### Trigger

The user has an important question and does not want to rely on one model's answer.

### Steps

1. User opens the application.
2. User sees warnings that high-stakes outputs are decision support only and that sensitive/private data should not be submitted until privacy controls are defined.
3. User enters one query.
4. User reviews the four default model slots and optionally replaces any model with an OpenRouter-supported model.
5. User starts the run.
6. The system gets source-backed responses from all four models.
7. The system shows each model output with source links.
8. The system runs debate/critique round one, where models review gaps, contradictions, and weak claims in each other's outputs.
9. The system runs debate/critique round two, where models respond to critique and refine their positions.
10. The synthesizer creates the final answer.
11. User reviews consensus, disagreement, final recommendation, and cited support.

### Success Criteria

- The user can see where models agree and disagree.
- The final answer does not hide uncertainty.
- Source links are visible for material claims.
- The result is framed as decision support, not guaranteed truth.

## Journey J-002: Replace Models Before Running

### Trigger

The user wants to compare different OpenRouter-supported models than the defaults.

### Steps

1. User opens the model selection area.
2. User replaces one or more default model slots.
3. The system validates that four model slots are selected.
4. User runs the query using the selected models.

### Success Criteria

- User can replace all four models.
- The UI makes model identity visible before execution.
- Unsupported or unavailable model selections are blocked or clearly explained.

## Journey J-003: Handle A High-Stakes Query

### Trigger

The user asks a medical, legal, financial, safety, or regulated-domain question.

### Steps

1. System detects or receives the query as high-stakes.
2. System shows decision-support-only warning.
3. User chooses whether to continue.
4. If the run continues, the output includes limitation language and source-backed uncertainty.

### Success Criteria

- The product does not present itself as professional advice.
- The warning appears before the user relies on the result.
- The final synthesis preserves uncertainty and disagreement.

## Journey J-004: Sensitive Data Warning

### Trigger

User may include private, personal, confidential, or regulated information in the query.

### Steps

1. System displays a clear warning near query entry.
2. User is told not to submit sensitive/private data until privacy controls are defined.
3. User can revise the query before running.

### Success Criteria

- Warning is visible before submission.
- Product does not claim sensitive-data safety.
- Privacy posture remains honest until controls are designed and validated.
