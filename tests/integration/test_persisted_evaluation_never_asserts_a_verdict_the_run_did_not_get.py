"""Issue #342: the durable audit row must not assert a verdict the run never got.

``_persist_terminal_run`` runs the judge at run COMPLETION. When the money
rails refuse a fresh paid dispatch (#216, ADR-0051), or when a reader loses the
in-flight call it meant to ride on, ``_MemoisedRunJudge`` serves the
verdict-less shape and ``_evaluate_terminal_run`` deliberately does NOT memoise
it — a refusal is scoped to the read that got it, never to the run.

Until this change ``_persist_run_evaluation`` wrote that suppressed shape into
the durable row anyway, as ``band="unverified", score=None,
support_verified=False``, and **nothing ever rewrote it**:
``_update_run_evaluation`` has exactly one caller, reachable only from terminal
persist (``grep -rn "_update_run_evaluation" src/`` → one call site,
``query_run_orchestration.py``; ``grep -rn "_persist_terminal_run(" src/`` →
``query_runs.py`` and ``query_run_orchestration.py``, both POST/execution
paths). Once the 24h rail reset, the served body said ``('high', 90, True)``
while the durable row still said ``('unverified', None, False)`` for good.

The fix: on a suppressed evaluation write NO trust verdict at all, and record
the refusal cause on the durable ``run_evaluated`` event so the empty column is
an honest, explained absence rather than a false claim.

**What this does NOT do**, stated so no test here is read as proving it: the
durable row still does not converge on the served projection. A run refused at
23:59 is served verified tomorrow and its trust column stays empty. That would
need a re-evaluation trigger, which does not exist (one persist per run, no
sweeper) and which ADR-0055 rejects.

Hermetic: the only provider seam is monkeypatched to a canned verdict, so there
is no network and no spend.

This file carries its own copies of the fixtures from
``test_judge_preflight_respects_the_spend_rails.py``. ``tests/integration/``
has neither ``__init__.py`` nor ``conftest.py`` (verified with ``ls``), so
those helpers are not importable across files, and lifting them into a new
package-level conftest would change collection for every integration test.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from tests.unit.test_evaluation_judge import VALID_VERDICT
from tests.unit.test_evaluation_layer_a import _answer

from product_app import query_run_orchestration as qro
from product_app import query_runs as qr
from product_app.config import settings
from product_app.costs import (
    DAILY_CAP_USD,
    GLOBAL_DAILY_CEILING_USD,
    CostThresholdAction,
    cost_estimation_service,
)
from product_app.debate import AgreementSummary
from product_app.feedback_store import COST_ACCEPTED_EVENT, ChargeOutcome, FeedbackStore, get_store
from product_app.model_slots import validate_model_slots_with_search
from product_app.providers import LiveProviderResult, provider_execution_service
from product_app.query_runs import QueryRunStatus, query_run_repository

MODELS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]
QUERY_TEXT = "Compare transparent model answers"
AGREEMENT = AgreementSummary(aligned=0, total=4)

#: A cap high enough that the per-account rail never refuses a helper charge
#: written to move the GLOBAL meter. Deliberately not derived from
#: ``DAILY_CAP_USD`` (AGENTS.md rule 7a).
NO_ACCOUNT_LIMIT = Decimal("1000")

#: The band/score/support the fixture run earns from a REAL verdict, as
#: literals on both sides so a silent downgrade cannot read as a pass.
FULL_VERDICT_BAND = "high"
FULL_VERDICT_SCORE = 90
FULL_VERDICT_SUPPORT = True

#: The Layer-A composite the fixture run scores. A literal, so a test that
#: proves the Layer-A telemetry SURVIVED the refusal cannot be satisfied by a
#: payload that merely echoes whatever the code computed.
FIXTURE_LAYER_A_COMPOSITE = 90.0

#: Every refusal token the application may write, hand-listed. NOT derived
#: from the enum — deriving both sides of this comparison from the same object
#: makes it green against any membership at all.
EXPECTED_REFUSAL_TOKENS = {
    "spend_rail_preflight",
    "inflight_owner_lost",
    "inflight_timeout",
}
TOKEN_SHAPE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


@pytest.fixture(autouse=True)
def _memos_empty() -> Any:
    """Both process-global memos start and end empty (AGENTS.md rule 16a)."""
    query_run_repository.clear()
    qr._judge_verdict_memo_clear_for_tests()
    qr._evaluation_memo_clear_for_tests()
    yield
    qr._judge_verdict_memo_clear_for_tests()
    qr._evaluation_memo_clear_for_tests()
    query_run_repository.clear()


@pytest.fixture
def judge_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Configure the judge and count every dispatch, without a network call."""
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "vendor/judge-model")
    calls: list[dict[str, Any]] = []

    def _fake(**kwargs: Any) -> LiveProviderResult:
        calls.append(kwargs)
        return LiveProviderResult(answer_text=json.dumps(VALID_VERDICT), sources=[], usage=None)

    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _fake)
    return calls


