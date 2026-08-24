# ADR-0068: Session residue is eight named categories, each with one verb

## Status

Accepted — 2026-08-25

## Context

`scripts/session_hygiene.py` reports what a working session left behind. It
shipped with two of the eight kinds of residue built, a wrong number for a
third, and no entry point at all — nothing in the repository ran it.

The eight kinds are a specification handed down for this work package. They
restate a standing cleanup rule that is **not checked into this repository**:
scratch and proof files, downloaded artifacts, build output, containers and
images the work built, one-off dependencies, and merged branches and worktrees,
with reusable caches deliberately kept. Two more come from this repository's own
history — poisoned local state, and the split between build output and the
files a human captured on purpose. Searching the tree for the specification
found only the handoff that carried it, so it is recorded here as a decision,
not as a recovered artifact.

Three things had to be settled before any of it could be built.

**One: the branch count was wrong, and the two obvious fixes are also wrong.**
The old code used `git branch --merged main`. This repository squash-merges
every pull request, and a squash leaves the branch's commits as ancestors of
nothing.

**Two: this tool deletes files.** Six new kinds of residue meant six new ways to
destroy work that has no git history to recover from. The failure modes were
enumerated before any of it was written, per the rule that says to do that for
safety-critical code.

**Three: two of the eight kinds live outside the repository** — session
scratchpads and reviewer copies — and one of them is not a filesystem path at
all.

## Decision

**Every kind of residue is a named category carrying its own verb.** `DELETE`
means the category may remove a named path. `REPORT` means it may only name what
it found and print the command a human should run. Five of the eight are
`REPORT`. The strongest verb a category may use is declared next to it, and the
acting path re-checks it rather than trusting the finder.

The gate restates the whole table independently, which stops a category being
UNLISTED. **It does not, on its own, stop one being UNBUILT** — measured: a
reviewer replaced category 2's finder with `return []` and every test stayed
green. So each of the eight also carries a behavioural test that plants its own
residue and asserts the category finds it. The table and those tests are two
different guards against two different failures, and saying the table did both
was wrong.

**Merged branches are detected with `git merge-tree --write-tree`, on fully
qualified refs, against the published trunk.** Three states are reported, not
two: merged, unmerged, and cannot-tell. Cannot-tell is never collapsed into
either neighbour.

**Branches, worktrees, scratchpads, reviewer copies, containers, images and
dependencies are all REPORT-only.** The tool never deletes outside its own root,
never deletes a branch, never deletes a container or an image, and never
uninstalls anything.

**`make session-clean` REPORTS.** It runs the script with no acting flag. The
name says clean and the target does not, which is deliberate: the two jobs have
opposite verbs, and a target that guessed which one you meant is the exact
conflation that destroys an untracked handoff. The acting flags stay explicit,
separate, and typed out by a human.

## Measurements (2026-08-25, macOS/darwin 25.5.0, git 2.54.0)

### The branch count, and why the obvious fixes fail

Throwaway repository, a two-commit branch squashed onto `main`, `main` then
moved on by one unrelated commit:

| check | printed | correct? |
|---|---|---|
| `git branch --merged main` | `main` only | no — the branch is missing |
| `git merge-base --is-ancestor` | no | no |
| `git diff --quiet main feature` | trees differ | no |
| `git cherry main feature` | `+` for BOTH commits | no — a squash of more than one commit preserves no patch-id |
| `git merge-tree --write-tree main feature` | `3527f87b…` = `main^{tree}` | **yes** |

Against a genuinely unmerged branch the same command printed `20ce1368…`, which
is not `main^{tree}`. Both directions demonstrated.

### The exit code is overloaded; the output shape is not

| exit | stdout | meaning | verdict |
|---|---|---|---|
| 0 | an object id | clean merge | compare with the trunk's tree |
| 1 | an object id | real conflicts | not merged |
| 1 | empty | a ref that could not be merged | cannot tell |
| 128 | empty | unrelated histories, or a git older than 2.38 | cannot tell |
| 129 | empty | unknown option | cannot tell |

