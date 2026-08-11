ultracode

Five issues shipped this session, all merged and deploy-verified: #126, #142,
#116, #141, #148 (stretch goal of 5 hit, floor was 3). Two pre-existing
issues closed with findings recorded (no code change): #63 (already
documented in a prior PR), #199 (unreachability confirmed by reading the
real precedence logic in `computeDemoModeBannerCopy`). Two follow-up issues
filed and deliberately NOT built this session: #222 (landing-page density,
#116 follow-on), #224 (doc-gate parenthetical-comma gap, #141 follow-on),
#226 (20 pre-existing e2e spec violations surfaced by #148's widened guard).

Final merged SHA this session: `303228262d7697793a268550a3b287d27f1a1584`.
Deploy JOB conclusion `success` confirmed on the newest run for that SHA (an
earlier same-SHA run was `cancelled` by concurrency dedupe — the 7TH
consecutive session hitting this, not a special case). Prod `build_sha`
verified matching on BOTH `quorum.stackclimb.com/status` and
`quorum-ai.fly.dev/status`. Local `main` fast-forwarded to `origin/main` at
this SHA. All 5 worktrees and branches (local + origin) removed. All review
`git archive` scratch copies removed.

Full detail for each issue — including both reviewers' findings, every
self-fix's mutation-proof evidence, and what was deliberately filed rather
than fixed — is in `ISSUE-126-RESULT.md`, `ISSUE-142-RESULT.md`,
`ISSUE-116-RESULT.md`, `ISSUE-141-RESULT.md`, `ISSUE-148-RESULT.md` at the
repo root (all untracked). Read the relevant one in full before touching
anything related to the session trail, the mutation gate's exit-code
mapping, the readiness banner, the doc-honesty gate, or the negative-
assertion guard.

Read AGENTS.md next — its operating rules bind, and rule 14's gate list must
be re-derived with `gh api` rather than trusted.

FIRST: re-measure this handoff's own premises yourself (git state, production
`build_sha`, issue states — INCLUDING checking whether any issue you plan to
touch has been auto-closed by a keyword-matching merge body, a CONFIRMED-
RECURRING failure mode across multiple sessions — and INCLUDING checking
whether #126/#142/#116/#141/#148/#63/#199 themselves, and the four new
follow-up issues #222/#224/#226, are in the state this handoff claims)
before touching anything. If any premise does not hold, STOP and tell me —
do not repair it silently.

═══════════════════════════════════════════════════════════════════════
STRUCTURAL CHANGE FROM PRIOR SESSIONS, STILL IN EFFECT: ship MULTIPLE
issues, sequentially, each through its own full build→review→merge cycle
before the next one starts. This section carries forward unchanged from the
prior handoff, refined by what actually worked/didn't this session.
═══════════════════════════════════════════════════════════════════════

## Target: minimum 3, stretch 5 — never a quota that overrides readiness

This session hit 5/5 (stretch). That does NOT mean 5 is now a floor for
every future session — it means this repo's backlog, at least at this
snapshot, had enough well-scoped, non-blocked candidates to sustain it. The
next session's own fresh shortlist may or may not. Do not treat "5" as a
new target to beat; treat "3" as the floor and "5" as a stretch worth
pushing for when genuinely available, same as before.

## Step 1 — build a FRESH top-5 shortlist, ranked, before writing any code

Pull the full open-issue list fresh (`gh issue list --state open --limit
100 --json number,title,createdAt,labels`) — do NOT inherit the shortlist
this paragraph could have handed you. This repo has a MEASURED, repeated
failure mode where a handoff chain recycles a narrow shortlist while the
real open-issue count grows underneath it. For context only (verify
freshness before trusting), issues investigated in real depth in recent
sessions and found blocked, stale, already fixed, or successfully shipped:
#180, #103, #105, #117, #127, #115 (shipped), #126 (shipped), #193, #120,
#142 (shipped), #182, #160, #123, #122, #63 (closed), #124, #134, #116
(shipped), #141 (shipped), #143, #145, #146, #148 (shipped), #162, #166,
#137, #138, #199 (closed), #167, #203, #209, #216, #222 (filed, #116
follow-on), #224 (filed, #141 follow-on), #226 (filed, #148 follow-on).

