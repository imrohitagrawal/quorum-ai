"""F-14 — readiness honesty: a key that is PRESENT is not a key that WORKS.

``run_startup_probe`` decided ``state="live"`` from configuration alone:
the live flag is on and ``OPENROUTER_API_KEY`` is a non-empty string.
Neither fact means the provider will accept the key. The deployment this
repo runs against reports ``state=live`` on every surface — the ops
readiness tile, the ``/status.live_execution`` monitoring bool, the
workspace connection pill ("provider configured") — while the key 401s
on every model, so every run FAILS outright (since #171 a refused key
still counts as present, so live execution stays on and nothing falls
back to local simulation).

That is the same silent-failure class the probe exists to catch, one
level deeper: the probe was built to catch a MISSING key and is blind to
a REJECTED one.

These tests pin the fourth state, ``offline_by_bad_key``, and the
credential probe that produces it:

* the probe calls ``GET {base}/key`` — auth-required and ZERO token cost,
  so honesty here never costs money;
* it runs on a BACKGROUND DAEMON THREAD and ``run_startup_probe`` only
  ever reads its cached verdict, because the probe is re-run on four hot
  paths (import, ``/ready``, ``/status``, ``/ui``) and none of them may
  grow a network round-trip;
* it dials NOTHING unless live execution is enabled AND a key is set —
  which is what keeps the contract gate's no-outbound-socket guard
  (``tests/contract/test_contract_gate_hermeticity.py``) green and the
  test suite hermetic;
* an ambiguous failure (timeout, 500, DNS) leaves the state alone. Only
  an explicit 401/403 — the provider saying "I do not accept this
  credential" — may downgrade a run to ``offline_by_bad_key``. A network
  blip must not tell an operator their key is bad.
"""

from __future__ import annotations

import ast
import pathlib
import threading
import time
from collections.abc import Callable, Iterator
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError

import pytest

from product_app import main, readiness
from product_app.config import settings
from product_app.readiness import (
    APPROVED_REASON_PREFIXES,
    _urlopen_key_probe,
    probe_key_auth,
    record_key_auth_state,
    run_startup_probe,
    start_key_auth_probe,
)

_FAKE_KEY = "sk-or-v1-fake-key-for-tests-only"


@pytest.fixture(autouse=True)
def reset_probe_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Restore the settings singleton AND the cached key-auth verdict.

    The verdict is process-wide module state by design (one probe, many
    readers). Leaking it across tests would let one test's 401 decide
    another test's state, so it is reset both before and after.
    """
    original_flag = settings.openrouter_live_execution_enabled
    original_key = settings.openrouter_api_key
    record_key_auth_state("unknown")
    yield
    record_key_auth_state("unknown")
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", original_flag)
    monkeypatch.setattr(settings, "openrouter_api_key", original_key)


def _set_live(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, key: str) -> None:
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", enabled)
    monkeypatch.setattr(settings, "openrouter_api_key", key)


def _http_error(code: int) -> HTTPError:
    return HTTPError(
        url="https://openrouter.ai/api/v1/key",
        code=code,
        msg="nope",
        hdrs=Message(),
        fp=None,
    )


class _StopLoop(Exception):
    """Sentinel used to end the probe's ``while True`` loop deterministically.

    The loop only ever exits via an exception escaping the ``time.sleep``
    call (nothing else in the loop body is left unsuppressed). Patching
    ``time.sleep`` directly — rather than a private attribute on the
    ``readiness`` module — works because ``readiness`` imports the same
    module object (``import time as _time_module``); patching the shared
    singleton's attribute affects both names. Raising this after a fixed
    number of calls turns an otherwise-infinite background thread into one
    that reliably finishes within a test's ``thread.join(timeout=)``,
    without the production code needing a test-only "stop after N"
    parameter.
    """


#: Every test using ``_sleep_stub_raising_after`` deliberately lets this
#: sentinel escape the daemon thread to end its loop — pytest's own
#: ``threading.excepthook`` capture reports that as
#: ``PytestUnhandledThreadExceptionWarning``. It is the intended, only
#: exit path (see ``_StopLoop`` above), not a bug, so it is silenced with
#: a marker rather than left to rot into a real failure the day CI turns
#: on ``-W error``.
_IGNORE_INTENTIONAL_STOP_LOOP_WARNING = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning"
)


def _sleep_stub_raising_after(n: int) -> Callable[[float], None]:
    """A fake ``sleep`` that lets ``n`` iterations complete, then ends the loop.

    Also records the interval it was called with, so a test can assert the
    production loop actually slept for ``settings.key_auth_reprobe_interval_seconds``
    rather than some other value.
    """
    calls: list[float] = []

    def _sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= n:
            raise _StopLoop
        return None

    _sleep.calls = calls  # type: ignore[attr-defined]
    return _sleep


# ---------------------------------------------------------------------------
# The headline: a rejected key must not be served as "live".
# ---------------------------------------------------------------------------


def test_a_rejected_key_is_not_reported_as_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect, stated directly: 401 on every call, state said ``live``."""
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    record_key_auth_state("unauthorized")

    report = run_startup_probe()

    assert report.state == "offline_by_bad_key"
    assert any("credential check was refused" in reason for reason in report.reasons), (
        report.reasons
    )


