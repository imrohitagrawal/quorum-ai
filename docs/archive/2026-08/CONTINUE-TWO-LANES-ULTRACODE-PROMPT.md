# CONTINUE — two lanes: finish the hygiene tool, and prove the skill

**Supersedes `CONTINUE-BACKLOG-ULTRACODE-PROMPT.md`**, whose packages A and B are
folded in below. That file's state block is stale (it says `ef55128`; main has
moved twice since). Archive it once this one is running.

Written 2026-08-25.

---

## RUN THIS IN TWO CHAT CONTEXTS, CONCURRENTLY

| Lane | Repo | Chat |
|---|---|---|
| **Lane 1** — finish the hygiene tool, then the backlog | `quorum-ai` | **one context, packages strictly sequential** |
| **Lane 2** — prove the skill, then generalise | a throwaway repo + `stackclimb-skills` | **a second context, runs in parallel** |

**Why two and not one:** the lanes touch different repositories, so they cannot
collide. Running them in one context serialises work that is genuinely parallel.

**Why not three:** Lane 1's packages are sequential — one pull request at a time
in one repository — and they share expensive context (this repo's traps, its
gates). Splitting them means re-deriving all of it.

**If a lane's context fills up**, hand off mid-lane rather than rushing.

---

## FIRST, DERIVE THE STATE — do not trust any number below

The superseded document's state block rotted within a day. Everything here is
marked VERIFIED (a command was run 2026-08-25) or INHERITED.

```bash
git fetch origin && git log --oneline -1 origin/main
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
gh issue list --state open
gh pr list
git worktree list
ls docs/adr/ | tail -3
```

At the time of writing: main and production both `7f4d217`; 0 open pull
requests; open issues 357, 337, 290, 268, 105; latest ADR 0067.

**Roughly half of what a handoff asserts does not survive contact with the tree.
Re-verify anything you depend on.**

---

## THE PROTOCOL — use the skill, and treat that as an experiment

Both lanes run under **`stackclimb:work-package-protocol`**
(https://github.com/im<user>/stackclimb-skills, installed at
`~/.claude/skills/work-package-protocol`).

Main orchestrator verifies and merges; one sub-orchestrator per package; it fans
out for planning and review; **a sub-orchestrator never merges**. Agree the
session contract — permissions, fan sizes — before any work starts.

### Verification discipline — non-optional, and it is what actually works

A compliance checker was considered and **deliberately rejected**: measured
against this session's six real failures it would have caught roughly zero, and
against this repo's defect history **0 of 16** `src/` defects were ever caught by
an automated check while **10 of 16** came from adversarial review. Do not build
one. Do these instead:

1. **Spot-check TWO claims per package by re-running them yourself.** Default to
   the highest-consequence pair: the mutation/bite proof, and a gate's actual
   number read from its own log. This caught real defects on 2026-08-24 — an
   advisory gate that was green having measured nothing, and an implementation
   that ignored its input entirely which 15 tests then rejected.
2. **Diff the implementation against the specification's own list.** This is new,
   and it maps to the session's largest failure: a plan specified **eight**
   categories, the implementation shipped **two**, and it was merged on green
   gates and reported complete. Green measured what was built; it cannot measure
   what was omitted. **Before merging anything, put the spec list and the
   implementation side by side and count.**

---

# LANE 1 — `quorum-ai`, strictly sequential

## Package 1 — finish `scripts/session_hygiene.py`

Merged as `7f4d217` and **incomplete**. It does Job B (document classification)
well. Job A is a quarter built, and one part of it is silently wrong.

### 1a. The live defect — fix this first

**VERIFIED 2026-08-25.** The tool reports `merged branches: 0` while three
branches had just been merged. Cause: `git branch --merged main` only lists
branches whose tip is an **ancestor** of main. **A squash merge creates a new
commit, so a squash-merged branch is never an ancestor** — and this repository
squash-merges everything.

The working method:

```bash
gh pr list --state merged --limit 20 --json number,headRefName,mergedAt
```

Cross-reference against `git branch -a`. **Report-only is not the issue —
reporting a wrong number is.**

**On deleting merged branches: there is no risk to manage.** A merged branch's
commits are in main; deleting loses nothing. The earlier "riskier" framing in
this repository's history was wrong. Delete local and remote once merged, after
removing any worktree that has it checked out.

### 1b. Job A is 2 of 8 categories

The approved plan specified eight; the script implements two:

| Specified | Built? |
|---|---|
| Build/run artifacts | yes |
| Poisoned local state | yes |
| Feature branches and worktrees | counted only, and wrongly (1a) |
| Scratch and proof files | **no** |
| Downloaded artifacts | **no** |
| Reviewer scratch copies | **no** |
| Containers and images | **no** |
| One-off third-party dependencies | **no** |

### 1c. The scratch-file problem is already solved — do not invent a manifest

**VERIFIED.** A **session-scoped scratchpad directory already exists**, and the
agent's own instructions say to use it instead of `/tmp`:

```
<scratch>```

