# Factory Runbook

## Standard run

1. Fill `PRODUCT_IDEA.md`.
2. Run `codex`.
3. Ask Codex: `Run product factory.`
4. Codex creates or updates product docs.
5. Run `make validate`.
6. Resolve open questions.
7. Implement the first vertical slice.
8. Run `make quality`.
9. Prepare release evidence.
10. Feed production signals back into Jira and the living spec.

## Emergency stop

Stop the factory if:

- Source-of-truth conflict is detected.
- Security or privacy impact is unclear.
- Acceptance criteria are missing.
- Requirement has no owner.
- CI/security/release gates fail.
