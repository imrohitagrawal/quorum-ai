"""W87-3 follow-up (CHG-088, ADR-0176 amendment): a signed-in cookie that
could not be checked keeps its cookie, mints nothing and touches nothing.

The owner's choices, quoted in ``w873-followup/plan.md`` §1: "Both doors"
(``/ui`` and ``/v1/session`` both keep the cookie and create nothing), "Same,
plus auto-reload" (a 503 page with a 60 s meta refresh), "New code, retry in
place" (401 ``SESSION_UNCHECKED``), and, for a process with NO store at all,
"Today's behaviour" (S16: absent, mint path).

Written against the plan's interface (§2.1.1): ``auth.Unchecked``
(``SIGNED_IN = "signed_in"``, ``UNKNOWN_KIND = "unknown_kind"``),
``auth.Lookup(session, unchecked)``, ``SessionRepository.lookup``,
``auth.SessionUnchecked``, ``AuthError.SESSION_UNCHECKED``,
``main.UNCHECKED_PAGE_REFRESH_S``. Before the build every test here fails on
its own assertion or with ``AttributeError``; each docstring has its
"Red when" line and names its positive partner.

The states (plan §2.0) are made on the REAL store (``tests/unchecked_harness``):
not ready by the flag, a failing read on the store's own connection, a held
lock from another thread. The GC tick's readiness refresh is stood down for
every test, so a window cannot end under one.

Every wait and join is bounded (``pytest-timeout`` is not installed).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.end_sessions_harness import plant_row
from tests.helpers import isolated_run_semaphore
from tests.integration.test_query_run_cost_guardrails import (
    DEFAULT_MODEL_IDS,
    _stable_catalog_price,  # noqa: F401 -- a fixture, used by name below
    acknowledged_request,
)
from tests.session_clock import age, freeze
from tests.unchecked_harness import (
    ACTIVE,
    SIGNED_IN_401,
    SIGNED_IN_BODY,
    SIGNED_IN_HEADING,
    SIGNED_IN_TITLE,
    TRY_AGAIN,
    UNKNOWN_401,
    UNKNOWN_BODY,
    UNKNOWN_HEADING,
    UNKNOWN_TITLE,
    ScriptedCutoff,
    account,
    anonymous_session,
    capped_theme_gate,
    client,
    cookie_value,
    counts,
    failing_session_reads,
    hold_store_lock,
    mint_count,
    not_ready,
    parse,
    ready,
    set_cookies,
    signed_in_session,
    timed,
)

from product_app import auth, end_sessions, fetch_site, session_store
from product_app.config import settings
from product_app.main import app
from product_app.query_run_orchestration import query_run_repository
from product_app.session_store import (
    DELETE_SESSIONS_BEFORE_SQL,
    RAISE_SESSIONS_CUTOFF_SQL,
    SessionStore,
    _digest,
)

pytestmark = pytest.mark.usefixtures("_stable_catalog_price")

ESTIMATE = "/v1/query-runs/estimate"
CREATE = "/v1/query-runs"
IDLE = "/v1/session/idle"
KEEP_ACTIVE = "/v1/session/keep-active"
QUESTION = "Compare these answers"


@pytest.fixture(autouse=True)
def _daemon_never_refreshes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The import-time ``session-gc`` daemon must not end a window."""
    monkeypatch.setattr(auth, "_refresh_store_readiness", lambda store: None)


@pytest.fixture(autouse=True)
def _no_daily_cap(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every ``TestClient`` is one address ("testclient"), and the 2-a-day
    mint cap is not what these tests measure: the mint ROWS are counted
    instead. T60 puts the cap back for its capped case."""
    monkeypatch.setattr(settings, "session_mint_cap_override", 100)
    query_run_repository.clear()
    yield
    query_run_repository.clear()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "sessions.sqlite3"


@pytest.fixture
def live(db: Path) -> Iterator[SessionStore]:
    store = SessionStore(str(db))
    session_store.configure(store)
    try:
        yield store
    finally:
        auth.session_repository._sessions.clear()
        auth.session_repository._valid_after.clear()
        store.close()


def _code(response: Any) -> str | None:
    try:
        return str(response.json()["detail"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


def _detail(response: Any) -> dict[str, Any]:
    body = response.json()
    assert isinstance(body, dict) and isinstance(body.get("detail"), dict), body
    detail: dict[str, Any] = body["detail"]
    return detail


def _assert_unchecked_page(response: Any, *, heading: str, body: str, title: str) -> None:
    """The 503 page's headers and words (plan §2.1.4, §2.1.6)."""
    assert response.status_code == 503, (response.status_code, set_cookies(response))
    assert response.headers.get("retry-after") == "60"
    assert response.headers.get("cache-control") == "no-store"
    assert set_cookies(response) == [], "the page must set no cookie (FM-1.6)"
    page = parse(response.text)
    assert page.title == title
    assert page.headings == [heading]
    assert body in page.body_text
    tries = [text for attrs, text in page.links if attrs.get("href") == "/ui"]
    assert tries == [TRY_AGAIN]


def _signed_in_cookie(db: Path, label: str = "asha") -> tuple[UUID, str, auth._Session]:
    account_id, email = account(db, label)
    return account_id, email, signed_in_session(account_id)


# -- T1 / T2: both doors keep the cookie -----------------------------------------------


def test_t1_ui_keeps_a_signed_in_cookie_it_could_not_check(db: Path, live: SessionStore) -> None:
    """T1 (FM-1.1, 1.5, 1.6, 1.13, 1.20). Not ready, Asha's cached signed-in
    cookie loads ``/ui`` three times: each a 503 with ``Retry-After: 60``,
    ``Cache-Control: no-store``, NO ``Set-Cookie``, the owner's heading, and
    none of her CSRF token, session id or email, no ``app.js`` and no
    ``<form``. Mint rows delta 0, cached delta 0. Partners: after recovery the
    same cookie gets 200, a ``Set-Cookie`` with the SAME id and "Sign out";
    a cookie-less load moves the mint rows by exactly 1.
    Red when: the unchecked branch falls through to ``issue_session``, or the
    page calls ``attach_session_cookie``."""
    _account_id, email, session = _signed_in_cookie(db)
    sid, csrf = session.session_id, session.csrf_token
    not_ready(live)
    before = counts()
    for _ in range(3):
        response = client(sid).get("/ui")
        _assert_unchecked_page(
            response, heading=SIGNED_IN_HEADING, body=SIGNED_IN_BODY, title=SIGNED_IN_TITLE
        )
        for secret in (csrf, sid, email, "app.js", "<form"):
            assert secret not in response.text, secret
    assert counts() == before, "no mint and no new cached session (FM-1.20)"
    ready(live)
    back = client(sid).get("/ui")
    assert back.status_code == 200
    assert cookie_value(back) == sid, "the same cookie, kept through the window"
    page = parse(back.text)
    assert [text for attrs, text in page.buttons if attrs.get("id") == "sign-out"] == ["Sign out"]
    minted = mint_count()
    fresh = TestClient(app).get("/ui")
    assert fresh.status_code == 200
    assert mint_count() - minted == 1, "partner: the counter counts a real mint"


def test_t2_v1_session_keeps_a_signed_in_cookie_it_could_not_check(
    db: Path, live: SessionStore
) -> None:
    """T2 (FM-1.2). Same state on ``/v1/session``: 401 ``SESSION_UNCHECKED``
    with the owner's sentence, no ``Set-Cookie``, ``no-store``, no
    ``csrf_token`` anywhere in the body; mint delta 0, cached delta 0.
    Partner: after recovery, 200 with her ``account_id`` and the same cookie.
    Red when: ``/v1/session`` mints (today: 200 with a new cookie, FM P1)."""
    account_id, _email, session = _signed_in_cookie(db)
    sid = session.session_id
    not_ready(live)
    before = counts()
    response = client(sid).get("/v1/session")
    assert response.status_code == 401, (
        response.status_code,
        response.text,
        set_cookies(response),
    )
    assert _detail(response) == {"code": "SESSION_UNCHECKED", "message": SIGNED_IN_401}
    assert set_cookies(response) == []
    assert response.headers.get("cache-control") == "no-store"
    assert "csrf_token" not in response.text
    assert counts() == before
    ready(live)
    back = client(sid).get("/v1/session")
    assert back.status_code == 200
    assert back.json()["account_id"] == str(account_id)
    assert cookie_value(back) == sid


# -- T3 / T3b: one cutoff read per request, and no later refusal ignored -----------------


def _create_body(probe: TestClient, csrf: str) -> dict[str, Any]:
    """A create body that clears the cost guardrail, priced with an estimate
    made BEFORE the counter is read."""
    preview = probe.post(
        ESTIMATE,
        json={"query_text": QUESTION, "model_slots": DEFAULT_MODEL_IDS},
        headers={"X-CSRF-Token": csrf},
    )
    assert preview.status_code == 200, preview.text
    estimate = preview.json()["cost_estimate"]
    body = acknowledged_request(QUESTION)
    if estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": estimate["estimated_cost_usd"],
            "confirmation_token": estimate["confirmation_token"],
        }
    return body


