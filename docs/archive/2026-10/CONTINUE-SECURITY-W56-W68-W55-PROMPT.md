# Session prompt: W56 (widened), W68, W55

Written by the session of 2026-10-11 to 2026-10-13 (transcript `20d36bac`). This file is the
session's wording. The owner's decisions are the CHG rows it names; the order below is CHG-042 (b).

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/<date>-session-handoff.md`.
2. `docs/analysis/2026-10-13-security-review.md`. Findings S1 to S4 are this session's work. Its
   section 1 is what was run; its section 2 is agents' reports, to reproduce before acting on.
3. `docs/65-open-work.md`, rows W56, W68, W59 and W55.
4. `docs/19-change-control-log.md`: CHG-042, CHG-029 (d) and CHG-033 (c).
5. `docs/adr/0144-anonymous-spend-is-counted-per-network.md`, decision 5, and
   `docs/48-data-retention.md`, the row "The spend key of an anonymous visitor's network".

## The items, in order

Each is its own pull request, merged and running in production before the next starts. Route each
with `make skill-route ITEM=<row>`. Each one touches privacy, secrets or the build, so each
review round includes a reviewer whose job is to break it as an attacker would.

1. **W56, widened (CHG-042 (a)): nothing private reaches Sentry.**
   - Covers the anonymous network's spend key beside `client_ip` in the event at the daily spend
     limit (`src/product_app/costs.py`, the `cost_guardrail_degraded_to_simulation` branch).
   - Also covers request headers: the visitor's address (`Fly-Client-IP`), the anti-forgery
     token, and any account header.
   - Also covers a key inside an exception message.
   - Start the tests from the two probes in the report's S1 and S2. Each must fail on today's
     `main` and pass after the fix.
   - Partner tests: a harmless header and a non-key message still arrive. Otherwise the scrubber
     could drop everything and still pass.
   - Update the `docs/48` rows in the same pull request.
   - If the fix cannot leave the signed-in account's Sentry fields unchanged, ask the owner at the
     START, with the question tool, one example and your recommendation marked. Record the answer
     as a CHG row.
   - Production cannot show this for free. Say so, and name the tests that prove it.
2. **W68: build from the lock file, and close the six library vulnerabilities.**
   - `Dockerfile:16` must install exactly what `uv.lock` pins.
   - Update `anyio` to 4.14.2 or later and `urllib3` to 2.8.0 or later in `uv.lock`.
   - Add a blocking CI job that runs `pip-audit` (or `osv-scanner`) on the locked runtime
     libraries. The job must print how many packages it checked, and must refuse an empty list.
   - This closes the cause of W59. Pin both rows with needles the change adds or deletes.
   - `docker-build` has no local equivalent, so read its CI log.
   - Production check: with `fly ssh console`, read-only, print the installed versions of
     `anyio`, `urllib3`, `cffi` and `pycparser`, and compare them with `uv.lock`.
3. **W55:** wipe the anonymous network's spend key from cost-ledger rows older than 48 hours.
   - Rows and amounts stay. The owner decided 48 hours (CHG-033 (c)).
   - Update the `docs/48` row and the board row in the same pull request.
   - Production check: inside the machine (`fly ssh console`), read-only, count the anonymous
     ledger rows older than 48 hours that still hold a key. Print the count only, never a key,
     and expect 0 once the wipe has run.

If time remains, the next rows in CHG-042 (b) are W69 then W70. Neither is approved by this prompt.

## Approvals

Sending this prompt approves the following for four pull requests: W56, W68, W55, and the
end-of-session handoff (docs only).
- Push and open the pull request.
- Squash-merge through `make close-guard`, with `EXPECT_CLOSE=""`.
- Deploy.

Each needs every required gate green and every reproduced blocker fixed. Nothing else is approved:
- no paid call;
- no `fly secrets` change;
- no attack on production.

## End of session

1. Run `make handoff`.
2. Write the narrative handoff. Every "merged" or "in production" must cite its pull request, or
   `make validate` refuses it.
3. In the handoff pull request, archive this file into `docs/archive/<month>/`.
4. After the merge, delete the root copy by name.
