# ADR-0054: No network intermediary is configured, so the 403 shape-capture is removed

## Status

Accepted — 2026-08-18. Closes issue #203 ("Credential probe cannot distinguish
a proxy 403 from a provider 403"), a follow-on of #112.

## Context

### The gap as filed

`probe_key_auth` (`src/product_app/readiness.py`) classifies any `HTTPError`
with status 401 or 403 on `GET {openrouter_api_base_url}/key` as
`unauthorized`, whoever sent it. A corporate proxy or WAF answering 403 on
that path by policy — nothing to do with the credential — would pin a healthy
deployment to `offline_by_bad_key` and tell users their genuinely live answers
were simulated. `DEPLOY.md` and `docs/architecture/50-failure-modes.md` both
disclosed it in the same words.

### Why it was never fixed

Issue #203 said so itself: there is no reliable way to tell the two 403s apart
without first measuring what a real proxy/WAF 403 looks like *on this
deployment's egress path*, "if one exists between the Fly.io runtime and the
internet — may require operator input on what network intermediaries, if any,
are actually in the path." Guessing at a classifier was explicitly ruled out,
citing #180's three broken fix attempts.

What shipped instead was `_log_credential_refusal_shape`: a deliberately
classifier-free capture that logged the *shape* of a refusal (status, allowed
header names, content-type class, body shape, bounded `error.code`) so a later
reading could design a classifier from real examples. It changed no verdict,
by design and by test.

### The infrastructure question, answered

The blocking question was never about code. It was: *is there an intermediary?*
Measured 2026-08-17 (orchestrator) and re-measured 2026-08-18 (this branch).

| Check | Command | Result | Who measured |
|---|---|---|---|
| Proxy env vars on the running production machine | `fly ssh console -a quorum-ai -C env` | no `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` in the dump | orchestrator, 2026-08-17 — **inherited, not re-measured here** (`fly ssh` is blocked in this agent's sandbox) |
| Proxy handling in the app | `grep -rniE "http_proxy\|https_proxy\|no_proxy\|trust_env\|proxies=\|ProxyHandler" src/` | exit 1, no matches | re-measured on this branch |
| Egress configuration | `grep -niE "proxy\|egress\|wireguard" fly.toml` | exit 1, no matches — `fly.toml` has only inbound `[[services]]`, a volume and a VM | re-measured on this branch |
| Fly org | `fly apps list` | `quorum-ai`, owner `personal` | re-measured on this branch |
| WireGuard peers | `fly wireguard list personal` | all `interactive-*` developer/CI tunnels, not an egress policy | orchestrator, 2026-08-17 — **inherited** (`fly wireguard` is blocked in this agent's sandbox) |

Two further facts about whether the capture could ever have collected anything:

* `probe_key_auth` returns `"unknown"` **without dialling** unless
  `settings.openrouter_live_execution_enabled` is true and a key is set
  (`src/product_app/readiness.py`, the first branch of the function).
* `fly.toml` `[env]` sets `OPENROUTER_LIVE_EXECUTION_ENABLED = "false"`
  (re-measured on this branch), and the production machine's own environment
  dump agreed on 2026-08-17 (inherited).

So the probe has not been issuing requests in production at all, and the
capture has recorded nothing.

## Decision

**Remove `_log_credential_refusal_shape`, its four private constants
(`_REFUSAL_HEADER_ALLOWLIST`, `_OPENROUTER_EXPOSED_HEADER_NAMES`,
`_KNOWN_CONTENT_TYPES`, `_ERROR_CODE_MIN`/`_ERROR_CODE_MAX`), its call site and
its test file. Close #203 as not-a-problem on this deployment's egress path.**

**Scope of that claim, stated narrowly.** The commands above show that no
intermediary is *configured* between the Fly runtime and the internet **today,
on this app**. They do **not** show that a proxy 403 is impossible in
principle, and they do not cover an intermediary introduced later.

Deliberately kept:

* `_CREDENTIAL_REFUSED_STATUSES` and the 401/403 → `unauthorized` behaviour —
  unchanged, and that is the point.
* `providers._read_within_budget`, `_ERROR_BODY_SNIFF_LIMIT_BYTES` and
  `_ERROR_BODY_SNIFF_TIMEOUT_SECONDS` — owned by #105, which still needs them.
  `readiness.py` only stops importing them.

## Rejected alternatives

**Keep the capture dormant, in case a proxy appears later.** Rejected. It is
154 lines removed from `readiness.py` plus a 473-line test file (measured:
`git diff --stat HEAD`), carrying its own hazards — a
header allowlist, a content-type allowlist and a 32-bit `error.code` clamp, all
of which exist purely to stop upstream-chosen bytes reaching a log record. That
is standing maintenance and standing log-injection surface bought for data that
cannot arrive: the probe does not dial while live execution is off, and there
is no intermediary to produce the 403 it is watching for. If an intermediary is
ever introduced, the capture is recoverable verbatim from git history along
with the reasoning here — cheaper than carrying it against a hypothetical.

**Write the classifier now.** Rejected for the same reason #203 gave
originally, and the reason has not changed: there is no measured proxy/WAF 403
to classify against. Guessing is exactly the #180 failure mode.

**Leave #203 open with the docs unchanged.** Rejected. The disclosure told an
operator a live risk existed on this deployment when the commands above say it
does not. A stale warning is not free — it competes for attention with the real
ones.

## Consequences

* The readiness verdict is **unchanged**. Proved by running
  `tests/unit/test_readiness.py` and `tests/unit/test_readiness_key_auth.py`
  before and after the removal: 51 tests, byte-identical `-v` outcome lines
  (`diff` clean).
* The positive partners that must survive this removal already exist and pass:
  `test_probe_classifies_an_explicit_credential_refusal_as_unauthorized[401]`
  and `[403]` (→ `unauthorized`), `test_probe_never_blames_the_key_for_an_upstream_fault`
  (429/500/502/503 → `unknown`) and `test_probe_never_blames_the_key_for_a_network_fault`
  (`URLError`, `TimeoutError`, `OSError`, `ValueError` → `unknown`), all in
  `tests/unit/test_readiness_key_auth.py`. They bite: mutating
  `_CREDENTIAL_REFUSED_STATUSES` to `frozenset()` turned 4 of them red
  (401, 403 and two re-probe tests), and restoring the file from a copy
  returned all 41 to green.
* **If an intermediary is ever put in front of egress** — a corporate proxy, an
  egress gateway, a Fly org-level policy — **this gap returns**, and
  `offline_by_bad_key` becomes a possible lie about a healthy deployment. The
  capture would have to come back, and the same measurement table is the thing
  to re-run before trusting the verdict. `DEPLOY.md` and
  `docs/architecture/50-failure-modes.md` both say so at the point an operator
  would be reading.
* `tests/unit/test_risk_constant_pins.py` loses five registry entries. It has a
  gate for exactly this —
  `test_the_registry_names_no_constant_that_has_been_deleted` — so a stale entry
  would have failed rather than rotted.
