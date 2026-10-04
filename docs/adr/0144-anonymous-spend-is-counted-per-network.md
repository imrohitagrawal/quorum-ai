# ADR-0144: Anonymous spend is counted per network

## Status

Accepted — 2026-10-04, board row W47. The product owner decided the behaviour on
2026-10-04 (CHG-027 a): *"Anonymous spend: count it per network — all anonymous
sessions on one network share one $0.40 a day; signed-in accounts keep their own $0.40.
Its own work item after W37, failure modes and an ADR first."* It answers the owner
question ADR-0141 left open. The shape below is the session's design; its own calls are
listed under Consequences so the owner can overturn them. Failure modes, listed before
the code: `docs/analysis/2026-10-04-w47-anonymous-spend-per-network-failure-modes.md`.

## Context

An anonymous session's spend key is its own random id, so every new anonymous session —
after a sign-out, an idle expiry, or a cleared cookie — starts with a fresh $0.40, while
a signed-in account keeps one key for good (ADR-0136, ADR-0141). The network is already
identified for the per-network session limits (`auth.client_ip_of`, W30, ADR-0132), but
`auth.spend_key_for` takes no request and cannot see it.

## Decision

1. **An anonymous session's spend key is its network's key**: a keyed one-way hash of
   `client_ip_of(request)` — the IPv4 address, or an IPv6 address's /64 — under the
   server secret with a W47-only prefix, turned into a UUID the same way the signed-in
   key is (`session_store.account_id_for`). Every anonymous session on one network gets
   the same key, so they share one daily allowance.
2. **A request whose network cannot be identified** (no client; a host that is not an
   address) gets one shared key for all such requests, so it fails closed.
3. **Signed-in accounts are unchanged**: their key is the keyed hash of the Google
   subject, and their spend never counts against a network's anonymous allowance, nor
   the reverse. The legacy test header keeps its own id. Whether a session is
   signed in is read from its account row. On a database that predates the spend-key
   column (read-only, so the column was never added), an account row that exists keeps
   the account's own id as its key, as it was metered before this change; a session
   with no row is anonymous; a read that fails refuses the run (503). Refusing every
   run in that state was the alternative, and was not chosen: it would stop signed-in
   people who could run before.
4. **The key is read once per request** by `auth.spend_meter_for(session, request)` on the
   estimate and create routes, and stored on the run at create, as today, so a run's
   charge, void and reconcile share one key even if the network changes mid-run.
5. **No address is written anywhere new**: the cost ledger holds the hashed key only.
   `docs/48` gains a row for it. One existing event already carried the visitor's
   address: a run degraded at the global ceiling sends `client_ip` to Sentry, and that
   event now carries the network key beside it, so Sentry can pair the two. The hash
   protects the address only from someone without the server secret: with it, an IPv4
   key can be reversed by trying every address (about one to three core-hours in
   Python on one core, measured twice by review).
6. **The page says the allowance is shared.** The estimate's daily allowance carries a
   flag saying it is the network's; for an anonymous session the allowance line, the
   daily-allowance block, the running-total block, the daily and running-total
   screen-reader announcements,
   the late daily-cap refusal and the composer footer say it is shared by everyone on
   this network who is not signed in, and, when the page shows "Sign in with Google",
   that signing in gives a person their own $0.40 a day; the cost card then shows its
   own sign-in button, except on a block signing in cannot lift (the per-run cap, a
   daily-cap block for a run larger than the whole day, or a spend ledger that cannot be
   read; see Consequences for one case it does not catch). The server's reasons and messages say "this network"
   where they said "the account". A signed-in page never mentions the network.
7. **A local-only test override.** Every browser in the e2e lanes comes from one
   loopback address, so they would all share one $0.40 a day and the lanes could not
   run (measured by the test designer, with its reference build, on a fresh database:
   `page-journey.spec.ts` had 18 failures by its 29th test of 44; the failure page it
   checked read "Not enough allowance left"). A setting,
   `ANONYMOUS_SPEND_PER_SESSION_OVERRIDE`, makes each anonymous session its own
   network for spend, with the same guards as `SESSION_MINT_CAP_OVERRIDE`: off by
   default, honoured only when `RUNTIME_ENVIRONMENT=local`, and the app refuses to
   start with it set anywhere else. The allowance still reports `shared_by_network`
   for an anonymous session. The e2e job sets it; the signed-in lane's server clears
   it, so that lane exercises the real per-network sharing in a browser.

