# Runbook: Provider Orchestrator (ProviderExecutionService)

## Component

- **Name:** ProviderExecutionService — the LLM provider orchestrator
- **Owner:** Rohit Agrawal · https://github.com/imrohitagrawal
- **What it does:** Executes up to four parallel LLM model calls per user query, routing each through a live→fallback→simulation chain ( primary, Tavily supplementation, fallback search, local simulation). Returns structured `InitialModelAnswer` objects the API serialises directly.
- **Steps / responsibilities covered:** Per-slot model dispatch, `:online` web-search retry, Tavily supplementation, fallback search, local simulation, citation coverage calculation, event recording, token-usage capture
- **Where it runs:** In-process within the Flask app on Fly.io (`fly launch`); also exercised by unit tests (`tests/unit/test_tavily_search.py`) and e2e (`e2e/tests/invariants/`)
- **Dependencies:**  `/chat/completions` (live path); Tavily `/search` (optional supplementation); Fly secrets (`OPENROUTER_API_KEY`, `TAVILY_API_KEY`); `settings` (timeouts, caps, feature flags)
- **Tracking / ADRs:** #26 (silent-simulation incident) · #31, #32 (Tavily fallback) · #41 (degraded banner) · #68 (live_count honesty) · `docs/runbooks/live-provider-outage.md` (OD-6)
- **Dashboards / alerts:** `/ui/ops` (OD-2) · `/metrics` (OD-1) · `/ready` · `/status` · `availability-check.yml` · `error-rate-check.yml`
- **Last reviewed: 2026-07-23** — [designed, not yet built] — this runbook was derived from code review of `providers.py` (current tree) and the incident record in `docs/runbooks/live-provider-outage.md`; it has not yet been walked through end-to-end. Walk it through on the next live incident or drill.

---

## How to run it

### Locally

```bash
python -m product_app
```

Prerequisites: Python 3.11+, dependencies from `requirements.txt`. No API key needed — local simulation is the hermetic default.

For live execution locally: `OPENROUTER_API_KEY=sk-... OPENROUTER_LIVE_EXECUTION_ENABLED=true python -m product_app`

For Tavily supplementation: add `TAVILY_API_KEY=...`.

### Deployed

- Prod: `https://quorum.stackclimb.com` (Fly.io, `fly deploy`)
- Secrets managed via `fly secrets set KEY=value` — **never** paste secrets into a doc or shell history.
- Roll back: `fly releases rollback` (see `DEPLOY.md`)

### Health signals

| Signal | Healthy | Check command |
| --- | --- | --- |
| `/health` | 200 | `curl -s https://quorum.stackclimb.com/health` |
| `/ready` | `state: live` (or `simulated` when intentionally off) | `curl -s https://quorum.stackclimb.com/ready` |
| `/status` | `live_execution: true` when key is set | `curl -s https://quorum.stackclimb.com/status` |
| `/metrics` | 5xx rate < 1%, request counts flowing | `curl -s https://quorum.stackclimb.com/metrics` |
| `/ui/ops` | All tiles green | Browser at `/ui/ops` |

---

## Monitoring

### What healthy looks like

A typical live query run emits four `provider_initial_answer_completed` events (one per slot), each with `provider_path=OPENROUTER_SEARCH`, `fallback_used=False`, real `token_usage`, and `latency_ms` in the 2–15 s range (model-dependent). `live_count` on the run payload equals the number of slots that returned live answers. No `provider_initial_answer_failed` events. `/metrics` request-count labels show `status_class="2xx"` dominant.

### Key signals and thresholds

| Signal | Source | Threshold / what to watch |
| --- | --- | --- |
| `provider_initial_answer_failed` event rate | `/metrics` or event recorder (`InMemoryProviderEventRecorder`) | Spikes indicate provider-side failures (see failure modes below) |
| `fallback_used=True` ratio | `/metrics` | A rising ratio means  is degraded; if it reaches ~100%, every slot is falling back |
| `upstream_provider_http_error` log lines | Structured stdout (JSON) | Each line carries `status_code`, `url`, `model_id` — pattern-match for 401/403 (key), 429 (rate limit), 5xx (provider) |
| `tavily_search_http_error` log lines | Structured stdout (JSON) | Tavily-side failures; supplementation silently degrades |
| `live_count` vs slot count | Run payload / `/ui/ops` | `live_count < 4` triggers the degraded banner (CI-blocking invariant) |
| Run latency | `/metrics` request-duration histogram | P95 ≤ 120 s, hard timeout 180 s (NFR-001) |
| Token cost per run | `/metrics` (when usage is captured) | Spike detection — a run with all four slots on expensive models and no `max_tokens` cap could bill far above estimate |

