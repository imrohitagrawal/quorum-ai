# ADR-0132: The session limits count the visitor, not the app

## Status

Accepted — 2026-09-25, board row W30. The product owner approved the address
fix on 2026-09-25 as item (1) of the session's proposal (CHG-022; their
words, 13:47:58Z: *"I have said yes, so it should not be mentioned as
awaiting owner. Everything is approved here."*). That item reads: take the
visitor's address from what Fly's proxy forwards, only from Fly's private
proxy ranges, after measuring what Fly actually sends; the cap stays 2. The
owner confirmed the queue order at 16:02:06Z (*"The order looks good."*).
Everything else below is the session's design: which header, trusting no
loopback, counting IPv6 by /64, carrying the scheme over, failing closed.

## Context

Two per-network limits guard session creation: the daily new-session cap
(`SESSION_MINT_CAP_PER_IP = 2` in 24 hours, the dollar-drain guard from #100)
and the per-minute session limit (10 a minute). Both keyed on
`request.client.host`, which uvicorn's `--proxy-headers` derived from
`X-Forwarded-For` for peers in Fly's private ranges (#58).

On 2026-09-25 the owner could not retest #511: "This network has reached its
session limit". Production had logged every visitor under the app's own
ingress addresses. Measured with PR #513's probe, on five requests to
production (IPv4, IPv6, forged headers, both host names), logged as kinds and
never as addresses:

| Header | What arrived |
|---|---|
| `Fly-Client-IP` | always the visitor; a client's forged value was **replaced** |
| `X-Forwarded-For` | a client's forged value **kept**, then the visitor, then the app's own address |
| uvicorn's resolved client | the app's own address, every time |

uvicorn takes the rightmost `X-Forwarded-For` entry not in its trusted
ranges, and Fly puts the app's public address there. So every visitor on an
address family shared one allowance of 2 a day.

The failure modes were listed before the code:
`docs/analysis/2026-09-25-w30-visitor-address-failure-modes.md`.

## Decision

1. uvicorn's proxy handling is off (`--no-proxy-headers`; its default is on).
2. `auth.VisitorAddressMiddleware`, the last `add_middleware` layer (only the
   security-headers function, which never reads the client, wraps it), replaces the client
   address with `Fly-Client-IP` only when the connecting peer is inside
   `auth.TRUSTED_PROXY_NETWORKS` (`172.16.0.0/12`, `fdaa::/16`, the ranges #58
   measured). Loopback is not trusted. An absent, unparseable or repeated
   header leaves the peer as the client. `X-Forwarded-For` is never read.
3. The same middleware carries the scheme over from `X-Forwarded-Proto`
   (`http` or `https` only), from the same peers, because
   `google_signin.on_sign_in_host` compares scheme, host and port.
4. Both limits count `auth.client_ip_of(request)`: the visitor's address, an
   IPv6 visitor's /64 network (`auth.IPV6_LIMIT_PREFIX = 64`), an
   IPv4-mapped IPv6 address as its IPv4 address.
5. No limit value moves. The daily cap stays 2 and the per-minute limit 10.

## Rejected alternatives

- **Keep uvicorn's handling and add the app's ingress addresses to its
  trusted list.** uvicorn would then take the next entry left, the visitor.
  But a trusted list containing a public address means any client that can
  reach the app from that address is believed, and the ingress addresses are
  Fly's to change. Rejected: it trusts by public address.
- **Read the second-from-right `X-Forwarded-For` entry.** Correct today, but
  it depends on Fly adding exactly one entry, and it reads a header Fly keeps
  from the client. `Fly-Client-IP` is replaced by the proxy, which the probe
  measured.
- **Count IPv6 per address.** A home IPv6 connection commonly holds a /64 (or
  more) and rotates
  through it, so one visitor could mint sessions without limit.
- **Fail open on an absent header** (skip the limit). Fails the dollar-drain
  guard; failing to the peer is today's too-strict behaviour instead.

## Consequences

- Each visitor now has their own allowance of 2 a day. People behind one
  IPv4 address (an office, a mobile carrier) still share one; that is the
  per-address design CHG-022 item (1) keeps ("the cap stays 2"), and the
  allow-list (W31) and the invite link (W32) are the answer for a firm.
- The /64 is a floor, not a full answer (the session's measurement, in
  review): one holder of a /56 gets 256 allowances and of a /48 65,536, a
  6to4 address counts separately from its IPv4, and a dual-stack visitor has
  one allowance per address family. What bounds spend there is unchanged:
  the per-account `DAILY_CAP_USD` and the site-wide `GLOBAL_DAILY_CEILING_USD`.
  Counting by a wider prefix, or an extra cap per /48, would change a pinned
  constant and is not decided here.
- Old cap rows carry the app's ingress address and match no visitor; they
  leave the 24-hour window within a day. Every visitor starts with a full
  allowance. Nothing prunes that table (`feedback_store.py`), so from now on
  each new-session row keeps the visitor's address (or /64) with no end date,
  where it kept the app's address before.
- The per-minute limiter now forgets idle visitors: at most once a minute it
  drops every entry idle longer than `STALE_BUCKET_SECONDS`. Review measured
  that without this a sweep of one /48 left 65,536 entries (about 11.5 MB)
  held for the life of the process. A dropped entry had already refilled, so
  dropping it grants nothing.
- `TRUSTED_PROXY_NETWORKS` is correct for Fly only. Under the README's
  `docker compose up`, a local browser arrives from the Docker bridge gateway
  (review measured 172.20.0.1, inside 172.16.0.0/12), so a forged
  `Fly-Client-IP` is believed there. Any other host must not put the app
  behind a hop inside those ranges without revisiting this.
- If Fly's proxy connects from more than one address, the no-header fallback
  is one allowance per proxy address, not one in total.
- uvicorn's access log shows Fly's private proxy address instead of the app's
  ingress address; neither is the visitor.
- The global-ceiling Sentry alert (#100 §2.8) reads `request.client.host`
  unchanged, so it now carries the visitor's address where it carried the
  app's; that alert was designed to carry the visitor's.
- Another machine in the owner's Fly organisation can name any visitor over
  the private network. Recorded, not defended.
- If Fly stops sending `Fly-Client-IP`, every visitor falls back to one shared
  allowance again (too strict, never open).
- Pinned: `tests/security/test_trusted_proxy_ips.py` (the owner's case, two
  visitors behind one proxy peer each getting 2; forgery; loopback; the /64;
  the scheme; the Dockerfile flag) and bucket A of
  `tests/unit/test_risk_constant_pins.py` for both constants.
