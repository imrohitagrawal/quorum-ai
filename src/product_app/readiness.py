"""Startup smoke-probe for live-execution readiness.

The application can run in two modes:

* **Live mode** — ``OPENROUTER_LIVE_EXECUTION_ENABLED=true`` AND a
  non-empty ``OPENROUTER_API_KEY`` are both set. Every query run
  calls the real provider; the catalog, debate, and synthesis are
  LLM-driven.
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
from dataclasses import dataclass, field
from typing import Literal

from product_app.config import settings
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    openrouter_model_catalog_service,
)

_log = logging.getLogger(__name__)


ReadinessState = Literal["live", "offline_by_config", "offline_by_no_key"]


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
    if live_flag and has_key:
        state: ReadinessState = "live"
    elif live_flag and not has_key:
        state = "offline_by_no_key"
        reasons.append(
            "OPENROUTER_LIVE_EXECUTION_ENABLED=true but OPENROUTER_API_KEY is "
            "missing. Every query will fall back to local_simulation. Set "
            "OPENROUTER_API_KEY in the environment (or .env) and restart to "
            "enable live execution."
        )
    else:
        state = "offline_by_config"
        reasons.append(
            "OPENROUTER_LIVE_EXECUTION_ENABLED is not set to 'true'. Every "
            "query will fall back to local_simulation. Set it to 'true' in "
            "the environment (or .env) and restart to enable live execution."
        )

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
        reasons.append(
            "Could not fetch the live  catalog at startup: "
            f"{type(exc).__name__}. The static default model list "
            "will still be served; live pricing is unavailable."
        )
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
            "Default model ids not in current  catalog: "
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
    if state == "live" and not drift:
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
