# Mermaid Module-Level Diagram (domain entities)

## Source Requirements
- FR-001 through FR-013; FR-015 (Release 2 evaluation entities)
- AC-001, AC-038 through AC-043

## Diagram

```mermaid
classDiagram
    class QueryRun {
        state: draft|cost_review|accepted|...|completed
    }
    class ModelSlot
    class ModelAnswer
    class DebateRound
    class Synthesis
    class CostRecord
    class RunEvaluation
    class TrustScore

    QueryRun "1" --> "4" ModelSlot
    QueryRun "1" --> "*" ModelAnswer
    QueryRun "1" --> "*" DebateRound
    QueryRun "1" --> "1" Synthesis
    QueryRun "1" --> "1" CostRecord
    QueryRun "1" --> "0..1" RunEvaluation
    RunEvaluation "1" --> "1" TrustScore
```

## Review Notes
The entity list and Release 2 additions (`RunEvaluation`, `TrustScore`,
`EvalJudgeVerdict`) are from `docs/21-domain-model.md`'s Entities table.
`EvalJudgeVerdict` is omitted from the diagram (advisory Layer B output, off in every
current deployment) — see 13-mermaid-sub-module-level.md for that detail.
