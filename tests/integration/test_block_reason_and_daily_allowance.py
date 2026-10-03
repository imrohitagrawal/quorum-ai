"""W33 slice C (ADR-0141): a blocked run names the limit it hit, and the
estimate shows the allowance left.

Written BEFORE the code, against the real routes (TestClient, live execution
off, the pinned static catalog). Each test names, in its docstring, the change
that turns it red. The failure-mode rows cited are the numbered rows of
``docs/analysis/2026-10-03-w33c-limit-messages-failure-modes.md``.

THE WIRE FORMAT THIS FILE PINS (the ADR says "decimal strings" and leaves the
places open; these are the choices, made here so the builder has one target):

* ``cost_estimate.block_reason``: one of ``"per_run_cap"``,
  ``"account_running_total"``, ``"ledger_unavailable"``, ``"daily_cap"``, or
  JSON ``null`` when ``threshold_action`` is not ``"block"``. The key is always
  present.
* ``cost_estimate.daily_allowance``: an object with EXACTLY four keys, or JSON
  ``null``. ``cap_usd`` is the daily cap as the constant prints it, ``"0.40"``.
  ``spent_usd`` and ``remaining_usd`` always carry FOUR decimal places — the
  same ``COST_DISPLAY_QUANTUM`` as ``estimated_cost_usd`` and the existing
  "Account has spent 0.0000 USD" reason — so a fresh session reads
  ``{"cap_usd": "0.40", "spent_usd": "0.0000", "remaining_usd": "0.4000",
  "bounded_by": "daily_cap"}`` and a clamped one reads ``"remaining_usd":
  "0.0000"``. ``bounded_by`` (review round 1) is ``"daily_cap"`` or
  ``"running_total"``: which limit set the remaining figure. The running total
  sets it only when ``0.50 - total`` is STRICTLY smaller than ``0.40 - spent``.
  Four places, not two, because decision 5 has the PAGE round spent up and
  remaining down, which needs the unrounded figure.
* The charge-time ``OVER_DAILY_CAP`` 402 carries ``detail.block_reason`` and
  ``detail.daily_allowance`` (top level of ``detail``; that body has no
  ``cost_estimate``).

Every dollar figure below is a literal (rule 7a): the cap is ``"0.40"`` and the
running limit ``"0.50"``, never ``DAILY_CAP_USD`` / ``HARD_LIMIT_USD``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.google_token_stub import good_claims
from tests.helpers import isolated_run_semaphore, scoped_events, wait_for_free_permits
from tests.integration.test_google_sign_in import SignIn, _boot, _signed_in
from tests.integration.test_query_run_cost_guardrails import (
    BLOCKED_MODEL_IDS,
    CONFIRM_MODEL_IDS,
    CONFIRM_QUERY,
    DEFAULT_MODEL_IDS,
    _stable_catalog_price,  # noqa: F401 -- a fixture, used by name below
    acknowledged_request,
)
from tests.integration.test_session_cap_sign_in import (
    OTHER,
    Network,
    _sign_in_only,
    net,  # noqa: F401 -- a fixture, used by name below
)

from product_app import auth, store_reconnect
from product_app.config import settings
from product_app.costs import CostThresholdAction, cost_estimation_service, cost_event_recorder
from product_app.feedback_store import (
    COST_ACCEPTED_EVENT,
    COST_ACCEPTED_SIMULATED_EVENT,
    ChargeOutcome,
    FeedbackStore,
    configure_for_tests,
)
from product_app.main import app
from product_app.model_slots import validate_model_slots
from product_app.query_runs import query_run_repository

pytestmark = pytest.mark.usefixtures("_stable_catalog_price")

ESTIMATE = "/v1/query-runs/estimate"
RUNS = "/v1/query-runs"
SIGN_OUT = "/v1/auth/sign-out"
QUERY = "Compare these answers"
#: Under the pinned catalog: point 0.3360, worst case 0.5315 (measured
#: 2026-10-03) — above the $0.50 per-run cap, under the $0.40 daily cap alone.
PER_RUN_ONLY_QUERY = "x" * 2_000
#: Point 0.5115, worst case 0.5863 (measured 2026-10-03): BOTH the per-run cap
#: and, on an account that has spent nothing, the daily cap fire — failure-mode
#: row 2's shape (the design reviewer measured 0.4628 / 0.6109 at 12,000).
BOTH_CAPS_QUERY = "x" * 8_000
FRESH = {
    "cap_usd": "0.40",
    "spent_usd": "0.0000",
    "remaining_usd": "0.4000",
    "bounded_by": "daily_cap",
}
CHARGE_TYPES = frozenset({COST_ACCEPTED_EVENT, COST_ACCEPTED_SIMULATED_EVENT})


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    query_run_repository.clear()
    yield
    query_run_repository.clear()


# --- helpers --------------------------------------------------------------------------


def _legacy(account: UUID) -> dict[str, str]:
    return {"X-Account-Id": str(account)}


def _post_estimate(
    client: TestClient,
    headers: dict[str, str],
    *,
    models: list[str] | None = None,
    query: str = QUERY,
) -> dict[str, Any]:
    response = client.post(
        ESTIMATE,
        json={"query_text": query, "model_slots": models or DEFAULT_MODEL_IDS},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _block_reason(cost_estimate: dict[str, Any]) -> Any:
    assert "block_reason" in cost_estimate, (
        f"cost_estimate has no block_reason; keys: {sorted(cost_estimate)}"
    )
    return cost_estimate["block_reason"]


def _allowance(holder: dict[str, Any]) -> Any:
    assert "daily_allowance" in holder, f"no daily_allowance; keys: {sorted(holder)}"
    return holder["daily_allowance"]


def _money(value: Decimal) -> str:
    """Four places, the wire format this file pins."""
    return str(value.quantize(Decimal("0.0001")))


def _book(store: FeedbackStore, key: UUID, amount: str, *, age: timedelta | None = None) -> None:
    """One opening charge on the durable ledger only (not the in-memory ring),
    as another tab or an earlier process life would have left it. No cap check:
    a reconciled live run can sit above the cap (failure-mode row 10)."""
    assert store.record(
        recorder="cost",
        event_type=COST_ACCEPTED_SIMULATED_EVENT,
        account_id=key,
        query_run_id=uuid4(),
        recorded_at=datetime.now(UTC) - (age or timedelta(0)),
        payload={"account_id": str(key), "estimated_cost_usd": amount},
    )


def _ring(key: UUID, amount: str) -> None:
    """One opening charge on the in-memory ring only (the running-total rail)."""
    assert cost_event_recorder is not None
    cost_event_recorder.record(
        event_type=COST_ACCEPTED_SIMULATED_EVENT,
        account_id=key,
        query_run_id=uuid4(),
        estimated_cost_usd=Decimal(amount),
        threshold_action=CostThresholdAction.ALLOW,
        confirmed=False,
        persist=False,
    )


def _rows(store: FeedbackStore, key: UUID) -> list[str]:
    """Event types of every durable cost row for ``key``, in order."""
    return [
        event.event_type
        for event in store.iter_events(recorders=["cost"])
        if event.account_id == str(key)
    ]


def _charge_rows(store: FeedbackStore, key: UUID) -> int:
    return sum(1 for event_type in _rows(store, key) if event_type in CHARGE_TYPES)


def _age_ledger(store: FeedbackStore, key: UUID, hours: int) -> None:
    """Move every ledger row of ``key`` back ``hours``, as the design reviewer
    did: the ledger forgets them, the in-memory ring (no window) does not."""
    stamp = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    with store._lock:  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "UPDATE events SET recorded_at = ? WHERE recorder = 'cost' AND account_id = ?",
            (stamp, str(key)),
        )
        store._conn.commit()  # noqa: SLF001


def _legacy_run(client: TestClient, account: UUID) -> Decimal:
    """One simulated run on the legacy path (runs inline); returns its charge."""
    created = client.post(RUNS, json=acknowledged_request(QUERY), headers=_legacy(account))
    assert created.status_code == 202, created.text
    return Decimal(created.json()["cost_estimate"]["estimated_cost_usd"])


def _cookie_run(client: TestClient, csrf: str, semaphore: Any) -> Decimal:
    """One simulated run on the cookie path, waited out (it runs on a thread)."""
    created = client.post(RUNS, json=acknowledged_request(QUERY), headers={"X-CSRF-Token": csrf})
    assert created.status_code == 202, created.text
    assert wait_for_free_permits(semaphore, 1) == 1
    return Decimal(created.json()["cost_estimate"]["estimated_cost_usd"])


def _ledger_reads(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Record every ``FeedbackStore.daily_spend_for`` call (the ledger read)."""
    calls: list[UUID] = []
    real = FeedbackStore.daily_spend_for

    def spy(self: FeedbackStore, account_id: UUID, **kwargs: Any) -> Decimal:
        calls.append(account_id)
        return real(self, account_id, **kwargs)

    monkeypatch.setattr(FeedbackStore, "daily_spend_for", spy)
    return calls


