> **Archived 2026-10-11** (CHG-040 (c)). The process now lives in `.agents/skills/work-item-delivery/SKILL.md`; this file is history and is not to be run. Edits: home-directory paths replaced with `~`; the user name in a transcript folder replaced with `<this repo's project folder>`; 2 citations of a handoff since archived now name its archive path; 1 example path written as `<dir>/notes.jsonl`.

# ULTRACODE — work the backlog autonomously, and ask me everything you need up front

ultracode. You may use the Workflow tool for read-only fan-out.

I am away for about ten hours. **Your first act is to post the decision brief in
§6 as one message.** Then do NOT wait for me — start §5 immediately and keep
going. When you reach an item whose decision has not arrived, park it per §5's
protocol and take the next one. Ask nothing else; §2 is the only other place
you stop.

---

## 0. Read first, in this order

1. **`AGENTS.md`.** It overrides everything here on every technical rule, with
   ONE exception: §2 and §3 of this file are the explicit human approval that
   AGENTS rule 17b requires (push / open a PR / merge / deploy). I grant those
   in advance for this session, bounded by §2's hard stops. Every other AGENTS
   rule still binds.
2. `docs/00-factory-console.md` and `docs/session-handoff.md` (AGENTS requires
   both before editing).
3. `docs/archive/2026-09/2026-09-21-session-handoff.md` — the live narrative: what
   shipped on 2026-09-20/21, what is next, and eight measured traps.
4. `docs/65-open-work.md` — **the repo calls itself the source of truth and
   GitHub the mirror.** §5 below is written from the mirror, so reconcile.

Then run these read-only checks and halt on any surprise:

```bash
cd ~/Projects/quorum-ai
git status --porcelain     # expect only CONTINUE-*.md prompts (untracked)
git worktree list          # expect only quorum-ai (main)
git log --oneline -1       # expect 097a223 or later
curl -s https://quorum.stackclimb.com/status | jq '{build_sha,live_execution,peer_critique_enabled,peer_critique_in_effect}'
ls -lt ~/.claude/projects/<this repo's project folder>/*.jsonl | head -3
```

`live_execution` must be **false**. The last command is the concurrent-session
check: a transcript written in the last few minutes means another session may
be live even with no extra worktree — read its tail before taking work.

**Do NOT run `make handoff` here.** It writes `docs/session-handoff.md`. It
belongs at §9 only.

The root `CONTINUE-105-…` and `CONTINUE-268-…` prompts are **partly superseded,
not stale**: W23, #268's judge and debate halves, #290, #448, #467 and PR #471
are done; everything else in them is still open and restated below. Do not
delete them. **This file is the current plan.**

Run the commands, not the numbers. If a figure here disagrees with a command,
the command wins and you say so out loud.

---

## 1. What this session is for

Four things, in this order of importance:

1. **Close the mutation gate's false green (#464).** It is the check that says
   whether every other test is real, and it can currently pass having measured
   a fraction of its scope.
2. **Get the local gates honest (item 0)**, so "green" means something on this
   machine.
3. **Migrate decisions into the repo (item 1).** Decisions I made in session
   were never written down, so every fresh session re-asks them. That is a
   process defect and it is costing real time.
4. **Then the queue**, without me.

---

## 2. HARD STOPS — stop and write it in your report; do not ask twice

- Any paid API call or live run. `/status`, `/ready`, `/metrics`, `/ui/ops` and
  the free OpenRouter models endpoint are fine.
- Opening, extending or re-affirming a live-execution window, or flipping
  `OPENROUTER_LIVE_EXECUTION_ENABLED` / `PEER_CRITIQUE_ENABLED`. Editing
  `configs/live-execution-windows.json` counts.
- **Merging any change to a shipped money value.** Build it, gate it, open a
  DRAFT PR with the evidence — merging waits for me.
- Any merge whose `EXPECT_CLOSE` is non-empty, i.e. closing an issue.
- Lowering a threshold, adding `# pragma: no cover`, or deleting/exempting a
  test to go green.
- Force-push, history rewrite, `git clean`, `git stash`, anything touching
  secrets, and **`git add -A` at the repo root** — it swept my untracked prompt
  files into a commit on 2026-09-21. Stage named paths.
- **Recording a decision I have not made.** On any owner-gated branch every
  artefact says `PROPOSED — AWAITING OWNER`: the ADR `## Status`, any CHG row,
  the commit body, the PR title. Never "Accepted".
