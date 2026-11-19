# Session handoff, 2026-11-19

Written by the session that started on 2026-11-18.

## Shipped

- **#644, `fastapi` 0.162.2 to 0.162.4**, merge `6255a93`. Between the two wheels the code changes
  are the version string, type annotations and one `typing.cast` call; the app's OpenAPI document
  and route table were byte-identical under both. 0.162.4 also declares `anyio` as a direct
  requirement; `anyio` was already locked. The built image booted in production mode and answered
  200 on `/health`, `/ready` and `/status`. Of the merge's seven Deploy runs, one Deploy job
  concluded `success` (two were cancelled, four skipped); production `/status` reported `6255a93`
  and `/ready` answered 200.

## Open, in order

- **W147** (with W76's log and Sentry items). This session re-planned it around scrubbing at the
  exits: a separate process that scrubs the app's standard output and error, and, in a later pull
  request, a relay for Sentry traffic in that process. The owner settled the promise, the failure
  posture (fail closed) and a split into three pull requests. The plan was reviewed three times;
  the design itself held, but each review found new critical gaps in the detailed rules, so the
  stop rule applied again (CHG-049, ADR-0168). A smaller plan is written; its first review found two
  more gaps, which the next session settles before building the scrubbing core first as tested
  code. The branch stays local. Before it merges, the owner checks the live keys against the
  scrubbing rules.
- **`pytest` 9.2 has to move together with `schemathesis` 4.33.** Under `pytest` 9.2.0 with the
  locked `schemathesis` 4.10.2, five of the 12 tests in `tests/test_lazy_nodeid_selection.py` fail:
  4.10.2 renames each contract case through an attribute that `pytest` 9.2 no longer reads.
  `schemathesis` 4.33.2 sets `pytest` 9.2's structured id instead, and on Dependabot's group pull
  request #642 those tests pass. That pull request's other test failures are two new
  `429:UndefinedStatusCode` contract findings under `schemathesis` 4.33 (`GET /ui`,
  `GET /v1/session`) and two citation tests under `markdown-it-py` 4.3, where an unclosed bracket
  now drops a real citation number. So `schemathesis` and `pytest` are one item, and
  `markdown-it-py` 4.3 changes the trust score's input.
- **The rest of the dependency updates** (Dependabot group #642): `schemathesis` 4.33,
  `fastapi` 0.162.5, `ruff` 0.17, `playwright` (Python) 1.65, `hypothesis`, `zizmor`, and
  `markdown-it-py` 4.3. The last is pinned exactly because the trust score depends on how it
  splits text, so its update needs a recorded decision. Then #603 (the e2e group) and
  Dependabot alert 10 (`minimatch`, test tooling).
- **The owner's page decisions (CHG-112)**, then W117 onward, as the earlier handoffs list them.
- **W13** waits on an owner decision; parked to 2026-11-24.

## Technical traps

- **A zsh loop over `make` targets fakes a green gate.** `for t in quality "diff-cover
  DIFF_BASE=origin/main"; do make $t; done` passes the second item as one word under zsh, which
  does not split unquoted variables; `make` ran its default target instead, so `diff-cover` never
  ran, and it exited 0 with an empty log. Name each target on its own line.
- **One merge starts several Deploy runs, and a later one can cancel the one you are watching**
  after its gate has passed. On `6255a93` the first two runs were cancelled and the seventh
  deployed. Read the Deploy job of every run for the merge commit.
- **The cross-browser CSP smoke check (advisory) failed on `6255a93`** because installing WebKit's
  system packages timed out after 15 minutes on the Ubuntu mirror, before any test ran. Firefox and
  Chromium passed.
- **A green `uv lock --check` does not check hashes.** Neither `uv lock --check` nor
  `uv sync --locked --dry-run` noticed a planted wrong wheel hash; only a real `uv sync --locked`
  refused it. CI and
  the image build do real installs.
- **`fly.toml` stops machines with SIGINT, not SIGTERM**, with a 5-second kill timeout; a comment
  in the `Dockerfile` still says SIGTERM. Under SIGINT uvicorn exits 0 and runs exit handlers; under
  SIGTERM it does not.
