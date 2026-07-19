"""Property-based API contract gate (Schemathesis) — R2 Phase 0, ledger RB-8.

This complements, and deliberately does not duplicate, the existing OpenAPI
governance in this package:

* ``tests/contract/test_openapi_contract.py`` + ``scripts/validate_openapi_contract.py``
  are a **drift guard**: they prove the checked-in ``openapi.yaml`` is a
  byte-faithful render of ``app.openapi()``. They say nothing about whether the
  *running app* obeys that spec.
* This module is the **conformance guard**: it generates requests from the
  spec and asserts the app's real responses obey it.

RB-8 asked for a concrete, stated config rather than a tool name. It is:

===========================  ==================================================
Setting                      Value (and why)
===========================  ==================================================
Transport                    ``schemathesis.openapi.from_asgi`` — the FastAPI
                             ASGI app is called in-process. No server process,
                             no listening socket, $0. "No network" is now true
                             as well, but it was NOT true when this line was
                             first written: see the hermeticity note below.
Checks                       ``not_a_server_error``,
                             ``response_schema_conformance``,
                             ``status_code_conformance`` (exactly the three
                             named in the Phase-0 brief). Every other bundled
                             check is off — notably ``unsupported_method``,
                             which fires on this API only because
                             ``GET /v1/query-runs/estimate`` is legitimately
                             matched by the ``GET /v1/query-runs/{id}`` route
                             and answered 422, not 405. That is routing, not a
                             contract defect.
``max_examples``             ``MAX_EXAMPLES`` below — set from a MEASURED
                             runtime sweep, see that constant's docstring.
Stateful testing             OFF. Stateful runs need OpenAPI ``links`` to chain
                             operations; this spec declares none, and the one
                             operation that creates a resource
                             (``POST /v1/query-runs``) is excluded (below), so
                             there is no lifecycle to chain. Turning it on
                             would generate nothing extra.
Hypothesis ``deadline``      ``None``. Per-example wall-clock deadlines are a
                             flake source in CI (cold imports, GC); this gate
                             asserts contract conformance, and the *timing*
                             gate is ``make perf-gate``, not this file.
``suppress_health_check``    ``function_scoped_fixture`` — ``tests/conftest.py``
                             installs an autouse function-scoped reset fixture
                             which Hypothesis (correctly) warns does not re-run
                             per example. The per-example state this gate cares
                             about (the rate-limiter buckets) is reset
                             explicitly in the test body instead.
``derandomize``              True — a fixed corpus per run so a CI failure is
                             reproducible rather than a one-in-N surprise.
===========================  ==================================================

EXCLUDED OPERATION (stated loudly, per the Phase-0 rule that silent exclusions
are a lie about coverage):

* ``POST /v1/query-runs`` — the only operation that starts the debate pipeline.
  On the legacy/test session path it executes the full four-model run inline,
  and on the cookie path it spawns a background thread. It is the surface that
  would reach a paid provider if live execution were ever on. Fuzzing it would
  break both hermeticity and the runtime budget. It is covered instead by the
  unit/integration suites. NOTHING ELSE is excluded, and
  ``test_every_spec_operation_is_covered_or_explicitly_excluded`` fails if a
  future endpoint quietly escapes this gate.

HERMETICITY ($0, no egress) is a construction, not a comment. The ASGI
transport never opens a listening socket, but that was never the whole story:
this module imports ``product_app.main``, whose startup fires
``openrouter_catalog_fetcher.prewarm()`` (main.py:252), and catalog-backed
operations re-enter ``list_models()`` while the fuzzer drives them. MEASURED
before the fix, with a socket guard installed and the gate's own recipe
(``uv run pytest tests/contract -q --no-cov``): **57 outbound TLS connect
attempts to openrouter.ai per run** — on a *blocking* CI job whose "$0" then
rested on that third-party endpoint staying free and up. ``_pin_static_catalog``
below closes it, and ``tests/contract/test_contract_gate_hermeticity.py`` is
the mechanical proof, running this module in a fresh interpreter with outbound
sockets blocked (and proving itself red against a pin-removed mutant).

KNOWN OPEN CONTRACT DEFECTS: see ``KNOWN_CONTRACT_DEFECTS``. They are real,
reproduced deterministically by the ratchet tests at the bottom of this file,
and reported to the R2 ledger. They are allowlisted per operation *and per
failure kind* so any NEW conformance failure still fails this gate.
"""

