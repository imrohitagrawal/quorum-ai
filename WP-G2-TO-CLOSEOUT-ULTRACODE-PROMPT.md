# WP-G2, then the guard backlog — handoff for a fresh chat

> **Written:** 2026-07-29, immediately after PRs #140/#144/#147/#149 merged and
> deploy-verified. Every number below was **measured at that moment** by running
> the command shown, not carried from an older document.
>
> **Anchor — this document was written at `b5f2e26`.** That commit is in the
> past and cannot change, so this line is never wrong. To see everything since:
> ```bash
> git log --oneline b5f2e26..origin/main
> ```
> Do NOT expect any identifier below to still be `main`'s tip. Merging this file
> moves it.

---

## 1. State, measured (re-measure before relying on any of it)

| Thing | Value | Command that produced it |
|---|---|---|
| Last product change on `main` | `b5f2e26` | `git log -1 --format=%H` |
| Production `/status.build_sha` | `b5f2e26f8e23…` — **matches** | `curl -s https://quorum.stackclimb.com/status` |
| Deploy | job **ran** (`success`), not skipped | `gh run list --workflow="Deploy to Fly.io"` |
| pytest | 1836 passed, 10 skipped | `uv run pytest -q` |
| e2e blocking invariants lane | 138 passed | see §4 rule 16 for the exact flags |
| e2e axe + parity lane | 94 passed | same |
| Changed-lines coverage | n/a on a clean tree | `make diff-cover DIFF_BASE=origin/main` |
| Open issues | 8, all from this session | `gh issue list` |

