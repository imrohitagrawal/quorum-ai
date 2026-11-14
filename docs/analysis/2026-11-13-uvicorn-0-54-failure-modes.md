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
   errors, or let through requests it refused.
5. **A dependency of `uvicorn[standard]` moves with it.** The lock change could pull other
   runtime packages along.
6. **The tests see the arguments, not the behaviour.** A test that reads the `Dockerfile`'s
   arguments passes even if uvicorn ignores one of them; the address the app sees must be
   checked by sending a request to the built image.
