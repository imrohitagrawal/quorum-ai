# 2026-07-30 — the whole open backlog, triaged by execution

**Every verdict below was settled by running something.** The command and its output are in the
table; the long-form evidence, including the probe scripts' verbatim stdout, is in the per-issue
records this document was built from. Where a thing could not be settled for $0, it says so and
names the check.

**Anchor:** `main` at `4749aa5`, production `build_sha` `4749aa5` (they match). Suite measured green
BEFORE triage began: **1905 passed, 10 skipped, coverage 93.35%** against a 88% floor, plus all ten
`make validate` gates. So no red reported here is pre-existing.

## 1. The denominator

**42 open, 42 triaged, 0 unclassified.**

| Verdict | Count |
|---|---:|
| REAL | 32 |
| PARTIALLY-REAL | 6 |
| ALREADY-FIXED | 3 |
| DUPLICATE-OF | 1 |
| STALE | 0 |
| REFUTED | 0 |
| UNVERIFIABLE-FREE | 0 |

### The prompt's central premise did not hold, and that is the most important finding here

The brief predicted *"roughly half of what a written claim asserts does not survive contact with the
code"* and told me to expect about half these issues to be wrong. **Measured: 4 of 42 (9.5%) looked
closeable, not ~21 — and after a third pass, `0 of 42` are safe to close outright.** See §3: two are
CLOSE-WITH-CAVEAT conditional on filing a follow-up, three must stay open.

**The three passes asked progressively harder questions, and each overturned the one before:**
1. *Is the defect real?* → 38 of 42 real.
2. *Would a closing verdict survive an adversary?* → all 4 upheld.
3. *Are the issue's own acceptance criteria met?* → **most of the close list collapsed**, and two live
   production defects fell out of the gap (§3a).

The lesson is not that passes 1 and 2 were sloppy — both were rigorous and their findings stand. It is
that **"the defect is gone" and "the issue is done" are different claims**, and only the second is
grounds to close.

The ~50% decay figure is real but was measured on a **different population** — claims inherited from
*handoff documents*, which `AGENTS.md` rule 11 is careful to describe as "a different and worse
population" than review findings. Filed issues in this repository are written with a reproduction
attached, and they hold up. **Do not carry the 50% expectation to filed issues again.**

The failure mode that actually showed up is the opposite one, and the adversarial pass is what caught
it: **6 of the 7 top findings were REAL but OVERSTATED.** Not one was refuted. The cost of believing
them as filed would have been mis-sequencing, not wasted work.

## 2. Verdict table

