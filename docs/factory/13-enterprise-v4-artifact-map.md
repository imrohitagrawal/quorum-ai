# Enterprise V4 Artifact Map

This factory expects every product to produce artifacts in a traceable chain.

```text
PRODUCT_IDEA.md
  -> docs/03-source-of-truth.md
  -> docs/01-product-brief.md
  -> docs/14-learner-spec.md
  -> docs/10-functional-requirements.md
  -> docs/11-non-functional-requirements.md
  -> docs/12-acceptance-criteria.md
  -> docs/17-requirement-registry.md
  -> docs/18-requirement-traceability-matrix.md
  -> docs/34-jira-issue-authoring.md
  -> docs/37-jira-confluence-sync-log.md
  -> docs/20-architecture.md
  -> docs/22-api-contract.md
  -> docs/40-threat-model.md
  -> docs/42-ai-safety-grounding.md
  -> docs/50-test-strategy.md
  -> docs/73-release-evidence.md
  -> docs/80-observability.md
  -> docs/83-runbook.md
  -> docs/95-production-readiness-review.md
```

## Evidence rule

Every important claim must point to evidence:

| Claim type | Required evidence |
|---|---|
| Requirement is approved | Jira issue, Confluence page, owner, sign-off record |
| AC is complete | Given/When/Then, negative path, data path, permission path |
| NFR is complete | Target, measurement method, test, dashboard, alert |
| Security risk is handled | Threat ID, control ID, test ID, residual risk owner |
| AI answer is grounded | Source list, citation behavior, fallback behavior, eval case |
| Release is ready | CI run, test result, security scan, performance baseline, rollback proof |
| Operation is ready | SLO, alert, dashboard, runbook, incident drill result |

## Strict validation rule

`make validate` is a skeleton health check. `FACTORY_STRICT=1 make validate-strict` is the release-quality check.
