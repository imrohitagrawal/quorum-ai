from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore
from typing import Protocol
from uuid import UUID

from fastapi.testclient import TestClient


class ScopedEvent(Protocol):
    """The two fields every in-memory recorder event carries.

    Read-only properties on purpose: a recorder whose ``query_run_id`` is a
    plain ``UUID`` (provider, debate, synthesis, model-slot) still satisfies a
    protocol declaring ``UUID | None`` (cost, warning), which a mutable
    attribute would not.
    """

    @property
    def account_id(self) -> UUID: ...

    @property
    def query_run_id(self) -> UUID | None: ...


class EventRecorder[E: ScopedEvent](Protocol):
    """The read side of ``product_app``'s in-memory event recorders."""

    def list_events(self) -> list[E]: ...


def scoped_events[E: ScopedEvent](
    recorder: EventRecorder[E],
    *,
    account_id: UUID | None = None,
    query_run_id: UUID | None = None,
) -> list[E]:
    """Return only the events THIS test caused, from a process-global recorder.

    ``provider_event_recorder``, ``debate_event_recorder``,
    ``synthesis_event_recorder``, ``warning_event_recorder``,
    ``model_slot_event_recorder`` and ``cost_event_recorder`` are all
    process-global ring buffers shared with every other test in the session.
    A per-module ``clear_state`` fixture empties them, but clearing does not
    make a read safe: a background query-run worker thread from an EARLIER
    test can still be in flight and append to the same buffer after the
    clear. #104 measured that concretely — 1 of 14 sequential runs of one test
    saw ``len(provider_events) == 6`` where the test expected 4.

    So an unfiltered ``list_events()`` used for a count, an index, or an
    ``all(...)`` is coupled to every other writer in the process. Every event
    type carries ``account_id`` and ``query_run_id``, and every test mints
    fresh ``uuid4()`` values, so scoping by either keeps the assertion exact
    while making it independent of the rest of the suite.

    Passing neither key raises: a no-key call is an unfiltered read wearing
    this function's name, and that is the bug, not the fix. A read that
    genuinely must span every writer (the security-redaction sweep, which
    proves no secret reaches ANY event) calls ``list_events()`` directly with
    an ``# unscoped-ok: <reason>`` comment — see
    ``tests/unit/test_event_recorder_reads_are_scoped.py``.

    Args:
        recorder: the process-global recorder to read.
        account_id: keep only events for this account.
        query_run_id: keep only events for this run.

    Both keys together are an AND.
    """
    if account_id is None and query_run_id is None:
        raise ValueError(
            "scoped_events needs account_id and/or query_run_id: a call with "
            "neither is an unfiltered process-global read, which is the bug "
            "this helper exists to prevent (#209)."
        )
    return [
        event
        # unscoped-ok: this comprehension IS the shared scoping filter that every
        # other test call site goes through; it is the one place allowed to read
        # the whole process-global buffer, and it narrows it on the next line.
        for event in recorder.list_events()
        if (account_id is None or event.account_id == account_id)
        and (query_run_id is None or event.query_run_id == query_run_id)
    ]


def start_session(client: TestClient) -> dict[str, str]:
    response = client.get("/v1/session")
    response.raise_for_status()
    body = response.json()
    return {"x-csrf-token": body["csrf_token"]}


@contextmanager
def isolated_run_semaphore(permits: int) -> Iterator[BoundedSemaphore]:
    """Install a PRIVATE run-capacity semaphore for the body of a test.

    ``query_runs._run_semaphore`` is a process-global ``BoundedSemaphore``
    shared with every other test in the session — including any worker thread
    still in flight from an earlier one, which holds a permit until its run
    reaches a terminal state. A test that drains it and then tops it back up
    restores it to its BOUND rather than to the number of permits it actually
    drained. MEASURED (16-permit bound, one permit held by an in-flight
    worker): the drain takes 15, the restore puts the counter back to 16, and
    the worker's own ``release()`` then raises ``ValueError: Semaphore released
    too many times`` inside ``_execute_query_run_with_semaphore_release``'s
    ``finally`` — killing that thread and leaving the process cap permanently
    inflated for every later test. That is the shape that made the F-01 permit
    specs non-deterministic in a full-suite run.

    Swapping in a private semaphore removes the coupling in BOTH directions:
    nothing this test does can be seen by another test, and no other test's
    in-flight worker can be seen here. ``create_query_run`` captures the
    semaphore OBJECT when it reserves, and hands that object to the worker
    thread, so a run started inside this block returns its permit here even if
    the block has already exited.

    Args:
        permits: bound for the private semaphore. Use a small number (1) so
            "leaked" and "released" produce visibly different HTTP responses.
    """
    from product_app import query_runs

    private = BoundedSemaphore(permits)
    original = query_runs._run_semaphore  # noqa: SLF001 — the seam under test
    query_runs._run_semaphore = private  # noqa: SLF001
    try:
        yield private
    finally:
        query_runs._run_semaphore = original  # noqa: SLF001


def wait_for_free_permits(
    semaphore: BoundedSemaphore,
    expected: int,
    *,
    timeout_s: float = 20.0,
) -> int:
    """Block until ``semaphore`` reports ``expected`` free permits.

    The worker thread returns its permit in a ``finally`` after the run reaches
    a terminal state, so "the run finished" and "the permit is back" are two
    different instants. Poll the counter itself rather than the run status so
    there is no window where a caller sees a terminal run but the capacity has
    not yet come back. Returns the observed value so the caller can assert on
    it (and see the real number in the failure message).
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if semaphore._value == expected:  # noqa: SLF001 — asserting on the leak itself
            return expected
        time.sleep(0.01)
    return semaphore._value  # noqa: SLF001


def unreachable_recoveries[S](
    transitions: dict[S, set[S]],
    healthy: set[S],
) -> list[S]:
    """Return the states from which no sequence of events reaches ``healthy``.

    An **absorbing** state is one you can enter and never leave. It is invisible
    when a decision is written as a boolean expression, and obvious the moment
    the states are enumerated as a table.

    Why this exists, measured (quorum-ai, 2026-08-03): a ~40-line spend-cap
    predicate had FIVE defects found across four review passes, and **none were
    in the predicates** -- all were wiring. One of them was exactly this: a
    recovered store could never become "trustworthy" (a monotonic loss counter
    never resets) and could never be replaced (the reopen was gated on a
    staleness the recovery had just cleared), so every priced request was
    refused until a process restart. Each fix added a *term* to a boolean
    instead of a *row* to a table, which is why fixing one revealed the next.

    Usage: build ``transitions`` as ``{state: {reachable states}}`` over the
    real signal domain (``itertools.product`` is exhaustive for a space this
    size and strictly beats random search), name the states that mean "serving
    normally", and assert the result is empty.

    Deliberately plain BFS: for ~40 cells a model checker is a week of learning
    to decide what twenty lines settles.
    """
    recovers: set[S] = set(healthy)
    changed = True
    while changed:
        changed = False
        for state, successors in transitions.items():
            if state in recovers:
                continue
            if successors & recovers:
                recovers.add(state)
                changed = True
    return sorted((s for s in transitions if s not in recovers), key=repr)