| # | Title | Verdict | Command that settled it | Decisive output |
|---|---|---|---|---|
| #62 | Deploy run reports success when the Deploy job is skipped | **REAL** | `gh run view 29896840556 --json conclusion,headSha,jobs --jq '{run_conclusion:.conclusion, sha:.headSha, jobs:[.jobs[]\\|{n` | {"jobs":[{"conclusion":"success","name":"Gate — require CI + Tests + E2E green for the SHA"},{"conclusion":"skipped","name":"Deplo |
| #63 | Practice: sequence slices to close live security risks first (Stage B before R | **ALREADY-FIXED** | `grep -in "security\\\|risk first\\\|sequenc" docs/59-backend-engineering-practices.md` | 68:- **Order work to close live risk first.** When sequencing independent slices, |
| #100 | No deployment-wide spend ceiling — the $0.20 cap is per-account, and accounts  | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python .../p100.py` | DAILY_CAP_USD = 0.20 |
| #103 | The nightly feedback-audit job has never audited production — it opens an empt | **PARTIALLY-REAL** | `gh run list --workflow=feedback-audit.yml --limit 60 --json conclusion --jq '[.[].conclusion]\\|group_by(.)\\|map({c:.[0],n:` | [{"c":"failure","n":37}] <- 37 of 37 runs listed, back to 2026-06-23, ALL failure |
| #104 | Two measured test flakes: provider_event_recorder unfiltered, and a non-hermet | **REAL** | `grep -n 'def list_events' -A 4 src/product_app/providers.py` | 344: def list_events(self) -> list[ProviderCallEvent]: |
| #105 | E1: 5xx is classified as possibly-billed on a premise with no evidence | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python <scratch>` | IMPORTING FROM: <repo>/src/product_app/providers.py |
| #106 | F-05 Layer 2: stop the spend inside debate/synthesis after a cancel | **REAL** | `grep -c "cancel\\\|should_stop" src/product_app/debate.py src/product_app/synthesis.py` | src/product_app/debate.py:0 |
| #110 | A BILLED Layer-B judge call is dispatched by the response that serves the run' | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python .../p110.py` | query_runs file: <repo>/src/product_app/query_runs.py |
| #112 | Credential probe runs once per process — a key drained or revoked mid-life kee | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python .../p112b.py # transport returns 200 once, then HTTPError 401` | probe calls after startup: 1 \\| verdict: ok |
| #113 | test_makefile_gate_integrity races on a fixed shared path — two concurrent pyt | **REAL** | `grep -n 'guard-good-xml\\|tmp_path\\|REPO_ROOT' tests/unit/test_makefile_gate_integrity.py` | 35:REPO_ROOT = Path(__file__).resolve().parents[2] |
| #115 | #demo-mode-banner is dead markup, and a blocking gate certifies it while invis | **PARTIALLY-REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python <scratch>` | GET /ui -> 200 107771 bytes |
| #116 | Readiness banner takes 48% of a mobile viewport and pushes the landing hero be | **PARTIALLY-REAL** | `PYTHONDONTWRITEBYTECODE=1 python3 /private/tmp/.../ui-surfaces/banner_height.py` | viewport = 390x664 |
| #117 | Readiness banner flashes and shifts layout when the page-load seed disagrees w | **REAL** | `node /private/tmp/.../ui-surfaces/flash.js` | extracted app.js lines 553-669 verbatim (117 lines) |
| #120 | Blockquote and inline-prose paths have no list handling (ordered-marker gate i | **PARTIALLY-REAL** | `node /private/tmp/.../ui-surfaces/fmt.js` | ### formatAnswerText("> Steps:\n> 1. do this") |
| #122 | Decide the spend-cap policy when the ledger is known stale (follow-up to #109) | **REAL** | `grep -inc "lost_billed_writes\\\|write_health\\\|degraded" src/product_app/costs.py ; grep -nc "daily_spend_for" src/product` | === does costs.py consult the stale-ledger signal? (positive control: daily_spend_for) === |
| #123 | feedback_store has no reconnect path: a recovered volume still needs a process | **REAL** | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .../probe123.py` | SANITY importing from: <repo>/src/product_app/__init__.py |
| #124 | Only 1 of the 9 provider notices has browser-level coverage (follow-up to #114 | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python - <<'PY'` | providers.py resolved to: <repo>/src/product_app/providers.py |
| #126 | Session trail can never hold more than one entry — and its blocking gate enfor | **REAL** | `grep -n "SESSION_TRAIL_CAP\\\|clearSessionTrail\\\|appendSessionTrailEntry\\\|restoreTrailRun" src/product_app/static/app.js` | 4394: const SESSION_TRAIL_CAP = 10; |
| #127 | 42 e2e tests run in no CI workflow | **REAL** | `cd <repo> && grep -rn "workspace.spec\\\|accessibility.spec\\\|api-mocking" .github/workflow` | NO MATCH |
| #128 | Screen and export disagree on provenance for a simulated synthesis | **REAL** | `node <scratch>` | EXPORT MAP SOURCE: |
| #129 | Stale visual baselines are the only thing blocking PR #96 from production | **ALREADY-FIXED** | `gh pr view 96 --json number,state,mergedAt,title --jq . ; git log --oneline -2 -- e2e/tests/invariants/visual-snapshots.` | {"headRefName":"feat/ui-pr1-quickfixes","mergeStateStatus":"UNKNOWN","mergedAt":"2026-07-28T16:15:05Z","number":96,"state":"MERGED |
| #134 | Teach 'make handoff' to print live state, so no document has to carry it | **REAL** | `wc -l scripts/session_handoff.py ; grep -nE "build_sha\\|/status\\|pytest\\|collected\\|diff-cover\\|coverage\\|issue\\|origin/main\\|re` |  134 scripts/session_handoff.py |
| #137 | TRIGGER-GATED: measure p90 mutation runtime on the CI runner | **REAL** | `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'` | validate-and-test |
| #138 | TRIGGER-GATED: survey the risk-based testing literature before any criticality | **REAL** | `grep -rln "criticality" docs/ *.md .github/` | docs/metrics/mutation-gate-study.md |
| #141 | Doc-honesty gate has a comma-shaped hole: '(`gate`, blocking …)' is never chec | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python -c 'import sys;sys.path.insert(0,"tests");import test_doc_gate_consistency as m;` | module file on disk: <repo>/tests/test_doc_gate_consistency.py |
| #142 | report() misclassifies mutmut exit codes; the no_tests guard is bypassed by ex | **REAL** | `cd $SCRATCH/m142 && printf 'include <repo>/Makefile\nemit:\n\t@printf "%%s" "$$MUTMUT_SC` | === exit_code=5 === |
| #143 | Nothing pins replay_mutation_scope.py ≡ the Makefile's MUTMUT_SCOPE_PY | **PARTIALLY-REAL** | `git grep -ln MUTMUT_SCOPE_PY # -> Makefile, 2 prompts, scripts/replay_mutation_scope.py, 3 test files (none compares t` | # (2) mutation of the real gate's scope predicate: |
| #145 | Risk-constant pin detector: no reachability check, rejects approx/containers,  | **REAL** | `git archive HEAD \\| tar -x -C $SCRATCH/copy145` | === STEP 1: delete the real pin -> expect RED === |
| #146 | #136 is reduced, not closed: 34 of 354 scoped globs still match zero mutants | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python - # (probe: mutate_file_contents() per src/product_app/*.py for the true mutan` | modules: 23 total real mutants: 9369 |
| #148 | #131 guard: blind to expect.soft, toBeHidden/toBeEmpty, and beforeEach partner | **REAL** | `cd <repo>/e2e && node <scratch>/nag/probe.mjs # imports checkSource() from e2e/tools/c` | REPORTED POSITIVE CONTROL: plain expect(x).toHaveCount(0) -> toHaveCount |
| #151 | The 0.0008 fallback price is underived, under-charges one shipped model, and t | **PARTIALLY-REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python .../p151.py # floor vs every shipped model, both directions` | FLOOR in : 0.0008 |
| #155 | High-stakes acknowledgement is bypassable via context — and the obvious fix 42 | **REAL** | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .../probe155.py` | A) query_text hostile -> 422 {"detail": {"code": "VALIDATION_ERROR", "message": "Required safety acknowledgements are missing.", " |
| #156 | WP-G2 leftovers: surviving mutations in the context-carry tests, and a cost-la | **REAL** | `python -m pytest tests/unit/test_context_carry.py::test_the_estimate_body_carries_every_cost_affecting_create_field -q -` | DIRECTION A: added cost-affecting field extra_rounds to QueryRunCreateRequest ONLY |
| #158 | The repaired mutation gate aborts before scoring on ANY PR that touches src/ P | **ALREADY-FIXED** | `git log --oneline --diff-filter=A -- tests/repo_root.py` | 024af24 fix(ci): repair the mutation gate, then make every blocking gate prove it measured (#164) |
| #160 | 11 of 14 production enums have no exhaustive pin — adding a member goes unnoti | **REAL** | `python3 - <<'EOF' # ast.walk over src/product_app/*.py collecting ClassDef with an Enum base` | TOTAL ENUMS: 14 |
| #161 | The F-05 test hardcodes 5 of the 6 terminal statuses — BLOCKED_BY_COST is neve | **REAL** | `grep -n 'TERMINAL_STATUSES = frozenset' -A 10 src/product_app/query_runs.py` | TERMINAL_STATUSES = frozenset( |
| #162 | Nine more gates can finish having measured nothing (the ones this PR did not f | **DUPLICATE-OF #166** | `python3 -c "...count top-level jobs per workflow..." # 21 jobs` | TOTAL top-level jobs: 21 |
| #163 | #156 item 2 confirmed live: the consumer-side synthesis cap has no test, and t | **REAL** | `python -m pytest tests/unit/test_context_carry.py tests/unit/test_synthesis.py -q --no-cov -p no:randomly` | MUTATED: consumer-side cap removed (max_chars=10**9) |
| #165 | Leftovers at the 2-round review cap on PR #164 (gate liveness floors) | **REAL** | `python3 scripts/check_diff_cover_measured.py --base base # with the json report absent / {} / null / malformed / {"tot` | --- case A: json report MISSING --- |
| #166 | WORK PACKAGE: finish gate liveness — 6 gates can still report a status having  | **REAL** | `uv run python -c "import sys; sys.path.insert(0,'scripts'); from error_rate_probe import exit_code_for; [print(o, exit_c` | alert -> exit 1 |
| #167 | Nothing proves a GUARD test bites — and mutating tests/ is measured to be the  | **REAL** | `python3 <scratch>/scope.py scope 024af24 80 # negative case: base..HEAD changed only tests/ + docs/ + app.js` | --- run scope: base=024af24 (tests/docs only) --- |
| #171 | Simulated answers are substituted per model and fed to debate, synthesis, agre | **REAL** | `PYTHONDONTWRITEBYTECODE=1 uv run python <scratch>` | IMPORTING FROM: <repo>/src/product_app/providers.py |

