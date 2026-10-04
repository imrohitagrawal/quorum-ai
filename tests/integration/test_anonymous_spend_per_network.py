"""W47 (ADR-0144): anonymous spend is counted per network.

Written BEFORE the code, against the real routes (TestClient, live execution
off, the pinned static catalog: one default-panel run is charged exactly
$0.1052, the figure ``test_block_reason_and_daily_allowance.py`` pins). Every
test names, in its docstring, the change that turns it red. The failure-mode
rows cited are the numbered rows of
``docs/analysis/2026-10-04-w47-anonymous-spend-per-network-failure-modes.md``.

THE CONTRACT THIS FILE PINS (ADR-0144's Decision section, plus the choices it
left open, made here so the builder has one target):

* ``auth.spend_key_for(session, request)`` takes the request as its second
  positional argument. For an anonymous (cookie) session it returns the
  NETWORK's key: the same UUID for every anonymous session whose request comes
  from one network (``auth.client_ip_of``: the IPv4 address, an IPv6 address's
  /64, an IPv4-mapped IPv6 address as its IPv4), and a different one for a
  different network. Never the session's own account id.
* Every request whose network cannot be identified -- no client at all, or a
  client host that is not an address (the TestClient's ``"testclient"``) --
  gets ONE shared key (fail closed, decision 2).
* The key is keyed by ``QUORUM_TOKEN_SECRET`` as it reads at call time (the
  same as the signed-in key, ``session_store._account_key``), deterministic for
  one secret and one network, and not the signed-in derivation of the same
  text (decision 1's "W47-only prefix").
* A signed-in account keeps its own key (decision 3), including an older
  account whose stored spend key IS its account id (ADR-0136 backfill, CHG-024).
  The legacy ``X-Account-Id`` header keeps its own id.
* ``cost_estimate.daily_allowance`` gains a FIFTH key, ``shared_by_network``
  (bool): ``true`` for an anonymous cookie session, ``false`` for a signed-in
  account, for the legacy header, and for a service call that names no
  network. The charge-time ``OVER_DAILY_CAP`` 402's ``detail.daily_allowance``
  carries it too (decision 6).
* The run keeps the key it was created with (decision 4); no address is
  written to the cost ledger (decision 5).

Every dollar figure is a literal (rule 7a), never ``DAILY_CAP_USD``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from tests.google_token_stub import good_claims
from tests.helpers import isolated_run_semaphore, wait_for_free_permits
from tests.integration.test_google_sign_in import SignIn, _boot, _signed_in
from tests.integration.test_query_run_cost_guardrails import (
    DEFAULT_MODEL_IDS,
    _stable_catalog_price,  # noqa: F401 -- a fixture, used by name below
    acknowledged_request,
)

from product_app import auth, session_store
from product_app import query_run_orchestration as qro
from product_app.config import RuntimeEnvironment, settings
from product_app.costs import cost_estimation_service
from product_app.feedback_store import (
    COST_ACCEPTED_EVENT,
    COST_ACCEPTED_SIMULATED_EVENT,
    FeedbackStore,
    configure_for_tests,
)
from product_app.main import app
from product_app.query_run_orchestration import QueryRun, query_run_repository
from product_app.query_runs import _ip_rate_limiter

pytestmark = pytest.mark.usefixtures("_stable_catalog_price")

COOKIE = "quorum_session"
ESTIMATE = "/v1/query-runs/estimate"
RUNS = "/v1/query-runs"
SIGN_OUT = "/v1/auth/sign-out"
QUERY = "Compare these answers"
CHARGE_TYPES = frozenset({COST_ACCEPTED_EVENT, COST_ACCEPTED_SIMULATED_EVENT})

#: Two IPv4 networks (documentation ranges). A TestClient built with
#: ``client=(NET_A, port)`` is a directly connecting, untrusted peer, so
#: ``VisitorAddressMiddleware`` leaves it as the visitor.
NET_A = "198.51.100.10"
NET_B = "203.0.113.20"
#: Two addresses inside ONE IPv6 /64, and one in the next /64.
V6_SAME_1 = "2001:db8:47:1::1"
V6_SAME_2 = "2001:db8:47:1:ffff:ffff:ffff:fffe"
V6_OTHER = "2001:db8:47:2::1"
#: NET_A written as an IPv4-mapped IPv6 address.
NET_A_MAPPED = "::ffff:198.51.100.10"
#: A Fly proxy peer (inside TRUSTED_PROXY_NETWORKS) and two visitors behind it,
#: as tests/security/test_trusted_proxy_ips.py sets them.
FLY_PEER = "172.19.4.129"
VISITOR_X = "198.51.100.42"
VISITOR_Y = "198.51.100.43"

#: One default-panel simulated run under the pinned catalog (pinned elsewhere
#: too: test_block_reason_and_daily_allowance.py).
UNIT = Decimal("0.1052")


def _allowance_dict(spent: str, remaining: str, *, shared: bool) -> dict[str, Any]:
    return {
        "cap_usd": "0.40",
        "spent_usd": spent,
        "remaining_usd": remaining,
        "bounded_by": "daily_cap",
        "shared_by_network": shared,
    }


ANON_FRESH = _allowance_dict("0.0000", "0.4000", shared=True)
OWN_FRESH = _allowance_dict("0.0000", "0.4000", shared=False)


@pytest.fixture(autouse=True)
def _limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The per-network SESSION limits are not under test here (W30/W34 have
    their own suites); several browsers per network need more than 2 mints and
    more than 10 ``/v1/session`` calls a minute."""
    monkeypatch.setattr(settings, "session_mint_cap_override", 100)
    monkeypatch.setattr(_ip_rate_limiter, "CAPACITY", 10_000)
    monkeypatch.setattr(_ip_rate_limiter, "REFILL_PER_MINUTE", 10_000)
    query_run_repository.clear()
    yield
    query_run_repository.clear()