def test_a_rejected_key_reason_is_in_the_approved_public_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``reasons`` is served verbatim on the PUBLIC ``/ready`` endpoint."""
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    record_key_auth_state("unauthorized")

    report = run_startup_probe()

    assert report.reasons
    for reason in report.reasons:
        assert reason.startswith(APPROVED_REASON_PREFIXES), reason


def test_a_rejected_key_reason_never_echoes_the_key_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-or-v1-DEADBEEF-super-secret"
    _set_live(monkeypatch, enabled=True, key=secret)
    record_key_auth_state("unauthorized")

    report = run_startup_probe()

    assert secret not in " ".join(report.reasons)
    assert "DEADBEEF" not in " ".join(report.reasons)


def test_an_accepted_key_is_still_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    record_key_auth_state("ok")

    assert run_startup_probe().state == "live"


def test_an_unproven_key_is_still_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Before the probe lands — and after a network blip — nothing changes.

    ``unknown`` is the boot state and the state every ambiguous failure
    falls back to. Treating it as a bad key would make every cold start
    and every transient upstream hiccup shout "your key is rejected".
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    record_key_auth_state("unknown")

    assert run_startup_probe().state == "live"


def test_a_missing_key_still_outranks_a_stale_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key at all is the more specific, more actionable diagnosis."""
    _set_live(monkeypatch, enabled=True, key="")
    record_key_auth_state("unauthorized")

    assert run_startup_probe().state == "offline_by_no_key"


def test_live_execution_off_outranks_a_stale_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_live(monkeypatch, enabled=False, key=_FAKE_KEY)
    record_key_auth_state("unauthorized")

    assert run_startup_probe().state == "offline_by_config"


