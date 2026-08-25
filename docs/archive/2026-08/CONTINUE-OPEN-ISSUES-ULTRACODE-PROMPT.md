# ULTRACODE — close the open backlog, free work first, paid probes last

> Paste everything below the line into a fresh Claude Code chat in this repo.
> Written 2026-08-17 at `main` = `7688528`. Every "measured" fact carries its
> date. **Treat all of it as INHERITED and re-verify before acting** — AGENTS.md
> rule 11 measures that roughly half of what a handoff asserts does not survive
> contact with the tree, and the previous session proved it twice.

---

ultracode: Continue the autonomous backlog-closing run in this repo
(`im<user>/quorum-ai`). Work the open GitHub issues in the phase order
below: **every item that can be closed without spending money first, then a
single deliberate paid session last.**

You have my full, standing authorization to push branches, open pull requests,
merge to `main`, and deploy — without asking me at any point. Do not pause for
approval before any individual merge and do not ask me to re-confirm autonomy.

**That authorization does NOT extend to spending money.** Phase 3 stops and waits
for me. See Phase 3 for exactly what to bring me.

## The state you are inheriting (verified 2026-08-17 — re-check it)

```
main (local) == origin/main == 7688528     0 ahead, 0 behind
prod /status.build_sha       == 7688528db7915371890e1d0568ef340de6571795
open PRs                     == none
worktrees                    == only the main checkout
```

**One live branch, deliberately unmerged:** `fix/226-vacuous-e2e-negative-assertions`
— the escalated #226 work. Kept because it holds real value (13 partners, a CSP
self-check proving the violation listener is live, 0 failures in 760 spec runs).
NOT mergeable as it stands; see its section.

**Untracked files:** this prompt, and six `docs/analysis/2026-*.md` that
**predate** the previous session. Do not clean those up on your own initiative.

Previously merged and deployed: #326 + #325 (`cc40737`), #209 (`7688528`), both
verified by the Deploy job's own conclusion and `/status.build_sha`. Filed: #332.

## Architecture: orchestrator + one sub-orchestrator per work package

**You are the MAIN ORCHESTRATOR.** You do not build and you do not review. You own
selection, sequencing, merging, deploy verification, issue closing, ADR number
assignment, and the final report. You hold the only global view, so you are the
only one who can see cross-package collisions.

**For each work package launch ONE sub-orchestrator** via the Workflow tool. It
owns one package and runs its whole internal lifecycle:

```
sub-orchestrator(work package)
  ├─ survey      read-only; re-derive the issue's claims by execution
  ├─ build       ONE sole writer, isolated worktree, strict TDD
  ├─ review      6 read-only adversarial lenses, each its own worktree
  ├─ fix         ONE sole writer applies surviving findings
  └─ re-review   3 lenses: did the FIX introduce a defect?
  → returns {branch, commit, findings, mergeable, open_findings}
```

It returns to you. **You** gate it, merge it, verify the deploy, close the issue,
and only then launch the next.

**SERIALIZE THE PACKAGES. Do not run two sub-orchestrators at once.** The previous
session ran three in parallel and all three independently created
`docs/adr/0047-*.md` while every gate stayed green. Parallelism is right for
*review* — independent lenses catch what one pass misses — and wrong for
*building*, because sub-agents cannot see their siblings and a numbered-artifact
directory is a shared namespace even when the code files are disjoint.

**Assign every ADR number yourself, before launching**, and have the builder
re-check `git ls-tree --name-only origin/main docs/adr/ | tail -3` immediately
before pushing.

Wrap every sub-orchestrator call in try/catch. One package's infrastructure
failure must not kill the run: catch it, record it, move on.

## Step 0 — triage fresh, trust nothing inherited

Run `gh issue list --state open` and `gh issue view` every one. For each, **verify
its claim by executing something** before deciding it is real, already fixed, or
how to fix it. Issues here go stale in measured ways:

- **#226's body says 20 violations; the real count was 13** (2026-08-15) — seven
  had been fixed by other work.
- **#209's file paths were wrong** — call sites had moved from `tests/e2e/` to
  `tests/security/` and from `tests/integration/` to `tests/perf/`.
