# ultracode — #171: stop substituting fabricated answers, autonomous through merge

> **HOW TO USE THIS FILE.** Do not paste it into a chat. Paste the block in **§11**.
> One short message from you; one long document for the session.
>
> **Anchor: written against `main` at `4749aa5`, deployed and verified.** That
> commit is in the past and cannot change, so this line is never wrong. See
> everything since with `git log --oneline 4749aa5..origin/main`. **Every other
> number, path and line reference in this file is a claim you must re-measure.**

---

## 1. The operator grant — read this before anything else

`AGENTS.md` rule 17b normally requires explicit human approval to push, open a
pull request, merge, or deploy. **For this task only, that approval is granted in
advance.** You may run the whole loop to merge and deploy without checking in,
**provided every condition in §7 holds.** If any one of them fails, you stop and
report instead — the grant is conditional, not blanket.

The grant does **not** extend to:

- **Any paid API call.** Hermetic and $0 throughout. No funding a key, no live
  provider run, no secret rotation.
- **Inventing the debate-participant floor.** See §3. That is an operator
  decision and it stays one.
- **Widening scope beyond #171.** File what you find; do not fix it here.
- **Closing any issue other than the ones your change actually closes**, and only
  with the evidence that it does.

---

## 2. What #171 is

**Read the issue itself — `gh issue view 171` — it is the source of truth and it
is unusually well evidenced.** This section is orientation only.

When one model's live call fails, the product **fabricates an answer for that
slot, marks it `completed`, and feeds it to the debate, the synthesis, the
agreement count and the source-coverage figure as if it were real.** Simulation is
applied per model, not per run.

The consequence is not a labelling problem. Four numbers the product leads with
are wrong on any run where a provider failed. The sharpest: a simulated answer is
given a source with `is_fallback=False`, which is exactly what makes a source
count as *primary* — so **a run with one real answer and three simulated ones
reports 100% source coverage, three quarters of it fabricated.**

The issue records eight findings, each with the file and the run that produced it.
It also records a measured reproduction that patched `urlopen` to raise
`TimeoutError` for slot 2 only — no network, no paid call. **Reproduce it yourself
before you build anything.** If it does not reproduce, that is a premise failure:
stop and say so.

---

## 3. The one thing you must NOT decide

The issue's rule 3 carries an explicit open question:

> should there also be a minimum number of answers before running a debate at
> all? A debate arguably needs more than one participant, but any specific floor
> is a product call and must not be invented here — **an unmeasured guardrail
> number is a fabricated one.**

**Do not pick that number.** Implement everything else; leave the floor
unenforced, record it as an explicit operator question in your final report, and
say what it would take to settle it. Shipping a guessed threshold as enforcing is
the exact failure this whole issue is about.

---

## 4. Phase 0 — re-measure the ground, then reproduce

Nothing below is trusted until you have run it.

```bash
git branch -f main origin/main          # do this FIRST
git log --oneline 4749aa5..origin/main
gh issue view 171 --json state -q .state          # must still be OPEN
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
uv sync --all-extras
make quality && make validate           # green BEFORE you touch anything
```

Record the pass count. **"Pre-existing" must mean measured against a named commit,
and you must say which** — otherwise you will attribute an inherited failure to
your own change, or worse, the reverse.

Then **reproduce the defect** with a fault-injection probe in the shape the issue
describes (patch the provider seam to fail exactly one slot; assert what the
debate, synthesis, agreement count and coverage figure then contain). Capture the
verbatim output. **That output is your RED.** If you cannot reproduce it, stop.

Also confirm the related issues the backlog claims this absorbs or unblocks —
check each by execution rather than by reading the claim, and say which ones your
change will actually close.

---

## 5. Phase 1 — plan, with subagents if it helps

Fan out **read-only** planners if the design space is genuinely open; otherwise
plan it yourself and move on. **Tell every subagent, IN CAPITALS: DO NOT WRITE,
EDIT, CREATE OR DELETE ANY FILE. DO NOT RUN `git checkout`, `git stash`,
`git commit`, `git add` OR `sed -i`. REPORT FINDINGS AS TEXT.**

The issue proposes a three-rung ladder. Decide, **by measuring the diff size, not
by preference**, whether they ship as one pull request or a sequence:

- **Rung 1 — make it not happen.** Live execution on + a model fails ⇒ the slot is
  reported missing. No invented answer. Debate, synthesis and agreement compute
  over answers that actually arrived, with the denominator being answers received.
  No fabricated source contributes to a trust number. Every stage reports its own
  provenance — the debate currently builds `fallback_messages` and then discards
  them, and `DebateResult` has no field for them.
- **Rung 2 — make it visible.** Tests that assert the *numbers*, not the statuses.
  See §6.
- **Rung 3 — make it unrepresentable.** A required provenance field on the answer,
  consumers switching exhaustively (`assert_never`, so mypy fails on an unhandled
  kind), and the coverage/agreement functions accepting only real-provenance
  answers. Plus an exhaustive pin on the provenance set **derived from the enum,
  never retyped**.

