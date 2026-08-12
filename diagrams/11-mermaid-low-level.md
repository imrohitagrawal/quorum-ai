# Mermaid Low-Level Diagram (request sequence)

## Source Requirements
- FR-001 through FR-013
- AC-001, AC-035

## Diagram

```mermaid
sequenceDiagram
    participant U as User (browser)
    participant API as main.py
    participant QR as query_runs.py
    participant CO as costs.py
    participant PR as providers.py (x4 parallel)
    participant DB as debate.py
    participant SY as synthesis.py
    participant EV as evaluation.py

    U->>API: POST /v1/query-runs/estimate
    API->>CO: CostEstimationService.estimate()
    CO-->>U: estimated cost + threshold action
    U->>API: POST /v1/query-runs (confirmed)
    API->>QR: _execute_query_run()
    QR->>PR: produce_initial_answer() x4, parallel
    PR-->>QR: 4 ModelAnswer
    QR->>DB: run_debate_rounds() (2 rounds)
    DB-->>QR: critique
    QR->>SY: produce_final_synthesis() (5 sections)
    SY-->>QR: Synthesis
    QR->>EV: evaluate_layer_a() + build_trust_score()
    EV-->>QR: TrustScore
    QR-->>U: terminal QueryRun (poll or final response)
```

## Review Notes
Function names verified against `src/product_app/query_runs.py`
(`_execute_query_run`, `_evaluate_terminal_run`), `providers.py`
(`ProviderExecutionService.produce_initial_answer`), `debate.py`
(`DebateOrchestrator.run_debate_rounds`), `synthesis.py`
(`SynthesisOrchestrator.produce_final_synthesis`), `evaluation.py`
(`evaluate_layer_a`, `build_trust_score`).