- **#226's causal claim was also wrong**: it credits #148 with exposing 13 sites;
  running the pre- and post-#148 guards over the same corpus gives 8 vs 13 with
  **7 in common**, so #148 exposed 6.

Two of nine issues described a tree that no longer existed. Assume yours do too.

---

# PHASE 1 — free code work, in this order

## 1.1 — #332: no gate catches duplicate ADR numbers

**Do this first.** It is the smallest item, it protects every later package, and
it smoke-tests your whole pipeline (build → review → merge → deploy → close) on a
low-risk change before you bet #216 on that machinery.

**Verified 2026-08-17:** `tests/unit/test_docs_numbering_no_collisions.py:20` uses
`^docs/(\d+)-`, which does not match `docs/adr/NNNN-*.md` at all:

```
docs/24-adr-index.md   -> True
docs/adr/0047-foo.md   -> False
```

With two `0047` files present, `make validate` exited **0** and the index carried
two ADR-0047 rows. The new gate **must refuse to pass on empty input** (assert it
found at least N ADRs), and ships with a negative partner (a synthetic duplicate
goes red) and a positive partner (the real, currently-unique tree goes green).
Also decide whether `scripts/generate_adr_index.py` should refuse to write an
index containing a duplicate.

## 1.2 — #216: judge re-dispatch bills with no ledger correction

The highest-value item and the only remaining `src/` change. **This is a design
decision before it is a code change.** Per rule 16e, enumerate the failure modes
of a spend gate on a read path FIRST, on one page, drawing on `docs/adr/` — then
design against that list. The spend-cap work went five review rounds because the
failure modes were discovered one at a time from defects instead of listed up
front. ADR-0002 already records the governing `SQLite single-writer` constraint;
**re-read it rather than reasoning on top of it.**

The issue poses the choice, and it must be decided, not assumed:

- **Option A** — let a judge call realized on a GET push the account past its cap
  retroactively. Means a GET mutates global spend-cap state, which today is only
  ever written at run creation (POST).
- **Option B** — a pre-flight check inside `_request_path_judge`: do not fire the
  judge at all for an account already at/over its daily cap. Never writes to the
  ledger from a read path.

The issue's own suggested first step favours B. **Verified 2026-08-15 that B's
seams exist:** `FeedbackStore.daily_spend_for(account_id, *, now=None)` at
`feedback_store.py:972`; `GLOBAL_DAILY_CEILING_USD` referenced at `costs.py:1083`
and `main.py:1003`; `_request_path_judge(query_run)` at
`query_run_orchestration.py:1968`. That function takes only the run, so how it
reaches the store is a real design question, not a detail.

**The issue's TITLE premise is partly false**, per its own later comments: on a
`measured` run the judge's dollar is already in the figure the ledger books. What
is actually open is the **memo-eviction / process-restart** path, where a second
paid judge call fires and `try_record_cost_reconciliation` refuses a second
correction (`feedback_store.py:1182-1183`). **Build the test around eviction, not
around the first dispatch.** `_JUDGE_VERDICT_MEMO_MAX` is 512.

Whatever you choose, **ADR in the same PR** (rule 16d).

## 1.3 — #226: vacuous e2e negative assertions, as TWO PRs

Branch `fix/226-vacuous-e2e-negative-assertions` is pushed and NOT merged. It hit
the two-round cap with five blocking findings, and the round-1 fix introduced one
of them. Read the escalation comment on the issue.

**The diagnosis: the work crept.** The issue is "give 13 assertions a positive
partner." The branch also rewrote the guard tool's classifier — and **every
blocking finding across both rounds came from the classifier changes, not the
spec fixes.** The worst: widening `isNonEmptyLiteral` to accept arrays made
`.not.toHaveText([...])` an accepted positive partner, and Playwright *passes*
that against a locator matching zero elements. On one synthetic file `main`
reports 4 violations and the branch reports 0 — strictly worse than not fixing it.

