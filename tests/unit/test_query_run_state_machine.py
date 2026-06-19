from uuid import UUID, uuid4

import pytest

from product_app.costs import cost_estimation_service
from product_app.model_slots import validate_model_slots
from product_app.query_runs import (
    InMemoryQueryRunRepository,
    InvalidQueryRunTransitionError,
    QueryRun,
    QueryRunStatus,
)

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def create_test_query_run(
    repository: InMemoryQueryRunRepository,
    account_id: UUID | None = None,
) -> QueryRun:
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    query_text = "Compare options"
    return repository.create(
        account_id=account_id or uuid4(),
        query_text=query_text,
        model_slots=model_slots,
        cost_estimate=cost_estimation_service.estimate(
            query_text=query_text,
            model_slots=model_slots,
        ),
    )


def test_query_run_allows_expected_execution_transitions() -> None:
    repository = InMemoryQueryRunRepository()
    query_run = create_test_query_run(repository)

    repository.transition(query_run.query_run_id, QueryRunStatus.INITIAL_ANSWERS_RUNNING)
    repository.transition(query_run.query_run_id, QueryRunStatus.DEBATE_ROUND_1_RUNNING)
    repository.transition(query_run.query_run_id, QueryRunStatus.DEBATE_ROUND_2_RUNNING)
    repository.transition(query_run.query_run_id, QueryRunStatus.SYNTHESIS_RUNNING)
    repository.transition(query_run.query_run_id, QueryRunStatus.COMPLETED)

    assert query_run.status == QueryRunStatus.COMPLETED
    assert query_run.is_terminal


def test_query_run_rejects_invalid_transition() -> None:
    repository = InMemoryQueryRunRepository()
    query_run = create_test_query_run(repository)

    with pytest.raises(InvalidQueryRunTransitionError):
        repository.transition(query_run.query_run_id, QueryRunStatus.COMPLETED)


def test_terminal_state_releases_active_slot() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    query_run = create_test_query_run(repository, account_id)

    repository.transition(query_run.query_run_id, QueryRunStatus.FAILED)

    assert repository.get_active_for_account(account_id) is None
    next_query_run = create_test_query_run(repository, account_id)
    assert next_query_run.status == QueryRunStatus.ACCEPTED


def test_partial_terminal_state_records_missing_steps() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    query_run = create_test_query_run(repository, account_id)
    repository.transition(query_run.query_run_id, QueryRunStatus.INITIAL_ANSWERS_RUNNING)

    repository.transition(
        query_run.query_run_id,
        QueryRunStatus.PARTIAL,
        failed_steps=["synthesis"],
        missing_steps=["debate_round_2", "synthesis"],
    )

    assert query_run.is_terminal
    assert query_run.failed_steps == ["synthesis"]
    assert query_run.missing_steps == ["debate_round_2", "synthesis"]
    assert repository.get_active_for_account(account_id) is None


def test_timed_out_terminal_state_records_missing_steps() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    query_run = create_test_query_run(repository, account_id)
    repository.transition(query_run.query_run_id, QueryRunStatus.INITIAL_ANSWERS_RUNNING)

    repository.transition(
        query_run.query_run_id,
        QueryRunStatus.TIMED_OUT,
        failed_steps=["initial_answers"],
        missing_steps=["debate_round_1", "debate_round_2", "synthesis"],
    )

    assert query_run.is_terminal
    assert query_run.failed_steps == ["initial_answers"]
    assert query_run.missing_steps == ["debate_round_1", "debate_round_2", "synthesis"]
    assert repository.get_active_for_account(account_id) is None
