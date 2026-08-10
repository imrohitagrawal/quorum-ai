"""Shared test fixtures and configuration.

This conftest file enables the legacy X-Account-Id header for tests,
since the default in production is False. Tests that exercise the
session path (cookie + CSRF) should NOT use this fixture; the
CSRF enforcement tests explicitly rely on the cookie path.

The suite runs as runtime environment "local", so the production guards
do not trigger. That comes from the FIELD DEFAULT
(``RuntimeEnvironment.LOCAL``), not from anything set here — see below.
"""

from __future__ import annotations

import os

# ``ENVIRONMENT`` is read by NOTHING, and this line has always been a no-op.
# The field is ``runtime_environment``, so the variable pydantic-settings
# looks for is ``RUNTIME_ENVIRONMENT``; ``Settings`` sets ``extra="ignore"``,
# which silently discards this one. MEASURED 2026-08-05: a .env containing
# ``ENVIRONMENT=production`` yields ``runtime_environment=local``.
# The docstring above used to claim this line "confirms the runtime
# environment is local". It does not — the field default does.
# Kept, labelled, because deleting it changes nothing and the label stops the
# next reader copying the wrong variable name. Setting ``RUNTIME_ENVIRONMENT``
# here WOULD be a real change and is deliberately not done.
os.environ.setdefault("ENVIRONMENT", "local")

# Enable the legacy X-Account-Id header for tests that need to bypass
# the cookie session dance. The default in production is False; tests
# that use the cookie path are unaffected.
os.environ.setdefault("ACCOUNT_LEGACY_HEADER_ENABLED", "true")

# Pin the durable run-history sink (S1/FR-014) to an in-memory SQLite DB for the
# whole test session so importing product_app.main creates no on-disk
# ``.data/run_history.sqlite3`` artifact and tests never share cross-session
# state. Tests that assert on persistence opt into an isolated store via
# ``run_history_store.configure_for_tests``.
os.environ.setdefault("RUN_HISTORY_DB_PATH", ":memory:")

# Same reasoning, same fix, for the feedback-events sink (issue #100): without
# this, importing ``product_app.main`` opens the REAL on-disk
# ``.data/feedback_events.sqlite3`` (``FeedbackStore.from_env()``'s default),
# and every test that hits a route minting or billing through it writes real,
# PERSISTENT rows there — durable across pytest invocations, not just within
# one. This was latent (nothing read cross-account/cross-test totals) until
# #100's global $5/24h ceiling and the per-IP daily session-mint cap started
# reading real SUMS across every account/IP. ``:memory:`` here only fixes
# cross-RUN persistence; see ``_reset_feedback_store`` below for the
# WITHIN-run fix (every ``TestClient`` reports the same fake peer IP,
# ``"testclient"``, so the mint cap — a 2-per-IP threshold, unlike the $5
# ceiling's much larger margin — collides across unrelated tests without it).
os.environ.setdefault("FEEDBACK_DB_PATH", ":memory:")

# Egress guard (Stage B): the working-tree ``.env`` sets
# ``OPENROUTER_LIVE_EXECUTION_ENABLED=true`` with a real key, and ``Settings``
# reads ``.env`` on every local pytest run. Force live execution OFF before any
# product_app module (hence ``Settings``) is imported, so a stray test can never
# make a paid provider call. This overrides ``.env`` because an explicit
# ``os.environ`` value wins over the ``.env`` file in pydantic-settings.
# The socket-level guard below is the belt to this suspenders.
os.environ["OPENROUTER_LIVE_EXECUTION_ENABLED"] = "false"

