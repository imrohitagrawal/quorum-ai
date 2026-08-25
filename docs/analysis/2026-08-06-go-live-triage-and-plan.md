# Go-live triage and the ordered plan to closure

**Date:** 2026-08-06 · **Tree:** `main` = `dfc0419` · **Method:** every issue driven by
execution, not by reading. Cost: $0 — no paid API call, no live run, no workflow dispatch.

This document is the output of a planning session. Nothing was built. The working tree was
never modified (`git status --porcelain --untracked-files=no` → empty, checked after every
subagent).

---

## 0. State of the world, measured

| Fact | Value | Command |
|---|---|---|
| local `main` / `origin/main` / prod `build_sha` | all `dfc0419` | `git rev-parse`, `curl -s …/status` |
| branded domain | `quorum.stackclimb.com` → 200, same SHA as `quorum-ai.fly.dev` | `curl` |
| environment / live execution / judge | `production` / `true` / **`judge_enabled: false`** | `/status` |
| spend today | `$0.0329` of `$5.00` | `/status` |
| readiness | `state: live`, no reasons, no catalog drift | `/ready` |
| open issues / open PRs / worktrees | 18 / 2 / none | `gh`, `git worktree list` |
| tests collected | 2482 | `uv run pytest --collect-only -q` |
| e2e invariant specs | 16 | `ls -1 e2e/tests/invariants/*.spec.ts \| wc -l` |
| required merge contexts | 6 | `gh api repos/:owner/:repo/branches/main/protection` |
| repo visibility | PUBLIC | `gh repo view --json visibility` |

---

## 1. Go-live, defined

> **Go-live = no defect that is LIVE in production and visible to a real user.**
>
> Owner's decision, 2026-08-06. **The repository could not supply this definition.**

The phrase "go-live" appears exactly once in the entire tree — `DEPLOY.md:219`, where
"Go live" means *set the OpenRouter key and turn live execution on*. That is already done.

The four release documents disagree with each other, and three are stale:

| Document | Says | Last touched | Verdict |
|---|---|---|---|
| `docs/95-production-readiness-review.md:8` | **"Go"** — single-instance Fly.io, human approval **2026-06-21** | 2026-07-27 | **Authoritative.** The only one revised after implementation, the only one carrying a dated human approval, and the only one whose claims survive contact with the running system. Its launch checklist (`:90-101`) is complete |
| `docs/73-release-evidence.md` | **"No-go for production release"**, five open `REL-BLOCK` items | **initial commit (2026-06-20), never updated** | **Stale and wrong.** It states that remote CI, live provider execution and deployment are unavailable. All three demonstrably exist |
| `docs/74-release-checklist.md` | every row `TBD / TBD / TBD` | 2026-06-20 | Unfilled template. Carries no criteria |
| `docs/71-release-plan.md` | five bare bullet headings | 2026-06-20 | Stub. Carries no criteria |

`docs/00-factory-console.md:7` records the current phase as **"Operate, learn, and
improve"** — the factory itself considers this product past release.

The only forward-looking gate anyone wrote down is in `docs/13-open-questions.md`:
**OQ-011**, *"Decide whether any high-stakes topic should move from warning-only to
block/limited mode **before public launch**"* — the sole use of "public launch" as a gate
anywhere in the repo. It, and OQ-009 / OQ-013 / OQ-014, are **product decisions only the
owner can make**. They gate *claims*, not function, and are out of scope under the
definition above (see §7).

---

## 2. Triage — all 18 issues

**LIVE** = a user hitting production today experiences it.
**LATENT** = needs a config, code path, or fixture that is not currently reachable.

### 2.1 BLOCKERS — LIVE and user-visible

#### #256 — the UI calls the point estimate "this run's spend cap"

Three different numbers govern one run, and the user is shown the one that governs least:

| Number | Where | What it actually does |
|---|---|---|
| `max_cost_usd` | `costs.py:1385-1388` | **Gates the run.** Confirmation and block both key off this |
| `estimated_cost_usd` | `costs.py:678-685` | **Books the daily ledger** |
| `estimated_cost_usd` | `workspace.html:369`, `:439`; `app.js:1964` | **Shown to the user, labelled "this run's spend cap"** |

Binary-searched the exact boundaries:

```
=== SOFT boundary (threshold = 0.15) ===
  n=690    est=0.0677 max=0.1500  -> allow
  n=691    est=0.0678 max=0.1501  -> require_confirmation

=== HARD boundary (threshold = 0.25) ===
  n=52303  est=0.2296 max=0.2500  -> require_confirmation
  n=52304  est=0.2297 max=0.2501  -> block
```

At the moment the system demands confirmation, **the figure on screen is $0.0678** — less
than half the number that triggered the demand.

Ratio across query sizes, four default model slots:

| chars | estimated | max_cost | ratio |
|---|---|---|---|
| 50 | 0.0318 | 0.0771 | **2.425** |
| 200 | 0.0323 | 0.0773 | 2.393 |
| 500 | 0.0333 | 0.0776 | 2.330 |
| 1000 | 0.0351 | 0.0782 | 2.228 |
| 8000 | 0.0594 | 0.0856 | 1.441 |
| 60000 | 0.1204 | 0.1408 | 1.169 |

