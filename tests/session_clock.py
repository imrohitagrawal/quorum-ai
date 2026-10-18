"""A stepped clock for the session code, and a way to age one session (W87-1).

The session code reads the time through one module clock, ``auth._now()``, so a
test can stand at an exact instant and step past it by a microsecond. Every
caller must look the clock up on the module at call time (``auth._now()``, or
``_now()`` inside ``auth.py``); a copy taken with ``from product_app.auth
import _now`` would keep the real clock and these tests would not reach it.

``freeze`` raises ``AttributeError`` while ``auth`` has no ``_now``: that is
the expected failure before the maximum age is built.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from product_app import auth, session_store
from product_app.session_store import _digest


@dataclass
class Clock:
    at: datetime

    def __call__(self) -> datetime:
        return self.at

    def advance(self, by: timedelta) -> None:
        self.at += by


def freeze(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Stand the session code at "now" and hold it there.

    The instant is the real time when called, so rows written with it are never
    in the future for the parts of the store that still read the wall clock.
    """
    clock = Clock(datetime.now(UTC))
    monkeypatch.setattr(auth, "_now", clock)
    return clock


def age(session_id: str, by: timedelta, *, now: datetime) -> None:
    """The session started ``by`` before ``now`` and was last used at ``now``,
    in the process cache and in the durable row (when there is one)."""
    created = now - by
    with auth.session_repository._lock:
        cached = auth.session_repository._sessions.get(session_id)
        if cached is not None:
            cached.created_at = created
            cached.last_used_at = now
            cached.persisted_last_used_at = now
    store = session_store.get_store()
    if store is not None:
        with store._lock:
            store._conn.execute(
                "UPDATE sessions SET created_at = ?, last_used_at = ? WHERE session_digest = ?",
                (created.isoformat(), now.isoformat(), _digest(session_id)),
            )
