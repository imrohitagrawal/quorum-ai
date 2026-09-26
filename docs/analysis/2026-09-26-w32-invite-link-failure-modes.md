# W32 — the invite link: failure modes first

Written before the code (AGENTS rule 16e), for board row W32 and CHG-022
item (4). The owner's words (2026-09-25): *"Also, I would like you to
include the one limit to know and the invite link that you have suggested"*
(13:47:27Z); *"Invite link should not be later. I expect it should be
planned and included."* (13:48:26Z). What they approved, CHG-022 item (4):
*a secret link the owner sends to a firm that lifts the session limit for
whoever opens it, from any network, until an end date.* CHG-022 leaves the
detailed design (who can mint one, how it is revoked, whether uses are
capped) to the building session, failure modes first. Every choice below
that is not in item (4) is **PROPOSED — AWAITING OWNER**, built at its safe
default.

## Measured before designing

- uvicorn's access log prints the request line WITH its query string:
  `GET /health?invite=SECRET123` appeared verbatim in a local run
  (2026-09-26). A secret in a query string reaches `fly logs`.
- A URL fragment (`#...`) is never sent in the request line or in
  `Referer`; the browser keeps it.

## Failure modes, and the design's answer to each

1. **The secret reaches a log or a `Referer`.** The link is
   `https://<host>/ui/invite#<token>`. The page reads the fragment in the
   browser, POSTs the token in a request body, removes the fragment from the
   address bar, and moves on to `/ui`. The server logs `POST /v1/invite`
   with no token. The token is never logged by the app.
2. **A leaked link.** Anyone holding it skips the per-network session
   limits. Bounded three ways: it expires on its end date; it can be
   revoked; and each link has its own daily cap on new sessions
   (PROPOSED: 50 a day, per link, durable), so a leaked link cannot mint
   without limit. A spend limit is never lifted.
3. **Revocation.** Each link has an id, printed when it is minted. Listing
   the id in the `INVITE_LINK_REVOKED_IDS` setting revokes that link
   (PROPOSED); a malformed id there stops the app at startup, like a
   malformed allow-list. Rotating `INVITE_LINK_SIGNING_KEY` revokes every
   link at once. A revoked or expired link already held in a cookie stops
   working on the next session request, because the cookie is checked
   every time.
4. **Expiry.** The end date is inside the signed token and checked on every
   use, through the end of that day in UTC. At most 90 days ahead
   (PROPOSED: shorter than the allow-list's 366, because a link travels).
5. **Who can mint one.** Operator only. There is no web endpoint that mints
   a link: the operator runs a local command that reads the signing key
   from standard input (never an argument or shell history) and prints the
   link and its id. No visitor, signed in or not, can create one.
6. **Forgery.** The token is an HMAC-SHA256 over its version, id and end
   date with the signing key (at least 32 characters; a shorter key stops
   the app at startup). A token that does not verify is
   refused the same way as an expired or revoked one, compared in constant
   time. No detail of why is returned to the browser.
7. **The signing key leaks.** Anyone could mint links. Rotating the key
   revokes all; the key is a Fly secret and never logged.
8. **Replay across browsers.** The link is meant to be shared within a
   firm, so it is not bound to one browser. The per-link daily cap is the
   bound.
9. **What the link lifts.** The browser that opened it holds an HttpOnly,
   SameSite=Lax cookie (Secure wherever session cookies are) carrying the
   token. On `/v1/session` and `/ui`, a valid cookie moves the daily
   new-session cap from the visitor's address to the link: the session
   counts against the link's own daily cap instead of the address's 2.
   The per-minute limit (10 a minute per address) still applies
   (PROPOSED): it was not what refused the owner's testers, and it bounds
   a leaked link's request rate. Nothing else reads the cookie;
   `DAILY_CAP_USD` and `GLOBAL_DAILY_CEILING_USD` count accounts and the
   site. An allow-listed visitor (W31) is exempt from both limits as
   before.
10. **A GET changes state.** Opening the link is a GET of a static page; the
    state change is the page's POST (ADR-0131: a GET must survive being
    fetched twice by something that runs no page code).
11. **Off by default.** With no signing key set, the invite page says links
    are not enabled and the POST answers 404.
12. **Counting.** `/status` shows whether invite links are enabled, the
    number of revoked ids and the session requests that carried a valid
    invite since start, never an id or a token.
13. **Cross-site planting.** Another site could try to make a visitor's
    browser accept an invite cookie. The endpoint takes only a JSON body, so
    a cross-site form cannot send it; and a planted cookie would only move
    that visitor's sessions onto someone else's link cap.
14. **Brute force.** Guessing a valid 256-bit signature is not feasible;
    the endpoint is still behind the per-minute limiter, like
    `/v1/session`.
