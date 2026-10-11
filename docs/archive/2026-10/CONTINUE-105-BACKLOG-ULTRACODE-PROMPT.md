> **Archived 2026-10-11** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Home-directory paths were replaced with `~`.

# ULTRACODE — rework #471, then work the verified backlog

**Written 2026-09-14. Self-contained: assume you know nothing about this repo.**

Read `AGENTS.md` first — **it overrides anything in this prompt.** Then
`docs/00-factory-console.md` and `docs/session-handoff.md`. Do not start from the code.

**Run the COMMANDS in this document, not the numbers.** Every figure here is paired with the
command that regenerates it. The session that wrote this shipped five wrong numbers, and every
one of them was transcribed from a document instead of re-derived. If a number matters to a
decision, run its command. If it disagrees with this file, **this file is wrong** — say so out
loud and fix it.

---

## 0. PRECONDITIONS — run these first, halt on any failure

```bash
cd ~/Projects/quorum-ai
test -e .env.bak-lane1 && { echo "HALT: a credential backup reappeared"; exit 1; }
git status --porcelain                      # expect: only untracked *-ULTRACODE-PROMPT.md files
git rev-parse --short origin/main           # expect 2813b40 or later
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution}'
git worktree list
```

Expected at hand-off: `live_execution` is **false**, three worktrees (`quorum-ai`,
`quorum-wt-105a`, `quorum-wt-debt014`), 1 open PR (#471), 11 open issues.

**A stale credential copy was deleted on 2026-09-14** (`.env.bak-lane1`, holding
`OPENROUTER_API_KEY`, `QUORUM_EVAL_JUDGE_API_KEY`, `QUORUM_TOKEN_SECRET`). Exactly one file on
disk should hold the key: `.env`. Verify with a **per-file** test, not `grep -r` — the recursive
form silently skips dotfiles and produced a false "0 occurrences" claim last session:

```bash
KEY=$(grep -m1 -E '^OPENROUTER_API_KEY=' .env | cut -d= -f2- | tr -d '"'"'"'\r' | xargs)
find . -type f -not -path "./.git/*" -not -path "./.venv/*" -not -path "*/node_modules/*" \
  | while read -r f; do grep -qF "$KEY" "$f" 2>/dev/null && echo "HOLDS KEY: $f"; done
unset KEY      # expect exactly one line: ./.env
```

If that prints anything other than `./.env`, **stop and tell the human.** Never delete a
credential file yourself.

---

## 1. HARD STOPS — ask every time, no exceptions

- **ANY paid API call or live run.** Money is never covered by any grant below.
  (`GET /api/v1/models` and `https://openrouter.ai/docs/llms-full.txt` are free and
  unauthenticated — those are fine.)
- **Opening, closing, extending or re-affirming a live-execution window**, or flipping
  `OPENROUTER_LIVE_EXECUTION_ENABLED` / `PEER_CRITIQUE_ENABLED`. **Never run `make close-window`
  on a date read from a document.**
- **Any merge whose `EXPECT_CLOSE` is non-empty** (i.e. it closes an issue).
- **Lowering a threshold, adding `# pragma: no cover`, or deleting a test to go green.** If it
  feels necessary, that is the signal to stop and say so.
- **Force-push, history rewrite, `git clean`, `git stash`.** Last session violated this one. The
  correct move to fix a pushed branch is a **follow-up commit**, which needs no force.
- **Anything touching secrets or credentials.**
- **Rule 12: if two fix rounds in a row introduce defects, STOP.** Do not patch a third time —
  do root-cause analysis and re-plan. This rule would have saved the most time last session.

## 2. STANDING AUTHORITY — you MAY push, PR, merge and deploy without asking, but ONLY when every
condition is objectively true. These are mechanical checks, not judgement calls. If you cannot
produce the command output for one, you do not have the authority — stop and ask.

1. **All required contexts green**, RE-DERIVED (never trust a table):
   `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`
   then confirm each is SUCCESS **on the PR head SHA**.
2. **`make diff-cover DIFF_BASE=origin/main` green on a COMMITTED tree**, and read its floor line
   — it states whether it measured lines, measured none because no `src/` Python changed, or
   measured none because the changed lines are comments. All three are honest; a silent pass is not.
3. **The blocking e2e lane, with CI's executed-count floors** (CI's numbers, not your local ones).
   If you add tests, RAISE the floor to CI's measured count.
4. **Adversarial fan-out COMPLETE: three independent read-only lenses — correctness, break-it,
   and rule-11a prose.** Every finding reproduced by you and triaged. ZERO outstanding reproduced
   CRITICAL_BLOCKER or REQUIRED_CONTRACT. **The prose lens caught what the other two missed twice
   last session — never drop it.**
