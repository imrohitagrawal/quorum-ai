# CONTINUE — fix the #290 readout, then spend the run once and capture everything

**Written 2026-09-08 by the session that shipped ADR-0104 and ADR-0105.**
Executable procedure. Read `AGENTS.md` FIRST — it overrides everything here.

**THIS SUPERSEDES `CONTINUE-HARVEST-AND-LIVE-RUN-ULTRACODE-PROMPT.md`**, whose
Items 2 and 3 are DONE and whose deadline is stale. That file has already been
**deleted** from the repo (commit `e7feef7`, on the user's explicit
instruction) — you do not need to archive it, and if you find it still at root
the deletion did not land. Recover it if you ever need it with
`git show 1899d49:CONTINUE-HARVEST-AND-LIVE-RUN-ULTRACODE-PROMPT.md`.

**The root prompt files that must NOT be deleted**, each verified 2026-09-08:
`R2-S2-S4-ULTRACODE-PROMPT.md` (the reference exemplar; pinned by
`tests/test_ultracode_prompt_enforcement_contract.py`,
`tests/test_findings_ledger_fs5_status.py`,
`tests/test_findings_ledger_consistency.py` and `pyproject.toml:168`),
`AUTONOMOUS-WORK-LOOP-ULTRACODE-PROMPT.md` (the generic template — carries no
work list, and is where this file's main-orchestrator / sub-orchestrator
architecture comes from), `REPO-HOUSEKEEPING-ULTRACODE-PROMPT.md` (named in
`AGENTS.md:739` as the worked example of a procedure correctly kept at root),
and `CONTINUE-OPEN-WORK-ULTRACODE-PROMPT.md` (the procedure for
`docs/65-open-work.md`, a board that is live: `python3
scripts/check_open_work.py --check` exits 0 and reads 17 needles from disk).

---

## RULE ZERO — THIS DOCUMENT IS A CLAIM, NOT A FACT

Every finding below was independently re-verified at HEAD `1899d49` by nine
read-only agents on 2026-09-08. **Three of the six original diagnoses were
corrected and one was REFUTED.** That is the base rate. Re-verify before acting.

If a premise turns out false, AGENTS.md rule 3 applies — **STOP and say so**.
Do not repair it silently.

---

## PREFLIGHT — mandatory, non-skippable, before you plan anything

