"""Behavioural (instrumentation-surviving) oracles for the RB-3 store lifecycle.

Ledger DEBT-008. ``tests/test_store_lifecycle.py`` and
``tests/test_store_shutdown_safety.py`` assert through the *environment* — the
garbage collector, a ``ResourceWarning`` finaliser, wall-clock thread joins, a
child interpreter. Those signals do not survive mutmut's trampoline (it retains
frames, so refcounts never drop, and it changes call latency), which is why they
are marked ``env_oracle`` and deselected from the mutation gate. The cost was a
blind spot: the RB-3 concurrency/leak-fix code had **no** oracle mutmut could
run, so mutants in ``close()``/``__del__``/``_close_open_stores`` survived
unkillable.

Everything here asserts only on state the code under test *owns*:

* ``_open_stores`` membership (a plain ``WeakSet``, a pure data assertion),
* ``store._closed`` and whether ``store._conn`` still answers,
* the arguments a lock double *records* — so "did close() give up within 20s of
  wall clock" becomes "did close() pass a finite timeout and take the give-up
  branch",
* ``__del__`` invoked by hand rather than by the collector.

No ``gc.collect()``, no ``threading``, no wall clock, no subprocess. This module
must stay that way: it is the one that runs under mutation.
"""

from __future__ import annotations

import math
import sqlite3
from types import ModuleType
from typing import Any

import pytest

from product_app import feedback_store as fs_mod
from product_app import run_history_store as rh_mod

#: (module, store factory) for both singleton stores. Both implementations are
#: independent copies of the same lifecycle, so every oracle runs against both.
_STORES = [
    pytest.param(rh_mod, rh_mod.RunHistoryStore, id="run_history"),
    pytest.param(fs_mod, fs_mod.FeedbackStore, id="feedback"),
]


