# ADR-0031: Three blocked issues get durable telemetry, not a guessed fix

## Status

Accepted — 2026-08-10

## Context

Issues #105, #268 and #203 have one thing in common: each asks a question about
the outside world that **cannot be answered from this repository**, and each has
a tempting one-line "fix" that would encode a guess as a fact.

| Issue | The question | The tempting guess |
|---|---|---|
| #105 | does a provider 5xx follow a generation that already billed? | move 5xx into `_UNBILLED_HTTP_STATUSES` |
| #268 | how many input tokens does OpenRouter's `:online` search inject? | re-set `cost_web_search_context_tokens` from one run |
| #203 | is a 403 from OpenRouter, or from something in front of it? | key a classifier off `Server` or `cf-ray` |

Every one of those guesses is wrong or unfounded on the evidence available
today, and #180 cost three broken attempts learning that a classification must
not move on a guess. So this package changes **no classification, no default
and no constant**, and closes **none** of the three issues. It ships the
measurement that makes them decidable.

### Why the data does not already exist

Four facts, each re-measured in this worktree on 2026-08-10:

| Claim | Command | Result |
|---|---|---|
| Fly keeps a small log ring | `fly logs --app quorum-ai --no-tail \| wc -l` | **100 lines** |
| no log drain is configured | `grep -in drain DEPLOY.md` | **0 hits**; the absence is recorded in ADR-0018 |
| the `runs` table has no per-token columns | read `run_history_store.py:116-140` | 23 columns, none about tokens |
| one uvicorn worker, so a file sink needs no cross-process locking | `grep -n workers Dockerfile` | `:72 "--workers", "1"` |
| production runs the base of this branch | `curl -s https://quorum.stackclimb.com/status` | `build_sha` = `f7128b1…` |

A record written only to stdout is therefore gone in about twenty minutes and
dies on restart. #105 needs a week.

### Two facts about the upstream, paid for with a free `curl`

AGENTS.md rule 8c exists because a previous fix gated a body read on
`Content-Length`, was correct against a loopback server, was green on every
gate, and **would have collected nothing at all in production**. So the live
API was probed again before anything here was designed. With a bad bearer
token, `https://openrouter.ai/api/v1/key` answers:

```
HTTP/2 401   server: cloudflare   content-type: application/json   (no content-length)
access-control-expose-headers: X-Generation-Id,X-Provider-Name,cf-ray
{"error":{"message":"User not found.","code":401}}
```

Two consequences, both load-bearing below:

1. **`server: cloudflare` and `cf-ray` cannot detect a proxy**, because
   OpenRouter is itself behind Cloudflare.
2. Errors are `Transfer-Encoding: chunked` with **no** `Content-Length`, so
   nothing may gate on that header.

Whether a genuine OpenRouter **403** carries the same envelope is UNVERIFIED —
the available key answers 401. That gap is exactly what #203's capture is for.

## Decision

Add one module, `src/product_app/telemetry_sink.py`, that routes three record
types to **two** bounded JSONL files on the Fly volume already mounted at
`/data`. Nothing reads them at runtime. No behaviour anywhere changes.

### The sink

| File | Feeds | maxBytes × backups | Ceiling |
|---|---|---|---|
| `/data/telemetry-billing.jsonl` | #105, #203 — rare, precious | 1 MiB × 4 | 5 MiB |
| `/data/telemetry-tokens.jsonl` | #268 — ~12 records per run | 4 MiB × 4 | 20 MiB |

**Two files, not one.** The token stream fires on every successful provider
call; the billing stream fires on a provider 5xx, which at today's spend
(`/status.global_daily_spend_usd` is `"0"`) is a once-in-a-long-while event.
Sharing one file would let the high-volume stream rotate the rare one out of
existence inside a single busy hour. `test_a_token_burst_cannot_evict_a_billing_record`
is that defect, written down as a test.

Both handlers use the **existing** `JsonFormatter`, so the on-disk shape equals
the stdout shape. `/data` is the same volume that already carries
`FEEDBACK_DB_PATH` and `RUN_HISTORY_DB_PATH` — issue #27 moved them there after
the ephemeral rootfs was wiped on every deploy. Read the files with
`fly ssh console -a quorum-ai -C "cat /data/telemetry-billing.jsonl"`.