**The issue's "2.3×, n=1" understates the problem.** 2.3× is not an artefact of one run —
it is the structural width of the estimate→bound band, and it is **worst (2.2–2.4×)
exactly where real user queries live**. The production run's actual landed at 99% of
`max_cost_usd`.

Also confirmed by execution: **the estimate contains no `judge` stage or kind at all**, so
with the judge enabled every run necessarily exceeds its "approved figure" by construction.

**Verdict: REAL-BUG-CONFIRMED, LIVE, user-facing. Blocker.**

#### #222 — landing content exceeds a 664px mobile viewport

Booted locally (never production `/ui` — durable 2-per-IP-per-24h mint cap), Playwright
chromium at 390×664:

| condition | CTA top | CTA bottom | fold | **overflow** | scrollHeight |
|---|---|---|---|---|---|
| `live`, banner absent | 830 | 874 | 664 | **+210px** | 1689 (2.54× viewport) |
| `offline_by_no_key`, banner 159px | 990 | 1034 | 664 | **+370px** | 1848 (2.78×) |

`document.elementFromPoint` over both CTAs returns **OFF-SCREEN**. The issue reported
830.5 and 989.8; measured 830 and 990 — reproduced to the pixel, four days later, on a
newer main. The element straddling the fold with the banner absent is
`div.landing-runbar [581,893]`.

**Verdict: REAL-BUG-CONFIRMED, LIVE, user-facing. Blocker.** The only user-facing issue in
the ops/UI batch.

#### NEW — landing CTA occlusion (not filed as an issue)

`app.css:5637-5647` pins `.session-trail-panel` to `position: fixed`, `[610,664]`,
`z-index: 100`, and **nothing hides it on the landing view**. With PR #238's density fix
applied but its trail-hide rule removed, the CTA sits inside the fold at `[616,660]` and
`elementFromPoint` over its centre still returns `div.session-trail-head`.

**The CTA is unclickable even when it is inside the fold.** This is why a
`toHaveScreenshot`/`toBeInViewport` style assertion never caught it — those are
structurally blind to paint order.

**Verdict: REAL-BUG-CONFIRMED, LIVE, user-facing. Blocker.** Accepted into scope by the
owner, 2026-08-06.

### 2.2 CRITICAL — LIVE, money integrity, not user-visible

#### #255 — the ledger meters estimates and never reconciles to actuals

Drove the real ledger (`costs.estimate` + `costs.record_guardrail_event` against
`FeedbackStore.configure_for_tests()`, exactly as `_record_run_billing` does):

```
 run  estimated    bound        action  ledger(daily)
   1     0.0317   0.0771         allow         0.0317
   ...
   6     0.0317   0.0771         allow         0.1902
   7     0.0317   0.0771         block  <-- DAILY CAP FIRED, token=None

LEDGER booked (what the cap sees)   : 0.1902
SUM of those runs' worst-case bounds: 0.4626
DAILY_CAP_USD                       : 0.20
REAL/CAP overshoot                  : 2.29x
```

The **$0.20 cap admits ~$0.458 of real spend.** The event payload has **no field for a
measured actual** — reconciliation is not merely unwritten, there is nowhere to write it.
All four `record_guardrail_event` call sites (`query_runs.py:1236,1306,1325,1522`) are on
the POST path; none writes an actual back. The measured actual lives in a **different
SQLite file** (`run_history.sqlite3` vs `feedback_events.sqlite3`) that the caps never read.

**Verdict: REAL-BUG-CONFIRMED, LIVE, operator-facing. Critical.**

#### NEW — read-modify-write race on the spend rail (not filed as an issue)

`estimate()` reads the rail at `costs.py:677`; `_record_run_billing` writes it ~200 lines
later at `query_runs.py:1501`. No lock spans the two. Barrier-synchronised threads between
the read and the write, one account, in-memory ledger:

```
THREADS=  2  admitted=  2  ledger_booked=0.0634  OVER_CAP=no   overshoot=0.32x
THREADS=  8  admitted=  8  ledger_booked=0.2536  OVER_CAP=YES  overshoot=1.27x
THREADS= 32  admitted= 32  ledger_booked=1.0144  OVER_CAP=YES  overshoot=5.07x
Serial control: 6 runs / 0.1902 booked / 0.95x cap.
```

Independently confirmed:

- `try_record_session_mint` (`feedback_store.py:857`) is the **only** atomic
  check-and-record in the store. Its own docstring says it exists to close *this identical
  race* for session minting, "MEASURED in adversarial review (issue #100 PR2)". **There is
  no spend equivalent.** The money rail is the one rail that did not get the treatment.
- `feedback_store.py:25` states outright: *"No concurrent-writer guarantees beyond SQLite's
  own locking."*
