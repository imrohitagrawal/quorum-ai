# ADR-0090: A credential does not follow a redirect, and Tavily gets the same scheme check

## Status

Accepted — 2026-09-01

## Context

ADR-0085 (W18) closed the scheme gap on the two calls that put the operator's
OpenRouter key on a URL built from `OPENROUTER_API_BASE_URL`. Its own
"Consequences" section named two things it explicitly did **not** close, and
both were carried on the board rather than smuggled into that PR:

* **W21.** `urllib.request.urlopen` follows a redirect and copies every
  header except `Content-Length`/`Content-Type` onto the redirected request.
  A base that passes ADR-0085's check — including the `http://localhost`
  carve-out that check itself needs to keep the repo's real-socket tests
  runnable — can still answer its *first* request with a `302` and hand the
  key to whatever host `Location` names, in clear if that host speaks
  `http`. Measured on loopback, 2026-09-01: a `POST` carrying
  `Authorization: Bearer sk-or-SECRET` to a server answering `302` arrived at
  the redirect target with that header intact.
* **W22.** `providers._tavily_search` sent `Authorization: Bearer <the
  operator's Tavily key>` to `f"{settings.tavily_api_base_url.rstrip('/')}/search"`
  with **no scheme guard of any kind** — not even the weaker one ADR-0085
  closed for OpenRouter. `tavily_api_base_url` is a plain, operator-settable
  field exactly like `openrouter_api_base_url`. Demonstrated dialling
  `http://attacker.example.com/search` with the key attached in clear.

Both are club­bed into one PR here, and the first line of that PR's body
states why: they are the same concern — hardening the two credential-bearing
outbound calls in `providers.py` against the two bypass vectors ADR-0085's
own review found and did not fix — not two unrelated items bundled for size
(rule 17). W21 is explicitly W18's dependent on the board; W22 is its
`credentialed_url.py` module-docstring-documented neighbour, added to the
same guard that already reserved a paragraph explaining why it did NOT yet
cover Tavily.

## Decision

**Both fixes land in `credentialed_url.py` — the module ADR-0085 already
built, extended rather than duplicated — as a shared opener plus a second
URL builder:**

```python
class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs) -> None:
        return None

CREDENTIAL_OPENER = build_opener(_NoRedirect)

def tavily_search_url(base_url: str) -> str | None:
    url = f"{base_url.rstrip('/')}/search"
    return url if is_credential_safe(url) else None
```

`providers.py` binds its module-level `urlopen` name to
`CREDENTIAL_OPENER.open` (see "Why a rebind, not a rename" below), and
`_tavily_search` builds its URL through `tavily_search_url` exactly the way
`_post_messages` already builds its through `chat_completions_url`.

### Why one shared opener, not two

Both call sites carry a Bearer credential to an operator-settable base and
both need the identical policy: refuse every redirect, unconditionally.
There is no dimension on which OpenRouter's and Tavily's redirect exposure
differ — the mechanism `readiness.py` already uses
(`class _NoRedirect(HTTPRedirectHandler)` /
`_KEY_PROBE_OPENER = build_opener(_NoRedirect)`) has no per-credential
parameter either. Building two openers would be two untested copies of the
same nine lines with no behavioural difference to justify the duplication.

### Why this module builds its own `_NoRedirect` rather than importing readiness's

`readiness.py` and `credentialed_url.py` do not import each other today (no
cycle either way), so importing `_KEY_PROBE_OPENER`'s class from
`readiness.py` into `credentialed_url.py` would work mechanically. It is not
done, because `credentialed_url.py`'s existing docstring already states, and
this ADR does not want to make false, that the module "depends on nothing
but the standard library" — load-bearing for `feedback_audit`, whose every
other `product_app` import is function-local so the audit can run
independently of the application's runtime state. `readiness.py` imports
`product_app.config` and `product_app.model_slots`. Importing `_NoRedirect`
from it would pull that whole chain into the one module that exists to be
free of it. Nine duplicated lines, both now covered by a real-socket test,
is a smaller cost than that.

### Why a rebind of `urlopen`, not a rename of the call sites

The direct fix — replace `urlopen(request, timeout=...)` with
`CREDENTIAL_OPENER.open(request, timeout=...)` at both call sites — would
work for production, and breaks the test suite: 17 test files across
`tests/unit/` and `tests/integration/` intercept both calls with
`monkeypatch.setattr(providers_module, "urlopen", double)` (or the
string-path form of the same call), and none of them would be replaced by
that edit's own diff, since the call sites would stop referencing the name
`urlopen` at all. Every one of those tests would then dial the double-hop
through the real opener with no double in place at all — in CI, with
outbound sockets blocked, that is a hang or an immediate `OSError`, not a
loud, legible failure naming its cause.

