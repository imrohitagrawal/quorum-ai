# Final Critique And Enterprise V4 Upgrade

## Final staff-principal critique

The Enterprise V3 skeleton had the correct enterprise ambition, but the control layer was not strict enough. It had many useful labels and lifecycle artifacts, but too many checks only proved that files existed. A generated product could still pass validation while containing placeholder requirements, weak acceptance criteria, incomplete NFRs, shallow traceability, and non-evidenced release claims.

The final judgment is:

- the previous skeleton was good enough to **guide Codex**;
- it was not strong enough to **control Codex**;
- this V4 upgrade turns the skeleton into a more enforceable product factory by adding skill contracts, strict gates, source-of-truth reconciliation, Jira/Confluence MCP operating contracts, AI-safety contracts, and production-readiness evidence requirements.

## What was not satisfactory in V3

| Area | Gap | V4 correction |
|---|---|---|
| Jira/Confluence | Policy existed, but tool-backed execution was not modeled deeply enough. | Added Jira/Confluence MCP integration model, sync log, reconciliation rules, and page/update request contract. |
| Validation | Gates checked structure more than quality. | Added `validate_quality_contracts.py`, strict mode, placeholder detection, skill-contract validation, and evidence expectations. |
| Skills | Many skills used similar generic procedure language. | Added a universal skill contract and new expert skills with explicit triggers, inputs, outputs, forbidden actions, validation, and handoff. |
| Learner spec | Living spec existed, but minute domain detail was not captured well. | Added learner spec, glossary, edge-case catalog, UI-state matrix, business-rule catalog, and decision/rationale sections. |
| AI governance | AI grounding existed, but model-risk, prompt registry, eval, and human approval were shallow. | Added AI feature classifier, grounding contract, prompt registry, model risk register, and AI incident-response controls. |
| Security | Security policy existed, but framework mapping and risk exception discipline were thin. | Added OWASP/control mapping, external skill security auditing, permission boundaries, and security exception workflow. |
| Testing | Test folders existed, but AC-to-test depth was weak. | Added AC quality gate, test generation expectations, mutation/flaky test management, and performance/resilience evidence hooks. |
| Operations | Runbook and observability existed, but SLO/error-budget evidence was limited. | Added SLI/SLO/error-budget contract, alert quality rules, incident drill, dashboard spec, and production readiness review. |
| External skills | Useful external skill sources were referenced, but supply-chain risk needed stronger controls. | Added provenance, permission, sandboxing, reviewer-only mode, and regression-evaluation policy. |

## Non-negotiable V4 operating rule

No generated product is enterprise-ready until this command passes in the generated product repository:

```bash
FACTORY_STRICT=1 make validate-strict
```

The normal `make validate` proves the skeleton structure is present. Strict validation proves product-specific artifacts have been filled with real, measurable, traceable, and evidence-backed content.