## 3. The close list — REVISED after a third pass. Nothing here is safe to close outright.

**I have closed nothing.** The first two passes asked *"is the defect gone?"* and answered it well. A
third pass asked the different question — **"are the issue's own acceptance criteria met?"** — by
executing each criterion bullet by bullet. **It overturned most of this list.**

**The two questions are not the same, and the gap between them is where a live defect hides.** Two new
production defects were found in that gap, both listed in §3a.

| # | Was | Now | What the third pass executed |
|---|---|---|---|
| **#129** | ALREADY-FIXED | **CLOSE-WITH-CAVEAT** | 4 of 5 bullets met. **Bullet 2 — "review each new/changed PNG" — was NOT done.** `94fc256` is a `github-actions[bot]` commit whose message is hardcoded in `seed-visual-baselines.yml` and marked `[skip ci]`; `gh pr view 96` returns **0 comments, 0 reviews**; no file records anyone accepting the 8 PNGs. It was a mechanical reseed. The repo's own procedure says *"a baseline reseed is not evidence of correctness; it is a record of what a human accepted."* **A green gate is the one piece of evidence that can never tell a reviewed baseline from an unreviewed one — a reseed makes it green by construction.** |
| **#63** | ALREADY-FIXED | **CLOSE-WITH-CAVEAT** | Both doc bullets genuinely met, and the pytest egress guard **proven to bite** by mutation (removing `conftest.py:38` goes red; layer 2 takes 75s instead of 0.09s because the connect reaches the real network). But the issue's **concrete case has two surfaces and only one is closed** — see §3a. |
| **#158** | ALREADY-FIXED | **KEEP-OPEN** | The code fix is confirmed *more* strongly than before (real mutmut output, 9369 mutants, exact `514` reproduction). But the issue's second acceptance sentence is explicitly **about CI, not a local run**: *"re-run against a `src/`-touching PR and **open the log to confirm it printed a score**."* Measured: **no PR since `024af24` has touched `src/*.py`** — #173/#172/#170/#169 all zero (#172 touched `src/` but only `app.css` and `app.js`), and all four post-fix mutation jobs print `NO SCORE WAS PRODUCED`. **The repo's own study, shipped in the same commit as the fix, says at line 418: *"proven LOCALLY. It has not yet been proven in CI."*** An ALREADY-FIXED verdict contradicts the evidence file the fix itself updated. |
| **#162** | DUPLICATE-OF #166 | **KEEP-OPEN** | The earlier justification — *"#166 carries all six gates"* — is **circular**: it measures #166's coverage against #166's own count of six, while #162 lists **seven**. Diffing the lists, #166's table has 6 and carries the 7th (`visual-snapshots`) only in a trailing **"Also:"** paragraph — and its Definition of Done reads *"Each of the **six**"*. So **the only BLOCKING gate in the set is the one item with no done-criterion anywhere.** Separately: **0 of 7 holes are fixed** at `4749aa5`, #165 §4 still points at #162 (closing it dangles a live reference), and the author's own condition — *"keeping this open until #166 is picked up"* — is **unmet**: #166 is OPEN, unassigned, no branch, no PR. |
| **#163** | close into #156 | **KEEP-OPEN** | Never a "done" claim — it is a **live, measured defect** and a dedupe of a live defect is bookkeeping, not a fix. The mutation still survives at `4749aa5`, across **all seven** test files touching `_user_prompt`/`prior_synthesis` (145 passed; positive control `max_chars=10` → 13 failed). #156 names item 2 verbatim, so the headline survives a merge — but **four sub-claims exist only in #163**, including the trap that the nearest existing test (`test_context_carry.py:266`) *asserts the bound against the constant that defines it*. **Amend #156 first, then close #163 — in that order.** |