**Unset means off.** `TELEMETRY_LOG_DIR` is a plain environment variable (the
same shape as the two DB paths, deliberately not a `Settings` field). The test
suite and any unconfigured deployment write no telemetry files at all;
`fly.toml`'s `[env]` block is what turns it on, and a test pins that so the
feature cannot ship switched off in the one deployment whose data is wanted.

**It cannot break a request.** Installation is wrapped: an unwritable or
un-creatable directory logs one `telemetry_sink_unavailable` warning and leaves
the process exactly as it was. Each emission is suppressed at its **call site**,
not merely inside its helper — inside `_post_messages` the parsing `try` returns
`_DISPATCH_UNMEASURED` for anything it catches, so an exception raised by
instrumentation there would silently downgrade an already-billed, perfectly
measurable call to `estimated`. Instrumentation must never move money.

**Routing differs per stream, deliberately.** The billing records stay on the
root logger and gain the file through a `logging.Filter` holding an allowlist of
event names — so operators keep seeing them on stdout and #105's already-shipped
records simply become durable. The token stream gets its own logger with
`propagate=False`, set at import rather than at installation: on the root logger
its dozen records per run would evict Fly's 100-line ring in seconds *and*
become Sentry breadcrumbs (`LoggingIntegration` is on by default and `main.py`
passes no `integrations=`).

### #105 — nothing new is instrumented

The evidence records already exist (`_billing_evidence_shape`, shipped and
tested). The only change is **routing them to a durable file**. Their fields —
`status_code`, `url`, `model_id`, `billing_class`, `body_shape`, `body_bytes`,
`error_metadata_present`, `provider_name_present`, `provider_name_header`,
`sniff_time_bounded`, and `error_type` on the opener-error branch — are
unchanged.

### #268 — a new `provider_call_tokens` record

Emitted on the success path of `_post_messages`, after the response has parsed.
Counts only, never content:

| Field | Why |
|---|---|
| `model_id` | as it goes on the wire, `:online` suffix included |
| `search_enabled` | `model_id.endswith(":online")` — the suffix IS the search flag |
| `max_tokens` | the output cap this call carried |
| `system_prompt_chars` | the direct measurement of what `cost_system_prompt_tokens` prices |
| `sent_chars`, `sent_tokens_est` | what we sent, and `sent_chars // 4` |
| `prompt_tokens`, `completion_tokens` | the provider's own numbers |
| `injected_tokens_est` | `prompt_tokens - sent_tokens_est` — **what neither constant bounds** |
| `usage_absent` | the provider reported no usage; the negative partner |

`config.py:326/331` sets `cost_system_prompt_tokens = 350` and
`cost_web_search_context_tokens = 2000`, and the comment above them grounds
**both** on a single live run (`d7785cd8`). One sample. #268 already measured
that our system prompts are comfortably under 350, so that is not the exposure.
The exposure is the web-search context, injected upstream by OpenRouter, billed
to us as input tokens, and bounded or measured by nothing of ours — and the cost
guardrail keys off the estimate, so an under-estimate there is a fail-safe hole.

`usage_absent` is reported rather than a fabricated `prompt_tokens: 0`. A zero
would sit in the distribution and drag every percentile taken from it, which is
the same reason `_extract_usage` refuses to invent a record.

### #203 — a new `key_probe_credential_refused` record, and NO classifier

Captured on the `401`/`403` branch of `readiness.probe_key_auth`. The provider
path needs nothing: `403` is already in `_UNBILLED_HTTP_STATUSES` and
`_billing_evidence_shape` already runs there unconditionally.

| Field | Note |
|---|---|
| `status_code` | 401 or 403 |
| `body_shape`, `body_bytes` | the #105 vocabulary, reusing the #105 bounded read |
| `content_type_main` | `application/json` / `text/html` / `other` / `absent` — an ENUM |
| `error_code_in_body` | `error.code` when the JSON envelope carries one |
| `server_class` | `cloudflare` / `other` / `absent` — an ENUM, never the raw value |
| `header_names_present` | intersection with a frozen allowlist. **Names only** |
| `expose_headers_names_openrouter` | does the CORS list name OpenRouter's own headers? |

**No decision rule is shipped, and that is the correct outcome** — see §"What
this package could not do" below.

## Measurements that shaped the design

