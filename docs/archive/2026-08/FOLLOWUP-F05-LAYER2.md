# Follow-up to file: F-05 Layer 2 — cancel-awareness inside the stage services

**Status:** not built. This file is the issue text to file; it is deliberately
*not* a GitHub issue yet.

**Depends on:** F-05 Layer 1 (`fix/f05-cancel-not-reverted`) — the
`update_status` terminal-status guard in `src/product_app/query_runs.py`.

## What Layer 1 already closed

`InMemoryQueryRunRepository.update_status` now refuses an already-TERMINAL run
the WHOLE write — status, stage annotation, `failed_steps`, `missing_steps`,
`updated_at` — with `allow_terminal=True` as the narrow opt-in for the two
callers that annotate a run they themselves just made terminal
(`cancel_query_run` and `_degrade_run_for_deadline`, plus
`_mark_remaining_stages` behind the latter). Because `_should_stop` reads only
the status field, that restores the cancel signal: the pipeline stops at the next
`_should_stop` gate instead of running to `completed`, and the
`except BaseException` backstop no longer relabels a `cancelled` run as
`failed`.

## What is left — the residual billed calls

Layer 1 can only stop the run at the *next* gate. It cannot cut a stage service
that has **already been entered**, because neither `debate.run_debate_rounds`
nor `synthesis.produce_final_synthesis` ever looks at the run's status.

Measured at the `product_app.providers.urlopen` seam
(`tests/integration/test_f05_terminal_status_not_overwritten.py`, a 10-call
run: 4 initial answers + 2 debate rounds + 4 live synthesis sections):

| cancel window | before Layer 1 | after Layer 1 | Layer 2 target |
| --- | --- | --- | --- |
| just after the pre-debate gate | 6 | **2** (debate rounds 1 + 2) | 0 |
| mid debate round 1 | 5 | **1** (debate round 2) | 0 |
| just after the pre-synthesis gate | 4 | **4** (synthesis sections) | 0 |

So the residual is **2 debate calls** when the cancel lands at the debate
boundary, and **4 synthesis-section calls** when it lands at the synthesis
boundary. Every one of them is billed to the account *after* the user's DELETE
returned `200 {"status": "cancelled"}`.

The `pre_synthesis` row is the reason the Layer 1 test asserts the preserved
`cancelled` label there rather than a reduced count: Layer 1 changes the label
(`completed` → `cancelled`) but not the call count.

### The residual `elapsed_time_ms` creep rides on the same calls

Layer 1's terminal guard covers `update_status`, so no stage annotation and no
`updated_at` bump reaches a terminal run through it. The `record_*` writers are
NOT guarded, and each of them still lands once after the cancel — because the
stage service that produces their payload had already been entered. Measured on
the same fixture (the delta is that fixture's fake-provider latency, so in
production it is the real debate/synthesis round-trip, i.e. seconds):

| cancel window | post-terminal `record_*` write | `updated_at` moved by |
| --- | --- | --- |
| just after the pre-debate gate | `record_debate_outputs` | 2.85 ms |
| just after the pre-synthesis gate | `record_final_synthesis` | 1.63 ms |

Deliberately left alone in Layer 1: guarding `record_*` would only mask the
symptom, and the writes disappear on their own once Layer 2 stops entering the
stage service at all. Layer 2 is done when the counts above are 0 AND no
`record_*` call lands on a terminal run.

## Why it is a separate change, not a bigger Layer 1

Layer 1 is one method in one file, guarded by a repository lock, with no new
parameters. Layer 2 changes two public service signatures and their call sites,
and touches the parallel synthesis-section thread pool. Different blast radius,
different review.

## The circular-import caveat (the actual design constraint)

The import direction is `query_runs → debate` and `query_runs → synthesis`
(`src/product_app/query_runs.py` imports `debate_stub_service` and
`synthesis_stub_service`). Neither service imports `query_runs`, and neither
may start: `debate.py` importing `query_runs` to call `_should_stop` — or to
read `query_run_repository` — would be a cycle.

So the cancel signal must be **threaded down as a callable**, not imported:

```python
# query_runs.py
debate_stub_service.run_debate_rounds(
    ...,
    should_stop=lambda: _should_stop(query_run_id),
)
```

```python
# debate.py / synthesis.py
def run_debate_rounds(self, *, should_stop: Callable[[], bool] | None = None, ...):
    ...
```

Keep the parameter keyword-only with a `None` default so every existing caller
and test keeps working unchanged.

## Suggested scope

1. `debate.run_debate_rounds`: check `should_stop()` before round 1's provider
   call and again before round 2's; on stop, return a `DebateResult` marked as
   not completed rather than raising (the caller already returns at its own
   `_should_stop` gate).
2. `synthesis.produce_final_synthesis`: check `should_stop()` before submitting
   the section calls, and inside each pooled section worker before its provider
   call — sections run in a `ThreadPoolExecutor`, so a single entry check only
   covers the window before submission.
3. Optionally replace the status-field-as-cancel-signal with an explicit
   per-run `threading.Event`. The status field works, but it couples "is the
   run cancelled" to "has some other writer touched the status", which is the
   exact coupling that produced F-05 in the first place.

## Tests it must ship with

Extend `tests/integration/test_f05_terminal_status_not_overwritten.py`: the
three `_run_pipeline_with_cancel_at` windows are already parametrised, so
Layer 2 is done when `pre_debate` and `mid_debate_round_1` drop to
`calls_after_cancel == 0` and `pre_synthesis` drops from 4 to 0. Prove RED
before / GREEN after by reverting the Layer 2 change only.