def _request(route: str, sid: str, csrf: str, body: dict[str, Any] | None = None) -> Any:
    made = client(sid)
    headers = {"X-CSRF-Token": csrf}
    if route == "GET /ui":
        return made.get("/ui")
    if route == "GET /v1/session":
        return made.get("/v1/session")
    if route == "GET idle":
        return made.get(IDLE)
    if route == "GET active":
        return made.get(ACTIVE)
    if route == "POST keep-active":
        return made.post(KEEP_ACTIVE, headers=headers)
    if route == "POST estimate":
        return made.post(
            ESTIMATE,
            json={"query_text": QUESTION, "model_slots": DEFAULT_MODEL_IDS},
            headers=headers,
        )
    if route == "POST create":
        return made.post(CREATE, json=body, headers=headers)
    raise AssertionError(route)


@pytest.mark.parametrize(
    ("route", "reads"),
    [
        ("GET /ui", 1),
        ("GET /v1/session", 1),
        ("GET idle", 1),
        ("GET active", 1),
        ("POST keep-active", 2),
        ("POST estimate", 3),
        ("POST create", 4),
    ],
)
def test_t3_cutoff_reads_per_request(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, route: str, reads: int
) -> None:
    """T3 (FM-1.3, Codex F2; plan §2.1.2's table). A spy on
    ``sessions_valid_after`` counts the reads one request makes for a
    signed-in cached cookie: 1 for ``/ui``, ``/v1/session``, the idle check
    and ``/v1/query-runs/active``; 2 for "Stay signed in"; 3 for an estimate;
    4 for a run creation. The request succeeds (partner: the spy saw it).
    Red when: ``/ui``'s two helpers read again (``/ui`` 3), the idle route's
    ``flush`` reads again (idle 2, keep-active 3), or
    ``issue_or_resume_session`` goes back to ``get`` then ``touch`` (2). The
    estimate and creation rows pin the deliberate re-checks (ADR-0137
    decision 3; the admission check) so a builder cannot drop one."""
    account_id, _email, session = _signed_in_cookie(db, "reads")
    sid, csrf = session.session_id, session.csrf_token
    body = _create_body(client(sid), csrf) if route == "POST create" else None
    spy = ScriptedCutoff(live, account_id)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    with isolated_run_semaphore(4):
        response = _request(route, sid, csrf, body)
    assert response.status_code in (200, 202), (route, response.status_code, response.text)
    assert spy.calls == reads, (route, spy.calls)


