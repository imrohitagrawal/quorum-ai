"""F-06: a billed call must never vanish from a receipt served as ``measured``.

These drive the REAL ``run_debate_rounds`` / ``produce_final_synthesis`` through
the ``product_app.providers.urlopen`` seam (network-free, $0) and then feed the
resulting usage lists to the REAL ``_actual_cost``, so they exercise the whole
producer→gate chain rather than the gate alone.

The defect: ``_actual_cost``'s gates are
``all(usage is not None for ... in <list>)`` and ``all([])`` is True. A billed
call that is never APPENDED is therefore invisible — unlike one appended as
``None``, which the gate catches. Before the fix a provider response that
consumed tokens but carried no usable content was collapsed to ``None`` and
dropped, so the run was served ``cost_source="measured"`` with those dollars
missing.

Every assertion here is CARDINALITY (POSTs actually issued vs usage entries
recorded), because a clean-path outcome assertion is exactly what let this
survive: the pre-existing suite asserted *that* a run was measured, never *how
many* calls the measurement covered.
"""

from __future__ import annotations

import http.client
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from product_app import config
from product_app.costs import CostEstimate, CostThresholdAction
from product_app.debate import DebateOutput, DebateRoundStatus, debate_stub_service
from product_app.model_slots import ModelSlot
from product_app.providers import (
    CitationCoverage,
    InitialAnswerStatus,
    InitialModelAnswer,
    ProviderPath,
    SourceReference,
    TokenUsage,
)
from product_app.query_runs import BillableStage, StageBillingState, _actual_cost
from product_app.synthesis import synthesis_stub_service

_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]

#: The provider's OWN statement of what it consumed. Its presence is what makes
#: "this call was billed" a measurement rather than a guess.
_BILLED = {"prompt_tokens": 4000, "completion_tokens": 700, "total_tokens": 4700}


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _install_provider(
    monkeypatch: pytest.MonkeyPatch, content: object, *, with_usage: bool = True
) -> list[int]:
    """Every POST returns 200 with ``content``. Counts POSTs actually issued.

    ``with_usage=False`` drops the ``usage`` object, which is the difference
    between a billed call we can PRICE and one we can only RECORD.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    posts = [0]
    body: dict[str, Any] = {
        # A real truncation: the model hit the section/round token cap having
        # emitted no message content. The tokens were consumed.
        "choices": [{"finish_reason": "length", "message": {"content": content}}],
    }
    if with_usage:
        # ...and the provider says so, in the same response body.
        body["usage"] = _BILLED

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        posts[0] += 1
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return posts


def _install_raising_provider(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException, *, on_read: bool
) -> list[int]:
    """Every POST fails with ``exc`` — during the body read, or at connect."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    posts = [0]

    class _TornResponse:
        def read(self) -> bytes:
            raise exc

        def __enter__(self) -> _TornResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_urlopen(request: Any, timeout: float = 0) -> _TornResponse:
        posts[0] += 1
        if not on_read:
            raise exc
        return _TornResponse()

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return posts


def _coverage() -> CitationCoverage:
    return CitationCoverage(
        material_claim_count=1,
        cited_claim_count=1,
        coverage_ratio=Decimal("1"),
        target_met=True,
    )


def _captured_initial_answers() -> list[InitialModelAnswer]:
    """Four slots that PASS the strict ``initial_fully_captured`` gate.

    This is what makes the test decisive: the run is otherwise perfectly
    measurable, so the label turns solely on the debate/synthesis lists.
    """
    return [
        InitialModelAnswer(
            slot_number=i + 1,
            model_id=mid,
            display_name=mid,
            answer_text="An answer.",
            sources=[
                SourceReference(
                    title="s",
                    url="https://example.com",
                    provider=ProviderPath.OPENROUTER_SEARCH,
                )
            ],
            provider_attempt_order=[ProviderPath.OPENROUTER_SEARCH],
            provider_path=ProviderPath.OPENROUTER_SEARCH,
            fallback_used=False,
            status=InitialAnswerStatus.COMPLETED,
            latency_ms=10,
            citation_coverage=_coverage(),
            token_usage=TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500),
        )
        for i, mid in enumerate(_MODEL_IDS)
    ]


