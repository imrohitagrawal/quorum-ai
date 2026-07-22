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

## Canonical domain: `quorum.stackclimb.com` (2026-07-22)

The app's canonical public URL is **https://quorum.stackclimb.com** (UI at
**`/ui`**). This is a **custom domain in front of the same Fly.io app** — the
runtime did *not* move off Fly.io. `quorum-ai.fly.dev` (Fly's default hostname)
continues to serve the identical app and is retained as a fallback.

**Why a custom domain, not a move:** `*.fly.dev` is only Fly's default hostname,
not a separate host. Pointing a `stackclimb.com` subdomain at the running app is
DNS + TLS, not a migration — matching how the other stackclimb.com products are
fronted. No redeploy of the app was required.

**Setup steps (reproducible / for rebuild):**

1. **Fly cert** — register the hostname so Fly provisions a Let's Encrypt cert:
   ```bash
   fly certs add quorum.stackclimb.com -a quorum-ai
   fly certs setup quorum.stackclimb.com -a quorum-ai   # prints exact DNS records
   ```
2. **Cloudflare DNS** (stackclimb.com zone) — add two records, both **grey-cloud
   (DNS only)**, pointing straight at the app's Fly IPs:
   - `A     quorum → 66.241.125.57`
   - `AAAA  quorum → 2a09:8280:1::131:de60:0`

   Grey-cloud is **required**: an orange-cloud (proxied) record makes Cloudflare
   intercept Let's Encrypt's challenge and the cert never validates. A/AAAA direct
   to Fly also proves ownership, so **no `_fly-ownership` TXT is needed** with this
   layout. (A CNAME-only or proxied setup *would* need the TXT.)
3. **Validate** — `fly certs check quorum.stackclimb.com` flips to `Issued`
   (1–5 min after DNS propagates).

**Verified end-state (2026-07-22):** `/health` 200 with valid TLS, `/ready`
`state: live`, HTTP→HTTPS 301, `/ui` 200 (HTML), CSP/HSTS/`X-Frame-Options`
present, and responses byte-identical to `quorum-ai.fly.dev`.

**Code touch-points:** the app needed **no** code change to work on the new domain
— the CSP is `self`-relative (`src/product_app/main.py`) and there is no
`CORSMiddleware`/`ALLOWED_HOSTS` host pinning, so it is domain-agnostic. Two
attribution strings were updated to the canonical URL (OpenRouter dashboard
labelling only, no functional impact): `OPENROUTER_APP_URL` (`fly.toml`) and the
`HTTP-Referer` header (`src/product_app/feedback_audit.py`).

**Deliberately unchanged:** the post-deploy health checks in
`.github/workflows/deploy.yml` and `deploy-drift-watchdog.yml` stay on
`quorum-ai.fly.dev`. They test the Fly origin directly and must stay decoupled
from Cloudflare/DNS, so a CDN or DNS hiccup can never fail a deploy gate for a
reason unrelated to the deploy.
