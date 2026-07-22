"""Stage B / D0 — the LOCAL-only ``/v1/session`` rate-limit override.

The per-IP limiter is pinned to 30/min in production. A LOCAL-only override
(``SESSION_RATE_LIMIT_PER_MINUTE``) raises it for the hermetic e2e lanes, which
otherwise measure the limiter (parity ≈ 53 boots/run × 10 repeats) instead of
the product. This is a security control: it is refused at startup outside LOCAL,
bounded so it can never lock the app out or grow ``session_repository``
unbounded, and it must actually change the constructed limiter's capacity.

Each test carries an explicit bite proof in its docstring.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from product_app import config
from product_app.config import RuntimeEnvironment, Settings, validate_production_environment
from product_app.query_runs import _InMemoryAccountRateLimiter, _InMemoryIpRateLimiter


def _settings(**overrides: object) -> Settings:
    # ``_env_file=None`` stops the working-tree ``.env`` from bleeding in, but it
    # does NOT isolate from ``os.environ`` — the caller must also delenv any var
    # it cares about (see ``test_production_default_is_thirty``).
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


# --- The production default is 30, from both sources -----------------------


def test_production_default_is_thirty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolved production capacity/refill is 30 and the override is unset.

    Neutralises BOTH sources: ``_env_file=None`` (the ``.env`` file) AND
    ``monkeypatch.delenv`` (``os.environ`` — Stage B itself exports the override
    into CI jobs, so without the delenv this reads the CI value and passes
    vacuously).

    Bite proof: change ``_InMemoryIpRateLimiter.CAPACITY = 30`` → 31 and the
    capacity assertion goes red.
    """
    monkeypatch.delenv("SESSION_RATE_LIMIT_PER_MINUTE", raising=False)
    settings = _settings()
    assert settings.session_rate_limit_per_minute is None
    assert _InMemoryIpRateLimiter.CAPACITY == 30
    assert _InMemoryIpRateLimiter.REFILL_PER_MINUTE == 30
    # A default-constructed limiter (no override) inherits the class default.
    default_limiter = _InMemoryIpRateLimiter()
    assert default_limiter.CAPACITY == 30
    assert default_limiter.REFILL_PER_MINUTE == 30


# --- Refused outside LOCAL --------------------------------------------------


@pytest.mark.parametrize(
    "environment",
    [RuntimeEnvironment.STAGING, RuntimeEnvironment.PRODUCTION],
)
def test_override_refused_outside_local(
    monkeypatch: pytest.MonkeyPatch, environment: RuntimeEnvironment
) -> None:
    """``validate_production_environment()`` raises when the override is set and
    runtime is STAGING or PRODUCTION (both, not one).

    Sets the earlier refusal preconditions to green (cookie_secure=True,
    legacy header off, token secret present) so the raise we observe is
    unambiguously the session-rate branch, not a neighbour.

    Bite proof: delete the ``session_rate_limit_per_minute`` refusal branch in
    ``validate_production_environment`` → no raise → red.
    """
    monkeypatch.setenv("QUORUM_TOKEN_SECRET", "x" * 32)
    hostile = _settings(
        runtime_environment=environment,
        session_cookie_secure=True,
        account_legacy_header_enabled=False,
        session_rate_limit_per_minute=600,
    )
    monkeypatch.setattr(config, "settings", hostile)
    with pytest.raises(RuntimeError, match="SESSION_RATE_LIMIT_PER_MINUTE"):
        validate_production_environment()


