# Failure modes: moving fastapi to 0.162.0 and pydantic-settings to 2.16.2

Written 2026-11-17, before review, on the branch that moves the lock. The same Dependabot group
also offered `prometheus-fastapi-instrumentator` 8.1.0; it is held at 8.0.2 (ADR-0190).

Each check ran the same source against two environments: the old lock (fastapi 0.137.2,
pydantic-settings 2.14.2, instrumentator 8.0.2) and the new one. Starlette stays at 1.3.1.
FastAPI 0.162 adds one new package, `opentelemetry-api` 1.45.2.

"Re-run" means the orchestrator ran the check again and saw the result; "reported" means a
research agent ran it and the orchestrator did not repeat it.

## Found, and fixed here

| # | Failure mode | Result | Evidence |
|---|---|---|---|
| 1 | The metrics library labels a request by its raw path | **Real on 8.1.0.** 20 trailing-slash requests to `/v1/query-runs/<id>/` gave 300 `/metrics` lines naming the raw path; 0 on 8.0.2. Held at 8.0.2 | Re-run. `tests/unit/test_metrics_endpoint.py`: 2 failed on 8.1.0, 13 passed on 8.0.2 |
| 2 | The settings library logs secret values | **Real on 2.16.2, not reachable today.** With `PYDANTIC_SETTINGS_DEBUG=1` and the root logger at DEBUG, building the settings logged 7 of 7 secret fields; 2.14.2 has no such switch. `config.py` now keeps that logger at WARNING | Re-run. `tests/unit/test_settings_debug_log_does_not_leak_secrets.py`: failed before the pin, passes after; deleting the pin turns it red again |

## Checked, no change

| # | Failure mode | Result | Evidence |
|---|---|---|---|
| 3 | The whole suite on the new versions | Green before items 1 and 2 were fixed ("8,394 passed, 80 skipped"), so the suite does not see either | Re-run, `make quality` |
| 4 | The OpenAPI schema changes | Matches the committed `openapi.yaml` in both environments | Reported; `make openapi-check` runs at the gates |
| 5 | Request handling changes (validation errors, 413, 405, 403, static files, `/docs`) | 44 requests with a real session answered the same; a full simulated run was byte-identical | Reported |
| 6 | A JSON `null` body | Still 422 `VALIDATION_ERROR`; the field error changes from `missing` to `model_attributes_type`, and the top-level message from "Field required" to the generic one. No client sends `null` | Reported |
| 7 | The request body limit (ADR-0171) | Holds, chunked bodies included | Reported |
| 8 | Configuration parsing | 379 of 379 settings cases identical (booleans, blanks, bounds, case, `.env` files) | Reported |
| 9 | FastAPI's new built-in telemetry, or Sentry's OpenTelemetry integration, sends data | Neither is active: FastAPI's telemetry is off and no provider is set; Sentry loads the same 12 integrations; an incoming `traceparent` is not followed; the events Sentry would send match | Reported |
| 10 | A real server boot with the `Dockerfile`'s flags, and shutdown | `/health` and `/ready` 200, clean shutdown, in both | Reported; the image is built and booted at the gates |
| 11 | Session minting, cookie attributes, the daily cap and the rate limit | Identical responses and headers | Reported |
| 12 | The Schemathesis contract | 54 passed in both | Reported; `make api-contract` runs at the gates |

## Present in both versions, not caused by this change

- The log scrubbing does not cover every secret the app holds (board row W147).

Checked and not a gap: Sentry events keep a request's query string, scrubbed only of
secret-shaped text except on the sign-in callback, where the whole query is dropped. No route
takes a visitor's text in a query string: the OpenAPI schema lists no query parameter, and the
only query reads in `src/` are two flags on `/ui` and the callback's `state` and `code`.
