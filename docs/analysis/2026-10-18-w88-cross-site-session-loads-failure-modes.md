# W88 failure modes: refusing another site's request on GET /ui and GET /v1/session

Written before any code, for board row W88, and committed with the fix (CHG-060: the detail is
held back from the public documents until the fix ships). The design is ADR-0177. Line numbers
below are those of `8463a72`, the tree the list was written on; they have moved since.

What changed after this list was written:
- Section 4's question was put to the owner. CHG-067 records the answer: from another site `/ui`
  may only be opened as a page, `/v1/session` is refused from any other site, and page loads that
  never count are a later row, W106.
- F3: the test designer measured `same-origin`, not `cross-site`, on the reload, in the Chromium of
  Playwright 1.61.1 (ADR-0177, "How it was tested in a browser"). The tests accept either.
- The plan's e2e attack page, served by `page.route` from F26's second local origin, did not work:
  Chromium's local-network check blocked its requests to the app, so the spec uses a real loopback
  server (ADR-0177).
- The second-tab token effect, which this list does not name, was found by Codex's first plan
  review and is board row W105 (CHG-071).
- F20 below calls the `/ui` refusal page something "nobody sees". The build found a person can land
  on it, in a browser that sends `Sec-Fetch-Site` without `Sec-Fetch-Dest` (ADR-0177, decision 4),
  so its words say only that the page was opened in a way the site does not allow.
- F20 below names a `Vary` of three headers. The build sends four (`Origin` too), and review round 1
  added `Sec-Purpose` and `Purpose`, so six.
- F21 below names four refusal classes. The build added `unknown`, and review round 1 added
  `prefetch`, so six.
- F16 below was wrong on two counts, found by review round 1 and measured: any page can ask for a
  prefetch, and Chromium sends it as `none`, so both routes let it through. It is F28, now fixed.

Tree read: `origin/main` at `8463a72`, a `git archive` copy. Probes ran on ports 18260-18265 against
(a) a header-echo server and (b) the real app copy with temporary databases, in Playwright
Chromium, Firefox and WebKit from `e2e/node_modules`. Everything marked MEASURED below was run
today (2026-10-18). Anything else is marked UNVERIFIED.

## 0. The attacks, reproduced in a real browser (MEASURED, Chromium, real app)

| Attack | What ran | Result |
|---|---|---|
| A1: images use up the network's allowance | page on `localhost:18263` with two `<img src="http://127.0.0.1:18262/ui?a=N">` | both `/ui` 200; **0 cookies stored** for the app in the attacker's context; the next two fresh visitors got **429, 429** |
| A2: a frame does the same, despite `X-Frame-Options: DENY` | one `<iframe src=".../ui">` | the request reached the app (200) and minted; fresh visitors then got **200, 429** |
| A3: an image of `/v1/session` | `<img src=".../v1/session">` | minted; fresh visitors **200, 429** |
| A4: a link replaces the open tab's token | tab A loads `/ui`, gets token T1, warnings POST with T1 = **200**; tab B on `localhost` clicks a link to `/v1/session` | the warnings POST with T1 then gets **403** |
| Control: links, not hidden loads | three clicks on a cross-site link to `/ui` in one browser | **one** mint (the Lax cookie set on the first visit is sent on the next two); fresh visitors then **200, 429** |

So the reading in the brief holds, and adds one case it did not name: a frame (A2). `X-Frame-Options`
(main.py:911) stops the frame being shown, not the request being served.

## 1. What browsers actually send (MEASURED, all three engines)

The "Lax cookie" column is the session cookie, which is `SameSite=Lax`: a browser sends it on
same-site requests and on top-level links, but not on another site's hidden loads.

