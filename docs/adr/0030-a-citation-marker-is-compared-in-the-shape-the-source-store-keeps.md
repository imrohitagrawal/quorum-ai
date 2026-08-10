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

| answer shape | length | per evaluation (3 separate best-of-3 runs) |
|---|---:|---|
| plain prose | 8 000 | **3.3 / 7.6 ms** |
| all `[` | 8 000 | **530.2 / 563.4 / 575.8 ms** |
| all `[` | 16 383 | **1 115.5 / 1 155.8 / 1 182.4 ms** |
| all `[` | 16 385 | **6.3 / 6.4 ms** (over the parse limit, the guard bites) |

**Three numbers per row on purpose.** The first version of this ADR quoted a
single figure — `563.4` / `1 155.8` — while `query_runs.py` quoted `575.8` /
`1 182.4` for the same measurement, and the commit body said "quote the
numbers above". Two figures, one measurement, one commit. Re-running the same
bench a third time gave a third answer. The honest reading is **half a second
at the 8 000-char cap and about a second just under the parse limit, ±5%
run-to-run on one machine**. Do not quote a third significant digit from this
table; it is noise, and treating it as a constant is what produced the
contradiction.

**The issue's 1 478 ms / 3 102 ms were NOT reproduced here.** Same phenomenon,
same order of magnitude, different machine. Quote the range above, or
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

**2. EVERY fragment folds, including a client-side route — because the store
already threw the route away.** The first draft of this decision kept a guard
for a fragment beginning `/` or `!`, reasoning that `https://a.test/#/route`
is a different document from `https://a.test/` to the reader. Review refuted
it by measurement, driving the real
`providers._extract_citations` → `citation_marker_census` path, where the
inline-markdown fallback mints the source row from the very same `[text](url)`
the census reads as a marker — so marker and row are the identical string by
construction:

| marker (source row minted from it) | with the route guard | without it |
|---|---|---|
| `https://petstore.swagger.io/#/pet/addPet` | unverifiable | resolved |
| `https://twitter.com/#!/someuser` | unverifiable | resolved |
| `https://a.test/doc#section` | resolved | resolved |

The first two rows are **#285 unfixed**, on an ordinary Swagger UI docs link.
The guard defended a distinction that no longer exists in the store: because
`_sanitize_source_url` cut the route off first, the row for a hash-route
citation *is* the base page.

Worse, it was a **spelling** filter, not a category one. Against one stored
`https://docs.example.com/`:

| marker fragment | with the route guard |
|---|---|
| `#/api/tokens` | unverifiable |
| `#!/api/tokens` | unverifiable |
| `#doc/12345` | resolved |
| `#page=3` | resolved |
| `#%2Fapi%2Ftokens` | resolved — the percent-encoded form of the shape it blocked |
| `#about` | resolved |

An inconsistency that arbitrary is worse than either consistent choice.

**The price, stated plainly:** a citation of `https://a.test/#/route` is now
credited against a stored `https://a.test/`, so grounding rises for hash-route
citations. To stop crediting them, the fix belongs in `_sanitize_source_url` —
**keep** the route on the stored row — not in a second, differently-shaped cut
on the comparison side.

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
| **Stop stripping the fragment in `_sanitize_source_url`** (fix the producer) | One shape fixed, two broken: a stored `…/doc#section` would stop matching a bare `…/doc` marker and a `…/doc#other` marker. It also splits one page into several bibliography rows through the `seen`-set dedup in `_extract_citations`, inflating the citation-coverage denominator, and it puts provider-chosen text back into **two** prompt-inlining consumers (`synthesis.py:764` and `evaluation.py:1715`; this row said "three", inherited from a comment in `providers.py` that named debate as a third — `grep -c "\.url" src/product_app/debate.py` prints **0**, and both have been corrected). **This is still the right fix for the hash-route case specifically** — see Decision 2 — but not for fragments in general. |
| **Fold the fragment inside `_normalize_url`** | Functionally identical today — that function has exactly four call sites, all inside `citation_marker_census` — but it falsifies the pinned docstring on `test_url_markers_are_matched_modulo_trailing_punctuation_and_case` ("folds exactly these differences and no others"). This row also said it "leaves nowhere clean for the route guard"; that reason died with the guard (Decision 2), and the docstring reason alone still stands. |
| ~~**Plain fold with no route guard**~~ — **ADOPTED, see Decision 2** | This row originally rejected it: "`https://a.test/#/route` cited against a stored `https://a.test/` becomes `resolved`, grounding 1.0, where today it is `unverifiable`. A new over-credit introduced by an anti-over-credit fix." The measurement was right and the conclusion was wrong, because it was taken with a hand-written source row. Derive the row from the marker through the real producer — which is what `_extract_citations` does on the inline-markdown path — and the guard leaves an ordinary Swagger UI citation in `unverifiable`, i.e. #285 unfixed. Kept on the record because it cost a review round. |
| **Parse with `urlparse` and drop `.fragment`** | A new `ValueError` path in a pure hot loop — and two independent parsers agreeing only by coincidence is exactly what produced #285. |
| **Extract one shared `strip_url_fragment` and import it into both modules** | This row's original reason — "incompatible with the route guard" — died with the guard. The remaining reason is weaker and worth stating honestly: the two cuts are now byte-identical, so a shared helper WOULD be the stronger construction, and the only thing against it is that `evaluation` importing a helper out of `providers` (or a third module) for one line is churn we chose not to spend here. Pinned instead by `tests/integration/test_source_url_sanitization.py`, which asserts the marker key against **literals** and separately asserts the two sides agree. If this drifts a second time, extract the helper. |
| **Also fold the query string** | A different concern — both sides already agree on it, so there is no asymmetry — and `tests/unit/test_evaluation_layer_a.py` deliberately pins the query string as discriminating. |
| **Fix the uppercase-scheme hole in the same PR** | Measured: `HTTPS://A.TEST/doc` scores res 0, unres 0, unver 0 — the marker vanishes from the census entirely, because `_LINK_TARGET_RE` is lowercase-only. Strictly worse than #285 and a separate concern. Not fixed here. |
| **Serve the persisted `eval_json` / `trust_json` instead of memoising** | The literal reading of #284, and it buys nothing today. `get_query_run_result` resolves the run through the in-memory repository (1-hour TTL), nothing on the result path reads the durable row back (`query_runs` imports three names from `run_history_store` — `RunHistoryRow` at `query_runs.py:98` plus `record_terminal_run` and `update_evaluation`; this row said "only" the latter two, and the conclusion survives but the absolute did not), and the deployment is one uvicorn worker (`Dockerfile:72`) — so any run a GET can reach was evaluated by this process on this build. It would take on **six** failure modes — this row said "eight" while its own list held six — (partial write with `eval_json IS NULL`, corrupt blob, store absent or reconnected mid-process, a rehydrated default served as a measurement, `trust_json` carrying no version stamp, SQLite lock contention on the request path) for no gain. If it is ever built, the rule is: serve the stored row **only** when the run is terminal AND `eval_json["schema_version"]` is **exactly equal** to `EVAL_SCHEMA_VERSION`; everything else recomputes. Exact equality, never an ordering comparison — the suffix is an unpadded integer, so `"s3-eval-v4" < "s3-eval-v10"` is `False`. And never `RunEvaluation.model_validate(eval_json)`: `to_eval_json` drops the required `judge.rationale` and adds `prompt_id`, while `EvalJudgeVerdict` is `extra="forbid", strict=True`, so that call raises on every judged run. |
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
- **The fixture version stamp is now gated.** This entry said "nothing enforces
  the fixture version stamp", and stating a hole is not closing one (AGENTS.md
  rule 1a). Measured: reverting all seven `schema_version` strings in
  `e2e/fixtures/evaluation-variants.json` from `s3-eval-v5` to `s3-eval-v4` and
  running `pytest tests/contract` gave **43 passed** — in a change whose whole
  premise was a grammar-version bump, the seven edits carrying it were the ones
  no gate could see, because `RunEvaluation.schema_version` is a bare `str`.
  `test_each_variant_is_stamped_with_the_schema_version_the_server_emits` now
  compares every variant against `EVAL_SCHEMA_VERSION`; the same revert now
  gives **7 failed, 44 passed**.