THIS session additionally freshly investigated and ranked #148 (negative-
assertion guard blind spots) as the 5th slot — a larger candidate (4 sub-
fixes in a ~300-line AST-walking Node tool) than the prior four, but still
concrete and bounded (the issue itself listed exact fixture shapes and a
suggested direction for each sub-fix). Worth noting for calibration: a
candidate with MULTIPLE named sub-fixes in ONE mechanism/file is still ONE
work package (rule 17g), even at 4 sub-fixes — the size test in the four-
test check is about the FINDING you're deciding whether to fold in or file
separately, not about how many named sub-parts the ORIGINAL shortlisted
issue itself has.

New candidates surfaced but NOT built this session, with fresh disposition:
- **#63**: CLOSED this session — a "practice" recommendation already fully
  documented and wired into a prior handoff (PR #64). Not a code defect.
- **#199**: CLOSED this session — re-verified the reachability finding from
  a prior session's investigation comment by reading
  `computeDemoModeBannerCopy` directly (`app.js:2320-2360`). Confirmed:
  `globalSpendCeilingReached` is checked FIRST and always wins when true;
  `readinessState` is session-static (only changes via page reload, which
  also resets the relevant tracking state). No reachable path for two
  DIFFERENT all-local causes inside one continuously-loaded session exists
  in the current code. If a future session finds a NEW route to a mid-
  session `readinessState` flip, reopen with that path named explicitly —
  do not re-open on the strength of the original issue text alone.
- **#222** (#116 follow-on): landing-page content exceeds a 664px mobile
  viewport even with the readiness banner given ZERO height (`#landing-
  estimate`/`#landing-run` sit at y≈830-990 regardless of banner height).
  Needs a real design decision about which page elements to compress on
  mobile — good AskUserQuestion candidate for the NEXT session if it makes
  the shortlist, since the decision itself (what to shrink/hide/reorder) is
  the actual blocker, not a measurement or research step.
- **#224** (#141 follow-on): doc-honesty gate misses a short parenthetical
  between a gate identifier and its status comma (`` (see #130), blocking
  ``). NOT a simple distance-based fix — checked against a real counter-
  example (`` "the `perf-gate` job, unrelated commentary, blocking since
  June" `` sits at almost the SAME short distance and must NOT be swallowed)
  and a naive fix breaks it. Needs either a small balanced-parenthetical
  parser or a different overall strategy (e.g. scan forward for the first
  status word within the full window, then separately check whether
  anything between the identifier and it looks like an unrelated clause).
  Real design work, not mechanical — do not attempt a quick fix without
  re-deriving why the naive approach fails, documented in the issue itself.
- **#226** (#148 follow-on): 20 pre-existing e2e spec violations across 8
  files (accessibility, CSP, degraded-banner, readiness-banner, rendering-
  invariants, trust-score-invariants, ui-parity, workspace), surfaced by
  #148's widened negative-assertion guard. Each needs its own positive-
  partner assertion or reasoned `// no-positive-partner:` exemption chosen
  with real knowledge of what that SPECIFIC test is supposed to prove —
  this is 8 unrelated concerns bundled by symptom, not by cause; if picked
  up, it should probably become 8 small PRs (or a handful of clustered
  ones, per rule 17g's own clustering test), not one. The full file:line
  list is in #226's body and `ISSUE-148-RESULT.md`.

Rank whatever you find by severity (money and correctness defects first)
over recency or convenience. Do not assume a title that "reads as
buildable" actually is without reading the issue's own text, its most
recent comments, and where relevant, the current code in full first.

Before finalizing the shortlist, check whether several open issues are
genuinely the SAME concern spread across multiple issue numbers — if so,
treat that cluster as ONE work package inside your shortlist. THIS session
found no new clubbing candidate among what it investigated (#126, #142,
#116, #141, #148 were each investigated and built alone, no nearby issue
close enough in mechanism). Calibration examples remain: #180-vs-#185,
#112-vs-#203, #128-vs-#206, #113/#104item2-vs-#104item1, #185-vs-#171,
#161-vs-#160, #165's own items 1/2/3, #165 item-2-vs-item-3,
#110-vs-#216-vs-#217, #216-vs-#217.

## Step 2 — work the shortlist sequentially, one full cycle per issue

Unchanged from the prior handoff: re-verify each issue's premise fresh
right before building it; build in its own dedicated git worktree, one
tree-writer per issue; fan out read-only review exactly as before (two
lenses, each on its OWN `git archive` copy, one executes and pastes output,
one is a breaker); PRE-MERGE CLEANUP → MERGE → confirm the PR's own CI is
green; do NOT deploy-verify after each individual merge, batch it at the
end (Step 4); immediately re-check whether merging issue N changed
anything material about issue N+1 before starting it.

**New this session, worth carrying forward explicitly:** when a shortlisted
branch is created from `origin/main` BEFORE an earlier issue in the SAME
session's sequence has merged, it will be stale by the time you're ready to
push it — merge `main` into it (rule 17d), re-run `make quality` +
`make diff-cover` on the merged tree BEFORE pushing, not after a failed
merge attempt tells you to. This happened for #142, #116, and #141 in this
session (each merged `main` in cleanly, no conflicts, since the issues
touched disjoint files) — expect it every time in a multi-issue session
past the first slot, it is not an exception.

## Step 3 — the AskUserQuestion escape valve

Unchanged. Not used this session — no shortlisted issue this session was
blocked on a decision a quick human answer could resolve; the blockers
found (#222, #224, #226) all failed the four-test check on size/design-
depth grounds instead, which routes to silent-defer-and-file, not to
asking. If a future session's shortlist DOES include something like #103
(nightly job needs a remediation-strategy choice) or the "suppress vs
reserve" half of #117, that is still the kind of case this valve exists
for — batch multiple such questions into one `AskUserQuestion` call if more
than one shortlisted issue needs it.

## Step 4 — batched close-out (done this session, template for the next)

Confirmed every PR's local gates + review findings were resolved per-issue
in Step 2 (all 5 had two-lens review with zero unresolved findings surviving
to merge — every finding was either self-fixed same-PR/same-mechanism, or
filed separately after failing the four-test check). Confirmed every merge
landed (`git log --oneline origin/main -10` showing all 5 SHAs in order).
DEPLOY: resolved the newest run for the LATEST merge SHA (one earlier run
for that SHA was `cancelled` by concurrency dedupe, confirmed routine now
across 7 sessions), polled that run's Deploy JOB conclusion specifically
(not the run's rollup), confirmed prod `build_sha` matches on both domains.
POST-MERGE CLEANUP: synced main (`git merge --ff-only origin/main` from the
primary checkout, NOT `git branch -f` — that fails when `main` is the
currently-checked-out branch of a non-worktree repo; use `merge --ff-only`
or `git pull` in that case), removed all 5 worktrees before deleting their
branches, deleted all 5 merged branches local + origin, removed all 10
git-archive review copies (2 per issue × 5 issues), left `git worktree
list` / `git branch -a` tidy (the two pre-existing stray branches
`feat/ui-pr5b-cost-guard-diff` and `worktree-wf_8fbedc6c-041-3` were seen
but untouched, per standing instruction — still there, still not this
session's business).

## The in-session-dissolution four-test check — now TEN same-PR self-fix
## calibration examples (up from five)

Unchanged mechanics: (1) concrete fix design exists? (2) needs a product/UX
decision? (3) large/high-risk relative to a single clean PR? (4) genuinely
different subsystem? Fail ANY → file it and defer. Pass ALL FOUR AND found
during review of a not-yet-merged PR, small, same file/mechanism → self-fix
in the same PR rather than a new issue or third review round.

Worked examples, in order, now TEN: #165's own round-2 finding, PR #214's
`test.describe.skip()` finding, PR #215's LRU-eviction documentation-only
finding, PR #218's `(kind, model_id)` collision finding, PR #219's DOM-write
cache bucket finding, **THIS session's PR #220 (#126) finding: a stale trail
entry could hijack an in-flight run** (logic change + new regression test,
same file/mechanism as the fix already being made), **PR #221 (#142)
finding #1: `type_check` mutants invisible in the summary line** (one-line
addition to a print statement already being touched, plus a test), **PR
#221 (#142) finding #2: exit code 2 "interrupted" mislabeled as
"suspicious"** (one dict entry plus a dedicated fail-closed branch, plus two
tests — found by a DIFFERENT reviewer than finding #1, on the same
already-open PR, showing a single PR can absorb more than one same-PR
self-fix across more than one review pass without needing a third round,
as long as each individual fix stays small), **PR #223 (#116) finding: the
height-regression test only covered one readiness state, plus a
mis-scoped test that checked the wrong DOM element** (a compound
self-fix — two related findings from the SAME review round, folded into
ONE commit since they were both test-file-only changes to the exact same
spec file), **PR #227 (#148) finding: `test.describe.parallel`/`.serial`
not recognized as describe calls**, reproducing the exact false-positive
class the PR itself exists to close, on a different modifier (small
generalization of a function the PR had already rewritten in this same
branch). Ten consecutive same-PR self-fixes now, spanning pure
documentation through logic-plus-new-test through small structural
generalizations — this remains the MORE common outcome for anything found
during review, not the exception.

**Calibration note from this session:** two of the ten (#221's pair) landed
on the SAME PR from TWO SEPARATE review passes (one from each of the two
parallel reviewers, not sequential rounds) — this is still "one round" in
the rule-12 sense (both reviewers ran once, in parallel, over the same
diff), not two rounds. Don't conflate "multiple reviewers found different
things in one pass" with "multiple sequential re-review rounds" — the cap
is on the latter.

## Documentation-only findings

Unchanged. None this session (all findings that surfaced were either code
defects self-fixed same-PR, or large-enough-to-file, not standing-doc
corrections).

## Pre-existing-issue premise-went-stale

Unchanged, two sub-flavors (worse, or wrongly-resolved). THIS session's
instances of the (b) sub-flavor (wrongly resolved / premise no longer
holds): #63 (already documented in PR #64, closed as already-actioned) and
#199 (premise unreachable in current code, closed with the finding
recorded). Neither needed a code fix — both were verified via direct code
reading before closing, not trusted from a prior comment alone.

## Known traps to brief every reviewer on, up front — updated

Carry forward the full list from the prior handoff (git-less review copy
phantom failures — now re-derive the file list fresh with `grep -rl
find_repo_root tests/` rather than trusting any hardcoded count, since it
has drifted before; the negative-assertions guard's own required blocking
CI check with no local `make` equivalent — note THIS session extended
that very guard, so its own test suite `tests/unit/
test_negative_assertion_guard.py` is now a 30-test file, up from ~12, worth
knowing if a future reviewer needs to understand its shape quickly;
`sys.executable` not `uv run python` in new subprocess-spawning tests; a
fresh worktree needing both `uv sync --all-extras` AND `npm install` in
`e2e/`; resolving the NEWEST run's own databaseId when polling a merged
SHA's deploy status, never "any completed run"; `make diff-cover`
measuring committed+working tree, commit before trusting it; the
non-keyword "Addresses #N" phrasing when a PR only partially closes an
issue OR when a finding surfaced mid-review could plausibly have been
scoped separately; zsh's `[ ]` needing `=` not `==`; a review agent needing
both `uv sync --all-extras` AND `npm install` in its OWN git-archive copy
before it can run anything real).

**New this session:**
(9) **`make format`'s line-length limit (100 chars) bites hardest on new
    test files with long f-string assertion messages** — three separate PRs
    this session (#142, #148) hit `format-check` failures from lines like
    `assert x, f"...long message...:\n{result.stdout}{result.stderr}"`
    exceeding 100 chars. `make format` (not just `format-check`) auto-fixes
    what `ruff format` can reformat on its own, but a genuinely-too-long
    single f-string still needs manual wrapping — either the whole
    `assert cond, (...)` onto multiple lines, or (when even the message
    alone is too long) splitting the f-string itself into a plain string
    concatenated with a shorter f-string continuation. Check for this
    BEFORE running `make quality` the first time on any new test file with
    long assertion messages, not after it fails.
(10) **`git branch -f main origin/main` fails when `main` is the currently
    checked-out branch of a non-worktree (the primary) checkout** — it
    only works from a DIFFERENT branch or a worktree. From the primary
    checkout with `main` checked out, use `git merge --ff-only origin/main`
    instead (or `git pull`) to fast-forward local `main` at session close.
    This is a real, reproducible command failure, not a style preference —
    hit exactly once this session during the batched close-out.
(11) **A wide, generalized fix to an AST-matching predicate function (e.g.
    widening a hardcoded modifier allowlist to a fully generic match) is
    itself worth a second look for correctness on adjacent, unlisted real
    API surface you didn't originally target** — #148's `isDescribeCall`
    fix started as "add `parallel`/`serial` to the allowlist" and was
    generalized to "match ANY `test.describe.X` chain" specifically because
    a fourth real modifier (`test.describe.configure`) exists and a
    hardcoded list would have missed it too. When generalizing a predicate
    like this, trace through what OTHER real API shapes your new, wider
    match now accepts (here: `test.describe.configure({...})`, which takes
    a config object not a callback) and confirm the wider match doesn't
    misbehave on those either — it didn't here (the function early-returns
    on any describe-call match regardless of whether a function-like
    argument follows, so a config-only call is a correct no-op), but this
    needs checking explicitly, not assumed.

## Session continuity

Before ending, write ONE RESULT document per issue this session ships
(done: `ISSUE-126-RESULT.md`, `ISSUE-142-RESULT.md`, `ISSUE-116-RESULT.md`,
`ISSUE-141-RESULT.md`, `ISSUE-148-RESULT.md`), each opening with a
"Behavior: before vs after" section in plain English, LIVE vs LATENT stated
explicitly. Then write ONE successor handoff prompt covering the whole
session (this document) — same structure every time: the top-3/stretch-5
target; the clubbable-issue-cluster check with its full calibration list;
the in-session-dissolution four-test check with its calibration list (now
ten;  update the count and add new examples every session that produces
any); the documentation-only-finding distinction; the pre-existing-issue
distinction with both stale-premise sub-cases; the four-step close-out
checklist, batched once at the end; and the full known-traps list, updated
with anything new (three new items this session, numbered 9-11 above,
appended to whatever count the next session inherits — re-derive the
numbering fresh rather than trusting it, same as the file-count in trap 1).
These are standing practices now, not one-time instructions, going on
several sessions of unbroken continuity.

When done, give a BULLET-POINTED SUMMARY (not prose) covering: for EACH
issue shipped, behavior before/after in plain English first (LIVE vs
LATENT, and for CI-tooling-only fixes, explicit that user-facing behavior
didn't change); task status with merged SHA(s) and Deploy JOB
conclusion(s); sync/branch state; whether each was PR-reviewed and why;
findings and resolution (including anything self-fixed mid-PR); for any
shortlisted issue you did NOT ship, whether it was silently deferred (and
why) or routed through AskUserQuestion (and what was decided); pending
items with issue states re-checked after merge; what you could not verify;
and the next action item with one line on why it outranks the
alternatives. Then stop.
