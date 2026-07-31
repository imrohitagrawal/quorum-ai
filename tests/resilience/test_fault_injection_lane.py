"""RB-5 — hermetic fault-injection lane.

Injects upstream provider faults at the **``providers.urlopen`` seam** and drives
them through the *full* ``produce_initial_answer`` path, then asserts the product
degrades **honestly**: a faulted slot is REPORTED MISSING, is NOT laundered into
the served ``live_count``, and — where the fault has a distinguishable
observable — surfaces it in the logs.

Until #171 that first clause read "a faulted slot becomes a clearly-labelled
local simulation", and this lane asserted it. The label was honest; the answer
was invented, and it then fed the debate, the synthesis, the agreement count
and the source-coverage figure as a real model answer. The lane now asserts the
NUMBERS a mixed run reports, not the shape of the degraded slot — see
``test_mixed_live_and_faulted_run_counts_only_the_answers_that_arrived``.

Why ``urlopen`` and not a higher seam (corrected twice during planning): at
``_live_openrouter_response`` a 500, a timeout, a JSON-decode failure and an empty
body are all the same value (``None``), so the lane could not tell the faults
apart. ``urlopen`` is the lowest seam at which the four faults are still distinct
Python events. See ``docs/analysis/R2-remaining-stages-build-plan.md`` §317.

Hermetic and $0: ``urlopen`` is monkeypatched to *raise* (or return a crafted
body) — no socket is ever opened. Stage B's egress guard is asserted active here
as a backstop precondition (``test_egress_guard_is_the_precondition``), so even a
mis-wired fault cannot dial out.

Distinguishability, stated honestly (the plan's rule: "if a fault has no
distinguishable observable, say so instead of asserting a difference that does not
exist"): only the ``HTTPError`` family emits the structured
``upstream_provider_http_error`` WARNING carrying its ``status_code``. A timeout, a
JSON-decode failure and an empty body all collapse to a silent ``None`` at the
``urlopen`` seam and are therefore NOT distinguishable from one another at the
observable level — the fault table encodes exactly that (``emits_http_warning`` is
True only for the HTTP-error legs), rather than pretending a difference exists.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from decimal import Decimal
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.conftest import OutboundSocketBlocked

from product_app import config
from product_app.costs import cost_estimation_service
from product_app.debate import _opening_synopsis
from product_app.main import app
from product_app.model_slots import ModelSlot
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    LOCAL_SIMULATION_URL_PREFIX,
    InitialAnswerStatus,
    ProviderPath,
    provider_stub_service,
)
from product_app.query_runs import (
    InMemoryQueryRunRepository,
    _result_response,
    query_run_repository,
)
from product_app.safety import WARNING_VERSION, WarningType
from product_app.synthesis_consensus import compute_consensus_strength

_FAKE_KEY = "sk-or-v1-fault-injection-not-a-real-key"


class _FakeResponse:
    """Minimal ``urlopen`` return stand-in (context manager + ``read()``)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _raise_http_500(request: Any, timeout: float = 0) -> _FakeResponse:
    raise HTTPError(url=request.full_url, code=500, msg="Server Error", hdrs=Message(), fp=None)


def _raise_timeout(request: Any, timeout: float = 0) -> _FakeResponse:
    raise TimeoutError("upstream timed out")


def _return_malformed_json(request: Any, timeout: float = 0) -> _FakeResponse:
    # A 200 whose body is not JSON — json.loads raises JSONDecodeError inside
    # _live_openrouter_response and the call returns None silently.
    return _FakeResponse(b"<html>502 upstream gibberish</html>")


def _return_empty_content(request: Any, timeout: float = 0) -> _FakeResponse:
    # A well-formed JSON envelope carrying no assistant text. ``not content``
    # → the call returns None silently (no warning).
    return _FakeResponse(
        json.dumps({"choices": [{"message": {"content": "", "annotations": []}}]}).encode()
    )


#: The fault table. Each row is one upstream failure mode injected at ``urlopen``.
#: ``emits_http_warning`` records the ONLY observable that distinguishes faults at
#: this seam: the ``upstream_provider_http_error`` WARNING fires for the HTTP-error
#: family and for nothing else. ``status_code`` is asserted only when it fires.
_FAULTS: list[tuple[str, Callable[..., Any], bool, int | None]] = [
    ("http_500", _raise_http_500, True, 500),
    ("timeout", _raise_timeout, False, None),
    ("malformed_json", _return_malformed_json, False, None),
    ("empty_body", _return_empty_content, False, None),
]


def _enable_live(monkeypatch: pytest.MonkeyPatch, fake_urlopen: Callable[..., Any]) -> None:
    """Turn live execution ON for the duration of a test and route ``urlopen``
    to the injected fault. The egress guard keeps ``settings`` OFF by default
    (asserted separately); this override is local to the test."""
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)


def test_egress_guard_is_the_precondition() -> None:
    """Safety precondition (RB-5 depends on Stage B's guard). Two layers:

    1. ``settings.openrouter_live_execution_enabled`` is forced ``False`` for the
       whole suite, so nothing reaches ``urlopen`` unless a test deliberately
       overrides it (as this lane does, with ``urlopen`` already monkeypatched).
    2. A non-loopback ``socket.connect`` raises ``OutboundSocketBlocked`` — so
       even a mis-wired fault that slipped past the ``urlopen`` patch cannot dial
       out to a real provider and incur a paid call.

    Bite proof: remove either guard layer in ``conftest`` → the matching
    assertion reds.
    """
    assert config.settings.openrouter_live_execution_enabled is False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # TEST-NET-3 (RFC 5737) — never routable even absent the guard.
        with pytest.raises(OutboundSocketBlocked):
            sock.connect(("203.0.113.7", 443))
    finally:
        sock.close()


@pytest.mark.parametrize(
    ("name", "fake_urlopen", "emits_http_warning", "status_code"),
    _FAULTS,
    ids=[row[0] for row in _FAULTS],
)
def test_upstream_fault_reports_the_slot_missing_and_fabricates_nothing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    name: str,
    fake_urlopen: Callable[..., Any],
    emits_http_warning: bool,
    status_code: int | None,
) -> None:
    """#171: every injected upstream fault leaves the slot MISSING.

    This test asserted the opposite until #171 — that the fault "degrades the
    slot to a clearly-labelled local simulation". That was the defect, pinned.
    The label was honest but the answer was invented, and the invented answer
    went on to the debate prompt, the synthesis prompt, the agreement count
    and — through a fabricated ``is_fallback=False`` source — the
    source-coverage numerator, none of which read anything but ``status``.

    Asserted as CARDINALITIES of what the slot contributes downstream, not as
    a status: zero text, zero sources, zero weight in the coverage
    denominator.

    Paired positive: ``test_a_demo_run_still_simulates_every_slot`` runs the
    same probe over a genuine demo run, where all four simulated answers ARE
    produced — so these zeros are not trivially true over a deleted path.

    Distinguishing observable: the HTTP-error leg — and only it — logs
    ``upstream_provider_http_error`` with its ``status_code``.

    What turns it red: delete the ``_live_execution_enabled`` guard from
    ``produce_initial_answer`` and the slot returns COMPLETED /
    LOCAL_SIMULATION carrying one fabricated source. Verified by mutation.
    """
    _enable_live(monkeypatch, fake_urlopen)
    model_slot = ModelSlot(slot_number=1, model_id="openai/gpt-4o-mini", search=True)

    with caplog.at_level("WARNING", logger="product_app.providers"):
        answer = provider_stub_service.produce_initial_answer(
            account_id=uuid4(),
            query_run_id=uuid4(),
            query_text="compare vendor uptime guarantees",
            model_slot=model_slot,
            credential_source=ProviderCredentialSource.APP_OWNED,
            openrouter_key=_FAKE_KEY,
        )

    # Reported missing, honestly attributed to the path that was attempted.
    assert answer.status is InitialAnswerStatus.FAILED
    assert answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    assert answer.error_code == "PROVIDER_UNAVAILABLE"

    # Nothing was invented. These are numbers, not statuses.
    assert answer.answer_text == "", f"{name}: a faulted slot must carry no text"
    assert len(answer.sources) == 0, f"{name}: a faulted slot must cite nothing"
    assert answer.citation_coverage.answer_count == 0, (
        f"{name}: a faulted slot must be OUT of the source-coverage denominator"
    )
    assert answer.citation_coverage.sourced_answer_count == 0

    # Distinguishing observable — asserted in BOTH directions.
    http_records = [r for r in caplog.records if r.getMessage() == "upstream_provider_http_error"]
    if emits_http_warning:
        assert http_records, f"{name}: expected an upstream_provider_http_error WARNING"
        assert getattr(http_records[0], "status_code", None) == status_code
    else:
        assert not http_records, (
            f"{name}: this fault has no distinguishable HTTP observable at the "
            "urlopen seam — it must NOT emit upstream_provider_http_error"
        )