class _RecordingLock:
    """Lock double that records how ``close()`` tried to take it.

    ``acquire`` returns whatever ``grant`` says and remembers the timeout it was
    handed (``None`` when called with no timeout at all). That turns the bounded
    acquire — the RB-3 invariant that keeps interpreter shutdown from hanging —
    into a deterministic argument assertion instead of a 20-second join.
    """

    def __init__(self, *, grant: bool) -> None:
        self._grant = grant
        self.acquire_timeouts: list[float | None] = []
        self.release_calls = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        self.acquire_timeouts.append(None if timeout == -1 else timeout)
        return self._grant

    def release(self) -> None:
        self.release_calls += 1

    def __enter__(self) -> _RecordingLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _is_dead(store: Any) -> bool:
    """True when the sqlite handle has actually been closed."""
    try:
        store._conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_construction_registers_the_store(module: ModuleType, factory: type) -> None:
    """``__init__`` must add the store to the process-exit registry.

    Kills the mutant that drops ``_open_stores.add(self)``: without it the exit
    hook has nothing to close and the live singleton leaks its handle — the
    original RB-3 defect.
    """
    store = factory(":memory:")
    try:
        assert store in module._open_stores
    finally:
        store.close()


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_close_deregisters_the_store(module: ModuleType, factory: type) -> None:
    """``close()`` must drop the store from the registry.

    Kills the mutant that drops ``_open_stores.discard(self)``. A closed store
    left in the registry makes the exit hook re-close it — harmless today only
    because ``close()`` is idempotent, which is a separate guarantee.
    """
    store = factory(":memory:")
    store.close()

    assert store not in module._open_stores


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_close_marks_closed_and_releases_the_handle(module: ModuleType, factory: type) -> None:
    """``close()`` sets ``_closed`` *and* actually closes the connection.

    Refcount-independent restatement of the leak test: the handle is dead
    because ``close()`` ran, not because the collector got round to it.
    """
    del module
    store = factory(":memory:")
    assert not store._closed
    assert not _is_dead(store)

    store.close()

    assert store._closed
    assert _is_dead(store)


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_close_is_idempotent(module: ModuleType, factory: type) -> None:
    """A second ``close()`` is a no-op — the body does not run twice.

    ``configure_for_tests`` closes explicitly and the exit hook may close the
    same instance again. Asserting only "no exception" would NOT kill the mutant
    that removes the ``if self._closed: return`` early exit, because a double
    ``sqlite3.Connection.close()`` is harmless (measured: that mutant survives a
    no-exception assertion). So the second call is made against a spy handle and
    the oracle is that it was never touched.
    """
    del module

    class _SpyConn:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1

    store = factory(":memory:")
    store.close()
    assert store._closed

    spy = _SpyConn()
    store._conn = spy
    store.close()

    assert spy.close_calls == 0, "close() re-ran its body on an already-closed store"
    assert store._closed


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_close_acquires_the_lock_with_a_finite_timeout(module: ModuleType, factory: type) -> None:
    """The lock acquire in ``close()`` must be *bounded*.

    ``close()`` runs from ``__del__`` and from the ``atexit`` hook; an unbounded
    ``acquire()`` there is an interpreter that never exits (measured pre-fix:
    the child had to be SIGKILLed, exit 137). Kills the mutant that rewrites
    ``acquire(timeout=_CLOSE_LOCK_TIMEOUT_S)`` as ``acquire()`` — the double
    records ``None`` for that — and any mutant that makes the bound infinite or
    non-positive.
    """
    store = factory(":memory:")
    lock = _RecordingLock(grant=True)
    store._lock = lock

    store.close()

    assert lock.acquire_timeouts, "close() never tried to take the store lock"
    timeout = lock.acquire_timeouts[0]
    assert timeout is not None, "close() acquired the lock with no timeout — shutdown can hang"
    assert timeout > 0
    assert math.isfinite(timeout)
    assert timeout == module._CLOSE_LOCK_TIMEOUT_S


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_close_gives_up_on_the_lock_and_still_closes(module: ModuleType, factory: type) -> None:
    """When the lock cannot be taken, ``close()`` closes the handle anyway.

    The deterministic twin of ``test_close_does_not_block_on_an_unreleasable_lock``
    (which spends up to 20s of wall clock on a real thread): the double refuses
    the acquire, so the give-up branch is taken by construction. Also kills the
    mutant that releases a lock it never acquired — ``if acquired:`` in the
    ``finally`` — which on a real ``RLock`` is a ``RuntimeError`` raised from a
    finaliser.
    """
    store = factory(":memory:")
    lock = _RecordingLock(grant=False)
    store._lock = lock

    store.close()

    assert store._closed, "close() gave up on the lock but left the store marked open"
    assert _is_dead(store), "close() gave up on the lock and leaked the sqlite handle"
    assert lock.release_calls == 0, "close() released a lock it never acquired"
    assert store not in module._open_stores


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_del_closes_the_store(module: ModuleType, factory: type) -> None:
    """``__del__`` delegates to ``close()``.

    Invoked by hand: the behaviour under test is "the finaliser closes", not
    "the collector runs", so this holds however many frames are retained.
    """
    del module
    store = factory(":memory:")

    store.__del__()

    assert store._closed
    assert _is_dead(store)


@pytest.mark.parametrize(("module", "factory"), _STORES)
def test_exit_hook_closes_every_registered_store(module: ModuleType, factory: type) -> None:
    """``_close_open_stores()`` closes *all* registered stores, not just one.

    Run against an isolated registry — pointing it at the real one would close
    the live singleton and hand every later test a dead connection. Kills
    mutants that break out of the loop early or iterate the registry live
    (``close()`` mutates ``_open_stores`` while it is being walked, hence the
    ``list(...)`` copy in the source).
    """
    first = factory(":memory:")
    second = factory(":memory:")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(module, "_open_stores", type(module._open_stores)([first, second]))

        module._close_open_stores()

    assert first._closed
    assert second._closed
    assert _is_dead(first)
    assert _is_dead(second)
