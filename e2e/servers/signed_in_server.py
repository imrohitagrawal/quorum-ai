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
from urllib.parse import parse_qs

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


class _TokenHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server's name
        length = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        body = json.dumps(
            {
                "access_token": ACCESS_TOKEN,
                "expires_in": 3599,
                "scope": "openid email",
                "token_type": "Bearer",
                "id_token": make_id_token(_claims_for(form.get("code", ""))),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def _start_token_stub() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TokenHandler)
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

    google_signin.GOOGLE_TOKEN_ENDPOINT = _start_token_stub()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
