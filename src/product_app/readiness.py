"""Startup smoke-probe for live-execution readiness.

The application can run in two modes:

* **Live mode** — ``OPENROUTER_LIVE_EXECUTION_ENABLED=true`` AND a
  non-empty ``OPENROUTER_API_KEY`` are both set, AND the provider has
  not rejected that key. Every query run calls the real provider; the
  catalog, debate, and synthesis are LLM-driven.
* **Offline / dev mode** — either flag is missing. Every query run
  falls back to ``local_simulation``; the debate and synthesis
  surfaces return templated text. The app still serves traffic.

The probe exists so an operator starting the app gets an immediate,
loud signal when they're in offline mode but expected live mode
(or vice versa). Without it, a misconfigured deployment serves
traffic that "looks fine" for hours until someone runs a real
query and notices all four slots are templated.

The probe runs once at process start, logs to the standard
logger, and exposes its findings on the ``/ready`` endpoint as
``live_readiness`` so an external check (load balancer, ops
dashboard) can surface the state without needing log access.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from product_app.config import settings
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    openrouter_model_catalog_service,
)

_log = logging.getLogger(__name__)


ReadinessState = Literal[
    "live",
    "offline_by_config",
    "offline_by_no_key",
    "offline_by_bad_key",
]

#: The verdict of the credential probe.
#:
#: ``"unknown"`` is both the boot value and the answer to every
#: ambiguous failure — a timeout, a 500, a DNS error. Only an explicit
#: 401/403 (the provider stating it does not accept this credential)
#: produces ``"unauthorized"``. Telling an operator their key is bad
#: because the network hiccuped would be its own dishonesty.
KeyAuthState = Literal["unknown", "ok", "unauthorized"]

#: Statuses that mean "the provider refused this credential", as opposed
#: to "the provider could not answer right now".
_CREDENTIAL_REFUSED_STATUSES = frozenset({401, 403})

_key_auth_lock = threading.RLock()
_key_auth_state: KeyAuthState = "unknown"

#: The probe transport: performs the request and returns the HTTP status.
#: Injectable so the suite can classify every outcome without a socket.
KeyAuthTransport = Callable[..., int]


# ---------------------------------------------------------------------------
# Closed set of operator-facing reason texts.
#
# ``reasons`` is served verbatim on the PUBLIC, unauthenticated ``/ready``
# endpoint, so every entry must come from this fixed vocabulary — never from
# interpolated runtime data (exception messages can carry hostnames, file
# paths, or credential fragments; those belong in the process log only).
# The single allowed variable part is the catalog-drift model-id list, which
# is provider catalog metadata already exposed via ``catalog_drift_ids``.
# ``tests/unit/test_readiness.py`` asserts every produced reason starts with
# one of ``APPROVED_REASON_PREFIXES`` — add new reasons HERE, not inline.
# ---------------------------------------------------------------------------

REASON_NO_KEY = (
    "OPENROUTER_LIVE_EXECUTION_ENABLED=true but OPENROUTER_API_KEY is "
    "missing. Every query will fall back to local_simulation. Set "
    "OPENROUTER_API_KEY in the environment (or .env) and restart to "
    "enable live execution."
)
REASON_OFFLINE_BY_CONFIG = (
    "OPENROUTER_LIVE_EXECUTION_ENABLED is not set to 'true'. Every "
    "query will fall back to local_simulation. Set it to 'true' in "
    "the environment (or .env) and restart to enable live execution."
)
REASON_CATALOG_UNREACHABLE = (
    "Could not fetch the live model catalog at startup. The static "
    "default model list will still be served; live pricing is unavailable."
)
REASON_CATALOG_DRIFT_PREFIX = "Default model ids not in current catalog: "
# MEASURED against the live provider, 2026-07-28, both directions:
#   funded + valid key   -> 200
#   UNFUNDED valid key   -> 401
# So on this provider an empty balance is NOT a 402 on this endpoint — it
# is indistinguishable from an invalid credential. An earlier draft of
# this comment asserted the opposite from reasoning rather than
# measurement, and dropped "funded" from the copy as a result. The reason
# text must therefore name BOTH causes: telling an operator with a valid
# but empty account to "check that the key is valid" sends them to
# inspect the one thing that is fine.
#
# It can also be something between us and the provider (a proxy answering
# 403 by policy), so the text names the check that failed rather than
# declaring the key itself dead.
#
# #176: this used to say "every query will fall back to local_simulation" —
# describing the PRE-#171 behaviour. Since #171, the key is still PRESENT (only
# refused), so ``_live_execution_enabled`` stays true and every model call is
# still attempted against the real provider — and refused the same way, so
# every query FAILS rather than falling back to anything. Measured by driving
# ``ProviderExecutionService.produce_initial_answers`` with a refused key: 4 of
# 4 slots come back FAILED, zero LOCAL_SIMULATION.
REASON_BAD_KEY = (
    "The OPENROUTER_API_KEY credential check was refused (HTTP 401/403). "
    "The key is present, so live execution stays on and every model call is "
    "still attempted against the real provider — and refused the same way, so "
    "every query FAILS rather than falling back to local_simulation. The key "
    "is either invalid or its account has no remaining credit — an unfunded "
    "key is refused here exactly like an invalid one. Check both (and that "
    "any network proxy allows the request), then restart to enable live "
    "execution."
)

#: Every reason the probe may emit must start with one of these.
APPROVED_REASON_PREFIXES = (
    REASON_NO_KEY,
    REASON_OFFLINE_BY_CONFIG,
    REASON_CATALOG_UNREACHABLE,
    REASON_CATALOG_DRIFT_PREFIX,
    REASON_BAD_KEY,
)


@dataclass(frozen=True)
class ReadinessReport:
    """The outcome of the startup probe.

    ``state`` is the headline:

    * ``"live"`` — every precondition is met; queries will hit the
      real provider.
    * ``"offline_by_config"`` — the operator has explicitly turned
      live execution off (either by leaving
      ``OPENROUTER_LIVE_EXECUTION_ENABLED`` false / unset, or by
      setting it to ``"false"``).
    * ``"offline_by_no_key"`` — the operator enabled live execution
      but did not set the API key. Every query will fall back to
      local simulation silently. This is the failure mode the probe
      is most designed to catch.
    * ``"offline_by_bad_key"`` — a key IS set and the provider
      REFUSED it (401/403 from the zero-cost ``GET /key`` probe).
      Configuration-only checks cannot see this, which makes it the
      quieter sibling of ``offline_by_no_key`` — except the failure
      mode differs: a refused key is still a PRESENT key (#171), so
      live execution stays on and every query FAILS rather than
      simulating. See ``REASON_BAD_KEY`` for the reason text and
      ``tests/unit/test_readiness_key_auth.py`` for the executed proof.

    ``reasons`` carries human-readable detail for logs and the
    ``/ready`` endpoint payload. ``catalog_drift_ids`` is the list
    of static defaults that were not found in the live catalog —
    empty when the catalog was unreachable (best-effort check).
    """

    state: ReadinessState
    reasons: tuple[str, ...]
    catalog_drift_ids: tuple[str, ...] = ()
    checked_at_process_start: bool = True
    extras: dict[str, str] = field(default_factory=dict)
    # PR-0 / Bug 11: ``catalog_loaded`` is true iff the startup
    # probe successfully fetched the live model catalog. It is
    # distinct from ``catalog_drift_ids``: a catalog can be loaded
    # AND have drifted defaults (e.g. the provider dropped a
    # default model id). The ``/status`` endpoint was conflating
    # the two — it reported ``model_catalog_loaded: false`` whenever
    # any default was drifted, which made the field useless for
    # "is the catalog subsystem healthy?" diagnostics. Operators
    # who want "any drift at all?" should look at
    # ``catalog_drift_ids`` directly.
    catalog_loaded: bool = False


def _live_flag_set() -> bool:
    """Read ``OPENROUTER_LIVE_EXECUTION_ENABLED`` from settings.

    Centralized here so the probe and the ``/ready`` endpoint agree
    on what "live mode" means. ``settings.openrouter_live_execution_enabled``
    is a ``bool`` populated by pydantic-settings from the env var.
    """
    return bool(settings.openrouter_live_execution_enabled)


def _has_api_key() -> bool:
    """True if a non-empty API key is set.

    The value is never logged or echoed in the report — only its
    presence is checked.
    """
    return bool(settings.openrouter_api_key)


def key_auth_state() -> KeyAuthState:
    """The credential probe's last verdict.

    Read on every ``run_startup_probe`` call — which happens on four hot
    paths (import, ``/ready``, ``/status``, ``/ui``) — so it must stay a
    lock-guarded memory read and never a network call.
    """
    with _key_auth_lock:
        return _key_auth_state


def record_key_auth_state(state: KeyAuthState) -> None:
    """Publish a probe verdict for every subsequent reader."""
    global _key_auth_state
    with _key_auth_lock:
        _key_auth_state = state


class _NoRedirect(HTTPRedirectHandler):
    """Refuse every redirect on the credential probe.

    urllib's default redirect handler copies ALL headers to the new
    location with no same-origin check, and permits http as a redirect
    target — so following one would hand ``Authorization: Bearer <key>``
    to whatever host the redirect names, in cleartext if it names http.
    A 302 from a captive portal or a typo'd base URL is enough.

    Refusing also protects the VERDICT: a redirect target answering 200
    would otherwise read as "the provider accepts this key", which is
    the exact lie this probe exists to prevent. Returning ``None`` makes
    urllib raise ``HTTPError`` for the 3xx, which the caller classifies
    as ``"unknown"`` — never ``"ok"``.
    """

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


#: Built once; the probe is the only caller and always wants this policy.
_KEY_PROBE_OPENER = build_opener(_NoRedirect)


def _urlopen_key_probe(*, url: str, api_key: str, timeout: float) -> int:
    """``GET {base}/key`` — auth-required, and it consumes ZERO tokens.

    That is the whole reason this endpoint was chosen over a one-token
    completion: an honesty check that bills the operator on every
    process start would not survive contact with the cost rails.

    The bearer token reaches exactly the configured origin and nowhere
    else: redirects are refused and the caller has already required an
    https URL.
    """
    request = Request(
        url=url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "HTTP-Referer": settings.openrouter_app_url,
            "X-Title": settings.openrouter_app_title,
        },
        method="GET",
    )
    # S310: the caller enforces the https scheme and redirects are
    # refused, so this cannot become a file:// or cleartext fetch.
    with _KEY_PROBE_OPENER.open(request, timeout=timeout) as response:  # noqa: S310
        return int(response.status)


def probe_key_auth(*, transport: KeyAuthTransport | None = None) -> KeyAuthState:
    """Ask the provider whether it accepts the configured credential.

    Returns ``"unknown"`` without dialling when live execution could not
    happen anyway (flag off, or no key). That gate is load-bearing: the
    test suite forces the flag off and blocks outbound sockets, and the
    contract gate proves that importing the app opens none.
    """
    api_key = settings.openrouter_api_key
    if not (settings.openrouter_live_execution_enabled and api_key):
        return "unknown"

    url = f"{settings.openrouter_api_base_url}/key"
    if transport is None and urlsplit(url).scheme != "https":
        # OPENROUTER_API_BASE_URL is operator-settable. Sending a bearer
        # token over cleartext is worse than not knowing whether the key
        # works, so decline to find out.
        _log.warning("live-execution probe: refusing to send the API key over a non-https base URL")
        return "unknown"

    send = transport if transport is not None else _urlopen_key_probe
    try:
        status = send(
            url=url,
            api_key=api_key,
            timeout=settings.openrouter_timeout_seconds,
        )
    except HTTPError as exc:
        if exc.code in _CREDENTIAL_REFUSED_STATUSES:
            # The one unambiguous signal: the provider named the
            # credential as the problem.
            _log.warning(
                "live-execution probe: provider rejected the API key (HTTP %s)",
                exc.code,
            )
            return "unauthorized"
        # 429/500/502/503 — the provider could not answer, which says
        # nothing about the key.
        _log.warning(
            "live-execution probe: key check inconclusive (HTTP %s); leaving state unchanged",
            exc.code,
        )
        return "unknown"
    except Exception as exc:  # noqa: BLE001 — probe is best-effort
        # The exception text stays in the process log ONLY: ``reasons``
        # is served on the public /ready endpoint and a raw error string
        # can carry hostnames, paths, or key material.
        _log.warning(
            "live-execution probe: key check failed (%s: %s); leaving state unchanged",
            type(exc).__name__,
            exc,
        )
        return "unknown"

    if status in _CREDENTIAL_REFUSED_STATUSES:
        return "unauthorized"
    if 200 <= status < 300:
        return "ok"
    return "unknown"


def start_key_auth_probe(*, transport: KeyAuthTransport | None = None) -> threading.Thread | None:
    """Run the credential probe on a background daemon thread.

    Returns ``None`` when there is nothing to prove (live execution off,
    or no key) — so a gated-off deployment starts no thread and opens no
    socket.

    It must not be synchronous: ``main.py`` already blocks module import
    on the catalog fetch, and this probe is a second network round-trip
    against an endpoint that can be slow or unreachable. Startup latency
    is not the price of honesty.
    """
    if not (settings.openrouter_live_execution_enabled and settings.openrouter_api_key):
        return None

    def _run() -> None:
        verdict = probe_key_auth(transport=transport)
        if verdict == "unknown":
            # "Inconclusive" is not a verdict, it is the ABSENCE of one.
            # Recording it would let a single timeout erase a proven
            # rejection and re-advertise the deployment as live — which
            # is exactly what every "leaving state unchanged" log line
            # in ``probe_key_auth`` already promises does not happen.
            return
        record_key_auth_state(verdict)

    thread = threading.Thread(target=_run, daemon=True, name="key-auth-probe")
    try:
        thread.start()
    except BaseException:  # noqa: BLE001 — thread exhaustion / interpreter shutdown
        # ``Thread.start`` raises RuntimeError when the process cannot
        # create another thread or is already shutting down. The app must
        # start even then: an unproven key verdict is a degraded
        # diagnosis, a failed import is an outage. Same guard, and the
        # same reasoning, as the dispatch in ``query_runs``.
        _log.warning("live-execution probe: could not start the key probe thread")
        return None
    return thread


def run_startup_probe() -> ReadinessReport:
    """Probe live-execution readiness and log a warning if degraded.

    Called once at process start (in ``product_app.main``). The
    probe is best-effort: a failing catalog fetch is logged at
    ``WARNING`` and reflected in ``catalog_drift_ids`` (which
    becomes the full static list, because "I could not check"
    conservatively means "treat them all as drifted"), but it
    does NOT raise. The app must always start.
    """
    live_flag = _live_flag_set()
    has_key = _has_api_key()

    reasons: list[str] = []
    if live_flag and has_key and key_auth_state() == "unauthorized":
        # A key that is PRESENT is not a key that WORKS. Reading the
        # cached probe verdict (never dialling here) is what lets this
        # run on the four hot paths that call the probe per request.
        # Ordered after neither of the two branches below by accident:
        # "no key at all" and "live execution is off" are the more
        # specific, more actionable diagnoses, so they keep priority —
        # a stale rejection must not mask them.
        state: ReadinessState = "offline_by_bad_key"
        reasons.append(REASON_BAD_KEY)
    elif live_flag and has_key:
        state = "live"
    elif live_flag and not has_key:
        state = "offline_by_no_key"
        reasons.append(REASON_NO_KEY)
    else:
        state = "offline_by_config"
        reasons.append(REASON_OFFLINE_BY_CONFIG)

    # Catalog drift check. The probe goes through the catalog
    # SERVICE (not the raw fetcher) so the service's
    # unreachable-catalog fallback policy is the one applied — the
    # same one the rest of the application sees. This keeps the
    # probe's view of "which models exist" consistent with what the
    # workspace UI will show on the next request.
    drift: tuple[str, ...] = ()
    catalog_loaded = False
    try:
        catalog_ids = {entry.model_id for entry in openrouter_model_catalog_service._entries()}
        catalog_loaded = True
        drift = tuple(model_id for model_id in DEFAULT_MODEL_IDS if model_id not in catalog_ids)
    except Exception as exc:  # noqa: BLE001 — probe is best-effort
        # The exception's class name and message stay in the process log
        # ONLY. ``reasons`` is served on the public /ready endpoint, so a
        # raw exception string (which can embed hostnames, paths, or key
        # material from a provider error body) must never flow into it —
        # the public reason is the fixed vocabulary entry.
        _log.warning(
            "live-execution probe: catalog fetch failed (%s: %s); serving the "
            "fixed catalog-unreachable reason on /ready",
            type(exc).__name__,
            exc,
        )
        reasons.append(REASON_CATALOG_UNREACHABLE)
        # Catalog unreachable: do not flag static ids as drifted
        # (we don't actually know). The route layer's drift check
        # will populate the per-request diagnostic.
        drift = ()

    if drift:
        # Operator-facing message: this goes into the ``reasons`` field
        # of the ``/ready`` JSON response (and the startup log). It is
        # NOT shown to end users — the UI banner builds its own plain
        # message from the ``catalog_drift_ids`` field. Keeping the
        # operator-facing text detailed (and end-user-facing text plain)
        # is the split.
        reasons.append(
            REASON_CATALOG_DRIFT_PREFIX
            + ", ".join(drift)
            + ". May have been renamed, deprecated, or moved."
        )

    report = ReadinessReport(
        state=state,
        reasons=tuple(reasons),
        catalog_drift_ids=drift,
        catalog_loaded=catalog_loaded,
    )

    # Log at WARNING when degraded so the operator sees it in the
    # startup banner; log at INFO when live so a healthy startup
    # leaves a paper trail.
    # Key the healthy-summary line off "no reasons at all", not state+drift:
    # a live state with an unreachable catalog still carries a reason, and
    # logging "catalog reachable" over it would lie to the operator.
    if not reasons:
        _log.info("live-execution probe: state=live (4 default models, catalog reachable)")
    else:
        for reason in reasons:
            _log.warning("live-execution probe: %s", reason)

    return report


#: Process-wide snapshot of the startup probe. Populated once at
#: app construction time so the warning shows in the startup
#: banner. The ``/ready`` endpoint reads a fresh probe result on
#: every request (cheap — it just inspects settings and does a
#: best-effort catalog lookup) so an operator hitting ``/ready``
#: after changing ``.env`` and restarting the process sees the
#: current state.
current_readiness: ReadinessReport | None = None
