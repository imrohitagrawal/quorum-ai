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
