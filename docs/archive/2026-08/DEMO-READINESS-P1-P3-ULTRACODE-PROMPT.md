# Demo-readiness — P1 (judge wiring) · P2 (accuracy pilot) · P3 (NFR-004 deadline)

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue DEMO-READINESS-P1-P3-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute. Work autonomously within the PRE-AUTHORISED
> scope below. The two things you must NEVER do: **invent a value, rate, or human
> subject-matter/correctness label you cannot measure**, and **flip a suppression /
> safety default from an unmeasured value**. When `gh pr merge` is blocked by the
> harness auto-mode classifier, STOP and ask the operator; do not work around it.
>
> This builds three small, independent, hermetic ($0) slices that make the product
> demo-able end-to-end WITHOUT any paid API call. **Funding + live verification in
> prod (real four-model execution AND the real LLM judge key) is deliberately
> DEFERRED to a later operator-gated step and is OUT OF SCOPE here.** Every slice
> ships its mechanism wired but OFF-by-default, proven hermetically via monkeypatch.

## MISSION — three PRs, built SERIALLY (one at a time on the shared tree)

1. **P1 — Wire the real Layer-B judge into the request/serving path** behind its
   existing `QUORUM_EVAL_JUDGE_API_KEY` gate, default OFF (byte-identical
   suppression preserved). Prove hermetically, via a monkeypatched
   `verifies_support=True` judge, that a numeric `TrustScore` + non-`unverified`
   band unlock and render in the served UI — and that with no key nothing changes.
2. **P2 — Measured-accuracy PILOT (n = small), on HUMAN-authored labels only.**
   Build the scoring harness + a distinctly-scoped pilot artifact + a
   process-metrics panel. The correctness labels come from the OPERATOR (see the
   OPERATOR-AUTHORED LABELS block) — the agent authors ZERO of them.
3. **P3 — Enforce NFR-004: a run-level wall-clock deadline** with graceful
   degrade-to-partial, env-configurable, default generous. Flip NFR-004 from
   UNENFORCED → ENFORCED in `docs/18` with the mechanism cited.

**Recommended order: P1 → P3 → P2.** They are logically independent, but P1 and P3
both touch the run/serving path in `src/product_app/query_runs.py`, so build them
one PR at a time, each merged + deploy-verified before the next, and rebase each on
fresh `main`. P2 is mostly `tests/` + `docs/` (no served-asset delta).

---

## GROUND TRUTH VERIFIED ON ENTRY (2026-07-22 — confirm, don't assume)

