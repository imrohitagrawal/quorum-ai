# Ultracode Prompt — Quorum-AI: issue #247, four models that were never invoked read as "4 of 4 aligned"

**Paste this whole file as the opening prompt.**

Shape follows `R2-S2-S4-ULTRACODE-PROMPT.md`, the repo's reference executable
(its contract is pinned by `tests/test_ultracode_prompt_enforcement_contract.py`:
real gate targets named in the Definition of Done, a literal Precondition, and
prime directives that carry the bounded-loop and no-guessed-threshold rules).

---

## 0. Plain English — what has been happening

The product asks four AI models the same question and tells the user how many
agreed. Recent work has been about one thing: **that agreement count has been
claiming agreement that does not exist.** Three items, with what the user saw
before and after.

**#193 — the "Source support" card. MERGED, live (`b0a8b2a`).**
- Before: a bare `75%`. Nothing said 75% *of what* — "3 of 4" and "15 of 20" are
  both 75%.
- After: the caption reads `3 of 4 answers came back carrying a primary source.`
- The counts went in the *caption*, not the value line, because the Agreement
  card sits beside it in the same three-up grid and its headline value **is** a
  bare fraction (`3 of 4`) measuring something unrelated.
- Found while building: `countOrNull("")` returned `0` (`Number("")` is a finite
  non-negative integer), which would have printed "0 of 4 answers…" — a
  measured-looking zero invented from a missing field. Never shipped.

**#180 part 1 — the caveat. MERGED (`9981bab`).**
- Before: a panel split **2-vs-2 in open disagreement** classified `strong`.
- After: `divided`.
- Cause: the disclaimer the product forces onto every synthesis contains the
  word **"support"**, and the disagreement detector keys on `support`/`oppose`.
  The system's own dictated words were scored as the models' opinions.
- The issue's premise was refuted mid-build by execution: `providers.py` has
  **0** occurrences of "decision support" — the mandate is in the *synthesizer's*
  prompt, at the END, while the scorer reads the FIRST 200 characters.

**#247 — THIS SESSION.**
- Before (live): with no funded API key the product calls nobody and fills all
  four slots with one template differing only by the model id. The scorer
  compares them, finds them near-identical, and reports **"4 of 4 models
  aligned."** It asks nobody, then says all four experts agreed.
- After (your job): a slot never sent to a model must not count as evidence of
  agreement, in either direction.

---

## 1. Precondition — do not start until these pass

**Verify by executing. Every line below is UNVERIFIED until you have run it.**
That rule has caught a false claim in every session that applied it, including
two in the session that wrote this file.

```bash
git fetch origin && git rev-parse --short origin/main    # expect 9981bab or later
gh issue view 247 --json state                            # expect OPEN
gh api repos/:owner/:repo/branches/main/protection \
  --jq '.required_status_checks.contexts[]'               # re-derive; never trust a table
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool | grep build_sha
```

Then reproduce the defect yourself before touching anything. **RED-proven means
you watched it fail, not that you read this file:**

```bash
cd <worktree> && UV_CACHE_DIR=.uv-cache uv run python - <<'PY'
import sys, itertools; sys.path.insert(0,"src")
from product_app import synthesis_consensus as sc
def sim(mid):
    return (f"Cross-check summary for {mid}: compare the cited evidence, "
            "preserve disagreement, and verify important claims before acting. "
            "This answer is simulated in local demo mode; the model was not actually invoked.")
texts = [sim(m) for m in ["openai/gpt-4o-mini","anthropic/claude-haiku-4.5",
                          "google/gemini-2.5-flash","x-ai/grok-4-fast"]]
gs = [sc._four_grams(sc._excerpt(sc._scoring_text.__wrapped__(t) if hasattr(sc._scoring_text,'__wrapped__') else t)) for t in texts]
for i,j in itertools.combinations(range(4),2):
    a,b = gs[i], gs[j]; print(f"pair {i}-{j} Jaccard={len(a&b)/len(a|b):.3f}")
print("threshold:", sc._OVERLAP_JACCARD_THRESHOLD)
print("partner counts:", sc._overlap_partner_counts(texts))
print("strong overlap:", sc._has_strong_overlap(texts))
PY
```

