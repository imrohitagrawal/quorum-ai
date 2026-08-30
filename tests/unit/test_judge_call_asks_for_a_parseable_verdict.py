"""The Layer-B judge must ask for output it can actually parse.

MEASURED against the live OpenRouter API on 2026-08-07, with the pinned judge
model ``openai/gpt-5-mini`` and real production-sized evidence built from
``tests/evals/golden/cases`` (prompt 757-1207 tokens, 4 answers + 5 synthesis
sections — the shape a real run produces).

**What ships today cannot work.** ``gpt-5-mini`` is a REASONING model: its
reasoning tokens are billed as completion tokens and count against
``max_tokens``. At the shipped cap of 512, on three real golden cases:

    case                          reasoning  completion  finish   content  conforms
    grounded-consensus                  512         512  length   EMPTY    no
    fabricated-citation-launder         512         512  length   EMPTY    no
    human-tax-deduction                 384         512  length   truncated no

Three calls, **$0.003931 billed, zero usable verdicts**. The entire budget went
to reasoning and the model never emitted a verdict. This is almost certainly
what issue #258 recorded as "the judge cost $0.0109 and changed nothing a user
can see".

**Two parameters fix it, and were measured to.** With
``reasoning: {"effort": "low"}`` and ``response_format: {"type":"json_object"}``
over all ten golden cases at the SAME 512 cap: **10/10 conforming**,
``finish_reason: stop`` every time, reasoning 128-256, completion 266-417 —
and CHEAPER, $0.0009 per call against $0.0013.

Sending ``reasoning`` is safe for a non-reasoning judge model too: measured,
``openai/gpt-4o-mini`` accepts it with HTTP 200 and returns content normally,
so no per-model gating is needed.

These tests assert on the BYTES ON THE WIRE, not on what was passed to a helper
— the defect was in what the API received.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.provider_wire import sse_from_completion

from product_app.config import Settings, settings
from product_app.evaluation import EvalJudgeService, JudgeEvidence
from product_app.providers import provider_execution_service


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


_VERDICT = {
    "faithfulness": 4,
    "grounding": 4,
    "disagreement_preserved": True,
    "hallucination_risk": "low",
    "rationale": "Fine.",
    "model_id": "openai/gpt-5-mini",
}


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the JSON body of every request that reaches the transport."""
    bodies: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        bodies.append(json.loads(request.data.decode()))
        return _FakeResponse(
            sse_from_completion(
                {
                    "choices": [{"message": {"content": json.dumps(_VERDICT)}}],
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 300,
                        "total_tokens": 1300,
                    },
                }
            )
        )

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return bodies


def _enable_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key")
    monkeypatch.setattr(settings, "quorum_eval_judge_model_id", "openai/gpt-5-mini")


def _evidence() -> JudgeEvidence:
    return JudgeEvidence(
        query_text="A question",
        source_lines=("- A source (https://example.org/a)",),
        answer_texts=("An answer with a claim [1].",),
        synthesis_sections=(("consensus", "The panel agrees [1]."),),
    )


