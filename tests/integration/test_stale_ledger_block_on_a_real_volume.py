"""Issue #122's BLOCK, driven end to end against a REAL read-only volume.

Every other test for this policy monkeypatches ``get_store`` or sets the
reopen flag directly. That is what let the original fix ship broken:
adversarial review reproduced a sequence in which #122's BLOCK **never
fires** for the exact fault shape it exists to fix, and no unit test could
see it because none of them ever ran a real ``FeedbackStore.from_env()``
reopen.

The sequence, measured (this file):

1. A healthy, already-migrated database — the production shape, which
   ``fly.toml`` pins ``FEEDBACK_DB_PATH`` to.
2. The volume goes read-only. The next billed write is lost, so
   ``write_health()`` reports ``"failing"`` and the ledger is stale.
3. The background reopen runs. ``FeedbackStore.from_env()`` attempts ZERO
   writes when opening an existing, already-migrated database, so it
   **returns successfully against the still-read-only volume**. A fresh
   handle is installed reporting ``"unverified"``.
4. That handle's own first billed write also fails: ``"failing"`` again.

Under the original "did the reopen raise" flag, step 3 latched the flag back
to ``False``, so at step 4 the cap check saw ``stale=True,
reopen_failed=False`` and took the allow-and-log branch. Every subsequent
cooldown-window reopen repeated the cycle, so the daily cap could never
block on a read-only volume — a permanent money leak, not a transient one.

The flag now means "a reopen COMPLETED and the store has not demonstrably
written since", cleared only by a landed write. This file is the proof, and
it is deliberately an integration test with a real SQLite file and real
``chmod``: no part of the failure is mocked.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from product_app import store_reconnect
from product_app.costs import CostEstimationService, CostThresholdAction
from product_app.feedback_store import FeedbackStore, configure, get_store
from product_app.model_slots import ModelSlot

_MODEL_IDS = [
    "anthropic/claude-opus-4",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
    "nvidia/nemotron-3-nano-30b-a3b",
]


def _slots() -> list[ModelSlot]:
    return [ModelSlot(slot_number=i + 1, model_id=m, search=True) for i, m in enumerate(_MODEL_IDS)]


def _charge(store: FeedbackStore, account_id: UUID, usd: str) -> None:
    """One billed cost event — the row the daily cap is metered from."""
    store.record(
        recorder="cost",
        event_type="cost_guardrail_accepted",
        account_id=account_id,
        query_run_id=uuid4(),
        recorded_at=datetime.now(UTC),
        payload={"estimated_cost_usd": usd},
    )


def _skip_if_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores the read-only mode bits this test depends on")


def _join_reconnect_threads(timeout: float = 5.0) -> None:
    """Wait for any in-flight background reopen to finish.

    The reopen is a daemon thread by design, so nothing else waits for it.
    A trial that starts while the previous trial's reopen is still running
    would see that reopen set the flag and mis-attribute the resulting block
    to its own request.
    """
    for thread in threading.enumerate():
        if thread.name.startswith("feedback-store-reconnect"):
            thread.join(timeout)


class _NoOpThread:
    """Keeps reopens under the test's control, without faking any of them.

    ``estimate()`` spawns its reconnect on a background thread, so a real
    ``Thread`` here would race the assertions — the reopen could land, or
    not, between two lines. Only the SCHEDULING is stubbed: every reopen in
    this file is a real ``_reopen_feedback_store()`` call against a real
    read-only volume, driven explicitly so the sequence is deterministic.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def start(self) -> None:
        pass


@pytest.fixture
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> object:
    store_reconnect._reset_for_tests()
    monkeypatch.setattr("product_app.store_reconnect.threading.Thread", _NoOpThread)
    yield
    store_reconnect._reset_for_tests()
    configure(None)