**PR 1 — spec partners only.** Low risk, already well evidenced. Accept the one
genuine guard false positive (`parity-behavior.spec.ts:524`, which already has
its partner on the line above) with a `// no-positive-partner:` note pointing at
PR 2. **Scope fence: this PR does not touch
`e2e/tools/check-negative-assertions.mjs`.**

**PR 2 — the guard classifier**, as its own concern, reviewed as the adversarial
surface it is. It needs a **property-style test that no empty-or-tautological
spelling is accepted in any argument shape** — not a case bolted on per
discovered evasion, which is exactly what kept failing.

Salvage from the existing branch; do not merge it as-is.

---

# PHASE 2 — free, non-code work that may close an issue outright

## 2.1 — #203: ask before you spend

**The four questions that settle #203 are free.** If the answer is "no proxy, no
WAF," the disambiguation problem is void, **#203 closes as not-a-problem, and the
capture is removed in the same PR** — at zero cost. Ask me:

1. Are `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` set as Fly secrets or machine env
   on `quorum-ai`? (`fly ssh console -a quorum-ai -C env | grep -i proxy` — free)
2. Does the Fly **organisation** apply any egress policy, WireGuard peering or
   private-networking rule routing outbound HTTPS anywhere other than Fly's
   default NAT?
3. Is there a Cloudflare Zero Trust / Gateway / WARP enrolment, or any other
   filtering layer, over this app's outbound traffic?
4. If yes to any: what does that layer return on a block — status, `content-type`,
   and does it strip or rewrite response headers?

Two live facts already kill the obvious signals, so do not re-derive them:
`server: cloudflare` and `cf-ray` do **NOT** discriminate, because OpenRouter is
itself behind Cloudflare. Its genuine 401 is `application/json`, ~50 bytes,
`Transfer-Encoding: chunked` with **no** `Content-Length`, and carries no
`error.metadata`.

## 2.2 — read what is already on the volume, for free

Both telemetry streams shipped in PR #289 (`ab4296c`). Read them before assuming
they are empty — it costs nothing:

```bash
fly ssh console -a quorum-ai -C "cat /data/telemetry-billing.jsonl" | wc -l
fly ssh console -a quorum-ai -C "cat /data/telemetry-tokens.jsonl"  | wc -l
```

Report the real counts. If a sample already exists, some of Phase 3 may be
answerable with no new spend at all.

---

# PHASE 3 — the paid session. STOP HERE AND WAIT FOR ME.

**Do not make a paid API call, provoke traffic, or trigger a paid run without my
explicit go-ahead in this chat.** This repo is hermetic/$0 by default (rule 17f).
Your standing authorization covers merging and deploying, not spending.

**What to bring me — one message, then stop:**

1. A **traffic plan**: how many runs, with what query shapes, `:online` on or off,
   over what window.
2. A **cost estimate produced by the free `/estimate` endpoint**, not arithmetic
   you did in your head. Show the command and its output.
3. A **spend ceiling** and what happens when it is hit.
4. **What each issue will and will not get** from that plan — honestly, per the
   next section.
5. The **exact read-back commands** you will run afterwards.

## What the paid session can and cannot settle — be honest about this

**#268 — CAN close.** Needs `n >= 50` `:online` calls. Traffic you generate *is*
the sample, so this one genuinely resolves. **Read its positive partner FIRST:**
for `search_enabled == false`, `injected_p95` must be **under 500**. If it is not,
`sent_tokens_est` is wrong, the whole measurement is void, and you fix the
estimator before reading anything else. This is also the only check on
`CHARS_PER_TOKEN = 4`, which is a repo constant, not a measurement of
OpenRouter's tokeniser. Report `injected_max` either way — the guardrail's
exposure is the tail, not the median.

**#290's probe — CAN run.** One call per slot model at the 2000-token cap,
measuring elapsed time against `openrouter_timeout_seconds = 8.0`, and checking
whether the cheapest model actually quotes passages as the prompt demands. This
unblocks the feature *decision*; it does not build the feature. **Bundle it into
the same paid window** — it is a handful of calls.