5. **Every behavioural change has a test PROVEN to bite by mutation.** `cp` the file aside,
   mutate, run, restore from the copy, `diff -q` byte-exact. **Never `git checkout`.** Record the
   mutation and its result in the commit body.
6. **`make close-guard` passes with an EXPLICIT `EXPECT_CLOSE`**, set deliberately.
7. **After merge, enumerate EVERY Deploy run for the merge SHA and read each one's JOB** (a merge
   yields 3–5 runs; most are cancelled and the rollup lies), then confirm `/status.build_sha`
   equals the merge SHA.

---

## 3. WHAT HAPPENED LAST SESSION (so you do not repeat it)

Merged and verified in production: defect B (`a2f6bd2`), defect C (`a6770b2`), #460 (`920f19d`),
the `.jsonl` citation-gate fix (`29ec302`), DEBT-015 fee validation (`2813b40`).

**Three failures worth internalising — all were INFERENCES FROM TRUE PREMISES, not false facts:**

1. *"Every comparison against `nan` is `False`, so a bound cannot reject it."* Premise true;
   conclusion backwards. `ge=0` **does** reject `nan` — the comparison failing is *why*.
2. *"All 8 generations show 5 search results, so the fee is $0.0014 per result."* Premise true;
   conclusion refuted by the provider's published schedule. It is **$0.007 flat per request**.
3. A bound test pinned **samples** (`-0.0001`, `-1.0`) instead of the **boundary**, so
   `ge=-0.00009` passed all 12 tests while still admitting a negative fee.

**So: verify the CONCLUSION, not just the inputs.** When you write "X, therefore Y", run the
check on **Y**. And before reasoning about an upstream's behaviour, **go and look** (AGENTS.md
rule 8c) — one free unauthenticated fetch refuted #2.

**A fabricated approval was written and retracted.** The branch `feat/105a-activate-search-fee`
once carried a CHG-007 row, an ADR-0113 `Accepted` status and a commit message asserting a
product-owner decision that was never made. Retracted in `5d56a37`. **Never record a decision the
human did not make**; write PROPOSED/AWAITING in every place a reader could mistake for authority.

---

## 4. TRAPS THAT COST REAL TIME — all measured

- **Never read a gate's exit status through a pipe.** A pipeline's status is the last command's.
  Two steps: `make <t> > /tmp/g.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/g.log`
- **Diff-scoped gates need a COMMIT first.** `make diff-cover` and the citation gate read
  `origin/main...HEAD` plus the working tree; an uncommitted fix reads red (rule 15a).
- **`make format` relocates mutation anchors.** It collapsed a multi-line `Field(...)` onto one
  line and invalidated a whole mutation matrix. Re-run mutations against the FORMATTED source.
- **Mutate-and-restore inside one second can report a FALSE survivor.** `diff -q` proves the
  source is restored, but CPython's second-resolution mtime check reuses stale `.pyc`. Clear
  `__pycache__` between steps.
- **A mutation whose test did not run proves nothing.** A `-k "per_result"` filter did not match
  `..._one_rate_per_search_result`, so a live mutant looked like a survivor at EXIT=0. Confirm
  selection with `--collect-only` before trusting any mutation result.
- **`uv sync --all-extras` BEFORE `uv run` in a fresh worktree**, or pytest is missing and every
  test reports a bogus failure. A `git archive` copy has no git history, so ~12 shell-out gate
  tests fail for that reason alone — do not attribute those to your diff.
- **`e2e/tests/review/` is gitignored and makes `make quality` RED locally, green in CI.**
  Before blaming your diff, run `ls e2e/tests/review/`.
- **The visual lane fails 8/8 on darwin on clean main.** Never `--update-snapshots`.
- **e2e must run exactly as CI does** or ~95 failures are phantom:
  `SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 --workers=1`.
- **The findings-ledger gate refuses a proof pointer that is untracked.** `git add` the new test
  file before citing it in the debt register.
- **`timeout` does not exist on this macOS box.** Use `perl -e 'alarm shift; exec @ARGV'`.
- **A squash merge never shows as `--merged`.** Verify content landed on `main` by grep, not by
  `git branch --merged`, before deleting a branch.

---

## 5. PARALLELISM

- **Fan out WIDE for research and review; never for building.** Subagents share one working tree.
- Tell every reviewer **IN CAPITALS** not to write, edit, `git checkout`, `git stash` or `sed -i`
  anything, and to take its own `git archive HEAD | tar -x -C <unique dir>` copy if it must mutate.
  **Give each agent a DIFFERENT scratch path** — two agents pointed at one directory polluted each
  other's measurement by +11 tests.
