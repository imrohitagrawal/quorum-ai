# Guardrails (#130, #131), then write the WP-G2 → WP-H handoff

> **Written:** 2026-07-28, immediately after PR #96 merged and deployed.
> Every number below was **measured at that moment**, not carried forward from
> an older document. Re-measure before you rely on any of it — this project has
> repeatedly been bitten by a plan restating a stale claim as fact.

---

## 1. State, measured

| Thing | Value |
|---|---|
| Last PRODUCT change on `main` | `2bba0d1` (PR #96) |
| Production `/status.build_sha` | `2bba0d1…` — **matches the last product change** |
| `main` tip | moves with docs-only commits (e.g. `c1d20f8` added this file). Do NOT expect `main` to equal prod: a docs merge changes `main` and redeploys the same app. Compare prod against the last commit that touched `src/`. |
| Deploy | job **actually ran** (not `skipped`); `/health` + `/ready` smoke tests passed, run `30377661288` |
| pytest | 1776 passed, 10 skipped |
| e2e blocking invariants lane (9 specs) | 138 passed |
| e2e axe + parity + ops lane (7 specs) | 94 passed |
| Changed-lines coverage | 98% |
| Open issues | 25 |
| Local branches | `main` only, plus two the delete refused (below) |

PR #96 shipped WP-A…WP-F: verdict band, citation-coverage math, data
completeness, copy + readiness honesty, the slot-4 model migration, and
frontend completeness.

**Two local branches deliberately survived cleanup** — `git branch -d` refused
them because each holds 1 commit not on `main`:
`feat/ui-pr5b-cost-guard-diff` (the master plan §11 calls it a stale draft that
would delete 1,059 lines — confirm, then `-D` if you agree) and
`worktree-wf_8fbedc6c-041-3`. Do not force-delete either without looking.

---

## 2. Your job, in order

### Task A — issue #130: make the mutation check block

`.github/workflows/ci.yml` line **211** is `continue-on-error: true` on the job
named at line **195**, `Mutation score (ADVISORY - non-blocking)`. Remove the
flag and rename the job so the name stops lying.

**Why it is safe, measured:** it runs only on pull requests (line 206), is
scoped to **changed functions** via `make mutation-baseline` (the Makefile notes
whole-module mutation is slow and gameable — 1009 mutants), finished in **1m11s**
on PR #96, and **passed**.

**Why now:** `docs/DAY-ONE-PROMPT.md` §4a already said to run it advisory *until
a baseline exists and the CI runtime is known*. Both were true a long time ago.
It stayed advisory because nobody wrote down what would flip it.

**Do not skip this check:** run `make mutation-baseline DIFF_BASE=origin/main`
locally on your own change first. If it fails on your change, that is the gate
working — fix the test, do not raise the threshold.

### Task B — issue #131: catch browser tests that cannot fail

The mutation tool reads **Python only**. Every browser test is in
`e2e/tests/**/*.spec.ts`, and nothing checks those can fail. Three tests written
in the WP-F session passed against the exact bug they existed to catch.

**Measured scale — read this before designing:** 23 spec files contain **92**
negative assertions: 31 `toEqual([])`, 22 `not.toContain`, 20 `toHaveCount(0)`,
15 `not.toMatch`, 4 `toBe(0)`.

**So a guard applied to all 92 is unshippable.** Scope it to **changed spec
files only**, the way `diff-cover` and the mutation check already scope
themselves. That is the pattern this repo uses; follow it.

Copy the shape from the two guards that already exist:
`tests/test_e2e_workflow_covers_all_invariant_specs.py` (reads the spec folder,
fails when a file is not named in the CI workflow) and
`tests/unit/test_provider_notice_copy.py` (walks Python with `ast`).

**The rule to enforce:** a negative assertion needs a positive partner in the
same test — something proving the thing being counted exists at all.
`expect(x).toHaveCount(0)` proves nothing when `x` never matches anything.

**Allow exceptions, but make them visible:** require a one-line reason beside
each. A silent exception is the same failure in a new coat.

### BEFORE WRITING ANY CODE FOR TASK B — bring the design to the operator

This check can be too strict (blocking honest tests and becoming a tax people
route around) or too loose (catching nothing and giving false confidence). That
balance is the operator's call, not yours. Present all four of these and
**wait for a decision**:

**1. The rule**, in one sentence, in plain English.

**2. The exception list** — every kind of test you propose to allow through,
each with the reason. Expect at least these, and say whether you would allow
them:
   - a test whose *whole point* is that something is absent (no error toast
     appeared, no console error, no forbidden colour on a surface);
   - a security check asserting a hostile input produced nothing;
   - a check inside a loop where the positive proof sits outside it.

**3. A worked example** — one real assertion from this repo shown three ways:
   as it is today, as it would fail the check, and as it would pass. Use a
   genuine one, not an invented one.

**4. Pros and cons, as bullets**, covering at least:
   - what it catches that nothing else does today;
   - what it will *not* catch (it is a shape check, not a proof — a test can
     have a positive partner and still be weak);
   - the false-alarm cost: how often you expect it to block an honest test;
   - the maintenance cost: who updates the exception list, and how a reader
     can tell a real exception from a lazy one;
   - what happens the first time it blocks someone in a hurry — the honest
     failure mode is that people write a throwaway positive assertion to get
     past it, which is worse than no check.

Then stop and wait. Do not build it before the operator answers.

**Prove it works on real examples.** These three shipped green against the bug
(all now fixed — reconstruct them to test your guard):
1. a check asserting a list had 6 items, which the broken output also had;
2. a check for emphasis carrying surrounding spaces — a shape the code cannot
   produce, so always true;
3. a check asserting a history panel holds exactly one entry, which *is* the
   defect.

### Task C — write the WP-G2 → WP-H handoff prompt

Only after A and B are merged and deploy-verified. Write
`WP-G2-TO-WP-H-ULTRACODE-PROMPT.md` for a **fresh chat**. It must contain:

- state you **measured yourself**, not copied from here;
- the WP-G2 facts below, each re-verified;
- a **hard stop after WP-G2**: report, then wait for explicit permission before
  starting WP-H. Do not chain work packages;
- the standing rules in §4;
- what is genuinely unknown, named as unknown.

---

## 3. WP-G2 facts — verified 2026-07-28, re-verify anyway

**F-10 / issue #11, context carry, is 2 of 5 links.** Not a stub — worse:

| Link | State |
|---|---|
| Client sends `context` | **NO** — `app.js` has zero occurrences |
| `/estimate` accepts it | **NO** — `query_runs.py:1113` calls `getattr(payload, "context", None)` but `QueryRunEstimateRequest` **has no such field**. Plumbing that cannot fire |
| `create` accepts it | yes — `query_runs.py:312`, keys validated at `:321` |
| `prior_question` → prompt | yes — `providers.py:880-891`, correctly fenced |
| `prior_synthesis` → prompt | **NO** — zero occurrences in `synthesis.py` and `debate.py` |
| Both priced | yes — and `costs.py:934-935` adds the context tokens **TWICE** |

So an API client sending `context` is **charged for tokens no model ever
receives**. The UI never sends it, so no user is affected today.

**The ordering trap:** adding `context` to the create body without also adding
it to the estimate body makes the estimate and the run disagree, producing a
permanent payment-confirmation loop. Both edits go in **one commit**.

**Also open, and cheap to fix while you are in that file:** `context` values are
typed `Any` and unbounded, so `{"prior_question": 123}` raises `AttributeError`
in `costs.py:724` — an unhandled 500 on the public API (issue #125).

**WP-H contents:** F-20 (UX batch), F-24 (stale a11y tests), plus issues #113,
#115, #116, #117, #118. **F-17 is already done** — the digit assertion is
present at `trust-score-invariants.spec.ts:456`. **F-16 is done** — baselines
were reseeded and the visual gate is green. WP-H is smaller than the plan says.

**#115 and #118 need a design decision from the operator before code:** both are
markup that exists and is never visible, because `.panel.panel-section
{ display: none }` (`app.css:654`) hides the whole legacy section by design.
Delete those surfaces, or move them? Ask; do not guess.

---

## 4. Standing rules — every one of these was learned by breaking something

1. **Verify before you build.** Re-measure the state above. A plan is a claim.
2. **Every test ships with the one line saying what turns it red.** If reverting
   the fix leaves it green, it is not a test.
3. **Never write a check that goes red when the bug is FIXED.** Two of the three
   examples in Task B had that property — they lock in the defect.
4. **A negative check needs a positive partner.**
5. **Prove the bite by mutation.** Copy the file aside with `cp` and restore
   from the copy. **Never `git checkout <file>`** — the tree may hold
   uncommitted work. Verify the restore with `diff -q`.
6. **A green suite is not proof — look at a screenshot.** In the WP-F session
   the suite was green twice while the UI was broken.
7. **Assert on every programmatic edit** (`assert old in s` before a replace). A
   silent no-op replace once produced a "fix" that was never applied, and a
   mutation test that passed anyway.
8. **Fan out for review, never for building.** Subagents share one working tree.
   Tell every reviewer **IN CAPITALS** not to write, edit, `git checkout`,
   `git stash` or `sed -i` anything. A reviewer once mutated `src/` and silently
   reverted work twice. Snapshot your diff to `/tmp` first.
9. **Verify every reviewer claim before acting.** About a fifth do not survive.
   Test the case the reviewer did **not** mention: advice taken on trust once
   made `3*40` render as `340`.
10. **Cap review at TWO rounds**, then ship with the leftovers written down.
    Each round's fixes need their own review, so more rounds is not convergence.
11. **If two fixes in a row add defects, change the approach.** Three rounds on
    one function was the signal; what worked was removing its hardest job and
    asserting the **outcome** rather than the mechanism.
12. **Done means merged AND running in production.** Never close an issue whose
    fix sits on an unmerged branch. Verify three ways: run it and check the
    output; search for absence (a flag never shown, a test in no workflow, a
    value charged for but never sent); confirm `/status.build_sha` equals the
    merged SHA **and** the deploy job actually ran, not `skipped` (issue #62).
13. **One work package, one pull request, merged before the next starts.** Merge
    `main` into your branch **before** starting, not after. A 45-commit branch
    caused a merge conflict that git could not even see — six new test files
    from `main` used a Pydantic model this branch had renamed; only `mypy`
    caught it.
14. **Register every new spec** in `.github/workflows/e2e.yml`. An unregistered
    gate is not a gate. 42 tests in three files currently run nowhere (#127).
15. **`make quality` and `make validate` do NOT include the blocking
    changed-lines coverage gate.** Run `make diff-cover DIFF_BASE=origin/main`
    before pushing.
16. **Run e2e exactly as CI does**, or ~95 phantom failures appear:
    ```bash
    lsof -ti tcp:18085 | xargs -r kill -9
    cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> \
      --project=chromium --workers=1 --retries=0
    ```
17. **Run `pytest` and `make diff-cover` serially, never at once** — they race on
    a shared path and produce a phantom failure (#113).
18. **Plain English in everything** — chat, commits, issues, docs. No jargon, no
    invented phrases, no short form not expanded first.
19. **Do not touch the cost layer** beyond what Task C names. A separate chat
    owns it. File what you find; do not fix it.

---

## 5. Stop points — do not chain work

- **STOP after Task A + B.** Report, and wait.
- **STOP after writing the handoff (Task C).** Report, and wait.
- The handoff you write must **STOP after WP-G2** and wait for explicit
  permission before WP-H.

The reason is context, not ceremony: a chat that runs three work packages loses
the detail that makes review honest, and the operator loses the chance to
redirect between them.

---

## 6. Paste this into a fresh chat

```text
ultracode

Read AGENTS.md, then GUARDRAILS-THEN-HANDOFF-ULTRACODE-PROMPT.md in full
before editing anything.

FIRST: re-measure the state in §1 yourself — make validate lint format-check
type-check openapi-check, then pytest, then BOTH e2e lanes, then
make diff-cover DIFF_BASE=origin/main. Expect 1776 pytest, 138 and 94 e2e,
98% diff-cover, and prod build_sha == the last commit that touched src/
(2bba0d1 at time of writing; main's tip will be AHEAD of that because of
docs-only commits — that is normal, not a failed deploy). Run pytest and
diff-cover SERIALLY (#113). If any number differs, find out why before
writing code.

THEN, in order, stopping between each:
  A. Issue #130 — remove continue-on-error from ci.yml:211 and rename the
     job. Run make mutation-baseline DIFF_BASE=origin/main on your own
     change first.
  B. Issue #131 — a guard that fails a CHANGED spec file whose negative
     assertion has no positive partner. 92 such assertions already exist
     across 23 files, so scope it to changed files only. Copy the shape from
     tests/test_e2e_workflow_covers_all_invariant_specs.py. Prove it catches
     the three real examples in §2 Task B.
     BEFORE WRITING ANY CODE for B: show me the rule, the exception list, a
     worked example from this repo shown three ways, and the pros and cons as
     bullets — then WAIT for my decision. Too strict blocks honest tests; too
     loose catches nothing. That call is mine.
  C. Write WP-G2-TO-WP-H-ULTRACODE-PROMPT.md, with state you measured
     yourself and a hard stop after WP-G2.

RULES: §4 of that file, all nineteen. The ones that cost the most last time:
two review rounds MAX then ship; test the case the reviewer did NOT mention;
never write a check that goes red when the bug is fixed; prove the bite by
mutation using cp and restore from the copy, never git checkout; done means
merged AND verified in production, never green on a branch.

Fan out read-only subagents for recon and adversarial review — tell every one
IN CAPITALS not to write, edit, git checkout, git stash or sed -i anything.
One tree-writer: you.

STOP and report after A+B, and again after C. Do not start WP-G2 or WP-H.
```

---

## 7. What is genuinely unknown

Named, so nobody mistakes an assumption for a fact:

- **Whether `:online` works for the nvidia slot-4 model.** It was settled by
  construction (`ONLINE_CAPABLE_VENDORS = frozenset(DEFAULT_VENDORS)`), never
  measured. Needs a funded key.
- **Real latency at the raised token caps** (2000 debate / 3000 synthesis). The
  180-second deadline at those caps is unproven.
- **Whether the 3 unregistered spec files pass.** Run them before registering
  them; `accessibility.spec.ts` is suspected stale (#127).
- **The right answer for #115 and #118.** A design call, not a code call.