### Status update — the two blocking amendments have landed (2026-07-30)

**#166 and #156 were amended**, so the scope that closing #162 and #163 would have discarded is now
carried by their successors. Both were drafted, then **fact-checked by an adversarial pass that blocked
publication** and forced four corrections — one of them a *false* claim the drafter had introduced by
hardening #162's hedged wording ("the baselines are Linux-only, seeded in CI") into an absolute
("the `*-linux.png` baselines exist only there"), which one `git ls-files` refutes: **16 committed
baseline PNGs, 8 linux and 8 darwin**, sitting in the tree on a macOS machine. Two more were overstated
citations inherited from the existing body — the stranded-merges incident is recorded in
`docs/103-incident-learnings.md`, not `mutation-gate-study.md` §3.3 (which is titled "Cost" and carries
no dates), and "the five floors already shipped are all file reads" is wrong because `gate-min-collected`
runs `uv run pytest --collect-only`, a collection pass.

- **#166** — `visual-snapshots` promoted from a trailing "Also:" paragraph into the table as a seventh
  row; Definition of done now reads "each of the **seven**"; title corrected to seven. **No floor value
  was invented** — its count has never been measured, and picking a number would be the exact
  fabrication that work package exists to remove.
- **#156** — absorbed #163's four unique sub-claims, with the mutation independently re-measured in a
  throwaway copy (55 / 55 / 145 passed; positive control `max_chars=10` → 13 failed, 132 passed).

**Still outstanding before #162 can be closed:** `#165 §4` says verbatim *"Tracked separately in #162"*
and still needs repointing at #166, or closing #162 leaves a live issue citing a dead one. **Nothing was
closed — #162, #163, #166 and #156 are all still OPEN.**

**#137 and #138 — confirmed parked, do not close.** Neither trigger has fired for its headline
condition: `mutation-baseline` still carries `continue-on-error: true` (`ci.yml:271`) and names no
required context. But one thing needs an operator call: **a criticality-scoped BLOCKING gate already
shipped without #138's survey** — `tests/unit/test_risk_constant_pins.py` applies a literal-pin
requirement to seven money/auth/config modules and nothing else, merged in PR #144 **two hours after
#138 was filed**, and it runs inside the required `pytest (Python 3.12)` context. Whether that counts
as the trigger is a judgement, not a measurement. Also: #137 got **more** load-bearing this week, not
less — its sibling half #136 is now closed and fixed, so #137 plus a fresh yield census are the last
two things standing between the mutation gate and a promotion argument.

## 3a. Two live defects found only because the third pass executed the criteria

Neither is named by any open issue. Both were re-verified independently before being written here.

**1. Production tells users a model that is not in the panel, and omits the one that is.** All four
degraded/offline notices say the answers are *"not generated by GPT, Claude, Gemini, or **Deepseek**"* —
but slot 4 has been NVIDIA Nemotron since PR #96 itself (`model_slots.py:67`, comment
`# slot 4 — NVIDIA (replaces deepseek)`). Call sites: `app.js:613`, `:627`, `:638`, `:4579`. The string
`Nemotron` appears **0 times** in `app.js` (positive control for the grep). **Confirmed serving from
production:** `curl -s https://quorum.stackclimb.com/static/app.js | grep -o "not generated by GPT,
Claude, Gemini, or Deepseek"` matches. So the user is told which four vendors did not produce the text,
one of the four named is absent from the panel, and the one that is actually there goes unnamed. Four
one-line string fixes. **This is exactly the defect the skipped visual review existed to catch** — it is
legible in `transcript-full-chromium-linux.png`, one of the 8 baselines nobody reviewed.

**2. A local e2e run can make paid provider calls.** `e2e/playwright.config.ts:32` boots the
`webServer` with `UV_CACHE_DIR`, `PYTHONPATH` and `SENTRY_DSN` — but **not**
`OPENROUTER_LIVE_EXECUTION_ENABLED` (`grep -c OPENROUTER` → **0**; positive control: `SENTRY_DSN` is set
on that same line). CI pins it false at `e2e.yml:74`; **the local lane never got it.** Loading `Settings`
with that webServer's exact environment prints `live_execution_enabled = True, api_key_present = True`.
Worse, `real-integration-smoke.spec.ts:11` **asserts the opposite in a comment** —
`(OPENROUTER_LIVE_EXECUTION_ENABLED=false — free, deterministic, no live LLM)` — which is why nobody
looked. This is the second surface of #63's own concrete case; Stage B closed the pytest one and left
this one. It needs a **structural** assertion on the config, not a substring on a comment.

## 4. What the adversarial pass changed — read this before using the ranking

Seven top findings were re-attacked by an agent told to assume each was overstated. **All seven
survived. Six were narrowed.** Two facts nobody had checked came out of it, and both change the plan:

**New fact 1 — `TAVILY_API_KEY` is deployed in production.** `providers.py:446` dispatches a paid
Tavily search on the *normal live path* whenever a searching slot's answer comes back without
citations, and `costs.py` has **zero** Tavily references (positive control: 6 openrouter references).
This is **un-metered paid egress, armed today**. Both grouping lenses had scheduled the Tavily piece
**last** inside a large ceiling work package. That inverts the correct order.

