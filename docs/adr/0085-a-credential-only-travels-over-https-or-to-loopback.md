# ADR-0085: A credential only travels over https, or to loopback

## Status

Accepted — 2026-09-01

## Context

`OPENROUTER_API_BASE_URL` is operator-settable. Four call sites build a URL
from it. **Three of them put the operator's API key on that URL, and two of
those three checked nothing about the scheme.**

| Call | Carries `Authorization: Bearer` | Scheme guard before this ADR |
|---|---|---|
| chat completions — `providers.py` (the paid answer, debate and synthesis call) | **yes** | **none** |
| audit model — `feedback_audit.py` (`make feedback-audit`) | **yes** | **none** |
| key probe — `readiness.py` | yes | `https` only, or it declines to dial |
| model catalog — `catalog_fetcher.py` | no | `{http, https}` (ADR-0080) |

ADR-0080 recorded the first row as a known, deliberately-deferred gap and
`docs/65-open-work.md` carried it as **W18**. The second row was not known: every
grep for this problem searched `openrouter_api_base_url`, the *settings*
attribute, and `feedback_audit` reads `os.environ["OPENROUTER_API_BASE_URL"]`
directly, so it never appeared in the results. It was found by re-grepping the
environment-variable name for this change.

Two things followed from the missing guard, both measured on `origin/main`
(`f81ffbb`) with a doubled `urlopen` that records requests:

* one full query run against a base of `http://openrouter.ai/api/v1` produced
  **11 dispatched requests**, every one carrying
  `Authorization: Bearer sk-or-SECRET` — the key in clear on the wire — and the
  run then reported `live_count 4`, `cost_source measured` and no failure at
  all. The leak was per-call, and nothing about the run looked wrong. (An
  earlier draft of this ADR said the call "returned `_DispatchedUnmeasured`".
  That holds only for some `urlopen` doubles — a `URLError` double gives
  `None` — and against the real host it would not have failed at all, so the
  claim is replaced with the dispatch count, which is the fact that matters
  and is not contingent on a double.);
* in `feedback_audit`, with the variable **unset**, the URL is
  `/chat/completions` and `urllib.request.Request` raises
  `ValueError: unknown url type: '/chat/completions'`. That is not one of the
  three classes its `except (HTTPError, URLError, TimeoutError)` catches, so the
  function's own docstring — *"Returns `None` on any failure"* — was false and
  the whole audit crashed instead of falling back to the local-only report.

## Decision

**A request that carries the operator's key may go to `https` anywhere, or to
`http` only when the host is loopback. Everything else is refused before the
request is built.**

The policy lives in one new stdlib-only module,
`src/product_app/credentialed_url.py`, which exports a **builder**, not a
predicate:

```python
def chat_completions_url(base_url: str) -> str | None
```

A call site cannot obtain the endpoint without passing the check, and the
builder **never raises** — a refusal that escaped as an exception would not be
a refusal. `urlsplit` itself raises `ValueError` on a netloc whose characters
NFKC-normalise into a URL delimiter, so both the builder and the log helper
catch it and refuse. Whitespace, control characters and userinfo are refused
for the same reason: `http.client` rejects each with `InvalidURL`, an
`HTTPException` that neither call site catches, and `InvalidURL`'s message for
`https://user:pass@host` contains the password verbatim. A trailing space in
an environment variable is the likeliest operator typo of the lot.

That is the answer to "what stops the *next* call site skipping this", and it is enforced
mechanically by
`test_exactly_one_module_builds_a_chat_completions_url`, which asserts that
across all of `src/product_app/*.py` exactly **one** module's code (comments and
docstrings stripped — rule 8) contains `/chat/completions`, and that it is the
guard.

### Why the paid call follows `readiness.py` and not `catalog_fetcher.py`

The two existing guards disagree, and the disagreement is principled rather than
accidental: ADR-0080 says so in as many words. The catalog request carries **no
credential**, so requiring TLS there would protect nothing while breaking a local
mirror. The paid call carries one. On that axis it is the same call as the key
probe, so `https` is the floor.

### Why loopback `http` is nevertheless allowed, when `readiness.py` allows nothing

The harm being prevented is a bearer token crossing a **network** in clear. A
loopback connection does not leave the machine, so there is no wire to observe —
the same reasoning that makes `http://localhost` a potentially-trustworthy
origin on the web platform.

`readiness.probe_key_auth` needs no such carve-out because it can decline
entirely (it returns `"unknown"`) and because its tests inject a `transport`.
`_post_messages` has no transport seam: its real-socket tests drive the actual
`urlopen` against `http://127.0.0.1:PORT`, deliberately, because doubles are what
hid the transport defects ADR-0078 and ADR-0084 exist to fix. **Measured by
mutation on 2026-09-01**: replacing the carve-out with `return False` — i.e.
https-only — turns **22 of the 31** tests in
`tests/unit/test_provider_streaming_transport.py` plus
`tests/unit/test_provider_call_time_budget.py` red. That is not a test-convenience
argument: those files are the repo's only real-socket coverage of the paid seam,
and an https-only rule would also remove an operator's ability to front the paid
call with a local gateway.