**TRUST THE MACHINE-READABLE STATE. NEVER THE PROSE — INCLUDING THIS FILE.**

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git fetch -q origin && git rev-list --left-right --count main...origin/main   # expect 0 0
uv run python scripts/live_posture_check.py > /tmp/p.log 2>&1; echo "EXIT=$?"; cat /tmp/p.log
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
gh issue list --state open --limit 50
ls docs/adr/ | tail -3
ls e2e/tests/review/ 2>/dev/null   # non-empty => make quality is RED locally, not your diff
```

Read the window's expiry and `last re-affirmed Nh ago` **from the watchdog's
output**, never from a document. Then state out loud which of this file's claims
are dead.

**A measured trap, not a hypothetical.** The superseded prompt hard-coded an
expiry of `2026-09-08T07:51:25Z`. ADR-0103 moved it to `2026-09-11T07:51:25Z` in
the very commit that added the prompt. **Three human-written re-affirmation
comments on #290 still quote the stale date**, so a grep-based cross-check
*confirms the wrong answer*. Only `configs/live-execution-windows.json` and the
watchdog are right.

### Three things that will destroy value if you get them wrong

1. **NEVER run `make close-window` on a date read out of a document.** It makes
   both edits atomically (flag → false, expires_at → now). Doing it on the stale
   date would kill, in one command, the window ADR-0103 extended *specifically*
   so the paid run could happen. Reopening is an owner decision.
2. **NEVER post a `REAFFIRM` comment yourself.** Workflow tokens are typed `Bot`
   and refused, and self-serving the token defeats the one mechanism proving a
   human attends a spend-capable posture. The real deadline is the **24h
   cadence**, not the window expiry. If it lapses: escalate, do not self-serve,
   and do not read the lapse as "the window is gone".
3. **`/status` will convince you the paid run already happened. It did not.**
   Money *was* spent today (`global_daily_spend_usd 0.0961`,
   `last_live_charge_at 2026-09-08T08:43:14Z`) — but the annotation capture
   merged at **12:52:33Z**, four hours later. **Zero paid runs have hit the
   capturing build.** An agent that greps `/data` and reports "annotations carry
   no content" has stated a fact about BUILD AGE as a fact about the provider.

---

## ARCHITECTURE — orchestrator, then one owner per work package

- **Main orchestrator** (you): selects the package, runs the preflight, owns the
  branch and the merge, and is the ONLY writer to the shared tree.
- **Sub-orchestrator per package**: owns one work package end to end — plan,
  build, gate, hand back. One at a time against the shared tree.
- **Review fans out, building does not** (AGENTS.md rule 9). Subagents share one
  working tree. Tell every reviewer **IN CAPITALS** not to write, edit,
  `git checkout`, `git stash` or `sed -i` anything, and to take its own
  `git archive HEAD | tar -x -C <dir>` copy if it must mutate.
- **Never move the tree under a running reader** (rule 9a). Either the gate runs
  or you edit — never both.
- Give every reviewer this verbatim (rule 11a): *"for every number, superlative
  and causal claim in the diff's comments, commit body and PR description, name
  the command that produces it — or mark it UNVERIFIED."*

---

## WORK PACKAGE 1 — the #290 readout (ONE PR, by the owner's ruling)

**The owner has ruled that all six ship as ONE PR**, overriding AGENTS.md rule
17 (one concern per PR). Recorded here as their decision, not an oversight.

An adversarial lens argued the split and concluded **do not split** — buy the
reviewer separation directly instead, which is cheaper than rule 17d's re-gate:

1. **Isolate the threshold change as one self-contained commit** inside the PR.
   Squash collapses it on merge, but the PR's commit list is what a reviewer
   reads, and `git show <that commit>` is what a dedicated reviewer is pointed at.
2. **Dispatch a separate threshold reviewer** with a written charter (below).
3. **Ship the consistency gate in the same commit as the threshold move.** This
   is the change that converts an un-gated sweep into a gated one, and it is why
   the bundle is safe.

### 1.1 The coverage target does no work — CONFIRMED, with corrections

`CITATION_COVERAGE_TARGET = Decimal("0.80")` (`providers.py:83`). The metric is
`sourced_answer_count / answer_count`; the product **refuses any slot list that
is not exactly 4** (`model_slots.py:314`), so the denominator is 1–4.

| n | attainable | meets 0.80 |
|---|---|---|
| 1 | 0, 1.00 | 1/1 |
| 2 | 0, .50, 1.00 | 2/2 |
| 3 | 0, .33, .67, 1.00 | 3/3 |
| 4 | 0, .25, .50, .75, 1.00 | 4/4 |

**Corrections to the loose framing:**
- "Unattainable" is wrong — 4/4 attains it routinely. The precise defect is that
  the target has **no attainable intermediate state**: it cuts a 5-valued space
  at exactly the point a 100% rule would. **The 80% number is doing no work.**
- Identical to a 100% gate for n ≥ 1 only. At n = 0 an early return hardcodes
  `target_met=False` (`providers.py:4155-4160`), which 0/0 does not mean.
- **The comparison runs on the 2dp-QUANTIZED ratio** (`providers.py:4165`). A
  target of `0.67` is met by 2/3 only because `0.666…` rounds UP. **Choose any
  replacement against the quantized values, not the true fractions.**

**Two tests lock the defect in, and one is load-bearing evidence:**
- `tests/unit/test_citation_coverage_semantics.py:229`
  `test_three_of_four_sourced_still_misses_the_eighty_percent_target`
- `tests/unit/test_provider_stubs.py:112` proves the bar is clearable below 100%
  **at `answer_count=5` — a shape the product rejects** — and
  `docs/18-requirement-traceability-matrix.md:24` names that file as
  **TEST-NFR-003's evidence**.

**No test references the constant by name.** The risk-constant pin gate does not
cover it.

**The target does NOT move the trust score.** Measured with only the constant
changed: composite `93.25` on both sides, `target_met` flipped. The score is a
function of the *ratio*; the target drives `target_met` and the prose hanging off
it. Do not claim otherwise.

**Proposed rule** (the owner's 2-of-3 case must pass):
`sourced_answer_count >= max(1, answer_count - 1)` → 1/1, 1/2, **2/3**, 3/4.
Measured: breaks **exactly one** test (the one above). 2/4 still fails, so the
metric keeps a real failing case.

**Fix surface — all of it moves together or the PR ships a contradiction:**
`providers.py:83, 222, 4155-4160, 4168`; prose at `providers.py:200, 4121`,
`synthesis.py:278` (**an LLM system prompt**), `:1206`, `:1310` (**user-facing
copy**), `query_run_orchestration.py:400`, `feedback_audit.py:420` (**an LLM
audit prompt**), `evaluation.py:1150`; ~13 `target_ratio` literals across e2e
fixtures/specs; `openapi.yaml` default; and the "80 percent" prose in **NFR-003,
AC-031** and `docs/114-success-metrics.md`. Check whether NFR-003's ALERT line
("two consecutive review batches below 80 percent") stays coherent.

**The gate to add:** one test importing the constant and asserting every
downstream copy equals it. Prove it bites by mutation (`cp` aside, restore from
the copy, `diff -q` — **never `git checkout`**). State plainly what it cannot
see: it proves the copies moved *together*, never that the new value is *right*.

### 1.2 Slot labels — PARTIALLY CONFIRMED, and it is a PROMPT change

`debate.py:1599` is **not** the round card. It is `_peer_digest`
(`debate.py:1566`), whose output is `DebateOutput.critique_text` with **four**
consumers: round 2's prompt (`debate.py:1107`), the synthesis excerpt, the round
card (`app.js:5087`) and the markdown export (`app.js:3247`). **Relabelling it
changes text a model reads.**

**REFUTED:** the idea that the critic was never told the model names. The critic
prompt already renders `- Slot 2 — Claude Haiku 4.5 (completed): …`
(`debate.py:1829`, label from `answer.display_name or answer.model_id`). The
model writes "Slot 1 claims…" because slot-numbering is **mandated** by
`MODERATOR_STANCE_INSTRUCTION` (`debate.py:156-170`, requires `{"slot": N}` and
"include every slot exactly once") and `_peer_critic_directive` (`:1404`).

So the fix is: add an instruction about **prose** naming while leaving the JSON
`positions` contract on slot numbers. `SlotCritique` carries `critic_model_id`
but **no display-name field** — check what the card can actually render.

### 1.3 The trust score is unexplained — CONFIRMED

96 is a weighted composite over seven signals (`LAYER_A_WEIGHTS`,
`evaluation.py:1105`); the judge is a **gate** (`support_verified`), not the
scorer. Verified arithmetic: coverage 0.75 with all else at 1.0 → **96.25 → 96**,
the coverage signal costing 3.75 points. Bands: <50 low, <75 moderate, ≥75 high.

`trust.diagnostics.contributions` is **already served** (`openapi.yaml:1709`) and
**already read** by `app.js:4222` — but only rendered as up-to-3 **negative**
lines for contributions < 1.0. **The data for the explanation exists; only the
display is missing.** No API change needed.

Rename the headline too: "96 of 100 — high trust" should name the scale and what
was checked.

### 1.4 Round 2 shows as running only after it finished — CONFIRMED

`query_run_orchestration.py:1305-1310` marks `debate_round_1` RUNNING, then calls
the debate service **once** — which runs *both* rounds internally
(`debate.py:983`, `:1102`) — and only on return fires round_1 COMPLETED, round_2
RUNNING, round_2 COMPLETED in a burst. Round 2 is marked running **after it has
already finished**. The UI is truthful about what it is told; it is told late.

Establish how the UI learns stage state (poll vs SSE) before choosing between a
callback from the service, splitting the orchestration call, or emitting the
transition before dispatch. Name the risk of each.

### 1.5 The wall of text — PARTIALLY CONFIRMED, and my original fix was WRONG

**Do not "fix" this by joining with `\n\n`.** The renderer sets `breaks: true`,
so a single `\n` already becomes `<br>` and the `Slot N:` rows *do* land on
separate lines. That change fixes almost nothing.

**The real cause** is `_one_line()` collapsing each critique's own headings,
blank lines and bullets, plus a ~4000-char cut mid-sentence.

`_one_line`'s docstring records that it is a **prompt-injection defence** for a
line-delimited list the *model* reads (`debate.py:1829`). **A fix must not weaken
that path.** The bug is reusing a prompt-safety control on the display path.

**Also:** `app.js:5146` already renders each critic's **full, untruncated**
`slot_critiques[].critique_text` through `setProse` *below* the digest. So the
transcript carries a redundant flattened digest above correctly-rendered full
critiques. The surface showing only the flattened digest is the **live** round
card (`app.js:1801`). Consider whether the digest belongs on the transcript at all.

**Carry this forward:** the blocking rendering gate is **structurally blind** to
flattened markdown — its heading/bullet/blockquote patterns are line-start
anchored, so a flattening surface leaks literal `##` and `- ` into text nodes
with the gate green.

