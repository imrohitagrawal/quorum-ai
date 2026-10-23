# ADR-0177: Another site may open the page, but cannot load it hidden or ask for a session

## Status

Accepted — 2026-10-23, board row W88. The owner's decisions it builds on are CHG-063 (b) (no
`Sec-Fetch-Site`: the `Origin` header decides; neither header: allow), CHG-067 (from another site
`/ui` may only be opened as a page; `/v1/session` is refused from any other site; page loads that
never count are a later row, W106) and CHG-071 (the second-tab token effect is fixed by its own
row, W105). CHG-060 holds the detail back from the public documents until the fix ships; this
pull request, which carries the fix, restores it. **Everything else below is the session's
design**, and the choices the owner was not asked about are marked "(the session's choice)".

The failure modes were listed before any code and are published with the fix in
`docs/analysis/2026-10-18-w88-cross-site-session-loads-failure-modes.md` (F1 to F27, and F28 added by review round 1; attacks A1 to
A4). Codex reviewed the plan three times before any code (ADR-0168, decision 7); its reviews are
kept outside the repository and none has a committed record. Round 1 found the second-tab token
effect (Known limits); round 2 found a port the e2e bounce could not use, a counter test that could
not fail, and two wrong line citations, all three fixed in the plan; round 3 found no defect.

## Context

`GET /ui` and `GET /v1/session` both open or renew a browser session. A new session counts against
the network's daily allowance, `SESSION_MINT_CAP_PER_IP = 2` (`auth.py:108`), and `/v1/session`
on an existing session replaces its anti-forgery token
(`tests/integration/test_page_load_keeps_csrf.py::test_the_session_call_still_retires_the_previous_token`).
Before W88 neither route asked where a request came from.

Measured on 2026-10-18 in Playwright's Chromium against a `git archive` copy of `8463a72`, with a
page on `localhost` attacking the app on `127.0.0.1` (the failure-modes file, section 0):

| Attack | What ran | Result before W88 |
|---|---|---|
| A1: hidden images use up the network's allowance | two `<img src=".../ui?a=N">` | both 200; 0 cookies stored for the app; the next two fresh visitors got 429, 429 |
| A2: a frame does the same, despite `X-Frame-Options: DENY` | one `<iframe src=".../ui">` | the request reached the app (200) and opened a session; fresh visitors then got 200, 429 |
| A3: an image of `/v1/session` | `<img src=".../v1/session">` | a session opened; fresh visitors 200, 429 |
| A4: a link replaces an open tab's token | tab A on `/ui` gets token T1 (warnings POST with T1: 200); a page on `localhost` links to `/v1/session` | the warnings POST with T1 then got 403 |
| Control: links, not hidden loads | three clicks on a cross-site link to `/ui` in one browser | one session (the session cookie, which is `SameSite=Lax`, set on the first visit is sent on the next two) |

`X-Frame-Options` and `frame-ancestors 'none'` stop a frame being shown, not the request being
served. The browser says where a request came from in `Sec-Fetch-Site`, and how it was made in
`Sec-Fetch-Mode` and `Sec-Fetch-Dest`; a page script cannot set them. The failure-modes file,
section 1, records what all three engines sent for each kind of load.

## Measured