**Measured 2026-08-04 on `b0a8b2a`, and again with #180 part 1 applied:**

```
pairwise 4-gram Jaccard      0.500 – 0.579
_OVERLAP_JACCARD_THRESHOLD   0.1
_overlap_partner_counts      [3, 3, 3, 3]
_has_strong_overlap          True
compute_consensus_strength   "strong"
rendered                     "4 of 4 models aligned"
```

**Reachability:** live for any deployment without a funded key and for any
fallback to simulation. Latent in this repo's production only because live
execution is ON there — **check that, do not assume it.**

---

## 2. Mission

Make an answer that was produced **without invoking a model** unable to act as
evidence of agreement — neither finding partners nor becoming one — without
weakening the detection of genuine agreement, and without changing a single
test to make it pass.

---

## 3. Prime directives (NON-NEGOTIABLE — apply to every phase, every file)

1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud. A grep is not an execution: in the last
   session `grep UNMEASURED` matched a *message string* and missed the `exit 1`
   on the next line, producing a wrong verdict on two gates that were already
   fixed.
2. **If a premise you were handed turns out to be false, STOP and say so.**
   Never repair it silently. This happened twice in the last two sessions and
   both times the correction changed what got built.
3. **Write the input-class table BEFORE writing the fix.** Three consecutive
   fixes to a ~40-line predicate in this repo each introduced a new defect
   because each added a condition instead of tabulating the state space.
4. **NEVER change a test to make it pass.** The operator's instruction, and it
   binds. Two things that are *not* violations of it, and must be argued
   explicitly per test rather than assumed: correcting a **fixture** that builds
   a combination the product cannot produce (the assertion is untouched), and
   updating a **contract test** when the contract deliberately changes (which
   requires a new test pinning the new behaviour, plus an ADR). Deleting a test,
   lowering a threshold, or adding `# pragma: no cover` is always a violation.
5. **No guardrail value, weight, or threshold is set from a guessed number.**
   If the fix needs a similarity cutoff or a length bound, it ships from a
   measurement or it ships OFF with the activation queued to the human.
6. **The review loop is bounded: MAX 2 ROUNDS**, then STOP and escalate with the
   open findings listed. "Review to fixpoint" is never unbounded. Expect your
   own fix to introduce a defect — budget a round for it. If two fixes in a row
   add defects, change the approach.
7. **A mutation that does not bite is a finding, not a nuisance.** When a
   mutation leaves a test green, change the test's input until only the guard
   under test can reject it — or state plainly that no input isolates it. Three
   tests in the last two sessions proved nothing because an earlier guard caught
   the input first.
8. **Fan out for review, never for building.** Subagents share one working tree.
   Tell every reviewer **IN CAPITALS** not to write, edit, `git checkout`,
   `git stash` or `sed -i` anything, and to take its own copy with
   `git archive HEAD | tar -x -C <dir>` if it must mutate to measure.
9. **Prose is audited like code.** Verbatim in every reviewer prompt: *"for
   every number, superlative and causal claim in the diff's comments, commit
   body and PR description, name the command that produces it — or mark it
   UNVERIFIED."* Every false claim this project has shipped lived in prose.
10. **One CONCERN per pull request.** Branch in a dedicated `git worktree`,
    never the main checkout. Merge `main` in **before** starting.
11. **Ask before** pushing, opening a pull request, merging, deploying, or any
    paid API call. Commit locally freely.

---

## 4. Ground-truth codebase map (design against these real symbols; Read to confirm)