### AI-component-specific signals

- **Fallback-fired events:** each slot that falls back to simulation or fallback_search increments `fallback_used=True`. A cluster of these across a query means the live path is compromised.
- **Token-usage capture rate:** when `token_usage` is `None` on a slot that should have gone live, the run stays "estimated" — not a failure, but a signal that the provider either omitted the field or the call failed.
- **Citation coverage:** `citation_coverage.target_met` flags when a slot's sourced claims fall below the 80% target. A sudden drop across all slots suggests a model-side change (not a provider failure — this is a **CORR** concern).

---

## Failure-mode entries

### 1.  HTTP error (401, 403, 429, 5xx) — class: OPS

- **Symptom.** One or more slots return local simulation instead of a live model answer. The run completes quickly (auth errors return in milliseconds). `live_count` is lower than the slot count. The degraded banner may appear if `live_count < 4`.
- **Signal / alert.** `upstream_provider_http_error` WARNING log lines with the `status_code` and `model_id`. `provider_initial_answer_failed` events for the affected slots. `fallback_used=True` in completed events. `/ui/ops` readiness tile may show degraded.
- **Blast radius.** Affected slots serve simulated output. Slots whose calls succeed are unaffected. The synthesis/debate stages consume whatever answers were produced — a partial live run is valid. The user-facing degraded banner surfaces the honesty gap.
- **First response.**
  1. Check `/ready` — if `state != live`, the availability-check alert has already fired; investigate the listed `reasons`.
  2. Identify the status code pattern:
     - **401 / 403:** key issue (invalid, expired, unfunded). See failure mode #2.
     - **429:** rate limit. See failure mode #3.
     - **5xx:** -side outage. See failure mode #4.
  3. Confirm from `/ui/ops` whether this is one slot or all slots.
- **Resume / recovery.** The fallback chain is automatic — simulation fires within milliseconds of the HTTP error. Once the root cause is fixed (key rotated, rate limit window passed, provider recovered), the next run resumes live. No manual intervention needed for the fallback path itself. Verify with one live run showing `live_count=4` and `fallback_used=False`.
- **Escalation.** If all four slots are failing simultaneously and the cause is unclear, escalate to the owner before relying on the fallback path for any decision-critical output. A weaker fallback (simulation) silently lowers quality.
- **Post-incident note.** Record the duration, which status codes fired, which models were affected, and whether the degraded banner appeared. Tune timeouts or fallback order if recovery was slow. [designed, not yet built] — walk through on the next live incident or drill.

### 2. API key invalid, expired, or unfunded (401/403) — class: OPS

- **Symptom.** All live slots fail within milliseconds. Runs complete in ~0.5 s. `/ready` may show `state=live` (the flag AND key-presence check passes — the key exists but is not funded). `/status` shows `live_execution: true`. This is the exact shape of incident #26 (2026-07-15).
- **Signal / alert.** `upstream_provider_http_error` with `status_code=401` or `403` on every slot. `EST == ACTUAL` on cost receipt (no tokens billed). The degraded banner and `live_count` honesty surface this to the user — this is the detection gap that is now closed.
- **Blast radius.** All four slots fall to local simulation. The run completes fast with simulated answers. User-facing degraded banner prevents misrepresentation.
- **First response.**
  1. Check `/ready` — note that it can show `state=live` even with an unfunded key (the $0 probe only checks key presence, not key validity). Trust the run payload (`live_count`, `EST==ACTUAL`) more than `/ready`.
  2. Run a single cheap catalog call to distinguish key-invalid from network failure:
     ```bash
     curl -s  \
       -H "Authorization: Bearer $(fly secrets get OPENROUTER_API_KEY --app quorum-ai)" \
       | head -c 200
     ```
     The catalog endpoint is free — do NOT fire a paid completion to test.
  3. If the response is a 403/401, the key is the problem.
