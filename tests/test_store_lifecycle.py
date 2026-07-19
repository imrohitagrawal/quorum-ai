"""Lifecycle guards for the two SQLite singleton stores (ledger RB-3).

The suite used to emit, at teardown::

    ResourceWarning: unclosed database in <sqlite3.Connection object at 0x...>

four times — one per store instance built by ``product_app.main`` at import
(``FeedbackStore.from_env()`` / ``RunHistoryStore.from_env()``), doubled because
``tests/unit/test_sentry_init.py`` reloads ``main`` and the *displaced*
singletons were dropped without ``close()``.

Two independent leaks were behind that, and each has a test here:

1. A store dropped without ``close()`` (a replaced singleton, a helper that
   forgot teardown) leaked the handle until the GC finalised the raw
   ``sqlite3.Connection`` — which is exactly when the warning fires.
2. The *live* singleton was never closed at process exit at all.

The leak assertion is scoped to the object under test, never to "whatever the
interpreter finalised at that moment". A per-test
``filterwarnings("error::ResourceWarning")`` looks narrow but is not: the
``gc.collect()`` inside the test finalises *any* garbage that happens to be
pending — e.g. an ``anyio`` ``MemoryObjectReceiveStream`` left by the
``tests/contract`` schemathesis client — and turned that unrelated leak into a
red build (deterministic when this module ran after ``tests/contract``). So we
record warnings instead of erroring on them and assert only on the sqlite
handle: see :func:`assert_no_sqlite_leak`.

Deliberately NOT tested/implemented: closing the displaced store inside
``configure()``. Callers such as ``tests/security/test_operations_info_leak.py``
save the current store and ``configure(original)`` it back afterwards; closing
on displacement would hand them a dead connection. See
``docs/adr/0002-sqlite-single-writer-ceiling.md``.
"""

from __future__ import annotations

import atexit
import gc
import importlib.util
import sqlite3
import sys
import warnings
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import pytest

from product_app import feedback_store as fs_mod
from product_app import run_history_store as rh_mod
from product_app.feedback_store import FeedbackStore
from product_app.run_history_store import RunHistoryStore


def _new_store(module: ModuleType) -> Any:  # module-parametrised helper
    """Build a store of whichever flavour ``module`` owns."""
    return (
        module.RunHistoryStore(":memory:") if module is rh_mod else module.FeedbackStore(":memory:")
    )


#: What sqlite's connection finaliser says when a handle is dropped unclosed:
#: ``unclosed database in <sqlite3.Connection object at 0x...>``.
_SQLITE_LEAK_MARKER = "sqlite3.Connection"