- **Never move the tree under a running reader OR a running gate** (rule 9a). Either the gate runs
  or you edit, never both.
- One writer at a time. One CONCERN per PR (rule 17); merge before starting the next.
- Tell review agents: **never read `.env`, never make an authenticated or paid call.**

---

## 6. THE WORK, IN ORDER

Every item below was independently re-derived against the tree on 2026-09-14 by its own agent.
**Claim status is given because roughly half of what an inherited document asserts does not
survive contact with the tree (rule 11) — and three of these did not.**

### 1. PR #471 — rework it (branch `docs/debt-014-generation-endpoint-measured`, worktree `quorum-wt-debt014`)

**It is an open PR whose central claim its own author refuted.** It says the `:online` fee is
`$0.0014 per search result`. The provider publishes otherwise — free, unauthenticated:

```bash
curl -s https://openrouter.ai/docs/llms-full.txt | grep -n "per request. This includes up to"
curl -s https://openrouter.ai/docs/llms-full.txt | grep -c '0\.0014 per'   # -> 0
# (a bare `grep -c "0.0014"` prints 1: it matches a token price string `0.00000014`,
#  not a search fee — corrected 2026-09-14 after running it)
```

> "Exa search: Instant, Fast, and Auto cost **$0.007 per request** … **Includes up to 10 results,
> then $0.001 per additional result**"

So the fee **is flat per request**; results are **free up to 10**; `$0.0014` divides by a quantity
nobody bills. The derived risk claim ("a change in the default result count doubles our pin") is
also false — 5 → 10 costs **$0.0000**.

**The real, unpinned levers** are the exa **MODE** (`auto` $0.007 → `deep` $0.012 →
`deep-reasoning` $0.015, **2.14×**) and the **ENGINE** route (parallel basic $0.005). We set
neither. Nothing pins either.

**Reverting is not a loss — it restores consistency.** Tracked files across `src/`, `docs/`,
`tests/` and `.env.example` still correctly say flat/per-request — including ADR-0110's own
filename and title. **Re-derive the count rather than quoting one; it moves on every commit,
and note `-l` (files) and `-n` (lines) give different answers:**

```bash
git grep -n -iE 'flat.*fee|fee.*flat|per-request fee|per request fee|flat term' -- \
  src docs tests .env.example | grep -v debt-014
```

**Also fix these, all reproduced:**
- `ACTIVITY_EXPORT` in `tests/test_doc_gate_consistency.py` is **declared and never used**. So the
  gate never cross-checks the CSV, and a forged evidence file (`num_search_results: 500`,
  `$0.70` fee, ratio preserved) passes all five tests and the whole doc gate.
- The prose-to-data tie is a **bare substring match**. A row reading *"$0.007 FLAT PER REQUEST —
  it is NOT 0.0014 per result"* satisfies it. Make it structural (rule 8).
- `assert len(rows) == 8` reds on any legitimate evidence refresh.
- `"no max_results anywhere in src/"` is **false** — 7 hits, all `tavily_max_results`, a different
  provider. The true form: the OpenRouter request body carries only `model`/`messages`/`stream`
  plus optional `max_tokens`/`response_format`/`reasoning`.
- **ADR-0110 lines ~139–144 still say the endpoint "appears nowhere in this repo"**, contradicting
  the annotation ~95 lines above. DEBT-014's repayment cell still **orders the curl already run**.
- *"The endpoint carries NO web-search cost field"* has no positive partner — the committed JSONL
  is a whitelist, so by construction it cannot evidence absence. Commit the response's sorted KEY
  LIST (no values) to close this.
- Half the original alternative was silently dropped: **reading the fee off the COMPLETION
  RESPONSE is still unmeasured** (`providers.py` deliberately does not send `include_usage`).
  Label it unmeasured; do not claim it settled.

**Keep:** the fee cannot be read at estimate time (the endpoint needs a generation id that exists
only after a call — `400` without one), so a pinned number is unavoidable: **pin for the estimate,
reconcile afterwards.** And an independent derivation corroborates `$0.007`: `total_cost` minus
(native tokens × catalog price) is exactly `0.007000` on every row with a live catalog price.

**If the rework exceeds two rounds, close #471 instead** and record only the confident findings as
a comment on DEBT-014. That is a legitimate outcome, not a failure.

### 2. #105 / W24 — THE ONLY ITEM THAT BLOCKS LIVE EXECUTION (XS, but gated on a human)

The `:online` fee is priced at `0.0` while the measured charge is `$0.007` per searching call, so
every searching run's receipt and daily-cap booking are `4 × $0.007 = $0.028` light. **The daily
ceiling keys on the estimate, so under-charging under-protects it.**

