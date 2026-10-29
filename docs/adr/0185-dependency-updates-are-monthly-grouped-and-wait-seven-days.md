# ADR-0185: Dependency updates are monthly, grouped, and wait seven days

## Status

Accepted — 2026-10-29, board rows W118 and W79. The owner's decision CHG-103 asked for a
Dependabot configuration and a real `CODEOWNERS`; the schedule, the grouping and the wait are
engineering choices made in W118.

## Context

The repository had no `.github/dependabot.yml`. Known vulnerabilities still raised Dependabot
alerts, but nothing proposed routine updates, so dependencies moved only when an alert forced
them. `CODEOWNERS`
held the template's placeholder owner, and the repository had no security policy of its own, so
GitHub showed a generic one inherited from the owner's account. That generic policy asks for
email and names a workflow this repository does not run.

Every pull request here runs the full CI (about 35 minutes for the unit tests alone on main's run
for `88f618d`, run 40868586655), so the number of update pull requests matters.

## Decision

1. `.github/dependabot.yml` covers the three kinds of lock file the tree has: `uv` at the root,
   `npm` in `e2e/`, and the workflows' actions. Each runs monthly, as one grouped pull request
   per kind, and waits 7 days after a release before proposing it (zizmor's
   `dependabot-cooldown` audit, which `make workflow-audit` runs, requires a wait). Only minor
   and patch versions are proposed; major versions are ignored and each is taken on as its own
   work item, because one breaking change would block the whole group (on 2026-10-29, five
   of the six actions the workflows pin were two or more major versions behind their latest
   release).
2. `CODEOWNERS` names the repository owner for every path.
3. `SECURITY.md` sends reports to GitHub's private vulnerability reporting for this repository
   and states the scope, including no automated scanning of production.
4. `docs/84-incident-response.md` lists every production secret with where it is read, where it
   is replaced and what replacing it does, and the order: revoke first when it leaked. `DEPLOY.md`'s
   rotation note now names every effect of replacing `QUORUM_TOKEN_SECRET`, not only the first.

`tests/unit/test_w118_repository_hygiene_files.py` pins all four, including that every setting
`config.py` hides from `repr` has a row in the secrets table.

## Alternatives rejected

- **Weekly or ungrouped updates.** Each pull request adds a full CI run to the queue; up to three grouped
  pull requests a month keep the cost bounded.
- **Majors in the groups.** The first actions pull request would have bumped five major
  versions at once, and any one breaking change would hold back the rest.
- **No wait.** Proposing a release the day it appears leaves no time for a malicious or broken
  release to be found and withdrawn before it reaches a pull request.

## Consequences

- Security updates for known vulnerabilities are not limited by the monthly schedule. Opening
  them automatically needs the repository's Dependabot security updates setting, which is still
  off; until it is on, maintainers fix alerts by hand.
- A new secret setting fails a test until its replacement steps are written.