Measured on this box: a conflicting merge exits 1 and still prints a tree hash;
`--no-such-option` exits 129. So the verdict keys on whether the first line is
an object id, never on the exit code alone.

### Three ways to get a FALSE "merged" — the dangerous direction

1. **A tag sharing the branch's name.** With `git tag feature main` in place,
   `git merge-tree --write-tree main feature` printed `main`'s own tree and
   exited 0, with only `warning: refname 'feature' is ambiguous` on stderr —
   because a bare name resolves `refs/tags/` before `refs/heads/`. Fully
   qualifying both sides gives the correct "not merged".
2. **A custom merge driver.** A committed `*.txt merge=ours` plus a
   `merge.ours.driver` config made a branch holding work found nowhere on the
   trunk report exit 0 and the trunk's own tree, with no warning at all.
   Neither half is present here today — there is no `.gitattributes` file and
   no `merge.*` config — but a driver can arrive from a user's global config,
   so it is checked and every verdict is downgraded to cannot-tell when it is.
3. **A branch with no commits of its own.** Every available check calls it
   merged, correctly, and deleting it still loses a work package's ref. Running
   the old code from this package's own worktree printed
   `merged branches : 1 -> pkg1-session-hygiene` — the live branch. Branches
   with no unique commits are now skipped, and a branch a worktree holds is
   flagged as checked out, with that worktree named. It is not hidden: that it
   is merged is still worth knowing, and `git branch -D` refuses it anyway.

### The old-git guard is a self-test, not a version comparison

`git merge-tree --write-tree HEAD HEAD` must equal `git rev-parse HEAD^{tree}`.
Measured: passes on git 2.54.0 and on Apple git 2.50.1; on git 2.32.7, which
predates the option, it exits 128 with `unknown rev --write-tree` and an empty
stdout — indistinguishable per-branch from unrelated histories, which is why the
test runs once up front. It writes no new object, because that tree is already
in the store.

### What the guards on the deleting path are for

| guard | the failure it prevents |
|---|---|
| category verb re-checked when acting | a REPORT category emitting a delete |
| path must resolve inside the root | the previous code took the path apart AFTER deleting it, so an escape would have destroyed the directory and then crashed without naming it |
| refuse a symlink | the session scratchpads on this machine hold symlinks pointing at real transcripts and at virtual environments inside the repository. The exact count is deliberately not written down: it moved from 125 to 129 while this package was being built |
| refuse anything git tracks | this script's own author destroyed 38 tracked files with one recursive remove |
| refuse a directory holding a `.git` | a reviewer copy taken per the review rule is a real checkout |

### Every path is literal

The ignore file ignores all of `build/`, which also holds the gate output the
Makefile gate-integrity test writes and reads; and all of the local data
directory, which holds a run-history database that is not residue. So no list
here is derived from ignore rules, and none of them is a glob.

### What adversarial review then broke, and the guards that answer it

A reviewer whose job was to destroy something the tool must not touch found
eight paths. Two would have destroyed real files on the first acting run, and
both were reproduced independently before the fix:

