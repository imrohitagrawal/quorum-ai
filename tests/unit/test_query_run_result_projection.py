from uuid import UUID, uuid4

from product_app.costs import cost_estimation_service
from product_app.model_slots import validate_model_slots
from product_app.providers import InitialAnswerStatus, provider_stub_service
from product_app.query_runs import InMemoryQueryRunRepository

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]


def create_test_query_run(
    repository: InMemoryQueryRunRepository,
    account_id: UUID,
    query_text: str,
) -> UUID:
    model_slots = validate_model_slots(DEFAULT_MODEL_IDS)
    query_run = repository.create(
        account_id=account_id,
        query_text=query_text,
        model_slots=model_slots,
        cost_estimate=cost_estimation_service.estimate(
            query_text=query_text,
            model_slots=model_slots,
        ),
    )
    initial_answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run.query_run_id,
        query_text=query_text,
        model_slots=model_slots,
    )
    repository.record_initial_answers(query_run.query_run_id, initial_answers)
    return query_run.query_run_id


def test_query_run_repository_keeps_model_answers_owner_scoped() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    other_account_id = uuid4()
    query_run_id = create_test_query_run(
        repository,
        account_id,
        "Compare source-backed answers",
    )

    query_run = repository.get_for_account(query_run_id=query_run_id, account_id=account_id)
    other_query_run = repository.get_for_account(
        query_run_id=query_run_id,
        account_id=other_account_id,
    )

    assert query_run is not None
    assert len(query_run.initial_answers) == 4
    assert all(
        answer.status == InitialAnswerStatus.COMPLETED for answer in query_run.initial_answers
    )
    assert other_query_run is None


def test_provider_failure_metadata_is_user_safe_and_non_secret() -> None:
    repository = InMemoryQueryRunRepository()
    account_id = uuid4()
    query_run_id = create_test_query_run(
        repository,
        account_id,
        "Force provider failure for redaction coverage",
    )

    query_run = repository.get_for_account(query_run_id=query_run_id, account_id=account_id)

    assert query_run is not None
    failed_answer = query_run.initial_answers[0]
    assert failed_answer.status == InitialAnswerStatus.FAILED
    assert failed_answer.error_code == "PROVIDER_UNAVAILABLE"
    assert failed_answer.provider_notice is not None
    serialized = failed_answer.model_dump_json()
    assert "sk-" not in serialized
    assert "provider_key" not in serialized
    assert "raw credentials" not in serialized.lower()