**New fact 2 — production has served exactly one query-run since boot** (`/metrics`: 1 `POST
/v1/query-runs`, against 106 `/ready` hits). So #100's "unbounded — accounts an attacker mints ×
$0.20" is a **capability statement with no observed traffic behind it**. The per-IP limiter is 30/min.
Real, worth fixing, but it is not on fire.

The six narrowings, each of which would otherwise have mis-ranked something:

| # | Claim as filed / grouped | What execution actually showed |
|---|---|---|
| **#171** | "every downstream trust computation filters on status only, **never** on `provider_path`" | **False as written.** `query_runs.py:2474-2488` *does* filter on `provider_path` to build `live_count`/`local_count`. A reviewer told "never" will grep, find the counter, and wrongly conclude the finding is stale. Correct: *run-level coverage, `summarize_agreement` and the debate prompt* filter on status only. Also, 2 of the 4 "corrupted numbers" are honest, and `app.js:2297` **does disclose** the run as degraded. The defect is *trust numbers computed over fabricated text on a disclosed-degraded run* — not a fake passed off as fully live. |
| **#122/#123** | "the control is **absent**", "total rather than partial", "silently" | A **second, independent rail** neither lens mentioned still bounds it: the in-memory cumulative guard (`costs.py:421-449`, `HARD_LIMIT_USD = $0.25`) **BLOCKED the account at $0.2226**. So it degrades from a durable $0.20/24h cap to an in-process $0.25 cap — not absent. Not silent either: `costs.py:559` logs at `_log.error` with Sentry live, and `/status` already serves all three health signals. |
| **#112** | "the instrument every money group needs" / "the cheapest instrument for pricing the money items" | **Refuted.** `_urlopen_key_probe` reads only the HTTP status of `GET /key` and never the body, so a 2xx proves the key **authenticates**, not that it has **credit**. No version of this fix, present or repaired, can answer "is this deployment able to spend money". Scheduling an S-effort slot expecting that answer would have wasted it. |
| **#110** | "4300 tokens per judged run"; dormancy *assumed* | 4300 is **arithmetic on two guesses** in the issue body. Measured on the shipped path: prompt = 3552 chars ≈ **888 tokens**, 512-token completion cap, and unbounded upward on a live run. Dormancy is now **measured** — `fly secrets list` shows five secrets and **neither judge variable is among them**. |
| **#151** | "under-charges by 25%"; trigger includes "operator selects a non-catalog model" | The **53.3% survived my attack** — priced on the production token mix the haiku shortfall is 44.0–56.3%, bracketing it, so the issue's own 25% is the wrong figure. But the trigger is **half refuted**: `_validate_model_id_list` (`model_slots.py:243`) rejects any non-catalog id, so only an upstream **delist/rename** reaches the floor — and that is **detected and surfaced** via `catalog_drift_ids` (production reads `[]`). Also the floor **over-charges the other three models by 2.7×–16×**, so "raise the floor" is not free. |
| **#106** | ranked above the cap groups on money | Counts are **calls, not dollars**. At ~$0.003/call the leak is **~$0.006 per pre-debate cancel, ~$0.013 pre-synthesis** — about a cent. Rank it on *unblocked + certain + cheap*, not on dollars. |

And one prior-document claim refuted outright: `docs/analysis/2026-07-30-backlog-triage.md:73` says
**"#171 absorbs #128 (same provenance disagreement)". It does not.** #171 is per-slot fabrication in
the provider layer; #128 is a UI label map missing a branch. Fixing #171 leaves #128 wrong, because
demo runs still produce a simulated synthesis.

## 5. The groups

Two independent lenses grouped the 42 — one by shared cause in the code, one by who gets hurt — and a
third agent adjudicated where they disagreed. **Where both landed on the same group independently,
that is signal and it is weighted up, not averaged away.** Those were: #122+#123, #116+#117, #165+#166,
#142+#143+#146, #113+#104, #160+#161.

A group is only a group if one sentence names the shared **cause**, and one reviewer can audit it as
**one concern**. Groups that failed either test were split.

