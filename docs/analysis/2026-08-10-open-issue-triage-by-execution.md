# Open-issue triage by execution — 2026-08-10

All 16 open issues, each checked by running a command rather than reading the
issue. Verified against `de1a639`, which is also production's `build_sha`
(`curl /status` → `de1a639a30d0425b3acbc71fa90a1b9b840c3bab`), so "on main" and
"in production" are the same tree today.

Every row below says how it was settled. Where a claim could not be settled
without a paid run or production telemetry, it is marked UNVERIFIED and the
exact missing measurement is named.

## Method note — one correction to my own run

An early `grep` for `.list_events(` returned **0 matches** and briefly looked
like #209 had evaporated. It had not: a previous `cd e2e` had persisted, so the
grep ran against the wrong tree. From the repo root the same command returns
**36**. Recorded because it is the failure this repo's rule 1 exists to catch,
and it nearly produced a confidently-wrong "already fixed" verdict.

## Verification results

| # | Verdict | Live or latent | How it was settled |
|---|---|---|---|
| 285 | **CONFIRMED** | **LIVE in production** | Executed `citation_marker_census` with both controls |
| 284 | **CONFIRMED, worse than filed** | **LIVE in production** | Counted recomputes per GET; measured the cost |
| 160 | **CONFIRMED** | Latent — but already bit once | Added a 14th enum member, ran the full suite |
| 145 | **CONFIRMED** | Test tooling | Executed `_is_literal` over 8 expressions |
| 209 | **CONFIRMED, larger than filed** | Test-only flakiness | 36 unfiltered call sites, not 8–11 |
| 226 | **CONFIRMED, smaller than filed** | Latent | Ran the guard: 13 violations in 5 files, not 20 in 8 |
| 224 | **CONFIRMED** | Latent | Executed `_window`/`_claims` with a positive control |
| 143 | **CONFIRMED** | Metrics integrity | No test compares the replay script to the Makefile |
| 167 | **CONFIRMED** | Process gap | No lint and no paired-mutation runner exists |
| 242 | **CONFIRMED** | Process durability | `.claude/` is gitignored; stale path still on line 7 |
| 216 | **CONFIRMED, latent today** | Latent — gates the judge | Production `judge_enabled: false` |
| 268 | **CONFIRMED gap, magnitude UNVERIFIED** | Unknown | Constants appear only in pricing and display code |
| 105 | Premise stands, **blocked** | Over-states, never under-states | No production telemetry exists to read |
| 203 | **Blocked on measurement** | Latent | Needs a real proxy/WAF 403 from the egress path |
| 134 | Confirmed as filed | Process | `scripts/session_handoff.py` prints no live state |
| 146 | **INHERITED, not re-verified** | Tooling | Re-checking needs a ~60-minute `mutmut` run |

## The two live defects, in detail

### #285 — a deep-link citation can never resolve

`_sanitize_source_url` strips the fragment from every stored source row;
`_normalize_url` does not strip it from a marker. Executed on the merged tree,
with controls in both directions:

```
marker WITH #fragment    -> resolved=0 unresolved=0 unverifiable=1
marker no fragment       -> resolved=1 unresolved=0 unverifiable=0   <- positive control
genuinely off-run URL    -> resolved=0 unresolved=0 unverifiable=1   <- negative control
```

The fragment case is **indistinguishable from a genuinely off-run URL**. It does
not count against the answer — it leaves the denominator entirely, so the
direction is *over*-crediting: the citation silently stops being checked.

Blast radius: the trust score and grounding percentage on every run whose model
cites a section anchor. Deep links into specs and standards are exactly the
citation style this product's stated users get from a search-backed model.

### #284 — the evaluation is recomputed on every read

Executed against a real terminal run through `TestClient`:

```
counts after CREATE: {'census': 2, 'evaluate_run': 2}
GET #1: evaluate_run=1 census=1   GET #2: evaluate_run=1 census=1   GET #3: evaluate_run=1 census=1
```

`eval_json`/`trust_json` are written to `run_history_store` and **never read
back** by `query_runs`. `get_query_run_result` is a plain `def` route, so this
runs in the threadpool holding the GIL.

Cost measured on a dev Mac, minimum of 3 runs, at the app's **own** answer cap
(`initial_answer_max_tokens` 2000 × `CHARS_PER_TOKEN` 4 = 8000 chars):