from __future__ import annotations

from time import monotonic
from typing import Any
from uuid import uuid4

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis import BaseSchema, Case
from schemathesis.checks import not_a_server_error
from schemathesis.core.failures import FailureGroup
from schemathesis.core.result import Ok
from schemathesis.specs.openapi.checks import (
    response_schema_conformance,
    status_code_conformance,
)
from starlette.testclient import TestClient

from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher

#: TTL used when pinning the static catalog. Long enough that the pin never
#: expires mid-session and lets a fetch through.
_CATALOG_PIN_TTL_SECONDS = 86_400.0


def _pin_static_catalog() -> None:
    """Serve the app's own static offline catalog instead of fetching it.

    Same seam, same reason, as ``tests/perf/test_workflow_latency_percentiles``:
    priming the shared fetcher's cache is the smallest change that covers both
    egress sites at once — ``_cache_valid()`` short-circuits before any
    transport is touched, so the import-time ``prewarm()`` and the per-request
    ``list_models()`` in model-slot validation both stay offline.
    ``_FALLBACK_CATALOG`` is the same static list the app itself serves in
    degraded mode, so the gate still fuzzes the pipeline the app really runs.
    """
    openrouter_catalog_fetcher._cache_entries = list(_FALLBACK_CATALOG)  # noqa: SLF001
    openrouter_catalog_fetcher._cache_expires_at = monotonic() + _CATALOG_PIN_TTL_SECONDS  # noqa: SLF001


# Executed at import time, i.e. *before* ``product_app.main`` is imported and
# its startup fires ``prewarm()``. Ordering is the whole fix: a pin applied
# from a fixture would run after the prewarm thread had already reached the
# network. ``tests/contract/test_contract_gate_hermeticity.py`` asserts both
# the ordering (statically) and the resulting silence (in a fresh interpreter
# with sockets blocked).
_pin_static_catalog()

from product_app.main import app  # noqa: E402  (must follow the catalog pin)
from product_app.query_runs import (  # noqa: E402  (must follow the catalog pin)
    _account_rate_limiter,
    _ip_rate_limiter,
)

#: The three checks the Phase-0 brief names. Kept as an explicit list (not
#: "all checks") so adding a check is a deliberate, reviewed change.
CONTRACT_CHECKS = [
    not_a_server_error,
    response_schema_conformance,
    status_code_conformance,
]

#: Measured, not guessed. Wall-clock sweep of the 13 fuzzed operations on this
#: machine (macOS, ``uv run pytest -q --no-cov -p no:randomly``, reported
#: pytest duration / total process ``real``):
#:
#:     max_examples=  25  ->  2.8 s /  3.7 s
#:     max_examples=  50  ->  3.7 s /  5.4 s
#:     max_examples= 100  ->  4.8 s /  5.7 s
#:     max_examples= 200  ->  7.5 s /  9.8 s
#:     max_examples= 400  -> 16.4 s / 17.6 s
#:
#: 100 is the knee: ~5 s, i.e. roughly a third of the existing ~14 s full-suite
#: budget, so the gate is cheap enough to run on every PR. Every distinct
#: failure *family* the sweep ever surfaced (see KNOWN_CONTRACT_DEFECTS) was
#: already surfaced at 25; 200 and 400 found nothing 100 did not, they only cost
#: more wall clock. Revisit when operations are added.
MAX_EXAMPLES = 100

#: Excluded from generation — see the module docstring for the reason.
EXCLUDED_OPERATIONS: frozenset[tuple[str, str]] = frozenset({("POST", "/v1/query-runs")})

