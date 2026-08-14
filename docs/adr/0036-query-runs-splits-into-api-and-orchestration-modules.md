# ADR-0036: `query_runs.py` splits into a thin `query_api` layer and a new `query_run_orchestration` module

## Status

Accepted — 2026-08-14 (#303)

## Context

`docs/20-architecture.md` declares seven separate components, including
`query_api`, `orchestration`, and `persistence`, each with an explicit "must
not own" boundary. Before this change, `src/product_app/query_runs.py`
(3,509 lines) merged at least three of them into one file:

- the six FastAPI `@router` endpoints (the `query_api` component);
- `InMemoryQueryRunRepository` and the run state machine (`persistence`);
- `_execute_query_run` and the rest of the pipeline —
  `_degrade_run_for_deadline`, judge memoisation, evaluation memoisation,
  billing reconciliation, progress tracking (`orchestration`).

It also fanned in imports from ten-plus other domain modules (`auth`,
`config`, `costs`, `debate`, `evaluation`, `feedback_store`, `model_slots`,
`provider_keys`, `providers`, `run_history_store`, `safety`, `synthesis`,
`visible_text`), so almost any change to a neighbouring domain module risked
a matching edit inside this one file — the real boundary was undocumented
and enforced by nothing. A reviewer trusting the architecture doc's
component table would look for a separate `orchestration.py` and not find
one. Filed as issue #303 (`docs/analysis/2026-08-11-repo-structure-audit.md`
§6, F11); explicitly deferred out of that housekeeping run's scope because
mixing a `src/` restructure into file-move/dedup cleanup would have produced
an unreviewable diff (rule 17, one concern per PR).

Fifty-five files (51 in `src/`+`tests/`, at the count taken before this PR)
import from `product_app.query_runs`, many via `from product_app.query_runs
import <private_name>` or `monkeypatch.setattr(query_runs, "<name>", ...)` —
process-global state (the run-capacity semaphore, the judge/evaluation memo
dicts, rate-limiter instances) and internal helper functions are poked at
directly by tests, not only through the public HTTP surface.

## Decision

Split into two modules along the `query_api` / `orchestration`+`persistence`
boundary, not three:

- **`query_run_orchestration.py`** (new, ~2,650 lines) owns the run state
  machine (`QueryRunStatus`, `StageState`, `ALLOWED_TRANSITIONS`),
  `InMemoryQueryRunRepository` and the `query_run_repository` singleton, and
  the whole pipeline (`_execute_query_run` and everything it calls: judge
  memoisation, evaluation memoisation, billing reconciliation, progress
  tracking). It has no FastAPI import and no route.
- **`query_runs.py`** (thin, ~930 lines) keeps the `APIRouter`, the six
  route handlers, the request/response Pydantic schemas, and the two
  in-process rate limiters (`_InMemoryIpRateLimiter`,
  `_InMemoryAccountRateLimiter`) — these are HTTP-shaped (`main.py` imports
  `_ip_rate_limiter` directly for its request middleware) and stay with the
  API layer rather than moving to orchestration.

`persistence` (the repository) was folded into the orchestration module
rather than given a third file. The repository's mutators are called from
inside the pipeline on almost every line (`update_status`, `transition`,
`mark_billable_stage_entered`, …), and the pipeline functions are called
from nowhere else — splitting them into a third module today would have
added an import hop with no caller on the other side of it, for a boundary
nothing currently needs enforced independently of the state machine it
mutates. Revisit if the repository grows a second real consumer (e.g. a
durable-store swap) that would benefit from importing persistence without
pulling in the whole pipeline.

**`query_runs.py` is a re-export shim, not a broken import path.** Every
name findable by `from product_app.query_runs import <name>` or
`query_runs.<name>` before this change resolves identically after it — the
`import NAME as NAME` idiom is used for the ~45 names that moved but are
referenced nowhere in `query_runs.py`'s own code (so ruff's F401 does not
flag them as unused; this is the standard PEP 484 explicit re-export form).
**Zero of the 55 importers needed an import-path change.**

## Rejected alternative: monkeypatch-driven module choice per test file

Eight test files monkeypatch a function or constant that lives inside the
moved pipeline (`_execute_query_run`, `_should_stop`, `_reconcile_run_billing`,
`_record_feedback_event`, `evaluate_run`, `_JUDGE_VERDICT_MEMO_MAX`,
`_JUDGE_INFLIGHT_WAIT_SECONDS`, `_EVALUATION_MEMO_MAX`, `_persist_run_evaluation`,
`_update_run_evaluation`). A re-export shim preserves *reading* `qr.<name>`,
but not *patching* it for effect: `monkeypatch.setattr(query_runs,
"_execute_query_run", boom)` only rebinds the name inside `query_runs`'s own
namespace. The function that actually calls `_execute_query_run` by its bare
name (`_execute_query_run_safely`) is now defined in
`query_run_orchestration.py` and resolves that name against *its own*
module globals — untouched by a patch made on the old module. Silently
shipping the split without fixing this would have left those 8 files
mutation-blind: the assertion would still run, but against the real
function instead of the test double, and would very likely still pass by
coincidence rather than by proof — the worst kind of false green.

Considered leaving those 8 files importing `query_runs` and just widening
the shim to proxy `setattr` through to the new module. Rejected: it would
require either metaclass/`__setattr__` trickery on a plain module (not
supported) or a `ModuleType` subclass registered in `sys.modules`, adding
real complexity to hide a one-line fix. Instead, each of the 8 files gained
one import (`from product_app import query_run_orchestration as qro`) and
had its `monkeypatch.setattr(qr, ...)` / `monkeypatch.setattr(query_runs,
...)` calls for the moved names retargeted to `qro`. Calls that only *read*
through the old name (`qr._persist_terminal_run(...)`,
`qr._actual_cost(run)`) were left alone — those work identically via the
re-export shim because they call the function object directly rather than
relying on a patched bare-name lookup inside another function.

## Consequences

- A reader looking for the `orchestration` component `docs/20-architecture.md`
  describes now finds it as a real, separate file.
- The pipeline can be read, tested, and (in a future PR) further decomposed
  without wading through six unrelated FastAPI route bodies first.
- `query_runs.py`'s import block is dominated by re-export lines. This is
  the deliberate cost of "zero importers change": the alternative (updating
  55 files' import paths in the same PR) would have produced exactly the
  unreviewable, multi-concern diff issue #303 was filed to avoid creating.
  A follow-up PR may migrate call sites to `query_run_orchestration`
  directly and shrink the shim once the split has bedded in.
- Process-global test-isolation helpers that reach into module internals
  (`tests/helpers.isolated_run_semaphore` and the 8 files listed above) are
  now split across two "which module actually owns this name" mental models.
  `_run_semaphore` itself did **not** need a test-file change: it is read by
  bare name only from `create_query_run`, which stayed in `query_runs.py`,
  so `tests/helpers.py`'s existing `query_runs._run_semaphore = private`
  patch still lands on the code path that reads it.

## Verification

- `uv run ruff check` clean on both modules and all 8 edited test files.
- Full test suite run before and after the split from a clean `origin/main`
  checkout; the pass/fail set is identical (see PR description for the
  counts) — this was a pure code move, not a refactor.
