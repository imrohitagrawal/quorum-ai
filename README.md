# Quorum-AI

> One question. Four models. One answer you can verify.

Quorum-AI runs your question against four LLMs in parallel, has a separate moderator model critique their answers, and returns a single answer — written by a separate synthesis model — with explicit consensus, disagreement, source support, uncertainty, and recommendation. Every finished run also gets a **trust score** (a deterministic evaluation of the run itself, not the claims in it), and sensitive or high-stakes questions get an explicit safety warning the user must acknowledge before the run starts. Cost is estimated before execution; higher-cost runs require confirmation. Results are ephemeral.

**Workspace:** [quorum.stackclimb.com](https://quorum.stackclimb.com) —
[`/ready`](https://quorum.stackclimb.com/ready) reports whether execution is live
or degraded right now; [`/status`](https://quorum.stackclimb.com/status) reports
the deployed build. Live-model calls are gated behind
`OPENROUTER_LIVE_EXECUTION_ENABLED`, so the deployed instance can legitimately run
in `offline_by_config` (local-simulation) mode at any given moment — check `/ready`
rather than assuming "deployed" means "calling real models." Cost controls gate
every live run, with explicit approval required for higher-cost requests.

**Contribute:** read the account-level
[CONTRIBUTING.md](https://github.com/imrohitagrawal/.github/blob/main/CONTRIBUTING.md),
then use [Discussions](https://github.com/imrohitagrawal/quorum-ai/discussions)
for questions and architectural ideas or
[Issues](https://github.com/imrohitagrawal/quorum-ai/issues) for reproducible
defects and accepted work.

The product brief is in [docs/PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md). Architecture,
requirements, operations, security, and evaluation evidence are indexed under
[docs/](docs/).

---

## What it does

A user types a research question. The app:

1. **Warns** — if the query looks like it contains sensitive data or asks for high-stakes (medical/legal/financial/safety) advice, the user must acknowledge a warning before the run starts (`src/product_app/safety.py`).
2. **Estimates** the cost across the four model slots (one vendor per slot, picked from a static default set in `src/product_app/model_slots.py`).
3. **Runs** the four models in parallel against the real provider (`src/product_app/providers.py`). Search-only and local-simulation are **whole-run** fallback modes (live execution disabled, or no key) — if live execution is enabled but one individual model call fails, that slot is reported as a failed slot, never silently swapped for a fabricated or simulated answer (issue #171 fixed exactly this substitution bug).
4. **Debates** — a separate moderator model (`settings.debate_model_id`) reads all four answers and writes a critique. Two rounds. The four answer models do not read each other; peer critique between them is planned, not built (#290). (`src/product_app/debate.py`)
5. **Synthesizes** a final 5-field response: consensus, disagreement, source support, uncertainty, recommendation. (`src/product_app/synthesis.py`, with consensus-strength classification in `synthesis_consensus.py` and length discipline in `synthesis_length.py`)
6. **Scores trust** — a deterministic, hermetic evaluation of the finished run (not the truth of its claims): were sources actually checked, did the models agree, was disagreement suppressed. The numeric score is computed either way, but it is only ever *shown* when a real LLM-as-judge (off by default) confirms citation support; otherwise every run is served `band="unverified"`, `score=null` (`src/product_app/evaluation.py`).
7. **Surfaces drift** — if the live model catalog has dropped any of the four static defaults, the workspace shows a banner and the `/v1/models/defaults` endpoint exposes `stale_model_ids` so an operator can see what's drifted without re-reading the catalog.

The whole thing is ephemeral by default. No query is persisted for the user, and refreshing the page loses the result — this is a deliberate product posture for a research/synthesis tool, not a chat log. A separate, append-only feedback/audit trail (`src/product_app/feedback_store.py`, `feedback_audit.py`) records billing- and reliability-relevant events server-side for operators; it is not a user-facing history.

---

## Run it

The app requires Python >=3.12 (`pyproject.toml`; CI runs 3.12) and `uv`. The four model slots default to:

- `openai/gpt-4o-mini`
- `anthropic/claude-haiku-4.5`
- `google/gemini-2.5-flash`
- `nvidia/nemotron-3-nano-30b-a3b`

The actual live execution path is gated on `OPENROUTER_LIVE_EXECUTION_ENABLED=true` and a real `OPENROUTER_API_KEY` in `.env`. With both set, every slot hits the live API; without either, the app silently runs in local-simulation mode (templated outputs). The smoke-probe added in `b42f0aa` makes that degraded state visible at startup.

```bash
# 1. Install dependencies
uv sync

# 2. Copy and edit env
cp .env.example .env  # then set OPENROUTER_API_KEY and OPENROUTER_LIVE_EXECUTION_ENABLED=true

# 3. Run dev server
UV_CACHE_DIR=$PWD/.uv-cache PYTHONPATH=src \
  uv run uvicorn product_app.main:app --host 127.0.0.1 --port 18084

# 4. Open the workspace
open http://127.0.0.1:18084/ui
```

**`.env` is in `.gitignore`.** Never commit it; the API key belongs only on the host that makes outbound calls.

**Or with Docker:** `docker compose up` builds from the repo-root `Dockerfile` and runs on `127.0.0.1:8000`. It reads secrets from `.env` (pinned explicitly in `docker-compose.yml` — `.env.example` alone is not enough, it's a template with no real key). Copy and fill in `.env` first, same as above.

Production runs on Fly.io (`fly.toml`, `fly deploy`) as a **single, non-scaled instance** — the in-memory session/query-run state and the single-writer SQLite stores below are sized for that on purpose; see [`DEPLOY.md`](DEPLOY.md) for the full deploy runbook and secrets setup.

---

## Test status

```bash
make test
```

- **2,885 tests passing, 11 skipped, 95% line coverage** (measured 2026-08-12, `uv run pytest -q`). Coverage requirement is 88%; actual is 95.05%.
- On a local checkout you'll likely also see 7 failures under `tests/unit/test_no_orphaned_e2e_specs.py`. These are expected locally: `e2e/tests/review/` is gitignored scratch-review Playwright specs that exist on disk but run in no CI workflow, and the gate finds them by walking the filesystem. `git check-ignore e2e/tests/review` confirms they're untracked; they do not fail in CI.
- `make test` runs `uv run pytest` only — that covers `tests/unit`, `tests/integration`, `tests/contract`, `tests/resilience`, `tests/accessibility`, `tests/perf`, and `tests/e2e` (Python-based end-to-end pytest specs, 3 files). It does **not** run the Playwright suite.
- The Playwright suite lives in the separate top-level [`e2e/`](e2e/) directory (28 `.spec.ts` files, not `tests/e2e/`) and runs via its own CI workflow (`.github/workflows/e2e.yml`), not via `make test`. It's timing-sensitive — see the local-run flags in `AGENTS.md` (rule 13) before running it directly.
- Security redaction tests live in `tests/security/test_release_security_redaction.py` and are pinned in CI. They pass.

The `make test` target is also wired into GitHub Actions (see `.github/workflows/test.yml`).

---

## Production evidence

Live signals, SLOs, the ops dashboard, the scheduled availability alert, the
incident runbook, and a 60–90 s demo click-path — each claim tied to a real
PR/SHA/run-id — are collected in **[`docs/124-demo-evidence.md`](docs/124-demo-evidence.md)**.
Observability details live in [`docs/80-observability.md`](docs/80-observability.md).
The deploy runbook and Fly.io secrets setup are in [`DEPLOY.md`](DEPLOY.md).
Recent changes are tracked in [`CHANGELOG.md`](CHANGELOG.md).

---

## Architecture (one-screen view)

The full architecture document is at [docs/20-architecture.md](docs/20-architecture.md) with C4 diagrams in [diagrams/](diagrams/). The high-level shape:

```
┌────────────────────────────────────────────────────────────────┐
│  Browser (workspace.html + app.js + app.css)                   │
│  Renders 4 model panels, debate rounds, synthesis sections     │
└──────────────────────────┬─────────────────────────────────────┘
                           │  POST /v1/query-runs/estimate, /v1/query-runs
                           │  GET /v1/query-runs/{id} (poll)
                           ▼
┌────────────────────────────────────────────────────────────────┐
│  FastAPI app (src/product_app/main.py)                          │
│  - CSRF + cookie session middleware (src/product_app/auth.py)   │
│  - Cost guardrail ($0.25 hard cap at costs.py:49)               │
│  - Live-readiness smoke-probe (src/product_app/readiness.py)    │
└─────┬──────────────────┬──────────────────┬────────────────────┘
      │                  │                  │
      ▼                  ▼                  ▼
   query_runs.py     providers.py       synthesis.py
   (state machine)   (4 vendor cascade)  (final 5-field answer)
      │                  │                  │
      ▼                  ▼                  ▼
   debate.py        catalog_fetcher.py  evaluation.py
   (2 rounds)        (live catalog)     (trust score)
```

The ASCII sketch above shows module structure; the Mermaid diagram below shows the
actual request pipeline (linear: cost estimate → 4 parallel models → debate → synthesis
→ evaluation) — the two are complementary, not identical (see
[diagrams/00-hero-diagram.md](diagrams/00-hero-diagram.md) for the source, and
[diagrams/02-c4-container.md](diagrams/02-c4-container.md) for the full 7-container
view):

```mermaid
flowchart LR
    User[User via browser] -->|"POST /v1/query-runs"| API[FastAPI app<br/>main.py]
    API --> Cost[Cost estimate<br/>costs.py]
    Cost -->|confirmed| Run[QueryRun orchestration<br/>query_runs.py]
    Run --> Providers["4 model slots, parallel<br/>providers.py"]
    Providers --> Debate["2 debate rounds<br/>debate.py"]
    Debate --> Synth["5-section synthesis<br/>synthesis.py"]
    Synth --> Eval["Trust-score evaluation<br/>evaluation.py"]
    Eval --> Result[Result shown to user]
```

Key design points, with file:line citations:

- **Cost guardrail, three tiers**: a per-run soft threshold of $0.15 requires explicit confirmation, a per-run hard cap of $0.25 blocks the run outright ([costs.py:48-49](src/product_app/costs.py#L48), `SOFT_THRESHOLD_USD` / `HARD_LIMIT_USD`), and a separate **per-account daily cap of $0.20** ([costs.py:116](src/product_app/costs.py#L116), `DAILY_CAP_USD`) bounds cumulative spend across a day's runs. If the durable spend ledger becomes untrustworthy after a fault, the system degrades to $0 local-simulation rather than serving real spend against an unreliable meter (ADR-0016).
- **Live-readiness probe**: [readiness.py](src/product_app/readiness.py) — runs at app start, re-runs on every `/ready` hit, distinguishes `live`, `live` (with drift), `offline_by_config`, `offline_by_no_key`, and `offline_by_bad_key` (the key is set but the provider refused it — checked with a zero-token key probe, so a revoked key can no longer be served as "live").
- **Static defaults are the source of truth** for the four model slots. The live catalog is consulted as a **drift check**, not the source — see [model_slots.py:63](src/product_app/model_slots.py#L63) (`DEFAULT_MODEL_IDS`) and `tests/unit/test_model_slots.py`.
- **Safety warnings before a run starts**: sensitive-data and high-stakes queries require an acknowledged warning before `POST /v1/query-runs` (run creation) succeeds — an unacknowledged required warning gets HTTP 422. `POST /v1/query-runs/estimate` does **not** enforce this; a cost estimate can be previewed without acknowledging anything. See [safety.py](src/product_app/safety.py) and `POST /v1/query-runs/warnings`.
- **Trust score is suppressed unless a real judge verified it**: the composite number is always computed the same deterministic way (`evaluate_layer_a` in [evaluation.py](src/product_app/evaluation.py)) regardless of the judge, so the judge never changes the arithmetic — but `build_trust_score` only ever *serves* that number when `support_verified` is True, which requires a real LLM-as-judge verdict. With the judge off (the default), every run shows `band="unverified"`, `score=null`, not a computed-but-lower number. Every weight and threshold in the composite is explicitly marked uncalibrated.
- **Redaction is a logging discipline, not a global filter**: call sites log structured fields (status code, model id, error class name) and deliberately never pass raw exception text or response headers to the logger — because a header value can carry key material verbatim. There is no scrubbing formatter that strips secrets after the fact, so a call site that *did* log a raw secret would leak it; the guarantee is "never construct that log call," verified by code review, not by a runtime filter. `tests/security/test_release_security_redaction.py` is a related but narrower contract: it asserts secrets never leak into HTTP **responses** or in-memory **event recorders**, not into logger output.
- **CSRF + cookie session** instead of bearer tokens. The CSRF token is bound to the session via a signed cookie; cross-site requests can't read it. See [auth.py](src/product_app/auth.py).
- **Durable feedback trail, best-effort not blocking**: in-memory ring buffers ([providers.py](src/product_app/providers.py), [synthesis.py](src/product_app/synthesis.py)) also write synchronously into a SQLite-backed sink ([feedback_store.py](src/product_app/feedback_store.py)) on the request thread; a failed write is caught and logged, never raised to the caller, so a durable-storage fault can't fail a user's run. `feedback_audit.py` reads that sink and exposes a summary at `GET /feedback/audit` — despite its own docstring calling it a "nightly" runner, nothing in `.github/workflows/` schedules it; today it only runs via the manual `make feedback-audit` target. Both durable SQLite stores are deliberately single-writer (one connection, one lock, no WAL) — a documented decision, not an oversight, that caps this design to a single-instance deployment (ADR-0002).

---

## What's interesting about this codebase

A few non-obvious properties that are worth a closer look:

- **Cheapest-per-vendor selection is a pure function; `:free`-filtering is the caller's job, not its own.** [`cheapest_per_vendor`](src/product_app/catalog_fetcher.py#L464) in `catalog_fetcher.py` takes "eligible" candidates as-given and picks the lowest listed price — it will happily return a `:free` variant if you hand it one (confirmed by calling it directly with a paid and a `:free` entry of the same vendor: it returned the free one). The actual `:free`/`:preview` exclusion lives one layer up, in `model_slots.py`'s `_is_unauthenticated_variant` — those suffixes rank first on price ($0) but routinely fail to authenticate against a real key, collapsing every default slot into `local_simulation`, so the caller filters them out before ever calling `cheapest_per_vendor`.
- **Live-readiness smoke-probe as a multi-state machine.** Most apps do a single boolean "is the key set?" check. This one logs at WARNING whenever a degraded state is detected and exposes a JSON envelope on `/ready` so an external monitor can observe the same state.
- **Drift detection over a static source-of-truth.** The architecture is deliberate: the four model ids in `DEFAULT_MODEL_IDS` are the *what we ship*; the live catalog is the *what's available now*. The drift check surfaces the gap, it doesn't auto-correct.
- **Trust score is deliberately two-tier, and the calibrated tier does not exist yet.** Layer A (deterministic, always on) is the only input to the numeric score. Layer B (LLM-as-judge) is advisory metadata that can suppress the score but never raise it, and every weight in the module is documented as chosen to match five hand-written test cases, not measured against real data.
- **Redaction is discipline, not a filter** — see the "Redaction" point above for what that means in practice.
- **A "nightly" audit job that nothing schedules** — see the "Durable feedback trail" point above.

---

## Project layout

```
.
├── src/product_app/              # Application package (~22.5k lines)
│   ├── main.py                   # FastAPI app + route definitions
│   ├── auth.py                   # Cookie session + CSRF
│   ├── providers.py              # 4-vendor live-call cascade with fallback
│   ├── debate.py                 # 2-round critique orchestrator
│   ├── synthesis.py              # Final synthesis orchestrator
│   ├── synthesis_consensus.py    # Consensus-strength classification
│   ├── synthesis_length.py       # Length discipline for synthesis output
│   ├── evaluation.py             # Trust-score engine (deterministic + optional LLM judge)
│   ├── safety.py                 # Sensitive/high-stakes query warnings
│   ├── catalog_fetcher.py        # Live model catalog + cheapest-per-vendor
│   ├── model_slots.py            # DEFAULT_MODEL_IDS (source of truth)
│   ├── costs.py                  # Cost estimation + $0.25 hard cap
│   ├── readiness.py              # Startup smoke-probe + /ready surface
│   ├── query_runs.py             # Async query-run state machine + HTTP routes
│   ├── feedback_store.py         # Durable SQLite sink for feedback events
│   ├── feedback_audit.py         # Feedback audit job (manual `make feedback-audit`, not scheduled) + /feedback/audit
│   ├── run_history_store.py      # Durable terminal-run history
│   ├── store_reconnect.py        # Background reconnect for the SQLite sinks
│   ├── telemetry_sink.py         # Bounded JSONL sinks for blocked-issue telemetry
│   ├── config.py                 # Application configuration / settings
│   ├── logging_config.py         # Structured JSON logging
│   ├── request_id.py             # Per-request ID correlation
│   ├── untrusted_text.py         # Fencing for untrusted prose sent to an LLM
│   ├── visible_text.py           # "does this provider text have visible content" predicate
│   ├── provider_keys.py          # Provider API key lookup
│   ├── static/                   # app.js, app.css
│   └── templates/workspace.html  # The single page
├── tests/
│   ├── unit/                     # Module-level tests
│   ├── integration/              # Multi-module flows + FastAPI client
│   ├── e2e/                      # Python pytest end-to-end specs (NOT Playwright — see top-level e2e/)
│   ├── security/                 # Redaction contract tests
│   ├── contract/                 # API contract tests
│   ├── evals/                    # Trust-score calibration corpus
│   ├── resilience/               # Failure-injection / chaos-style tests
│   ├── accessibility/            # a11y checks
│   └── perf/                     # Load / throughput tests
├── e2e/                           # Playwright suite (28 .spec.ts), invariant specs, own CI workflow
├── docs/                         # Product, architecture, ops docs (141 top-level entries, incl. docs/adr/ with 35 more)
├── diagrams/                     # C4, Mermaid, and Excalidraw diagrams
├── configs/, policies/, schemas/, scripts/  # Factory-generated governance config + dev tooling (Makefile targets call into scripts/)
├── openapi.yaml                  # Generated OpenAPI 3.1 spec
```

---

## License

MIT + Attribution — see [`LICENSE`](LICENSE). Redistribution and modification are
permitted; a visible attribution notice naming the author must be carried through
to any distribution. `docs/learning/` (not yet written) is reserved separately
under CC BY-NC-ND 4.0 — see [`docs/learning/LICENSE`](docs/learning/LICENSE).
