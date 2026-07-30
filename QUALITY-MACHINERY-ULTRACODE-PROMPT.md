# Repair the quality machinery — handoff for a fresh chat

> **HOW TO USE THIS FILE.** Do not paste this whole document into a chat. Paste
> the short block in **§7**, which tells the new chat to come and read this file.
> One short message from you; one long document for it.

> **Written:** 2026-07-29, immediately after WP-G2 (PR #157, `1c6954b`) merged and
> was verified in production. Every number below was measured by running the
> command shown, at that moment.
>
> **Anchor — written at `1c6954b`.** That commit is in the past and cannot change.
> To see everything since:
> ```bash
> git log --oneline 1c6954b..origin/main
> ```
> Do NOT expect any identifier below to still be `main`'s tip.

---

## 1. Why this work package exists, in one paragraph

This project's single most important testing rule is **"a test must fail when the
thing it tests is broken."** It is written in `AGENTS.md`, in
`docs/DAY-ONE-PROMPT.md`, and in every recent handoff. It is enforced by nothing.
The one mechanism that could enforce it — the mutation gate, which breaks the code
itself and checks whether tests notice — **has never produced a number in CI**, and
was measured aborting on the first pull request that actually engaged it (#158).
So the rule currently rests entirely on whoever is at the keyboard choosing to
follow it. Six tasks below close that gap. Task A is the one that matters, Task F
is how the lesson survives this project, and the rest are scaffolding.

---

## 2. State, measured (re-measure before relying on any of it)

| Thing | Value | Command that produced it |
|---|---|---|
| Last product change on `main` | `1c6954b` (WP-G2) | `git log -1 --format=%H` |
| Production `/status.build_sha` | `1c6954b…` — **matches** | `curl -s https://quorum.stackclimb.com/status` |
| Deploy | job **ran** (`success`); a second run shows `cancelled` — that is concurrency dedupe, not a failure | `gh run list --workflow="Deploy to Fly.io" --branch main` |
| pytest | 1873 passed, 10 skipped | `uv run pytest -q` |
| e2e blocking invariants lane | 138 passed | §6 rule 12 for the exact flags |
| e2e axe + parity lane | 94 passed | same |
| Changed-lines coverage | 100% on the WP-G2 diff | `make diff-cover DIFF_BASE=origin/main` |
| Open issues | 35 | `gh issue list --state open --limit 100 --json number -q '.\|length'` |
| PR template | **none exists** | `ls .github/pull_request_template.md` → no such file |
| Evidence-artifact gate | **none exists** | `grep -rniE "evidence.artifact\|no mutation" .github/workflows/` finds only an artifact *upload* |
| Decorated functions in real `src/product_app` | **40** (guard threshold 55) | the AST walk in `tests/unit/test_mutation_test_set_integrity.py:177` |

**Run `pytest` and `make diff-cover` SERIALLY** — they race on a shared path (#113).

---

## 3. Your job — six tasks, in this order, stopping at the end

### Task A — fix the mutation gate so it produces a number (#158) — DO THIS FIRST

**This is the whole point of the work package.** Everything else is scaffolding.

The gate aborts before scoring on any pull request touching `src/` Python. Measured
on PR #157, the first such PR since the gate was repaired — which
`docs/metrics/mutation-gate-study.md` §9 had named in advance as the real proof.

Job log: https://github.com/imrohitagrawal/quorum-ai/actions/runs/30436468037/job/90525272686

```
FAILED tests/unit/test_mutation_test_set_integrity.py::test_the_decorated_function_blind_spot_is_recorded
  AssertionError: 514 decorated functions under src/product_app; the study measured 40 ...
  assert 514 <= 55
!!!! stopping after 1 failures !!!!
failed to collect stats. runner returned 1
make: *** [Makefile:427: mutation-baseline] Error 1
```

**Cause, verified:** `tests/unit/test_mutation_test_set_integrity.py:43` computes
`REPO_ROOT = Path(__file__).resolve().parents[2]`. mutmut runs the suite from
inside `./mutants/`, so the root resolves to `mutants/` and the test walks
`mutants/src/product_app/*.py` — mutmut's generated files, which carry a decorated
`x_<name>__mutmut_N` variant per mutant. Real source has 40. `-x` then kills
collection, so **no mutant is ever scored**.

**The printed message is the WRONG cause.** It says "usually a repo-root file
missing from `[tool.mutmut].also_copy`". Nothing is missing. Do not go looking there.

Requirements:

1. Resolve the root explicitly — `git rev-parse --show-toplevel`, or detect and skip
   when running inside the copy. **Audit every other check for the same bug**: any
   test resolving paths from `__file__`, `cwd`, or `parents[n]` will silently point
   at the copy when run under mutmut. Grep for them and report how many you found.
2. **Prove the repair by RUNNING the gate**, not by reading it. `make mutation-baseline`
   locally on a branch that changes a `src/` function, and read the output.
3. Then prove it in CI on your own pull request — which touches `src/` Python by
   definition — and **open the job log and quote the score it printed.** A green tick
   is not the proof. Neither is a red one. The number is the proof.
4. Fix the failure message so the next person is not sent to `also_copy`.
5. **Keep the gate ADVISORY.** Do not promote it. `docs/metrics/mutation-gate-study.md`
   §4 measured 4% yield against a 158-defect history and ~15% wrong answers.
   Advisory-and-producing-a-number beats blocking-and-broken. Anyone arguing for
   promotion must first re-run `scripts/replay_mutation_scope.py` and post the number.

### Task B — research and write a pull request template

**There is no `.github/pull_request_template.md` today.** Verify that before writing one.

1. **Research first, and cite what you read.** Look at how well-run open-source
   projects structure PR templates, what makes a template get filled in honestly
   versus skipped, and the known failure mode of checkbox theatre (people tick boxes
   without doing the thing). Search the web; read at least four real templates from
   substantial projects; summarise what you took from each and what you rejected.
2. **Design for THIS project's measured failure history**, not a generic checklist.
   The recurring failures are recorded in `docs/metrics/mutation-gate-study.md` §8 and
   `docs/103-incident-learnings.md`. They are, in order of cost:
   - claims made from reading rather than running;
   - tests that pass whether or not the feature works;
   - advisory gates believed without opening the log;
   - numbers written into prose without being measured.
   The template's core field should therefore ask for **evidence, not assent**:
   *which line did you break, which test went red, which command did you run.*
   A field that can be satisfied by ticking a box is worth nothing here.
3. **Keep it short.** A long template gets skimmed. Prefer four fields that are
   always filled over twelve that are not.
4. **State honestly, in the template itself, that it is not enforcement** — it sits
   above the line in `docs/DAY-ONE-PROMPT.md` §1. It makes an invisible habit
   visible; it cannot compel anything.
5. Check whether `codex-review` or any existing workflow parses PR bodies before you
   change their shape (`grep -rn "pull_request" .github/workflows/`).

### Task C — build the evidence-artifact gate that the day-one file already specifies

`docs/DAY-ONE-PROMPT.md` §1 and §5 describe this layer and give the exact example:
*"changed `src/` module with no mutation report → fail."* **No workflow implements
it.** Only an "Upload mutation report" step exists, which uploads a file and fails
nothing.

Build the honest version:

1. **Scope it to what is structurally checkable.** A `src/` change with no
   added-or-modified test file → fail. That is checkable from the diff and cannot be
   faked without writing a test.
2. **Do not claim more than it does.** §1's anti-gaming caveat is explicit:
   *"artifact present ≠ artifact valid."* This gate cannot tell a good test from a
   worthless one. Say so in its charter, in the workflow file, next to the job.
3. **Measure its yield before shipping it**, exactly as rule 3 in §6 requires: replay
   it over real history and report how many of the last N pull requests it would have
   blocked, and how many of those were genuine. If it would have blocked mostly
   legitimate work, say so and recommend against it rather than shipping it anyway.
4. Ship it **blocking only if the replay supports that**; otherwise advisory with a
   stated promotion condition. Register it in a workflow — an unregistered gate is
   not a gate.

### Task D — charter every gate you touch

`docs/DAY-ONE-PROMPT.md` §4a-bis requires one paragraph next to each gate saying
what it cannot see — **including the gate's own failure modes**, which is the line
added on 2026-07-29 after #158.

For the mutation gate at minimum: cannot see JavaScript, CSS, or browser tests;
cannot see module-level constants or config tables; cannot see decorated functions
(7% of PRs abort on this); cannot see pure deletions; **and can exit non-zero
without having measured anything, which looks like this in the log: `failed to
collect stats`.**

### Task E — close the loop on the documentation

`docs/DAY-ONE-PROMPT.md` §4a-bis was updated on 2026-07-29 with the red-advisory
rule and the copied-tree corollary. **Verify that edit is present and reads correctly**
(`grep -n "RED advisory" docs/DAY-ONE-PROMPT.md`), then:

1. Make sure `AGENTS.md` and the mutation study agree with it — no document should
   still imply that opening the log matters only for green jobs.
2. Add a `docs/103-incident-learnings.md` entry for #158 with the measurement.
3. If the doc-honesty gate (#141) flags anything you wrote, fix it rather than
   waiving it.

### Task F — write what you learned into the day-one file, before you report

**Standing instruction from the operator, and it applies to every work package
from here on, not only this one.**

`docs/DAY-ONE-PROMPT.md` is the file that carries this project's hard-won process
into the next project. A lesson that lives only in a chat, a pull request body, or
a closing report **is lost** — that is the whole point of §1's durability ladder,
applied to the ladder's own documentation.

So: if this work package teaches you something pivotal — a failure mode, a rule
that would have prevented it, a check that turned out to be worthless, a tool that
lied — **you write it into `docs/DAY-ONE-PROMPT.md` in the same pull request that
teaches it.** Not afterwards, not as a follow-up issue.

What counts as pivotal, concretely:

- a rule you had to *invent* mid-task because none of the existing ones covered it;
- anything that made a green or red signal untrustworthy;
- any check, gate, or test you discovered was measuring nothing;
- any fix that turned out to be worse than the bug it fixed;
- anything that cost more than an hour to diagnose and would have been cheap to
  prevent.

What does **not** belong there: this project's specific issue numbers, file paths,
or one-off details. The day-one file must stay portable to a project that shares
none of them. State the lesson in general terms, then cite the measurement as
evidence in one line — the existing §4a-bis entries are the pattern to copy.

Then check the rest of the chain still agrees: `AGENTS.md`, the relevant `docs/`
file, and — if the lesson changes how future sessions must work — your own closing
handoff prompt. **A lesson recorded in exactly one place is one edit away from
being lost.**

---

## 4. Stop point

**Stop after Task F.** Report, then wait. Specifically:

- Do **not** start WP-H. It needs explicit permission, and two of its items (#115,
  #118) need a design decision from the operator before any code.
- Do **not** attempt #155. The obvious fix is measured to be worse than the bug —
  see the issue.
- Do **not** touch the cost layer. A separate work package owns it.

Your closing report must list, with issue numbers: what you shipped, what you
measured, what you deliberately left, and what the next pull request should be.
It must also state, in one line, **what you added to `docs/DAY-ONE-PROMPT.md`** —
or say plainly that this work package taught nothing that belonged there, which is
a legitimate answer but must be a stated decision rather than an omission.

---

## 5. Open issues you may encounter (35 total; these are the relevant ones)

| # | What | Status for you |
|---|---|---|
| **#158** | The mutation gate aborts before scoring on any `src/` PR | **Task A — do it** |
| #155 | High-stakes acknowledgement bypassable via `context`; the obvious fix 422s every legitimate follow-up | **Do not attempt.** Needs a design decision |
| #156 | Four surviving mutations in the WP-G2 tests + a cost-layer over-charge | The cost half is out of scope; the test half is optional after Task A |
| #142 | `report()` misclassifies mutmut exit codes; the `no_tests` guard is bypassed by exit 5 | **Read it before Task A** — same subsystem, may be the same sitting |
| #146 | 34 of 354 scoped globs match zero mutants | Related to Task A; do not scope-creep into it |
| #143 | Nothing pins `replay_mutation_scope.py` ≡ the Makefile's `MUTMUT_SCOPE_PY` | You will use that script in Task C. Consider fixing while there |
| #141 | The doc-honesty gate truncates its scan at the first comma | Relevant to Task E |
| #113 | `test_makefile_gate_integrity` races on a fixed shared path | Why pytest and diff-cover must run serially |
| #137, #138 | TRIGGER-GATED | **Not work. Leave them.** |

---

## 6. Standing rules — every one was learned by breaking something

1. **Verify by executing, never by reading.** A claim about what a tool does is
   UNVERIFIED until you have run it and read its output. State the command and what
   it printed, or say UNVERIFIED out loud.
2. **A green advisory job is not evidence it ran. A RED advisory job is not evidence
   it measured.** Open the log; find the number. This work package exists because of
   the second half.
3. **Before proposing or promoting a gate, measure its yield** against real defect
   history (`scripts/replay_mutation_scope.py`) and state what it cannot see.
4. **If a premise in this document turns out to be false, STOP and say so.** Do not
   repair the premise and carry on.
5. **Every test ships with one line saying what turns it red.** Prove it by mutation:
   `cp` the file aside, mutate, restore from the copy, verify with `diff -q`. **Never
   `git checkout <file>`** — the tree may hold uncommitted work. **Confirm the
   mutation hit the line you meant**, and confirm the test run actually executed —
   a mutation that breaks collection proves nothing.
6. **A negative check needs a positive partner.** A check that counts nothing needs
   something proving the counted thing exists.
7. **Never parametrize a test over the constant it is testing.** Measured on WP-G2:
   a forgery test parametrized over `_LINE_BREAKING_CHARS` silently became zero test
   cases when that constant was narrowed, and the suite still reported all-green.
   Use literals in the test and add a separate test that the production constant
   still covers them.
8. **Never assert a bound against the constant that defines it.** Same work package:
   a test built its payload from the limit it was checking, so it passed with the
   limit set 6000× too small. Measure against something independent.
9. **Fan out for review, never for building.** Subagents share one working tree. Tell
   every reviewer **IN CAPITALS** not to write, edit, `git checkout`, `git stash` or
   `sed -i`. Snapshot your diff to a scratch path first.
10. **Verify every reviewer claim before acting.** About a fifth do not survive. On
    WP-G2, a round-1 fix accepted from review had to be reverted in round 2 because it
    broke the feature — check the fix, not just the finding.
11. **Cap review at TWO rounds**, then ship with the leftovers filed as issues. Each
    round's fixes need their own review.
12. **Run e2e exactly as CI does**, or ~95 phantom failures appear:
    ```bash
    lsof -ti tcp:18085 | xargs -r kill -9
    cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> \
      --project=chromium --workers=1 --retries=0
    ```
13. **`make quality` / `make validate` do NOT include the blocking changed-lines
    coverage gate.** Run `make diff-cover DIFF_BASE=origin/main` before pushing.
14. **Run `pytest` and `make diff-cover` serially** (#113).
15. **`make format` reformats your test assertions** and will break `sed`-style
    anchors. Grep for the real text before any programmatic edit.
16. **One work package, one pull request**, merged before the next starts. Merge
    `main` into your branch **before** starting. **Check you are actually on your
    branch before committing** — on WP-G2 a commit landed on `main` and had to be
    moved before anything was pushed.
17. **Done means merged AND running in production.** Verify three ways: the deploy JOB
    ran (not `skipped`/`cancelled`), `/status.build_sha` equals the merged SHA, and the
    thing you built actually fires. Probe production only where it costs nothing —
    `/estimate` makes no provider call; a full run does.
18. **Plain English everywhere.** No jargon, no invented shorthand.
19. **A pivotal lesson goes into `docs/DAY-ONE-PROMPT.md` in the same pull request
    that teaches it.** Operator standing instruction. That file is what carries this
    project's process into the next one; a lesson left in a chat, a PR body, or a
    closing report is lost. State it in portable general terms, cite the measurement
    in one line, and check `AGENTS.md` and the relevant `docs/` file still agree.
    See Task F for what counts as pivotal.

---

## 7. Paste this into a fresh chat

```text
ultracode

Read AGENTS.md, then QUALITY-MACHINERY-ULTRACODE-PROMPT.md in full before editing
anything. Then read docs/metrics/mutation-gate-study.md §7-§9 and
docs/DAY-ONE-PROMPT.md §1, §4a-bis and §5.

FIRST: re-measure §2 yourself — make validate lint format-check type-check
openapi-check, then pytest, then BOTH e2e lanes, then
make diff-cover DIFF_BASE=origin/main. Run pytest and diff-cover SERIALLY (#113).
Expect 1873 pytest, 138 and 94 e2e, and prod build_sha == the last commit that
touched src/. If any number differs, find out why before writing code. If a
PREMISE in §3 does not hold when you check it, STOP and tell me — do not repair
it silently.

THEN do Tasks A to F in order. Task A first and alone until it is proven: the
mutation gate must PRINT A SCORE in CI on your own pull request, and you must
quote that number from the job log. A green tick is not proof and neither is a
red one. Keep the gate advisory. For Task B, research real PR templates on the
web before writing one, and cite what you read.

RULES: §6 of that file, all eighteen. The ones that cost the most: verify by
EXECUTING not reading, and say which command you ran; never parametrize a test
over the constant it tests, or assert a bound against the constant that defines
it; prove every test bites by mutation using cp/restore and confirm the run
actually executed; verify a reviewer's FIX, not just the finding; two review
rounds MAX then ship with leftovers filed; done means merged AND deploy-verified.

Fan out read-only subagents for recon and adversarial review — tell every one IN
CAPITALS not to write, edit, git checkout, git stash or sed -i anything. One
tree-writer: you.

Task F is not optional paperwork: anything pivotal you learn goes into
docs/DAY-ONE-PROMPT.md in the SAME pull request that teaches it, in portable
general terms. That file carries this project's process into the next project.

STOP after Task F and report, listing every pending item with its issue number,
and state what you added to docs/DAY-ONE-PROMPT.md.
Do not start WP-H. Do not attempt #155. Do not touch the cost layer.
```

---

## 8. What is genuinely unknown

- **Whether the mutation gate produces a usable score once it stops aborting.** It has
  never run to completion in CI. The recorded 87.2–88.7% baseline came from a
  different invocation path and, per #142, from a classifier that misreads exit codes.
- **p90 mutation runtime on the CI runner** (#137). The 30-minute-timeout risk is
  extrapolated from two local data points. Task A will produce the first real
  data point — record it.
- **Whether an evidence-artifact gate is worth its noise here.** Task C's replay
  answers that. A recommendation against shipping it is a valid outcome.
- **How many other checks resolve paths from `__file__`** and would therefore
  misbehave inside the mutmut copy. Task A step 1 answers it; nobody has counted.
