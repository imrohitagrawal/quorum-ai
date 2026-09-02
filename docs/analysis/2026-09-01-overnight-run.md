# Overnight unattended run — 2026-09-01

Main orchestrator log. One entry per work package. The orchestrator never
writes code; each item is built end to end by a fresh sub-orchestrator and
then INDEPENDENTLY re-verified here from command output.

## Starting state (verified 2026-09-01)

```
git rev-parse HEAD          -> f81ffbb987aa13c2339f298a3a3bf536fef4ca34
git rev-parse origin/main   -> f81ffbb987aa13c2339f298a3a3bf536fef4ca34
/status.build_sha           -> f81ffbb987aa13c2339f298a3a3bf536fef4ca34
/status.live_execution      -> false
/status.judge_enabled       -> true
check_open_work.py --check  -> EXIT=0 (19 rows, 8 PENDING, 7 DONE, 15 needles, 4 unpinned)
gh issue list --state open  -> #402 #394 #290 #268 #105
git worktree list           -> main checkout only
```

All three of local `main`, `origin/main` and production `build_sha` agree.
`OPENROUTER_LIVE_EXECUTION_ENABLED` is false and stays false all night.

## Entries

### W18 — the paid call's base URL had no scheme guard — SHIPPED, VERIFIED IN PRODUCTION