| Group | Root cause, in one sentence | Closes | Order inside it |
|---|---|---|---|
| **A. A failed live slot is replaced by a fabricated answer** | `produce_initial_answer` falls through to a COMPLETED `LOCAL_SIMULATION` answer for any per-slot live failure (`providers.py:521-545`), and run-level coverage, `summarize_agreement` and the debate prompt all filter on status only. | #171 | Provider-layer decision (MISSING vs fabricated) first, then all four consumers **in the same diff** — each is only correct relative to the new shape. The debate-entry gate (`query_runs.py:1829-1846`, "any answer COMPLETED") must be re-decided here too, since a simulated answer satisfies it. Golden fixture and degraded-banner spec **last** — widening the fixture early reds a blocking lane. |
| **B. Paid Tavily egress is outside the cost model** | `providers.py:446` dispatches a billable Tavily search on the normal live path and `costs.py` has no Tavily line, so that spend is invisible to both the estimate and the cap. | part of #100 | Meter or disable first; the per-request price is the operator question. **Split out of #100 and taken first** — it is the only armed half. |
| **C. Cancellation does not stop the stages that spend** | Cancellation is a status flag polled only by the orchestrator's own gates; `debate.py` and `synthesis.py` take no stop signal, so once entered they run to completion and bill. | #106 | The parametrize table in `test_f05_terminal_status_not_overwritten.py` must go 2/1/4 → 0/0/0 **in the same commit** — it asserts equality, so it goes RED when the bug is fixed. The synthesis check must sit **inside each pooled worker**, and a stopped section must not return the templated fallback prose. |
| **D. The spend cap cannot tell a broken ledger from an empty one, and never repairs it** | The daily-cap branch gates only on `store is None`, so both ledger failure modes read as "$0 spent", and nothing ever re-opens the store. | #122, #123 | **Policy ruling first**, then the reconnect (off the request thread, built on #109's write-health counter), then the cap predicate. Two tests that pin today's semantics must be **rewritten, not deleted**. `run_history_store` has the same import-time shape (`main.py:381`) and must be fixed with it. |
| **E. The fallback price is an invented constant** | One constant stands in for per-model pricing, so it cannot be conservative for every shipped model at once, and the only tests on it pin the literal value rather than the property. | #151, cost half of #156 | The **FAQ line is XS and independent — take it alone first**; it is the only live user-facing half. The constant and #156's context split move the same CONFIRM/BLOCK rails and must be measured together. |
| **F. Two sources of truth for one provenance label** | The on-screen badge is a two-branch ternary with no "simulated" case while the export uses a four-entry label map. | #128 | One label map driving both surfaces. XS, unblocked. **Not absorbed by #171.** |
| **G. A refusal to deploy exits 0** | `scripts/deploy_gate.py` returns 0 on every path including `BLOCKED_FAILURE`, so a refusal is only a job output and GitHub scores the skipped Deploy job as a successful run. | #62 | One conditional non-zero exit. |
| **H. The credential verdict is a one-shot process global** | The key-auth verdict is computed once at startup and cached with no refresh, so a key **revoked** mid-life keeps `/ready` asserting live forever. | #112 | Pin the two existing invariants first or the suite stops being socket-free. **Scope it to revocation detection — it cannot detect drained credit.** |
| **I. A billable judge call has no cost line** | The judge call uses the same provider seam as debate and synthesis but has no `BillableStage`, no usage capture and no cost line. | #110 | Needs a catalog row for the judge model or #151's floor mis-prices it. Judge-OFF path must stay byte-identical and zero-I/O. |
| **J. Safety detection reads a different string than the prompt does** | High-stakes detection is keyed on `query_text` while two context fields reach provider prompts. | #155 | **Do not attempt the obvious fix** — measured to 422 every legitimate follow-up. |
| **K. The readiness banner has no render contract** | The banner is painted twice from two sources of truth into an unbounded box. | #116, #117 | One element, one CSS region, one 224-line spec. |
| **L. The nightly feedback audit has never audited anything** | The workflow invokes `product_app` as an installed module when nothing installs it, and never points `FEEDBACK_DB_PATH` at the volume. | #103 | **Decide delete-vs-repair first** — repairing it as written starts paying for nightly live model calls against an empty DB. |
| **M. Tests read state they do not own** | Two tests read shared mutable state scoped to the tree or process rather than the test. | #113, #104 | ~10 lines. Removes two reproduced false reds that slow every other group's verification. |
| **N. The session trail is a single-slot indicator, certified by a blocking gate** | `clearSessionTrail()` is called unconditionally at run creation (`app.js:6458`), so the cap, the dedupe and the newest-first loop are unreachable — and a required e2e check asserts the single slot. | #126 | Needs the product ruling (indicator vs real trail) before any code. |
| **O. Markdown lists exist on one render path only** | F-13 gave the dedicated list buffer to the paragraph path alone, so blockquote and inline surfaces keep `mdInline`'s per-line bullet rule. | #120 | Needs the block-vs-inline ruling for the four inline surfaces. |
| **P. Context-carry tests that cannot fail** | The tests assert clean-path outcomes against a hand-maintained exclusion list, so four mutations survive the **entire** suite. | #163 (→ fold into #156) | Four test additions, XS each. |
| **Q. Nothing asserts that a set of enum members is complete** | No test asserts a whole enum member set, and a test-local list retypes a production frozenset by hand. | #160, #161 | #161 is the mutation-proven instance of #160's property. |
| **R. Notice visibility is proven only for the notice the fixture seeds** | No parameterised (run shape → expected notice) drive over `PROVIDER_NOTICES`; arrival is proven for **1 of 9**. | #124 | Follows A — #171 rewrites what a missing slot says. |
| **S. 69 maintained e2e tests run in no workflow** | `e2e.yml` enumerates spec paths by hand, and the guard meant to catch an unenumerated spec sweeps **2 of 11** spec directories and asserts a **substring** against the workflow's raw text. | #127 | Widening `GATED_SPEC_DIRS` is XS; deciding which of the 69 to keep is the real work. |
| **T. Gate exit codes are decoupled from their denominators** | A gate's exit code does not depend on what it counted: four detect the unmeasured state, print it honestly, and exit 0 anyway. | #166, #165 | One work package, not eight. |
| **U. The mutation gate models mutmut from the outside, twice** | The gate re-derives mutmut's own facts from the AST and a sign test instead of from mutmut, in two copies that have already drifted apart. | #142, #143, #146 | One 175-line embedded program plus its drifted copy. |
| **V. The doc-honesty gate recognises a shape, not the property** | It matches a punctuation-terminated prose window, so a comma-shaped construction is never checked — **7 wrong "blocking" claims shipped through it**. | #141 | Kept **separate** from #148: one is a Python doc gate over prose, the other a Node AST linter over Playwright matchers. The shared "cause" is an analogy, not a mechanism. |
| **W. The e2e guard linter is blind to this repo's idioms** | Blind to `expect.soft`, `toBeHidden`/`toBeEmpty` and `beforeEach` partners. | #148 | — |

**Ungrouped, deliberately, with nothing invented to hold them:** #105 (a logging step, not a defect —
see the operator queue), #134 (an enhancement with no defect behind it), #145 and #167 (see below),
#137 and #138 (parked triggers).

