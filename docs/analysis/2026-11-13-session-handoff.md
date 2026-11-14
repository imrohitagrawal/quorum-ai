# Session handoff, 2026-11-13

Written by the session. Each item below was gated, reviewed, deployed and checked before the
next started.

## Shipped

Every merge below has exactly one Deploy run whose "Deploy to Fly.io" job concluded `success`
(the other runs for each merge were skipped or cancelled), and production `/status` reported the
merge as its `build_sha`, with `/ready` answering 200.

- **The five CI action updates off Node 20 (W122 to W126).** Each replaced its Dependabot pull
  request, which could not pass on its own because the board row's needle is the old pin, so the
  row had to be regenerated in the same change. Each pin is a full commit, checked against the
  tag. Workflows that run only on a schedule or by hand were run on the branch first; the
  baseline seeder ran on throwaway branches.
  - #627, `astral-sh/setup-uv` v5.4.2 to v10.3.3 (W126), merge `2ba73bc`. ADR-0166 records how
    v10.3.3 checks the uv download.
  - #628, `actions/setup-python` v5.6.0 to v7.1.0 (W123), merge `f834680`.
  - #629, `actions/checkout` v4.4.0 to v7.0.1 (W122), merge `478125f`. v6 stores persisted
    credentials in a separate file; the seeder, the one checkout that keeps them, was run with
    one Linux baseline removed and pushed the regenerated image back, so its push still works.
  - #630, `actions/setup-node` v4.4.0 to v7.1.0 (W125), merge `c860a1c`.
  - #631, `actions/upload-artifact` v4.6.2 to v7.0.2 (W124), merge `d34a4f0`. Main's CI log for
    that merge has no Node 20 deprecation warning.
- **#632, `sentry-sdk` 2.63.0 to 2.73.0, with a guard that drops every log item.** Merge
  `2913511`; the deploy's build installed `sentry-sdk==2.73.0`. Review found that 2.73.0 sends a
  line written through `sentry_sdk.logger` as a `log` item even with `enable_logs=False`, past
  both scrubbing hooks. Nothing in `src/` calls `sentry_sdk.logger`, so nothing private was sent,
  but ADR-0163 would have held only by accident. `_sentry_options()` now passes
  `before_send_log=_drop_sentry_log`; three tests pin it, one of them a partner proving the path
  does send without the hook. ADR-0163 has a dated update, and
  `docs/analysis/2026-11-13-sentry-sdk-2-73-failure-modes.md` lists what was checked.
- **#634, `uvicorn` 0.49.0 to 0.54.0.** Merge `e2cf4ad`; the deploy's build installed
  `uvicorn==0.54.0`. On both versions, run with the `Dockerfile`'s flags, forwarded-address
  headers from an untrusted peer were ignored and ADR-0171's three uvicorn behaviours held
  (`docs/analysis/2026-11-13-uvicorn-0-54-failure-modes.md`).

## Open, in order

- **The rest of the dependency updates.**
  - #633, Dependabot's Python group (it replaced #604). It is bigger than it looks and should be
    split. On its CI run, three tests in
    `tests/unit/test_w116_tests_run_inside_the_mutation_copy.py` failed, the log showing
    `ImportError: cannot import name 'record_trampoline_hit' from 'mutmut.__main__'` (mutmut 3.8),
    three tests in `test_stance_majority_flags_has_no_equivalent_mutants.py` errored, and
    `schemathesis` 4.33 failed the contract cases for `GET /ui` and `GET /v1/session`
    (`429:UndefinedStatusCode`). The required `validate-and-test` check failed too: `ruff` 0.17's
    format check now reads Python inside Markdown files and reported "12 files would be
    reformatted". It also moves `ruff` 0.15 to 0.17,
    `playwright` (Python) 1.42 to 1.64 and `fastapi` 0.137 to 0.162. Suggested order: the runtime
    packages (`fastapi`, `pydantic-settings`, `prometheus-fastapi-instrumentator`) with their
    tests and a boot of the image, then `mutmut`, `schemathesis`, `ruff` and `playwright` each on
    their own.
  - #603, the e2e group. It moves `@playwright/test` 1.61 to 1.64, which can change the Linux
    visual baselines (AGENTS.md 13d, 13e). Its e2e check failed.
  - Dependabot alert 10, `minimatch` in `e2e/package-lock.json` (test tooling only). #603 does not
    fix it: `@typescript-eslint/typescript-estree` still asks for `minimatch` ^10, and the
    advisory's fixed version is 11.0.1, so the fix is an npm override to 11 with a proof that the
    e2e lint still runs.
- **The owner's page decisions (CHG-112):** W136, W137, W141, W142, W143 and W144; then W51 and
  W129; then W117 and the rest, as the previous handoff lists them.
- **W146 (new):** two Sentry test files interfere when run in a non-default order: run
  `tests/unit/test_sentry_init.py` and then
  `tests/unit/test_logging_config_sentry_redaction.py::test_reentrant_logging_does_not_recurse_through_redaction`,
  and the second fails on `sentry-sdk` 2.73.0 (the redaction recursed 88 levels deep) and hung
  past two minutes on 2.63.0. The default alphabetical order runs the second file first, so the
  suite passes; a Sentry client is left attached by the first file.

## Technical traps

- **A dependency bump can pass every test and still break a promise.** The whole suite was green
  on `sentry-sdk` 2.73.0, locally and in Dependabot's CI; only a reviewer driving the real client
  with production's options found the log path. For a runtime library that a decision record
  depends on, list the failure modes from that record first and test what reaches the wire.
- **Run a lock bump's gates in an environment synced from that lock.** Pointing
  `UV_PROJECT_ENVIRONMENT` at the main checkout's environment runs the tests on the old version.
  In the worktree, `uvx --from 'uv==0.13.0' uv sync --locked --all-extras --python 3.12` gives it
  its own environment (a real folder, which `.gitignore` covers).
- **Write a lock with the uv version CI pins (0.13.0).** It writes lock format revision 5 where
  the older lock had 3; the local uv may differ. It may also resolve a release newer than the
  repository's 7-day wait allows; pin the version Dependabot chose.
- **A Dependabot pull request for a CI action cannot pass alone** when a board row's needle is
  the pin it moves: rebuild it on a branch that also runs `make open-work-write`.
- **The baseline seeder commits with a skip-CI marker.** Run it on a throwaway branch, never on a
  pull request's branch; to prove its push works, remove one baseline on that branch first.
- **The built image listens on port 8000**, not 8080 (`Dockerfile` `EXPOSE`).