**DO NOT ACTIVATE IT YOURSELF.** `docs/19-change-control-log.md` CHG-006 reads *"Pending
product-owner decision — the exclusion stands until they decide"*, and ADR-0110 reserves the
decision. The built-but-unapproved change sits on `feat/105a-activate-search-fee` (`5d56a37`).

The engineering prerequisites are now **clear**:
- DEBT-015 (validation) — **DONE**, merged `2813b40`.
- `_supports_online()` gating — **WITHDRAWN**: the fee is charged uniformly across four vendors,
  so suppressing it outside a hardcoded vendor list would make estimates too LOW. Do not build it.
- DEBT-014 (is the fee readable?) — **answered**: not pre-run; pin and reconcile.

So the remaining question is **purely the human's**: activate the fee at the same time live
execution is turned on, in the same PR, because before that it costs run capacity to prevent $0,
and after it every searching run books light. **Surface this; do not decide it.**

### 3. #290 — CLOSE AS STALE (XS). Rule 19: close more than you open.

Every load-bearing claim in it is **REFUTED**: the billing defect it calls unskippable is closed
at `query_run_orchestration.py:2928`, and the peer path exists at `debate.py:1407-1530`. Correct
`docs/65-open-work.md:240` in the same change. **Closing an issue needs a non-empty `EXPECT_CLOSE`
— which is a HARD STOP. Ask.**

### 4. #448 — the operator key goes through a bare `urlopen` with no redirect guard (M, safety)

The one **safety** rail on the list. Failure mode is an uncapped credential leak this app's spend
meter would never see; reproduced on loopback (the key reached the redirect target). Claim status:
**PARTLY** — re-derive before building.

### 5. #458 — `PEER_CRITIQUE_ENABLED` not coupled to the live window (M, gate-integrity)

**Carries the list's only check that goes RED when the bug is fixed** — a blocking e2e lane
asserts peer copy under a config whose default is `peer_critique_enabled=False`. Your global rules
forbid a test that locks in a defect, so this one is structural, not cosmetic. Code + gate only;
the doc half rides with #290.

### 6. #447 PIECE 1 ONLY — repair `_extract_citations` for the nested `url_citation` shape (S)

`src/product_app/providers.py:4267`. Measured waste on a **paid** path: one run carried 20 distinct
annotations and 40,479 characters of usable passage content that were dropped. **Split it** —
pieces 2–3 (carrying passage content to the judge) are L and push ~10KB of unbounded upstream text
onto a paid input, widening the exposure. Do piece 1 alone.

### 7–10 (in order): #467 (S) · #268 (M) · **W23 then** #464 (M) · #459 (S)

- **#467** — `scripts/session_handoff.py`'s `/status` probe has **never once worked**: an
  `AttributeError` is swallowed and reported as a network failure, in 11 of 11 generated handoffs,
  while the host answers 200 in 0.45s. Its covering test monkeypatches the broken function to
  `lambda: None`, so the gate is green over it.
- **#268** — debate output priced at 400 tokens against an enforced 4000 cap; users under-quoted
  ~3–4×. The issue's own "we cannot measure this" blocker is **itself stale** — check before
  believing it. **Do not** re-try the refuted fix (folding `prior_critique_input_cost` into
  `debate_prompt_tokens` flipped 9 of 495 mixes CONFIRM → BLOCK).
- **#464** — the mutation gate gets **greener as the diff gets bigger**; reproduced by execution
  (exit 1 at a 720-mutant scope, exit 0 at 1277 with the same latent survivors).
  **STOP — do not start #464 here. Read W23 in section 7 FIRST and fix it first.** W23 has no
  issue number, so it is invisible to `gh issue list`, and it is the root cause under both #464
  and #465: the gate dies before scoring a single mutant for any diff touching `/status`,
  `/ready`, `/ui` or `/v1/*`. Fixing #464 without W23 is fixing a symptom.
- **#459** — the live-posture watchdog runs every **2–7h** against a declared 30 minutes, and the
  header note that already corrects this is itself ~3× stale. Nothing is unmetered by it while
  `live_execution=false`, but it is the instrument for an unattended spend-capable posture, so it
  should land **before** any live window opens.

### DEFER: #469 (S) · #465 (M) · #447 pieces 2–3 (L) · #105/W14 (L)

- **#469** — confirmed byte-exact, but measured exposure is **zero** today (0 tracked
  `.tsx`/`.mdx`/`.pyi`, 0 divergent lines across all 5088 citations) and the failure is loud, not
  missed. **Do not "fix" it with a trailing lookahead or end anchor** — both silence a real broken
  citation, and both are pre-refuted in the issue.