| Symbol | File | Why it matters |
|---|---|---|
| `_scoring_text(answer)` | `synthesis_consensus.py` | Added by #180 part 1. **The single place the population is built.** Your change almost certainly belongs here. |
| `_overlap_partner_counts` | `synthesis_consensus.py` | The clustering primitive. Skips empty n-gram sets already. |
| `_polar_split`, `_opening_majority_flags` | `synthesis_consensus.py` | Consume the same population. #180 part 1 moved the strip to the population level precisely so these cannot diverge. |
| `_OVERLAP_JACCARD_THRESHOLD = 0.1` | `synthesis_consensus.py` | Do not raise it. See §6 rejected alternatives. |
| `_local_simulation_text` | `providers.py:1311` | One template, differs only by `model_slot.model_id`. |
| `ProviderPath.LOCAL_SIMULATION` | `providers.py:81` | The obvious discriminator — **and it is not sound as written**, see §5. |
| `providers.py:546` | | Shows that branch can carry `live_response.answer_text`. |
| `safety.strip_own_caveat` | `safety.py:135` | Already handles the dictated caveat. Reuse, never reimplement. |

---

## 5. Phase 1 — plan, and get agreement before building

Produce a written plan. It must contain:

1. **The input-class table** for "may this answer count as evidence of
   agreement?", written before any code. Minimum classes: all-simulated;
   all-live-aligned; all-live-unrelated; mixed 2+2; mixed 3+1; mixed 1+3; a
   simulated slot carrying live text; failed slots; zero completed slots.
2. **The discriminator decision, with evidence.** `provider_path is
   LOCAL_SIMULATION` is the obvious choice and `providers.py:546` shows it can
   carry live text. Options: the path anyway; matching the template text; a new
   explicit field on `InitialModelAnswer`. **Measure which combinations are
   reachable — do not reason about it.**
3. **What demo mode should render**, decided together with the degraded-banner
   behaviour, not separately. Excluding simulated slots makes a keyless run say
   "weak"/"divided" and 0 of 4. Honest, and a visible product change.
4. **The test blast radius, re-derived.**

---

## 6. Phase 2 — evaluate every failing test BY EXECUTION (the core of the task)

When the fix is applied, **13 tests failed** (measured 2026-08-04; re-derive,
the number may have moved). For **each**, record:

1. The exact command and its **verbatim** output.
2. What the test asserts, in one sentence.
3. Whether the fixture it builds is **reachable in production** — prove it by
   finding the code path that produces that combination, or show none exists.
4. Verdict: `TEST CORRECT, PRODUCT WRONG` / `FIXTURE UNREPRESENTATIVE` /
   `TEST ENCODES THE DEFECT`.
5. What you will do, and which new test pins the corrected behaviour.

**What was measured on 2026-08-04 — re-derive it, do not inherit it:**

- **9 tests in `tests/unit/test_agreement_positions.py`.** Its `_answer` helper
  defaults `provider_path=LOCAL_SIMULATION` (line 65) while passing real,
  distinct answer text. The default looks incidental: no comment defends it, and
  the same file explicitly overrides it to `OPENROUTER_SEARCH` whenever the path
  matters (line 939). **Verify both line numbers and that claim yourself.**
- **4 tests assert the defect as correct.** `tests/unit/test_synthesis.py:78`
  says in a comment: *"identical, the consensus strength is 'strong', so
  `false_consensus_preserved` is now correctly False."* Also
  `tests/evals/test_synthesis_eval_checks.py`,
  `tests/integration/test_query_run_result_endpoint.py`,
  `tests/e2e/test_release_hardening_workflow.py`.

**Separability, measured:** with only #180 part 1's caveat fix and no simulation
branch, the suite was **2280 passed, 0 failed**. All 13 come from this half.

This phase is READ-ONLY and is the right place to fan out — one subagent per
failing test file, each returning the five-point record. Directive 8 applies.

---

## 7. Phase 3 — build (single writer), then review

**One sole writer applies all fixes.** If you must parallelise, use
`isolation: "worktree"` and only across genuinely disjoint files.

Then two lenses, **max 2 rounds** (directive 6). Two reviewers ≈ four; one is
worse (Porter et al., *IEEE TSE* 1997). Spend the difference on verification.