**Run `pytest` and `make diff-cover` SERIALLY** — they race on a shared path (#113).

---

## 2. Your job, in order, stopping between each

### Task A — WP-G2 / issue #11: context carry is 2 of 5 links

Every line re-verified 2026-07-29 by running the command in the right column.
**Re-verify anyway.**

| Link | State | How I checked |
|---|---|---|
| Client sends `context` | **NO** — 0 occurrences | `grep -c context src/product_app/static/app.js` |
| `/estimate` accepts it | **NO** — `QueryRunEstimateRequest` has no such field | `python -c "from product_app.query_runs import QueryRunEstimateRequest as E; print('context' in E.model_fields)"` |
| …yet `/estimate` READS it | yes — 1 `getattr(payload, "context", None)` site | `grep -c 'getattr(payload, "context"' src/product_app/query_runs.py` |
| `create` accepts it | **yes** | same trick on `QueryRunCreateRequest` |
| `prior_question` → prompt | **yes** — 3 sites, correctly fenced | `grep -c prior_question src/product_app/providers.py` |
| `prior_synthesis` → prompt | **NO** — 0 in both files | `grep -c prior_synthesis src/product_app/synthesis.py src/product_app/debate.py` |
| Both priced | yes | `costs.py` |

**So an API client sending `context` is charged for tokens no model ever
receives.** The UI never sends it, so no user is affected today.

**The ordering trap:** adding `context` to the create body without also adding it
to the estimate body makes the estimate and the run disagree, producing a
permanent payment-confirmation loop. **Both edits go in ONE commit.**

**Cheap to fix while you are there (issue #125):** `context` values are typed
`Any` and unbounded, so `{"prior_question": 123}` raises `AttributeError` in
`costs.py` — an unhandled 500 on the public API.

**STOP after WP-G2. Report, and wait for explicit permission before WP-H.**

### Task B — the guard backlog (only if the operator asks for it)

Eight issues, all filed this session, none started. Two are **trigger-gated:
do not schedule them.**

| # | What | Size |
|---|---|---|
| **#141** | The doc-honesty gate truncates its scan window at the first comma, so ``(`gate`, blocking)`` is never checked. This is why 7 false "blocking" claims got through. Needs RED-then-GREEN on the exact strings. Expect it to surface further real drift. | S, high value |
| **#146** | #136 is reduced, not closed: **34 of 354** scoped globs still match zero mutants (11 nested functions — mutmut registers their mutants under the OUTER name; 23 with no mutable content). | M |
| **#142** | `report()` misclassifies mutmut exit codes; the `no_tests` guard is bypassed by exit 5 (the *likelier* code). The recorded 87.2–88.7% baseline was produced by this classifier. | M |
| **#148** | The #131 guard is blind to `expect.soft`, `toBeHidden`/`toBeEmpty`, and partners asserted in `beforeEach` or via a page object. | M |
| **#145** | The constant-pin detector ignores reachability (a pin inside `if False:` counts), rejects `pytest.approx`, and misses 16 class-level constants incl. `Settings.RUN_DEADLINE_MAX_SECONDS`. | M |
| **#143** | Nothing pins `replay_mutation_scope.py` ≡ the Makefile's `MUTMUT_SCOPE_PY`, though review measured them equivalent today (66 commits, 0 mismatches). | S |
| **#137** | TRIGGER-GATED: measure p90 mutation runtime on CI. **Only when someone proposes making the gate blocking.** | — |
| **#138** | TRIGGER-GATED: survey the risk-based-testing literature. **Only when someone proposes criticality-tiered gates.** | — |

### Task C — WP-H, only on explicit permission

F-20 (UX batch), F-24 (stale a11y tests), plus #113, #115, #116, #117, #118.
**F-17 and F-16 are already done.** WP-H is smaller than the old plan says.

**#115 and #118 need a design decision from the operator before code:** both are
markup that exists and is never visible, because `.panel.panel-section
{ display: none }` (`app.css:654`) hides the whole legacy section by design.
Delete those surfaces, or move them? **Ask; do not guess.**

---

## 3. Read these first — they are the reason the last session existed

- **`docs/metrics/mutation-gate-study.md`** — why the mutation gate is advisory,
  measured. §7 is the generalisable lessons; §8 is a record of the author
  getting it wrong; §9 names what is still open.
- **`docs/DAY-ONE-PROMPT.md` §4a-bis** — the three rules §4a was missing.
- **`docs/analysis/how-we-steered-this-session.md`** — how the work was
  directed, and which instructions to reuse.
- **`docs/103-incident-learnings.md`** — the 2026-07-29 entry.

---

## 4. Standing rules — every one was learned by breaking something

1. **Verify by executing, never by reading.** A claim about what a tool does is
   UNVERIFIED until you have run it and read its output. Measured last session:
   four separate false claims, each from verifying something *adjacent* to what
   shipped. State the command and what it printed, or say UNVERIFIED.
2. **A green advisory job is not evidence it ran.** Open the log; confirm it
   produced its number.
3. **Before proposing a gate, measure its yield** against real defect history
   (`scripts/replay_mutation_scope.py`) and state what it cannot see.
4. **If the premise of a task turns out to be false, STOP and say so.** Do not
   repair the premise and carry on.
5. **Every test ships with the one line saying what turns it red.** Prove it by
   mutation: `cp` the file aside, mutate, restore from the copy. **Never
   `git checkout <file>`** — the tree may hold uncommitted work. Verify with
   `diff -q`. **And confirm the mutation hit the line you meant** — one probe
   last session mutated a comment and passed.
6. **A negative check needs a positive partner.** A check that counts nothing
   needs something proving the counted thing exists.
7. **Never write a check that goes red when the bug is FIXED.**
8. **Fan out for review, never for building.** Subagents share one working tree.
   Tell every reviewer **IN CAPITALS** not to write, edit, `git checkout`,
   `git stash` or `sed -i`. Snapshot your diff to `/tmp` first.
9. **Verify every reviewer claim before acting.** About a fifth do not survive.
10. **Cap review at TWO rounds**, then ship with the leftovers written down as
    issues. Each round's fixes need their own review.
11. **Done means merged AND running in production.** Verify three ways: the
    deploy JOB ran (not `skipped`/`cancelled`), `/status.build_sha` equals the
    merged SHA, and the thing you built actually fires.
12. **One work package, one pull request**, merged before the next starts. Merge
    `main` into your branch **before** starting.
13. **Register every new gate in a workflow.** An unregistered gate is not a gate.
14. **`make quality` / `make validate` do NOT include the blocking changed-lines
    coverage gate.** Run `make diff-cover DIFF_BASE=origin/main` before pushing.
15. **Run `pytest` and `make diff-cover` serially** (#113).
16. **Run e2e exactly as CI does**, or ~95 phantom failures appear:
    ```bash
    lsof -ti tcp:18085 | xargs -r kill -9
    cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> \
      --project=chromium --workers=1 --retries=0
    ```
17. **`make format` reformats your test assertions.** It flipped
    `assert X == literal` to `assert literal == X` three times last session and
    broke `sed`-style anchors. Grep for the real text before any programmatic edit,
    and `assert old in s` before replacing.
18. **Plain English everywhere.** No jargon, no invented shorthand.
19. **Do not touch the cost layer** beyond what Task A names. A separate chat
    owns it. File what you find; do not fix it.

---

## 5. Stop points

- **STOP after WP-G2 (Task A).** Report and wait.
- **Do not start WP-H without explicit permission.**
- The two TRIGGER-GATED issues are not work. Leave them.

---

## 6. Paste this into a fresh chat

```text
ultracode

Read AGENTS.md, then WP-G2-TO-CLOSEOUT-ULTRACODE-PROMPT.md in full before
editing anything. Then read docs/metrics/mutation-gate-study.md §7-§9.

FIRST: re-measure §1 yourself — make validate lint format-check type-check
openapi-check, then pytest, then BOTH e2e lanes, then
make diff-cover DIFF_BASE=origin/main. Run pytest and diff-cover SERIALLY
(#113). Expect 1836 pytest, 138 and 94 e2e, and prod build_sha == the last
commit that touched src/. If any number differs, find out why before writing
code. If a PREMISE in §2 does not hold when you check it, STOP and tell me —
do not repair it silently.

THEN: Task A only — WP-G2 / issue #11, context carry. The estimate and create
bodies change in ONE commit or the payment-confirmation loop becomes
permanent. Fix #125 (unbounded Any context values -> unhandled 500) while you
are in that file.

RULES: §4 of that file, all nineteen. The ones that cost the most last time:
verify by EXECUTING not reading, and say which command you ran; a green
advisory job is not evidence it ran; prove every test bites by mutation using
cp/restore and confirm the mutation hit the line you meant; two review rounds
MAX then ship with leftovers filed; done means merged AND deploy-verified.

Fan out read-only subagents for recon and adversarial review — tell every one
IN CAPITALS not to write, edit, git checkout, git stash or sed -i anything.
One tree-writer: you.

STOP and report after WP-G2. Do not start WP-H.
```

---

## 7. What is genuinely unknown

- **Whether `:online` works for the nvidia slot-4 model.** Settled by
  construction (`ONLINE_CAPABLE_VENDORS = frozenset(DEFAULT_VENDORS)`), never
  measured. Needs a funded key.
- **Real latency at the raised token caps** (2000 debate / 3000 synthesis). The
  180-second deadline at those caps is unproven.
- **p90 mutation runtime on the CI runner** (#137). The 30-minute-timeout risk
  is an extrapolation from two local data points.
- **Whether the 3 unregistered spec files pass** (#127). Run them before
  registering; `accessibility.spec.ts` is suspected stale.
- **The right answer for #115 and #118.** A design call, not a code call.