| What | How | Result |
|---|---|---|
| The new tests fail without the fix | the test designer's commit `a5c628a`: `tests/unit/test_fetch_site.py`, `tests/integration/test_cross_site_session_requests.py`, `tests/integration/test_page_load_keeps_csrf.py`, `tests/unit/test_signed_in_bounce_is_closed.py` | `74 failed, 26 passed` (the designer's run) |
| The same files with the fix | the builder's run on `896e892`, `pytest ... -q --no-cov` | `100 passed` |
| The browser spec, without and with the fix | `e2e/tests/navigation/cross-site-loads.spec.ts`, AGENTS.md rule 13's command | `5 failed, 3 passed` on `a5c628a` (the designer); `8 passed` on `896e892` (the builder) |
| The two e2e lanes the specs join | the builder, as `e2e.yml` runs them, then `scripts/check_e2e_executed.py` | navigation: `60 passed`, floor 60; signed-in History: `48 passed`, floor 48 |
| The tests bite | the designer's mutations of a reference copy, each restored and checked with `diff -q` | allow every `navigate` on `/ui`: 14 red; share `/ui`'s page rule with `/v1/session`: 5 red; treat `same-site` as ours: 10 red; ignore the scheme in the `Origin` compare: 4 red; log the raw headers: 1 red; the `/v1/session` check below the invite counter and the limiter: 3 red; the `/ui` check below `record_exempted_request`: 2 red; the `/ui` check below the mint: 20 red; no `Vary` on a 429: 1 red |
| Changed lines covered | the builder, the last two steps of `make diff-cover DIFF_BASE=origin/main` run by hand on its coverage report | `Total: 108 lines, Missing: 3 lines, Coverage: 97%` |
| The OpenAPI document | `make openapi-check` | `openapi contract validation passed`; the only change is the two 403s and their two schemas |
| Review round 1: another site's prefetch | a page at `localhost` carrying `<script type="speculationrules">` for `/ui` and `/v1/session` on `127.0.0.1`: Playwright's Chromium 148 (the round-1 break reviewer, against a header logger and then the real app at `ecbbe63`), and Chromium 149 (the orchestrator, against a header logger) | both fetched in the background with `Sec-Fetch-Site: none`, `Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest: document`, `Sec-Purpose: prefetch`, no `Origin`, no cookie; both answered 200 and each opened a counted session, while the tab stayed on the other site |
| The round-1 tests fail without the prefetch fix | `tests/unit/test_fetch_site_prefetch_and_edges.py`, `tests/integration/test_cross_site_prefetch.py` on `ecbbe63`'s code | `16 failed, 15 passed` (the fixer's run) |
| The round-1 browser spec, without and with the fix | `e2e/tests/navigation/cross-site-prefetch.spec.ts`, AGENTS.md rule 13's command, the server confirmed by its `/status` | `2 failed` (`Expected: 403`, `Received: 200`) against a `git archive` copy of `ecbbe63`; on the fix, the navigation lane run as `e2e.yml` runs it, both of these tests included, gave `62 passed` |
| The round-1 tests bite | the fixer's mutants of `fetch_site.py` and `main.py`, each restored and checked byte for byte | 23 mutants: 22 killed, 1 survived (it left the first prefetch check in place, so it changed nothing). Three versions of its intended form, the check moved below the `none` allow, were each killed (1, 1 and 13 red) |

## Decision