**Everything in it is that session's by construction**, so cleanup is deleting
that one directory — no manifest, no pattern matching, no guessing which file
belongs to whom.

An earlier analysis proposed building a manifest. That was **over-engineering
caused by not checking whether a mechanism already existed** — the same failure
that produced a wrong licence conclusion earlier in the same session. The
scratchpad convention makes it unnecessary.

Two facts worth acting on, both VERIFIED 2026-08-25:
- **187 files** were written to shared `/tmp` in one session, against the
  instruction to use the scratchpad. That is a behaviour defect, not a missing
  feature.
- Scratchpads hold **2.3 GB across 55,420 files** and nothing cleans them.

### 1d. Also required

- **`make session-clean`** — the script has **no entry point at all** today, so
  nothing ever runs it. That is the difference between a tool and a tool that
  gets used.
- Containers and images **by name** — `docker ps -aq` returns 0 here, so this
  needs a real test fixture, not a live check.
- **A test asserting every specified category is implemented**, so the
  specification and the script cannot drift apart again. This is the mechanical
  form of verification step 2 above.

## Package 2 — the mutation gate

### 2a. File the equivalent-mutant defect as an issue FIRST

It has never been filed. It exists only in a commit body and a superseded
prompt. Rule 19 (close more than you open) still applies, but an unrecorded
defect is worse than an open issue.

**The evidence, VERIFIED exhaustively:** two mutants survived in
`synthesis_consensus._stance_majority_flags` —

- mutant 8: `sizes.get(label, 0)` → `sizes.get(label, 1)`
- mutant 9: `+ 1` → `+ 2`

The function uses counts **only** for `max()` and equality-with-max, so both
mutations are monotonic and preserve the result exactly. Over **all 5,460 label
assignments** for panels of size 1–6 with 4 labels, neither differs from the
original in a single case. **No test can kill them.**

The gate nonetheless prints *"A survivor is a test gap that was DEMONSTRATED"*
and fails. **That claim is false for this class**, and the consequence is
structural: the job fails red on an unkillable mutant **with no path to green**.

**Design constraint:** an exclusion mechanism must not become a way to silence
real survivors. Enumerate how an exclusion list gets abused **before** designing
it. A genuine survivor must still fail.

### 2b. Issue 337's remaining half

The gate now produces a real score — `250 killed, 2 survived, 85 timeout` on a
CI runner, against `0 killed, 0 survived` before the repair. But the run was
**TRUNCATED** at the 1440s deadline.

Note what changed: it now dies on a **large 20-file diff**, not "at minimum
scope" as issue 337's title still says. **Retitle or re-scope the issue to match
what is now true**, and say so.

**Unexplained, worth one bounded look:** why the clean-test phase was ~9× slower
than the stats phase over the same suite. Time-box it. The honest alternatives
are a longer deadline, a nightly lane, or accepting truncation on large diffs.

## Package 3 — issue 357

The single switch that lets any visitor spend real money was set for one
attended session and **ran three days unattended**. Nothing noticed.

Spend was $0.1768 — **not the point**. The exposure was bounded only by a
$5.00/day ceiling **that resets daily**, so unnoticed it renews indefinitely.

INHERITED from the issue, verify each: the status endpoint **does** serve the
flag and nothing reads it; the deploy watchdog reported the drift *resolved* when
the flag deployed; availability and error-rate checks watch for outages, and a
money-spending posture is neither unavailable nor erroring; the ADR's revert
condition is prose that nothing executes.

**Every automated check was green throughout, correctly, because none of them
asks this question.**

Design guidance: this is the same shape as a human remembering. The answer is a
mechanism. Enumerate the failure modes first — this is money. Ask where a check
can live that cannot be bypassed; whether the signal is "on at all" or "on longer
than a declared window"; **how it avoids crying wolf during a legitimate sampling
window**; and where the alert actually goes. **Do not switch live execution on to
test this** — drive it with a fixture.

---

# LANE 2 — prove the skill, then generalise

## Package 4 — test the skill in a repo it was not written for

**Testing it in `quorum-ai` is uninterpretable.** That repository's agents file
already encodes most of the protocol and is auto-loaded every session, so a good
result cannot distinguish the skill from the agents file.

**Use a throwaway repository with no agents file and no `CLAUDE.md`.** Clean by
construction, deletable afterwards.

### 4a. Seed a deliberate defect — the only experiment that can falsify the skill

Plant **two** flaws in the task:

- a **vacuous test** — one that passes for any implementation
- a **money-touching change**, which should force the breaker lens

**If the review lenses catch neither, the lens table is decoration** and the
skill needs rewriting before it is recommended to anyone. Record the result
either way.

### 4b. Negative control

Run a comparable task **without** the skill. If the artifacts look the same, the
skill added nothing — the "could this pass for any implementation?" question,
applied to a skill.

### 4c. Record what leaks

Anything the skill cannot do, or does wrongly, in a repository it was not written
for is a project fact that leaked into it. **Reading the skill will not surface
these; only running it elsewhere will.**

## Package 5 — generalise, but only once Package 1 is COMPLETE

