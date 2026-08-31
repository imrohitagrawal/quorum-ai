"""S2 per-run evaluation is persisted and served (FR-015, AC-041/042, NFR-011).

Drives real runs through the create endpoint (legacy inline path → synchronous
to terminal) with the stub provider pipeline, and asserts:

* the durable S1 row gets ``eval_json`` / ``trust_json`` attached AFTER the row
  exists, metrics only (no query text, no answer prose),
* ``GET /v1/query-runs/{id}`` serves an ``evaluation`` projection for terminal
  runs whose trust band is ``"unverified"`` with ``score is None`` — never a
  high-confidence number, because no real judge verified citation support,
* the served projection is byte-identical to the persisted one (one engine
  call site, no drift),
* a non-terminal run serves no evaluation,
* persistence is idempotent,
* a raising evaluation can never fail a user run,
* a full terminal run makes ZERO calls to the LLM judge seam (NFR-011).

Network-free: the sim pipeline runs locally and ``evaluate_run`` is called with
``judge=None``, so the provider seam is never touched.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.unit.test_evaluation_layer_a import REAL_URL, _answer, _source

from product_app import evaluation, run_history_store
from product_app import query_run_orchestration as qro
from product_app import query_runs as qr
from product_app.config import settings
from product_app.costs import cost_estimation_service
from product_app.debate import AgreementSummary, debate_event_recorder
from product_app.evaluation import (
    EVAL_SCHEMA_VERSION,
    LayerASignals,
    TrustDiagnostics,
    TrustScore,
    evaluate_run,
)
from product_app.main import app
from product_app.model_slots import validate_model_slots_with_search
from product_app.providers import provider_event_recorder, provider_execution_service
from product_app.query_runs import (
    QueryRunEvaluationProjection,
    QueryRunStatus,
    query_run_repository,
)
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis import synthesis_event_recorder

DEFAULT_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

QUERY_TEXT = "Compare transparent model answers"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the module to the local simulation pipeline, unconditionally.

    A developer ``.env`` with ``OPENROUTER_LIVE_EXECUTION_ENABLED=true`` and a
    real key makes the debate/synthesis stages attempt live provider calls,
    which would make these specs neither free nor deterministic. CI already
    exports the false value for the gates; this makes the module hermetic
    wherever it runs.
    """
    monkeypatch.setattr(settings, "openrouter_live_execution_enabled", False)
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "")


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    query_run_repository.clear()
    provider_event_recorder.clear()
    debate_event_recorder.clear()
    synthesis_event_recorder.clear()