- `ACTIVE_QUERY_EXISTS` (`query_runs.py:1437`) bounds **one account** to one in-flight run.
  But `costs.py:719` reads the **global $5.00 rail unscoped across all accounts**, and
  accounts are free and self-minted (`costs.py:96-99`). **The global rail has no such
  guard.**

Compounds multiplicatively with #255.

**Verdict: REAL-BUG-CONFIRMED, LIVE, operator-facing. Critical.** Accepted into scope by
the owner, 2026-08-06.

### 2.3 DEFERRABLE — LATENT

| # | Executed evidence |
|---|---|
| **#216**, **#258** | Judge is off. With the production-shaped env: `judge_configured() → False`, `_request_path_judge() → None`; with `socket.socket` monkeypatched to raise on any use, still `None` — **zero I/O confirmed**. Setting both env vars to dummies flips the branch to `_MemoisedRunJudge`. $0/day both. **Execution settled #258's open question:** `EvalJudgeService.verifies_support` is a class attribute hard-set `True` (`evaluation.py:1371`), so `support_verified=False` mathematically requires `verdict is None`. The issue's first hypothesis — "the judge declined on principle" — is **impossible for the real service**. The production event was a **failed or non-conforming call**. Three scenarios run: no judge → `unverified/None/$0`; judge ran, non-conforming → `unverified/None/**$0.0109 CHARGED**`; judge ran, conforming → `low/14/$0.0109`. Rows 1 and 2 are byte-identical in every user-visible field while differing by a real charge |
| **#105** | **ALREADY-FIXED (step 1)** in `843583b` + `bc38bbb` + ADR-0012. Built an `HTTPError` with a real `BytesIO` body — clearing the AGENTS.md rule-8a vacuity trap by proving the positive case first (`error_metadata_present: True, provider_name_present: True`) before trusting any negative — then ran the classifier over 9 input classes. The three-valued discriminator **works**, cleanly separating router refusal (`False/False`), provider engaged (`True/True`) and unreadable (`None/None`). `_UNBILLED_HTTP_STATUSES` is deliberately unchanged pending data. **Remaining work is a week of production logs, not code.** The clock started ~2026-08-05, so not before ~2026-08-12 |
| **#203** | Ran `probe_key_auth` over 8 stubbed input classes. A squid HTML 403 and an OpenRouter JSON 403 **both return `unauthorized`**; the function reads zero bytes of body or headers (`mentions '.read()': False`, `'exc.headers': False`, `'Content-Type': False`). Requires a proxy/WAF in the Fly egress path to bite; prod is `state: live`, so none is firing. **New finding: the issue's "no known reliable signal" premise is now weaker** — `_billing_evidence_shape`, landed since the issue was filed, correctly tags the proxy HTML as `not_json` |
| **#245** claim (b) | "Red main yields a skipped deploy rather than a red one" — confirmed on runs `30834990023` and `30835022094` (both jobs `skipped` for red SHA `3444961`), but the last red push to main was 2026-08-03. LATENT since. Condition byte-identical on today's main |

### 2.4 DEFERRABLE — developer-only

| # | Executed evidence |
|---|---|
| **#245** claim (a) | **CONFIRMED and LIVE.** Paired every workflow completion against deploy-run creation for the whole of 2026-08-05: CI **12/12 → deploy run created**; Tests **12/12 → created**; E2E (axe + parity) **12/12 → ZERO**. Not once, in either event class, at any conclusion — a *failing* CI run did create one. Deploy trigger redundancy is permanently one-third down. **Cause UNVERIFIED**: the workflow name matches `deploy.yml:28` byte-for-byte, has never been renamed, has a single registration, and no path filters. Separately: **22 of 40 `skipped` deploy runs are healthy PR-trigger noise**, and GitHub labels them with `head_branch: main`, which is what makes the real failure invisible at a glance |
| **#134** | `make handoff` mutates a tracked file (`scripts/session_handoff.py:128` writes `docs/session-handoff.md`), so it was **not run**. The read-only half was: `scripts/session_handoff.py` reads exactly three git facts (`:33-35`) and **every live-state key #134 asks for is absent** — no main tip, no `build_sha`, no test count, no issue count. Its own output is 12 days stale, names branch `feat/ui-pr1-quickfixes`, and its manual sections still read *"Update manually before closing the session"* — the issue's thesis demonstrated inside its own target file |
| **#242** | `.claude/settings.json` exists on disk (5,670 bytes), is **gitignored** (`.gitignore:27`) and **untracked**. `git ls-tree -r HEAD \| grep -c '^\.claude'` → **0**. So `tests/unit/test_claim_gate_hooks.py` is **15 passed locally, 15 SKIPPED in CI** — the enforcement layer is untested in the only place testing counts. Its `:7` permission still names a `~/Documents/Projects/…` path that does not exist. No ADR records the decision |
| **#143 #145 #146 #160 #167 #224 #226 #209** | Gate-machinery integrity — see §2.5 |

### 2.5 The eight gate-machinery issues, re-measured

Every one was driven by execution, mutating only `git archive HEAD | tar -x` scratch
copies (rule 12b). **Three of the eight numbers have moved, and two issues are now worse
than they were filed.**

