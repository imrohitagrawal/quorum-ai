# Session handoff — 2026-10-14

The session that ran from 2026-10-13 to 2026-10-14 (transcript `43b1c6b0`) on the security items
of CHG-042 (b): W56, W68 and W55. The source of truth is `git log` and the ADRs; this note says
where things stand.

## Shipped

| Pull request | Merge commit | What | Decisions |
|---|---|---|---|
| #562 | `1b6adf9` | W56: nothing private reaches Sentry. Request headers are allow-listed, keys are redacted from messages and extras, and the daily-limit alert no longer carries the visitor's address | ADR-0163, CHG-042 (a), CHG-043 |
| #563 | `cc1032f` | W68: production is built from `uv.lock`; `anyio` 4.14.2 and `urllib3` 2.8.0; a blocking CI job audits the locked libraries | ADR-0164 |
| #564 | `8953725` | W55: spend keys are wiped from every cost-ledger row, and visitor addresses from session rows, 48 hours after they were written; rows and amounts stay | ADR-0165, CHG-044 |

Each of #562, #563 and #564 was verified by the Deploy job of the run that succeeded and by
`/status` `build_sha`:
- #562 at `1b6adf9`, 2026-10-13T14:48:44Z (run 38416421605). Production cannot show a Sentry event
  for free; the tests in `tests/security/test_w56_regressions.py` are the proof.
- #563 at `cc1032f`, 2026-10-13T20:55:53Z (run 38466517167). Inside the machine, read-only, 31 of
  31 installed packages matched `uv.lock`. CI printed "31 packages, 0 known vulnerabilities".
- #564 at `8953725`, 2026-10-14T02:44:13Z (run 38502528857). Production's start-up log printed
  `cost_keys_wiped=142 session_addresses_wiped=70 malformed_payloads=0`. The read-only check in
  `docs/runbooks/feedback-store-schema-migration.md` then printed `cost_keyed_past_cut 0`,
  `mint_addressed_past_cut 0`, with 142 cost rows and 70 session rows still present.

## Next

W69, then W70 (CHG-042 (b)). The prompt is `CONTINUE-SECURITY-W69-W70-PROMPT.md` in the owner's
main checkout, untracked, so a fresh clone does not have it; the one it replaced is archived in
`docs/archive/2026-10/`. It approves nothing until the owner sends it.

## Left as advisory

From W56 (#562):
- a visitor's `sentry-trace` header forces that request to be sampled (costs quota only);
- key patterns the redactor does not know belong to W76;
- the rule that blanks `query*` extras also blanks `query_run_id`;
- outgoing requests to OpenRouter and Google carry trace headers;
- nothing checks `docs/48` against the code.

From W68 (#563):
- the `python:3.12-slim` base image ships pip 25.0.1 outside the app's environment (6 entries in the
  Python security advisory database; the app cannot import it);
- the audit needs the network, so an outage of the vulnerability database can turn
  `validate-and-test` red, and a newly published vulnerability blocks deploys;
- `uv` is not pinned in CI (W69);
- operating-system packages are not audited, and nothing audits after a merge (Dependabot alerts
  are off; the security review files that under W79).

From W55 (#564):
- an outside reader holding the database open makes start-up waits stack (10.81 s and 21.74 s
  measured in review);
- a clock more than 24 hours ahead at a wipe, later corrected, lets one account spend its daily cap
  once more; the site ceiling still holds;
- a disk short of room never gets the first wipe;
- accounts created before the spend key existed use one id as both account id and spend key, and
  it stays on other rows and in run history (ADR-0165, "Accounts created before the spend key
  existed"). This is outside CHG-044 and is an owner question for later;
- pre-existing: a damaged charge row inside 24 hours makes `daily_spend_for` raise
  `JSONDecodeError` (no writer produces one).

Found this session, pre-existing on `main`:
- `tests/unit/test_run_history_store.py::test_configure_for_tests_isolation` fails when it runs
  after any test that starts the app (for example `tests/security/test_w56_regressions.py`).
  Reproduced on `cc1032f`. It stopped the advisory mutation job on #564 from producing a score
  ("Failed to run clean test").
- `test_a_fixed_panels_estimate_and_bound_are_unchanged` in the W52 tests fails when run alone and
  passes in the full suite.

## Traps met this session

- The signed-in History lane of the E2E workflow fails now and then on CI. On #564's merge commit,
  `shared-allowance.spec.ts:120` waited 90 s for an estimate response, so the Deploy gate refused
  three times. The same tree had passed on the pull request; the lane then passed 10 runs out of
  10 locally (25 tests each), and a re-run of the failed job passed, and the deploy followed.
  Among the last 30 runs of that workflow (2026-10-08 to 2026-10-14), 4 failed their first
  attempt, all in this lane, and each passed on a re-run (`gh api .../runs/<id>/attempts/<n>`;
  `gh run list` shows only the latest attempt). The cause is not known, and the uploaded report
  held only the visual lane's results, so there was no trace to read. No board row records it.
- A merge's Deploy runs can all fail at the gate. Read each run's Deploy job; when none
  succeeded, read the E2E log, then re-run the failed job.
- `docker builder prune -f` freed 20.3 GB when the disk was down to 486 MB.
- The cited-paths and planted-claims tests read committed files: commit before trusting them.
- In a fresh worktree run `uv sync --locked --all-extras --python 3.12` first, and run tests
  through `uv run pytest`.