| Request | Sec-Fetch-Site | Mode | Dest | Lax cookie sent | Origin |
|---|---|---|---|---|---|
| typed URL / `page.goto` | none | navigate | document | yes | absent |
| the page's own `fetch("/v1/session")` (app.js:8368) | same-origin | cors | empty | yes | absent |
| cross-site `<img>` | cross-site | no-cors | image | **no** | absent |
| cross-site `<iframe>` | cross-site | navigate | iframe | no | absent |
| cross-site `<object>` | cross-site | navigate | object (Chromium, Firefox) / **iframe (WebKit)** | no | absent |
| cross-site `<script>`, `fetch(no-cors)`, `<link rel=prefetch>` | cross-site | no-cors | script / empty / empty (`Sec-Purpose: prefetch`) | no | absent |
| cross-site `fetch()` in cors mode | cross-site | cors | empty | no | **present** |
| fetch from a sandboxed frame | cross-site (even inside a same-site parent) | cors | empty | no | **`null`** |
| cross-site link click, form GET, `location.href=`, `target=_blank` | cross-site | navigate | document | **yes** | absent |
| same thing from another port on the same host (same-site) | **same-site** | as above | as above | **yes, on images and fetches too** | absent except cors |
| reload of a page reached by a cross-site link | **cross-site in Chromium**; same-origin in Firefox, WebKit | navigate | document | yes | absent |
| cross-site link, then a 303 inside the app | **cross-site** on the redirected request too (all three) | navigate | document | yes | absent |
| app page → another origin → 302 back to the app (the Google sign-in shape) | **cross-site** on the return and on the next 303 (all three) | navigate | document | yes | absent |
| same bounce faked with `page.route(...).fulfill({status: 302})` (the e2e stub) | **same-origin in Chromium**, cross-site in Firefox; WebKit refuses to fulfil a 302 | navigate | document | yes | absent |
| `http://` image → 301 → `https://` (Fly's `force_https`, fly.toml:166-167) | **cross-site** on the https hop (Chromium, Firefox) | no-cors | image | — | absent |
| any request to a plain `http://` host that is not localhost/127.0.0.1 | **no Sec-Fetch headers at all** | — | — | — | — |
| Playwright `page.request.get` and `request.newContext().get` | **none sent** | — | — | page.request: yes | absent |

Sites, MEASURED in Chromium over https with host mapping: `evil.fly.dev` → `quorum-ai.fly.dev` is
**cross-site** (fly.dev is a public suffix); `blog.stackclimb.com` → `quorum.stackclimb.com` is
**same-site**; `quorum-ai.fly.dev` → `quorum.stackclimb.com` is **cross-site**. `dig` shows
`stackclimb.com` and `www.stackclimb.com` resolving to Cloudflare addresses, not to the app's Fly
address, so same-site neighbours exist and are hosted elsewhere.

## 2. Recommended policy, per route

Read `Sec-Fetch-Site` first. Allowed values are compared lower-cased and stripped.

**GET /v1/session** (main.py:1925-2010): allow only `same-origin` and `none`. Refuse `cross-site`,
`same-site` and any unknown value, whatever the mode or destination. No real flow reaches it any
other way: the page fetches it same-origin (app.js:8368), and a typed URL is `none`.

**GET /ui** (main.py:2133-2176): allow `same-origin` and `none`; also allow a request with
`Sec-Fetch-Mode: navigate` AND `Sec-Fetch-Dest: document` from any site (a page opened from a
search result, an email, a chat app, the Google sign-in return, a Chromium reload). Refuse
everything else: image, script, empty, iframe, frame, object, embed, fencedframe, a missing
`Sec-Fetch-Dest` beside a present `Sec-Fetch-Site`, and an unknown site value.
Note this is NOT the textbook resource-isolation policy, which allows every `navigate` request and
so would let A2 (the frame) through.

**No `Sec-Fetch-Site` at all** (CHG-063 (b), the owner's choice): look at `Origin`. If present and
not this request's own origin, refuse; `Origin: null` is refused too (only an opaque origin, a page
with no origin of its own such as a sandboxed frame or a local file, sends
it, and the app's own GETs never carry `Origin`). With neither header, allow, as today.

**Not gated**: the Google callback (google_signin.py:667), `/ui/invite`, `/v1/invite`, every
other route. The 2-per-network daily limit (auth.py:84) stays as it is.

**Where**: as the first statement of both handlers, before `_daily_cap_key` (main.py:1910, which
increments the invite counter at :1921), before `record_exempted_request` (:1941, :2146), before
the per-minute limiter (:1942) and before `issue_or_resume_session` (:1955, :2151). A plain
function, not `@app.middleware` (the decorated-function cap is full, ADR-0142) and not a new
outermost `add_middleware` (it would sit outside the security-header function at main.py:907, the
W85 A8 failure).

## 3. Failure modes

Each row: trigger, the test that catches it (with what turns it red), the design answer.

### Real visitors refused (false refusal)

**F1. A visitor arriving from Google or an email link is refused.**
Trigger: the CHG-063 words read literally ("a request that names another site is refused"); the
arrival is `cross-site / navigate / document` (MEASURED).
Test: `/ui` with those three headers and no cookie → 200, one mint, a cookie set. Red if the
navigation exception is dropped.
Answer: the navigation exception in section 2. **This departs from the recorded words, so it needs
the owner (section 4).**

**F2. Every Google sign-in breaks.**
Trigger: the callback 303s to `/ui` (google_signin.py:131, :713); after the bounce through Google
the `/ui` request is `cross-site` in all three engines (MEASURED).
Test: an integration test that signs in through the stub callback, sending
`cross-site/navigate/document` on the follow-up `/ui`, asserts the signed-in page (200, account
controls). Red if `/ui` refuses cross-site navigations.
**Trap**: the e2e signed-in lane fakes Google with `route.fulfill({status: 302})`
(e2e/tests/signed-in/follow-up-context.spec.ts:44), and Chromium then reports the return as
**same-origin** (MEASURED). That lane would stay green while every real sign-in broke. It cannot
be the positive partner. Use a real second-origin bounce server in e2e, or the integration test
above.

**F3. "Refresh session" fails after a cross-site arrival in Chrome.**
Trigger: `location.reload()` (app.js:917-918, :9995) re-sends `cross-site` in Chromium (MEASURED).
Test: covered by F1's test (the same headers). Red as F1.
Answer: the navigation exception covers it.

**F4. A typed URL, bookmark, or extension is refused.**
Trigger: `none` treated as foreign.
Test: `/ui` and `/v1/session` with `Sec-Fetch-Site: none` → 200. Red if `none` is not on the
allow list.

**F5. The page's own token fetch is refused.**
Trigger: allowing only `same-origin` + `navigate`, or reading `Mode` on `/v1/session`.
Test: `/v1/session` with `same-origin / cors / empty` and a cookie → 200 and the token rotates
(keep `test_the_session_call_still_retires_the_previous_token` meaning). Red if refused.

**F6. The invite link stops working.**
Trigger: gating `/ui/invite` or `/v1/invite` by mistake. Today the chat-app click opens the static
`/ui/invite` (cross-site, not gated), its script POSTs `/v1/invite` same-origin (invite.js:51),
and "Continue" (invite.html:49) is a same-origin click to `/ui`.
Test: `/ui/invite` with `cross-site/navigate/document` → 200 (static page); `/ui` with
`same-origin/navigate/document` and an invite cookie → 200 and the invite cap used. Red if either
route is gated.

**F7. Old-browser visitors refused by the Origin fallback.**
Trigger: comparing `Origin` with `request.url` when the scheme is wrong. Behind Fly the scheme
comes from `X-Forwarded-Proto` only from trusted peers (auth.py:140-141); a mismatch would make
`https://quorum.stackclimb.com` look foreign to an app that thinks it is on `http`.
Test: from a trusted peer with `X-Forwarded-Proto: https`, `Origin: https://<host>` and no
Sec-Fetch → 200; same with `Origin: https://evil.example` → refused. Red if the comparison ignores
the forwarded scheme. Also two hosts serve the app (`quorum-ai.fly.dev`, `quorum.stackclimb.com`,
google_signin.py:590-600): compare against the request's own host, not a fixed list.

**F8. Local or docker-compose use over plain http on a LAN address.**
Trigger: browsers send no Sec-Fetch headers to a non-localhost `http://` host (MEASURED). Not a
refusal (the fallback allows), but it means the protection is off there. Production is https only
(fly.toml:166-171). Record it as a limit; no fix needed.

### Attacks still getting through (false acceptance)

**F9. A frame still mints (A2).**
Trigger: allowing every `Sec-Fetch-Mode: navigate`, the textbook policy.
Test: `/ui` with `cross-site/navigate/iframe` (and `object`, `embed`, `frame`) → refused, no
Set-Cookie, zero new mint rows. Red if the check reads Mode alone.

**F10. A same-site neighbour replaces the token silently.**
Trigger: treating `same-site` as ours. Same-site images and fetches carry the Lax cookie (MEASURED),
so an `<img>` on any `*.stackclimb.com` page could rotate an open tab's token with no visible
navigation, which is worse than A4.
Test: `/v1/session` with `same-site/no-cors/image` and a live cookie → refused, and the old token
still passes the warnings POST (200). Partner: `same-origin` rotates. Red if `same-site` is allowed.

**F11. A cross-site navigation to `/v1/session` still rotates (A4).**
Trigger: copying the `/ui` navigation exception onto `/v1/session`.
Test: `/v1/session` with `cross-site/navigate/document` and a cookie → refused; then the earlier
token → 200 on the warnings POST. Red if the exception is shared between the routes.

**F12. The refusal sits after the side effect.**
Trigger: checking after `issue_or_resume_session`, or inside `_session_capped_response`, which
mints a sign-in-only session (main.py:2102-2103).
Test, by cardinality: two refused `/ui` image requests with no cookie → the mint table has **0**
rows, the session repository has **0** sessions, the response has no Set-Cookie; partner: the same
two without headers → **2** rows. Red if the check moves below the mint.

**F13. A browser that sends Sec-Fetch-Site but no Sec-Fetch-Dest (Chrome 76-79).**
Trigger: treating a missing Dest as `document`. Test: `cross-site/navigate` with no Dest on `/ui`
→ refused. These versions are effectively gone (UNVERIFIED share), so refusing costs nothing.

**F14. Old browsers with no Sec-Fetch at all.**
Trigger: an `<img>` or frame sends neither Sec-Fetch nor Origin (MEASURED for modern engines; old
Safari's exact behaviour UNVERIFIED). The fallback allows it, as the owner chose. Accepted residual.

**F15. A forced top-level navigation (`location =` or a popup) still mints.**
Trigger: the navigation exception. MEASURED: it costs one mint per browser while the cookie lives
(three link clicks → one mint), and it is visible: the visitor lands on the app. A private window
starts fresh each time. Accepted residual; state it in the ADR.

**F16. A cross-site navigational prefetch (search-engine prefetch).**
Trigger: allowed as a navigation; it may mint a session the visitor never opens. UNVERIFIED headers
for Google's prefetch proxy. Today's behaviour, not made worse. **Superseded by F28**: this entry
assumed a prefetch arrives as a cross-site navigation and only from a search engine; both were
wrong.

**F28. Any page's speculation-rules prefetch arrives as a typed address (MEASURED, now fixed).**
Found by W88's review, round 1, after the build. A page on another site carrying
`<script type="speculationrules">` with `/ui` and `/v1/session` in a prefetch list makes Chromium
149 fetch both in the background with `Sec-Fetch-Site: none`, `Sec-Fetch-Mode: navigate`,
`Sec-Fetch-Dest: document`, `Sec-Purpose: prefetch`, no `Origin` and no cookie (measured against a
header logger and against the real app at `ecbbe63`: both 200, each opening a counted session,
the tab still on the other site). `none` is allowed, so the fix as first built let it through on
both routes, `/v1/session` included. With a live session cookie Chromium did not send the
prefetch at all (round 1, measured), so the exposure is visitors with no cookie, the same group
A1's images hit. Fix: refuse on both routes when `Sec-Purpose` or `Purpose` names `prefetch`,
checked before the `none` allow, counted as `prefetch` in `/status`, with both headers in `Vary`.
Tests: `tests/unit/test_fetch_site_prefetch_and_edges.py`, `tests/integration/test_cross_site_prefetch.py`
(the measured headers give 403 with no mint; the same headers without `Sec-Purpose` give 200 and
one mint), and `e2e/tests/navigation/cross-site-prefetch.spec.ts` (a real second server's page;
the browser's `sec-purpose: prefetch` is asserted before the 403; a link click after the refused
prefetch still reaches a working page). UNVERIFIED: a browser's own preloading of an address
while it is typed, and prefetches in Firefox and WebKit.

### Side effects of the refusal itself

**F17. Refusals use up the per-minute limiter, so an attacker's images lock the victim's network
out of `/v1/session` for a minute.**
Trigger: the check placed after main.py:1942. Test: 11 refused `/v1/session` calls from one address,
then one same-origin call → 200 (the limiter is 10/min in deployed environments,
query_runs.py:555-565; the test must set it explicitly and not rely on that number). Red if the
check moves below the limiter.

**F18. Refusals inflate `/status` counters.** `requests_with_invite` (main.py:1921) and
`exempted_requests` (main.py:1941, :2146). Test: a refused request with an invite cookie leaves
`requests_with_invite` unchanged.

**F19. The refusal lacks security headers, `X-Request-ID`, or a metrics count.** Trigger: a new
outermost middleware. Test: refused response carries `X-Frame-Options`, `Content-Security-Policy`,
`X-Content-Type-Options` and `X-Request-ID`, and `/metrics` counts it under the route's 4xx.

**F20. What the refusal returns.** 403, `Cache-Control: no-store`, **no Set-Cookie**, a small body;
`/v1/session` gets the JSON envelope with a new code (for example `CROSS_SITE_REFUSED`), and `/ui`
a short plain page (nobody sees it; it lands in an image or a frame). Not 429: that would read as
the daily cap on `/ui` and in the page script. A `Vary: Sec-Fetch-Site, Sec-Fetch-Mode,
Sec-Fetch-Dest` is cheap and stops any cache serving one answer for the other (no cache is known
to sit in front, UNVERIFIED for Fly).

**F21. Metrics that grow without bound.** Trigger: putting raw header values in a label (the same
trap as the method label, main.py:678-709). Answer: a `/status` count of refusals per route and per
fixed class (`subresource`, `frame`, `navigation`, `origin-fallback`), and log only the class.
A count also shows false refusals of real visitors, which nobody would otherwise report.

**F22. Header parsing.** Upper case or spaces (`Cross-Site`), an empty value, the header twice.
Test: `Cross-Site` → refused; empty value → treated as absent (fallback); two values with one
foreign → refused. A browser cannot set `Sec-` headers from script, so only non-browser clients
can send odd values, and they could mint without them anyway.

**F23. HEAD and OPTIONS.** MEASURED today: `HEAD` and `OPTIONS` on both routes → 405, no
Set-Cookie. Test pins it, so a later "add HEAD for uptime checks" must go through the same check.

### Tests and tooling

**F24. Every existing test still passes with the check missing.** All 34 files under `tests/` that
call the quoted route `"/v1/session"` (33 test files and `tests/helpers.py`;
`git grep -l '"/v1/session"' 8463a72 -- tests | wc -l` prints 34; without the quotes it prints 38,
the other 4 naming only `/v1/session/keep-active` or the route in a docstring) use `TestClient`, which sends no Sec-Fetch headers, so they take the "allow"
path. That keeps them green (good), and means none of them can show the check works. Every new
test above needs a refused case and a partner without headers.

**F25. e2e request contexts.** MEASURED: `page.request` and `request.newContext()` send no
Sec-Fetch headers, so the e2e calls that go through them (for example
e2e/tests/navigation/navigation.spec.ts:31) keep working. Browser navigations send `none` and
page fetches `same-origin`.

**F26. The e2e lane cannot show the cap being saved.** It runs with
`SESSION_MINT_CAP_OVERRIDE=600` (AGENTS.md rule 13), so "two images use the allowance" never shows
there. An e2e spec should assert on the image request's own response status (403) through
`page.on("response")`, from a second local origin (`localhost` against `127.0.0.1`, which is
cross-site; another port on `127.0.0.1` is same-site, also worth one case).

**F27. Fly's proxy may change the headers.** UNVERIFIED: nothing in the repo measures whether Fly
passes `Sec-Fetch-*` and `Origin` unchanged (ADR-0132 measured only `Fly-Client-IP` and
`X-Forwarded-For`). Review round 1 corrected the check first written here, a cookie-less `curl`
of production `/ui` with cross-site headers: if the proxy dropped the headers, that request would
be allowed and would spend one of the network's two daily sessions, so it is not free. The free
check after the deploy is `/status` `cross_site_refusals` (ADR-0177, Known limits). A header
request is an optional check for the owner, sent with an existing session cookie.

## 4. The owner question it still needs

CHG-063 (b) records: "a request that names another site is refused". Taken literally, that refuses
F1 and F2. Suggested wording, with a concrete example:

> Someone clicks a link to quorum.stackclimb.com/ui in a Gmail message. Their browser says "this
> came from another site, to open a page". The same is true when Google sends them back after
> "Sign in with Google".
> **Option A, as recorded:** refuse it. They see an error instead of the app, and sign-in stops
> working for everyone.
> **Option B (recommended):** allow opening the page from another site. It starts at most one
> session per browser, because the next link sends the same cookie. Refuse every hidden load from
> another site (an image, a frame, a script). Refuse `/v1/session` from another site in any form,
> including a link, so no other site can replace an open tab's token.

Decided without the owner (engineering calls): `same-site` counts as another site
(`www.stackclimb.com` is hosted elsewhere, and its images carry the cookie); `Origin: null` counts
as another site.

## 5. Most likely to be missed

1. The frame (F9): `X-Frame-Options: DENY` does not stop the mint, and the textbook policy allows it.
2. The e2e sign-in stub reports same-origin in Chromium (F2), so a broken sign-in passes CI.
3. Placing the check after the counters and the per-minute limiter (F12, F17, F18).
4. Same-site neighbours carry the cookie on images (F10).
5. The Chromium reload keeps `cross-site` (F3).

## Cleanup

Probe servers on 18260-18265 stopped (`lsof -ti tcp:18260-18269 | wc -l` printed 0). The folder
`w88fm` (archive copy, probe scripts, temporary databases, self-signed certificate) is deleted
after this file is written.
