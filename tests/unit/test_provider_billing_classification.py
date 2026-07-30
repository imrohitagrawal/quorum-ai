"""F-06: the provider seam must express THREE outcomes, not two.

``_post_openrouter`` used to collapse every failure to ``None``, which made
"the provider refused the request before inference, so nothing was billed"
indistinguishable from "a request was dispatched and may already have been
billed". Both readings are needed and they pull in OPPOSITE directions:

* treat an unbilled refusal as billed and a perfectly measurable run is
  downgraded to ``estimated`` and the SERVED figure jumps to the pre-run
  estimate (which prices calls that were never made);
* treat a billed failure as unbilled and the charge leaves no usage entry at
  all, so ``_actual_cost``'s ``all(usage is not None for ... in [])`` passes
  VACUOUSLY and the receipt is served ``measured`` with dollars missing.

So there are now three returns from ``_post_openrouter`` — ``None`` (provably
not billed), ``_DISPATCH_UNMEASURED`` (dispatched, maybe billed, no usage), and
a ``LiveProviderResult`` (possibly with blank text, carrying whatever usage the
provider stated) — and ``call_with_prompt`` maps them to ``None`` / a blank
marker / the result.

Every test drives the REAL code through the ``product_app.providers.urlopen``
seam (network-free, $0) and asserts CARDINALITY: how many POSTs were actually
issued alongside what came back. Asserting only the outcome is what let the
original defect survive.
"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest

from product_app import config
from product_app.model_slots import ModelSlot
from product_app.provider_keys import ProviderCredentialSource
from product_app.providers import (
    NOTICE_PROVIDER_UNAVAILABLE,
    InitialAnswerStatus,
    LiveProviderResult,
    ProviderPath,
    TokenUsage,
    provider_execution_service,
)

#: The provider's OWN statement of what it consumed. Its presence is what makes
#: "this call was billed" a measurement rather than a guess.
_BILLED = {"prompt_tokens": 4000, "completion_tokens": 700, "total_tokens": 4700}
_BILLED_USAGE = TokenUsage(prompt_tokens=4000, completion_tokens=700, total_tokens=4700)

_MODEL_ID = "openai/gpt-4o-mini"


class _Body:
    """A 200 whose body read returns ``payload``."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _RaisingBody:
    """A 200 whose body read dies mid-stream — the request WAS billed."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def read(self) -> bytes:
        raise self._exc

    def __enter__(self) -> _RaisingBody:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _completion(content: object) -> bytes:
    return json.dumps(
        {
            "choices": [{"finish_reason": "length", "message": {"content": content}}],
            "usage": _BILLED,
        }
    ).encode()


def _install(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[int]:
    """Point ``providers.urlopen`` at ``outcome`` and count POSTs issued.

    ``outcome`` is either an exception INSTANCE (raised in place of the
    connection) or a context-manager response object.
    """
    monkeypatch.setattr(config.settings, "openrouter_live_execution_enabled", True, raising=False)
    posts = [0]

    def fake_urlopen(request: Any, timeout: float = 0) -> Any:
        posts[0] += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("product_app.providers.urlopen", fake_urlopen)
    return posts


def _http_error(code: int) -> HTTPError:
    return HTTPError(
        url="https://openrouter.ai/api/v1/chat/completions",
        code=code,
        msg="upstream said no",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )


def _call(model_id: str = _MODEL_ID) -> LiveProviderResult | None:
    return provider_execution_service.call_with_prompt(
        openrouter_key="sk-or-test",
        model_id=model_id,
        system_prompt="s",
        user_prompt="u",
    )


# --- row group 1: the provider REFUSED the request -> nothing was billed ------
#
# ``call_with_prompt`` must return a bare ``None`` so the caller records NO
# usage entry. This is what keeps a measurable run ``measured``; recording an
# entry here is the regression that inflated a $0.0051 receipt to $0.0246.


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429])
def test_request_rejected_before_inference_is_reported_as_not_billed(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    posts = _install(monkeypatch, _http_error(status))
    result = _call()
    assert posts[0] == 1, "the POST was issued, it was the PROVIDER that refused"
    assert result is None, f"HTTP {status} precedes inference; it must read as not billed"


def test_connection_that_never_landed_is_reported_as_not_billed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS failure / connection refused: the model never saw the request."""
    posts = _install(monkeypatch, URLError(ConnectionRefusedError(61, "Connection refused")))
    assert _call() is None
    assert posts[0] == 1


