# ADR-0166: CI actions are pinned to commits, and the workflows are audited

## Status

Accepted — 2026-10-14. The work is the owner's choice: CHG-042 (b) put "CI pinning" fourth, after
W56, W68 and W55 (board row W69). The design below is the session's: commit pins with a version
comment, exact `uv` and `flyctl` versions, a refusal of a manual deploy from any ref but `main`
(in the files, so it binds only refs that carry them; see Decision 3), and `zizmor` run
from the lock as a step of the required `validate-and-test` job.

## Context

Finding S6 of `docs/analysis/2026-10-13-security-review.md`: 50 `uses:` lines in
`.github/workflows/*.yml` named an action from outside this repository, and 1 was pinned to a
full commit. A tag such as `v4` is a movable label. Whoever controls the action's repository can
point it at different code, and that code then runs in this repository's jobs, including the
deploy job that holds `FLY_API_TOKEN`.

The row also carried three agents' reports, each reproduced before it was built (measurements 4
to 6):
- the deploy's `flyctl` version was "latest";
- a manual deploy ran from any branch, ungated;
- `zizmor`, an auditor for workflow files, reported findings.

## Decision

1. **Every outside action is pinned to the full commit its tag pointed at on 2026-10-14**, with
   the version as a trailing comment: `actions/checkout@11d5960… # v4.4.0`. Each tag was
   resolved with `gh api` to a commit, and to the exact release at that commit (measurement 2).
   So the pin changes no code that runs today; it stops the code from changing silently later.
2. **`uv` and `flyctl` are pinned.** Every `astral-sh/setup-uv` step sets `version: "0.13.0"`.
   Six steps had `"latest"` and six had no `with:` at all. The `setup-flyctl` step sets
   `version: "0.4.117"`. These are the versions CI and the deploy used last before this change
   (measurement 3). Pinning an action does not pin what it installs: both actions default to
   "latest".
3. **The files refuse a manual deploy from any ref but `main`; this does not by itself stop a
   branch from deploying.** `scripts/deploy_gate.py` refuses a `workflow_dispatch` whose
   `GITHUB_REF` is not exactly `refs/heads/main`: `proceed=false`, exit 1, so the run is red.
   The `deploy` job's `if:` refuses it too, as a second check in the same file. That second
   check is weaker than the script: GitHub compares strings in expressions ignoring case, so
   `refs/heads/MAIN` passes the `if:` and only the script refuses it. The `gate` job's `if:`
   still admits a dispatch from any ref, on purpose: a ref term there would turn the refusal
   into a silent skip. `github.ref`, not `github.ref_name`, because a tag named `main` has
   `ref_name` `main`.

   **What this covers, and what it does not.** GitHub runs a manual dispatch with the workflow
   file as it is on the ref the operator picks, and the gate job checks out that ref's
   `deploy_gate.py`. So both checks bind only a branch or tag whose files already carry this
   change: they catch an operator who picks the wrong ref in the dropdown. They cannot stop a
   branch whose `deploy.yml` or `deploy_gate.py` is older or edited. Every one of the 5 remote
   branches on 2026-10-14 is such a branch: each carries the old gate
   (`git show origin/<branch>:scripts/deploy_gate.py | grep -c ungated` printed 2 for each).
   Anyone who can push a branch can also edit `deploy.yml` on it. The boundary that does stop
   this is a GitHub deployment environment restricted to `main` that holds `FLY_API_TOKEN` and is
   attached to the deploy job. That is a repository setting this work was not approved to
   change; see the owner action under Consequences.
4. **`make workflow-audit` runs `zizmor --offline` over `.github`**, with
   `.github/zizmor.yml`, as a blocking step of `validate-and-test` (after the security scan).
   `zizmor` 1.30.1 is in the `quality` extra and in `uv.lock`, so CI installs a hashed file, not
   whatever PyPI serves that day. The config requires a commit pin for every action, GitHub's
   own included. On zizmor 1.30.1 that is already the default: `--no-config` on `b604c69`'s
   `.github` reports the same 49 unpinned actions (106 findings, exit 14). The config line is
   insurance against a later release changing the default.