## Rejected alternatives

- **Count both the session and the network** (block when either is over). The same
  daily figure twice; the network one always binds, so the session one adds nothing.
- **Key on the raw address.** Writes a visitor's address into rows nothing deletes.
- **Group IPv6 by /56 or /48 for spend.** Fewer allowances per IPv6 holder, but a
  different network from the one the session limit counts, and whole ISPs' customers
  would share; the session limit's /64 is kept (ADR-0132).
- **Move the last 24 hours of anonymous spend to the network keys at deploy.** A
  migration for one day of simulated spend (live execution is off).

## Consequences

- After this change, signing out no longer starts a fresh $0.40: the next anonymous
  session sees what the network has spent in the last 24 hours.
- Everyone behind one address — an office, a university, a mobile carrier's shared
  address — shares one $0.40 a day while not signed in. Signing in gives each person
  their own.
- The allowance shown to an anonymous visitor includes other people's spend on the same
  network (the total only, never which session or run).
- Known limits: an IPv6 holder with a /56 or /48 can use up to 256 or 65,536 /64s (the
  same limit ADR-0132 records); the in-memory running total ($0.50, no time window) now
  counts a network across days, as it already counts a signed-in account; at deploy each
  network starts once with a fresh allowance; rotating the server secret restarts every
  network's day.
- Allow-listed networks (W31) and invite links (W32) never touched spend, and still do
  not: their visitors share their network's allowance.
- How it is built: the routes read the key and the shared flag together
  (`auth.spend_meter_for`; `spend_key_for` returns the key alone); whether a session
  is anonymous is a second store read, made before the deletion check, because an
  older account's spend key can equal its own id (ADR-0136); the network key is
  derived in `session_store.network_spend_key` beside `account_id_for`; with the
  override on, the session's account id is folded into the hashed text.
- Calls taken by the session (the owner may overturn any of them): (i) the hash
  construction and its prefix; (ii) unidentifiable requests share one key; (iii) IPv6
  counted by /64; (iv) the wording that says the allowance is shared and offers sign-in;
  (v) no move of the last day's spend at deploy; (vi) the running-total rail is left as
  it is; (vii) the local-only test override of decision 7; (viii) on a database without the
  spend-key column, a signed-in account keeps its own id rather than being refused
  (decision 3); (ix) the network's spend total is shown to everyone on it who is not
  signed in; (x) `shared_by_network` is a required field of `daily_allowance`, also in
  the charge-time 402; (xi) a failed read of the account row refuses the run (503). The
  copy of (iv) is: "This allowance is shared by everyone on this network who is not
  signed in. Sign in to get your own $0.40 a day."; (xii) the words for a shared
  allowance after review: the block card says "Everyone on this network who is not
  signed in has used $X of the $0.40 they can spend in the last 24 hours" and "This
  network's recent runs", never "You have used" or "Your recent runs"; the server says
  "this network" instead of "the account"; a "Sign in for your own allowance" button
  in the cost card; and the composer footer adds "shared by everyone on your network
  while not signed in" for an anonymous page only.
- Known limits found by the browser review and left: on a phone the card's sign-in
  button opens just below the first screen; signing in reloads the page and loses the
  question just priced (as the top-bar sign-in already did); the late daily-cap
  refusal offers sign-in in words only; the block card names the shared group twice;
  the screen-reader announcement of the larger-than-a-day block does not say the
  allowance is shared. Found by the last check before release and left by choice (both
  review rounds were used): when the in-memory running total fires first on a run
  larger than the whole day, the block is the running-total one, and the card still
  offers sign-in, which cannot lift it (a signed-in account would get the daily-cap
  block). It costs nothing; the offer is only unhelpful.
