"""TEST-ONLY launcher for the signed-in browser lane (W33 slice D, ADR-0142).

Starts the real app with Google sign-in switched on against a LOOPBACK token
stub, so a browser test can sign in without reaching Google. It never ships:
the Dockerfile copies only ``src``, and nothing here is read by the app.

ADR-0142 rejects an environment variable for the token endpoint as a critical
risk (the ID token's signature is not checked, so whoever sets the endpoint
chooses the account). This launcher therefore sets
``google_signin.GOOGLE_TOKEN_ENDPOINT`` IN-PROCESS, after import; the module
reads that global at call time (``exchange_code``). No product code changes.

Which account a sign-in becomes is chosen by the browser test through the
authorization code it hands the callback: ``<google sub>|<email>``. The stub
answers the app's exchange with an ID token for exactly those claims, so
every test can sign in as its OWN account (a charging signed-in test must
not share a Google subject with another). A code without ``|`` gets the stub's
default claims.

Everything is hermetic and $0: a fresh temporary directory holds the sessions,
feedback and run-history databases; live execution is off and every provider
key is blank, so every run is a local simulation.

W87-1 (ADR-0174) adds ONE more test-only seam, on the same loopback stub and
never on the app: ``POST /age-sessions`` with ``{"session_id": ..., "age_seconds":
...}`` makes that session have started ``age_seconds`` ago (in the process
cache and its durable row), so a browser test can stand at 11 h 55 m of a
12-hour session without waiting. The stub listens on the app's port + 1 so a
spec can reach it. ``tests/unit/test_age_sessions_is_test_only.py`` keeps the
handler out of ``src``.

W88 adds ``GET /bounce?to=<url>`` on the same stub: a 302 to ``to`` when it is
the app's own sign-in callback (``GOOGLE_OAUTH_REDIRECT_URI``, any query), and
400 for anything else. A spec addresses the stub as ``localhost`` while the app
is ``127.0.0.1``, so the hop back to the callback is a real cross-site
navigation, as Google's return is. A ``page.route`` fulfilment alone does not
give that: Chromium then reports the return as same-origin.

Usage (from the repository root)::

    PYTHONPATH=src:. uv run python e2e/servers/signed_in_server.py --port 18096
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from tests.google_token_stub import (
    ACCESS_TOKEN,
    CLIENT_ID,
    CLIENT_SECRET,
    good_claims,
    make_id_token,
)


def _claims_for(code: str) -> dict[str, Any]:
    sub, sep, email = code.partition("|")
    if not sep:
        return good_claims()
    return good_claims(sub=sub, email=email)


def _age_session(raw: bytes) -> tuple[int, dict[str, Any]]:
    """TEST-ONLY (W87-1): the session started ``age_seconds`` ago and was
    last used now. Imported here, at call time: the app is imported by then."""
    from datetime import UTC, datetime, timedelta

    from product_app import auth, session_store
    from product_app.session_store import _digest

    asked = json.loads(raw.decode() or "{}")
    session_id = str(asked.get("session_id") or "")
    now = datetime.now(UTC)
    started = now - timedelta(seconds=float(asked.get("age_seconds") or 0))
    with auth.session_repository._lock:
        cached = auth.session_repository._sessions.get(session_id)
        if cached is not None:
            cached.created_at = started
            cached.last_used_at = now
    rows = 0
    store = session_store.get_store()
    if store is not None:
        with store._lock:
            rows = store._conn.execute(
                "UPDATE sessions SET created_at = ?, last_used_at = ? WHERE session_digest = ?",
                (started.isoformat(), now.isoformat(), _digest(session_id)),
            ).rowcount
    found = cached is not None or rows > 0
    return (200 if found else 404), {"cached": cached is not None, "rows": rows}


def _bounce_target(request_path: str, callback: str) -> str | None:
    """TEST-ONLY (W88): where ``GET /bounce?to=...`` may send the browser.

    Only the app's own callback, compared by scheme, host, port and path; the
    query (``code``, ``state`` or ``error``) is the spec's. Anything else,
    including a missing or repeated ``to``, gets ``None`` (answered 400), so
    the stub is never an open redirect."""
    targets = parse_qs(urlsplit(request_path).query).get("to", [])
    if len(targets) != 1:
        return None
    target, allowed = urlsplit(targets[0]), urlsplit(callback)
    same = (target.scheme, target.netloc, target.path) == (
        allowed.scheme,
        allowed.netloc,
        allowed.path,
    )
    if not same or target.fragment or not allowed.netloc:
        return None
    return targets[0]


class _TokenHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        if urlsplit(self.path).path != "/bounce":
            self._send(404, b"{}")
            return
        target = _bounce_target(self.path, os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", ""))
        if target is None:
            self._send(400, b'{"error": "not the app callback"}')
            return
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - http.server's name
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/age-sessions":
            status, answer = _age_session(raw)
            self._send(status, json.dumps(answer).encode())
            return
        form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        body = json.dumps(
            {
                "access_token": ACCESS_TOKEN,
                "expires_in": 3599,
                "scope": "openid email",
                "token_type": "Bearer",
                "id_token": make_id_token(_claims_for(form.get("code", ""))),
            }
        ).encode()
        self._send(200, body)

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def _start_token_stub(port: int) -> str:
    server = ThreadingHTTPServer(("127.0.0.1", port), _TokenHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/token"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    port = parser.parse_args().port

    data = tempfile.mkdtemp(prefix="quorum-signed-in-lane-")
    os.environ.update(
        {
            "RUNTIME_ENVIRONMENT": "local",
            "OPENROUTER_LIVE_EXECUTION_ENABLED": "false",
            "OPENROUTER_API_KEY": "",
            "TAVILY_API_KEY": "",
            "QUORUM_EVAL_JUDGE_API_KEY": "",
            "SENTRY_DSN": "",
            "ACCOUNT_LEGACY_HEADER_ENABLED": "false",
            # Each test opens fresh browser contexts from one address; the
            # per-address limits are not what this lane measures (rule 13).
            "SESSION_RATE_LIMIT_PER_MINUTE": "600",
            "SESSION_MINT_CAP_OVERRIDE": "600",
            # W47 (ADR-0144 decision 7): cleared on purpose, so this lane
            # exercises the real per-network sharing (shared-allowance.spec.ts)
            # even though the e2e job's env sets the override for other lanes.
            "ANONYMOUS_SPEND_PER_SESSION_OVERRIDE": "",
            # Every test signs in from this one address; the start limiter
            # (5 then 1 a minute) is not what this lane measures.
            "SIGN_IN_STARTS_PER_ADDRESS_BURST": "100",
            "SIGN_IN_STARTS_PER_ADDRESS_PER_MINUTE": "100",
            "SESSION_DB_PATH": os.path.join(data, "sessions.sqlite3"),
            "FEEDBACK_DB_PATH": os.path.join(data, "feedback_events.sqlite3"),
            "RUN_HISTORY_DB_PATH": os.path.join(data, "run_history.sqlite3"),
            "GOOGLE_OAUTH_CLIENT_ID": CLIENT_ID,
            "GOOGLE_OAUTH_CLIENT_SECRET": CLIENT_SECRET,
            "GOOGLE_OAUTH_REDIRECT_URI": f"http://127.0.0.1:{port}/v1/auth/google/callback",
        }
    )

    # Imported only now: the settings are read when the package is imported.
    import uvicorn

    from product_app import google_signin
    from product_app.main import app

    # Port + 1, fixed, so session-max-age.spec.ts can reach /age-sessions.
    google_signin.GOOGLE_TOKEN_ENDPOINT = _start_token_stub(port + 1)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