#: Open contract defects this gate has FOUND and is holding the line on.
#: Key: ``(method, path)``. Value: ``{"<status>:<FailureClass>": "why"}``.
#: A failure whose key is not listed here fails the gate.
KNOWN_CONTRACT_DEFECTS: dict[tuple[str, str], dict[str, str]] = {
    # DEFECT 1 (all body/param-validating operations): the app installs a
    # custom RequestValidationError handler (``main._format_validation_error``)
    # that returns ``{"detail": {"code", "message", "field_errors"}}`` — an
    # OBJECT — but FastAPI's auto-generated spec still declares 422 as
    # ``HTTPValidationError`` with ``detail`` as an ARRAY of ``ValidationError``.
    # Every 422 the API emits violates its own published contract. The fix
    # (declare the real envelope in the spec + regenerate openapi.yaml) spans
    # files outside this agent's Phase-0 ownership; filed to the ledger.
    #
    # DEFECT 2: undeclared 404. Both ``/v1/query-runs/{id}`` operations answer
    # 404 QUERY_RUN_NOT_FOUND and ``/feedback/audit`` answers 404
    # AUDIT_NOT_FOUND, but each declares only its success status (+422).
    #
    # DEFECT 3: undeclared 400. A body that is not parseable JSON gets
    # Starlette's ``{"detail": "There was an error parsing the body"}`` with
    # status 400, which no operation declares. (Reproduced by the fuzzer at
    # max_examples 25/200/400 but not 50/100 — the corpus differs per
    # ``max_examples`` — so it is registered from the measured superset and
    # pinned deterministically by a ratchet test below.)
    ("POST", "/v1/query-runs/estimate"): {
        "422:JsonSchemaError": "DEFECT 1 - custom 422 envelope vs HTTPValidationError",
        "400:UndefinedStatusCode": "DEFECT 3 - undeclared 400 malformed-JSON body",
    },
    ("POST", "/v1/query-runs/warnings"): {
        "422:JsonSchemaError": "DEFECT 1 - custom 422 envelope vs HTTPValidationError",
        "400:UndefinedStatusCode": "DEFECT 3 - undeclared 400 malformed-JSON body",
    },
    ("GET", "/v1/query-runs/{query_run_id}"): {
        "422:JsonSchemaError": "DEFECT 1 - custom 422 envelope vs HTTPValidationError",
        "404:UndefinedStatusCode": "DEFECT 2 - undeclared 404 QUERY_RUN_NOT_FOUND",
    },
    ("DELETE", "/v1/query-runs/{query_run_id}"): {
        "422:JsonSchemaError": "DEFECT 1 - custom 422 envelope vs HTTPValidationError",
        "404:UndefinedStatusCode": "DEFECT 2 - undeclared 404 QUERY_RUN_NOT_FOUND",
    },
    ("GET", "/feedback/audit"): {
        "404:UndefinedStatusCode": "DEFECT 2 - undeclared 404 AUDIT_NOT_FOUND",
    },
}

schema = schemathesis.openapi.from_asgi("/openapi.json", app)

_fuzzable: BaseSchema = schema
for _method, _path in sorted(EXCLUDED_OPERATIONS):
    _fuzzable = _fuzzable.exclude(method=_method, path=_path)


def _failure_key(sub_exception: BaseException, status_code: int) -> str:
    """Stable identity for one conformance failure: ``<status>:<FailureClass>``."""
    return f"{status_code}:{type(sub_exception).__name__}"


@_fuzzable.parametrize()
@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_api_conforms_to_openapi_contract(case: Case) -> None:
    """Generated requests must obey the published contract.

    Failures are allowed through ONLY if their ``<status>:<FailureClass>`` key
    is registered in :data:`KNOWN_CONTRACT_DEFECTS` for that operation.
    """
    # The rate limiters are process-global token buckets (30/min). A fuzz run
    # would exhaust them and turn every later example into an undocumented 429,
    # which tells us nothing about the contract. Reset per example; the 429
    # path has its own dedicated tests in tests/security.
    _ip_rate_limiter.clear()
    _account_rate_limiter.clear()
    # Authenticate via the legacy X-Account-Id header (enabled for tests in
    # tests/conftest.py) so generation reaches the real handlers instead of
    # bouncing off 401. A fresh account per example keeps runs independent.
    response = case.call(headers={"X-Account-Id": str(uuid4())})
    allowed = KNOWN_CONTRACT_DEFECTS.get((case.method.upper(), case.path), {})
    try:
        case.validate_response(response, checks=CONTRACT_CHECKS)
    except FailureGroup as group:
        unexpected = [
            sub
            for sub in group.exceptions
            if _failure_key(sub, response.status_code) not in allowed
        ]
        if unexpected:
            raise AssertionError(
                f"{case.method} {case.path}: unregistered contract failure(s) "
                f"{[_failure_key(s, response.status_code) for s in unexpected]}\n"
                + "\n".join(str(sub) for sub in unexpected)
            ) from group