| finding | reproduction | answer |
|---|---|---|
| the tracked-content guard failed OPEN | with `GIT_INDEX_FILE` naming a file that does not exist, `git ls-files -- htmlcov` exits **0** with EMPTY stdout while the work-tree floor still says true — so even an exit-code check passes it through and the tracked file is deleted | `index_unreadable` proves git can list something before any empty answer is trusted, and refuses every deletion when it cannot. It is the ONE place that handles "git could not answer" |
| the browser-log directory was in the delete list | `grep -rIl playwright-mcp` over the tree matches ONLY the ignore file. No spec, workflow or Makefile target writes it; it is filled when a human drives the browser by hand, and re-running the suite does not recreate it. The working checkout holds 15 such files from June | moved to the reported list, beside the other hand-made captures |
| the checkout guard looked only at the top level | a repository at `mutants/reviewer-copy` — exactly where a mutation harness and a reviewer both work — was destroyed by the recursive remove on `mutants`, and the tracked guard could not see it either, because a nested repository is untracked in the outer one | the search runs at any depth, and a walk that cannot complete refuses |
| one unremovable path aborted the run | a directory the user lacks permission on raised out of the loop: the tree half cleaned, later categories unexamined, and the summary naming what had gone never printed | every delete is caught, counted, and summarised |
| a category that could not measure printed silence | with no trunk ref resolvable, the branch category printed "(none present)" while the same report's git-state line said there were two worktrees | worktrees are listed first, and an unresolvable trunk is reported as cannot-tell |
| the worktree list was split on whitespace | a worktree at `/tmp/t12 wt` was reported as `/tmp/t12` — a different, existing directory — inside a `git worktree remove` instruction | the porcelain form, which puts the path on its own line |
| a docker that could not answer read as clean | the command-line tool is on the path even when the daemon is down, so an ignored exit code prints "I could not look" as "nothing there" | the exit code is checked and reported |

### The tests bite

Thirty-six mutations were applied one at a time, each with the file copied aside
first and restored from the copy afterwards; the tree was byte-identical after
every restore. Thirty-five went red. They are named here so the claim is
reproducible rather than asserted.

Round one, on the eight categories and the branch fix: revert the merge-tree
check to `merge-base --is-ancestor`; flip category 5's verb; delete category 6;
point every category at one finder; drop the symlink guard; drop the
tracked-content guard; drop the checkout guard; use bare refs instead of
qualified ones; widen the image allowlist to a substring match; drop the
zero-unique-commit filter; make the Makefile target pass an acting flag; remove
the target from `.PHONY`; make the scratchpad finder return nothing; give the
scratchpad category a delete verb; move the hand-made captures into the delete
list; take the regenerable outputs out of it; empty the reviewer-scratch list;
drop the stray-checkout scan; degrade manifest drift to "the manifest exists";
remove the manifest check.

Round two, on the first review's fixes: remove the index probe; make the index
probe refuse everything; return the checkout search to the top level only; put
the hand-made browser output back in the delete list; put the worktree listing
back behind the trunk lookup; return the worktree parse to splitting on
whitespace; stop catching the delete; ignore the docker exit code.

Round three, on what a second reviewer proved was untested: delete the
containment check; stub category 2's finder; widen the poisoned-state path to
the whole data directory; add a real `docker system prune -af`; restore the
message that blamed a conflict; drop the checked-out warning; collapse the two
refusal conditions back into one sentence.

**The twenty-ninth did not go red, and that is recorded rather than quietly
dropped.** A per-path exit-code branch on the tracked-content check survived
its mutation, because `index_unreadable` refuses the run before that line is
ever reached. An untestable branch is the vacuity this repository's own rules
warn about, so the branch was removed and the comment in its place says why.
The behaviour it defended is covered by the probe, which does go red.

Suite: 11 tests before, 45 after, all passing.

## Rejected alternatives

**`git cherry` for merge detection.** Correct for a one-commit branch; measured
wrong for the two-commit squash that is this repository's normal shape, marking
both commits unmerged. It is also wrong in the dangerous direction after a
revert, where patch-id calls a branch merged whose content is no longer anywhere
on the trunk.

**`git diff --quiet main <branch>`.** Correct until the trunk moves forward by
one unrelated commit, after which it reports a fully merged branch as differing.

**`gh pr list` to ask whether the pull request merged.** Needs the network and
authentication, and answers a different question — whether a pull request was
merged, not whether the content is on the trunk. `merge-tree` is offline, free,
and works on any host.

