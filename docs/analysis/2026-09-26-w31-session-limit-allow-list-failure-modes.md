# W31 — the session-limit allow-list: failure modes first

Written before the code (AGENTS rule 16e), for board row W31 and CHG-022
item (2). The owner's words (13:41:59Z, 2026-09-25): *"should we also have an
allow list, which would help us allow certain IPs for testing purposes? ...
if I need to give this application to a firm for testing ... multiple
people's HRs and hiring managers need to test it ... I can simply update
their IPs in the allow list, and they will be relieved from this check."*
What they approved (CHG-022 item 2): single addresses or ranges, each with a
name and an end date; refused at startup if wider than /24 (IPv4) or /48
(IPv6); lifting ONLY the two per-network session limits, never the spend
limits; set as one secret; logged at startup as counts and end dates without
addresses; exempted requests counted on the operations page. And item (3),
kept in view: an address list helps only people on the firm's own network,
not someone at home or on mobile data. The invite link (W32) is for them.

## Failure modes, and the design's answer to each

1. **The list lifts a spend limit.** It must not. The exemption is applied at
   exactly two call sites, the per-minute limiter and the daily new-session
   cap, both in the session routes. `DAILY_CAP_USD` (per account) and
   `GLOBAL_DAILY_CEILING_USD` (site-wide) read neither the list nor the
   address. A test proves an exempt visitor's run is still refused by the
   per-account cap.
2. **An entry too wide** (a typo like `/8`, or `0.0.0.0/0`). Refused at
   startup, as approved: wider than /24 (IPv4) or /48 (IPv6). Also refused:
   a host part set (`81.2.69.7/24`, ambiguous), and (**PROPOSED — the
   session's bound**) any range that is not public: private, loopback,
   link-local, reserved, documentation or IPv4-mapped. No real visitor comes
   from one, and an entry inside Fly's proxy range would match every request
   that reaches the app without a usable `Fly-Client-IP`.
3. **A refusal takes production down.** A bad secret stops the app from
   starting. The mitigation: the owner checks the value first with a local
   command that runs the same parser and prints what it would load (counts
   and end dates only), and only then sets the secret. The value is read
   from standard input, so it never lands in shell history; `DEPLOY.md` sets
   the secret from standard input too, and gives the recovery step
   (`fly secrets unset SESSION_CAP_EXEMPT_NETWORKS`).
4. **An entry that never ends.** Every entry needs an end date. After that
   date it no longer applies (checked on every request, not only at
   startup, so a long-running machine stops honouring it on time); an entry
   ending on 2026-10-31 applies through the end of that day in UTC. Expired
   entries are counted in the startup log and do not stop the app. An end
   date more than 366 days ahead is refused (**PROPOSED — the session's
   bound**, the safe default until the owner says otherwise).
5. **A nameless entry.** Refused: every entry needs a name, so the owner can
   tell who each one was for and remove it.
6. **Addresses in logs.** The startup log names counts and end dates only.
   Names are not logged either (a firm's name in the log adds nothing the
   owner does not know). Nothing logs a matched address.
7. **A forged address.** The list matches the visitor's address as W30
   resolves it (Fly-Client-IP from Fly's private ranges only), so a client
   cannot name an exempt address. Under docker compose W30's trust differs
   (ADR-0132), and this inherits that.
8. **IPv6 matching.** The list matches the visitor's full address, not
   W30's /64 key, so a /64 or /48 entry covers exactly what it says.
9. **Counting exempted requests** must not add a new label per address
   (metrics cardinality). It is one counter, and `/status` shows the number
   of exempted requests since start and the number of active entries.
10. **Malformed secret** (not JSON, wrong shape, bad date, unknown key,
    duplicate names). Refused at startup with a message that names the
    entry's position, not its address.
11. **A list so long nobody reviews it.** At most 50 entries (**PROPOSED —
    the session's bound**). Each is a firm's network, so 50 is far above
    the owner's described use.
12. **A visitor not on the firm's network.** Not exempt, by design; this is
    the limit the owner asked to keep in view (CHG-022 item 3). The invite
    link (W32) is the answer for them.