def test_one_provider_failure_slot_is_excluded_from_served_live_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end honesty (ties the fault lane to the D3 served-number fix): in a
    4-slot run where exactly one slot suffers a hard *provider failure*, the
    served ``live_count`` reads 3 — the failed slot is NOT counted as live.

    A hard provider failure produces a slot with ``status=FAILED`` **and**
    ``provider_path=OPENROUTER_SEARCH`` (``providers._failed_answer``) — the exact
    shape D3 fixes. (Since #171 a *transient* urlopen fault produces that same
    shape — see
    ``test_upstream_fault_reports_the_slot_missing_and_fabricates_nothing``
    above. This paragraph read "a transient urlopen fault degrades to a
    COMPLETED LOCAL_SIMULATION slot instead" and cited a test name the #171
    rename removed: a dangling citation attached to the behaviour #171 deleted.
    What still makes THIS test distinct is its ROUTE — the LOCAL-independent
    ``provider-failure`` model marker short-circuits to ``_failed_answer``
    before live execution is attempted at all, so it exercises the
    ``live_count`` filter without depending on the #171 guard.)

    This is the served-number contract RB-5 protects: a provider failure must not
    inflate the "N of 4" banner.

    Bite proof: revert the D3 ``status is COMPLETED`` clause in
    ``_result_response``'s ``live_count`` → the failed OPENROUTER_SEARCH slot is
    counted → ``live_count`` reads 4 → red (verified by mutation).
    """

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        # The three non-failing slots return a real live answer. The failing
        # slot never reaches urlopen — _should_force_provider_failure short-
        # circuits it to _failed_answer before live execution is attempted.
        return _FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "A grounded live answer [1].",
                                "annotations": [{"title": "Src", "url": "https://live.example/a"}],
                            }
                        }
                    ]
                }
            ).encode()
        )

    _enable_live(monkeypatch, fake_urlopen)
    account_id = uuid4()
    query_text = "compare vendor uptime guarantees"
    # Slot 4 carries the ``provider-failure`` marker → a hard provider failure
    # (FAILED, provider_path=OPENROUTER_SEARCH). The marker path is not
    # LOCAL-gated, so this holds in any runtime.
    model_slots = [
        ModelSlot(slot_number=1, model_id="prov/model-1", search=True),
        ModelSlot(slot_number=2, model_id="prov/model-2", search=True),
        ModelSlot(slot_number=3, model_id="prov/model-3", search=True),
        ModelSlot(slot_number=4, model_id="prov/provider-failure-4", search=True),
    ]

    repository = InMemoryQueryRunRepository()
    estimate = cost_estimation_service.estimate(query_text=query_text, model_slots=model_slots)
    query_run = repository.create(
        account_id=account_id,
        query_text=query_text,
        model_slots=model_slots,
        cost_estimate=estimate,
    )
    answers = provider_stub_service.produce_initial_answers(
        account_id=account_id,
        query_run_id=query_run.query_run_id,
        query_text=query_text,
        model_slots=model_slots,
        credential_source=ProviderCredentialSource.APP_OWNED,
        openrouter_key=_FAKE_KEY,
    )
    repository.record_initial_answers(query_run.query_run_id, answers)

    response = _result_response(repository.get(query_run.query_run_id))

    # Three genuinely-live slots; the failed slot is excluded from live_count.
    assert response.live_count == 3
    # Positive control: exactly three slots took the OpenRouter path COMPLETED.
    live_slots = [
        a
        for a in response.result.model_answers
        if a.provider_path is ProviderPath.OPENROUTER_SEARCH
        and a.status is InitialAnswerStatus.COMPLETED
    ]
    assert len(live_slots) == 3
    # Paired negative: the failed slot IS on the OpenRouter path but FAILED, so
    # it is exactly the shape that would inflate live_count without the D3 fix.
    failed_slots = [
        a
        for a in response.result.model_answers
        if a.provider_path is ProviderPath.OPENROUTER_SEARCH
        and a.status is InitialAnswerStatus.FAILED
    ]
    assert len(failed_slots) == 1


# ---------------------------------------------------------------------------
# #171 — the MIXED run: some slots answered, one did not.
#
# The issue measured that no test covered a run with real AND simulated answers
# together. The two that looked like they did (including
# ``test_one_provider_failure_slot_is_excluded_from_served_live_count`` above)
# use a *failed* slot reached through the ``provider-failure`` model marker,
# which never enters the live path at all. The pair below drives the real
# ``urlopen`` seam so exactly one slot genuinely fails mid-call, and asserts the
# NUMBERS the whole run then reports — through the full create-to-terminal
# pipeline, not the provider layer in isolation.
# ---------------------------------------------------------------------------

#: The sentence ``providers._local_simulation_text`` puts in every fabricated
#: answer. Quoted here so the probe searches for the fabrication's own words;
#: ``test_a_demo_run_still_simulates_every_slot`` proves the probe can find it.
_FABRICATION_SENTENCE = "This answer is simulated in local demo mode"

_MIXED_MODEL_IDS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4.5",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-chat-v3.1",
]
#: Slot 3. Mid-list, so an off-by-one in slot handling cannot pass — and it must
#: be a model the MODERATOR does not also use. Slot 2 is
#: ``anthropic/claude-haiku-4.5``, which IS ``settings.debate_model_id``, and
#: slot 1 is ``openai/gpt-4o-mini``, which IS ``settings.synthesis_model_id``.
#: Faulting either one takes a moderator stage down with the participant, so the
#: run under test would no longer be "one participant missing" — it would be
#: "one participant missing AND that stage templated", and the numbers below
#: would be measuring two changes at once.
#:
#: This test faulted slot 2 when it was written, on the stated but unchecked
#: belief that the moderator "uses a different model id". It does not. The
#: assertion in ``_faulted_model_collides_with_no_moderator`` is what makes the
#: belief checkable, so a change to either setting reds this test instead of
#: silently changing what it measures.
_FAULTED_MODEL_ID = _MIXED_MODEL_IDS[2]
_FAULTED_SLOT_NUMBER = 3

_LIVE_BODY = json.dumps(
    {
        "choices": [
            {
                "message": {
                    "content": "A grounded live answer [1].",
                    "annotations": [
                        {"title": "Live evidence", "url": "https://live.example/evidence"}
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 300, "total_tokens": 1300},
    }
).encode()


def _urlopen_faulting_only_the_participant(request: Any, timeout: float = 0) -> _FakeResponse:
    """Time out for the faulted slot's model; answer normally for everything else.

    Keyed on the model id in the POST body. Because ``_FAULTED_MODEL_ID`` is
    neither moderator model (asserted, not assumed — see
    ``_faulted_model_collides_with_no_moderator``), the two debate rounds and
    the five synthesis sections still run live, so exactly ONE participant is
    missing. That is the case #171 is about. The ``split(":")`` strips the
    ``:online`` search suffix.
    """
    payload = json.loads(request.data.decode())
    if str(payload.get("model", "")).split(":")[0] == _FAULTED_MODEL_ID:
        raise TimeoutError("upstream timed out")
    return _FakeResponse(_LIVE_BODY)


def _faulted_model_collides_with_no_moderator() -> None:
    """Fail loudly if the faulted participant is also a moderator model.

    The collision this guards against was real and silent: the test faulted
    ``anthropic/claude-haiku-4.5``, which is ``settings.debate_model_id``, so
    both debate rounds fell back to their local template while the docstring
    said they were 'unaffected'. Derived from ``settings`` rather than retyped,
    so changing either setting reds this instead of quietly changing the
    scenario under test.
    """
    assert config.settings.debate_model_id != _FAULTED_MODEL_ID, (
        "the faulted participant is also the debate moderator — the debate would "
        "template and the run would no longer be 'one participant missing'"
    )
    assert config.settings.synthesis_model_id != _FAULTED_MODEL_ID, (
        "the faulted participant is also the synthesis model — the synthesis "
        "would template and the run would no longer be 'one participant missing'"
    )


def _drive_full_run(client: TestClient, model_ids: list[str] | None = None) -> dict[str, Any]:
    account_id = uuid4()
    create = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare durable storage options for a small team",
            "model_slots": model_ids if model_ids is not None else _MIXED_MODEL_IDS,
            "safety_acknowledgements": [
                {"warning_type": WarningType.SENSITIVE_DATA, "version": WARNING_VERSION},
            ],
        },
        headers={"X-Account-Id": str(account_id)},
    )
    assert create.status_code in (200, 201, 202), create.text[:400]
    run_id = create.json()["query_run_id"]
    body: dict[str, Any] = client.get(
        f"/v1/query-runs/{run_id}", headers={"X-Account-Id": str(account_id)}
    ).json()
    return body


def test_mixed_live_and_faulted_run_counts_only_the_answers_that_arrived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three models answered, one timed out. Every served number says three.

    This is the run the issue measured. Before #171 it served, verbatim::

        <faulted slot> completed local_simulation primary=1 'Cross-check summary ...'
        live_count 3 local_count 1 demo_mode True
        answer_count 4 sourced_answer_count 4 ratio 1.00

    — 100% source coverage over four answers when only three existed, a quarter
    of the evidence invented, and the run labelled a demo because a real
    provider had failed.

    Every assertion below is a COUNT, and each would be satisfiable by a
    different wrong implementation, so none of them is decoration:

    * the coverage DENOMINATOR is 3, not 4 — the slot that produced nothing
      does not dilute or inflate the ratio;
    * exactly 3 sources are treated as primary, and none carries the
      fabricated ``example.test/local-demo`` prefix;
    * exactly 1 slot is FAILED and exactly 0 are on a simulated path;
    * the fabrication's own sentence appears 0 times in the ENTIRE served
      payload, model answers included — that is where the invented answer used
      to sit, and where the paired positive finds it;
    * the missing slot's row in the position-movement table opens with the
      no-answer stand-in, not a synopsis of an invented answer.

    SCOPE of those two string searches, stated so a later reader does not
    over-trust them: they detect ONE generator, ``_local_simulation_text``,
    which is the one #171 is about. They are NOT a general "nothing fabricated
    reached the user" check — a templated debate round and a templated
    synthesis section match neither string, and an empty-but-not-blank live
    answer matches neither either. The load-bearing assertions here are the
    counts above.

    SEVEN of the assertions below are NOT defect detectors. They are pins, and
    each is marked ``PIN`` at its own line so no reader has to trust a count in
    a docstring to know which is which. They are: ``len(answers) == 4``,
    ``sourced_answer_ratio == 1``, ``live_count == 3``, ``agreement["aligned"]
    == 3``, ``len(missing_movement) == 1``, ``revised is False``, and
    ``cost_source``. Every one was measured under the mutation named below, not
    assumed — the ratio and ``live_count`` read the same before the fix because
    it is the DENOMINATOR that moved, and the fabricated slot happened to
    cluster as the minority so ``aligned`` read 3 either way.

    ``cost_source == "estimated"`` is a no-change pin on the money contract: a
    run with a missing slot must not yield a measured receipt. Its positive
    partner is ``test_an_unfaulted_run_of_the_same_harness_is_measured``, which
    drives this identical harness with no fault and gets ``measured`` — so the
    value here is caused by the missing slot and not by a harness that can only
    ever produce one answer.

    What turns it red: delete the ``_live_execution_enabled`` guard from
    ``produce_initial_answer``. 13 of the 20 assertions below move; the seven
    marked ``PIN`` do not. Two earlier drafts of this docstring got that
    enumeration wrong — one said "eleven" and one said "four pins" — which is
    why every pin is now marked at its own line rather than listed only here.
    A count in prose is a claim, and this one has been re-measured twice.
    """
    query_run_repository.clear()
    _faulted_model_collides_with_no_moderator()
    _enable_live(monkeypatch, _urlopen_faulting_only_the_participant)
    monkeypatch.setattr(config.settings, "openrouter_api_key", _FAKE_KEY, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)

    body = _drive_full_run(TestClient(app))
    answers = body["result"]["model_answers"]

    # --- what arrived -------------------------------------------------------
    assert len(answers) == 4, "all four slots are still reported"  # PIN
    completed = [a for a in answers if a["status"] == InitialAnswerStatus.COMPLETED]
    failed = [a for a in answers if a["status"] == InitialAnswerStatus.FAILED]
    assert len(completed) == 3
    assert len(failed) == 1
    assert failed[0]["slot_number"] == _FAULTED_SLOT_NUMBER, (
        "the faulted slot is the one reported missing"
    )
    simulated = [
        a
        for a in answers
        if a["provider_path"] in {ProviderPath.LOCAL_SIMULATION, ProviderPath.FALLBACK_SEARCH}
    ]
    assert len(simulated) == 0, "a live run may not contain a simulated answer"

    # --- the trust numbers --------------------------------------------------
    coverage = body["result"]["final_synthesis"]["citation_coverage"]
    assert coverage["answer_count"] == 3, "the denominator is answers RECEIVED"
    assert coverage["sourced_answer_count"] == 3
    assert Decimal(str(coverage["sourced_answer_ratio"])) == Decimal("1")  # PIN

    primary_sources = [
        source for answer in answers for source in answer["sources"] if not source["is_fallback"]
    ]
    assert len(primary_sources) == 3, "exactly one primary source per answer that arrived"
    assert not [s for s in primary_sources if s["url"].startswith(LOCAL_SIMULATION_URL_PREFIX)]

    # --- the served labels --------------------------------------------------
    assert body["live_count"] == 3  # PIN
    assert body["local_count"] == 0
    assert body["demo_mode"] is False, "one provider failing does not make a run a demo"

    # --- the verdict ring ---------------------------------------------------
    # NOTE on what this pair does and does not prove. ``aligned == 3`` is a
    # REGRESSION pin, not a defect detector: it read 3 before the fix too,
    # because the fabricated slot happened to cluster as the minority. Measured
    # under mutation rather than assumed — so it is labelled, not dressed up.
    agreement = body["result"]["agreement"]
    assert agreement["aligned"] == 3, "only answers that arrived can align"  # PIN
    # The ``opening`` assertion below — and only it — moves. The two around it
    # are pins. The missing slot's row in the "how positions moved"
    # table used to open with a synopsis of the INVENTED answer, narrating a
    # fabrication as a model's stance. It must now be the fixed no-answer
    # stand-in — compared against ``_opening_synopsis("")`` rather than a
    # retyped copy of that sentence, so rewording the copy cannot silently
    # decouple the two.
    missing_movement = [
        m for m in body["result"]["position_movements"] if m["slot_number"] == _FAULTED_SLOT_NUMBER
    ]
    assert len(missing_movement) == 1  # PIN
    assert missing_movement[0]["opening"] == _opening_synopsis("")
    # PIN — read False before the fix too. It sits here for topical grouping,
    # NOT because it moves; only the ``opening`` assertion above does.
    assert missing_movement[0]["revised"] is False, "a slot with no answer revised nothing"

    # --- nothing fabricated reached ANY served surface ----------------------
    served = json.dumps(body)
    assert served.count(_FABRICATION_SENTENCE) == 0
    assert served.count(LOCAL_SIMULATION_URL_PREFIX) == 0

    # --- the money contract did not move ------------------------------------
    assert body["cost_source"] == "estimated", (  # PIN
        "a slot that produced no usage cannot yield a measured receipt"
    )


def _urlopen_never_faults(request: Any, timeout: float = 0) -> _FakeResponse:
    """Every call answers. The control arm of the mixed run."""
    return _FakeResponse(_LIVE_BODY)


def test_an_unfaulted_run_of_the_same_harness_is_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive partner for the mixed run's ``cost_source == "estimated"``.

    Identical harness, identical model list, identical live body — the ONLY
    difference is that no slot faults. Four answers arrive, the coverage
    denominator is 4, and the receipt is ``measured``. That is what makes the
    mixed run's ``estimated`` attributable to the missing slot rather than to a
    harness that could never have produced a measured receipt in the first
    place.

    What turns it red: make ``_urlopen_never_faults`` raise for any slot, or
    strip ``usage`` from ``_LIVE_BODY`` — the receipt drops to ``estimated``.
    """
    query_run_repository.clear()
    _enable_live(monkeypatch, _urlopen_never_faults)
    monkeypatch.setattr(config.settings, "openrouter_api_key", _FAKE_KEY, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)

    body = _drive_full_run(TestClient(app))
    answers = body["result"]["model_answers"]

    assert len([a for a in answers if a["status"] == InitialAnswerStatus.COMPLETED]) == 4
    assert len([a for a in answers if a["status"] == InitialAnswerStatus.FAILED]) == 0
    assert body["live_count"] == 4
    assert body["result"]["final_synthesis"]["citation_coverage"]["answer_count"] == 4
    assert body["cost_source"] == "measured"


# ---------------------------------------------------------------------------
# #175 — the WHITESPACE run: every slot answered 200 OK, and said nothing.
#
# Not a fault at all at the transport level: HTTP 200, well-formed JSON, a real
# ``usage`` object, and a completion consisting only of whitespace. That is a
# real provider behaviour (an image-only model, a refusal that emits only
# whitespace, a ``max_tokens`` cut landing on a space), and before #175 it was
# the ONE run shape that reached a ``measured`` receipt with no text anywhere.
# ---------------------------------------------------------------------------


def _whitespace_body(annotations: list[dict[str, str]]) -> bytes:
    """200 OK, whitespace-only completion, WITH the usage the provider charged.

    The ``usage`` object is the point: this call was BILLED. It is what made the
    old behaviour reach ``initial_fully_captured`` and serve a ``measured``
    receipt, and it is what the money decision in ``providers._failed_answer``
    is about.
    """
    return json.dumps(
        {
            "choices": [{"message": {"content": "   \n\t  ", "annotations": annotations}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 300, "total_tokens": 1300},
        }
    ).encode()


def test_a_run_in_which_every_slot_returned_whitespace_is_not_a_completed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#175, variant A: four billed calls, zero characters, and the run says so.

    Measured on origin/main (e6c84ea) before the fix, driving THIS fixture's
    exact body, verbatim::

        slot 1..4 completed openrouter_search  text='   \\n\\t  '
        live_count 4 local_count 0 demo_mode False
        status completed  cost_source measured
        failed_steps []  missing_steps []
        coverage {'answer_count': 4, 'sourced_answer_count': 0,
                  'sourced_answer_ratio': '0.00', 'target_ratio': '0.80',
                  'target_met': False}

    Four models produced nothing and the product reported "4 of 4 answered
    live", status ``completed``, no failed steps, and a ``measured`` (billed)
    receipt. No degraded banner fired, because ``app.js`` derives
    ``failedCount`` by subtracting ``live_count`` from the slot count — and
    ``live_count`` was the very number the whitespace slots inflated.

    Every assertion is a CARDINALITY, and each is satisfiable by a different
    wrong implementation:

    * ``posts[0] >= 4`` — the POSITIVE PARTNER for every zero below. Without
      it, a harness that never dialled out at all would satisfy "no live
      answers" trivially. It also states the money fact plainly: these calls
      really were made, and really were billed.
    * ``live_count == 0`` with ``local_count == 0`` — nothing was laundered
      into the live count, and nothing was fabricated to replace it either.
    * ``0`` answers carry ``token_usage`` — the money decision (#175 option b),
      asserted as a COUNT rather than a label. The provider stated a charge on
      all four calls; none of it is itemised, and the receipt says
      ``estimated`` rather than claiming a measured figure it cannot support.
    * ``final_synthesis is None`` — no synthesis was built over nothing.

    What turns it red: revert ``.strip()`` in
    ``providers._live_openrouter_response``. Then ``live_count`` reads 4,
    ``status`` reads ``completed``, ``cost_source`` reads ``measured``, four
    answers carry usage and a synthesis exists. Verified by mutation.
    """
    query_run_repository.clear()
    posts = [0]
    body = _whitespace_body([])

    def _urlopen_all_whitespace(request: Any, timeout: float = 0) -> _FakeResponse:
        posts[0] += 1
        return _FakeResponse(body)

    _enable_live(monkeypatch, _urlopen_all_whitespace)
    monkeypatch.setattr(config.settings, "openrouter_api_key", _FAKE_KEY, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)

    served = _drive_full_run(TestClient(app))
    answers = served["result"]["model_answers"]

    # --- the calls really went out, and really were billed ------------------
    assert posts[0] >= 4, "positive partner: at least one POST per slot was dispatched"

    # --- what arrived -------------------------------------------------------
    assert len(answers) == 4, "all four slots are still reported"
    assert len([a for a in answers if a["status"] == InitialAnswerStatus.COMPLETED]) == 0
    assert len([a for a in answers if a["status"] == InitialAnswerStatus.FAILED]) == 4
    assert {a["answer_text"] for a in answers} == {""}, "no whitespace text is served"

    # --- the served labels --------------------------------------------------
    assert served["live_count"] == 0, "whitespace never counts as a live answer"
    assert served["local_count"] == 0, "and nothing was fabricated to replace it"
    assert served["demo_mode"] is False
    assert served["status"] == "partial", "a run that produced nothing is not completed"
    assert "initial_answers" in served["failed_steps"]

    # --- nothing was built on top of nothing --------------------------------
    assert served["result"]["final_synthesis"] is None

    # --- the money, as a COUNT ----------------------------------------------
    billed_but_unitemised = [a for a in answers if a["token_usage"] is None]
    assert len(billed_but_unitemised) == 4, (
        "every slot was billed and none of it is itemised — the #175 money decision"
    )
    assert served["cost_source"] == "estimated", (
        "a run with no usable answer must never serve a measured receipt"
    )

    # --- and nothing fabricated reached any surface -------------------------
    assert json.dumps(served).count(_FABRICATION_SENTENCE) == 0


def test_a_whitespace_slot_carrying_a_citation_leaves_the_coverage_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#175, variant B: 100% source coverage over an answer with no text.

    The sharper shape. Three slots answer normally; the fourth returns a
    citation annotation and no prose — a model that emits a citation block and
    nothing else. Measured on origin/main (e6c84ea) before the fix, verbatim::

        slot 3 completed primary=1 text='   \\n\\t  '
        live_count 4 demo_mode False status completed cost_source measured
        coverage {'answer_count': 4, 'sourced_answer_count': 4,
                  'sourced_answer_ratio': '1.00', 'target_ratio': '0.80',
                  'target_met': True}
        agreement {'aligned': 3, 'total': 4}

    ``coverage 4 of 4 = 100%`` on a run where one slot produced no text — the
    same wrong figure #171 was filed about, reached through a different door.

    THE PAYLOAD CONTRADICTED ITSELF. ``synthesis_consensus`` applies
    ``.strip()`` when deciding alignment, so ``agreement`` read 3 while
    ``live_count`` and the coverage denominator read 4. The product knew the
    slot was empty in one place and not in the other. ``live_count == 3`` is the
    assertion that catches it — on its own, since it read 4 before the fix — and
    ``aligned == 3`` is the PIN beside it that shows WHAT it disagreed with.

    An earlier draft of this paragraph claimed "NO assertion on either one alone
    would have caught it". That is false, and it was refuted by the very
    measurement that produced the block above: ``live_count`` moves 4 -> 3, so
    asserting it alone is sufficient. Corrected rather than deleted, because the
    pairing is still what makes the failure legible.

    ``sourced_answer_ratio == 1`` reads the same before and after — it is a
    PIN, not a defect detector. It is the DENOMINATOR that moved (4 -> 3), which
    is exactly why asserting the ratio alone is worthless here and the counts
    are load-bearing.

    What turns it red: revert ``.strip()`` in
    ``providers._live_openrouter_response``. ``live_count`` returns to 4 while
    ``aligned`` stays 3, the coverage denominator returns to 4, and a fourth
    answer carries usage. Verified by mutation.
    """
    query_run_repository.clear()
    _faulted_model_collides_with_no_moderator()
    whitespace_body = _whitespace_body(
        [{"title": "Live evidence", "url": "https://live.example/evidence"}]
    )

    def _urlopen_whitespace_only_for_the_participant(
        request: Any, timeout: float = 0
    ) -> _FakeResponse:
        payload = json.loads(request.data.decode())
        if str(payload.get("model", "")).split(":")[0] == _FAULTED_MODEL_ID:
            return _FakeResponse(whitespace_body)
        return _FakeResponse(_LIVE_BODY)

    _enable_live(monkeypatch, _urlopen_whitespace_only_for_the_participant)
    monkeypatch.setattr(config.settings, "openrouter_api_key", _FAKE_KEY, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)

    served = _drive_full_run(TestClient(app))
    answers = served["result"]["model_answers"]

    # --- what arrived -------------------------------------------------------
    assert len(answers) == 4
    failed = [a for a in answers if a["status"] == InitialAnswerStatus.FAILED]
    assert len(failed) == 1
    assert failed[0]["slot_number"] == _FAULTED_SLOT_NUMBER, (
        "the whitespace slot is the one reported missing"
    )
    assert failed[0]["answer_text"] == ""
    assert len(failed[0]["sources"]) == 0, (
        "a citation annotation cannot survive an answer that has no text"
    )

    # --- the trust numbers --------------------------------------------------
    coverage = served["result"]["final_synthesis"]["citation_coverage"]
    assert coverage["answer_count"] == 3, "the denominator is answers RECEIVED, not slots"
    assert coverage["sourced_answer_count"] == 3
    assert Decimal(str(coverage["sourced_answer_ratio"])) == Decimal("1")  # PIN

    # --- the disagreement, pinned closed ------------------------------------
    # These two numbers came from code that disagreed about whether slot 3 was
    # empty: ``live_count`` did not strip, ``classify_model_alignment`` did. So
    # the run served ``live_count 4`` beside ``aligned 3``. ``live_count`` is
    # the assertion that MOVES (4 -> 3); ``aligned`` is a PIN, unchanged at 3.
    #
    # An earlier draft added a third line asserting the two are EQUAL. Review
    # showed it could not fail: both are asserted ``== 3`` immediately above, so
    # the equality is entailed and pins nothing. Equality is also not a property
    # of the product — the two legitimately part company whenever a model
    # answers and DISAGREES. The pair below is what carries the meaning.
    assert served["live_count"] == 3
    assert served["result"]["agreement"]["aligned"] == 3  # PIN

    # --- the money, as a COUNT ----------------------------------------------
    carrying_usage = [a for a in answers if a["token_usage"] is not None]
    assert len(carrying_usage) == 3, "exactly the three answers that arrived are itemised"
    assert {a["slot_number"] for a in carrying_usage} == {1, 2, 4}
    assert served["cost_source"] == "estimated", (
        "the whitespace call was billed and cannot be itemised, so the receipt "
        "falls back to the estimate rather than claiming a measured figure"
    )


def test_a_demo_run_still_simulates_every_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positive partner: the probe above can actually see a fabricated answer.

    ``test_mixed_live_and_faulted_run_counts_only_the_answers_that_arrived``
    asserts two counts of ZERO over the served payload. A typo in the search
    string, a renamed field, or a serialiser that dropped the answer text would
    satisfy both while proving nothing.

    So this drives the identical pipeline with live execution OFF — the one
    mode where simulation is legitimate and labelled end to end — and asserts
    the SAME two strings are found, four times over, one per slot. That is what
    makes the zeros above evidence.

    What turns it red: make the ``_live_execution_enabled`` guard in
    ``produce_initial_answer`` unconditional; the demo run then produces four
    missing slots and every count here drops to zero.
    """
    query_run_repository.clear()
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", False, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)

    body = _drive_full_run(TestClient(app))
    answers = body["result"]["model_answers"]

    assert len(answers) == 4
    assert all(a["status"] == InitialAnswerStatus.COMPLETED for a in answers)
    assert all(a["provider_path"] == ProviderPath.LOCAL_SIMULATION for a in answers)
    assert body["local_count"] == 4
    assert body["live_count"] == 0
    assert body["demo_mode"] is True

    served = json.dumps(body)
    assert served.count(_FABRICATION_SENTENCE) == 4, (
        "one simulated answer per slot — this is the count the mixed-run test "
        "asserts is zero, so it must be findable here"
    )
    assert served.count(LOCAL_SIMULATION_URL_PREFIX) == 4


# ---------------------------------------------------------------------------
# #171 finding 5 — the MODERATOR fault. Every participant answers; the
# SYNTHESIS falls back to its template. Nothing is missing, nothing is
# simulated, no step failed — and the verdict ring is nonetheless decided by
# this product's own words.
#
# The pair below is the whole point: the two runs are IDENTICAL except for who
# wrote the five synthesis sections. Same four participants, same four openings,
# same debate, same query. Only the author of the final answer differs, and the
# aligned count differs with it.
# ---------------------------------------------------------------------------

#: Four priced catalog participants, none of which is a moderator model — so
#: faulting a moderator leaves all four participants answering. Asserted, not
#: assumed: see ``_participants_collide_with_no_moderator``.
_MODERATOR_FREE_PARTICIPANTS = [
    "google/gemini-2.5-flash",
    "google/gemini-2.5-flash-lite",
    "nvidia/nemotron-3-nano-30b-a3b",
    "deepseek/deepseek-chat-v3.1",
]

#: Slots 1 and 2 share this, so they cluster as the majority.
_PANEL_MAJORITY_TEXT = (
    "Durable object storage with versioning enabled is the pragmatic default here, "
    "because lifecycle rules and cross-region replication are operated by the "
    "provider rather than by your own on-call rota [1]."
)
#: Slot 3 — a minority opener that neither the template nor the live synthesis
#: mentions. The control: it must stay unaligned in BOTH runs, so the pair is
#: measuring the synthesis's provenance and not "minorities got switched off".
_PANEL_UNRELATED_TEXT = (
    "Attach one block device to a single virtual machine and take nightly "
    "snapshots into a separate billing account under a different root key [1]."
)
#: Slot 4 — the attack. Its first sentence is its own distinctive position; its
#: second is lifted VERBATIM from the tail of Quorum's own weak-consensus
#: template (``synthesis._build_consensus``'s ``else`` branch), which is exactly
#: the kind of generic advisory sentence a real model emits unprompted.
_PANEL_ECHOES_TEMPLATE_TEXT = (
    "Encrypted tape archives stay the cheapest long-horizon medium at this scale. "
    "Some models disagreed on points; treat the consensus as a working hypothesis, "
    "not a verdict [1]."
)
#: The distinctive half of slot 4's opening. A LIVE synthesis that contains this
#: has genuinely carried slot 4's position into the final answer.
_SLOT_FOUR_OWN_POSITION = (
    "Encrypted tape archives stay the cheapest long-horizon medium at this scale."
)
#: A moderator critique with no ``synthesis_consensus._CONVERGE_KEYWORDS`` in it.
#: If the critique signalled convergence the panel would classify "strong", the
#: panel-strength fallback would align the minority on its own, and the pair
#: below would read the same number twice. Asserted in the tests via
#: ``compute_consensus_strength``.
_NEUTRAL_CRITIQUE = (
    "The panel weighed retention cost against recovery time and the differences "
    "between the four positions remain open."
)

_OPENING_BY_PARTICIPANT = {
    _MODERATOR_FREE_PARTICIPANTS[0]: _PANEL_MAJORITY_TEXT,
    _MODERATOR_FREE_PARTICIPANTS[1]: _PANEL_MAJORITY_TEXT,
    _MODERATOR_FREE_PARTICIPANTS[2]: _PANEL_UNRELATED_TEXT,
    _MODERATOR_FREE_PARTICIPANTS[3]: _PANEL_ECHOES_TEMPLATE_TEXT,
}


def _participants_collide_with_no_moderator() -> None:
    """Fail loudly if a participant is also a moderator model.

    Mirrors ``_faulted_model_collides_with_no_moderator`` for the inverse
    scenario: there, the faulted participant must not be a moderator; here, NO
    participant may be, because the fault targets the moderator and every
    participant must still answer. Derived from ``settings`` rather than
    retyped, so changing either setting reds this instead of quietly changing
    the scenario under test.
    """
    for model_id in _MODERATOR_FREE_PARTICIPANTS:
        assert config.settings.synthesis_model_id != model_id, (
            f"participant {model_id} is also the synthesis model — faulting the "
            "synthesis would take a participant down with it"
        )
        assert config.settings.debate_model_id != model_id, (
            f"participant {model_id} is also the debate model — faulting the "
            "debate would take a participant down with it"
        )


def _panel_envelope(content: str) -> bytes:
    return json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": content,
                        "annotations": [
                            {"title": "Live evidence", "url": "https://live.example/evidence"}
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 300, "total_tokens": 1300},
        }
    ).encode()