# Credential guard (2026-08-07 incident). The same mechanism and the same
# reason as the line above: an explicit ``os.environ`` value beats the ``.env``
# file in pydantic-settings, so this covers BOTH sources — which a scrubbing
# hook cannot, because it would have to parse ``.env`` to know what to hide.
#
# WHY: a real key in ``.env`` reached ``Settings``, a test compared it against
# "", and pytest's assertion rewriting printed it in full — to the terminal, to
# the session transcript, and via ``make test-report`` into
# ``build/test-results/pytest.xml``, whose CI sibling is an uploaded artifact.
# CI never saw it because CI has no ``.env``; the defect could only fire on a
# developer's machine.
#
# The fix is to remove the secret from the process rather than to hide it at
# one print site. Kept in sync with ``config.py`` mechanically by
# ``tests/unit/test_no_credential_reaches_a_test_run.py`` — every field marked
# ``repr=False`` there must appear here.
# Written as individual assignments, not a loop: ruff's E402 tolerates the
# simple subscript assignment above before the imports, but a compound
# statement ends that allowance and reds `make lint`.
#
# ESCAPE HATCH. ``tests/integration/test_tavily_live.py`` is an opt-in, PAID,
# operator-run verification that reads ``TAVILY_API_KEY`` and skips when it is
# absent. Blanking unconditionally made that test skip ALWAYS — it silently
# removed a documented capability, which is the failure mode the "prove both
# directions" rule exists to catch. So the blanking is skipped, loudly and
# explicitly, when the operator opts in:
#
#     QUORUM_TEST_LIVE_CREDENTIALS=1 TAVILY_API_KEY=tvly-... uv run pytest ...
#
# Default OFF. Named after the existing ``OPENROUTER_LIVE_EXECUTION_ENABLED``
# idiom. It is visible in the command line, so an accidental leak is traceable
# to a deliberate opt-in rather than to an invisible default.
# Spelled as ``os.environ[...] = <conditional expression>`` throughout, and the
# opt-in is re-read inline rather than hoisted into a local. Measured: ruff's
# E402 allowance for pre-import code covers ``os.environ`` mutation but NOT a
# plain module-level assignment (`_KEEP = ...` produced 8 E402 errors on this
# file), and an ``if`` block ends the allowance too.
os.environ["OPENROUTER_API_KEY"] = (
    os.environ.get("OPENROUTER_API_KEY", "")
    if os.environ.get("QUORUM_TEST_LIVE_CREDENTIALS", "") == "1"
    else ""
)
os.environ["TAVILY_API_KEY"] = (
    os.environ.get("TAVILY_API_KEY", "")
    if os.environ.get("QUORUM_TEST_LIVE_CREDENTIALS", "") == "1"
    else ""
)
os.environ["QUORUM_EVAL_JUDGE_API_KEY"] = (
    os.environ.get("QUORUM_EVAL_JUDGE_API_KEY", "")
    if os.environ.get("QUORUM_TEST_LIVE_CREDENTIALS", "") == "1"
    else ""
)
os.environ["QUORUM_TOKEN_SECRET"] = (
    os.environ.get("QUORUM_TOKEN_SECRET", "")
    if os.environ.get("QUORUM_TEST_LIVE_CREDENTIALS", "") == "1"
    else ""
)
os.environ["SENTRY_DSN"] = (
    os.environ.get("SENTRY_DSN", "")
    if os.environ.get("QUORUM_TEST_LIVE_CREDENTIALS", "") == "1"
    else ""
)
# Not a credential, but the OTHER half of the two-value judge gate. Leaving it
# set makes the local config differ from CI's, and since #269 priced the judge
# into ``max_cost_usd`` that divergence moves the SPEND RAILS — CI would
# validate them in a shape production never runs.
os.environ["QUORUM_EVAL_JUDGE_MODEL_ID"] = ""

import ipaddress
import socket
from collections.abc import Iterator
from typing import Any

import pytest

from product_app import feedback_store, store_reconnect
from product_app.auth import session_repository
from product_app.query_runs import (
    _account_rate_limiter,
    _evaluation_memo_clear_for_tests,
    _ip_rate_limiter,
    query_run_repository,
)


class OutboundSocketBlocked(RuntimeError):
    """Raised when a test attempts a non-loopback outbound socket connection.

    The test suite must be hermetic and $0: no test may reach an external
    host. The working-tree ``.env`` carries a real ``OPENROUTER_API_KEY`` with
    live execution enabled, so an un-guarded provider call would be a paid,
    real network request. This is the socket-level backstop behind the
    ``OPENROUTER_LIVE_EXECUTION_ENABLED=false`` override above.
    """


