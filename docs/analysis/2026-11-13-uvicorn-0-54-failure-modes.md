# Failure modes: moving uvicorn from 0.49.0 to 0.54.0

Written 2026-11-13, before review, on the branch that moves the lock.

Production runs uvicorn from `uv.lock` (ADR-0164) with the arguments in the `Dockerfile`'s
`CMD`: one worker, `--no-proxy-headers`, `--timeout-keep-alive 30` and
`--timeout-graceful-shutdown 30`. The visitor's address is worked out by the app, not by
uvicorn (ADR-0132), and it keys the session rate limit, the daily session cap and the anonymous
spend shared per network (ADR-0144). Listed from those records before review:

1. **uvicorn trusts a forwarded address again.** If a release changes what `--no-proxy-headers`
   does, or adds another path that rewrites `scope["client"]` from `X-Forwarded-For` or
   `Forwarded`, a visitor could choose the address their limits are counted under.
2. **A flag in the `CMD` is renamed or removed.** The container would fail to start, and the
   deploy's health check is the first place it would show.
3. **A timeout's meaning changes.** Keep-alive or graceful-shutdown timing that changes could
   cut a long run's stream or drop requests during a deploy.
4. **Request parsing changes.** A different limit on header size, a changed HTTP parser default,
   or a changed handling of a malformed request could turn requests the app relies on into
   errors, or let through requests it refused. ADR-0171 (the request body limit) relies on three
   behaviours measured on 0.49.0: after the app answers 413, uvicorn reads and discards the rest
   of the body; it falls back to the h11 parser when httptools cannot be imported; and it
   answers 400 for a `Content-Length` that is not digits, before the app runs.
5. **A dependency of `uvicorn[standard]` moves with it.** The lock change could pull other
   runtime packages along.
6. **The tests see the arguments, not the behaviour.** A test that reads the `Dockerfile`'s
   arguments passes even if uvicorn ignores one of them; the address the app sees must be
   checked by sending a request to the built image.

## What the checks found

Each item was checked by reading the two versions' source side by side and by running the app
on each with the `Dockerfile`'s flags.

- Item 1 did not happen. `--no-proxy-headers` still means the proxy layer is never added; the
  only proxy change is that the default trusted list for `FORWARDED_ALLOW_IPS` gained `::1`,
  which matters only when that layer is on. Requests from an untrusted peer carrying
  `X-Forwarded-For`, `Forwarded`, `Fly-Client-IP` or `X-Real-IP` were all counted under the
  peer's own address on both versions.
- Item 2 did not happen. Every flag in the `CMD` exists in 0.54.0; the built image starts and
  `/ready` answers 200.
- Item 3: keep-alive handling changed in small ways (h11 stops its keep-alive timer sooner
  between back-to-back requests; httptools now reads every value of the app's `Connection`
  response header, and asks its parser whether the request allows keep-alive).
  Both timeout flags still exist under the same names; no long run was streamed across a
  deploy to compare timing.
- Item 4 did not happen. The three ADR-0171 behaviours hold on 0.54.0 as on 0.49.0, checked by
  request (413 then a second request on the same connection; a blocked httptools import; four
  malformed `Content-Length` values, through the httptools parser).
- Item 5: only a Windows-only dependency left uvicorn's list, and the lower bound on
  `websockets` rose to 13.0, which the lock already satisfies.
- Item 6: the existing tests read the arguments; the address check above was made by request.
- One change this list did not name: when uvicorn cannot load the app, it now exits with
  status 3 (`STARTUP_FAILURE` in `uvicorn/config.py`) where 0.49.0 exited with 1.