def test_a_read_only_volume_eventually_blocks_even_though_the_reopen_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _clean_state: object,
) -> None:
    """The whole defect, end to end, with nothing mocked.

    Turns red if: ``_reopen_feedback_store`` clears the reopen flag on an
    open that merely did not raise, or if the flag is cleared by anything
    short of a landed write (e.g. by ``write_health() != "failing"``, which
    a freshly-reopened handle satisfies while writing nothing).
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    account_id = uuid4()
    monkeypatch.setenv("FEEDBACK_DB_PATH", str(db))

    # 1. A healthy, already-migrated database.
    seed = FeedbackStore(str(db))
    _charge(seed, account_id, "0.05")
    assert seed.write_health() == "ok", "precondition: the seed store must write"
    seed.close()

    # 2. The volume goes read-only, under a handle opened after the fault.
    #    Both the file and its directory: SQLite needs to create a -journal
    #    sibling to start a write transaction.
    db.chmod(0o444)
    db.parent.chmod(0o555)
    try:
        broken = FeedbackStore(str(db))
        _charge(broken, account_id, "0.05")
        configure(broken)
        assert broken.write_health() == "failing", "precondition: the fault must be real"
        assert store_reconnect.feedback_ledger_is_stale(get_store()) is True

        service = CostEstimationService(binding_secret="x" * 32)

        # Before any reopen has completed, the policy is allow-and-log:
        # staleness alone must never block. This is #122's own confirmed
        # policy, not an accident -- and it is asserted with REAL threads in
        # ``test_the_first_sighting_of_staleness_never_blocks_with_real_threads``
        # below, because with the ``_NoOpThread`` stub active here this
        # assertion cannot fail and would be worth nothing on its own.
        first = service.estimate(query_text="hi", model_slots=_slots(), account_id=account_id)
        assert first.threshold_action is not CostThresholdAction.BLOCK, (
            "first sighting of staleness must not block"
        )

        # 3. The reopen runs against the STILL read-only volume. It does not
        #    raise -- opening an existing, already-migrated database attempts
        #    no writes -- and installs a fresh 'unverified' handle.
        store_reconnect._reopen_feedback_store()
        reopened = get_store()
        assert reopened is not None and reopened is not broken, (
            "precondition: the reopen must actually have installed a new handle"
        )
        assert reopened.write_health() == "unverified", (
            "precondition: this is the state that made the original fix fail -- "
            "a reopen that wrote nothing, on a volume that is still broken"
        )

        # NO FLICKER. ``"unverified"`` is not stale, so a block keyed on
        # staleness alone would let this request through and meter it off a
        # frozen ledger -- once per cooldown window, for the whole outage.
        # The block must hold from the first completed reopen onward.
        unverified = service.estimate(query_text="hi", model_slots=_slots(), account_id=account_id)
        assert unverified.threshold_action is CostThresholdAction.BLOCK, (
            "a freshly reopened, unproven handle must not un-block the cap"
        )

        # 4. The reopened handle's own first billed write also fails.
        _charge(reopened, account_id, "0.05")
        assert reopened.write_health() == "failing"

        # THE ASSERTION THIS FILE EXISTS FOR. Stale again, and a reopen has
        # completed without the store ever writing -- so the cap must now
        # refuse rather than meter spend off a frozen ledger.
        blocked = service.estimate(query_text="hi", model_slots=_slots(), account_id=account_id)
        assert blocked.threshold_action is CostThresholdAction.BLOCK, (
            "a read-only volume that survived a reopen must block, not allow-and-log"
        )
        assert blocked.confirmation_token is None
        assert any("reconnect" in r.lower() or "ledger" in r.lower() for r in blocked.reasons), (
            f"the reason must name the storage fault, got: {blocked.reasons}"
        )
    finally:
        db.parent.chmod(0o755)
        db.chmod(0o644)


def test_the_block_stands_down_once_the_volume_is_writable_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _clean_state: object,
) -> None:
    """The other direction, and the reason the flag is not simply sticky.

    A fault that has genuinely healed must stop refusing traffic. If the
    only way out were a process restart, this policy would convert a
    transient volume blip into an outage lasting until someone noticed --
    strictly worse than the under-metering it exists to prevent.

    Turns red if: the flag is never cleared (the account stays blocked after
    a real write lands), or if it is cleared on something weaker than a
    landed write.
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    account_id = uuid4()
    monkeypatch.setenv("FEEDBACK_DB_PATH", str(db))

    seed = FeedbackStore(str(db))
    _charge(seed, account_id, "0.01")
    seed.close()

    db.chmod(0o444)
    db.parent.chmod(0o555)
    try:
        broken = FeedbackStore(str(db))
        _charge(broken, account_id, "0.01")
        configure(broken)
        service = CostEstimationService(binding_secret="x" * 32)

        store_reconnect._reopen_feedback_store()
        still_broken = get_store()
        assert still_broken is not None
        _charge(still_broken, account_id, "0.01")
        blocked = service.estimate(query_text="hi", model_slots=_slots(), account_id=account_id)
        assert blocked.threshold_action is CostThresholdAction.BLOCK, (
            "precondition: the block must actually be engaged before we clear it"
        )
    finally:
        db.parent.chmod(0o755)
        db.chmod(0o644)

    # The operator restores write access. The next reopen lands a real write.
    store_reconnect._reopen_feedback_store()
    recovered = get_store()
    assert recovered is not None
    _charge(recovered, account_id, "0.01")
    assert recovered.write_health() == "ok", "precondition: the volume must really be writable"

    allowed = CostEstimationService(binding_secret="x" * 32).estimate(
        query_text="hi", model_slots=_slots(), account_id=account_id
    )
    assert allowed.threshold_action is not CostThresholdAction.BLOCK, (
        "a healed volume must stop refusing traffic without a restart"
    )
    assert store_reconnect.feedback_reopen_tried_without_recovery() is False


