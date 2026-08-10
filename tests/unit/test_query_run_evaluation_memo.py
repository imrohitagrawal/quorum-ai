"""The per-run evaluation memo is bounded and resettable (issue #284).

``_evaluate_terminal_run`` used to run the whole Layer-A engine on every
result read. It is memoised now, which introduces a process-global cache —
the same class of hazard as the cost event ring and the run-capacity
semaphore (AGENTS.md rule 16a). Two properties have to hold for that to be
safe: it can never grow without bound, and a test can empty it.

Hermetic: builds ``RunEvaluationResult`` values directly, no app, no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tests.unit.test_evaluation_layer_a import _answer

from product_app import query_runs as qr
from product_app.debate import AgreementSummary
from product_app.evaluation import RunEvaluationResult, evaluate_run


def _result() -> RunEvaluationResult:
    return evaluate_run(
        initial_answers=[_answer()],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=1, total=1),
    )


def _keys(count: int) -> list[qr._EvaluationMemoKey]:
    base = datetime(2026, 8, 10, tzinfo=UTC)
    return [(str(uuid4()), base + timedelta(seconds=index), 1, 1) for index in range(count)]


def test_the_evaluation_memo_evicts_its_oldest_entry_at_the_cap() -> None:
    """One entry over the cap drops the oldest, never the newest.

    RED if the ``popitem(last=False)`` eviction loop is removed from
    ``_evaluate_terminal_run``'s memo write: the length then grows past
    ``_EVALUATION_MEMO_MAX`` and the first key survives.
    """
    qr._evaluation_memo_clear_for_tests()
    cap = qr._EVALUATION_MEMO_MAX
    result = _result()
    keys = _keys(cap + 1)

    for key in keys:
        qr._evaluation_memo_store(key, result)

    assert len(qr._evaluation_memo) == cap
    assert keys[0] not in qr._evaluation_memo
    assert keys[-1] in qr._evaluation_memo


def test_the_evaluation_memo_can_be_emptied_between_tests() -> None:
    """The reset seam exists and actually empties the cache.

    Without it a memoised evaluation outlives the test that made it, and a
    later test reading the same run id sees another test's numbers.

    RED if ``_evaluation_memo_clear_for_tests`` stops clearing (e.g. its
    body becomes ``pass``): the entry written below survives.
    """
    qr._evaluation_memo_clear_for_tests()
    key = _keys(1)[0]
    qr._evaluation_memo_store(key, _result())
    assert len(qr._evaluation_memo) == 1

    qr._evaluation_memo_clear_for_tests()

    assert len(qr._evaluation_memo) == 0
