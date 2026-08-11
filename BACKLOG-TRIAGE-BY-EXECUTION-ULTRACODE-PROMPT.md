# ultracode — triage the whole open backlog by EXECUTION, then plan. Do not fix anything.

> **HOW TO USE THIS FILE.** Do not paste it into a chat. Paste the short block in
> §8. One short message from you; one long document for the session.
>
> **Anchor: this document was written against `main` at `4749aa5`.** That commit is
> in the past and cannot change, so this line is never wrong. To see everything
> since: `git log --oneline 4749aa5..origin/main`. Do **not** expect any count,
> issue number or status below to still hold — every one is a claim you must
> re-measure. A handoff cannot contain the identifier that recording it creates.

---

## 1. The job, in one paragraph

There are open issues in this repository. Nobody knows how many of them are still
real. Some were fixed by a later commit and never closed. Some describe code that
no longer exists. Some are duplicates of each other under different words. Some are
real and are quietly costing money right now. **Your job is to find out which, by
running things — then to plan, and stop.**

**You will not fix anything.** Not one line. The deliverable is an analysis and a
sequenced plan. If you find yourself editing `src/`, you have misread this
document.

---

## 2. The single rule this whole task exists to enforce

**An issue's text is a claim, not a fact. Treat every one as UNVERIFIED until you
have run something that confirms or refutes it.**

Measured on 2026-07-30, on this repository: of 22 claims inherited from handoff
documents and checked against the tree, **12 were wrong or already resolved** — 6
of them fixed by a single commit nobody had connected to the issues. Four headline
findings were checked and all four were refuted. **Roughly half of what a written
claim asserts does not survive contact with the code.** Assume the same rate here
and you will be about right.

For each issue, one of these verdicts, and nothing else:

| Verdict | Means | Requires |
|---|---|---|
| `REAL` | reproduced today | the command and its output |
| `ALREADY-FIXED` | the code no longer does this | the commit or the code that fixed it, plus a run showing the fixed behaviour |
| `REFUTED` | it never worked the way the issue says | the run that disproves the premise |
| `DUPLICATE-OF #n` | same root cause as another issue | the shared cause named, not just similar symptoms |
| `STALE` | describes code/config that no longer exists | the grep that returns nothing, **plus a positive control proving your grep works** |
| `UNVERIFIABLE-FREE` | needs a paid call, a funded key, or production write access | the exact command an operator would run, and what it would cost |

**`UNVERIFIABLE-FREE` is a legitimate verdict. Guessing is not.** If you cannot
settle something for $0, say so and name the check. Never let a guess wear the
clothes of a fact.

---

## 3. Before you touch the backlog — re-measure the ground

Run these first. If any disagrees with what you expect, **find out why before
continuing**; a stale baseline is how a regression gets mistaken for a known
failure.

```bash
git branch -f main origin/main   # do this FIRST, and again at the end
git log --oneline 4749aa5..origin/main | head -30
gh issue list --state open --limit 300 --json number --jq length
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
curl -s https://quorum.stackclimb.com/status | jq -r '.build_sha, .live_execution'
curl -s https://quorum.stackclimb.com/ready | jq -r '.state'
git log -1 --format=%H -- src/          # last commit that touched product code
```

Then confirm the suite is green **before** you start, so you never attribute a
pre-existing failure to something you found:

```bash
uv sync --all-extras
make quality && make validate
```

Record the numbers. "Pre-existing" must mean *measured against a named commit*, and
you must say which.

---

## 4. Phase A — enumerate, then verify by execution (fan out)

### A1. Get the real population

Not just titles. Bodies and comments too — an issue's status often lives in a
comment nobody folded back into the description.

```bash
gh issue list --state open --limit 300 --json number,title,labels,createdAt,updatedAt > /tmp/open.json
# and for each, the body + comments
```

**Print the denominator.** `N issues found, N triaged, 0 unclassified.` A triage
that cannot state its denominator has verified nothing.

### A2. Fan out READ-ONLY verifiers

Split the issues into batches and give each batch to a subagent.

**Tell every one of them, IN CAPITALS: DO NOT WRITE, EDIT, CREATE OR DELETE ANY
FILE. DO NOT RUN `git checkout`, `git stash`, `git commit`, `git add`, `sed -i`, OR
ANY MUTATING COMMAND. DO NOT MODIFY ANY GITHUB ISSUE OR PULL REQUEST.** They report
findings as text; a single writer (you) records them.

Each verifier must, per issue:

1. Read the body **and every comment**.
2. Locate the code it names — **by symbol, not by line number.** Line numbers in
   old issues have drifted; treat them as locators and confirm the quoted text.