**#105 — LIKELY WILL NOT CLOSE. Say so up front.** It needs `n >= 30` **5xx**
records. **5xx cannot be manufactured**: they come from upstream router refusals
on OpenRouter's schedule, not yours. A paid session collects whatever 5xx happen
to occur, which will probably be far fewer than 30. Collect them opportunistically
and **leave the issue open** unless the threshold is genuinely met. Read per
status code, never "all 5xx". If `unknown/n > 0.20` → **STOP**: ADR-0012 records
the `error.metadata.provider_name` schema as ASSUMED, and a dominant `null`
refutes it.

**#203 — only if Phase 2 said a proxy exists.** One question: does more than one
distinct shape appear under status 403? One shape → no evidence of a second
answerer; keep the gap open honestly and delete the stream.

**Never move a guardrail constant on a guess.** #180 cost three broken attempts
to learn that. If a threshold is not met, the honest outcome is "not decidable
yet," not a number invented to close a ticket.

## The second thing the paid session buys you

A real run exercises the code just shipped: the #216 judge path end to end, the
scoped event recorders, the cost receipt. **Design the traffic plan to verify
those too**, not only to collect telemetry. State in the plan which shipped fix
each run leg confirms.

---

# Every sub-orchestrator's internal contract

**Point every agent at the source of truth.** The first instruction to every
builder and reviewer must be: *read this repo's `AGENTS.md` and `CLAUDE.md` IN
FULL and follow them exactly.* Do not paraphrase the rules into the prompt — a
paraphrase drifts from what you did not think to restate.

**Build:** one sole writer, `isolation: 'worktree'`, strict TDD. RED first;
capture the **verbatim** failure output; confirm it fails for the right reason
(not a collection or import error); GREEN; then bite-proof by `cp`-ing the file
aside, reverting the fix, confirming RED, and restoring from the copy with
`diff -q`. **Never `git checkout <file>` to revert** — it discards uncommitted
work. Every test ships one line saying what turns it red. Every negative check
gets a positive partner. Accounting code asserts **cardinality**, not just a
clean-path outcome.

**Push as soon as there is a green commit, before review starts.** A usage limit
killed two review fans in the previous session and both builders' work was
unpushed; it was recoverable from the object store, but only by luck.

**Review:** read-only, isolated worktrees, told **IN CAPITALS** not to edit,
`git checkout`, `git stash`, `git commit`, `git push` or `sed -i` the shared tree.
A reviewer that must mutate source gets its own copy
(`git archive HEAD | tar -x -C <dir>`). Six lenses: tester (does the test actually
bite?), correctness, devops/CI, performance, **security whose explicit job is to
break it**, and architecture/ADR-compliance.

Reviewers **refute by default** and report only findings backed by something they
actually executed, with the command and its verbatim output.

**Tell every reviewer to audit the diff's PROSE, verbatim** (rule 11a): *"for
every number, superlative and causal claim in the diff's comments, commit body,
ADR and PR description, name the command that produces it — or mark it
UNVERIFIED."* That one instruction caught false test counts, a corpus figure
measured against the wrong tree, an ADR guarantee the code did not deliver, and a
"strictly less exposure" claim execution flatly refuted.

**Fix loop:** verify each reviewer claim before acting; refute the wrong ones out
loud with the refuting command. Expect your own fix to introduce a defect. **Cap
at two rounds.** If still blocking after round 2, DO NOT merge: record the open
findings on the issue and move on. If two fixes in a row add defects, change the
approach rather than trying a third.

**Give each package a scope fence.** Name the files in scope and say that touching
a shared tool is a separate PR. #226 failed precisely here.

# Merge, deploy, close (the main orchestrator's job)

**Re-derive the required contexts, never trust a list:**

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
```

As of 2026-08-17 there are six: `validate-and-test`, `pytest (Python 3.12)`,
`Changed-lines coverage >= 95% (blocking)`, `Schemathesis API contract (blocking)`,
`FR traceability completeness (blocking)`, `e2e axe + parity (chromium)`. An
**advisory** job failing is not a merge blocker. A `toHaveScreenshot` failure on a
diff touching zero UI/CSS/template files is very likely flake — confirm the
changed-file list, then `gh run rerun --failed` once before treating it as real.

Squash-merge with an explicit subject and body (`gh pr merge --squash --subject
--body`); a bare `--squash` concatenates every intermediate commit body onto
`main`. **`Closes #N` in the squash body DOES auto-close the issue here** —
confirmed three times. Post the verification record as a separate comment after.

