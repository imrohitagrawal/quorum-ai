# ADR-0134: An invite link that lifts the daily session cap

## Status

Accepted — 2026-09-26, board row W32. The product owner decided an invite
link on 2026-09-25 (CHG-022, transcript `efe4f2fc`). Their words:
*"Also, I would like you to include the one limit to know and the invite
link that you have suggested"* (13:47:27Z) and *"Invite link should not be
later. I expect it should be planned and included."* (13:48:26Z). What they
approved, CHG-022 item (4): a secret link the owner sends to a firm that
lifts the session limit for whoever opens it, from any network, until an end
date. CHG-022 left the detailed design to the building session, failure
modes first.

So everything below beyond item (4) is the session's design, and these
choices are **PROPOSED — AWAITING OWNER**, built at their safe default:

- a link works at most **90 days** ahead;
- each link opens at most **12 new sessions** in a rolling 24 hours (so
  12 x `DAILY_CAP_USD` 0.40 = 4.80 stays under the site-wide 5.00 ceiling;
  the 50 first proposed let one leaked link use up the whole site's day,
  measured in review: 50 x 0.40 = 20.00);
- a link lifts the **daily** new-session cap only, not the 10-a-minute limit;
- only the operator mints links, with a local command; there is no web
  endpoint that makes one;
- one link is revoked by listing its id; rotating the key revokes all;
- the signing key needs at least **32 characters**.

## Context

W30 (ADR-0132) counts each visitor's address: 2 new sessions a day. W31
(ADR-0133) lifts that for a listed network, but CHG-022 item (3), which the
owner asked to keep in view, says an address list does not help someone at
home or on mobile data. The link is for them. The failure modes were listed
first: `docs/analysis/2026-09-26-w32-invite-link-failure-modes.md`.

Measured before designing: uvicorn's access log prints the request line
with its query string (`GET /health?invite=SECRET123` appeared verbatim in a
local run). A token in a query string would reach `fly logs`.

## Decision

1. **The link:** `https://<host>/ui/invite#v1.<id>.<until>.<signature>`. The
   token is in the fragment, which a browser never sends in a request line
   or a `Referer`. `id` is 12 random hex digits, `until` the last day the
   link works (UTC, inclusive), `signature` an HMAC-SHA256 of
   `v1.<id>.<until>` under `INVITE_LINK_SIGNING_KEY`, compared in constant
   time.
2. **Accepting it:** `/ui/invite` is a static page (no-store). Its script
   (`static/invite.js`) first removes the fragment from the address bar,
   then POSTs the token as JSON to `/v1/invite` (behind the per-minute
   limiter), then says what happened and offers a link to `/ui`. A valid
   token becomes an HttpOnly, SameSite=Lax cookie (Secure wherever session
   cookies are), lasting to the end of `until`. Forged, expired, revoked and
   malformed tokens get one identical 400. With no key set, a well-formed POST
   answers 404 and the page says links are not enabled.
3. **What it lifts:** on `/v1/session` and `/ui`, a valid invite cookie moves
   the daily new-session cap from the visitor's address to the link: the
   session is recorded under `invite:<id>` with a cap of 12, using the same
   atomic durable counter as the address cap (`try_record_session_mint`).
   The per-minute limit still applies per address on `/v1/session` and
   `/v1/invite`; `/ui` has no per-minute limiter, so a link's `/ui` mints
   are bounded by its daily cap alone. A link over its cap answers 429
   `INVITE_DAILY_LIMIT` on `/v1/session`, and `/ui` renders a page that
   names the link, not the visitor's network. An allow-listed visitor (W31) is exempt
   from both limits and does not use the link's cap. Spend limits are
   untouched: they count accounts and the site.
4. **Minting:** `pbpaste | PYTHONPATH=src uv run python -m
   product_app.invite_links mint --until YYYY-MM-DD --base-url https://host`
   reads the key from standard input and prints the link and its id.
5. **Revoking:** list ids, comma-separated, in `INVITE_LINK_REVOKED_IDS`;
   the cookie is checked on every request, so a revoked link stops at once.
   A malformed id or a short key stops the app at startup.
6. **Counting:** `/status.invite_links` reports whether links are on, the
   number of revoked ids, and session requests (`/v1/session`, `/ui`) that
   carried a valid invite since
   start. Never an id or a token.

## Rejected alternatives

- **The token in a query string** (`/ui?invite=...`): measured to reach the
  access log.
- **Unlimited uses per link:** a leaked link would mint without bound; 12 a
  day is PROPOSED.
- **Lifting the per-minute limit too:** it was not what refused the owner's
  testers, and it bounds a leaked link's request rate.
- **A web page to mint links:** it would need its own authentication and
  becomes the thing to attack; the operator already has the key locally.
- **Binding a link to one browser:** a firm shares one link among several
  people; the per-link cap is the bound instead.

## Consequences

- A tester with the link opens sessions beyond their address's 2 a day, up
  to the link's 12 across everyone using it.
- A leaked link is bounded by its end date, its revocation and its 12 a day,
  which cannot use up the site-wide daily ceiling on its own (pinned by
  `test_one_leaked_link_cannot_use_up_the_sites_daily_ceiling`).
  The spend limits, per account and site-wide, still apply to every run.
- The operator keeps the signing key (a Fly secret) and must have it locally
  to mint. Losing it means rotating it, which revokes every link.
- The cookie outlives a session. Signing out does not remove the invite.
- Pinned by `tests/unit/test_invite_links.py`,
  `tests/security/test_invite_link.py` and
  `e2e/tests/invite/invite-link.spec.ts`.
