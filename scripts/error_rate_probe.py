"""Two-sample 5xx-rate probe over the public ``/metrics`` endpoint.

Mechanises alert rule 2 of ``docs/80-observability.md`` (5xx error rate
over the declared 1% SLO) with zero storage and zero paid infra: scrape
``/metrics`` twice, sleep a measured window in between, and judge the 5xx
share of the request-count DELTA over that window. Run by
``.github/workflows/error-rate-check.yml``; the workflow-failure email is
the alert channel (same design as ``availability-check.yml`` / rule 1).

Exit codes (the workflow's contract):

* ``0`` — SLO met over the window, or an HONEST SKIP (below the minimum
  request delta, or a counter reset from a deploy). Skips log why.
* ``1`` — alert: 5xx share of the delta exceeded the threshold, OR the
  scrape was malformed/unreachable. A scrape we cannot parse is a real
  failure (the metrics pipeline is broken), never a silent skip.

Guard rationale (all three are tested in
``tests/unit/test_error_rate_probe.py``):

1. **Minimum request delta** — with only a handful of requests in the
   window, a single stray 5xx dominates the ratio (1 of 10 = 10%) and a
   1% threshold cannot be judged meaningfully. Below the floor the run
   skips, honestly logged. At this app's background traffic (an
   availability probe every 15 min plus dashboard reads) quiet windows
   WILL regularly skip — the alert bites during real use, which is
   exactly when a 5xx spike matters.
2. **Negative delta** — a counter that went DOWN means the process
   restarted (deploy, crash-loop recovery) and the two samples are not
   comparable. Skip, do not false-alert. A crash-loop is rule 1's job
   (readiness), not this ratio's.
3. **Malformed scrape** — a body without the ``http_requests_total``
   counter family is a broken exposition surface, and this probe would
   otherwise be blind forever. That alerts (exit 1).

Stdlib only, so the workflow needs no dependency install.
"""

from __future__ import annotations

import argparse
import http.client
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

#: The documented SLO from docs/80-observability.md ("HTTP 5xx error
#: rate < 1% of requests"). Not invented here.
DEFAULT_THRESHOLD = 0.01

#: Judged-window floor. Below this many requests in the window the 5xx
#: share is dominated by single stray responses (see module docstring,
#: guard 1) — the run skips rather than judging noise.
DEFAULT_MIN_DELTA = 25

#: Seconds between the two scrapes. The ACTUAL elapsed time is measured
#: and logged by ``main`` — this is the request, not the claim.
DEFAULT_WINDOW_SECONDS = 120

# The Prometheus text format allows an OPTIONAL trailing millisecond
# timestamp after the value ("name{...} 42 1700000000000"). The current
# exposition library never emits one, but if that ever changed, a regex
# anchored right after the value would silently match nothing and every
# run would degrade to a perpetual low-traffic skip (cycle-1 review
# finding) — so the timestamp is tolerated explicitly.
_SAMPLE_RE = re.compile(
    r'^http_requests_total\{[^}]*status="(?P<klass>[^"]+)"[^}]*\}'
    r"\s+(?P<value>[0-9.eE+-]+)(?:\s+-?[0-9.eE+]+)?\s*$"
)
_FAMILY_MARKER = "# TYPE http_requests_total counter"


class MalformedScrapeError(Exception):
    """The body is not a /metrics exposition containing http_requests_total."""


@dataclass(frozen=True)
class Sample:
    """Request totals from one scrape, summed across handlers/methods."""

    total: float
    err5xx: float


@dataclass(frozen=True)
class Decision:
    outcome: str  # "ok" | "alert" | "skip_low_traffic" | "skip_counter_reset"
    detail: str
    delta_total: float
    delta_5xx: float
    share: float | None  # None when not judged


def parse_sample(body: str) -> Sample:
    """Sum ``http_requests_total`` across all series, split out 5xx.

    Raises :class:`MalformedScrapeError` when the counter family is absent
    — an empty or HTML error body must alert, not read as "zero traffic".
    A PRESENT family with no series yet (fresh process, prometheus_client
    emits HELP/TYPE before the first observation) is genuinely zero.
    """
    if _FAMILY_MARKER not in body:
        raise MalformedScrapeError(
            "scrape has no 'http_requests_total' counter family — not a "
            "Prometheus exposition of this app"
        )
    total = 0.0
    err5xx = 0.0
    for line in body.splitlines():
        match = _SAMPLE_RE.match(line)
        if not match:
            continue
        value = float(match.group("value"))
        total += value
        if match.group("klass") == "5xx":
            err5xx += value
    return Sample(total=total, err5xx=err5xx)