def _judge_body(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _enable_judge(monkeypatch)
    bodies = _capture(monkeypatch)
    verdict = EvalJudgeService().evaluate(_evidence())
    assert verdict is not None, "the judge produced no verdict; the seam never returned"
    assert len(bodies) == 1, f"expected exactly one request, saw {len(bodies)}"
    return bodies[0]


# ---------------------------------------------------------------------------
# The two parameters, on the wire
# ---------------------------------------------------------------------------


def test_the_judge_asks_for_strict_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The output contract is strict JSON and ``parse_judge_verdict`` does no
    repair, so asking the API to enforce it is free reliability.

    MEASURED: OpenRouter honours it — every conforming reply over ten golden
    cases came back as bare JSON with no markdown fence.

    WHAT TURNS THIS RED: stop sending ``response_format`` on the judge call.
    """
    body = _judge_body(monkeypatch)
    assert body.get("response_format") == {"type": "json_object"}


def test_the_judge_caps_reasoning_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this the judge is structurally unable to answer.

    A reasoning model spends completion tokens thinking BEFORE emitting
    content, and those count against ``max_tokens``. Measured at the shipped
    512 cap on real golden evidence: 512 reasoning tokens, 0 content, three for
    three, all billed.

    WHAT TURNS THIS RED: stop sending ``reasoning`` on the judge call.
    """
    body = _judge_body(monkeypatch)
    assert body.get("reasoning") == {"effort": "low"}


def test_the_judge_still_sends_what_it_always_did(monkeypatch: pytest.MonkeyPatch) -> None:
    """POSITIVE PARTNER: the new keys are ADDITIONS. If a future edit replaced
    the payload wholesale, the two assertions above could pass while the model,
    the prompt or the token cap went missing.

    Red if any of the original four payload keys stops being sent.
    """
    body = _judge_body(monkeypatch)
    assert body["model"] == "openai/gpt-5-mini"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "EVIDENCE" in body["messages"][1]["content"]
    assert body["max_tokens"] == settings.quorum_eval_judge_max_tokens


# ---------------------------------------------------------------------------
# Blast radius: debate and synthesis must be untouched
# ---------------------------------------------------------------------------


def test_a_non_judge_call_sends_neither_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller that asks for neither parameter must send neither.

    Red if the parameters are added to ``_post_messages`` unconditionally
    rather than passed per-call.

    This docstring used to say the debate and synthesis stages "feed the VISUAL
    BASELINE lane" and that their payloads "must not move at all". Both halves
    were wrong and #354 is what surfaced it. The visual lane drives Playwright
    against route-mocked responses (``e2e/fixtures/golden-run.ts`` fulfils
    ``/v1/query-runs/...`` itself), so no provider request is made on it and no
    payload of any kind reaches a pixel. And the debate payload has now moved on
    purpose: it carries ``response_format`` so the moderator answers in a shape
    the consensus gate can read. What this test actually pins is narrower and
    still worth pinning — the forwarding is PER-CALL, so a caller that wants
    neither parameter gets neither, which keeps the fixed-signature
    ``_post_messages`` doubles working.

    Scope, stated so the next reader does not inherit more assurance than exists:
    this watches TWO NAMED KEYS on the transport, not the full key set. No test
    anywhere asserts the complete set of keys on an outbound provider body, so a
    future cost-bearing key would be caught by nothing here. Pre-existing, and
    deliberately not fixed in this change (AGENTS rule 17, one concern per pull
    request).
    """
    bodies = _capture(monkeypatch)
    result = provider_execution_service.call_with_prompt(
        openrouter_key="sk-not-a-real-key",
        model_id="vendor/writer",
        system_prompt="Write a synthesis.",
        user_prompt="Some answers.",
        max_tokens=700,
    )
    assert result is not None
    assert len(bodies) == 1
    body = bodies[0]
    assert "response_format" not in body, "a non-judge call now asks for JSON output"
    assert "reasoning" not in body, "a non-judge call now sets reasoning effort"
    # POSITIVE PARTNER (rule 7): the thing being guarded must EXIST, or this
    # passes against source where the feature was never written — review proved
    # it does, by running this file against the parent commit. So assert on the
    # SAME transport that a judge call DOES carry both keys.
    assert body["model"] == "vendor/writer"
    assert body["max_tokens"] == 700
    judge_body = _judge_body(monkeypatch)
    assert judge_body["response_format"] == {"type": "json_object"}
    assert judge_body["reasoning"] == {"effort": "low"}


def test_a_non_judge_call_reaches_the_transport_with_an_unchanged_SIGNATURE(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The payload is not the only thing that must not move — the CALL must not.

    ``_post_messages`` is doubled by several pre-existing tests whose fakes take
    a fixed keyword signature, so passing ``response_format=None`` explicitly
    would break them even though the wire payload would be identical. That is
    exactly what happened while building this change: seven tests went red.

    Review then showed the guard was unpinned — deleting the conditional
    forwarding in ``_post_openrouter`` left every other test in this file GREEN,
    because they all watch ``urlopen`` and can only see the payload. This test
    watches the CALL.

    WHAT TURNS THIS RED: forward ``response_format``/``reasoning`` to
    ``_post_messages`` unconditionally instead of building the ``extra`` dict.
    """
    seen: list[set[str]] = []
    real = provider_execution_service._post_messages

    def spy(**kwargs: Any) -> Any:
        seen.append(set(kwargs))
        return real(**kwargs)

    monkeypatch.setattr(provider_execution_service, "_post_messages", spy)
    _capture(monkeypatch)

    provider_execution_service.call_with_prompt(
        openrouter_key="sk-not-a-real-key",
        model_id="vendor/writer",
        system_prompt="Write a synthesis.",
        user_prompt="Some answers.",
        max_tokens=700,
    )
    assert seen == [{"openrouter_key", "model_id", "messages", "max_tokens"}], (
        f"a non-judge call now reaches _post_messages with {seen}; the new "
        "parameters must be forwarded ONLY when set"
    )

    # POSITIVE PARTNER: the judge call on the same seam DOES carry them, so
    # this pins conditional forwarding rather than the feature being absent.
    seen.clear()
    _enable_judge(monkeypatch)
    EvalJudgeService().evaluate(_evidence())
    assert seen == [
        {"openrouter_key", "model_id", "messages", "max_tokens", "response_format", "reasoning"}
    ], f"the judge call did not carry the new parameters: {seen}"


# ---------------------------------------------------------------------------
# The token budget, derived from the measurement
# ---------------------------------------------------------------------------


def test_the_token_cap_clears_the_measured_worst_case() -> None:
    """The cap must leave room for reasoning AND the verdict.

    Literals on both sides (rule 7a) — this must not be derived from the
    constant it checks. 417 is the largest completion observed across
    **fourteen** calls at ``effort: low`` — ten golden cases, three toy-prompt
    trials, and the end-to-end call through the shipped path:

        266 271 281 285 292 294 314 315 326 334 366 389 405 417
        (14 values, max 417)

    An earlier version said "thirteen" and printed twelve numbers, having
    dropped two measurements from the published list. Review counted them.

    The shipped cap must clear that with real headroom, because the tail at
    LARGER evidence than the golden set is **unmeasured** — ADR-0017 bounds a
    worst-case judge prompt at ~23,000 tokens against the golden set's 1,207,
    and reasoning may scale with it. Erring high costs a fraction of a cent;
    erring low costs the entire verdict, silently.

    WHAT TURNS THIS RED: lower ``quorum_eval_judge_max_tokens`` below 1024.
    """
    # The CODE DEFAULT, not ``settings.…`` — ``config.py`` reads ``.env``, so
    # asserting the live setting would red this test on any machine whose
    # ``.env`` pins a different value, for reasons unrelated to the diff.
    assert Settings.model_fields["quorum_eval_judge_max_tokens"].default == 1024
    # NO ``>= 2 * 417`` assertion here. Review proved it unreachable: anything
    # satisfying ``== 1024`` satisfies ``>= 834``, so it could never fail and
    # was a check that counted nothing. The 2.5x headroom is REASONING for the
    # literal above, and reasoning belongs in prose, not in an assertion that
    # cannot fire.
