# W87-3 follow-up: how the five changes can fail (written before any design)

> Published with the W87-3 follow-up (CHG-088, ADR-0176 amendment of 2026-10-25) as the
> session's record of the failure modes listed before any design. Unchanged except that
> local folder paths were removed. One count here was corrected by the plan: the bound was
> stated 10 times in **5** files, not 6 (the files listed below are those 5). Review round 1
> corrected FM-1.4's call-site count (12, not 15) and added the last section, which defines the
> labels the code, the tests and ADR-0176's amendment use for modes found after this list.


Role: failure modes, read-only. Written 2026-10-25. Tree: a read-only copy of
the tree. It has no git metadata. Its five session files are byte-identical to
`c40159e` (measured: `git show c40159e:src/product_app/<f>.py | shasum` against the copy, for `auth`,
`end_sessions`, `google_signin`, `main` and `session_store`. All five gave equal hashes.) Nothing
was written to any repository. One side effect: running Python against the copy probably created
`src/product_app/__pycache__/` there (its timestamp is 06:43, the time of my first probe). I did not
delete it, because the rules let me delete only folders prefixed `fm-` that I made. No server was started and nothing was sent to production. The probes
ran the real ASGI app in-process (FastAPI `TestClient` / `httpx.ASGITransport`), with Python 3.12.13
and SQLite 3.50.4.

Legend: **M** = measured, with the command named in "Measurements". **R** = read with `grep -n` or
`sed -n` at the file:line given. **U** = UNVERIFIED, with the check that would settle it.

## Measurements (commands and what they printed)

Probe scripts were kept in a scratch folder outside the repository
(`probe.py`, `threads.py`, `logs.py`) and are not published. Each script asserts that it imports
`product_app` from the copy. The run command, from the copy, was
`FMDIR=<fm-probe> .venv/bin/python -I -c "import sys; sys.path.insert(0,'src'); exec(open('<script>').read())"`.

- **P1 `probe.py`.** A signed-in cookie, with the cutoff read forced to `(False, None)`, the value
  `sessions_valid_after` returns when the store is not ready or its lock times out.
  ```
  healthy signed-in API: 200
  API while unreadable: 401 SESSION_EXPIRED
  idle poll while unreadable: 401 SESSION_EXPIRED
  GET /v1/session while unreadable: 200 | sets cookie: True | new id: True | body keys: ['anonymous', 'csrf_token', 'expires_at']
  HEAD /ui while unreadable: 405 | sets cookie: False | new id: False | cache-control: None
  GET /ui while unreadable: 200 | sets cookie: True | new id: True | cache-control: None
  cached copy kept: True | last_used moved: False
  after recovery, original cookie: 200
  ```
- **P2 `threads.py <bound> <hold> <n>`.** The store lock is held for `hold` seconds. `n` signed-in
  requests run at once, plus one `/ready` 0.3 s later.
  ```
  threads=40 bound=1.0s hold=8.0s signed_in_requests=45 codes={401: 40, 200: 5} slowest=8.04s /ready=200 in 7.71s
  threads=40 bound=6.0s hold=8.0s signed_in_requests=45 codes={401: 40, 200: 5} slowest=8.01s /ready=200 in 7.70s
  threads=40 bound=6.0s hold=8.0s signed_in_requests=10 codes={401: 10} slowest=8.02s /ready=200 in 0.01s
  threads=40 bound=6.0s hold=3.0s signed_in_requests=45 codes={200: 45} slowest=3.04s /ready=200 in 2.71s
  ```
  (load average 8.1, from `uptime`.) `threads=40` is anyio's default thread limiter, printed by
  `anyio.to_thread.current_default_thread_limiter().total_tokens`. The library versions are the
  `.venv`'s (starlette 1.3.1, fastapi 0.137.2). That the production image has the same limit is
  **U**: it follows from `uv.lock`, but was not run in the image.
- **P3 `logs.py`.** WARNING lines per cause of a refusal, with the account's email planted:
  ```
  not ready: 5 requests -> 5 x 401, 0 WARNING lines, ids in them: False
  lock timeout: 1 request -> [401], 0 WARNING lines
  failed read: 5 requests -> 5 x 401, 10 WARNING lines, ids in them: False, distinct: ['session_store: could not read a sessions cutoff: disk I/O error']
  ```
- **P4 SQLite busy shape.** A second connection with a 0.2 s timeout, against `BEGIN IMMEDIATE` /
  `BEGIN EXCLUSIVE`. Under IMMEDIATE, a read is OK and `BEGIN IMMEDIATE` raises `OperationalError |
  database is locked | 5 SQLITE_BUSY`. Under EXCLUSIVE, both the read and `BEGIN IMMEDIATE` raise the
  same.
