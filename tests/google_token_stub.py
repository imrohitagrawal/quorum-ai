"""A loopback stand-in for Google's token endpoint (W7, ADR-0130).

No test may reach Google (the suite's socket guard refuses any non-loopback
connect), so the sign-in tests point ``google_signin.GOOGLE_TOKEN_ENDPOINT``
at this server instead. It records every request it receives and answers with
whatever the test configured: a status, a JSON body, and an optional delay
before answering.
"""

from __future__ import annotations

import base64
import contextlib
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

CLIENT_ID = "stub-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "stub-client-secret-Qx81Lm"  # noqa: S105 - a test value
ACCESS_TOKEN = "ya29.STUB-ACCESS-TOKEN-7f3a9c"  # noqa: S105 - a test value
REFRESH_TOKEN = "1//STUB-REFRESH-TOKEN-c41e0d"  # noqa: S105 - a test value
ID_TOKEN_SIGNATURE = "STUBSIGNATUREb6e2"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_id_token(claims: dict[str, Any]) -> str:
    header = _b64(json.dumps({"alg": "RS256", "kid": "stub"}).encode())
    return f"{header}.{_b64(json.dumps(claims).encode())}.{ID_TOKEN_SIGNATURE}"


def good_claims(
    *, sub: str = "108000000000000000001", email: str = "ada@example.com"
) -> dict[str, Any]:
    now = int(time.time())
    return {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "azp": CLIENT_ID,
        "sub": sub,
        "email": email,
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
    }


@dataclass
class StubConfig:
    status: int = 200
    claims: dict[str, Any] = field(default_factory=good_claims)
    delay_s: float = 0.0
    #: Send the first ``drip_bytes`` of the body one byte every
    #: ``drip_interval_s`` seconds: each read is quick, so only a bound on the
    #: TOTAL time stops the wait (a per-read socket timeout never fires).
    drip_bytes: int = 0
    drip_interval_s: float = 0.0
    requests: list[dict[str, Any]] = field(default_factory=list)

    def body(self) -> bytes:
        return json.dumps(
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "expires_in": 3599,
                "scope": "openid email",
                "token_type": "Bearer",
                "id_token": make_id_token(self.claims),
            }
        ).encode()


@contextlib.contextmanager
def token_stub() -> Iterator[tuple[str, StubConfig]]:
    config = StubConfig()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server's name
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode()
            config.requests.append(
                {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "form": {k: v[0] for k, v in parse_qs(raw).items()},
                }
            )
            if config.delay_s:
                time.sleep(config.delay_s)
            body = config.body() if config.status == 200 else b'{"error":"invalid_grant"}'
            try:
                self.send_response(config.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                for index in range(min(config.drip_bytes, len(body))):
                    self.wfile.write(body[index : index + 1])
                    self.wfile.flush()
                    time.sleep(config.drip_interval_s)
                self.wfile.write(body[config.drip_bytes :])
            except OSError:
                return

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.block_on_close = False  # a delayed handler must not hold teardown
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/token", config
    finally:
        server.shutdown()
        server.server_close()
