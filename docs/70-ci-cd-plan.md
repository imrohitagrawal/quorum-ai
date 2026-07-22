# CI/CD Plan

## Gates

- Validate docs
- Format check
- Lint
- Type check
- Report-generating pytest with JUnit XML and coverage XML
- Deterministic repository security scan
- Docker image build
- Non-secret release evidence artifact upload

## Artifact Evidence

The VS-013 local and CI evidence path is:

- `make test-report` writes `build/test-results/pytest.xml` and `build/coverage/coverage.xml`.
- `make security-scan` writes `build/security/security-scan.json`.
- `make ci-evidence` runs both evidence targets locally.
- `.github/workflows/ci.yml` uploads those files as the `release-hardening-evidence` artifact.

Remote CI evidence is not claimed until GitHub Actions runs and the uploaded artifact is retained.

## Branch protection on `main` (#61)

`main` is a protected branch. Changes land only through a pull request; direct
pushes are rejected (including for docs and including for admins). This closes the
concurrency race behind the 2026-07-22 undeploy churn: a follow-up direct push
could cancel a just-merged commit's in-flight CI (`docs/103-incident-learnings.md`).

Enforced configuration (GitHub → Settings → Branches, or the REST protection API):

- **Require a pull request before merging.** No direct `git push origin main`.
- **Require branches be up to date before merging** (`strict: true`), so a merge
  cannot race a just-merged commit's CI.
- **Require these status checks to pass** — names must match the check runs CI
  actually reports (verified against a real commit, not the issue text):
  - `validate-and-test`
  - `pytest (Python 3.12)`
  - `Changed-lines coverage >= 95% (blocking)`
  - `Schemathesis API contract (blocking)`
  - `FR traceability completeness (blocking)`
  - `e2e axe + parity (chromium)`
- **Include administrators** (`enforce_admins: true`) — the incident's trigger was
  an admin's direct docs push, so admins are bound too. Advisory checks
  (`Mutation score`, `Hermetic perf`, `codex-review`) are intentionally **not**
  required so they cannot block a merge.

Inspect / re-apply:

```bash
gh api repos/:owner/:repo/branches/main/protection \
  -q '{strict: .required_status_checks.strict, checks: .required_status_checks.contexts, admins: .enforce_admins.enabled}'
```
