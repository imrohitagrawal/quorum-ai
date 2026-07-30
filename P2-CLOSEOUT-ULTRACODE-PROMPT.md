# P2 (measured-accuracy pilot) + demo-readiness close-out — ultracode continuation

> **How to run:** in a FRESH Claude Code session in the `quorum-ai` repo, send:
> **`ultracode continue P2-CLOSEOUT-ULTRACODE-PROMPT.md`**
> Read this file fully, then execute autonomously within the PRE-AUTHORISED scope
> below. The two things you must NEVER do: **invent, alter, or "correct" a value,
> rate, or human correctness label**, and **flip a suppression/safety default from
> an unmeasured value**. If `gh pr merge` is denied by the harness classifier,
> STOP and ask the operator — but TRY it first (it succeeded twice in the prior
> session once blocking checks were green).
>
> Everything here is hermetic ($0): no paid API call in any step. The funding +
> live-prod verification (real four-model execution AND the real judge key) stays
> DEFERRED and operator-gated — it is the very last item, listed under CLOSE-OUT,
> and you do not perform it.

## MISSION

1. **P2 — measured-accuracy PILOT (n = 7, operator-authored labels — embedded
   VERBATIM below).** Build the scoring harness + a distinctly-scoped pilot
   artifact + a process-metrics panel. STANDARD review depth + one fabrication
   lens.
2. **Close-out** — `DEMO-READINESS-P1-P3-RESULT.md`, factory console update,
   session handoff. Then stop.

**Do NOT re-open P1 or P3.** They are merged, deploy-verified, and reviewed to
fixpoint. No refactors, no "improvements", no re-review of merged code. If P2
work surfaces what looks like a P1/P3 bug, verify it by execution, then STOP and
report it — do not fix it inside P2's PR.

---

## GROUND TRUTH VERIFIED ON ENTRY (2026-07-22 — confirm, don't assume)

Confirm on entry: `git fetch origin main && git log --oneline -3 origin/main`
shows the two SHAs below; prod `curl -s https://quorum.stackclimb.com/ready`
returns `"state":"live"`.

- **P1 SHIPPED** — PR #72, squash `b2848e5`: real Layer-B judge wired into the
  request path behind `QUORUM_EVAL_JUDGE_API_KEY` + `QUORUM_EVAL_JUDGE_MODEL_ID`,
  default OFF (byte-identical, zero-I/O), per-run memoised (in-flight Future,
  one paid call per run), verified UI treatment fail-closed behind the exact
  verified shape + passed-state guard. Deploy JOB success; prod live. AC-049;
  `tests/integration/test_judge_request_path_wiring.py`.
- **P3 SHIPPED** — PR #73, squash `c663ad5`: NFR-004 run-level deadline
  ENFORCED (`quorum_run_deadline_seconds`, default 180, finite + (0,3600]),
  checkpoint-granularity degrade to honest terminal `timed_out` via atomic
  `transition()` (cancel wins), cut slots FAILED with
  `error_code=RUN_DEADLINE_EXCEEDED`. docs/18 NFR-004 UNENFORCED → ENFORCED.
  `tests/integration/test_run_deadline.py`. Deploy JOB verified per the protocol
  below.
- **Engine facts P2 builds on** (verify by reading, not memory):
  `tests/evals/golden/loader.py` (reuse its primitives — do NOT fork);
  `tests/evals/golden/cases/` (10 hand-authored cases; the 7 labeled ones below
  are a subset by `case_id`); `tests/evals/test_golden_set_gate.py` (structural
  gate — judge-OFF expectations assert band `unverified`/score `None`; P2 must
  NOT touch them); `docs/metrics/quality-ledger.md` Part 2 is an em-dash and
  MUST STAY an em-dash; `docs/metrics/operator-label-queue.md` (D5 queue).