1. **The table** (`fetch_site.classify`). Values are stripped and lower-cased; a repeated or
   comma-joined header has every value read, and one value that is not allowed refuses; an empty
   value counts as missing.

   | `Sec-Fetch-Site` | `/ui` | `/v1/session` |
   |---|---|---|
   | any value, or none, with `Sec-Purpose` or `Purpose` naming `prefetch` | 403 (`prefetch`) | 403 (`prefetch`) |
   | `same-origin`, `none` | allow | allow |
   | `same-site`, `cross-site` | allow only `Sec-Fetch-Mode: navigate` with `Sec-Fetch-Dest: document`; else 403 | 403 in every mode, a link included |
   | any other value | 403 (`unknown`) | 403 (`unknown`) |
   | missing, and no `Origin` | allow | allow |
   | missing, `Origin` is this request's own | allow | allow |
   | missing, `Origin` is another origin or `null` | 403 (`origin-fallback`) | 403 (`origin-fallback`) |

   The prefetch row is checked first (review round 1, the session's choice). `Sec-Purpose`, or its
   older name `Purpose`, is read as a list: a value counts when one of its parts, split at `,` and
   `;`, is `prefetch` in any case (`prefetch`, `prefetch;prerender`,
   `prefetch;anonymous-client-ip`); a word that only contains it, such as `noprefetch`, does not.
   It comes before the `none` allow because Chromium sends another site's speculation-rules
   prefetch as `none`, the value of a typed address (Measured). This site's own pages never
   prefetch either route.
   On both routes a frame `Dest` (`iframe`, `frame`, `object`, `embed`, `fencedframe`) is `frame`
   whatever the mode. On `/ui` a missing `Dest`, or a missing `Mode` beside `Dest: document`, is
   refused, and any other hidden load (an image, a script, a fetch) is `subresource`. On
   `/v1/session` any other navigation is `navigation`, and any other load `subresource`.
   `same-site` counts as another site (the session's choice): a neighbour such as
   `www.stackclimb.com` is hosted elsewhere (`dig`, failure-modes section 1), and same-site images
   carry the session cookie, which is `SameSite=Lax` (sent on same-site requests and on top-level
   links, not on another site's images), so allowing it would let any page on the domain replace
   an open tab's token (F10). `Origin: null` counts as another origin (the session's choice): a
   browser sends it from a page with no origin of its own, such as a sandboxed frame or a local
   file, and the app's own GETs send no `Origin`.
2. **Why `/v1/session` refuses every other site, unlike the usual "allow every navigation" rule.**
   The usual resource-isolation rule allows any `Sec-Fetch-Mode: navigate`. A frame is a navigation
   too, so that rule lets A2 through, on both routes. On `/v1/session` it would also let A4 through:
   a link carries the session cookie, so it resumes the visitor's session and replaces the open
   tab's token. Nothing real needs `/v1/session` from another site: the page asks for it with its
   own same-origin fetch (`initSession`, `static/app.js:8397`), and a typed address sends `none`.
   A prefetch sends `none` too, which is why the prefetch row comes first.
   `/ui` keeps the page exception because people open it from email, chat and search links, and
   Google's sign-in return is a cross-site navigation in all three engines (F1, F2).
3. **Placement: before every counter.** `fetch_site.cross_site_refusal` is the first statement of
   `browser_session` (`main.py:2039`) and `browser_ui` (`main.py:2267`), before `_daily_cap_key`
   (which counts invite use), `record_exempted_request`, the per-minute limiter,
   `issue_or_resume_session` and `_session_capped_response`. Allow-listed visitors are checked too.
   It is a plain function: the decorated-function cap of
   `tests/unit/test_mutation_test_set_integrity.py` is full, and a new outermost `add_middleware`
   would sit outside `_security_headers_middleware`, so its answer would carry no security headers,
   no `X-Request-ID` and no request count (ADR-0171's A8 measurement).
4. **The refusal.** `403`, not `429`: on these two routes a 429 already means a session limit
   (`main.py:2057`, `:2072`, `:2094` on `/v1/session`; the daily cap's page on `/ui`,
   `_session_capped_response`), so a refusal sent as 429 would read as one. `/v1/session` answers
   `{"detail":{"code":"CROSS_SITE_REFUSED","message":"This request came from another site, so it cannot open or renew a session."}}`.
   `/ui` answers a short HTML page (under 4,096 bytes, no script, no inline style) that says only
   "This page was opened in a way this site does not allow. No session was started." (it
   does not guess why, since the one person who can see it opened it as a page) and links back with
   `<a id="cross-site-back" href="/ui">Open Quorum-AI</a>`, a same-origin link, so always allowed.
   A person can land on it in a browser that sends `Sec-Fetch-Site` without `Sec-Fetch-Dest`
   (the user-journey tester's addition). Both carry `Cache-Control: no-store` and no `Set-Cookie`,
   and count against no limit: no session, no mint row, no limiter hit, no invite or allow-list
   count. `/status` and the log count each refusal (decision 6).
   They are returned from the handler, so the security headers, `X-Request-ID` and the request
   metrics (a 4xx of the route) apply. The 403 is declared with `responses=` in `openapi.yaml`.
5. **`Vary`.** Every answer of both routes (200, 403 and 429) carries
   `Vary: Sec-Fetch-Site, Sec-Fetch-Mode, Sec-Fetch-Dest, Origin, Sec-Purpose, Purpose`, added by
   path in
   `_security_headers_middleware` and combined with any `Vary` already there, so a cache that
   honours `Vary` cannot serve one kind of request's answer to another. No cache is known to sit in front (UNVERIFIED for Fly).
6. **`/status` and the log.** `/status` gains `cross_site_refusals`, the refusals since the process
   started, shaped `{"/ui": {class: n}, "/v1/session": {class: n}}` with all six classes
   (`subresource`, `frame`, `navigation`, `unknown`, `origin-fallback`, `prefetch`) always present.
   Each refusal
   writes one INFO line, `refused another site's request: route=%s class=%s`, naming the route and
   the class only, never a header value, which would let anyone write into the log (F21). A count
   also shows a false refusal of a real visitor, which nobody would otherwise report.
7. **This request's own origin** is `request.url.scheme` and its host and port, never a fixed
   list: two hosts serve the app (`quorum-ai.fly.dev`, `quorum.stackclimb.com`, F7). The scheme
   comes from `X-Forwarded-Proto` only from a trusted proxy (`auth.py:163-165`,
   `VisitorAddressMiddleware`).
8. **The `Origin` compare is a browser's** (the test designer's choice, from the plan's "normalised
   like `google_signin._origin`"): the host is lower-cased and a default port dropped
   (`google_signin._origin`, `google_signin.py:597`). The builder added: an origin that is not plain
   http(s), has a bad port, or carries a user part, a path or a query, counts as foreign.
9. **Not gated:** `/ui/invite`, `POST /v1/invite`, the Google callback (always cross-site; guarded
   by `state`, PKCE and the session; its 303 to `/ui` arrives as a cross-site navigation to a
   document, which the `/ui` row allows), `/v1/session/idle` and keep-active. The daily limit is
   unchanged.

## How it was tested in a browser

- **Chromium's local-network check blocked the attack page.** An `<img>` or `<iframe>` of the app
  from a page served by Playwright's `page.route` never reached the app:
  `net::ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS` (the test designer, measured on their machine).
  Those cases would have failed with the fix too, so `cross-site-loads.spec.ts` starts a real
  loopback server for the other site: `localhost:<port>` is cross-site to the app on `127.0.0.1`,
  and another port on `127.0.0.1` is same-site.
- **The headers are read from the DevTools protocol** (`e2e/fixtures/wire-headers.ts`):
  `request.allHeaders()` showed no `sec-fetch-site` for an `<img>`, while the protocol showed
  `cross-site`; and an `<img>` answered with HTML or JSON gives no Playwright response event.
  Every test in `cross-site-loads.spec.ts` checks the sent `sec-fetch-*` before it checks the
  status, so it cannot pass on a request that never named another site.
- **The Google return through a real second host.** The signed-in lane fakes Google with a
  fulfilled 302, and Chromium then reports the return as same-origin (failure-modes F2), so that
  lane would stay green while every real sign-in broke. `e2e/servers/signed_in_server.py` gained
  `GET /bounce` on its existing token stub (the app's port plus 1), addressed as `localhost`; it
  302s only to the app's own callback and answers 400 to anything else
  (`tests/unit/test_signed_in_bounce_is_closed.py`).
- **A reload after a cross-site arrival.** The failure-modes probe of 2026-10-18 recorded Chromium
  sending `cross-site` on that reload (F3). The test designer measured `same-origin` with the
  Chromium of Playwright 1.61.1, the version `e2e/package-lock.json` pins for CI, run on their
  machine. The e2e accepts either; the integration test sends `cross-site` on the reload, so the
  server side of F3 is pinned whichever a browser sends.

## Consequences

- A hidden image, script, fetch or frame of `/ui` or `/v1/session` from another site, and a
  prefetch of either, gets a 403, opens no session and counts against no limit, so it can no
  longer use up a network's 2 daily sessions or replace an open tab's token.
- After a refused prefetch of `/ui`, a click on the link it was for still opens a working page
  (`e2e/tests/navigation/cross-site-prefetch.spec.ts`, measured in Chromium).
- A link from another site still opens the page, and Google sign-in, its cancel and W87-2's
  deletion sign-in still return to it (the cross-site integration tests and
  `e2e/tests/signed-in/cross-site-return.spec.ts`).
- The tests that called these routes before W88 use `TestClient`, which sends no `Sec-Fetch-*`
  header, so they take the allow path (F24, counted at `8463a72`:
  `git grep -l '"/v1/session"' 8463a72 -- tests | wc -l` prints 34, the files that call the quoted
  route, `tests/helpers.py` among them); only the new tests show the check works.
- The e2e navigation lane's floor rises from 52 to 62 (8 tests in `cross-site-loads.spec.ts`, 2 in
  `cross-site-prefetch.spec.ts`) and the signed-in History lane's from 46 to 48.

## Known limits

- **The second-tab token effect** (Codex, plan review 1, reproduced with the real auth functions).
  A link on another site that opens `/ui` in a new tab passes the `/ui` row, and the new page's own
  same-origin `/v1/session` call renews the session's token, so the first tab is refused on its
  next action until it reloads. A person opening a second tab does the same today. Handled by board
  row W105 (CHG-071: tabs share a renewed token); W88 asserts neither way.
- **A page opened from another site still opens one counted session per browser** (F15): a link,
  or a forced top-level navigation, costs one session while the cookie lives (three clicks gave one,
  measured), and a private window starts fresh each time. The visitor does not always stay on
  the app: after one click on another site, that site can open `/ui` as a page in a small window
  and close it again at once. That too counts one session per browser, as it did before W88.
  Handled by board row W106 (CHG-067: page loads never count).
- **Old browsers that send neither header** are allowed, as the owner chose (CHG-063 (b), F14).
- **Plain http on a LAN address** (F8): browsers send no `Sec-Fetch-*` header to an `http://` host
  that is not `localhost` or `127.0.0.1` (measured), so the check is off there. Production is https
  only (`fly.toml:167`, `force_https = true`).
- **Prefetches are refused, from any page.** The first version of this record called a
  cross-site prefetch (F16) a search engine's, allowed as a navigation. Review round 1 measured
  that wrong on both counts: any page can ask for one with a script tag, and Chromium sends it as
  `none`, so both routes let it through. It is now refused (decision 1, F28). Still UNVERIFIED: a
  browser's own preloading of an address while it is being typed. If the browser marks that load
  with `Sec-Purpose`, it is refused too, and nothing here measures that the browser then loads the
  page normally when the visitor presses Enter; whether it marks it at all was not measured. The
  e2e measures the normal load only for a prefetch followed by a link click. Firefox and WebKit
  prefetches were not measured. Only loopback http (`localhost` to `127.0.0.1`) was measured; the
  same over https, which the deployed site uses, is UNVERIFIED.
- **Fly's proxy may change the headers** (F27, UNVERIFIED: no test here measures it). The free
  check after the deploy is `/status` `cross_site_refusals`: it should list all six classes for
  both routes (counts since the process started), and non-zero counts later show the deployed
  check refusing real requests. It cannot show that a header arrives unchanged. An optional check for the owner: send a cross-site image of `/ui`, a
  `same-site` `/v1/session` and a `/v1/session` with a foreign `Origin`, each expecting 403.
  **Warning:** these have no cookie, so if the proxy dropped the headers each would be allowed and
  would spend one of the network's 2 daily sessions; send them only with an existing session
  cookie, or accept that cost.
- **Not tested:** an empty `Origin` value. (A malformed port and an `Origin` with a user part, a
  path or a query, untested at first, are now tested in
  `tests/unit/test_fetch_site_prefetch_and_edges.py`.)

## Rejected alternatives

- **Refuse every request that names another site**, as CHG-063 (b)'s result text read. Links from
  email and every Google sign-in would break (F1, F2); CHG-067 narrowed it.
- **The usual "allow every navigation" rule.** It lets a frame open a session (A2, F9), and on
  `/v1/session` a link replace a token (A4, F11). Decision 2.
- **Move the page from `/ui` to `/`** (the owner's question in CHG-067). Any address that opens a
  session when loaded can be loaded by a hidden image.
- **Make page loads never count now.** The owner chose it as a second step, W106 (CHG-067).
- **A new outermost middleware, or a decorated one.** Decision 3.
- **A fixed list of the app's origins.** Two hosts serve it, and a list would also have to follow
  the forwarded scheme (F7).
- **Answer 429.** On these routes it already means a session limit (decision 4).
- **Put header values in the log or in `/status`.** Anyone could write into the log, and a label
  per value grows without bound (F21).
- **`SameSite=Strict` on the cookie.** A1 opened sessions with no cookie at all, so the cookie's
  rules cannot stop it (by reading of A1's result).

## Related

- Code: `src/product_app/fetch_site.py` (`classify`, `cross_site_refusal`, `status_snapshot`),
  `src/product_app/main.py` (`browser_session`, `browser_ui`, `_add_vary`,
  `_security_headers_middleware`, `status_snapshot`), `openapi.yaml`.
- Tests: `tests/unit/test_fetch_site.py`, `tests/integration/test_cross_site_session_requests.py`,
  `tests/integration/test_page_load_keeps_csrf.py`, `tests/unit/test_signed_in_bounce_is_closed.py`,
  `tests/unit/test_fetch_site_prefetch_and_edges.py`, `tests/integration/test_cross_site_prefetch.py`,
  `e2e/tests/navigation/cross-site-loads.spec.ts`, `e2e/tests/navigation/cross-site-prefetch.spec.ts`,
  `e2e/tests/signed-in/cross-site-return.spec.ts`.
- ADR-0131 (loading the page keeps the token; the session call still renews it), ADR-0132 (the
  session limits count the visitor), ADR-0139 (a capped network gets a sign-in-only session),
  ADR-0171 (A8: where a refusal sits decides its headers). `docs/41-security-controls.md` SC-105;
  ASVS V3.5.3 in `docs/analysis/2026-10-17-asvs-5-level-2-check.md`.
- CHG-060, CHG-063 (b), CHG-067, CHG-071; board rows W88, W105, W106.