**One concern per pull request.** A slice must be independently shippable and
reviewable in one pass. If rungs 1+2 and rung 3 cannot honestly be reviewed
together, they are two pull requests, and the second starts only after the first
merges. Say which you chose and why, with the changed-line count that decided it.

Also plan the **user-facing reporting rule** the issue requires: every trust number
states its denominator and what it excluded — *"coverage 100% (4 of 4 answers, 0
excluded)"*, never a bare *"100%"*. That touches `app.js` and the golden fixture,
so it brings the e2e invariants with it.

---

## 6. Phase 2 — build serially, test so it bites

**Build with ONE writer: you.** Subagents share one working tree and parallel
writers corrupt each other. Parallelise a build only across genuinely disjoint
files using `isolation: "worktree"`, and keep any tightly-coupled unit — a surface
plus the specs asserting its exact shape — as one builder. **Fan the review, never
the construction.**

Test discipline, all of it non-negotiable:

- **RED first, and capture the verbatim failure.** "It failed" is not evidence; the
  message is.
- **Prove every test bites by mutation.** `cp` the file aside, re-introduce the
  defect by hand, watch it go red, restore **from the copy**. **Never
  `git checkout <file>`** — it discards uncommitted work. Confirm with `diff -q`.
  Purge `__pycache__` first; stale bytecode gives false green *and* false red.
- **Assert CARDINALITY, not clean-path outcome.** This is trust-number code, the
  same family as accounting. Assert *how many* answers were counted, *how many*
  sources were treated as primary, *what the denominator was* — never merely that
  a run completed. Ask of every assertion: **could this fail for ANY
  implementation?** If not, it is worthless.
- **A negative check needs a positive partner.** "No fabricated answer reached
  synthesis" is trivially true over an empty list.
- **Do NOT enforce this by grepping source text for the fabrication.**
  `docs/DAY-ONE-PROMPT.md` §4a-bis records four consecutive failures of exactly
  that approach. Assert the observable consequence.
- **The mixed case is the gap.** The issue measured that no test covers a run with
  real *and* simulated answers together — the two that look like they do use a
  *failed* slot, not a simulated one. That mixed case is the heart of this fix.
- **If you touch a UI surface, add its shape to `e2e/fixtures/golden-run.ts` in the
  same change**, or the gate cannot see it. Run any timing-sensitive spec N≥10× for
  a real flake rate rather than asserting once.

---

## 7. Phase 3 — review, gates, merge. The conditions on the grant.

### Review — two lenses, two rounds, no third

Fan out **read-only** reviewers on the staged diff. Two lenses, not five: two
reviewers find about as much as four and one finds less. Spend the difference on
verification.

- **One lens must EXECUTE rather than read.** Give it its own copy
  (`git archive HEAD | tar -x -C <dir>`) if it needs to mutate source. Its prompt
  must require pasted command output for every verdict — **a verdict with no output
  is void.** On this repository the executing lens has found the real defects while
  reading lenses produced refuted noise.
- **One lens is the breaker**, whose explicit job is to get a fabricated answer
  past your new guard. This is trust-and-money code; that lens is mandatory.
- **Reviewers refute by default** and report only findings backed by a demonstrated
  failure. Reviews are read-only; you are the single writer who applies fixes.
- **Verify every reviewer claim by execution before acting on it.** Roughly a fifth
  do not survive. **Check the fix, not just the finding.**
- **Round 2 re-reviews the FIX DIFF ONLY.** Expect your own fix to introduce a
  defect — that is measured here, repeatedly. **Then stop.** No round three.

### Gates — all six required contexts

`make quality` and `make validate` do **not** cover the merge gates. Re-derive the
required list rather than trusting any table:

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
```

Run, stopping on the first red — and run `pytest` and `make diff-cover` **serially**,
they race on a shared path:

```bash
make quality && make validate
make diff-cover DIFF_BASE=origin/main
make api-contract
make openapi-check
make security-scan
# e2e exactly as CI does, or ~95 phantom failures appear:
lsof -ti tcp:18085 | xargs -r kill -9
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> \
  --project=chromium --workers=1 --retries=0
```

**Never lower a threshold, add `# pragma: no cover`, or delete a test to go green.**
If a line is genuinely untestable, say so with evidence.

### Merge — only if ALL of these hold

1. The defect **reproduces before** the change and **does not after**, with both
   outputs captured.
2. Every new test **proven to bite** by mutation.
3. All six required contexts green on the real runner. Re-verify the rollup
   independently — the API is flaky, re-check once on error.
4. Two review rounds completed; every surviving finding fixed or explicitly listed
   as shipped-open in the pull request body.
5. No fabricated number, label or threshold anywhere in the change — including the
   debate floor from §3.
6. The pull request body says what changed, what it closes, what it deliberately
   leaves open, and **one line on why this item outranks the top of the backlog.**

Then merge:

```bash
gh pr merge <n> --squash --delete-branch --subject "<explicit>" --body "<explicit>"
```

**Never a bare `--squash`** — it concatenates every commit body onto `main`.

**If any condition fails, do not merge. Stop and report with the open findings
listed.** That is a successful outcome, not a failure.

