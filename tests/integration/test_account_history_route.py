"""W33 slice D (ADR-0142): ``GET /v1/account/history``, through the real routes.

The History panel asks the server for its list each time it opens. These are
the route's acceptance tests, written before the route. Each test names the
row of ``docs/analysis/2026-10-03-w33d-history-refresh-failure-modes.md`` it
pins. The route is hidden from the OpenAPI schema (row 19), so the Schemathesis
gate never calls it and these tests ARE its contract.

The contract they pin:

* 200 ``{"html": <the list markup>, "email": <the account's email>}`` for a
  signed-in cookie session; ``html`` is ``main._history_list_html(entries)``,
  the ONE builder the page's ``_history_html`` also uses (row 14);
* 401 with no session (and after the session was ended elsewhere, row 7);
* 403 ``NOT_SIGNED_IN`` for an anonymous, a sign-in-only (ADR-0139) or a
  legacy ``X-Account-Id`` session (rows 2-4);
* ``Cache-Control: no-store`` on every one of those (row 15);
* no draw on the per-account limiter estimate and create share (row 16).

Every API test asserts the STATUS first, so on a tree without the route each
one fails on ``404`` against the expected status, not on a later line.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims
from tests.helpers import isolated_run_semaphore
from tests.integration.test_account_history_flow import _finish, _start_run
from tests.integration.test_google_sign_in import SignIn, _boot, _signed_in
from tests.integration.test_query_run_cost_guardrails import DEFAULT_MODEL_IDS, confirmed_request

from product_app import account_history, auth, main
from product_app import query_run_orchestration as qro
from product_app.main import app
from product_app.query_run_orchestration import query_run_repository
from product_app.query_runs import _account_rate_limiter

ROUTE = "/v1/account/history"
COOKIE = "quorum_session"  # the LOCAL cookie name; the suite runs as local
ADA = "ada@example.com"  # the stub's default claims
GRACE_SUB, GRACE = "108000000000000000331", "grace.w33d@example.com"


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    account_history.clear_carried()
    yield
    query_run_repository.clear()
    account_history.clear_carried()


class _Questions(HTMLParser):
    """The text of every ``<span class="history-question">``, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.questions: list[str] = []
        self._in = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "span" and ("class", "history-question") in attrs:
            self._in = True
            self.questions.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self._in = False

    def handle_data(self, data: str) -> None:
        if self._in:
            self.questions[-1] += data


def _questions_in(html: str) -> list[str]:
    parser = _Questions()
    parser.feed(html)
    return parser.questions


def _account(sign_in: SignIn, email: str) -> UUID:
    (row,) = [r for r in sign_in.account_rows() if r["email"] == email]
    return UUID(row["account_id"])


def _sign_in_as(sign_in: SignIn, *, sub: str, email: str) -> TestClient:
    sign_in.stub.claims = good_claims(sub=sub, email=email)
    client = sign_in.client()
    assert _signed_in(client).status_code == 303
    return client


def _get(client: TestClient, **kwargs: Any) -> Any:
    return client.get(ROUTE, **kwargs)


def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"html", "email"}, body
    return dict(body)


def _refused(response: Any, status: int) -> None:
    """A refusal carries no list markup at all."""
    assert response.status_code == status, response.text
    assert "history-" not in response.text
    assert "html" not in response.json()


# --- rows 1 and 14: whose rows, and the one builder ---------------------------------


def test_each_cookie_gets_exactly_its_own_accounts_questions(sign_in: SignIn) -> None:
    """Row 1. RED-IF: the route is missing, takes the account from anything
    but the cookie session, or lists another account's question; or the list
    is not this account's N rows (count AND text)."""
    client_a = sign_in.client()
    assert _signed_in(client_a).status_code == 303
    client_b = _sign_in_as(sign_in, sub=GRACE_SUB, email=GRACE)
    account_a, account_b = _account(sign_in, ADA), _account(sign_in, GRACE)
    mine = [f"A's question {n} 4e1b" for n in range(3)]
    theirs = [f"B's question {n} 77c0" for n in range(2)]
    for question in mine:
        _finish(_start_run(account_a, question))
    for question in theirs:
        _finish(_start_run(account_b, question))

    body_a = _ok(_get(client_a))
    body_b = _ok(_get(client_b))

    assert len(_questions_in(body_a["html"])) == 3
    assert sorted(_questions_in(body_a["html"])) == sorted(mine)
    assert not any(q in body_a["html"] for q in theirs)
    assert len(_questions_in(body_b["html"])) == 2
    assert sorted(_questions_in(body_b["html"])) == sorted(theirs)
    # A query string naming the other account changes nothing.
    assert _ok(_get(client_a, params={"account_id": str(account_b)}))["html"] == body_a["html"]


def test_the_email_is_the_accounts_own(sign_in: SignIn) -> None:
    """Row 6's server half. RED-IF: the answer carries no email, or an email
    other than the signed-in account's."""
    client = _sign_in_as(sign_in, sub=GRACE_SUB, email=GRACE)
    assert _ok(_get(client))["email"] == GRACE