`readiness.py` is deliberately **not** refactored onto the shared module.
Widening it to allow loopback would loosen an existing security guard for no
demonstrated need, and that is not this change's concern.

### The loopback carve-out is narrower than "it cannot leave the machine"

An earlier draft justified the carve-out with *"a loopback connection does not
leave the machine, so there is no wire to observe."* **Review refuted that
twice, by execution, and it is corrected rather than deleted because the
refutation is the interesting part:**

* `urlopen` follows redirects and copies `Authorization` onto the redirected
  request. Measured: a base of `http://localhost:PORT` whose listener answers
  `302` to a foreign host delivered `Authorization: Bearer sk-or-SECRET` to
  that host, in clear. So whatever is listening on the loopback port has full
  control of where the key goes.
* `urlopen` also honours `http_proxy`, and `urllib`'s `proxy_bypass_environment`
  has **no** built-in loopback exemption — only `no_proxy`. Measured: with
  `http_proxy` set, a `http://127.0.0.1:...` base dialled the proxy host and
  put `Authorization: Bearer sk-or-SECRET` on that connection. (ADR-0054
  records — as an inherited, not re-measured, observation — that no proxy
  variables are set on the production machine.)

The honest statement of the carve-out is therefore narrower: **cleartext to
loopback does not put the key on a network by itself, but it delegates the
key's destination to whatever holds that port.** That is an acceptable trade
for a local gateway or a test double, which are its only uses, and it is
strictly narrower than the status quo it replaces, where cleartext to *any*
host was allowed. It is not a claim that nothing can leave the machine. The
redirect half is board row **W21**.

### Loopback is matched exactly, and fails closed

`urlsplit` lower-cases both scheme and host and strips embedded tabs (measured on
CPython 3.12.13), so `HTTP://LOCALHOST` normalises before comparison and
`http://127.0.0.1\t.evil.com` becomes `127.0.0.1.evil.com` — which is refused,
because the host is compared by **equality** against `localhost` or parsed by
`ipaddress` and asked `is_loopback`, never by prefix or substring.

`http://127.1` and `http://2130706433` do reach loopback once a resolver is
involved, and are **refused anyway**. Reimplementing name resolution to widen a
carve-out would trade a real risk for no gain, so the guard fails closed. So does
any hostname that merely resolves to loopback.

### The refusal returns `None`, and logs a host, not a URL

`None` is not a new shape. `_post_messages` already documents it as *"no charge
is possible — either no request left this process, or the provider refused it
before inference"*, and `_call_audit_model` already documents it as its
best-effort failure. `_DISPATCH_UNMEASURED` would have been a lie: it means
"dispatched and possibly billed" and would force an honest run's receipt to
`estimated` for a request that was never made.

The warning record carries the base URL's **scheme and host only**. A base URL
can carry userinfo (`https://user:pass@host`) and that is credential material;
`urlsplit(...).hostname` excludes it. `test_the_refusal_names_the_host_and_never_the_url`
pins this with a base of `http://someone:hunter2@gateway.internal/v1`.

It asserts over the record's own **attributes**, not over `caplog.text`, and
that distinction was itself found by review: the first version asserted
`"hunter2" not in caplog.text`, which renders only the formatted message. Since
this record puts everything in `extra`, adding
`"base_url": settings.openrouter_api_base_url` to that dict left the whole file
at `36 passed` while production's `JsonFormatter`, which emits unknown extras,
wrote the password out. **The assertion guarding the credential could not see
the credential.** The same mutation now fails.

## Rejected alternatives

**`https` only, with no exception.** The honest version of the rule, and it is
what `readiness.py` does. Rejected on a measurement, not a preference: it turns
22 of 31 real-socket tests red (above), and the only ways to keep them would be
to add a transport-injection seam to the one function that talks to a paid
upstream — widening the very surface this ADR is narrowing — or to stand up TLS
in unit tests. It would also break an air-gapped or local-gateway deployment,
which is a legitimate reason the setting is configurable at all.

**`{http, https}`, matching `catalog_fetcher`.** That is the policy for a request
with no credential. Applying it here would leave the defect exactly as it is and
only rule out `file:`.

**Gate cleartext on `runtime_environment is LOCAL`.** Couples a transport
decision to a deployment label, and would be defeated by a misconfigured
`RUNTIME_ENVIRONMENT`. "Is this host loopback" is a stronger fact than "does this
process think it is a dev box", and it needs no configuration to be true.

**A predicate (`is_credential_safe(url)`) called beside the existing
f-strings.** Keeps the URL construction duplicated at each call site, which is
precisely how the second call site came to be unguarded, and leaves nothing for
the population pin to assert.

