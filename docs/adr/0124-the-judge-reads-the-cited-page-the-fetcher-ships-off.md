# ADR-0124: The judge reads the cited page, not the model's memory of it — the fetcher, behind a default-off setting

## Status

Accepted — 2026-09-24. Code and tests, default OFF. **Authorises nothing**:
it flips no flag, opens no window, licenses no paid run, and with the
setting off (the shipped default, `fly.toml` unchanged) the product's
behaviour and every existing pin are byte-identical. The owner decided the
direction (2026-09-24, their words: *"JUdge should be able to verify the
sources then only will be able to judge properly."* and, to the session's
choice of the issue's Route B, *"I agree with your choice"*; CHG-012 D4).
The design below is the session's. The judge WIRING — handing fetched text
to the judge, the input reserve, the receipt row and the posture-keyed copy
— is the second pull request of this package. The session's expectation,
not a measurement, is that fetcher plus wiring in one pull request would be
four concerns and would not converge in two review rounds.

## Context

The judge is asked whether an answer asserts only what its evidence
supports, and it is shown titles and URLs (`build_judge_evidence`,
`evaluation.py`: `[n] title :: url`, at most 32 lines, title and URL each capped at 300 characters). Nothing in
`src/` opens a cited URL. The honest copy says so ("Sources are cited, but
aren't checked against their pages", ADR-0099).

**The package's first step is already answered in the tree.** The "free
capture" (does an `:online` annotation carry page content?) was measured on
2026-09-10: `sed -n 6,18p docs/analysis/2026-09-10-window-measurements.md`
prints ANSWERED — run 5a9c2d63, 4 of 4 searching calls with a nested
`url_citation` whose `content` is a string, 20 annotations, 40,479
characters, largest call 10,245; raw rows in
`docs/analysis/2026-09-10-telemetry-tokens.jsonl` (about 2,000 characters
per citation, all four default models). No completion was spent here.
Route B stands because that content is the excerpt the model's SEARCH tool
chose for the query, not the page, and inline-Markdown and Tavily sources
carry no excerpt at all. The repository holds no sample of passage text
(ADR-0104 records a shape, a count and a length), and whether the repaired
nested reader (PR #477) yields `annotation_usable_count > 0` on live traffic
is UNVERIFIED (newest telemetry row 2026-09-10; live execution is off).

**`credentialed_url.py` has the opposite policy.** It sends the operator's
key to OpenRouter safely, so it accepts loopback and link-local hosts. The
fetcher must refuse exactly those and carry no key. What is shared is the
rule that a redirect is never followed; here it holds by construction,
because the fetcher uses `http.client` directly, which never follows one.

The failure modes were listed before the code:
`docs/analysis/2026-09-24-447-source-fetch-failure-modes.md` (21 rows).

## Decision

**1. One stdlib module, `src/product_app/source_fetcher.py`.** No new
dependency (`bs4` and `lxml` are not in the venv); `html.parser` extracts
text; `http.client` makes the request, so no urllib opener, redirect handler
or proxy machinery is involved. `fetch_cited_pages(urls, ...)` returns one
`FetchedSource` row per distinct, non-blank URL it was given — fetched or
refused — so a caller can always say what was and was not fetched. Outcomes:
`fetched`, `unusable`, `refused_scheme`, `refused_host`, `refused_address`,
`refused_redirect`, `refused_content_type`, `too_large`, `timeout`,
`http_error`, `network_error`, `skipped_cap`.

**2. Address policy, the SSRF guard.** The host is resolved once; the fetch
is refused unless EVERY address is `is_global and not is_multicast and not
is_reserved`, with IPv4-mapped forms judged by the IPv4 address they carry,
and NAT64 (`64:ff9b::/96`, `64:ff9b:1::/48`) and site-local (`fec0::/10`)
refused. The connection classes `_PinnedHTTPConnection` and
`_PinnedHTTPSConnection` override `connect()` to dial the CLASSIFIED
address, not the name, while keeping the hostname for `Host` and for TLS SNI
and certificate verification (`ssl.create_default_context`). `http.client`
reads no proxy variables. Schemes are `http`/`https` by `urlsplit`; userinfo
and control characters are refused. Every 3xx is `refused_redirect`.

**3. No credential leaves.** The request carries `User-Agent`, `Accept`
and `Accept-Encoding: identity` only. Proof is at the wire: a loopback
recording server asserts the request arrived and that no header name or
value carries the OpenRouter, judge or Tavily key.

**4. Bytes and time.** The body is read in chunks with the cap on the
`read1` ARGUMENT and the loop (AGENTS 8b); `Content-Length` is a cheap
pre-check, never the bound; the content type is checked BEFORE the read
(`text/html`, `text/plain` only). Time has ONE budget per call, shared by
every page, enforced two ways: the name lookup runs in a worker thread
joined with the remaining time (`getaddrinfo` takes no timeout, and a slow
nameserver is attacker-controlled for any name it can get cited); and a
watchdog timer, armed before the request, shuts the socket when the budget
runs out. That bounds what a per-recv socket timeout cannot: dribbled status
lines and headers, endless `100 Continue` responses, chunk-size lines and
trailers. Over HTTPS the TLS socket is created without handshaking,
assigned, and only then handshaken, so the watchdog can shut it mid-handshake;
the watchdog is also checked once the request is sent. Each recv is also bounded by the per-read
timeout. Past the budget, remaining URLs are `skipped_cap`. Text is capped
per page; non-ASCII paths are percent-encoded.

**5. Settings, all default off or small**, in the shape of the peer flag:
`quorum_source_fetch_enabled = False`, `_timeout_seconds = 3.0` (per recv),
`_budget_seconds = 8.0` (total per call), `_max_bytes = 262144`,
`_max_pages = 8`, `_max_text_chars = 4000`; one validator refuses 0,
negative and NaN for every bound and a budget at or below the per-read
timeout. The flag is reported on `/status` (ADR-0013). Nothing reads the
fetcher until the wiring pull request gates it on
`judge_configured() and quorum_source_fetch_enabled`.

**6. What this pull request proves and does not.** It proves, over HTTP on
loopback with the suite's no-egress guard in force: the address predicate on
every listed literal address; the refusal of a name with any non-public
answer; that a refused address is never dialled; that the dial uses the
classified address; that no credential leaves; that no redirect is followed;
and the byte and time bounds against each hostile-server shape above. Over
HTTPS, with a throwaway certificate generated per test run and a real
loopback TLS server, it proves a verified fetch succeeds and that a slow
connect plus a deadline-straddling handshake plus dribbled headers is still
cut at the budget; and that a server not speaking TLS fails closed.
Resolver-level spellings such as `127.1` or `metadata.google.internal` are
not exercised (the suite cannot reach a resolver). It does not prove the judge grades better: that is the wiring,
and its first real measurement needs a live window the owner has not opened.

## Measurements

All on the `wp/447-source-fetcher` worktree at f2de08a plus this change;
loopback servers only, the suite's no-egress guard in force, no paid call.

| what | command | result |
|---|---|---|
| D4, the free capture | `sed -n 6,18p docs/analysis/2026-09-10-window-measurements.md` | ANSWERED on 2026-09-10: annotations carry page content (run 5a9c2d63, 4 of 4 searching calls, 40,479 characters) |
| RED before the code | `uv run pytest tests/unit/test_source_fetcher_guards.py tests/unit/test_source_fetcher_bounds.py -q --no-cov` | collection error: `ImportError: cannot import name 'source_fetcher' from 'product_app'`; the settings file: `16 failed` |
| GREEN | the three new test files | `83 passed` (the 21-mutation run below was measured before the two TLS tests were added, against 65) |
| mutation, by hand (cp aside, mutate, purge `__pycache__`, run the two fetcher test files — baseline `65 passed` — restore, `cmp`) | 21 mutations | 20 killed, 1 equivalent (below) |

The 21: the predicate refuses only loopback; `all()` over resolved answers
becomes `any()`; a 3xx is read; the HTTP connection dials the name; the read
argument is unbounded; the content type is unchecked; the per-host cap is
dropped; any scheme is accepted; a login shell counts as evidence; control
characters are accepted; userinfo is accepted; a compressed body is decoded;
the watchdog is never armed; a truncated head after the watchdog is read;
the lookup is unbounded; the path is not percent-encoded; site-local is
admitted; the budget is renewed per page; a trailing dot opens a new host
bucket; a per-read timeout is reported as a network error — all killed. The
`isclosed()` stop of the read loop is EQUIVALENT in this design: `read1` on
a closed response returns empty. The IPv4-mapped unwrap is not in the list:
Python 3.12.13 already judges `::ffff:` addresses by the embedded IPv4
(`::ffff:127.0.0.1` is_global False, `::ffff:93.184.216.34` True); it is kept
because `requires-python` admits interpreters not measured here.

**Defects found by review round 1 and fixed here** (each a loopback
reproduction by the reviewer, now a test):

- Every page served with `Content-Length` on a closing connection came back
  `network_error`: the first draft re-applied a socket timeout on the socket
  http.client had just closed. Test: the closing-connection read.
- The budget did not bound the whole fetch: a dribbled header block, endless
  `100 Continue` responses and an endless chunked trailer each held one fetch
  6 s (20 s once the server's own stop was raised) against a 1.0 s budget;
  a slow lookup held it 3.0 s and reported `skipped_cap`. Fixed by the
  watchdog and the bounded lookup. Tests: the three hostile servers end in
  `timeout` under 1.6 s; the slow lookup under 1.5 s.
- Also fixed: non-ASCII paths, an unusable charset label, site-local IPv6,
  trailing-dot host keys.
- Review round 2: over HTTPS the handshake ran inside `wrap_socket()`,
  which detaches the raw socket before the TLS socket is assigned, so a
  deadline passing mid-handshake left the watchdog nothing to shut and a
  dribbled header block ran on (the reviewer measured 23.5 s against a
  3.0 s budget, with a real certificate). The TLS socket is now assigned
  before the handshake, and the watchdog is checked after the request.
  Test: a real loopback TLS server with a slow connect, a handshake
  straddling the deadline and dribbled headers ends in `timeout` under
  4.0 s against a 3.0 s budget. With both guards removed it measured 18.7 s
  and failed; each guard alone passes it, so they are a redundant pair,
  proven together.

## Consequences

- The copy that says sources are not checked stays TRUE on every deployment
  until the wiring lands and follows one posture predicate (ADR-0116's
  pattern); it is not rewritten here.
- The judge input reserve, the `source_fetch` receipt row, the threat-model
  extension for page text leaving the deployment to the judge provider, the
  memoised-failure decision and the robots policy belong to the wiring
  record; the failure-mode page names each.
- The transport-guard scan (`test_credential_transport_guard.py`) inspects
  urllib callers only; it does not see `http.client`, so it neither covers
  nor flags the fetcher. The fetcher's own tests are its guard; the scan's
  allowed set is unchanged.
- The fetcher's module constants (the caps, the user agent, the readable
  types) are asserted by the behaviour tests above, not by literal pins; the
  module is not in the risk-constant registry.

## Rejected alternatives

- **Route A alone (use the annotation excerpt).** It is what the model's
  search tool chose for the query, present only on the annotations path, and
  cannot verify a claim outside the excerpt. It remains a cheaper INPUT to the
  same judge in the wiring, never a substitute (CHG-012 D4).
- **Reuse `credentialed_url.is_credential_safe` as the guard.** It accepts
  loopback and `169.254.169.254` by design; the fetcher needs the inverse.
- **A hostname denylist.** Passes `127.1`, `2130706433`, `::ffff:127.0.0.1`,
  private DNS answers and NAT64 spellings (measured on the venv).
- **`requests`/`httpx`/`bs4`.** New dependencies for a surface whose whole
  point is a small, auditable egress path; the stdlib covers it.
- **Ship the wiring in the same pull request.** Four concerns on top of the
  fetcher; the package text itself allows the split.

## Related

#447, CHG-012 D4, ADR-0099 (the honest copy), ADR-0084 and ADR-0104 (the
annotation capture), ADR-0027 and #268 (the judge input bound), T-014 (new),
`docs/analysis/2026-09-24-447-source-fetch-failure-modes.md`.