def _panel_urlopen(synthesis_content: str | None) -> Callable[..., _FakeResponse]:
    """Route each call by the model id in the POST body.

    Participants always answer with their own opening; the debate moderator
    always answers with the neutral critique. ``synthesis_content=None`` times
    the SYNTHESIS moderator out, so all five sections fall back to their
    template; a string makes it answer with that text.
    """

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        payload = json.loads(request.data.decode())
        model_id = str(payload.get("model", "")).split(":")[0]
        if model_id == config.settings.synthesis_model_id:
            if synthesis_content is None:
                raise TimeoutError("synthesis moderator timed out")
            return _FakeResponse(_panel_envelope(synthesis_content))
        if model_id == config.settings.debate_model_id:
            return _FakeResponse(_panel_envelope(_NEUTRAL_CRITIQUE))
        return _FakeResponse(_panel_envelope(_OPENING_BY_PARTICIPANT[model_id]))

    return fake_urlopen


def _drive_moderator_fault_run(
    monkeypatch: pytest.MonkeyPatch, *, synthesis_content: str | None
) -> dict[str, Any]:
    query_run_repository.clear()
    _participants_collide_with_no_moderator()
    _enable_live(monkeypatch, _panel_urlopen(synthesis_content))
    monkeypatch.setattr(config.settings, "openrouter_api_key", _FAKE_KEY, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)
    return _drive_full_run(TestClient(app), _MODERATOR_FREE_PARTICIPANTS)


