# Contract and Schema Governance

Use this when the product contains shared schemas, API contracts, event contracts, traceability contracts, or config contracts used by more than one component.

## Golden rules

- Treat shared contracts as platform APIs.
- Within major version `v1`, prefer additive-only changes: optional fields, new enum values, new entities, or new events.
- Removing fields, renaming fields, tightening constraints, changing semantics, or changing required behavior is breaking.
- Breaking changes require owner approval, an ADR, migration plan, and major version decision.
- Run `python scripts/check_breaking.py` before committing contract changes.
- Do not invent fields, enum values, formats, or IDs. Ask or record an assumption.
- Mirror shared patterns from `schemas/_common.schema.json`.
- Every contract change updates `CHANGELOG.md`, relevant assumptions, and examples/fixtures.
- IDs use type-prefixed ULIDs where generated IDs are needed.
- Timestamps use UTC ISO-8601.
- Project/environment-specific values belong in `configs/`, not schemas.

## Review rule

Use `fanatic-critic`, `api-contract-governance`, `traceability-graph-gate`, and `code-quality-review` before shipping contract changes.

## Validation

```bash
python scripts/check_breaking.py
make validate
```
