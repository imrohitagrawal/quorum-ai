# Validation Gates

## Gate model

Validation gates are intentionally executable. A phase is not complete because a file exists; it is complete only when the required content, mappings, and evidence exist.

## Required gates

- G0: Intake
- G1: Discovery
- G2: Living Specification
- G3: Architecture
- G4: Security, Privacy, and AI Safety
- G5: Quality and Testing
- G6: Implementation Readiness
- G7: Release Readiness
- G8: Operations Readiness

## Scripts

Run:

```bash
make validate
```

or:

```bash
python scripts/validate_all.py
```

## Stop rule

Failed validation blocks the next phase unless the owner explicitly records risk acceptance.