@pytest.mark.parametrize("route", ["GET /ui", "GET /v1/session", "GET active"])
def test_t3_an_anonymous_cache_hit_reads_no_cutoff(
    live: SessionStore, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """T3's partner. An anonymous cache hit reads no cutoff (``auth.py``'s
    anonymous-age test). Red when: the anonymous path asks the store."""
    session = anonymous_session()
    spy = ScriptedCutoff(live, session.account_id)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    response = _request(route, session.session_id, session.csrf_token)
    assert response.status_code == 200, response.text
    assert spy.calls == 0


OK: tuple[bool, datetime | None] = (True, None)
NOT_READ: tuple[bool, datetime | None] = (False, None)


def test_t3b_ui_after_one_good_read_renders_its_real_time_left(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3b, ``/ui`` (Codex F2). The first read answers "no cutoff" and every
    later one "not read": the page resumes on the session it checked, with
    the real ``data-max-age-seconds-left`` (about 12 hours, never ``0``) and
    the same cookie; no mint. Red when: a later read's refusal turns the
    page into a mint (today: ``touch`` reads again and mints) or a helper
    reads again and writes ``0``."""
    account_id, _email, session = _signed_in_cookie(db, "ui3b")
    sid = session.session_id
    monkeypatch.setattr(
        live, "sessions_valid_after", ScriptedCutoff(live, account_id, [OK], then=NOT_READ)
    )
    before = counts()
    response = client(sid).get("/ui")
    assert response.status_code == 200
    assert cookie_value(response) == sid
    assert counts() == before
    page = parse(response.text)
    assert "idle-reminder" in page.ids
    left = int(response.text.split('data-max-age-seconds-left="', 1)[1].split('"', 1)[0])
    assert 11 * 3600 < left <= 12 * 3600, left


def test_t3b_idle_makes_one_read_and_a_later_refusal_is_not_ignored(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3b, the idle check and "Stay signed in" (Codex F2: today's idle route
    answers 200, makes two lookups, and renews the cookie although the second
    read refused). With the first read good and the rest "not read": the
    idle check answers 200 with exactly 1 read; keep-active answers 401
    ``SESSION_UNCHECKED`` (its second read, in ``_idle_response``, refuses)
    and sets no cookie. Red when: ``flush`` reads again, or keep-active's
    second refusal is dropped or reported as an ended session."""
    account_id, _email, session = _signed_in_cookie(db, "idle3b")
    sid, csrf = session.session_id, session.csrf_token
    spy = ScriptedCutoff(live, account_id, [OK], then=NOT_READ)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    idle = client(sid).get(IDLE)
    assert idle.status_code == 200, idle.text
    assert spy.calls == 1
    spy.calls, spy.script = 0, [OK]
    kept = client(sid).post(KEEP_ACTIVE, headers={"X-CSRF-Token": csrf})
    assert kept.status_code == 401, kept.text
    assert _detail(kept)["code"] == "SESSION_UNCHECKED"
    assert set_cookies(kept) == []


@pytest.mark.parametrize("route", ["POST estimate", "POST create"])
def test_t3b_a_refusal_at_the_spend_key_is_unchecked_and_stores_no_run(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    """T3b, the estimate and the run creation. Read 1 (``require_session``)
    is good; read 2 (the early late-run guard, ``query_runs.py:725`` /
    ``:788``) answers "not read" and HANDS ON (the guard returns, as it does
    for an ended session); read 3, the spend key (``spend_meter_for``),
    refuses with 401 ``SESSION_UNCHECKED``; no run is stored (delta 0).
    Partner: with every read good the same request succeeds and a creation
    stores exactly 1 run.
    Red when: the spend key's refusal is reported as an ended session, or
    the late-run guard's not-read refuses or is treated as a pass that
    stores a run."""
    account_id, _email, session = _signed_in_cookie(db, "spend3b")
    sid, csrf = session.session_id, session.csrf_token
    body = _create_body(client(sid), csrf) if route == "POST create" else None
    spy = ScriptedCutoff(live, account_id, [OK, NOT_READ, NOT_READ], then=NOT_READ)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    runs = len(query_run_repository._query_runs)
    with isolated_run_semaphore(4):
        refused = _request(route, sid, csrf, body)
    assert refused.status_code == 401, refused.text
    assert _detail(refused)["code"] == "SESSION_UNCHECKED"
    assert spy.calls == 3, "the third read is the one that refused"
    assert len(query_run_repository._query_runs) == runs
    spy.calls, spy.script, spy.then = 0, [], OK
    with isolated_run_semaphore(4):
        served = _request(route, sid, csrf, body)
    assert served.status_code in (200, 202), served.text
    expected = runs + 1 if route == "POST create" else runs
    assert len(query_run_repository._query_runs) == expected


# -- T4: get() keeps None; lookup() carries the reason ----------------------------------


def test_t4_get_stays_none_while_lookup_says_unchecked(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4 (FM-1.4). Not ready: ``get`` returns ``None`` (never a truthy
    "refused" value) while ``lookup`` returns ``Lookup(None,
    Unchecked.SIGNED_IN)``; ``spend_meter_for`` raises 401
    ``SESSION_UNCHECKED``; the estimate route and the idle check answer 401
    ``SESSION_UNCHECKED``. Partner: ready, ``get`` returns the session and
    both routes answer 200. Red when: ``get`` returns anything but ``None``
    for a refusal, or a site keeps ``session_ended``."""
    from fastapi import HTTPException
    from starlette.requests import Request

    _account_id, _email, session = _signed_in_cookie(db, "get4")
    sid, csrf = session.session_id, session.csrf_token
    not_ready(live)
    assert auth.session_repository.get(sid) is None
    found = auth.session_repository.lookup(sid)
    assert found.session is None
    assert found.unchecked is auth.Unchecked.SIGNED_IN
    assert auth.Unchecked.SIGNED_IN.value == "signed_in"
    context = auth.SessionContext(account_id=session.account_id, session_id=sid, csrf_token=csrf)
    fake = Request({"type": "http", "headers": [], "client": ("testclient", 1)})
    with pytest.raises(HTTPException) as raised:
        auth.spend_meter_for(context, fake)
    assert raised.value.status_code == 401
    refusal: Any = raised.value.detail
    assert refusal["code"] == "SESSION_UNCHECKED"
    for route in ("POST estimate", "GET idle"):
        response = _request(route, sid, csrf)
        assert response.status_code == 401, (route, response.text)
        assert _detail(response) == {"code": "SESSION_UNCHECKED", "message": SIGNED_IN_401}
    ready(live)
    assert auth.session_repository.get(sid) is not None
    for route in ("POST estimate", "GET idle"):
        assert _request(route, sid, csrf).status_code == 200, route


# -- T5 / T6: an ended session is never resumed, and nothing is touched -----------------


def test_t5_a_session_the_command_ended_stays_ended_through_the_window(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """T5 (FM-1.1, journeys N1). The command ends Asha's sessions; then the
    store is not ready: her cookie (still cached here) gets the 503 page on
    ``/ui``, never the workspace, and 401 on ``/v1/query-runs/active``. After
    recovery: the anonymous workspace, a new cookie and a mint delta of
    exactly 1. Partner: Ben, not ended, is signed in after recovery with his
    same cookie. Red when: the unchecked branch resumes, or recovery restores
    an ended session."""
    monkeypatch.setenv("SESSION_DB_PATH", str(db))
    asha, asha_email, ended = _signed_in_cookie(db, "asha5")
    _ben, _ben_email, kept = _signed_in_cookie(db, "ben5")
    assert end_sessions.main(["--email", asha_email]) == 0, capsys.readouterr()
    not_ready(live)
    page = client(ended.session_id).get("/ui")
    _assert_unchecked_page(
        page, heading=SIGNED_IN_HEADING, body=SIGNED_IN_BODY, title=SIGNED_IN_TITLE
    )
    api = client(ended.session_id).get(ACTIVE)
    assert api.status_code == 401
    ready(live)
    minted = mint_count()
    back = client(ended.session_id).get("/ui")
    assert back.status_code == 200
    assert cookie_value(back) not in (None, ended.session_id), "a new anonymous cookie"
    assert "sign-out" not in parse(back.text).ids
    assert mint_count() - minted == 1
    ben = client(kept.session_id).get("/ui")
    assert ben.status_code == 200 and cookie_value(ben) == kept.session_id
    assert "sign-out" in parse(ben.text).ids
    assert live.sessions_valid_after(asha)[0] is True, "partner: Asha's cutoff is readable"


def _durable_last_used(db: Path, session_id: str) -> str:
    import sqlite3

    connection = sqlite3.connect(str(db))
    try:
        row = connection.execute(
            "SELECT last_used_at FROM sessions WHERE session_digest = ?", (_digest(session_id),)
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, "partner: the durable row exists"
    return str(row[0])


def test_t6_unchecked_loads_do_not_extend_the_sessions_life(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T6 (FM-1.7, journeys N2). The cutoff read fails (scripted "not
    read"; the store stays writable, so a wrongful touch save WOULD land), and
    the clock moves 301 s before each of three loads: each load is the 503
    page, and the cached ``last_used_at``, ``persisted_last_used_at`` and the
    durable row's ``last_used_at`` are unchanged. Partner: one healthy load
    moves all three. Red when: the unchecked branch calls ``use``, ``touch``
    or ``_persist_touch``. (Today the loads are not 503, so it is red on that
    premise first.)"""
    clock = freeze(monkeypatch)
    account_id, _email, session = _signed_in_cookie(db, "life6")
    sid = session.session_id
    spy = ScriptedCutoff(live, account_id, then=NOT_READ)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    held = auth.session_repository._sessions[sid]
    before = (held.last_used_at, held.persisted_last_used_at, _durable_last_used(db, sid))
    for _ in range(3):
        clock.advance(timedelta(seconds=301))
        response = client(sid).get("/ui")
        assert response.status_code == 503, response.status_code
    assert (held.last_used_at, held.persisted_last_used_at, _durable_last_used(db, sid)) == before
    spy.then = OK
    clock.advance(timedelta(seconds=301))
    assert client(sid).get("/ui").status_code == 200
    after = (held.last_used_at, held.persisted_last_used_at, _durable_last_used(db, sid))
    assert all(a != b for a, b in zip(after, before, strict=True)), (before, after)


# -- T7 / T7b / T7c: an ended session is ended, not "unchecked" --------------------------


def _uncached_row(db: Path, account_id: UUID, *, age_by: timedelta) -> str:
    sid = f"w873f-row-{uuid4().hex}"
    now = datetime.now(UTC)
    plant_row(db, sid, account_id, created_at=now - age_by, last_used_at=now - timedelta(minutes=1))
    return sid


def _unknown_kind(store: SessionStore, monkeypatch: pytest.MonkeyPatch, who: UUID) -> None:
    """Every kind lookup of ``who`` fails (``None``), by both of the store's
    two ways of asking; every other id is asked for real."""
    real_is, real_has = store.is_anonymous, store.has_no_account_row
    monkeypatch.setattr(
        store, "is_anonymous", lambda target: None if target == who else real_is(target)
    )
    monkeypatch.setattr(
        store, "has_no_account_row", lambda target: None if target == who else real_has(target)
    )


def test_t7_a_known_signed_in_row_past_12_hours_is_ended_while_not_ready(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7 (FM-1.8). Not ready, uncached rows: a known signed-in row 13 h old
    is ENDED (200 anonymous page, a new cookie, mint delta exactly 1). An
    11 h old row of the same kind gets the 503 page (unchecked), and so does
    a 13 h old row whose kind lookup failed (it may be an anonymous session
    inside its 24 h). Red when: the 12-hour check moves after the not-ready
    exit (the 13 h row would get the page), or the kind is guessed."""
    old_account, _e1 = account(db, "old7")
    young_account, _e2 = account(db, "young7")
    unknown_account = uuid4()
    old = _uncached_row(db, old_account, age_by=timedelta(hours=13))
    young = _uncached_row(db, young_account, age_by=timedelta(hours=11))
    unknown = _uncached_row(db, unknown_account, age_by=timedelta(hours=13))
    _unknown_kind(live, monkeypatch, unknown_account)
    not_ready(live)
    minted = mint_count()
    ended = client(old).get("/ui")
    assert ended.status_code == 200
    assert cookie_value(ended) not in (None, old)
    assert mint_count() - minted == 1
    _assert_unchecked_page(
        client(young).get("/ui"),
        heading=SIGNED_IN_HEADING,
        body=SIGNED_IN_BODY,
        title=SIGNED_IN_TITLE,
    )
    _assert_unchecked_page(
        client(unknown).get("/ui"),
        heading=UNKNOWN_HEADING,
        body=UNKNOWN_BODY,
        title=UNKNOWN_TITLE,
    )


@pytest.mark.parametrize("how", ["12 hours", "idle", "sign-out everywhere"])
@pytest.mark.parametrize("store_fault", ["fetch raises", "store closed"])
def test_t7b_a_cached_session_that_ended_is_ended_when_the_store_then_fails(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, how: str, store_fault: str
) -> None:
    """T7b (Codex F3, S17). A signed-in session is cached, then ends (its
    12 hours pass; or it idles past its limit; or a sign-out everywhere in
    this process), THEN the session-row read fails (``fetch`` raises
    ``OperationalError``, or the store is closed): the API answers
    ``SESSION_EXPIRED`` or ``SESSION_MAX_AGE``, never ``SESSION_UNCHECKED``,
    and ``/ui`` is the ended path (200 anonymous, mint delta exactly 1), never
    the 503 page. Partner: a session never cached, same fault, gets the 503
    "session" page and mints nothing (S8).
    Red when: the ended list is not read before ``fetch``, or an ending path
    does not record the id."""
    clock = freeze(monkeypatch)
    account_id, _email, session = _signed_in_cookie(db, "ended7b")
    # Its row is never read (the read fails or the store is closed), so an id
    # with no row is the same cookie to the code under test.
    never_cached = f"w873f-never-{uuid4().hex}"
    sid = session.session_id
    if how == "12 hours":
        age(sid, auth.SIGNED_IN_MAX_AGE + timedelta(seconds=1), now=clock.at)
    elif how == "idle":
        clock.advance(auth.signed_in_idle_limit() + timedelta(seconds=1))
    else:
        assert live.end_sessions_before(account_id, clock.at) == "ended"
        auth.session_repository.end_sessions_of(account_id, clock.at)
    # The ending is noticed by a request (the purge at the top of the lookup).
    with auth.session_repository._lock:
        auth.session_repository._purge_expired_locked()
    assert sid not in auth.session_repository._sessions, "partner: the session left the cache"

    def run_checks() -> None:
        api = client(sid).get(ACTIVE)
        assert api.status_code == 401, api.text
        assert _code(api) in ("SESSION_EXPIRED", "SESSION_MAX_AGE"), api.text
        minted = mint_count()
        page = client(sid).get("/ui")
        assert page.status_code == 200, page.status_code
        assert cookie_value(page) not in (None, sid)
        assert mint_count() - minted == 1
        before = mint_count()
        _assert_unchecked_page(
            client(never_cached).get("/ui"),
            heading=UNKNOWN_HEADING,
            body=UNKNOWN_BODY,
            title=UNKNOWN_TITLE,
        )
        assert mint_count() == before

    if store_fault == "fetch raises":
        with failing_session_reads(live) as failing:
            run_checks()
        assert failing.raised >= 1, "partner: the fault was met"
    else:
        live.close()
        run_checks()


def test_t7c_a_session_that_expires_during_the_cutoff_wait_is_ended(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7c (Codex F3, S18), made deterministic: instead of a 0.6 s lock hold
    against a 0.3 s bound (the plan's shape, a timing race), the cutoff read
    itself moves the session clock past the 12 hours and answers "not read",
    which is what a read that waited out its bound looks like to the caller.
    The session is then ENDED: 401 ``SESSION_MAX_AGE`` or ``SESSION_EXPIRED``,
    and ``/ui`` mints (delta 1). Partner: the same "not read" with 1 h left is
    unchecked (401 ``SESSION_UNCHECKED``; the 503 page).
    Red when: the expiry re-check after a failed read is removed."""
    clock = freeze(monkeypatch)
    late, _e1, late_session = _signed_in_cookie(db, "late7c")
    early, _e2, early_session = _signed_in_cookie(db, "early7c")
    late_ui, _e3, late_ui_session = _signed_in_cookie(db, "lateui7c")
    age(early_session.session_id, auth.SIGNED_IN_MAX_AGE - timedelta(hours=1), now=clock.at)

    def ends_during_the_wait(call: int) -> None:
        if call == 1:
            clock.advance(timedelta(seconds=2))

    for who in (late, late_ui):
        # Aged here, not before the loop: the first round's 2 s step would
        # otherwise end late_ui before its own request, and no read would run.
        sid = late_session.session_id if who == late else late_ui_session.session_id
        age(sid, auth.SIGNED_IN_MAX_AGE - timedelta(seconds=1), now=clock.at)
        spy = ScriptedCutoff(live, who, [NOT_READ], on_call=ends_during_the_wait)
        monkeypatch.setattr(live, "sessions_valid_after", spy)
        if who == late:
            api = client(late_session.session_id).get(ACTIVE)
            assert api.status_code == 401
            assert _code(api) in ("SESSION_MAX_AGE", "SESSION_EXPIRED"), api.text
        else:
            minted = mint_count()
            page = client(late_ui_session.session_id).get("/ui")
            assert page.status_code == 200, page.status_code
            assert mint_count() - minted == 1
        assert spy.calls >= 1, "partner: the scripted read ran"
    monkeypatch.setattr(live, "sessions_valid_after", ScriptedCutoff(live, early, then=NOT_READ))
    api = client(early_session.session_id).get(ACTIVE)
    assert api.status_code == 401 and _code(api) == "SESSION_UNCHECKED", api.text
    assert client(early_session.session_id).get("/ui").status_code == 503


# -- T8: the wording follows what the server knows -------------------------------------


def test_t8_a_cookie_of_unknown_kind_gets_the_session_wording(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T8 (FM-1.11). An uncached ANONYMOUS row whose kind lookup fails, not
    ready: the 503 page has the "session" title, heading and body, and its
    visible text contains neither "account" nor "sign-in" (case-insensitive,
    parsed text); ``/v1/session`` answers the "session" 401 sentence.
    Partner: a known signed-in row gets the owner's words exactly. Red when:
    the variant is chosen wrongly or the kind is guessed."""
    anonymous_account = uuid4()
    anonymous = _uncached_row(db, anonymous_account, age_by=timedelta(minutes=5))
    signed_account, _email = account(db, "known8")
    signed = _uncached_row(db, signed_account, age_by=timedelta(minutes=5))
    _unknown_kind(live, monkeypatch, anonymous_account)
    not_ready(live)
    page = client(anonymous).get("/ui")
    _assert_unchecked_page(page, heading=UNKNOWN_HEADING, body=UNKNOWN_BODY, title=UNKNOWN_TITLE)
    text = parse(page.text).body_text.casefold()
    assert "account" not in text and "sign-in" not in text, text
    api = client(anonymous).get("/v1/session")
    assert api.status_code == 401
    assert _detail(api) == {"code": "SESSION_UNCHECKED", "message": UNKNOWN_401}
    _assert_unchecked_page(
        client(signed).get("/ui"),
        heading=SIGNED_IN_HEADING,
        body=SIGNED_IN_BODY,
        title=SIGNED_IN_TITLE,
    )
    known = client(signed).get("/v1/session")
    assert _detail(known) == {"code": "SESSION_UNCHECKED", "message": SIGNED_IN_401}


# -- T9 / T10 / T11: W88 first, nothing written, HEAD unchanged ---------------------------


def test_t9_another_sites_image_load_is_refused_before_the_unchecked_page(
    db: Path, live: SessionStore
) -> None:
    """T9 (FM-1.15). With an unchecked cookie, a cross-site image load of
    ``/ui`` gets W88's 403 and ``cross_site_refusals["/ui"]["subresource"]``
    moves by exactly 1. Partner: a same-origin navigation gets the 503 page.
    Red when: the unchecked check moves before ``cross_site_refusal``."""
    _account_id, _email, session = _signed_in_cookie(db, "w88")
    sid = session.session_id
    not_ready(live)
    before = fetch_site.status_snapshot()["/ui"]["subresource"]
    refused = client(sid).get(
        "/ui",
        headers={
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Dest": "image",
        },
    )
    assert refused.status_code == 403
    assert fetch_site.status_snapshot()["/ui"]["subresource"] == before + 1
    page = client(sid).get(
        "/ui",
        headers={
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        },
    )
    _assert_unchecked_page(
        page, heading=SIGNED_IN_HEADING, body=SIGNED_IN_BODY, title=SIGNED_IN_TITLE
    )


def _row_bytes(db: Path, session_id: str) -> tuple[Any, ...]:
    import sqlite3

    connection = sqlite3.connect(str(db))
    try:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_digest = ?", (_digest(session_id),)
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, "partner: the row is on disk"
    return tuple(row)


def test_t10_repeated_unchecked_gets_write_nothing(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T10 (FM-1.16, #511). With the cutoff read failing (the store
    writable), two ``/ui`` loads and one ``/v1/session`` leave the durable
    row byte-identical (``SELECT *``), the cached CSRF token identical and the
    mint rows unchanged. Partner: a healthy ``/v1/session`` rotates the token.
    Red when: the page path writes, rotates or mints."""
    account_id, _email, session = _signed_in_cookie(db, "write10")
    sid = session.session_id
    spy = ScriptedCutoff(live, account_id, then=NOT_READ)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    held = auth.session_repository._sessions[sid]
    row, token, minted = _row_bytes(db, sid), held.csrf_token, mint_count()
    assert client(sid).get("/ui").status_code == 503
    assert client(sid).get("/ui").status_code == 503
    assert client(sid).get("/v1/session").status_code == 401
    assert (_row_bytes(db, sid), held.csrf_token, mint_count()) == (row, token, minted)
    spy.then = OK
    healthy = client(sid).get("/v1/session")
    assert healthy.status_code == 200
    assert healthy.json()["csrf_token"] != token


def test_t11_head_ui_stays_405_and_sets_no_cookie(db: Path, live: SessionStore) -> None:
    """T11 (FM-1.17). ``HEAD /ui`` is 405 with no ``Set-Cookie``, ready and
    not ready. Partner: ``GET /ui`` answers (200 ready, 503 not ready). Red
    when: HEAD is added to the route without the GET rule."""
    _account_id, _email, session = _signed_in_cookie(db, "head11")
    sid = session.session_id
    for state, get_status in ((ready, 200), (not_ready, 503)):
        state(live)
        head = client(sid).head("/ui")
        assert head.status_code == 405
        assert set_cookies(head) == []
        assert client(sid).get("/ui").status_code == get_status


# -- T12 / T13: the page's structure and its one constant ---------------------------------


@pytest.mark.parametrize("kind", ["signed_in", "unknown_kind"])
def test_t12_the_page_has_one_theme_script_one_refresh_one_link_and_no_form(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """T12 (FM-1.5, FM-1.18), both variants, parsed with ``html.parser``:
    exactly one ``<script>``, with no ``src``, whose text is byte-identical to
    ``session-capped.html``'s theme gate; exactly one
    ``<meta http-equiv="refresh" content="60; url=/ui">``; exactly one link
    to ``/ui`` (``id="unchecked-try-again"``) reading "Try again"; no
    ``<form>``; no ``<input>``. Partner: the workspace page parses to a
    ``<script src="/static/app.js">``, so the parser does see ``src``
    scripts. Red when: a script, a form or a data island is added, or the
    refresh is removed."""
    if kind == "signed_in":
        account_id, _email = account(db, "page12")
        sid = signed_in_session(account_id).session_id
    else:
        anonymous_account = uuid4()
        sid = _uncached_row(db, anonymous_account, age_by=timedelta(minutes=5))
        _unknown_kind(live, monkeypatch, anonymous_account)
    not_ready(live)
    response = client(sid).get("/ui")
    assert response.status_code == 503
    page = parse(response.text)
    assert len(page.scripts) == 1, page.scripts
    attrs, text = page.scripts[0]
    assert "src" not in attrs
    assert text == capped_theme_gate()
    refreshes = [m for m in page.metas if (m.get("http-equiv") or "").lower() == "refresh"]
    assert refreshes == [{"http-equiv": "refresh", "content": "60; url=/ui"}]
    assert [(a.get("href"), a.get("id"), t) for a, t in page.links if a.get("href") == "/ui"] == [
        ("/ui", "unchecked-try-again", TRY_AGAIN)
    ]
    assert (page.forms, page.inputs) == (0, 0)
    ready(live)
    workspace = parse(TestClient(app).get("/ui").text)
    assert "/static/app.js" in [a.get("src") for a, _t in workspace.scripts]


def test_t13_the_refresh_constant_is_60_and_the_header_says_so(
    db: Path, live: SessionStore
) -> None:
    """T13. ``UNCHECKED_PAGE_REFRESH_S == 60`` (a literal, rule 7a), and a
    page rendered with it says ``Retry-After: 60`` and refreshes after 60.
    Red when: either changes alone."""
    from product_app import main

    assert main.UNCHECKED_PAGE_REFRESH_S == 60
    _account_id, _email, session = _signed_in_cookie(db, "const13")
    not_ready(live)
    response = client(session.session_id).get("/ui")
    assert response.headers.get("retry-after") == "60"
    assert 'content="60; url=/ui"' in response.text


# -- T14 / T15: a refused-unchecked request ends at the bound ------------------------------


def test_t14_an_unchecked_api_refusal_ends_at_the_bound_not_the_hold(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T14 (FM-5.3 part-fix). The bound is patched to 0.2 s and another thread
    holds the store lock for 1.5 s: a signed-in cached API request answers
    401 ``SESSION_UNCHECKED`` in under 0.7 s (it no longer waits on
    ``end_reason``'s unbounded ``fetch``). Partner: an ended session with no
    hold answers ``SESSION_EXPIRED``. Red when: the unchecked branch calls
    ``end_reason`` (it then waits about 1.5 s). Timing: run 10 times under
    load before trusting it (ADR-0176 practice)."""
    monkeypatch.setattr(session_store, "SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S", 0.2)
    _account_id, _email, session = _signed_in_cookie(db, "bound14")
    probe = client(session.session_id)
    with hold_store_lock(live, 1.5):
        response, took = timed(lambda: probe.get(ACTIVE))
    assert response.status_code == 401, (response.text, took)
    assert _code(response) == "SESSION_UNCHECKED", (response.text, took)
    assert took < 0.7, f"{took:.2f} s: the refusal waited for the hold"
    ended = auth.session_repository.create(account_id=uuid4()).session_id
    auth.session_repository.revoke(ended)
    gone = client(ended).get(ACTIVE)
    assert gone.status_code == 401 and _code(gone) == "SESSION_EXPIRED"


def test_t15_ui_behind_a_held_lock_is_the_page_at_the_bound(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T15 (FM-5.4). Same hold: ``/ui`` with a cached signed-in cookie
    answers the 503 page in under 0.7 s, with no ``Set-Cookie``. Partner: a
    0.1 s hold (under the bound) gives 200 signed in with the same cookie.
    Red when: the page path reads unbounded (today it mints, and its save
    waits the whole hold)."""
    monkeypatch.setattr(session_store, "SIGNED_IN_CUTOFF_LOCK_TIMEOUT_S", 0.2)
    _account_id, _email, session = _signed_in_cookie(db, "page15")
    sid = session.session_id
    probe = client(sid)
    with hold_store_lock(live, 1.5):
        response, took = timed(lambda: probe.get("/ui"))
    assert response.status_code == 503, (response.status_code, took)
    assert set_cookies(response) == []
    assert took < 0.7, f"{took:.2f} s"
    with hold_store_lock(live, 0.1):
        served = client(sid).get("/ui")
    assert served.status_code == 200
    assert cookie_value(served) == sid


# -- T16: the contract ----------------------------------------------------------------


def test_t16_the_new_statuses_are_documented() -> None:
    """T16 (FM-1.14, FM-2.6). ``app.openapi()`` documents 503 (``text/html``)
    on ``/ui``, 401 on ``/v1/session`` and 503 on ``/v1/auth/google/start``.
    Partner: W88's 403 entries are there. Red when: a status is
    undocumented. (``make openapi-check`` after ``make openapi-export`` is the
    builder's gate; a green ``make api-contract`` proves nothing here, since
    Schemathesis never reaches the state.)"""
    paths = app.openapi()["paths"]
    ui = paths["/ui"]["get"]["responses"]
    session = paths["/v1/session"]["get"]["responses"]
    start = paths["/v1/auth/google/start"]["post"]["responses"]
    assert "403" in ui and "403" in session, "partner: W88's entries"
    assert "text/html" in ui["503"]["content"]
    assert "401" in session
    assert "503" in start


# -- T18: a failed session-row read is unchecked, a missing row is not --------------------


def test_t18_a_failed_session_row_read_is_unchecked_and_mints_nothing(
    db: Path, live: SessionStore
) -> None:
    """T18 (FM-1.21). An uncached cookie whose ``fetch`` raises
    ``sqlite3.OperationalError("disk I/O error")`` (on the store's own
    connection) gets the 503 "session" page and mints nothing; so does one
    presented while the store is closed. Partners: a missing row mints
    exactly 1; an unparseable row mints exactly 1 (both are "absent", S7).
    Red when: ``fetch_checked`` reports a failed read as "no row"."""
    owner, _email = account(db, "row18")
    sid = _uncached_row(db, owner, age_by=timedelta(minutes=5))
    with failing_session_reads(live) as failing:
        minted = mint_count()
        page = client(sid).get("/ui")
        assert failing.raised >= 1
    _assert_unchecked_page(page, heading=UNKNOWN_HEADING, body=UNKNOWN_BODY, title=UNKNOWN_TITLE)
    assert mint_count() == minted
    minted = mint_count()
    missing = client(f"w873f-missing-{uuid4().hex}").get("/ui")
    assert missing.status_code == 200 and mint_count() - minted == 1
    broken = f"w873f-broken-{uuid4().hex}"
    plant_row(
        db,
        broken,
        owner,
        created_at=datetime.now(UTC) + timedelta(days=3),
        last_used_at=datetime.now(UTC) + timedelta(days=3),
    )
    minted = mint_count()
    unparseable = client(broken).get("/ui")
    assert unparseable.status_code == 200 and mint_count() - minted == 1
    live.close()
    minted = mint_count()
    closed = client(sid).get("/ui")
    _assert_unchecked_page(closed, heading=UNKNOWN_HEADING, body=UNKNOWN_BODY, title=UNKNOWN_TITLE)
    assert mint_count() == minted


# -- T19: the Lookup invariant over the states -------------------------------------------


def _state(
    name: str, db: Path, store: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    """Put the store in state ``name`` of plan §2.0; return the cookie and the
    outcome expected: ``served``, ``ended`` or ``unchecked:<kind>``."""
    if name == "S1 cached anonymous, not ready":
        sid = anonymous_session().session_id
        not_ready(store)
        return sid, "served"
    if name in ("S3 cached signed-in, ready", "S4 cached signed-in, cutoff covers it"):
        who, _e = account(db, "s3")
        sid = signed_in_session(who).session_id
        if name.startswith("S4"):
            assert store.end_sessions_before(who, datetime.now(UTC)) == "ended"
        return sid, "served" if name.startswith("S3") else "ended"
    if name == "S5 cached signed-in, not ready":
        who, _e = account(db, "s5")
        sid = signed_in_session(who).session_id
        not_ready(store)
        return sid, "unchecked:signed_in"
    if name == "S6 cached, kind unknown at its restore, not ready":
        who, _e = account(db, "s6")
        sid = _uncached_row(db, who, age_by=timedelta(minutes=5))
        _unknown_kind(store, monkeypatch, who)
        assert auth.session_repository.lookup(sid).session is not None, "S15: restored"
        not_ready(store)
        return sid, "unchecked:unknown_kind"
    if name == "S7 not cached, no row":
        return f"w873f-none-{uuid4().hex}", "ended"
    if name == "S8 not cached, fetch fails":
        who, _e = account(db, "s8")
        sid = _uncached_row(db, who, age_by=timedelta(minutes=5))
        real = store._conn
        from tests.unchecked_harness import FailingConnection, is_session_row_read

        store._conn = FailingConnection(real, is_session_row_read)  # type: ignore[assignment]
        return sid, "unchecked:unknown_kind"
    if name == "S9 not cached anonymous, not ready":
        sid = _uncached_row(db, uuid4(), age_by=timedelta(minutes=5))
        not_ready(store)
        return sid, "served"
    if name == "S10 not cached signed-in, 13 h, not ready":
        who, _e = account(db, "s10")
        sid = _uncached_row(db, who, age_by=timedelta(hours=13))
        not_ready(store)
        return sid, "ended"
    if name == "S12 not cached signed-in, not ready":
        who, _e = account(db, "s12")
        sid = _uncached_row(db, who, age_by=timedelta(minutes=5))
        not_ready(store)
        return sid, "unchecked:signed_in"
    if name == "S13 not cached, kind unknown, not ready":
        who = uuid4()
        sid = _uncached_row(db, who, age_by=timedelta(minutes=5))
        _unknown_kind(store, monkeypatch, who)
        not_ready(store)
        return sid, "unchecked:unknown_kind"
    if name == "S14 not cached signed-in, cutoff covers it":
        who, _e = account(db, "s14")
        sid = _uncached_row(db, who, age_by=timedelta(minutes=5))
        assert store.end_sessions_before(who, datetime.now(UTC)) == "ended"
        plant_row(
            db,
            sid,
            who,
            created_at=datetime.now(UTC) - timedelta(minutes=5),
            last_used_at=datetime.now(UTC),
        )
        return sid, "ended"
    if name == "S15 not cached signed-in, ready":
        who, _e = account(db, "s15")
        return _uncached_row(db, who, age_by=timedelta(minutes=5)), "served"
    raise AssertionError(name)


STATES = [
    "S1 cached anonymous, not ready",
    "S3 cached signed-in, ready",
    "S4 cached signed-in, cutoff covers it",
    "S5 cached signed-in, not ready",
    "S6 cached, kind unknown at its restore, not ready",
    "S7 not cached, no row",
    "S8 not cached, fetch fails",
    "S9 not cached anonymous, not ready",
    "S10 not cached signed-in, 13 h, not ready",
    "S12 not cached signed-in, not ready",
    "S13 not cached, kind unknown, not ready",
    "S14 not cached signed-in, cutoff covers it",
    "S15 not cached signed-in, ready",
]


@pytest.mark.parametrize("name", STATES)
def test_t19_lookup_never_returns_a_session_and_a_reason_together(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """T19 (plan §2.0, one row per state). ``lookup`` gives exactly one
    outcome per state, and ``unchecked`` is never set together with a
    session. Red when: a branch returns both, or a state gets another
    outcome (for example S10, the 12 hours, answered as unchecked)."""
    real_conn = live._conn
    try:
        sid, expected = _state(name, db, live, monkeypatch)
        found = auth.session_repository.lookup(sid)
    finally:
        live._conn = real_conn
    assert not (found.session is not None and found.unchecked is not None), found
    if expected == "served":
        assert found.session is not None and found.session.session_id == sid
    elif expected == "ended":
        assert (found.session, found.unchecked) == (None, None)
    else:
        assert found.session is None
        assert found.unchecked is not None
        assert found.unchecked.value == expected.split(":", 1)[1]


# -- T60: no store at all is today's behaviour (the owner's "No database") ----------------


def test_t60_with_no_store_a_presented_cookie_gets_a_fresh_session_as_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T60 (S16, CHG-088 (g): "Today's behaviour (Recommended)"). No session
    store: a presented cookie this process never issued gets 200 and a new
    cookie, with exactly one mint, on ``/ui`` and on ``/v1/session``; on a
    network whose 2 mints are spent, ``/ui`` gets the capped page (429) with
    its sign-in-only session when the per-minute limiter allows; the sign-in
    start answers 503 ``SIGN_IN_UNAVAILABLE`` with the owner's sentence.
    Partners: a cookie-less first visit mints exactly 1; a cookie THIS
    no-store process issued (cached, S2) is served with the same cookie.
    Red when: the no-store branch flips to "unchecked" (the page or the
    401), or the start is not refused."""
    from tests.unchecked_harness import SIGN_IN_UNAVAILABLE

    session_store.configure(None)
    monkeypatch.setattr(settings, "google_oauth_client_id", "w873f-client")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "w873f-secret")
    monkeypatch.setattr(
        settings, "google_oauth_redirect_uri", "https://testserver/v1/auth/google/callback"
    )
    stale = f"w873f-stale-{uuid4().hex}"
    for path in ("/ui", "/v1/session"):
        minted = mint_count()
        response = client(stale).get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert cookie_value(response) not in (None, stale)
        assert mint_count() - minted == 1, path
    minted = mint_count()
    first = TestClient(app).get("/ui")
    assert first.status_code == 200 and mint_count() - minted == 1
    own = cookie_value(first)
    assert own is not None
    again = client(own).get("/ui")
    assert again.status_code == 200 and cookie_value(again) == own
    csrf = client(own).get("/v1/session").json()["csrf_token"]
    start = client(own).post("/v1/auth/google/start", headers={"X-CSRF-Token": csrf})
    assert start.status_code == 503, start.text
    assert _detail(start) == {"code": "SIGN_IN_UNAVAILABLE", "message": SIGN_IN_UNAVAILABLE}
    assert start.headers.get("retry-after") == "60"
    monkeypatch.setattr(settings, "session_mint_cap_override", 2)
    statuses = [TestClient(app).get("/ui").status_code for _ in range(3)]
    assert statuses[-1] == 429, f"partner: the network's mints are spent: {statuses}"
    capped = client(stale).get("/ui")
    assert capped.status_code == 429
    assert cookie_value(capped) is not None, "the capped page's sign-in-only session"


# -- T61 (and T3b's fourth read): admission keeps its durable read --------------------------


def _write_cutoff_elsewhere(db: Path, account_id: UUID) -> None:
    """The operator command's two statements, on their own connection: an
    end written by another process (the shape of
    ``test_another_process_applies_the_command_on_its_next_lookup``)."""
    import sqlite3

    stamp = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(str(db), timeout=5.0)
    try:
        connection.execute(RAISE_SESSIONS_CUTOFF_SQL, (stamp, str(account_id)))
        connection.execute(DELETE_SESSIONS_BEFORE_SQL, (str(account_id), stamp))
        connection.commit()
    finally:
        connection.close()


def test_t61_admission_refuses_a_session_another_process_ended_after_the_spend_key(
    db: Path, live: SessionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T61 (FM-5.8; Codex's interleaving, ``memory_external_end: accepted;
    runs_stored=1``). The spend-key check passes; then another process writes
    the account's durable cutoff; then admission runs (inside the run store's
    lock): 401 ``SESSION_EXPIRED``, runs stored delta 0. Partner: with no
    cutoff written the same creation stores exactly 1 run. Second case (and
    T3b's fourth read): reads 1-3 good, admission's read "not read": 401
    ``SESSION_UNCHECKED``, runs delta 0, and ``end_reason`` called exactly 0
    times. Red when: admission stops reading the durable cutoff, or its
    unchecked branch calls ``end_reason``."""
    ended_account, _e1, ended = _signed_in_cookie(db, "admit61")
    kept_account, _e2, kept = _signed_in_cookie(db, "partner61")
    unread_account, _e3, unread = _signed_in_cookie(db, "unread61")
    bodies = {
        s.session_id: _create_body(client(s.session_id), s.csrf_token)
        for s in (ended, kept, unread)
    }
    # The route calls the name ``query_runs`` imported from ``auth``.
    real_meter = auth.spend_meter_for
    ends_written: list[UUID] = []

    def meter_then_end(session: Any, request: Any) -> Any:
        answer = real_meter(session, request)
        if session.account_id == ended_account:
            _write_cutoff_elsewhere(db, ended_account)
            ends_written.append(ended_account)
        return answer

    monkeypatch.setattr("product_app.query_runs.spend_meter_for", meter_then_end)
    for session in (ended, kept):
        body = bodies[session.session_id]
        runs = len(query_run_repository._query_runs)
        with isolated_run_semaphore(4):
            response = _request("POST create", session.session_id, session.csrf_token, body)
        if session is ended:
            assert response.status_code == 401, response.text
            assert _code(response) == "SESSION_EXPIRED", response.text
            assert len(query_run_repository._query_runs) == runs
        else:
            assert response.status_code == 202, response.text
            assert len(query_run_repository._query_runs) == runs + 1
    assert ends_written == [ended_account], "partner: the end was written after the spend key"
    assert kept_account != ended_account
    body = bodies[unread.session_id]
    spy = ScriptedCutoff(live, unread_account, [OK, OK, OK], then=NOT_READ)
    monkeypatch.setattr(live, "sessions_valid_after", spy)
    reasons: list[str] = []
    real_reason = auth.session_repository.end_reason

    def counted(session_id: str) -> str:
        reasons.append(session_id)
        return real_reason(session_id)

    monkeypatch.setattr(auth.session_repository, "end_reason", counted)
    runs = len(query_run_repository._query_runs)
    with isolated_run_semaphore(4):
        response = _request("POST create", unread.session_id, unread.csrf_token, body)
    assert response.status_code == 401, response.text
    assert _code(response) == "SESSION_UNCHECKED", response.text
    assert spy.calls == 4, "the fourth read, admission's, refused"
    assert len(query_run_repository._query_runs) == runs
    assert reasons == [], "the unchecked branch never asks why a session ended"
