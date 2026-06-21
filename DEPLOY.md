# Quorum-AI Production Deployment Guide

This document is the **operational runbook** for deploying Quorum-AI to production on Fly.io. It assumes you have an  API key and a Sentry project (both optional for first deploy).

---

## Prerequisites

1. **Fly.io account** — [Sign up](https://fly.io/app/sign-up) (free tier works)
2. **Fly.io CLI** — [Install](https://fly.io/docs/hands-on/install-flyctl/)
3. ** API key** (optional) — [Get one]()
4. **Sentry project DSN** (optional) — [Set up a project](https://sentry.io/welcome/)

---

## First-time setup (one-time per environment)

### 1. Authenticate with Fly

```bash
fly auth signup   # if you don't have an account
fly auth login
```

### 2. Launch the app

From the project root:

```bash
fly launch --no-deploy
```

This creates the Fly app (`quorum-ai`) but does not deploy yet. If it asks for a region, choose one near your users (e.g. `iad` for US East, `lhr` for London).

### 3. Set production secrets

```bash
# Required: secret used to sign session tokens. Generate a random value:
fly secrets set QUORUM_TOKEN_SECRET="$(openssl rand -hex 32)"

# Optional:  API key for live LLM execution.
# Without this, the app runs in offline mode (uses fallback responses).
fly secrets set OPENROUTER_API_KEY="sk-or-v1-..."

# Optional: Sentry DSN for error tracking. Get this from:
# https://sentry.io/settings/[org]/projects/[project]/keys/
fly secrets set SENTRY_DSN="https://...@sentry.io/..."

# Production environment marker (already in fly.toml, but explicit for clarity)
fly secrets set RUNTIME_ENVIRONMENT="production"
```

**Important:** Never commit these values. `fly secrets set` encrypts them at rest and injects them as environment variables at runtime.

### 4. Enable live execution (after the first deploy verifies the app boots)

```bash
# This requires OPENROUTER_API_KEY to be set (see step 3).
# The app refuses to start in production if this is "true" but the key
# is missing, so set the key FIRST, then enable this.
fly secrets set OPENROUTER_LIVE_EXECUTION_ENABLED="true"
```

### 5. Deploy

```bash
fly deploy
```

The first deploy takes ~3-5 minutes (builds the Docker image, pushes to Fly's registry, starts the container). Subsequent deploys with no dependency changes are faster (~30s).

### 6. Verify

```bash
# Check the app is up
fly status

# Health check
curl -sf https://quorum-ai.fly.dev/health

# Readiness check (should show live_readiness.state == "live" or "live-with-drift")
curl -sf https://quorum-ai.fly.dev/ready | jq .

# UI check
curl -sf -o /dev/null -w "%{http_code}\n" https://quorum-ai.fly.dev/ui
```

You should see HTTP 200 on all three. If `/ready` shows `offline_by_no_key`, you forgot to set `OPENROUTER_API_KEY` (or `OPENROUTER_LIVE_EXECUTION_ENABLED` is still `"false"`).

---

## Ongoing operations

### Deploy a new version

```bash
# Option 1: Push to main → CI runs tests → deploy workflow ships it
git push origin main

# Option 2: Manual deploy from your machine
fly deploy
```

The `deploy.yml` workflow runs `/health` and `/ready` smoke tests post-deploy. If they fail, the workflow fails (but the previous version is **not** auto-rolled back — check `fly releases rollback` to do that manually).

### View logs

```bash
# Live tail
fly logs

# Last 100 lines
fly logs --tail-count 100
```

Logs include the Sentry init line, the startup probe result, and the catalog prewarm. Sentry errors show up in the Sentry UI.

### Scale up

The default `fly.toml` runs a single 512MB instance. To scale:

```bash
# More memory (if you're seeing OOMs)
fly scale memory 1024

# More CPU
fly scale vm shared-cpu-2x
```

**Don't scale to multiple machines yet** — the in-memory state (sessions, query runs) is per-process. Multi-instance requires Redis (sessions) and Postgres (query runs) — see "When you outgrow single-instance" below.

### Rotate the token secret

```bash
# Generate a new secret
NEW_SECRET="$(openssl rand -hex 32)"

# Set it. All existing sessions are invalidated (users get logged out).
fly secrets set QUORUM_TOKEN_SECRET="$NEW_SECRET"

# Watch logs for the "Production environment validated" line
fly logs
```

### Rollback to a previous version

```bash
# List recent releases
fly releases

# Rollback to a specific version
fly releases rollback <version>
```

---

## Environment variables reference

| Variable | Required in prod? | Source | Notes |
|----------|-------------------|--------|-------|
| `QUORUM_TOKEN_SECRET` | **Yes** | `fly secrets set` | Random 32+ byte hex. Used to sign session tokens. App refuses to start if missing. |
| `RUNTIME_ENVIRONMENT` | **Yes** | `fly.toml` (env) | Set to `production`. Triggers stricter validation. |
| `SESSION_COOKIE_SECURE` | **Yes** | `fly.toml` (env) | `true` in production. App refuses to start if `false` in prod. |
| `ACCOUNT_LEGACY_HEADER_ENABLED` | No | `fly.toml` (env) | `false` (default). Allows old clients to send `X-Account-Id` header. Disabled by default for security. |
| `OPENROUTER_API_KEY` | For live mode | `fly secrets set` | Without this, the app runs offline (uses fallback responses). |
| `OPENROUTER_LIVE_EXECUTION_ENABLED` | For live mode | `fly secrets set` | Must be `true` AND `OPENROUTER_API_KEY` set, otherwise app refuses to start. |
| `SENTRY_DSN` | No | `fly secrets set` | Optional. If set, exceptions are reported to Sentry. |
| `LOG_LEVEL` | No | `fly.toml` (env) | Default `INFO`. Use `WARNING` for less noise. |
| `OPENROUTER_APP_URL` | No | `fly.toml` (env) | Public URL of this deployment. Used for `Referer` header. |

---

## Cost & quotas

Fly.io free tier includes:
- 3 shared-cpu-1x 256MB VMs (we use 1x 512MB — this exceeds the free tier, but the cheapest paid tier is ~$2/month)
- 160GB outbound data transfer/month
- 3GB persistent volume storage

The app itself has:
- No persistent storage requirement (state is in-memory)
- A 5-second `/ready` HTTP check (well within Fly's limits)
- A 15-second TCP check

**Realistic cost:** ~$2-5/month for a low-traffic deployment. Heavy traffic (10k+ queries/day) would push this to ~$10-20/month plus  costs.

---

## When you outgrow single-instance

The in-memory state (sessions, query runs) is the first thing to break when you scale. Order of operations:

1. **Sessions in Redis** — add Upstash Redis (free tier), update `InMemorySessionRepository` in `src/product_app/auth.py` to use a Redis-backed store
2. **Query runs in Postgres** — add Fly Postgres (free tier available), update `query_runs.py` repository
3. **Catalog cache in Redis** — once sessions are in Redis, also cache the  catalog there (5-minute TTL is fine)
4. **Sticky sessions** — when you have 2+ instances, configure Fly's load balancer with sticky sessions (`fly.toml` `[services.concurrency]` + `sticky_sessions = true`)
5. **Observability** — add OpenTelemetry exporter to a backend (Datadog, Honeycomb, Grafana Cloud)

These are not needed for launch. The app's README documents the in-memory state as MVP design.

---

## Troubleshooting

### App won't start: "Production environment validation failed"

`QUORUM_TOKEN_SECRET`, `SESSION_COOKIE_SECURE=true`, or `RUNTIME_ENVIRONMENT=production` is missing/misconfigured. Check:

```bash
fly secrets list          # Should show QUORUM_TOKEN_SECRET
fly config show -a quorum-ai  # Should show RUNTIME_ENVIRONMENT and SESSION_COOKIE_SECURE
```

### /ready shows "offline_by_no_key"

`OPENROUTER_API_KEY` is not set, or `OPENROUTER_LIVE_EXECUTION_ENABLED` is not `"true"`. Either:

```bash
# Option A: Go live (requires  key)
fly secrets set OPENROUTER_API_KEY="sk-or-v1-..."
fly secrets set OPENROUTER_LIVE_EXECUTION_ENABLED="true"

# Option B: Accept offline mode (the app still works, using fallback responses)
# No action needed - just acknowledge this is expected
```

### Users get logged out every deploy

Expected with in-memory state. Two options:

- Document this in the UI (there's already a "session expires on deploy" disclaimer planned)
- Move sessions to Redis (see "When you outgrow single-instance")

### High memory usage

The default 512MB is generous for a single user. If you're seeing OOMs:

```bash
fly scale memory 1024
```

The most likely cause is the catalog cache growing (rare — ~200 models max).

### Sentry shows no events

- Check `SENTRY_DSN` is set: `fly secrets list | grep SENTRY`
- Check the DSN is correct (it should be a full URL like `https://abc@sentry.io/123`)
- Trigger a test exception: `fly ssh console -C "python -c 'raise Exception(\"sentry test\")'"` then check Sentry

### Smoke tests in deploy.yml fail

If the deploy succeeded but the post-deploy smoke tests fail, the previous version is still running (Fly's `strategy = "rolling"` means new version replaces old only after health check passes). Check:

```bash
fly status      # Should show "running" on the new release
fly releases    # Check the latest release is "deployed"
```

If the new release is "pending" or "failed", check `fly logs` for the boot logs.

---

## See also

- [docs/95-production-readiness-review.md](docs/95-production-readiness-review.md) — the formal production-readiness review
- [docs/13-open-questions.md](docs/13-open-questions.md) — open product questions (deployment target, retention, etc.)
- [README.md](README.md) — what the app does