class _Write:
    """One captured ``_update_run_evaluation`` call."""

    def __init__(self, run_id: str, eval_json: Any, trust_json: Any) -> None:
        self.run_id = run_id
        self.eval_json = eval_json
        self.trust_json = trust_json


@pytest.fixture
def durable_writes(monkeypatch: pytest.MonkeyPatch) -> list[_Write]:
    """Capture every write to the durable evaluation columns, in order."""
    writes: list[_Write] = []

    def _capture(run_id: str, *, eval_json: Any, trust_json: Any) -> None:
        writes.append(_Write(run_id, eval_json, trust_json))

    monkeypatch.setattr(qro, "_update_run_evaluation", _capture)
    return writes


@pytest.fixture
def evaluated_events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture every ``run_evaluated`` payload, still writing it to the store."""
    payloads: list[dict[str, Any]] = []
    real_record = qro._record_feedback_event  # type: ignore[attr-defined]

    def _spy(**kwargs: Any) -> Any:
        if kwargs.get("event_type") == "run_evaluated":
            payloads.append(kwargs.get("payload", {}))
        return real_record(**kwargs)

    monkeypatch.setattr(qro, "_record_feedback_event", _spy)
    return payloads


def _terminal_run(account_id: UUID | None = None) -> Any:
    """A COMPLETED run with one live answer — the shape the judge accepts."""
    slots = validate_model_slots_with_search(MODELS)
    estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=slots)
    run = query_run_repository.create(
        account_id=account_id or uuid4(),
        query_text=QUERY_TEXT,
        model_slots=slots,
        cost_estimate=estimate,
    )
    run.initial_answers = [_answer(slot=1)]
    run.final_synthesis = None
    run.status = QueryRunStatus.COMPLETED
    return run


def _charge(
    store: FeedbackStore,
    *,
    account_id: UUID,
    amount: Decimal,
    daily_cap: Decimal = NO_ACCOUNT_LIMIT,
) -> None:
    """Book a real ``cost_guardrail_accepted`` charge through the atomic writer."""
    run_id = uuid4()
    outcome = store.try_record_cost_charge(
        account_id=account_id,
        query_run_id=run_id,
        estimated_cost_usd=amount,
        payload={
            "event_type": COST_ACCEPTED_EVENT,
            "account_id": str(account_id),
            "query_run_id": str(run_id),
            "estimated_cost_usd": str(amount),
            "threshold_action": CostThresholdAction.ALLOW.value,
            "confirmed": False,
        },
        daily_cap_usd=daily_cap,
        global_ceiling_usd=GLOBAL_DAILY_CEILING_USD + amount,
    )
    assert outcome is ChargeOutcome.RECORDED, f"the helper charge itself was refused: {outcome}"


def _at_cap_run(store: FeedbackStore) -> Any:
    """A terminal run whose account is at its daily cap, charged AFTER create.

    Charging after ``_terminal_run`` keeps ``_request_path_judge``'s
    create-time clauses inert, so only the LIVE #216 rail can be refusing.
    """
    account = uuid4()
    run = _terminal_run(account)
    assert run.cost_estimate.global_ceiling_reached is False
    assert run.cost_estimate.spend_metering_unavailable is False
    _charge(store, account_id=account, amount=Decimal("0.20"))
    assert store.daily_spend_for(account) >= DAILY_CAP_USD, "the fixture did not reach the rail"
    return run


# ---------------------------------------------------------------------------
# What gets WRITTEN to the durable trust columns.
# ---------------------------------------------------------------------------


def test_a_spend_rail_refusal_writes_no_trust_verdict_to_the_durable_row(
    judge_calls: list[dict[str, Any]],
    durable_writes: list[_Write],
) -> None:
    """A refused run leaves the durable trust column empty, not falsely unverified.

    RED if ``_persist_run_evaluation`` calls ``_update_run_evaluation`` on the
    suppressed path: measured on ``21d8358`` this wrote
    ``{'support_verified': False, 'band': 'unverified', 'score': None, ...}``
    for a run the judge was never allowed to look at, and nothing rewrote it.
    """
    store = get_store()
    assert store is not None
    run = _at_cap_run(store)

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(durable_writes) == 0, (
        "a run the money rails refused to judge was recorded as judged-and-unverified"
    )
    assert len(judge_calls) == 0, "the rail did not actually refuse; this test proves nothing"


def test_a_run_below_the_rails_still_writes_its_full_verdict(
    judge_calls: list[dict[str, Any]],
    durable_writes: list[_Write],
) -> None:
    """POSITIVE PARTNER to the test above: the clean path still persists.

    Without this, "no write happened" is trivially satisfied by a fix that
    simply stops writing (AGENTS.md rule 7).

    RED if the suppression check fires unconditionally — the durable write
    disappears for every run, not only refused ones.
    """
    run = _terminal_run()

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(durable_writes) == 1, "the clean path stopped persisting its evaluation"
    trust = durable_writes[0].trust_json
    assert trust["band"] == FULL_VERDICT_BAND
    assert trust["score"] == FULL_VERDICT_SCORE
    assert trust["support_verified"] is FULL_VERDICT_SUPPORT
    assert len(judge_calls) == 1, "the judge must fire on the clean path"


def test_a_later_refusal_cannot_overwrite_a_verdict_already_written(
    judge_calls: list[dict[str, Any]],
    durable_writes: list[_Write],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANTI-CLOBBER. ``update_evaluation`` is a blind UPDATE of both columns.

    ``run_history_store.update_evaluation`` runs
    ``UPDATE runs SET eval_json = ?, trust_json = ? WHERE query_run_id = ?``
    with no rowcount check and no partial update, so a second persist after
    memo eviction — with the rail now closed — replaced a real ``high``
    verdict with ``unverified``.

    RED if the suppressed path writes anything at all, including a row with
    nulls: the second persist appends a second write and the last-written band
    is no longer ``high``.
    """
    store = get_store()
    assert store is not None
    account = uuid4()
    run = _terminal_run(account)

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)
    assert len(durable_writes) == 1
    assert durable_writes[0].trust_json["band"] == FULL_VERDICT_BAND
    assert len(judge_calls) == 1

    # Both memos evicted (the shipped LRUs are bounded), and the rail closes.
    qr._judge_verdict_memo_clear_for_tests()
    qr._evaluation_memo_clear_for_tests()
    _charge(store, account_id=account, amount=Decimal("0.20"))
    assert store.daily_spend_for(account) >= DAILY_CAP_USD

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(durable_writes) == 1, "a money refusal overwrote a verdict already persisted"
    assert durable_writes[-1].trust_json["band"] == FULL_VERDICT_BAND
    assert len(judge_calls) == 1, "the refused re-persist must not have paid for a dispatch"
    monkeypatch  # noqa: B018 - fixture kept for symmetry with the suite's style


