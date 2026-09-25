"""The per-minute session limiter forgets idle visitors (W30, ADR-0132).

Before W30 every production request was keyed on the app's own ingress
address, one per address family, so the limiter's table held about two
entries. W30 counts each visitor (an IPv6 visitor by /64), and a stale
entry was dropped only when the SAME key came back: review measured a /48
sweep leaving 65,536 entries, about 11.5 MB, still held an hour later. The
limiter now sweeps stale entries at most once per
``SWEEP_INTERVAL_SECONDS``.
"""

from __future__ import annotations

from product_app.query_runs import _InMemoryIpRateLimiter

T0 = 1_000_000.0


def _fill(limiter: _InMemoryIpRateLimiter, n: int, now: float) -> None:
    for i in range(n):
        assert limiter.allow(ip=f"2001:db8:{i:x}::/64", now_epoch=now)


def test_idle_visitors_are_forgotten_on_the_next_sweep() -> None:
    """Turns red if the sweep is removed: the 1,000 idle keys stay."""
    limiter = _InMemoryIpRateLimiter()
    _fill(limiter, 1_000, T0)
    assert len(limiter._buckets) == 1_000
    later = T0 + _InMemoryIpRateLimiter.STALE_BUCKET_SECONDS + 1
    assert limiter.allow(ip="198.51.100.1", now_epoch=later)
    assert list(limiter._buckets) == ["198.51.100.1"]


def test_no_sweep_before_the_interval() -> None:
    """Turns red if the sweep runs on every request (a full scan each time)."""
    limiter = _InMemoryIpRateLimiter()
    _fill(limiter, 10, T0)
    limiter.allow(ip="198.51.100.1", now_epoch=T0 + 1)
    before = limiter._last_sweep
    limiter.allow(ip="198.51.100.2", now_epoch=T0 + 2)
    assert limiter._last_sweep == before
    assert len(limiter._buckets) == 12


def test_a_recent_visitor_keeps_their_count_through_a_sweep() -> None:
    """The positive partner. Turns red if the sweep drops a bucket that is not
    stale: a visitor who used up their allowance would get it back."""
    limiter = _InMemoryIpRateLimiter()
    _fill(limiter, 5, T0)
    busy = "198.51.100.9"
    late = T0 + _InMemoryIpRateLimiter.STALE_BUCKET_SECONDS + 1
    for _ in range(_InMemoryIpRateLimiter.CAPACITY):
        assert limiter.allow(ip=busy, now_epoch=late)
    assert not limiter.allow(ip=busy, now_epoch=late)
    # The sweep ran on the first `late` call; the idle five are gone and the
    # busy visitor is still refused.
    assert list(limiter._buckets) == [busy]
    assert not limiter.allow(ip=busy, now_epoch=late + 1)


def test_the_sweep_interval_is_pinned() -> None:
    """Bucket A. Turns red if the interval moves."""
    assert _InMemoryIpRateLimiter.SWEEP_INTERVAL_SECONDS == 60.0


def test_the_stale_boundary_is_exact() -> None:
    """Pinned with literals on both sides. Turns red if an entry idle exactly
    300 s is dropped, or one idle 301 s is kept."""
    limiter = _InMemoryIpRateLimiter()
    limiter.allow(ip="198.51.100.1", now_epoch=T0)
    limiter.allow(ip="198.51.100.2", now_epoch=T0 + 300)  # sweeps, cutoff T0
    assert "198.51.100.1" in limiter._buckets
    limiter.allow(ip="198.51.100.3", now_epoch=T0 + 361)  # sweeps, cutoff T0 + 61
    assert "198.51.100.1" not in limiter._buckets
    assert "198.51.100.2" in limiter._buckets


def test_a_sweep_restarts_the_interval() -> None:
    """Turns red if a sweep does not record its time, which would make every
    later request scan the whole table."""
    limiter = _InMemoryIpRateLimiter()
    limiter.allow(ip="198.51.100.1", now_epoch=T0)
    limiter.allow(ip="198.51.100.2", now_epoch=T0 + 60)
    assert limiter._last_sweep == T0 + 60
