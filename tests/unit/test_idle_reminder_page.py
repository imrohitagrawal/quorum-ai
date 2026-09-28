"""W7 part 3, pull request B (ADR-0138): the page's side of the idle reminder.

The markup is rendered only for a signed-in account (with the account
controls); the three pure functions that decide WHEN to ask and WHAT to say
are lifted out of ``app.js`` and run under Node, as
``tests/unit/test_sign_in_start_message.py`` does.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_receipt_attribution_note import _extract_function

from product_app import main
from product_app.config import settings

APP_JS = Path(__file__).resolve().parents[2] / "src" / "product_app" / "static" / "app.js"


def test_the_reminder_markup_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turns red if the reminder loses its polite announcement, a button, the
    hidden start, or the two values the page schedules from."""
    monkeypatch.setattr(settings, "signed_in_idle_minutes", 45)
    monkeypatch.setattr(settings, "signed_in_idle_warning_minutes", 4)
    assert main._idle_reminder_html() == (
        '<div class="idle-reminder" id="idle-reminder" role="region" '
        'aria-label="Staying signed in" hidden '
        'data-idle-seconds="2700" data-warning-seconds="240">'
        '<p class="idle-reminder-text" id="idle-reminder-text" aria-live="polite"></p>'
        '<div class="idle-reminder-actions">'
        '<button type="button" id="idle-stay" class="topbar-howitworks">Stay signed in</button>'
        '<button type="button" id="idle-sign-out" class="topbar-howitworks">Sign out now</button>'
        '<button type="button" id="idle-reload" class="topbar-howitworks" hidden>'
        "Reload the page</button>"
        "</div></div>"
    )


def test_the_reminder_is_rendered_only_for_a_signed_in_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turns red if an anonymous page gets the reminder (B5), or a signed-in
    one does not."""
    from uuid import uuid4

    from product_app.session_store import StoredAccount

    account = uuid4()
    stored = StoredAccount(account_id=account, email="ada@example.com")
    monkeypatch.setattr(main, "signed_in_account", lambda a: stored if a == account else None)
    monkeypatch.setattr(main, "_history_html", lambda _a: "")
    signed, _ = main._account_controls_html(account, sign_in_failed=False)
    anonymous, _ = main._account_controls_html(uuid4(), sign_in_failed=False)
    assert signed.count('id="idle-reminder"') == 1
    assert 'id="idle-reminder"' not in anonymous
    assert 'id="idle-reminder"' not in main._render_workspace_html()


@pytest.fixture
def _node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")


def _run(names: list[str], calls: str) -> Any:
    source = APP_JS.read_text(encoding="utf-8")
    harness = "\n".join(_extract_function(source, name) for name in names)
    out = subprocess.run(
        ["node", "-e", harness + "\nconsole.log(JSON.stringify(" + calls + "));\n"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(out.stdout)


@pytest.mark.usefixtures("_node")
def test_the_page_asks_the_server_when_the_warning_is_due() -> None:
    """B1: the timer only decides when to ASK. Turns red if the page asks
    late (after the warning is due) or waits a negative time."""
    got = _run(
        ["idleCheckDelayMs"],
        "[idleCheckDelayMs(7200, 300), idleCheckDelayMs(301, 300), "
        "idleCheckDelayMs(300, 300), idleCheckDelayMs(10, 300), idleCheckDelayMs(0, 300)]",
    )
    assert got == [6_900_000, 1_000, 0, 0, 0]


@pytest.mark.usefixtures("_node")
def test_the_reminder_says_how_long_is_left() -> None:
    """Minutes rounded up. Turns red if the rounding or the singular
    changes."""
    got = _run(
        ["idleReminderText"],
        "[idleReminderText(300), idleReminderText(241), idleReminderText(61), "
        "idleReminderText(60), idleReminderText(5)]",
    )
    tail = " because nothing has happened on this page. Stay signed in?"
    assert got == [
        "You will be signed out in about 5 minutes" + tail,
        "You will be signed out in about 5 minutes" + tail,
        "You will be signed out in about 2 minutes" + tail,
        "You will be signed out in about a minute" + tail,
        "You will be signed out in about a minute" + tail,
    ]


@pytest.mark.usefixtures("_node")
def test_the_expired_message_names_the_idle_length() -> None:
    """B7. Turns red if the page does not say why it signed out, or names the
    wrong length."""
    got = _run(["idleExpiredText"], "[idleExpiredText(7200), idleExpiredText(2700)]")
    assert got == [
        "You were signed out after 120 minutes with nothing happening on this page. "
        "Reload the page to sign in again.",
        "You were signed out after 45 minutes with nothing happening on this page. "
        "Reload the page to sign in again.",
    ]


@pytest.mark.usefixtures("_node")
def test_stay_signed_in_asks_the_keep_active_route() -> None:
    """B7, the owner's "keep it active". Turns red if the button's request
    changes route or method (for example to the status route, which keeps
    nothing alive)."""
    got = _run(
        ["idleKeepActive"],
        "(() => { const calls = []; idleKeepActive((path, options) => { "
        "calls.push([path, options]); return {}; }); return calls; })()",
    )
    assert got == [["/v1/session/keep-active", {"method": "POST"}]]


@pytest.mark.usefixtures("_node")
def test_sign_out_now_presses_the_sign_out_button() -> None:
    """B7, "or not". Turns red if the button stops using the page's sign-out,
    or claims to have signed out with no sign-out button on the page."""
    got = _run(
        ["idleSignOutNow"],
        "(() => { let clicks = 0; const button = { click() { clicks += 1; } }; "
        "const found = idleSignOutNow((id) => (id === 'sign-out' ? button : null)); "
        "const missing = idleSignOutNow(() => null); return [found, clicks, missing]; })()",
    )
    assert got == [True, 1, False]
