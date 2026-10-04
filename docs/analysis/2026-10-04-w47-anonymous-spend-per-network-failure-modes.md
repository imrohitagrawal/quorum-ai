# W47 — anonymous spend counted per network: failure modes before the code

Written 2026-10-04 before the change (AGENTS.md rule 16e: money code). Board row W47.
Decision: CHG-027 (a), the owner's words: *"Anonymous spend: count it per network — all
anonymous sessions on one network share one $0.40 a day; signed-in accounts keep their
own $0.40. Its own work item after W37, failure modes and an ADR first."* It answers the
owner question ADR-0141 recorded: after signing out, the next anonymous session starts
with a fresh $0.40. Design: ADR-0144.

## Mechanism today (read on `9386fee`)

- An anonymous session's spend key is its own random account id (`auth.issue_session`;
  `SessionStore.spend_key_for` returns the id unchanged when no account row exists). A
  signed-in account's key is a keyed hash of its Google subject (ADR-0136).
- `auth.spend_key_for(session)` takes no request, so it cannot see the network. The
  estimate and create routes (`query_runs.py`) call it once each; create stores the key
  on the run, and every later charge, void and reconcile uses the stored key.
- The rails that read the key: the 24-hour daily cap ($0.40) at estimate and, atomically
  under one lock, at charge time (`FeedbackStore.try_record_cost_charge`); the
  in-memory running total ($0.50, counted over the last 1,024 cost events in the
  process, no time window); and the allowance figure and block reason on the estimate
  (ADR-0141). The deployment-wide $5.00 ceiling has no key.
- The network: `auth.client_ip_of(request)` gives the IPv4 address, or an IPv6 address's
  /64, taken from what Fly's proxy forwards (W30); a client that is not an address is its
  own key (the test client's `"testclient"`); no client is `None`. The per-network
  session limits (2 new anonymous sessions a day, ADR-0132) count on it, and store the
  raw key in each `session_minted` row's payload with no end date.
- Pinned today: `tests/integration/test_block_reason_and_daily_allowance.py::
  test_after_sign_out_the_anonymous_allowance_is_fresh_and_names_nothing_of_the_account`
  asserts the fresh $0.40 after sign-out; `test_spend_key.py` asserts an anonymous key is
  the session's id.

## Failure modes and the design answer

| # | Failure | Harm | Answer |
|---|---|---|---|
| 1 | Sign out, or let an anonymous session expire, and the next anonymous session starts with $0.40 again. | A signed-in person can spend less in a day than someone who signs out (ADR-0141); the daily cap is per browser session, not per person. | An anonymous session's spend key is derived from its network; every anonymous session on that network shares it. |
| 2 | The network address is stored on every cost-ledger row, which nothing deletes. | A visitor's address kept forever, in a table `docs/48` does not list for it. | The key is a one-way keyed hash of the network (the server secret, a W47-only prefix), turned into a UUID like the signed-in key. No address is written anywhere new. `docs/48` gets a row. A run degraded at the global ceiling already sent the visitor's address to Sentry; that event now carries the network key beside it (recorded in `docs/48`). |
| 3 | The network cannot be identified (no client; a non-address host). | Either every such visitor gets a fresh allowance per session (the bug again), or a crash. | Fail closed: every unidentifiable request shares one key. Production always has an address behind Fly's proxy (W30). |
| 4 | Signed-in spend is added to the network's anonymous allowance, or the network's to the account. | Against the owner's words: accounts keep their own $0.40. | Signed-in keys are unchanged; the network key is used only for a session with no account. |
| 5 | Many people behind one address (an office, a university, a mobile carrier's shared address) share one $0.40. | One heavy visitor uses the day for everyone else on that address. | The consequence of the decision. The page says the allowance is shared by everyone on this network who is not signed in, and that signing in gives one's own. Recorded in ADR-0144. |
| 6 | An IPv6 visitor holding a /56 or /48 moves between /64s. | Up to 256 (a /56) or 65,536 (a /48) allowances. | Known limit, the same one ADR-0132 records for the session limit; the network is counted the same way as there. |
| 7 | The allowance figure shows a stranger's spend on a shared network. | Someone sees that others on the network spent $0.31 today. | Only the network's total and remainder are shown, never which session or run; recorded. |
| 8 | Two anonymous sessions on one network run at the same moment. | Both pass the estimate and together exceed $0.40. | The charge-time check reads and writes under one store lock (`try_record_cost_charge`); a test runs two concurrent charges on one network key. |
| 9 | The network changes between estimate and create, or during a run (Wi-Fi to mobile). | A run charged to one key and voided or reconciled under another. | The key is read once at create and stored on the run (unchanged); the estimate may show the other network's allowance, and create re-checks. |
| 10 | The in-memory running total ($0.50, no time window) now counts a whole network. | A network that spent $0.35 yesterday can be refused today until the process restarts or 1,024 newer events push its events out. | The same behaviour a signed-in account has today (one key across days); recorded as a known limit, as ADR-0141 did, not redesigned here. |
| 11 | At deploy, anonymous spend from the last 24 hours sits under session ids, not network keys. | Each network gets a fresh allowance once, at the deploy. | Recorded; not worth a migration (live execution is off; simulated spend only). |
| 12 | Allow-listed networks (W31) and invite links (W32). | Their visitors might be assumed to get an allowance each. | Neither touches spend (CHG-022): an allow-listed network or an invite visitor's network shares one allowance like any other. The invite-link comment that multiplies 12 sessions by $0.40 is corrected. |
| 13 | The server secret is rotated. | Every network's day restarts (as for signed-in accounts). | Recorded. |
| 14 | A sign-in-only session (a network that used its 2 anonymous sessions, ADR-0139). | — | Already refused before any key is read (unchanged). |
| 15 | The test client's address is `"testclient"` for every request. | Every anonymous test shares one key, so tests that expect a fresh allowance per session would interfere. | Expected: a test that needs two networks sends them through the trusted-proxy header the W30 tests use; per-test state is reset by the existing fixture. |
| 16 | The legacy `X-Account-Id` path (tests and development only). | — | Unchanged: its key stays the header's id. |