def test_the_route_answers_the_builders_markup_and_the_page_shows_the_same(
    sign_in: SignIn,
) -> None:
    """Row 14. RED-IF: the route's ``html`` is not exactly what
    ``main._history_list_html`` builds for the account's rows, or the page's
    History panel does not carry those same bytes (two renderers drift)."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in, ADA)
    _finish(_start_run(account, "the same bytes 2d9a"))
    _finish(_start_run(account, "and <i>escaped</i> too"))
    html = _ok(_get(client))["html"]
    assert html == main._history_list_html(account_history.history_for(account))
    assert html.startswith('<ol class="history-list" id="account-history-list">')
    assert html in client.get("/ui").text


def test_an_empty_history_answers_the_empty_line(sign_in: SignIn) -> None:
    """Row 3's partner. RED-IF: a signed-in account with no rows gets
    anything but exactly the page's "No questions yet." line."""
    client = sign_in.client()
    _signed_in(client)
    assert _ok(_get(client))["html"] == (
        '<p class="history-empty" id="account-history-empty">No questions yet.</p>'
    )


# --- rows 2, 3, 4: who is refused -----------------------------------------------------


def test_the_legacy_header_naming_an_account_is_refused(sign_in: SignIn) -> None:
    """Row 2 (the suite runs with the legacy header ENABLED, tests/conftest.py).
    RED-IF: a cookie-less request naming A's id in ``X-Account-Id`` gets
    anything but 403 ``NOT_SIGNED_IN`` with no rows. Partner: A's own cookie
    gets A's row, so the row exists to be leaked."""
    client = sign_in.client()
    _signed_in(client)
    account = _account(sign_in, ADA)
    _finish(_start_run(account, "never through the header 61aa"))
    bare = sign_in.client()
    refused = _get(bare, headers={"X-Account-Id": str(account)})
    _refused(refused, 403)
    assert refused.json()["detail"]["code"] == "NOT_SIGNED_IN"
    assert "never through the header 61aa" not in refused.text
    assert _questions_in(_ok(_get(client))["html"]) == ["never through the header 61aa"]


def test_an_anonymous_session_is_refused_not_signed_in(sign_in: SignIn) -> None:
    """Row 3. RED-IF: an anonymous cookie gets 200 (a "No questions yet."
    while not signed in) or any code but 403 ``NOT_SIGNED_IN``."""
    client = sign_in.client()
    _boot(client)
    refused = _get(client)
    _refused(refused, 403)
    assert refused.json()["detail"]["code"] == "NOT_SIGNED_IN"


def test_no_session_is_401(sign_in: SignIn) -> None:
    """Row 3. RED-IF: a request with no cookie and no header gets anything
    but 401."""
    _refused(_get(sign_in.client()), 401)


def test_a_sign_in_only_session_is_refused(sign_in: SignIn) -> None:
    """Row 4 (ADR-0139). RED-IF: a sign-in-only session gets 200, list
    markup, or any code but 403 ``NOT_SIGNED_IN``."""
    issued = auth.issue_sign_in_only_session()
    client = TestClient(app)  # a fresh jar: no server-set cookie to duplicate
    client.cookies.set(COOKIE, issued.session_id)
    assert auth.session_repository.get(issued.session_id) is not None  # it is live
    refused = _get(client)
    _refused(refused, 403)
    assert refused.json()["detail"]["code"] == "NOT_SIGNED_IN"


# --- row 7: ended elsewhere -------------------------------------------------------------


@pytest.mark.parametrize("how", ["sign_out_everywhere", "account_deletion"])
def test_a_session_ended_on_another_device_gets_401(sign_in: SignIn, how: str) -> None:
    """Row 7. RED-IF: after "sign out everywhere" or account deletion on a
    second device, the first device's session still reads rows (anything
    but 401). Partner: before that, the same session reads its row."""
    first = sign_in.client()
    _signed_in(first)
    _finish(_start_run(_account(sign_in, ADA), "ended elsewhere 0b3c"))
    assert _questions_in(_ok(_get(first))["html"]) == ["ended elsewhere 0b3c"]
    second = sign_in.client()
    _signed_in(second)  # the same Google subject: the same account
    csrf = second.get("/v1/session").json()["csrf_token"]
    if how == "sign_out_everywhere":
        ended = second.post("/v1/auth/sign-out-everywhere", headers={"X-CSRF-Token": csrf})
    else:
        ended = second.post(
            "/v1/account/delete", json={"confirm_email": ADA}, headers={"X-CSRF-Token": csrf}
        )
    assert ended.status_code == 200, ended.text
    response = _get(first)
    _refused(response, 401)
    assert "ended elsewhere 0b3c" not in response.text


# --- rows 9, 15, 16, 17 -----------------------------------------------------------------


