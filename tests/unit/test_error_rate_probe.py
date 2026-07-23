"""Unit tests for ``scripts/error_rate_probe.py`` (alert rule 2, 5xx SLO).

The script lives outside ``--cov=src``'s view (repo rule: helper/gate logic
needs its own test), so every guard is pinned here:

* normal path — within/over the 1% SLO on a healthy request delta;
* guard 1 — below the minimum request delta the run SKIPS (exit 0);
* guard 2 — a negative delta (counter reset from a deploy) SKIPS;
* guard 3 — a malformed scrape ALERTS (exit 1), never silently skips.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from error_rate_probe import (  # type: ignore[import-not-found]  # noqa: E402 — path shim above
    MalformedScrapeError,
    Sample,
    evaluate,
    exit_code_for,
    parse_sample,
)

FAMILY = (
    "# HELP http_requests_total Total number of requests by method, status and handler.\n"
    "# TYPE http_requests_total counter\n"
)


def _exposition(*series: str) -> str:
    return FAMILY + "".join(f"{line}\n" for line in series)


# ---------------------------------------------------------------------------
# parse_sample
# ---------------------------------------------------------------------------


def test_parse_sums_all_series_and_splits_out_5xx() -> None:
    body = _exposition(
        'http_requests_total{handler="/ready",method="GET",status="2xx"} 700.0',
        'http_requests_total{handler="/",method="GET",status="4xx"} 90.0',
        'http_requests_total{handler="/v1/queries",method="POST",status="5xx"} 10.0',
    )
    sample = parse_sample(body)
    assert sample.total == 800.0
    assert sample.err5xx == 10.0


def test_parse_accepts_a_family_with_no_series_yet_as_zero() -> None:
    """A fresh process emits HELP/TYPE before the first observation —
    that is genuinely zero traffic, not a malformed scrape."""
    sample = parse_sample(FAMILY)
    assert sample == Sample(total=0.0, err5xx=0.0)


@pytest.mark.parametrize(
    "body",
    [
        "",  # empty body
        "<html><body>502 Bad Gateway</body></html>",  # proxy error page
        "# TYPE python_info gauge\npython_info 1.0\n",  # exposition without our family
    ],
)
def test_parse_raises_on_a_body_without_the_request_counter(body: str) -> None:
    """Guard 3: a scrape without ``http_requests_total`` must raise (the
    workflow turns that into an alert), never read as zero traffic."""
    with pytest.raises(MalformedScrapeError):
        parse_sample(body)


def test_parse_tolerates_a_trailing_prometheus_timestamp() -> None:
    """The exposition format allows "name{...} value timestamp". If the
    library ever started emitting timestamps, a stricter regex would match
    zero series while the family marker still passed the malformed guard —
    every run would silently skip as low-traffic forever (cycle-1 finding)."""
    body = _exposition(
        'http_requests_total{handler="/ready",method="GET",status="2xx"} 700.0 1700000000000',
        'http_requests_total{handler="/",method="GET",status="5xx"} 10.0 1700000000000',
    )
    sample = parse_sample(body)
    assert sample.total == 710.0
    assert sample.err5xx == 10.0


# ---------------------------------------------------------------------------
# evaluate — normal path
# ---------------------------------------------------------------------------


def test_within_slo_is_ok() -> None:
    decision = evaluate(
        Sample(total=1000, err5xx=5),
        Sample(total=2000, err5xx=10),
        min_delta=25,
        threshold=0.01,
    )
    # 5 of 1000 = 0.5% <= 1%
    assert decision.outcome == "ok"
    assert exit_code_for(decision.outcome) == 0


def test_over_slo_alerts() -> None:
    decision = evaluate(
        Sample(total=1000, err5xx=5),
        Sample(total=2000, err5xx=25),
        min_delta=25,
        threshold=0.01,
    )
    # 20 of 1000 = 2% > 1%
    assert decision.outcome == "alert"
    assert exit_code_for(decision.outcome) == 1


def test_exactly_at_the_threshold_alerts() -> None:
    """The SLO is "5xx rate < 1%" (docs/80): a share of exactly 1% is NOT
    under 1%, so the boundary value is a breach and must alert (>=, not >).
    Cycle-1 review finding: the first cut used > and let 1.00% pass."""
    decision = evaluate(
        Sample(total=0, err5xx=0),
        Sample(total=100, err5xx=1),
        min_delta=25,
        threshold=0.01,
    )
    assert decision.outcome == "alert"


def test_just_under_the_threshold_is_ok() -> None:
    """Other direction of the boundary: 0.5% of a judged window meets the SLO."""
    decision = evaluate(
        Sample(total=0, err5xx=0),
        Sample(total=200, err5xx=1),
        min_delta=25,
        threshold=0.01,
    )
    assert decision.outcome == "ok"


# ---------------------------------------------------------------------------
# evaluate — guard 1: minimum request delta
# ---------------------------------------------------------------------------


def test_below_min_delta_skips_even_with_a_5xx_present() -> None:
    """One stray 5xx among a handful of requests is noise (10% of 10), not
    a judged SLO breach — the honest outcome is a logged skip, exit 0."""
    decision = evaluate(
        Sample(total=100, err5xx=0),
        Sample(total=110, err5xx=1),
        min_delta=25,
        threshold=0.01,
    )
    assert decision.outcome == "skip_low_traffic"
    assert exit_code_for(decision.outcome) == 0


def test_at_the_min_delta_floor_the_window_is_judged() -> None:
    """Both directions of guard 1: the floor suppresses noise BUT a genuine
    breach at/above the floor still alerts."""
    decision = evaluate(
        Sample(total=100, err5xx=0),
        Sample(total=125, err5xx=2),
        min_delta=25,
        threshold=0.01,
    )
    # 2 of 25 = 8% > 1% and delta_total == floor → judged, alerts.
    assert decision.outcome == "alert"


# ---------------------------------------------------------------------------
# evaluate — guard 2: counter reset
# ---------------------------------------------------------------------------


def test_negative_total_delta_skips_as_counter_reset() -> None:
    decision = evaluate(
        Sample(total=5000, err5xx=10),
        Sample(total=40, err5xx=0),
        min_delta=25,
        threshold=0.01,
    )
    assert decision.outcome == "skip_counter_reset"
    assert exit_code_for(decision.outcome) == 0


def test_negative_5xx_delta_alone_also_skips_as_reset() -> None:
    """A partial-looking reset (total grew past the old value again but the
    5xx series went backwards) still means the samples straddle a restart."""
    decision = evaluate(
        Sample(total=100, err5xx=10),
        Sample(total=300, err5xx=2),
        min_delta=25,
        threshold=0.01,
    )
    assert decision.outcome == "skip_counter_reset"


def test_reset_guard_does_not_mask_a_real_spike_after_restart() -> None:
    """Both directions of guard 2: only a BACKWARDS counter skips. A
    post-restart window where counters grew normally is judged, and a real
    spike in it alerts."""
    decision = evaluate(
        Sample(total=0, err5xx=0),
        Sample(total=200, err5xx=50),
        min_delta=25,
        threshold=0.01,
    )
    assert decision.outcome == "alert"