| Input shape | 9 scopes | Per GET |
|---|---|---|
| benign prose, 16 KB | — | 48 ms |
| hostile `[[[[1`, 8 000 chars (reachable within the app's own cap) | — | **1 478 ms** |
| hostile `[[[[1`, 16 380 chars (just under `_PARSE_LIMIT_CHARS`) | — | **3 102 ms** |

#283's `_PARSE_LIMIT_CHARS = 16_384` bounds a *single* scope. It does not bound
the **nine** scopes a run projects, so the per-GET worst case is ~9× the
per-scope bound. The issue filed 2.55 s; the measured figure is higher, and the
production box is a 512 MB machine, not this Mac.

Second symptom, same root: a run that completed before a grammar change serves a
different number than the one stored for it.

## Priority list

**P0 — live, user-visible, fix now**

1. **#285** — trust surface over-credits unchecked citations.
2. **#284** — multi-second GIL-holding recompute on every page view.

**P1 — one PR unblocks three issues**

3. **#105 + #268 + #203** are all blocked on the *same* missing thing, verified:
   no log drain (`DEPLOY.md` lists it as future work), no per-token columns in
   `run_history_store`'s `runs` table, and the Fly log ring holds ~100 lines.
   None can be closed by reasoning; all three become decidable the moment
   durable structured telemetry exists.

**P2 — a guard gap that has already let a change through**

4. **#160 + #145.** Executed: adding a 14th `QueryRunStatus` and omitting it
   from `TERMINAL_STATUSES` left **2 701 tests passing**, with one OpenAPI
   shape complaint that regenerating the schema would clear. A control run on an
   unmutated copy confirms the three `findings_ledger` failures were `git init`
   artifacts, not the mutation. Independent evidence it is already biting: the
   repo now has **17** enums, not the 14 the issue counted, and `AlignmentState`
   grew from 4 to 5 members with nothing noticing.

**P3 — tests that do not prove what they claim**

5. **#226** (13 vacuous e2e negatives) **+ #209** (36 unfiltered recorder reads).

**P4 — gated, or process**

6. **#216** — $0/day today (`judge_enabled: false` in production), but it must
   be fixed **before** the judge is switched on, not after.
7. **#167 + #143** — nothing proves a guard test bites.
8. **#224, #242, #134, #146** — latent gate gap, agent-config durability, live
   handoff state, mutation-scope residue.

## Clubbing — how to spend the fewest review-and-deploy cycles

Rule 17 keeps one *concern* per PR; rule 17g permits clubbing issues that share
a function, file, or narrow surface. These four groups do that.

**Group A — "the served evaluation is honest and cheap" (#285 + #284)**
Both were found reviewing #283, both live in `_evaluation_projection` /
`citation_marker_census`, and both are exercised by the same tests. Fixing #284
changes *when* the census runs and #285 changes *what it returns* — doing them
apart means baselining the same surface twice. Note the ordering: fix #285
first, because serving a stored row (#284) would otherwise freeze the wrong
number into the persisted row.

**Group B — "measure production before deciding" (#105 + #268 + #203)**
One PR adding structured, durable telemetry: HTTP status and error-envelope
shape on the 5xx branch (#105), per-call input-token counts (#268), and the
response shape of a 403 on the egress path (#203). Ship the telemetry; the three
classification decisions follow from the data later. This is the single highest
-leverage PR in the backlog — it converts three unanswerable issues into
answerable ones.

**Group C — "our pins bite" (#160 + #145)**
#145 fixes the detector that #160's pins have to pass. Doing #160 first means
writing pins in a form the detector rejects (it refuses `pytest.approx`, used
**84** times in this repo, and every container literal — executed and confirmed).

**Group D — "our guards bite" (#167 + #143)**
Both are "an assertion we cannot show can fail". #143 is the concrete first
instance of #167's general gap, so #167's mechanism can be built and then
demonstrated on #143 in the same PR.

**Group E — test-suite integrity (#226 + #209)**
Both are mechanical and both are "a test that passes over nothing". Separable if
a reviewer objects to Python and TypeScript in one diff; the work does not
interact.

**Deliberately NOT clubbed**

- **#242** and **#134** are both agent-workflow durability, but #242 needs an
  ADR and a `.gitignore` decision while #134 is a script feature. Different
  review shapes.
- **#224** and **#146** are each isolated tooling refinements with no shared
  surface.

## What I did not verify, and the command that would

- **#146** — the claim that 34 of 354 scoped globs still match zero mutants is
  inherited from the issue. Settling it needs a full `mutmut` run over
  `src/product_app` (~60 minutes), which I did not spend.
- **#268's magnitude** — whether any real run has crossed its cap. Needs one
  deliberate paid live run with token logging, or Group B's telemetry.
- **#105's distribution** — needs a week of production logs that do not
  currently exist anywhere.
- **#203's signal** — needs a captured real proxy/WAF 403 from this
  deployment's actual egress path, which may need operator input on what
  intermediaries exist.