| Question | Command | Result |
|---|---|---|
| does `JsonFormatter` drop `extra` keys? | read `logging_config.py:59-79` | yes, silently: `timestamp`, `level`, `logger`, `message`, `module`, `function`, `line` are in `payload` before the fold |
| would a naive `isinstance` in `setup_json_logging` remove the sink? | `RotatingFileHandler` is a `StreamHandler` | yes — narrowed to an exact type check, with a test |
| does `repr(UnicodeEncodeError)` leak the key? | run on CPython 3.12.13 | **yes**, in full. `str(exc)` does **not** |
| do the repo's `_http_error` doubles read as empty? | run on CPython 3.12.13 | `HTTPError(fp=None).read()` → `b''`; `.headers` → `None` |
| does `email.message.Message` iterate header names? | run | yes — ruff's `.keys()` removal is safe here, contrary to first reading |
| does `run_history_store` have migration machinery? | `grep -rn 'ALTER TABLE\|user_version\|migrat' src/product_app/run_history_store.py` | **none**, while `feedback_store.py` has a full `schema_migrations` table |

## What is deliberately NOT recorded

The rule is one rule: **shapes, counts, enumerations and header NAMES. Never
content, never a header VALUE, never an exception message.**

| Not recorded | Why |
|---|---|
| any response-body substring | an OpenRouter error body can echo the user's query; a WAF denial page routinely echoes the request headers, including `Authorization` |
| any header **value** (hence `server_class`, not `server`) | one value is enough. `Content-Type` is enum-ised for the same reason: it is an upstream-controlled string, and recording it verbatim would let an upstream write arbitrary text into our logs |
| `repr(exc)`, `exc.args`, `exc.object`, `exc_info=True` | measured above: `repr` carries the bearer token in full |
| the `messages` list, or any element of it | `sent_chars` is a count; the content never leaves the frame |
| a new HTTP route serving the files | a new authentication surface serving upstream-controlled bytes. `fly ssh console` is free |

`scripts/security_scan.py` **cannot see any of this** — it is four static
line-oriented regex checks with no notion of a logger, an `extra=` dict or
dataflow, so `_LOGGER.warning("x", extra={"body": raw})` produces zero findings.
And `tests/security/test_release_security_redaction.py` asserts absence from
HTTP responses and in-memory recorders only. **No test in this repo asserted
that a credential is absent from a LOG RECORD before this one.**
`test_no_credential_reaches_any_log_record_or_sink_file` is that missing gate,
and it is the highest-value test in the package.

## The reading that settles each issue

### #105

```bash
jq -c 'select(.message=="upstream_provider_http_error" and .status_code>=500)' \
   /data/telemetry-billing.jsonl \
| jq -s 'group_by(.status_code) | map({
    status: .[0].status_code, n: length,
    router_refusal: [.[]|select(.provider_name_present==false and .error_metadata_present==false and .provider_name_header==false)]|length,
    provider_named: [.[]|select(.provider_name_present==true or .provider_name_header==true)]|length,
    unknown:        [.[]|select(.provider_name_present==null)]|length })'
```

Decision rule, **per status code, never "all 5xx"**:

- `unknown/n > 0.20` → **STOP.** ADR-0012 records the
  `error.metadata.provider_name` schema as ASSUMED, not measured; a dominant
  `null` refutes it and nothing further may proceed.
- `n < 30` → not enough. Do not decide.
- `router_refusal/n >= 0.95` **and** `provider_named == 0` → add **that status
  only** to `_UNBILLED_HTTP_STATUSES`, in its own PR, with the count recorded.
- `provider_named > 0` → leave it possibly-billed.

**Stated blocker, not papered over:** `/status.global_daily_spend_usd` is `"0"`.
`n` will stay zero however long anyone waits. Reaching `n >= 30` needs
deliberately provoked traffic, which is an operator decision about spending.
**This package does not supply that traffic plan.**

### #268

```bash
jq -c 'select(.message=="provider_call_tokens")' /data/telemetry-tokens.jsonl \
| jq -s 'group_by(.search_enabled) | map({
    searching: .[0].search_enabled, n: length,
    injected_p50: (map(.injected_tokens_est)|sort|.[length/2|floor]),
    injected_p95: (map(.injected_tokens_est)|sort|.[length*0.95|floor]),
    injected_max: (map(.injected_tokens_est)|max) })'
```

- **Positive partner first:** for `search_enabled == false`, `injected_p95` must
  be **under 500**. If it is not, `sent_tokens_est` is wrong and the whole
  measurement is void — fix the estimator before reading anything else. This is
  also the check on `CHARS_PER_TOKEN = 4`, which is a repo constant and not a
  measurement of OpenRouter's tokeniser.