- **P5 stdout encoding.** Printing `'/data/\udcff'` into a pipe: stdout errors=`strict` raises
  `UnicodeEncodeError is OSError: False`; stderr errors=`backslashreplace` prints it.
- **Config (R).**
  - `Dockerfile:89-95` runs `uvicorn ... "--workers", "1"`.
  - `fly.toml:183-188` has an http check on `/ready` every 30 s with a 5 s timeout.
  - `fly.toml:173-176` has connections hard_limit 100.
  - `fly.toml:196` is `shared-cpu-1x`.
  - `fly.toml:138` sets `SESSION_DB_PATH = "/data/sessions.sqlite3"`.
- **Sweep for the bound (R).** `grep -rn SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S` plus a regex sweep for
  "1.0 s / 1 s" near "cutoff|lock". The number appears in these places:
  - `session_store.py:99` (the rationale) and `:105` (the constant);
  - ADR-0176 `:105`, `:109` and `:171` ("the 1 s bound");
  - `docs/41-security-controls.md:59` ("at most 1 s");
  - `docs/analysis/2026-10-20-w87-3-end-sessions-failure-modes.md:50` and `:60`;
  - `tests/security/test_signed_in_cutoff_on_cache_hits.py:508` (docstring) and `:510` (`== 1.0`).

  That is **10 statements in 6 files**. The constant is also named, without the number, at
  `auth.py:497/506`, `tests/unit/test_risk_constant_pins.py:237` and
  `tests/test_doc_gate_consistency.py:1535-1600`. The D5 gate's own planted literals (`actual=1.0`,
  `2.5`) are test inputs, not statements. **DEPLOY.md states no cutoff bound.** `grep -nE
  "busy|5 s|locked" DEPLOY.md` finds only `:343`, the command's "locked for more than 5 s".

## Premises in the plan, checked

| Premise | Verdict | Evidence |
|---|---|---|
| "API requests keep the 401 refusal" | **FALSE for `/v1/session`.** It is an API request, and it does not refuse. It mints a counted anonymous session, sets a new cookie and answers `anonymous: true` (P1). Fixing `/ui` alone still loses the cookie on the page's own boot call (FM-1.2). | P1; `main.py:2068`, `:2136`; `app.js:8399` |
| `/ui` code at `auth.py ~1630-1691` | True. `issue_or_resume_session` is lines 1630-1691, and it mints at `:1679`, `:1689` and `:1691` | R |
| The post-Google refusal at `google_signin.py ~758` and `session_store.py ~1236` | True. `exchange_code` is at `:759`; `account_not_recorded` is at `:764/:782/:804`; the flag check is at `session_store.py:1236`. `_start` (`:657-708`) has 0 lines matching `store|ready|available` | R (`grep -c` printed 0) |
| "The refusal logs nothing" (implied by "today neither does") | **Partly false.** A *failed read* already logs, twice per refused request and with no rate limit. Not-ready and lock timeouts log nothing | P3 |
| `/ready` has only environment, live_readiness, status | True | `main.py:1500-1527` |
| Sweep "ADR-0176, docs/41, DEPLOY.md, tests, failure modes" | DEPLOY.md does **not** state the bound. The count is 10 statements in 6 files (above) | R |
| 6 s is "just above the command's 5 s busy timeout" | The value works, but the reason names the wrong timeout. What holds the **store lock** is the *app's own* write waiting on its connection's busy timeout. That timeout is the implicit `sqlite3.connect` default of 5.0 (`session_store.py:423-427`, no `timeout=`), not `end_sessions.COMMAND_BUSY_TIMEOUT_S`. No test ties the two together (FM-5.2) | R |
| `docs/103-incident-learnings.md` holds the past sign-in incidents (named in my brief, not in the plan) | **False.** `grep -c -iE "session\|sign-in\|511" docs/103-incident-learnings.md` printed `0`. #511 is in ADR-0131, and the recurring-id lesson is in the session memory, not in docs/103 | R |

## 1. `/ui` keeps a signed-in cookie it could not check

