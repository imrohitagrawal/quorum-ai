"""#105 defect B: the search fee follows the WIRE, not the intent.

OpenRouter charges its flat per-request web-search fee on a call made against
a ``<model>:online`` id, and not on one made against the bare id. The measured
cost layer therefore has to know which id actually went out — so
``InitialModelAnswer.searched`` is stamped from the model id this process
POSTed, never from ``ModelSlot.search``.

The distinction is not cosmetic, and it is the whole reason this file exists.
``ModelSlot.search`` is the INTENT. When ``:online`` is rejected (HTTP
400/404) ``_call_openrouter_with_optional_search`` retries with the BARE id,
and it is that bare retry which serves the answer and gets billed — no search
fee. A slot like that has ``search=True`` and owes nothing, so pricing the fee
off the intent would over-charge it on a receipt the UI labels ``measured``.

Every test here asserts the MECHANISM — the model id observed on the wire,
paired with the flag that reached the answer — rather than only the flag. A
test that checked the flag alone would pass against an implementation that
returned the intent, because in the clean case the intent and the outcome
agree; the rejected-``:online`` row is the one that separates them.

Network-free and $0: every call goes through the ``product_app.providers``
``urlopen`` seam.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from uuid import uuid4

import pytest
from tests.provider_wire import sse_from_completion

from product_app import config
from product_app.model_slots import ModelSlot
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    InitialAnswerStatus,
    ProviderPath,
    provider_execution_service,
)

_BARE_MODEL_ID = "openai/gpt-4o-mini"
_ONLINE_MODEL_ID = f"{_BARE_MODEL_ID}:online"

#: A model id that ALREADY contains a colon. ``_MODEL_ID_RE`` in
#: ``model_slots.py`` permits these and the live catalog serves them (the
#: module says so where it keeps ``_UNAUTHENTICATED_VARIANT_SUFFIXES``), so a
#: caller can put one in a slot. It is the case that separates "ends with
#: ``:online``" from a looser colon test -- see the last test in this file.
_VARIANT_MODEL_ID = "openai/gpt-4o-mini:free"

#: A real ``usage`` block. Its presence is what makes the slot measurable at
#: all — without it the cost layer skips the slot and the fee question never
#: arises, so every row here must carry one.
_USAGE = {"prompt_tokens": 2400, "completion_tokens": 700, "total_tokens": 3100}


def _answer_body() -> bytes:
    return sse_from_completion(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "A real answer from the model."},
                }
            ],
            "usage": _USAGE,
        }
    )


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _search_rejected_error() -> HTTPError:
    """The shape that makes the transport return ``_SEARCH_REJECTED``.

    404 on a ``:online`` id is OpenRouter saying it does not know that model
    variant. The caller's documented response is to retry the bare id.
    """
    return HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=404,
        msg="No endpoints found for model",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )


def _install(monkeypatch: pytest.MonkeyPatch, *, reject_online: bool) -> list[str]:
    """Record the model id of every POST; optionally 404 the ``:online`` one.

    Returns the list the test asserts on, so "what went on the wire" is
    observed rather than assumed.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    # Keep the Tavily backstop out of this: it would fire on a sourceless
    # answer and is irrelevant to the fee.
    monkeypatch.setattr(config.settings, "tavily_api_key", "", raising=False)
    wire_model_ids: list[str] = []

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        payload = json.loads(request.data.decode("utf-8"))
        model_id = payload["model"]
        wire_model_ids.append(model_id)
        if reject_online and model_id.endswith(":online"):
            raise _search_rejected_error()
        return _Body(_answer_body())

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return wire_model_ids


def _produce(*, search: bool, model_id: str = _BARE_MODEL_ID) -> Any:
    return provider_execution_service.produce_initial_answer(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options with no trigger phrases",
        model_slot=ModelSlot(slot_number=1, model_id=model_id, search=search),
        credential_source=ProviderCredentialSource.APP_OWNED,
        openrouter_key="sk-or-test",
    )