| # | Issue claims | Measured today | Verdict |
|---|---|---|---|
| **143** | equivalence holds, only needs pinning (66 examined, **0** mismatches) | **75 of 80 commits mismatch**, 14 distinct phantom globs | **WORSE — the drift already happened** |
| **145** | 3 detector gaps | 6/6 unreachable shapes accepted, 6/6 approx/container shapes rejected, **16** class constants invisible | CONFIRMED, broader than filed |
| **146** | 34 of 354 globs match zero mutants | **35 of 388** (11 nested + 24 no-content) | CONFIRMED, denominator stale |
| **160** | 11–12 of 14 enums unpinned | **10 of 15** unpinned — 15 enums exist, 5 now pinned | PARTLY FIXED |
| **167** | 3 vacuous guards | all 3 fixed; **a 4th, still live, found 30 lines below one of them** | CONFIRMED via new instance |
| **224** | *"Not live: no current doc uses the shape"* | **2 real doc lines** now carry it | **WORSE — now live** |
| **226** | 20 vacuous specs across 8 files | **13** across 5 tracked files (+1 gitignored) | PARTLY FIXED, incidentally |
| **209** | ~8–11 call sites across ≥6 files | **9 tests across 6 files** break under an injected leak | CONFIRMED, now precise |

**#143 is no longer a missing pin — it is a broken-evidence bug.** The Makefile gained
`unmutatable()` / frozen-class handling at `024af24` (the #136/#144 fix);
`scripts/replay_mutation_scope.py` was last touched at `f473288` and has **no decorator
handling at all**. The 14 phantom globs are exactly the decorated things the Makefile
documents mutmut cannot mutate — FastAPI routes, Pydantic validators, `@property`.
Consequence: every figure in `docs/metrics/mutation-gate-study.md` §3 sourced from the
replay script — including the **7% abort rate** — was produced by a script modelling a gate
that no longer exists, and is over-reporting the failure the Makefile fix already
eliminated. Meanwhile `tests/unit/test_mutation_test_set_integrity.py:199` tells the next
reader to *"Re-measure with `scripts/replay_mutation_scope.py`"* — pointing at the stale tool.

**#224's own "Not live" assessment is now false.** Two lines in
`docs/analysis/03-enforcement-machinery.md` (`:77`, `:81`) carry the exact shape today, and
the file was last touched the day *after* #224 was filed. Both hidden claims happen to be
**true** against the workflow, so the corpus tests are green **by luck, not by coverage**.
Execution also shows the gap is broader than the title: `` `id` job, blocking `` with no
parenthetical at all is equally missed. The rule is simply "the first comma cuts".

**#167's fourth instance**, proven by mutating a scratch copy — deleting the
`check_diff_cover_measured.py` invocation from the Makefile leaves
`test_the_diff_cover_floor_is_wired_into_the_makefile` (`tests/unit/test_gate_liveness_floors.py:584-590`)
**green**. It reads the raw Makefile; the guard 30 lines above it in the same file uses
`code_without_comments()`. The helper exists, the convention exists, and the very next
guard does not use it — #167's thesis, demonstrated. Repo-wide: **5** assertions use the
helper against **131** raw substring assertions.

**#160's most valuable pin is still open.** Adding a 14th `QueryRunStatus` member to a
scratch copy and running the full suite turns exactly **one** test red — and it is a schema
complaint (`test_openapi_yaml_matches_app_openapi`). Regenerate `openapi.yaml` and the
omission ships. That is the shape of **F-05**, a real escaped production defect. Three
enums (`ProviderPath`, `AlignmentState`, `FinalAnswerProvenance`) gained pins as a **side
effect of #247**, not from any #160 work.

**#209's flake is a timing race, not an ordering bug** — 0 failures in 20 sequential runs,
and reversing module order changed nothing, so shuffling cannot surface it. Making the leak
deterministic (a `pytest_runtest_call(tryfirst)` hook recording one unrelated event *after*
every fixture) broke **9 tests across 6 files**. The issue over-claimed two files and
missed one (`tests/integration/test_query_run_safety_warnings.py`). It also proved #104's
fix genuinely works: `test_release_hardening_workflow` survives a provider-recorder-only
leak via its `account_id` filter, while its debate/synthesis/warning reads at `:147-149`
do not.

---

## 3. Clusters and the clubbing decision

| Cluster | Issues | Decision | Rule |
|---|---|---|---|
| **Money truth** | #255, #256, #216, + the race | **CLUB — one PR** | **17g.** File sets overlap on `costs.py`, `feedback_store.py`, `query_runs.py`. #216 is a strict subset of #255 (the issue owner's own comment says so; verified independently). The race lives in the same two functions. Owner's decision 2026-08-06, and the money subagent independently recommended the identical grouping |
| **Landing mobile** | #222 + occlusion | **CLUB — one PR** | **17g.** Literally the same CSS block, `app.css:5633-5651` |
| **Judge observability** | #258 | **SEPARATE** | **17.** Different concern (observability, not billing); files `evaluation.py` + `query_runs.py`; $0/day. Clubbing it into the money PR would put one reviewer on two concerns |
| **Provider / readiness evidence** | #105, #203 | **NOT SCHEDULABLE** | Both blocked — one on elapsed time, one on an operator answer |
| **Gate machinery** | #143 #145 #146 #160 #167 #224 #226 #209 | **CLUB #143+#146 ONLY. The other six stay separate.** Not go-live work either way | **17g** for the pair (4 shared files, causally one bug); **17** for the rest — seven disjoint file-sets sharing only a *theme*, and 17g explicitly forbids clubbing on that. See §3.6 |
| **Deploy signal** | #245 | **SEPARATE** | **17.** Workflow YAML only |

### 3.5 The refuted cluster

The inherited handoff proposed that **#105 and #203 are a pair on `providers.py`**. That
is **false, and confirmed false by execution**:

- #105's subject is `_UNBILLED_HTTP_STATUSES` at **`providers.py:1592`**. The issue body
  names no file at all.
- #203's subject is `probe_key_auth` at **`readiness.py:291`**. It does not touch
  `providers.py`.
- **Zero shared files.**

They share a *methodology* (ADR-0012's "measure before reclassifying"), not code. If they
are ever done together it is on a **new** basis discovered here: `_billing_evidence_shape`
in `providers.py` is exactly the body-shape discriminator `readiness.py` needs.

### 3.6 The eight gate issues are eight, not one — with exactly one clubbing pair

**They are one *theme* (test/gate honesty) spread across seven disjoint file-sets.** Rule
17g is explicit that this distinction is the whole point: *"Do not club issues just because
each is individually small if they are actually unrelated concerns."*

**CLUB #143 + #146 — the only pair that passes 17g.** They share four files (the Makefile's
`MUTMUT_SCOPE_PY`, `scripts/replay_mutation_scope.py`,
`tests/unit/test_mutation_gate_integrity.py`, `docs/metrics/mutation-gate-study.md`), and
execution shows they are not merely adjacent but **causally one bug**: fixing #146's
ancestor in the Makefile at `024af24` is *what created* #143's drift, and #143's
differential test is the only mechanism that would have caught it. Fixing #146 without #143
re-drifts the pair on the next scope change. **Do #143 first** — it is a broken-evidence bug
today; #146 is a 7%-of-PRs annoyance.

**Every other pairing shares zero files.** #167 and #226 both mean "a test that asserts
nothing", but one is Python guards via `tests/code_text.py` and the other TypeScript specs
via `e2e/tools/check-negative-assertions.mjs` — different language, tool, and reviewer.
#145 and #160 both mean "pin a value", but #145 is one detector file and #160 is ten new
test files. #224 is one function. #209 is six test files and no gate at all.

**And the ROI is inverted.** `docs/metrics/defect-discovery-audit.md` — verified exactly,
both figures — records **0 of 16** `src/` defects caught by an automated check and **10 of
16** by adversarial review. The single gate catch *"caught test-vs-code drift, not a product
defect."* `mutation-gate-study.md` §4 independently censuses 158 escaped defects and puts
the mutation gate's yield at **6/158 = 4%**, with a measured **~15% wrong-answer rate** on
PRs. Six of these eight propose *more* machinery on that base.

**#167 anticipates this and demands a replay before anything is built:** *"n=3. Before
building option 2, replay it: how many of the last N guard tests would it have caught? Same
rule every other gate here is held to."* That instruction binds.

Sequencing within the post-go-live burn-down, by measured severity rather than theme:

| Priority | Issue(s) | Why |
|---|---|---|
| **P1** | **#143 + #146**, one PR | The only genuine pair, and #143 is now a broken-evidence bug: 75/80 mismatches, and the study's headline numbers are stale because of it |
| **P2** | **#167 — the 4th instance only** | Provably vacuous today; a two-line fix using a helper that already exists. **Do not build the general runner** until the replay #167 itself demands |
| **P3** | **#160 — `QueryRunStatus` only** | Highest user-defect adjacency of the eight (the F-05 shape). Proven by full-suite run that a 14th member ships silently. The other nine enums are churn |
| **P4** | **#224** | Now live on 2 doc lines, but both hidden claims are *true*, so nothing is currently mis-stated. Fix the framing too — the gap is "any comma", not "a parenthetical" |
| **P5** | **#226, #209, #145** | Real, bounded, low-yield hygiene. #226 blocks nothing until one of 5 files is touched; #209 is a 0/20 flake the issue itself calls non-production; #145 is one file whose gaps are already in its own docstring |

**None of the eight touches a product surface a user sees.** All are out of the go-live set.

---

## 4. Ordered PR sequence

One concern per PR, merged before the next starts (rule 17), each in a dedicated worktree
(17a), squash-merged with an explicit message (17c).

| # | PR | Closes | Size |
|---|---|---|---|
| **0** | Merge PR **#243** (update branch, then merge) | — | Trivial. 1 commit, 2 files, **all 12 checks SUCCESS**, `MERGEABLE`, zero conflict. Its README rewording ("higher-cost runs require confirmation") is more honest and points the same way as #256 |
| **1** | **Money truth** — reconcile the ledger to actuals, make the approved figure mean something, close the race | #255, #256, #216 | **Large.** ~5 source files + ADR + tests |
| **2** | **Landing mobile** — density + occlusion | #222 | Small-medium. `app.css`, one spec |
| **3** | Close PR **#238** as superseded, referencing PR 2 | — | Trivial |
| **4** | **Judge observability** — distinguish "ran and declined" from "ran and failed" | #258 | Small |
| **5** | **Deploy signal** — why E2E never fires `workflow_run`; a red main must go red | #245 | Medium, investigation-heavy |
| **6** | **Mutation-scope drift** — port `unmutatable()` into the replay script, pin the equivalence, re-measure the study | #143, #146 | Medium. The only gate pair; #143 first |
| **7** | The `diff-cover` floor guard — make it read `code_without_comments()` | part of #167 | **Two lines** |
| **8** | Pin `QueryRunStatus` exhaustively | part of #160 | Small |
| **9+** | #224, #226, #209, #145, #134, #242, remainder of #160/#167 | — | Post-go-live burn-down, lowest yield |
| — | #105 (~2026-08-12, needs a week of logs), #203 (needs an operator answer) | — | Not schedulable |

### The two open pull requests

**PR #238 `fix/222-landing-mobile-density` — RESCOPE, do not merge, do not simply close.**

```
compare main...fix/222-landing-mobile-density
  ahead_by=14  behind_by=14  files_changed=51  status=diverged
  mergeable=false  mergeable_state=dirty
```

- **50 of its 51 files have moved on main** since its merge base `3032282`. Only the new
  spec file has not.
- Its non-#222 payload already landed by other routes — `store_reconnect.py`,
  `run_with_deadline.py`, `provider-notice-coverage.spec.ts` all verified present on main.
- **`Tests` and `E2E` never ran on any of its three head SHAs.** Its four new e2e specs have
  never been executed by CI. (Cause UNVERIFIED — both workflows declare
  `pull_request: branches: [main]` with no path filter on that branch.)
- Its own body is honest about why it is held. Re-measured against today's main by
  injecting its exact CSS at runtime: survives at 390×664/16px **by 4px**, and fails at
  375×667 (**+37**), 360×640 (**+64**), 390×664 @18px root font (**+90**). *An 18px font
  setting alone breaks it.*

Extract its **two confirmed-valuable findings** — the one-line trail-panel occlusion fix
and the density block — into a fresh branch off `dfc0419`. Then close #238 as superseded.

**PR #243 `codex/brand-readiness-2026-08-03` — REVIVE and merge.**

```
compare main...codex/brand-readiness-2026-08-03
  ahead_by=1  behind_by=14  files_changed=2  status=diverged
  mergeable=MERGEABLE  mergeStateStatus=BEHIND
  12 checks, ALL SUCCESS (including e2e axe + parity and pytest 3.12)
```

`README.md` (+22/−20) and a new `docs/assets/social-preview.jpg`. Neither file has moved on
main → zero conflict. Its `quorum.stackclimb.com` link verified live (200, same
`build_sha`). Only action needed: update branch, merge.

**The two PRs' file sets are disjoint** — #243 can merge today without touching #238 or
#222. **#222 ↔ #238 collide totally** (same CSS block), so new #222 work must start from
`app.css:5633-5651` on `dfc0419`, not from the #238 branch.

---

## 5. The critical path to go-live

```
PR 0  merge #243        free, green, improves money honesty
PR 1  money truth       #255 + #256 + #216 + the race   ← the long pole
PR 2  landing mobile    #222 + occlusion                ← file-disjoint from PR 1
PR 3  close #238        bookkeeping
```

PR 1 and PR 2 touch disjoint source sets (`costs.py`/`feedback_store.py`/`query_runs.py`
vs `app.css`), so they can be *built* in parallel worktrees — but rule 17 still means one
**merges** before the other starts. PR 1 also touches `app.js`/`workspace.html` for the
copy fix; if PR 2 lands first, PR 1 rebases onto it.

---

## 6. Per-PR risk notes

### PR 1 — money truth. Highest risk in the plan.

**The obvious fix is pre-refuted, and the experiment was re-run rather than trusted.**
Swapping the daily rail's addend from `estimated` to `bound` in a scratchpad copy of the
tree (`git archive HEAD | tar -x`):

```
FAILED ...::test_high_cost_query_requires_confirmation_before_creation
FAILED ...::test_high_cost_query_accepts_matching_confirmation_token
FAILED ...::test_gate_approval_is_honoured_by_the_create_that_follows
FAILED ...::test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for
4 failed, 17 passed

E  AssertionError: assert 'COST_LIMIT_EXCEEDED' == 'COST_CONFIRMATION_REQUIRED'
```

**Four tests go red, not the two the comment at `costs.py:678-685` names.** The
confirmation band is converted into a hard block. The ladder
(`SOFT 0.15 < DAILY 0.20 < HARD 0.25`, at `costs.py:44,45,112`) is load-bearing on itself.
**Do not key the daily rail off `max_cost_usd`.**

**What is *not* foreclosed:** that comment rules out swapping the *addend*. A post-hoc
**reconciliation event** carrying the measured delta is untouched by it. That is the design
to pursue.

**Rule 16e — the failure modes, enumerated up front so they are not discovered one defect
at a time (the last spend-cap work went five review rounds for exactly that reason):**

1. Read-modify-write race — **demonstrated**, 5.07× at 32 threads.
2. Estimate/actual drift — **measured**, 1.004×–2.43×, worst for short queries.
3. No idempotency key on the charge — the payload carries `query_run_id`, but nothing
   enforces one billing event per run at write time. F-01's double-bill was fixed by
   call-site discipline (a `preview=True` flag), not a constraint. A retried POST bills twice.
4. Unpriced subsystem — the judge is billed but absent from the estimate (proven).
5. Fail-open — `daily_cap_fail_closed` defaults `False` (`config.py:494`); an untrustworthy
   ledger logs and proceeds (ADR-0004).
6. Lost writes are counted, not prevented — `feedback_lost_billed_writes` exposes them;
   nothing replays them.

**ADR-0002 governs the storage design** (single connection, one `RLock`,
`journal_mode=DELETE`, totals recomputed by full scan). Read it before designing the
reconciliation write. **Rule 16d: this PR needs an ADR.** Decide label-vs-figure explicitly
and record it — a fix that changes *which figure is approved* spills the UI change into the
ledger.

### PR 2 — landing mobile

- **Do not resurrect PR #238's blocking fold assertion.** 4px of slack plus a
  `fonts.googleapis.com` dependency in a blocking lane is exactly the gate this repo has
  learned not to add; a font-CDN outage would red a merge gate for a reason unrelated to
  any diff.
- **Assert the hit-test, not `toBeInViewport`.** #238 proved the latter is structurally
  blind to paint order — which is how the occlusion bug survived in the first place.
- **Rules 13d/13e:** do not grow `goldenCompletedResp()`, and never `--update-snapshots`.
  The visual lane fails 8/8 on macOS on clean `main` and that is not a regression.

### PR 5 — deploy signal

The *effect* is measured 12/12; the *cause* is **UNVERIFIED**. The settling experiment is a
deliberate `workflow_dispatch` of E2E alone on main with CI/Tests untouched — that is a
workflow run, so it needs explicit approval.

### Anything in PR 6+

Before adding a gate, measure its yield against real defect history: **0 of 16** `src/`
defects caught by an automated check; **10 of 16** by adversarial review.

---

## 7. Explicitly NOT in scope for go-live, and why that is safe

- **OQ-009, OQ-011, OQ-013, OQ-014** — retention, high-stakes blocking, eval sampling,
  provider data-processing terms. Product/policy decisions only the owner can make. They
  gate *claims*, not function. **OQ-011 becomes binding** if the definition ever moves from
  "no LIVE user-facing defect" to "public announcement".
- **The eight gate-machinery issues** — developer confidence, not user experience, and the
  lowest measured yield of any activity here.
- **#105 and #203** — blocked on elapsed time and an operator answer. Neither costs live
  money; #105's current direction is the deliberately safe one (overstating uncertainty on
  a run already labelled `estimated`).