| ID | What goes wrong | Who it hurts | Where | Source | Test that catches it (red when) |
|---|---|---|---|---|---|
| 1.1 | "Could not check" resumes the session: it renders signed in, is touched, or serves the cached copy. That is the fail-open the owner refused. | Attacker gains access with an ended cookie | `auth.py:508`, `:1665-1689` | CHG-083 (a) | While unreadable, `/ui` has no account email, no "Sign out" and no CSRF, and `/v1/query-runs/active` is 401. Partner: the same cookie after recovery shows "Sign out". Red when the friendly path calls `touch` or `_issued`. |
| 1.2 | **`/v1/session` still mints.** Fixing `/ui` alone fails in two ways. If the friendly page is the workspace template, its boot runs `initSession` (`app.js:8399`) → `/v1/session` mints and replaces the cookie. And a page that `/ui` resumed a moment earlier can get the refusal on its `/v1/session` call. | Signed-in user (cookie lost, one of the 2 daily mints spent) | `main.py:2068`, `auth.py:1684-1689` | **M (P1)** | GET `/v1/session` with an unreadable signed-in cookie: no `Set-Cookie`, no mint row (assert the mint-event **count** is unchanged, rule 6b), and a non-200. Red today (P1 prints 200 with a new cookie). |
| 1.3 | Two reads per load, and the second one fails. `get` reads OK (`:1665`), then `touch` → `get` reads again and fails → `resumed is None` → mint (`:1679`). The rotate path does the same (`:1689`). Classifying only the first `get` leaves this path minting. | Signed-in user | `auth.py:1677-1689` | R | Make the cutoff read answer `(True, None)` once, then `(False, None)`. `/ui` must not mint. Red when only the first read is classified. |
| 1.4 | `get()`'s return type changes, to a sentinel or tuple. 12 call sites test `is None` (`git grep -cE "session_repository\.(get\|touch\|rotate_csrf)\(" c40159e -- src` printed 8 in `auth.py`, 3 in `google_signin.py`, 1 in `account_deletion.py`; this list first said 15, which counts `auth.py`'s own `self.get/touch/rotate_csrf(` calls too). A truthy "refused" object at `auth.py:1424` (`spend_meter_for`) or at `google_signin.py:745` **lets a refused session through** | Attacker (spend under an ended session; sign-in "recovery") | 12 sites in `auth.py`, `google_signin.py`, `account_deletion.py` | R | Keep `get()` returning `None`, and expose the reason through a separate call that only `issue_or_resume_session` uses. A mutation test returns a sentinel and expects every protected route to stay 401. |
| 1.5 | The page carries the session's token or id: a CSRF token in the HTML, or the session id echoed. | Attacker who can read the page (cache, extension) | `main.py:2224-2243` (the capped page embeds a token) | Plan; ADR-0131 | The friendly body contains neither `csrf_token` nor `session_id`. Red if the capped-page renderer is reused. |
| 1.6 | `Set-Cookie` on the friendly page. `attach_session_cookie` re-sets `max_age=SESSION_TTL`, which **extends the browser cookie's life**. `clear_session_cookie` would end it. | Signed-in user (logout); or an ended cookie lives longer | `auth.py:1609-1627`, `main.py:2318` | Plan | No `Set-Cookie` header at all. Partner: a normal load has one. |
| 1.7 | The friendly path extends the session's life server-side (`_use_locked` sets `last_used_at`, or a persist touch). An ended or stolen cookie then never idles out. | Attacker (an ended cookie kept alive) | `auth.py:541-565` | Plan | `last_used_at` and the durable row are unchanged after N friendly loads. Partner: a normal load moves it. P1 shows it does not move today (`last_used moved: False`). |
| 1.8 | "Ended" is classed as "could not check". `_restore` returns at `:701` (not ready) **before** the 12-hour check and before `_before_cutoff_locked`. A signed-in row 12-24 h old (`fetch` admits it up to `ANONYMOUS_MAX_AGE`, `:677-681`) then gets "briefly unavailable" though it has certainly ended. | Visitor (misleading page; must still sign in) | `auth.py:692-731` | R | A 13 h old signed-in row while not ready gets the ended path, not the friendly page. Red if the classification takes the `:701` exit before the age check. |
| 1.9 | The page is stuck for good. Some "could not check" causes never clear: a missing migration marker (until a restart, per ADR-0176 Known limits), a malformed `sessions_valid_after` (`_require_aware` fails, `session_store.py:699-702`; `MAX(...)` keeps a malformed value that sorts high, so the command cannot repair it), or a closed store. "Try again in a minute" is then false, and the visitor has no anonymous fallback short of clearing cookies. | Visitor; operator (no tell) | `session_store.py:676-702` | R; ADR-0176 | Plant a malformed cutoff. The page must not promise a minute (or must say something true), and the log/`/status` must show it. Owner wording question: is "try again in a minute" approved text? **U**. `owner-answers.md` holds only the option labels. |
| 1.10 | The classification takes unbounded locks. Reusing `session_ended`/`end_reason` (`auth.py:753`, `:771`, `:777`, with `fetch` and `sessions_valid_after` called **without** `lock_timeout`) to tell the two apart hangs `/ui` for the whole hold, and it conflates them anyway (`end_reason` gives `SESSION_EXPIRED` for both). | Every visitor (threads, FM-5.3) | `auth.py:733-794` | R; ADR-0176 Known limits | `/ui` behind a store-lock hold longer than the bound answers within bound + ε. Red if it calls `end_reason`. |
| 1.11 | An anonymous cookie gets the "account" page. An anonymous row whose kind lookup fails (`has_no_account_row` → `None`) is refused at `:701` like a signed-in one, so the copy says "your account" to someone with no account. | Anonymous visitor | `auth.py:692-702` | ADR-0176 Known limits | The kind lookup fails → the friendly copy names no account (or the case is excluded on purpose, as a decided choice). |
| 1.12 | The idle reminder still says "signed out". The open tab's poller gets 401 on `/v1/session/idle` (P1), then shows "You were signed out after 120 minutes with nothing happening" and **stops polling** (`app.js:11811-11818`). The kept cookie is invisible to the visitor. | Signed-in user | `app.js:11805-11818`, `google_signin.py:928` | M (P1); availability.md | An e2e test on the signed-in lane: unreadable store → the poller shows no "signed out" sentence and keeps polling. Needs a code the page can tell apart, which changes CHG-083 (a)'s "Your session has expired" → **owner decision**. |
| 1.13 | No-store is missing. Today the anonymous `/ui` has **no** `Cache-Control` (P1: `cache-control: None`). A cached friendly page could be shown after recovery, or the cached normal page during the outage. | Visitor | `main.py:2314-2318` | M (P1) | The friendly response has `Cache-Control: no-store` (and `Retry-After` if it is a 503). |
| 1.14 | Status code and contract. A 503 on `/ui` is undocumented: `PAGE_RESPONSES` lists only 403 (`fetch_site.py`), and Schemathesis runs `status_code_conformance` (`tests/contract/test_api_contract_schemathesis.py:101`). | CI; API clients | `fetch_site.py` PAGE_RESPONSES, `openapi.yaml` | R | `make openapi-check` and `make api-contract` go red if it is undocumented. Note that Schemathesis never reaches the state, so a green contract run proves nothing here. |
| 1.15 | Order against W88. The friendly path must run after `cross_site_refusal` (`main.py:2267`). Otherwise a prefetch or another site's hidden load of `/ui` gets the friendly page (harmless) or, worse, reaches the new code before W88's refusal. | Visitor | `main.py:2264-2269` | W88 (CHG-067) | A cross-site `Sec-Fetch-Dest: image` load with an unreadable signed-in cookie still gets the W88 403. |
| 1.16 | A repeated GET with no JS (#511). Something that fetches `/ui` again without running code (prefetch, extension) must change nothing. That holds if the friendly path writes nothing; any rotation, mint or touch repeats the #511 class. | Signed-in user | `main.py:2283-2288` | ADR-0131 | Two friendly GETs in a row leave the session row, the CSRF token and the mint count unchanged. |
| 1.17 | HEAD. Today it is 405, so it neither mints nor serves a page (P1). If a later change adds HEAD to `/ui`, it must follow GET's no-mint rule. | Visitor | `main.py:2260` | M (P1) | HEAD `/ui` stays 405, or it follows the GET rule. A pin test is cheap. |
| 1.18 | Under the CSP. The page's CSP allows inline script (`'unsafe-inline'`, `main.py:883-886`). So a friendly page *can* run script, which is the risk (FM-1.2), not a protection. A meta refresh is not blocked either; an auto-retry every N s from many tabs is fine, but each one goes through FM-5.3. | Visitor | `main.py:883-903` | R | The friendly page has no `<script>` and does not load `app.js`. That can be asserted on the body, as W88's refusal page is. |
| 1.19 | A test seam reaches production. An e2e journey needs "could not check". A seam in `src` or behind an env var could make production fail closed (or open). | Everyone | `e2e/servers/signed_in_server.py` (the precedent: in-process, test-only) | ADR-0142; `tests/unit/test_age_sessions_is_test_only.py` | Extend the test-only guard to the new seam. |
| 1.20 | A wrong count passes the test. Asserting only "no new cookie" misses an in-memory mint, such as a sign-in-only session from the capped path. | Visitor (the 2 daily mints) | `main.py:2224-2231` | AGENTS.md rule 6b | Assert `len(session_repository._sessions)` and the mint-row count: equal before and after. |

## 2. Sign-in checks the store before sending the visitor to Google

| ID | What goes wrong | Who it hurts | Where | Source | Test (red when) |
|---|---|---|---|---|---|
| 2.1 | The final guard is dropped. Readiness flags only rise (`refresh_readiness`, `session_store.py:993-1013`, "Never lowers a flag"), so ready → not-ready cannot happen within a process. But the upsert still fails on `BEGIN IMMEDIATE` busy (5 s), on a closed store at shutdown, or after a restart between start and callback. The callback guard (`:1236`) must stay. | Signed-in user ("did not complete" or a half-made session) | `google_signin.py:762-782` | Codex §2; R | Keep the test that the callback with a not-ready store returns `account_not_recorded` and writes 0 account rows. |
| 2.2 | The pre-check takes the store lock unbounded. Calling `refresh_readiness()` on the request thread runs `with self._lock` (`:1005`) plus 2 SELECTs and a PRAGMA, so the start hangs during a hold. | Visitor; thread pool | `session_store.py:993-1013` | R | Start behind a held store lock answers within a bound. Read the flags only (`accounts_available()`, `cutoffs_available()`), or use an acquire with a timeout. |
| 2.3 | Free probes or limiter spend. Placed before the limiter (`google_signin.py:688`), a pre-check that reads the DB is an unthrottled read per request. Placed after it, a refused start spends a start token the visitor needs a minute later. ADR-0175's precedent: refusals go "before the limiter, so a refused start spends nothing". | Visitor; store | `google_signin.py:657-708` | ADR-0175 decision 4 | Assert the order: a not-ready start leaves `sign_in_start_limiter` untouched and makes 0 store statements. |
| 2.4 | An oracle. The start's answer tells any cookie holder whether the store is ready. That gives nothing beyond `/status` once change 3 ships (public, `main.py:1531`). An attacker cannot make the store unready remotely (availability.md: routine holds 0.03-1.7 ms, the largest 0.69 s). | Attacker (low) | — | availability.md | None needed. Record it as accepted. |
| 2.5 | The page cannot show it. A new status or code reaches `startGoogleSignIn` (`app.js:11473`) → `api()` throws → `ERROR_TITLES` has no entry → "Something went wrong". | Visitor | `app.js:908-929`, `:11473-11479` | R | A unit or e2e test: a not-ready start shows "Sign-in is briefly unavailable", not the generic title. |
| 2.6 | Undocumented status. A 503 on `/v1/auth/google/start` is missing from `_DOCUMENTED_ERRORS` (`google_signin.py:552-563`) and from `openapi.yaml`. | CI | as cited | R | `make openapi-check`. |
| 2.7 | The deletion start shares `_start`. The pre-check also refuses `start-for-deletion`, and its copy says "sign in" while the visitor is deleting. (A signed-in visitor with an unreadable cutoff is already 401 at `_require_cookie_session`, `:640-654`, before any pre-check.) | Signed-in user deleting | `google_signin.py:716-720` | ADR-0175 | Both starts refuse while not ready, with wording that fits each. |
| 2.8 | Lock-held, not unready. The flags say ready while the lock is held past 5 s. The pre-check passes, Google runs, and the upsert gives up → "did not complete". The pre-check cannot promise success. | Visitor | `session_store.py:1236-1245` | P4; availability.md | Do not claim more than "not ready" in the copy. |

## 3. A rate-limited warning (no ids), and the store's readiness on `/status`

| ID | What goes wrong | Who it hurts | Where | Source | Test (red when) |
|---|---|---|---|---|---|
| 3.1 | The log goes only at the cache-hit guard. Not-ready begins only at process start (availability.md). After a restart every cache is empty, so the likely case is refused in `_restore` (`auth.py:701`, `:705-707`), and a guard placed only at `:508` logs nothing there. | Operator (blind) | `auth.py:508`, `:701`, `:706` | availability.md; R | After a restart with not-ready, one signed-in request → exactly 1 warning. Red with the cache-hit-only placement. |
| 3.2 | The existing flood stays. A failed read already logs **2 lines per refused request**, with no rate limit (P3: 5 requests → 10 lines). They come from `session_store._warn` (`:692` or `:701`) plus `end_reason`'s second read. Fly keeps 100 log lines (operator.md F-P1), so about 50 refusals erase the evidence. | Operator | `session_store.py:692`, `:701`, `:1183`, `:1449-1450` | **M (P3)** | 100 refused requests on a failed read → at most k lines (k fixed) in the window, and the count of suppressed refusals reported. Red today. |
| 3.3 | The rate limiter races. 40 request threads refuse at once (P2: `codes={401: 40}`). A check-then-set with no lock logs up to 40 lines. | Operator | new code | P2; general | A barrier of 40 threads → exactly 1 line (cardinality, rule 6b). |
| 3.4 | Ids or email in the line, or in the exception text. `_refused_by_durable_cutoff` holds `session.account_id`. `_warn` interpolates `str(exc)`, which for SQLite is fixed text today (P3: `disk I/O error`, no ids). `exc_info=True` would send a traceback, and Sentry captures locals unless redacted (`main.py:328-380`, `tests/security/test_w56_nothing_private_reaches_sentry.py`). | Signed-in user (privacy) | `auth.py:481-513` | ADR-0130 decision 9; W56 | Plant an email, account id and session id; none appears in any captured record (P3's leak check is the shape). Partner: the line IS emitted. |
| 3.5 | The rate-limit state is per process. With `--workers 1` (Dockerfile:92) that means per machine. It resets on restart, so the first refusal after each boot logs. Good: the boot case is the likely one. The command runs as its own process and never imports `auth`, so it neither logs nor sees the state. Use `time.monotonic`: a wall-clock step back would silence the log for that long. | Operator | new code | R | A unit test with a fake monotonic clock: 1 line, then silence for the window, then 1 line with the suppressed count. |
| 3.6 | `/status` leaks a path or an error. `/status` is public and unthrottled. Its docstring promises no paths (`main.py:1531-1541`). `_configure_session_store` logs `exc` text that can name the path (`main.py:831-837`), and reusing that text, or `str(exc)`, leaks it. | Attacker (recon) | `main.py:1531-1930` | `tests/security/test_operations_info_leak.py:47` (the pattern) | A test with a distinctive store path asserts it is absent from `/status`, and the field is one of a fixed set of values. |
| 3.7 | `/status` takes the store lock. A field computed by `_readiness_from_schema` or `refresh_readiness` locks and reads on a public endpoint. It hangs while the lock is held, and `/ui/ops` polls `/status`. | Operator; thread pool | `session_store.py:952-991` | R | `/status` behind a held store lock answers in < 0.5 s. Read `cutoffs_available()` (a bool, no lock) only. |
| 3.8 | One boolean says "ready" while every signed-in request is refused by **lock timeouts**, which change no flag. The operator is misled. | Operator | `session_store.py:676-679` | R | Report refusal counts by cause (not_ready, lock_timeout, read_failed, closed), per process, as `cross_site_refusals` does (`main.py:1924`). |
| 3.9 | "No store" reads as "not ready". `get_store()` is `None` after a failed open (`main.py:828-837`). That fault needs a different fix (a restart), and `/status` already separates `disconnected` from `degraded` for the feedback store. | Operator | `main.py:1671-1675` (the precedent) | R | Three distinct values for absent, not ready and ready. |
| 3.10 | Readiness goes on `/ready` or changes its status. Fly's http check uses `/ready` (`fly.toml:183-188`). A non-200 for a sign-in-only fault could take the single machine out of routing, turning a sign-in outage into a full one (**U**: Fly's routing on a failed check, for one machine). | Every visitor | `main.py:1499-1527` | R | `/ready` stays 200 with the store not ready. |
| 3.11 | Contract drift. The `/status` docstring is `openapi.yaml`'s description (`openapi.yaml:312`). Editing it without `make openapi-export` turns `openapi-check` red. | CI | `openapi.yaml:307-320` | R | `make openapi-check`. |

## 4. The command: "busy, run it again"; `--all` with 0 accounts

| ID | What goes wrong | Who it hurts | Where | Source | Test (red when) |
|---|---|---|---|---|---|
| 4.1 | Busy is matched on the message text. `"locked" in str(exc)` also matches SQLite's "database **table** is locked" (SQLITE_LOCKED, a different fault). P4: busy is `sqlite_errorcode == 5`, `sqlite_errorname == 'SQLITE_BUSY'`. | Operator (told to re-run a broken file) | `end_sessions.py:228-232`, `:266-269` | **M (P4)** | Match `sqlite_errorcode` 5. A test with a real held lock → "busy". A partner with another `OperationalError` (a directory as the path) → not "busy". |
| 4.2 | Busy is caught at only one place. It can surface at the marker read (`:225-232`, under EXCLUSIVE per P4), in the write transaction (`:240-269`), or in the read-back (`:307-321`). | Operator | `end_sessions.py` as cited | M (P4); operator.md | One held-lock test per place. |
| 4.3 | **"Nothing was changed" printed after the commit.** A busy read-back (`:319-321`) comes after `COMMIT` (`:265`), so a generic "busy, run again. Nothing was changed." helper there would lie. The cutoff IS written, and the exit is 4. | Operator (thinks the thief is still in, or that it is safe to give up) | `end_sessions.py:270-282` | R; ADR-0176 decision 2 | Hold the lock between commit and read-back → exit 4, the text does not contain "Nothing was changed", and the stolen cookie is 401. |
| 4.4 | The exit codes move. Making "busy" a new code breaks DEPLOY.md's table (`:343`: exit 3 includes "locked for more than 5 s") and any operator habit. Keep 3, or amend ADR-0176 decision 3 and DEPLOY.md in the same PR. | Operator | `end_sessions.py:36-42`, DEPLOY.md:343 | ADR-0176 decision 3 | A table-driven test of every exit path and code, plus a doc check that DEPLOY.md's table lists the same codes. |
| 4.5 | `--all` with 0 accounts exits non-zero **after** the commit, or says "Nothing was changed" after committing. With 0 accounts both statements change nothing, but the check belongs before `COMMIT`, with a `ROLLBACK`, as `--email`'s exit 1 does (`:255-260`). | Operator | `end_sessions.py:241-265` | R | `--all` on a migrated store with 0 accounts → the chosen code, 0 statements committed, and the path printed. Partner: 1 account → exit 0. |
| 4.6 | A real 0. A production store where nobody has signed in yet is legitimately 0. A non-zero exit then reads as "failed". The message must say "no signed-in accounts in <path>". | Operator | same | security.md D1 | The text assertion above. |
| 4.7 | The printed path crashes the run. `_write` catches only `OSError` (`:146-154`). A path that does not decode (P5: `UnicodeEncodeError is OSError: False` on a pipe's stdout) raises after the commit → traceback → exit 1, which is the "no account matched" code. | Operator | `end_sessions.py:139-154` | **M (P5)** | `SESSION_DB_PATH` with an undecodable byte → the exit code still matches what was done. Print the path to stderr (backslashreplace), or catch `UnicodeError`. |
| 4.8 | Printing the path changes ADR-0176 decision 4 ("Counts and the cutoff only"). It needs an amendment. The path comes from the environment, not from typed input, so the "never echo input" rule holds only if usage errors still print the fixed sentence. | Process | ADR-0176:90-96 | ADR-0176 | The existing usage-error tests stay green: no argument echoed, no path. |
| 4.9 | `--email` against a wrong but set path still matches (security.md D1: exit 0, the session still served). Printing the path only for `--all`-0 leaves this case blind. | Operator; attacker keeps access | `end_sessions.py:283-293` | security.md D1 | Advisory: print the resolved path on every outcome. |

## 5. `SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S` 1.0 → 6.0 s

| ID | What goes wrong | Who it hurts | Where | Source | Test (red when) |
|---|---|---|---|---|---|
| 5.1 | A statement is missed in the sweep. There are 10 statements in 6 files (above). The D5 gate (`tests/test_doc_gate_consistency.py:1539-1590`) checks 6 of them by pattern. It does **not** check `session_store.py:99`'s rationale, the test docstring at `:508`, or ADR-0176's reasoning at `:111-112` ("well under the 5 s a stuck write can take"). At 6.0 s that sentence becomes false, and no gate reads it. | Readers; the next reviewer | as listed | R; AGENTS.md rule 1a | Re-run the grep in the PR and print the count. Review the rationale prose (rule 11a). |
| 5.2 | The reason names the wrong timeout (see Premises). If someone later changes `COMMAND_BUSY_TIMEOUT_S`, or gives the app's connection an explicit `timeout=`, the "just above" relation breaks silently. | Signed-in user (false sign-outs return) | `session_store.py:423-427`, `end_sessions.py:65` | R | A test that `SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S` exceeds the app connection's busy timeout. That needs the timeout made explicit first, because today it is an implicit default. |
| 5.3 | **The thread pool runs out, under both bounds.** 45 signed-in requests behind an 8 s hold kept `/ready` waiting **7.71 s at 1.0 s and 7.70 s at 6.0 s** (P2). Fly's check times out at 5 s. The cause is the unbounded 401 reason lookup, which waits the whole hold under either bound. 6.0 s does not make it worse, and it does not fix it. With 10 requests `/ready` took 0.01 s. | Every visitor; health check | `auth.py:753-779` (unbounded); `Dockerfile:92`; anyio 40 | **M (P2)** | Record it as a known limit in the ADR amendment. A test: N > 40 refused requests behind a hold, `/ready` latency recorded. Fixing it means bounding `end_reason`, which is out of scope unless the owner widens it. |
| 5.4 | Raising the bound, against change 1. Once change 1 makes `/ui`'s friendly path bounded (FM-1.10), a held lock costs `/ui` up to 6 s instead of 1 s. That is new latency on the page only. | Visitor | — | inference from FM-1.10 and P2 | Measure `/ui` latency behind a 3 s hold at 6.0 s in the PR. |
| 5.5 | The lock is not fair. Python's `RLock` gives no FIFO order (general, CPython). Two queued app writes, each waiting about 5 s on SQLite, can make the cutoff read lose twice and refuse at 6 s although the lock was free in between. **U** in this repo. | Signed-in user | `session_store.py:678` | general | Two writers each holding the lock 3.5 s back to back, then a reader with a 6 s bound: record the outcome (an inherited `exp1` style probe). |
| 5.6 | The pin and its docstring. `tests/security/test_signed_in_cutoff_on_cache_hits.py:510` (`== 1.0`) must become 6.0 with a new reason. Its docstring (`:508`) repeats the refuted reason. `test_risk_constant_pins.py:233-237` gives the reason "shorter signs people out under routine holds"; it should now name the busy-timeout coupling. | Readers | as cited | R | The pin goes red at the change (intended). Review its new text. |
| 5.7 | Timing tests inherit the real bound. Tests that use the real constant and wait on bounded joins (`WAIT = 5.0`, `:50`) now finish their refusal at 6 s, past 5.0, and can fail or hang to the join timeout. The tests at `:200` and `:385` monkeypatch 0.05 and are safe. | CI | `tests/security/*.py` | R | Run the three timing files 10× at load (ADR-0176's own practice), as the plan's PR requires. |

## Totals and the five most serious

**55 failure modes** (`grep -c "^| [1-5]\.[0-9]* |"` on this file printed 55): 20 for change 1,
8 for change 2, 11 for change 3, 9 for change 4 and 7 for change 5. One of them, 2.4, is accepted
and needs no test. Most serious:

1. **FM-1.2**: `/v1/session` mints and replaces the cookie for an unreadable signed-in cookie (P1).
   The plan's "API requests keep the 401" premise is false there, so a `/ui`-only fix still loses the
   cookie on the page's own boot call.
2. **FM-1.4**: changing `get()`'s return type. A truthy "refused" value at any of 12 `is None` sites
   (for example `auth.py:1424`, the spend key) fails open.
3. **FM-1.3**: `/ui` reads the cutoff twice (`get`, then `touch`). The second refusal falls into the
   mint at `auth.py:1679`.
4. **FM-4.3**: a "busy, run again — Nothing was changed" message reused at the read-back would lie
   after the commit (exit 4).
5. **FM-5.3 / FM-1.10**: 45 requests behind an 8 s hold kept `/ready` waiting 7.7 s under both bounds
   (P2). The friendly page must not add unbounded reads.

Owner decisions this list surfaces (not the session's to make): whether the API's 401 gets a code
the page can tell apart, so the idle poller stops saying "signed out" (FM-1.12, which touches CHG-083
(a)'s "Your session has expired"); and whether "try again in a minute" is approved wording when some
causes never clear (FM-1.9).

## Labels added after this list

The plan, its review by Codex, and the build added these. The code, the tests and ADR-0176's
amendment refer to them by these labels.

| Label | What it is | Where it is handled |
|---|---|---|
| FM-1.21 | A session-row read that fails (`sqlite3.Error`, or a closed store) was read as "no row", so the page minted over the cookie. | `SessionStore.fetch_checked`; state S8; T18 |
| FM-1.22 | No store object at all (it failed to open at start): a presented cookie mints. Same as Codex F1. | The owner kept today's behaviour, CHG-088 (g); state S16; T60 |
| FM-1.23 | A later cutoff read's refusal was ignored: `/ui`'s two time-left helpers and the idle route's write-through read again. Same as Codex F2. | The helpers and `flush_session` take the session already checked; T3, T3b |
| FM-1.24 | A cached session known to have ended became "unchecked" when the store then failed. Same as Codex F3. | The ended list; the expiry re-check after a failed read; states S17, S18; T7b, T7c |
| FM-5.8 | The run creation's admission check reads the cutoff inside the run store's lock, so the 6 s bound can hold that lock longer than the old 1 s. | Kept as a known limit; the durable check stays; T61 |
| Codex F1 | The plan's review: no state for a failed store open. | FM-1.22 |
| Codex F2 | The plan's review: later reads ignored. | FM-1.23 |
| Codex F3 | The plan's review: a known-ended session becomes unchecked. | FM-1.24 |
| Codex F4 | The plan's review: the sign-in start's bound was overstated, because the start's own authentication can save a due touch under the store lock first. | Recorded as a known limit; T20 and T23 test a fresh and a persistence-due session apart |
| Codex F5 | The plan's review: two planned tests passed for the defect they named (a text match for "busy"; "at most 2" log lines passing with 0). | T44 pairs a real `SQLITE_BUSY` with a real `SQLITE_LOCKED`; T33 requires exactly 1 line of each kind |
