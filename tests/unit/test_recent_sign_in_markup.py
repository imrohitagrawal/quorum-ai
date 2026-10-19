"""W87-2 (ADR-0175): the page markup for a recent sign-in before deletion.

Three things, each through the function or the route that renders it:

* ``#account-delete`` carries ``data-recent-sign-in-seconds-left``, the
  session's time left before deletion needs a new sign-in (600 just after
  sign-in, 0 once past 10 minutes, never negative);
* on ``/ui?account=switched`` the signed-in panel says, in a ``role="status"``
  line, the owner's answer (4) with the session's own email, escaped;
* the 2-Step line, CHG-063 (e), is beside "Sign in with Google" on the
  anonymous top bar and on the capped page, and nowhere else (owner answer 6).

The rendered pages come through the real sign-in flow (the sign-in suite's
loopback Google stub) on the session code's stepped clock.
"""

from __future__ import annotations

from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims
from tests.integration.test_google_sign_in import (  # noqa: F401 - the fixture
    SignIn,
    _enable,
    _signed_in,
    sign_in,
)
from tests.session_clock import Clock, age, freeze

from product_app import account_history, main
from product_app.session_store import StoredAccount

COOKIE = "quorum_session"
TEMPLATES = Path(main.__file__).resolve().parent / "templates"

#: CHG-063 (e), verbatim.
TWO_STEP = (
    "We sign you in with Google. Turn on 2-Step Verification in your Google account to protect it."
)
#: Owner answer (4), 2026-10-20 (CHG-073), with the email put in.
SWITCHED = (
    "You are now signed in as {email}. Nothing was deleted. "
    'To delete this account, press "Delete my account" again.'
)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str | None], parent: _Node | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node | str] = []

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def ancestors(self) -> list[_Node]:
        found: list[_Node] = []
        node = self.parent
        while node is not None:
            found.append(node)
            node = node.parent
        return found

    def walk(self) -> list[_Node]:
        found: list[_Node] = [self]
        for child in self.children:
            if isinstance(child, _Node):
                found.extend(child.walk())
        return found


class _Tree(HTMLParser):
    """A small DOM: elements with attributes, text and parents (no scripts)."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self._open = self.root
        self._skip = 0
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
            return
        node = _Node(tag, dict(attrs), self._open)
        self._open.children.append(node)
        if tag not in VOID:
            self._open = node

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip -= 1
            return
        node: _Node | None = self._open
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self._open = node.parent

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._open.children.append(data)

    def by_id(self, element_id: str) -> list[_Node]:
        return [n for n in self.root.walk() if n.attrs.get("id") == element_id]

    def text_count(self, sentence: str) -> int:
        return " ".join(self.root.text().split()).count(sentence)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return freeze(monkeypatch)


def _signed_in_client(sign_in: SignIn, email: str = "ada@example.com") -> TestClient:  # noqa: F811
    sign_in.stub.claims = good_claims(email=email)
    client = sign_in.client()
    assert _signed_in(client).headers["location"] == "/ui"
    return client


def _delete_block(page: str) -> _Node:
    (block,) = _Tree(page).by_id("account-delete")
    return block


# --- 13. the time left, on the page ----------------------------------------------


def test_the_delete_block_carries_the_time_left_before_a_new_sign_in_is_needed(
    sign_in: SignIn,  # noqa: F811
    clock: Clock,
) -> None:
    """Red when: ``#account-delete`` has no ``data-recent-sign-in-seconds-left``,
    the value is not the time left (600 just after sign-in, 300 at 5 minutes,
    0 at 11 minutes), or it goes negative."""
    client = _signed_in_client(sign_in)
    session_id = str(client.cookies[COOKIE])
    seen = []
    for by in (timedelta(0), timedelta(minutes=5), timedelta(minutes=11)):
        age(session_id, by, now=clock.at)
        page = client.get("/ui")
        assert page.status_code == 200
        seen.append(_delete_block(page.text).attrs.get("data-recent-sign-in-seconds-left"))
    assert seen == ["600", "300", "0"]


# --- 14. the other-account line -----------------------------------------------------


def test_the_switched_line_names_the_sessions_own_email_escaped(
    sign_in: SignIn,  # noqa: F811
) -> None:
    """Owner answer (4). Red when: ``/ui?account=switched`` shows no
    ``role="status"`` line in the account panel, the words differ, or the
    email is written unescaped. Partner: the escaped email is on the page."""
    email = "a<b>@x.com"
    client = _signed_in_client(sign_in, email)
    page = client.get("/ui?account=switched").text
    assert "a<b>@x.com" not in page
    assert "a&lt;b&gt;@x.com" in page
    tree = _Tree(page)
    lines = [
        n
        for n in tree.root.walk()
        if n.attrs.get("role") == "status"
        and " ".join(n.text().split()) == SWITCHED.format(email=email)
    ]
    statuses = [
        " ".join(n.text().split()) for n in tree.root.walk() if n.attrs.get("role") == "status"
    ]
    assert len(lines) == 1, statuses
    (line,) = lines
    (history,) = tree.by_id("account-history")
    assert history in line.ancestors(), "the line is inside the account panel"


def test_no_marker_gives_no_switched_line(sign_in: SignIn) -> None:  # noqa: F811
    """Red when: the line shows without ``?account=switched``. Partner: the
    page is signed in (its email shows)."""
    client = _signed_in_client(sign_in)
    page = client.get("/ui").text
    assert "ada@example.com" in page
    assert "Nothing was deleted." not in page


def test_an_anonymous_page_with_the_marker_gives_no_switched_line(
    sign_in: SignIn,  # noqa: F811
) -> None:
    """Red when: an anonymous page shows the line (there is no account to
    name). Partner: the anonymous page rendered its sign-in button."""
    page = sign_in.client().get("/ui?account=switched").text
    assert 'id="sign-in-google"' in page
    assert "Nothing was deleted." not in page
    assert "You are now signed in as" not in page


# --- 15. the 2-Step line --------------------------------------------------------------


def test_the_two_step_line_is_beside_sign_in_on_the_anonymous_top_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHG-063 (e), owner answer (6). Red when: the line is missing from the
    anonymous sign-in branch, is there twice, or comes before the button.
    Partner: the branch rendered its "Sign in with Google" button."""
    _enable(monkeypatch)
    controls, shows_account = main._account_controls_html(uuid4(), sign_in_failed=False)
    assert shows_account is False
    assert 'id="sign-in-google"' in controls
    assert _Tree(controls).text_count(TWO_STEP) == 1
    assert controls.index('id="sign-in-google"') < controls.index("2-Step Verification")


