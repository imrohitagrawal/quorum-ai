# Next session — the whole open backlog, in priority order

> **HOW TO USE THIS FILE.** Do not paste this document into a chat. Paste the
> short block in **§9**. One short message from you; one long document for it.

> **Written 2026-07-29**, immediately after PR #169 (`fde39e89`) merged and was
> verified in production. Every number below was produced by running the command
> shown, at that moment.
>
> **Anchor — written at `fde39e89`.** That commit is in the past and cannot
> change. To see everything since:
> ```bash
> git log --oneline fde39e89..origin/main
> ```
> Do **not** expect any identifier below to still be `main`'s tip.

---

## 1. Why this file exists, and the one number that should shape the session

Two work packages in a row shipped a fix and filed more problems than they
closed. Measured:

```
2026-07-27  opened 7   closed 0
2026-07-28  opened 33  closed 9
2026-07-29  opened 12  closed 3
open issues now: 42
```

The backlog grows monotonically. Every session has been finding that the
previous session's work was incomplete, filing that finding, and adding to the
pile. **Your job is to reverse that, not to continue it.**

The rule for this session: **close more than you open.** If an item turns out to
be bigger than it looked, that is a legitimate reason to file — but say so and
stop, rather than filing and continuing.

There is a second number that should shape your priorities more than any process
concern. Over every fix commit touching `src/`, traced by `git blame` to the
commit that introduced each defect (`docs/metrics/defect-discovery-audit.md`):

| How defects were actually found | Count |
|---|---:|
| Adversarial review / bug-hunt fan-out | **10 of 16** |
| Manual testing, driven audit, walkthrough | 3 |
| Production measurement | 1 |
| **An automated check that existed to catch it** | **0** |

**Gates here prevent regressions. They do not detect new defects.** Weight your
effort accordingly: fixing a live money defect beats building another gate.

---

## 2. State, measured — re-measure before relying on any of it

| Thing | Value | Command |
|---|---|---|
| `main` tip | `fde39e89` | `git log -1 --format=%H` |
| Production `build_sha` | `fde39e89` — **matches** | `curl -s https://quorum.stackclimb.com/status` |
| Deploy | job **ran** (`success`); a sibling run shows `cancelled` — concurrency dedupe, not a failure | `gh run list --workflow="Deploy to Fly.io" --branch main` |
| Last commit touching `src/` | `1c6954b` (2026-07-29) — **note this** | `git log -1 --format=%h -- src/` |
| pytest | **1905 passed, 10 skipped** | `uv run pytest -q` |
| e2e invariants lane | **138 passed** | §8 rule 12 for the exact flags |
| e2e axe + parity lane | **94 passed** | same |
| Changed-lines coverage | 100% on the merged diff | `make diff-cover DIFF_BASE=origin/main` |
| Open issues | **42** | `gh issue list --state open --limit 200 --json number -q 'length'` |

