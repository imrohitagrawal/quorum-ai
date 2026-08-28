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

**No test asserted that behaviour.** Measured 2026-08-28 on `97827bb`
(`git grep -c OPENROUTER_CATALOG_URL`): **5 occurrences across 3 files** — three
in `catalog_fetcher.py` (its definition and two uses), one in that registry
note, and one in the open-work board's own row for this item. Outside its own
module, nothing but prose named it, and **no test compared it to anything**.
Bucket B is not mechanically checked for having a pin (only bucket A is), so the
promise sat unkept.

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

### The scheme IS constrained — to http or https

`urlopen` speaks more than http. A `file://` base would make the fetcher read an
arbitrary local path and serve its contents as the **live price catalog**;
`ftp:` and `data:` are no better. The old hardcoded literal made that
unreachable by construction, so making the endpoint configurable is exactly the
moment to keep it unreachable on purpose. `catalog_url()` raises `ValueError` on
any other scheme.

That is the SSRF-adjacent obligation the risk register recorded against the old
constant, now enforced **at runtime** rather than only asserted on the shipped
default. Review found this gap after the first version of this change, which
constrained nothing.

### Why there is no *https* guard, when `readiness.py` has one

`readiness.probe_key_auth` refuses to dial at all when the configured base is
cleartext, and logs *"refusing to send the API key over a non-https base URL"*.
That is right for that call: it carries a bearer token, and not knowing whether
the key works is a better outcome than putting it on the wire in clear.

The catalog request carries **no credential**. It is public, unauthenticated and
free, fetched once per TTL window. Sending an unauthenticated `GET` to a base
the operator chose is the operator's decision; putting their API key on that
wire is not. Requiring https here would block the legitimate reason to make this
configurable — pointing the fetcher at `http://127.0.0.1` — while protecting
nothing. `test_http_is_allowed_so_a_local_double_still_works` is the positive
partner that stops the guard quietly hardening into https-only.

**A gap this change does NOT close, stated because the contrast above invites
the wrong conclusion.** `readiness.py` guards that credential; `providers.py`
does **not** — it sends `Authorization: Bearer …` to
`f"{settings.openrouter_api_base_url}/chat/completions"` with no scheme check at
all. So the codebase is *inconsistent* about this, not careful about it. That is
pre-existing and outside this change's concern (the catalog), and it is recorded
as **W18** on `docs/65-open-work.md` rather than fixed here, because the paid
path deserves its own reviewer.

That argument depends on a fact that could quietly stop being true, so it is
pinned — **on the artefact, not on the source text**, and the difference is not
academic. The first version of the pin read `_urlopen_catalog`'s source and
failed if `authorization`, `bearer` or `api_key` appeared in it. Review defeated
it in one small edit: a module-level helper returning
`{"Authorization": f"Bearer {key}"}`, splatted into the existing header dict,
contains none of those tokens *inside the scanned function*. The pin stayed
green, **the whole 3,767-test suite stayed green**, and a loopback server driven
with a cleartext base received the operator's key in the clear.

`test_the_catalog_request_carries_exactly_two_headers_and_no_credential` now
patches the module's `urlopen`, takes the `Request` the code really built, and
asserts `set(request.headers) == {"Accept", "User-agent"}` — an **exact set**,
not a denylist of token names, because a denylist can always be spelled around.
It also asserts the two allowed headers carry their real values (so the set
check is reading a populated block) and that nothing smuggled a key into the
URL. The exploit above now fails it.

## Rejected alternatives

**Leave it hardcoded and document the divergence.** The divergence is the
defect. A comment saying "this one does not follow the setting" makes the
surprise cheaper to diagnose without making it less likely.

**Require https for the catalog too.** Protects nothing — no credential is sent
— and breaks pointing the fetcher at `http://127.0.0.1` for a test or an
air-gapped mirror, which is one of the reasons to make it configurable.
Constraining the *scheme set* to `{http, https}` is a different and cheaper
thing, and that is what shipped.

**Add a separate `OPENROUTER_CATALOG_URL` setting.** Two settings that must be
kept consistent, where one derived value would do. The failure mode being fixed
is precisely two URLs drifting apart.

## Consequences

An operator who sets `OPENROUTER_API_BASE_URL` now redirects the whole
OpenRouter surface, which is what the setting's name has always implied.

**What this does not do.** Beyond the scheme, it does not validate the
configured base URL — a typo in the host yields a catalog fetch that fails and
degrades to `_FALLBACK_CATALOG` prices, exactly as a network failure does today. Adding validation is a
separate, larger decision about how the app should behave on a misconfigured
base, and it would apply to all three call sites rather than this one.

The risk register's `catalog_fetcher.OPENROUTER_CATALOG_URL` entry is removed,
because the constant is gone; `test_the_registry_names_no_constant_that_has_been_deleted`
would otherwise fail. The behaviour it described is now a test rather than a note.
