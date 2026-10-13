> **Archived 2026-10-13.** Replaced by the root prompt for W56 (widened), W68 and W55 after the owner's decisions in CHG-042. It was never run; it is history, not to be run.

# Session prompt: W55 and W56

Written by the session of 2026-10-11 to 2026-10-13 (transcript `20d36bac`). This file is the
session's wording; the owner's decisions are the CHG rows it names.

**Process:** every item is built by `.agents/skills/work-item-delivery/SKILL.md`. Read it first,
and follow it for roles, review rounds, gates, merging, production checks and cleanup.

## Read first

1. `docs/README.md`, then the newest `docs/analysis/<date>-session-handoff.md`.
2. `docs/65-open-work.md`, rows W55 and W56.
3. `docs/19-change-control-log.md`: CHG-029 (d) and CHG-033 (c).
4. `docs/adr/0144-anonymous-spend-is-counted-per-network.md`, decision 5.
5. `docs/48-data-retention.md`, the rows "The spend key of a signed-in account" and "The spend key
   of an anonymous visitor's network". Both items change the second row.

## The items, in order

Each is its own pull request, merged and running in production before the next starts. Route each
with `make skill-route ITEM=W55` (or `W56`).

1. **W55:** wipe the anonymous network's spend key from cost-ledger rows older than 48 hours.
   - Rows and amounts stay. The owner decided 48 hours (CHG-033 (c)).
   - Update the `docs/48` row and the board row in the same pull request.
   - Production check: inside the machine (`fly ssh console`), read-only, count the anonymous
     ledger rows older than 48 hours that still hold a key. Print the count only, never a key,
     and expect 0 once the wipe has run.
2. **W56:** stop sending the anonymous network's spend key to Sentry in the same event as the
   visitor's address. Today it goes as `account_id` beside `client_ip` in the event sent when a run
   is switched to simulated answers at the site's daily spend limit (`src/product_app/costs.py`,
   the `cost_guardrail_degraded_to_simulation` branch).
   - The owner's instruction is to stop sending the network key there, so the key is the field
     that goes. What Sentry gets for a signed-in account is a separate, still-open row in `docs/48`.
   - If the fix cannot leave signed-in accounts unchanged, ask the owner at the START of the
     session, with the question tool and your recommendation marked, and record the answer as a
     CHG row.
   - Production cannot show this for free. Say so in the closing block, and name the test that
     proves it.

## Approvals

Sending this prompt approves push, pull request, squash-merge (through `make close-guard`, with
`EXPECT_CLOSE=""`) and deploy for three pull requests: W55, W56, and the end-of-session handoff
(docs only). Each needs every required gate green and every reproduced blocker fixed. Nothing
else is approved.

## End of session

Run `make handoff`, write the narrative handoff (every "merged" or "in production" cites its pull
request, or `make validate` refuses it), archive this file into `docs/archive/<month>/` in the
handoff pull request, and delete the root copy by name after the merge.