def evaluate(
    before: Sample,
    after: Sample,
    *,
    min_delta: float = DEFAULT_MIN_DELTA,
    threshold: float = DEFAULT_THRESHOLD,
) -> Decision:
    """Judge the 5xx share of the request delta between two samples."""
    delta_total = after.total - before.total
    delta_5xx = after.err5xx - before.err5xx

    if delta_total < 0 or delta_5xx < 0:
        return Decision(
            outcome="skip_counter_reset",
            detail=(
                f"counter went backwards (Δtotal={delta_total:g}, "
                f"Δ5xx={delta_5xx:g}) — process restarted between samples; "
                "the two scrapes are not comparable. Skipping, not alerting."
            ),
            delta_total=delta_total,
            delta_5xx=delta_5xx,
            share=None,
        )
    if delta_total < min_delta:
        return Decision(
            outcome="skip_low_traffic",
            detail=(
                f"only {delta_total:g} request(s) in the window (floor "
                f"{min_delta:g}) — a {threshold:.0%} SLO cannot be judged on "
                "that few; a single stray 5xx would dominate. Skipping."
            ),
            delta_total=delta_total,
            delta_5xx=delta_5xx,
            share=None,
        )

    share = delta_5xx / delta_total
    # The SLO is "5xx rate < 1%" (docs/80), so a share of EXACTLY the
    # threshold is already a breach — alert on >=, not >.
    if share >= threshold:
        return Decision(
            outcome="alert",
            detail=(
                f"5xx share {share:.2%} of {delta_total:g} requests exceeds "
                f"the {threshold:.0%} SLO ({delta_5xx:g} server errors in the window)"
            ),
            delta_total=delta_total,
            delta_5xx=delta_5xx,
            share=share,
        )
    return Decision(
        outcome="ok",
        detail=(
            f"5xx share {share:.2%} of {delta_total:g} requests is within the {threshold:.0%} SLO"
        ),
        delta_total=delta_total,
        delta_5xx=delta_5xx,
        share=share,
    )


def exit_code_for(outcome: str) -> int:
    """Alert is the only judged failure; both skips are honest exits 0."""
    return 1 if outcome == "alert" else 0


def _scrape(url: str, timeout: float = 15.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "quorum-error-rate-probe"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — https URL from our own CLI arg
        if response.status != 200:
            raise MalformedScrapeError(f"{url} returned HTTP {response.status}")
        return response.read().decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://quorum.stackclimb.com/metrics")
    parser.add_argument("--window-seconds", type=float, default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--min-delta", type=float, default=DEFAULT_MIN_DELTA)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    try:
        started = time.monotonic()
        first = parse_sample(_scrape(args.url))
        time.sleep(args.window_seconds)
        second = parse_sample(_scrape(args.url))
        elapsed = time.monotonic() - started
    except (
        MalformedScrapeError,
        urllib.error.URLError,
        OSError,
        # A truncated/garbled response raises http.client exceptions
        # (IncompleteRead, BadStatusLine) which are NOT OSError subclasses,
        # and a pathological value token can make float() raise ValueError
        # in parse_sample. Both must produce the clean ALERT line + exit 1,
        # not a raw traceback.
        http.client.HTTPException,
        ValueError,
    ) as exc:
        # A scrape we cannot fetch or parse is a REAL failure: the
        # observability surface itself is broken. Alert, never skip.
        print(f"ALERT: scrape failed — {exc}", file=sys.stderr)
        return 1

    decision = evaluate(first, second, min_delta=args.min_delta, threshold=args.threshold)
    print(
        f"window: {elapsed:.1f}s measured (requested {args.window_seconds:g}s) | "
        f"before total={first.total:g} 5xx={first.err5xx:g} | "
        f"after total={second.total:g} 5xx={second.err5xx:g}"
    )
    print(f"{decision.outcome.upper()}: {decision.detail}")
    return exit_code_for(decision.outcome)


if __name__ == "__main__":
    raise SystemExit(main())
