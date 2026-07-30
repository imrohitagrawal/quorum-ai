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
from uuid import uuid4

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


def _drive_full_run(client: TestClient) -> dict[str, Any]:
    account_id = uuid4()
    create = client.post(
        "/v1/query-runs",
        json={
            "query_text": "Compare durable storage options for a small team",
            "model_slots": _MIXED_MODEL_IDS,
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
