ultracode

Issue #217 is now CLOSED. PR #218 (merged squash-commit `c4730748`) fixed the
issue's own core claim — the result receipt's "Cost by model"/"Cost by
stage" columns now render an actual-only row (est side "—", never a
fabricated number) whenever the actual breakdown has a row the pre-run
estimate never had, instead of silently dropping it while the displayed
Total still included its dollar amount. A SECOND, adversarially-found
defect (a `model_id`-only key colliding between a debate-slot row and a
judge row, since the operator-set judge model id has nothing preventing it
from reusing a slot's model id) was fixed and mutation-proven in a second
commit on the SAME unmerged PR before merge — not filed separately, not
given a third review round. Deploy job (not run rollup) confirmed `success`
on the newest run for the merge SHA (an earlier same-SHA run was
`cancelled` by concurrency dedupe — the 5th consecutive session hitting
this trap); prod `build_sha` verified `c4730748d82f05c5a6c7236a6606139e48d3ea50`
on BOTH `quorum.stackclimb.com/status` and `quorum-ai.fly.dev/status`. Full
detail, including both reviewers' findings and the mutation-proof evidence
for both fix commits, is in `ISSUE-217-RESULT.md` at the repo root
(untracked) — read it in full before touching anything related to the
result receipt or the judge cost breakdown.

**#216 was deliberately NOT built this session.** It's #110's other named
follow-up (the daily spend-cap ledger not reflecting a post-run judge
cost). Re-derived from scratch this session (not inherited from a prior
handoff's characterization): #216 is genuinely the SAME CLASS of problem
as issue #122 ("Decide the spend-cap policy when the ledger is known
stale"), which prior sessions already found blocked on an operator/product
policy decision, not a code readiness gap. #216's own issue text names two
real, opposed options (allow a judge call to retroactively push a run's
account past its daily cap vs. gate the judge from firing at all when the
account is already at/over cap) with genuinely different cost/data-quality
tradeoffs — this is a decision, not an engineering default I should pick
unilaterally and ship silently, especially for spend-cap-enforcement
semantics in a repo that treats money defects as the highest-severity
category. It remains open, untouched, exactly as filed.

Read AGENTS.md next — its operating rules bind, and rule 14's gate list
must be re-derived with `gh api` rather than trusted.

FIRST: re-measure this handoff's own premises yourself (git state,
production `build_sha`, issue states — INCLUDING checking whether any issue
you plan to touch has been auto-closed by a keyword-matching merge body,
which is a CONFIRMED-RECURRING failure mode across multiple sessions now,
not a one-off — and INCLUDING checking whether #217/#216 themselves are in
the state this handoff claims) before touching anything. If any premise
does not hold, STOP and tell me — do not repair it silently.

THEN pick the next work package YOURSELF, from scratch:

  gh issue list --state open --limit 100 --json number,title,createdAt,labels

Do not inherit the shortlist named in this handoff's "What to do next"
section — that list is already stale by construction, and this repo has a
MEASURED, repeated failure mode where a handoff chain recycles a narrow
shortlist while the real open-issue count grows underneath it. Weigh
severity — money and correctness defects first, per
docs/metrics/defect-discovery-audit.md's finding that 0 of 16 real src/
defects were ever caught by a gate, 10 of 16 by adversarial review — over
recency or convenience. Note: recent sessions investigated several
higher-severity-looking issues (#180, #103, #105, #117, #127, #115, #126,
#193, #120, #142, #182, #160, #123, #122, #63, #124, #134, #116, #141,
#143, #145, #146, #148, #162, #166, #137, #138, #199, #167, #203, #209,
#216) in real depth and found each one either genuinely blocked on a
measurement step, a product/design decision, an operator step, scope
larger than one session, an explicit trigger condition that hasn't fired,
or already fixed/stale. #217 (a real correctness/trust defect with a
concrete, already-sketched fix design in its own text) WAS built this
session, unlike the others above. **This session did NOT re-investigate
the full "already investigated" list in fresh depth itself** — it trusted
the prior handoff's characterization for everything except #216, #217,
#209, and #122 (each checked fresh this session). If it has been several
sessions since one of the others in that list was last actually
re-examined (not just re-cited), treat its "still blocked" status as
worth a fresh look rather than assumed. Do not assume a title that "reads
as buildable" actually is without reading the issue's own text, its most
recent comments (issue text can go STALE in EITHER direction — #103's most
recent comment showed a materially WORSE problem than its original body;
#165 showed an issue can go from "open with real leftovers" to "wrongly
closed" through no one's deliberate action — verify the issue's FULL
comment/state history, not just `gh issue view`'s current `state` field),
and where relevant, the current code in full first.

Before settling on ONE issue, check whether several open issues are
genuinely the SAME concern spread across multiple issue numbers (same
function/file/narrow area, a direct follow-on, or trivial same-surface
copy/doc fixes) — if so, treat that cluster as ONE work package / ONE PR.
Do NOT club issues just because each is individually small if they are
actually unrelated concerns — AGENTS.md rule 17 ("one CONCERN per pull
request") still binds; this only changes how you SELECT the work package.
Same file/function is necessary but not sufficient for clubbing — the root
cause AND the fix's readiness/maturity must actually be the same. TEN
calibration examples now exist (nine from the prior handoff, plus this
session's #216-vs-#217):
#180-vs-#185: same function, different mechanisms; #112-vs-#203: same
ISSUE bundled both, different fix maturity, split anyway; #128-vs-#206: a
finding surfaced DURING review, not from a stale issue list, still failed
the same test — same field/file, different fix LAYER; #113/#104item2-vs-
#104item1: same ISSUE NUMBER, different file/mechanism, split across two
PRs anyway — the issue number is not the unit of clubbing; #185-vs-#171:
mirrors an existing precedent's FIX SHAPE but is a wholly separate, later
concern; #161-vs-#160: part of the same wider finding is still not enough
on its own when fix mechanism and size/readiness differ; #165's own items
1-vs-2-vs-3: SAME issue number, SAME filing session, SAME review cap, SAME
broad lineage — and STILL three different files/mechanisms with different
readiness; #165 item-2-vs-item-3 investigated together in ONE session still
ended up with two entirely different DISPOSITIONS; #110-vs-#216-vs-#217:
the ORIGINAL issue's own recon comment named BOTH follow-up consequences
explicitly, yet the fix design document still split them into three
separate issues/PRs because the receipt-honesty fix, the pre-run-ledger
fix, and the frontend-rendering fix are three genuinely different
subsystems with three different risk profiles and testing bars. **NEW this
session: #216-vs-#217 — both explicitly named as siblings ("#110 follow-up"
in both titles), same filing session, same parent issue, yet split again
at BUILD time: #217 had a concrete, ready fix design in its own text and
no policy question; #216 explicitly posed an open policy question in its
own text ("Decide the semantics before building") and turned out to be the
SAME CLASS of blocker as an unrelated pre-existing issue (#122) once
compared side-by-side. Two issues can be named as a matched pair by their
own filer and still have completely different build-readiness the moment
you actually try to build them — filed-together is not built-together.**
Even when an issue's own text bundles multiple consequences, OR a
second/third issue is discovered mid-review rather than pre-existing, OR
two issues are explicitly filed as a named pair, split them if fix
readiness/layer/urgency differs. State the ranking (or the cluster and why
each member belongs) and WHY it outranks the alternatives, in one line,
before starting (AGENTS.md rule 20).

SEPARATELY from clubbing: if YOUR OWN work this session (a review round, an
investigation, the build itself) surfaces a NEW issue, do not automatically
file it and stop — that produced a measured "close one, open one, net zero"
pattern before this practice existed
(docs/analysis/2026-08-01-in-session-issue-dissolution.md). Instead, test it
against these four conditions: (1) does a concrete fix design already exist,
or does it need a measurement/research step first? (2) does it need a
product/UX decision you cannot make unilaterally? (3) is it large or
high-risk relative to a single clean PR (rough estimate in the hundreds of
lines, or its own open design questions)? (4) is it a genuinely different
subsystem or mechanism, not just a deeper layer of the same one? If it fails
ANY of these four, file it and defer, same as before. If it passes ALL FOUR,
build it in this same session as its OWN separate PR (one-concern-per-PR
still binds — this never means bundling it into your current PR) — UNLESS it
was found DURING review of a PR that has not yet merged, is small (rough
guide: under a few dozen lines), and is the SAME mechanism/file already being
changed — in that narrower case, the right move is to self-fix and
self-verify it inside the SAME PR before merge, with the same
execute-and-mutate rigor a review round would apply, rather than opening
either a new issue or a third review round. Worked examples of this
narrower case, in order: #165's own round-2 finding (prior session), PR
#214's `test.describe.skip()` finding, PR #215's LRU-eviction
documentation-only finding (proved the carve-out covers a pure explanatory
fix with no logic change), and THIS session's PR #218 `(kind, model_id)`
collision finding — a fresh data point that the carve-out ALSO covers the
opposite end of the spectrum: a genuine LOGIC change (13 lines) plus a
BRAND-NEW dedicated regression test (not just a broadened assertion in the
existing one), not merely a doc/comment fix. Both ends of that spectrum
qualify for the same-PR self-fix carve-out as long as the finding stays
same-file/same-mechanism and stays small in absolute size. By contrast,
THIS session's earlier #216 finding (discovered while comparing it against
#217 during work-package selection, not during PR review) did NOT qualify
for the narrower carve-out at all — it never got to code, because it failed
condition (2) of the four-test check (needs a product/policy decision) at
the SELECTION stage, before a PR ever existed to self-fix inside of. That's
a useful contrast: the narrower carve-out only applies to findings surfaced
DURING review of your own in-flight PR; a finding surfaced while comparing
candidate issues BEFORE you pick one still goes through the four-test
check (or, if it's a pre-existing filed issue rather than a fresh
discovery, is simply left as-is, per the third category below).

Note: a finding can also be documentation-only (a correction to a standing
operating note, not a code defect) — that doesn't need a PR or the
four-test check at all, just fold it directly into your result doc and the
next handoff. THIS session had no new instance of this category (no
correction to AGENTS.md, a handoff doc, or similar was needed) — carrying
the distinction forward unchanged. The prior session's LRU-eviction example
remains the sharpest illustration of the DIFFERENCE between this category
and the "self-fix inside the PR" category: the distinction is WHERE the
documentation lives (a shipped source-code docstring/comment, which DOES
ship in a PR diff and counts as a same-PR self-fix, vs. this repo's own
standing operating notes like AGENTS.md or a handoff doc, which is the
true "documentation-only finding" category), not whether it changes
runtime behavior.

There's also a THIRD small category, distinct from both: a PRE-EXISTING
filed issue whose premise turns out to already be false OR MATERIALLY WORSE
by the time you check it — this has TWO confirmed sub-flavors: (a) a premise
that went stale by getting WORSE (#103: the issue's own most recent comment
showed a crash-failing job, not the "quietly auditing an empty DB" its
original text claimed) — re-scope the fix, don't close the issue; (b) a
premise that went stale by getting WRONGLY RESOLVED (#129 in an earlier
session: a PR it named as blocked had already merged; #165 in a later
session: the entire issue got auto-closed by a keyword-matching merge body
while 2 of 3 items were still genuinely unfixed) — for (b), verify via the
issue's FULL comment/state history (not just `gh issue view`'s current
`state` field, which will look identically "closed" whether it was closed
correctly or by accident) before either trusting a closed state or treating
it as done. This is not a license to keep building indefinitely — if a
"small" follow-up turns out bigger once started, say so and stop (AGENTS.md
rule 19, "close more than you open").

Build serially in a dedicated git worktree, one tree-writer (you). Fan out
read-only subagents for review only, each with its OWN copy via `git
archive HEAD | tar -x -C <dir>`, never a shared working tree. Two lenses (one
must EXECUTE and paste real command output for every verdict; one is a
breaker trying to defeat the specific safety/correctness property the
change exists for), cap two rounds, second round scoped to the fix diff
only. If a round finds a real defect, fix it and self-verify with the same
execute-and-mutate rigor (paste real command output, mutate-and-restore via
`cp`, never `git checkout`) rather than opening a third agent round — this
is now the MORE common outcome across recent sessions (#165's original PR,
PR #214, PR #215, and THIS session's PR #218 all hit it), not the
exception. If neither lens requires a code change, one round is enough —
don't manufacture a second round for its own sake (#161's session is the
calibration example for that branch; a prior session is the calibration
example for the OTHER branch — one round found real things, self-fixed
inline, still didn't need a second round; THIS session is a further
calibration point for the same "one round is enough when the fix is
self-verified" pattern). Known traps to brief reviewers on up front: (1) a
`.git`-less review copy shows phantom test failures in repo-integrity
meta-tests that shell out to `git` — the known list is at least EIGHT
files: `test_makefile_gate_integrity.py`, `test_mutation_copy_completeness.py`,
`test_findings_ledger_consistency.py`, `test_repo_root_resolution.py`,
`tests/unit/test_context_carry.py`, `tests/unit/test_gate_liveness_floors.py`,
`tests/unit/test_mutation_test_set_integrity.py` — re-derive the full list
fresh with `grep -rl find_repo_root tests/` plus the direct-`git`-subprocess
files rather than trusting this count as final — verify any full-suite
failure a reviewer reports against your OWN real-worktree gate run before
trusting it's a phantom, per rule 11: check the fix, not just the finding;
(2) `e2e/tools/check-negative-assertions.mjs` (issue #131's guard) is a
required, blocking CI check with no local `make` equivalent — run it
directly from `e2e/` on any touched `.spec.ts` file before pushing; (3) a
subprocess spawned from a NEW test that imports anything third-party must
use `sys.executable`, not `uv run python`, or it can break inside
`test_mutation_copy_completeness.py`'s bare-copy gate (no `.venv`/lock file
there); a fresh worktree also needs `uv sync --all-extras` before ANY `uv
run` command will work at all, AND (fresh trap from THIS session, npm-side)
`npm install` inside `e2e/` before ANY `npx playwright` command works —
neither install carries over from the main checkout to a new worktree.
(4) When polling a merged SHA's deploy status, resolve the NEWEST run's own
`databaseId` first and poll THAT run specifically to `completed` — a loop
that exits on "any completed run for this SHA" can exit early on a run
that was `cancelled` by concurrency dedupe while the real newest run is
still `in_progress`. This has now been hit in at least FIVE consecutive
sessions (confirmed again THIS session: PR #218's merge produced a
`cancelled` run and a separate, later, real Deploy run for the same SHA) —
treat it as the default expectation for every single merge, not an
occasional surprise; always list every run for the SHA, sort by
`createdAt`, and poll the newest one specifically, THEN check that specific
run's Deploy JOB conclusion (not the run's overall rollup) via `gh run view
<id> --json jobs`. (5) `make diff-cover` measures the COMMITTED tree plus
the working tree (rule 15a) — commit before trusting it, and re-run `make
quality` immediately before `make diff-cover` too, since `make api-contract`
and the other pytest-invoking targets rewrite the same shared coverage
data. When a PR touches NO Python under `src/`, `make diff-cover` correctly
reports "no Python under src/ changed — nothing to measure, and that is
honest" rather than a false pass or a false fail — confirmed this session
on a pure-frontend (`app.js` + `.spec.ts`) PR. (6) before merging with a
"Closes #N" keyword in a PR body, check whether #N has MULTIPLE named
sub-items/consequences and only SOME are done by this PR — if so, do NOT
use a close-keyword at all (write "Addresses #N, see issue for remaining
items" instead, as a prior session did for #110 and THIS session did for
#217 even though #217 turned out to be fully resolved by the PR — err
toward the non-keyword phrasing whenever a finding surfaces MID-REVIEW that
could plausibly have been scoped as a separate follow-up, then close the
issue MANUALLY afterward with an explicit comment stating what's fixed),
because GitHub's parser closes the WHOLE issue on the keyword regardless of
any qualifying text you add next to it. Only use a close-keyword directly
in the merge body when you are CERTAIN before merge that the PR finishes
every open item/consequence named on the issue AND no review round is
still pending that could change that. (7) NEW this session: a
shell-portability trap — this environment's default shell is zsh, and
zsh's POSIX `[ ]` test builtin does NOT accept `==` (only bash's `[[ ]]`
does) — `[ "$x" == "y" ]` fails with a cryptic `= not found` error in a
background/Monitor script. Use `[ "$x" = "y" ]` (single `=`) in any `[ ]`
test inside a script you background or hand to Monitor, or use `[[ ]]`
throughout. Also NEW: the `Monitor` tool's poll-loop pattern intermittently
exits with code 1 for reasons not yet root-caused (happened twice this
session, unrelated to the zsh bug above, which was in a SEPARATE plain
`Bash run_in_background` attempt) — if a `Monitor` call for a CI/deploy
poll-loop fails, fall back to `Bash` with `run_in_background: true` and a
simple `until` loop rather than retrying `Monitor` repeatedly.

Close out with all FOUR steps, every time, in order, for EACH PR this
session produces (including any dissolved-in-session follow-up from the
paragraph above) — do not skip or reorder: (1) PRE-MERGE CLEANUP —
gates/lint/mypy green, review findings resolved; (2) MERGE — squash with
explicit --subject/--body once required CI is green (re-derived via `gh
api`, never assumed) — and per trap (6) above, check whether the issue
being closed has other unfixed items before using a close-keyword; (3)
DEPLOY — batched if this session merges more than one PR: verify the
Deploy JOB (not run rollup) ONCE at the end, on the NEWEST run for the
LATEST merge SHA (a first run getting cancelled by concurrency dedupe is
routine — resolve the run's own id and poll it specifically, per trap (4)
above), confirming prod `build_sha` matches on BOTH domains — if only one
PR merges this session, check after that one merge as before; (4)
POST-MERGE CLEANUP — sync main (`git fetch origin` first if a stale local
view says "already up to date" incorrectly, then `git merge --ff-only
origin/main`; `git branch -f` will refuse whenever main is checked out in
your active worktree, this is normal, not an error to work around), remove
each dedicated worktree BEFORE deleting its branch (`git worktree remove`
first, or branch deletion fails with "used by worktree"), delete each
merged branch (local + origin — a squash-merged branch needs `git branch
-D`, not `-d`), remove any git-archive review-copy directories AND any
mutation-backup scratch directories, leave `git worktree list` / `git
branch -a` tidy. Note: there may be pre-existing stray branches/worktrees
in the repo that were NOT created by your session (e.g.
`feat/ui-pr5b-cost-guard-diff`, `worktree-wf_8fbedc6c-041-3`, seen but not
touched across multiple sessions now, including this one) — do not delete
anything you did not create this session without checking with the human
first; the close-out checklist covers YOUR OWN worktrees and branches, not
a general repo tidy-up. Also: verify any pre-existing candidate issue's
premise (including its FULL comment history, not just its original body,
AND its current open/closed STATE — a closed state can itself be the stale
premise) before ranking it.

When done, give me a BULLET-POINTED SUMMARY (not prose) covering: for EACH
issue fixed, the BEHAVIOR BEFORE and AFTER in plain English first (what a
user, the system, or — for CI-tooling fixes — the merge GATE ITSELF actually
did wrong, and what it does correctly now; say plainly whether the defect
was ever LIVE, LATENT/a coverage gap, or reachable-in-principle-but-never-
hit-in-the-real-pipeline; for a test-only or CI-tooling-only fix, be
explicit that the application's behavior for a real user didn't change and
what changed is the gate's own honesty/confidence instead), then task status
with merged SHA(s) and Deploy JOB conclusion(s) for EVERY PR this session
produced, sync/branch state, whether each was PR-reviewed and why, findings
and resolution status (including anything self-fixed mid-PR per the
narrower-than-a-new-PR case above), pending items with issue states
re-checked after merge (INCLUDING whether any issue you touched got
auto-closed by a keyword you didn't intend to fully close it with), what you
could not verify, and the next action item with one line on why it outranks
the alternatives.

Then write a RESULT document PER ISSUE (or, when one issue has multiple
items/consequences with genuinely different dispositions, one document
covering all of them, clearly sectioned, per `ISSUE-110-RESULT.md`'s own
"Deliberately out of scope" section and THIS session's `ISSUE-217-RESULT.md`
as worked templates) and a successor handoff prompt at the repo root, all
untracked. Every RESULT document opens with a "Behavior: before vs after"
section in plain English before the technical description. The successor
handoff's OWN paste-block must carry forward all SIX of these practices
(the clubbable-issue-cluster check including all calibration examples so
far — now TEN; the in-session-dissolution four-test check including all
calibrations — now with the full-spectrum self-fix carve-out example
(doc-only through logic+test) and the "found while comparing candidates
before picking one, not during PR review" counter-example; the
documentation-only-finding distinction; the pre-existing-issue distinction
with both stale-premise sub-cases; the narrower "self-fix inside the same
unmerged PR" case, now proven to cover BOTH a pure documentation fix AND a
genuine logic-change-plus-new-test fix; the four-step close-out checklist
with the batched-deploy-verification refinement and the newest-run-not-
any-completed-run polling trap now confirmed recurring across FIVE
sessions; "apply + self-verify a review round's findings rather than
opening a third agent round" including both calibration branches; PLUS the
two new environment-portability traps from this session: zsh's `[ ]` not
accepting `==`, and Monitor's poll-loop occasionally failing where a plain
`Bash run_in_background` until-loop succeeds) in full, worded for its own
situation — not dropped, not left as a one-off. These are standing
practices now, not one-time instructions for this session only. Then stop.
