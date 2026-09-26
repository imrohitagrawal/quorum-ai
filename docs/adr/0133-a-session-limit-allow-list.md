# ADR-0133: A session-limit allow-list for named, dated networks

## Status

Accepted — 2026-09-26, board row W31. The product owner decided this on
2026-09-25 (CHG-022, transcript `efe4f2fc`). Their words at 13:41:59Z:
*"should we also have an allow list, which would help us allow certain IPs
for testing purposes? ... if I need to give this application to a firm for
testing ... multiple people's HRs and hiring managers need to test it ... I
can simply update their IPs in the allow list, and they will be relieved
from this check."* At 13:47:58Z: *"I have said yes, so it should not be
mentioned as awaiting owner. Everything is approved here."* What they
approved is the session's proposal, CHG-022 item (2): single addresses or
ranges, each with a name and an end date; refused at startup if wider than
/24 (IPv4) or /48 (IPv6); lifting ONLY the two per-network session limits,
never the spend limits; one secret; logged at startup as counts and end
dates without addresses; exempted requests counted on the operations page.
Item (3), in the owner's view: an address list helps only people on the
firm's own network, not someone at home or on mobile data (W32, the invite
link, is for them).

Everything else here is the session's design. Four bounds are **PROPOSED —
AWAITING OWNER**, built at their safe default: an end date at most 366 days
ahead; at most 50 entries; names of at most 80 characters; public ranges
only.

## Context

W30 (ADR-0132) made both per-network session limits count the visitor: 2 new
sessions a day and 10 session requests a minute per address (an IPv6 visitor
by /64). A firm's testers usually share one office address, so after two
sessions the rest are refused. The failure modes were listed first:
`docs/analysis/2026-09-26-w31-session-limit-allow-list-failure-modes.md`.

## Decision

1. One setting, `SESSION_CAP_EXEMPT_NETWORKS`, a JSON list of
   `{"name", "network", "until"}`, set as one Fly secret. Empty (the shipped
   state): no one is exempt.
2. `session_exemptions.parse_exemptions` refuses, naming the entry's
   position and never its address: not JSON or not a list; an entry without
   exactly those three keys; an empty, repeated or over-long name; a network
   wider than /24 or /48, with host bits set, IPv4-mapped, or not public; an
   end date not written `YYYY-MM-DD` or more than 366 days ahead; more than
   50 entries. `main.py` parses it at import, so a malformed value stops the
   app at startup, as approved.
3. Before setting it, the owner checks a value with
   `pbpaste | uv run python -m product_app.session_exemptions --check`,
   which reads standard input (not shell history) and prints only counts and
   end dates, or the refusal.
4. An entry applies through the end of its `until` day in UTC, checked on
   every request. An expired entry does not stop the app; it is counted.
5. The two session routes (`/v1/session`, `/ui`) check the visitor's full
   address (W30's middleware, not the /64 key). An allow-listed visitor
   skips the per-minute limiter and the daily new-session cap; nothing else
   reads the list. Spend limits key on the account and the site, never an
   address.
6. The startup log is `session-limit allow-list: N entries: A active, E
   expired; active until <dates>`. `/status` gains
   `session_limit_allow_list` (active and expired entry counts, exempted
   requests since start), shown as a tile on `/ui/ops`. No name and no
   address is logged or shown.

## Rejected alternatives

- **Drop a bad entry and carry on.** Kinder to a typo, but a silently
  dropped entry is a firm refused with no signal; the owner approved
  "refused at startup", and the check command removes the risk of learning
  it in production.
- **Lift the limits by /64 key.** A single-address entry would then cover a
  whole /64. Matching the full address makes an entry cover what it says.
- **Allow private ranges.** Fly's proxy connects from `172.16.0.0/12`; such
  an entry would exempt every visitor.
- **No end-date bound.** An entry with an end date years ahead is the
  "never ends" failure with extra steps; 366 days is PROPOSED.

## Consequences

- A firm's testers on the listed network open sessions without the daily
  cap of 2 or the 10-a-minute limit. Their runs are still bounded by
  `DAILY_CAP_USD` per account and `GLOBAL_DAILY_CEILING_USD` for the site
  (`test_the_allow_list_never_lifts_a_spend_limit`).
- Testers at home or on mobile data are not covered (CHG-022 item 3).
- The exempted-request count is per process and resets on restart, like the
  other process counters on `/ui/ops`.
- A typo in the secret stops the app. The check command is the mitigation;
  the ADR does not add a softer failure.