**Two I will not rank, and say so rather than bury:**
- **#145** — one lens folded half of it into a PR it does not belong in and orphaned the reachability
  item; the other split it into two groups that close nothing. Neither produces an honest "this
  outranks the next" line. **Put it to the operator as close-or-own.**
- **#167** — its cheapest option was already measured and **declined** in `tests/code_text.py`, and its
  own operator question offers the honest close.

## 6. The ranking

Ordered by what can hurt. Reachable-today beats latent; effort breaks ties. **Readiness is not an
input, and neither is sunk cost** — that is the failure this repo recorded on 2026-07-30, when a
session ranked #171 top in writing and then spent itself on a half-built banner.

| # | Group | Why it outranks the next |
|---|---|---|
| 1 | **A** — #171 | The only production path from a live failure **is** the fabrication branch — `_post_messages` catches `HTTPError`, `URLError` and a catch-all and its own docstring says it never raises, while the only FAILED path is a test-only magic phrase gated to `LOCAL`. So this fires on any single slot timeout and corrupts the product's core output. |
| 2 | **B** — Tavily half of #100 | It is spending real money on the normal live path **right now** with no cost line, where everything below is either bounded, dormant, or needs a user to do something first. |
| 3 | **C** — #106 | The only money defect with **no operator decision in front of it**, proven by a passing equality assertion, and it ships a test that goes red when the bug is fixed — a rule violation sitting in the tree. |
| 4 | **D** — #123+#122 | A disarmed daily cap is real money, but it degrades to a measured $0.25 in-process rail and is already visible on `/status` and in Sentry, so it is bounded where #106 is unbounded per cancel. |
| 5 | **E** — #151 (FAQ line first) | The FAQ states a **5.33× wrong price to users today** at XS effort; the 44–56% under-charge behind it is real but arms only on an upstream delist, which `/ready` already flags. |
| 6 | **F** — #128 | XS and unblocked: the screen calls a template summary an "automated summary" where the export of the same run says no model was involved. Queue it behind nothing. |
| 7 | **G** — #62 | It protects every release that follows; it is this low only because production `build_sha` equals main's tip today. |
| 8 | **H** — #112 | Fix it for what it **actually** does — detect a key revoked mid-life. It unlocks nothing below it. |
| 9 | **I** — #110 | Measured **dormant** (`fly secrets list`: neither judge variable deployed). Real, uncapped and re-billable the moment judging is switched on — not before. |
| 10 | **J** — #155 | A reproduced safety bypass that still executes and bills, but unreachable from the shipped UI; it needs a hand-written API client. |
| 11–13 | **K**, **R**, **O** — #116+#117, #124, #120 | User-facing correctness with no money behind it. #115 and #124 must follow group A, which rewrites the copy they assert. |
| 14 | **L** — #103 | Removes a money **trap** rather than a defect: the wrong repair starts paying for a nightly live model call against an empty database. |
| 15 | **M** — #113+#104 | XS, and it removes two reproduced false reds that slow the verification of everything above. |
| 16+ | **N, S, Q, P**, then **T, U, V, W** | Gate machinery last, on this repo's own measurement: **0 of 16** real defects were ever caught by an automated check. Only **V** (#141 — 7 wrong "blocking" claims shipped through it) earns a PR on its own merit. |

### The uncomfortable note, re-derived rather than inherited

**13 of 42 open issues are gate machinery.** The route table in
`docs/metrics/defect-discovery-audit.md` shows **0 of 16** `src/` defects caught by an automated
check and **10 of 16** by adversarial review (its own caveats: 1 route UNKNOWN, 1 INFERRED at low
confidence). **A new gate is not a defence.** The recommendation stands: close or park the majority of
that tier behind one question — *does this gate prevent a regression we actually had?*

**One inherited number was wrong and is corrected here.** The brief says money defects are "~31% of
the traced defect history (5 of 16)". Counting the audit table's own commits by subsystem tag gives
**6 of 16 `fix(costs)` (37.5%)**, and 8 of 16 (50%) if the two `fix(ops)` spend-cap fixes count as
money. The "5 of 16" figure appears **nowhere in `docs/`** — only in two handoff prompt files
(`BACKLOG-TRIAGE-BY-EXECUTION-ULTRACODE-PROMPT.md:192`, `NEXT-SESSION-ULTRACODE-PROMPT.md:182`). It is
inherited and unsourced. Money is a **bigger** share than claimed, which strengthens this ranking.

## 7. The operator queue — decisions only a human can make

Batched into one checkpoint. **No guardrail number is invented below; where a value is needed and
unmeasured, it says so.**

