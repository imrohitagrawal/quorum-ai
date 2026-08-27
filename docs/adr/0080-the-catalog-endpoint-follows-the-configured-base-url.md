# ADR-0080: The catalog endpoint follows the configured base URL

## Status

Accepted — 2026-08-28

## Context

`OPENROUTER_API_BASE_URL` was a **half-honoured** setting. Three call sites
build a URL from the OpenRouter base; only two of them read the setting:

| Call | How it built its URL | Honoured the setting? |
|---|---|---|
| chat completions (`providers.py`) | `f"{settings.openrouter_api_base_url}/chat/completions"` | yes |
| key probe (`readiness.py`) | `f"{settings.openrouter_api_base_url}/key"` | yes |
| model catalog (`catalog_fetcher.py`) | `OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"` | **no** |

So an operator pointing the app at a proxy, a self-hosted gateway or a local
double redirected every paid call and the key probe, while the catalog went on
talking to the real upstream. One process, two providers, and nothing in the
code or the configuration said so. The catalog decides model prices, so the
divergence is not cosmetic: prices could come from one endpoint while the calls
they price go to another.

`tests/unit/test_risk_constant_pins.py` classified the constant in
`BUCKET_B_PIN_BEHAVIOUR` — *pin the behaviour, not the literal* — with the note
*"assert https scheme and openrouter.ai host (SSRF-adjacent)"*.

**No test asserted that behaviour.** Measured 2026-08-28: `OPENROUTER_CATALOG_URL`
appeared in exactly two places in the whole repository — its definition and that
registry note. Bucket B is not mechanically checked for having a pin (only
bucket A is), so the promise sat unkept.

## Decision

**`catalog_url()` derives the endpoint from `settings.openrouter_api_base_url`,
at call time.**

```python
return f"{settings.openrouter_api_base_url.rstrip('/')}/models"
```

Call time, not import time, so a running process and a test that monkeypatches
the setting are both honoured — and so the test that matters can assert the URL
**handed to the transport**, not the return value of a helper. A module-level
constant computed at import would satisfy every other assertion here and still
dial the wrong host.

**And the behaviour the register asked for is now actually asserted**, for the
first time: `test_the_shipped_default_still_resolves_to_the_public_catalog`
pins scheme `https`, host `openrouter.ai`, path `/api/v1/models` on the shipped
default. Making a value configurable is exactly the moment to write the test
that stops its default drifting.

### Why there is no https guard here, when `readiness.py` has one

`readiness.probe_key_auth` refuses to dial at all when the configured base is
cleartext, and logs *"refusing to send the API key over a non-https base URL"*.
That is right for that call: it carries a bearer token, and not knowing whether
the key works is a better outcome than putting it on the wire in clear.

The catalog request carries **no credential**. It is public, unauthenticated and
free, fetched once per TTL window. Sending an unauthenticated `GET` to a base
the operator chose is the operator's decision; putting their API key on that
wire is not. Copying the guard across would block the legitimate reason to
change the setting — pointing the fetcher at a local double — while protecting
nothing.

That argument depends on a fact that could quietly stop being true, so it is
pinned: `test_the_catalog_request_carries_no_credential` reads
`_urlopen_catalog`'s source and fails if `Authorization`, `Bearer` or `api_key`
appears in it, with a positive partner asserting the headers it *does* send. If
a credential is ever added, that test goes red and the guard has to come with
it.

## Rejected alternatives

**Leave it hardcoded and document the divergence.** The divergence is the
defect. A comment saying "this one does not follow the setting" makes the
surprise cheaper to diagnose without making it less likely.

**Require https for the catalog too.** Protects nothing — no credential is sent
— and breaks pointing the fetcher at `http://127.0.0.1` for a test or an
air-gapped mirror, which is one of the reasons to make it configurable.

**Add a separate `OPENROUTER_CATALOG_URL` setting.** Two settings that must be
kept consistent, where one derived value would do. The failure mode being fixed
is precisely two URLs drifting apart.

## Consequences

An operator who sets `OPENROUTER_API_BASE_URL` now redirects the whole
OpenRouter surface, which is what the setting's name has always implied.

**What this does not do.** It does not validate the configured base URL at all —
a typo yields a catalog fetch that fails and degrades to `_FALLBACK_CATALOG`
prices, exactly as a network failure does today. Adding validation is a
separate, larger decision about how the app should behave on a misconfigured
base, and it would apply to all three call sites rather than this one.

The risk register's `catalog_fetcher.OPENROUTER_CATALOG_URL` entry is removed,
because the constant is gone; `test_the_registry_names_no_constant_that_has_been_deleted`
would otherwise fail. The behaviour it described is now a test rather than a note.
