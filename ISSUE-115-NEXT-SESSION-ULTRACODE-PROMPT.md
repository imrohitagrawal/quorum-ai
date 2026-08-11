ultracode

Issue #115 is now CLOSED. PR #219 (merged squash-commit `36b96c9`) fixed
the issue's own core claim — the transcript view's disclosure banner
(`#demo-mode-banner`) was correctly kept up to date by JS but lived inside
CSS that hides it unconditionally on every view, so no user could ever see
it. Moved it into the transcript view's own markup (mirroring
`#result-degraded` on the result view) and restored a `toBeVisible()` gate.
A SECOND, adversarially-found defect (the DOM-write cache was keyed on a
coarse 3-value bucket, so a stale count from an earlier "mixed" run in the
same session could survive into a later, differently-mixed run once the
banner became visible) was found and fixed, mutation-proven, in a second
commit on the SAME unmerged PR before merge — not filed separately, not
given a third review round. Deploy job (not run rollup) confirmed
`success` on the newest run for the merge SHA (an earlier same-SHA run was
`cancelled` by concurrency dedupe — the 6TH consecutive session hitting
this trap); prod `build_sha` verified `36b96c96611bc562336db2b7862271645503da7f`
on BOTH `quorum.stackclimb.com/status` and `quorum-ai.fly.dev/status`.
Full detail, including both reviewers' findings and the mutation-proof
evidence for both fix commits, is in `ISSUE-115-RESULT.md` at the repo
root (untracked) — read it in full before touching anything related to
the transcript view's disclosure banner.

**#216 was NOT touched this session** (re-verified fresh: still OPEN,
still blocked on the same policy decision described in its own text — the
daily spend-cap ledger doesn't reflect a post-run judge cost, and the
fix requires choosing between two opposed, real cost/data-quality
tradeoffs a human has to pick, same class as pre-existing #122). It
remains open, untouched, exactly as filed.

Read AGENTS.md next — its operating rules bind, and rule 14's gate list
must be re-derived with `gh api` rather than trusted.

FIRST: re-measure this handoff's own premises yourself (git state,
production `build_sha`, issue states — INCLUDING checking whether any issue
you plan to touch has been auto-closed by a keyword-matching merge body,
which is a CONFIRMED-RECURRING failure mode across multiple sessions now,
not a one-off — and INCLUDING checking whether #115/#216 themselves are in
the state this handoff claims) before touching anything. If any premise
does not hold, STOP and tell me — do not repair it silently.

═══════════════════════════════════════════════════════════════════════
STRUCTURAL CHANGE THIS SESSION, PER EXPLICIT HUMAN INSTRUCTION: instead of
picking ONE work package and stopping, this session's job is to ship
MULTIPLE issues, sequentially, each through its own full build→review→
merge cycle before the next one starts. Read this whole section before
starting — it changes how you plan the session, not just how you execute
one PR.
═══════════════════════════════════════════════════════════════════════

## Target: minimum 3, stretch 5 — never a quota that overrides readiness

Ship **at least 3** issues this session (built, reviewed, merged, and
covered by the session's batched deploy verification at the end).
**Stretch goal: 5.** This is a floor to push hard for, not a license to
force a genuinely-blocked issue through to hit a number — AGENTS.md rule
19 ("close more than you open," stop and say so when something's bigger
than it looked) and this repo's own measured history (roughly half of
what a candidate list asserts does not survive contact with the tree, per
`docs/analysis/2026-07-30-backlog-triage-by-execution.md` and
`docs/metrics/defect-discovery-audit.md`) still apply in full. The
difference from prior sessions is HOW you handle a shortlisted issue that
turns out blocked: see the escape valve below, before you give up on it
and move to the next-ranked candidate.

## Step 1 — build a FRESH top-5 shortlist, ranked, before writing any code

