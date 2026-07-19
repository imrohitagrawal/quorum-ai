"""The perf gate must be hermetic ($0, no egress) by construction — proven.

``test_workflow_latency_percentiles`` claims to be hermetic. That claim used
to be false: importing ``product_app.main`` calls
``openrouter_catalog_fetcher.prewarm()`` (main.py:252), which opens a live
HTTPS connection to the model catalog, and the perf assertions *depend* on
that catalog — two of the four model ids the gate posts
(``anthropic/claude-haiku-4.5``, ``google/gemini-2.5-flash``) are not in the
curated ``model_slots.DEFAULT_MODEL_IDS`` whitelist, so with egress blocked
the POST came back ``422 INVALID_MODEL_SLOT`` and the *blocking* CI
``perf-gate`` job failed for a reason unrelated to the change under test.

This test is the mechanical check that the claim holds. It runs the perf
module in a **subprocess** with a socket guard installed before any import,
because the only honest place to observe the import-time prewarm is a fresh
interpreter — in-process the catalog cache is already warm by the time any
fixture runs, so an in-process assertion would pass vacuously.

The subprocess target is overridable via ``QUORUM_HERMETICITY_TARGET`` so the
RED proof can be run against a pre-fix copy of the perf module.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_MODULE = REPO_ROOT / "tests" / "perf" / "test_workflow_latency_percentiles.py"

#: Seconds to let the daemon prewarm thread run after the workflow finishes.
#: The thread is started at ``product_app.main`` import time and would connect
#: within milliseconds; this is slack, not a race we are relying on.
_PREWARM_SETTLE_SECONDS = 1.5

_CHILD_SCRIPT = '''
"""Import the perf module under a socket guard and drive one stubbed run."""
import importlib.util
import os
import socket
import sys
import time

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
spec = importlib.util.spec_from_file_location("perf_gate_under_test", target)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

from fastapi.testclient import TestClient  # noqa: E402  (must follow the guard)

from product_app.main import app  # noqa: E402

module.settings.openrouter_live_execution_enabled = False
status, elapsed_ms = module._drive_one_run(TestClient(app))
print("RUN-STATUS " + status, flush=True)

time.sleep(float(os.environ["QUORUM_HERMETICITY_SETTLE_SECONDS"]))
print("NETGUARD-COUNT " + str(len(_blocked)), flush=True)
sys.exit(1 if _blocked else 0)
'''


def _run_child(target: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "hermeticity_child.py"
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
        "QUORUM_HERMETICITY_SETTLE_SECONDS": str(_PREWARM_SETTLE_SECONDS),
    }
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=180,
        check=False,
    )


def test_perf_gate_opens_no_outbound_socket(tmp_path: Path) -> None:
    """The perf gate must complete a full stubbed run with egress blocked.

    Failure mode this catches: any code path in the gate (catalog prewarm,
    catalog lookup during model-slot validation, provider inference, error
    reporting) that reaches the public internet. Such a path makes the
    blocking CI job depend on a third party's uptime and, for inference,
    costs money.
    """
    result = _run_child(PERF_MODULE, tmp_path)

    blocked = [line for line in result.stdout.splitlines() if line.startswith("NETGUARD-BLOCKED")]
    assert not blocked, (
        "perf gate attempted outbound network I/O:\n"
        + "\n".join(blocked)
        + f"\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "RUN-STATUS completed" in result.stdout or "RUN-STATUS partial" in result.stdout, (
        f"perf gate could not complete a run offline:\n{result.stdout}\n{result.stderr}"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hermeticity_probe_fails_on_a_non_hermetic_gate(tmp_path: Path) -> None:
    """The probe itself must be able to fail — a gate that never goes red is not a gate.

    A mutant copy of the perf module with the static-catalog pin removed is
    exactly the pre-fix code; the probe must reject it.
    """
    source = PERF_MODULE.read_text()
    assert "_pin_static_catalog()" in source, "the pin call this mutant removes has moved"
    mutant = tmp_path / "mutant_perf_gate.py"
    mutant.write_text(source.replace("\n_pin_static_catalog()", "\n"))

    result = _run_child(mutant, tmp_path)

    assert result.returncode != 0, (
        "probe passed a gate with the catalog pin removed — it cannot detect egress:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "NETGUARD-BLOCKED" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize(
    "model_id",
    [
        "openai/gpt-4o-mini",
        "anthropic/claude-haiku-4.5",
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat-v3.1",
    ],
)
def test_static_catalog_covers_every_model_slot_the_perf_gate_posts(model_id: str) -> None:
    """The offline pin is only safe if it satisfies the gate's own slot list.

    If a future edit adds a model id to the perf gate that the shipped static
    fallback catalog does not carry, the gate would silently need the live
    catalog again. Fail here, at the seam, rather than in CI on a network blip.
    """
    import importlib.util

    from product_app.catalog_fetcher import _FALLBACK_CATALOG

    spec = importlib.util.spec_from_file_location("_perf_gate_slots", PERF_MODULE)
    assert spec is not None and spec.loader is not None
    perf_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(perf_module)

    assert model_id in perf_module.DEFAULT_MODEL_IDS, (
        "parametrisation drifted from the gate's slot list"
    )
    assert model_id in {entry.model_id for entry in _FALLBACK_CATALOG}
