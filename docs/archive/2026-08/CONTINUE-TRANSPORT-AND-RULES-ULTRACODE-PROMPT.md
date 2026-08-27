> **SUPERSEDED 2026-08-28 — do not execute.** This document was archived by the
> pull request that created `docs/65-open-work.md`. Its live items (W1, W15 and W16) were carried
> onto that board before it was moved here, and the board is checked against the
> tree by `scripts/check_open_work.py`. `docs/archive/` is excluded from this
> repository's doc gates, so nothing here is held to a live claim any more.
> Read it as history.

# Continue: provider transport (Track B) and the review-practice rules

Written 2026-08-26 at the close of the session that shipped Track A. This is an
**executable procedure** — a future session runs it. It lives at root by the
convention in `AGENTS.md` ("Where files live"), not in `docs/archive/`.

**There is a stale sibling at root, `CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md`.
IGNORE IT.** It is untracked, predates this work, and is not mine to delete.

---

## The prompt to paste into a fresh session

> Read the approved plan at
> `/Users/rohitagrawal/.claude/plans/is-it-advisable-to-fuzzy-quilt.md` in full, then
> read `CONTINUE-TRANSPORT-AND-RULES-ULTRACODE-PROMPT.md` at the repo root and
> implement what it says is pending, in the order it gives.
>
> Treat every claim in BOTH documents as INHERITED — re-derive state by command
> before acting. The last session measured that roughly half of what a handoff
> asserts does not survive contact with the tree, and its own approved plan was
> half wrong.
>
> **Track A is DONE and merged — do not rebuild it.** Read ADR-0075 before
> touching `synthesis_consensus.py`; it records a rejected alternative that looks
> attractive and is a measured false acceptance.
>
> Use the `work-package-protocol` skill. One work package at a time, merged before
> the next starts. Fan out for review, never for building.
>
> You may push, open PRs, merge and deploy.
>
> SPEND NOTHING. 2 paid OpenRouter calls remain of an authorised 10; do not use
> them without asking. `OPENROUTER_LIVE_EXECUTION_ENABLED` stays false everywhere
> including production. Do not move any money constant.
>
> For orchestration, follow the "Workflows: what to use where" table in the root
> document. Short version: use a workflow for every REVIEW phase and for B2's
> failure-mode enumeration; do not turn ultracode on.

---

## State, re-derived 2026-08-26 (verify it again anyway)

```
main == origin/main == production build_sha == d96e1150a4fc03158b14a2fe939f91d45291226e
live_execution: false          judge_enabled: true
worktrees: 1 (main only)       open PRs: 0       tree clean
next free ADR numbers: 0076, 0077, 0078
```

Open issues: **383, 382, 380, 379, 290, 268, 105**.
(382 and 383 were filed by the last session; both are pre-existing defects in
`synthesis_consensus.py`, neither introduced by Track A.)

---

## What is DONE — do not redo

**Track A shipped as PR #384, merged `d96e115`, deployed and verified.** But it
shipped **half** of what the plan specified, deliberately:

* **DONE:** the *stance* bar (the moderator's reading) is now
  `_required_cluster(N) = N // 2 + 1` on `len(stance)`. N=4 unchanged; N=3 2-vs-1
  now `strong` instead of `divided`.
* **REJECTED, with measurement:** applying the same rule to `_has_strong_overlap`.
  `_required_cluster` returns 2 at **both** panel size 2 and 3, so a "majority
  cluster" there is a **single edge**, and two answers reaching opposite
  conclusions form that edge from shared opening boilerplate — flipping
  `false_consensus_preserved` from True to False on a panel saying *approve* and
  *reject*. The overlap machinery is byte-identical to the pre-merge `main`.
  **`test_row12_...` pins this exhaustively. If you find yourself "fixing" it,
  read ADR-0075 first.**

The plan's Track A claim "proven identical at N=4, 0 of 256 vectors differ" was
**true** — and still pointed at the wrong conclusion, because N=4 being unchanged
said nothing about N=3. Expect the same shape of error in Track B.

---

## PENDING WORK, in order

### 1. Rules PR — small, researched, do it first (ADR-0076)

Three edits to `AGENTS.md`, all earned by measurement last session. A draft patch
script exists but was NOT applied; rewrite it, do not trust it verbatim.

**(a) New rule 9a — never move the tree under a running reader.** Rule 9 stops
reviewers writing; nothing stopped the *orchestrator* writing while readers ran.
Two false signals in one session:
* committing while a read-only planner was mid-measurement split its baseline
  across two trees;
* editing `synthesis_consensus.py` (+15 lines) during a backgrounded
  `make diff-cover` turned
  `tests/unit/test_not_invoked_is_not_evidence.py::test_classify_model_alignment_always_sets_invoked_explicitly`
  RED with `assert 'invoked=invoked' in 'def _opening_reflected_in_final(...)'` —
  `inspect.getsource` resolves by LINE NUMBER against the file on disk. Same suite
  on a stable tree: `3690 passed`.
Remedy to encode: give read-only agents their own `git archive HEAD | tar -x -C <dir>`
copy (extend rule 12b from mutators to READERS); either the gate runs or you edit;
**a full-suite failure in a file your diff never touched is a phantom until re-run
on a stable tree.**

**(b) Rule 10 re-graded.** Its finder cap traces to ONE row (1.1) in
`docs/evidence/2026-07-30-engineering-practice.md`, which the repo itself
**already downgraded to `ASSERTION`** ("an author list that wrong is proof the
primary source was not read"), and which records that no modern replication
exists. It measured HUMAN inspection teams in MEETINGS on 1997 C++. Applying it to
LLM agents transfers a result across populations — what rule 11 forbids.
What IS `WELL-EVIDENCED` is row 2.1: **precision 16.65%, recall 23.18%**
(SWRBench, arXiv:2509.01494v2). Recall 23% ⇒ one lens misses ~77%, so two is a
FLOOR not a ceiling. Precision 17% ⇒ ~83% of findings are noise, so verification
is the bottleneck. Keep "spend the difference on verification"; mark the cap
unmeasured for agents.
Session evidence: four agents produced four **disjoint** finding sets.

**(c) New rule 13f — never read a gate's success through a pipe.**
`make quality 2>&1 | tail -30` returns *tail's* status: it reported **exit 0**
while make failed `format-check` with Error 1. This bit **four times in one
session**. Use `make <target> > log 2>&1; echo "EXIT=$?"`. Related: `ruff format`
does not reflow docstring prose, so a >100-char docstring line passes
`format-check` and fails `ruff check` (E501); and `ruff check` printing
"All checks passed!" does not mean mypy passed after it.

**No workflow for this one.** Three prose edits already researched; a fan-out
costs more than it returns.

### 2. Track B1 — re-classify billing for in-band stream errors (ADR-0077)

**Blocking prerequisite for B2.** Under streaming, a mid-stream failure arrives as
**HTTP 200 + an SSE error event**; every branch in `_post_messages` keys on HTTP
status, so shipping streaming first would convert a possibly-billed failure into a
silently `measured` one.

Plan says: extend classification so an in-band error event maps to
`_DISPATCHED_UNMEASURED`, preserving the four-way return type and the
never-raises invariant; `_UNBILLED_HTTP_STATUSES` unchanged for pre-dispatch.

**Re-derive these premises before building — they are inherited and unverified:**
* the exact structure of `_post_messages`' classification branches (grep, do not
  trust the plan's line numbers — they moved twice already);
* that OpenRouter emits errors in-band under `stream: true`. AGENTS.md rule 8c
  already records that OpenRouter errors are **chunked, JSON, ~50 bytes,
  `Server: cloudflare`, no `Content-Length`**. One free `curl` with a bad key
  settles more than reading will.

**Money-adjacent ⇒ rule 16e applies: enumerate the known failure modes on one page
BEFORE writing code.** Bite-proofs must assert **cardinality** (rule 6b): a stubbed
stream emitting 3 deltas then an error yields exactly ONE `_DISPATCHED_UNMEASURED`
and ONE usage record. Keep the `product_app.providers.urlopen` seam — ~117 tests
depend on it.
**Trap, already recorded:** the repo's two `_http_error` doubles have EMPTY bodies
and do not say so (AGENTS.md rule 8a). Give every such test a REAL body and a
positive partner.

### 3. Track B2 — stream the provider call

Only after B1. Hand-rolled SSE parsing. Reuse `_read_within_budget`'s deadline
discipline. Usage arrives in the final chunk — preserve F-06 finding C (extract
usage BEFORE any empty-content guard). Leave `catalog_fetcher.py`, `readiness.py`
and Tavily on plain `urlopen`.
ADR-0029 sets the bar for adopting an SDK instead: **two measured failed attempts**
at the hand-rolled version. Record the attempts honestly; if hand-rolled SSE fails
twice, the OpenAI SDK pointed at OpenRouter with `max_retries=0` becomes correct.

### 4. Track B3 — the two timeout constants (ADR-0078)

**This is a STOP condition, not a build task.** Moving
`quorum_run_deadline_seconds` 180 → 300 and adding a ~45s per-call budget are
**guardrail values**. The plan's ~122s critical path includes an *estimated* ~37s
synthesis leg for a model that was never probed, and the sample is 2 reps, so the
true p95 is unknown. Present the numbers and **ask** — do not set a guardrail from
an unmeasured figure.

### 5. Small, separate — carry into whichever PR touches those files

* `providers.py:1735` and `:1745` reference `_bound_sniff_time`, which has **no
  definition anywhere** (verified). Doc-only fix; belongs with B1/B2.
* `catalog_fetcher.py:47` hardcodes the models URL instead of honouring
  `settings.openrouter_api_base_url`. Separate concern — its own tiny PR or a
  filed issue, not folded into B1.

---

## Workflows: what to use where

The last session ran one 14-agent workflow and it found **two REQUIRED_CONTRACT
defects that two hand-run lenses had missed**, including that its own "guard" test
pinned only one shape. Gates found **none** of the three design defects in Track A.

| Work | Orchestration | Why |
|---|---|---|
| Rules PR (item 1) | **Solo** | Three prose edits, already researched. Fan-out costs more than it returns. |
| B1 failure-mode enumeration | **Workflow** | Money code; rule 16e wants the list before the code. Enumerable space, parallelises cleanly. |
| B1 review | **Workflow** | Billing classification. Include a lens whose job is to *break* it (AGENTS.md "Review before done"). |
| B2 failure-mode enumeration | **Workflow** | SSE parsing has a known enumerable failure space: partial frames across chunk boundaries, keep-alive comments, the `[DONE]` sentinel, in-band errors, usage in the final chunk. |
| B2 review | **Workflow** | Largest, riskiest diff of the three. |
| B3 | **Solo, then STOP and ask** | A guardrail decision, not an implementation. |
| Any BUILD phase | **Never** | Rule 9 is mechanical: subagents share one working tree. |

### Recommended workflow shape (proven, with its two known flaws fixed)

```
Find     4 diverse lenses, read-only, schema-forced findings
Dedup    plain code, across all finders (a real barrier)
Verify   2 independent refuters per finding; a finding dies only if BOTH refute
```

**Fix these two before reusing it** — both cost real work last session:
1. **Sort findings by severity BEFORE capping.** The cap was applied in finder
   order, so 6 of 11 findings went unverified and a REQUIRED_CONTRACT could have
   been among them. Log what is dropped — never truncate silently.
2. **Give every agent a uniquely-named scratch dir.** Two agents collided in
   `/tmp`; one detected the contamination and had to redo its run.

Tell every agent **IN CAPITALS**: read-only, no `git checkout`/`stash`/`sed -i`,
own `git archive` copy for any mutation, no pytest in the shared tree, and
`PYTHONDONTWRITEBYTECODE=1` with `python -B` for mutation runs.

### Should the next session turn ultracode on? **No — recommendation.**

Ultracode is not a different engine; it is the same `Workflow` tool with a
*standing* default ("workflow for every substantive task, token cost not a
constraint"). Two reasons against it here:
* it spends on **finders** when the measured bottleneck is **precision** (~83% of
  LLM findings are noise);
* B3 must STOP and ask a human, and a standing "always orchestrate" default pulls
  against that.

Ask for a workflow per phase instead. That keeps a human in the loop between
phases, which is where every real decision in this work has been made.

---

## Traps measured in the last session — all cost real work

1. **Never read a gate's exit through a pipe** (bit 4×; see rule 13f above).
2. **Never edit the tree while a gate or read-only agent is running** (bit 2×).
3. **Mutation proofs need `PYTHONDONTWRITEBYTECODE=1` and `python -B`**, and a
   purged `__pycache__`. Two independent reviewers got FALSE mutation counts from
   stale `.pyc` files — same-size edits inside one second reuse the prior mutant's
   bytecode. Restore from a `cp` copy and `diff -q`; **never `git checkout`**.
4. **A merge fires several deploy runs; most are cancelled by concurrency.**
   Measured on this merge: **3 runs, 2 `cancelled`, 1 `success`**. Enumerate ALL
   runs for the SHA and read each Deploy **JOB** — never key on "newest" or "any
   completed".
5. **`make close-guard` before every merge**, with the text in the ENVIRONMENT.
   Never put a close keyword next to an issue number, *including* in a sentence
   saying you are not closing it — GitHub cannot read negation. Refer to
   "issue 382" without the `#` when in doubt.
6. **`e2e/tests/review/` (7 specs) exists only in the main checkout** and is
   gitignored at `.gitignore:60`. It reddens `test_no_orphaned_e2e_specs` locally
   while passing in CI. A fresh worktree does not have it.
7. **The advisory mutation gate is GREEN and it MEASURES.** Correcting a stale
   briefing: on PR #384 it scored `43 killed, 0 survived, 3 timeout (excluded),
   0 no-tests = 100.0%` against an 80% threshold. The `--cov-fail-under` leak is
   already fixed in `pyproject.toml:233-240`. **Caveat: timeouts are EXCLUDED from
   the denominator**, so a survivor could in principle hide there.
8. **A fresh worktree needs `uv sync --all-extras --python 3.12` first.** A bare
   `uv run` builds a 3.14 venv with no pytest.
9. **Doc line numbers rot within a single session.** Two citations moved under me
   between writing and committing. Reference symbols, not lines.
10. **Correct artifacts that have already left the repo.** Issue #383 was filed
    against a design later abandoned and kept asserting a constant that exists in
    no commit until review caught it. When you reset a design, re-check the
    issues, not just the code.

---

## Definition of done for each package

Merged AND verified running in production: Deploy **job** `success` (not the run
rollup), `/status.build_sha` equal to the merged SHA, and the built thing actually
firing. **Where the third is impossible, say so plainly** — Track A's stance branch
cannot fire in production because `debate.py:889` returns `None` while live
execution is off, so it is latent-correct, covered by tests and 43 CI mutants and
by nothing observable. That is an honest report, not a gap to paper over.

Then: local `main` fast-forward, delete the branch local **and** remote, remove the
worktree — worktree FIRST, then the branch.