- **#216 / #258 as *money* risks** — $0/day while `judge_enabled: false`. **But #258 must
  land before the judge is ever switched on**, because without it the operator cannot tell
  a paid failure from a paid decline. Today those two states are byte-identical in every
  user-visible field while differing by a real charge.
- **The four accepted markdown gaps in ADR-0015** — §7 (`:257`, `:265`) and §4 (`:127`,
  `:134`). **Three of the four are correct-by-specification** (CommonMark / GFM;
  `markdown-corpus.spec.ts` already marks one `test.fail()` so it reds the day it is
  fixed). Only *"a rejected link leaves its raw `[text](url)` on screen"* is a genuine
  latent risk — the blocking rendering gate's own `](url)` pattern would match it if a
  future fixture ever seeds a rejected link.

---

## 8. Wall-clock cost

Gate timings are **inherited from the prior session's measurements, not re-measured here**
— re-running a 45-minute gate purely to time it was not worth the session.

- `make diff-cover` — **~45 min** · full `pytest` — ~1m45s · e2e invariants lane — ~4 min
  alone, **~40 min if anything heavy runs concurrently** · merge → deploy — ~15 min.
- Run `pytest` and `diff-cover` **serially** (rules 15/15a), and **commit before trusting
  diff-cover** or it attributes pre-existing untouched lines to your diff.

