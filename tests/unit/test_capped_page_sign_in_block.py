"""W34 (ADR-0139): the capped page's sign-in block, in isolation.

Two things the route tests cannot see: the CSRF token is the one value on
the page that comes from outside ``main``, so it is HTML-escaped inside the
attribute; and the inline script follows Google's URL only when it really is
``https://accounts.google.com``. The guard runs under Node, the way
``tests/unit/test_idle_reminder_page.py`` runs functions lifted from
``app.js``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html import unescape
from pathlib import Path

import pytest
from tests.unit.test_receipt_attribution_note import _extract_function

from product_app import main

TEMPLATE = Path(main.__file__).resolve().parent / "templates" / "capped-sign-in.html"
HOSTILE_TOKEN = 'a"b<c>&d'
ESCAPED_TOKEN = "a&quot;b&lt;c&gt;&amp;d"


def _data_csrf(html: str) -> str:
    """The raw text inside the ``data-csrf`` attribute of the sign-in button."""
    buttons = re.findall(r'<button[^>]*id="sign-in-google"[^>]*>', html)
    assert len(buttons) == 1, buttons
    match = re.search(r'data-csrf="([^"]*)"', buttons[0])
    assert match is not None, buttons[0]
    return match.group(1)


@pytest.mark.parametrize("invite", [False, True])
def test_the_token_is_escaped_inside_the_attribute(invite: bool) -> None:
    """RED-IF: the token is substituted raw (a quote in it would end the
    attribute and the rest would be markup). Partner: the escaped form reads
    back as the original token."""
    html = main._render_session_capped_html(3600, invite=invite, cap=2, csrf_token=HOSTILE_TOKEN)
    raw = _data_csrf(html)
    assert raw == ESCAPED_TOKEN
    assert unescape(raw) == HOSTILE_TOKEN
    assert HOSTILE_TOKEN not in html


def test_without_a_token_the_page_has_no_sign_in_block() -> None:
    """RED-IF: the block renders with no token to carry (a button that posts
    an empty token, on a page for a visitor who cannot sign in)."""
    html = main._render_session_capped_html(3600, invite=False, cap=2, csrf_token=None)
    assert 'id="sign-in-google"' not in html
    assert "data-csrf" not in html


@pytest.fixture
def _node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _guard() -> tuple[str, str]:
    """The navigation guard: the one function in the template that takes
    ``url``. Found by shape, not by name, so a rename does not blind this."""
    source = TEMPLATE.read_text(encoding="utf-8")
    names = re.findall(r"function (\w+)\(url\)", source)
    assert len(names) == 1, names
    return names[0], _extract_function(source, names[0])


ALLOWED = [
    "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=y",
    "https://accounts.google.com/",
    "https://accounts.google.com:443/o/oauth2/v2/auth",
]
REFUSED = [
    "http://accounts.google.com/",
    "https://accounts.google.com.evil.example/",
    "https://evil.example/accounts.google.com",
    "javascript:alert(1)",
    "/o/oauth2/v2/auth",
    "//accounts.google.com/x",
    "https://user@evil.example",
    "https://accounts.google.com:8443/",
]


@pytest.mark.usefixtures("_node")
def test_the_page_follows_only_googles_own_origin() -> None:
    """RED-IF: the guard accepts anything but ``https://accounts.google.com``
    (today it compares the host only, so ``http://accounts.google.com/``
    passes), or refuses Google's real authorization URL."""
    name, function = _guard()
    cases = ALLOWED + REFUSED
    script = (
        function
        + "\nconsole.log(JSON.stringify("
        + json.dumps(cases)
        + ".map(function (u) { return "
        + name
        + "(u); })));\n"
    )
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=True
    )
    verdicts = json.loads(out.stdout)
    assert verdicts == [True] * len(ALLOWED) + [False] * len(REFUSED), dict(
        zip(cases, verdicts, strict=True)
    )