def test_a_store_that_cannot_be_read_answers_exactly_the_unavailable_line(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 9. RED-IF: a read failure answers "No questions yet.", an error
    status, or anything but exactly the page's unavailable line."""
    client = sign_in.client()
    _signed_in(client)
    monkeypatch.setattr(sign_in.store, "history_for", lambda *a, **k: None)
    assert _ok(_get(client))["html"] == (
        '<p class="history-empty" id="account-history-unavailable">'
        "Your history could not be loaded just now.</p>"
    )


@pytest.mark.parametrize("who", ["signed_in", "no_session", "anonymous"])
def test_every_answer_is_no_store(sign_in: SignIn, who: str) -> None:
    """Row 15. RED-IF: a 200, 401 or 403 from the route lacks
    ``Cache-Control: no-store`` (a shared computer or a proxy could keep it)."""
    client = sign_in.client()
    expected = {"signed_in": 200, "no_session": 401, "anonymous": 403}[who]
    if who == "signed_in":
        _signed_in(client)
    elif who == "anonymous":
        _boot(client)
    response = _get(client)
    assert response.status_code == expected, response.text
    assert response.headers.get("Cache-Control") == "no-store"


def test_opening_history_does_not_draw_on_the_account_limiter(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 16. RED-IF: the route draws on the 30-a-minute per-account limiter
    estimate and create share: after 30 GETs, the account could then make
    fewer than 30 estimates. Refill is held at 0, so the count is exact; the
    31st estimate's 429 is the partner proving the limiter is live here.
    Its own Google subject: estimates are recorded per account."""
    monkeypatch.setattr(_account_rate_limiter, "REFILL_PER_MINUTE", 0)
    client = _sign_in_as(sign_in, sub="108000000000000000332", email="limiter.w33d@example.com")
    csrf = client.get("/v1/session").json()["csrf_token"]
    for _ in range(30):
        assert _get(client).status_code == 200
    statuses = [
        client.post(
            "/v1/query-runs/estimate",
            json={"query_text": "Compare these answers", "model_slots": DEFAULT_MODEL_IDS},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        for _ in range(31)
    ]
    assert statuses == [200] * 30 + [429]


def test_the_question_is_escaped_in_the_routes_answer(sign_in: SignIn) -> None:
    """Row 17. RED-IF: the route returns a question as raw HTML."""
    client = sign_in.client()
    _signed_in(client)
    _finish(_start_run(_account(sign_in, ADA), "is <b>this</b> escaped?"))
    html = _ok(_get(client))["html"]
    assert "is &lt;b&gt;this&lt;/b&gt; escaped?" in html
    assert "<b>" not in html
    assert _questions_in(html) == ["is <b>this</b> escaped?"]  # the parser unescapes


# --- row 12, the server half: a cancel writes the row itself ---------------------------


def test_a_cancelled_run_is_in_history_as_soon_as_the_cancel_returns(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 12. A real cookie-path create starts a worker whose pipeline is a
    stub that sleeps until released; the DELETE cancels it. RED-IF: the
    cancel route does not write the History row itself, so the row appears
    only when the worker exits (measured 903 ms with a 1 s stub). Partner:
    once the worker has exited, its second write replaced the row, never
    added one (exactly one row, keyed by run id)."""
    release = threading.Event()
    workers: list[threading.Thread] = []

    def sleeping_pipeline(query_run_id: UUID, account_id: UUID) -> None:
        workers.append(threading.current_thread())
        release.wait(timeout=20)

    monkeypatch.setattr(qro, "_execute_query_run", sleeping_pipeline)
    client = _sign_in_as(sign_in, sub="108000000000000000333", email="cancel.w33d@example.com")
    account = _account(sign_in, "cancel.w33d@example.com")
    csrf = client.get("/v1/session").json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    question = "cancelled before it finished 5f2e"
    try:
        with isolated_run_semaphore(1):
            created = client.post(
                "/v1/query-runs",
                json=confirmed_request(client, question, headers=headers),
                headers=headers,
            )
            assert created.status_code == 202, created.text
            run_id = created.json()["query_run_id"]
            for _ in range(200):  # the worker thread has entered the stub
                if workers:
                    break
                threading.Event().wait(0.01)
            assert workers, "the worker never started"

            cancelled = client.delete(f"/v1/query-runs/{run_id}", headers=headers)
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"
            assert workers[0].is_alive(), "the window under test: the worker has not exited"
            entries = account_history.history_for(account) or []
            assert [(e.query_run_id, e.question, e.status) for e in entries] == [
                (run_id, question, "cancelled")
            ]
            assert _questions_in(_ok(_get(client))["html"]) == [question]
    finally:
        release.set()
    workers[0].join(timeout=10)
    assert not workers[0].is_alive()
    entries = account_history.history_for(account) or []
    assert [(e.query_run_id, e.status) for e in entries] == [(run_id, "cancelled")]


# --- row 19: hidden from the schema, but there -----------------------------------------


def test_the_route_exists_and_is_hidden_from_the_openapi_schema() -> None:
    """Row 19. RED-IF: the route is not registered as a GET, or it appears
    in the OpenAPI schema (it is hidden like the other account routes, and
    these tests carry its contract)."""
    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == ROUTE
        and "GET" in (getattr(route, "methods", None) or ())
    ]
    assert len(routes) == 1
    paths = app.openapi()["paths"]
    assert "/v1/account/delete" not in paths  # the sibling hidden route, for scale
    assert ROUTE not in paths
    assert len(paths) > 0