# --- helpers --------------------------------------------------------------------------


def _browser(host: str, headers: dict[str, str] | None = None) -> TestClient:
    """A new browser (empty cookie jar) connecting from ``host``."""
    return TestClient(app, client=(host, 50000), headers=headers)


def _request(host: str | None) -> Request:
    """A bare request from ``host`` (``None``: no client at all)."""
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": ESTIMATE,
            "headers": [],
            "query_string": b"",
            "client": None if host is None else (host, 50000),
        }
    )


def _context(client: TestClient) -> auth.SessionContext:
    record = auth.session_repository.get(client.cookies[COOKIE])
    assert record is not None, "the cookie does not resolve"
    return auth.SessionContext(
        account_id=record.account_id,
        session_id=record.session_id,
        csrf_token=record.csrf_token,
    )


def network_spend_key(client: TestClient, host: str | None) -> UUID:
    """The key ``auth.spend_key_for(session, request)`` gives this browser's
    session for a request from ``host`` -- asked of the code under test, so no
    test here (or in the files that import this) pins the hash construction."""
    key = auth.spend_key_for(_context(client), _request(host))
    assert isinstance(key, UUID)
    return key


def _account_of(client: TestClient) -> UUID:
    return _context(client).account_id


def _estimate(client: TestClient, csrf: str) -> dict[str, Any]:
    response = client.post(
        ESTIMATE,
        json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    estimate: dict[str, Any] = response.json()["cost_estimate"]
    return estimate


def _allowance(estimate: dict[str, Any]) -> Any:
    assert "daily_allowance" in estimate, f"no daily_allowance; keys: {sorted(estimate)}"
    return estimate["daily_allowance"]


def _run(client: TestClient, csrf: str, semaphore: Any, *, permits: int = 1) -> QueryRun:
    """One simulated cookie-path run, waited out (every one of the semaphore's
    ``permits`` back); the run as stored."""
    created = client.post(RUNS, json=acknowledged_request(QUERY), headers={"X-CSRF-Token": csrf})
    assert created.status_code == 202, created.text
    assert wait_for_free_permits(semaphore, permits) == permits
    run = query_run_repository.get(UUID(created.json()["query_run_id"]))
    assert run is not None
    assert run.cost_estimate.estimated_cost_usd == UNIT
    return run


def _key(run: QueryRun) -> UUID:
    """The spend key stored on ``run`` (set at create, decision 4)."""
    assert run.spend_key is not None
    return run.spend_key


def _charge_rows(store: FeedbackStore, key: UUID) -> int:
    return sum(
        1
        for event in store.iter_events(recorders=["cost"])
        if event.account_id == str(key) and event.event_type in CHARGE_TYPES
    )


def _sign_in(client: TestClient, sign_in: SignIn, sub: str, email: str) -> str:
    """Sign this browser in as its OWN Google subject; returns a fresh CSRF."""
    sign_in.stub.claims = good_claims(sub=sub, email=email)
    assert _signed_in(client).status_code in (302, 303, 307)
    return _boot(client)


def _account_spend_key(sign_in: SignIn, client: TestClient) -> UUID:
    account = _account_of(client)
    (key,) = [
        UUID(row["spend_key"])
        for row in sign_in.account_rows()
        if row["account_id"] == str(account)
    ]
    return key


# --- 1. one network, one allowance (rows 1 and 5) -------------------------------------


def test_a_second_anonymous_session_on_the_network_sees_the_first_sessions_spend() -> None:
    """RED-IF: an anonymous session's spend key is its own id (today), so a
    second session on the same network starts at $0.00 spent. Partners: a
    session on ANOTHER network still has the whole $0.40, and both sessions'
    runs are charged under one key that is neither session's id (rule 6b:
    exactly two charge rows under it, summing to exactly 2 x 0.1052)."""
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        first = _browser(NET_A)
        first_run = _run(first, _boot(first), semaphore)
        second = _browser(NET_A)
        second_csrf = _boot(second)

        seen = _estimate(second, second_csrf)
        elsewhere = _browser(NET_B)
        fresh = _estimate(elsewhere, _boot(elsewhere))
        second_run = _run(second, second_csrf, semaphore)

        key = _key(first_run)
        assert _allowance(seen) == _allowance_dict("0.1052", "0.2948", shared=True)
        assert _allowance(fresh) == ANON_FRESH
        assert second_run.spend_key == key
        assert key not in {_account_of(first), _account_of(second)}
        assert _charge_rows(store, key) == 2
        assert store.daily_spend_for(key) == Decimal("0.2104")


def test_the_networks_spend_blocks_a_new_session_on_it_with_the_daily_cap() -> None:
    """RED-IF: after one session spends $0.3156 (three runs), another session on
    the same network is not blocked with ``block_reason: "daily_cap"`` at the
    estimate AND at create, or the create charges a fourth run. Partner: a
    session on another network can still start a run (202)."""
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        spender = _browser(NET_A)
        spender_csrf = _boot(spender)
        key = _key([_run(spender, spender_csrf, semaphore) for _ in range(3)][0])
        elsewhere = _browser(NET_B)
        other_run = _run(elsewhere, _boot(elsewhere), semaphore)
        newcomer = _browser(NET_A)
        csrf = _boot(newcomer)

        estimate = _estimate(newcomer, csrf)
        created = newcomer.post(
            RUNS, json=acknowledged_request(QUERY), headers={"X-CSRF-Token": csrf}
        )
        assert wait_for_free_permits(semaphore, 1) == 1

        assert estimate["threshold_action"] == "block"
        assert estimate["block_reason"] == "daily_cap"
        assert _allowance(estimate) == _allowance_dict("0.3156", "0.0844", shared=True)
        assert created.status_code == 402, created.text
        detail = created.json()["detail"]
        assert detail["code"] == "COST_LIMIT_EXCEEDED"
        assert detail["cost_estimate"]["block_reason"] == "daily_cap"
        assert detail["cost_estimate"]["daily_allowance"]["shared_by_network"] is True
        assert _charge_rows(store, key) == 3
        assert other_run.spend_key != key
        assert _charge_rows(store, _key(other_run)) == 1


def test_signing_out_does_not_start_a_fresh_allowance(sign_in: SignIn) -> None:
    """THE OWNER'S CASE (CHG-027 a, row 1). RED-IF: after an anonymous session
    spends, signs in and signs out, the next anonymous session on the network
    starts with a fresh $0.40 (today's behaviour, ADR-0141). Partner: it really
    is a NEW anonymous session (a different account id)."""
    with configure_for_tests(), isolated_run_semaphore(1) as semaphore:
        client = _browser(NET_A)
        _run(client, _boot(client), semaphore)
        before = _account_of(client)
        csrf = _sign_in(client, sign_in, "108000000000000047001", "w47-out@example.com")
        assert client.post(SIGN_OUT, headers={"X-CSRF-Token": csrf}).status_code == 200

        again = _boot(client)
        after = _account_of(client)
        estimate = _estimate(client, again)

    assert after != before
    assert _allowance(estimate) == _allowance_dict("0.1052", "0.2948", shared=True)


# --- 2. signed-in accounts keep their own allowance (row 4) -----------------------------


def test_an_accounts_spend_and_the_networks_anonymous_spend_never_mix(sign_in: SignIn) -> None:
    """RED-IF: a later anonymous session on the network does not see exactly the
    network's anonymous spend ($0.1052) -- it sees $0.00 (today: a fresh
    session key) or $0.3156 (the account's $0.2104 added in) -- or the
    account's own estimate includes the network's spend. Partners: the account
    is metered under its own spend key, with exactly its two charges."""
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        anonymous = _browser(NET_A)
        _run(anonymous, _boot(anonymous), semaphore)
        account = _browser(NET_A)
        account_csrf = _sign_in(account, sign_in, "108000000000000047002", "w47-mix@example.com")
        account_key = _account_spend_key(sign_in, account)
        runs = [_run(account, account_csrf, semaphore) for _ in range(2)]

        later = _browser(NET_A)
        later_estimate = _estimate(later, _boot(later))
        own_estimate = _estimate(account, account_csrf)

        assert [run.spend_key for run in runs] == [account_key, account_key]
        assert _charge_rows(store, account_key) == 2
        assert _allowance(later_estimate) == _allowance_dict("0.1052", "0.2948", shared=True)
        assert _allowance(own_estimate) == _allowance_dict("0.2104", "0.1896", shared=False)


def test_an_exhausted_network_does_not_block_a_signed_in_account(sign_in: SignIn) -> None:
    """RED-IF: a network whose anonymous sessions spent $0.3156 does not block
    another anonymous session there (today it does not), or the block reaches a
    signed-in account on the same network. Partner: the account's estimate is
    allowed with its own whole $0.40."""
    with configure_for_tests(), isolated_run_semaphore(1) as semaphore:
        spender = _browser(NET_A)
        spender_csrf = _boot(spender)
        for _ in range(3):
            _run(spender, spender_csrf, semaphore)
        account = _browser(NET_A)
        account_csrf = _sign_in(account, sign_in, "108000000000000047003", "w47-own@example.com")

        own = _estimate(account, account_csrf)
        anonymous = _browser(NET_A)
        blocked = _estimate(anonymous, _boot(anonymous))

    assert blocked["threshold_action"] == "block"
    assert blocked["block_reason"] == "daily_cap"
    assert own["threshold_action"] == "allow"
    assert _allowance(own) == OWN_FRESH


def test_an_older_account_whose_spend_key_is_its_own_id_keeps_its_own_allowance(
    sign_in: SignIn,
) -> None:
    """A GUARD against one wrong build: ADR-0136's backfill gives an account
    created before the spend key a stored key EQUAL to its account id, so
    "the store returned the id, therefore anonymous" would meter that signed-in
    account under the network. RED-IF that happens (its run's key is not its
    id, or the network's anonymous spend shows on its estimate), or the
    ``shared_by_network`` field is missing (red today on that field only)."""
    with configure_for_tests(), isolated_run_semaphore(1) as semaphore:
        spender = _browser(NET_A)
        spender_csrf = _boot(spender)
        for _ in range(3):
            _run(spender, spender_csrf, semaphore)
        account = _browser(NET_A)
        csrf = _sign_in(account, sign_in, "108000000000000047004", "w47-old@example.com")
        account_id = _account_of(account)
        sign_in.store._conn.execute(  # noqa: SLF001 - the backfilled shape
            "UPDATE accounts SET spend_key = account_id"
        )
        assert sign_in.store.spend_key_for(account_id) == account_id

        estimate = _estimate(account, csrf)
        run = _run(account, csrf, semaphore)

    assert _allowance(estimate) == OWN_FRESH
    assert run.spend_key == account_id


# --- 3. what one network is (rows 3, 6) -------------------------------------------------


def test_two_ipv6_addresses_in_one_64_share_and_the_next_64_does_not() -> None:
    """RED-IF: an IPv6 network is keyed per address (each address a fresh
    $0.40) or wider than the /64 the session limit counts (ADR-0132). Partner:
    the next /64 has the whole allowance."""
    with configure_for_tests(), isolated_run_semaphore(1) as semaphore:
        first = _browser(V6_SAME_1)
        _run(first, _boot(first), semaphore)
        same = _browser(V6_SAME_2)
        shared = _estimate(same, _boot(same))
        other = _browser(V6_OTHER)
        separate = _estimate(other, _boot(other))

    assert _allowance(shared) == _allowance_dict("0.1052", "0.2948", shared=True)
    assert _allowance(separate) == ANON_FRESH


def test_an_ipv4_mapped_ipv6_address_is_its_ipv4_network() -> None:
    """RED-IF: ``::ffff:198.51.100.10`` gets a different allowance from
    ``198.51.100.10`` (one visitor, two allowances). Partner: another IPv4
    network is fresh."""
    with configure_for_tests(), isolated_run_semaphore(1) as semaphore:
        plain = _browser(NET_A)
        _run(plain, _boot(plain), semaphore)
        mapped = _browser(NET_A_MAPPED)
        shared = _estimate(mapped, _boot(mapped))
        other = _browser(NET_B)
        separate = _estimate(other, _boot(other))

    assert _allowance(shared) == _allowance_dict("0.1052", "0.2948", shared=True)
    assert _allowance(separate) == ANON_FRESH


def test_two_visitors_behind_flys_proxy_each_get_their_own_spend_allowance() -> None:
    """The spend half of W30's owner case. Both visitors arrive from ONE Fly
    proxy peer. RED-IF the spend key reads the peer (both share one allowance)
    or the session (a second session of visitor X starts fresh, today).
    Partner: visitor Y, behind the same peer, is fresh."""
    with configure_for_tests(), isolated_run_semaphore(1) as semaphore:
        x_first = _browser(FLY_PEER, {"Fly-Client-IP": VISITOR_X})
        _run(x_first, _boot(x_first), semaphore)
        x_second = _browser(FLY_PEER, {"Fly-Client-IP": VISITOR_X})
        again = _estimate(x_second, _boot(x_second))
        y = _browser(FLY_PEER, {"Fly-Client-IP": VISITOR_Y})
        fresh = _estimate(y, _boot(y))

    assert _allowance(again) == _allowance_dict("0.1052", "0.2948", shared=True)
    assert _allowance(fresh) == ANON_FRESH


def test_sessions_whose_network_cannot_be_identified_share_one_allowance() -> None:
    """Row 3, at the route: the TestClient's host ``"testclient"`` is not an
    address. RED-IF each such session gets a fresh $0.40 (the bug again).
    Partner: the first session really spent (one charge under the shared key)."""
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        first = TestClient(app)
        run = _run(first, _boot(first), semaphore)
        second = TestClient(app)
        seen = _estimate(second, _boot(second))

        assert _charge_rows(store, _key(run)) == 1
        assert _allowance(seen) == _allowance_dict("0.1052", "0.2948", shared=True)


def test_spend_key_for_gives_every_unidentifiable_request_one_key() -> None:
    """Row 3 / decision 2, at the unit: no client, ``"testclient"`` and any other
    non-address host all get ONE key, whichever anonymous session asks. RED-IF
    ``spend_key_for`` takes no request (today: TypeError), returns the session
    id, or gives a non-address host its own key. Partner: an identified network
    gets a different key."""
    first, second = TestClient(app), TestClient(app)
    _boot(first)
    _boot(second)

    keys = {
        network_spend_key(first, None),
        network_spend_key(second, None),
        network_spend_key(first, "testclient"),
        network_spend_key(second, "not-an-address"),
    }

    assert len(keys) == 1
    (unidentified,) = keys
    assert unidentified not in {_account_of(first), _account_of(second)}
    assert network_spend_key(first, NET_A) != unidentified


def test_spend_key_for_is_one_key_per_network_for_every_anonymous_session() -> None:
    """Decision 1, at the unit. RED-IF two anonymous sessions on one network get
    different keys, two networks share one, an IPv6 /64 is split, or a mapped
    address is not its IPv4. Partners: the inequalities (NET_A vs NET_B, one
    /64 vs the next) hold, so equality is not trivially everything-equal."""
    first, second = TestClient(app), TestClient(app)
    _boot(first)
    _boot(second)

    a = network_spend_key(first, NET_A)

    assert network_spend_key(second, NET_A) == a
    assert network_spend_key(second, NET_A_MAPPED) == a
    assert network_spend_key(first, NET_B) != a
    assert network_spend_key(first, V6_SAME_1) == network_spend_key(second, V6_SAME_2)
    assert network_spend_key(first, V6_SAME_1) != network_spend_key(first, V6_OTHER)
    assert a not in {_account_of(first), _account_of(second)}


# --- 4. no address is stored, and the key is keyed (row 2) -------------------------------


def test_the_network_key_is_keyed_by_the_server_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 1. RED-IF the key is an unkeyed function of the address (anyone
    could compute every network's key, or confirm a guessed address), is not
    deterministic for one secret and one network, or is the SIGNED-IN
    derivation of the same text (decision 1 asks for a W47-only prefix: a
    network must never share a key with a Google subject)."""
    first, second = TestClient(app), TestClient(app)
    _boot(first)
    _boot(second)
    monkeypatch.setenv("QUORUM_TOKEN_SECRET", "w47-secret-one-" + "a" * 32)
    under_one = network_spend_key(first, NET_A)
    same_again = network_spend_key(second, NET_A)
    monkeypatch.setenv("QUORUM_TOKEN_SECRET", "w47-secret-two-" + "b" * 32)
    under_two = network_spend_key(first, NET_A)

    assert same_again == under_one
    assert under_two != under_one
    assert under_one != session_store.account_id_for(
        NET_A, key=("w47-secret-one-" + "a" * 32).encode()
    )


def _rows_holding(store: FeedbackStore, recorder: str, needles: tuple[str, ...]) -> list[str]:
    """Each event of ``recorder`` whose account id or payload text holds any needle."""
    found: list[str] = []
    for event in store.iter_events(recorders=[recorder]):
        text = f"{event.account_id} {json.dumps(event.payload, default=str)}"
        found.extend(f"{event.event_type}: {needle}" for needle in needles if needle in text)
    return found


def test_no_cost_ledger_row_holds_the_visitors_address() -> None:
    """Decision 5 / row 2. RED-IF any cost-ledger row (charge or preview) holds
    the address or the /64 in its account id or payload -- the "key on the raw
    address" alternative ADR-0144 rejects. Positive partners: the SAME scan
    finds those very strings in the session-mint rows (ADR-0132 stores the
    network there), so the needles are the form the app writes; and the cost
    rows exist -- exactly one charge per network, under a key that is neither
    session's id (red today: it is the session's id)."""
    v4, v6 = "198.51.100.77", "2001:db8:77:1::5"
    needles = (v4, v6, "2001:db8:77:1::/64", "2001:db8:77:1:")
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        runs: list[tuple[QueryRun, UUID]] = []
        for host in (v4, v6):
            client = _browser(host)
            csrf = _boot(client)
            _estimate(client, csrf)
            runs.append((_run(client, csrf, semaphore), _account_of(client)))

        in_cost_rows = _rows_holding(store, "cost", needles)
        in_session_rows = _rows_holding(store, "session", needles)

        assert any(v4 in hit for hit in in_session_rows), in_session_rows
        assert any("2001:db8:77:1::/64" in hit for hit in in_session_rows), in_session_rows
        for run, account in runs:
            assert run.spend_key != account
            assert _charge_rows(store, _key(run)) == 1
        assert in_cost_rows == []


# --- 5. a run keeps the key it was created with (row 9) ----------------------------------


def test_a_runs_charge_void_and_reconcile_stay_on_the_network_it_was_created_on() -> None:
    """Decision 4. A browser starts a run on network A, then the SAME session
    (same cookie) moves to network B and starts another. RED-IF the second run
    is keyed like the first (today both are the session's id), or voiding or
    reconciling the first run moves network B's ledger. The ledger reconciles
    only a LIVE charge, so the reconcile half opens one under the first run's
    key, as tests/integration/test_spend_key.py does."""
    with configure_for_tests() as ledger, isolated_run_semaphore(1) as semaphore:
        on_a = _browser(NET_A)
        first = _run(on_a, _boot(on_a), semaphore)
        on_b = _browser(NET_B)
        # The same cookie, with its own domain and path, into an EMPTY jar (a
        # bare ``set`` beside a server-set cookie would send two).
        (cookie,) = [c for c in on_a.cookies.jar if c.name == COOKIE]
        on_b.cookies.set(COOKIE, cookie.value or "", domain=cookie.domain, path=cookie.path)
        assert _account_of(on_b) == _account_of(on_a)
        second = _run(on_b, _boot(on_b), semaphore)
        key_a, key_b = _key(first), _key(second)
        assert key_a != key_b
        assert ledger.daily_spend_for(key_a) == UNIT
        assert ledger.daily_spend_for(key_b) == UNIT

        qro._void_run_billing(session=None, query_run=first, reason="test")  # type: ignore[arg-type]
        assert ledger.daily_spend_for(key_a) == Decimal("0")
        assert ledger.daily_spend_for(key_b) == UNIT

        live = query_run_repository.create(
            account_id=first.account_id,
            spend_key=key_a,
            query_text=QUERY,
            model_slots=first.model_slots,
            cost_estimate=first.cost_estimate,
        )
        outcome = ledger.try_record_cost_charge(
            account_id=key_a,
            query_run_id=live.query_run_id,
            estimated_cost_usd=Decimal("0.0500"),
            payload={"account_id": str(key_a), "estimated_cost_usd": "0.0500"},
            daily_cap_usd=Decimal("0.40"),
            global_ceiling_usd=Decimal("50.00"),
            live_execution=True,
        )
        assert outcome.value == "recorded"
        qro._reconcile_run_billing(
            query_run=live,
            response=SimpleNamespace(cost_source="measured", actual_cost_usd=Decimal("0.0123")),  # type: ignore[arg-type]
        )

        assert ledger.daily_spend_for(key_a) == Decimal("0.0123")
        assert ledger.daily_spend_for(key_b) == UNIT


# --- 6. two sessions at the same moment (row 8, rule 6b) ---------------------------------


def test_two_concurrent_runs_on_one_network_cannot_together_pass_the_daily_cap() -> None:
    """Row 8. The network has spent $0.2104; two sessions on it each pass the
    estimate ($0.2104 + $0.1052 fits) and are held at the charge until BOTH
    have arrived. RED-IF both are charged (today: two keys, two 202s,
    $0.4208 between them) -- exactly one may be. Cardinality: two charge
    attempts, both under ONE key; three charge rows in all; the refusal is the
    charge-time ``daily_cap`` 402 with the network's allowance."""
    real = cost_estimation_service.try_record_run_charge
    barrier = threading.Barrier(2)
    attempts: list[UUID] = []

    def held(**kwargs: Any) -> Any:
        attempts.append(kwargs["account_id"])
        barrier.wait(timeout=20)
        return real(**kwargs)

    with configure_for_tests() as store, isolated_run_semaphore(2) as semaphore:
        spender = _browser(NET_A)
        spender_csrf = _boot(spender)
        key = _key(_run(spender, spender_csrf, semaphore, permits=2))
        _run(spender, spender_csrf, semaphore, permits=2)
        racers = [_browser(NET_A), _browser(NET_A)]
        tokens = [_boot(client) for client in racers]
        responses: list[Any] = [None, None]

        def race(index: int) -> None:
            responses[index] = racers[index].post(
                RUNS, json=acknowledged_request(QUERY), headers={"X-CSRF-Token": tokens[index]}
            )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(cost_estimation_service, "try_record_run_charge", held)
            threads = [threading.Thread(target=race, args=(i,)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
        assert wait_for_free_permits(semaphore, 2) == 2

        statuses = sorted(response.status_code for response in responses)
        assert attempts == [key, key]
        assert statuses == [202, 402], [response.text for response in responses]
        (refused,) = [response for response in responses if response.status_code == 402]
        detail = refused.json()["detail"]
        assert detail["block_reason"] == "daily_cap"
        assert detail["daily_allowance"]["shared_by_network"] is True
        assert detail["daily_allowance"]["spent_usd"] == "0.3156"
        assert _charge_rows(store, key) == 3
        assert store.daily_spend_for(key) == Decimal("0.3156")


# --- 7. the flag the page words the allowance from (decision 6) ---------------------------


def test_the_allowance_says_whether_it_is_shared_by_the_network(sign_in: SignIn) -> None:
    """RED-IF ``daily_allowance`` has no ``shared_by_network``, or it is not
    exactly ``true`` for an anonymous session and ``false`` for a signed-in
    account and for the legacy header (decision 3: those keep their own key).
    ``is True`` / ``is False``, not truthiness: a string or null fails."""
    with configure_for_tests():
        anonymous = _browser(NET_A)
        anonymous_allowance = _allowance(_estimate(anonymous, _boot(anonymous)))
        account = _browser(NET_A)
        csrf = _sign_in(account, sign_in, "108000000000000047005", "w47-flag@example.com")
        account_allowance = _allowance(_estimate(account, csrf))
        legacy = TestClient(app, client=(NET_A, 50000))
        response = legacy.post(
            ESTIMATE,
            json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
            headers={"X-Account-Id": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        legacy_allowance = _allowance(response.json()["cost_estimate"])

    assert anonymous_allowance.get("shared_by_network", "MISSING") is True
    assert account_allowance.get("shared_by_network", "MISSING") is False
    assert legacy_allowance.get("shared_by_network", "MISSING") is False


def test_with_no_session_store_anonymous_sessions_still_share_the_networks_allowance() -> None:
    """Today ``spend_key_for`` uses the session's id whenever there is no
    session store. RED-IF that path still gives each anonymous session its own
    $0.40. Partner: the first session's charge is on the ledger."""
    session_store.configure(None)  # restored by conftest's _isolated_session_store
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        first = _browser(NET_A)
        run = _run(first, _boot(first), semaphore)
        second = _browser(NET_A)
        seen = _estimate(second, _boot(second))

        assert _charge_rows(store, _key(run)) == 1
        assert _allowance(seen) == _allowance_dict("0.1052", "0.2948", shared=True)


# --- 8. the LOCAL-only override for the e2e lanes (decision 7) ----------------------------
#
# ``ANONYMOUS_SPEND_PER_SESSION_OVERRIDE`` (setting
# ``anonymous_spend_per_session_override``): with it on, and only in LOCAL,
# each anonymous session is its own network for spend; the allowance still
# reports ``shared_by_network: true``. Config guards (default off, blank,
# refused outside LOCAL): ``tests/unit/test_anonymous_spend_override.py``.


def test_the_override_is_off_in_this_suite() -> None:
    """The premise of every sharing test above: conftest blanks the variable,
    so a developer's shell or .env cannot turn them into per-session tests.
    RED-IF the setting is missing (today) or on here."""
    assert settings.anonymous_spend_per_session_override is False


def test_with_the_local_override_each_anonymous_session_has_its_own_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 7. RED-IF, with the override on in LOCAL, a second anonymous
    session on the same network sees the first one's spend (the e2e lanes
    would starve), or the flag stops saying the allowance is shared (the page
    copy must not change with a test switch). Partners: the override does not
    make spend free -- the first session's own estimate shows its $0.1052, and
    each session's run is charged exactly once under its own key."""
    assert settings.runtime_environment is RuntimeEnvironment.LOCAL
    monkeypatch.setattr(settings, "anonymous_spend_per_session_override", True)
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        first = _browser(NET_A)
        first_csrf = _boot(first)
        first_run = _run(first, first_csrf, semaphore)
        own = _estimate(first, first_csrf)
        second = _browser(NET_A)
        second_csrf = _boot(second)
        fresh = _estimate(second, second_csrf)
        second_run = _run(second, second_csrf, semaphore)

        assert _allowance(own) == _allowance_dict("0.1052", "0.2948", shared=True)
        assert _allowance(fresh) == ANON_FRESH
        assert _key(first_run) != _key(second_run)
        assert _charge_rows(store, _key(first_run)) == 1
        assert _charge_rows(store, _key(second_run)) == 1


def test_the_override_is_not_honoured_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt and braces behind the startup refusal, as
    ``_effective_session_mint_cap`` does for the mint cap: outside LOCAL the
    read path itself ignores the override. RED-IF two anonymous sessions on
    one network get different keys there. Partner: in LOCAL the same two
    sessions DO get different keys, so the equality is not a dead switch."""
    first, second = _browser(NET_A), _browser(NET_A)
    _boot(first)
    _boot(second)
    monkeypatch.setattr(settings, "anonymous_spend_per_session_override", True)

    local = (network_spend_key(first, NET_A), network_spend_key(second, NET_A))
    monkeypatch.setattr(settings, "runtime_environment", RuntimeEnvironment.PRODUCTION)
    deployed = (network_spend_key(first, NET_A), network_spend_key(second, NET_A))

    assert local[0] != local[1]
    assert deployed[0] == deployed[1]


def test_the_override_leaves_a_signed_in_account_on_its_own_spend_key(
    sign_in: SignIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decision 7 changes ANONYMOUS sessions only. RED-IF, with the override
    on, a signed-in account's run is keyed per session (its id, or a session
    hash) instead of its account's spend key, so signing in on another device
    would open a fresh $0.40."""
    monkeypatch.setattr(settings, "anonymous_spend_per_session_override", True)
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        account = _browser(NET_A)
        csrf = _sign_in(account, sign_in, "108000000000000047006", "w47-override@example.com")
        run = _run(account, csrf, semaphore)

        assert _key(run) == _account_spend_key(sign_in, account)
        assert _charge_rows(store, _key(run)) == 1


# --- 9. the accounts table cannot be read (ADR-0136's SPEND_KEY_UNAVAILABLE) -------------


def test_an_anonymous_session_is_refused_when_the_accounts_table_cannot_be_read(
    sign_in: SignIn,
) -> None:
    """A GUARD, green today by design: today ``spend_key_for`` reads the
    accounts row for every session and refuses (503) when it cannot. The W47
    build must keep that order -- whether a session is anonymous is itself a
    read of that table, and guessing "anonymous" on a failed read would meter
    a signed-in account under the network. RED-IF an anonymous session on an
    unreadable table is estimated or charged instead of refused with 503
    ``SPEND_KEY_UNAVAILABLE``. Partners: the same session's estimate is served
    before the table breaks, and nothing at all is charged."""
    with configure_for_tests() as store:
        client = _browser(NET_A)
        csrf = _boot(client)
        before = client.post(
            ESTIMATE,
            json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
            headers={"X-CSRF-Token": csrf},
        )
        sign_in.store._conn.execute("ALTER TABLE accounts RENAME TO accounts_gone")  # noqa: SLF001
        estimate = client.post(
            ESTIMATE,
            json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
            headers={"X-CSRF-Token": csrf},
        )
        created = client.post(
            RUNS, json=acknowledged_request(QUERY), headers={"X-CSRF-Token": csrf}
        )
        charges = [
            event
            for event in store.iter_events(recorders=["cost"])
            if event.event_type in CHARGE_TYPES
        ]

    assert before.status_code == 200, before.text
    for refused in (estimate, created):
        assert refused.status_code == 503, refused.text
        assert refused.json()["detail"]["code"] == "SPEND_KEY_UNAVAILABLE"
    assert charges == []