def test_search_rejected_variant_is_reported_as_not_billed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 400/404 on a ``:online`` model id is the search-unsupported signal.

    ``call_with_prompt`` does not retry, and the rejection still precedes
    inference, so it must read as not billed.
    """
    posts = _install(monkeypatch, _http_error(404))
    assert _call(model_id=f"{_MODEL_ID}:online") is None
    assert posts[0] == 1


@pytest.mark.parametrize(
    ("key", "model_id"),
    [("", _MODEL_ID), ("sk-or-test", "")],
    ids=["no-key", "no-model-id"],
)
def test_pre_dispatch_guards_issue_no_post_and_report_not_billed(
    monkeypatch: pytest.MonkeyPatch, key: str, model_id: str
) -> None:
    posts = _install(monkeypatch, _http_error(500))
    result = provider_execution_service.call_with_prompt(
        openrouter_key=key, model_id=model_id, system_prompt="s", user_prompt="u"
    )
    assert posts[0] == 0, "nothing may leave the process when a credential guard trips"
    assert result is None


# --- row group 2: dispatched, possibly billed, no usage captured --------------
#
# ``call_with_prompt`` must return a BLANK-TEXT marker with ``usage=None`` so
# the caller falls back to templated prose but still records an entry, which
# forces ``estimated``. Anything that RAISES out of here instead is finding A:
# the exception escapes the whole stack and the billed call leaves no trace.


def _assert_dispatched_unmeasured(result: LiveProviderResult | None) -> None:
    assert result is not None, "a possibly-billed call must not read as 'not billed'"
    assert result.answer_text == "", "no usable text arrived"
    assert result.usage is None, "no usage arrived either — the call is unmeasurable"


@pytest.mark.parametrize("status", [500, 502, 503, 504, 418])
def test_non_refusal_http_error_is_reported_as_dispatched_unmeasured(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """A 5xx can follow a generation that already consumed tokens."""
    posts = _install(monkeypatch, _http_error(status))
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


def test_connect_timeout_is_reported_as_dispatched_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``urlopen`` reports a connect timeout as ``URLError(TimeoutError())``.

    A timeout cannot be distinguished from a slow generation, so it is treated
    as possibly billed — the conservative direction.
    """
    posts = _install(monkeypatch, URLError(TimeoutError("timed out")))
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


def test_read_timeout_is_reported_as_dispatched_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare ``TimeoutError`` from the body read follows a real generation."""
    posts = _install(monkeypatch, _RaisingBody(TimeoutError("read timed out")))
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


def test_unparsable_body_is_reported_as_dispatched_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A body ARRIVED, so the call billed; we simply cannot read it."""
    posts = _install(monkeypatch, _Body(b"<html>502 Bad Gateway</html>"))
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


def test_extractor_failure_on_a_good_body_is_reported_as_dispatched_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The body block's ``except`` must be broad, not just ``JSONDecodeError``.

    A mutation narrowing it back to ``except json.JSONDecodeError`` SURVIVED the
    suite, because the only other body-block test uses an HTML body — which IS a
    ``JSONDecodeError`` and so cannot tell the two apart. This case is the
    difference: a perfectly good, priceable 200 whose EXTRACTION raises (a
    ``RecursionError`` out of ``json.loads`` on a pathologically nested body, or
    a bug in ``_extract_usage``). Narrow the clause and the exception escapes
    ``_post_openrouter`` entirely — on the DEBATE path there is no
    ``_safe_section_result`` to swallow it, so a billed call's usage goes down
    with it. That is finding A's shape, one frame lower.
    """

    def _boom(_payload: object) -> None:
        raise RecursionError("maximum recursion depth exceeded")

    posts = _install(
        monkeypatch,
        _Body(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()),
    )
    monkeypatch.setattr("product_app.providers._extract_usage", _boom)
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


@pytest.mark.parametrize(
    "exc",
    [
        http.client.IncompleteRead(b'{"choices":[{"message":{"content":"par'),
        http.client.RemoteDisconnected("Remote end closed connection"),
        ssl.SSLError("decryption failed or bad record mac"),
        ConnectionResetError(54, "Connection reset by peer"),
    ],
    ids=["incomplete-read", "remote-disconnected", "ssl-error", "conn-reset"],
)
def test_torn_body_is_reported_as_dispatched_unmeasured(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    """FINDING A, closed.

    None of these are ``URLError`` / ``TimeoutError`` / ``HTTPError`` /
    ``JSONDecodeError``. Before the catch-all they escaped ``_post_openrouter``,
    escaped ``call_with_prompt``, and ``_safe_section_result`` swallowed them
    into ``live=None`` — five billed POSTs, zero usage entries, receipt served
    ``measured``.
    """
    posts = _install(monkeypatch, _RaisingBody(exc))
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


def test_non_utf8_body_is_reported_as_dispatched_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``.decode()`` raising ``UnicodeDecodeError`` is also post-dispatch."""
    posts = _install(monkeypatch, _Body(b"\xff\xfe\x00garbage"))
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


