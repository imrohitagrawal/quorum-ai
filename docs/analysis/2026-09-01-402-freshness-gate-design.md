# 2026-09-01 — #402: what a board-anchor squash-survival gate has to survive, and why two designs did not

**STOPPED. Nothing merged. `#402` stays open.** Two designs were built, reviewed
and measured; each fix round introduced a new defect, which is AGENTS.md rule
12's stop condition. This file is the record so the next attempt starts from
measurements rather than from the same two dead ends.

The branch `issue-402-freshness-anchor-gate` (commits `fa32055`, `9cf58d8`) was
deleted after this was written. Everything below is reproducible from the
commands given.

## Provenance of every claim here

Marked throughout:

- **[me]** — I ran the command in this session and read its output.
- **[reviewer]** — an independent read-only reviewer ran it; I did not
  re-run it.
- **UNVERIFIED** — nobody produced the command output.

## 1. The failure being prevented

`docs/65-open-work.md` carries `Verified at: <40-hex sha>`.
`scripts/check_open_work.py::check_freshness` requires that commit to exist, to
be an ancestor of **`HEAD`**, and to be within `MAX_DRIFT_COMMITS` (60)
first-parent commits of it.

On a feature branch a commit made ON that branch *is* an ancestor of HEAD, so
the gate passes it. This repository squash-merges, which discards the branch
commit; on `main` the anchor is neither present nor an ancestor, and the gate
refuses far too late. PR #399 did exactly that: anchor `2350e59`, squash
`59f402a`.

Measured on that SHA **[reviewer, re-confirmed by me for the run list]**: `Tests`
→ failure, `CI` → failure, and of nine `Deploy to Fly.io` runs **3 failed** at
the *require CI + Tests + E2E green* gate and **6 were skipped** — so "every
Deploy run went red" (which I wrote in the first draft) is false; nothing
deployed, but only three runs failed.

```
gh run list --commit 59f402a7c951b90e2af376558f71ff4701b831a1 \
  --json name,conclusion --jq '.[]|"\(.name): \(.conclusion)"' | sort | uniq -c
   1 CI: failure
   3 Deploy to Fly.io: failure
   6 Deploy to Fly.io: skipped
   1 Tests: failure
```

**Trap worth keeping:** one reviewer got `[]` from `gh run list --commit
59f402a…` and had to use `--branch main` — the AGENTS.md rule 18a trap, alive
again. My own invocation above returned rows. Try both. **[me + reviewer,
disagreeing — treat `--commit` as unreliable]**

## 2. The four hypotheses I was handed, and which survived

**H1 — direction (b), ancestry against `merge-base(HEAD, origin/main)`, does
not escape the stale-remote false positive. SURVIVES. [me]**

Stale model: clone, `git update-ref refs/remotes/origin/main <M0>` while HEAD is
`M1`, a real `main` commit. Exit codes captured into variables first (a command
substitution inside the `echo` that prints `$?` resets it — that mistake made
(b) look like it passed on my first run):

```
HEAD/anchor M1=1597255b  origin/main(stale)=2a66b9c7  merge-base=2a66b9c7
(a) is-ancestor anchor origin/main EXIT=1
(b) is-ancestor anchor merge-base  EXIT=1
```

(b) is strictly stronger than (a) — the merge-base is itself an ancestor of the
ref tip — so it can only refuse more often. It is not an escape hatch.

**H2 — `git rev-list origin/main..HEAD` fails the same way. SURVIVES. [me]** In
the same model, `git rev-list origin/main..HEAD | grep -c M1` → `1`: a commit
genuinely on `main` looks branch-unique.

**H3 — the fact is not derivable offline against a stale ref. SURVIVES. [me]**
The obvious discriminator answers identically in both cases, because both
anchors are descendants of the ref tip:

```
stale case  : origin/main anc of anchor: 0
branch case : origin/main anc of anchor: 0
```

**H4 — in CI the ref is present and fresh, so a blocking check is affordable
there. SURVIVES. [me, from CI logs]** `make validate` runs in exactly one job
(`grep -rn "make validate" .github/workflows/` → `ci.yml:77`,
`validate-and-test`, `fetch-depth: 0`). From that job's own log:

- push build, run `33467478567`: `fetch --prune --no-recurse-submodules origin
  +refs/heads/*:refs/remotes/origin/* +refs/tags/*:refs/tags/*`, then
  `git rev-parse refs/remotes/origin/main`;
- pull-request build, run `33466696419`: the same wildcard refspec plus
  `+64d0c46…:refs/remotes/pull/415/merge`; HEAD is the pull merge ref, so no
  `rev-parse` line appears in that log — the fetch reports
  `* [new branch] main -> origin/main` instead **[reviewer]**.

## 3. Design A — "the anchor must be an ancestor of `origin/main`, plus a
committer escape". BUILT, THEN REFUTED.

Because H3 holds, the first draft added an offline discriminator: accept a
non-ancestor anchor whose committer is `GitHub <noreply@github.com>`, on the
reasoning that GitHub performs every squash merge here.

The supporting measurement was real **[me]**:

```
git log --first-parent origin/main -40 --format='%cn <%ce>' | sort | uniq -c
  40 GitHub <noreply@github.com>
git log --first-parent origin/main --format='%ce' | sort | uniq -c | sort -rn
 267 noreply@github.com
  57 rohit.ra.agrawal@gmail.com
   5 rohitagrawal@users.noreply.github.com
git rev-list --count --first-parent b729950..origin/main   ->  222
```

**And it measured the wrong population.** The discriminator is only ever applied
to commits that are *not* on `main`; nobody measured those. GitHub stamps the
same identity on every commit it creates server-side, **including the "Update
branch" merge it makes on a feature branch** — the one-click way to satisfy
AGENTS.md rule 17d. Re-verified by hand **[me]**:

```
172803b7804e | committer=noreply@github.com | parents=2 |
  Merge branch 'main' into codex/brand-readiness-2026-08-03
git merge-base --is-ancestor 172803b origin/main  ->  EXIT=1
```

Design A accepted that commit. A reviewer reported **three** such commits among
this repository's 281 pull-request head tips; I confirmed **one** (the other two
are no longer in the local object store). "three of 281" is **[reviewer]**;
"at least one, and it is `172803b`" is **[me]**.

Design A also refused correct anchors in two layouts **[reviewer, reproduced by
me]**: a `git clone --bare` plus `git worktree add` layout, and a
`--single-branch` clone of a feature branch. Neither configures a refspec that
could produce `origin/main`, so the remedy the message printed
(`git fetch origin main`) provably does nothing and `make validate` stays red
permanently.

## 4. Design B — "decide skip-versus-refuse from the configured refspec".
BUILT, THEN REFUTED, AND IT WAS A REGRESSION.