- **PR #413**, squash-merged as `c15edbe7abdaa8f79cd35e7a3fad40bbd93881b8`. Closed no issue (W18 had none); `closingIssuesReferences` is `[]`, confirming the merge text closed nothing by accident.
- Fix: both credential-bearing call sites now build the endpoint through a new
  `credentialed_url.chat_completions_url` — **https anywhere, or http only to loopback** — which returns `None` (refuse, don't dial, report unbilled) otherwise. A *builder*, not a predicate, so a future call site cannot obtain the URL without the check.
- The brief's grep was **incomplete**, and the sub-orchestrator caught it: `feedback_audit._call_audit_model` reads `os.environ["OPENROUTER_API_BASE_URL"]` directly and sent the same key to the same endpoint. **Two unguarded sites, not one.** That second site also raised an uncaught `ValueError: unknown url type: '/chat/completions'` when the variable was unset, so its documented "returns None on any failure" was false.

**What the MAIN ORCHESTRATOR re-ran itself** (not taken from the sub-orchestrator's report):

| Check | Command | Result |
|---|---|---|
| Merge landed | `gh pr view 413 --json state,mergeCommit` | `MERGED`, `c15edbe7…` |
| Closed nothing | same, `closingIssuesReferences` | `[]` |
| Deploy **job** | enumerated all 4 `Deploy to Fly.io` runs for the SHA | 1 `skipped`, 2 `cancelled`, **run 33454794735 job = `success`** |
| Production | `curl /status` | `build_sha` = `c15edbe7…` **exact match**, `live_execution: false` |
| Board | `check_open_work.py --check` | EXIT=0, 21 rows, W18 **DONE** |
| Needle actually flips | `grep -c 'url=f"{settings.openrouter_api_base_url}/chat/completions"' src/product_app/providers.py` | **0** — the fix DELETED the pinned needle, so DONE is derived (`check_open_work.py:269`), not typed |
| Guard behaviour | drove `chat_completions_url` over 12 inputs | https ok; `http://` public → `None`; loopback http ok; `file:`/`ftp:`/userinfo/whitespace/empty → `None`; **not fooled by `http://127.0.0.1.evil.com`** |
| Tests bite | neutered the guard to `return url`, ran the guard suite, restored from a `cp` copy | **30 failed, 24 passed**; `diff -q` and `git status` confirm clean restore |
| Tree | `git worktree list`, `git branch -a` | worktree removed, branch gone local AND remote |

**Rule 19 note — this package closed one row and opened two.** `W21` (a redirect carries the key off the guarded base; `urlopen` follows redirects with `Authorization` intact) and `W22` (`_tavily_search` sends the Tavily key to a configured base with *no* scheme guard at all — demonstrated dialling `file:///etc/passwd/search` with the key attached). Both are measured credential exposures found by this package's own review fan. Recorded rather than hidden; neither was in scope tonight.

**Left as advisory debt, not fixed:** the advisory mutation gate is red and self-reports UNMEASURED (truncated at 141 of 401 mutants by its own deadline); survivors fell 82 → 38 with **zero in the new code** — all remaining ones sit in `feedback_audit._call_audit_model`, a CLI-only helper that had no prior tests and entered scope only because this diff touched it. Also: `provider_base_url_refused` is outside `telemetry_sink.BILLING_EVENTS`, and a refused base is visible only in the log, not on `/ready`, `/status`, `/metrics` or `/ui/ops`.

**Could not be verified:** the refusal path firing *in production* — doing so would mean misconfiguring the live base. The good path is confirmed serving on the shipped https default. Marked UNVERIFIED rather than claimed.

**Spend: zero.** `live_execution` stayed `false` throughout.

### W9 — the moderator model could grade its own answer — SHIPPED, VERIFIED IN PRODUCTION

- **PR #414**, squash-merged as `ee27c19e7a670f53ccbb638d6952506e28dac145`. Closed no issue (W9 had none); `closingIssuesReferences` is `[]`.
- **The premise was demonstrated, not assumed.** The moderator is not blind to authorship: `debate._debate_user_prompt` labels every answer with its model and both moderator system prompts say *"Cite the model names"*. The moderator's `PanelStance` reaches `panel_agreement` and `compute_consensus_strength` via `synthesis_consensus._usable_stance`, so one of the four votes behind the reader-visible verdict was cast on its own author's work. With `_required_cluster(4) == 3`, moving one slot turns a 2-2 `divided` into a 3-1 `strong`.
- **The scope fence held.** The fix is a guard that REPORTS, never refuses: `moderator_overlap_slots()` in `model_slots.py`, surfaced as `moderator_slot_overlap` on `/status`. `debate_model_id`, `DEFAULT_MODEL_IDS`, the price table and `costs.py` are all untouched — **no money or safety constant moved.** ADR-0086 records the posture and three rejected alternatives, including the finding that ADR-0028's costed proposal would have moved the moderator onto *slot 1's* id — relocating the overlap rather than removing it.

**What the MAIN ORCHESTRATOR re-ran itself:**

| Check | Command | Result |
|---|---|---|
| Merge landed | `gh pr view 414` | `MERGED`, `ee27c19e…`, closed nothing |
| Deploy **job** | enumerated all 3 `Deploy to Fly.io` runs for the SHA | 2 `cancelled`, **run 33462081090 job = `success`** |
| Production | `curl /status` | `build_sha` = `ee27c19e…` **exact match**, `live_execution: false` |
| **Fix fires in prod** | same probe | `moderator_slot_overlap: [2]` — the guard is live and reporting the real overlap |
| No id leak | same probe | `'anthropic/claude-haiku-4.5' in payload` → **False** |
| Board | `check_open_work.py --check` | EXIT=0, 22 rows, W9 **DONE** |
| Needle actually flips | `grep -c debate_model_id src/product_app/model_slots.py` | **0 → 5** — the fix ADDED the pinned needle, so DONE is derived, not typed |
| Tests bite (mine, 3 independent mutations) | neuter guard → `8 failed`; `slot_number`→sequence position → `1 failed` (`test_the_reported_numbers_are_the_slots_own_not_their_position`); drop normalisation → `2 failed` (case/space + routing-suffix tests) | all killed, each by a specifically-named test; `diff -q` + `git status` clean after each restore |
| Tree | `git worktree list`, `git branch -a` | worktree removed, branch gone local AND remote |

**Review caught two false claims the sub-orchestrator had written itself**, both corrected with the replacement verified by command first (AGENTS.md rule 4): "`/status` carries no OpenAPI schema" was false (it is in `openapi.yaml`, description byte-identical to the docstring at 8317 chars both sides); and "no ADR, requirement or test mentions it" was false — `tests/resilience/test_fault_injection_lane.py` already named and asserted the overlap, but **for a different consequence**, and nobody had carried it across to the verdict question. Five mutants survived the first test drafts and the tests were strengthened until they bit.

**New row W23 (UNPINNED), filed not fixed — and I verified it myself.** The advisory mutation gate aborts before scoring anything when a changed function is covered by a schemathesis case: `mutmut` re-invokes pytest with node ids, schemathesis parametrises by `"{METHOD} {PATH}"`, and pytest cannot select a node id containing a space. My own run on the real tree:
```
$ uv run pytest 'tests/contract/test_api_contract_schemathesis.py::test_api_conforms_to_openapi_contract[GET /status]' --no-cov -q --collect-only
EXIT=4 ... no tests collected in 0.21s
```
pytest exits 4 → `BadTestExecutionCommandsException` → no score. This is **not** a pre-existing red: PR #413 the same night scored normally (38 survivors) because its scope was `providers.py`, which no schemathesis case covers. It affects any future diff touching a function reachable from a documented endpoint. Left unfixed deliberately — gate machinery is a separate concern (rule 17). W9's own functions were mutation-proven by hand instead.

**Advisory debt recorded in ADR-0086, not fixed:** no `/ui/ops` tile; caller-supplied slot lists unchecked; alias classes (`~vendor/model-latest`, `openrouter/auto`, canonical slugs) invisible to the comparison; `/status` now writes the `_last_drift_diagnostic` process global (mechanism only, no harm demonstrated).

**Spend: zero.**

### W20 / #394 — `panel_agreement()` called a one-model panel "agreed" — SHIPPED, VERIFIED IN PRODUCTION

- **PR #415**, squash-merged as `350119fad360522adbcbaa8e442d6fbda6597202`. **#394 is CLOSED**, and `closingIssuesReferences` is exactly `[394]` — it closed that issue and nothing else.
- Fix: one guard, `if len(stance) < 2: return "undetermined"`, following ADR-0083's precedent for the sibling function rather than inventing a shape. ADR-0087 added; ADR-0083's caveat annotated to point at it.
- **Behaviour before:** a degraded one-answer run served `agreement.panel_agreement: "agreed"`. **After:** `"undetermined"`.

**The inherited "zero live impact" premise was half wrong, and the sub-orchestrator caught it by execution rather than trusting the board.** At N=1 the green banner really was already blocked (`isConsensusResult` requires `false_consensus_preserved === false` as a separate conjunct, and that is correctly `True` at N=1). But `agreement.panel_agreement` crosses the API boundary, so the false claim *did* reach every client reading the JSON. **LATENT for the banner, LIVE for the served field.** The board's old wording was true of the banner and too broad about the field; corrected in the same PR.

Reachability was proved, not assumed: on `ee27c19` before writing anything, 3 slots FAILED + 1 COMPLETED + one live moderator round gives `_usable_stance: {1: 'nrr'}` → `panel_agreement: agreed`. Reachable today; no unreleased feature needed. N=0 is unreachable (`_usable_stance` returns `None`).

**What the MAIN ORCHESTRATOR re-ran itself:**

| Check | Command | Result |
|---|---|---|
| CI before merge | waited on `gh pr checks 415` myself | all 11 pass, **all six required contexts green**, `mergeStateStatus: CLEAN` |
| Merge landed | `gh pr view 415` | `MERGED`, `350119fa…` |
| Closed exactly one issue | `closingIssuesReferences` | `[394]`; `gh issue view 394` → **CLOSED** |
| Deploy **job** | enumerated all 3 runs for the SHA | 2 `cancelled`, **run 33468177467 job = `success`** |
| Production | `curl /status` | `build_sha` = `350119fa…` **exact match**, `live_execution: false` |
| Board | `check_open_work.py --check` | EXIT=0, 22 rows, **7 PENDING / 10 DONE**, W20 **DONE** |
| Needle re-pinned correctly | row now reads `ABSENT … :: if len(stance) < 2:` | the fix ADDS that line, so DONE is derived — the needle was moved off the line the fix edits, exactly as briefed |
| Tests bite (mine, 3 mutations, `PYTHONDONTWRITEBYTECODE=1`) | baseline `11 passed`; delete guard → **4 failed**; `< 1` → **4 failed**; `< 3` → **2 failed** | all killed. The `< 3` mutant is caught by `test_a_genuine_disagreement_of_two_or_more_still_reads_split[2-groups0]` — the rule-7 positive partner proving N≥2 is not regressed |
| Tree | `git worktree list`, `git branch -a` | worktree removed, branch gone local AND remote |

**A trap worth carrying forward, measured tonight at the cost of one wasted `make quality`.** A mutant that only *reorders* lines keeps the file's byte size, so a `cp` restore inside the same one-second mtime bucket leaves a `.pyc` whose `(mtime, size)` header still validates — CPython then goes on executing the **mutated** bytecode. It reported 4 phantom failures while `grep` showed the guard in place and `module.__file__` pointed at the right file, so the usual staleness checks pass and tell you nothing. Proved: `pyc records source mtime=1788232519 size=53444 / actual mtime=1788232519 size=53444 / STALE-BUT-CONSIDERED-VALID: True`. Clearing `__pycache__` restored `11 passed`. Recorded in ADR-0087. **Set `PYTHONDONTWRITEBYTECODE=1` for every mutation proof** — I did for mine above.

**Reviewer work (four independent read-only lenses, each in its own `git archive` copy):** differential sweeps of 21,810 and 542,190 input shapes across both trees found the only reachable transition is `agreed → undetermined` at stance size 1 — zero N≥2 verdicts moved, zero browser green-gate flips. Two reviewers independently reproduced all eight of the sub-orchestrator's mutants. No CRITICAL_BLOCKER, no REQUIRED_CONTRACT; one fix round, all of it prose.

**UNVERIFIED, and not claimed:** the fix firing in production. `panel_agreement` appears only in a run result payload — `/metrics`, `/ready` and `/ui/ops` return 0 matches and `/status` does not carry it, so the only way to observe it is a paid run. Covered by 11 tests, 8 mutants and six green required contexts; not by production observation.

**Advisory debt, recorded not fixed:** `test_a_stance_that_names_only_the_answering_slot_is_also_undetermined` hands `panel_agreement` byte-identical state to the reproduction test, so no mutation can distinguish them — it is really a `_usable_stance` regression test. Harmless, left in place.

**Process note:** this package's sub-orchestrator hit a per-turn tool budget three times while polling CI, handing control back with the PR open each time. The main orchestrator waited on CI itself (read-only) and returned only the terminal steps. **Lesson for future overnight briefs: tell the sub-orchestrator to hand CI-waiting back to the orchestrator rather than polling.**

**Spend: zero.**

### #402 — the board-anchor squash-survival gate — **STOPPED, NOTHING MERGED** (correct outcome)

`#402` stays **OPEN**. Nothing was pushed, merged or deployed from this package. This was the outcome my brief explicitly licensed, and the evidence forced it.

Two designs were built, each with TDD and mutation proofs, and each was demolished by adversarial review:

- **Design A** — ancestry against `origin/main`, plus an escape for anchors committed by `GitHub <noreply@github.com>`. **False negative.** GitHub stamps that identity on every commit it creates server-side, *including the "Update branch" merge it makes on a feature branch*. The supporting measurement (40/40 recent `main` commits are GitHub-committed) was real but drawn from the wrong population.
- **Design B** — decide skip-vs-refuse from `remote.origin.fetch`. **Regression.** It silently ACCEPTS an ordinary branch-only anchor in `--single-branch`, bare-clone+worktree, and `remote set-branches` shapes that Design A refused.

**Two fix rounds, each adding a new defect — AGENTS.md rule 12's stop condition.** I called the stop as orchestrator rather than letting a third round run.

**What the MAIN ORCHESTRATOR verified itself:**

| Check | Command | Result |
|---|---|---|
| The decisive false negative is real | `git log -1 --format='%H \| committer=%ce \| parents=%p \| %s' 172803b` | `172803b… \| committer=noreply@github.com \| parents=4b6d9d9 dfc0419 \| Merge branch 'main' into codex/brand-readiness-2026-08-03` |
| …and it is NOT on main | `git merge-base --is-ancestor 172803b origin/main` | **EXIT=1** — a real commit in this repo's own history that Design A would have wrongly accepted |
| Nothing merged | `git rev-parse HEAD` / `origin/main` | both still `350119fa…` — unchanged from before the package |
| Nothing pushed | `git branch -a` | branch absent local and remote; it was never pushed |
| Worktree gone | `git worktree list` | main checkout only |
| Issue still open | `gh issue view 402` | **OPEN**, 1 comment recording both dead ends |

**Why shipping it would have been worse than the prose it replaces** — the argument, not just the verdict:
1. **It fails open in the workflow the rulebook mandates.** Rule 17a *requires* branching in a dedicated worktree, and the bare-clone+worktree shape is one Design B accepts.
2. **It declines to answer questions it can answer.** In the bare-clone+worktree case `refs/heads/main` is present and complete locally; in the `set-branches` case `refs/remotes/origin/main` is present, correct and current. The skip fires because a *config line* stopped mentioning the ref, not because the fact was unknowable. Root cause: a docstring sentence conflating "no refspec could produce `origin/main`" with "main is unknowable here."
3. **The test pinned the hole open — twice, in one package.** Every skip-path test used an anchor already on `main`, so by construction no test could assert that a branch-only anchor is still caught in a skip shape. AGENTS.md rule 7 (a negative check needs a positive partner) failing the same way in two consecutive designs is the most transferable lesson here.

**Hypotheses settled** (I supplied four to the sub-orchestrator to refute; it measured them):
- **H1 and H2 SURVIVE** — the merge-base variant and `rev-list origin/main..HEAD` both fail the same way as the naive fix under a stale remote. The escape hatch the issue hoped for does not exist.
- **H3 SURVIVES** — **the fact is not derivable offline.** With a stale `origin/main` the local object graph genuinely cannot distinguish "a main commit you have not fetched" from "a commit that exists only on your branch." This is the central finding, and it means AGENTS.md rule 1a's "prefer a gate over a corrected sentence" runs into its own stated network caveat here.
- **H4 SURVIVES** — `make validate` runs only in `ci.yml:77` (`validate-and-test`, `fetch-depth: 0`, default refspec), so a network-requiring check would be genuinely blocking in CI. CI is not exposed to the Design B hole: `actions/checkout@v4` never writes `remote.origin.fetch` (zero hits in run `33466696419`'s log).

**The record:** `docs/analysis/2026-09-01-402-freshness-gate-design.md` (412 lines). It marks every claim `[me]` / `[reviewer]` / `UNVERIFIED`, carries both adversaries' full false-positive and false-negative matrices with commands, and states the **eleven-case bite-proof** any future attempt must pass — now including, as *measured* requirements rather than hypotheticals: the fork-behind topology, `--single-branch`, bare-clone+worktree, and `remote set-branches`.

**Honest note on the mutation score:** 13 mutations, 13 killed, every row summing to the 46-test baseline (so none broke collection). **That score measured nothing that mattered** — the defect that stopped the package is invisible to all 13, because the tests encoded the wrong contract. A green mutation score over a wrong contract is not evidence.

**Marked UNVERIFIED, not claimed:** "three such commits among the 281" (one confirmed by command), and the "both advance it" half of the `git fetch origin <sha>` clause.

**Advisory debt:** a fork contributor whose `origin` is their own fork is accepted silently by *every* design tried.

**Spend: zero.**

### W17 — FR-004 named a model we do not ship — SHIPPED, VERIFIED IN PRODUCTION

- **PR #416**, squash-merged as `ffdeaea6804e247c7c1e61b098b62fe488807f71`. Closed no issue (W17 had none); `closingIssuesReferences` empty, matching `EXPECT_CLOSE=""`.
- FR-004 and AC-007 named `deepseek/deepseek-chat-v3.1` as slot 4's default; the app ships `nvidia/nemotron-3-nano-30b-a3b`. **8 files corrected, 7 deliberately left alone**, and — per rule 1a — the corrected sentences are now backed by a GATE, which is the part that outlives them.

**The sizing warning earned its keep.** `git grep -l` returns 113 files; the defect was two sentences. Left alone on purpose: dated owner answers in `docs/04-problem-statement.md` (D-010) and `docs/13-open-questions.md` (OQ-005) — rewriting a dated record falsifies it, so they got additive "Superseded" notes; the approved design mock and its README (the mock really does show DeepSeek); `PRODUCT_IDEA.md` (intake record); `scripts/seed_feedback_audit_data.py` (demo data that asserts nothing).

**Review found two files the census itself had missed**, because the needle did not match their spelling: `docs/design-handoff/AC-CROSSWALK.md:48` (ids written without vendor prefixes) and `docs/architecture/40-decisions.md:53` (a vendor family, no id at all).

**A reviewer request was correctly DECLINED.** Correcting `docs/faq/index.html:585/713` was refused because ADR-0032 examined those exact two lines and recorded them as deliberately correct — that would have been the false correction this package existed to avoid.

**What the MAIN ORCHESTRATOR re-ran itself:**

| Check | Command | Result |
|---|---|---|
| CI before merge | waited on `gh pr checks 416` myself | all 11 pass, six required contexts green, `mergeStateStatus: CLEAN` |
| Deploy **job** | enumerated all 3 `Deploy to Fly.io` runs for the SHA | 2 `cancelled`, **run 33482619442 job = `success`** |
| Production | `curl /status` | `build_sha` = `ffdeaea6…` **exact match**, `live_execution: false` |
| Board | `check_open_work.py --check` | EXIT=0, 22 rows, **6 PENDING / 11 DONE**, W17 **DONE** |
| Needle flipped | `grep -c deepseek/deepseek-chat-v3.1 docs/10-functional-requirements.md` | **0** — the fix DELETED the pinned needle, so DONE is derived |
| FR-004 text | `sed -n '53p'` | now names `nvidia/nemotron-3-nano-30b-a3b` |
| **Gate bites on DOC drift** | reintroduced deepseek into FR-004, ran the gate | **2 failed** — `test_spec_docs_name_the_default_model_ids_the_app_actually_ships`, `test_no_covered_doc_names_a_non_default_model_anywhere` |
| **Gate bites on CODE drift** | changed `DEFAULT_MODEL_IDS` slot 4 in a `cp` copy | **2 failed**, same two tests |
| **Anti-vacuity floor is real** | read `test_the_default_slot_gate_refuses_an_empty_input` | a doc naming NO defaults FAILS with *"makes no default-model-slot claim"*; carries its own "what turns it red" line and a CARDINALITY partner for the names-some-but-not-all case |
| Cleanup | `git worktree list`, `git branch -a`, `git log --oneline` | worktree removed, branch gone local AND remote; the orchestrator's docs commit correctly rebased on top as `e9de7a7`, both files intact |

Both mutation proofs run with `PYTHONDONTWRITEBYTECODE=1`, restored from `cp` copies, `diff -q` and `git status` clean after each.

**Review: two rounds, six reviewers, five reproduced holes.** Round 1 (4 reviewers) broke the original whole-file gate three ways. Round 2 (2 reviewers) broke the fix twice more — block scoping had silently traded away coverage the first version had, and the new corpus floor fell to respelling an entry `./README.md`. Both closed; the gate now keeps both halves.

**Advisory debt, recorded not fixed:** `docs/faq/index.html:1223` states the *synthesis* default as `openai/gpt-4o-mini` while the app ships `openai/gpt-5-mini` (pre-existing, different concern); the FAQ is ungated because it uses `<code>` tags rather than backticks; `docs/architecture/40-decisions.md` is corrected but ungated; `docs/37-jira-confluence-sync-log.md` has no row for the now-diverged published Confluence page; `check_open_work.py`'s comment stripper would mis-read a needle placed in a Markdown heading.

**A trap I hit MYSELF, worth recording.** My first deploy-wait loop counted incomplete runs over an EMPTY list — `gh run list --commit <sha> --workflow "Deploy to Fly.io"` returned `[]` because the Deploy workflow had not started yet (it gates on CI + Tests + E2E), and `sum()` over nothing is `0`, so the loop reported "complete" and I read a stale `build_sha`. **That is the exact anti-vacuity failure AGENTS.md warns about, committed by the orchestrator inside its own verification.** The fix is to require the count to be non-zero AND complete. Also re-confirmed: `gh run list --commit` can return `[]` here; `--branch main` with a SHA-prefix match is the reliable form.

**Spend: zero.**

### W19 — a timing bound that failed on unmodified `main` — SHIPPED, VERIFIED IN PRODUCTION

- **PR #417**, squash-merged as `875839602aec3e0adba7aa0358fb679240fd8091`. Closed no issue (`EXPECT_CLOSE=""`).
- **The test stopped being a timing test.** `test_the_budget_covers_the_header_phase_not_only_the_body` no longer asserts on the wall clock; it asserts on the budget ARGUMENT handed to `_iter_body_within_budget` — which is exactly what AGENTS.md rule 8b prescribes for this function (*"Assert on the ARGUMENT, not the result"*). ADR-0089 records the decision.

**The measurement that justifies it** (sub-orchestrator's, and the separation is the whole argument): 8 interleaved pairs at load ~4.9 — clean wall 4.008–4.106 vs mutant wall 4.049–4.157 (**the wall figures OVERLAP**), while the argument reads −2.508…−2.606 clean vs +1.4999905…+1.4999957 mutant (**completely separated**). Baseline: **10/10 failed on a pristine `origin/main` worktree**. Charge across 28 reps at load 3.6–20.9: 3.762–4.106s, lowest **3.7617s** — and the lowest values came at *ambient* load, so it is load-INsensitive, not load-monotonic. 25% headroom over the new 3.0 literal.

**What the MAIN ORCHESTRATOR re-ran itself:**

| Check | Command | Result |
|---|---|---|
| CI before merge | waited on `gh pr checks 417` myself | `Counter({'pass': 11})`, `mergeStateStatus: CLEAN` |
| Deploy **job** | enumerated all 3 runs for the SHA | 2 `cancelled`, **run 33494642220 job = `success`** |
| Production | `curl /status` | `build_sha` = `87583960…` **exact match**, `live_execution: false` |
| Board | `check_open_work.py --check` | EXIT=0, 22 rows, **5 PENDING / 12 DONE**, W19 **DONE** |
| **Needle re-pin was NECESSARY, not cosmetic** | `grep -c "assert wall < 4.0," tests/unit/test_provider_call_time_budget.py` | **1** — still present, at line 209 in a DIFFERENT test (`test_a_slow_dribble_is_cut_at_the_budget`, where a 1.5s budget genuinely CUTS a body read, so the bound is meaningful there). Had the old needle been kept, line 209 would have held it `PRESENT` forever and the row would have lied. The re-pin to `ABSENT … :: budget_handed_to_body_read` is correct. |
| New assertion is sound | read lines 690-707 | lower bound `charged_for_the_header_phase >= 3.0`; **positive partner** `charged <= wall` proving the charge is a real elapsed slice of THIS call and not a constant a stubbed reader could hand back; `wall < 30.0` liveness only |

**What turns the new test red:** moving `call_started = time.monotonic()` after `urlopen`, or deleting the `- (time.monotonic() - call_started)` subtraction. **How it separates load from a regression:** the charge is floored at ~3.55s by 71 `time.sleep(0.05)` calls that never return early — structural, not statistical — while the defect drives it to exactly **zero**.

**The accepted loss, unsoftened.** `header_tick` has exactly one call site in the suite, so after this change **no test anywhere bounds the total wall clock of a call whose header block dribbles**. A regression making the header phase take twelve seconds would now pass; only the `wall < 30.0` liveness ceiling remains, and that catches hangs, not slowness. Why accepting it is right: the budget can only CHARGE for the header phase, it cannot CUT it — `urlopen` has already returned before any client-side code runs, so no correct implementation ever made this call finish sooner. The old ceiling was measuring the SERVER's dribble loop, not the product: a bound on the test fixture wearing the costume of a bound on the code. It failed 10/10 on unmodified `origin/main`, and one reviewer measured it **green on the defect and red on the fix** — an inverted detector, which AGENTS.md forbids outright.

---

## 🔴 #418 — THE MOST IMPORTANT FINDING OF THE NIGHT (filed, not fixed)

**A docstring line can satisfy any Python board needle, so `check_open_work.py` can report DONE for absent work.**

Root cause: `scripts/check_open_work.py:180-186` defines its OWN `code_text()` that strips only `#` comment tails line-by-line and never tokenizes, so **docstrings survive**. It does not use `tests/code_text.py`, the helper written precisely to prevent this.

**I reproduced this myself**, independently, on W20's needle:
```
STEP 1  delete the W20 guard              -> EXIT=1  "W20 says DONE, the tree says PENDING"   (gate works)
STEP 2  guard STILL deleted, add ONE line
        to the docstring containing
        `if len(stance) < 2:`             -> EXIT=0  W20 reads DONE again                     (defect masked by prose)
```
Restored from a `cp` copy; `diff -q` and `git status` clean.

**Why this matters beyond one row:** it affects **all 17 Python-pinned needles**. The derived-state board is the mechanism this entire overnight run leaned on to tell a claim from a fact, and it can be satisfied by prose.

**Tonight's four DONE flips are NOT in doubt.** In every case I verified the actual code construct directly — reading the guard bodies, driving the functions over real inputs, and mutating them — rather than trusting the board. W18: drove `chat_completions_url` over 12 inputs. W9: `debate_model_id` 0→5 occurrences plus 3 mutations. W20: read the shipped guard, 3 mutations. W17: reintroduced deepseek and drifted `DEFAULT_MODEL_IDS`, both red. W19: read lines 690-707 and confirmed the line-209 subtlety above.

**Advisory, recorded in ADR-0089:** `test_the_deadline_still_bounds_the_read_when_the_socket_cannot_be_reached` **hangs** rather than reddening under a body-deadline mutant, because `pytest-timeout` is not installed (pre-existing). A `max(0.0, remaining)` clamp is behaviour-preserving in production yet now a false red (intended, recorded).

**Review pattern worth carrying forward:** round 2 found **six errors in prose the sub-orchestrator had just rewritten**, including a figure it had inherited from a reviewer instead of measuring. This is the third package tonight where the *corrections* were less reliable than the original draft.

**Spend: zero.**

### W4 — variable panel size N ∈ {2,3,4} — **NOT ATTEMPTED, deliberately deferred**

Sized, not skipped. The board calls it unblocked and it is — the hard prerequisite really did land (`_required_cluster(panel_size)` in `synthesis_consensus.py:530` is already generalised by W10/ADR-0083, and the CSS already reflows). The mechanical surface is small: `EXPECTED_SLOT_COUNT = 4` with `if len(model_ids) != EXPECTED_SLOT_COUNT` (`model_slots.py:45,314`), `slot_number: int = Field(ge=1, le=EXPECTED_SLOT_COUNT)` (`:105`), and three `Field(ge=1, le=4)` sites (`debate.py:209`, `debate.py:1268`, `providers.py:322`).

**What stops it is not size — it is that it needs a decision only the product owner can make.** Measured:

```
$ grep -rn "panel size|variable panel|two to four|N ∈" docs/10-functional-requirements.md \
      docs/12-acceptance-criteria.md docs/11-non-functional-requirements.md
(no matches)

$ grep -n "slot" src/product_app/templates/workspace.html
247:  <legend>Four model slots</legend>
248:  <div class="muted">Choose four different models. …</div>
```

**No FR, no acceptance criterion, and no NFR defines variable panel size**, while the UI hardcodes "Four model slots" as user-facing copy. Nothing anywhere says HOW a user would choose N — a control, a URL parameter, removing a slot — and that is a product decision, not an implementation detail.

AGENTS.md's own **Mandatory lifecycle** section is explicit: *"Do not code until these exist and validate"*, listing `docs/10-functional-requirements.md` and `docs/12-acceptance-criteria.md`. Writing that requirement IS the product decision. Inventing it unattended would be exactly the half-ship the overnight brief forbids.

**The tempting "safe subset" was considered and rejected.** Relaxing only the backend to accept N ∈ {2,3,4} while the UI keeps sending 4 would (a) pin the very bounds the real design has to choose — `le=4` and the new minimum — fixing them in place before the decision is made, and (b) ship a code path nothing exercises, which is the anti-vacuity problem in a new place.

**For the morning:** the decision needed is *how a user selects N, and whether it is exposed at all*. Once that is written as an FR + AC, the code change is genuinely small and W10 has already done the hard part.

---

## FINAL SUMMARY — overnight run 2026-09-01

### Shipped, merged, and verified running in production

Each verified by the orchestrator independently — merge state, Deploy **job** conclusion (never the run rollup), production `/status.build_sha`, board flip by direct `grep`, and at least one mutation proof of my own per package.

| Item | PR | Merge SHA | Deploy job | Prod `build_sha` |
|---|---|---|---|---|
| **W18** — paid call sent the API key to an operator-settable base with no scheme guard | #413 | `c15edbe7` | run 33454794735 `success` | ✅ exact |
| **W9** — moderator could grade its own answer | #414 | `ee27c19e` | run 33462081090 `success` | ✅ exact |
| **W20 / #394** — `panel_agreement()` called a one-model panel "agreed" | #415 | `350119fa` | run 33468177467 `success` | ✅ exact |
| **W17** — FR-004 named a model we do not ship | #416 | `ffdeaea6` | run 33482619442 `success` | ✅ exact |
| **W19** — timing bound that failed 10/10 on unmodified `main` | #417 | `87583960` | run 33494642220 `success` | ✅ exact |

Production is on `875839602aec3e0adba7aa0358fb679240fd8091`. Board: **22 rows, 5 PENDING, 12 DONE**. **#394 closed.** **Spend: $0** — `live_execution` was `false` at every check; no live window was ever opened.

### Stopped or deferred, with reasons

- **#402** (board-anchor squash-survival gate) — **STOPPED, nothing merged, issue still open.** Two designs built and both demolished: one accepted a branch-only anchor (refuted by a real commit, `172803b`, which I confirmed myself), the other regressed to accepting branch-only anchors in `--single-branch` and bare-clone+worktree checkouts — the latter being the workflow AGENTS.md rule 17a *mandates*. Two fix rounds each adding a defect = rule 12's stop condition. Central finding: **the fact is not derivable offline.** Full record with both adversaries' matrices and an eleven-case bite-proof: `docs/analysis/2026-09-01-402-freshness-gate-design.md`.
- **W4** (variable panel size) — **NOT ATTEMPTED**, see above: needs an FR/AC that is a product decision.
- **Not touched, per instruction:** W3, W13/#268 (money constants), W14/#105, W2/#290, W7, W5.

### Left for the product owner

1. **#418 — the highest-value finding of the night, and it is about the board itself.** A docstring line can satisfy any Python board needle, because `check_open_work.py:180-186` strips `#` comments but never tokenizes. I reproduced it myself: delete W20's guard → gate correctly fails; then, guard still absent, add ONE docstring line → **EXIT=0 and W20 reads DONE**. Affects all 17 Python-pinned needles. *Tonight's five flips are not in doubt* — each was verified against the actual code construct, not via the board.
2. **W21 / W22** — two further credential exposures found by W18's own review: `urlopen` follows redirects carrying `Authorization` (so an https base that 302s to http still leaks the key), and `_tavily_search` has no scheme guard at all (a reviewer demonstrated dialling `file:///etc/passwd/search` with the key attached). **W22 is the more serious and is fully unblocked.**
3. **W23** — the advisory mutation gate aborts before scoring when a changed function is covered by a schemathesis case (pytest cannot select a node id containing a space). Confirmed by me.
4. **A credential was surfaced into a subagent transcript.** A reviewer ran `env | grep ^GIT`, which printed `GITHUB_PERSONAL_ACCESS_TOKEN` into its local transcript. It is **not** in any tracked file (`git grep` clean). Rotation is the owner's call; nothing was rotated.
5. **One unpushed local commit** carries this log and the #402 design record. Push, or fold into a PR, as preferred.

### Process lessons worth keeping

- **Sub-orchestrators hit a per-turn tool budget while polling CI**, handing back open PRs. Fixed mid-run: later briefs told them to hand CI-waiting back to the orchestrator. That worked cleanly for #416 and #417.
- **I committed the anti-vacuity error myself**, inside my own verification: a deploy-wait loop counted incomplete runs over an EMPTY list (the Deploy workflow had not started, because it gates on CI+Tests+E2E) and reported success, so I read a stale `build_sha`. Caught only because production disagreed with the merge SHA. Require the count to be non-zero AND complete.
- **`.pyc` staleness can fake a mutation result.** A size-preserving mutation restored inside the same one-second mtime bucket leaves a `.pyc` that still validates, and CPython keeps running the MUTATED bytecode while `grep` and `__file__` both look correct. Use `PYTHONDONTWRITEBYTECODE=1` for every mutation proof.
- **Corrections were less reliable than the drafts**, again — in three separate packages, a review round found errors in prose that had just been rewritten to fix earlier errors.
- **A needle chosen for precision under-counts its own population.** W17's census used the exact model id and missed two real defects that spelled it differently.