3. **Run something.** A unit test, a probe script, a `curl` against a local server,
   a `grep` with a positive control. Reading the code is not verification —
   that is the failure mode that has cost this project the most.
4. Return the verdict, the command, and its verbatim output.

**A verdict with no pasted command output is void and gets re-run.**

### A3. Traps that will bite the verifiers — put these in their prompts

- **`make quality` green ≠ CI green.** Six contexts are required at merge; see
  rule 14 in `AGENTS.md`, and re-derive the list with `gh api` rather than trusting
  the table.
- **Run `pytest` and `make diff-cover` serially** — they race on a shared path.
- **`SESSION_RATE_LIMIT_PER_MINUTE=600` is for Playwright only.** Exporting it for
  pytest fails a rate-limit test and produces a phantom red.
- **e2e must be run exactly as CI does** or ~95 phantom failures appear.
- **Purge `__pycache__` before trusting any result** — stale bytecode gives false
  green *and* false red.
- **Process-global test state** (the cost event ring, the run-capacity semaphore,
  the model catalog) means one test can change the answer for the next.
- **A negative result needs a positive control.** "grep returns nothing" is
  trivially true if your pattern is wrong.
- **Hermetic / $0.** No paid API calls, no secret rotation, no production writes.
  `/ready`, `/status`, `/metrics`, `/ui/ops` and `/estimate` are free; a full run
  is not.

### A4. Then verify the verifiers

Roughly a fifth of review findings do not survive inspection, and inherited claims
do far worse. **Spot-check every `ALREADY-FIXED` and every `STALE` yourself** —
those two verdicts close issues, and a wrong one buries a live defect. Re-run the
command; do not trust the transcript.

**Repeated independent discovery is signal, not noise.** If two verifiers
independently land on the same finding, weight it up, do not average it away.

---

## 5. Phase B — group by shared root cause, not by symptom

This is the step most likely to produce something genuinely useful, and the one
most likely to be skipped.

