"""The per-run evaluation memo is bounded and resettable (issue #284).

``_evaluate_terminal_run`` used to run the whole Layer-A engine on every
result read. It is memoised now, which introduces a process-global cache —
the same class of hazard as the cost event ring and the run-capacity
semaphore (AGENTS.md rule 16a). Three properties have to hold for that to be
safe: it can never grow without bound, a read refreshes an entry's position
so a hot run is not evicted first, and a test can empty it.

**Everything here drives the real ``_evaluate_terminal_run``**, not the
``_evaluation_memo_store`` helper. The first version of this file called the
helper directly, and measured: replacing the store call inside
``_evaluate_terminal_run`` with a bare ``_evaluation_memo[key] = result``
left **347 passed** across every touched test file while the real path grew
to ``memo size: 562, cap: 512``. A test that drives a helper proves things
about the helper.

Hermetic: builds ``QueryRun`` values directly and runs with the judge
unconfigured, so ``evaluate_run`` is called with ``judge=None`` and performs
no I/O at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.unit.test_evaluation_layer_a import _answer

from product_app import query_runs as qr
from product_app.config import settings
from product_app.costs import cost_estimation_service
from product_app.debate import AgreementSummary
from product_app.model_slots import validate_model_slots_with_search
from product_app.query_runs import QueryRun, QueryRunStatus

MODELS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]
AGREEMENT = AgreementSummary(aligned=1, total=1)

#: The cap this file runs the real path against. Deliberately NOT
#: ``_EVALUATION_MEMO_MAX``: rule 7a — a test parametrized over the constant
#: it tests cannot see that constant change. Measured on the first version of
#: this file, which used ``cap = qr._EVALUATION_MEMO_MAX``: raising
#: ``_EVALUATION_MEMO_MAX`` from 512 to 200000 left **29 passed**.
TEST_CAP = 5


@pytest.fixture(autouse=True)
def _bounded_memo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A 5-entry cap and an empty memo, restored afterwards.

    ``_EVALUATION_MEMO_MAX`` is a process global (rule 16a), so this must be
    a fixture that restores it or every later test inherits a 5-entry cache.
    """
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")
    monkeypatch.setattr(qr, "_EVALUATION_MEMO_MAX", TEST_CAP)
    qr._evaluation_memo_clear_for_tests()
    yield
    qr._evaluation_memo_clear_for_tests()


def _terminal_run(*, offset_seconds: int = 0) -> QueryRun:
    """A distinct terminal run — distinct ``query_run_id`` AND ``updated_at``."""
    slots = validate_model_slots_with_search(MODELS)
    stamp = datetime(2026, 8, 10, tzinfo=UTC) + timedelta(seconds=offset_seconds)
    return QueryRun(
        query_run_id=uuid4(),
        account_id=uuid4(),
        query_text="Compare transparent model answers",
        status=QueryRunStatus.COMPLETED,
        correlation_id="corr",
        created_at=stamp,
        updated_at=stamp,
        started_at=stamp,
        model_slots=slots,
        cost_estimate=cost_estimation_service.estimate(query_text="q", model_slots=slots),
        initial_answers=[_answer(slot=1)],
    )


def _key(run: QueryRun) -> qr._EvaluationMemoKey:
    return (str(run.query_run_id), run.updated_at, AGREEMENT.aligned, AGREEMENT.total)


def test_the_real_evaluation_path_never_grows_past_the_cap() -> None:
    """Six runs through ``_evaluate_terminal_run`` leave FIVE entries.

    Literals on both sides (rule 7a / rule 8b): the cap is pinned to 5 by
    the fixture and the assertion says 5, so neither the eviction loop nor
    the constant can move without this going red.

    RED if the ``popitem(last=False)`` eviction loop is removed from
    ``_evaluation_memo_store``, or if ``_evaluate_terminal_run`` writes the
    dict directly instead of calling it: the length reads 6.
    """
    runs = [_terminal_run(offset_seconds=index) for index in range(TEST_CAP + 1)]

    for run in runs:
        qr._evaluate_terminal_run(run, agreement=AGREEMENT)

    assert len(qr._evaluation_memo) == 5
    assert _key(runs[0]) not in qr._evaluation_memo
    assert _key(runs[-1]) in qr._evaluation_memo


def test_a_re_read_run_survives_the_arrival_that_evicts_a_cold_one() -> None:
    """The LRU partner: reading refreshes, so a hot run is not evicted first.

    Without this, ``_evaluation_memo`` degrades to FIFO and the run a user
    is actively polling is the one thrown away.

    RED if ``_evaluation_memo.move_to_end(key)`` is deleted from the
    memo-hit branch of ``_evaluate_terminal_run``: measured on the first
    version of this file, deleting it left **29 passed**. Here the oldest
    run is re-read and then a sixth arrives — with the refresh the SECOND
    run is evicted, without it the re-read first one is.
    """
    runs = [_terminal_run(offset_seconds=index) for index in range(TEST_CAP)]
    for run in runs:
        qr._evaluate_terminal_run(run, agreement=AGREEMENT)
    assert len(qr._evaluation_memo) == 5

    qr._evaluate_terminal_run(runs[0], agreement=AGREEMENT)
    qr._evaluate_terminal_run(_terminal_run(offset_seconds=99), agreement=AGREEMENT)

    assert len(qr._evaluation_memo) == 5
    assert _key(runs[0]) in qr._evaluation_memo, "the re-read run was evicted first"
    assert _key(runs[1]) not in qr._evaluation_memo, "the coldest run should have gone"


def test_a_second_read_of_one_run_comes_from_the_memo() -> None:
    """The POSITIVE PARTNER (rule 7) for the two bound tests above.

    Both assert that entries are ABSENT, which is trivially true over a memo
    that never stores anything. This one proves the store happens at all, by
    identity: the second read must be the very object the first produced.

    RED if ``_evaluate_terminal_run``'s memo-hit branch stops returning the
    cached value: the second read builds a new ``RunEvaluationResult`` and
    ``is`` fails.
    """
    run = _terminal_run()

    first = qr._evaluate_terminal_run(run, agreement=AGREEMENT)
    second = qr._evaluate_terminal_run(run, agreement=AGREEMENT)

    assert first is not None
    assert second is first
    assert len(qr._evaluation_memo) == 1


def test_the_evaluation_memo_can_be_emptied_between_tests() -> None:
    """The reset seam exists and actually empties the cache.

    Without it a memoised evaluation outlives the test that made it, and a
    later test reading the same run id sees another test's numbers.

    RED if ``_evaluation_memo_clear_for_tests`` stops clearing (e.g. its
    body becomes ``pass``): the entry written below survives.
    """
    qr._evaluate_terminal_run(_terminal_run(), agreement=AGREEMENT)
    assert len(qr._evaluation_memo) == 1

    qr._evaluation_memo_clear_for_tests()

    assert len(qr._evaluation_memo) == 0