**One PR's gate-and-merge overhead is ~1.5–2 hours of wall clock regardless of diff size.**
The four critical-path PRs ≈ **6–8 hours of gates alone**, plus build time. PR 1 is the
only large one.

### Two traps that will otherwise cost an hour

1. **`e2e/tests/review/` currently holds 7 files** (verified by `ls`). It is gitignored, so
   `tests/unit/test_no_orphaned_e2e_specs.py` — which enumerates with `rglob`, the
   filesystem — reports **7 phantom failures locally that are green in CI**. Before blaming
   your diff for a red `test_no_orphaned_e2e_specs`, run `ls e2e/tests/review/`.
2. **A fresh worktree's `uv sync` picks Python 3.14**, where a `sentry_sdk` call raises
   `AttributeError: '_NoOpThread' object has no attribute 'is_alive'` — which reads as a
   product defect and is not. Pin with `uv venv --python 3.12`; the required context is
   `pytest (Python 3.12)`.

---

## 9. What "done" means, per PR

Rule 18/18a, in this order, every time:

1. **Local gates green** — re-derive the required contexts, do not trust any table:
   ```bash
   gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
   uv sync --all-extras          # NOT --extra dev: schemathesis lives in `quality`
   make quality && make validate
   make diff-cover DIFF_BASE=origin/main   # AFTER committing
   make api-contract && make openapi-check && make security-scan
   lsof -ti tcp:18085 | xargs -r kill -9
   cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
     npx playwright test <spec> --project=chromium --workers=1 --retries=0
   ```
