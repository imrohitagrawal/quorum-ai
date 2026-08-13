# Telemetry inventory: #105, #268, #203 — what exists, what's missing, next action

**Status:** all three issues stay OPEN. This is an inventory, not a fix. Nothing
in `_UNBILLED_HTTP_STATUSES` or `_CREDENTIAL_REFUSED_STATUSES` moved — both
confirmed byte-identical to `origin/main`:

```
$ grep -n "_UNBILLED_HTTP_STATUSES\s*:" src/product_app/providers.py
1650:_UNBILLED_HTTP_STATUSES: frozenset[int] = frozenset({400, 401, 402, 403, 404, 429})
$ grep -n "_CREDENTIAL_REFUSED_STATUSES\s*=" src/product_app/readiness.py
84:_CREDENTIAL_REFUSED_STATUSES = frozenset({401, 403})
```

Commit `ab4296c` (2026-08-10, "Make three blocked issues decidable: durable
telemetry, no guessed classification") already shipped the instrumentation
this doc inventories — `src/product_app/telemetry_sink.py`,
`docs/adr/0031-three-blocked-issues-get-durable-telemetry-not-a-guessed-fix.md`.
This doc is the follow-on: a concrete answer to "what does it actually emit,
where, and does anything read it back", plus a script
(`scripts/telemetry_classification_report.py`) that reads the JSONL and
prints ADR-0031's own decision rules against whatever sample exists — never
inventing a rule ADR-0031 doesn't already state.

## What `telemetry_sink.py` actually emits

Two JSONL files, written only when `TELEMETRY_LOG_DIR` is set
(`src/product_app/telemetry_sink.py:74`, `fly.toml:44` sets it to `/data` in
production; the local test suite and any deployment that unsets it write
nothing):

| File | Constant | Rotation | Issues |
|---|---|---|---|
| `telemetry-billing.jsonl` | `BILLING_FILE_NAME` (`telemetry_sink.py:76`) | 1 MiB × 4 backups = 5 MiB ceiling | #105, #203 |
| `telemetry-tokens.jsonl` | `TOKENS_FILE_NAME` (`telemetry_sink.py:77`) | 4 MiB × 4 backups = 20 MiB ceiling | #268 |

The billing file is an **allowlist**, not everything the root logger emits —
`BILLING_EVENTS` (`telemetry_sink.py:90-96`) admits exactly three event names:
`upstream_provider_http_error`, `upstream_provider_opener_error`,
`key_probe_credential_refused`. The token file gets its own dedicated logger
(`TOKEN_TELEMETRY_LOGGER = "product_app.telemetry"`,
`telemetry_sink.py:84`) and carries only `provider_call_tokens`.

## Exact call sites (verified with `grep -n`, 2026-08-14)

| Event | Emitted at | Fields (verified against the code, not the ADR prose) |
|---|---|---|
| `upstream_provider_http_error` | `src/product_app/providers.py:1230-1239` | `status_code`, `url`, `model_id`, `billing_class`, plus `_billing_evidence_shape(exc)` (`body_shape`, `body_bytes`, `error_metadata_present`, `provider_name_present`, `provider_name_header`, `sniff_time_bounded`) |
| `upstream_provider_opener_error` | `src/product_app/providers.py:1266-1273` | `error_type`, `model_id`, `billing_class` |
| `provider_call_tokens` | `src/product_app/providers.py:1989` (`_TOKEN_LOGGER.info`, logger built at `providers.py:1931`) | `model_id`, `search_enabled`, `max_tokens`, `system_prompt_chars`, `sent_chars`, `sent_tokens_est`, `usage_absent`, and (only when `usage is not None`) `prompt_tokens`, `completion_tokens`, `injected_tokens_est` |
| `key_probe_credential_refused` | `src/product_app/readiness.py:198` (unreadable-body early return) and `:219` (normal path) | `status_code` (401/403), `body_shape`, `body_bytes`, `content_type_main`, `error_code_in_body`, `server_class`, `header_names_present`, `expose_headers_names_openrouter` |

`key_probe_credential_refused` lands in `telemetry-billing.jsonl`, not a
separate #203 file — it's in `BILLING_EVENTS` alongside the two provider
events, confirmed by `telemetry_sink.py:90-96`.

## Where it's written

`install_telemetry_sinks()` is called once, unconditionally, at import time
in `src/product_app/main.py:87`. It is a no-op returning `False` whenever
`TELEMETRY_LOG_DIR` is unset (`telemetry_sink.py:224-227`) — verified:

```
$ grep -n "install_telemetry_sinks\|TELEMETRY_LOG_DIR" src/product_app/main.py fly.toml
src/product_app/main.py:75:from product_app.telemetry_sink import install_telemetry_sinks
src/product_app/main.py:87:install_telemetry_sinks()
fly.toml:44:  TELEMETRY_LOG_DIR = "/data"
```

In production the two files land on the same Fly volume that already holds
`FEEDBACK_DB_PATH` / `RUN_HISTORY_DB_PATH` (mounted at `/data`). Reading them
back requires `fly ssh console -a quorum-ai -C "cat /data/telemetry-billing.jsonl"`
— there is deliberately no HTTP route (ADR-0031, "WHERE IT LANDS").

## Whether anything reads it back today

**No.** Verified:

```
$ grep -rl "telemetry-billing.jsonl\|telemetry-tokens.jsonl\|telemetry_sink" src scripts
src/product_app/telemetry_sink.py
```

The only hit is the sink module itself. No script, no test, no route reads
either file. `scripts/telemetry_classification_report.py` (added by this PR)
is the first thing that does — and it only reads a **local** directory passed
on the command line or via `$TELEMETRY_LOG_DIR`; running it against
production data means pulling the file down first (`fly sftp get` or `fly ssh
console -C cat`), which this PR does not do and does not have to, since
production spend is `"0"` today and both files are empty on the volume as of
2026-08-14 (unverified from this worktree — no network access to `fly ssh`
from here; the honest state is "assumed empty from the #105 ADR's own
'`n` will stay zero however long anyone waits' note", not measured this
session).

## Concrete next action per issue, once N samples exist

Each rule below is copied from ADR-0031's own "The reading that settles each
issue" section — this PR does not invent a new threshold or a new rule, it
implements the ones already written down as a script
(`scripts/telemetry_classification_report.py`, functions `classify_billing_5xx`,
`classify_token_injection`, `classify_credential_refusal_shapes`):

- **#105** — group `upstream_provider_http_error` records with
  `status_code >= 500` **per status code, never pooled**. Need `n >= 30` per
  status before deciding anything. If `unknown/n > 0.20`, STOP — the
  `error.metadata.provider_name` schema ADR-0012 assumed is refuted. Otherwise,
  if `router_refusal/n >= 0.95` and no record ever named the provider,
  reclassify that status to unbilled in `_UNBILLED_HTTP_STATUSES`, **in its
  own PR**, with the count recorded. `/status.global_daily_spend_usd` is
  `"0"` today, so `n` stays at zero without deliberately provoked traffic —
  an operator decision this doc does not make.
- **#268** — split `provider_call_tokens` by `search_enabled`. First check
  the non-search group's `injected_p95` is under 500 (validates
  `sent_tokens_est`/`CHARS_PER_TOKEN`); if it fails, the whole reading is
  VOID and the estimator needs fixing before anything else is trusted. Then,
  with `n >= 50` searching calls, if `injected_p95 > 2000` raise
  `cost_web_search_context_tokens` to the observed p95 in its own PR (the
  fail-safe hole); if `injected_p95 < 1000` over `n >= 200`, lower it **only
  with the operator** — `config.py:315-319` says the constant is
  deliberately conservative.