Pull the full open-issue list fresh (`gh issue list --state open --limit
100 --json number,title,createdAt,labels`) — do NOT inherit the shortlist
this paragraph could have handed you. This repo has a MEASURED, repeated
failure mode where a handoff chain recycles a narrow shortlist while the
real open-issue count grows underneath it
(`handoff-chain-narrows-the-backlog` in memory; #106 sat unbuilt 4+ cycles
this way). For context only (verify freshness before trusting, per the
rule below), issues investigated in real depth in recent sessions and
found blocked, stale, or already fixed: #180, #103, #105, #117, #127,
#115 (built this session), #126, #193, #120, #142, #182, #160, #123,
#122, #63, #124, #134, #116, #141, #143, #145, #146, #148, #162, #166,
#137, #138, #199, #167, #203, #209, #216. THIS session additionally
freshly re-investigated #103, #193, #117, #123, #199 as candidates before
settling on #115 — their disposition (see `ISSUE-115-RESULT.md`'s
companion analysis, or re-derive fresh if the doc doesn't cover it in
enough depth) as of this session:
- **#103** (nightly feedback-audit job crash-fails 8+ consecutive days):
  concrete, well-diagnosed module-path bug, BUT the underlying "audits an
  empty/wrong DB" problem needs one of three remediation options chosen
  (SSH into the live prod machine from CI / export a periodic snapshot /
  drop the job) — a security/infra decision with real tradeoffs, not a
  routine engineering default. **Good candidate for the AskUserQuestion
  escape valve below** if you shortlist it.
- **#193** (source-support trust card shows a bare percentage): needs an
  OPERATOR-run visual-baseline reseed before merge per this repo's own
  standing rule (UI change inside the blocking `visual-snapshots.spec.ts`
  region) — not something a session can do unattended, and not something
  a clarifying question resolves either (it's a mechanical operator step,
  not a decision). Skip unless the human volunteers to run the reseed.
- **#117** (readiness banner flashes on `/ready` disagreement): has a real
  product tradeoff between two fix shapes (suppress first paint on every
  load vs. reserve banner space) that a PRIOR session already flagged as
  genuinely contested — but ALSO has a small, uncontroversial FIRST step
  (fire `refreshReadiness()` in parallel at the start of `boot()` instead
  of serially after two other round trips) that a prior session
  independently called "safe regardless of which way the bigger decision
  goes." That narrower step might be buildable without asking anything —
  investigate fresh; the bigger suppress-vs-reserve half is a genuine
  AskUserQuestion candidate.
- **#123** (feedback_store has no reconnect path): the issue's own text
  estimates ~130 src lines + ~300 test lines and lists five separate
  correctness constraints (ordering-dependent recovery, a 5.24s lock
  timeout, request-path cooldown, tests pinning `:memory:` degraded
  behavior, `run_history_store` symmetry) — likely too large for one slot
  in a multi-issue session. Re-assess fresh; if it still reads as
  hundreds-of-lines-plus-open-design, it fails the size test outright
  (this is a filed issue, not a fresh in-session finding, so it doesn't
  go through the four-test check — it just isn't a good candidate for a
  tightly time-boxed slot).
- **#199** (stale demo-mode-banner cause across two different all-local
  causes in one session): a PRIOR session's own investigation comment
  concluded it could find NO reachable path for this (both candidate
  causes turn out to either be dead code or require a page reload that
  resets the relevant state) — re-verify that reachability finding fresh
  before either building or dismissing it; if genuinely unreachable, this
  is a case for the third category (pre-existing issue whose premise
  turns out false) — consider whether it should be CLOSED with that
  finding recorded, not left open indefinitely as a phantom target.

Rank whatever you find by severity (money and correctness defects first,
per the defect-discovery-audit's finding that 0 of 16 real `src/` defects
were ever caught by a gate, 10 of 16 by adversarial review) over recency
or convenience. Do not assume a title that "reads as buildable" actually
is without reading the issue's own text, its most recent comments (issue
text can go STALE in EITHER direction — #103's most recent comment showed
a materially WORSE problem than its original body; #165 showed an issue
can go from "open with real leftovers" to "wrongly closed" through no
one's deliberate action — verify the issue's FULL comment/state history,
not just `gh issue view`'s current `state` field), and where relevant, the
current code in full first.