- **Flake fact for the process panel:** flake scan **0/960**, run
  `29911231157` (recorded in #69). Cite it as PROCESS evidence, never as
  accuracy/quality.

## WORKING STYLE (non-negotiable — how the last eleven PRs shipped)

- **Evidence-first / no claim without a check.** Before asserting any cause,
  number, status, or config value, run the single cheapest command that
  confirms it. Say "UNVERIFIED hypothesis" out loud when you cannot.
- **TDD with a bite proof.** RED → GREEN → prove it BITES. **Revert mutations
  with a FILE COPY, never `git checkout <file>`.** Protocol: `cp src/x.py
  $SCRATCH/x.bak` → mutate → run the one test → `cp $SCRATCH/x.bak src/x.py` →
  `git diff --stat` clean. Commit the coherent unit BEFORE any mutation fan.
  Before trusting any bite result: `find src tests -name __pycache__ -type d
  -exec rm -rf {} +` (stale bytecode gives false green AND false red).
- **Fan the REVIEW, build SERIALLY.** Review lenses are READ-ONLY (say so in
  their prompts); give any executing lens its own `isolation: "worktree"`.
  Adversarially verify majors before acting; after fixes, re-review ONLY the
  fix diff. Majority refutation is not proof — confirm survivors by execution.
- **Never fabricate** a number, label, rate, or baseline. "Unmeasured" must
  never read as "clean".

## LEARNINGS FROM THE P1/P3 SESSION (apply them — each cost real time)

- **Local e2e needs the CI seam:** run Playwright with
  `SESSION_RATE_LIMIT_PER_MINUTE=600` or `/v1/session` 429s masquerade as
  product flakes (verified via trace, not assumption). CI already sets it.
- **First-request lazy init ≈ 1.7s:** warm the app (one full untimed request)
  before any timing-sensitive assertion.
- **Never `git add -A e2e`:** local darwin `*-snapshots/*.png` are artifacts
  (CI baselines are Linux); they polluted one commit and had to be amended out.
  Stage files explicitly.
- **Merging:** `gh pr merge <n> --squash --delete-branch` worked from the
  session once blocking checks were green (approvals required = 0). Try it;
  only ask the operator if the classifier denies it.
- **Deploy truth without flyctl:** local `flyctl` is unauthenticated. Verify:
  (1) CI/Tests/E2E for the squash SHA all completed/success
  (`gh run list --branch main --json headSha,... --jq` filtering
  `startswith(SHA)` — `--commit` silently returns nothing); (2) the
  LATEST-created "Deploy to Fly.io" run for the SHA has its Deploy JOB
  `success` (earlier cancelled runs are per-SHA concurrency, expected);
  (3) prod `/ready` state=live. **P2 has no served-asset delta — the Deploy
  JOB success + fresh release IS the deploy signal; do not hunt a UI change.**
- **Do NOT push anything to main until the merge SHA's CI finishes** (per-SHA
  concurrency cancels it).
- **openapi.yaml drifts when served-model docstrings change** — if the
  contract test reds, `uv run python scripts/export_openapi.py`.
- **Python ≥3.11: `concurrent.futures.TimeoutError` IS builtin
  `TimeoutError`** — never classify a timeout by exception type alone.

## SKILLS TO LEAN ON (deterministic routing first)

- Start with `make skill-route` and `make next` — follow the recommended
  driver skill as the single writer for each artifact (AGENTS.md V5 routing).
- **Plan before building:** enter plan mode (or an explicit task-breakdown
  pass) for P2's three deliverables before touching the tree; keep the plan's
  step→skill mapping visible in the todo list.
- `systematic-debugging` — on ANY unexpected red or flake before proposing a
  fix (it prevented two wrong turns last session).
- `e2e-testing-patterns` / `webapp-testing` — only if you touch a spec; P2
  should not need UI work (the panel is a docs section — see P2 spec).
- `taste-check` + `simplify` — on the finished harness code before review
  (quality pass, not bug-hunt).
- `deploy-checklist` — before and after the merge.
- Reviewer-style skills critique; they never overwrite the driver's artifact.

## PER-SLICE LOOP (same as P1/P3)

1. `git fetch origin main && git switch -c feat/p2-accuracy-pilot origin/main`.
2. Build per spec below. TDD, bite proofs (file-copy revert), commit the unit
   before the review fan.
3. Local gates, stop on first red: `make validate` · `make format-check` ·
   `make lint` · `make type-check` · `uv run pytest -q` · `make diff-cover`
   (≥95 on any changed src/test lines) · `cd e2e && npx playwright test --list`.
4. Review fan: STANDARD depth (2–3 read-only lenses + 1 executing lens in a
   worktree) **plus one lens whose explicit job is to find any place a label,
   accuracy number, or n is fabricated, extrapolated, or unscoped** — including
   "does any doc/table imply the pilot number generalises?". Fix findings
   test-first; re-review only the fix diff.
5. Push → PR → wait for blocking checks green; independently re-verify the
   rollup (`gh pr view <n> --json statusCheckRollup,mergeable` — the API is
   flaky; re-check on error).
6. `gh pr merge <n> --squash --delete-branch` (ask the operator only if the
   classifier blocks). No pushes to main until that SHA's CI finishes.
7. Deploy verification per the LEARNINGS block above.
8. Traceability: cite REAL, new-since-baseline, git-tracked, non-empty
   artifacts only.

---

## P2 — measured-accuracy PILOT (STANDARD depth + fabrication lens)

**Goal:** an HONEST, small, clearly-scoped "measured accuracy" the demo can
show — without fabricating anything and without touching the global quality
claim.