- **Resume / recovery.**
  1. Set a funded key: `fly secrets set OPENROUTER_API_KEY=sk-... --app quorum-ai`
  2. **Verify the secret actually changed:** `fly secrets list --app quorum-ai` and check the digest changed.
  3. Run one live query and confirm `live_count=4`, `fallback_used=False`, and non-zero `token_usage` on each slot.
  4. **Lesson from #26:** a `fly secrets set` can silently fail to apply. Always verify the digest change AND a live run — never assume the update took.
- **Escalation.** If the key has been invalid for more than a few hours, check whether any user-facing output was presented as live during the degraded period (not recorded for #26; no request-level analytics existed then).
- **Post-incident note.** Record when the key became invalid, which runs were affected, and the user-visible duration. Update `docs/runbooks/live-provider-outage.md` if the detection gap changed.

### 3. Rate limiting (429 Too Many Requests) — class: OPS

- **Symptom.** Slots start returning simulation. Runs complete. `upstream_provider_http_error` with `status_code=429` in logs. The fallback chain absorbs the hit transparently.
- **Signal / alert.** `upstream_provider_http_error` WARNING lines with `status_code=429`. Rising `fallback_used=True` ratio in `/metrics`. Cost may temporarily drop (no tokens billed for simulated slots).
- **Blast radius.** Rate-limited slots fall to simulation. Other slots that have not hit the limit continue live. The run completes with a mix of live and simulated answers.
- **First response.**
  1. Confirm it is rate limiting (429), not a full outage (5xx).
  2. Check the  dashboard for rate-limit status and remaining quota.
  3. Identify whether the rate limit is per-key (shared across all slots) or per-model.
- **Resume / recovery.** Rate limits are time-based — wait for the window to reset (typically 60 s to 1 min). The next automatic run should resume live. No code change needed. If rate limits are chronic, consider:
  - Reducing concurrent slot count (fewer parallel calls per query).
  - Requesting a higher rate-limit tier from .
  - Adding request-level backoff in the orchestrator (not currently implemented — see implications section).
- **Escalation.** If rate limits persist across multiple run windows (suggesting a tier or quota issue, not a burst), escalate to the owner to review the  plan tier.
- **Post-incident note.** Note the duration, time of day (rate limits often correlate with traffic patterns), and whether all four slots hit the limit simultaneously.

### 4.  outage or 5xx — class: OPS

- **Symptom.** All slots return simulation. Runs complete fast. `upstream_provider_http_error` with `status_code=502/503/504` (or other 5xx). `/ready` may show `state != live` if the availability check catches it.
- **Signal / alert.** `upstream_provider_http_error` WARNING with 5xx codes. `provider_initial_answer_failed` events. `availability-check.yml` may fire if `/ready` degrades. `/ui/ops` readiness tile.
- **Blast radius.** All slots serve simulation. The degraded banner surfaces the degraded state. External monitoring: check  **First response.**
  1. Check  for known outages.
  2. Confirm from `/ui/ops` and `/metrics` that this is provider-side, not local.
  3. Check whether the app itself is healthy (`/health` 200, `/metrics` flowing).
- **Resume / recovery.** Automatic — simulation serves. When  recovers, the next run resumes live. Verify with `live_count=4` on the first recovery run. No manual action needed unless the outage is prolonged (see escalation).
- **Escalation.** For outages longer than ~2 hours, consider:
  - Configuring an alternative provider endpoint if  supports failover regions.
  - Communicating to users via the degraded banner that live answers are temporarily unavailable.
  - The owner may choose to temporarily disable `OPENROUTER_LIVE_EXECUTION_ENABLED` to avoid unnecessary failed calls and cost of retry storms.
- **Post-incident note.** Record the outage window, 's post-mortem (if published), and whether the degraded banner was the primary user-visible signal.

### 5. Network failure (DNS, timeout, connection reset) — class: OPS

- **Symptom.** Slots return simulation. Runs complete. **No log line is emitted** for network-level failures — this is an asymmetry in the current code. Detection relies on the run payload (`live_count`) and the degraded banner.
- **Signal / alert.** Absence of `upstream_provider_http_error` for slots that should have called live (the logging asymmetry: only HTTP errors log; `URLError`, `TimeoutError`, `JSONDecodeError`, and empty-body returns are silent). `fallback_used=True` in completed events. `live_count` below slot count.
- **Blast radius.** Affected slots serve simulation. Other slots unaffected. The degraded banner surfaces if `live_count < 4`.
- **First response.**
  1. Check whether the issue is local (DNS resolution, outbound connectivity) or remote (Fly region,  endpoint).
  2. From a shell on Fly: `nslookup .ai` and `curl -s -o /dev/null -w "%{http_code}"  (catalog endpoint, free).
  3. If outbound connectivity is the issue, check Fly's status page and region health.
- **Resume / recovery.** Automatic — simulation serves. Once connectivity is restored, the next run resumes live. The silent-logging asymmetry means this failure mode is harder to diagnose than HTTP errors — the operator must infer it from `live_count` mismatch.
- **Escalation.** If network failures persist and cannot be attributed to a known provider issue, escalate — the silent logging means you may be missing a local connectivity problem.
- **Post-incident note.** This failure mode is hard to diagnose because it produces no log line. Consider whether the logging asymmetry (documented in the existing `live-provider-outage.md`) should be closed — see implications section.

### 6. JSON decode failure or empty response body — class: OPS

- **Symptom.** A slot that reached  receives a response that cannot be parsed. The slot falls to simulation silently (no log line). Other slots continue normally.
- **Signal / alert.** No log line (same asymmetry as network failures). `live_count` lower than expected. `fallback_used=True` on the affected slot. The `_extract_usage` call would also fail downstream, so `token_usage` is `None`.
- **Blast radius.** Single slot affected (the other three continue live). The run completes with one simulated answer. If this happens to all four slots simultaneously, it is more likely an -side issue returning malformed responses.
- **First response.**
  1. Identify if it is one slot or all slots from the run payload.
  2. Manually call the same endpoint with the same model id to inspect the raw response:
     ```bash
     curl -s  \
       -H "Authorization: Bearer $(fly secrets get OPENROUTER_API_KEY --app quorum-ai)" \
       -H "Content-Type: application/json" \
       -d '{"model":"<model_id>","messages":[{"role":"user","content":"test"}]}' \
       | head -c 500
     ```
  3. If the response is truncated or non-JSON, this is an -side issue.
- **Resume / recovery.** Automatic — simulation serves the affected slot. Retry on the next query. If persistent for a specific model, that model may have a compatibility issue with the  API version.
- **Escalation.** If a specific model consistently returns malformed responses, report to  and consider removing it from the slot picker until resolved.
- **Post-incident note.** Record the model id, the raw response (if obtainable), and whether it resolved on retry. [designed, not yet built] — walk through on the next live incident or drill.

### 7. Tavily search failure — class: OPS

- **Symptom.** A live slot returns an answer from the model but with no citations (because `:online` returned no sources and Tavily supplementation failed). The slot still shows `provider_path=OPENROUTER_SEARCH` and `fallback_used=False` — the user sees a `provider_notice` explaining the limited sourcing.
- **Signal / alert.** `tavily_search_http_error` WARNING log lines. Missing sources on a slot that went live. `citation_coverage.target_met` may be `false` (but this is per-slot and advisory — the honest heuristic surfaces it rather than hiding it).
- **Blast radius.** Only the source list for the affected slot is degraded. The answer text is still from the live model. Other slots unaffected.
- **First response.**
  1. Check `tavily_search_http_error` log lines for Tavily-side errors (key, rate limit, timeout).
  2. Confirm `TAVILY_API_KEY` is set: `fly secrets get TAVILY_API_KEY --app quorum-ai`.
  3. Test Tavily directly:
     ```bash
     curl -s https://api.tavily.com/search \
       -H "Authorization: Bearer $(fly secrets get TAVILY_API_KEY --app quorum-ai)" \
       -H "Content-Type: application/json" \
       -d '{"query":"test","max_results":3}' \
       | head -c 500
     ```
- **Resume / recovery.** Automatic — the slot serves the model's answer with the `provider_notice` flag. The fallback sources degrade to the `example.test` stub if Tavily is unavailable. When Tavily recovers, supplementation resumes on the next run.
- **Escalation.** Not needed — this is a graceful degradation. The user is informed via `provider_notice`. Escalate only if Tavily is consistently failing (possible key or quota issue).
- **Post-incident note.** Note the Tavily error pattern. If the key expired or quota was exceeded, set a reminder to monitor Tavily usage.

### 8. Token usage parsing failure — class: OPS

- **Symptom.** A live call returns a response, but the `usage` object is missing, malformed, or contains implausible values. The slot's `token_usage` is `None`. The run's cost stays "estimated" rather than "measured".
- **Signal / alert.** `token_usage` is `None` on a slot that otherwise succeeded. The cost layer cannot compute a measured actual cost — the run stays in `estimated` mode. No log line is emitted (the absence of usage is not logged as a warning).
- **Blast radius.** Only the cost calculation is affected. The answer text, sources, and all other fields are correct. The run completes normally.
- **First response.**
  1. Check the raw  response for the `usage` object — it may be omitted on certain model tiers or response shapes.
  2. Confirm from `/metrics` whether token-usage capture rate is dropping (requires metrics instrumentation for usage fields — not currently implemented).
- **Resume / recovery.** No action needed — the run stays "estimated" and the user is not affected. If a model consistently omits usage, consider whether it should stay in the slot picker.
- **Escalation.** Not needed for individual occurrences. If the usage capture rate drops across all models simultaneously, escalate — it may indicate an  API version change.
- **Post-incident note.** Record which model(s) omitted usage and whether the issue persists across retries. [designed, not yet built] — walk through on the next live incident or drill.

### 9. Run wall-clock deadline exceeded — class: OPS

- **Symptom.** One or more slots are cut before producing an answer. The slot shows `status=FAILED`, `error_code="RUN_DEADLINE_EXCEEDED"`, `latency_ms=0`, and a `provider_notice`: "The run reached its time limit before this model answered."
- **Signal / alert.** `provider_initial_answer_failed` events with `error_code=RUN_DEADLINE_EXCEEDED`. The run-level deadline (180 s hard, from NFR-001 / PR #73) fires. `/metrics` request-duration histogram shows runs near the ceiling.
- **Blast radius.** Cut slots show FAILED. Remaining slots (that answered before the deadline) are unaffected. The synthesis/debate stages consume whatever answers completed. The user sees the deadline-exceeded notice on cut slots.
- **First response.**
  1. Confirm the deadline from the run payload or `/metrics` latency histogram.
  2. Check whether all four slots hit the deadline (suggests the models are collectively too slow) or just one or two (suggests a slow model).
  3. Check `/ui/ops` p95 latency tile — if it is trending toward the 120 s target, the deadline may need adjustment before it starts cutting healthy runs.
- **Resume / recovery.** The run is already terminal — the synthesis stage has consumed whatever completed. The next run gets a fresh 180 s budget. No manual intervention needed.
- **Escalation.** If deadline cuts are frequent (not just occasional on slow models), escalate to review:
  - Whether the 180 s hard timeout is appropriate for the current model mix.
  - Whether the `initial_answer_max_tokens` cap is preventing slow-but-valid completions.
  - Whether to remove slow models from the slot picker.
- **Post-incident note.** Record which slots were cut, the run latency distribution, and whether the deadline was the primary cause of incomplete runs. [designed, not yet built] — walk through on the next live incident or drill.

### 10. Forced provider failure (test hook) — class: CORR (test-only)

- **Symptom.** A slot returns `status=FAILED`, `error_code="PROVIDER_UNAVAILABLE"` with the notice "This model's answer is unavailable because the request to the provider did not succeed."
- **Signal / alert.** This is triggered only by the magic phrase "force provider failure" in the query text (LOCAL environment only) or the `provider-failure` marker in `model_id`. It is a test hook, not a real failure.
- **Blast radius.** Only the test run is affected. Production cannot trigger this path — the phrase is gated on `runtime_environment == LOCAL`, and `model_id` is operator-curated.
- **Resume / recovery.** N/A — this is a deliberate test path. Remove the trigger phrase or model marker.
- **Escalation.** N/A.
- **Post-incident note.** N/A — this is a correctness test, not an incident.

---

## Routine operations

### Deploy

1. `git push origin main` (or merge the PR).
2. Fly auto-deploys via GitHub Actions (`fly-deploy.yml`).
3. Verify: `curl -s https://quorum.stackclimb.com/health` → 200.
4. Verify: `curl -s https://quorum.stackclimb.com/ready` → `state` matches expectation.
5. Run one live query and confirm `live_count=4` (if live execution is configured).

### Roll back

1. `fly releases rollback --app quorum-ai`
2. Verify: same three checks as deploy.

### Rotate keys

1. Generate a new key at the provider (, Tavily).
2. `fly secrets set OPENROUTER_API_KEY=sk-new-key --app quorum-ai`
3. **Verify the secret changed:** `fly secrets list --app quorum-ai` — check the digest.
4. **Verify with a live run:** confirm `live_count=4`, `fallback_used=False`, non-zero `token_usage`.
5. **Lesson from #26:** never skip step 3 — a `fly secrets set` can silently fail to apply.

### Run a scheduled job manually

- **Availability check:** `gh workflow run availability-check.yml --repo imrohitagrawal/quorum-ai`
- **Error rate check:** `gh workflow run error-rate-check.yml --repo imrohitagrawal/quorum-ai`
- **Flake scan:** `gh workflow run flake-scan.yml --repo imrohitagrawal/quorum-ai`

---

## Service-level objectives and error budget

SLOs are declared in `docs/80-observability.md` (OD-1). The runbook links to them rather than restating numbers:

| SLO | Target | How to read current value |
| --- | --- | --- |
| Availability | 99% non-5xx | `/metrics` request-count status-class labels |
| HTTP 5xx error rate | < 1% | `/metrics` (same read) |
| E2E query latency | P50 ≤ 45 s, P95 ≤ 120 s, hard 180 s | `/metrics` request-duration histogram + `perf-sample.yml` |
| Readiness honesty | `/ready` reports `live` in prod; simulated never shown as live | `/ready` + degraded-banner e2e invariant |
| E2E flake rate | 0/960 baseline | `flake-scan.yml` latest run |

The live budget is tracked in `/ui/ops` (OD-2) and the `/metrics` endpoint. Burn-rate alerting is not yet mechanised — the `error-rate-check.yml` covers 5xx rate but not fallback-fired events or latency burn rate.

---

## Escalation and contacts

| Role | Contact |
| --- | --- |
| Owner / primary on-call | Rohit Agrawal — https://www.linkedin.com/in/rohitagrawal14/ |
| GitHub issues | https://github.com/imrohitagrawal/quorum-ai/issues |
|  status |  |
| Fly.io status | https://status.fly.io/ |

**Rule:** a human is the final gate for any risky or irreversible step. This includes: rotating production API keys, changing `OPENROUTER_LIVE_EXECUTION_ENABLED` in production, disabling the degraded banner, and removing models from the slot picker.

---

## Implications for the quorum-ai application

Writing this runbook surfaced three gaps in the current implementation that the skill's methodology (walk each dependency, walk each step, walk correctness, add AI-specific modes) made visible:

1. **Silent network-level failures (no log line).** `URLError`, `TimeoutError`, `JSONDecodeError`, and empty-body returns in `_post_messages` return `None` without logging. Only HTTP errors produce `upstream_provider_http_error` WARNING lines. This asymmetry (already documented in `live-provider-outage.md`) means network failures are harder to diagnose — the operator must infer them from `live_count` mismatch rather than reading a log line. The runbook treats this honestly (failure mode #5 says "no log line is emitted") but the underlying gap remains.

2. **No mechanised burn-rate alerting for fallback events.** The `error-rate-check.yml` covers 5xx rate, and `availability-check.yml` covers readiness-not-live. But a slow provider degradation — where  is returning answers but with rising latency or falling quality — would only be visible through `/ui/ops` tiles or manual `/metrics` inspection. A fallback-fired event burn-rate alert would catch this shape.

3. **No request-level backoff / circuit breaker.** The fallback chain fires per-slot at every call — there is no backoff window, no circuit breaker, and no per-model cooldown. If  is rate-limiting (429), all four slots hammer it simultaneously on the next query. The Tavily path has the same shape. This is a deliberate simplicity choice (the fallback is cheap), but it means a struggling upstream gets no relief.

These are design observations, not bugs — the current behaviour is intentional and honest (the degraded banner, `live_count`, and `provider_notice` all surface the fallback truthfully). The runbook makes the gaps explicit so they can be deliberately addressed or accepted.

---

## Licence

© 2026 Rohit Agrawal (StackClimb). Internal — not for distribution. Provided "as is"; see LICENSE.