| # | Question | Options |
|---|---|---|
| **#171** | When live execution is on and a model's call fails, what should the run show? | (A) report that slot **MISSING** and compute every number over answers received; (B) also refuse to run a debate below a minimum participant count — **that floor is unmeasured, so pick it deliberately or leave it unset**; (C) keep per-slot fabrication (closes #171 as WONTFIX). |
| **#100 / Tavily** | Should Tavily web-search spend count against the same ceiling, and at what assumed per-search price? | The $5/24h ceiling and "degrade to simulation" are **already decided** in the issue comment. Open: the Tavily price, and meter-vs-disable in the interim. |
| **#122** | When the cap's ledger is known stale, should `estimate` keep allowing? | (i) ALLOW + log — today's behaviour, defensible to ratify; (ii) fail closed; (iii) fail closed only after a failed re-open. **(iii) requires #123 first** — gating on `lost_billed_writes > 0` is permanently sticky, measured: the counter climbed 3→6 and never returned to zero after the volume was repaired. |
| **#151** | Raise the fallback floor to the derived max-across-shipped (in 0.001 / out 0.005)? | It makes every degraded-mode estimate higher and pushes more runs into CONFIRM/BLOCK — a guardrail-input change requiring ratification. **And it over-charges the other three models 2.7×–16×.** The FAQ fix is independent and needs no ruling. |
| **#155** | Is closing this bypass an accepted **breaking** API change? | A client already sending high-stakes wording in `context` gets 202 today and 422 after. (a) breaking now; (b) warn-then-enforce. **The obvious fix is measured worse than the bug.** |
| **#103** | The nightly audit has been red for **37 consecutive runs**. | (a) delete the job; (b) run it against the real volume; (c) keep it disabled. Repairing it as written audits an empty checkout-local DB **with live LLM calls enabled**. |
| **#126** | Is "This session" a current-run indicator or a real conversation trail? | (1) indicator — rename, delete `SESSION_TRAIL_CAP` and the dead branches, retitle the spec; (2) real trail — stop clearing on run creation. |
| **#120** | Should a list in provider text render as a real list on the four inline surfaces? | (a) convert those spans/cells to block containers; (b) keep inline and accept flattened lists. |
| **#105** | Land the shape-logging step now (log whether the 5xx body carried `error.metadata.provider_name`)? | Without it the classification stays an unevidenced premise. **The evidence does not exist yet** — the field is not logged today. |
| **#145** | Close it, or give it an owner? | Neither grouping lens could place it honestly. Three items of unequal size; only the reachability check deserves its own PR. |
| **#167** | Build the paired-mutation fixture runner, or accept human review and record it as a named gap? | Its cheaper option is already **measured and declined**. |
| **#163** | Close as part of #156, or keep separate? | It is item 2 of #156. Two numbers for one mutation caused a miscount once already. |
| **#166** | Four independent rulings on gate exit codes | e.g. flake-scan and perf-sample print UNMEASURED then exit 0 — fail the step and carry advisory-ness via job-level `continue-on-error`, or leave the exit code lying? |
| **`refs/archive/stash-0..3`** | Push or drop? | Four commits, **none an ancestor of `main`**, and `git ls-remote origin 'refs/archive/*'` returns **nothing** — they exist on this disk only. One disk failure decides it otherwise. |

## 8. What is genuinely unknown

Separating *settled by construction but never measured* from *measured*.

**Measured this session** (previously unknown): how many open issues are real — 38 of 42, with 4
closeable; #110's dormancy (`fly secrets list`); Tavily's armed status; production traffic volume
(1 query-run since boot); the fate of the archive stashes.

**Still unknown, with the exact command that would settle each:**

| Unknown | Settling check | Cost |
|---|---|---|
| **Whether production's OpenRouter key can actually spend.** `/ready` says `state: live`, but the probe reads only an HTTP status, never credit — and per #112 that verdict is at most `uptime_seconds` old. **No version of the #112 fix ever proves funding.** | Read the OpenRouter dashboard, or one funded run. | Operator access, or ~$0.03 for one run. |
| **Real latency at current token caps, and whether the 180s run deadline holds.** Extrapolated, never measured. | One funded live run, timed. | ~$0.03. |
| **Whether the e2e workflow-coverage guard has ever missed a spec in practice.** Known-broken by construction (substring match; `GATED_SPEC_DIRS` sweeps 2 of 11 dirs) — never measured for actual escapes. | Add a spec named only in `e2e.yml`'s comment block and confirm the guard passes. | $0. |
| **#122's "1024 refused requests flush the in-memory ring."** The issue's own comment labels it UNVERIFIED; I left it that way rather than repair it. | Drive 1024 refusals against the ring and read the counter. | $0. |
| **Browser-confirmed geometry for #116 (the "48% of a mobile viewport" claim) and the #117 flash.** Both were settled by CSS/JS arithmetic on the real on-disk bytes, not by a browser. | `cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test invariants/readiness-banner.spec.ts --project=chromium --workers=1 --retries=0` | $0 — **not run here**, because eight verifiers shared one working tree and port 18085 collides. |

## 9. What could not be verified for $0

**Nothing received an `UNVERIFIABLE-FREE` verdict** — every one of the 42 was settled hermetically,
using doubled transport seams rather than network calls. Two *sub-claims* inside otherwise-settled
issues need money, both listed in §8: whether the key has credit, and real latency under load. Each is
about **$0.03** for one live run, or free with operator dashboard access.

## 10. Method, and what I would not trust

- **8 read-only verifiers** over 42 issues, each required to run a command and paste verbatim output;
  a verdict with no output was void.
- **3 adversarial re-checkers** re-ran every issue-closing verdict from scratch. 4 of 4 upheld.
- **6 acceptance-criteria executors** (third pass) ran each close candidate's own done-criteria bullet
  by bullet. This is the pass that found the two defects in §3a, and it is the one worth repeating on
  any future close list. It also exceeded `AGENTS.md` rule 12's two-round cap — deliberately, at the
  operator's explicit request, recorded here rather than left implicit.
- **2 independent grouping lenses** plus **1 adjudicator** that also re-attacked the 7 top findings.
- **A known asymmetry in this method:** the 32 `REAL` verdicts were attacked only for the 7 that drive
  the ranking. **The other 25 have one lens each.** A wrong `REAL` wastes a work package; it does not
  bury a defect, which is why the effort went to the closing verdicts and the top of the ranking — but
  it is a real limit of this document, not a footnote.
- Two commands in the brief's own §3 do not work: `git branch -f main origin/main` fails when `main`
  is the checked-out branch, and `curl .../ready | jq -r '.state'` prints `null` because the field is
  `.live_readiness.state`. Both are recorded rather than silently repaired.