def _acknowledged_request(query_text: str) -> dict[str, object]:
    return {
        "query_text": query_text,
        "model_slots": DEFAULT_MODEL_IDS,
        "safety_acknowledgements": [
            {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
        ],
    }


def _confirmed_request(
    client: TestClient, query_text: str, headers: dict[str, str]
) -> dict[str, object]:
    """ADR-0028: attach the confirmation round-trip a plain create now needs.

    The shipped DEFAULT_MODEL_IDS mix stays in ALLOW under ADR-0028 (MEASURED
    bound 0.1043), but this file's own fixture mix may not, so this
    defensively round-trips a confirmation whenever the estimate lands in
    require_confirmation (a no-op otherwise). None of the create calls below
    are testing the cost guardrail itself.
    """
    preview = client.post(
        "/v1/query-runs/estimate",
        json={"query_text": query_text, "model_slots": DEFAULT_MODEL_IDS},
        headers=headers,
    )
    cost_estimate = preview.json()["cost_estimate"]
    body = _acknowledged_request(query_text)
    if cost_estimate["threshold_action"] == "require_confirmation":
        body["cost_confirmation"] = {
            "estimated_cost_usd": cost_estimate["estimated_cost_usd"],
            "confirmation_token": cost_estimate["confirmation_token"],
        }
    return body


def _create_terminal_run(client: TestClient, account_id: Any) -> dict[str, Any]:
    headers = {"X-Account-Id": str(account_id)}
    response = client.post(
        "/v1/query-runs",
        json=_confirmed_request(client, QUERY_TEXT, headers),
        headers=headers,
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "completed"
    return body


def test_terminal_run_persists_metrics_only_evaluation() -> None:
    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()

        body = _create_terminal_run(client, account_id)

        row = store.get(body["query_run_id"])
        assert row is not None, "the S1 metrics row must exist before the evaluation attaches"
        assert row.eval_json is not None, "terminal run must have an evaluation attached"
        assert row.trust_json is not None

        assert row.eval_json["schema_version"] == EVAL_SCHEMA_VERSION
        assert row.eval_json["judge"] is None
        assert set(row.eval_json) == {
            "schema_version",
            "signals",
            "faithfulness_label",
            "hallucination_risk",
            "judge",
        }
        # OC-2: no verified support in a hermetic run ⇒ no number to serve.
        assert row.trust_json["support_verified"] is False
        assert row.trust_json["band"] == "unverified"
        assert row.trust_json["score"] is None

        # PII: metrics only — never the query text or answer prose.
        serialized = str(row)
        assert QUERY_TEXT not in serialized
        assert "rationale" not in serialized


def test_result_endpoint_serves_unverified_evaluation_for_a_terminal_run() -> None:
    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        created = _create_terminal_run(client, account_id)

        response = client.get(
            f"/v1/query-runs/{created['query_run_id']}",
            headers={"X-Account-Id": str(account_id)},
        )

        assert response.status_code == 200
        served = response.json()["evaluation"]
        assert served is not None, "a terminal run must serve an evaluation"
        assert served["schema_version"] == EVAL_SCHEMA_VERSION
        assert served["faithfulness_label"] in {"faithful", "unfaithful", "partial"}
        assert served["hallucination_risk"] in {"low", "medium", "high"}
        # DEBT-012 presentation guard is served on the projection.
        assert served["label_confidence"] in {"reportable", "indeterminate"}

        trust = served["trust"]
        assert trust["support_verified"] is False
        assert trust["band"] == "unverified"
        assert trust["score"] is None
        # The ONLY number in the trust payload is the explicitly-named
        # unverified diagnostic composite and its parts. Nothing a client
        # could read as a confidence figure may appear while support is
        # unverified — that suppression is the entire point of the slice.
        assert set(trust) == {"support_verified", "band", "score", "diagnostics"}
        assert set(trust["diagnostics"]) == {"layer_a_composite_unverified", "contributions"}
        for name, _value in _walk_numbers(served):
            assert name not in {
                "score",
                "confidence",
                "trust_score",
                "confidence_score",
                "trust",
            }, f"{name} is a confidence-shaped number served while support is unverified"

        # Judge prose is never served.
        assert "rationale" not in response.text
        # And the served projection is exactly what was persisted.
        row = store.get(created["query_run_id"])
        assert row is not None and row.eval_json is not None and row.trust_json is not None
        assert served["signals"] == row.eval_json["signals"]
        assert served["faithfulness_label"] == row.eval_json["faithfulness_label"]
        assert served["hallucination_risk"] == row.eval_json["hallucination_risk"]
        assert trust == row.trust_json


def _walk_numbers(payload: Any, key: str = "") -> list[tuple[str, float]]:
    """Every (key, numeric value) pair reachable in a JSON-ish payload."""
    if isinstance(payload, dict):
        found: list[tuple[str, float]] = []
        for child_key, child in payload.items():
            found.extend(_walk_numbers(child, child_key))
        return found
    if isinstance(payload, list):
        found = []
        for item in payload:
            found.extend(_walk_numbers(item, key))
        return found
    if isinstance(payload, bool):
        return []
    if isinstance(payload, (int, float)):
        return [(key, float(payload))]
    return []


def test_non_terminal_run_serves_no_evaluation() -> None:
    account_id = uuid4()
    model_slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(
        query_text="still running",
        model_slots=model_slots,
    )
    run = query_run_repository.create(
        account_id=account_id,
        query_text="still running",
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    assert not run.is_terminal

    assert qr._result_response(run).evaluation is None


def test_evaluation_persistence_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second persist rewrites identical bytes — and really runs.

    The re-persist is driven with a real ``UUID``: the in-memory repository
    keys on ``UUID``, so a ``str`` id raises ``KeyError`` inside
    ``_persist_terminal_run`` and is swallowed by its best-effort guard,
    which would make this whole spec vacuous (it would then re-read the same
    untouched row and pass even if a re-persist wiped the evaluation). The
    spy below is the anti-vacuity oracle: the evaluation write must actually
    execute a second time.
    """
    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        created = _create_terminal_run(client, account_id)
        first = store.get(created["query_run_id"])
        assert first is not None and first.eval_json is not None

        real_persist_evaluation = qr._persist_run_evaluation
        repersists: list[dict[str, Any]] = []

        def _spy(**kwargs: Any) -> None:
            repersists.append(kwargs)
            real_persist_evaluation(**kwargs)

        monkeypatch.setattr(qro, "_persist_run_evaluation", _spy)

        qr._persist_terminal_run(UUID(created["query_run_id"]))

        assert len(repersists) == 1, (
            "the re-persist under test never executed — this spec would pass "
            "even if the second write wiped eval_json/trust_json"
        )
        assert store.run_count() == 1
        second = store.get(created["query_run_id"])
        assert second is not None
        assert second.eval_json == first.eval_json
        assert second.trust_json == first.trust_json


def test_a_raising_evaluation_write_is_swallowed_at_the_module_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S1 parity: the wrapper swallows, the store method still raises.

    The method must keep raising so a bug surfaces in a test rather than
    hiding behind the guard; the wrapper is the single place the hot path is
    protected. Both directions are asserted here.
    """
    with run_history_store.configure_for_tests() as store:

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(store, "update_evaluation", _boom)

        with pytest.raises(RuntimeError):
            store.update_evaluation(str(uuid4()), eval_json={}, trust_json={})

        # The wrapper over the same failing store does not raise.
        run_history_store.update_evaluation(str(uuid4()), eval_json={}, trust_json={})

        # And a real run still completes end to end.
        client = TestClient(app)
        body = _create_terminal_run(client, uuid4())
        row = store.get(body["query_run_id"])
        assert row is not None
        assert row.eval_json is None


def test_a_raising_evaluation_cannot_fail_a_user_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**kwargs: Any) -> object:
        raise RuntimeError("evaluation engine exploded")

    monkeypatch.setattr(qro, "evaluate_run", _boom)

    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()

        body = _create_terminal_run(client, account_id)

        # The run still reaches terminal, the response is still served, and
        # the S1 metrics row is still written — only the evaluation is absent.
        row = store.get(body["query_run_id"])
        assert row is not None
        assert row.status == "completed"
        assert row.eval_json is None
        assert row.trust_json is None

        response = client.get(
            f"/v1/query-runs/{body['query_run_id']}",
            headers={"X-Account-Id": str(account_id)},
        )
        assert response.status_code == 200


def test_terminal_run_makes_zero_llm_judge_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """NFR-011: a full terminal run never touches the provider/judge seam.

    Two independent proofs, because either alone could pass for the wrong
    reason: the shared ``call_with_prompt`` seam records nothing at all, AND
    ``build_judge_evidence`` — which ``evaluate_run`` calls if and only if a
    judge is configured — is never entered.
    """
    calls: list[dict[str, Any]] = []
    evidence_builds: list[dict[str, Any]] = []

    def _spy(**kwargs: Any) -> None:
        calls.append(kwargs)
        return None

    def _evidence_spy(**kwargs: Any) -> None:
        evidence_builds.append(kwargs)
        raise AssertionError("judge evidence must never be built on the pipeline path")

    # Reduced to a bool in a SEPARATE statement, deliberately. pytest's
    # assertion rewriting reports INTERMEDIATE values, so `assert not
    # settings.<key>` prints the real key on failure — measured 2026-08-07,
    # the same primitive as that day's leak incident. Wrapping inline does not
    # help (`assert bool(...) is False` prints it too); only reducing to a
    # non-secret in its own statement does. Pinned by
    # tests/unit/test_no_credential_reaches_a_test_run.py.
    judge_key_present = bool(settings.quorum_eval_judge_api_key)
    assert judge_key_present is False
    monkeypatch.setattr(provider_execution_service, "call_with_prompt", _spy)
    monkeypatch.setattr(evaluation, "build_judge_evidence", _evidence_spy)

    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        body = _create_terminal_run(client, account_id)
        row = store.get(body["query_run_id"])
        assert row is not None and row.eval_json is not None

    assert calls == [], f"the evaluation path called the LLM seam {len(calls)} time(s)"
    assert evidence_builds == []


def _laundered_answers() -> list[Any]:
    """The DEBT-012 laundering shape: 1 resolving ordinal + 20 off-run links/slot."""
    fabricated = " ".join(
        f"[claim{i}](https://fabricated-{i}.example.org/paper)" for i in range(20)
    )
    return [
        _answer(
            slot=slot,
            text=f"Therapy reduces mortality by 42% [1]. {fabricated}",
            sources=[_source(REAL_URL)],
        )
        for slot in (1, 2, 3, 4)
    ]


def _terminal_run_with(client: TestClient, account_id: Any, answers: list[Any]) -> Any:
    """Create a run and force it terminal with the given initial answers."""
    model_slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=model_slots)
    run = query_run_repository.create(
        account_id=account_id,
        query_text=QUERY_TEXT,
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    run.initial_answers = answers
    run.final_synthesis = None
    run.status = QueryRunStatus.COMPLETED
    return run


def test_a_laundered_run_is_served_as_indeterminate() -> None:
    """The DEBT-012 laundering shape is served ``label_confidence: indeterminate``.

    Its engine labels are still ``faithful``/``low`` (unchanged), but it carries
    80 unverifiable off-run URL markers, so the presentation guard downgrades it.
    """
    client = TestClient(app)
    account_id = uuid4()
    run = _terminal_run_with(client, account_id, _laundered_answers())

    response = client.get(
        f"/v1/query-runs/{run.query_run_id}",
        headers={"X-Account-Id": str(account_id)},
    )
    assert response.status_code == 200
    served = response.json()["evaluation"]
    assert served is not None
    # The engine label is unchanged and still confident...
    assert served["faithfulness_label"] == "faithful"
    assert served["hallucination_risk"] == "low"
    assert served["signals"]["unverifiable_marker_count"] == 80
    # ...but the presentation guard closes the exposure.
    assert served["label_confidence"] == "indeterminate"


def test_the_persisted_eval_json_key_set_is_unchanged_by_the_new_signals() -> None:
    """The two new signals live INSIDE ``signals``; the top-level key set is frozen.

    ``label_confidence`` is a projection-only presentation fact and is NOT
    persisted, so ``set(eval_json)`` is untouched (D-8).
    """
    with run_history_store.configure_for_tests() as store:
        client = TestClient(app)
        account_id = uuid4()
        body = _create_terminal_run(client, account_id)

        row = store.get(body["query_run_id"])
        assert row is not None and row.eval_json is not None
        assert set(row.eval_json) == {
            "schema_version",
            "signals",
            "faithfulness_label",
            "hallucination_risk",
            "judge",
        }
        # The new signals are present INSIDE the signals sub-object...
        assert "unverifiable_marker_count" in row.eval_json["signals"]
        assert "unverifiable_marker_ratio" in row.eval_json["signals"]
        # ...and label_confidence is NEVER persisted (projection-only).
        assert "label_confidence" not in row.eval_json


def test_an_s2_eval_v2_row_missing_the_new_signals_is_presented_as_indeterminate() -> None:
    """A persisted ``s2-eval-v2`` row fails CLOSED (D-3 / D-7).

    Nothing re-validates on read, so an old row's signals lack the
    ``unverifiable_*`` keys — loading them back gives the DEFAULT
    ``unverifiable_marker_count == 0``, which a BLACKLIST (``count > 0``) would
    read as the CONFIDENT branch on a run of unknown provenance. The guard is a
    WHITELIST instead: ``label_confidence`` has NO default on the projection, so
    an ``s2`` row can never be served as ``reportable`` — the UI treats an absent
    value as ``indeterminate``.
    """
    # An s2-eval-v2 signals dict for a laundering-shaped run: faithful/low, but
    # WITHOUT the new unverifiable_* keys.
    s2_signals = {
        "citation_coverage_ratio": 1.0,
        "citation_marker_grounding": 1.0,
        "agreement_ratio": 1.0,
        "live_ratio": 1.0,
        "completeness": 1.0,
        "false_consensus_preserved": False,
        "polar_disagreement_detected": False,
        "disagreement_suppressed": False,
        "decision_support_framing_present": True,
        "high_stakes_warning_required": False,
        "high_stakes_warning_present": False,
        "uncertainty_surfaced": True,
        "refusal_detected": False,
        "run_wholly_refused": False,
    }
    loaded = LayerASignals.model_validate(s2_signals)
    # The trap: the additive default hides the laundering shape.
    assert loaded.unverifiable_marker_count == 0
    assert loaded.unverifiable_marker_ratio is None

    trust = TrustScore(
        support_verified=False,
        band="unverified",
        score=None,
        diagnostics=TrustDiagnostics(layer_a_composite_unverified=0.0, contributions=[]),
    )
    # Fail-closed: a projection cannot be built from an s2 row without an
    # explicit label_confidence — it raises rather than defaulting to reportable.
    with pytest.raises(ValidationError):
        QueryRunEvaluationProjection(  # type: ignore[call-arg]
            schema_version="s2-eval-v2",
            signals=loaded,
            faithfulness_label="faithful",
            hallucination_risk="low",
            trust=trust,
        )


def test_a_non_terminal_run_writes_nothing_and_logs_no_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D-10: the non-terminal early return writes nothing and logs no warning.

    ``_persist_run_evaluation`` on a non-terminal run must return before any
    store write or feedback event, and — critically — WITHOUT tripping the
    broad ``except`` that logs ``run evaluation persistence failed``. Deleting
    the ``if result is None: return`` guard makes ``result.eval_json()`` raise
    ``AttributeError`` on ``None``, which the guard swallows into that exact
    WARNING; the caplog assertion (b) is what makes this test bite.
    """
    account_id = uuid4()
    model_slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
    estimate = cost_estimation_service.estimate(query_text="still running", model_slots=model_slots)
    run = query_run_repository.create(
        account_id=account_id,
        query_text="still running",
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    assert not run.is_terminal

    update_calls: list[Any] = []
    feedback_calls: list[Any] = []
    monkeypatch.setattr(qro, "_update_run_evaluation", lambda *a, **k: update_calls.append((a, k)))
    monkeypatch.setattr(
        qro, "_record_feedback_event", lambda *a, **k: feedback_calls.append((a, k))
    )

    with caplog.at_level(logging.WARNING):
        qr._persist_run_evaluation(query_run=run, agreement=AgreementSummary(aligned=0, total=0))

    # (a) zero store writes, zero feedback events.
    assert update_calls == []
    assert feedback_calls == []
    # (b) no swallowed-exception warning — the load-bearing assertion.
    assert not any(
        "run evaluation persistence failed" in record.getMessage() for record in caplog.records
    )


# --------------------------------------------------------------------------
# Issue #284 — the evaluation is recomputed on every read.
#
# ``_evaluate_terminal_run`` is the ONE site both the persist path and the
# served projection go through. A terminal run cannot change its evaluation
# unless the run body itself changes, so recomputing it per GET is pure
# waste — and the waste lands on a plain ``def`` route, i.e. in the
# threadpool holding the GIL.
#
# These tests assert CARDINALITY (rule 6b): how many times the engine ran,
# never merely that the answer came back right. A clean-path value assertion
# passes for every implementation, including the wasteful one.
# --------------------------------------------------------------------------


def _counting_evaluate_run(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap ``query_runs.evaluate_run`` with a call counter.

    Counts the ENGINE call, not the memo wrapper, so the number is the real
    work done rather than the number of times a cache was consulted.
    """
    calls = [0]
    # ``query_runs`` imported this by value, so this IS the object it calls.
    real = evaluate_run

    def counted(**kwargs: Any) -> Any:
        calls[0] += 1
        return real(**kwargs)

    monkeypatch.setattr(qro, "evaluate_run", counted)
    return calls


def test_the_persist_path_evaluates_a_run_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creating a run runs the evaluation engine ONCE, not twice.

    ``_persist_terminal_run`` builds its response through
    ``_result_response`` -> ``_evaluation_projection`` and then calls
    ``_persist_run_evaluation``; both reach ``_evaluate_terminal_run``.

    RED if the memo lookup is removed from ``_evaluate_terminal_run``:
    measured before the fix, this counted 2.
    """
    with run_history_store.configure_for_tests():
        client = TestClient(app)
        calls = _counting_evaluate_run(monkeypatch)

        _create_terminal_run(client, uuid4())

        assert calls[0] == 1


def test_three_reads_of_one_terminal_run_evaluate_it_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N reads of a terminal run cost ZERO extra evaluations.

    The counter is installed AFTER the run is created, so it measures the
    READS alone. RED if the memo lookup is removed from
    ``_evaluate_terminal_run``: measured before the fix, this counted 3 —
    one full engine run per GET.
    """
    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        created = _create_terminal_run(client, account_id)
        headers = {"X-Account-Id": str(account_id)}

        calls = _counting_evaluate_run(monkeypatch)

        bodies = []
        for _ in range(3):
            response = client.get(f"/v1/query-runs/{created['query_run_id']}", headers=headers)
            assert response.status_code == 200
            bodies.append(response.json()["evaluation"])

        assert calls[0] == 0, "a terminal run that has not changed must not be re-evaluated"
        assert bodies[0] is not None
        assert bodies[0] == bodies[1] == bodies[2]


def test_an_answer_landing_after_the_run_turned_terminal_is_re_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The memo tracks the run; it does not freeze it.

    ``record_initial_answer`` has NO terminal guard (unlike ``update_status``,
    which refuses a terminal write), so a late answer CAN change the inputs
    of an already-terminal run. Today's per-read recompute self-corrects;
    a memo keyed on the run id alone would serve the stale evaluation
    forever. The key therefore carries ``updated_at``, which every mutator
    bumps.

    RED if the memo key is reduced to the run id alone: the second GET then
    serves the first GET's signals and the inequality below fails.

    HONEST LIMIT, measured: dropping ONLY ``updated_at`` from the key leaves
    this green, because a replaced answer also moves the agreement summary
    and the agreement is in the key too. The sibling test below isolates
    ``updated_at`` by holding the agreement fixed. This one is the
    end-to-end statement — what the READER is served after a late answer.
    """
    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        created = _create_terminal_run(client, account_id)
        headers = {"X-Account-Id": str(account_id)}
        run_id = UUID(created["query_run_id"])

        first = client.get(f"/v1/query-runs/{run_id}", headers=headers)
        assert first.status_code == 200
        before = first.json()["evaluation"]["signals"]

        query_run_repository.record_initial_answer(
            run_id,
            _answer(
                slot=1,
                text="A late claim ([elsewhere](https://off-run.test/page)) and [7].",
                sources=[_source(REAL_URL)],
            ),
        )

        calls = _counting_evaluate_run(monkeypatch)
        second = client.get(f"/v1/query-runs/{run_id}", headers=headers)
        assert second.status_code == 200
        after = second.json()["evaluation"]["signals"]

        assert calls[0] == 1, "a changed run must be re-evaluated exactly once"
        assert after != before


def test_a_late_answer_re_evaluates_even_when_the_agreement_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``updated_at`` alone must invalidate the memo.

    The end-to-end test above cannot prove this: replacing an answer through
    the HTTP path also moves the agreement summary, which is in the key for
    its own reason, so the key changes either way. Here the SAME
    ``AgreementSummary`` object is passed both times, so ``updated_at`` is
    the only part of the key the mutation can move.

    RED if ``query_run.updated_at`` is dropped from the memo key (measured:
    ``calls[0] == 1`` and ``second == first``). Verified by mutation that
    this is the only one of the two tests that catches it.
    """
    with run_history_store.configure_for_tests():
        client = TestClient(app)
        account_id = uuid4()
        created = _create_terminal_run(client, account_id)
        run_id = UUID(created["query_run_id"])
        run = query_run_repository.get_for_account(query_run_id=run_id, account_id=account_id)
        assert run is not None and run.is_terminal
        agreement = AgreementSummary(aligned=1, total=len(run.initial_answers))

        calls = _counting_evaluate_run(monkeypatch)
        first = qr._evaluate_terminal_run(run, agreement=agreement)
        # Same run, same agreement, nothing changed: no second engine run.
        assert qr._evaluate_terminal_run(run, agreement=agreement) is first
        assert calls[0] == 1

        query_run_repository.record_initial_answer(
            run_id,
            _answer(
                slot=1,
                text="A late claim ([elsewhere](https://off-run.test/page)) and [7].",
                sources=[_source(REAL_URL)],
            ),
        )

        second = qr._evaluate_terminal_run(run, agreement=agreement)

        assert calls[0] == 2, "a run whose body changed must be evaluated again"
        assert second is not None and first is not None
        assert second.evaluation.signals != first.evaluation.signals


def test_a_slot_that_never_recorded_an_answer_is_reflected_in_the_persisted_completeness() -> None:
    """#380, wired end to end through the real persist path.

    This drives ``model_slots`` through the same
    ``validate_model_slots_with_search`` construction a real create uses, then
    simulates the three "never recorded" paths in
    ``query_run_orchestration.py`` (a slot lost to a worker timeout, an
    unexpected future failure, or ``_should_stop`` mid-turn) by simply never
    calling ``record_initial_answer`` for slot 4 — the run turns COMPLETED
    with 4 requested slots and 3 recorded answers.

    RED IF: ``_persist_run_evaluation``'s call into ``evaluate_run`` stops
    passing ``requested_slot_count=len(query_run.model_slots)`` — the
    persisted ``completeness``/``live_ratio`` would then read ``1.0`` instead
    of the correct ``0.75``, silently reporting a complete run as complete
    when a quarter of it never answered.
    """
    with run_history_store.configure_for_tests() as store:
        slots = validate_model_slots_with_search(DEFAULT_MODEL_IDS)
        estimate = cost_estimation_service.estimate(query_text=QUERY_TEXT, model_slots=slots)
        run = query_run_repository.create(
            account_id=uuid4(),
            query_text=QUERY_TEXT,
            model_slots=slots,
            cost_estimate=estimate,
        )
        for slot_number in (1, 2, 3):
            query_run_repository.record_initial_answer(run.query_run_id, _answer(slot=slot_number))
        run = query_run_repository.get(run.query_run_id)
        assert run is not None
        assert len(run.model_slots) == 4
        assert len(run.initial_answers) == 3, "the fixture must genuinely lose one slot"
        run.status = QueryRunStatus.COMPLETED

        qr._persist_terminal_run(run.query_run_id)

        row = store.get(str(run.query_run_id))
        assert row is not None and row.eval_json is not None
        assert row.eval_json["signals"]["completeness"] == pytest.approx(0.75)
        assert row.eval_json["signals"]["live_ratio"] == pytest.approx(0.75)
