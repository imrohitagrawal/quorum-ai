# ADR-0190: The metrics library stays below 8.1, and the settings library's debug dump is kept off

## Status

Accepted — 2026-11-17, in the dependency updates that CHG-109 placed after the browser-lane fixes.
The hold and the logging default below are the session's design, made while moving `fastapi` to
0.162.0 and `pydantic-settings` to 2.16.2 (the runtime half of Dependabot's Python group). They
are not product decisions. Codex reviewed the plan and its revision before any code.

## Context

The same update would have moved `prometheus-fastapi-instrumentator` from 8.0.2 to 8.1.0. The
whole test suite was green on all three new versions (`make quality` printed "8,394 passed,
80 skipped" and exited 0), yet two promises broke. Both were found by listing failure modes before the change, not
by any existing test
(`docs/analysis/2026-11-17-fastapi-0-162-failure-modes.md`).

1. **Raw paths in `/metrics`.** `main.py` promises that raw paths never become label values:
   requests are grouped by route template. On 8.1.0 a request to `/v1/query-runs/<anything>/`
   (a trailing slash, which FastAPI answers with a 307 redirect) is labelled with the raw path.
   No sign-in is needed, so any visitor could create as many metric series as they like, and a
   run id would land in a label. 8.0.2 labels the same request with the template plus a
   trailing slash (`/v1/query-runs/{query_run_id}/`): one fixed series.
2. **Secrets in a debug log.** `pydantic-settings` 2.16 adds a switch: when the environment
   variable `PYDANTIC_SETTINGS_DEBUG` is set and its logger is enabled for DEBUG, building the
   settings logs every source value, keys included. 2.14.2 has no such switch. Production does not
   set it and logs at INFO (`fly.toml`), so it could not fire today. Through the app it would
   need more than that variable: the settings are built when `config.py` is imported, before
   the app sets its log level, so `LOG_LEVEL=DEBUG` alone does not reach it. A process that turns
   on DEBUG logging before importing the app (a script, a test harness, a debugging session) and
   has the variable set would log every key.

## Decision

1. `prometheus-fastapi-instrumentator` is held at 8.0.2 by `>=8.0.2,<8.1` in `pyproject.toml`.
   8.1.0 is the latest release, so there is no fixed version to move to.
2. `config.py` sets the `pydantic_settings` logger to WARNING before any settings object is
   built, so the debug dump stays off whatever the environment says.
3. Both are pinned by tests that were shown failing first: the metrics tests in
   `tests/unit/test_metrics_endpoint.py` (every templated route, both methods, with and without a
   trailing slash, and the `/static` mount; exact counts), and
   `tests/unit/test_settings_debug_log_does_not_leak_secrets.py` (every secret field, with a
   partner proving the dump is live on the installed version).

## Measurements

Each row was run on the same source with the old and the new environment.

| Check | Old versions | New versions | How |
|---|---|---|---|
| Lines in `/metrics` naming a raw run path, after 20 trailing-slash requests | 0 (8.0.2) | 300 (8.1.0) | a TestClient script sending `GET /v1/query-runs/zz-probe-<i>/` without following redirects, then counting `/metrics` lines that contain `zz-probe` |
| Log lines holding a fake key, with the switch on and the root logger at DEBUG | 0 (2.14.2) | 2 of 2 keys (2.16.2) | a script setting `logging.basicConfig(level=DEBUG)`, `PYDANTIC_SETTINGS_DEBUG=1` and two fake keys, then building `Settings()` |
| The same, every secret field, before the logger pin | — | 7 of 7 fields leaked | `test_building_settings_with_debug_env_and_root_at_debug_logs_no_secret`, on the tree before the fix |

## Rejected alternatives

- **Take 8.1.0 and drop trailing-slash paths with `excluded_handlers`.** It hides the 307s from
  the metrics and covers only the one templated route the app has today.
- **Turn off FastAPI's trailing-slash redirect (`redirect_slashes=False`).** It changes an answer
  visitors get, to fix a metrics label.
- **Check that production sets no `PYDANTIC_SETTINGS_DEBUG`.** True today, but it holds only until
  someone sets it; the logger pin holds in code.
- **Hold `pydantic-settings` at 2.14.2.** The pin closes the only new risk found, and the rest of
  the release behaved the same in 379 of 379 configuration cases (reported by the research pass).

## Consequences

- The metrics library is kept out of Dependabot's grouped Python update
  (`exclude-patterns` in `.github/dependabot.yml`), so its next release arrives as its own pull
  request and the metrics tests turn that one red, not the whole group.
  `tests/unit/test_held_package_is_kept_out_of_the_dependabot_group.py` keeps the exclusion in
  place while the cap stands. Resume when a release labels a redirected request by its template;
  then drop the cap, the exclusion and this decision's first item.
- If the app ever wants the settings debug dump, it has to remove the pin on purpose.
- Not closed here: the app's log scrubbing does not cover every secret it holds. Board row W147
  fixes it.