def test_an_online_call_is_stamped_searched_and_went_out_with_the_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive partner (rule 7): the fee-bearing case IS detected.

    Turns RED when: the ``searched`` stamp is dropped from ``_post_messages``
    (the transport that actually POSTs, which ``_post_openrouter`` delegates
    to), from ``LiveProviderResult``, from ``_completed_answer``, or from the
    live branch of ``produce_initial_answer``.
    """
    wire = _install(monkeypatch, reject_online=False)
    answer = _produce(search=True)
    assert wire == [_ONLINE_MODEL_ID], "the searching call must POST the :online id"
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.token_usage is not None, "an unmeasurable slot cannot test the fee"
    assert answer.searched is True


def test_a_search_disabled_slot_never_posts_online_and_is_not_stamped_searched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slot the caller opted out of search for owes no fee, and the wire
    confirms why: the suffix never went out.

    Turns RED when: ``searched`` is hardcoded ``True``, or is derived from
    anything that ignores the wire id (``provider_path`` is
    ``OPENROUTER_SEARCH`` on this very answer, so a fee keyed on THAT would
    wrongly charge this slot).
    """
    wire = _install(monkeypatch, reject_online=False)
    answer = _produce(search=False)
    assert wire == [_BARE_MODEL_ID], "a search-disabled slot must POST the bare id only"
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.token_usage is not None
    # The trap this guards: provider_path is OPENROUTER_SEARCH even here.
    assert answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    assert answer.searched is False


def test_a_rejected_online_attempt_billed_as_the_bare_retry_is_not_stamped_searched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE case that separates outcome from intent.

    ``search=True`` (the intent) but the ``:online`` POST is refused 404 and a
    second, BARE POST serves the answer. Only the bare call was billed, so no
    search fee is owed. Two POSTs are asserted so the retry is proven to have
    happened rather than inferred — if the first attempt had succeeded there
    would be one, and the flag's value would prove nothing.

    Turns RED when: ``searched`` is derived from ``ModelSlot.search``, from
    ``provider_path``, from ``provider_attempt_order``, or from the id the
    caller INTENDED rather than the id the serving response came from. Each of
    those reports True here and would over-charge this slot by the flat fee on
    a receipt labelled ``measured``.
    """
    wire = _install(monkeypatch, reject_online=True)
    answer = _produce(search=True)
    assert wire == [_ONLINE_MODEL_ID, _BARE_MODEL_ID], (
        "the :online attempt must be refused and retried on the bare id"
    )
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.token_usage is not None
    assert answer.searched is False


def test_a_colon_bearing_model_id_is_not_mistaken_for_a_search_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag must test for the ``:online`` SUFFIX, not for a colon.

    Every other test in this file uses ``openai/gpt-4o-mini``, which has no
    colon at all — so a looser predicate like ``":" in model_id`` agrees with
    the correct one on all of them and survives. Adversarial review made
    exactly that substitution and the entire suite stayed green.

    The case is real, not contrived: ``_MODEL_ID_RE`` accepts a colon in the
    model half of the id, the live catalog serves ``:free`` and ``:preview``
    variants, and ``_UNAUTHENTICATED_VARIANT_SUFFIXES`` filters them only when
    picking DEFAULTS — a caller-supplied slot keeps whatever it was given. Under
    the loose predicate a ``:free`` slot with search OFF is stamped as having
    searched and is charged a fee it never incurred, on a receipt the UI labels
    ``measured``.

    Turns RED when: the predicate becomes ``":" in model_id``, a split on
    ``":"``, a ``!= bare_model_id`` comparison, or anything else that treats a
    variant suffix as a search suffix.
    """
    wire = _install(monkeypatch, reject_online=False)
    answer = _produce(search=False, model_id=_VARIANT_MODEL_ID)
    assert wire == [_VARIANT_MODEL_ID], "the id must go on the wire unchanged"
    assert ":" in _VARIANT_MODEL_ID, "this test is pointless unless the id has a colon"
    assert not _VARIANT_MODEL_ID.endswith(":online")
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.token_usage is not None
    assert answer.searched is False


def test_a_colon_bearing_model_id_still_reports_searched_when_online_is_appended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive partner for the test above (rule 7): the colon-bearing id
    is not simply excluded from ever earning a fee.

    With search ON, the ``:online`` suffix is appended to the variant id and
    that composite is what goes on the wire, so the fee IS owed.

    Turns RED when: the predicate anchors on the whole id rather than its
    suffix (e.g. an equality test against a known-online id), which would
    report False here and UNDER-charge a real searching call.
    """
    wire = _install(monkeypatch, reject_online=False)
    answer = _produce(search=True, model_id=_VARIANT_MODEL_ID)
    assert wire == [f"{_VARIANT_MODEL_ID}:online"]
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.token_usage is not None
    assert answer.searched is True
