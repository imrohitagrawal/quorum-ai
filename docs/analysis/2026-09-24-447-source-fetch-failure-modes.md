# The judge reads the cited pages: failure modes, listed before any code (2026-09-24)

AGENTS rule 16e. Package 5 of the 2026-09-24 order (#447, Route B: a
credential-guarded fetcher reads the cited pages so the judge grades what it
has read; owner: "JUdge should be able to verify the sources then only will
be able to judge properly" and "I agree with your choice", CHG-012 D4).
Every "today" claim names the command that shows it, read on `main` at
b6213c4; no paid call.

## Two facts first

- **The "free capture" the package puts first is already in the tree.**
  `sed -n 6,18p docs/analysis/2026-09-10-window-measurements.md`: OpenRouter
  `:online` annotations DO carry page content — run 5a9c2d63, 4 of 4
  searching calls with a nested `url_citation` block whose `content` is a
  string, 20 annotations, 40,479 characters (largest call 10,245); the raw
  rows are `docs/analysis/2026-09-10-telemetry-tokens.jsonl` lines 127-130
  and 145-148 (about 2,000 characters per citation, all four default
  models). No completion is needed to answer D4, and none was spent. Route B
  still stands: the annotation is the excerpt the model's search tool chose
  for the query, not the page, and sources from other paths (inline
  Markdown, Tavily) carry no excerpt at all. Two caveats: the repository
  holds no SAMPLE of passage text (telemetry records a shape, a count and a
  length, ADR-0104), and whether the repaired nested reader (PR #477) yields
  `annotation_usable_count > 0` on live traffic is UNVERIFIED (newest
  telemetry row 2026-09-10, nine days before the fix; production runs with
  live execution off).
- **`credentialed_url.py` has the OPPOSITE policy.** It exists to send the
  operator's key safely to OpenRouter, so `is_credential_safe` accepts
  `http://localhost` and `https://169.254.169.254`; only its rule that a redirect is never
  followed is shared (the fetcher uses `http.client`, which never follows one). The fetcher must
  refuse exactly what that module accepts, and carry no key at all.

## The modes

| # | Failure mode | Threat | What pins it today | What the fetcher must add |
|---|---|---|---|---|
| 1 | **SSRF into the deployment's own network**: loopback, RFC1918, Fly's private ranges and its 6PN ULA, `0.0.0.0`. | T-014 (new) | A six-literal hostname denylist in `providers.py` with no DNS resolution. | Resolve every A/AAAA answer; refuse unless ALL pass `is_global and not is_multicast and not is_reserved`, after unwrapping IPv4-mapped addresses; literal IPs go through the same predicate. |
| 2 | **Cloud metadata endpoints** and their spellings: `169.254.169.254`, `metadata.google.internal`, `fd00:ec2::254`, `127.1`, `2130706433`, `0x7f000001`, `::ffff:169.254.169.254`, NAT64 `64:ff9b::/96` and `64:ff9b:1::/48`. | T-014 | Nothing. | The same predicate plus the two NAT64 networks; a parametrised test over every literal address. Name spellings (`127.1`, `metadata.google.internal`) go through the resolver, which the suite cannot reach; the resolver normalises them to the addresses above before they are classified. |
| 3 | **DNS rebinding**: classify at resolve time, connect by name later, the answer changes. | T-014 | Nothing. | Dial the CLASSIFIED address (`_PinnedHTTPConnection`/`_PinnedHTTPSConnection` override `connect()`), keep the hostname for `Host` and SNI; `http.client` reads no proxy variable, so none can bypass the pin. (This row first proposed a urllib opener; the built design uses `http.client`.) |
| 4 | **Redirects** to `file:`, `gopher:`, a private address or a different host. | T-014 | `credentialed_url._NoRedirect`; the transport-guard AST scan refuses any `build_opener` without a positional `_NoRedirect` and any bare `urlopen`. | `http.client` never follows a redirect, so every 3xx is `refused_redirect` by construction; the transport-guard scan inspects urllib callers only and does not see the fetcher. |
| 5 | **Non-http schemes at the first hop** (`file:`, `data:`, `ftp:`, `javascript:`), userinfo, control characters. | T-014 | The same scheme conventions in `credentialed_url.py`. | `urlsplit` scheme in {`http`, `https`} only, never `startswith`; refuse userinfo and whitespace. |
| 6 | **A key leaks to a cited host.** | T-004 | `tests/unit/test_credential_transport_guard.py` proves where the OpenRouter key goes; nothing proves where it does NOT go for a new caller. | The request carries only `User-Agent`, `Accept`, `Accept-Encoding: identity`; a wire test on a loopback recording server asserts the request arrived (positive partner) and no header name or value carries the OpenRouter, judge or Tavily key. |
| 7 | **A response bomb**: an oversize body, or gzip sent despite `identity`. | availability | `catalog_fetcher.py`'s bounded read. | A byte cap on the `read1` ARGUMENT and on the loop, never a post-hoc slice (AGENTS 8b); `Content-Length` as a cheap pre-check, not the bound; a body that is not decodable text is `unusable`, not evidence. |
| 8 | **A slow body** (slowloris), and a slow head. | availability | `providers.py`'s per-recv socket timeout shape. | One TOTAL budget for all of a call's fetches, enforced by a watchdog that shuts the socket at the deadline — covering dribbled headers, endless `100 Continue`, chunked trailers and the TLS handshake — and a name lookup joined with the remaining budget (a per-recv timeout is not a total bound; memory `socket-timeout-is-per-recv`). Corrected after review round 1: this row first said slow headers were bounded by `urlopen`'s timeout; the fetcher uses no `urlopen`, and they were not bounded. |
| 9 | **Time per run**: the judge runs on the serving GET, outside the 720 s run deadline; concurrent readers wait 30 s; the browser fetch has no timeout. | availability | `_JUDGE_INFLIGHT_WAIT_SECONDS`; the judge call's own 60 s budget. | A total fetch budget per run (proposal 8 s), skipped pages past it (`skipped_cap`), and an honest UNMEASURED note: first-read latency with the fetch stacked on the judge is not measured. |
| 10 | **Pages per run and per host.** | availability, etiquette | `JUDGE_MAX_SOURCE_LINES = 32` bounds source LINES, not fetches. | A page cap (proposal 8, in the judge's kept-sources order so every slot gets a page before any gets two), a per-host cap, one GET per page, no retries, an identifying `User-Agent` with a contact URL; the robots.txt decision recorded either way. |
| 11 | **Prompt injection from a fetched page into the judge.** | T-007, T-011 | Answer and synthesis text already pass through `_neutralize_delimiters` inside the UNTRUSTED block; today's injection tests inject through answer text only. | Every page line through the same fence; the system prompt says page text is a third author and that instructions inside a page are evidence of a problem; an injection test whose payload sits in a fetched page, with a positive partner. |
| 12 | **The judge input bound and its cost.** | money | `JUDGE_MAX_SOURCE_LINES/TITLE_LEN/URL_LEN` derive the judge reserve; `cost_judge_input_tokens = 7300` (CHG-008). Eight pages of 4,000 characters roughly double the judge's input. | The page cap and the reserve ship in the SAME pull request as the wiring, or ADR-0064's defect (the judge billed above its reserve) returns. Not in the fetcher PR: with the setting off, no reserve moves. |
| 13 | **The receipt row.** | honesty | Every optional stage is a `by_stage` row (CHG-011 D9); `test_estimate_prices_the_judge.py` pins `len(by_stage) == 5`. | An explicitly-free `source_fetch` row on BOTH the estimate and the measured breakdown, same key, appended before the single reconcile; a cardinality test; the measured-honesty gate's treatment of a free stage decided in the ADR. Wiring PR. |
| 14 | **Copy that says sources are not checked** (`workspace.html` chip, `TRUST_DISCLOSURE_VERIFIED`, "never retrieved here", README, ADR-0096, ADR-0098). | honesty | Pinned by `test_judge_disclosure_is_honest.py`, `landing-cta-reachable.spec.ts`, `trust-score-invariants.spec.ts`. | All stay TRUE while the setting is off. They follow one posture predicate (the ADR-0116 pattern) in the wiring PR, never an unconditional rewrite. |
| 15 | **A page that changed since the model cited it.** | honesty | Nothing; the judge is memoised first-outcome-wins and `eval_json` is persisted. | Carry the fetch time and `Last-Modified`/`Date` in the provenance line; the prompt says the page may differ from what the model saw; no cross-run cache. |
| 16 | **Paywalls, consent walls, bot challenges, 401/403/429/451**: a `200` whose body is a login shell. | honesty | Nothing. | Classify as `fetched, unusable` under a minimum-usable-text threshold so the judge grades them as not fetched, never as a contradiction. |
| 17 | **Non-HTML content types and charsets.** | availability | Nothing. | Accept `text/html` and `text/plain` only, decided BEFORE the body read; charset from `Content-Type` else UTF-8 with replacement; strip script, style, noscript, template, svg and head with the stdlib parser (no bs4 or lxml in the venv). |
| 18 | **Fetched page text leaves the deployment to the judge provider.** | T-012 (extend) | T-012 covers query text and provider prose. | A third class of data in the threat model and in `docs/42`; wiring PR. |
| 19 | **A transient fetch failure is memoised forever.** | honesty | First-outcome-wins memo; persisted `eval_json`. | Decide skip-the-judge versus judge-on-titles for a 0-of-N fetch and record it; wiring PR. |
| 20 | **The fetch runs for a run nobody judges.** | availability | `judge_configured()` gates the judge. | Gate every fetch on `judge_configured() and quorum_source_fetch_enabled`; the setting defaults OFF and is reported on `/status` (ADR-0013). |
| 21 | **The test suite reaches the network.** | hermeticity | `tests/conftest.py` blocks every non-loopback connect and fails closed on hostnames. | Every fetcher test uses loopback servers and a monkeypatched resolver; the address classifier is monkeypatched to accept loopback only in the pinned-connect test. |

## Numbering and gates

ADR-0124 is free (0122 merged; 0123 is the token record on its branch;
W5 is parked with no branch). The fetcher's board row needs the count
sentence in `docs/65-open-work.md` bumped. `tests/unit/test_risk_constant_pins.py`
will refuse untriaged module constants in a new risk-tier module: triage
each. The transport-guard scan's allowed set must stay unchanged by the
fetcher (it must satisfy the scan, not be exempted from it).

## Recorded after review round 2 (advisory, not fixed)

- A complete page sent with no `Content-Length` and no chunking on a
  connection the server keeps open is reported `timeout` after the per-read
  timeout, with its text dropped: HTTP/1.1 says such a body ends only at
  close, so the page never finished. Defensible; revisit if real citations
  hit it.
- A lookup that outlives the budget leaves its daemon thread running until
  the OS resolver returns. Within one call at most one is left (the shared
  deadline skips the rest); across concurrent calls nothing caps them. The
  wiring pull request, which puts the fetcher on a request path, should add
  a cap.