5. **Findings are fixed, not suppressed, where a fix is safe** (measurement 6):
   - template injection (9): each `${{ github.base_ref }}`, `${{ github.ref_name }}` and the
     deploy's `GIT_SHA` expression inside `run:` now goes through `env:`, and the shell reads a
     quoted variable;
   - persisted git credentials (18 of 19): `persist-credentials: false` on every checkout whose
     job never pushes. The repository is public, so `git fetch` needs no credentials, and `gh`
     reads `GH_TOKEN`, not git's stored credentials;
   - the `test.yml` token's permissions: now `contents: read`.

   Six findings are suppressed in `.github/zizmor.yml`, each with its reason:
   - `dangerous-triggers` on `deploy.yml`: the `workflow_run` trigger is the deploy gate
     (ADR-0024), and the gate job runs only for a push to this repository's `main`;
   - persisted credentials at `seed-visual-baselines.yml:38`: that job pushes the baselines back;
   - `self-repository` in 4 files: zizmor suggests GitHub's new `$/` form for the in-repo action
     `./.github/actions/bound-apt-waits`. That is a separate change (Consequences).

## Measurements

All on 2026-10-14. The branch is `w69/pin-actions`, cut from `b604c69`.

| # | Fact | Value | Command |
|---|---|---|---|
| 1 | Outside actions before | 50 `uses:` lines, 1 pinned to a commit; by action: `actions/checkout` 19, `astral-sh/setup-uv` 12, `actions/upload-artifact` 7, `actions/setup-python` 6, `actions/setup-node` 5, `superfly/flyctl-actions/setup-flyctl` 1 (already a commit) | `grep -hE '^\s*-?\s*uses:' .github/workflows/*.yml \| sed -E 's/.*uses:\s*//' \| sort \| uniq -c` |
| 2 | Each tag's commit | 11 lookups, all matching: `checkout` v4 and v4.4.0 → `11d5960…`; `setup-uv` v5 (an annotated tag, dereferenced) and v5.4.2 → `d4b2f3b…`; `upload-artifact` v4 and v4.6.2 → `ea165f8…`; `setup-python` v5 and v5.6.0 → `a26af69…`; `setup-node` v4 and v4.4.0 → `49933ea…`; `flyctl-actions` tag 1.6 → `ed8efb3…` | `gh api repos/<owner>/<repo>/git/ref/tags/<tag>`, then `git/tags/<sha>` for an annotated tag; run by the orchestrator and again by the builder |
| 3 | The tool versions in use | `uv` 0.13.0 (CI run 38506956039 on `main`: `Downloading uv from ".../download/0.13.0/..."`); `flyctl` 0.4.117 (Deploy run 38508871831: `Acquired 0.4.117`) | `gh run view <id> --log` |
| 4 | `setup-flyctl`'s default | `version` defaults to `latest` | `gh api 'repos/superfly/flyctl-actions/contents/setup-flyctl/action.yml?ref=ed8efb3…'` |
| 5 | A manual deploy from another branch | before this change, `deploy_gate.py`'s `main()` returned 0 and wrote `proceed=true` for any `workflow_dispatch`, whatever the ref (`scripts/deploy_gate.py:280` at `b604c69`); the deploy job checks out `github.sha`, the dispatching ref's commit. The 3 manual Deploy runs in the API's history all ran from `main` | reading the code at `b604c69`; `tests/unit/test_w69_manual_deploy_main_only.py` failed 14 cases there; `gh run list --workflow 'Deploy to Fly.io' --event workflow_dispatch` |
| 6 | zizmor's findings before | zizmor 1.30.1, offline, with only the hash-pin policy, on `b604c69`'s `.github`: exit 14, `106 findings (23 suppressed, 29 unsafe fixes)`: 49 unpinned actions, 19 persisted credentials, 9 template injection, 4 self-repository, 1 excessive permissions, 1 dangerous trigger. The security review's agent also reported 106. zizmor 1.14.2 with no config shows 42 (26 suppressed): its default allows a tag for `actions/*` | `git archive b604c69 .github`, then `zizmor --offline --config <hash-pin only> <copy>/.github`; `uvx zizmor@1.14.2 --offline .github/workflows .github/actions` |
| 7 | zizmor after | exit 0, `No findings to report. Good job! (6 ignored, 22 suppressed)` | `make workflow-audit` |
| 8 | The lock change | only `zizmor` 1.30.1 added; no other package moved | `git diff uv.lock` |

## Rejected alternatives

- **Keep the major tags and rely on automated update pull requests to notice a moved tag.** A moved tag runs new code on the next job, before any pull request exists. Nothing here configures automated updates today (there is no `.github/dependabot.yml`); a later change can add them for the pinned commits.
- **Fetch zizmor at run time with `uvx zizmor==1.30.1`**, as `make vuln-audit` does for
  `pip-audit` (ADR-0164). `uvx` pins the version but not the file's hash. The lock pins both,
  and `uv sync --locked` already runs in the job.