# ---------------------------------------------------------------------------
# The probe itself: classification by what the provider actually said.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", [401, 403])
def test_probe_classifies_an_explicit_credential_refusal_as_unauthorized(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        raise _http_error(code)

    assert probe_key_auth(transport=_transport) == "unauthorized"


def test_probe_classifies_a_200_as_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        return 200

    assert probe_key_auth(transport=_transport) == "ok"


@pytest.mark.parametrize("code", [429, 500, 502, 503])
def test_probe_never_blames_the_key_for_an_upstream_fault(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    """A rate limit or a provider outage is not a bad credential."""
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        raise _http_error(code)

    assert probe_key_auth(transport=_transport) == "unknown"


@pytest.mark.parametrize(
    "boom",
    [URLError("dns"), TimeoutError("slow"), OSError("reset"), ValueError("garbage")],
)
def test_probe_never_blames_the_key_for_a_network_fault(
    monkeypatch: pytest.MonkeyPatch, boom: Exception
) -> None:
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        raise boom

    assert probe_key_auth(transport=_transport) == "unknown"


def test_probe_sends_the_key_to_the_key_endpoint_and_nowhere_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``GET /key`` is auth-required and costs ZERO tokens.

    Pinning the URL is what keeps this a free honesty check rather than
    a billed one — a probe that drifted to ``/chat/completions`` would
    charge the operator for every process start.
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    seen: dict[str, object] = {}

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        seen.update(url=url, api_key=api_key, timeout=timeout)
        return 200

    probe_key_auth(transport=_transport)

    assert seen["url"] == f"{settings.openrouter_api_base_url}/key"
    assert seen["api_key"] == _FAKE_KEY
    assert seen["timeout"] == settings.openrouter_timeout_seconds


# ---------------------------------------------------------------------------
# Hermeticity: the probe must not dial when there is nothing to prove.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "key"),
    [(False, _FAKE_KEY), (True, ""), (False, "")],
)
def test_probe_dials_nothing_when_live_execution_cannot_happen(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, key: str
) -> None:
    """Gating on (flag AND key) is what keeps the suite socket-free.

    ``tests/conftest.py`` forces the live flag off and blocks outbound
    sockets for the whole session; the contract gate additionally proves
    that importing the app opens none. An ungated probe thread would trip
    both.
    """
    _set_live(monkeypatch, enabled=enabled, key=key)
    calls: list[str] = []

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        calls.append(url)
        return 200

    assert probe_key_auth(transport=_transport) == "unknown"
    assert calls == []


def test_start_key_auth_probe_starts_no_thread_when_gated_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_live(monkeypatch, enabled=False, key=_FAKE_KEY)

    assert start_key_auth_probe() is None


@_IGNORE_INTENTIONAL_STOP_LOOP_WARNING
def test_start_key_auth_probe_runs_off_the_calling_thread_and_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup must never block on this: ``main.py`` already pays a
    synchronous catalog fetch at import time.

    ``sleep`` is stubbed to end the loop after the first iteration so the
    test observes exactly one probe (#112 turned this into a periodic
    loop; the sleep-raises trick is what keeps a single-probe assertion
    deterministic without a test-only "stop after N" parameter in prod).
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    monkeypatch.setattr(time, "sleep", _sleep_stub_raising_after(1))

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        raise _http_error(401)

    thread = start_key_auth_probe(transport=_transport)

    assert thread is not None
    assert thread.daemon is True
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert readiness.key_auth_state() == "unauthorized"


@_IGNORE_INTENTIONAL_STOP_LOOP_WARNING
def test_start_key_auth_probe_survives_a_transport_that_explodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe failure may never take the process down."""
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    monkeypatch.setattr(time, "sleep", _sleep_stub_raising_after(1))

    record_key_auth_state("ok")

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        raise RuntimeError("catastrophe")

    thread = start_key_auth_probe(transport=_transport)

    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()
    # Starts from "ok" deliberately: asserting "unknown" here matched the
    # fixture's own reset value, so the test passed even with the
    # exception guard deleted. Found by review.
    assert readiness.key_auth_state() == "ok"


@_IGNORE_INTENTIONAL_STOP_LOOP_WARNING
def test_start_key_auth_probe_reprobes_after_the_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core of #112: the probe does not stop after one check.

    Three iterations are allowed to run; the transport is called three
    times and ``sleep`` is invoked with the configured interval between
    each — proving this is a periodic loop, not the pre-#112 one-shot.
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    monkeypatch.setattr(settings, "key_auth_reprobe_interval_seconds", 42.0)
    sleep_stub = _sleep_stub_raising_after(3)
    monkeypatch.setattr(time, "sleep", sleep_stub)

    call_count = 0

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        nonlocal call_count
        call_count += 1
        return 200

    thread = start_key_auth_probe(transport=_transport)
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()

    assert call_count == 3, "expected exactly 3 probes across 3 loop iterations"
    assert sleep_stub.calls == [42.0, 42.0, 42.0]  # type: ignore[attr-defined]
    assert readiness.key_auth_state() == "ok"


@_IGNORE_INTENTIONAL_STOP_LOOP_WARNING
def test_start_key_auth_probe_reprobe_does_not_erase_an_earlier_proven_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-call invariant, proven ACROSS iterations, not just within one.

    Iteration 1 proves ``unauthorized``; iteration 2 is an inconclusive
    network blip. If the loop's re-probe logic ever regressed to "always
    record whatever this iteration returned", the blip on iteration 2
    would silently re-advertise the deployment as live.
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    monkeypatch.setattr(time, "sleep", _sleep_stub_raising_after(2))

    call_count = 0

    def _transport(*, url: str, api_key: str, timeout: float) -> int:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _http_error(401)
        raise TimeoutError("network blip on re-probe")

    thread = start_key_auth_probe(transport=_transport)
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()

    assert call_count == 2
    assert readiness.key_auth_state() == "unauthorized"


# ---------------------------------------------------------------------------
# Found by adversarial review (round 2) of #112's periodic re-probe.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_interval", ["-5", "0"])
def test_key_auth_reprobe_interval_rejects_non_positive_values(bad_interval: str) -> None:
    """A non-positive interval must fail LOUD at startup, not silently at runtime.

    ``time.sleep()`` raises on a negative value, and that call sits OUTSIDE
    the probe loop's ``contextlib.suppress(Exception)`` — so ``-5`` used to
    kill the daemon thread forever after exactly one probe, permanently
    reintroducing the pre-#112 stale-verdict bug. ``0`` doesn't raise but
    busy-spins the loop (a live socket call with no delay between calls —
    a self-inflicted DoS against the provider). Both are excluded at the
    config layer, matching how a non-numeric value already fails closed.
    """
    from pydantic import ValidationError

    from product_app.config import Settings

    with pytest.raises(ValidationError, match="key_auth_reprobe_interval_seconds"):
        Settings(_env_file=None, key_auth_reprobe_interval_seconds=bad_interval)  # type: ignore[call-arg,arg-type]


def test_key_auth_reprobe_interval_accepts_the_documented_default() -> None:
    from product_app.config import Settings

    assert Settings(_env_file=None).key_auth_reprobe_interval_seconds == 1800.0  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Found by adversarial review of this work.
# ---------------------------------------------------------------------------


@_IGNORE_INTENTIONAL_STOP_LOOP_WARNING
def test_an_inconclusive_probe_does_not_erase_a_proven_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline regression the review caught.

    ``probe_key_auth`` logs "leaving state unchanged" for a timeout, but
    the thread recorded the ``"unknown"`` anyway — so ONE network blip
    turned a proven ``offline_by_bad_key`` back into ``live``. The log
    line was telling the truth about the intent and a lie about the code.
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    monkeypatch.setattr(time, "sleep", _sleep_stub_raising_after(1))
    record_key_auth_state("unauthorized")

    def _blip(*, url: str, api_key: str, timeout: float) -> int:
        raise TimeoutError("network blip")

    thread = start_key_auth_probe(transport=_blip)
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()

    assert readiness.key_auth_state() == "unauthorized"
    assert run_startup_probe().state == "offline_by_bad_key"


def test_a_probe_thread_that_cannot_start_does_not_break_the_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Thread.start`` raises under thread exhaustion / shutdown.

    Unguarded, that exception escapes module import and the process
    never serves traffic — trading a degraded diagnosis for an outage.
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)

    def _explode(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", _explode)

    assert start_key_auth_probe() is None


def test_probe_refuses_to_send_the_key_over_cleartext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPENROUTER_API_BASE_URL is operator-settable.

    A typo'd or downgraded base must not put a bearer token on the wire
    in cleartext. Not knowing whether the key works is the safer failure.

    Asserts the DIAL NEVER HAPPENS, not the return value: the suite's
    outbound-socket guard raises an ``Exception``, which
    ``probe_key_auth``'s catch-all also converts to ``"unknown"`` — so a
    return-value assertion passes with the gate deleted and proves
    nothing. (It also lets a real DNS lookup escape.) Found by review.
    """
    _set_live(monkeypatch, enabled=True, key=_FAKE_KEY)
    monkeypatch.setattr(settings, "openrouter_api_base_url", "http://openrouter.ai/api/v1")
    dialled: list[str] = []

    def _spy(*, url: str, api_key: str, timeout: float) -> int:
        dialled.append(url)
        return 200

    # Patched as a module attribute because probe_key_auth resolves
    # ``_urlopen_key_probe`` as a global at call time; the transport=
    # parameter cannot be used here, since the gate keys off it being None.
    monkeypatch.setattr(readiness, "_urlopen_key_probe", _spy)

    assert probe_key_auth() == "unknown"
    assert dialled == [], f"the API key was sent over cleartext to {dialled}"


def test_the_real_transport_refuses_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect would hand ``Authorization: Bearer <key>`` to the
    redirect target — urllib copies every header, cross-origin, and
    permits http. It would also let any 200 forge an "ok" verdict.

    Driven against the REAL ``_urlopen_key_probe`` (the injected
    transport used everywhere else cannot prove this), over loopback.
    """
    received: list[str] = []

    class _Redirector(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received.append(self.headers.get("Authorization", ""))
            if self.path.endswith("/key"):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{sink_port}/stolen")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    class _Sink(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            stolen.append(self.headers.get("Authorization", ""))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    stolen: list[str] = []
    sink = HTTPServer(("127.0.0.1", 0), _Sink)
    sink_port = sink.server_port
    origin = HTTPServer(("127.0.0.1", 0), _Redirector)
    for server in (sink, origin):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(HTTPError) as caught:
            _urlopen_key_probe(
                url=f"http://127.0.0.1:{origin.server_port}/key",
                api_key=_FAKE_KEY,
                timeout=5,
            )
        assert caught.value.code == 302
    finally:
        sink.shutdown()
        origin.shutdown()

    assert received and _FAKE_KEY in received[0]
    assert stolen == [], f"the API key was forwarded to the redirect target: {stolen}"


def test_importing_the_app_does_not_probe_the_credential() -> None:
    """Importing must not be a network action.

    ``scripts/export_openapi.py`` and ``make openapi-check`` import
    ``product_app.main``. With the probe at module scope that made a
    CODEGEN step send the operator's live API key to the provider — the
    first time this repo transmitted the key from a build tool. The probe
    now runs from the app's lifespan, so it fires when the server starts
    and not when the module is read.
    """
    source = pathlib.Path(main.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level_calls = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "start_key_auth_probe" not in module_level_calls, (
        "start_key_auth_probe() is called at module scope again — importing "
        "the app would send the API key from any script that imports it"
    )
    # ...and it is still CALLED somewhere, or the probe never runs at all.
    # Checking for the bare name would pass on the import statement alone.
    assert "start_key_auth_probe()" in source


def test_the_bad_key_reason_names_credit_as_well_as_validity() -> None:
    """MEASURED 2026-07-28 against the live provider, both directions:

        funded + valid key -> 200
        UNFUNDED valid key -> 401

    An unfunded key is refused exactly like an invalid one at this
    endpoint, so the operator-facing reason must name BOTH causes. An
    earlier draft argued from first principles that an empty balance
    would surface as a 402 and dropped "credit" from the copy; the
    measurement refuted it. This test exists so that reasoning cannot
    quietly win again.
    """
    lowered = readiness.REASON_BAD_KEY.lower()
    assert "credit" in lowered, readiness.REASON_BAD_KEY
    assert "invalid" in lowered, readiness.REASON_BAD_KEY


def test_the_bad_key_reason_does_not_promise_a_fallback_that_no_longer_happens() -> None:
    """#176 surface 1: pin the exact served string, and pin what it must NOT say.

    The pre-#171 REASON_BAD_KEY said "Every query will fall back to
    local_simulation." Since #171 a refused key is still a PRESENT key, so
    ``_live_execution_enabled`` stays true and every model call is still
    attempted against the real provider — and refused the same way. See
    ``test_every_slot_fails_on_a_refused_key_none_fall_back_to_simulation``
    below for the executed proof of what actually happens instead.
    """
    assert readiness.REASON_BAD_KEY == (
        "The OPENROUTER_API_KEY credential check was refused (HTTP 401/403). "
        "The key is present, so live execution stays on and every model call is "
        "still attempted against the real provider — and refused the same way, so "
        "every query FAILS rather than falling back to local_simulation. The key "
        "is either invalid or its account has no remaining credit — an unfunded "
        "key is refused here exactly like an invalid one. Check both (and that "
        "any network proxy allows the request), then restart to enable live "
        "execution."
    )
    assert "fall back to local_simulation" not in readiness.REASON_BAD_KEY
    assert "every query fails" in readiness.REASON_BAD_KEY.lower()


def test_every_slot_fails_on_a_refused_key_none_fall_back_to_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drives the REAL provider layer (network-free) to prove REASON_BAD_KEY's
    claim: with live execution on and the key refused, EVERY slot fails —
    cardinality, not a clean-path outcome. Before this test's fix, the
    identical setup produced 4 FAILED / 0 LOCAL_SIMULATION just the same (the
    behaviour was already correct); only the copy describing it was wrong.
    """
    from uuid import uuid4

    from product_app import providers as providers_mod
    from product_app.model_slots import ModelSlot
    from product_app.provider_keys import ProviderCredentialSource
    from product_app.providers import (
        InitialAnswerStatus,
        ProviderPath,
        provider_execution_service,
    )

    def _refused(request: object, timeout: float = 0) -> None:
        raise _http_error(401)

    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", True)
    monkeypatch.setattr(providers_mod, "urlopen", _refused)

    slots = [
        ModelSlot(slot_number=i, model_id=f"vendor/model-{i}", search=False) for i in (1, 2, 3, 4)
    ]
    answers = provider_execution_service.produce_initial_answers(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="hello",
        model_slots=slots,
        credential_source=ProviderCredentialSource.APP_OWNED,
        openrouter_key="sk-refused-key",
    )

    assert len(answers) == 4
    assert sum(1 for a in answers if a.status is InitialAnswerStatus.FAILED) == 4
    assert sum(1 for a in answers if a.provider_path is ProviderPath.LOCAL_SIMULATION) == 0