**Do not generalise a partially-built tool.** Generalising 2-of-8 categories
bakes the gap into the reusable version.

Once `session_hygiene` is finished and proven, **research how it should be
generalised** — do not assume the answer. Evaluate, with evidence for each:

- a skill alone
- a skill plus a CI gate
- a skill plus hooks
- pre-hooks / post-hooks (note the doctrine already recorded: **gates fail
  closed, convenience hooks fail open**)
- a `make` target
- something else entirely

Weigh each against this repository's measured history — **0 of 16** `src/`
defects caught by an automated check — and against the fact that cleanup is a
**session-end** act rather than a merge condition. State what each option cannot
see.

**Destination:** `stackclimb-skills`
(https://github.com/im<user>/stackclimb-skills). Its
`shared/project-profile.md` **already carries `archive_dir` and `keep_caches`**,
so the parameterisation is half designed. Its `verify.py` gate will require a
per-skill changelog and forbid project facts in skill text.

---

# STOP HERE AND ASK — issues 290, 268, 105

**All three need a human decision about spending money. Do not start any of
them. Present the decision and end the run.**

- **290 — peer critique.** The four models are called once each and never read
  each other. Blast radius: 18 test files consume the debate type, ~13 UI and
  end-to-end files touch it, orchestration goes from 2 debate calls to 8.
  **Derived arithmetic, not measured:** the estimate rises ~57% and the
  fail-safe bound plausibly crosses the confirmation threshold, meaning users
  confirm every run. A half-day spike settles it. Estimate if approved: 12–16
  hours across 3–4 pull requests, upper end ~20.
- **268 — the debate input is mis-priced.** Body was rewritten around the
  measured cause; its original diagnosis is refuted. **VERIFIED structural gap:**
  the point estimate prices debate output at **400** tokens while the call site
  enforces **2000**. Blocked because setting that constant is setting a money
  guardrail and the only evidence is one production run.
- **105 — 5xx classified as possibly-billed on no evidence.** Causes a **4.2×**
  overstatement. **Half-blocked:** the logging step is buildable now and costs
  nothing; the decision needs a week of data. **If more autonomous runway is
  wanted, the logging half is a legitimate package** — propose it.

---

# GATES, TRAPS, AND MONEY

## Money — hard constraint

**Live execution is OFF and must stay OFF. Make no paid provider call.** Free and
encouraged: the public model catalog, `/ready`, `/status`, `/metrics`,
`/ui/ops`, `/estimate`. If a question can only be settled by spending, mark it
**UNVERIFIED**, name the exact check, and carry on.

**The local `.env` has live execution enabled with a real key**, and the browser
test runner does NOT override it. A local end-to-end run **can bill**. Pin it
false yourself.

## Gates

```bash
uv sync --all-extras --python 3.12   # a bare `uv run` in a fresh worktree builds a 3.14.5 venv with NO pytest
make quality && make validate
make diff-cover DIFF_BASE=origin/main   # COMMIT first — it measures the working tree too
make api-contract && make openapi-check && make security-scan
```

Run test and coverage-diff targets **serially**. Re-derive the required contexts
from branch protection; never trust a list.

**Vet the merge text before merging** — CI never sees text typed at merge time:

```bash
PR=<n> MERGE_SUBJECT="..." MERGE_BODY="$(cat body.md)" make close-guard
```

A close keyword next to a hash-number closes that issue and the parser cannot
read negation. **Four** issues have been closed that way.

## Traps

- **`e2e/tests/review/`** makes `make quality` red locally and green in CI.
- **Repeated local end-to-end runs poison `.data/feedback_events.sqlite3`** →
  ~130 phantom failures. The hygiene tool now deletes it by name.
- **A stale `build/mutation/score.txt`** makes `make quality` red locally.
- **The visual lane fails 8/8 on a Mac on clean main** — stale baselines. Never
  update snapshots to go green.
- **`timeout` does not exist on this box.** Use `perl -e 'alarm shift; exec @ARGV'`.
- **Never run two test suites concurrently with a browser run** — an hour of
  phantom failures.
- **Never `git clean -fdx` / `-fd` / `git stash -u`.** They destroy untracked
  files the user owns. **Delete named paths only** — a wildcard removed 38
  tracked files on 2026-08-24 while five were intended.

---

# WHEN YOU STOP

Report in this shape, as the **last action**:

```
## Done
## Verified myself      (the command, and what it printed)
## Cleanup              (each line confirmed by a command)
## Pending              (nothing tidied away)
## Next action
```

Say explicitly whether work is **pushed**, **merged**, and **running in
production**. Keep what you ran separate from what a subagent reported. If
nothing is outstanding, say **"nothing pending — safe to close this session"**.

**Report faithfully.** If a gate was green having measured nothing, say that
rather than calling it a pass.

---

# NOT NOW — recorded, not tracked

`~/.claude/CLAUDE.md` and 49 memory files are in no git repository and would be
lost with the machine. **Deliberately deprioritised by the user. Do not action
it, do not open an issue for it.** Recorded here only so it is not rediscovered
as news.
