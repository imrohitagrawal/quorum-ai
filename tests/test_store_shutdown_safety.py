"""Shutdown must never block on the store lock (ledger follow-up to RB-3).

RB-3 added ``__del__`` + an ``atexit`` hook so a dropped store closes its sqlite
handle. Both of those run in a *finaliser* context, and the ``close()`` they call
took ``self._lock`` unconditionally — so a store whose ``RLock`` had been
orphaned made the interpreter hang forever at exit instead of leaking a handle.

The orphaning is not hypothetical: ``FeedbackStore.iter_events`` used to hold the
lock across its ``yield``s. A consumer that abandons the generator mid-iteration
has the generator finalised later, possibly on a different thread, where
``RLock.release()`` raises ``cannot release un-acquired lock`` — leaving the lock
permanently held by a thread that no longer exists. Before RB-3 nothing ever
touched the lock again and the process exited cleanly (measured: exit 0); after
it, ``_close_open_stores()`` blocked and the process had to be SIGKILLed
(measured: exit 137). On Fly that is a deploy/restart that never drains.

Two guards, because the defect has two halves:

1. :func:`test_close_does_not_block_on_an_unreleasable_lock` pins the
   *invariant* — ``close()`` is bounded no matter who holds the lock. It holds
   the lock directly, so it stays meaningful even if no code path ever yields
   under the lock again.
2. :func:`test_interpreter_exits_when_an_iterator_orphans_the_lock` pins the
   *scenario* end-to-end in a real subprocess, since an interpreter-shutdown
   hang cannot be observed from inside the interpreter that is hanging.

Both are *environmental* oracles — one asserts on wall-clock thread-join timing,
the other on a child interpreter's exit status with a hand-built ``PYTHONPATH``
pointing at the repo-root source tree. Neither survives mutmut, which changes
call latency and copies the project into ``./mutants/`` (where that PYTHONPATH
addresses the *unmutated* tree, so the assertion would be meaningless even if it
passed). Hence the module-level ``env_oracle`` mark: the mutation gate deselects
it by marker (ledger DEBT-008). The bounded-acquire invariant itself is covered
for mutation by ``tests/test_store_lifecycle_behaviour.py``
(``test_close_acquires_the_lock_with_a_finite_timeout`` /
``test_close_gives_up_on_the_lock_and_still_closes``), which injects a lock
double instead of racing a real thread.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any

import pytest

from product_app import feedback_store as fs_mod
from product_app import run_history_store as rh_mod
from product_app.feedback_store import FeedbackStore
from product_app.run_history_store import RunHistoryStore

#: Generous multiple of the store's own bounded acquire, so a slow CI box cannot
#: flake this: the assertion is "bounded at all", not "fast".
_JOIN_TIMEOUT_S = 20.0

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every spec in this module is an environmental oracle — see the module
#: docstring. Deselected from the mutation gate by marker, never by path.
pytestmark = pytest.mark.env_oracle


@pytest.mark.parametrize(
    ("factory", "module"), [(RunHistoryStore, rh_mod), (FeedbackStore, fs_mod)]
)
def test_close_does_not_block_on_an_unreleasable_lock(factory: type, module: Any) -> None:
    """``close()`` must return even when the lock can never be acquired.

    Pre-fix this never returned: the closer thread sat in ``with self._lock``
    forever and the join timed out.

    The lock is held by *this* (living) thread rather than by a thread that has
    exited, which is what the real orphaning produces. Holding it from a dead
    thread is not a reliable model: CPython's ``RLock`` keys ownership on the
    thread *ident*, and idents are recycled — a freshly spawned closer can
    inherit the dead holder's ident and re-enter the lock, which made an earlier
    version of this test pass on a broken ``close()``. A live foreign holder is
    deterministic and stresses the same code path.

    The lock is released in ``finally`` so a future regression fails *this test*
    rather than hanging the whole pytest process in its own ``__del__``/
    ``atexit`` path.
    """
    store = factory(":memory:")
    store._lock.acquire()
    try:
        closer = threading.Thread(target=store.close, daemon=True)
        closer.start()
        closer.join(timeout=_JOIN_TIMEOUT_S)

        assert not closer.is_alive(), (
            f"{factory.__name__}.close() blocked on a lock it cannot take; at "
            "interpreter shutdown that is a hang, not a leak"
        )
        assert store._closed, "close() returned but left the store marked open"
        # The whole point of giving up on the lock: the handle is released
        # anyway, so shutdown neither hangs nor leaks.
        with pytest.raises(sqlite3.ProgrammingError):
            store._conn.execute("SELECT 1")
    finally:
        store._lock.release()
        module._open_stores.discard(store)


#: Runs in a child interpreter: record a few events, abandon ``iter_events``
#: mid-iteration on a thread that then dies, drop the generator, and exit. The
#: assertion is simply that the child *reaches* exit.
_ABANDONED_ITERATOR_SCRIPT = textwrap.dedent(
    """
    import gc, threading
    from datetime import UTC, datetime

    from product_app.feedback_store import FeedbackStore

    store = FeedbackStore(":memory:")
    for index in range(3):
        store.record(
            recorder="cost",
            event_type="probe",
            account_id=None,
            query_run_id=None,
            recorded_at=datetime.now(UTC),
            payload={"index": index},
        )

    abandoned = {}

    def consume():
        iterator = iter(store.iter_events())
        next(iterator)
        abandoned["iterator"] = iterator  # dropped below, never exhausted

    worker = threading.Thread(target=consume)
    worker.start()
    worker.join()

    del abandoned["iterator"]
    gc.collect()
    print("REACHED_EXIT", flush=True)
    """
)


def test_interpreter_exits_when_an_iterator_orphans_the_lock() -> None:
    """The whole process must still terminate — ``__del__``/``atexit`` included.

    Pre-fix the child printed ``REACHED_EXIT`` and then hung in the exit hook,
    so it died on the timeout below with ``-SIGKILL`` instead of returning 0.
    """
    completed = subprocess.run(
        [sys.executable, "-c", _ABANDONED_ITERATOR_SCRIPT],
        cwd=_REPO_ROOT,
        env={"PYTHONPATH": str(_REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=_JOIN_TIMEOUT_S,
        check=False,
    )

    assert "REACHED_EXIT" in completed.stdout
    assert completed.returncode == 0, (
        f"child exited {completed.returncode} (negative = signal); stderr:\n{completed.stderr}"
    )
