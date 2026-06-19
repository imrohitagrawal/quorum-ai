# C4 Component Diagram

## Source Requirements
- FR-001
- AC-001

## Diagram

```mermaid
flowchart LR
    User[User / Actor] --> Product[Product Capability]
    Product --> Service[Application Service]
    Service --> Data[(Data Store)]
    Service --> Evidence[Tests / Logs / Metrics / Release Evidence]
```

## Review Notes
Replace placeholder nodes with approved architecture only.