### 1.6 Per-slot answers are a wall of text — **REFUTED**

Per-slot answers are **not** flattened or truncated anywhere between the provider
and `setProse`. If the owner still sees a wall there, the cause is elsewhere —
most likely provider output that genuinely contains no markdown. **Reproduce it
on the live run before changing anything.** Do not carry the original claim
forward as fact.

### 1.7 Found during verification — the session trail mislabels restored runs

`restoreTrailRun` (`app.js:5609`) receives only a `runId` and never the entry's
own question; at `:5623` it falls back to `state.liveQueryText`, which is set only
on submit (`:7722`). **Restoring an earlier run relabels it with the most recent
run's question** — the UI says "You asked" above the wrong question.

Smallest correct fix: store the full question on the trail entry (it is
in-memory only, `sessionTrail: []` at `:266`, never persisted, never sent to the
server — do **not** put it on the API payload), pass the entry rather than the
id, and delete the `answer_text.slice(0,120)` fallback (unreachable today, one
refactor from printing a model's answer under "You asked"); render the existing
empty-question treatment instead.

**The test that must go red:** extend
`e2e/tests/invariants/session-trail.spec.ts` — it already has a two-run driver at
`:195-213`. Drive both, click the FIRST entry, assert `#result-question` and the
exported Markdown's `**Question:**` line. Reverting the wiring turns it red. Give
it a positive partner (rule 7) so the fix cannot be "always render —".

---

## WORK PACKAGE 2 — THE LIVE RUN. CAPTURE EVERYTHING, ONCE.

**The owner's instruction: when the live run is done, ALL of this data must be
captured.** The run is the scarce resource — 2 session mints per IP per 24h, real
money, and a window that expires. Engineering time is not scarce; the run is.

> **Anything not captured during the run costs another run to obtain.** On
> 2026-09-06 measurement 3 was lost for exactly this reason, and recovering it
> cost this entire cycle.

### Preconditions — all four, verified, immediately before spending

1. Work package 1 merged **and deployed** — `/status.build_sha` equals the merge
   SHA. A run against a build without the fixes cannot evidence them.
2. Watchdog `EXIT=0`, window not expired, cadence not lapsed.
3. **The owner's explicit go for the money**, re-confirmed at that moment. The
   17b override covers push/PR/merge/deploy; it does **not** cover money.
4. **A free session mint slot.** Check by opening `/ui` in the browser you will
   run in. **DO NOT probe `GET /v1/session` — it IS the mint endpoint**, so a
   probe spends a slot to learn there was one. On 2026-09-08 both slots were
   already used and the page said a slot frees in ~6 hours.

### The capture manifest — collect every item, in the same run

**Before the run**
- `/status` (build_sha, spend, flags) and the watchdog output.

**During**
- **The `query_run_id`, captured first.** Without it the harvester refuses to
  choose a run — by design.
- Screenshots at 1440px of: the consensus card, the trust panel, **the stage
  progress while the debate is running** (this is the only evidence for 1.4), the
  debate round cards, the per-slot answers (this is the evidence for 1.6), and
  the session trail with two runs (evidence for 1.7).
- The rendered `outerHTML` of each of those surfaces, so a later session can diff
  them **at $0** instead of re-spending.

**After**
```bash
mkdir -p /tmp/harvest
fly ssh console -a quorum-ai -C "cat /data/telemetry-tokens.jsonl" \
  > /tmp/harvest/telemetry-tokens.jsonl
python3 scripts/window_measurement_report.py /tmp/harvest --run <query_run_id>
```
- **Keep `/tmp/harvest/telemetry-tokens.jsonl`** — copy it into the repo's
  archive. Every later question is then answerable for free.
- The run's receipt, and `/status` again.

### Read measurement 3 ONLY through the script

**Never** `grep`/`jq` the telemetry by hand. ADR-0105 lists nine refusals the
script makes and a hand-grep bypasses all of them, including the measured
headline case where picking a run by recency "printed the exact opposite of the
paid run in both money directions". Two mis-reads a hand-grep will make:

- readings must be scoped to rows with `search_enabled is True` — debate,
  synthesis and judge rows carry `false`, and pooling them floods the census with
  `absent` and makes a run look like the provider sent nothing;
- `annotation_content_chars` **absent vs 0 are different answers**.

If the script prints `BUILD TOO OLD`, `NOT MEASURED`, `ROUTE A UNPROVEN` or
`ROUTE A THIN` — **that is the answer. Report it and stop.**

### What the run must settle

| Question | What proves it |
|---|---|
| Does round 1 fit inside `DEBATE_HARD_TIMEOUT_MS` (180s)? | 4 `debate_round_2` rows AND a synthesis present |
| Is cap 4000 enough? | `finish_reason` on **both** debate rounds — one seam, one cap |
| Do `:online` annotations carry content? | the `annotation_*` fields, via the script |
| Did the six readout fixes land? | the screenshots and `outerHTML` above |

If the round-1 gate fires, the owner's stated preference is 180s → 360s. That now
fits, because the run deadline moved to 720s. **Its own package, its own ADR,
re-measured — not assumed.**

---

## WORK PACKAGE 3 — #447, DEFERRED BY THE OWNER

**Do not implement Route A or Route B.** The owner has deferred it. Recorded so
the next session does not re-litigate.

Corrections to carry:
- "Cannot be implemented" is **too strong**. Route-independent work exists — the
  seam, the bound mechanism, the prompt change and tests against synthetic
  content. What cannot be built is the **producer** and the **honest size** of
  the content bound.
- The blocker is not "a live run" generically. It is **a live run on the
  capturing build**, and as of 2026-09-08 that has not happened.
- Measurement 3 answers **two** questions. `_verdict_3` reports
  `annotation_usable_count` by actually running `_extract_citations`, which also
  settles ADR-0084's flat-vs-nested question. `providers.py:4055` reads a **flat**
  `annotation.get("url")`. **If the block never arrives in that shape, Route A is
  dead by construction** and any speculative Route A parser is dead code.
- If Route B is ever chosen, it ships **with** #268's input bound in the same
  package. Passage content is orders of magnitude larger than a title.

---

## GATES — rule 14, and how to read them

```bash
uv sync --all-extras              # NOT --extra dev
make quality && make validate
make diff-cover DIFF_BASE=origin/main    # on a COMMITTED tree (rule 15a)
make api-contract && make openapi-check && make security-scan
# e2e per rule 13 if you touched UI, specs or fixtures — this package DOES
```

- **Never read a gate's exit status through a pipe.** `make X 2>&1 | tail`
  reports *tail's* status. Write:
  `make <target> > /tmp/gate.log 2>&1; echo "EXIT=$?"; tail -40 /tmp/gate.log`
  and **quote the EXIT= line** in any claim that a gate passed.
- **A green advisory job is not evidence it ran; a RED one is not evidence it
  measured.** Open the log and find the NUMBER. The mutation gate on PR #449 was
  red having reached only 34% of its scope — and the two survivors it *did* find
  were real, one a missing test and one an equivalent mutant.
- **Report two coverage numbers, never one:** `--cov-fail-under=88` from
  `make quality`, and the blocking changed-lines ≥95% from `diff-cover`. For a
  module-constant change, say explicitly that diff-cover measured 0 lines and
  name the behavioural test covering it instead.
- **Never** lower a threshold, add `# pragma: no cover`, or delete a test to go
  green. If it feels necessary, say so and stop.
- **Memory pressure kills long gates.** Do not stack background watcher loops;
  run gates one at a time. If `make quality` is killed, that is a machine fact,
  not a test failure — re-run chunked (`tests/unit tests/contract`, then the rest).

---

## CLOSE-OUT — in this order, every time

1. Local gates green and every review finding resolved.
2. `make close-guard` **before** the merge — CI never sees the merge text, and
   four issues have been closed by accident this way:
   ```bash
   PR=<n> EXPECT_CLOSE="<issues to close, or empty>" \
     MERGE_SUBJECT="..." MERGE_BODY="$(cat body.md)" make close-guard
   ```
3. Squash-merge with an explicit subject and body (`--squash --subject --body`).
4. Verify the deploy: filter to the Deploy workflow, take the **newest by
   `createdAt`**, and read its Deploy **JOB** — a merge yields ~3 runs and 2 are
   `cancelled` by concurrency dedupe. Then `/status.build_sha` == the merge SHA.
5. `git merge --ff-only origin/main` from the main checkout, remove the worktree
   FIRST, then delete the branch local and remote.
6. Delete your own residue by name. **Never `git clean -fdx`.** Keep `.venv` and
   `node_modules`.

---

## THE THRESHOLD REVIEWER'S CHARTER (dispatch this verbatim)

> **READ-ONLY. DO NOT WRITE, EDIT, `git checkout`, `git stash` OR `sed -i`
> ANYTHING.** Take your own `git archive HEAD | tar -x -C <dir>` copy if you must
> mutate.
>
> Review only the coverage-threshold commit. Answer: is the new value attainable
> on real runs, and on what measurement? Does the attainability test assert
> against a **literal** rather than against the constant that defines it (rule
> 7a)? Did every `target_ratio` copy and every "80 percent" document move? Is
> NFR-003's ALERT line still coherent at the new value? Was the value chosen
> against the **2dp-quantized** ratio? And per rule 11a: for every number and
> causal claim in the ADR and the commit body, name the command that produces it
> — or mark it UNVERIFIED.

---

## WHAT THIS SESSION MEASURED, SO YOU DO NOT RE-LEARN IT

- **Four review rounds each found the previous round's fix was wrong**, with all
  six gates green every time. Budget a round for your own fix's defect.
- **A committed mutation proof caught four defects in tests that looked right** —
  fixtures whose two branches gave the same answer, and assertions pinning a
  constant instead of the behaviour using it. Commit the proof; do not hand-run it.
- **Do not read a kill rate as adequacy.** A reviewer wrote seven mutants a 67/67
  set did not contain and two survived — both judgement *values*, not control
  flow. Three classes the harness cannot catch are named in ADR-0104.
- **A green diff-scoped gate on an uncommitted tree measures nothing.** It has
  nothing to scan. Commit, then run it.