On 2026-07-30, four issues filed across four sessions (#111, #115, #118, #128)
turned out to be **one habit expressed four times** — degrading by inventing
plausible filler rather than admitting a gap. Each had been triaged separately.
Grouping them was worth more than any individual fix.

So: after every issue has a verdict, look across them.

- **Group by cause, and name the cause in one sentence.** "These four are all X."
  If you cannot write that sentence, it is not a group.
- A group must be **shippable as one pull request** — one concern, one reviewer can
  audit it. If it cannot, it is two groups.
- Say explicitly which issues each group **closes**, and which it merely touches.
- Note any ordering constraint *inside* a group (a derived constant forces build
  order; an estimate-body change and a create-body change must land together).

---

## 6. Phase C — rank by what can hurt, not by what is satisfying to build

For each group, record these, each with its evidence:

| Field | Must be |
|---|---|
| **Exposure** | who or what is harmed, and how much — money, correctness shown to a user, security, or developer time |
| **Severity** | reproduce it and state the blast radius. No severity without a reproduction |
| **Confidence** | how sure the verdict is, and what would change it |
| **Effort** | rough, and say it is rough |
| **Blocked by** | anything that must land first, including an operator decision |

Then rank. **Ranked by what can hurt, not by what is ready to start.**

Known weightings from this repository's own history, which you should re-derive
rather than inherit:

- **Money defects are ~31% of the traced defect history** (5 of 16). They are the
  highest-yield place to spend.
- **0 of 16 real defects were caught by an automated check; 10 of 16 by adversarial
  review** (`docs/metrics/defect-discovery-audit.md`). **A new gate is not a
  defence.** Weight "fix a live defect" above "build a gate" unless the gate
  prevents a regression you actually had.
- **Close live/paid exposure before advisory or quality work.**

**Anything requiring an operator decision gets its own list**, with the exact
question, the options, and what each costs. Do not invent a guardrail number — an
unmeasured guardrail number is a fabricated one. Batch every such question into
**one** checkpoint rather than blocking repeatedly.

---

## 7. What to produce, and then STOP

One document, `docs/analysis/<date>-backlog-triage-by-execution.md`, containing:

1. **The denominator line.** `N open, N triaged, 0 unclassified.`
2. **The verdict table** — one row per issue: number, title, verdict, the command
   that settled it, and its output in one line.
3. **The close list** — every `ALREADY-FIXED`, `REFUTED`, `STALE` and `DUPLICATE`,
   with evidence, ready for an operator to close in one pass. **Do not close them
   yourself.**
4. **The groups** — each with its one-sentence root cause, the issues it closes,
   and its internal ordering.
5. **The ranking** — groups in order, each with the one line saying why it outranks
   the next. *If that line cannot be written honestly, the ranking is wrong.*
6. **The operator queue** — decisions only a human can make, each with the question
   and the options.
7. **What is genuinely unknown** — named as unknown, distinguishing *settled by
   construction but never measured* from *measured*. Include the exact command that
   would settle each.
8. **What you could not verify for $0**, and what it would cost.

Then **stop and report.** Do not start work on group 1. Do not open new issues
unless you find something genuinely new and severe — and if you do, remember the
standing rule: **close more than you open.** If an item turns out bigger than it
looked, say so and stop, rather than filing and continuing.

---

## 8. Paste this into a fresh chat

```
ultracode

Read BACKLOG-TRIAGE-BY-EXECUTION-ULTRACODE-PROMPT.md at the repo root and follow
it. Also read AGENTS.md first — its operating rules bind, and rule 14's gate list
must be re-derived with gh api rather than trusted.

FIRST: re-measure everything in §3 yourself. If a number differs from what you
expected, find out why before doing anything else. If any PREMISE in this prompt
does not hold when you check it, STOP and tell me — do not repair it silently.

Then triage the whole open backlog by EXECUTION, per §4-§6. Every verdict needs a
command and its output; a verdict with no output is void. Fan out read-only
verifiers and tell each one IN CAPITALS not to write, edit, git checkout, git
stash or sed -i anything, and not to touch any issue or PR. One tree-writer: you.

DO NOT FIX ANYTHING. DO NOT CLOSE ANY ISSUE. The deliverable is the analysis and
the plan in §7, then you stop and report.

Hermetic and $0 throughout — no paid API calls. If something can only be settled
by a paid run, say so and tell me what it would cost.

Expect roughly half the issue claims to be wrong; that is the measured rate here.
A refutation, a "could not reproduce in N runs", and a "could not verify — here is
the check that would" are all successful outcomes. A confident wrong answer is the
only real failure.
```

---

## 9. Rules that earned their place — apply all of them

Every one of these was learned by breaking something on this repository.

1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud.
2. **When you CORRECT a false claim, verify the REPLACEMENT before writing it.**
   Twice on 2026-07-30 a correction was itself wrong — including one that
   "corrected" a rule that was already right. Prefer narrow hedged wording over
   absolutes.
3. **If a premise you were handed turns out to be false, STOP and say so.** Never
   repair it silently and carry on.
4. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log and find the number.
5. **A negative check needs a positive partner.** "No X found" is trivially true
   over nothing.
6. **Assert structure, not substrings.** A substring matches the prose that
   explains the thing — this repository has a live gate satisfied by a comment.
7. **Fan out for review and recon, never for building.** Subagents share one
   working tree.
8. **Two lenses, not five.** Spend the difference on verification, not more
   finders. Keep at least one lens that **executes** rather than reads — it is the
   one that has found the real defects here.
9. **Cap review at TWO rounds**, then stop and report with open findings listed.
   **Expect your own work to contain a defect — budget a round for it.**
10. **A content audit cannot see an inbound reference.** Before concluding anything
    is unused, `git grep` for it. On 2026-07-30 this exact gap let a "safe" cleanup
    break 18 tests.
11. **Line numbers are locators, not addresses.** Confirm the quoted text.
12. **Before deleting anything, `git ls-files` it.** Tracked files are recoverable;
    untracked ones may survive only as dangling blobs.
13. **Never fabricate a number, label, or baseline.** "Unmeasured" must never read
    as "clean". Absent means `—`, never a placeholder value.
14. **Plain English. No jargon, no invented shorthand.**
15. **Close more than you open.**

---

## 10. What is genuinely unknown, as of `4749aa5`

Named so nobody mistakes an assumption for a fact. Re-check each.

- **How many open issues are still real.** That is the whole point of this task.
  The last count was 42, and no one has verified them by execution.
- **Whether the e2e workflow-coverage guard has ever missed a spec in practice.**
  It asserts a substring, so a spec named only in a comment satisfies it, and
  `GATED_SPEC_DIRS` does not sweep `e2e/tests/degraded/`. Known-broken, never
  measured for actual escapes.
- **Real latency at the current token caps**, and whether the 180-second run
  deadline holds. Extrapolated, never measured — needs one funded run.
- **Whether `refs/archive/stash-0..3` matter.** They preserve four stashes on one
  disk and were never pushed. Someone should decide whether to push or drop them.
- **The deployment-wide spend ceiling (#100).** An operator policy number. Do not
  invent it.