def _debate_outputs() -> list[DebateOutput]:
    return [
        DebateOutput(
            round_number=n,
            focus_areas=["disagreement"],
            critique_text="critique",
            status=DebateRoundStatus.COMPLETED,
        )
        for n in (1, 2)
    ]


def _run(
    *,
    debate_call_usages: list[tuple[int, TokenUsage | None]],
    synthesis_call_usages: list[TokenUsage | None],
    debate_stage: StageBillingState = StageBillingState.RECORDED,
    synthesis_stage: StageBillingState = StageBillingState.RECORDED,
) -> SimpleNamespace:
    """A run shaped exactly as ``_actual_cost`` reads it.

    Both E2 ``billing_stages`` markers default to ``RECORDED``: every driver
    above runs its stage to completion and hands back the list the pipeline
    would record, so the handshake genuinely closed. ``RECORDED`` is also the
    only one of the three states under which the usage-list assertions below
    are load-bearing — ``NOT_ENTERED`` would wave an empty list through and
    ``ENTERED`` would block regardless of the list.
    """
    return SimpleNamespace(
        cost_estimate=CostEstimate(
            estimated_cost_usd=Decimal("0.0200"),
            threshold_action=CostThresholdAction.ALLOW,
            confirmation_token=None,
            reasons=[],
        ),
        model_slots=[ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(_MODEL_IDS)],
        initial_answers=_captured_initial_answers(),
        debate_call_usages=debate_call_usages,
        synthesis_call_usages=synthesis_call_usages,
        billing_stages={
            BillableStage.DEBATE: debate_stage,
            BillableStage.SYNTHESIS: synthesis_stage,
        },
    )


def _drive_debate() -> Any:
    return debate_stub_service.run_debate_rounds(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_captured_initial_answers(),
        openrouter_key="sk-or-test-live",
    )


def _drive_synthesis() -> Any:
    return synthesis_stub_service.produce_final_synthesis(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options",
        initial_answers=_captured_initial_answers(),
        debate_outputs=_debate_outputs(),
        openrouter_key="sk-or-test-live",
    )


# --- the defect: billed, unusable, and previously invisible -------------------


def test_billed_debate_calls_with_no_content_are_recorded_and_priced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty completion that reported usage is CHARGED, not merely recorded.

    EXPECTATION CHANGED from ``estimated`` to ``measured`` (F-06 finding C).
    ``_post_openrouter`` used to hit ``if not content: return None`` one frame
    BEFORE ``usage = _extract_usage(parsed)``, so the provider's own statement
    of the charge was discarded and the best the run could do was downgrade.
    The usage is now extracted first, so these dollars are in the bill —
    strictly more honest than the downgrade this test used to assert. The
    unmeasurable case (no ``usage`` object) still forces ``estimated`` and is
    asserted immediately below.
    """
    posts = _install_provider(monkeypatch, None)
    result = _drive_debate()

    assert posts[0] == 2, "expected both debate rounds to dispatch a billed POST"
    # CARDINALITY: one entry per BILLED call. Before F-06 this was 0 entries
    # for 2 billed calls, and `all([])` then passed vacuously.
    assert len(result.live_call_usages) == posts[0]
    assert all(usage is not None for _, usage in result.live_call_usages)

    run = _run(debate_call_usages=result.live_call_usages, synthesis_call_usages=[])
    total, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    stages = {line.stage: line.usd for line in breakdown.by_stage}
    assert stages["debate_round_1"] > Decimal("0")
    assert stages["debate_round_2"] > Decimal("0")
    assert total > Decimal("0")


def test_billed_debate_calls_with_no_content_and_no_usage_force_estimated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same billed calls, but the provider omitted ``usage``: unpriceable.

    The entry is still RECORDED — that is what stops ``all([])`` from passing
    vacuously — and its ``None`` is what forces the honest downgrade.
    """
    posts = _install_provider(monkeypatch, None, with_usage=False)
    result = _drive_debate()

    assert posts[0] == 2
    assert len(result.live_call_usages) == posts[0]
    assert result.live_call_usages == [(1, None), (2, None)]

    run = _run(debate_call_usages=result.live_call_usages, synthesis_call_usages=[])
    total, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    # The run is otherwise fully captured, so the label turns entirely on the
    # debate list. A call we cannot price must never be served as measured.
    assert source == "estimated"
    assert total == Decimal("0.0200"), "the served figure is the pre-run estimate"