- `n < 50` searching calls → not enough.
- `injected_p95 > 2000` → `cost_web_search_context_tokens` **under**-estimates,
  which is the fail-safe hole. Raise it to the observed p95, own PR.
- `injected_p95 < 1000` over `n >= 200` → over-estimating. Lower it **only with
  the operator**: `config.py:315-319` says these are calibrated deliberately
  conservative, and the guardrail keys off them.
- Report `injected_max` either way — the guardrail's exposure is the tail.

### #203

```bash
jq -c 'select(.message=="key_probe_credential_refused")' /data/telemetry-billing.jsonl \
| jq -s 'group_by([.status_code,.content_type_main,.server_class,.expose_headers_names_openrouter])
         | map({key:.[0]|{status_code,content_type_main,server_class,expose_headers_names_openrouter}, n:length})'
```

The observation is one question: **does more than one distinct shape appear
under status 403?** One shape → no evidence of a second answerer, and the known
gap stays open honestly. Two or more → there is something to disambiguate, and
only then is designing a signal a real task.

## What this package could not do

**The #203 proxy/WAF question is not answerable from the repository, and this
is stated rather than guessed around.**

`grep -rniE "https?_proxy|no_proxy|egress|wireguard|flycast|nat gateway|static.?ip|outbound"`
across `*.toml`, `*.md`, `*.yml`, `*.yaml` and `Dockerfile` returns nothing
about egress. `fly.toml` configures inbound services, a volume and a VM. The
Dockerfile sets no proxy variable. The repo does not merely fail to answer the
question — it has already written it down twice as unresolved, in `DEPLOY.md`
and in `docs/architecture/50-failure-modes.md`, in the same words.

The operator must be asked four questions, each answerable without touching code:

1. Are `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` set as Fly secrets or machine
   env on app `quorum-ai`? (`fly ssh console -a quorum-ai -C env | grep -i proxy`)
2. Does the Fly **organisation** apply any egress policy, WireGuard peering or
   private-networking rule routing outbound HTTPS through anything other than
   Fly's default NAT?
3. Is there a Cloudflare Zero Trust / Gateway / WARP enrolment, or any other
   filtering layer, covering this app's outbound traffic?
4. If yes to any: what does that layer return on a block — status,
   `content-type`, and does it strip or rewrite response headers?

Until those are answered, **the capture ships and the classifier does not**.
That is the expected outcome, not a shortfall.

**A `stage` label was designed and then dropped, because an existing guard
refuses it.** The plan called for tagging each token record
`initial`/`debate`/`synthesis`/`judge`. Threading that parameter means passing
it to `_post_messages`, and
`tests/unit/test_judge_call_asks_for_a_parseable_verdict.py::test_a_non_judge_call_reaches_the_transport_with_an_unchanged_SIGNATURE`
asserts the exact kwarg set that reaches it is
`{"openrouter_key", "model_id", "messages", "max_tokens"}` — a guard written
because seven tests went red the last time that signature moved, and because the
debate and synthesis payloads feed a visual-baseline lane that cannot be
re-seeded locally (rules 13d/13e). `system_prompt_chars` is recorded instead: it
measures `cost_system_prompt_tokens`'s subject directly, per call, and costs no
signature change. `max_tokens` does **not** substitute for a stage label —
`initial_answer_max_tokens` and `DEBATE_ROUND_MAX_TOKENS` are both 2000, so it
separates synthesis (3000) and judge (1024) only. Stated because #268's reading
groups by `search_enabled`, which does isolate the population that matters.

## Removal condition

**This is scaffolding, not a feature.** Each stream is deleted independently, on
its own reading.

- **#105 stream** — delete when, for every 5xx status with `n >= 30`, that
  status has either moved into `_UNBILLED_HTTP_STATUSES` with its count recorded
  here, or been affirmed possibly-billed on evidence. Deleting it also removes
  `_billing_evidence_shape`, `_read_within_budget`,
  `_provider_name_header_present` and their tests from the paid error path.
- **#268 stream** — delete when both constants have been re-set from a
  distribution of `n >= 200` calls (`n >= 50` searching), **and** a cheap
  standing check replaces it: an assertion at cost-computation time that a
  searching initial call's measured `prompt_tokens` falls inside the estimate's
  envelope, alerting only on breach. Continuous per-call token logging is not a
  permanent need.
