# ADR-0030: A citation marker is compared in the shape the source store keeps, and a terminal run is evaluated once

## Status

Accepted — 2026-08-10 (issues #285 then #284, in that order)

## Context

Two defects on the same read path, one of which had to be fixed before the
other could be safely built.

### #285 — the fragment asymmetry

`providers._sanitize_source_url` cuts everything from the first `#` off every
URL it stores on a source row. `evaluation.citation_marker_census` compared a
citation marker against those rows **without** that cut. Two independent
spellings of "the same page", and nothing in the tree compared them.

So a model that cited its own retrieved page with an anchor —
`https://a.test/doc#section` against the stored `https://a.test/doc` — matched
nothing, and fell into `unverifiable`: the bucket for an **off-run** URL, which
is deliberately excluded from the grounding denominator.

The premise this work was handed said "direction is over-crediting". That is
half wrong, and the correction is the point of the record. **The marker leaves
the denominator entirely, so grounding moves in whichever direction the
exclusion happened to favour.** Measured on this tree at `de1a639`, one stored
source `https://a.test/doc` (produced by `_sanitize_source_url` from
`.../doc#section`), probe in the session scratchpad:

| answer prose | before | after |
|---|---|---|
| `[d](…/doc#section)` alone | res 0, unres 0, **unver 1**, grounding `None` | res 1, grounding **1.0** |
| `[d](…/doc#section)` plus a bogus `[9]` | res 0, unres 1, unver 1, grounding **0.0** | res 1, unres 1, grounding **0.5** — before was UNDER-crediting |
| a stub row cited as `…/local-demo/1#s` | res 0, unres 0, unver 1, grounding **`None`** | unres 1, grounding **0.0** — before was OVER-crediting |
| off-run host, with or without `#` | unver 1 | unver 1 — unchanged |
| same host, different path, with `#` | unver 1 | unver 1 — unchanged |
| same URL with a query string | unver 1 | unver 1 — unchanged |

The harm the issue text does not mention is the largest one.
`evaluation.presentation_confidence` returns `"indeterminate"` — the advisory
faithfulness and hallucination labels are withheld from the page — whenever
`unverifiable_marker_count` is above zero and the labels sit at the confident
end. Every anchored citation inflated that count. **A run that cited its own
real sources correctly, with anchors, had its labels suppressed for doing so.**

### #284 — the evaluation is recomputed on every read

`query_runs._evaluation_projection` ran the whole Layer-A engine on every
`GET /v1/query-runs/{id}`, and `get_query_run_result` is a plain `def` FastAPI
route, so that CPU burns in the threadpool holding the GIL. A terminal run's
evaluation cannot change unless the run body changes, so every poll after the
first was waste.

Measured on this Mac (`evaluate_run`, 4 slots, best of 3, probe in the session
scratchpad; `_PARSE_LIMIT_CHARS = 16384`):

| answer shape | length | per evaluation |
|---|---:|---:|
| plain prose | 8 000 | **3.3 ms** |
| all `[` | 8 000 | **563.4 ms** |
| all `[` | 16 383 | **1 155.8 ms** |
| all `[` | 16 385 | **6.4 ms** (over the parse limit, the guard bites) |

**The issue's 1 478 ms / 3 102 ms were NOT reproduced here.** Same phenomenon,
same order of magnitude, different machine. Quote the numbers above, or
re-measure.

Two more facts, measured through the endpoint with a counter wrapped around
`query_runs.evaluate_run`: creating one run ran the engine **2** times
(`_result_response` and then `_persist_run_evaluation`), and each subsequent
GET ran it **1** more.

### Why #285 had to ship first

Serving a stored evaluation while the fragment bug is live freezes a
wrong number into `/data/run_history.sqlite3` — a Fly volume with no migration
machinery, no backfill, and no retention sweep. ADR-0029 already records that
a code fix is not a backfill.

## Decision

**1. A citation marker is compared in the shape the source store keeps it in.**
A new module-private helper, `evaluation._canonical_marker_key`, cuts the
fragment and then delegates to the existing `_normalize_url`. It is applied to
**both** sides at all four `citation_marker_census` call sites. Neither
`_normalize_url` nor `_sanitize_source_url` changes behaviour.

**2. A fragment that begins `/` or `!` is a client-side ROUTE and is not
folded.** `https://a.test/#/route` is a different document from
`https://a.test/` to the reader. The guard is strictly conservative: every case
it declines to fold keys exactly the way today's code does, so it can never
move a marker that is currently counted.

**3. `EVAL_SCHEMA_VERSION` moves `s3-eval-v4` → `s3-eval-v5`.** The meaning of
`citation_marker_grounding` and `unverifiable_marker_ratio` changes, so rows
written under v4 and v5 are not comparable.

**4. The terminal evaluation is memoised in-process, keyed on
`(query_run_id, updated_at, agreement.aligned, agreement.total)`,** in a bounded
LRU of 512 entries, at `query_runs._evaluate_terminal_run` — the one site both
readers go through. One create plus N reads collapses from N+2 engine runs to
**1**, and the served projection and the persisted row become identical by
construction rather than by two runs of a pure function agreeing.

`updated_at` is in the key because `record_initial_answer` and
`record_final_synthesis` carry **no** terminal guard — unlike `update_status`,
which refuses a terminal write at `query_runs.py:865`. A late-landing answer
after a deadline degrade or a cancel therefore can still change the inputs of
an already-terminal run. The per-read recompute self-corrected for that; a
run-id-only memo would freeze the evaluation while the body kept moving. Every
mutator bumps `updated_at`, so the key invalidates exactly when the run
changes, and it fails in the safe direction: an unexpected bump costs one extra
evaluation, never a stale answer. `agreement` is in the key because it is
computed by the caller, so the memo must not assume it is a function of the run.

**5. The route stays a plain `def`.** The complaint is CPU under the GIL;
removing the CPU removes it. `async def` would put blocking work on the event
loop instead, which is strictly worse.

## Rejected alternatives

| Alternative | Why not |
|---|---|
| **Stop stripping the fragment in `_sanitize_source_url`** (fix the producer) | One shape fixed, two broken: a stored `…/doc#section` would stop matching a bare `…/doc` marker and a `…/doc#other` marker. It also splits one page into several bibliography rows through the `seen`-set dedup in `_extract_citations`, inflating the citation-coverage denominator, and it puts provider-chosen text back into three prompt-inlining consumers. |
| **Fold the fragment inside `_normalize_url`** | Functionally identical today — that function has exactly four call sites, all inside `citation_marker_census` — but it falsifies the pinned docstring on `test_url_markers_are_matched_modulo_trailing_punctuation_and_case` ("folds exactly these differences and no others"), and leaves nowhere clean for the route guard. |
| **Plain fold with no route guard** | Measured: `https://a.test/#/route` cited against a stored `https://a.test/` becomes `resolved`, grounding 1.0, where today it is `unverifiable`. A new over-credit introduced by an anti-over-credit fix. The guard costs one condition and one test. |
| **Parse with `urlparse` and drop `.fragment`** | A new `ValueError` path in a pure hot loop — and two independent parsers agreeing only by coincidence is exactly what produced #285. |
| **Extract one shared `strip_url_fragment` and import it into both modules** | Attractive, but incompatible with the route guard: the two sides then legitimately differ on `#/`. Cheaper to state the byte-equality in the helper docstring and pin it with `tests/integration/test_source_url_sanitization.py::test_the_marker_key_agrees_with_the_sanitiser_on_a_stored_source_url`. |
| **Also fold the query string** | A different concern — both sides already agree on it, so there is no asymmetry — and `tests/unit/test_evaluation_layer_a.py` deliberately pins the query string as discriminating. |
| **Fix the uppercase-scheme hole in the same PR** | Measured: `HTTPS://A.TEST/doc` scores res 0, unres 0, unver 0 — the marker vanishes from the census entirely, because `_LINK_TARGET_RE` is lowercase-only. Strictly worse than #285 and a separate concern. Not fixed here. |
| **Serve the persisted `eval_json` / `trust_json` instead of memoising** | The literal reading of #284, and it buys nothing today. `get_query_run_result` resolves the run through the in-memory repository (1-hour TTL), nothing on the result path reads the durable row back (`query_runs` imports only `record_terminal_run` and `update_evaluation` from it), and the deployment is one uvicorn worker (`Dockerfile:72`) — so any run a GET can reach was evaluated by this process on this build. It would take on eight failure modes (partial write with `eval_json IS NULL`, corrupt blob, store absent or reconnected mid-process, a rehydrated default served as a measurement, `trust_json` carrying no version stamp, SQLite lock contention on the request path) for no gain. If it is ever built, the rule is: serve the stored row **only** when the run is terminal AND `eval_json["schema_version"]` is **exactly equal** to `EVAL_SCHEMA_VERSION`; everything else recomputes. Exact equality, never an ordering comparison — the suffix is an unpadded integer, so `"s3-eval-v4" < "s3-eval-v10"` is `False`. And never `RunEvaluation.model_validate(eval_json)`: `to_eval_json` drops the required `judge.rationale` and adds `prompt_id`, while `EvalJudgeVerdict` is `extra="forbid", strict=True`, so that call raises on every judged run. |
| **Do #284 first, or fold both into one PR** | Every run completing in between would freeze a v4-grammar score into a durable volume with no backfill. |
| **Persist `judge_status` and `label_confidence` alongside** | `_judge_status_for` is a dict lookup in a memo that already exists, and `presentation_confidence` is two comparisons. Neither is the cost. |

## Consequences

- **Anchored citations now count.** A run whose models cite their own retrieved
  pages with `#section` anchors gets a grounding number instead of an
  exclusion, and keeps its advisory labels instead of being forced to
  `"indeterminate"`.
- **Stored evaluations from before this change are not comparable to new ones.**
  The version stamp says so; nothing backfills them. `run_history_store` has no
  migration machinery and no retention sweep, so v4 rows will sit in the volume
  indefinitely. An operator comparing grounding across the deploy boundary must
  filter on `schema_version`.
- **Nothing enforces the fixture version stamp.** The seven `schema_version`
  strings in `e2e/fixtures/evaluation-variants.json` were updated by hand;
  `tests/contract/test_golden_fixture_matches_served_schema.py` validates those
  fixtures against `RunEvaluation`, whose `schema_version` is a bare `str`, so a
  stale fixture is silent. Stated here rather than left to be discovered.
- **The route guard is unmeasured against real provider output.** Whether a
  model ever emits a `#/` or `#!` citation offline cannot be answered; the guard
  is conservative either way, because it can only ever leave a marker where
  today's code already leaves it.
- **A new process global exists.** The evaluation memo joins the cost event
  ring, the run-capacity semaphore and the judge verdict memo. It is reset in
  `tests/conftest.py::_reset_state`, and `tests/unit/test_query_run_evaluation_memo.py`
  pins both the eviction and the reset seam.
- **The memo is in-process only.** It matches the single-worker deploy. A second
  worker, or a restart, costs one extra evaluation per run — never a wrong
  answer.
- **Two docstrings that were wrong are now correct and say so.** The stated
  reasons for stripping the fragment — SPA hash routing and `javascript:`
  smuggling — were both false: `grep -c "location.hash\|hashchange\|pushState"
  src/product_app/static/app.js` returns 0, `grep -rn iframe` over `app.js` and
  `templates/` returns nothing, and the scheme gate runs before the fragment
  cut. The behaviour is unchanged; only the reasons are.
