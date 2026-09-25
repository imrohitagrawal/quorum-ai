# W30 — counting the visitor, not the app: failure modes first

Written before the code (AGENTS rule 16e), for board row W30 and CHG-022
item (1). The two limits concerned are the per-network session limits: the
daily new-session cap (`SESSION_MINT_CAP_PER_IP`, 2 in 24 hours) and the
per-minute session limit (10 a minute, `query_runs._InMemoryIpRateLimiter.CAPACITY`). Neither value moves. What moves is
WHOSE address they count.

## What was measured (2026-09-25, PR #513's probe, production)

Five requests to `/status` from this machine, each carrying the probe header;
Fly's log saved at once to the session scratchpad. The probe logged kinds,
never addresses.

| Request | `Fly-Client-IP` arrived as | `X-Forwarded-For` arrived as | uvicorn resolved the client to |
|---|---|---|---|
| IPv4, no forged headers | the visitor | visitor, app ingress | app ingress |
| IPv4, forged `Fly-Client-IP` and `X-Forwarded-For` (documentation range) | the visitor, one header | forged, visitor, app ingress | app ingress |
| IPv6, no forged headers | the visitor | visitor, app ingress | app ingress |
| IPv6, forged both | the visitor, one header | forged, visitor, app ingress | app ingress |
| IPv4 via `quorum-ai.fly.dev` | the visitor | visitor, app ingress | app ingress |

So: Fly's proxy **replaces** a client's `Fly-Client-IP` with the address it
accepted the connection from, and **keeps** a client's `X-Forwarded-For`,
appending the visitor and then the app's own ingress address. uvicorn's
`--proxy-headers` takes the rightmost untrusted entry, which is the app's own
address. That is the fault.

## Failure modes, and what the design does about each

1. **A visitor forges the header to get a fresh allowance per request.**
   Through Fly: measured above, a forged `Fly-Client-IP` is replaced, so
   it never reaches the app. Forging `X-Forwarded-For` works (it is kept),
   so the design never reads `X-Forwarded-For`.
2. **A client connects to the machine directly, not through Fly's proxy.**
   The header is believed only when the connecting peer is inside Fly's
   private ranges (`172.16.0.0/12`, `fdaa::/16`, the ranges the Dockerfile
   already trusted; #58 measured the machine's own routes as
   172.19.4.128-135, its health-check peer as 172.19.4.129 and its private
   network address as fdaa:87:4c93:… ; that the public proxy connects from
   inside these ranges is inferred, and checked after deploy). Any other peer is counted as itself and
   its header is ignored. Loopback is NOT trusted: nothing in production
   connects from loopback, and trusting it would let any local process
   choose its own key.
3. **Another machine in the same Fly organisation sends the header over the
   private network.** It is inside `fdaa::/16`, so it would be believed. Only
   the owner's own applications can do this; recorded, not defended.
4. **The trusted peer sends no header, an unparseable one, or more than
   one.** Counted as the peer itself. For Fly's proxy that means one shared
   bucket per proxy address, which is today's behaviour: the failure is back to too strict,
   never to open. Health checks carry no header and never call the session
   routes.
5. **An IPv6 visitor rotates addresses.** A home IPv6 connection commonly
   holds at least a /64 (2^64 addresses), and privacy extensions rotate the
   address on their own. Counting single IPv6 addresses would let one
   visitor mint sessions without limit. An IPv6 visitor is therefore counted
   by their /64 network. An IPv4-mapped IPv6 address counts as the IPv4
   address.
6. **Many people share one IPv4 address** (carrier-grade NAT, an office).
   They share an allowance. This is the per-address design CHG-022 approved;
   the allow-list (W31) and the invite link (W32) are the answer for a firm.
7. **Keys already stored.** The daily cap's rows carry the address they were
   counted under. Rows written before this change carry the app's ingress
   address, which no visitor will present again, so every visitor starts
   with a full allowance of 2. The old rows leave the 24-hour window within
   a day; nothing is migrated. Nothing prunes that table, so new rows keep
   the visitor's address (or /64) with no end date.
8. **What reaches logs and Sentry.** uvicorn's access log stops showing the
   app's ingress address and shows Fly's private proxy address instead (no
   visitor address either way). The global-ceiling Sentry alert (#100 §2.8)
   was designed to carry the visitor's address and until now carried the
   app's; it now carries the visitor's address, as that design intended. It fires only when a run is degraded by the
   site-wide ceiling.
9. **The request scheme.** uvicorn's `--proxy-headers` also rewrote the
   scheme from `X-Forwarded-Proto`, and one piece of code reads it:
   `google_signin.on_sign_in_host` compares the request's scheme, host and
   port with the redirect address. Turning uvicorn's handling off without a
   replacement would make that compare `http` against `https`. So the new
   middleware carries the scheme over as well, from the same trusted peers
   only, and only the values `http` and `https`. (A first draft of this page
   said nothing read the scheme; `git grep request.url` found this one.)
10. **Fly changes its headers later.** The code falls back to the peer
    (mode 4), so the limits become too strict, never too loose. The probe's
    finding is dated here so a later reader knows what was measured.

## Tests promised

- Two different visitors behind Fly's proxy each get their own daily
  allowance of 2 (the owner's case).
- A forged header from a peer outside Fly's ranges is ignored.
- A trusted peer without the header is counted as itself.
- Two addresses in one IPv6 /64 share an allowance; two /64s do not.
- A trusted peer's `X-Forwarded-Proto: https` reaches the sign-in host check;
  an untrusted peer's does not.
