# B1 — provider billing failure modes, enumerated before the code

**Status: evidence, not conclusions.** Produced 2026-08-26 by four read-only
agents over `d96e115`, each with its own `git archive` copy, deduplicated and
spot-checked by a fifth. It exists because AGENTS.md rule 16e asks for the
failure modes of money code to be listed on one page *before* the code is
written, and because the spend-cap work went five review rounds discovering
them one at a time instead.

**How to read it.** Only the modes this pull request acts on were re-verified by
hand at the keyboard; the rest carry each lens's own evidence and are marked
UNVERIFIED where no command settled them. Roughly half of what one agent
asserts does not survive another's check — three claims were refuted on
re-check and are listed first, deliberately, so a reader who copies from this
page copies the correction too.

**Nothing here is a commitment to build.** Several modes are out of scope for
the pull request that carries this file; they are recorded so the next session
starts from measurements rather than from a fresh guess.

---

# B1 — Failure modes to design against before writing code

**Scope.** `ProviderClient._post_messages` (`src/product_app/providers.py:1164`) and everything downstream of its four return values, on `d96e115`. Written for one builder, per AGENTS.md rule 16e.

**How this page was checked.** 38 candidate modes from four lenses, deduplicated to 19. Every mode marked CRITICAL_BLOCKER or REQUIRED_CONTRACT, and every mode a lens marked `verified: true`, was re-run by me against my own `git archive HEAD` copy at `/private/tmp/claude-501/-Users-rohitagrawal-Projects-quorum-ai/a71c5a66-65c1-486e-9233-5b5079c1fb79/scratchpad/dedup/tree`, driven by `/Users/rohitagrawal/Projects/quorum-ai/.venv/bin/python -B` (3.12.13) with `PYTHONDONTWRITEBYTECODE=1`. Nothing was written, run, or mutated under `/Users/rohitagrawal/Projects/quorum-ai`; `git status --porcelain` at the end shows only the two pre-existing untracked prompt files. No network call left loopback. No money.

---

## Three lens claims that did NOT survive my check

Read these first — a builder who copies them writes a wrong test.

**R1. "`finish_reason` values `error`, `content_filter` and `tool_calls` appear nowhere in src or tests" — PARTLY REFUTED.**
`content_filter` IS covered: `tests/unit/test_providers.py:382` — `({"choices": [{"finish_reason": "content_filter"}]}, "a non-length reason")` inside `test_malformed_payloads_never_assert_truncation`, which deliberately asserts it is NOT truncation. Only `"error"` and `"tool_calls"` are genuinely absent (`git grep -n 'finish_reason.*"error"' -- src tests` → exit 1; `git grep -n 'tool_calls' -- src tests` → exit 1). Lens 1's `uniq -c` table is also wrong on counts: my run of the same grep prints `32 finish_reason": "stop`, not 2.