**Run `pytest` and `make diff-cover` SERIALLY** — they race on a shared path (#113).

---

## 3. FIRST — WP-H needs a decision from the operator before any code

**Do not write code for this. Ask, then wait.** Two issues need one design call,
and they must be decided together because they are the same call.

### The problem, precisely

`src/product_app/static/app.css` hides a whole class of legacy markup on every
screen:

```css
.layout > aside,
.panel.panel-section { display: none; }
```

The rationale is written out at `app.css:578-594` — the design-comp parity work
hid the legacy panels but kept them in the DOM so `app.js` render targets stay
valid. The consequence is that **three separate features render into markup no
user can see**:

| Issue | What renders into nothing |
|---|---|
| #111 (fixed) | the readiness banner — moved out, resolved |
| **#115** | `#demo-mode-banner` (`workspace.html:912`). `app.js:4091` sets `hidden = false`; measured `rect: {w:0, h:0}` |
| **#118** | per-model `provider_notice` → `.model-card-notice`. Measured 0×0 in all three views |

### The sharper half of #115 — a blocking gate certifies an invisible element

`e2e/tests/degraded/degraded-banner.spec.ts:146-168` is in the **blocking** CI
lane and asserts:

```ts
await expect(banner).toContainText(/3 of 4 model answers came from a live provider/i);
```

`toContainText` does **not** require visibility. So a hard merge gate is
currently certifying the honesty of a 0×0 element. That is the worst
combination — the defect plus a passing test on top, which reads as covered.

### What is already true, so you are not deciding blind

- The result view already renders `#result-degraded`, which carries the same
  "N of 4 came from a live provider" message and **is** visible. #115's banner
  may simply be redundant.
- WP-F already put the per-model notice somewhere visible — the transcript
  opening card, with a blocking gate asserting `toBeVisible()`. #118's
  `.model-card-notice` path is a **duplicate**, not the only surface.
- The run-level notice list (`#live-notices`) is a separate, genuinely visible
  path and is not in question.

### The options, with the trade-offs

**Option A — delete the dead paths.** Remove `#demo-mode-banner` and its
renderer; remove the `.model-card-notice` render; repoint the degraded-banner
spec at `#result-degraded` and require `toBeVisible()`.
*For:* smallest diff; removes markup nothing reads; the visible surfaces already
exist and are gated. *Against:* if the legacy "Model outputs" section is ever
un-hidden, the per-model notice has to be rebuilt.

**Option B — un-hide the legacy "Model outputs" section.** Make the markup
visible rather than deleting it.
*For:* the notices appear where the model answers are, which is arguably where a
user looks for them. *Against:* reverses a deliberate design-comp decision;
touches every view's layout; needs new visual baselines; much larger blast
radius. This is a product design change, not a bug fix.

**Option C — leave the markup, fix only the gate.** Make the spec require
visibility so it stops certifying nothing, and accept the dead paths.
*For:* tiny; stops the false assurance immediately. *Against:* leaves dead code
that will trip the next person exactly as it tripped the last three.

### Recommendation

**Option A, with one caveat to confirm.** The visible surfaces already exist and
are gated, so deleting the duplicates loses no user-facing information — and the
gate change is the part that matters most, because a blocking test over an
invisible element is worse than no test.

**The question I need answered before writing any code:**

> Is the legacy "Model outputs" `section.panel.panel-section` intended to come
> back — is it hidden temporarily pending design work, or permanently superseded
> by the transcript and result views?
>
> - If **permanently superseded** → Option A, and the whole hidden-panel class
>   should be deleted rather than kept as render targets.
> - If **temporarily hidden** → Option C now (fix the lying gate), and file the
>   deletion against whenever the design work lands.

Also confirm: **may the degraded-banner spec be changed to require
`toBeVisible()`?** It is a blocking gate; tightening it may red the lane until
the markup question is settled, and that is a merge-blocking decision.

---

## 4. Then, in this order

Ranked by what can hurt, not by what is satisfying to build.

### Tier 1 — money and unbounded spend

| # | What | Note |
|---|---|---|
| **#100** | **No deployment-wide spend ceiling.** `DAILY_CAP_USD = 0.20` is **per account**, and `GET /v1/session` mints an account on demand with no payment instrument and no proof of anything. Exposure = (accounts an attacker can mint) × $0.20. The only limiter is a per-IP bucket that is **in-process only**, so it does not hold across Fly machines or restarts. | **Needs a policy decision from the operator first** — what IS the deployment ceiling? Do not invent the number (`docs/DAY-ONE-PROMPT.md` §4a: an unmeasured guardrail number is a fabricated one). |
| #106 | Spend continues inside debate/synthesis after a cancel (F-05 Layer 2) | Live money leak |
| #110 | A **billed** Layer-B judge call is dispatched by the response that serves `cost_source="measured"` | Live |
| #151 | The 0.0008 fallback price is underived and under-charges one shipped model by 25%; the FAQ misstates it | |
| #122 | Spend-cap policy when the ledger is known stale (follow-up to #109) | Needs a decision |

**Money is 31% of this project's entire defect history** — 5 of 16 traced
defects. It is the highest-yield place to spend the session.

### Tier 2 — a gate that is not a gate

| # | What |
|---|---|
| **#127** | **42 e2e tests run in no CI workflow.** Three committed, maintained spec files execute nowhere; one was edited on 2026-07-27 and still runs nowhere. Cheapest large win on the board. |
| #126 | Session trail can never hold more than one entry — **and its blocking gate enforces the bug** |
| #129 | Stale visual baselines are the only thing blocking PR #96 from production |
| #62 | A Deploy run reports `success` when the Deploy job is `skipped` |

### Tier 3 — the enum and test-oracle gaps

| # | What |
|---|---|
| **#161** | The F-05 test drives 5 of the 6 terminal statuses; `BLOCKED_BY_COST` is never exercised. **UNVERIFIED whether it is a live bug** — settle it in 30 minutes: add the status to `TERMINAL_STATUSES_UNDER_TEST` and run the file. Green ⇒ coverage hole. Red ⇒ a real defect in terminal-run handling, the class that already cost a 989-line fix. |
| #160 | 12 of 14 production enums have no test that fails when a member is added. `QueryRunStatus` has 13 members and is F-05's exact shape. Proven to work: adding a third `BillableStage` reddens 6 tests immediately. |
| #163 | The consumer-side synthesis cap has no test; the mutation survives (measured) — **test-only fix, the production line is correct** |

### Tier 4 — gate liveness, the rest

| # | What |
|---|---|
| #166 | **Work package**: 6 gates can still report a status having measured nothing. Four *detect* the unmeasured state and then `exit 0`. Carries the RCA, the empty-input checklist, a hard ~5s-per-gate runtime ceiling, and the **mutation-gate watchdog**. |
| #167 | Nothing proves a guard test bites. Tiered plan; the helper (`tests/code_text.py`) already ships. |
| #165 | PR #164 leftovers — the diff-cover floor still passes with no denominator when its JSON report is missing |
| #162 | Superseded by #166; close it when #166 is picked up |

### Tier 5 — the standing backlog

#103 (nightly feedback-audit has never audited production), #104, #105, #112,
#113, #116, #117, #120, #123, #124, #128, #134, #141, #142, #143, #145, #146,
#148, #156, #158, #63.

**#137 and #138 are TRIGGER-GATED. They are not work. Leave them.**
**#155: do not attempt.** The obvious fix is measured to be worse than the bug.

---

## 5. The debt this session inherits, stated plainly

**The mutation gate has never printed a score in CI.** #158 is still open for
exactly this reason. The repair is proven locally in both directions on the same
tree — the old resolution gives `assert 514 <= 55` → `failed to collect stats` →
no score; the repair gives `2 killed, 0 survived → 100.0%`. It has never run to a
score on a GitHub runner, because it only scopes on a pull request that changes
`src/` Python, and the last two work packages changed none.

**This is now the second time follow-through has depended on someone
remembering, and it has failed both times.**

**So:** Tier 1 and Tier 3 both touch `src/`. Whichever you do first, that pull
request is the one that finally scores. **Open its `mutation-baseline` job log
and quote the number in your closing report.** Do not manufacture a `src/` edit
to feed the gate — that is the dishonesty this whole line of work exists to
remove.

---

## 6. Ultracode — yes, and where

**Use `ultracode` for this session.** Justification, not habit: the top of the
backlog is money and spend-cap work, where the measured discovery route is
adversarial review at 10 of 16, and where a wrong answer costs real money.

Where to fan out **wide**:

- **Recon and review — always.** Read-only, parallel, diverse lenses. Tell every
  subagent **IN CAPITALS** not to write, edit, `git checkout`, `git stash` or
  `sed -i` anything. Snapshot your diff to a scratch path first.
- **The money issues (#100, #106, #110, #151)** deserve a reviewer whose
  explicit job is to *break* the change and find the evasion.

Where **not** to fan out:

- **Building.** Subagents share one working tree; parallel writers corrupt each
  other. One tree-writer: you. Parallelise builds only across disjoint files
  with `isolation: "worktree"`.

---

## 7. What must be written into `docs/DAY-ONE-PROMPT.md`

**Standing operator instruction, every work package, not just this one.** A
lesson that lives only in a chat, a pull request body or a closing report **is
lost**. If this session teaches something pivotal, write it into that file **in
the same pull request that teaches it**, in portable general terms — no issue
numbers, no file paths — then cite the measurement in one line.

What counts as pivotal: a rule you had to invent because none existed; anything
that made a green or red signal untrustworthy; any check that turned out to be
measuring nothing; any fix that was worse than the bug; anything that cost more
than an hour and would have been cheap to prevent.

**Already in that file from the last two sessions — read §4a-bis before you
start, and do not re-derive these:**

- A green advisory job is not evidence it ran. **A red one is not evidence it
  measured.** Open the log; find the number.
- Every gate must be able to **state its denominator** and fail when it is
  empty. Nearly every gate is a negative check, and negative checks are
  trivially true over nothing.
- **Before adding a gate, count how your last N real defects were found.**
- A guard test must assert against **structure, never a substring of a file** —
  a substring matches the prose that explains the thing, not the thing. Four
  consecutive attempts at one pin failed this way.
- Any check resolving paths from `__file__` points at the copy when a tool
  re-runs your suite from a generated tree.

**Candidate additions this session may earn** — only if measured, not if merely
plausible:

- What a per-account cap is worth when identities are free to mint (#100). This
  generalises: **a quota is only as strong as the identity it is attached to.**
- Whether "delete the dead path" or "make it visible" is the right default when
  markup exists that no user can see but a gate asserts on (WP-H).

---

## 8. Standing rules — every one was learned by breaking something

1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud.
2. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log.
3. **Before proposing or promoting a gate, measure its yield** against real
   defect history and state what it cannot see.
4. **If a premise in this document turns out to be false, STOP and say so.** Do
   not repair it silently and carry on.
5. **Every test ships with one line saying what turns it red.** Prove it by
   mutation: `cp` the file aside, mutate, restore from the copy, verify with
   `diff -q`. **Never `git checkout <file>`.** Confirm the run actually
   executed — a mutation that breaks collection proves nothing.
6. **A negative check needs a positive partner.**
7. **Never parametrize a test over the constant it tests**, and **never assert a
   bound against the constant that defines it.**
8. **Assert structure, not substrings.** Use `tests/code_text.py` when you must
   read a file that also contains prose.
9. **Fan out for review, never for building.** IN CAPITALS: reviewers must not
   write.
10. **Verify every reviewer claim before acting.** About a fifth do not survive.
    On PR #164 two reviewer claims were refuted by execution. **Check the fix,
    not just the finding** — a round-1 fix there introduced two vacuous tests.
11. **Cap review at TWO rounds**, then ship with leftovers filed as issues. Each
    round's fixes need their own review. **If two fixes in a row add defects,
    change the approach** — that rule fired on PR #164 and the fifth attempt only
    worked because the approach changed from pinning source to observing
    behaviour.
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
    `main` into your branch **before** starting. **Check you are on your branch
    before committing.**
17. **Done means merged AND running in production.** Verify three ways: the
    deploy **job** ran (not `skipped`/`cancelled`), `/status.build_sha` equals
    the merged SHA, and the thing you built actually fires. Probe production only
    where it costs nothing — `/estimate` makes no provider call; a full run does.
18. **Plain English everywhere. No jargon, no invented shorthand.** This was
    violated twice in the last session — "conservation invariants at the seam"
    should have been "a test that checks the money adds up".
19. **A pivotal lesson goes into `docs/DAY-ONE-PROMPT.md` in the same pull
    request that teaches it.**
20. **Close more than you open.** If an item is bigger than it looked, say so and
    stop — do not file and continue.

---

## 9. Paste this into a fresh chat

```text
ultracode

Read AGENTS.md, then NEXT-SESSION-ULTRACODE-PROMPT.md in full before editing
anything. Then read docs/DAY-ONE-PROMPT.md §1 and §4a-bis, and
docs/metrics/defect-discovery-audit.md.

FIRST: re-measure §2 yourself — make validate lint format-check type-check
openapi-check, then pytest, then BOTH e2e lanes, then
make diff-cover DIFF_BASE=origin/main. Run pytest and diff-cover SERIALLY
(#113). Expect 1905 pytest, 138 and 94 e2e, prod build_sha == main's tip. If any
number differs, find out why before writing code. If a PREMISE in this file does
not hold when you check it, STOP and tell me — do not repair it silently.

THEN §3 — WP-H. Do NOT write code for it. Ask me the clarifying questions in §3,
with the options and your recommendation, and WAIT for my answer.

THEN work §4 in order. #100 needs a policy number from me before any code — ask,
do not invent it. Tier 1 and Tier 3 touch src/, so whichever you do first is the
pull request that finally makes the mutation gate print a score in CI — open its
job log and quote that number. Do not manufacture a src/ edit to feed it.

RULES: §8 of that file, all twenty. The ones that cost the most: verify by
EXECUTING not reading, and say which command you ran; assert structure not
substrings; prove every test bites by mutation using cp/restore and confirm the
run actually executed; verify a reviewer's FIX, not just the finding; two review
rounds MAX then ship with leftovers filed; done means merged AND deploy-verified;
plain English, no jargon.

CLOSE MORE THAN YOU OPEN. The backlog has grown every session — 42 open now. If
something is bigger than it looked, say so and stop rather than filing and
carrying on.

Fan out read-only subagents for recon and adversarial review — tell every one IN
CAPITALS not to write, edit, git checkout, git stash or sed -i anything. One
tree-writer: you.

Anything pivotal you learn goes into docs/DAY-ONE-PROMPT.md in the SAME pull
request that teaches it, in portable general terms.

STOP after Tier 1 and report, listing every pending item with its issue number,
what you closed, and what you added to docs/DAY-ONE-PROMPT.md.
Do not attempt #155. #137 and #138 are TRIGGER-GATED — leave them.
```

---

## 10. What is genuinely unknown

- **Whether `BLOCKED_BY_COST` is a live F-05 defect** (#161). Thirty minutes
  settles it; nobody has spent them.
- **What the deployment-wide spend ceiling should be** (#100). A policy number
  only the operator can set.
- **Whether the legacy hidden panels are coming back** (WP-H). A design call.
- **p90 mutation runtime on the CI runner** (#137). Still an extrapolation; the
  one local data point (23.4s generation, 7.32 mutations/second) came from a
  build directory since cleared, so it is not reproducible.
- **Whether the mutation gate produces a usable score once it scores in CI.** It
  never has.