- **#203 stream** — delete when the operator has answered the four questions
  above. If there is **no** proxy or WAF, the disambiguation question is void
  and the capture goes with it. If there is one, the fields feed a classifier
  once and are then superseded by it.
- **The sink itself** — delete when all three streams are gone, or when a real
  log drain exists (ADR-0018 records that there is none today).

## Rejected alternatives

| Alternative | Cost | Why rejected |
|---|---|---|
| **stdout only** | $0 | collects **zero**, not "less". `fly logs --no-tail` returned exactly 100 lines, most of it `/ready` noise; a record survives minutes and dies on restart. #105 needs a week |
| **new columns on the `runs` table** | new migration machinery | `run_history_store.py` has **none** (`grep` for `ALTER TABLE`/`user_version`/`migrat` → 0 hits), while `feedback_store.py` solved the same problem differently with a `schema_migrations` table. Building a second, divergent mechanism for scaffolding data is the wrong trade — and the granularity is wrong anyway: `runs` is one row per run, #268 needs one per **call** |
| **a `provider_calls` child table** | correct granularity, still needs the machinery | right shape, wrong moment. JSONL is deletable; a table is forever. Revisit if #268's data justifies a permanent per-call ledger |
| **Fly Log Shipper (Vector sidecar)** | a second Fly machine plus a sink credential | not $0 (rule 17f), and needs an operator |
| **a third-party free tier** | claimed-free — UNVERIFIED | needs an operator and a third party, and exports the very records whose leak surface this design minimises |
| **`/metrics` counters** | $0 | `main.py:349` does wire `Instrumentator(...).expose(app)`, so `fly.toml`'s "no /metrics endpoint" comment is stale — but nothing scrapes it, and a counter cannot carry a distribution. (That stale comment is a separate one-line fix and is **not** in this PR, per rule 17) |
| **a `/ops/telemetry` read endpoint** | small | a new authentication surface serving upstream-controlled material |
| **one shared JSONL file** | $0 | the token stream rotates the rare 5xx records out of existence |
| **gating any read on `Content-Length`** | — | rule 8c, already measured fatal: OpenRouter answers errors chunked. Do not reintroduce |

## Consequences

**Good.**

- Three issues that could only be closed by guessing become decidable by
  reading, and each has a written decision rule with an explicit "not enough
  data" arm.
- The #105 evidence that already existed stops evaporating in twenty minutes.
- The repo gains its first test asserting a credential is absent from a **log
  record** — a gap `security_scan.py` structurally cannot see.
- `setup_json_logging` no longer removes handlers it did not add.

**Bad, and accepted.**

- 25 MiB of the Fly volume is reserved. The volume's created size is
  **UNVERIFIED** — `fly.toml`'s comment says `--size 1` but that is the operator
  instruction, not the created size; `fly volumes list -a quorum-ai` settles it.
- The files are read by hand over `fly ssh console`. That `fly ssh` is
  provisioned for this app is **UNVERIFIED** (`fly logs` works and the CLI is
  authenticated, but SSH is separate); `fly ssh issue --agent` settles it.
- `readiness` now imports three private names from `providers` rather than
  duplicating a 40-line bounded read. Renaming them would touch 45 existing
  tests on a paid error path for no behavioural gain.
- `injected_tokens_est` is only as good as `CHARS_PER_TOKEN = 4`, which is a
  repo constant and **not** a measurement of OpenRouter's tokeniser. The
  non-searching arm of #268's reading is the check on that, and it is stated as
  the first step of the reading for exactly that reason.
- #105's `n` will not grow on its own at today's spend.

## References

- Issues #105, #268, #203; #180 (why a classification does not move on a guess).
- ADR-0012 — the `error.metadata.provider_name` schema, recorded as assumed.
- ADR-0018 — records that no log drain exists.
- ADR-0002 — the single-writer store constraint that rules out a casual table.
- `src/product_app/telemetry_sink.py`, `tests/unit/test_telemetry_sink.py`,
  `tests/unit/test_provider_token_telemetry.py`,
  `tests/unit/test_key_probe_refusal_shape.py`.
- AGENTS.md rules 8a (empty-body doubles), 8b (bound the argument and the time),
  8c (measure the upstream before gating on it).
