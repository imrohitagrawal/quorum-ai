"""No user query text may leave the process in a Sentry payload.

MEASURED 2026-08-07, by pointing the real Sentry init at a loopback collector
and running the suite. Two independent paths carried the user's question off
the machine, and the redaction hook stopped neither:

1. **``before_send`` is not called for transactions.** Counted on one run:

       envelope item   request.data
       event           [REDACTED]   8 of 8
       transaction     RAW          9 of 9

   Transactions need ``before_send_transaction``, which was not set. With
   ``traces_sample_rate=0.1`` that is ~10% of production requests shipping the
   raw request body, ``query_text`` included.

2. **Stack-frame locals were never touched.** In error events the question
   appeared under ``exception.values[].stacktrace.frames[].vars`` as
   ``payload=QueryRunCreateRequest(query_text='...')``, as raw
   ``body_bytes=b'{"query_text":"..."}'``, and inside ``query_run``.
   ``_redact_sentry_event`` only rewrote ``request.data`` and ``extra``.

The old docstring claimed the hook "ensures that if a future change
accidentally includes request bodies, query text is still redacted". That was
false in both directions, which is why these tests assert on STRUCTURE and on a
whole-payload sweep rather than on the one key the old code happened to handle.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from product_app.main import _redact_sentry_event, _redact_sentry_transaction

#: A recognisable stand-in for a user's question. Every assertion below is that
#: this string does not survive anywhere in the outgoing payload.
SECRET_QUERY = "WHAT-THE-USER-ACTUALLY-ASKED-0123456789"


def _payload_contains_query(event: object) -> bool:
    """True if ``SECRET_QUERY`` survives ANYWHERE in the serialised payload.

    Deliberately a whole-payload sweep, not a key lookup. The defect was that
    the redaction only knew about the keys someone had thought of; a test that
    checks the same keys would have passed against the broken code.
    """
    return SECRET_QUERY in json.dumps(event, default=repr)


def _event_with_query_everywhere() -> dict[str, Any]:
    """An event carrying the query in every place it was measured escaping."""
    return {
        "request": {
            "url": "http://testserver/v1/query-runs",
            "data": {"query_text": SECRET_QUERY, "model_slots": ["openai/gpt-4o-mini"]},
        },
        "extra": {"query_preview": SECRET_QUERY, "unrelated": "keep-me"},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "create_query_run",
                                "vars": {
                                    "payload": (
                                        f"QueryRunCreateRequest(query_text='{SECRET_QUERY}')"
                                    ),
                                    "body_bytes": f'b\'{{"query_text":"{SECRET_QUERY}"}}\'',
                                    "account_id": "acct-123",
                                },
                            },
                            {
                                "function": "dispatch",
                                "vars": {"query_run": f"QueryRun(query_text='{SECRET_QUERY}')"},
                            },
                        ]
                    },
                }
            ]
        },
    }


def test_the_fixture_really_carries_the_query() -> None:
    """POSITIVE PARTNER (rule 7) for every absence check below.

    All the other tests assert the query is GONE. That is trivially true over a
    payload that never contained it. This proves the fixture is a real
    reproduction before anything is asserted about removing it.

    WHAT TURNS THIS RED: stop seeding ``SECRET_QUERY`` into the fixture.
    """
    assert _payload_contains_query(_event_with_query_everywhere())


def test_an_error_event_does_not_carry_the_query_anywhere() -> None:
    """The whole-payload guarantee for error events.

    WHAT TURNS THIS RED: drop the stack-frame ``vars`` scrubbing from
    ``_redact_sentry_event`` — ``request.data`` alone leaves the query in
    ``exception.values[].stacktrace.frames[].vars``.
    """
    cleaned = _redact_sentry_event(cast(Any, _event_with_query_everywhere()), {})
    assert cleaned is not None
    assert not _payload_contains_query(cleaned), (
        "the user's query survived redaction somewhere in the error payload"
    )


def test_a_transaction_does_not_carry_the_query_anywhere() -> None:
    """The same guarantee for transactions, which took a SEPARATE hook.

    This is the path that was completely unprotected: ``before_send`` is never
    invoked for transaction items, so ``request.data`` shipped raw.

    WHAT TURNS THIS RED: remove ``before_send_transaction`` from the
    ``sentry_sdk.init`` call, or make ``_redact_sentry_transaction`` return its
    argument unchanged.
    """
    cleaned = _redact_sentry_transaction(cast(Any, _event_with_query_everywhere()), {})
    assert cleaned is not None
    assert not _payload_contains_query(cleaned), (
        "the user's query survived in a TRANSACTION payload — this is the ~10% "
        "of production requests sampled by traces_sample_rate"
    )


def test_redaction_keeps_the_fields_an_operator_needs() -> None:
    """Prove BOTH directions: the false positive is gone AND the event is still useful.

    A hook that returned ``{}`` would pass every check above and destroy error
    tracking. This pins the diagnostic fields that must survive.

    WHAT TURNS THIS RED: scrub indiscriminately — e.g. blank every ``vars`` key
    rather than only those carrying user text.
    """
    cleaned = _redact_sentry_event(cast(Any, _event_with_query_everywhere()), {})
    assert cleaned is not None
    blob = json.dumps(cleaned, default=repr)
    assert "create_query_run" in blob, "the frame's function name was destroyed"
    assert "ValueError" in blob, "the exception type was destroyed"
    assert "acct-123" in blob, "a non-user-text local was destroyed"
    assert "keep-me" in blob, "an unrelated extra key was destroyed"
    assert cleaned["request"]["url"] == "http://testserver/v1/query-runs", (
        "the request URL was destroyed — it carries no user text and is needed"
    )


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"request": {}},
        {"exception": {"values": []}},
        {"exception": {"values": [{"stacktrace": {"frames": []}}]}},
        {"exception": {"values": [{"stacktrace": {}}]}},
        {"exception": {"values": [{}]}},
        {"extra": {}},
        # Non-dict members at each level. These are not hypothetical padding:
        # Sentry payloads are assembled from many integrations, and a single
        # unexpected type here would raise inside ``before_send`` and DROP the
        # error report entirely — failing closed on the very signal we keep
        # Sentry for. Each case exercises one defensive ``continue``.
        {"exception": {"values": ["not-a-dict"]}},
        {"exception": {"values": [{"stacktrace": {"frames": ["not-a-dict"]}}]}},
        {"exception": {"values": [{"stacktrace": {"frames": [{"vars": "not-a-dict"}]}}]}},
        {"exception": {"values": [{"stacktrace": {"frames": [{"vars": None}]}}]}},
        {"exception": "not-a-dict"},
        {"request": "not-a-dict"},
        {"extra": "not-a-dict"},
    ],
)
def test_redaction_survives_a_partial_event(event: dict[str, Any]) -> None:
    """Sentry payload shapes vary; a KeyError here would DROP a real error report.

    WHAT TURNS THIS RED: index into a nested key without a guard, e.g.
    ``event["exception"]["values"][0]["stacktrace"]["frames"]``; or remove any
    of the ``isinstance`` guards, which the non-dict cases above exercise.
    """
    assert _redact_sentry_event(cast(Any, dict(event)), {}) is not None
    assert _redact_sentry_transaction(cast(Any, dict(event)), {}) is not None


def test_both_hooks_are_wired_into_the_sentry_init() -> None:
    """A correct function that is never installed protects nothing.

    The measured defect was not a broken redactor — it was a redactor that the
    transaction path never called. Assert the WIRING, not just the behaviour.

    WHAT TURNS THIS RED: delete either ``before_send=`` or
    ``before_send_transaction=`` from the ``sentry_sdk.init`` call.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "src" / "product_app" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "before_send=_redact_sentry_event" in src, (
        "the error-event redactor is no longer wired into sentry_sdk.init"
    )
    assert "before_send_transaction=_redact_sentry_transaction" in src, (
        "the TRANSACTION redactor is no longer wired into sentry_sdk.init — "
        "transactions bypass before_send entirely, which is the 2026-08-07 defect"
    )