def _panel_preconditions(body: dict[str, Any]) -> None:
    """The shape both runs of the pair share, asserted in both.

    Every one of these holds in the DEFECTIVE build too — that is the point of
    finding 5. A run in which the synthesis was never written by a model looks,
    by every served signal except ``synthesis_mode``, like a complete live run.
    """
    answers = body["result"]["model_answers"]
    assert len(answers) == 4
    assert [a["status"] for a in answers] == [InitialAnswerStatus.COMPLETED] * 4
    assert [a["provider_path"] for a in answers] == [ProviderPath.OPENROUTER_SEARCH] * 4
    assert body["live_count"] == 4, "every participant answered live"
    assert body["local_count"] == 0, "nothing was simulated"
    assert body["demo_mode"] is False
    assert body["failed_steps"] == [], "no stage reported a failure"
    assert body["missing_steps"] == []
    assert json.dumps(body).count(_FABRICATION_SENTENCE) == 0


def test_a_templated_synthesis_does_not_decide_the_served_verdict_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#171 finding 5, end to end: four live answers, a TEMPLATED synthesis, and
    the served ``agreement`` must not count a model the template vouched for.

    Reproduced at ``9c60bc3`` before the fix, verbatim::

        live_count 4  local_count 0  demo_mode False  failed_steps []
        synthesis_mode 'simulated'
        agreement {'aligned': 3, 'total': 4}
        move slot 4 revised=True final='Aligns with the group consensus ...'

    Slot 4's opening shares 12 of its 25 opening 4-grams with the templated
    consensus — 48% against a 10% containment threshold — for the single reason
    that it happens to repeat a sentence Quorum wrote. The run served "3 of 4
    aligned" with nothing failed, nothing simulated and four live answers, and
    the third of those three was granted by this product's own boilerplate
    about an answer it had never read.

    The assertions are cardinalities and every one of them is satisfiable by a
    different wrong implementation:

    * ``aligned`` is 2 — the two clustered majority openers and nobody else;
    * exactly 0 slots are marked ``revised``;
    * the panel strength is NOT "strong", so the fallback did not do this by
      itself (without this the test could pass for the wrong reason);
    * every precondition in ``_panel_preconditions`` still holds, so the fix
      did not buy the number by degrading the run.

    Its positive partner is
    ``test_a_live_synthesis_still_carries_a_minority_into_the_verdict_ring``,
    which drives the SAME panel with a model-written synthesis and gets 3 — so
    ``aligned == 2`` here is not a guard that refuses every minority.

    What turns it red: drop the ``synthesis_mode != SYNTHESIS_MODE_LIVE`` guard
    from ``synthesis._final_synthesis_alignment_text``; the templated consensus
    is handed to alignment again, slot 4 is counted, and ``aligned`` reads 3.
    """
    body = _drive_moderator_fault_run(monkeypatch, synthesis_content=None)

    _panel_preconditions(body)
    assert body["result"]["final_synthesis"]["synthesis_mode"] == "simulated", (
        "the premise: no section came back from the model"
    )
    # The templated consensus really is the text that used to decide this, and
    # slot 4's borrowed sentence really is in it. Asserted so the scenario
    # cannot rot into a run where the echo is absent and the zero below is free.
    consensus = body["result"]["final_synthesis"]["consensus"]
    assert "treat the consensus as a working hypothesis, not a verdict" in consensus
    assert "treat the consensus as a working hypothesis, not a verdict" in (
        _PANEL_ECHOES_TEMPLATE_TEXT
    )

    run = query_run_repository.get(UUID(body["query_run_id"]))
    assert compute_consensus_strength(run.initial_answers, run.debate_outputs) != "strong", (
        "a 'strong' panel would align the minority through the panel-strength "
        "fallback, and this test would pass without measuring the synthesis"
    )

    assert body["result"]["agreement"] == {"aligned": 2, "total": 4}
    revised = [m for m in body["result"]["position_movements"] if m["revised"]]
    assert len(revised) == 0, f"no model may be counted as moved by a template: {revised}"


def test_a_live_synthesis_still_carries_a_minority_into_the_verdict_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive partner. Same panel, same openings, same debate — but the
    synthesis moderator ANSWERS, and its final answer carries slot 4's own
    position. Slot 4 is then counted aligned, and marked ``revised``.

    This is what stops the fix above from being "never align a minority". The
    only difference between the two runs is who wrote the five sections; the
    aligned count differs by exactly one, and it is slot 4 that differs.

    Slot 3 is the control inside this test: its opening is in neither
    synthesis, so it stays unaligned here as well — proving the live synthesis
    aligns the model it actually quoted rather than every minority.

    Note which assertions are PINS. ``aligned == 3`` does NOT move under the
    fix: with a live synthesis, ``_final_synthesis_alignment_text`` returns the
    same text before and after. It is here as the paired positive, not as a
    bite proof.

    What turns it red: make ``_final_synthesis_alignment_text`` return ``None``
    unconditionally (rather than only for a non-live mode) — the panel-strength
    fallback is "weak" here, so slot 4 stops being counted and ``aligned``
    drops to 2, collapsing the pair to one number.
    """
    body = _drive_moderator_fault_run(monkeypatch, synthesis_content=_SLOT_FOUR_OWN_POSITION)

    _panel_preconditions(body)
    assert body["result"]["final_synthesis"]["synthesis_mode"] == "live", (
        "the premise: all five sections came back from the model"  # PIN
    )
    assert _SLOT_FOUR_OWN_POSITION in body["result"]["final_synthesis"]["consensus"]

    run = query_run_repository.get(UUID(body["query_run_id"]))
    assert compute_consensus_strength(run.initial_answers, run.debate_outputs) != "strong"

    assert body["result"]["agreement"] == {"aligned": 3, "total": 4}  # PIN
    revised = [m["slot_number"] for m in body["result"]["position_movements"] if m["revised"]]
    assert revised == [4], "the model whose position the synthesis actually carried"