**Raise `ValueError`, as `catalog_url()` does.** The catalog fetcher has a
caller that treats a raised error as a degradation to fallback prices.
`_post_messages` has an invariant — *"once `urlopen` has been called, this method
RETURNS; it never raises"* — and a catch-all that would classify the raise as
`_DISPATCH_UNMEASURED`, i.e. possibly billed. Returning `None` states the truth
directly instead of laundering it through an exception handler.

Stated as a contract, not as an observed difference: review mutated the refusal
to `_DISPATCH_UNMEASURED` and diffed every run-level field — `status`,
`live_count`, `local_count`, `cost_source`, `actual_cost_usd`, `failed_steps`,
the daily meter — and found **no difference in any of them**, because a refused
base refuses every call in the run and no measured slot survives for the
distinction to protect. It is still the right return; it is not a defect that
today's runs cannot tell the difference.

## Consequences

An operator who points `OPENROUTER_API_BASE_URL` at a cleartext remote host now
gets **no live answers**, plus one `provider_base_url_refused` warning per slot
(measured: four per run) naming the scheme and host, instead of a working
deployment that leaks the key on every call.

**The failure is HARD, not soft, and an earlier draft of this paragraph had it
backwards.** It said the run "degrades to local simulation exactly as it does
when the key is absent". Measured — `produce_initial_answers` with a key
present and a refused base against the same call with no key:

| | slot status | provider path |
|---|---|---|
| refused base, key present | `failed` ×4 | `openrouter_search`, empty text |
| no key | `completed` ×4 | `local_simulation` |

`providers.py:608` is why: with live execution enabled a slot that produced no
live text takes `_failed_answer`, because simulation is a whole-run mode and
never a per-model substitute (#171). The run then ends `partial` with
`failed_steps` covering initial answers, both debate rounds and synthesis, and
the workspace degraded banner fires. Nothing is misreported to the user — but
an operator diagnosing this must not be told to expect simulated answers.

No real money is charged. The deployment-wide daily spend **meter** is still
charged the run's estimate, which is pre-existing and identical in the no-key
case.

**An operator learns about this from the log and from nowhere else.** `/ready`
still reports `state: "live"` with empty reasons, because
`readiness.probe_key_auth` returns `"unknown"` for a cleartext base and only an
explicit `"unauthorized"` sets `offline_by_bad_key`. `/status`, `/metrics` and
`/ui/ops` carry no base-URL field. Making a refused base visible on `/ready` is
a readiness-surface decision, not a transport one, and is not taken here.

`make feedback-audit` with the variable unset now writes the local-only report
instead of crashing with a `ValueError`.

### What this does NOT do — a redirect still carries the key

The guard checks the **configured base**, not the **final URL**.
`urllib.request.urlopen` follows redirects and copies every header except
`Content-Length` and `Content-Type` onto the redirected request — **measured on
loopback in this worktree on 2026-09-01**: a `POST` carrying
`Authorization: Bearer sk-or-SECRET` to a server answering `302` arrived at the
redirect target with that header intact. So an `https` base that redirects to
`http://` still puts the key on the wire in clear, and this ADR does not stop it.

**This is sharper than "a limitation", and the sharpening matters:** the
loopback carve-out introduced above is the enabling condition for the worst
form of it. A base of `http://localhost:PORT` — the deployment the carve-out
exists to support — hands the key's final destination to whatever is listening
on that port, because one `302` from it delivers `Authorization: Bearer …` to
an arbitrary remote host in clear. Measured, on loopback, in this worktree.

The mechanism to close it already exists **in this repository** and this ADR
does not adopt it: `readiness.py` ships `class _NoRedirect(HTTPRedirectHandler)`
plus `_KEY_PROBE_OPENER = build_opener(_NoRedirect)`, and its docstring already
records the same measurement. So "follow `readiness.py`" — which is this ADR's
argument for the scheme — is followed for the scheme half of readiness's
credential policy and **not** for the redirect half. The reason is scope, not
disagreement: every existing test doubles `providers.urlopen` directly, so
moving the paid call to an opener changes how the whole seam is tested. It is
recorded as **W21** on `docs/65-open-work.md` rather than smuggled in here.

A second, adjacent gap found by the same review and recorded as **W22**:
`providers._tavily_search` sends `Authorization: Bearer <the operator's Tavily
key>` to `f"{settings.tavily_api_base_url}/search"` with no scheme guard at
all, on a setting that is operator-settable in exactly the same way.
Demonstrated dialling `file:///etc/passwd/search` with the key attached. It is
a different credential and a different setting, so this ADR's table — which is
scoped to `OPENROUTER_API_BASE_URL` — is correct as written, and the policy
sentence above is a policy for that variable, not yet a property of the
process.

Beyond the scheme and the loopback question, the base URL is still not
validated; ADR-0080's closing paragraph on that remains true.