2. **Adversarial review — two lenses, READ-ONLY**, told IN CAPITALS not to write, edit,
   `git checkout`, `git stash` or `sed -i`. One lens must audit the diff's **prose**: for
   every number, superlative and causal claim in comments, commit body and PR description,
   name the command that produces it — or mark it UNVERIFIED (rule 11a).
3. **Squash-merge with an explicit subject and body** (17c).
4. **Verify the deploy** — resolve the **newest** run by `createdAt` (a merge produces
   several; older ones are `cancelled` by concurrency dedupe), read its Deploy **JOB**
   conclusion rather than the run rollup, and confirm `/status.build_sha` equals the merged
   SHA.
5. **Clean up** — `git branch -f main origin/main`, delete the branch local and remote,
   remove the worktree.

### Per-PR acceptance

- **PR 1** — a test that books an estimate, completes a run, and asserts the ledger reflects
  the **measured actual**; red on today's code. A **cardinality** assertion (rule 6b): how
  many billing records, not merely that billing happened. A concurrency test reproducing
  the 5.07× overshoot. And a regression proof that the ladder still holds — re-run the
  four-test mutation above and show they stay green.
- **PR 2** — a hit-test at 390×664 returning `#landing-run`, not `OFF-SCREEN` and not
  `div.session-trail-head`. Prove RED then GREEN by reverting the CSS.