#: A panel where THREE participants cluster — the product's ordinary shape, and
#: the one that classifies ``"strong"``. Slot 4 is the outlier.
_STRONG_OPENING_BY_PARTICIPANT = {
    _MODERATOR_FREE_PARTICIPANTS[0]: _PANEL_MAJORITY_TEXT,
    _MODERATOR_FREE_PARTICIPANTS[1]: _PANEL_MAJORITY_TEXT,
    _MODERATOR_FREE_PARTICIPANTS[2]: _PANEL_MAJORITY_TEXT,
    _MODERATOR_FREE_PARTICIPANTS[3]: _PANEL_UNRELATED_TEXT,
}


def test_a_templated_synthesis_on_a_strong_panel_invents_no_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression the FIRST version of this fix introduced, pinned at the
    served-API level. Found by adversarial review, not by me.

    Refusing the templated text is only half the job: it left the minority
    falling through to the panel-strength inference, which aligns EVERY
    minority once the panel is ``"strong"`` — three of four models agreeing,
    the ordinary case. Measured on this exact scenario: 3 of 4 before the
    original #171 fix, **4 of 4 after it**, with slot 4 additionally flipped to
    ``revised``. The browser renders that as "4 of 4 models aligned · 1 revised
    their position" (``app.js``), a manufactured claim that a model changed its
    mind, on a synthesis no model wrote. The fix made its own target worse.

    Slot 4 answers about single-VM block devices while the other three answer
    about provider-operated object storage; its position is in neither the
    panel nor the templated synthesis.

    Asserted as cardinalities:

    * ``aligned`` is 3 — the three clustered openers, and not the outlier;
    * exactly 0 slots are ``revised``;
    * the panel really IS ``"strong"``, so the run exercises the branch that
      was wrong rather than passing for an unrelated reason;
    * ``_panel_preconditions`` still holds — four live answers, nothing
      simulated, no failed step — so the number was not bought by degrading
      the run.

    What turns it red: delete the ``elif final_answer_was_templated`` branch
    from ``classify_model_alignment``; the minority falls through to
    ``strength == "strong"``, ``aligned`` reads 4 and one slot reads
    ``revised``.
    """
    monkeypatch.setitem(
        _OPENING_BY_PARTICIPANT, _MODERATOR_FREE_PARTICIPANTS[2], _PANEL_MAJORITY_TEXT
    )
    body = _drive_moderator_fault_run(monkeypatch, synthesis_content=None)

    _panel_preconditions(body)
    assert body["result"]["final_synthesis"]["synthesis_mode"] == "simulated"

    run = query_run_repository.get(UUID(body["query_run_id"]))
    assert compute_consensus_strength(run.initial_answers, run.debate_outputs) == "strong", (
        "this test exists for the strong panel; on any other the panel-strength "
        "fallback and the templated refusal already agree"
    )

    assert body["result"]["agreement"] == {"aligned": 3, "total": 4}
    revised = [m["slot_number"] for m in body["result"]["position_movements"] if m["revised"]]
    assert revised == [], f"no model moved to a consensus this product wrote: {revised}"


# ---------------------------------------------------------------------------
# #171 finding 5, the DEBATE half. The synthesis half (above) shipped first —
# ``FinalSynthesis.synthesis_mode`` and the ``final_answer_was_templated`` guard
# in ``classify_model_alignment``. The debate side of the same finding was left
# open: ``DebateOutput`` had no field saying whether a round was produced by a
# live moderator call or by ``debate.py``'s own local heuristic, and the notice
# ``_debate_fallback_notice`` built for that case (``fallback_messages``) was
# appended to a local list and never read again — not returned on
# ``DebateResult``, not folded into ``provider_failure_notices``, nothing. A run
# where all four participants and the synthesis model answer live, but the
# debate MODERATOR call fails on both rounds, served every signal a genuinely
# complete live run serves — ``live_count`` 4, ``demo_mode`` False, no failed or
# missing step — while the two debate critiques on screen were entirely
# Quorum's own template, indistinguishable from a real moderator's output.
# ---------------------------------------------------------------------------


def _debate_fault_urlopen(*, debate_content: str | None) -> Callable[..., _FakeResponse]:
    """Route each call by model id. Participants and the synthesis model always
    answer live; the debate moderator times out on both rounds when
    ``debate_content`` is ``None``, or answers with that text otherwise.
    """

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        payload = json.loads(request.data.decode())
        model_id = str(payload.get("model", "")).split(":")[0]
        if model_id == config.settings.debate_model_id:
            if debate_content is None:
                raise TimeoutError("debate moderator timed out")
            return _FakeResponse(_panel_envelope(debate_content))
        if model_id == config.settings.synthesis_model_id:
            return _FakeResponse(_panel_envelope("A live synthesis paragraph [1]."))
        return _FakeResponse(_panel_envelope(f"A grounded live answer from {model_id} [1]."))

    return fake_urlopen


def _drive_debate_fault_run(
    monkeypatch: pytest.MonkeyPatch, *, debate_content: str | None
) -> dict[str, Any]:
    query_run_repository.clear()
    _participants_collide_with_no_moderator()
    _enable_live(monkeypatch, _debate_fault_urlopen(debate_content=debate_content))
    monkeypatch.setattr(config.settings, "openrouter_api_key", _FAKE_KEY, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)
    return _drive_full_run(TestClient(app), _MODERATOR_FREE_PARTICIPANTS)


def test_a_templated_debate_round_reports_its_own_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#171 finding 5, the debate half. Reproduced before the fix, verbatim::

        live_count 4  local_count 0  demo_mode False  failed_steps []
        debate_outputs[0] -> KeyError: 'debate_mode'  (the field does not exist)
        provider_failure_notices []

    Every served signal except the debate transcript's own words said this was
    a complete live run. Nothing distinguished the two on-screen critiques from
    a real moderator's output.

    Asserted as cardinalities, not a clean-path outcome:

    * exactly 2 of 2 debate rounds report ``debate_mode == "fallback"`` — not
      "the run degraded somehow", but specifically which rounds and how many;
    * the four participants and the synthesis are still fully live —
      ``_panel_preconditions``-equivalent for the debate case, so the number
      was not bought by degrading an unrelated stage.

    ``provider_failure_notices == []`` is a PIN, not an oversight: the shared
    notices list is populated only from initial-answer failures
    (``query_runs.py``'s ``provider_failure_notices`` comprehension), and this
    run has none — folding the debate's own fallback into that list would
    conflate two different signals and, since live execution defaults OFF,
    would surface on nearly every existing demo-mode test. The structural
    ``debate_mode`` field is the fix in scope here; routing it to a shared
    notice surface is a separate, larger decision left alone.

    What turns it red: delete the ``debate_mode=`` argument from either
    ``DebateOutput(...)`` construction in ``run_debate_rounds`` (reverting to
    the pre-fix constructor call). The field either vanishes from the response
    (``KeyError``) or reverts to the Pydantic default, and the assertion below
    fails on the literal value rather than an exception.
    """
    body = _drive_debate_fault_run(monkeypatch, debate_content=None)

    answers = body["result"]["model_answers"]
    assert len(answers) == 4
    assert [a["status"] for a in answers] == [InitialAnswerStatus.COMPLETED] * 4
    assert body["live_count"] == 4, "every participant answered live"
    assert body["local_count"] == 0, "nothing was simulated"
    assert body["demo_mode"] is False
    assert body["failed_steps"] == [], "no stage reported a failure"
    assert body["missing_steps"] == []
    assert body["result"]["final_synthesis"]["synthesis_mode"] == "live"

    debate_outputs = body["result"]["debate_outputs"]
    assert len(debate_outputs) == 2, "both rounds still ran, just not live"
    assert [round_["debate_mode"] for round_ in debate_outputs] == ["fallback", "fallback"], (
        "both rounds fell back to the local template; neither made it into a live call"
    )
    assert body.get("provider_failure_notices") == [], (  # PIN — see docstring
        "the debate's own fallback is not routed to the shared notices list"
    )