- **#105/W14** — the titular 5xx reclassification. Deferred because its direction of error is the
  **SAFE** one: every 5xx forces `cost_source='estimated'`, over-stating spend. It closes on
  production logs, not a diff. And **W14 as specified is unclosable** — the 2026-08 window
  produced zero 5xx events.

---

## 7. WORK THE SURVEY COULD NOT SEE — and one of these outranks most of the issue list

The 11 GitHub issues are not the backlog. These carry no issue number:

- **W23** (`docs/65-open-work.md:120`, detail `:316-341`) — **the most consequential omission.**
  `mutmut` re-invokes pytest with node ids covering a changed function; schemathesis parametrises
  as `test_api_conforms_to_openapi_contract[GET /status]`, and **pytest cannot select a node id
  containing a space**, so the gate raises `BadTestExecutionCommandsException` and **dies before
  scoring a single mutant** for any diff touching a function reachable from `/status`, `/ready`,
  `/ui` or `/v1/*`. **Upstream of both #464 and #465.** Fix this before either.
- **W4** (`:102`) — PENDING, blocker already discharged. Collides with W7 on `main.py`/`app.js`.
- **DEBT-015 is marked RESOLVED but carries three live sub-findings**: `_actual_cost`'s catch-all
  swallows the cause; **there is no UPPER bound** (≥`1e24` raises an uncaught
  `decimal.InvalidOperation` — an outage, fail-closed); and `Settings` sets no
  `validate_assignment`, so runtime assignment bypasses the bound (unreached in production).
- **DEBT-016** — the CANCELLED slot's `billing_class` has no observable surface, so nothing pins
  it. Adjacent to the just-merged `a6770b2`.
- **DEBT-012** — the detection half is explicitly OPEN: one resolving ordinal launders any number
  of fabricated URLs to `faithful`. **#447 piece 1 feeds exactly this machinery** — read it first.
- **`docs/65-open-work.md:206-236` is a ~30-line STALE block** quoting `SOFT_THRESHOLD_USD = 0.15`,
  `HARD_LIMIT_USD = 0.25`, `DAILY_CAP_USD = 0.20`. The tree says `0.30` / `0.50` / `0.40`
  (`grep -n 'SOFT_THRESHOLD_USD\|HARD_LIMIT_USD\|DAILY_CAP_USD' src/product_app/costs.py`). It is
  the money-headroom reasoning a session would use to size #268 — **do not reason from it.**
  Worse: W3's own needle matches a **comment**, so the board's gate is satisfied by a substring
  inside a git incantation (rule 8, biting inside the gate that enforces the board).

---

## 8. DO NOT TOUCH

- `OPENROUTER_LIVE_EXECUTION_ENABLED`, `PEER_CRITIQUE_ENABLED`, or the fee constant — all need
  explicit human approval (rule 17b).
- `~/Projects/quorum-wt-105a` — another worktree. Read it; never write to it.
- `#268`'s refuted fix; `#469`'s lookahead/end-anchor; `#105/W14` as specified.
- The visual lane — never `--update-snapshots`, never grow `goldenCompletedResp()`.
- Stale numbers that must not be carried forward: **"5063 citations"** (now 5088, and it moves on
  every docs commit), ADR-0094's `cost_debate_output_tokens` 400, and the W3 cap block above.
- Re-running the 12m26s mutmut pass for #465 — the triage is already done (6 provably equivalent,
  19 logging shape, 10 real gaps).

---

## 9. HOW TO RUN THIS

Use a **Workflow** per phase, staying in the loop between phases:

1. **Understand** — parallel read-only agents over the item you picked; each re-derives the claim
   before you build anything.
2. **Build** — ONE writer, in a dedicated `git worktree`. Never fan out a build.
3. **Review** — three fixed lenses (correctness, break-it, rule-11a prose), read-only, each with
   its OWN scratch path. Reproduce every finding yourself before acting.
4. **Close out** in this order, every time: local gates green → merge (`gh pr merge --squash
   --subject --body`) → verify the deploy per condition 7 → `git merge --ff-only origin/main` from
   the main checkout → remove the worktree → delete the branch (local + remote).

**Close more than you open** (rule 19). #290 is a free close. Two of the eleven issues had claims
that did not survive contact with the tree — expect more.

**Report in this format, every time:**
`Done` / `Verified myself` / `Cleanup` / `Pending` / `Next action`.
Keep what YOU ran (with its output) separate from what a subagent reported. Say explicitly whether
work is pushed, merged, and running in production — never leave it inferred from silence.
