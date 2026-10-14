# ADR-0166: CI actions are pinned to commits, and the workflows are audited

## Status

Accepted — 2026-10-14. The work is the owner's choice: CHG-042 (b) put "CI pinning" fourth, after
W56, W68 and W55 (board row W69). The design below is the session's: commit pins with a version
comment, exact `uv` and `flyctl` versions, a manual deploy from `main` only, and `zizmor` run
from the lock as a step of the required `validate-and-test` job.

## Context

Finding S6 of `docs/analysis/2026-10-13-security-review.md`: 50 `uses:` lines in
`.github/workflows/*.yml` named an action from outside this repository, and 1 was pinned to a
full commit. A tag such as `v4` is a movable label. Whoever controls the action's repository can
point it at different code, and that code then runs in this repository's jobs, including the
deploy job that holds `FLY_API_TOKEN`.

The row also carried three agents' reports, each reproduced before it was built (measurements 4
to 7):
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
3. **A manual deploy runs only from `main`.** `scripts/deploy_gate.py` refuses a
   `workflow_dispatch` whose `GITHUB_REF` is not exactly `refs/heads/main`: `proceed=false`,
   exit 1, so the run is red. The `deploy` job's `if:` refuses it too, as a second, independent
   check. The `gate` job's `if:` still admits a dispatch from any ref, on purpose: a ref term
   there would turn the refusal into a silent skip. `github.ref`, not `github.ref_name`, because
   a tag named `main` has `ref_name` `main`.
4. **`make workflow-audit` runs `zizmor --offline` over `.github`**, with
   `.github/zizmor.yml`, as a blocking step of `validate-and-test` (after the security scan).
   `zizmor` 1.30.1 is in the `quality` extra and in `uv.lock`, so CI installs a hashed file, not
   whatever PyPI serves that day. The config requires a commit pin for every action, GitHub's
   own included.
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
- **zizmor's online audits** (for example, a commit that exists only in a fork of the action's
  repository). They need the network and a token in the audit step. The commits here were
  checked once against their tags (measurement 2); a later pin change gets the same check by
  hand until this is revisited.
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
- A manual deploy from a branch now fails at the gate. Rolling back is unaffected: it is
  `fly releases rollback` (`DEPLOY.md`).
- Advisory, recorded and not built here:
  - zizmor's stricter `pedantic` mode reports 4 workflow-wide write permissions, 4 matrix values
    pasted into `run:` (set in the workflow file, not by visitors), and 11 lower-level items;
  - the `$/` self-repository form for `bound-apt-waits`;
  - `FLY_API_TOKEN` is a repository secret with no environment rules (a repository setting);
  - the Dockerfile's `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` base is a tag, not a
    digest.