- **#203** — group `key_probe_credential_refused` records with
  `status_code == 403` by `(status_code, content_type_main, server_class,
  expose_headers_names_openrouter)`. One distinct shape means no evidence of
  a second answerer and the known proxy/WAF gap stays open honestly. Two or
  more means there is something to disambiguate — and only then is designing
  a signal a real task. The proxy/WAF question itself is not answerable from
  this repository regardless of sample size (ADR-0031, "What this package
  could not do") — it needs the operator to answer the four questions listed
  there (`HTTP_PROXY`/`HTTPS_PROXY` secrets, Fly org egress policy, Cloudflare
  Zero Trust enrolment, and what a filtering layer returns on a block).

## Running the report

```bash
# locally, against an empty/missing directory — the expected state today
python scripts/telemetry_classification_report.py /tmp/no-telemetry-yet

# against a pulled-down production snapshot
fly sftp get /data/telemetry-billing.jsonl /tmp/prod-telemetry/telemetry-billing.jsonl -a quorum-ai
fly sftp get /data/telemetry-tokens.jsonl /tmp/prod-telemetry/telemetry-tokens.jsonl -a quorum-ai
python scripts/telemetry_classification_report.py /tmp/prod-telemetry
```

It never writes anything, never calls a paid API, and never changes a
constant — it prints counts and, only once a rule's stated floor is met, the
verdict that rule already specifies. Below the floor it prints
`insufficient data (N/required)` per issue and stops.