- **Lens 1 — correctness.** Break it. Refute by default; report only findings
  backed by a demonstrated failure. Point it explicitly at: **false negatives**
  (does the fix stop detecting *real* agreement?), the discriminator's
  soundness, every input class in the table, and whether each new test could
  pass against a wrong implementation.
- **Lens 2 — prose.** Directive 9, verbatim. In the last session this lens found
  8 false claims in 43, including three that would have landed on `main` in
  commit bodies.

**Verify every reviewer claim before acting on it.** Last session a reviewer was
right on four findings and the fifth needed narrowing; the session before, a
reviewer's grep-based verdict was wrong in both directions.

---

## 8. Cross-cutting gates & Definition of Done

`make quality` and `make validate` do **NOT** cover the merge gates. Run all of:

```bash
uv sync --all-extras          # NOT --extra dev: schemathesis lives in `quality`
make quality
make validate                 # includes make fr-completeness
make api-contract
make openapi-check
make security-scan
make perf-gate
make mutation-baseline        # advisory; open the log and find the number
git commit -a                 # COMMIT FIRST — rule 15a
make diff-cover DIFF_BASE=origin/main
```

e2e, exactly as CI runs it (or ~95 phantom failures appear):

```bash
lsof -ti tcp:18085 | xargs -r kill -9
rm -f .data/feedback_events.sqlite3
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
  npx playwright test <spec> --project=chromium --workers=1 --retries=0
```

**Done means:**

1. A written plan with the input-class table, agreed before building.
2. A per-test verdict for every failing test, each backed by a command and its
   verbatim output.
3. A test that would fail without the change, **proved by mutation** (`cp` aside,
   restore from the copy, `diff -q`; never `git checkout <file>`), with the
   verbatim failure captured. Every guard mapped to the mutation that reddens
   it — and any guard no input can isolate **stated as such, not claimed**.
4. Adversarial review, two lenses, max two rounds, every claim verified.
5. An **ADR** for both decisions (discriminator; what demo mode says), with a
   measured table and rejected alternatives, then
   `python3 scripts/generate_adr_index.py` — `make validate` fails otherwise.
   **Do not hand-edit the index.**
6. Every gate above green, `make diff-cover` included.
7. Merged **and** verified in production: the deploy **job** ran (not
   `skipped`/`cancelled` — read the job, not the run rollup), `/status.build_sha`
   equals the merged SHA, and the thing you built actually fires. A merge
   produces two runs; one is `cancelled` by concurrency dedupe, so resolve the
   **newest by `createdAt`**.
8. Cleanup: `git branch -f main origin/main`, delete the branch local **and**
   remote, remove the worktree. Final state: local `main` == `origin/main` ==
   production `build_sha`. State all three.
9. **Close more than you open.**

### Rejected alternatives — do not re-litigate without new measurement

- **Raise `_OVERLAP_JACCARD_THRESHOLD` above 0.579.** The module's own comment
  explains the 0.1 is deliberately low to catch "all four models answer the same
  factual question with slightly different wording", which scores in the same
  range. Trades a false positive for a false negative.
- **Change the simulation text so the four slots differ.** Cosmetic: it makes
  the score fall below a threshold without making the claim true. Four models
  still were not asked.
- **Suppress the alignment count in demo mode only.** Leaves the fallback-to-
  simulation path (a funded key that fails mid-run) still lying.

---

## 9. Suggested orchestration (workflow shape)

```
Phase 1  plan + input-class table            single agent, no writes
Phase 2  per-test verdicts                   FAN OUT read-only, 1 per test file
Phase 3  build                               SINGLE writer, dedicated worktree
Phase 4  review round 1 (2 lenses)           read-only, parallel
Phase 5  fix round 1 findings                same single writer
Phase 6  review round 2 (2 lenses)           read-only, parallel  — HARD STOP
Phase 7  gates, ADR, merge, deploy verify, cleanup
```

---

## 10. Standing traps — each costs about an hour if rediscovered