def _no_background_reconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_reconnect, "maybe_reconnect_feedback_store", lambda: None)
    monkeypatch.setattr(store_reconnect, "maybe_reconnect_run_history_store", lambda: None)


def _ledger_condemned(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fail-closed setting on, a reopen already tried, the ledger not
    trustworthy: the ``ledger_unavailable`` block (issue #122)."""
    _no_background_reconnects(monkeypatch)
    monkeypatch.setattr(settings, "daily_cap_fail_closed", True)
    monkeypatch.setattr(store_reconnect, "feedback_reopen_tried_without_recovery", lambda: True)
    monkeypatch.setattr(store_reconnect, "feedback_ledger_is_trustworthy", lambda _store: False)


def _sign_in_as(sign_in: SignIn, sub: str, email: str) -> TestClient:
    """A browser signed in as its OWN Google subject (the spend key derives
    from it, so two tests sharing a subject would share an envelope)."""
    sign_in.stub.claims = good_claims(sub=sub, email=email)
    client = sign_in.client()
    assert _signed_in(client).status_code in (302, 303, 307)
    return client


def _account_of(client: TestClient) -> UUID:
    session = auth.session_repository.get(client.cookies["quorum_session"])
    assert session is not None, "the cookie does not resolve"
    return session.account_id


def _spend_key_of(client: TestClient, sign_in: SignIn | None = None) -> UUID:
    """The key this browser's runs are metered under: the account id for an
    anonymous session, the account row's spend key once signed in (ADR-0136)."""
    account = _account_of(client)
    if sign_in is None:
        return account
    rows = sign_in.account_rows()
    (key,) = [UUID(row["spend_key"]) for row in rows if row["account_id"] == str(account)]
    return key


# --- 1. block_reason, one kind at a time --------------------------------------------


def test_a_non_blocking_estimate_has_a_null_block_reason() -> None:
    """RED-IF: ``block_reason`` is missing from the estimate, or is set on an
    ALLOW or REQUIRE_CONFIRMATION estimate. Partner: both bands really are the
    bands named (green today)."""
    client = TestClient(app)
    allow = _post_estimate(client, _legacy(uuid4()))["cost_estimate"]
    confirm = _post_estimate(
        client, _legacy(uuid4()), models=CONFIRM_MODEL_IDS, query=CONFIRM_QUERY
    )["cost_estimate"]

    assert allow["threshold_action"] == "allow"
    assert confirm["threshold_action"] == "require_confirmation"
    assert _block_reason(allow) is None
    assert _block_reason(confirm) is None


def test_the_per_run_cap_names_itself() -> None:
    """RED-IF: a worst case above $0.50 on an account that has spent nothing
    is not labelled ``per_run_cap`` (failure-mode row 13: the real case must
    keep its label). The price comes from the pinned catalog's opus-tier rows,
    not a lowered constant (rule 7a). Partner: the premise — worst case above
    0.50, point under 0.40 — holds today."""
    client = TestClient(app)
    estimate = _post_estimate(
        client, _legacy(uuid4()), models=BLOCKED_MODEL_IDS, query=PER_RUN_ONLY_QUERY
    )["cost_estimate"]

    assert Decimal(estimate["max_cost_usd"]) > Decimal("0.50")
    assert Decimal(estimate["estimated_cost_usd"]) < Decimal("0.40")
    assert estimate["threshold_action"] == "block"
    assert _block_reason(estimate) == "per_run_cap"


def test_the_daily_cap_names_itself_for_an_anonymous_session() -> None:
    """RED-IF: the fourth default-panel run of an anonymous (cookie) session,
    after three simulated runs, is blocked without ``block_reason ==
    "daily_cap"``. Partner (green today): exactly three runs were admitted and
    charged, and the fourth estimate blocks."""
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        client = TestClient(app)
        csrf = _boot(client)
        key = _spend_key_of(client)
        charges = [_cookie_run(client, csrf, semaphore) for _ in range(3)]

        estimate = _post_estimate(client, {"X-CSRF-Token": csrf})["cost_estimate"]

        assert _charge_rows(store, key) == 3
        assert store.daily_spend_for(key) == sum(charges)
        assert estimate["threshold_action"] == "block"
        assert _block_reason(estimate) == "daily_cap"


def test_the_daily_cap_names_itself_for_a_signed_in_session(sign_in: SignIn) -> None:
    """RED-IF: the same block for a signed-in account (metered under its spend
    key, not its id) is not labelled ``daily_cap``. Partner (green today): the
    three charges sit under the spend key."""
    with configure_for_tests() as store, isolated_run_semaphore(1) as semaphore:
        client = _sign_in_as(sign_in, "108000000000000033301", "w33c-daily@example.com")
        csrf = _boot(client)
        key = _spend_key_of(client, sign_in)
        for _ in range(3):
            _cookie_run(client, csrf, semaphore)

        estimate = _post_estimate(client, {"X-CSRF-Token": csrf})["cost_estimate"]

        assert _charge_rows(store, key) == 3
        assert estimate["threshold_action"] == "block"
        assert _block_reason(estimate) == "daily_cap"


def test_the_running_total_names_itself() -> None:
    """RED-IF: a block by the in-memory running total is not labelled
    ``account_running_total``. Reached the way production reaches it: three
    runs, their ledger rows aged past 24 hours (the ring has no window), one
    more run — ledger 1 run, ring 4 runs. Partner (green today): the ledger is
    under its cap, so only the running total can be what fired."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        unit = _legacy_run(client, account)
        _legacy_run(client, account)
        _legacy_run(client, account)
        _age_ledger(store, account, hours=25)
        _legacy_run(client, account)

        estimate = _post_estimate(client, _legacy(account))["cost_estimate"]

        assert store.daily_spend_for(account) == unit
        assert unit + unit <= Decimal("0.40")
        assert cost_estimation_service._cumulative_spend_for(account) == 4 * unit  # noqa: SLF001
        assert 4 * unit + unit > Decimal("0.50")
        assert estimate["threshold_action"] == "block"
        assert _block_reason(estimate) == "account_running_total"


def test_a_condemned_ledger_names_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-IF: the fail-closed ledger block (setting on, reopen tried, ledger
    untrustworthy) is not labelled ``ledger_unavailable``, or its allowance is
    not ``null`` (a figure off a ledger nobody can trust is invented,
    failure-mode row 5). Partner (green today): it is the storage-fault
    block."""
    _ledger_condemned(monkeypatch)
    client = TestClient(app)

    estimate = _post_estimate(client, _legacy(uuid4()))["cost_estimate"]

    assert estimate["threshold_action"] == "block"
    assert any("storage fault" in reason for reason in estimate["reasons"])
    assert _block_reason(estimate) == "ledger_unavailable"
    assert _allowance(estimate) is None


# --- 2. both caps at once (decision 1) -----------------------------------------------


def test_the_per_run_cap_wins_over_the_daily_cap_and_keeps_its_reason() -> None:
    """RED-IF: a run whose worst case is above $0.50 AND would cross the daily
    cap is labelled ``daily_cap`` (the user is told to wait for a run that can
    never start, failure-mode row 2), or loses the per-run reason text. The
    per-run text is taken from a per-run-only estimate of the same panel, so no
    sentence is pinned here. Partner (green today): both rails really fire."""
    client = TestClient(app)
    per_run_only = _post_estimate(
        client, _legacy(uuid4()), models=BLOCKED_MODEL_IDS, query=PER_RUN_ONLY_QUERY
    )["cost_estimate"]
    both = _post_estimate(
        client, _legacy(uuid4()), models=BLOCKED_MODEL_IDS, query=BOTH_CAPS_QUERY
    )["cost_estimate"]

    assert Decimal(both["max_cost_usd"]) > Decimal("0.50")
    assert Decimal(both["estimated_cost_usd"]) > Decimal("0.40")
    assert _block_reason(both) == "per_run_cap"
    assert set(per_run_only["reasons"]) <= set(both["reasons"]), both["reasons"]


def test_the_per_run_cap_wins_over_the_running_total() -> None:
    """RED-IF: a worst case above $0.50 on an account whose running total also
    fires is labelled ``account_running_total`` ("whatever else also fires",
    decision 1). Partner (green today): the ring alone would block."""
    client = TestClient(app)
    account = uuid4()
    _ring(account, "0.4000")

    estimate = _post_estimate(
        client, _legacy(account), models=BLOCKED_MODEL_IDS, query=PER_RUN_ONLY_QUERY
    )["cost_estimate"]

    assert Decimal("0.4000") + Decimal(estimate["estimated_cost_usd"]) > Decimal("0.50")
    assert _block_reason(estimate) == "per_run_cap"


# --- 3. daily_allowance (decision 2) -------------------------------------------------


def test_a_fresh_session_has_the_whole_allowance() -> None:
    """RED-IF: the estimate carries no ``daily_allowance``, or a fresh session's
    is anything but exactly the four strings pinned in the module docstring."""
    with configure_for_tests():
        client = TestClient(app)
        csrf = _boot(client)
        estimate = _post_estimate(client, {"X-CSRF-Token": csrf})["cost_estimate"]

        assert _allowance(estimate) == FRESH


def test_the_allowance_falls_by_exactly_the_runs_charged() -> None:
    """RED-IF: remaining is not 0.40 minus the sum of EXACTLY the n charges
    (rule 6b: a charge counted twice, or a preview counted as one, moves it).
    Cardinality partner (green today): exactly n charge rows on the ledger."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        charges = [_legacy_run(client, account) for _ in range(2)]

        estimate = _post_estimate(client, _legacy(account))["cost_estimate"]

        assert _charge_rows(store, account) == 2
        spent = sum(charges, Decimal("0"))
        assert _allowance(estimate) == {
            "cap_usd": "0.40",
            "spent_usd": _money(spent),
            "remaining_usd": _money(Decimal("0.40") - spent),
            "bounded_by": "daily_cap",
        }
        # Spelled out once at today's unit price, so the arithmetic above is
        # checked against a literal too (0.1052 per run, pinned elsewhere).
        assert charges == [Decimal("0.1052"), Decimal("0.1052")]
        assert estimate["daily_allowance"]["remaining_usd"] == "0.1896"


def test_the_allowance_is_clamped_at_zero_when_spend_exceeds_the_cap() -> None:
    """RED-IF: a ledger above the cap (a live run reconciled above its
    estimate, failure-mode row 10) shows a negative remainder, or the block is
    not ``daily_cap``. Partner (green today): the estimate blocks."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        _book(store, account, "0.4500")

        estimate = _post_estimate(client, _legacy(account))["cost_estimate"]

        assert estimate["threshold_action"] == "block"
        assert _block_reason(estimate) == "daily_cap"
        assert _allowance(estimate) == {
            "cap_usd": "0.40",
            "spent_usd": "0.4500",
            "remaining_usd": "0.0000",
            "bounded_by": "daily_cap",
        }


def test_the_running_total_lowers_the_remainder_when_it_is_the_smaller_rail() -> None:
    """RED-IF: the allowance reads the ledger alone when the in-memory total is
    above 0 and 0.50 - total < 0.40 - ledger (failure-mode row 3: "$0.29 left"
    while the server blocks). Three runs, ledger rows aged 25 h: ledger 0, ring
    0.3156, so remaining is 0.50 - 0.3156 = 0.1844, and spent stays the ledger's
    0.0000. Before the ageing the ledger is the smaller rail (0.0844)."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        for _ in range(3):
            _legacy_run(client, account)
        before = _post_estimate(client, _legacy(account))["cost_estimate"]
        _age_ledger(store, account, hours=25)

        after = _post_estimate(client, _legacy(account))["cost_estimate"]

        assert store.daily_spend_for(account) == Decimal("0")
        assert after["threshold_action"] == "allow"
        assert _allowance(before) == {
            "cap_usd": "0.40",
            "spent_usd": "0.3156",
            "remaining_usd": "0.0844",
            "bounded_by": "daily_cap",
        }
        assert _allowance(after) == {
            "cap_usd": "0.40",
            "spent_usd": "0.0000",
            "remaining_usd": "0.1844",
            "bounded_by": "running_total",
        }


def test_the_lowered_remainder_is_clamped_at_zero_too() -> None:
    """RED-IF: a running total above 0.50 gives a negative remainder (the clamp
    must cover the lowered branch as well as the ledger one). Partner (green
    today): the estimate blocks on the running total."""
    with configure_for_tests():
        client = TestClient(app)
        account = uuid4()
        _ring(account, "0.5500")

        estimate = _post_estimate(client, _legacy(account))["cost_estimate"]

        assert estimate["threshold_action"] == "block"
        assert _allowance(estimate) == {
            "cap_usd": "0.40",
            "spent_usd": "0.0000",
            "remaining_usd": "0.0000",
            "bounded_by": "running_total",
        }


def test_the_allowance_is_null_when_the_ledger_cannot_be_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: the ADR-0016 degrade path (ledger not meterable, run simulated)
    shows an allowance instead of ``null`` (failure-mode row 5), or sets a
    ``block_reason`` (it does not block). Partner: the same request on a
    meterable ledger has an allowance, and the degrade flag is set (green)."""
    client = TestClient(app)
    metered = _post_estimate(client, _legacy(uuid4()))["cost_estimate"]
    _no_background_reconnects(monkeypatch)
    monkeypatch.setattr(store_reconnect, "feedback_ledger_may_be_metered", lambda _store: False)

    degraded = _post_estimate(client, _legacy(uuid4()))["cost_estimate"]

    assert degraded["spend_metering_unavailable"] is True
    assert degraded["threshold_action"] == "allow"
    assert _allowance(metered) == FRESH
    assert _allowance(degraded) is None
    assert _block_reason(degraded) is None


def test_an_estimate_with_no_spend_key_has_a_null_allowance() -> None:
    """RED-IF: ``CostEstimationService.estimate`` called with neither an account
    nor a spend key (no route does this — both pass ``spend_key_for(session)``
    — but the service accepts it) reports an allowance for nobody. Partner:
    the same call with a key has one."""
    slots = validate_model_slots(DEFAULT_MODEL_IDS)
    with configure_for_tests():
        keyless = cost_estimation_service.estimate(query_text=QUERY, model_slots=slots)
        keyed = cost_estimation_service.estimate(
            query_text=QUERY, model_slots=slots, account_id=uuid4()
        )

    assert keyless.model_dump(mode="json").get("daily_allowance", "MISSING") is None
    assert keyed.model_dump(mode="json").get("daily_allowance") == FRESH


# --- 4. privacy on a shared computer (failure-mode row 11) ----------------------------


def _leaks(text: str, *needles: object) -> list[str]:
    found: list[str] = []
    for needle in needles:
        forms = [str(needle)]
        if isinstance(needle, UUID):
            forms.append(needle.hex)
        found.extend(form for form in forms if form in text)
    return found


def test_after_sign_out_the_anonymous_allowance_is_fresh_and_names_nothing_of_the_account(
    sign_in: SignIn,
) -> None:
    """RED-IF: after an account spends and signs out, the next anonymous
    estimate's allowance is anything but fresh, or its body carries the
    account's spend figure, its remainder, its spend key or its account id.
    Positive partner: the account's OWN estimate shows its spend (so the
    figure the absence check looks for really is the one that would leak)."""
    with configure_for_tests() as store:
        client = _sign_in_as(sign_in, "108000000000000033302", "w33c-out@example.com")
        csrf = _boot(client)
        session = auth.session_repository.get(client.cookies["quorum_session"])
        assert session is not None
        account, key = session.account_id, _spend_key_of(client, sign_in)
        assert key != account
        _book(store, key, "0.3317")
        own = _post_estimate(client, {"X-CSRF-Token": csrf})

        assert client.post(SIGN_OUT, headers={"X-CSRF-Token": csrf}).status_code == 200
        anonymous_csrf = _boot(client)
        response = client.post(
            ESTIMATE,
            json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
            headers={"X-CSRF-Token": anonymous_csrf},
        )

        assert _allowance(own["cost_estimate"])["spent_usd"] == "0.3317"
        assert _leaks(response.text, key) == [], "the spend key went on the wire"
        assert _leaks(str(own), key) == [], "the spend key went on the wire"
        assert response.status_code == 200, response.text
        assert _allowance(response.json()["cost_estimate"]) == FRESH
        assert _leaks(response.text, "0.3317", "0.0683", key, account) == []


def test_after_sign_in_the_account_allowance_names_nothing_of_the_anonymous_session(
    sign_in: SignIn,
) -> None:
    """RED-IF: an anonymous session spends and then signs in, and the signed-in
    estimate shows the anonymous spend (or its remainder or id) instead of the
    account's own fresh envelope. Positive partner: the anonymous estimate
    showed that spend before signing in."""
    with configure_for_tests() as store:
        sign_in.stub.claims = good_claims(sub="108000000000000033303", email="w33c-in@example.com")
        client = sign_in.client()
        csrf = _boot(client)
        anonymous = auth.session_repository.get(client.cookies["quorum_session"])
        assert anonymous is not None
        _book(store, anonymous.account_id, "0.2917")
        before = _post_estimate(client, {"X-CSRF-Token": csrf})

        assert _signed_in(client).status_code in (302, 303, 307)
        signed_in_csrf = _boot(client)
        key = _spend_key_of(client, sign_in)
        response = client.post(
            ESTIMATE,
            json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
            headers={"X-CSRF-Token": signed_in_csrf},
        )

        assert _allowance(before["cost_estimate"])["spent_usd"] == "0.2917"
        assert response.status_code == 200, response.text
        assert _allowance(response.json()["cost_estimate"]) == FRESH
        assert _leaks(response.text, "0.2917", "0.1083", anonymous.account_id, key) == []


# --- 5. a read writes nothing (rule 6b, failure-mode rows 17 and 18) --------------------


def test_estimates_write_one_preview_each_and_read_the_ledger_once_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: reading the allowance writes anything (a charge row, a second
    preview), moves the allowance between identical reads, or reads the ledger
    more than once per estimate (decision 2: one read serves the block and the
    allowance). Cardinality partners (green today): N estimates leave exactly
    N preview rows and the one earlier charge."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        _legacy_run(client, account)
        rows_before = _rows(store, account)
        ring_before = len(scoped_events(cost_event_recorder, account_id=account))
        reads = _ledger_reads(monkeypatch)

        estimates = [_post_estimate(client, _legacy(account))["cost_estimate"] for _ in range(3)]

        assert reads == [account, account, account]
        rows_after = _rows(store, account)
        assert rows_after[: len(rows_before)] == rows_before
        assert rows_after[len(rows_before) :] == ["cost_estimate_previewed"] * 3
        assert _charge_rows(store, account) == 1
        assert len(scoped_events(cost_event_recorder, account_id=account)) == ring_before + 3
        allowances = [_allowance(estimate) for estimate in estimates]
        assert allowances[0] is not None
        assert allowances == [allowances[0]] * 3
        assert allowances[0]["remaining_usd"] == "0.2948"


# --- 6. the create route's two 402s (decision 3) ---------------------------------------


def _create_402(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(RUNS, json=acknowledged_request(QUERY), headers=headers)
    assert response.status_code == 402, response.text
    detail: dict[str, Any] = response.json()["detail"]
    assert detail["code"] == "COST_LIMIT_EXCEEDED"
    return detail


def test_the_create_routes_estimate_402_names_the_daily_cap() -> None:
    """RED-IF: the create route's re-run-estimate 402 for a daily block lacks
    ``cost_estimate.block_reason == "daily_cap"`` or its allowance, or its
    message still says "exceeds the hard ceiling" (failure-mode row 7).
    Partner (green today): it is that 402, and nothing was charged."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        _book(store, account, "0.3900")

        detail = _create_402(client, _legacy(account))

        assert _charge_rows(store, account) == 1
        assert detail["cost_estimate"]["threshold_action"] == "block"
        assert _block_reason(detail["cost_estimate"]) == "daily_cap"
        assert _allowance(detail["cost_estimate"]) == {
            "cap_usd": "0.40",
            "spent_usd": "0.3900",
            "remaining_usd": "0.0100",
            "bounded_by": "daily_cap",
        }
        assert "hard ceiling" not in detail["message"], detail["message"]


def test_the_create_402_message_is_worded_per_reason() -> None:
    """RED-IF: the create route gives a per-run block and a daily block the
    same message (decision 3: worded from the reason, not one sentence for
    all). Partner (green today): both are 402 COST_LIMIT_EXCEEDED blocks."""
    with configure_for_tests() as store:
        client = TestClient(app)
        daily_account = uuid4()
        _book(store, daily_account, "0.3900")
        daily = _create_402(client, _legacy(daily_account))
        per_run_response = client.post(
            RUNS,
            json=acknowledged_request(PER_RUN_ONLY_QUERY, BLOCKED_MODEL_IDS),
            headers=_legacy(uuid4()),
        )
        assert per_run_response.status_code == 402, per_run_response.text
        per_run = per_run_response.json()["detail"]

        assert _block_reason(per_run["cost_estimate"]) == "per_run_cap"
        assert daily["message"] != per_run["message"]


def _another_tab_charges_first(
    monkeypatch: pytest.MonkeyPatch, store: FeedbackStore, amount: str
) -> list[UUID]:
    """Book ``amount`` on the ledger between the create route's estimate and its
    charge, as a second tab of the same account would: the real atomic charge
    then refuses with ``OVER_DAILY_CAP``. Returns the keys it charged."""
    real: Callable[..., Any] = cost_estimation_service.try_record_run_charge
    keys: list[UUID] = []

    def first(**kwargs: Any) -> Any:
        keys.append(kwargs["account_id"])
        _book(store, kwargs["account_id"], amount)
        return real(**kwargs)

    monkeypatch.setattr(cost_estimation_service, "try_record_run_charge", first)
    return keys


def _assert_the_charge_time_402(detail: dict[str, Any], store: FeedbackStore, key: UUID) -> None:
    # The estimate this create ran said 0.0000 spent; only a FRESH read sees
    # the other tab's 0.3500.
    assert "cost_estimate" not in detail
    assert _charge_rows(store, key) == 1
    assert "hard ceiling" not in detail["message"], detail["message"]
    assert detail.get("block_reason", "MISSING") == "daily_cap"
    assert _allowance(detail) == {
        "cap_usd": "0.40",
        "spent_usd": "0.3500",
        "remaining_usd": "0.0500",
        "bounded_by": "daily_cap",
    }


def test_the_charge_time_402_names_the_daily_cap_and_reads_the_allowance_afresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: the cookie path's charge-time ``OVER_DAILY_CAP`` 402 lacks
    ``block_reason: "daily_cap"`` or a ``daily_allowance`` read AFTER the
    refused charge (failure-mode row 6). Partners (green today): the 402
    fires, exactly one charge row (the other tab's) and no run left active."""
    with configure_for_tests() as store, isolated_run_semaphore(1):
        client = TestClient(app)
        csrf = _boot(client)
        key = _spend_key_of(client)
        charged = _another_tab_charges_first(monkeypatch, store, "0.3500")

        detail = _create_402(client, {"X-CSRF-Token": csrf})

        assert charged == [key]
        assert query_run_repository.get_active_for_account(key) is None
        _assert_the_charge_time_402(detail, store, key)


def test_the_legacy_paths_charge_time_402_says_the_same(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: the legacy (inline) path's copy of the charge-time 402 is not
    changed with the cookie path's — the two are kept in step on purpose
    (``_start_reserved_query_run``). Partners as above."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        charged = _another_tab_charges_first(monkeypatch, store, "0.3500")

        detail = _create_402(client, _legacy(account))

        assert charged == [account]
        _assert_the_charge_time_402(detail, store, account)


# --- 7. wording (decisions 3 and 4) -----------------------------------------------------


def test_the_running_total_reason_says_what_fired() -> None:
    """RED-IF: the running-total block still says "Worst-case cost is above the
    USD 0.50 hard limit" (it is not the worst case that fired, failure-mode
    row 4). Partner (green today): the reasons still name the 0.50 figure, the
    running limit decision 4 says they must name."""
    client = TestClient(app)
    account = uuid4()
    _ring(account, "0.4500")

    estimate = _post_estimate(client, _legacy(account))["cost_estimate"]

    assert estimate["threshold_action"] == "block"
    assert any("0.50" in reason for reason in estimate["reasons"]), estimate["reasons"]
    assert not any("Worst-case cost is above" in reason for reason in estimate["reasons"]), (
        estimate["reasons"]
    )


def test_the_top_level_reasons_are_worded_per_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED-IF: the top-level ``reasons`` (``_estimate_reasons``) say "exceeds
    USD 0.50" for a daily-cap or ledger block, or give the running-total block
    the per-run copy. Asserted by figure, never by sentence (rule 8). Partner
    (green today): the per-run block's top-level reasons do name 0.50."""
    with configure_for_tests() as store:
        client = TestClient(app)
        per_run = _post_estimate(
            client, _legacy(uuid4()), models=BLOCKED_MODEL_IDS, query=PER_RUN_ONLY_QUERY
        )["reasons"]
        daily_account = uuid4()
        _book(store, daily_account, "0.3900")
        daily = _post_estimate(client, _legacy(daily_account))["reasons"]
        running_account = uuid4()
        _ring(running_account, "0.4500")
        running = _post_estimate(client, _legacy(running_account))["reasons"]
        _ledger_condemned(monkeypatch)
        ledger = _post_estimate(client, _legacy(uuid4()))["reasons"]

    assert any("USD 0.50" in reason for reason in per_run), per_run
    assert not any("0.50" in reason for reason in daily), daily
    assert any("0.40" in reason for reason in daily), daily
    assert not any("0.50" in reason for reason in ledger), ledger
    assert running != per_run, running


# --- 8. a sign-in-only session is refused before any allowance (ADR-0139) --------------


def test_a_sign_in_only_session_is_refused_before_the_ledger_is_read(
    net: Network,  # noqa: F811 -- the fixture imported above, requested by name
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: the estimate route reads the ledger (or returns an allowance) for
    a sign-in-only session before refusing it (failure-mode row 21). Partner:
    an ordinary session on another address is served WITH a fresh allowance
    and exactly one ledger read."""
    client, token = _sign_in_only(net)
    reads = _ledger_reads(monkeypatch)

    refused = client.post(
        ESTIMATE,
        json={"query_text": QUERY, "model_slots": DEFAULT_MODEL_IDS},
        headers={"X-CSRF-Token": token},
    )

    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["code"] == "SIGN_IN_REQUIRED"
    assert "daily_allowance" not in refused.text
    assert reads == []

    other = TestClient(app, client=(OTHER, 5))
    served = _post_estimate(other, {"X-CSRF-Token": _boot(other)})
    assert len(reads) == 1
    assert _allowance(served["cost_estimate"]) == FRESH


# --- review round 1 -------------------------------------------------------------------
#
# Rows 23-25 of the failure-mode list, ADR-0141 decisions 7, 8 and 2 (bounded_by).

#: Under the pinned catalog: point 0.4013, worst case 0.4278 (reproduced by the
#: round-1 reviewer, and asserted below as the premise): the run alone is above
#: the $0.40 daily cap while its worst case is under the $0.50 per-run cap.
LARGER_THAN_A_DAY_QUERY = "x" * 12_000
#: Wording that tells the person to wait. Matched as phrases, not sentences
#: (rule 8). "wait" alone is NOT here: decision 7's own message may say the run
#: will not fit "however long the person waits".
WAIT_PHRASES = ("frees up", "24 hours old", "window resets")


def _says_wait(texts: list[str]) -> list[str]:
    return [text for text in texts if any(phrase in text for phrase in WAIT_PHRASES)]


def test_a_run_larger_than_a_whole_day_is_not_told_to_wait() -> None:
    """RED-IF: a run whose estimate ALONE is above $0.40 (worst case not above
    $0.50, nothing spent) is labelled anything but ``daily_cap``, or any of its
    estimate reasons, top-level reasons or create-402 message tells the person
    that spend frees up (row 23, decision 7). Also red if its create message is
    the ordinary daily-cap message (decision 7 words it differently). Partner:
    the premise holds (point > 0.40, worst case <= 0.50, spent 0.0000)."""
    with configure_for_tests():
        client = TestClient(app)
        account = uuid4()
        body = _post_estimate(
            client, _legacy(account), models=CONFIRM_MODEL_IDS, query=LARGER_THAN_A_DAY_QUERY
        )
        estimate = body["cost_estimate"]
        created = client.post(
            RUNS,
            json=acknowledged_request(LARGER_THAN_A_DAY_QUERY, CONFIRM_MODEL_IDS),
            headers=_legacy(account),
        )
        ordinary_account = uuid4()
        for _ in range(3):
            _legacy_run(client, ordinary_account)
        ordinary = _create_402(client, _legacy(ordinary_account))

    assert Decimal(estimate["estimated_cost_usd"]) > Decimal("0.40")
    assert Decimal(estimate["max_cost_usd"]) <= Decimal("0.50")
    assert estimate["daily_allowance"]["spent_usd"] == "0.0000"
    assert _block_reason(estimate) == "daily_cap"
    assert created.status_code == 402, created.text
    detail = created.json()["detail"]
    assert detail["code"] == "COST_LIMIT_EXCEEDED"
    assert _says_wait(estimate["reasons"]) == []
    assert _says_wait(body["reasons"]) == []
    assert _says_wait([detail["message"]]) == []
    assert detail["message"] != ordinary["message"]


def test_an_ordinary_daily_block_still_says_it_frees_up() -> None:
    """Positive partner of the test above: the ordinary daily block (three runs,
    then a fourth) still says spend frees up as each run turns 24 hours old, in
    its estimate reasons and its create-402 message (decision 5's rule).
    RED-IF the fix for row 23 drops that wording from every daily block."""
    with configure_for_tests():
        client = TestClient(app)
        account = uuid4()
        for _ in range(3):
            _legacy_run(client, account)
        estimate = _post_estimate(client, _legacy(account))["cost_estimate"]
        detail = _create_402(client, _legacy(account))

    assert Decimal(estimate["estimated_cost_usd"]) <= Decimal("0.40")
    assert _block_reason(estimate) == "daily_cap"
    assert any("frees up" in reason and "24 hours old" in reason for reason in estimate["reasons"])
    assert "frees up" in detail["message"] and "24 hours old" in detail["message"]


class _FailingAllowanceRead:
    """Book ``amount`` between the create's estimate and its charge (another
    tab), let the REAL atomic charge refuse, and from then on make the ledger
    read (``FeedbackStore.daily_spend_for``) raise ``sqlite3.OperationalError``
    — so only the charge-time allowance read fails, never the estimate's."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, store: FeedbackStore, amount: str) -> None:
        self.armed = False
        self.raised = 0
        self.outcomes: list[object] = []
        real_read = FeedbackStore.daily_spend_for
        real_charge: Callable[..., Any] = cost_estimation_service.try_record_run_charge

        def read(this: FeedbackStore, account_id: UUID, **kwargs: Any) -> Decimal:
            if self.armed:
                self.raised += 1
                raise sqlite3.OperationalError("disk I/O error")
            return real_read(this, account_id, **kwargs)

        def charge(**kwargs: Any) -> Any:
            _book(store, kwargs["account_id"], amount)
            outcome = real_charge(**kwargs)
            self.outcomes.append(outcome)
            self.armed = True
            return outcome

        monkeypatch.setattr(FeedbackStore, "daily_spend_for", read)
        monkeypatch.setattr(cost_estimation_service, "try_record_run_charge", charge)


def _assert_a_refusal_without_an_allowance(
    response: Any, fault: _FailingAllowanceRead, rows_before: list[str], rows_after: list[str]
) -> None:
    # Partners: the real charge refused, and the injected fault really fired.
    assert fault.outcomes == [ChargeOutcome.OVER_DAILY_CAP]
    assert fault.raised >= 1
    # Cardinality (rule 6b): the only new row is the other tab's charge. No
    # ``cost_charge_voided`` for a charge this request never made.
    assert rows_after == [*rows_before, COST_ACCEPTED_SIMULATED_EVENT], rows_after
    assert response.status_code == 402, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "COST_LIMIT_EXCEEDED"
    assert detail.get("block_reason", "MISSING") == "daily_cap"
    assert "daily_allowance" in detail
    assert detail["daily_allowance"] is None


def test_a_failed_allowance_read_on_the_cookie_path_still_refuses_with_a_402(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: on the cookie path, the charge-time allowance read raising turns
    the refusal into a 500, or writes a ``cost_charge_voided`` row for a charge
    that never happened (row 24, decision 8; the reviewer measured STATUS 500
    and rows ['cost_guardrail_accepted_simulated', 'cost_charge_voided'])."""
    with configure_for_tests() as store, isolated_run_semaphore(1):
        client = TestClient(app, raise_server_exceptions=False)
        csrf = _boot(client)
        key = _spend_key_of(client)
        rows_before = _rows(store, key)
        fault = _FailingAllowanceRead(monkeypatch, store, "0.3500")

        response = client.post(
            RUNS, json=acknowledged_request(QUERY), headers={"X-CSRF-Token": csrf}
        )
        fault.armed = False

        rows_after = _rows(store, key)
        assert query_run_repository.get_active_for_account(key) is None
        _assert_a_refusal_without_an_allowance(response, fault, rows_before, rows_after)


def test_a_failed_allowance_read_on_the_legacy_path_still_refuses_with_a_402(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-IF: the legacy (inline) path's copy of the same refusal turns into a
    500 when the allowance read raises, or writes any row but the other tab's
    charge (row 24; the two paths are kept in step)."""
    with configure_for_tests() as store:
        client = TestClient(app, raise_server_exceptions=False)
        account = uuid4()
        rows_before = _rows(store, account)
        fault = _FailingAllowanceRead(monkeypatch, store, "0.3500")

        response = client.post(RUNS, json=acknowledged_request(QUERY), headers=_legacy(account))
        fault.armed = False

        rows_after = _rows(store, account)
        assert query_run_repository.get_active_for_account(account) is None
        _assert_a_refusal_without_an_allowance(response, fault, rows_before, rows_after)


def test_the_running_total_sets_bounded_by_in_the_reviewers_case() -> None:
    """RED-IF: ``bounded_by`` is missing, or is not ``"running_total"`` when the
    running total set the figure (row 25). The reviewer's case: three runs,
    their ledger rows aged 25 h, a fourth run — ledger 0.1052, ring 0.4208, so
    remaining is 0.50 - 0.4208 = 0.0792, not 0.40 - 0.1052 = 0.2948. Partner:
    the ledger and ring hold exactly those sums."""
    with configure_for_tests() as store:
        client = TestClient(app)
        account = uuid4()
        for _ in range(3):
            _legacy_run(client, account)
        _age_ledger(store, account, hours=25)
        _legacy_run(client, account)

        estimate = _post_estimate(client, _legacy(account))["cost_estimate"]

        assert store.daily_spend_for(account) == Decimal("0.1052")
        assert cost_estimation_service._cumulative_spend_for(account) == Decimal("0.4208")  # noqa: SLF001
        assert _allowance(estimate) == {
            "cap_usd": "0.40",
            "spent_usd": "0.1052",
            "remaining_usd": "0.0792",
            "bounded_by": "running_total",
        }


def test_bounded_by_switches_only_when_the_running_total_is_strictly_smaller() -> None:
    """RED-IF: the boundary moves. With nothing on the ledger, a ring total of
    exactly 0.1000 leaves both limits at 0.4000 — a tie, which stays
    ``daily_cap`` (decision 2 lowers the figure only when the running-total
    figure "is smaller"); 0.1001 makes it 0.3999 and ``running_total``. Literals
    on both sides of the line (rule 8b)."""
    with configure_for_tests():
        client = TestClient(app)
        tie, over = uuid4(), uuid4()
        _ring(tie, "0.1000")
        _ring(over, "0.1001")

        at_tie = _post_estimate(client, _legacy(tie))["cost_estimate"]
        past_it = _post_estimate(client, _legacy(over))["cost_estimate"]

    assert _allowance(at_tie) == {
        "cap_usd": "0.40",
        "spent_usd": "0.0000",
        "remaining_usd": "0.4000",
        "bounded_by": "daily_cap",
    }
    assert _allowance(past_it) == {
        "cap_usd": "0.40",
        "spent_usd": "0.0000",
        "remaining_usd": "0.3999",
        "bounded_by": "running_total",
    }