**The integrity spine (read twice):**
- The correctness labels below are **authored by the OPERATOR (Rohit Agrawal,
  2026-07-22)** and embedded VERBATIM. The agent builds the SCORING mechanism
  and renders the result; it authors ZERO labels. If a label looks wrong, STOP
  and ask — never overwrite a human label.
- **`docs/metrics/quality-ledger.md` Part 2 stays an em-dash.** It requires
  real captured 4-model runs with human labels; the golden set is hand-authored
  fixtures, so filling Part 2 from this pilot would fabricate the global
  measured number. The pilot lives in a SEPARATE artifact and never claims to
  be Part 2.
- The pilot artifact states ON ITS FACE: `n = 7`, "human-labeled", "on
  hand-authored golden fixtures", "pilot — not a population estimate, do not
  extrapolate".
- Reuse `tests/evals/golden/loader.py` primitives; do not fork them.

**Build:**
- `docs/metrics/accuracy-pilot.md` — for each of the 7 labeled cases: the
  engine's DERIVED structural/faithfulness verdict vs the operator's
  correctness label, and the resulting agreement on n = 7, with the scoping
  caveats above on the same page as the number.
- A harness/test that COMPUTES the pilot agreement by re-deriving the engine
  verdicts through the real evaluation engine (never reading a hard-coded
  accuracy) and asserts it matches what `accuracy-pilot.md` records — so the
  doc cannot drift from the measurement. Decide and document the explicit
  engine-verdict → operator-label agreement mapping BEFORE computing (e.g. how
  engine `faithfulness_label` maps onto faithful/unfaithful/partial), so the
  mapping cannot be tuned post-hoc to force a result.
- A **process-metrics panel** — a section of the pilot doc (and/or an existing
  metrics doc), badged distinctly as **PROCESS (not accuracy)**: golden-set
  coverage, structural-gate pass posture, flake rate **0/960** (run
  `29911231157`). Cite sources; do not restate them as quality. No UI change.

**Prove (hermetic, $0):**
- The harness BITES: perturb one operator label in a COPY → the computed
  agreement changes and the doc-consistency test reds (file-copy revert).
- The harness REJECTS: a `correctness` value outside
  {faithful, unfaithful, partial}; an EMPTY label set (an unlabeled pilot must
  not silently report 100%); a label whose `case_id` has no golden case.
- **Expected result: 7/7 agreement** (two `faithful`… see the labels; the
  operator pre-verified the engine agrees). **If the computed agreement is NOT
  7/7, do not "fix" a label or the mapping to force it — report the
  disagreement honestly, record the actual number in the artifact, and STOP
  for the operator.**

### OPERATOR-AUTHORED LABELS — VERBATIM (7 cases, do NOT invent or alter)

Schema (each block): `case_id`, `correctness` (faithful | unfaithful |
partial), `error_if_any`, `source`, `reviewer`, `note`.

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

**Labels are COMPLETE — do NOT stop to request them.**

---

## CLOSE-OUT (after P2 is merged + deploy-verified)

1. Write **`DEMO-READINESS-P1-P3-RESULT.md`** (repo root, committed via the
   P2 PR or a tiny docs-only PR — never a push to main):
   - Per slice: PR number + squash SHA + deploy verification evidence.
   - P1: the wiring seam (`_request_path_judge`/`_MemoisedRunJudge`), the
     hermetic monkeypatch proof, confirmation default-OFF is byte-identical,
     and that the on-screen numeric score awaits the operator funding
     `QUORUM_EVAL_JUDGE_API_KEY` + pinning the model.
   - P3: mechanism + env var + the partial-degrade proof + the docs/18
     UNENFORCED→ENFORCED flip (checkpoint granularity stated).
   - P2: n=7, the exact scoping caveats, the computed agreement, and the
     explicit statement that quality-ledger Part 2 stays em-dash.
   - The still-deferred, operator-gated items: **fund + verify live four-model
     execution AND the real judge key in prod** (one deliberate measured run;
     also closes #24 measured-cost), plus any carried-over decisions —
     including the follow-up question from P1's review: should
     `support_verified` also gate on judge-verdict CONTENT (needs a measured
     threshold, so operator-gated).
2. Update `docs/00-factory-console.md` (phase, next best action, validation
   status — the next action becomes the deferred funding step).
3. `make next` · `make skill-route` · `make handoff` (session continuity per
   AGENTS.md).
4. Then stop. Do not start the funding step.

## STOP / ASK CONDITIONS

Pause and ask the operator if: computed agreement ≠ 7/7; any change would
require a fabricated number or label; a review fixpoint is not reached in 3
rounds; CI is red for a reason you cannot root-cause from logs; `gh pr merge`
is denied by the classifier; another session is writing the shared tree; or a
P1/P3 defect is discovered (report, don't fix). Shipping the scoped version and
handing off beats stalling — but never ship red, unconverged, or fabricated.