- **Hash-route citations now count toward grounding.** The consequence of
  Decision 2, and the one thing this change makes more generous rather than
  more honest. It is unavoidable while `_sanitize_source_url` discards the
  route: the store keeps no information that could distinguish
  `https://a.test/#/route` from `https://a.test/`. Whether a model emits such
  citations often enough to matter is **unmeasured** — it cannot be answered
  offline.
- **A polled run's judge entry is kept hot deliberately.** Serving from the
  evaluation memo skips `_MemoisedRunJudge.evaluate`, whose `move_to_end` was
  the only thing refreshing `_judge_verdict_memo` for a run being polled. That
  entry is the sole record that a paid judge call happened, so an eviction
  reads as "no judge ever ran" and drops a billed line from a receipt still
  labelled `measured` — measured on the first draft, $0.0101 → $0.0035.
  `_judge_memo_touch` restores the refresh, and reorders only: it must never
  insert, or `_actual_cost` would price a judge that never ran.
- **A judge-timeout read is served but never memoised.** `_MemoisedRunJudge`
  serves the suppressed, verdict-less shape once to a reader whose wait on the
  owner's in-flight call expires. With a memo in front, whichever thread stores
  LAST wins a key that never changes again for a terminal run, so that reader
  could freeze `band="unverified", score=None` over a run the judge really
  verified. Such results are excluded from the memo. The cost is that a run
  whose judge never answers recomputes Layer A per read — bounded to that run,
  and only until the owner stores.
- **A new process global exists.** The evaluation memo joins the cost event
  ring, the run-capacity semaphore and the judge verdict memo. It is reset in
  `tests/conftest.py::_reset_state`, and `tests/unit/test_query_run_evaluation_memo.py`
  pins the eviction, the LRU refresh and the reset seam — driving six real runs
  through `_evaluate_terminal_run` with the cap monkeypatched to 5. That file
  originally drove the `_evaluation_memo_store` helper instead, and measured:
  replacing the store call inside `_evaluate_terminal_run` with a bare
  `_evaluation_memo[key] = result` left **347 passed** while the real path grew
  to 562 entries against a cap of 512.
- **The memo is in-process only.** It matches the single-worker deploy. A second
  worker, or a restart, costs one extra evaluation per run — never a wrong
  answer.
- **Two docstrings that were wrong are now correct and say so.** The stated
  reasons for stripping the fragment — SPA hash routing and `javascript:`
  smuggling — were both false: `grep -c "location.hash\|hashchange\|pushState"
  src/product_app/static/app.js` returns 0, `grep -rn iframe` over `app.js` and
  `templates/` returns nothing, and the scheme gate runs before the fragment
  cut. The behaviour is unchanged; only the reasons are. **Note the scope on
  the iframe claim** — `grep -rl iframe src/` DOES hit
  `static/vendor/markdown-it.min.js` and `static/vendor/swagger-ui-bundle.js`,
  so "no iframe anywhere" (as an earlier commit body put it) is false; what is
  true is that the workspace this app authors mounts none.