def test_the_two_step_line_is_absent_from_the_signed_in_top_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner answer (6): only near "Sign in". Red when: the signed-in branch,
    or the reminder in it, carries the line. Partner: the branch rendered the
    account's email and its reminder."""
    _enable(monkeypatch)
    account = StoredAccount(account_id=uuid4(), email="ada@example.com")
    monkeypatch.setattr(main, "signed_in_account", lambda _id: account)
    monkeypatch.setattr(account_history, "history_for", lambda _id: [])
    controls, shows_account = main._account_controls_html(account.account_id, sign_in_failed=False)
    assert shows_account is True
    assert "ada@example.com" in controls
    assert 'id="idle-reminder"' in controls
    assert "2-Step" not in controls
    assert "2-Step" not in main._idle_reminder_html(600)


def test_with_sign_in_off_the_top_bar_is_still_empty() -> None:
    """The visual lane's page has sign-in off, so its top bar must stay the
    empty string. Red when: the line (or anything) is rendered with sign-in
    off. Partner: with sign-in on, the same call renders the button (the
    test above)."""
    assert main._account_controls_html(uuid4(), sign_in_failed=False) == ("", False)


def test_the_two_step_line_is_not_in_the_workspace_template() -> None:
    """Red when: the line is put in ``workspace.html`` (every page, cards and
    the 12-hour messages included). Partner: the template is the real one."""
    template = (TEMPLATES / "workspace.html").read_text(encoding="utf-8")
    assert "{{ account_controls }}" in template
    assert "2-Step" not in template


def test_the_two_step_line_is_below_the_capped_pages_sign_in_button() -> None:
    """Red when: ``capped-sign-in.html`` loses the line, carries it twice, or
    puts it above its button. Partner: without a token the page has no
    sign-in block and no line."""
    html = main._render_session_capped_html(3600, invite=False, cap=2, csrf_token="t0ken")
    assert 'id="sign-in-google"' in html
    assert _Tree(html).text_count(TWO_STEP) == 1
    assert html.index('id="sign-in-google"') < html.index("2-Step Verification")
    bare = main._render_session_capped_html(3600, invite=False, cap=2, csrf_token=None)
    assert "2-Step" not in bare
