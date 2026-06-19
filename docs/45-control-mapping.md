# Control Mapping

## Scope

This maps Release 1 security, privacy, and AI safety threats to controls, tests, owners, and evidence status. Evidence remains `Not available` until implementation and CI exist.

| Threat/Risk | Control | Requirement | Test | Evidence | Owner |
|---|---|---|---|---|---|
| T-001 Anonymous provider-consuming execution | CTRL-001 Authentication required | FR-001, NFR-005 | TEST-FR-001 | Not available | Engineering lead |
| T-006 Wrong-account result or key access | CTRL-002 Owner authorization | FR-012, FR-013, NFR-005 | TEST-FR-012, TEST-NFR-005 | Not available | Engineering lead |
| T-005 Concurrent cost abuse | CTRL-003 One active query per account | FR-002 | TEST-FR-002 | Not available | Engineering lead |
| T-002 Cost confirmation tampering | CTRL-004 Server-side cost enforcement | FR-005, NFR-002 | TEST-FR-005, TEST-NFR-002 | Not available | Engineering lead |
| T-004 Provider secret exposure | CTRL-005 Server-only key handling and redaction | FR-011, NFR-006 | TEST-FR-011, TEST-NFR-006 | Not available | Engineering lead |
| BYO key persistence risk | CTRL-006 Protected storage and removal | FR-012, NFR-006 | TEST-FR-012, TEST-NFR-006 | Not available | Engineering lead |
| T-007 Prompt injection through sources | CTRL-007 Untrusted-source handling | FR-006, FR-008, FR-011 | Prompt-injection regression tests | Not available | Engineering lead |
| T-008 Sensitive content in logs | CTRL-005 Redaction and CTRL-010 non-secret events | NFR-006, NFR-007, NFR-010 | TEST-NFR-006, TEST-NFR-007, TEST-NFR-010 | Not available | Engineering lead |
| T-009 High-stakes advice overclaiming | CTRL-008 Warning and decision-support framing | FR-003, NFR-008 | TEST-FR-003, TEST-NFR-008 | Not available | Product owner |
| Provider timeout/failure | CTRL-009 Bounded timeout and partial result | FR-010, NFR-001, NFR-004 | TEST-FR-010, TEST-NFR-001, TEST-NFR-004 | Not available | Engineering lead |
| Missing operational insight | CTRL-010 Structured event coverage | NFR-010 | TEST-NFR-010 | Not available | Engineering lead |
| T-010 False consensus | CTRL-011 Preserve disagreement and uncertainty | FR-009 | TEST-FR-009 | Not available | Product owner |
| Release secret regression | CTRL-012 Secret/security scans | NFR-006 | Release security checks | Not available | Engineering lead |

## Residual Risk Decisions

| Risk | Decision | Owner | Status |
|---|---|---|---|
| Users may submit sensitive data despite warnings. | Warn and minimize logging for MVP; do not claim sensitive-data safety. | Product owner | Open until retention/provider terms are finalized. |
| Provider catalogs, costs, and search support may change. | Re-check during implementation planning and before release. | Engineering lead | Open. |
| Search grounding may not support every material claim. | Measure sampled citation coverage and show uncertainty. | Product owner | Open until eval rubric is approved. |