def test_billed_synthesis_calls_with_no_content_are_recorded_and_priced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis sibling of the debate case above; see it for why ``measured``."""
    posts = _install_provider(monkeypatch, None)
    result = _drive_synthesis()

    assert posts[0] == 5, "expected all five synthesis sections to dispatch a billed POST"
    assert len(result.live_call_usages) == posts[0]
    assert all(usage is not None for usage in result.live_call_usages)

    run = _run(debate_call_usages=[], synthesis_call_usages=result.live_call_usages)
    total, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    assert {line.stage: line.usd for line in breakdown.by_stage}["synthesis"] > Decimal("0")
    assert total > Decimal("0")


def test_billed_synthesis_calls_with_no_content_and_no_usage_force_estimated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _install_provider(monkeypatch, None, with_usage=False)
    result = _drive_synthesis()

    assert posts[0] == 5
    assert len(result.live_call_usages) == posts[0]
    assert result.live_call_usages == [None] * 5

    run = _run(debate_call_usages=[], synthesis_call_usages=result.live_call_usages)
    _, _, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


# --- finding A: an exception AFTER the provider billed erased every call -----


@pytest.mark.parametrize(
    ("label", "exc", "on_read"),
    [
        (
            "torn-body",
            http.client.IncompleteRead(b'{"choices":[{"message":{"content":"par'),
            True,
        ),
        ("remote-disconnected", http.client.RemoteDisconnected("closed"), True),
        ("read-timeout", TimeoutError("read timed out"), True),
        ("http-503", HTTPError("https://x/y", 503, "unavailable", None, None), False),  # type: ignore[arg-type]
    ],
)
def test_a_billed_call_lost_to_an_exception_is_still_recorded(
    monkeypatch: pytest.MonkeyPatch, label: str, exc: BaseException, on_read: bool
) -> None:
    """The vacuous gate, closed on the exception route.

    Measured before the fix, via this exact seam:
    ``POSTs billed=5  usage entries=0  cost_source=measured  total=$0.0051``.
    ``IncompleteRead`` / ``RemoteDisconnected`` / ``ssl.SSLError`` are none of
    ``URLError`` / ``TimeoutError`` / ``HTTPError`` / ``JSONDecodeError``, so
    the exception escaped ``_post_openrouter``, escaped ``call_with_prompt``,
    and ``_safe_section_result`` swallowed it into ``live=None`` — no entry at
    all, and ``all([])`` is True.
    """
    posts = _install_raising_provider(monkeypatch, exc, on_read=on_read)
    result = _drive_synthesis()

    assert posts[0] == 5, f"{label}: all five sections dispatched a POST"
    # CARDINALITY: entries == POSTs. This was 0 == 5 before the fix.
    assert len(result.live_call_usages) == posts[0]
    assert result.live_call_usages == [None] * 5

    run = _run(debate_call_usages=[], synthesis_call_usages=result.live_call_usages)
    total, _breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated", f"{label}: a charge we cannot price is not a measurement"
    assert total == Decimal("0.0200")


def test_a_debate_exception_no_longer_escapes_the_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Debate has no ``_safe_section_result``, so the exception took the RUN.

    Before the fix ``run_debate_rounds`` raised ``IncompleteRead`` outright:
    ``record_debate_outputs`` was never reached, ``debate_call_usages`` stayed
    ``[]``, and the vacuous gate served ``measured`` from a run that had died.
    """
    posts = _install_raising_provider(
        monkeypatch,
        http.client.IncompleteRead(b'{"choices":[{"message":{"content":"par'),
        on_read=True,
    )
    result = _drive_debate()

    assert posts[0] == 2
    assert len(result.live_call_usages) == posts[0]
    assert result.live_call_usages == [(1, None), (2, None)]
    # The templated critique is served rather than the run dying.
    assert [output.round_number for output in result.debate_outputs] == [1, 2]

    run = _run(debate_call_usages=result.live_call_usages, synthesis_call_usages=[])
    _, _, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "estimated"