The R2 tail is fully shipped: Stage B (#66/v28), RB-6 (#67/v29), RB-5 (#68/v30),
flake-record (#69/v31), **S4 (#70/`6a412f8`/v32)**. Confirm on entry: `git log
--oneline -3 origin/main` shows `6a412f8`; prod `/ready` returns `"state":"live"`.

**Judge machinery ALREADY EXISTS — you are wiring it, not building it:**
- `src/product_app/evaluation.py`:
  - `_judge_enabled()` (`:1305`) — gated SOLELY on `settings.quorum_eval_judge_api_key`.
  - `EvalJudgeService` (`:1316`) — the REAL judge; `verifies_support = True`; reuses
    `provider_execution_service.call_with_prompt`; needs BOTH a key AND
    `settings.quorum_eval_judge_model_id` (returns `None` if either is absent).
  - `StubEvalJudge` (`:1352`) — deterministic; **`verifies_support = False` ON
    PURPOSE.** Its verdict is a constant that reads nothing.
  - `evaluate_run(..., judge: EvalJudge | None = None)` (`:1574`):
    `support_verified = verdict is not None AND judge.verifies_support` (`:1598`);
    `build_trust_score(..., support_verified=...)` suppresses `score` to `None` and
    band to `"unverified"` whenever `support_verified` is False (the OC-2 rule,
    STRUCTURAL not conventional — `:1484`, `:1496`).
- `src/product_app/config.py`: `quorum_eval_judge_api_key` (`:111`, default `""`,
  `repr=False`), `quorum_eval_judge_model_id` (`:115`, default `""`),
  `quorum_eval_judge_max_tokens`.
- **The prod path hard-codes `judge=None`:** `query_runs._evaluate_terminal_run`
  (`~:1613`) calls `evaluate_run(...)` with NO judge; `_evaluation_projection`
  (`~:1621`) drops the judge entirely from the served projection.

### THE HARD INTEGRITY FACT FOR P1 (do not get this wrong)
**Wiring `StubEvalJudge` into the prod path can NEVER show a real trust number** —
`verifies_support = False` means it is byte-identical to judge-OFF by design, and
that is the whole point of the OC-2 suppression rule. **Do NOT flip
`StubEvalJudge.verifies_support` to True, and do NOT construct any other stub whose
`verifies_support` is True.** A numeric TrustScore is unlocked ONLY by a REAL judge
(`EvalJudgeService`, key + model present). Therefore:
- P1 wires `EvalJudgeService` into the request/serving path **behind
  `_judge_enabled()`**, default OFF. With no key → ZERO behaviour change (prove it).
- The on-screen numeric score with a REAL judge is demonstrated **only when the
  operator funds `QUORUM_EVAL_JUDGE_API_KEY` + pins the model** — that is the
  deferred funding step, NOT this PR. P1's job is: make it correct + ready + tested.
- Hermetic proof that the mechanism WORKS uses a **test-only fake judge with
  `verifies_support=True` injected via monkeypatch** (never shipped, never wired
  into a served path) — exactly the "ship OFF, prove via monkeypatch, queue
  activation to the human" discipline this repo already uses for Tavily and cost
  guardrails.

---

## ENVIRONMENT FACTS YOU MUST RESPECT

- **`main` branch protection is ENFORCED** (#65). Required blocking checks:
  `validate-and-test`, `pytest (Python 3.12)`, `Changed-lines coverage >= 95%
  (blocking)`, `Schemathesis API contract (blocking)`, `FR traceability
  completeness (blocking)`, `e2e axe + parity (chromium)`. **Required approvals:
  0** — you CAN `gh pr merge --squash` once blocking checks are green (subject to
  the classifier below). Advisory jobs (perf, mutation, csp-smoke) never block.
- **NEVER push to `main` directly** (#61) — always branch + PR, even for docs.
  After a merge, do NOT push anything else to main until that commit's CI finishes,
  or per-SHA concurrency cancels it.
- **A green Deploy *run* is not a deploy** (#62) — verify the per-SHA Deploy JOB
  (see DEPLOY VERIFICATION). P1 and P3 change served behaviour paths; P2 does not.
- **The auto-merge is blocked by the harness classifier.** When `gh pr merge` is
  denied, STOP and ask the operator to approve/perform it. Do not work around it.

## WORKING STYLE (non-negotiable — this is how the last nine PRs shipped)

- **Evidence-first / no claim without a check.** Before asserting any cause,
  number, status, config value, or version, run the single cheapest command that
  confirms it. If you cannot verify, say "UNVERIFIED hypothesis" and name the
  check. This repo has a logged history of confident-but-wrong claims (the
  Actions-billing hallucination; asserting a 78-case set that never existed).
- **TDD with a bite proof.** RED → GREEN → prove it BITES (mutate source, see red,
  revert). **Revert a bite-proof mutation with a FILE COPY, never `git checkout
  <file>`** (it discards uncommitted real edits). Protocol: `cp src/x.py
  /tmp/x.bak` → mutate → run the one test → `cp /tmp/x.bak src/x.py` → confirm `git
  diff --stat` empty. **Commit the coherent unit BEFORE any mutation fan.**
- **Beware the STALE-ARTIFACT false green AND false RED.** Before trusting a
  bite-proof result: `find src tests -name __pycache__ -type d -exec rm -rf {} +`.
  Ignore the gitignored `mutants/` dir from a prior mutmut run.
- **Adversarial review is not majority-safe.** When lenses converge on a finding,
  verify it yourself by EXECUTION before trusting a refutation. In RB-5 a
  triple-skeptic majority correctly refuted 6 findings, but the 2 survivors were
  both real, and re-reviewing the fix diff surfaced a THIRD.
- **Fan the REVIEW, build SERIALLY.** Review lenses must be READ-ONLY (no writes,
  no coverage runs that touch `build/`/`.coverage`) — say so in their prompts. Give
  an executing output-correctness lens its own `isolation: "worktree"`.
- **Never fabricate** a number, label, rate, or baseline. "Unmeasured" must never
  read as "clean". Hermetic, $0 — no paid API calls in any slice here.

## UI VERIFICATION GATE (applies to P1 and P3 — they touch served surfaces)

P1 makes a trust score/band potentially visible; P3 changes the degraded/partial
path. Both are governed by the below-the-line UI gate (`AGENTS.md` "UI
verification" + `.github/workflows/e2e.yml`):
- Any NEW provider-text surface must route through the markdown renderer
  (`setProse` for block prose, `setInlineProse` for inline/cell) — never raw
  `textContent`/`mkEl`. The **judge rationale is free text**: if you surface it at
  all, it MUST go through `setInlineProse`; if you do NOT surface it, say so. The
  trust score/band is numeric/enum → plain, but assert it in the golden fixture.
- Add the new surface's shape to the **golden messy fixture**
  (`e2e/fixtures/golden-run.ts`) so the invariant gate covers it, and screenshot at
  1440px as a user would — do not trust a green unit test on clean sim data alone.
- P3's partial/degraded result must keep satisfying `degraded-banner.spec.ts`
  (banner whenever `live_count < 4`) and the honest slot-count denominator RB-5
  shipped. **Prove RED then GREEN** on any UI-gate change (revert-and-rerun), and
  run any timing-sensitive spec N ≥ 10× to establish a real flake rate.

## DEPLOY VERIFICATION (do exactly this)

`deploy.yml` triggers on push AND on each of CI/Tests/E2E completing, so several
Deploy runs exist per SHA and per-SHA concurrency CANCELS superseded ones. A single
`cancelled`/`skipped` run means nothing.
1. Wait until CI, Tests, E2E for the merge SHA are all `completed/success`.
2. `gh run list --branch main --limit 20 --json
   headSha,databaseId,conclusion,workflowName,createdAt` — find the LATEST-created
   `Deploy to Fly.io` run for the SHA (ignore earlier cancelled ones).
3. On that run, the JOB conclusion must be `success`:
   `gh run view <id> --json jobs --jq '.jobs[]|select(.name|startswith("Deploy to
   Fly"))|.conclusion'`.
4. `fly releases --app quorum-ai | head -3` (version bumps, `complete`, dated
   seconds ago) AND prod `/ready` state=live. P2 has no served-asset delta, so its
   deploy signal is Deploy JOB `success` + a fresh Fly release.

## REVIEW DEPTH (operator-set)

- **P1 → FULL depth** (up to 3 rounds) — it touches suppression/trust integrity.
  Keep one lens whose explicit job is to **break the suppression** (find any path,
  config, or stub that unlocks a numeric score WITHOUT a real judge) and one
  EXECUTING output-correctness lens (monkeypatch a fake real-judge, assert score
  unlocks; remove key, assert suppressed) in its own worktree.
- **P3 → FULL depth** — a run-deadline can strand partial state or double-degrade.
  Keep an EXECUTING lens that injects a slow slot and asserts a partial result +
  correct banner, and a lens on "does the deadline ever cut a run that would have
  finished cleanly under normal load".
- **P2 → STANDARD depth**, plus one lens whose job is to find any place a label,
  accuracy number, or `n` is fabricated, extrapolated, or unscoped.
- After fixing findings, re-review only the fix diff.

## PER-SLICE LOOP (repeat for each of P1, P3, P2)

1. `git fetch origin main && git switch -c <feat-branch> origin/main`.
2. Build per the slice spec. TDD, bite proofs (file-copy revert). Commit the unit
   before any mutation fan.
3. Local gates, stop on first red: `make validate` · `make format-check` ·
   `make lint` · `make type-check` · `uv run pytest -q` · `make diff-cover`
   (≥95 on any `src` lines in the slice) · `cd e2e && npx playwright test --list`.
   For P1/P3 also run the touched e2e specs (rendering-invariants, degraded-banner)
   and screenshot the golden fixture at 1440px.
4. Review fan at the depth above. Fix findings test-first; re-review the fix diff.
5. Push → PR → wait for BLOCKING checks green on the real runner; independently
   re-verify the rollup (`gh pr view <n> --json statusCheckRollup,mergeable`; the
   API is flaky — re-check).
6. Ask the operator to `gh pr merge <n> --squash --delete-branch` (classifier
   blocks you). Do NOT push anything else to main until this commit's CI finishes.
7. Verify the deploy per DEPLOY VERIFICATION.
8. Update traceability/ledger citing REAL, new-since-baseline, git-tracked,
   non-empty artifacts.

---

## P1 — Wire the real Layer-B judge (FULL depth)

**Goal:** the request/serving path uses `EvalJudgeService` WHEN a key + model are
configured, so trust turns on the moment the operator funds the key — and is
byte-identical to today when they are not.

**Build:**
- In `src/product_app/query_runs.py`, replace the hard-coded `judge=None` at the
  terminal-eval site so it passes the real judge **only when `_judge_enabled()` is
  True AND `quorum_eval_judge_model_id` is set** (reuse `EvalJudgeService` +
  `_judge_enabled` — do not fork them). Respect NFR-011/NFR-012: with no judge, the
  path must still perform ZERO I/O (no evidence built, provider seam untouched) —
  keep that invariant and assert it.
- Ensure `_evaluation_projection` surfaces `score` + `band` when
  `support_verified` is True. Decide explicitly whether the judge **rationale** is
  served: if yes, route it through `setInlineProse` and add it to the golden
  fixture; if no, state that and drop it (matching today).
- Add the served trust score/band shape to `e2e/fixtures/golden-run.ts` (a
  `support_verified=true` variant) and assert it renders under the invariant gate.

**Prove (hermetic, $0):**
- RED→GREEN unit: monkeypatch a **test-only fake judge** (`verifies_support=True`,
  returns a fixed verdict) injected at the wiring seam → assert `evaluate_run`
  yields a numeric `score` and a non-`unverified` band, and the served projection
  exposes them. Remove the key/model → assert `score is None`, band `unverified`,
  and zero I/O. Bite-proof the wiring (revert the wiring edit → the "score unlocks"
  test must fail).
- **Suppression regression test:** assert that with the SHIPPED `StubEvalJudge`
  (or any `verifies_support=False` judge) the score STAYS suppressed — a guard so
  no future change can quietly unlock a number without a real judge.

**Landmines / integrity:**
- Do NOT flip `StubEvalJudge.verifies_support`. Do NOT wire the stub into any
  served path. Do NOT set a default key/model in `config.py` — default OFF.
- Do NOT touch `tests/evals/` golden-set gate expectations for judge-OFF (they
  assert band `unverified`, score `None`) — those stay true by default.
- Since default is OFF, there is **no served-asset delta by default**; the deploy
  signal is Deploy JOB `success` + fresh Fly release. Say so in the PR body.
- Traceability: this realises FR-015 (Layer-B judge) request-path wiring — add/flip
  the relevant AC + `docs/17`/`docs/18` rows; do NOT claim any *measured* judge
  quality (it is uncalibrated until the D5 labels exist).

---

## P3 — Enforce NFR-004 run-level deadline (FULL depth)

**The fact (verified):** there is NO run-level wall-clock bound in `src/`. The only
180s timer is `DEBATE_HARD_TIMEOUT_MS` (`debate.py:47`), which merely gates whether
debate *round 2* runs — it does not bound total run wall-clock. `docs/18`
Traceability Notes currently records NFR-004 **UNENFORCED**.

**First, locate the real orchestrator (evidence-first — do NOT assume async):** the
run path is not `asyncio`-based in `query_runs.py`; it sequences providers →
synthesis → debate using `perf_counter()`/`elapsed_ms` (see `debate.py:259`,
`259-329`). Find the single top-level entry that produces a terminal `QueryRun` and
measure how time is already tracked (`started_at`, `_elapsed_time_ms`
`query_runs.py:1891`) before choosing the mechanism.

**Build:**
- Add a run-level deadline enforced consistently with the EXISTING
  `perf_counter()`-since-`started_at` pattern (mirror how `debate.py` already
  bounds itself) — bound TOTAL run wall-clock, not just round 2.
- Make it env-configurable: add `quorum_run_deadline_seconds` to `config.py`,
  **default deliberately generous** (e.g. 180s per NFR-004, but confirm the number
  against the doc; do NOT invent a tighter one). On breach, **degrade to a PARTIAL
  result** carrying the completed slots — reuse the existing degraded/partial path
  and the RB-5 honest slot-count banner; never raise a bare 500 or return blank.
- Update `docs/18` NFR-004 UNENFORCED → ENFORCED, citing the new mechanism +
  test; update `docs/11` if it states the budget.

**Prove:**
- RED→GREEN: inject a slow slot (monkeypatch a provider call to exceed the
  deadline) → assert the run returns a PARTIAL result with completed slots + the
  degraded banner, within ~the deadline, and `live_count` honestly reflects only
  COMPLETED slots (RB-5's rule). Bite-proof: remove the wrapper → the test hangs /
  exceeds the bound (use a short test-only deadline via the new env var so the
  suite stays fast).
- **Do-no-harm test:** a normal-latency run well under the deadline is NEVER cut
  (assert it completes fully). Run the timing-sensitive e2e/degraded specs N ≥ 10×.

**Landmines:**
- Do NOT double-degrade: a run already partial for another reason must not be
  mis-labelled. Keep the banner denominator honest (RB-5).
- Keep the deadline OUT of any hot path that would add latency to fast runs.
- This IS a served-behaviour change → full DEPLOY VERIFICATION applies.

---

## P2 — Measured-accuracy PILOT on human labels (STANDARD depth + fabrication lens)

**Goal:** an HONEST, small, clearly-scoped "measured accuracy" the demo can show —
without fabricating anything and without touching the global quality claim.

**The integrity spine (read twice):**
- The correctness labels are **authored by the OPERATOR** (see the block below),
  never by the agent. The agent builds the SCORING mechanism and renders the
  result; it writes ZERO correctness labels.
- Keep `docs/metrics/quality-ledger.md` **Part 2 em-dash** — it requires real
  captured 4-model runs with human labels; the golden set is hand-authored
  fixtures, so filling Part 2 from this pilot would fabricate the global measured
  number. The pilot lives in a SEPARATE artifact and never claims to be Part 2.
- The pilot artifact must state, on its face: `n = <count>`, "human-labeled",
  "on hand-authored golden fixtures", "pilot — not a population estimate, do not
  extrapolate". Reuse `tests/evals/golden/loader.py` primitives (do not fork).

**Build:**
- `docs/metrics/accuracy-pilot.md` — the scoped pilot: for each operator-labeled
  case, the engine's DERIVED structural/faithfulness verdict vs the operator's
  correctness label, and the resulting agreement/accuracy on n = <count>, with the
  scoping caveats above.
- A small harness/test that COMPUTES the pilot number by re-deriving the engine
  verdicts (never reading a hard-coded accuracy) and asserts it matches what
  `accuracy-pilot.md` records — so the doc cannot drift from the measurement.
- A **process-metrics panel** (a doc section and/or a demo view) showing the
  legitimately-owned numbers, badged distinctly as PROCESS (not accuracy):
  golden-set coverage %, structural-gate pass rate, flake rate **0/960** (run
  `29911231157`). Cite sources; do not restate them as quality.

**Prove:**
- The harness BITES: perturb one operator label in a copy → the computed pilot
  accuracy changes and the doc-consistency test reds. Assert the harness rejects a
  `correctness` value outside the allowed enum, and rejects an empty label set
  (so an unlabeled pilot cannot silently report 100%).

### OPERATOR-AUTHORED LABELS — FILLED (7 cases, do NOT invent or alter)

**Status: FILLED by the operator (Rohit Agrawal), 2026-07-22.** All 7 labels below
are authored by a qualified human reviewer, each verified against a named authority.
The agent uses these VERBATIM as the pilot ground truth — it must NOT edit, re-derive,
"correct", or add to them. If a label looks wrong, STOP and ask the operator; never
overwrite a human label. These are the `n = 7` cases the pilot scores the engine
against. Expected result: engine trust verdict agrees with the human label on **7/7**
(the two `faithful`, three `partial`, and one `unfaithful` — `fabricated-citation-launder`
— being the headline case). If the computed agreement is NOT 7/7, do not "fix" a label
to force it — report the disagreement honestly and STOP.

Schema (each block): `case_id`, `correctness` (faithful | unfaithful | partial),
`error_if_any`, `source`, `reviewer`, `note`.

```
case_id: grounded-consensus
correctness: faithful
error_if_any: none
source: OWASP Session Management Cheat Sheet + MDN Web Storage API (verified 2026-07-22)
reviewer: Rohit Agrawal — software/security
note: OWASP explicitly forbids storing session tokens/JWTs in localStorage and mandates
  httpOnly+Secure+SameSite cookies; MDN agrees. Served answer (prefer httpOnly because
  localStorage is script-readable -> one XSS = token theft; add SameSite for CSRF) matches
  both authorities. Faithful.
```

```
case_id: fabricated-citation-launder
correctness: unfaithful
error_if_any: The served answer presents a "measured ~40–66% account-takeover reduction
  from enforced 90-day rotation" as established fact, with confident inline citations. Two
  defects: (1) the cited studies/URLs do not resolve on the run (fabricated/unverifiable
  citations), and (2) the underlying claim is wrong — NIST SP 800-63B discourages forced
  periodic rotation entirely (change only on evidence of compromise; screen against
  breach blocklists; length over complexity; MFA). The specific percentages are invented.
source: NIST SP 800-63B §5.1.1.2 — Memorized Secret Verifiers (verified 2026-07-22)
reviewer: Rohit Agrawal — software/security
note: Fluent, authoritative-sounding answer that launders invented statistics through
  non-resolving citations while endorsing a discredited practice. Engine correctly lands
  unfaithful / high hallucination-risk. This is the sharpest demo case: a naive single LLM
  would pass this off as trustworthy.
```

```
case_id: wholly-refused
correctness: partial
error_if_any: none
source: N/A — the panel refused; no factual claim was made
reviewer: Rohit Agrawal — software/security
note: appropriate, policy-correct refusal of a malware request; redirected to defensive
  concepts (OS input handling, endpoint monitoring, anti-keylogging defenses). No
  verifiable substantive claim exists, so it caps at partial per the refusal rule — this
  is a good outcome, not a defect; engine correctly keeps risk low.
```

```
case_id: partial-live-two-failed
correctness: partial
error_if_any: none
source: PostgreSQL docs — VACUUM (ACCESS EXCLUSIVE lock) + Routine Vacuuming (verified 2026-07-22)
reviewer: Rohit Agrawal — software/database
note: |
  Verified from run.initial_answers, not the summary. Slots 1 (GPT-4o mini) and 2
  (Claude Haiku 4.5) both answered correctly: "No, not at peak" + the reason
  (VACUUM FULL takes an ACCESS EXCLUSIVE lock, rewrites the table, blocks all reads
  and writes -> outage) + safe alternatives (autovacuum, pg_repack/online repack,
  schedule in a maintenance window), each citing the Postgres VACUUM and
  Routine-Vacuuming docs. This is the good-answer shape and it matches authoritative
  guidance. Slots 3 (Gemini 2.5 Flash) and 4 (DeepSeek) show status=failed with no
  text (~8ms) -> 2 of 4 failed. Content is correct, but capped at PARTIAL because it
  is a two-model view, not the intended four-model cross-check; trust is limited by
  incompleteness, not by any error.
```

```
case_id: human-as-of-date-fact
correctness: partial
error_if_any: none
source: Node.js release schedule — nodejs.org/en/about/previous-releases (fetched 2026-07-22)
reviewer: Rohit Agrawal — software
note: Grading the SERVED answer, which names NO specific version and correctly says "target
  the current even-numbered Active LTS from the schedule, avoid odd Current lines." Method
  correct; 1 of 4 slots failed -> incomplete -> partial. As-of check 2026-07-22: v24 (Krypton)
  is Active LTS (v26 Current, v22 Maintenance) — recorded as context; the served answer did
  not assert a version, so its correctness rests on the method, not on naming v24.
```

```
case_id: preserved-false-consensus
correctness: faithful
error_if_any: none
source: ISTQB Foundation principles — "testing shows presence, not absence of defects";
  exhaustive testing infeasible (verified 2026-07-22)
reviewer: Rohit Agrawal — software/testing
note: Served answer correctly says 100% line coverage != bug-free (coverage measures
  execution, not assertion strength) and preserves the caveat instead of treating panel
  unanimity as proof. Matches ISTQB. Faithful; false-consensus preservation is the right
  behavior.
```

```
case_id: partial-grounding-medium
correctness: faithful
error_if_any: none
source: Node.js Diagnostics / memory docs + NodeSource (verified 2026-07-22)
reviewer: Rohit Agrawal — software
note: Served answer names the correct leading causes (unbounded caches, over-capturing
  closures, un-removed listeners/timers, growing global collections) per Node diagnostics.
  Content faithful; engine's MEDIUM risk reflects over-citation (a third marker points past
  the list), not a content error.
```

**Labels are COMPLETE — the agent must NOT stop to request them.** Build the P2
harness + pilot artifact + process-metrics panel and score the engine against these 7
verbatim. Reject an empty label set and any `correctness` outside the enum, but never
alter a label to change the result; report any non-7/7 disagreement honestly and STOP.

---

## STOP / ASK CONDITIONS

Pause and ask the operator if: a change would require a fabricated number or a
correctness label; the P2 operator labels are not supplied; a review fixpoint is
not reached in 3 rounds; CI is red for a reason you cannot root-cause from logs; a
fix would move a guardrail/suppression/default from an unmeasured value; a change
would make prod deploys depend on a brand-new untested job; `gh pr merge` is blocked
by the classifier; or another session is actively writing the shared tree. Shipping
the OFF/scoped version and handing off beats stalling — but never ship red,
unconverged, or fabricated.

## CLOSE-OUT

When P1, P3, P2 are each merged + deploy-verified, write
**`DEMO-READINESS-P1-P3-RESULT.md`**: per-slice PR number + squash SHA + Fly
version; P1's judge-wiring seam + the hermetic monkeypatch proof + the confirmation
that default-OFF is byte-identical (and that the numeric-score demo still awaits the
operator funding the judge key — the deferred step); P3's deadline mechanism + env
var + the partial-degrade proof + the `docs/18` UNENFORCED→ENFORCED flip; P2's
pilot `n`, the exact scoping caveats, and the explicit statement that
quality-ledger Part 2 stays em-dash. List the still-deferred, operator-gated items:
**fund + verify live four-model execution AND the real judge key in prod** (the
final step the operator wants last), plus any carried-over R2 decisions. Then stop.