def test_override_unset_outside_local_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the override UNSET, a well-formed production config still starts —
    the refusal keys off the override being present, not merely non-LOCAL.

    Bite proof: change the branch guard to fire when the override is ``None``
    → this raises → red.
    """
    monkeypatch.setenv("QUORUM_TOKEN_SECRET", "x" * 32)
    good = _settings(
        runtime_environment=RuntimeEnvironment.PRODUCTION,
        session_cookie_secure=True,
        account_legacy_header_enabled=False,
        session_rate_limit_per_minute=None,
    )
    monkeypatch.setattr(config, "settings", good)
    validate_production_environment()  # must not raise


# --- Bounds -----------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, -30, Settings.SESSION_RATE_LIMIT_MAX + 1, 1_000_000])
def test_override_rejects_zero_and_out_of_range(bad: int) -> None:
    """0, negative, and above the upper bound are rejected. ``0`` must never
    mean "unlimited" — a zero bucket locks the endpoint out.

    Bite proof: remove the ``_session_rate_within_bounds`` validator → these
    are accepted → red.
    """
    with pytest.raises(ValidationError, match="SESSION_RATE_LIMIT_PER_MINUTE"):
        _settings(session_rate_limit_per_minute=bad)


@pytest.mark.parametrize("ok", [1, 30, 600, Settings.SESSION_RATE_LIMIT_MAX])
def test_override_accepts_in_range(ok: int) -> None:
    """The bounds are inclusive of 1 and the documented maximum."""
    assert _settings(session_rate_limit_per_minute=ok).session_rate_limit_per_minute == ok


def test_blank_override_is_unset() -> None:
    """A blank ``SESSION_RATE_LIMIT_PER_MINUTE`` is treated as unset, not a
    crash in the int parser (the ``EXPOSE_API_DOCS=`` footgun)."""
    assert _settings(session_rate_limit_per_minute="").session_rate_limit_per_minute is None


# --- The override actually moves the constructed limiter -------------------


def test_override_applies_in_local() -> None:
    """A limiter CONSTRUCTED FROM an overridden setting moves BOTH capacity and
    refill to N, not the class-constant 30.

    Built directly (not via the module singleton, which is created at import
    time — a monkeypatched setting cannot retroactively change it). Two
    independent assertions, one per seeded attribute:

    * CAPACITY: drain the bucket at a fixed epoch and assert the (N+1)-th
      request is refused — proves the burst ceiling is N.
    * REFILL_PER_MINUTE: advance the clock 6s and assert 5 consecutive requests
      succeed. At the overridden 100/min, 6s refills ~10 tokens; at the class
      default 30/min it would refill only ~3, so the 4th would be refused. This
      is what makes the test bite the refill wiring, not just capacity — a fixed
      epoch never exercises refill (verified: mis-seeding refill left this green
      until this assertion was added).

    Bite proof: (a) revert the capacity wiring → the 31st request is refused at
    t0 → red; (b) revert ONLY the refill wiring → the 4th request at t0+6s is
    refused → red.
    """
    n = 100
    limiter = _InMemoryIpRateLimiter(capacity=n, refill_per_minute=n)
    ip = "203.0.113.7"
    t0 = 1_000_000.0  # fixed epoch; no wall-clock refill within the burst
    # CAPACITY: N pass, N+1 refused.
    for i in range(n):
        assert limiter.allow(ip=ip, now_epoch=t0), f"request {i} should pass at capacity {n}"
    assert not limiter.allow(ip=ip, now_epoch=t0), "N+1 must be refused"
    # REFILL: 6s later, at 100/min ~10 tokens are back; 5 in a row must pass.
    # At the class-default 30/min only ~3 would refill, so this bites refill.
    t1 = t0 + 6.0
    for i in range(5):
        assert limiter.allow(ip=ip, now_epoch=t1), (
            f"refill request {i} at t0+6s should pass at refill {n}/min "
            "(only ~3 would refill at the un-overridden 30/min)"
        )


# --- The account limiter is out of scope and stays pinned ------------------


def test_account_limiter_is_pinned_at_thirty() -> None:
    """``_InMemoryAccountRateLimiter`` is explicitly out of scope: no setting
    moves it, and its capacity stays 30.

    Bite proof: add a ``capacity`` kwarg to the account limiter and wire it to
    a setting → this pin no longer proves isolation → the intent is violated.
    """
    assert _InMemoryAccountRateLimiter.CAPACITY == 30
    assert _InMemoryAccountRateLimiter.REFILL_PER_MINUTE == 30
    limiter = _InMemoryAccountRateLimiter()
    assert limiter.CAPACITY == 30
