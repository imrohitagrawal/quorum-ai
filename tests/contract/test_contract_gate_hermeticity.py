"""The contract gate must be hermetic ($0, no egress) by construction — proven.

``test_api_contract_schemathesis`` says in its own docstring: "No server
process, no socket, no network, $0". Two of those four were false. The ASGI
transport claim holds — schemathesis never opens a listening socket — but the
module imports ``product_app.main`` at module scope, whose startup calls
``openrouter_catalog_fetcher.prewarm()`` (main.py:252), and catalog-backed
operations re-enter ``list_models()`` while the fuzzer drives them. MEASURED on
this tree before the fix, with a ``sitecustomize`` socket guard installed and
the gate's exact recipe command (``uv run pytest tests/contract -q --no-cov``):
57 blocked outbound connects to openrouter.ai (19 x 104.18.2.115:443, 19 x
104.18.3.115:443, 19 x the matching IPv6). The same command against
``tests/perf`` — which already carries the static-catalog pin — blocked 0.

So a *blocking* CI job was making ~57 third-party TLS connect attempts per run,
and its "$0" claim rested on that catalog endpoint staying free and
unauthenticated. The perf gate got the ``_pin_static_catalog()`` seam and a
mechanical probe; the contract gate got neither. This file is that probe.

It runs the contract module in a **subprocess** with a socket guard installed
before any import, because the only honest place to observe the import-time
prewarm is a fresh interpreter — in-process the catalog cache is already warm
by the time any fixture runs, so an in-process assertion would pass vacuously.
This mirrors ``tests/perf/test_perf_gate_hermeticity.py`` deliberately: the
same failure mode, observed the same way, so the two gates cannot drift.

The subprocess target is overridable via ``QUORUM_HERMETICITY_TARGET`` so a
mutant (pin removed = the pre-fix code) can be run through the same probe,
proving the probe is able to go red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_MODULE = REPO_ROOT / "tests" / "contract" / "test_api_contract_schemathesis.py"

#: Seconds to let the daemon prewarm thread run after the requests finish. The
#: thread is started at ``product_app.main`` import time and would connect
#: within milliseconds; this is slack, not a race we are relying on.
_PREWARM_SETTLE_SECONDS = 1.5

#: Endpoints driven after the import. ``/v1/models/defaults`` is the operation
#: the fuzzer covers that re-enters ``model_slots`` ->
#: ``openrouter_catalog_fetcher.list_models()``, i.e. the *second* egress site,
#: the one an import-only probe would miss. ``/status`` reports catalog health
#: and is the cheap second reader of the same cache.
_CATALOG_BACKED_PATHS = ("/v1/models/defaults", "/status")

_CHILD_SCRIPT = '''
"""Import the contract module under a socket guard and drive catalog reads."""
import importlib.util
import json
import os
import socket
import sys
import time
import uuid

_LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}
_blocked: list[object] = []
_real_connect = socket.socket.connect


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in _LOOPBACK:
        _blocked.append(address)
        print("NETGUARD-BLOCKED " + repr(address), flush=True)
        raise OSError("NETGUARD: outbound connect blocked: " + repr(address))
    return _real_connect(self, address)


socket.socket.connect = _guarded_connect

target = os.environ["QUORUM_HERMETICITY_TARGET"]
spec = importlib.util.spec_from_file_location("contract_gate_under_test", target)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

from starlette.testclient import TestClient  # noqa: E402  (must follow the guard)

from product_app.main import app  # noqa: E402

client = TestClient(app)
headers = {"X-Account-Id": str(uuid.uuid4())}
for path in json.loads(os.environ["QUORUM_HERMETICITY_PATHS"]):
    status = client.get(path, headers=headers).status_code
    print("PATH-STATUS " + path + " " + str(status), flush=True)

time.sleep(float(os.environ["QUORUM_HERMETICITY_SETTLE_SECONDS"]))
print("NETGUARD-COUNT " + str(len(_blocked)), flush=True)
sys.exit(1 if _blocked else 0)
'''


def _run_child(target: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "contract_hermeticity_child.py"
    script.write_text(_CHILD_SCRIPT)
    env = {
        **os.environ,
        # tests/conftest.py is not loaded in a bare subprocess, so reproduce the
        # environment the suite relies on.
        "ENVIRONMENT": "local",
        "ACCOUNT_LEGACY_HEADER_ENABLED": "true",
        "RUN_HISTORY_DB_PATH": ":memory:",
        "OPENROUTER_LIVE_EXECUTION_ENABLED": "false",
        "OPENROUTER_API_KEY": "",
        "SENTRY_DSN": "",
        "PYTHONPATH": str(REPO_ROOT / "src"),
        "QUORUM_HERMETICITY_TARGET": str(target),
        "QUORUM_HERMETICITY_PATHS": json.dumps(list(_CATALOG_BACKED_PATHS)),
        "QUORUM_HERMETICITY_SETTLE_SECONDS": str(_PREWARM_SETTLE_SECONDS),
    }
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=300,
        check=False,
    )


def test_contract_gate_opens_no_outbound_socket(tmp_path: Path) -> None:
    """The contract gate must import and serve catalog reads with egress blocked.

    Failure mode this catches: any code path reached by this gate (catalog
    prewarm at ``product_app.main`` import, catalog lookup during model-slot
    validation, provider inference, error reporting) that touches the public
    internet. Such a path makes a blocking CI job depend on a third party's
    uptime, and the "$0" claim depend on that third party's pricing.
    """
    result = _run_child(CONTRACT_MODULE, tmp_path)

    blocked = [line for line in result.stdout.splitlines() if line.startswith("NETGUARD-BLOCKED")]
    assert not blocked, (
        "contract gate attempted outbound network I/O:\n"
        + "\n".join(blocked)
        + f"\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    for path in _CATALOG_BACKED_PATHS:
        assert f"PATH-STATUS {path} 200" in result.stdout, (
            f"contract gate could not serve {path} offline:\n{result.stdout}\n{result.stderr}"
        )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hermeticity_probe_fails_on_a_non_hermetic_contract_gate(tmp_path: Path) -> None:
    """The probe itself must be able to fail — a gate that never goes red is not a gate.

    A mutant copy of the contract module with the static-catalog pin removed is
    exactly the pre-fix code; the probe must reject it.
    """
    source = CONTRACT_MODULE.read_text()
    assert "_pin_static_catalog()" in source, "the pin call this mutant removes has moved"
    mutant = tmp_path / "mutant_contract_gate.py"
    mutant.write_text(source.replace("\n_pin_static_catalog()", "\n"))

    result = _run_child(mutant, tmp_path)

    assert result.returncode != 0, (
        "probe passed a gate with the catalog pin removed — it cannot detect egress:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "NETGUARD-BLOCKED" in result.stdout, result.stdout + result.stderr


def test_contract_gate_pins_the_catalog_before_importing_the_app() -> None:
    """Ordering is the whole fix: a pin applied after the app import is too late.

    ``product_app.main``'s startup fires ``prewarm()`` on import, so the pin has
    to be executed at module scope *above* the ``from product_app.main import
    app`` line. This is a cheap static assert that a future re-order (e.g. an
    import-sorting autofix moving the call down) is caught at the seam rather
    than by the subprocess probe alone.
    """
    lines = CONTRACT_MODULE.read_text().splitlines()
    pin_line = next(i for i, line in enumerate(lines) if line == "_pin_static_catalog()")
    app_import_line = next(
        i for i, line in enumerate(lines) if line.startswith("from product_app.main import app")
    )
    assert pin_line < app_import_line, (
        "_pin_static_catalog() must run before product_app.main is imported; "
        f"pin at line {pin_line + 1}, app import at line {app_import_line + 1}"
    )