def _address_is_loopback(address: object) -> bool:
    """True if ``address`` targets loopback / a local (AF_UNIX) socket.

    ``connect`` addresses are: ``(host, port)`` for IPv4, ``(host, port,
    flowinfo, scope_id)`` for IPv6, or a ``str``/bytes path for AF_UNIX.
    We permit loopback IPs, ``localhost``, and AF_UNIX paths; everything
    else is treated as egress and blocked.
    """
    # AF_UNIX (local IPC) — a path, never a network hop.
    if isinstance(address, (str, bytes)):
        return True
    if not isinstance(address, tuple) or not address:
        # Unknown shape — fail closed (treat as egress).
        return False
    host = address[0]
    if host in ("localhost", "", None):
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname we cannot classify without a DNS lookup. A hermetic
        # test never needs to reach a named external host, so fail closed.
        return False


@pytest.fixture(autouse=True, scope="session")
def _block_outbound_sockets() -> Iterator[None]:
    """Block every non-loopback ``socket.connect``/``connect_ex`` for the run.

    Installed session-wide so a stray live provider call surfaces as a loud
    ``OutboundSocketBlocked`` rather than a silent paid request.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: Any) -> object:
        if not _address_is_loopback(address):
            raise OutboundSocketBlocked(
                f"Blocked outbound socket connection to {address!r}. "
                "Tests must be hermetic; mock the network seam instead."
            )
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> object:
        if not _address_is_loopback(address):
            raise OutboundSocketBlocked(
                f"Blocked outbound socket connection to {address!r}. "
                "Tests must be hermetic; mock the network seam instead."
            )
        return real_connect_ex(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[assignment,method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment,method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]


def _reset_state() -> None:
    """Reset all in-memory state between tests."""
    query_run_repository.clear()
    session_repository.clear()
    _ip_rate_limiter.clear()
    _account_rate_limiter.clear()
    # Issue #284. The terminal evaluation is memoised per
    # ``(query_run_id, updated_at, agreement)``, which is a process global in
    # exactly the sense rule 16a means. A test that forges a run id another
    # test also uses would otherwise read the first test's numbers, and the
    # failure would look like an evaluation bug rather than test bleed.
    _evaluation_memo_clear_for_tests()
    # Issue #122/#123. The reconnect cooldown stamps and the "a reopen was
    # tried and the store still cannot be shown to write" flag are module
    # globals, and any test whose ``estimate()`` runs against a stale store
    # spawns a REAL background reopen that sets them. MEASURED: that leaked
    # out of ``tests/integration/test_feedback_store_write_failures.py`` and
    # failed two unrelated tests in
    # ``tests/integration/test_feedback_store_locked_database.py`` — the
    # flag was still set, so the daily-cap guard blocked and the bypass
    # ERROR those tests assert on never fired. Same class of process-global
    # hazard as the cost event ring and the run-capacity semaphore.
    #
    # PREVENTIVE, not currently load-bearing: both of those files now pin
    # `store_reconnect_enabled = False` for their own reasons, so deleting
    # this line leaves the whole suite green today (verified by mutation, not
    # assumed). It stays because the hazard is real and was realised once,
    # and because every other process global above is reset here for exactly
    # the same reason.
    store_reconnect._reset_for_tests()


@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    """Auto-reset all in-memory state between tests."""
    _reset_state()
    yield
    _reset_state()


@pytest.fixture(autouse=True)
def _isolated_feedback_store() -> Iterator[None]:
    """Give every test its own fresh, empty ``:memory:`` feedback store.

    Issue #100: every ``TestClient`` reports the same fake peer address
    (``request.client.host == "testclient"`` — verified directly; there is
    no per-instance override), so without this fixture the durable per-IP
    session-mint cap (2/24h) and, at large enough test-suite scale, the
    global $5/24h ceiling would accumulate real events across UNRELATED
    tests that happen to mint a session or bill a run — exhausting a
    2-per-IP cap within the first couple of such tests in the whole suite,
    not just this file's own.

    Reuses ``feedback_store.configure_for_tests()`` (the existing, already
    correct isolation primitive individual tests opt into) as the AUTOUSE
    default instead, mirroring ``reset_state`` above for every other piece
    of shared process-global state. A test that explicitly calls
    ``configure_for_tests()`` or ``configure(...)`` itself simply layers a
    further swap on top for its own scope, restored back to THIS fixture's
    fresh store on exit — nesting composes safely because both are the same
    save-and-restore shape.
    """
    with feedback_store.configure_for_tests():
        yield
