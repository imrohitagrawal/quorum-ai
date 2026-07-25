# Observability and SLOs — what to monitor, thresholds, and AI signals

You cannot operate what you cannot see. Define monitoring before you need it. Define each term on
first use — on-call may not be the original author.

## The three pillars of observability
- **Metrics** — numbers over time (request rate, error rate, latency, resource use). Cheap to store;
  good for alerts and trends.
- **Logs** — timestamped records of events. Good for "what exactly happened" during an incident.
- **Traces** — the path of one request across components. Good for "where did the time go" and for
  cause-finding in a distributed system.

## The four golden signals (watch these for every service)
- **Latency** — how long requests take. Track **p95 and p99** (the 95th/99th-percentile times), not
  just the average — the average hides the slow tail users feel.
- **Traffic** — how much demand (requests per second, jobs per minute).
- **Errors** — the rate of failed requests.
- **Saturation** — how full the system is (CPU, memory, queue depth) — how close to its limit.

## Service-level objectives (SLOs) and error budgets
- A **service-level indicator (SLI)** is a measured number (e.g. the fraction of successful requests).
- A **service-level objective (SLO)** is the target for it (e.g. 99.5% success over 30 days).
- The **error budget** is the allowed failure (100% − SLO). When it is being spent fast, slow down and
  fix reliability; when it is healthy, you can ship faster. Track the budget in one place and **link**
  it from the runbook rather than restating the number.
- **Burn-rate alerts** page when the budget is being consumed too quickly (a fast tier for sudden, sharp
  failure; a slow tier for a steady leak), instead of paging on every blip.

## Extra signals for AI components
When a component calls AI models, watch these too — ordinary service metrics miss them:
- **Token cost and usage** — tokens in/out per request and total spend; alert on a cost spike (a
  budget failure is a real incident).
- **Model latency and errors** per provider, and **fallback-fired** events (a weaker fallback may
  silently lower quality).
- **Output quality / drift** — a measurable quality signal on outputs, watched over time, so a slow
  decline is caught (a **CORR** concern, not OPS).
- **Guardrail hits** — how often a safety or validation guardrail blocks an output, and why.
- **Tool-call success rate** — when the model calls tools, how often those calls succeed.

## OpenTelemetry GenAI conventions (use the standard, do not invent your own)
- Instrument with **OpenTelemetry**; for AI calls follow the **GenAI semantic conventions** so spans
  are consistent across tools.
- **Store prompt and response content in span *events*, not span *attributes*.** Content can be large
  and sensitive; events are the right place and keep attributes clean. Redact secrets and personal data
  before recording.
- **Non-determinism needs reproducibility data.** The same input can give different output, so to
  reproduce an issue you must record the **exact input, the parameters, the model and version, and the
  temperature/seed**. Without those, a bug report is not reproducible.

## In the runbook
For each component, list the concrete signals, their thresholds, and the dashboard and alert links.
Make "what healthy looks like" explicit, so an operator can tell normal from not at a glance.