**R2. "Every one of the evidence file's `_billing_evidence_shape` tests survives the blanket mutation" — REFUTED as stated.**
Under the mutation, `test_capturing_the_evidence_does_not_change_the_classification` FAILS on 6 of its 9 rows and `test_the_http_record_states_the_same_billing_class_it_returns` FAILS on 3. Those two DO bite and are the pattern to copy. (Lens 4's own notes say this; its finding text contradicts them.) The 78/103 headline itself is exactly right — see M-T1.

**R3. "HTTP 400 refused pre-inference → `http_calls=1`" — REFUTED.**
I measured **2** POSTs. The slot model id is suffixed `:online`, a 400 on `:online` returns `_SEARCH_REJECTED` at `providers.py:1234`, and `providers.py:1078` retries on the bare id. Verbatim from my `probeF.py`:
```
HTTP 503 (possibly billed):            posts=1 status=failed path=openrouter_search token_usage=None
HTTP 400 (provably unbilled):          posts=2 status=failed path=openrouter_search token_usage=None
200 EMPTY completion, 740+4096 stated: posts=1 status=failed path=openrouter_search token_usage=None
200 GOOD answer (CONTROL):             posts=1 status=completed path=openrouter_search token_usage=prompt_tokens=740 completion_tokens=300 total_tokens=1040
```
Do not pin `posts == 1` for a 4xx on an initial slot.

Everything else I checked reproduced, several to three decimal places.

---

## Ground truth you can build on (re-verified)

- **The measured/estimated switch is one four-way AND**, `_actual_cost` at `query_run_orchestration.py:2649`, decided at line 2753: `initial_fully_captured` (2715) AND `debate_captured` AND `synthesis_captured` (both `_stage_captured`, 2629) AND `judge_captured` (2748). Any false conjunct returns the pre-run estimate.
- **`_stage_captured` is vacuously True over an empty list.** Executed directly:
  ```
  NOT_ENTERED | empty list -> True | [None] -> True  | [usage] -> True
  ENTERED     | empty list -> False| [None] -> False | [usage] -> False
  RECORDED    | empty list -> True | [None] -> False | [usage] -> True
  ```
- **`cost_source` is the only thing that reaches the durable ledger.** `query_run_orchestration.py:1531`: `if response.cost_source != "measured": return` — above the `reconcile_run_charge` call.
- **`_UNBILLED_HTTP_STATUSES = frozenset({400, 401, 402, 403, 404, 429})`** (`providers.py:1672`), consulted in exactly one place: `providers.py:1251`, inside `except HTTPError`, i.e. strictly post-dispatch.
- **There is no SSE machinery anywhere in this repo.** `grep -c '"stream"' src/product_app/providers.py` → `0`, exit 1. `git grep -n "event-stream"` and `git grep -nF "[DONE]"` over `src` (minus `static/vendor`), `tests`, `docs` → exit 1 both. `"stream": true` is not a flag flip; it is a new reader, a new framing contract and a new timeout model.
- **Positive partner for every negative below** (`probeA.py` A13): a healthy 200 returns `LiveProviderResult(text='hello', usage=prompt_tokens=10 completion_tokens=5 total_tokens=15, trunc=False)`.

---

# The failure modes, worst money direction first

## A. UNDERSTATE — a real charge vanishes behind a `measured` label

### U1. A dispatched debate/synthesis/judge call answered 400/401/402/403/404/429 keeps the run `measured` and reconciles the ledger DOWN
**LIVE TODAY.** Merges: `measured-survives-unbilled-set` (Lens 3).
`_post_messages` returns `None` → `call_with_prompt` returns `None` → `debate.py:610/683` (`if round_one_live is not None:`) and `synthesis.py:579-589` (`if live is not None`) append **nothing**; the judge sets `NO_VERDICT_UNBILLED`, which `judge_captured` (`:2751`) explicitly forgives. `_stage_captured(RECORDED, all([]))` is **True** (measured above), so the run stays `measured` and `_reconcile_run_billing` **overwrites** the ledger with a total omitting the call.
Verified mechanically end to end at the `_stage_captured` and `:1531` seams. **The premise is not verified**: the comment at `providers.py:1247-1250` asserts these statuses are "refused before any token is generated" with no measurement behind it, and issue #105 already records that the 5xx half has none.
**UNVERIFIED · settling check:** a week of `upstream_provider_http_error` records with `billing_class=not_billed`, cross-referenced against the OpenRouter activity page. That is what #105 exists for. Do not widen or narrow the frozenset on a guess.

### U2. A partially generated answer is served as a complete one, priced, and labelled `measured`
**LIVE TODAY on the non-streaming route (trigger unverified); arrives again by a second route under `stream: true`.** Merges: `200-partial-with-inband-error` (Lens 1) + `stream-inband-error-then-done` (Lens 1).
`_finish_reason_indicates_truncation` (`providers.py:2035`) returns True only for the literal `"length"`. Measured, `probeA.py` A6:
```
A6 200 PARTIAL content + finish_reason=error + top-level error
   -> LiveProviderResult(text='half an ans', usage=..., trunc=False, sources=0)   events=[]
```
So a partial answer counts toward `live_count`, sits in the citation-coverage denominator, carries usage into `initial_fully_captured`, and the UI's `shortened` notice never paints. Nothing in the code looks at a top-level `error` coexisting with non-empty `choices`, nor at a `finish_reason` outside `{stop, length}`. Per R1, `content_filter` is at least tested as non-truncation; `"error"` and `"tool_calls"` are untested and unhandled.
**UNVERIFIED · settling check:** one authenticated POST to a model whose provider is forced to fail mid-generation, reading the status line and the `finish_reason`. Costs tokens; out of scope for a $0 lens.

### U3. A definitely-billed initial call throws away the provider's own usage number
**LIVE TODAY.** Merges: `empty-completion-usage-discarded` (Lens 3) + `200-length-empty-content` + `200-content-null-or-reasoning-only` (Lens 1).
`_post_messages` deliberately extracts usage before the emptiness check (F-06 finding C) — `probeA.py` A5 returns `usage=10/5/15, trunc=True`, A7 (`content: null` + `reasoning`) returns `usage=10/5/15`. Then `_live_openrouter_response` hits `if not is_visible(result.answer_text): return None` (`providers.py:1034`) and the usage is dropped. Measured through the real path (`probeF.py`): `200 EMPTY completion, provider stated 740+4096 → status=failed token_usage=None`.
Priced with the repo's own `costs.measured_call_cost_usd`: **$0.00256860** for 740+4096 on `openai/gpt-4o-mini`, against **$0.00029100** for a normal 740+300 — **8.83×**. The run falls to `estimated`, so the ledger permanently keeps a pre-run estimate that priced a normal completion, not a burnt cap.

### U4. `_post_messages` RAISES on `BaseException`, so a billed call is recorded nowhere
**LIVE TODAY; reachability UNVERIFIED.** Merges: `never-raises-holds-for-exception-not-baseexception` (Lens 2).
The "once `urlopen` is called this returns, it never raises" invariant holds for every `Exception` and breaks for `BaseException`. Measured (`probeE.py`):
```
urlopen raises KeyboardInterrupt      -> RAISED KeyboardInterrupt
urlopen raises MemoryError (CONTROL)  -> _DispatchedUnmeasured
read() raises KeyboardInterrupt       -> RAISED KeyboardInterrupt
```
`contextlib.suppress(Exception)` around `_log_call_token_shape` and `EvalJudge.evaluate`'s `except Exception` both miss `BaseException`, so a judge outcome could stay `None` — the state `_actual_cost` reads as "no judge fired" — while a billed call escaped. Initial answers run on a `ThreadPoolExecutor`, where SIGINT-driven `KeyboardInterrupt` reaches only the main thread, so production reachability is low but not argued to zero.
**UNVERIFIED · settling check:** drive a full run to a served receipt with a `BaseException` injected at the read seam and assert `cost_source`.

### U5. A second paid judge call after LRU memo eviction reaches no ledger at all
**LIVE TODAY (judge is ON in production).** `judge-memo-eviction-zero-record` (Lens 3). **UNVERIFIED by any lens** — reported from the code's own comments (`query_run_orchestration.py:1596-1601`, `_JUDGE_VERDICT_MEMO_MAX = 512` at `:1815`, eviction at `:2106`; `feedback_store.try_record_cost_reconciliation` refuses a second correction by design).
**Settling check:** fill the memo past 512 entries, re-GET an evicted run with a counting `call_with_prompt` double, assert `reconcile_run_charge` call count == 1 while provider dispatch count == 2.

### U6. STREAM ONLY — treating EOF as success serves a cut answer as complete
`stream-drop-without-done` (Lens 1). The **absence of `data: [DONE]`** is the only way to tell a completed stream from a truncated one; a stream ending after a normal content frame is byte-identical to one that was cut. Today this is neutral-but-lossy (`_DISPATCH_UNMEASURED`, usage discarded). **UNVERIFIED against OpenRouter specifically**; generic CPython behaviour is `IncompleteRead` / `RemoteDisconnected`, both already in `_EXPECTED_TRANSPORT_ERRORS` (`providers.py:1898`).

---

## B. OVERSTATE — a $0 or lost-usage outcome inflates the served receipt and the ledger

The shared mechanism, worth stating once: `_reconcile_run_billing` is the **only** thing that corrects the pre-run estimate booked by `try_record_run_charge`, and it fires only on a `measured` receipt (`:1531`). So a single call classified `_DISPATCH_UNMEASURED` anywhere in a run leaves the full pre-run estimate metered against the account's daily cap and the global ring, **permanently**.

### O1. A healthy HTTP 200 whose chunked body has an inter-chunk silence > 8s is thrown away — happening on `main` today
**LIVE TODAY. This is the most expensive mode on the page and it has nothing to do with streaming.** `live-200-chunked-slow-gap` (Lens 1).
`urlopen(..., timeout=T)` sets a **socket** timeout, applied per-`recv`, not cumulatively. Reproduced against a real loopback server serving 200 + `Transfer-Encoding: chunked` + a controllable mid-body gap (`probeB.py`):
```
CASE 200 chunked, mid-body gap 10s > timeout 8s: -> _DispatchedUnmeasured   wall=8.012s
CONTROL same body, gap 1s < timeout 8s:          -> LiveProviderResult(usage=100/2000/2100)   wall=1.003s
```
The control is what proves the case is the gap, not the harness. The repo's own live spike (`docs/analysis/2026-08-26-session-handoff.md:41-49`, 4 models × 2 reps, `max_tokens=2000`) measured max inter-chunk gaps of **5.722–25.055s** against `openrouter_timeout_seconds = 8.0` (`config.py:85`): **8 of 8 exceed it on wall clock, 6 of 8 on the per-`recv` gap**. Up to 2000 completion tokens are billed; the usage never reaches a row; the run is served `estimated`; and the user sees a FAILED slot (`PROVIDER_UNAVAILABLE`) for an answer they paid for. There is no distinguishing observation — the client never sees a body.
**UNVERIFIED · settling check:** how often it fires in production. Read `upstream_provider_transport_error` records with `error_type: TimeoutError` in `/data/telemetry-billing.jsonl` over `fly ssh console` — and note ADR-0031 flags that drain as not yet provisioned.

### O2. STREAM ONLY — an SSE body fed to today's parser fails 100% of the time, and a clean stream is indistinguishable from a broken one
Merges: `stream-sse-body-to-json-loads` + `naive-b1-proof-is-green-on-main` + `clean-stream-partner-is-red-today` (Lens 1 + Lens 4). **These three are one fact.**
Measured (`probeA.py`), both bodies through the real `_post_messages`:
```
A1 SSE clean stream (deltas + final usage + [DONE])
   posts=1 -> _DispatchedUnmeasured   events=['upstream_provider_body_unreadable']
A2 SSE 3 deltas then in-band error then [DONE]
   posts=1 -> _DispatchedUnmeasured   events=['upstream_provider_body_unreadable']
```
and at the `call_with_prompt` boundary (`probeE.py`) the SSE error stream, an HTTP 503 and a 200 error envelope are **bit-for-bit identical**:
```
SSE error stream:             -> LiveProviderResult(answer_text='', sources=[], usage=None, is_truncated=False)
HTTP 503:                     -> LiveProviderResult(answer_text='', sources=[], usage=None, is_truncated=False)
200 top-level error envelope: -> LiveProviderResult(answer_text='', sources=[], usage=None, is_truncated=False)
HTTP 401 (unbilled):          -> None
```
**Consequence for B1: the obvious bite-proof is already green on `main`.** A test that stubs 3 deltas then an error and asserts `call_with_prompt` returns a blank marker with `usage=None` passes today, before the code exists — so it cannot fail when a later real parser drops the error event and serves 3 deltas plus final-chunk usage as `measured`. That is the understate direction. The **only** assertion that bites is the clean-stream partner (A1), which is genuinely RED on `main`.

### O3. STREAM ONLY — keep-alive comments reset the per-`recv` timer, so `openrouter_timeout_seconds` stops bounding anything
`stream-keepalive-defeats-the-timeout` (Lens 1). This is the mechanism the 2026-08-26 handoff proposes as the FIX for #290; it is also the mechanism that removes the provider call's only wall-clock brake. Reproduced (`probeC.py`):
```
SSE keep-alive comment every 1s (timeout=2.0s) -> read OK, 187 bytes   WALL CLOCK = 6.055s
CONTROL: single 3s gap > timeout (timeout=2.0s) -> TimeoutError: timed out   WALL CLOCK = 2.003s
```
3× the nominal timeout, completing successfully. The only remaining bound is the run deadline in `query_run_orchestration.py`, whose own comment says the cut future "keeps running on its pool thread … its late answer is simply never recorded". `quorum_run_deadline_seconds` stops the RECORDING, never the BILLING.
**UNVERIFIED · settling check:** does OpenRouter actually send `: OPENROUTER PROCESSING`, and at what cadence? The string appears nowhere in this repo. One `curl -N` with a timestamped read settles it. The consequence above does not depend on the cadence being any particular number — only on it being shorter than the socket timeout.

### O4. A provably-$0 call is classified possibly-billed, permanently over-metering the ledger
**LIVE TODAY.** Merges: `predispatch-header-failure-reads-as-possibly-billed` + `connect-or-send-timeout-reads-as-possibly-billed` + `predispatch-raise-before-urlopen-escapes-the-function` (Lens 2).
Measured against a real loopback server counting connections and bytes (`probeE.py`):
```
ascii key (CONTROL): -> LiveProviderResult   | conns +1 bytes +279
key with U+2013:     -> _DispatchedUnmeasured | conns +0 bytes +0
key with newline:    -> _DispatchedUnmeasured | conns +0 bytes +0
URLError(TimeoutError):      -> _DispatchedUnmeasured  (billing_class=possibly_billed)
URLError(ConnectionRefused): -> None                   (billing_class=not_billed)
```
Zero bytes on the wire, classified possibly-billed. `Settings` sets no `str_strip_whitespace`, so a secret with a trailing newline survives into `Authorization: Bearer …` verbatim. The connect-timeout arm needs no misconfiguration at all — a transient network stall is enough. The code documents both tradeoffs honestly; the point here is the ledger consequence, not the label.

### O5. STREAM ONLY — a `data:` frame split across two socket reads, and usage that only arrives in the final chunk
Merges: `stream-split-data-frame` + `stream-usage-only-in-final-chunk` (Lens 1). Measured, both directions (`probeD.py`):
```
read(63) returned 63 bytes: b'data: {"choices":[{"delta":{"content":"hello world"}}],"usage":'
  parses as JSON: NO -> JSONDecodeError Expecting value: line 1 column 58 (char 57)
readline() len=106: b'data: {"choices":[{"delta":{"content":"hello world"}}],"usag'...
  parses as JSON: YES
  next lines: b'\n' b'data: [DONE]\n'
```
A frame is terminated by `\n`, never by a byte count. The final chunk carrying `usage` is the largest and therefore the one most likely to be torn — so a byte-counting reader silently drops the run to `estimated` on a call that fully succeeded.
**UNVERIFIED · settling check:** does a streamed OpenRouter response carry `usage` at all without an explicit opt-in? One streamed request with and without a usage opt-in, diffing the final frame. If the opt-in is missing, **every** streamed run is `estimated` forever — which defeats the whole point of #378/#268's cost ledger.

### O6. HTTP 200 whose JSON body carries a top-level `error` and no usable `choices`
**LIVE TODAY.** Merges: `200-error-no-choices` (Lens 1) + `http200-error-envelope-returns-liveresult` (Lens 2).
Measured (`probeA.py`):
```
A3 200 top-level error, NO choices  -> LiveProviderResult(text='', usage=None, trunc=False)   events=[]
A4 200 top-level error WITH usage   -> LiveProviderResult(text='', usage=10/5/15, trunc=False) events=[]
A8 200 usage missing completion_tokens -> LiveProviderResult(text='ok', usage=None)
A9 200 body is a JSON ARRAY         -> LiveProviderResult(text='', usage=None)   events=[]
A10 200 empty body / A11 bare text  -> _DispatchedUnmeasured  events=['upstream_provider_body_unreadable']
```
Three things follow. (1) This shape returns a **real** `LiveProviderResult`, never the sentinel — its equivalence with `_DISPATCH_UNMEASURED` downstream is accidental, holding only while `call_with_prompt`'s one flattening line stays as it is. (2) An error framed as 200 can never become `_SEARCH_REJECTED` (that branch keys on `exc.code in (400, 404)`), so the `:online` → bare-model retry **never fires** for a 200-framed rejection. (3) `json.loads` succeeding is not the same test as the payload being a mapping, and the code splits on the first while behaving as if it split on the second — which is why a JSON array loses even the log record.
**UNVERIFIED · settling check:** does OpenRouter genuinely emit this non-streaming? One authenticated POST to a valid model id with no available provider, reading the status line. Note the branch is reachable regardless — a truncated-but-valid JSON object, a proxy's JSON denial page, and `{}` all land here.

---

## C. NEUTRAL on any single receipt — but they corrupt the evidence #105 will decide from

### N1. Two of the four `_DISPATCH_UNMEASURED` sites emit no `billing_class`, and neither reaches the durable billing file
**LIVE TODAY.** Merges: `billing-evidence-blind-spots` (Lens 3) + `http200-error-emits-no-billing-telemetry-at-all` (Lens 2) + `online-400-404-bypasses-the-set-and-the-log` (Lens 2). Measured (`probeE.py`):
```
HTTP 503                    -> upstream_provider_http_error      billing_class=possibly_billed
URLError(TimeoutError)      -> upstream_provider_opener_error    billing_class=possibly_billed
URLError(ConnectionRefused) -> upstream_provider_opener_error    billing_class=not_billed
bare TimeoutError           -> upstream_provider_transport_error billing_class=<ABSENT>
IncompleteRead              -> upstream_provider_transport_error billing_class=<ABSENT>
torn JSON body 200          -> upstream_provider_body_unreadable billing_class=<ABSENT>
HTTP 400 on :online         -> _SearchRejected                   events=[]        (NO log at all)
200 top-level error         -> LiveProviderResult                events=[]        (NO log at all)
```
`_log_post_dispatch_failure`'s `extra` is only `{"error_type", "model_id"}` (`providers.py:1934`). Separately, `telemetry_sink.BILLING_EVENTS` (`telemetry_sink.py:94-99`) is an allowlist of exactly `upstream_provider_http_error` and `upstream_provider_opener_error`, so transport and body-unreadable records are filtered out of the durable billing file entirely. Note **O1 is a `upstream_provider_transport_error`** — the most expensive live mode on this page is invisible in the very dataset that will re-tune billing classification. And because `:online` 400/404 returns before both the set and the log, the sample under-counts 400/404 for the majority of initial-answer calls.

### N2. On the initial-answer path the whole billed/unbilled classification is discarded
**LIVE TODAY.** Merges: `initial-path-erases-classification` (Lens 3) + `initial-answer-lane-cannot-tell-refused-from-unmeasured` (Lens 4).
`providers.py:969` — `if result is None or isinstance(result, _SearchRejected | _DispatchedUnmeasured): return None` — collapses the sentinel into the same `None` that means "provably $0". Measured (`probeF.py`, above): a 503 and a 400 both produce `status=failed path=openrouter_search token_usage=None`, indistinguishable. So `_DISPATCH_UNMEASURED` carries zero information past line 969, on the path that makes 4 of a run's ~8 provider calls. The direction is safe (both force `estimated`) but the classification buys nothing there, and no existing assertion separates "record no usage entry, stay measured" from "record an entry, force estimated".

### N3. The secret-leak guard at `test_provider_billing_classification.py:379` does not detect a real secret leak
**LIVE TODAY.** `caplog-text-secret-assertion-is-vacuous` (Lens 4). Reproduced: I planted `"detail": str(exc)` into `_log_post_dispatch_failure`'s `extra=` in my copy, purged `__pycache__`, and reran both files → `EXIT=0`, `103 passed in 4.80s`. Then `cp providers.py.orig` and `diff -q` against the real repo file → `RESTORED_AND_MATCHES_MAIN`.
`caplog.text` is rendered with `DEFAULT_LOG_FORMAT` and contains no `extra` fields at all, while `JsonFormatter` folds them into the production log. The sibling in the evidence file (`test_opener_failure_never_logs_the_exception_message`) fixed exactly this by walking `record.__dict__`; the classification file never got the walk. This matters directly for B1 because a stream-error branch will be tempted to add `"stream_error_message": ...`.

---

# WHAT B1 MUST ASSERT

Rule 6b: accounting code asserts **cardinality**, never a clean-path outcome. The seam to keep is `product_app.providers.urlopen` (the `_install` helper at `test_provider_billing_classification.py:100` and `test_provider_billing_evidence.py:120`; ~117 tests depend on it).

**On the error stream (3 deltas → in-band error → `[DONE]`):**

1. **Exactly 1 POST.** `posts[0] == 1`, never `>= 1`.
2. **Return identity at the `_post_messages` seam**, not at `call_with_prompt`: `result is providers._DISPATCH_UNMEASURED` (the singleton at `providers.py:1664`). Measured above: at `call_with_prompt` the SSE error stream, an HTTP 503 and a 200 error envelope are bit-identical, so an assertion there discriminates nothing.
3. **Exactly 1 usage entry, carrying `None`.** Debate: `len(live_call_usages) == 1 and live_call_usages[0][1] is None`. Synthesis: `len(...) == 1`. Never 0 (that is the vacuous `all([])` of U1) and never 2.
4. **Exactly 1 record of the NEW stream-error event AND exactly 0 `upstream_provider_body_unreadable` records.** This pair is the only thing that proves the new branch ran instead of the old one.
5. **Exactly 0 `_log_call_token_shape` records** (its one call site is `providers.py:1390`).
6. **`answer_text == ""` as a full-string equality**, never a `not in` substring check.
7. **`record["billing_class"] == "possibly_billed"` on that single record AND the return agreeing, in the same test** — the shape of `test_the_http_record_states_the_same_billing_class_it_returns`, which R2 confirms bites.
8. **Exactly 3 delta frames consumed before the error frame**, asserted on the stub's own read counter, so a parser that bails after frame 1 cannot pass.

**Positive partners — every negative above needs one (rule 7; 78 of 103 tests here are already satisfied by "nothing"):**

| Negative | Partner | Red on `main` today? |
|---|---|---|
| `answer_text == ""` | clean stream serves exactly `"Part one. Part two. Part three."` | **YES** — measured `answer_text=''` |
| `usage is None` | clean stream's final chunk yields `TokenUsage(4000, 700, 4700)` | **YES** — measured `usage=None` |
| 0 `upstream_provider_body_unreadable` | a genuinely unparsable non-SSE body still produces exactly 1 (existing `test_unparsable_body_is_reported_as_dispatched_unmeasured`) | no — passes today |
| `is _DISPATCH_UNMEASURED` (i.e. NOT `None`) | a pre-inference refusal over the SAME streaming transport (stream request + HTTP 401) still returns `None` and records ZERO usage entries | no — but without it the blanket mutation passes |
| 0 `_log_call_token_shape` on the error stream | exactly 1 on the clean stream | **YES** |
| no secret in the log | walk `record.__dict__` for every record, not `caplog.text` (N3) | n/a — the guard is the point |
| "it returns rather than raises" | assert the returned value's identity — the never-raises invariant is otherwise satisfied by any return at all | n/a |

**The mutation the suite must stop (M-T1).** Rewriting all 8 returns in `_post_messages` to `return _DISPATCH_UNMEASURED`, leaving `urlopen` and the POST counters intact, leaves **78 of 103** green. Reproduced exactly: baseline `EXIT=0, 103 passed in 4.89s`; mutated `EXIT=1, 25 failed, 78 passed in 4.94s`; per file `classification 15 failed / 36 passed`, `evidence 10 failed / 42 passed`. Surviving in bulk: 6 rows of `test_notice_provider_unavailable_never_claims_a_response_arrived_or_absent`, 4 of 5 rows of `test_initial_answer_path_reports_the_slot_missing_and_invents_nothing` (the one failure, `[http-404-outcome2-2]`, fails on POST cardinality, not classification), 5 rows of `test_the_body_content_is_never_logged`, 4 of `test_torn_body_is_reported_as_dispatched_unmeasured`. Your new test must be in the 25, not the 78.

---

# WHAT B1 MUST NOT DO

1. **Do not write the classification branch before running one free `curl`.** Whether OpenRouter under `stream: true` returns HTTP 200 + an SSE `data: {"error":...}` frame, or a plain HTTP error, is **UNVERIFIED** and it is the premise the whole package rests on. A bad key + `"stream": true` gives a 401 and costs no tokens. AGENTS.md rule 8c exists because the last mitigation gated on unmeasured upstream behaviour would have collected nothing in production while every gate stayed green. The same curl also settles whether the frame is `{"error": {...}}` at top level — if it is, `_billing_evidence_shape` (which already understands `error.metadata.provider_name`, three-valued) is reusable verbatim; if not, it is not.
2. **Do not write the "stub an error stream, assert a blank marker" test.** It is green on `main` today (O2). It passes before the code exists, so it cannot fail when a real parser later drops the error event and serves the prefix plus final-chunk usage as `measured`.
3. **Do not assert at `call_with_prompt`.** Measured bit-identical across three different upstream conditions. Assert `_post_messages`' return by identity.
4. **Do not build the test on `test_provider_billing_classification.py:119`'s `_http_error`.** Its `fp=None` makes `_billing_evidence_shape` return `{'body_shape': 'empty', 'body_bytes': 0, 'error_metadata_present': None, 'provider_name_present': None, 'provider_name_header': None, 'sniff_time_bounded': False}` — measured. Every HTTP-error test in that file exercises only the empty branch, and an SSE error event lives in the **body** of an HTTP 200, which that double can never express. Give it a real `io.BytesIO` body; the same call with one produces `{'body_shape': 'json', 'body_bytes': 88, 'error_metadata_present': True, 'provider_name_present': True, ...}`.
5. **Do not assert secret absence with `caplog.text`.** Proven vacuous against a real `extra=` leak (N3): 103 passed with `Bearer sk-or-v1-REALKEYMATERIAL` reaching `record.detail`. Walk `record.__dict__`.
6. **Do not pin `posts == 1` for a 4xx on an initial slot.** Measured 2 (R3) — the `:online` retry fires.
7. **Do not widen the classification so the happy path and the not-billed path fall into the sentinel.** That is mutation M-T1: 78 tests would not notice, and every run would be served at the pre-run estimate — the 5.27× overstate direction #105 measured.
8. **Do not byte-count SSE frames.** `read(n)` tears the frame; `readline()` does not — both directions measured (O5). Treat `\n\n` as the event boundary, not one line per event.
9. **Do not adopt streaming keep-alives as the #290 fix without replacing the wall-clock bound.** They demonstrably defeat the per-`recv` socket timeout (O3), and the run deadline stops the recording, not the billing.
10. **Do not gate a mitigation on an upstream header, status or body shape you have not measured** — rule 8c, and the reason this whole page exists.
11. **Two money decisions here need an ADR line in the same PR** (rule 16d; ADR-0077 is already named): (a) is a stream that delivers 3 deltas, real final-chunk usage, then an error frame `measured` (honest about dollars, dishonest about the answer) or `estimated`? Today's non-streaming analogue — F-06 finding C — keeps stated usage on an empty completion, which argues for `measured` plus a degraded-slot flag. Either way the test must pin the usage-entry count, because the two answers differ by exactly one entry. (b) A stream that errors before any delta arrives as **HTTP 200**, so nothing in `_UNBILLED_HTTP_STATUSES` can reach it — the new branch owns that call entirely and needs its own not-billed partner.

---

**Scope limit on my own check.** I ran only the two named billing test files (103 tests), so the 78/103 figure is for those two files only. Other files touching this seam — `tests/unit/test_provider_stubs.py`, `test_provider_token_telemetry.py`, `test_telemetry_sink.py`, `tests/resilience/test_fault_injection_lane.py` — were not run. I made no network call beyond loopback and no paid call of any kind, so every claim about what OpenRouter actually emits is marked UNVERIFIED above with the single command that settles it.