def test_a_reader_that_lost_its_in_flight_owner_also_writes_no_verdict(
    judge_calls: list[dict[str, Any]],
    durable_writes: list[_Write],
    evaluated_events: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The money rail is not the only cause, and the fix must cover both.

    A persist whose in-flight owner vanishes between the two lock takes serves
    the same verdict-less shape without any rail being consulted.

    RED if the fix keys on ``_judge_money_rails_allow_dispatch`` rather than on
    the judge's own suppression flag: this persist writes
    ``('unverified', None, False)`` durably again, and the event's refusal
    token is missing.
    """

    class _InFlightThatVanishes(dict):  # type: ignore[type-arg]
        """Present for the ``sharing`` probe, gone by the ``.get`` below it."""

        def __contains__(self, key: object) -> bool:
            return True

    run = _terminal_run()
    monkeypatch.setattr(qro, "_judge_inflight", _InFlightThatVanishes())
    monkeypatch.setattr(
        qro,
        "_judge_money_rails_allow_dispatch",
        lambda account_id: pytest.fail("the rails must not even be consulted while sharing"),
    )

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(durable_writes) == 0, "a reader that lost its owner persisted a false unverified"
    assert len(judge_calls) == 0
    assert len(evaluated_events) == 1
    assert evaluated_events[0]["judge_refusal"] == "inflight_owner_lost"


# ---------------------------------------------------------------------------
# What the durable ``run_evaluated`` event SAYS about the refusal.
# ---------------------------------------------------------------------------


def test_the_refusal_cause_reaches_the_durable_event(
    judge_calls: list[dict[str, Any]],
    durable_writes: list[_Write],
    evaluated_events: list[dict[str, Any]],
) -> None:
    """An empty trust column must be an explained absence, not a silent one.

    Without a recorded cause, "refused for money" is byte-identical to "no
    judge configured", to a store fault, and to a crash mid-persist — the
    indistinguishability ADR-0018 exists to remove.

    RED if the payload drops ``judge_refusal`` or hard-codes it to ``None``.
    """
    store = get_store()
    assert store is not None
    run = _at_cap_run(store)

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(evaluated_events) == 1, "the refused run emitted no audit event at all"
    assert evaluated_events[0]["judge_refusal"] == "spend_rail_preflight"
    assert len(durable_writes) == 0
    assert len(judge_calls) == 0


def test_the_refused_event_claims_no_trust_verdict_either(
    judge_calls: list[dict[str, Any]],
    evaluated_events: list[dict[str, Any]],
) -> None:
    """Do not move the false claim from the row into the event.

    RED if the payload keeps emitting the Layer-A downgrade shape
    (``trust_band="unverified"``, ``support_verified=False``) on the refusal
    path, which is the same assertion the durable row used to make.
    """
    store = get_store()
    assert store is not None
    run = _at_cap_run(store)

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(evaluated_events) == 1
    payload = evaluated_events[0]
    assert payload["trust_band"] is None
    assert payload["support_verified"] is None
    assert len(judge_calls) == 0


def test_the_refused_event_still_carries_its_layer_a_telemetry(
    judge_calls: list[dict[str, Any]],
    evaluated_events: list[dict[str, Any]],
) -> None:
    """POSITIVE PARTNER to the test above: the event is nulled, not emptied.

    Layer A is unaffected by a judge refusal, so its composite and signals are
    still true and still worth auditing.

    RED if the fix suppresses the whole payload, or blanks it wholesale rather
    than only the two fields the judge would have decided.
    """
    store = get_store()
    assert store is not None
    run = _at_cap_run(store)

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(evaluated_events) == 1
    payload = evaluated_events[0]
    assert payload["layer_a_composite_unverified"] == FIXTURE_LAYER_A_COMPOSITE
    assert payload["signals"], "the Layer-A signals were lost with the trust verdict"
    assert payload["faithfulness_label"] is not None
    assert len(judge_calls) == 0


def test_a_clean_run_records_no_refusal(
    judge_calls: list[dict[str, Any]],
    evaluated_events: list[dict[str, Any]],
) -> None:
    """POSITIVE PARTNER: ``judge_refusal`` is ``None`` when nothing refused.

    RED if the fix stamps a refusal token unconditionally — which would make
    every "the token is X" assertion above true for the wrong reason.
    """
    run = _terminal_run()

    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)

    assert len(evaluated_events) == 1
    payload = evaluated_events[0]
    assert payload["judge_refusal"] is None
    assert payload["trust_band"] == FULL_VERDICT_BAND
    assert payload["support_verified"] is FULL_VERDICT_SUPPORT
    assert len(judge_calls) == 1


# ---------------------------------------------------------------------------
# Cardinality on the ledger: a persist that refuses must not write money rows.
# ---------------------------------------------------------------------------


def test_a_refused_persist_writes_exactly_one_ledger_row(
    judge_calls: list[dict[str, Any]],
) -> None:
    """AGENTS.md rule 6b: count the rows, do not assert a clean outcome.

    The whole refused persist must add exactly ONE event — the
    ``run_evaluated`` audit row — and no charge, reconciliation or void.

    RED if any fix books, reconciles or voids money from the persist path, or
    emits a second audit event: the delta moves off 1.
    """
    store = get_store()
    assert store is not None
    run = _at_cap_run(store)

    before = store.event_count()
    qr._persist_run_evaluation(query_run=run, agreement=AGREEMENT)
    after = store.event_count()

    assert after - before == 1, f"the refused persist wrote {after - before} ledger rows, not 1"
    assert len(judge_calls) == 0


def test_the_ledger_counter_moves_for_a_deliberate_write(
    judge_calls: list[dict[str, Any]],
) -> None:
    """POSITIVE PARTNER: ``event_count`` is not stuck.

    Without this, the delta assertion above is satisfiable by a counter that
    never moves at all.

    RED if the fixture store's ``event_count`` stops observing new rows.
    """
    store = get_store()
    assert store is not None
    account = uuid4()

    before = store.event_count()
    _charge(store, account_id=account, amount=Decimal("0.01"))
    after = store.event_count()

    assert after - before == 1, "a deliberate charge did not move the event counter"
    assert len(judge_calls) == 0


# ---------------------------------------------------------------------------
# The memo identity the docstring claims, and the path where it does not hold.
# ---------------------------------------------------------------------------


def test_an_unsuppressed_evaluation_is_one_memoised_object(
    judge_calls: list[dict[str, Any]],
) -> None:
    """The narrowed docstring claim, in its positive half.

    A result that IS memoised is served and persisted from the SAME object, so
    the two readers cannot disagree.

    RED if ``_evaluation_memo_store`` is removed from ``_evaluate_terminal_run``:
    the second call recomputes and returns a different object.
    """
    run = _terminal_run()

    first = qr._evaluate_terminal_run(run, agreement=AGREEMENT)
    second = qr._evaluate_terminal_run(run, agreement=AGREEMENT)

    assert first is second, "the evaluation memo stopped serving one object to both readers"
    assert len(judge_calls) == 1


def test_a_suppressed_evaluation_is_deliberately_not_memoised(
    judge_calls: list[dict[str, Any]],
) -> None:
    """NEGATIVE PARTNER: the identity claim does NOT hold on the refusal path.

    That is on purpose — memoising a refusal would freeze ``unverified`` past
    the 24h rail reset — and it is exactly why the durable row and the served
    projection can diverge, which is issue #342.

    RED if the suppressed result is memoised: the two calls return the same
    object and the key appears in ``_evaluation_memo``.
    """
    store = get_store()
    assert store is not None
    run = _at_cap_run(store)

    first = qr._evaluate_terminal_run(run, agreement=AGREEMENT)
    second = qr._evaluate_terminal_run(run, agreement=AGREEMENT)

    assert first is not second, "a money refusal was frozen into the evaluation memo"
    assert not any(key[0] == str(run.query_run_id) for key in qr._evaluation_memo)
    assert len(judge_calls) == 0


# ---------------------------------------------------------------------------
# The refusal vocabulary is closed and app-authored.
# ---------------------------------------------------------------------------


def test_every_refusal_token_is_a_closed_app_authored_slug() -> None:
    """No prose reaches the durable event stream through this field.

    The expected set is hand-written above rather than derived from the enum:
    deriving both sides of the comparison makes it green against any
    membership at all.

    RED if a member is added, removed or renamed without updating
    ``EXPECTED_REFUSAL_TOKENS``, or if any value stops being a lowercase slug.
    """
    actual = {reason.value for reason in qro.JudgeSuppressionReason}

    assert actual == EXPECTED_REFUSAL_TOKENS
    for token in actual:
        assert TOKEN_SHAPE.match(token), f"refusal token is not a closed slug: {token!r}"