### Deploy — verify three ways, then prove the thing fires

```bash
git branch -f main origin/main    # the merge lands on the remote; the local ref does not follow
```

- The Deploy **job** concluded `success` — not `skipped`, not `cancelled`, and not
  the run's rollup. **A merge produces two runs; one is cancelled by concurrency
  dedupe.** Resolve the **newest run by `createdAt`**, then read its Deploy job.
- `/status.build_sha` equals the merged SHA.
- Prod health: `/ready` returns `live_readiness.state: live`.
- **The thing you built actually fires.** Probe production only where it costs
  nothing — `/ready`, `/status`, `/metrics`, `/ui/ops` and `/estimate` are free; a
  full run is not.

---

## 8. Phase 4 — report, and name the next action

Write `ISSUE-171-RESULT.md` at the repo root:

1. **What shipped** — pull request number, squash SHA, deploy run id, the Deploy
   job conclusion, and the prod `build_sha` you observed.
2. **RED → GREEN** — the reproduction before, the same probe after, both verbatim.
3. **The bite proofs** — for each new test, the mutation you made and the failure
   it produced.
4. **Review** — findings raised, findings verified, findings refuted, findings
   fixed. Report the refuted ones too; a refutation is a result.
5. **Issues closed**, each with the evidence that it is closed.
6. **Shipped open** — anything left, and why.
7. **The operator queue** — the debate-participant floor from §3, with the exact
   question and what would settle it.
8. **The next action item**, ranked by what can hurt, with the one line saying why
   it outranks the alternatives. Derive it from the live backlog, not from this
   document.

Then **stop.** Do not start the next item.

---

## 9. Stop and ask instead of proceeding if

- The defect does not reproduce, or reproduces differently than the issue says —
  **a false premise is a mandatory stop.**
- A fix would require inventing a number, a threshold, or a label.
- Review has not converged after two rounds.
- CI is red for a reason you cannot root-cause from the logs.
- The change would put a new job on the deploy path, or make deploys depend on an
  untested one.
- You discover a higher-ranked item mid-work — **that is a mandatory stop.** Park
  the branch, record it, re-run selection.
- The work turns out to be materially bigger than one reviewable pull request and
  cannot be honestly split.

---

## 10. Standing rules — every one was learned by breaking something here

1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud.
2. **When you CORRECT a false claim, verify the REPLACEMENT before writing it.**
   Twice on 2026-07-30 a correction was itself wrong — one of them "corrected" a
   rule that was already right.
3. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log and find the number.
4. **Assert structure, not substrings.** A substring matches the prose explaining
   the thing; this repository has a live gate satisfied by a comment.
5. **Never parametrize a test over the constant it tests.**
6. **Fan out for review, never for building. One tree-writer: you.**
7. **A content audit cannot see an inbound reference.** Before concluding anything
   is unused, `git grep` for it. That gap broke 18 tests here on 2026-07-30.
8. **Before deleting any file, `git ls-files` it.**
9. **`make format` reformats test assertions.** Grep for the real text and
   `assert old in s` before any programmatic edit.
10. **Line numbers are locators, not addresses.** Confirm the quoted text — the
    references in the issue were captured at `d3994253` and will have drifted.
11. **Never fabricate a number, label or baseline.** "Unmeasured" must never read
    as "clean". Absent means `—`, never a placeholder.
12. **Plain English. No jargon, no invented shorthand.**
13. **Close more than you open.** If an item is bigger than it looked, say so and
    stop — do not file and continue.

---

## 11. Paste this into a fresh chat

```
ultracode

Work issue #171 end to end, autonomously, through merge and deploy verification.

Read ISSUE-171-ULTRACODE-PROMPT.md at the repo root and follow it. Read AGENTS.md
first — its operating rules bind, and rule 14's gate list must be re-derived with
gh api rather than trusted. Then read the issue itself: gh issue view 171.

You have my approval in advance to branch, commit, push, open a pull request,
merge and verify the deploy WITHOUT checking in — but only if every condition in
section 7 holds. If any one fails, stop and report instead.

FIRST: re-measure section 4 yourself and REPRODUCE the defect before building
anything. If it does not reproduce, or any premise in the issue does not hold,
STOP and tell me — do not repair it silently.

DO NOT invent the minimum-answers-before-debate floor (section 3). Leave it
unenforced and put it in the operator queue.

Build serially — one tree-writer, you. Fan out read-only subagents for planning
and review, and tell every one IN CAPITALS not to write, edit, git checkout, git
stash or sed -i anything. Two review lenses, not five, one of which must EXECUTE
rather than read and one of which is a breaker trying to get a fabricated answer
past the new guard. Two rounds maximum, the second on the fix diff only, then stop.

Assert cardinality, not clean-path outcomes. Prove every test bites by mutation
using cp-aside and restore-from-copy, never git checkout. Do not enforce this by
grepping source text — assert the observable consequence.

Hermetic and $0 throughout: no paid API calls, no funded key, no live provider run.

When done, write ISSUE-171-RESULT.md and tell me the next action item with one
line on why it outranks the alternatives. Then stop.
```
