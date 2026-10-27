"""W87-1: the signed-in lane ages a session through a TEST-ONLY handler on its
loopback token stub (``e2e/servers/signed_in_server.py``), never through the
app. The launcher never ships (the Dockerfile copies only ``src``); this test
keeps the handler out of ``src``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient
from tests.repo_root import find_repo_root

from product_app.main import app

ROOT = find_repo_root(Path(__file__))
NEEDLE = "/age-sessions"


def _compared_strings(path_text: str) -> set[str]:
    """String constants the code COMPARES with (``x == "..."``): a docstring
    that merely mentions the path is not the handler."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path_text)):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    found.add(side.value)
    return found


def test_the_app_has_no_route_that_ages_a_session() -> None:
    """Red when: the app answers ``/age-sessions`` (any method) with anything
    but 404. Partner: a real session route answers, without a cookie, with its
    own 401, so a 404 here means "no such route", not "nothing answers"."""
    client = TestClient(app)
    assert client.get("/v1/session/idle").status_code == 401
    for method in ("GET", "POST", "PUT"):
        assert client.request(method, NEEDLE, json={"age_seconds": 1}).status_code == 404


def test_no_file_under_src_names_the_handler() -> None:
    """Red when: any file under ``src/`` mentions ``age-sessions``. Partner:
    the lane launcher does hold the handler, as a string constant its code
    compares the request path with, so the search can find it."""
    hits = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*")
        if path.is_file() and "age-sessions" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == []
    launcher = (ROOT / "e2e" / "servers" / "signed_in_server.py").read_text(encoding="utf-8")
    assert NEEDLE in _compared_strings(launcher)


#: T17 (W87-3 follow-up, plan §2.1.8, FM-1.19): the lane's other test-only
#: seams, all on the loopback stub, never on the app.
SEAMS = ("/store-ready", "/hold-store-lock", "/unchecked-refresh-seconds", "/session-counts")


def test_t17_the_app_answers_no_store_seam() -> None:
    """T17. Red when: the app answers any of the follow-up's seam paths (any
    method) with anything but 404. Partner: ``/v1/session/idle`` answers its
    own 401 without a cookie, so a 404 here means "no such route"."""
    client = TestClient(app)
    assert client.get("/v1/session/idle").status_code == 401
    for path in SEAMS:
        for method in ("GET", "POST", "PUT"):
            assert client.request(method, path, json={"ready": False}).status_code == 404, (
                method,
                path,
            )


def test_t17_no_file_under_src_names_a_store_seam_and_the_launcher_holds_each() -> None:
    """T17. Red when: any file under ``src/`` names a seam path (without its
    leading slash, so a reference in any form is caught), or the launcher
    stops comparing the request path with one of them (partner: the search
    finds each, as a string constant the launcher's code compares with)."""
    names = [path.lstrip("/") for path in SEAMS]
    hits = [
        (str(path.relative_to(ROOT)), name)
        for path in (ROOT / "src").rglob("*")
        if path.is_file()
        for name in names
        if name in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits == []
    launcher = (ROOT / "e2e" / "servers" / "signed_in_server.py").read_text(encoding="utf-8")
    compared = _compared_strings(launcher)
    assert [path for path in SEAMS if path not in compared] == []