- **zizmor's online audits** (`impostor-commit`: a commit that exists only in a fork of the
  action's repository; `ref-version-mismatch`: a version comment that does not match the
  commit). They need the network and a token in the audit step. The commits here were
  checked once against their tags (measurement 2); a later pin change gets the same check by
  hand until this is revisited.
- **Treat the in-file refusal of a non-`main` dispatch as the boundary.** It is not one: a
  manual dispatch runs the picked ref's own `deploy.yml` and `deploy_gate.py` (Decision 3).
  The real boundary is a deployment environment, which needs a repository setting.
- **A separate audit job.** It would block a merge only if branch protection named it, which is
  a repository setting this work was not approved to change. A step in `validate-and-test`
  blocks without one, as in ADR-0164.
- **A ref condition on the `gate` job's `if:`.** It refuses a non-`main` dispatch by skipping
  the job, and a skipped job looks like a run that had nothing to do.

## Consequences

- An update to an action is a pull request that changes the commit and the comment together.
  `tests/unit/test_w69_actions_pinned.py` fails when an outside action is added without a
  commit or a version comment, or when one commit carries two version labels.
- A new zizmor finding in a workflow fails `validate-and-test`. A line-scoped suppression
  (`seed-visual-baselines.yml:38`) goes red if lines above it move; update the number with the
  edit.
- A manual deploy from a branch or tag cut after this change fails at the gate. A manual
  deploy from a branch with an older or an edited `deploy.yml` or `deploy_gate.py` is NOT
  stopped: it runs that branch's own copy, with the same `FLY_API_TOKEN` (Decision 3).
- **Owner action, not done here.** To make "a manual deploy runs only from `main`" true for
  every branch: move `FLY_API_TOKEN` into the `production` environment (it exists today, with
  no protection rules, and no workflow uses it), add a deployment-branch rule to it that
  allows only `main`, attach `environment: production` to the `deploy` job, then delete the
  repository-level `FLY_API_TOKEN`. This session did not do it, because repository settings
  were not approved. The last step is the one that protects: GitHub's documentation says a job
  receives repository secrets whether or not it names an environment, so while the
  repository-level secret exists, a branch whose `deploy.yml` drops `environment:` still gets
  the token (documented behaviour, not tested here).
- Rolling back does not go through `deploy.yml`. It redeploys an earlier image:
  `fly releases --image -a quorum-ai` lists each release's image, and
  `fly deploy --image <that image> -a quorum-ai` deploys it (`DEPLOY.md`). Both flags exist in
  flyctl 0.4.113 (`fly releases --help`, `fly deploy --help`); flyctl has no
  `releases rollback` subcommand. The procedure has not been run against production.
- Advisory, recorded and not built here:
  - zizmor's stricter `pedantic` mode reports 4 workflow-wide write permissions, 4 matrix values
    pasted into `run:` (set in the workflow file, not by visitors), and 11 lower-level items;
  - the `$/` self-repository form for `bound-apt-waits`;
  - `FLY_API_TOKEN` is a repository secret with no environment rules (a repository setting;
    the owner action above);
  - two Dockerfile bases are tags, not digests: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
    (`Dockerfile:3`) and `python:3.12-slim` (`Dockerfile:39`, the runtime image);
  - a pin to a wrong commit, used the same way everywhere with a plausible version comment,
    passes every offline check here; zizmor's online `impostor-commit` (a commit only in a
    fork) and `ref-version-mismatch` (a comment that does not match the commit) audits would
    catch those two cases (not used; see Rejected alternatives);
  - `setup-uv` at `d4b2f3b` checks the uv download only against its built-in checksum list,
    which has no entry for 0.13.0 (its newest is 0.6.14), so the uv binary's bytes are not
    checked; a `checksum:` input on each step would check them;
  - an action outside `.github` used through `./` is read by neither
    `tests/unit/test_w69_actions_pinned.py` nor zizmor, which both read only `.github`;
  - the whole-file `dangerous-triggers` ignore on `deploy.yml` would also hide a new trigger
    added to that file; `tests/unit/test_w69_round1_regressions.py` now fails if `deploy.yml`'s
    triggers are anything but `workflow_run` and `workflow_dispatch`.