def test_call_with_prompt_never_raises_once_a_request_was_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The invariant, stated once and asserted generically.

    Enumerating exception classes is exactly what failed before (the ``except
    (URLError, TimeoutError)`` list did not include ``IncompleteRead``), so the
    guarantee is now structural: past ``urlopen``, this seam RETURNS.
    """
    exotic: list[BaseException] = [
        RuntimeError("something nobody predicted"),
        MemoryError(),
        RecursionError("maximum recursion depth exceeded"),
        OSError(9, "Bad file descriptor"),
    ]
    for exc in exotic:
        posts = _install(monkeypatch, _RaisingBody(exc))
        _assert_dispatched_unmeasured(_call())
        assert posts[0] == 1, f"{type(exc).__name__} must not stop the POST from counting"


def test_a_pre_dispatch_encoding_failure_is_conservatively_reported_as_billed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PIN the deliberate ASYMMETRY, so it is a choice and not an accident.

    A non-latin-1 character in a header value (an API key pasted with a smart
    quote) raises ``UnicodeEncodeError`` out of ``http.client.putheader``
    before a byte leaves the process. ``AbstractHTTPHandler.do_open`` wraps
    only ``OSError`` into ``URLError``, so it reaches the catch-all and is
    reported as possibly-billed even though nothing was.

    That is the intended direction. Over-reporting a charge costs a receipt its
    ``measured`` label; under-reporting one hides real dollars behind a
    ``measured`` label, which is the dishonesty this whole change exists to
    prevent. Only ``URLError`` — CPython's own "the opener failed" signal — is
    trusted to mean "not billed".
    """
    exc = UnicodeEncodeError("latin-1", "Bearer sk’or", 9, 10, "ordinal not in range(256)")
    posts = _install(monkeypatch, exc)
    _assert_dispatched_unmeasured(_call())
    assert posts[0] == 1


