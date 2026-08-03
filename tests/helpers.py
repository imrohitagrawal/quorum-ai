from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from threading import BoundedSemaphore

from fastapi.testclient import TestClient


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
