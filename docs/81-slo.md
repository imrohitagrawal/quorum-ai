# SLO

The SLO table lives in **`docs/80-observability.md` → "SLOs (declared
targets — measurement source stated per row)"** — single source of truth
(OD-1). Declared there: availability 99% non-5xx, 5xx rate < 1%,
end-to-end latency P50 ≤ 45 s / P95 ≤ 120 s (NFR-001), HTTP p95 < 1 s,
readiness honesty, flake-rate baseline. Each row names how to read the
live value; no current number is frozen into prose.