Instead, `providers.py` keeps calling `urlopen(request, timeout=...)` at
both sites — unchanged text — and rebinds the module-level name itself:

```python
urlopen = CREDENTIAL_OPENER.open
```

A bare name inside a function body resolves against the module's globals at
**call** time, not at `def` time, so `monkeypatch.setattr(providers_module,
"urlopen", double)` still intercepts both calls exactly as before: it
replaces whatever the module attribute is bound to, not a snapshot of the
stdlib free function. Verified: all 17 files, plus the two new real-socket
tests added by this change, pass with zero edits to any pre-existing test.

### Why the board's W21 needle changes shape

`docs/65-open-work.md`'s W21 row was pinned `PRESENT`-polarity on the call
site's literal text
(`with urlopen(request, timeout=settings.openrouter_timeout_seconds) as
response:`), with a paragraph explaining why an `ABSENT` needle naming an
identifier was rejected — `scripts/check_open_work.py` strips `#` comments
but not docstrings, so a docstring merely *claiming* the fix could flip the
row without landing it. Because the fix above deliberately keeps that
exact call-site text (the previous section explains why), the old needle
can no longer distinguish fixed from broken — it is present either way. The
evidence cell is rewritten to pin the line the fix actually **adds**
instead: `ABSENT src/product_app/providers.py :: urlopen = CREDENTIAL_OPENER.open`.
This is not the shape the earlier rejection was written against: it names a
full assignment statement, not a bare identifier a sentence could restate in
passing, and it is additionally backed by a real-socket bite-proof
(`tests/unit/test_credential_transport_guard.py::test_a_redirect_never_delivers_the_openrouter_key`)
that a doc-only claim cannot pass. W22's needle is untouched — the fix
naturally deletes the literal f-string it names.

## Rejected alternatives

**Gate the redirect on `Location`'s scheme/host, reusing `is_credential_safe`
inside a custom `redirect_request`.** Considered as a way to allow a
same-scheme, same-host redirect (e.g. a load balancer's internal hop) while
refusing everything else. Rejected: `readiness.py`'s existing `_NoRedirect`
already refuses unconditionally, or a demonstrated real-world need to be
narrower. No such need was found, and a permissive redirect policy is a
second place the scheme check could drift from the first.

**Fold this into ADR-0085 / the original W18 PR.** Rejected there, at the
time, for the reason ADR-0085 itself records: doing so would have changed
how the whole paid seam is tested inside a PR whose stated concern was the
scheme guard alone (rule 17). The same reasoning holds now for keeping this
a separate ADR from ADR-0085 rather than an amendment to it — the decision
being recorded (redirect + a second scheme guard) is materially different
from ADR-0085's (scheme guard for one call).

**Two separate PRs, one per row.** Rejected per this PR's own opening
sentence: W21 and W22 are the same concern (hardening `providers.py`'s two
credential-bearing outbound calls against the two bypass vectors ADR-0085's
review found), in the same file, sharing the fix's actual mechanism
(`CREDENTIAL_OPENER`). Splitting them would cost a second review-and-deploy
cycle on the same code for no risk reduction.

## Consequences

An operator whose configured base — OpenRouter or Tavily — answers with a
redirect now gets that call refused (an `HTTPError` for the 3xx, caught by
each call site's existing catch-all exactly like any other transport
failure) instead of the key following the redirect. Neither call site's
documented failure shape changes: `_post_messages` still returns `None`
without dialling, or an unbilled failure once dialling starts;
`_tavily_search` still degrades to `[]` (the local-simulation stub).

A configured Tavily base that is cleartext-to-a-remote-host or a non-http(s)
scheme is now refused before it is dialled at all, logged as
`tavily_base_url_refused` with scheme and host only (never the configured
URL, which can carry userinfo) — the same shape ADR-0085 gives
`provider_base_url_refused` for OpenRouter.

Nothing about billing accounting changes: a refused Tavily search was
already unbilled (Tavily has no separate meter in this codebase), and a
refused OpenRouter redirect is `None`/unbilled for the same reason ADR-0085's
own refusal is — nothing left the process, so nothing can have been charged.

`readiness.py`'s `_NoRedirect`/`_KEY_PROBE_OPENER` are untouched. They remain
the probe's own copy of the same idea; nothing here refactors them, per the
"Why this module builds its own" section above.