def test_an_unrecognised_post_dispatch_exception_is_logged_at_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The catch-all must not let a BUG degrade receipts quietly.

    Classification stays a catch-all — guessing a return value from an
    exception class is exactly what finding A was — but the LOG LEVEL splits:
    a real network event (torn body, TLS error, reset socket) is a WARNING,
    while anything unrecognised is far more likely to be a bug in our own
    response handling and is an ERROR.

    Only the class NAME is recorded. ``str(exc)`` is never logged, because an
    exception message here can carry key material verbatim — see
    ``test_a_pre_dispatch_encoding_failure_...``, whose payload is the
    ``Authorization`` header.
    """
    secret_bearing = AssertionError("Bearer sk-or-v1-REALKEYMATERIAL")
    _install(monkeypatch, _RaisingBody(secret_bearing))
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        _assert_dispatched_unmeasured(_call())
    records = [r for r in caplog.records if r.msg == "upstream_provider_transport_error"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert getattr(records[0], "error_type", None) == "AssertionError"
    assert "REALKEYMATERIAL" not in caplog.text, "an exception message must never be logged"


@pytest.mark.parametrize(
    ("exc", "event"),
    [
        (http.client.IncompleteRead(b"partial"), "upstream_provider_transport_error"),
        (ssl.SSLError("bad record mac"), "upstream_provider_transport_error"),
        (ConnectionResetError(54, "Connection reset by peer"), "upstream_provider_transport_error"),
    ],
    ids=["incomplete-read", "ssl-error", "conn-reset"],
)
def test_a_real_transport_failure_stays_a_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exc: BaseException,
    event: str,
) -> None:
    """The other direction: routine network noise must not page anyone."""
    _install(monkeypatch, _RaisingBody(exc))
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        _assert_dispatched_unmeasured(_call())
    records = [r for r in caplog.records if r.msg == event]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING


def test_an_unreadable_body_is_a_warning_not_an_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed JSON is the BODY's fault, not ours."""
    _install(monkeypatch, _Body(b"<html>502 Bad Gateway</html>"))
    with caplog.at_level(logging.DEBUG, logger="product_app.providers"):
        _assert_dispatched_unmeasured(_call())
    records = [r for r in caplog.records if r.msg == "upstream_provider_body_unreadable"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert getattr(records[0], "error_type", None) == "JSONDecodeError"


# --- row group 3: a body arrived, so the provider's stated charge is REAL -----


def test_empty_completion_keeps_the_usage_the_provider_stated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FINDING C, closed.

    The comment on ec5c853 claimed the marker carried "whatever usage we
    captured" for "an HTTP 200 whose completion is empty". It could not:
    ``_post_openrouter`` hit ``if not content: return None`` one frame BEFORE
    ``usage = _extract_usage(parsed)``, so the provider's own statement of what
    it had just charged (prompt 4000 / completion 700) was discarded. The
    extraction now happens first and the result is returned WITH its usage, so
    the dollars are priced instead of merely forcing a downgrade.
    """
    posts = _install(monkeypatch, _Body(_completion("")))
    result = _call()
    assert posts[0] == 1
    assert result is not None
    assert result.answer_text == ""
    assert result.usage == _BILLED_USAGE


def test_null_completion_keeps_the_usage_the_provider_stated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``"content": null`` — the shape a truncated generation actually returns."""
    _install(monkeypatch, _Body(_completion(None)))
    result = _call()
    assert result is not None
    assert result.answer_text == ""
    assert result.usage == _BILLED_USAGE


def test_empty_completion_without_a_usage_object_is_unmeasurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``usage`` object -> a recorded but unpriceable entry, never a guess."""
    body = json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
    _install(monkeypatch, _Body(body))
    result = _call()
    assert result is not None
    assert result.answer_text == ""
    assert result.usage is None


def test_normal_completion_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """CONTROL: without this, the tests above could pass on a broken happy path."""
    posts = _install(monkeypatch, _Body(_completion("A usable critique with substance.")))
    result = _call()
    assert posts[0] == 1
    assert result is not None
    assert result.answer_text == "A usable critique with substance."
    assert result.usage == _BILLED_USAGE


# --- the initial-answer path: the LIVE-CALL CARDINALITY must not move --------
#
# ``_live_openrouter_response`` shares ``_post_openrouter`` with the
# debate/synthesis path, and ``_post_openrouter`` returns a RESULT where it used
# to return ``None`` (empty completion) plus a new sentinel. The number of POSTs
# each upstream outcome provokes is the billing contract these tests exist for,
# and #171 does not touch it — the guard it adds runs AFTER every live attempt
# has been made and decided.
#
# What #171 DID change is what the slot then looks like. These tests used to be
# named ``..._still_falls_back_to_local_simulation`` and asserted a COMPLETED
# LOCAL_SIMULATION answer carrying invented text. That was the defect, pinned:
# the invented answer went on to the debate, the synthesis, the agreement count
# and the source-coverage figure as though a model had written it. The slot is
# now reported MISSING instead, so the assertions below assert exactly that —
# with the POST counts untouched, which is what proves the billing contract
# survived the change.

_SLOT = ModelSlot(slot_number=1, model_id=_MODEL_ID)


def _produce_initial() -> Any:
    return provider_execution_service.produce_initial_answer(
        account_id=uuid4(),
        query_run_id=uuid4(),
        query_text="Compare durable options with no trigger phrases",
        model_slot=_SLOT,
        credential_source=ProviderCredentialSource.APP_OWNED,
        openrouter_key="sk-or-test",
    )


@pytest.mark.parametrize(
    ("label", "outcome", "expected_posts"),
    [
        ("empty-content", _Body(_completion("")), 1),
        ("null-content", _Body(_completion(None)), 1),
        # 404 on the ``:online`` variant is the search-unsupported signal, so
        # the bare model id is retried once — TWO POSTs. Pinned here because
        # that retry must survive the new sentinel: ``_DISPATCH_UNMEASURED`` is
        # not ``_SEARCH_REJECTED``, so a 5xx must NOT trigger it.
        ("http-404", _http_error(404), 2),
        ("http-500", _http_error(500), 1),
        ("read-timeout", _RaisingBody(TimeoutError("read timed out")), 1),
    ],
)
def test_initial_answer_path_reports_the_slot_missing_and_invents_nothing(
    monkeypatch: pytest.MonkeyPatch, label: str, outcome: Any, expected_posts: int
) -> None:
    """#171: live execution on, no usable live text -> the slot is MISSING.

    The billing half is unchanged and is asserted first: each upstream outcome
    provokes exactly the same number of POSTs it always did.

    The honesty half is the change. Every assertion is a CARDINALITY on what
    the slot contributes downstream, not a status check:

    * ``citation_coverage.answer_count == 0`` — the slot is out of the
      source-coverage DENOMINATOR. Before #171 it carried 1, and a fabricated
      ``is_fallback=False`` demo source put it in the NUMERATOR too, so a run
      with one real answer and three of these reported 100% coverage.
    * ``len(answer.sources) == 0`` — nothing fabricated can be cited.
    * ``answer_text == ""`` — no invented text reaches the debate or the
      synthesis prompt, both of which print every COMPLETED answer verbatim.

    What turns it red: restore the old tail of ``produce_initial_answer`` (drop
    the ``_live_execution_enabled`` guard) and the slot comes back COMPLETED
    with one source and ``answer_count == 1``. Verified by mutation.
    """
    posts = _install(monkeypatch, outcome)
    answer = _produce_initial()
    assert posts[0] == expected_posts, f"{label}: live-attempt cardinality changed"

    assert answer.status is InitialAnswerStatus.FAILED
    assert answer.error_code == "PROVIDER_UNAVAILABLE"
    # Honest about what was attempted: the OpenRouter call really was made.
    assert answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    assert answer.provider_attempt_order == [ProviderPath.OPENROUTER_SEARCH]
    assert answer.fallback_used is False
    assert answer.token_usage is None, "a missing slot must never carry live usage"
    assert answer.provider_notice == NOTICE_PROVIDER_UNAVAILABLE

    # The cardinalities, which are the point.
    assert answer.answer_text == ""
    assert len(answer.sources) == 0
    assert answer.citation_coverage.answer_count == 0
    assert answer.citation_coverage.sourced_answer_count == 0


def test_initial_answer_path_torn_body_now_degrades_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ONE initial-path behaviour this change deliberately alters.

    On origin/main a torn body raised ``http.client.IncompleteRead`` straight
    out of ``produce_initial_answer`` (verified by running this module against
    origin/main's ``providers.py``: every other case passes, this one raises).
    The exception then hit ``except Exception: continue`` in
    ``query_runs._produce_one_initial_answer``'s collection loop, so the slot
    was silently DROPPED — no answer, no failure notice, just a missing model.

    The catch-all in ``_post_messages`` converts that into an honest degraded
    slot instead. Since #171 that degraded slot is a MISSING one rather than a
    simulated one, and the cost label still does not move: a FAILED slot fails
    ``initial_fully_captured``'s ``status is COMPLETED`` requirement just as a
    LOCAL_SIMULATION slot failed its ``provider_path`` requirement, so a torn
    body that may have been billed still forces ``estimated``. That equivalence
    is asserted end-to-end in ``tests/resilience/test_fault_injection_lane.py``
    (``test_mixed_live_and_faulted_run_counts_only_the_answers_that_arrived``).

    What turns it red: drop the ``except Exception`` catch-all in
    ``_post_messages`` and ``IncompleteRead`` propagates out of
    ``produce_initial_answer`` — the call itself raises.
    """
    posts = _install(
        monkeypatch,
        _RaisingBody(http.client.IncompleteRead(b'{"choices":[{"message":{"content":"par')),
    )
    answer = _produce_initial()  # must not raise
    assert posts[0] == 1
    assert answer.status is InitialAnswerStatus.FAILED
    assert answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    assert answer.provider_attempt_order == [ProviderPath.OPENROUTER_SEARCH]
    assert answer.token_usage is None
    assert answer.provider_notice == NOTICE_PROVIDER_UNAVAILABLE
    # A torn body is exactly the shape most likely to smuggle a partial,
    # plausible-looking answer through: assert there is no text at all.
    assert answer.answer_text == ""
    assert answer.citation_coverage.answer_count == 0


def test_initial_answer_path_still_serves_a_whitespace_only_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PIN: whitespace-only content was a live COMPLETED answer before F-06.

    ``_post_openrouter`` returned the RAW content, so ``"   "`` passed its
    ``if not content`` guard. The replacement guard in
    ``_live_openrouter_response`` is deliberately ``not result.answer_text`` and
    NOT ``.strip()`` so this stays true; tightening it would be a silent
    behaviour change smuggled in under a billing fix.
    """
    _install(monkeypatch, _Body(_completion("   \n  ")))
    answer = _produce_initial()
    assert answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    assert answer.provider_attempt_order == [ProviderPath.OPENROUTER_SEARCH]
    assert answer.answer_text == "   \n  "
    assert answer.token_usage == _BILLED_USAGE


def test_initial_answer_path_control_live_answer_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTROL: the happy initial-answer path still produces a live slot."""
    _install(monkeypatch, _Body(_completion("A real answer from the model.")))
    answer = _produce_initial()
    assert answer.status is InitialAnswerStatus.COMPLETED
    assert answer.provider_path is ProviderPath.OPENROUTER_SEARCH
    assert answer.provider_attempt_order == [ProviderPath.OPENROUTER_SEARCH]
    assert answer.answer_text == "A real answer from the model."
    assert answer.token_usage == _BILLED_USAGE