- **PR 4** — a test distinguishing "judge ran and declined" from "judge ran and failed";
  red on today's code, where those two states are indistinguishable to a user while
  differing by $0.0109.

Every test ships with one line naming the change that turns it red, proven by mutation:
`cp` the file aside, mutate, restore from the copy, confirm with `diff -q`.
**Never `git checkout <file>`** — it discards uncommitted work.

---

## Appendix — inherited claims, checked

| Claim from the handoff | Verdict |
|---|---|
| Section 0 state of the world (SHAs, 18 issues, 2 PRs, no worktrees, spend) | **All reproduced exactly** |
| ADR-0015 §7 records two accepted leftovers | **True** — and the ADR records **four**; the handoff missed §4's two |
| #255 and #256 both name `costs.py` | True |
| #258 and #216 belong with them (flagged as a guess) | **#216 yes** — strict subset, verified. **#258 no** — separate concern, separate files |
| "#105 and #203 are a pair on `providers.py`" (flagged already-refuted) | **Refutation confirmed.** #203 = `readiness.py:291`; #105 = `providers.py:1592`; zero shared files |
| The `costs.py:679-685` pre-refutation comment | **True**, at `:678-685`. Re-ran the experiment: **4 tests red, not 2** |
| `DAILY_CAP_USD` recorded at `costs.py:84` | **FALSE** — `:84` is inside a comment block; the constant is at `:112` |
| #245's owner comment calling the issue "stale" | **Wrong** — the 12/12 measurement shows claim (a) is live today |
| #256's "2.3×" ratio | **True but understated** — it is structural, and worst (2.4×) for the shortest queries |
| #143 "the equivalence holds today, it only needs pinning" | **FALSE** — 75 of 80 commits mismatch; the drift already happened |
| #224 "Not live: no current doc uses the shape" | **FALSE** — 2 lines in `docs/analysis/03-enforcement-machinery.md` carry it today |
| #146 "34 of 354 globs" | **35 of 388** — nested count unchanged at 11; denominator grew |
| #160 "11 of 14 enums unpinned" | **10 of 15** — three gained pins as a side effect of #247 |
| #226 "20 vacuous specs across 8 files" | **13 across 5** — seven vanished as collateral from unrelated PRs |
| #167 "3 vacuous guards" | All three fixed — **but a fourth is live**, 30 lines below one of them |
| `defect-discovery-audit.md`: 0 of 16 / 10 of 16 | **Both exact.** The one gate catch was test-vs-code drift, not a product defect |