Before finalizing the shortlist, check whether several open issues are
genuinely the SAME concern spread across multiple issue numbers (same
function/file/narrow area, a direct follow-on, or trivial same-surface
copy/doc fixes) — if so, treat that cluster as ONE work package / ONE PR
inside your shortlist (it still only costs you one of your 3-5 slots).
Do NOT club issues just because each is individually small if they are
actually unrelated concerns — AGENTS.md rule 17 ("one CONCERN per pull
request") still binds; this only changes how you SELECT work packages.
Same file/function is necessary but not sufficient for clubbing — the root
cause AND the fix's readiness/maturity must actually be the same. TEN
calibration examples exist so far (see prior handoffs for the full list:
#180-vs-#185, #112-vs-#203, #128-vs-#206, #113/#104item2-vs-#104item1,
#185-vs-#171, #161-vs-#160, #165's own items 1/2/3, #165 item-2-vs-item-3,
#110-vs-#216-vs-#217, #216-vs-#217). THIS session found no new clubbing
candidate — #115 was investigated and built alone, with no nearby issue
close enough in mechanism to be a real clubbing question. State the
ranking and WHY it outranks the alternatives, in one line per shortlisted
issue, before starting (AGENTS.md rule 20) — you need this justification
for EACH of the 3-5 slots, not just the first.

## Step 2 — work the shortlist sequentially, one full cycle per issue

For issue N in your ranked shortlist:
1. Re-verify ITS premise fresh right before you start building it (not
   just at shortlist time) — state can go stale over the course of a
   multi-issue session just as easily as over a multi-session handoff
   chain. A few minutes' staleness check (current code, issue's latest
   comments) is cheap; discovering mid-build that the issue was already
   fixed, or its premise changed, is not.
2. Build serially in its OWN dedicated git worktree (one tree-writer —
   you — per AGENTS.md rule 17a). Do not start issue N+1's worktree until
   issue N is merged and its worktree/branch are cleaned up — AGENTS.md
   rule 17 ("one CONCERN per pull request, merged before the next
   starts") applies BETWEEN issues in this session exactly as it always
   has between sessions.
3. Fan out read-only review exactly as before: two lenses, each on its
   OWN `git archive HEAD` copy (never a shared working tree), one must
   EXECUTE and pasteoutput for every verdict, one is a breaker targeting
   the specific correctness/safety property the change exists for. Cap
   two rounds; if a round finds a real defect, fix it and self-verify
   with the same execute-and-mutate rigor rather than opening a third
   round (see the calibration list below — now FIVE examples, all
   resolved this way).
4. PRE-MERGE CLEANUP → MERGE (squash, explicit `--subject`/`--body`, CI
   green re-derived via `gh api`) → confirm the PR's own CI is green.
   **Do NOT do a full prod deploy-verification after each individual
   merge** — per this repo's own established batching preference, verify
   prod ONCE at the end of the session, covering every merge (see Step 3).
   "Success" for the purpose of moving to issue N+1 means: local gates
   green, review findings resolved, PR's CI green, merged, worktree/branch
   for issue N cleaned up.
5. Immediately re-check whether merging issue N changed anything material
   about issue N+1 on your shortlist (unblocked it, made it moot, revealed
   it's the same concern after all) before starting N+1.

## Step 3 — the AskUserQuestion escape valve (NEW this session, explicit
## human instruction — use it to protect the minimum-3 floor)

In every PRIOR session, when a shortlisted or investigated issue turned
out blocked on a product/policy decision, an operator-only step, or an
infra/security tradeoff, the standing instruction was: defer it, document
why, move to the next candidate, never decide it unilaterally. That
default is now REFINED, not replaced: **for an issue on your top-5
shortlist specifically**, if investigation shows it is blocked ONLY on a
decision a quick human answer could actually resolve — a genuine
either/or product call, a choice between named implementation options, an
explicit "yes, do the operator step" — **ask via `AskUserQuestion` with
concrete, named options before giving up on that slot**, rather than
silently deferring straight to the next-ranked candidate. The goal is to
protect your minimum-3 floor by unblocking a shortlisted issue in place
where a human answer can do that cheaply, not to ask permission for things
you're equipped to decide yourself.

This does NOT apply, and you should still silently defer + document +
move to the next candidate, when:
- The blocker is a genuine multi-day measurement or research step no
  single answer can shortcut (e.g. #105's "read a week of production
  logs" — no question resolves that faster).
- The blocker is a mechanical operator-only action with no real
  decision content (e.g. #193's visual-baseline reseed — there's nothing
  to ask, it's a "someone else has to run this" gap, not a fork in the
  road). You MAY mention in your final summary that a quick human
  volunteering to do the mechanical step would unblock it, without
  formally asking via the tool for something that isn't a decision.
- The issue is large/high-risk regardless of the answer (e.g. #123's
  ~430-line estimate) — a policy answer doesn't shrink the diff.
- You're not confident you've actually found ALL the real blockers yet —
  don't ask a premature question and then discover a second, unrelated
  blocker after the human already answered the first one. Finish
  investigating an issue fully before deciding whether it's a genuine
  "ask" case.

When you do ask: batch questions for MULTIPLE blocked shortlist issues
into as few `AskUserQuestion` calls as reasonably possible (the tool
supports up to 4 questions per call) rather than interrupting once per
issue serially, so the human isn't pulled in and out repeatedly.

## Step 4 — batched close-out (once, covering every merge this session)

Same four-step close-out as always, run ONCE at the end, covering every
PR merged this session: (1) confirm every PR's local gates + review
findings were already resolved per-issue in Step 2; (2) confirm every
merge landed (git log / `gh pr list --state merged`); (3) DEPLOY — resolve
the NEWEST run for the LATEST merge SHA (not the first one you see — a
first run getting `cancelled` by concurrency dedupe is now confirmed
routine across SIX consecutive sessions, this session included), poll
that specific run's Deploy JOB conclusion (not the run's overall
rollup), confirm prod `build_sha` matches on BOTH domains; (4) POST-MERGE
CLEANUP — sync main, remove each dedicated worktree BEFORE deleting its
branch, delete each merged branch local + origin (squash-merged needs
`-D` not `-d`), remove every git-archive review copy and mutation-backup
scratch directory, leave `git worktree list` / `git branch -a` tidy (do
not touch pre-existing stray branches/worktrees you did not create this
session — `feat/ui-pr5b-cost-guard-diff` and
`worktree-wf_8fbedc6c-041-3` have now been seen-but-untouched across many
sessions; leave them alone without asking unless the human raises it).

═══════════════════════════════════════════════════════════════════════
END OF STRUCTURAL CHANGE SECTION. Everything below is the same standing
practice as every prior handoff — read it in full, it still binds.
═══════════════════════════════════════════════════════════════════════

## The in-session-dissolution four-test check (unchanged, now FIVE
## same-PR self-fix calibration examples)

If YOUR OWN work (a review round, an investigation, the build itself)
surfaces a NEW issue, do not automatically file it and stop — that
produced a measured "close one, open one, net zero" pattern before this
practice existed (`docs/analysis/2026-08-01-in-session-issue-dissolution.md`).
Test it against four conditions: (1) does a concrete fix design already
exist, or does it need a measurement/research step first? (2) does it
need a product/UX decision you cannot make unilaterally? (3) is it
large/high-risk relative to a single clean PR (rough guide: hundreds of
lines, or its own open design questions)? (4) is it a genuinely different
subsystem, not just a deeper layer of the same one? Fail ANY of these →
file it and defer. Pass ALL FOUR → build it as its OWN separate PR this
same session — UNLESS it was found DURING review of a PR that has not yet
merged, is small (rough guide: under a few dozen lines), and is the SAME
mechanism/file already being changed — in that narrower case, self-fix
and self-verify inside the SAME PR with the same execute-and-mutate rigor
a review round would apply, rather than opening a new issue or a third
review round. Worked examples, in order: #165's own round-2 finding, PR
#214's `test.describe.skip()` finding, PR #215's LRU-eviction
documentation-only finding, PR #218's `(kind, model_id)` collision
finding (a genuine 13-line logic change plus a brand-new dedicated
regression test), and **THIS session's PR #219 finding: the DOM-write
cache keyed on a coarse bucket instead of the actual counts** — same
file (`app.js`), same mechanism (`renderModelPanels`'s caching), 13-line
source change plus one new regression test, found during review of the
still-unmerged PR. Five consecutive same-PR self-fixes now, spanning the
full spectrum from pure documentation through logic-plus-new-test — this
is the MORE common outcome, not the exception; only escalate past it if a
finding is genuinely large, cross-cutting, or needs a decision.

A finding surfaced while COMPARING candidate issues BEFORE picking one
(not during review of an in-flight PR) still goes through the four-test
check like any fresh discovery — it does NOT get the narrower same-PR
carve-out just because you happened to be doing selection work when you
found it. #216 (found this way in a prior session) is the calibration
example: it failed condition (2) at the selection stage, before any PR
existed to self-fix inside of.

## Documentation-only findings (unchanged)

A finding can be a correction to a standing operating note (AGENTS.md, a
handoff doc, this file) rather than a code defect — that needs neither a
PR nor the four-test check, just fold it directly into your RESULT doc
and the next handoff. THIS session's new instance:
`ISSUE-115-RESULT.md`'s "New trap" section — a DOM-position assertion
(`banner_pos < grid_pos`) can hold true by template-layout coincidence,
independent of the CSS visibility property it was meant to prove; only
caught by mutating the file and re-running the test, not by reading the
assertion. Generalizable, not specific to #115 — worth remembering the
NEXT time you touch a structural DOM-order test: mutate it to prove it
actually encodes the property, don't trust that a passing assertion means
the right thing was checked.

## Pre-existing-issue premise-went-stale (unchanged, two sub-flavors)

A PRE-EXISTING filed issue whose premise turns out already false OR
MATERIALLY WORSE by the time you check it has two confirmed sub-flavors:
(a) premise went stale by getting WORSE (#103: most recent comment showed
a crash-failing job, not the "quietly auditing an empty DB" the original
text claimed) — re-scope the fix, don't close the issue; (b) premise went
stale by getting WRONGLY RESOLVED (#129: a PR it named as blocked had
already merged; #165: the entire issue got auto-closed by a
keyword-matching merge body while 2 of 3 items were still genuinely
unfixed) — for (b), verify via the issue's FULL comment/state history
before either trusting a closed state or treating it as done. Not a
license to keep building indefinitely — if a "small" follow-up turns out
bigger once started, say so and stop (rule 19).

## Known traps to brief every reviewer on, up front

(1) A `.git`-less review copy shows phantom test failures in
repo-integrity meta-tests that shell out to `git` — at least EIGHT files
known (`test_makefile_gate_integrity.py`, `test_mutation_copy_completeness.py`,
`test_findings_ledger_consistency.py`, `test_repo_root_resolution.py`,
`tests/unit/test_context_carry.py`, `tests/unit/test_gate_liveness_floors.py`,
`tests/unit/test_mutation_test_set_integrity.py`) — re-derive fresh with
`grep -rl find_repo_root tests/` rather than trusting this count; verify
any full-suite failure a reviewer reports against your OWN real-worktree
gate run before trusting it's a phantom (rule 11: check the fix, not just
the finding).
(2) `e2e/tools/check-negative-assertions.mjs` (issue #131's guard) is a
required, blocking CI check with no local `make` equivalent — run it
directly from `e2e/` on any touched `.spec.ts` file before pushing.
(3) A subprocess spawned from a NEW test that imports anything
third-party must use `sys.executable`, not `uv run python`, or it can
break inside `test_mutation_copy_completeness.py`'s bare-copy gate; a
fresh worktree needs `uv sync --all-extras` before ANY `uv run` command
works, AND `npm install` inside `e2e/` before ANY `npx playwright`
command works — neither install carries over from the main checkout to a
new worktree, and this now applies to potentially SEVERAL worktrees in
one session, not just one.
(4) When polling a merged SHA's deploy status, resolve the NEWEST run's
own `databaseId` first and poll THAT run specifically to `completed` — a
loop that exits on "any completed run for this SHA" can exit early on a
run `cancelled` by concurrency dedupe while the real newest run is still
`in_progress`. Confirmed recurring across SIX consecutive sessions now
(THIS session: PR #219's merge produced a `cancelled` run and a separate,
later, real Deploy run for the same SHA) — treat it as the default
expectation for EVERY merge this multi-issue session produces, not an
occasional surprise. List every run for the SHA, sort by `createdAt`,
poll the newest one specifically, then check that run's Deploy JOB
conclusion via `gh run view <id> --json jobs` — not the run's rollup.
(5) `make diff-cover` measures the COMMITTED tree plus the working tree
(rule 15a) — commit before trusting it, and re-run `make quality`
immediately before `make diff-cover` too, since `make api-contract` and
the other pytest-invoking targets rewrite the same shared coverage data.
When a PR touches NO Python under `src/`, `make diff-cover` correctly
reports "no Python under src/ changed — nothing to measure, and that is
honest" rather than a false pass or fail — confirmed again this session
on PR #219 (JS/HTML/tests only).
(6) Before merging with a "Closes #N" keyword, check whether #N has
MULTIPLE named sub-items and only SOME are done by this PR — if so, do
NOT use a close-keyword (write "Addresses #N, see issue for remaining
items" instead), then close the issue MANUALLY afterward with an
explicit comment. THIS session used "Addresses #115" even though #115
turned out fully resolved — err toward the non-keyword phrasing whenever
a finding surfaces MID-REVIEW that could plausibly have been scoped
separately, then close manually once you're certain nothing remains.
(7) zsh's POSIX `[ ]` test builtin does NOT accept `==` (only bash's
`[[ ]]` does) — `[ "$x" == "y" ]` fails with a cryptic `= not found`
error in a background/Monitor script. Use `[ "$x" = "y" ]` (single `=`)
in any `[ ]` test inside a script you background, or use `[[ ]]`
throughout. Also: the `Monitor` tool's poll-loop pattern has
intermittently exited with code 1 for reasons not yet root-caused
(observed twice in one earlier session) — if a `Monitor` call for a
CI/deploy poll-loop fails, fall back to `Bash` with `run_in_background:
true` and a simple `until` loop (this session used exactly that pattern
successfully for both the PR-checks poll and the post-merge deploy poll,
with no Monitor failures — the `until [ "$x" = "y" ]; do sleep N; done`
shape with single-`=` comparisons is the proven-working pattern).
(8) When a review agent needs BOTH the Python server and the Playwright
e2e harness to actually execute tests (not just read code), its prompt
must explicitly tell it to run `uv sync --all-extras` in the repo root
AND `npm install` inside `e2e/` in its OWN `git archive` copy before
attempting to run anything — a review copy has neither by default, same
as a fresh worktree per trap (3).

## Session continuity

Before ending, write ONE RESULT document per issue this session ships (or
one document per issue if their dispositions differ — see
`ISSUE-110-RESULT.md`'s "Deliberately out of scope" section and
`ISSUE-115-RESULT.md`'s "Second finding" section as worked templates),
each opening with a "Behavior: before vs after" section in plain English.
Then write ONE successor handoff prompt covering the whole session (not
one per issue), carrying forward this same structure: the top-3/stretch-5
target with the AskUserQuestion escape valve refined by whatever you
learn about where it actually helped or didn't this time; the clubbable-
issue-cluster check with its full calibration list; the in-session-
dissolution four-test check with its calibration list (now however many
same-PR self-fixes you accumulate this session, or unchanged at five if
none occur); the documentation-only-finding distinction; the
pre-existing-issue distinction with both stale-premise sub-cases; the
four-step close-out checklist, batched once at the end; and the full
known-traps list, updated with anything new. These are standing
practices now, not one-time instructions.

When done, give a BULLET-POINTED SUMMARY (not prose) covering: for EACH
issue shipped, behavior before/after in plain English first (LIVE vs
LATENT, and for CI-tooling-only fixes, explicit that user-facing behavior
didn't change); task status with merged SHA(s) and Deploy JOB
conclusion(s); sync/branch state; whether each was PR-reviewed and why;
findings and resolution (including anything self-fixed mid-PR); for any
shortlisted issue you did NOT ship, whether it was silently deferred (and
why) or routed through AskUserQuestion (and what was decided); pending
items with issue states re-checked after merge; what you could not
verify; and the next action item with one line on why it outranks the
alternatives. Then stop.
