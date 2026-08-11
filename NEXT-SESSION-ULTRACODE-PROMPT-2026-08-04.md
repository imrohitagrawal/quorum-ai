# Next session — ULTRACODE mode (supersedes `NEXT-SESSION-ULTRACODE-PROMPT.md`, 30 Jul)

**Paste this whole file as the opening prompt.**

`main` is `52f72da`, deployed and verified in production. The major-issues batch
(#240) and the regression it caused (#244) are both merged. Nothing is broken.

Your job, in order: one operator hand-off, one framing question, then **derive**
the work package rather than inherit it.

---

## 1. FIRST ACTION — hand #193 back to the operator

Before any analysis, print the block below and ask the operator to act on it.
PR **#236** is complete and blocked on exactly one thing only they can do.

### Where the images are

Committed baselines live beside the spec that uses them:

```
e2e/tests/invariants/visual-snapshots.spec.ts-snapshots/
    result-verdict-chromium-linux.png     <- the one this PR moves
    result-verdict-chromium-darwin.png
    transcript-full-chromium-linux.png
    transcript-full-chromium-darwin.png
```

CI compares only the `-linux.png` files. They cannot be regenerated on a Mac —
they are produced inside the CI container by the **`Seed visual baselines`**
workflow (`.github/workflows/seed-visual-baselines.yml`, `workflow_dispatch`),
which checks out the dispatched branch, runs Playwright with
`--update-snapshots`, and commits the new `*-linux.png` back to that branch.

**Operator steps:** dispatch that workflow on branch
`fix/193-source-support-denominator` → it pushes a commit containing the updated
PNG → review the image diff in PR #236's "Files changed" → merge.

### What the behaviour was BEFORE

The result view's trust panel showed a tile with the kicker **"Source support"**
and a bare percentage — for example just `75%`.

### What the behaviour is AFTER

The same tile reads `75% (3 of 4 answers)`. The number itself is unchanged; only
the denominator is added. Nothing is recomputed — `answer_count` and
`sourced_answer_count` already exist on `CitationCoverage`; the card now prints
what it was already using.

Why it matters: a bare `75%` reads as authoritative without saying 75% *of
what*, and the panel is four answers, so "3 of 4" and "18 of 25" are very
different claims wearing the same number. That is #171's own rule applied to the
card that was breaking it.

### What the operator should verify in the PNG

- The **"Source support"** tile now reads `NN% (X of Y answers)`, and `Y`
  matches the number of answer slots visible in the panel.
- `X ≤ Y`, and the percentage is consistent with `X/Y`.
- The added text has **not** wrapped awkwardly, been clipped, or pushed any
  neighbouring tile out of alignment.
- **Nothing else in the screenshot changed.** This is a text-only change; any
  other visual delta means something unintended moved.
- The six `trust-score-*.png` baselines are **not** in the diff. The card renders
  into `#result-trust`, not the `#result-trust-score` element those snapshot —
  re-confirm that from the diff rather than trusting this sentence.

---

## 2. SECOND — put #222 in front of the operator, framed

Do not start work on #222. Present it, get a decision, move on.

**What it is.** PR **#238**. Two real improvements are done and verified:
the landing CTAs were **100% occluded** by the fixed session-trail panel (a real
click hit the trail and did nothing) — now 0% — and page density went 830 → 660.

**What is not done.** The issue's actual goal, "content fits a 664px mobile
fold", holds *only* at 390×664 with default text. It fails at 375×667, 360×640,
320×568, 390×600, at an 18px user font, and with the font CDN blocked.

**Why it is not a formality.** That fold assertion sits in a **blocking** CI lane
with **4px** of slack and a dependency on `fonts.googleapis.com`. A CDN outage
would red a merge gate for reasons unrelated to any diff.

**So the decision is mostly about the TEST, not the page.** Three options:
1. Merge as-is and demote the fold assertion out of the blocking lane, filing
   the fold goal as its own design item. *(Recommended: it banks two verified
   wins now and removes a third-party dependency from a merge gate.)*
2. Merge as-is and keep the fold assertion blocking. *(Accepts CDN-driven flake
   in a required check.)*
3. Hold the whole PR for a landing redesign. *(Leaves a 100%-occluded CTA in
   production in the meantime — the worst of the three.)*

If the operator wants a drill-down, scope it: **measure the viewport matrix and
return a recommendation about the gate.** It is not an open design exploration.

---

## 3. THIRD — derive the work package. Do not inherit one.

**Analyse every open issue before proposing anything.** Not the shortlist below,
not the last handoff's list — all of them:

```bash
gh issue list --state open --limit 200
gh pr list --state open
```

The measured failure mode here is that handoff documents recycle a narrow
shortlist while the real backlog grows; a money leak sat unbuilt for four cycles
because of it. §5 of this file is a **prior to be re-derived, not a plan to
execute.** If your analysis disagrees with it, your analysis wins — say so
explicitly and show the reasoning.

For each open issue, establish four things, briefly:
- **Impact if unfixed** — who is affected, how often, and is it live in
  production or latent? (Check, do not assume: production currently runs with
  live execution ON, so anything described as "affects offline deployments" is
  latent there.)
- **Size** — is this one work package or three?
- **Dependency** — does another issue have to land first, or does this one
  unblock others?
- **Same-surface siblings** — which other open issues touch the same function,
  file or narrow area?

Then **pick the single highest-impact item and club its dependents into one work
package** where they are genuinely the same concern (AGENTS.md rule 17g). Club
because they are the same concern, never merely because each is small — rule 17
(one CONCERN per PR) still binds.

Present the ranking and the proposed cluster, with the one-line justification
rule 20 requires — why this outranks the top of the backlog — and get agreement
before building.

---

## 4. The one failure mode to avoid

The last session shipped **seven** first implementations that were wrong. Every
one was caught by *executing* something; none by reading. Three patterns:

- **Code behaviour was verified; prose about code was not.** Comments, issue
  bodies and PR descriptions asserted things the code did not do — including two
  shipped comments that stated the opposite of their own function, and a PR
  description that described a policy the branch had already reversed.
- **Boolean terms were added where a state table was needed.** Three consecutive
  fixes to one ~40-line predicate each introduced a new defect, because each
  added a condition instead of tabulating the state space. The fix that held came
  from writing the table out (`tests/unit/test_spend_cap_state_table.py`).
- **Review ran only in pull-request context.** A gate that fails *by
  construction* on `main` passed two review rounds, because in a PR the diff is
  never empty. It reddened `main` on merge and blocked the deploy. **Any change
  whose behaviour depends on the diff, the base ref, or `github.event_name` must
  be exercised once with `HEAD == origin/main` before it ships.**

So: write the input-class table before fixing a decision function; treat every
sentence — including in this file — as UNVERIFIED until executed; and budget a
review round for your own fix introducing a defect (rule 12).

---

## 5. Candidate work — INPUT TO §3, NOT A PLAN

Listed with what is known, so §3's analysis starts from facts rather than from
scratch. Re-rank freely.

**#242 — `.claude/settings.json` and cross-session memory.** Operator's stated
priority. The only enforcement that fires *while* an agent works is the hook
config, and it is `.gitignore`d onto one laptop. Already inspected: 10
`permissions.allow` entries, 4 hooks (blocks `--no-verify`; runs
`make validate + pytest` pre-commit; a green-run marker; a Stop-hook claim gate
behind `QUORUM_STOP_HOOK=1`). **Secret scan clean.** Two blockers:
`permissions.allow[3]` hardcodes `/Users/rohitagrawal/Documents/Projects/...`,
which is machine-specific *and* already the wrong path; and
`settings.local.json` must stay ignored. If tracked,
`tests/unit/test_claim_gate_hooks.py` stops skipping — verify it actually
executes. Needs an ADR stating the honest limit: a hook config is enforcement
for one agent runtime, not CI.

**#245 — the deploy signal lies quietly.** `E2E (axe + parity)` never triggers
the Deploy workflow though `deploy.yml` lists it (measured on two commits; cause
UNVERIFIED — find it, do not guess). And a red `main` yields a **skipped**
Deploy, not a red one, because the gate's `if:` needs
`workflow_run.conclusion == 'success'` — so the stranding check cannot run
exactly when stranding happens. Blocks nothing; means a failed deploy shows no
red anywhere. This is why rule 18 says verify `/status.build_sha`.

**#226 — 20 pre-existing specs are vacuous** under the widened
negative-assertion guard. Now evidenced, not theorised: the same guard blocked
#240 with 6 findings in *new* specs, all real. One test's entire body sat inside
`if (await hasDriftWarning())` with nothing creating the drift, so it had
reported green while executing nothing since it was written. Mutation proof to
copy is in Addendum 2 of the batch record: same mutation, original body **passes**
in 3.7s, fixed body **fails** in 12.1s.

**Simulated-consensus defect — not yet filed.** Four models that were never
invoked read as "strong consensus, 4 of 4 aligned": `_local_simulation_text`
returns text identical across slots but for the model id, measured pair Jaccard
**0.541** against a 0.1 threshold. **Latent in production** (live execution is
ON there) but real for any deployment without a funded key and for any fallback
to simulation. Same class as #180 but strictly more reachable — and note #180's
premise was *refuted* by execution (`grep -c "decision support" providers.py`
→ 0) and PR #239 was dropped after four attempts. Start here, not from #239.
Enumerate input classes first: identical simulated text; near-identical live
answers; genuinely aligned live answers; genuinely divergent answers.

**#122 follow-through.** The 402 renders "Over the hard cap — this run won't
start" and a `$0.25` note for a **storage** fault. Needs a discriminator field on
`CostEstimate`, an OpenAPI change, UI branching and e2e. Why #122 stayed open.

**#162 / #166.** Six gate-liveness fixes landed against issue text naming nine
and seven gates. Not re-derived. Count, then close honestly or state what
remains.

**Two small ones found late in #240.** `_playwright_invocations`
(`tests/unit/test_e2e_flake_policy.py:67`) scrapes `e2e.yml` as raw text, so a
*comment* mentioning the Playwright command reds the `--retries=0` guard — hit
for real, worked around by rewording, which is brittle. And **11 mutants still
survive in `costs._log_daily_cap_bypassed`**; the advisory gate went 79.5% →
84.9% and now passes, but 11 of the original 15 survivors were never examined,
and ADR-0004 makes that ERROR the only signal that the spend cap stopped
metering. "Above threshold" is not "covered".

---

## 6. Standing traps — measured; each costs about an hour if rediscovered

- **e2e must run exactly as CI does**, or ~95 phantom failures appear:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <spec> --project=chromium --workers=1 --retries=0
  ```
- **`/ui` returns 429** once repeated local e2e runs poison the durable per-IP
  daily session-mint cap. Presents as ~12 unrelated spec failures and a webServer
  timeout. Fix: `rm -f .data/feedback_events.sqlite3` (gitignored).
- **`make quality` and `make validate` do not cover the merge gates.** Six
  contexts are required; re-derive rather than trusting any table:
  ```bash
  gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
  ```
  `make diff-cover DIFF_BASE=origin/main` and `make api-contract` are the two
  most often forgotten. The negative-assertion guard runs **only on a pull
  request**, so run it by hand before pushing any e2e change:
  ```bash
  cd e2e && node tools/check-negative-assertions.mjs --base origin/main
  ```
- **`make diff-cover` measures the working tree too — commit first** (rule 15a),
  or it attributes untouched pre-existing lines to your diff. Re-run
  `make quality` immediately before it; the pytest-invoking targets rewrite the
  coverage data underneath it.
- **Mutation proof uses `cp` aside and restore from the copy. Never
  `git checkout <file>`** — it discards uncommitted work. Confirm with `diff -q`.
- **A RED gate is not evidence it measured.** #240's e2e job showed 8 test
  failures and a "0 executed" floor; the real cause was a setup step three steps
  earlier, and all three red signals pointed away from it.
- **Squash-merge with explicit `--subject` and `--body`** (rule 17c). A bare
  `--squash` concatenates every commit body onto `main`. And `not fixed: #N` in a
  merge body still **closes** #N — GitHub ignores the negation.
- **A merge produces two runs; one is `cancelled` by concurrency dedupe.**
  Resolve the newest by `createdAt`, then read its Deploy **job**.
- **Deleting a branch that other PRs use as their BASE auto-closes them.**
  Re-target first. Three PRs nearly went that way on 2026-08-03.

---

## 7. Definition of done

1. Local gates green, including the ones `make quality` does not run.
2. A test that would fail without the change, **proved by mutation**, with the
   verbatim failure output captured (rules 6, 6a).
3. Adversarial review by independent subagents — **two lenses, not five**
   (rule 10), read-only, told IN CAPITALS not to write, each given its own copy
   if it must mutate anything (rule 12b). Cap at two rounds.
4. An **ADR** if the change makes a decision anyone could reasonably reverse
   (rule 16d).
5. Merged **and** verified in production: the deploy **job** ran (not
   `skipped`/`cancelled`), `/status.build_sha` equals the merged SHA, and the
   thing you built actually fires — check the served asset, not just the SHA.
   Probe only where it costs nothing: `/ready`, `/status`, `/metrics`,
   `/ui/ops`, `/estimate`. Then `git branch -f main origin/main`, delete the
   branch local + remote, remove the worktree (rule 18a).

**Close more than you open** (rule 19). **Ask before** pushing, opening a PR,
merging, deploying, or any paid API call (rules 17b, 17f). Commit locally freely.

---

## 8. Housekeeping — one line in your first reply

**Stale local branches.** Eight per-issue branches from the batch remain locally
(`fix/103-…`, `fix/124-…`, `fix/127-…`, `fix/162-166-…`, `fix/182-…`, plus
`feat/ui-pr5b-cost-guard-diff` and a `worktree-wf_…` branch). Their work is on
`main`, but it arrived by **squash**, so git does not consider them merged and
`git branch --merged` will not list them. Left in place deliberately. If you
clear them, verify containment per branch — and `fix/180-…`, `fix/193-…` and
`fix/222-…` back OPEN pull requests (#239, #236, #238) and must be kept.

**Untracked result documents.** ~40 `ISSUE-*-RESULT.md` files sit untracked at
the repo root, so the project's record of what was learned lives on one laptop.
The batch record was deliberately moved into `docs/analysis/` for that reason.
If told to delete any, run `git ls-files <path>` first — and note rule 16c: an
untracked file that was ever `git add`ed survives as a dangling blob and is
recoverable via `git fsck --lost-found`. Check the object store before declaring
loss.

---

## 9. Ground truth — read before touching anything

1. `AGENTS.md` — rules 6, 7, 11, 12, 14, 15a, 17c, 17g, 18a, and 11a / 16d / 16e.
2. `docs/analysis/2026-08-03-major-issues-batch-result.md` — what shipped, and
   every claim the last session made that proved false. Addendum 2 is the most
   useful part.
3. `docs/adr/0004`–`0007` — the four decisions, with measurements and rejected
   alternatives.
4. `docs/analysis/03-enforcement-machinery.md` — the gate register, each gate now
   carrying why it exists, what it cannot see, and **when to remove it**. Read a
   gate's charter before fighting it.
5. `docs/metrics/defect-discovery-audit.md` — **0 of 16** real `src/` defects
   caught by an automated check; 10 of 16 by adversarial review. Weigh any
   proposal to add a gate against this.
