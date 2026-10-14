# Session prompt: W69, W70

Written by the session of 2026-10-13 to 2026-10-14 (transcript `43b1c6b0`). This file is the
session's wording. The owner's decisions are the CHG rows it names; the order below is the rest of
CHG-042 (b), after W56, W68 and W55.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/<date>-session-handoff.md`.
2. `docs/analysis/2026-10-13-security-review.md`, findings S5 and S6. Its section 1 is what was
   run; its section 2 is agents' reports, to reproduce before acting on.
3. `docs/65-open-work.md`, rows W69 and W70.
4. `docs/19-change-control-log.md`: CHG-042.

## The items, in order

Each is its own pull request, merged and running in production before the next starts. Route each
with `make skill-route ITEM=<row>`. Each touches the build or the secret checks, so each review
round includes a reviewer whose job is to break it as an attacker would.

1. **W69: pin every GitHub Action from outside this repository to a full commit.**
   - Measured on 2026-10-14 at `8953725`: 50 `uses:` lines name an outside action and 1 is pinned
     to a full commit.
   - Keep the version as a comment beside each commit id. Check each id against its tag with
     `gh api`, and say in the pull request how many you checked.
   - Pin the `uv` version that CI installs (a W68 advisory).
   - The row's other parts are agents' reports: the `zizmor` workflow check, a pinned `flyctl`
     version, and deploys from `main` only. Reproduce each before building it.
   - A test must go red when an unpinned outside action is added, with a partner proving the
     check reads the real workflow files.
   - Production check: the Deploy job of this merge succeeds with the pinned actions, and
     `/status` `build_sha` matches.
2. **W70: the secret scan misses keys outside Python files.**
   - Start from the reproduced case: the same fake key in a new `.py` file and a new `.js` file;
     today the scan names only the `.py` file. The test must fail on `main` and pass after.
   - The rest of the row is agents' reports (`.ts`, `.sh` and `.example` files, split keys, other
     secret names). Reproduce each before building it.
   - A home-directory path rule would flag files under `docs/` that already hold one (28 by the
     row). If the fix must change those files or exempt them, ask the owner at the START, with
     the question tool, one example and your recommendation marked. Record the answer as a CHG
     row.
   - Partner tests: a file with no key still passes, so the scan cannot pass by flagging nothing
     or fail by flagging everything.
   - Production cannot show this; the scan runs in CI. Name the tests that prove it.

## Approvals

Sending this prompt approves the following for three pull requests: W69, W70, and the
end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""`.
- Deploy.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is approved:
- no paid call;
- no `fly secrets` change;
- no change to GitHub's repository settings;
- no attack on production.

## End of session

1. Run `make handoff`.
2. Write the narrative handoff. Every "merged" or "in production" must cite its pull request, or
   `make validate` refuses it.
3. In the handoff pull request, archive this file into `docs/archive/<month>/`. Run `ls` there
   first; if a file of the same name exists, add a date suffix.
4. After the merge, delete the root copy by name.