- Two fix rounds in a row that add a defect: stop, root-cause, re-plan, report.

Everything else — branch, build, test, review, push, open the PR, merge on
green, verify the deploy, clean up, next item — you do without asking.

---

## 3. Standing authority to merge, when ALL hold and you show the output of each

1. Required contexts re-derived
   (`gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`)
   and each SUCCESS on the PR head SHA. There are six; `validate-and-test`
   also runs `docker-build` and `make test-report`, which **have no local
   equivalent** — a locally green tree can still fail it, and that is not a
   mystery.
2. `make quality` and `make validate` exit 0 — read as two steps, never through
   a pipe (a pipeline reports `tail`'s status). See §8 for the two local-only
   red causes and what is acceptable evidence when they bite.
3. `make diff-cover DIFF_BASE=origin/main` green on a **committed** tree, floor
   line read. Run it **last**, right after a fresh `make quality`: it runs the
   full suite itself, and `api-contract` and the other pytest targets overwrite
   the coverage data underneath it. "No lines to measure" is honest only when
   no `src/` Python changed — the floor says which.
4. `make api-contract`, `make openapi-check`, `make security-scan` exit 0; the
   e2e lane per §8 if you touched UI, specs or fixtures.
5. Review complete: correctness, break-it and prose lenses, every finding
   reproduced **by you** and triaged, zero open CRITICAL_BLOCKER or
   REQUIRED_CONTRACT.
6. Every behavioural change has a test proven by mutation, recorded in the
   commit body.
7. `make close-guard` passes with an explicit empty `EXPECT_CLOSE`:
   ```bash
   PR=<n> EXPECT_CLOSE= MERGE_SUBJECT="…" MERGE_BODY="$(cat body.md)" make close-guard
   ```
   So write **`Refs #N`, never `Fixes/Closes/Resolves #N`**, in the PR title,
   the PR body AND the merge body — GitHub's parse of the PR is half of what
   the guard compares, and a closing keyword anywhere makes it refuse after
   you have already pushed.
8. **Finish and audit the PR body BEFORE the final push.** `ci.yml` fires on
   `edited`, so a `gh pr edit` afterwards re-runs the pipeline and a merge
   attempted meanwhile is refused.
9. After merge: enumerate every Deploy **run** for the merge SHA (2–5 per
   merge; the extras are cancelled by concurrency) and read each Deploy
   **JOB**, then confirm `/status.build_sha` equals the merge SHA.
10. Then comment on the issue with the merge SHA, the PR, what shipped and what
    remains, and list it in §9 as "fixed, awaiting your close".

---

## 4. How to use workflows

- **Read-only fan-out only**: Understand (re-derive an item's claims against
  the tree — roughly half of what an issue asserts does not survive that) and
  Review (three lenses + independent verifiers). **Never for building**:
  subagents share one working tree.
- Tell every agent **IN CAPITALS** not to write, edit, `git checkout`,
  `git stash` or `sed -i` anything in the repo or any worktree; never read
  `.env`; make no authenticated or paid call.
- An agent that must run or mutate code gets its OWN copy
  (`git archive <ref> | tar -x -C $D && mkdir $D/.git`, then
  `uv sync --all-extras`) and confirms `product_app.__file__` is inside it.
- Never edit the tree while a reader or a gate is running.
- Under 10 agents per workflow. Cap review at two rounds, then stop and report.
- Installed skills worth using rather than reinventing: `work-package-protocol`,
  `systematic-debugging`, `e2e-testing-patterns`.

---

## 5. The queue — work it in order, parking anything gated

**Money tag on every item** so there is no doubt which touch §2:
item 0 no · item 1 no · #464 no · #465 no (Tavily is an accepted cost
exclusion, ASSUMP-005 / D-011) · #469 no · **#268 YES** · **#447 YES** (paid
judge input) · **#458 YES** (eight critic calls per run instead of two) ·
W4/W5 no · W7 no.

**Parking protocol.** When an item needs a decision that has not arrived: push
the branch, open a **draft** PR carrying the evidence, leave the worktree in
place, record it in §9's Pending, and cut the next worktree fresh off
`origin/main`. Do not idle.

### Item 0 — make the local gates honest (no decision needed)