def test_an_unfaulted_debate_reports_live_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positive partner to the test above: when the debate moderator succeeds,
    both rounds report ``debate_mode == "live"``, not the fallback default.

    Without this pair, a defective fix that just hardcodes ``"fallback"`` on
    every ``DebateOutput`` would still pass the faulted test above.
    """
    body = _drive_debate_fault_run(monkeypatch, debate_content=_NEUTRAL_CRITIQUE)

    debate_outputs = body["result"]["debate_outputs"]
    assert len(debate_outputs) == 2
    assert [round_["debate_mode"] for round_ in debate_outputs] == ["live", "live"]
    assert body["live_count"] == 4
    assert body["demo_mode"] is False


def test_a_round_that_recovers_reports_its_own_provenance_per_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-scoped, not run-scoped: round 1 times out, round 2 (a fresh call
    to the same moderator model) succeeds. ``debate_mode`` must read
    ``["fallback", "live"]``, not the same value copied onto both rounds.

    Both prior tests here only exercise a UNIFORM outcome across the two
    rounds (both fallback, or both live) — a defective fix that computed one
    ``debate_mode`` value once and stamped it on every ``DebateOutput`` would
    still pass both of them. This is the scenario that catches that: the
    orchestrator calls the SAME ``debate_model_id`` twice (round 1, then round
    2), independently, and each call's own outcome must decide its own round's
    field — never the other round's.

    What turns it red: compute a single ``debate_mode`` before round 1 runs
    and reuse it for round 2's ``DebateOutput`` too (instead of the separate
    ``round_one_mode``/``round_two_mode`` locals). The result flips to
    ``["fallback", "fallback"]`` and this test fails on the second element.
    """
    call_count = {"debate": 0}

    def fake_urlopen(request: Any, timeout: float = 0) -> _FakeResponse:
        payload = json.loads(request.data.decode())
        model_id = str(payload.get("model", "")).split(":")[0]
        if model_id == config.settings.debate_model_id:
            call_count["debate"] += 1
            if call_count["debate"] == 1:
                raise TimeoutError("debate moderator timed out on round 1 only")
            return _FakeResponse(_panel_envelope(_NEUTRAL_CRITIQUE))
        if model_id == config.settings.synthesis_model_id:
            return _FakeResponse(_panel_envelope("A live synthesis paragraph [1]."))
        return _FakeResponse(_panel_envelope(f"A grounded live answer from {model_id} [1]."))

    query_run_repository.clear()
    _participants_collide_with_no_moderator()
    _enable_live(monkeypatch, fake_urlopen)
    monkeypatch.setattr(config.settings, "openrouter_api_key", _FAKE_KEY, raising=False)
    monkeypatch.setattr(config.settings, "stage_delay_ms", 0, raising=False)
    body = _drive_full_run(TestClient(app), _MODERATOR_FREE_PARTICIPANTS)

    assert call_count["debate"] == 2, "both rounds must call the debate moderator independently"
    debate_outputs = body["result"]["debate_outputs"]
    assert len(debate_outputs) == 2
    assert [round_["debate_mode"] for round_ in debate_outputs] == ["fallback", "live"], (
        "round 1's failure must not be copied onto round 2's genuinely live call"
    )