# --- finding B: a provably UNBILLED failure must not downgrade anything ------


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429])
def test_a_rejected_request_records_nothing_and_keeps_the_run_measured(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """The regression ec5c853 introduced, closed.

    A stale ``debate_model_id`` gives HTTP 404 "No endpoints found for model":
    nothing is inferred and nothing is billed. ec5c853 recorded ``(1, None),
    (2, None)`` anyway, so a perfectly measurable run flipped to ``estimated``
    and the SERVED figure inflated from the measured $0.0051 to the pre-run
    estimate $0.0246 — pricing seven calls that were never made, a ~4.8x
    overstatement. On origin/main that case was correctly ``measured``.
    """
    posts = _install_raising_provider(
        monkeypatch,
        HTTPError("https://openrouter.ai/api/v1/chat/completions", status, "no", None, None),  # type: ignore[arg-type]
        on_read=False,
    )
    result = _drive_debate()

    assert posts[0] == 2, "both rounds attempted; both were refused"
    # CARDINALITY, the other direction: a refused request is NOT a billed call.
    assert result.live_call_usages == []

    run = _run(debate_call_usages=result.live_call_usages, synthesis_call_usages=[])
    total, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured", f"HTTP {status} bills nothing; it cannot make a run unmeasurable"
    assert breakdown is not None
    # The served figure is the MEASURED initial-answer cost, not the estimate.
    assert total != Decimal("0.0200")
    assert total > Decimal("0")
    assert {line.stage for line in breakdown.by_stage} >= {"initial_answers"}


def test_billed_call_with_blank_content_keeps_its_usage_and_is_priced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace content: the usage object DID reach us, so the dollars count.

    ``_post_openrouter`` returns the raw message content, so ``"   "`` yields a
    real ``LiveProviderResult`` carrying ``usage``. Here the honest answer is not
    to downgrade but to CHARGE for it — the call is billed, priced, and included.
    """
    posts = _install_provider(monkeypatch, "   \n  ")
    result = _drive_debate()

    assert posts[0] == 2
    assert len(result.live_call_usages) == posts[0]
    # The usage survived, so every entry is priceable.
    assert all(usage is not None for _, usage in result.live_call_usages)

    run = _run(debate_call_usages=result.live_call_usages, synthesis_call_usages=[])
    total, breakdown, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
    assert breakdown is not None
    # And the debate tokens are actually in the bill, not silently zero.
    assert total > Decimal("0")


# --- control: the harness measures the product, not the fake -----------------


def test_control_healthy_live_calls_are_recorded_and_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this, the tests above could pass on a harness that never calls."""
    posts = _install_provider(monkeypatch, "A usable critique with substance.")
    result = _drive_debate()

    assert posts[0] == 2
    assert len(result.live_call_usages) == posts[0]
    assert all(usage is not None for _, usage in result.live_call_usages)

    run = _run(debate_call_usages=result.live_call_usages, synthesis_call_usages=[])
    _, _, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"


# --- scope pin: PARTIAL-run labelling is NOT changed by this fix -------------


def test_actual_cost_ignores_run_status_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin, do not change, the fact that ``_actual_cost`` never reads status.

    A PARTIAL/cancelled run whose captured calls are all present is still
    labelled ``measured``, because the gate looks only at capture completeness.
    Whether that SHOULD gate on a clean terminal status is a separate decision
    (deliberately out of scope for this billing-cardinality fix); this test
    exists so the F-06 change cannot move it silently.
    """
    posts = _install_provider(monkeypatch, "A usable critique with substance.")
    result = _drive_debate()
    assert posts[0] == 2

    run = _run(debate_call_usages=result.live_call_usages, synthesis_call_usages=[])
    run.status = "partial"  # _actual_cost does not consult this attribute at all

    _, _, source = _actual_cost(run)  # type: ignore[arg-type]
    assert source == "measured"