Design B deleted the committer escape and replaced "refuse whenever
`origin/main` is absent" with a test on `git config --get-all
remote.origin.fetch`: if no refspec maps `refs/heads/main`, skip with a note.

The refspec table it rested on is correct **[me]**:

| Clone shape | `remote.origin.fetch` | `origin/main` |
|---|---|---|
| full clone | `+refs/heads/*:refs/remotes/origin/*` | PRESENT |
| `--depth 1` of `main` | `+refs/heads/main:refs/remotes/origin/main` | PRESENT |
| `--single-branch -b feat` | `+refs/heads/feat:refs/remotes/origin/feat` | ABSENT |
| `git clone --bare` + `git worktree add` | *(none configured)* | ABSENT |
| `git remote add origin`, never fetched | `+refs/heads/*:refs/remotes/origin/*` | ABSENT |

**The inference from it does not follow, and that is the root cause.** The
docstring's load-bearing sentence was *"Only the last of those is an environment
that SHOULD have the ref."* Rows 3 and 4 are not environments with nothing to
check — they are environments where an author is holding a branch-only anchor.
Row 4 has a complete local `refs/heads/main` in the same object store; row 3 is
one explicit fetch away. **"No refspec could produce `origin/main`" was treated
as "`main` is unknowable here", and those are different facts.**

Reproduced by me, same tree, same branch-only anchor with an ordinary local
committer, in a `--single-branch --branch issue-999` clone:

```
anchor (branch-only) = fe3c8ea57214
clone refspec: +refs/heads/issue-999:refs/remotes/origin/issue-999
origin/main present? NO
  9cf58d8 -> ACCEPTED, note=', squash-survival SKIPPED (`origin` tracks no `main`)'
  fa32055 -> REFUSED: 65-open-work.md: this checkout has an `origin` remote but no `origin/m…
```

**Design B is a regression against Design A on this shape.** A reviewer drove it
end to end **[reviewer]**: `open-work-check EXIT=0` on the branch, then after a
real squash merge, on a full clone of `main`,
`FAIL 65-open-work.md: anchor commit 4c94719 is not in this repository` — the
#399 failure reproduced one design later, with no GitHub involvement at all.

Two further shapes **[reviewer]**: `git remote set-branches origin <feature>` in
a *full* clone leaves `origin/main` present, correct and current while the
config stops mentioning it → skip; and the bare-clone+worktree layout skips
though `refs/heads/main` is local and complete. **The gate can answer and
declines to.**

## 5. The test pinned the hole. Twice. This is the transferable lesson.

Design A shipped `test_a_squash_merge_not_yet_fetched_is_accepted_because_github_committed_it`,
which asserted the committer escape *as intended behaviour* — so the suite
locked in the false negative.

Design B shipped `test_an_origin_that_tracks_only_another_branch_skips_instead_of_refusing`,
which asserts the skip using an anchor that **is** on `main`, and whose two
positive partners also use an on-`main` anchor. No test asserts that a
branch-only anchor is still caught in a skip shape — and none can, because the
skip returns before looking at the anchor.

Both are AGENTS.md rule 7 failing the same way: **a negative check whose
positive partner shares the input class that hides the defect.** The partner
must vary the dimension the check is about. For a squash-survival gate that
dimension is *"is this anchor branch-only?"*, and every skip-path test used an
anchor that was not.

## 6. The bite-proof any future attempt must pass

Both directions, as executable cases. The first three were the brief's
requirements; the rest are now **measured** requirements, not hypotheticals.

**Must REFUSE (false-negative proofs):**

1. a branch-only commit with an ordinary local committer, in a full clone;
2. a branch-only commit **committed by `GitHub <noreply@github.com>`** — the
   "Update branch" merge; `172803b` is a real instance;
3. the same branch-only anchor in a `--single-branch --branch <feature>` clone;
4. the same in a `git clone --bare` + `git worktree add` layout;
5. the same after `git remote set-branches origin <feature>` in a full clone,
   where `origin/main` is present and current;
6. end to end: gate green on the branch **and then** a real squash merge, with
   the gate re-run on a fresh full clone of `main`. A design that passes 1–5 in
   unit form can still fail this.

**Must NOT REFUSE (false-positive proofs):**

7. a valid `main` anchor in a full clone (the trivial partner — without it,
   "refuses" is indistinguishable from "refuses everything");
8. a valid anchor in a repository with **no** remote, and in one whose only
   remote is `upstream`;
9. a valid anchor in a `--depth 1` / `--depth 5` clone of `main` (**these HAVE
   `origin/main`** — "shallow" is *not* the shape that lacks it; Design A's
   error message said it was, and that was measured false);
10. a valid anchor against a **stale** `origin/main` (H3: not derivable
    offline — either accept the refusal and say so, or find something ancestry
    cannot see);
11. **the fork-behind topology** — `origin` = the contributor's unsynced fork,
    `upstream` = canonical, anchor a real `main` commit on `upstream/main`.
    Design B refuses it, permanently, and `git fetch origin main` does **not**
    clear it because `origin/main` is the fork's own stale tip **[reviewer]**.

**Also required:** every skip path needs a test proving a branch-only anchor is
still caught *in that same shape* — see §5.

## 7. Facts already paid for, so nobody re-derives them

- **CI is not exposed by the refspec path.** `actions/checkout@v4` never writes
  `remote.origin.fetch`; a grep of run `33466696419`'s full log returns zero
  hits. It passes refspecs on the command line. **[reviewer]**
- Both real checkouts have `remote.origin.fetch =
  +refs/heads/*:refs/remotes/origin/*` and a present `origin/main`. **[me]**
- `git fetch origin <sha>` brings an object **without** advancing
  `origin/main`; `git fetch origin main` and `git pull` both advance it. **[me,
  all three]** A reviewer adds that `git fetch upstream` also brings objects
  without advancing `origin/main` **[reviewer]** — so "the only operation that
  does this" (which ADR-0088's draft said) is false.
- `git merge-base --is-ancestor <absent sha> <ref>` exits **128** with
  `fatal: Not a valid commit name`; a depth-1 clone of `main` lacking an older
  anchor already fails the pre-existing existence check. **[me]**
- `gpg` is not installed on this machine, so any signature-based discriminator
  is vacuous locally: `error: cannot run gpg: No such file or directory`,
  `%G?` = `N`. **[me]** A reviewer measured the actual signing key id as
  `B5690EEEBB952194`, not the legacy `4AEE18F83AFDEB23` **[reviewer]**.
- `fnmatch.fnmatchcase` over 29 pathological refspec values raised nothing and
  never hung (worst case 5.43 ms, subprocess-dominated). **[reviewer]**
- Global git config breaks these sandboxes unless pinned: `commit.gpgsign =
  true` kills five tests in `test_open_work_matches_reality.py` (three of them
  pre-existing, via `_sandbox_repo`), and `protocol.file.allow = never` kills
  any helper that pushes over `file://`. `-c commit.gpgsign=false` and building
  the remote with `git remote add` + `git update-ref` instead of a push fix
  both. **[me]** Note `-c core.hooksPath=/dev/null` is refused by this repo's
  own pre-tool hook as a gate bypass — do not reach for it.
- An ambient `GIT_COMMITTER_EMAIL` beats `-c user.email`, so a test that cares
  about the committer must set `GIT_COMMITTER_NAME/EMAIL` explicitly. **[me]**

## 8. Mutation results, with both counts

Thirteen mutations against Design B, each applied to a `cp` copy of
`scripts/check_open_work.py`, suite re-run with `PYTHONDONTWRITEBYTECODE=1`,
restored from the copy and confirmed with `diff -q`. Baseline **46 passed**
**[me]**. Reported with the pass count as well as the fail count, because a
mutation that breaks collection is otherwise indistinguishable from a kill —
every row below sums to 46, so none broke collection.

| # | Mutation | Result |
|---|---|---|
| N1 | drop the `check_squash_survival` call from `check_all` | 2 failed, 44 passed |
| N2 | `REMOTE_MAIN` → `"HEAD"` | 5 failed, 41 passed |
| N3 | `--is-ancestor` arguments swapped | 5 failed, 41 passed |
| N4 | ancestry polarity `== 0` → `!= 0` | 7 failed, 39 passed |
| N5 | no-`origin` becomes a hard failure | 3 failed, 43 passed |
| N6 | no-`origin` skips silently (note dropped) | 2 failed, 44 passed |
| N7 | refspec test always true | 1 failed, 45 passed |
| N8 | refspec test always false | 7 failed, 39 passed |
| N9 | refspec matched on the destination, not the source | 7 failed, 39 passed |
| N10 | missing-ref branch degrades to a silent pass | 2 failed, 44 passed |
| N11 | `cat-file` existence guard removed | 1 failed, 45 passed |
| N12 | `git_note` dropped in `check_all` | 1 failed, 45 passed |
| N13 | the `git fetch origin main` remedy sentence replaced with `XXXX` | 1 failed, 45 passed |

**All thirteen were killed — and that is worth exactly nothing here.** The
defect that stopped this package (§4) is invisible to every one of them, because
the tests themselves encoded the wrong contract (§5). A mutation score measures
whether the tests pin the code that exists; it cannot tell you the code is
wrong.

Four rows (N7, N11, N12, N13) are killed by a single test each; N7 is the only
guard on the entire skip path **[reviewer]**. N7 and N13 are recorded here with
their exact replacements so they can be reproduced byte-for-byte.

## 9. What I would build next, if anything

Not a recommendation to build immediately — see §10.

The shape that survives everything measured above is: **do not ask which refs
are configured; ask what `main` this repository can actually see, and refuse to
guess when it can see none.**

1. Resolve a "known `main`" from, in order: `refs/remotes/origin/main`, then
   any other remote-tracking `*/main`, then the local `refs/heads/main`.
   Requirement 5 (`set-branches`) and requirement 4 (bare clone + worktree)
   both fall out of this, because in both the ref is right there.
2. If **no** `main` is resolvable anywhere, skip — and say so in the report
   line. That population is now small and honest: a `git init` sandbox with no
   remote and no local `main`.
3. If more than one is resolvable and they disagree, the anchor must be an
   ancestor of **at least one**. That admits the fork-behind topology
   (requirement 11) without any heuristic, because `upstream/main` covers it.
4. Accept the stale-ref refusal of requirement 10 explicitly, in hedged wording,
   with `git fetch` named as the first remedy — and never claim one fetch
   always clears it, because in the fork-behind case it does not.

Every skip path needs the §5 partner: a branch-only anchor, in that same shape,
still caught.

## 10. Why this was not shipped

Two fix rounds, each introducing a defect the previous one did not have — the
condition AGENTS.md rule 12 names for changing the approach rather than
patching again. Beyond the rule:

- Design B **fails open in a layout adjacent to this repository's own mandated
  workflow** (rule 17a requires a dedicated worktree; the bare-clone spelling of
  that is accepted).
- Design B's skip fires because a config line stopped mentioning a ref, not
  because the fact was unknowable — it can answer and declines to.
- Both designs shipped a test that pinned their own hole open.

A gate that turns `main` red for everyone, or that is blind in the workflow the
rulebook mandates, is worse than the prose it replaces. The prose in
`docs/65-open-work.md` ("Stamp a commit that is already on `main`, never one
from your branch") is unchanged and still correct.

## 11. Explicitly UNVERIFIED

- Two of the three GitHub-committed pull-request head tips a reviewer reported;
  I confirmed one (`172803b`).
- `git fetch upstream` bringing objects without advancing `origin/main`
  **[reviewer only]**.
- The GitHub signing key id `B5690EEEBB952194` **[reviewer only]**.
- The reviewers' own end-to-end squash-merge reproductions; I reproduced the
  unit-level regression myself (§4) but not their full merge cycle.
- Whether the §9 shape actually passes all eleven requirements. It is a design,
  not a measurement.

## 12. Late addendum — a third, independent lens reached the same stop

A fourth reviewer, auditing the fix round rather than the feature, arrived at
the §4 regression from mutation testing instead of from topology, and added two
things worth keeping. All **[reviewer]**; I did not re-run them.

**Two behaviour-changing mutants survive all 46 tests.** This is the concrete
form of §8's warning that a 13-of-13 kill measured nothing that mattered.

- Moving the `_origin_tracks_main` guard inside the missing-ref branch leaves
  `46 passed`, and changes behaviour: with `origin/main` **present** but a
  refspec that does not match `refs/heads/main`, Design B skips where Design A
  refused. Design B's `--`-marked design table never covered the ref-present
  half of that row, and no test does either.
- `splitlines()[:1]` (read only the first refspec line) leaves `46 passed`, and
  is reachable: `git remote set-branches --add origin main` puts `main` on the
  **second** line — which is precisely the remedy a skipped user would apply.

**`_origin_tracks_main` gets git's real behaviour wrong in four cases**
(helper's answer vs. what git actually does, on `git 2.54.0`):

| `remote.origin.fetch` | helper says | git actually |
|---|---|---|
| `refs/heads/main` (no colon) | tracks | ref stays ABSENT after `git fetch origin main` |
| `+*:refs/remotes/origin/*` | tracks | ref ABSENT after fetch |
| `+main:refs/remotes/origin/main` | does not track | git **does** create the ref |
| `[` / `?` metacharacters | no exception | git rejects the refspec outright |

Also: `if source and …` is dead code, since `fnmatchcase(x, "")` is always
False; and negative refspecs are handled correctly only by accident
(`lstrip("+")` happens to leave the `^`).

**What the fix round did get right, so the cost was not total.** The
escape-hatch deletion is well founded, and the test-helper hardening works:
under a hostile global git config the draft is `10 failed, 35 passed` and the
fix is `46 passed` — 5 frames from `commit.gpgsign`, 6 from
`protocol.file.allow=never`, 3 from an ambient `GIT_COMMITTER_EMAIL`, matching
the three numbers written in the docstrings exactly. Those helper fixes are
worth salvaging into any future attempt.

**One prose claim of mine that this reviewer contradicts:** the commit body
called `git clone --bare` + `git worktree add` "how rule 17a's workflow is
usually done". Not in this repository — the worktree used for this very package
was a worktree of the ordinary clone and inherited the wildcard refspec. The
bare-clone layout remains a real shape that must be handled (§6 requirement 4),
but it is not what rule 17a produces here.