def test_every_spec_operation_is_covered_or_explicitly_excluded() -> None:
    """No endpoint may silently escape the contract gate.

    A new route added to the app is fuzzed automatically; this test exists so
    that *removing* one from coverage requires editing ``EXCLUDED_OPERATIONS``
    (and therefore the stated-exclusions docstring), never a silent drop.
    """
    spec_operations = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    fuzzed: set[tuple[str, str]] = set()
    for result in _fuzzable.get_all_operations():
        operation = result.ok() if isinstance(result, Ok) else None
        assert operation is not None, f"schema failed to load an operation: {result}"
        fuzzed.add((operation.method.upper(), operation.path))
    assert fuzzed == spec_operations - EXCLUDED_OPERATIONS, (
        "Contract-gate coverage drifted from the spec. Fuzzed operations must be "
        "every spec operation minus the explicitly documented exclusions."
    )
    assert spec_operations >= EXCLUDED_OPERATIONS, (
        "EXCLUDED_OPERATIONS names an operation that is not in the spec — stale exclusion."
    )


# --- Ratchet: the allowlisted defects must still be real ---------------------
# Each allowlisted entry above is reproduced here deterministically (no
# Hypothesis). When the underlying defect is fixed, THESE tests fail, forcing
# the allowlist entry to be deleted. That is what stops the allowlist rotting
# into a permanent blind spot.


@pytest.fixture
def client() -> Any:
    return TestClient(app)


def test_ratchet_422_envelope_still_violates_declared_schema(client: Any) -> None:
    """DEFECT 1 is still live: the 422 body is an object, spec says array."""
    response = client.get(
        "/v1/query-runs/not-a-uuid",
        headers={"X-Account-Id": str(uuid4())},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, dict), (
        "The 422 envelope now matches the declared HTTPValidationError array shape. "
        "DEFECT 1 is fixed — remove the '422:JsonSchemaError' entries from "
        "KNOWN_CONTRACT_DEFECTS."
    )
    declared = app.openapi()["components"]["schemas"]["HTTPValidationError"]
    assert declared["properties"]["detail"]["type"] == "array"


def test_ratchet_404_responses_still_undeclared() -> None:
    """DEFECT 2 is still live: 404-capable operations declare no 404."""
    paths = app.openapi()["paths"]
    for path, method in (
        ("/feedback/audit", "get"),
        ("/v1/query-runs/{query_run_id}", "get"),
        ("/v1/query-runs/{query_run_id}", "delete"),
    ):
        assert "404" not in paths[path][method]["responses"], (
            f"{method.upper()} {path} now declares its 404 response. DEFECT 2 is "
            "fixed for it — remove the matching KNOWN_CONTRACT_DEFECTS entry."
        )


def test_ratchet_malformed_json_400_still_undeclared(client: Any) -> None:
    """DEFECT 3 is still live: a malformed body 400s, and no operation says so.

    The exact body is the fuzzer's own reproducer: bytes that are not valid
    UTF-8 at all. FastAPI turns a ``JSONDecodeError`` into its 422 path, but an
    undecodable body escapes as ``HTTPException(400)`` from Starlette.
    """
    response = client.post(
        "/v1/query-runs/warnings",
        content=b"\xa5l\xa9",
        headers={"X-Account-Id": str(uuid4()), "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    declared = app.openapi()["paths"]["/v1/query-runs/warnings"]["post"]["responses"]
    assert "400" not in declared, (
        "POST /v1/query-runs/warnings now declares its 400 response. DEFECT 3 is "
        "fixed — remove the matching KNOWN_CONTRACT_DEFECTS entries."
    )