- **A pre-existing local failure that is not yours.**
  `tests/unit/test_evals_summary.py::test_run_suite_red_on_nonzero_exit_even_without_parsed_failures`
  fails locally under `make quality` with an ANSI-colour parse error. Verified
  identical on `origin/main`; CI's `pytest (Python 3.12)` is green. Deselect it
  only to produce a coverage report; never modify it, and re-verify it still
  fails on `main` before blaming your diff.
- **`e2e/tests/review/*.spec.ts` are gitignored local leftovers.** They make
  `test_no_orphaned_e2e_specs.py` fail in a dirty checkout and never in CI.
- **`/ui` returns 429** once repeated local e2e runs poison the durable per-IP
  daily mint cap. Presents as ~12 unrelated failures. Fix:
  `rm -f .data/feedback_events.sqlite3`.
- **A worktree has no `node_modules` and no `.venv`.** Symlink
  `e2e/node_modules` from the main checkout and **remove it before committing**
  — as a symlink it is NOT gitignored. Run `uv sync --all-extras`.
- **`make format` reformats test assertions** and breaks `sed`-style anchors.
  Grep for the real text before any programmatic edit.
- **Squash-merge with explicit `--subject` and `--body`.** A bare `--squash`
  concatenates every commit body onto `main`. And `not fixed: #N` in a merge
  body still **closes** #N — GitHub ignores the negation.
- **Process-global test state.** The cost event ring, the run-capacity semaphore
  and the model catalog are process globals. Use
  `tests/helpers.isolated_run_semaphore`.

---

## 11. Final report for human review (produce at the end)

Lead with status bullets, never an essay: **pushed or not, merged or not, done
or not, what is pending and who it waits on.** Then, in plain English: the
behaviour before, the behaviour after, what changed, and the next action item.
Then the evidence — commands and their output, the mutation map, and anything
still UNVERIFIED.

---

## 12. After #247 — the remaining backlog, re-derive it

`gh issue list --state open --limit 200`. As of 2026-08-04:

1. **#247** (this) — the only remaining item where a user is shown something false.
2. **#222** — landing CTAs below the fold. **Measured, decision pending:** the
   fold assertion passes in 1 of 6 viewports, live state only, default font
   only, CDN reachable only. `main` puts the CTAs at 874px on a 664px viewport;
   the fix moves them to 660. Recommendation on the table: merge the CSS but pin
   the gate at `<= 700px` (a density regression pin) rather than `<= 664px` (the
   fold), removing a `fonts.googleapis.com` dependency from a blocking merge
   gate and giving 21px of slack instead of 4.
3. **Money: #105, #122, #216** — one surface, one PR.
4. **Gate blind spots: #226** (16 violations, not the 20 in its title), **#224**.
5. **Test machinery: #209** (35 unfiltered sites, not the ~8 in its title),
   **#143, #145, #160, #167**.
6. Singletons: #203, #120, #134, #242, #146. **#166** is 6 of 7 done and
   proposed for closure — the last item is a decision the code already answers
   in writing.

**Unfiled, found 2026-08-04, fold into #222:** the visual-snapshot baseline lane
allows `maxDiffPixelRatio: 0.01`. On a 1440×3100 full-page shot a caption-sized
text change is ~0.002, so **wording changes pass the visual gate without human
review**. That is why #193 needed no baseline reseed. Mitigation is a text
assertion per surface, which is the existing pattern.

---

## 13. Read before touching anything

1. `AGENTS.md` — rules 3, 6, 6a, 11, 11a, 12, 14, 15a, 16d, 17, 17c, 18a, 19, 20.
2. `docs/adr/0009` — the #180 decision, its rejected alternatives, and the
   premise adversarial review refuted.
3. `docs/analysis/2026-08-03-major-issues-batch-result.md` — Addendum 2.
4. `docs/analysis/03-enforcement-machinery.md` — the gate register. Read a
   gate's charter before fighting it.
5. `docs/metrics/defect-discovery-audit.md` — **0 of 16** real `src/` defects
   caught by an automated check; **10 of 16** by adversarial review. Weigh any
   proposal to add a gate against this, and note what it implies about where to
   spend effort.