**Verify the deploy three ways** (rule 18), and beware the run-count trap:

> **A merge produces THREE deploy runs, not two.** Measured twice. The first two
> are `cancelled` by concurrency dedupe, which is normal. A wait-loop keyed on a
> run id captured earlier reads `cancelled` and wrongly reports a failed deploy.
> **Re-resolve the newest run by `createdAt` every time**, including after the
> watch returns.

1. the Deploy **job** ran `success` — read the JOB, not the run's rollup;
2. `curl -s https://quorum-ai.fly.dev/status` shows `build_sha` == the merge SHA;
3. the thing you built actually fires.

`gh run list --commit <SHA>` has returned `[]` here before; fallback is
`--branch main` plus a SHA-prefix match.

Then `gh issue close <n> --comment "..."` citing the merge SHA and the
verification, and **confirm with `gh issue list --state open`**. Finally
`git branch -f main origin/main`, delete the merged branch local and remote
(**verify `gh pr view <n> --json state` says `MERGED` first** — deleting a head
branch before merge auto-closes the PR), and remove the worktree.

# Pitfalls that actually bit, in this exact task

- **Never create a branch named `origin/main`.** Cleanup is
  `git branch -f main origin/main`. A branch with that literal name collides with
  the remote-tracking ref and makes every later `git worktree add` fail with
  "refname 'origin/main' is ambiguous."
- **Chain `cd` with `&&`, never `;`.** A failed `cd` let the next git command run
  in the main checkout instead of the intended worktree.
- **Do not use `status` as a shell variable** — read-only in zsh.
- **Do not track `.claude/settings.json`, do not narrow `.gitignore` to expose
  it.** Full autonomy does not extend to the permission surface itself.
- **Python 3.12 is required.** `uv sync --all-extras` picks 3.14.5 on this box and
  `make quality` then fails at ~54% coverage with everything passing. Use
  `uv sync --all-extras --python 3.12` and confirm `uv run python -V`.
- **e2e must run exactly as CI does** or ~95 phantom failures appear:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <spec> --project=chromium --workers=1 --retries=0
  ```
  If `/ui` returns 429, delete the gitignored `.data/feedback_events.sqlite3` — a
  stale reused server without the mint-cap override wedged a run for ~45 minutes.
- **The visual lane fails 8/8 on this Mac on clean `main` and that is not a
  regression.** Never `--update-snapshots`.
- **`e2e/tests/review/` is gitignored scratch.** A red `test_no_orphaned_e2e_specs`
  is a known local-only false failure — run `ls e2e/tests/review/` first.
- **Run `pytest` and `make diff-cover` serially**, and **commit before trusting
  diff-cover** — it measures the working tree too.
- **Background long CI waits.** Foreground polling loops burn the tool timeout.
- **`timeout` does not exist on this macOS box.** Use
  `perl -e 'alarm shift; exec @ARGV'`.

# Closing adversarial pass — do not skip

After Phase 1, run ONE more independent review round with fresh agents reading the
CURRENT state of `main` — no memory of what the builders believed — probing the
highest-risk surfaces you touched: anything security or secret-handling, anything
with recursive or cyclic data, anything with an exception-handling path. A prior
run found three more real bugs this way, including a live secret-leak channel that
survived two full rounds because nobody tried a cyclic input. **Verify each
finding with an independent skeptic trying to refute it** before you trust it,
then fix what survives through the same cycle.

# Report

- how many issues you closed vs left open, and why for each;
- a table of issue → PR → merge SHA → deploy-verified (yes/no);
- anything filed rather than fixed, with why;
- the Phase 3 plan, its cost estimate, and — after I approve and it runs — what
  each issue actually got from it, including what it did **not** settle;
- **any mistakes you made and how you recovered — do not round these up into a
  clean summary.** Tell me what actually went wrong, the way I would want to hear
  it from a human engineer.

Be concise and lead with the answer. Plain English, no invented shorthand.