**Comparing against local `main`.** Measured: with local `main` one commit
behind the remote, the same branch reports unmerged against `refs/heads/main`
and merged against `refs/remotes/origin/main`. Merged, for a cleanup tool, means
on the published trunk — and this repository's own close-out rule records that
local `main` does not follow the remote after a merge, so it is routinely
behind. The trunk actually used is printed in the report.

**Deleting the session scratchpad, defaulting to the harness's session-id
variable.** The variable does reach a subprocess — the brief assumed it does not,
and that premise is false. It is also INHERITED: measured on this machine, a
subagent process carries a marker saying so alongside its parent's id, so a
child reading it would name its parent's LIVE scratchpad. Four sibling session
directories exist here, and mtime does not distinguish abandoned from active.
Deleting outside the repository root is the highest-risk thing this tool could
do and it saves one typed command, so the containment invariant wins and the
category reports.

**Identifying reviewer copies by shape.** A copy taken per the review rule
carries a real `.git` and is indistinguishable from a genuine checkout. Any
sweep matching `*copy*`, `*-probe` or "a directory with a `.git`" eventually
matches a user's own clone. Named paths only, plus a top-level scan that reports
checkouts git does not know as worktrees.

**Pruning containers and images.** `docker system prune -af` destroys every
other project's images on the machine, and a `dangling` filter can take the
layer cache backing an unrelated in-progress build. Even a substring match on
the product name claims a lookalike. An exact allowlist, reported and never
removed: an image is cheap to rebuild, but a running container may be the
developer's live application. On a clean development box `docker ps -aq` and
`docker images -q` list nothing at all, so a live daemon demonstrates neither
that the allowlist matches nor that no prune happens — the gate drives a fake
`docker` that RECORDS every argv it is handed, which makes "no prune" checkable
as a CALL. That distinction was itself a review finding: the first version of
that test asserted only that the word "prune" was absent from the printed
report, and a real `docker system prune -af` added to the code left the whole
suite green.

**Uninstalling undeclared packages.** A package installed by hand into the
virtual environment is indistinguishable there from a transitive pin of a
declared one; this repository's own property-test dependency arrived only
transitively for a period, so an "uninstall the undeclared" pass would have
broken it. What is precise and offline is manifest drift, so that is what is
reported.

**Reporting remote-tracking branches.** Out of scope here. Remote-tracking refs
go stale silently until someone prunes them, and the tool must not fetch — it
stays offline and free. Named so the next reader knows it was considered.

## Consequences

- Five of the eight categories will never clean anything on their own. That is
  the trade accepted: the tool's value is that it *sees* everything and destroys
  nothing it cannot prove is residue.
- `merge-tree --write-tree` adds unreferenced tree objects to the object store —
  a handful, tens of bytes, reclaimed by ordinary garbage collection. It touches
  no ref, no index, no HEAD and no working tree; verified with staged, modified
  and untracked files present, the porcelain status was byte-identical before
  and after. There is no read-only variant that answers this question.
- A branch whose changes were merged and then reverted on the trunk reports as
  unmerged. That is the correct answer for a cleanup tool: the branch is the
  only remaining reachable copy.
- A branch that adds a file and removes it again reports as merged, so deleting
  it loses the intermediate blob. Accepted: the working state is genuinely
  identical to the trunk's.
- Adding a ninth category means editing two files in the same change — the
  script and the table in the gate — or the gate fails.
- A reviewer copy taken with `git archive` carries no `.git`, so the checkout
  guard cannot see it at any depth. A copy taken with `git clone` is caught. The
  named-paths discipline is what covers the rest: no delete list contains a
  directory a reviewer would plausibly unpack into.

## Related

- `scripts/session_hygiene.py` — the tool.
- `tests/unit/test_session_hygiene.py` — the gate, including the category table.
- `docs/adr/0066-a-negated-issue-close-is-caught-in-the-two-places-it-can-happen.md`
  — the other place this repository writes down a "two things that look like one
  thing" hazard.