def test_the_first_sighting_of_staleness_never_blocks_with_real_threads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one guarantee the ``_NoOpThread`` stub cannot honestly assert.

    Deliberately does NOT use ``_clean_state``: real ``threading.Thread``, so
    the reconnect ``estimate()`` spawns actually runs and races the block
    check ~100 lines further down the same call.

    Round 1's fix failed this 20/20 and round 2's adversarial pass measured
    30/30 -- not flaky, deterministic. The reopen completed INSIDE the first
    request, installed an ``"unverified"`` handle, and the cap refused a
    request that the operator's policy says must be allowed ("only after a
    reopen attempt has actually been tried and failed, not an immediate
    block on staleness alone"). The fix is a snapshot of the flag taken
    before the reconnect is spawned, so a reopen a request starts can never
    condemn that same request.

    Repeated because the failure it guards is a RACE: a single green run
    would prove very little.

    Each trial JOINS the reopen threads the previous trial spawned before
    resetting. Without that the test failed in the full suite while passing
    alone — a reopen from trial N landed during trial N+1 and set the flag
    before its snapshot. That is CORRECT product behaviour (an earlier
    request's reopen is exactly what should condemn a later one); the
    guarantee under test is narrower — a request is never condemned by the
    reopen IT started — so leaking threads across trials measured the wrong
    thing.

    Turns red if: ``costs.estimate`` reads
    ``feedback_reopen_tried_without_recovery()`` live at the block check
    instead of using the snapshot taken before ``maybe_reconnect_*``.
    """
    _skip_if_root()
    db = tmp_path / "feedback_events.sqlite3"
    monkeypatch.setenv("FEEDBACK_DB_PATH", str(db))

    seed = FeedbackStore(str(db))
    _charge(seed, uuid4(), "0.01")
    seed.close()

    db.chmod(0o444)
    db.parent.chmod(0o555)
    try:
        blocked_first = 0
        trials = 20
        for _ in range(trials):
            _join_reconnect_threads()
            store_reconnect._reset_for_tests()
            account_id = uuid4()
            broken = FeedbackStore(str(db))
            _charge(broken, account_id, "0.01")
            configure(broken)
            assert broken.write_health() == "failing", "precondition: the fault must be real"

            first = CostEstimationService(binding_secret="x" * 32).estimate(
                query_text="hi", model_slots=_slots(), account_id=account_id
            )
            if first.threshold_action is CostThresholdAction.BLOCK:
                blocked_first += 1

        assert blocked_first == 0, (
            f"the first sighting of staleness blocked in {blocked_first}/{trials} trials; "
            "a reconnect spawned by a request must not condemn that same request"
        )
    finally:
        db.parent.chmod(0o755)
        db.chmod(0o644)
        store_reconnect._reset_for_tests()
        configure(None)
