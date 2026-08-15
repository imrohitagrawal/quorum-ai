"""Unit tests for ``tests.helpers.scoped_events`` (#209).

``scoped_events`` is the one shared filter every test uses to read a
process-global event recorder. If it silently stopped filtering, ~30 call
sites across the suite would go back to reading the whole process-global
buffer and nothing would fail — which is exactly the class of bug #209 is
about. So the filter gets its own tests.

What turns each test red is stated on the test itself.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from tests.helpers import scoped_events

from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import ProviderPath, provider_event_recorder
from product_app.safety import WarningType, warning_event_recorder


def setup_function() -> None:
    provider_event_recorder.clear()
    warning_event_recorder.clear()


def _record_provider_event(*, account_id: UUID, query_run_id: UUID, model_id: str) -> None:
    provider_event_recorder.record(
        event_type="initial_answer_recorded",
        account_id=account_id,
        query_run_id=query_run_id,
        model_id=model_id,
        provider_path=ProviderPath.LOCAL_SIMULATION,
        duration_ms=1,
        fallback_used=False,
        source_count=0,
        credential_source=ProviderCredentialSource.APP_OWNED,
    )


def test_scoped_events_returns_the_matching_account_and_drops_a_foreign_one() -> None:
    """Positive AND negative partner in one assertion pair.

    What turns it red: make ``scoped_events`` return
    ``recorder.list_events()`` unfiltered — the length goes to 2 and the
    model-id assertion sees the foreign event.
    """
    mine = uuid4()
    theirs = uuid4()
    my_run = uuid4()

    _record_provider_event(account_id=mine, query_run_id=my_run, model_id="mine/model")
    _record_provider_event(account_id=theirs, query_run_id=uuid4(), model_id="foreign/model")

    events = scoped_events(provider_event_recorder, account_id=mine)

    # Positive: the event this caller recorded IS returned.
    assert [event.model_id for event in events] == ["mine/model"]
    assert events[0].account_id == mine
    # Negative partner: the foreign account's event is NOT returned, and the
    # recorder really did hold it, so the negative is not trivially true.
    whole_buffer = (
        # unscoped-ok: this test's whole point is that the unscoped buffer
        # holds MORE than the scoped read returns, so scoping this one read
        # would delete the evidence the assertion below rests on.
        provider_event_recorder.list_events()
    )
    assert len(whole_buffer) == 2
    assert "foreign/model" not in [event.model_id for event in events]


def test_scoped_events_narrows_to_one_run_inside_one_account() -> None:
    """Two runs, same account: scoping by ``query_run_id`` keeps only one.

    What turns it red: drop the ``query_run_id`` clause from the helper's
    comprehension — both runs' events come back and the length is 2.
    """
    account_id = uuid4()
    wanted_run = uuid4()
    other_run = uuid4()

    _record_provider_event(account_id=account_id, query_run_id=wanted_run, model_id="wanted/model")
    _record_provider_event(account_id=account_id, query_run_id=other_run, model_id="other/model")

    events = scoped_events(provider_event_recorder, query_run_id=wanted_run)

    assert [event.model_id for event in events] == ["wanted/model"]
    assert [event.query_run_id for event in events] == [wanted_run]


def test_scoped_events_applies_both_keys_together() -> None:
    """Both keys are an AND, not an OR.

    What turns it red: change the helper's ``and`` to ``or`` — the event that
    matches only the account and the event that matches only the run both come
    back, and the length is 3 instead of 1.
    """
    account_id = uuid4()
    query_run_id = uuid4()

    _record_provider_event(account_id=account_id, query_run_id=query_run_id, model_id="both/model")
    _record_provider_event(account_id=account_id, query_run_id=uuid4(), model_id="account/only")
    _record_provider_event(account_id=uuid4(), query_run_id=query_run_id, model_id="run/only")

    events = scoped_events(
        provider_event_recorder,
        account_id=account_id,
        query_run_id=query_run_id,
    )

    assert [event.model_id for event in events] == ["both/model"]


def test_scoped_events_works_on_a_recorder_whose_query_run_id_is_optional() -> None:
    """``WarningEvent.query_run_id`` is ``UUID | None``; a run-less event must
    still be reachable by account and must not match a run filter.

    What turns it red: make the helper compare ``query_run_id`` unconditionally
    (drop the ``query_run_id is None or`` short-circuit) — the account-scoped
    read then returns nothing.
    """
    account_id = uuid4()
    warning_event_recorder.record(
        event_type="safety_warning_impression",
        account_id=account_id,
        query_run_id=None,
        warning_type=WarningType.SENSITIVE_DATA,
        warning_version="v1",
        acknowledged=False,
    )

    by_account = scoped_events(warning_event_recorder, account_id=account_id)
    by_unrelated_run = scoped_events(warning_event_recorder, query_run_id=uuid4())

    assert len(by_account) == 1
    assert by_account[0].query_run_id is None
    assert by_unrelated_run == []


def test_scoped_events_refuses_a_call_with_no_scope_at_all() -> None:
    """A no-key call would be an unfiltered read wearing the helper's name.

    What turns it red: delete the ``ValueError`` guard — the call then returns
    the whole process-global buffer and no exception is raised.
    """
    _record_provider_event(account_id=uuid4(), query_run_id=uuid4(), model_id="any/model")

    with pytest.raises(ValueError, match="account_id"):
        scoped_events(provider_event_recorder)
