# Security policy

## Reporting a vulnerability

Report a vulnerability privately through GitHub's private vulnerability reporting:
[open a private report](https://github.com/imrohitagrawal/quorum-ai/security/advisories/new).
Do not open a public issue, discussion or pull request about it.

Please include what the problem is, the steps or request that show it, and what an attacker
could do with it. A report that reproduces against a local run (`make run`) is the most useful.
Please keep the details private until a fix is in production.

## Scope

- This repository's code, workflows and configuration.
- The deployed service at `https://quorum-ai.fly.dev`, for problems you can show with ordinary
  requests. Do not run automated scanners, load tests or denial-of-service attempts against it,
  and do not try to read or change another visitor's data.

## Supported versions

Only the current `main` branch is supported. Production runs a commit from `main`, deployed
after that commit's checks pass (`GET /status` reports it as `build_sha`), so a fix ships as a
pull request to `main`.

## How this repository is protected

- Secrets are never committed. `make security-scan` blocks key shapes and home-folder paths in
  CI, and GitHub secret scanning with push protection is on.
- Dependencies are pinned by lock file and audited in CI (`make vuln-audit`); Dependabot
  reports known vulnerabilities, and opens grouped version-update pull requests monthly.
- Every workflow action is pinned to a commit, and workflows are audited with zizmor.
- The threat model is `docs/40-threat-model.md`; replacing a leaked secret is described in
  `docs/84-incident-response.md`.