def test_local_variable_capture_is_disabled_at_the_source() -> None:
    """The scrubber is defence in depth; THIS is the guarantee.

    Pattern-scrubbing frame locals means enumerating the ways user text can be
    reached, and enumeration is the losing game this session already lost once
    (on assertion wrappers). Turning capture off at the SDK removes the class.

    WHAT TURNS THIS RED: drop ``include_local_variables=False`` from
    ``sentry_sdk.init``.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "src" / "product_app" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "include_local_variables=False" in src, (
        "sentry_sdk now captures frame locals again — the 2026-08-07 leak "
        "reached Sentry through stacktrace.frames[].vars"
    )


def test_every_redacted_field_name_really_occurs_in_src() -> None:
    """Rule 1a: pin the list to the tree so a rename cannot silently shrink it.

    A field renamed in ``src/`` while this tuple keeps the old spelling would
    leave that prose unredacted, and nothing else would notice. This does not
    prove the list is COMPLETE — nothing offline can — but it does prove no
    entry has rotted into a dead string.

    WHAT TURNS THIS RED: rename e.g. ``query_text`` throughout ``src/`` without
    updating ``_USER_TEXT_FIELDS``.
    """
    from pathlib import Path

    from product_app.main import _USER_TEXT_FIELDS

    src_dir = Path(__file__).resolve().parents[2] / "src" / "product_app"
    corpus = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(src_dir.rglob("*.py")) if p.is_file()
    )
    assert corpus, "no source read — this check would pass vacuously"
    dead = [f for f in _USER_TEXT_FIELDS if f not in corpus]
    assert not dead, (
        f"these entries in _USER_TEXT_FIELDS no longer occur anywhere in src/: {dead}. "
        "Either the field was renamed (update the tuple) or it is dead weight."
    )
    assert len(_USER_TEXT_FIELDS) >= 5, (
        "the redaction set shrank below the five fields measured leaking on "
        "2026-08-07 — removing one silently un-redacts that prose"
    )