@contextmanager
def assert_no_sqlite_leak() -> Iterator[None]:
    """Fail if an *unclosed sqlite handle* is finalised inside the block.

    Collects the garbage on the way out, then asserts on the sqlite handle only.

    Deliberately **not** ``filterwarnings("error::ResourceWarning")``: that
    escalates the whole category, and the ``gc.collect()`` finalises whatever
    the rest of the suite left pending, so an unrelated ``anyio`` stream leaked
    by ``tests/contract`` failed *this* module (see the module docstring).
    Recording and filtering keeps the guard pointed at the object under test.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
        gc.collect()
    leaks = [
        str(entry.message)
        for entry in caught
        if issubclass(entry.category, ResourceWarning) and _SQLITE_LEAK_MARKER in str(entry.message)
    ]
    assert not leaks, f"unclosed sqlite handle(s) finalised: {leaks}"


@pytest.fixture(autouse=True)
def _live_singleton_survives() -> Any:
    """No test in this module may damage the process-wide singletons.

    These tests poke the module globals (``configure``, ``_open_stores``, the
    exit hook) that every other test in the suite reads through
    ``get_store()``. ``tests/unit/**`` collects *after* this file, so a test
    that leaves ``_store`` as ``None`` or as a closed handle silently breaks
    ~470 later tests — loudly for the cost daily-cap read path
    (``FeedbackStore.daily_spend_for`` raises ``sqlite3.ProgrammingError``),
    and worse, *silently* for ``record_event``/``record_terminal_run``, which
    return early on a ``None`` store and would make persistence assertions pass
    vacuously.

    When ``product_app.main`` has not been imported there is no live singleton
    to protect, so install a sentinel: the guard then holds in isolation too,
    instead of passing vacuously against ``None``.
    """
    sentinels: dict[ModuleType, Any] = {}
    for module in (rh_mod, fs_mod):
        if module.get_store() is None:
            sentinels[module] = _new_store(module)
            module.configure(sentinels[module])
    before = {module: module.get_store() for module in (rh_mod, fs_mod)}
    try:
        yield
        for module, store in before.items():
            assert module.get_store() is store, (
                f"{module.__name__}.get_store() was left as {module.get_store()!r}; "
                "every test here must restore the singleton it displaced"
            )
            assert not store._closed, (
                f"{module.__name__}'s live singleton was left closed; later tests "
                "would hit sqlite3.ProgrammingError or persist nothing at all"
            )
    finally:
        for module, store in before.items():
            module.configure(store)
        for module, sentinel in sentinels.items():
            module.configure(None)
            sentinel.close()


@pytest.mark.parametrize("factory", [RunHistoryStore, FeedbackStore])
def test_dropped_store_releases_its_connection(factory: type) -> None:
    """Dropping the last reference must not leak an unclosed sqlite handle.

    Pre-fix this raised ``ResourceWarning: unclosed database`` from the
    connection's finaliser during ``gc.collect()``.
    """
    with assert_no_sqlite_leak():
        store = factory(":memory:")
        del store


class _ForeignLeaker:
    """Stand-in for the third-party garbage the suite leaves lying around.

    Modelled on the real offender: an ``anyio.MemoryObjectReceiveStream`` left
    unclosed by the ``tests/contract`` schemathesis client, which warns from its
    ``__del__``. Self-referential so it is finalised by ``gc.collect()`` rather
    than by refcount, exactly as the real one is.
    """

    def __init__(self) -> None:
        self._cycle = self

    def __del__(self) -> None:
        warnings.warn("Unclosed <MemoryObjectReceiveStream at 0x0>", ResourceWarning, stacklevel=2)


def test_leak_guard_ignores_foreign_resource_warnings() -> None:
    """A leak that is not ours must not turn this module red.

    The guard used to be ``filterwarnings("error::ResourceWarning")``, which
    made the collection inside the store tests fail on *any* pending
    third-party finaliser: running this file after ``tests/contract`` failed
    8/8. Scoping to the sqlite handle is what makes the gate order-independent.
    """
    with assert_no_sqlite_leak():
        _ForeignLeaker()


def _import_private_copy(module: ModuleType) -> ModuleType:
    """Re-execute ``module``'s source under a throwaway name.

    ``importlib.reload`` would rebind the real ``RunHistoryStore``/``FeedbackStore``
    classes and break ``isinstance`` for everything already holding the originals,
    so the import-time wiring is replayed into a private module object instead.
    """
    spec = importlib.util.spec_from_file_location(
        f"{module.__name__}__atexit_probe", module.__file__
    )
    assert spec is not None and spec.loader is not None
    copy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = copy  # dataclasses/typing resolve names via sys.modules
    try:
        spec.loader.exec_module(copy)
    finally:
        del sys.modules[spec.name]
    return copy


@pytest.mark.parametrize("module", [rh_mod, fs_mod])
def test_exit_hook_is_registered_at_import(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hook must actually be wired to ``atexit``, not merely exist.

    Without this, deleting ``atexit.register(_close_open_stores)`` leaves the
    whole suite green: the test below calls the hook by hand and would never
    notice that nothing calls it at process exit — which is precisely the leak
    RB-3 was opened for.
    """
    registered: list[Any] = []

    def _capture(fn: Any, *args: Any, **kwargs: Any) -> Any:
        registered.append(fn)
        return fn

    monkeypatch.setattr(atexit, "register", _capture)

    copy = _import_private_copy(module)

    assert copy._close_open_stores in registered


@pytest.mark.parametrize("module", [rh_mod, fs_mod])
def test_process_exit_hook_closes_the_live_singleton(module: ModuleType) -> None:
    """The ``atexit`` hook closes whatever store is still open at exit.

    This is the leak the suite actually surfaced: the singleton installed by
    ``product_app.main`` lives for the whole process and nothing ever closed it.
    Calling the registered hook directly keeps the assertion deterministic (an
    interpreter-shutdown warning is unraisable and cannot be asserted on).

    The hook closes *every* store in ``_open_stores`` — including the live
    singleton ``product_app.main`` installed for the whole process. So it is
    run against an isolated registry holding only this test's store; pointing
    it at the real registry would hand the ~470 tests that collect after this
    module a dead connection.
    """
    store = _new_store(module)
    previous = module.get_store()
    module.configure(store)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(module, "_open_stores", weakref.WeakSet([store]))
            module._close_open_stores()

        with pytest.raises(sqlite3.ProgrammingError):
            store._conn.execute("SELECT 1")
    finally:
        module.configure(previous)


@pytest.mark.parametrize("factory", [RunHistoryStore, FeedbackStore])
def test_close_is_idempotent(factory: type) -> None:
    """Double ``close()`` is a no-op, not a crash.

    ``configure_for_tests`` closes explicitly and the exit hook may close the
    same instance again; both paths have to be safe.
    """
    with assert_no_sqlite_leak():
        store = factory(":memory:")
        store.close()
        store.close()
        del store


@pytest.mark.parametrize("module", [rh_mod, fs_mod])
def test_configure_does_not_close_the_displaced_store(module: ModuleType) -> None:
    """Re-configuring must leave the previous store usable.

    Guards the save/restore idiom used by the security tests: they stash the
    live store, install their own, then put the original back. If ``configure``
    closed on displacement, the restored store would be dead.
    """
    original = _new_store(module)
    replacement = _new_store(module)
    previous = module.get_store()
    module.configure(original)
    module.configure(replacement)
    try:
        # The displaced store still answers queries.
        assert original._conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        module.configure(previous)
        original.close()
        replacement.close()


def test_configure_for_tests_leaves_no_open_handle() -> None:
    """The public test helper closes its store and drops out of the registry.

    ``configure_for_tests`` restores ``None`` rather than the store it
    displaced (``feedback_store``'s docstring claims otherwise), so the caller
    has to save and restore the singleton itself — see the note on
    ``_live_singleton_survives``. That is asserted explicitly below so the day
    the helper starts restoring the previous store, this stays honest.
    """
    with assert_no_sqlite_leak():
        for module in (rh_mod, fs_mod):
            previous = module.get_store()
            try:
                with module.configure_for_tests() as store:
                    assert module.get_store() is store
                assert store not in module._open_stores
                # Documented-but-unfixed: the helper drops the previous store.
                assert module.get_store() is None
            finally:
                module.configure(previous)


def test_importing_main_leaves_no_unclosed_singleton() -> None:
    """End-to-end shape of the original defect.

    ``product_app.main`` builds both singletons at import time. Reloading it (as
    ``tests/unit/test_sentry_init.py`` does) displaces them; the displaced pair
    used to be the loudest source of the warning. Here we rebuild that exact
    sequence without touching ``main``: install a store, displace it, drop the
    only reference, collect.
    """
    with assert_no_sqlite_leak():
        for module in (rh_mod, fs_mod):
            previous = module.get_store()
            first = _new_store(module)
            module.configure(first)
            del first
            second = _new_store(module)
            module.configure(second)
            module.configure(previous)
            second.close()
            del second
            gc.collect()