`make quality` and `make diff-cover` are red on this machine for two reasons
that are not anyone's diff. Fix one, work around the other:

- **`.uv-cache` is missing from `test_code_text_strips_js_comments`'s exclusion
  list** (`tests/unit/test_code_text_strips_js_comments.py`, ~line 179), while
  `Makefile:4` sets `UV_CACHE_DIR ?= $(CURDIR)/.uv-cache` — so the cache lands
  inside every checkout, including every new worktree. Measured: 12 minified
  offenders, all under it. Add the entry, with a comment in the same shape as
  the `playwright-report` / `test-results` entries already there for the
  identical reason. **This is not the §2 hard stop** — the rule-7 floor
  `assert len(targets) >= 1` is untouched — but prove both directions anyway:
  the 12 offenders gone AND a real repo `.js` still swept. Its own PR, first,
  because anything that blocks a merge is scheduled first.
- **`e2e/tests/review/` holds 7 gitignored scratch specs** that
  `test_no_orphaned_e2e_specs` finds with `rglob`. Never delete them and never
  exempt the test. They are untracked, so they do NOT follow you into a
  worktree — run your gates there, or on a clean `git archive HEAD` copy, and
  record that as your §3.2 evidence.

### Item 1 — migrate my decisions into the repo (no decision needed)

The process defect behind half this backlog: decisions I made in session were
never written into `docs/`, so the board, the handoffs and every fresh prompt
re-label them "undecided". Verified on 2026-09-21: W4 and W5 were decided in
substance and **none of it is in the repo**.

Create `docs/analysis/2026-09-22-decision-register.md` recording, for W4, W5
and W7, the owner's own words with their source, and clearly labelled
**RECONSTRUCTED FROM SESSION TRANSCRIPTS — AWAITING OWNER CONFIRMATION**:

- **W4 (variable panel size N ∈ {2,3,4})** — plan approved 2026-08-25; owner,
  2026-08-26: *"The two, three, or four-model flexibility was provided to the
  user. We cannot force the user to always select four panels… It was given as
  flexibility, not on a panel being cheaper."*; owner authorised unattended
  build 2026-08-31 (*"Real feature work, larger scope — if it doesn't fit
  cleanly in one package, say so and stop rather than half-ship it."*). Plan of
  record: `~/.claude/plans/i-think-you-did-quiet-stearns.md`
  §5 and work item 3; repo-side scope:
  `docs/archive/2026-08/CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md` package D.
- **W5 (quick-answer N=1)** — shape settled in that same approved plan: a
  distinct "Quick answer" mode keeping the answer, source support, citation
  coverage, safety notices and the cost receipt, dropping the agreement ring,
  verdict band, debate transcript and convergence-based trust. Owner excluded
  it from *unattended* work only because it sits behind W4.
- **W7 (Google sign-in)** — owner, 2026-08-31: *"unpinned, no reliable 'done'
  shape chosen yet, needs scoping with me first."* Note `CHG-003` (2026-06-17)
  moved durable accounts to a later enhancement and has never been reversed.

Then add one line to `docs/65-open-work.md`'s W4/W5/W7 narrative pointing at
that register, so the next session stops re-deriving this. **Do not** file a
CHG row or an ADR "Accepted" for any of them — that is my confirmation to give.

### Item 2 — #464, the mutation gate gets greener as the diff gets bigger

The gate stops at a wall-clock deadline and, having reached less of its scope,
reports fewer survivors and **passes**. Measured on two heads of one PR: 720
mutants in scope, 465 reached, 35 survivors, FAILURE; then 1,277 in scope, 249
reached, 0 survivors, SUCCESS. Nothing was fixed in between.

Fix in the issue's own order, cheapest first:

1. **A truncated run must not pass.** It already prints its own reach honestly
   (`UNMEASURED: … reached 249 of the scope's 1277`) and then exits 0 — the
   Makefile's report block raises only `if counts["survived"]`, and a truncated
   run with zero survivors hits a bare `return`. One condition closes it.
   **Ship this alone if the rest is big: it is the one that stops a false pass.**
2. **Make the scope match the diff.** The derivation is `define MUTMUT_SCOPE_PY`
   **in the `Makefile`** — its `changed_lines()` uses `git diff -U0`, so the
   issue's "inferred" line-range claim is now confirmed. `scripts/replay_mutation_scope.py`
   only MIRRORS it and is pinned identical by
   `tests/unit/test_replay_scope_matches_makefile_scope.py`; editing the mirror
   alone changes nothing and goes red on that differential test. Change both.
3. **Order the diff's own functions first**, so a truncated run still covers the
   change.

Raising the deadline is the weakest option — it moves the line without removing
the inversion. Read `docs/adr/0117-…` first: it records what W23 did and did
not change, and the contrast that matters — a module global gave a false
**100.0% / exit 0** where the same diff's honest control was **68.4% / exit 2**.

### Item 3 — #465, 35 surviving mutants in `_tavily_search`

Pre-existing, surfaced by #464's over-broad scope. Do it after #464 so the
verdict can be trusted. **Triage first, fix second:** for each of the 35, is it
uncovered behaviour or an EQUIVALENT mutant no input can distinguish? Uncovered
→ a test that fails without the behaviour. Equivalent → change the code so the
mutant is not GENERATED (ADR-0069's worked example), never a scope exclusion
and never a recorded exception. **Report the triage split in your running
report before writing 35 tests** — a previous 867-line PR was closed here as
disproportionate to an advisory gate's hole.

### Item 4 — #469, the citation gate reports a broken path nobody wrote

Prefix-truncation remains for `.tsx`, `.mdx`, `.pyi` and dot-suffixed paths
(`<dir>/notes.jsonl.gz` → `<dir>/notes.jsonl`). **`.md` is NOT affected** — it is
a listed extension the others truncate *to*. **Read the issue.** It rules out
the trailing `(?![\w])` lookahead (tried in #468 and reverted before merge: it
turns a loud misnamed failure into a silent skip). Direction: add the colliding
extensions to the alternation, longest-first. Proportionality:
`git ls-files "*.tsx"` → 0, so nothing is broken today — this is gate honesty,
not an outage.

### Item 5 — W4, variable panel size (BUILD AUTHORISED; one answer still owed)

I authorised this build (see item 1). What is missing is **how a user chooses
N** — FR-004 and AC-007 still say "four model slots", and the UI copy
hardcodes it. Question 4 in §6 asks it.

- **If my answer has arrived:** amend FR-004 + AC-007, file the CHG row, then
  build. `Field(ge=1, le=4)` appears at **four** sites — `debate.py:352`,
  `debate.py:456`, `debate.py:2180`, `providers.py:451` (the board's "three
  sites" and every line number in the older plans are stale — verify with grep
  before editing). W10 (ADR-0083) discharged the consensus primitive, and
  `.model-slot-grid` already reflows at N=2 and N=3.
- **If it has not:** park. Do **not** ship the "relax the backend only" subset:
  it was considered and rejected because it pins the very bounds the real
  design has to choose and ships a path nothing exercises.
- Known and settled: at N=2, consensus requires both models to agree
  (`_required_cluster` = `panel_size // 2 + 1`). Known and NOT settled: what
  the verdict band and trust copy may claim at N=2. Measured, and it undercuts
  the obvious sales pitch: N=2 is **15–30% cheaper, not 50%**.

### Item 6 — W5, quick-answer N=1 (shape settled; needs W4 and my go)

Build only if W4 has landed AND question 5 is answered yes. The shape is in the
approved plan (item 1 above). N=1 needs its own guard: `_opening_majority_flags`
returns `[True]` at N=1, so the panel path would call a single answer
"unanimous".

### Item 7 — #268's input half, `cost_web_search_context_tokens` (MONEY — propose, do not merge)

The judge and debate halves shipped (ADR-0114, ADR-0115). This one is still
2000 (`config.py:453`). Measured from
`docs/analysis/2026-09-10-telemetry-tokens.jsonl` on 2026-09-21: **48 readings,
43 above 2000**, median 2438, max 3160. Parse the JSON — a
`grep -o '"injected_tokens_est": *[0-9][0-9]*'` silently drops negative rows.

Sweep first, then measure, then propose. **No existing sweep covers this
constant**: `scripts/proofs/debate_output_band_sweep.py` hardcodes
`cost_debate_output_tokens` and `scripts/proofs/search_fee_band_sweep.py`
hardcodes `cost_web_search_request_fee_usd`. Write a third on the same shape —
print POSTURE and PRICE SOURCE before any number, offer `--fallback-prices`,
and refuse to run if the configured judge is missing from the price table.

**Unlike the debate constant, this one feeds the fail-safe bound.** Measured at
2900 on 2026-09-21: **7 of 715 mixes change band and 5 more become `block`**;
the default panel keeps 3 runs/day. So the autonomy rule in question 1 matters:
if it holds, merge; if it does not, park with the table.

### Item 8 — #447, the judge grades evidence it has never read (MONEY, BLOCKED)

Piece 1 shipped (PR #477). What remains is carrying passage `content` to the
judge: **Route A** (use the `:online` annotation content, no new network path)
vs **Route B** (a credential-guarded fetcher). **Build neither.** Two blocks,
both real: the choice turns on a measurement that needs a paid live run (a §2
hard stop), and ADR-0104 records that pieces 2–3 "need an input bound first
(#268)" — the value item 7 forbids merging. Shipping it early widens the paid
judge input that #268 is open about. Question 6 asks for the route.

### Item 9 — #458 and #459 (decisions owed; see §6)

#458: couple `PEER_CRITIQUE_ENABLED` to the live window so opening a window
stops silently switching critics on. #459: **its option 2 is NOT "refuse live
execution when the window lapses"** — that wording came from a handoff, not the
issue. The issue's two options are (1) correct the latency claim to the
measured 2–6 h band, which shipped, and (2) move the watchdog off `schedule`
onto something with a real latency guarantee. Read the issue before acting.

### Not ready

**#105** closes on ~7 days of production log collection, not a diff. **W7**
needs a scoping conversation with me.

---

## 6. The decision brief — post this FIRST, then carry on without me

Post one message containing these six questions, each with your own
recommendation and the measured consequence. Use my answers when they arrive,
at the next work-package boundary. Do not wait for them.

1. **#268's input half — may you merge a money value on your own, under a
   rule?** Proposed rule: merge only if the change is conservative, **no mix
   moves into `block`**, and the default panel's runs-per-day is unchanged;
   otherwise park with the table. *On today's measurement, 2900 fails that
   rule (5 new blocks) and you would park.*
2. **#458 — may you couple the flags without flipping them?** i.e. make the
   window scripts flip `PEER_CRITIQUE_ENABLED` with the live flag and add a
   test that peer ⊆ live, leaving `fly.toml` as it is. Recommended: yes — it
   removes the standing risk and changes nothing about production today.
3. **#459 — does it close on option 1 alone?** Option 1 (correct the latency
   claim) shipped. Option 2 is real work only if sub-hour detection is actually
   required. Recommended: close on option 1 unless you need sub-hour.
4. **W4 — how does a user choose N?** A visible control (remove/add a slot), a
   URL parameter, or not exposed at all — and the range to pin (`2..4` or
   `3..4`). This is the one answer that unblocks the build you already
   authorised. Give your recommendation and its consequence for FR-004/AC-007.
5. **W5 — build the quick-answer mode after W4 lands?** The shape is settled;
   this is a yes/no on sequencing.
6. **#447 — Route A or Route B**, knowing the deciding measurement needs a paid
   window and the input bound is unmerged. Recommended: neither yet.

Also tell me, in the same message: anything in §5 you found to be wrong when
you re-derived it, and anything you are parking.

---

## 7. Practices that are not optional

- **One concern per PR**, in a dedicated `git worktree` off fresh `origin/main`,
  merged and deployed before the next starts. Club issues only when they are
  the same concern on the same surface.
- **TDD with a bite-proof.** Test first; capture the VERBATIM red output; then
  fix. Prove every behavioural change by mutation: `cp` the file aside, mutate,
  clear `__pycache__`, run, restore from the copy, `diff -q`. Record each
  mutation and what went red in the commit body. Never `git checkout <file>`.
- **A test must be able to fail, and must test what executes.** Three ways this
  bit on 2026-09-21: a probe written to `tmp_path` sat outside the conftest's
  scope so the plugin under test never ran; a test asserted pytest's
  `--collect-only` summary while a real run behaved differently; and a
  single-mutant proof could not see a defect that only appears with two.
- **Two false-green mechanisms to watch for in this harness specifically:**
  a module global in a pytest plugin (mutmut calls `pytest.main` in-process
  then forks; parent state leaks into children, whose runs die and are dropped
  from the denominator — that is the 100.0% vs 68.4% pair), and
  `@pytest.mark.repo_introspection` on a FUNCTION, which is invisible to the
  guard that forbids silent exemptions because it reads MODULE-level markers.
- **Decisions get an ADR in the same PR** (`docs/adr/`, ADR-0002's shape) and
  `python3 scripts/generate_adr_index.py` — never hand-edit the index. Put any
  amendment note **below** the `## Status` value, or the posture checker reads
  that ADR as not live.
- **Correct the board in the same PR.** Only #464 has any board presence today
  (prose, ~line 397); #465, #469, #447, #459 and #458 have none — add a row
  with a needle that the fix must ADD or DELETE, never one it merely edits
  around. Re-stamp `Verified at:` if it is 60+ commits behind, and keep the
  unpinned-row count in the header true. `scripts/check_open_work.py --check`
  verifies all three, inside `make validate`.
- **Audit your own prose** (rule 11a): for every number, superlative and causal
  claim in the diff's comments, ADR, commit body and PR description, name the
  command that produces it or mark it UNVERIFIED. Tell your reviewers to do the
  same — on 2026-09-21 that lens found two false claims the code lenses missed.
- **When a design looks more accurate, compare each term, not the total.** A
  variant that matched a measured total better was cancelling two opposite
  errors (ADR-0115's rejected alternative).
- **Maintain `docs/00-factory-console.md`** after each meaningful step.
- **Close out in order:** gates green → findings resolved → `make close-guard`
  → `gh pr merge --squash --subject --body` → every Deploy job read and
  `/status.build_sha` checked → `git merge --ff-only origin/main` → delete the
  branch local **and** remote → remove the worktree → comment on the issue.

---

## 8. Commands that bite

- **Fresh worktree setup**, before anything else runs in it:
  ```bash
  uv sync --all-extras          # NOT --extra dev: schemathesis lives in `quality`
  cd e2e && npm ci              # only if you will run e2e
  ```
  A bare `uv run` in a fresh worktree builds a 3.14.5 venv with no pytest and
  `test_contract_gate_collection_floor` goes red naming contract collection —
  that is the environment, not your diff.
- **The mutation gate** is `make mutation-baseline DIFF_BASE=origin/main`,
  threshold `MUTATION_MIN_SCORE=80`. It is **advisory in CI**
  (`continue-on-error`, not one of the six required contexts) and blocking
  locally — so items 2 and 3 cannot make `main` unmergeable, and their remedy
  must stay proportionate. A run can take the full
  `MUTATION_RUN_DEADLINE_SECONDS=1440` (24 min), longer than any tool timeout:
  run it in the background and poll. Read its log for the NUMBER; a green job
  can mean "nothing in scope" and it says so.
- **e2e exactly as CI runs it**, or ~95 phantom failures appear:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  rm -f .data/feedback_events.sqlite3     # a 429-poisoned db fails ~12 specs
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <spec> --project=chromium --workers=1 --retries=0
  ```
- Never read a gate's exit status through a pipe:
  `make <target> > /tmp/gate.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/gate.log`.
- `timeout` does not exist on this box. Use your tool's own timeout.
- Commit before trusting `make diff-cover`: it measures the diff **plus** the
  working tree.
- A visual-lane failure on your Mac is expected (`-darwin` baselines are stale;
  CI compares `-linux`). Never `--update-snapshots` to go green.
- `/ui` answers 429 from this machine, so the served landing page cannot be
  read here; `/status` can.

---

## 9. Reporting

Lead with the answer, plain English, short sentences. End each work package
with `Done` / `Verified myself` / `Cleanup` / `Pending` / `Next action`, saying
explicitly whether it is pushed, merged and running in production. Keep what
YOU ran, with its output, separate from what a subagent reported. Never claim a
subagent's measurement as your own.

Before the session ends:

1. Write the narrative handoff at
   `docs/analysis/<today>-session-handoff.md`. **If a file for today already
   exists, write `-2.md` or update it in place — never overwrite it.**
   (the 2026-09-21 narrative handoff, then in `docs/analysis/` and since archived as `docs/archive/2026-09/2026-09-21-session-handoff.md`, exists; archive it only once
   yours is written.)
2. `make next`, `make skill-route`, `make handoff`.
3. List, explicitly: every item merged and verified in production; every item
   parked and why; every question from §6 still unanswered; and anything left
   uncommitted or unpushed.
