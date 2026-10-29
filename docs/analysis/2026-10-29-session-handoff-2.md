# Session handoff, 2026-10-29 (second session)

Written by the session. Decisions are the CHG rows named here, each a plain restatement (CHG-102).

## Shipped

- **#600: test-tool dependency patches.** Squash-merged as `a11c036`. `graphql-core` 3.2.13,
  `Werkzeug` 3.1.9 and `brace-expansion` 5.0.12, all reached only through test tools. Deploy run
  40904076491 has the job "Deploy to Fly.io" concluded `success`, and production `/status`
  reported `build_sha` `a11c036…` afterwards. Four of the five open Dependabot alerts closed; the
  fifth, `pytest`, needs version 9, a major.
- **#601, W117 part 1: public records restate decisions.** Squash-merged as `5ec92ab`. `AGENTS.md`,
  the delivery skill, its prompt template and `docs/README.md` record a decision as what was
  decided, its basis, its trade-offs and the date, and keep the next-session prompt private
  (CHG-102). The public-content guard is shared across repositories rather than built here
  (CHG-104, ADR-0184). The secret scan is now the step right after the install in
  `validate-and-test`; on main's run for `5ec92ab` it is step 8, ahead of the unit tests at step
  14. Deploy run 40910289162 has the job "Deploy to Fly.io" concluded `success`, and `/status`
  reported `build_sha` `5ec92ab…` afterwards.
- **#602, W118 and W79 part A.** Squash-merged as `e52646e`. A real `CODEOWNERS`; Dependabot
  proposes one grouped minor-and-patch update a month for `uv`, the e2e npm packages and the
  workflows' actions, each waiting 7 days, with majors left to their own work items (ADR-0185);
  the repository's own `SECURITY.md`; and every production secret's replacement steps in
  `docs/84-incident-response.md`, with all three effects of replacing `QUORUM_TOKEN_SECRET`
  stated there and in `DEPLOY.md`. Its blocking e2e lane failed once on the flaky
  `tabs-share-token.spec.ts` E3 test (now in W121) and passed on a re-run of that job.
  Deploy run 40923088925 has the job "Deploy to Fly.io" concluded `success` (one of twelve
  Deploy runs for that merge; the rest were skipped or cancelled), and `/status` reported
  `build_sha` `e52646e…` afterwards. GitHub's security-policy page for the repository now shows
  this `SECURITY.md`.

## Repository settings changed

- CodeQL default setup: on (advisory, not a required check).
- Branch protection on `main`: conversation resolution is required. The six required checks
  are unchanged.
- Commits made in this repository's checkouts use the GitHub no-reply address (repository-local
  git configuration).
- Not changed, though approved in CHG-103: Dependabot security updates and secret scanning's
  non-provider patterns are still off. The owner turns them on.

## Open, in order

- **W117:** adopt the shared public-content guard (its CI step, advisory first, and a scan of the
  merge text in `make close-guard`) once it passes the shared test set; then `make prompt-check`
  inverted so no next-session prompt sits at the root.
- **W118 and W79, the rest:** `security.txt` served by the app; bandit and gitleaks, advisory, and
  a review of bandit's findings of SQL built from strings; `pytest` 9.
- **W121** (flaky tests) before **W62** (suite time); the cleanup of existing public records;
  **W120**; **W119**; then W114's pull request B, W80, W75, W76, W95's code part and W113's
  redesign.

## Technical traps

- **`make validate`'s completion-claims check reads only committed files.** A new, untracked ADR
  with "released" in it was not refused by `make validate`; once committed, it was. Commit before
  trusting it.
- **zizmor requires a Dependabot cooldown.** `make workflow-audit` reports `dependabot-cooldown`
  and fails without `cooldown.default-days` on each update entry.
- **A test that asks git or reads root files must be kept out of the mutation run, and listed.**
  Mark it `pytestmark = pytest.mark.repo_introspection` and add it, with its reason, to
  `DESELECTED_FROM_THE_MUTANT_RUN` in `tests/unit/test_mutation_test_set_integrity.py`; the guards
  from W116 fail otherwise.
- **Tests that shell out to `make` or `uv run` fail with "Failed to spawn: pytest" in a worktree
  with no `.venv`** unless `UV_PROJECT_ENVIRONMENT` points at an environment. That failure is the
  environment, not the change; re-run with it set before blaming the diff.
- **zsh does not split `$VAR` into words.** `pytest $FILES` passes one argument; use `${=FILES}`.
- **BSD `sed` ignores GNU's `0,/re/` address.** A mutation made that way changes nothing and
  "survives". Make mutations with Python and check the file changed.
- **Replacing `QUORUM_TOKEN_SECRET` is not cheap.** Besides confirmation tokens, it restarts every
  network's anonymous daily allowance and its in-memory running total, and resets a deleted
  account's 24-hour carry (`docs/84-incident-response.md`, ADR-0144, ADR-0136).
- **`gh pr merge --author-email` with the GitHub no-reply address is refused** (`GraphQL: Invalid
  email address`) while the account does not keep its email private; squash commits then carry the
  account's default address. Local commits in this repository already use the no-reply address.
