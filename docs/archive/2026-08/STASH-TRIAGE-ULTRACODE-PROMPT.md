# Triage the four stashes — verify, archive, then drop

> **Written:** 2026-07-29 at `ed10143`. Four stashes from 23–25 July sit in the
> local clone. They are **not** from the 28–29 July session. This decides,
> per stash, whether its content reached `main` — and drops only the ones
> proven.
>
> **These live only in ONE clone.** A stash is not pushed. If this clone is
> lost, they are gone; if they are dropped without archiving, they are gone.
> That asymmetry is why this is a dedicated session and not a one-liner.

---

## 1. The four, measured

| ref | SHA | date | contents |
|---|---|---|---|
| `stash@{0}` | `a201f48f` | 25 Jul | 11 files — `costs.py`, `debate.py`, `providers.py`, `query_runs.py`, `synthesis.py`, `app.js`, `app.css`, `golden-run.ts`, 3 test files. **184 insertions, 449 deletions** |
| `stash@{1}` | `33922927` | 25 Jul | 1 line in `costs.py`: add `cumulative > 0` to the hard-limit guard |
| `stash@{2}` | `3ba73c08` | 23 Jul | `Makefile`: fail `gate-min-executed` when the JUnit XML is missing or counts cannot be derived |
| `stash@{3}` | `acc2f701` | 23 Jul | ops dashboard — `ops.js`, `ops.html`, `ops.css`, `ops-dashboard.spec.ts`, `test_ops_dashboard.py`. **748 insertions** |

**Use the SHAs, never the indices.** Dropping `stash@{1}` renumbers `{2}`→`{1}`
and `{3}`→`{2}`. Dropping by index in a loop deletes the wrong things.

---

## 2. What has already been checked, and why it is not enough

Two checks were run on 2026-07-29. **Read both — the second is the reason this
task exists.**

**String-level evidence (suggests {1} and {2} landed):**

```bash
grep -n "cumulative > 0 and cumulative + estimated > HARD_LIMIT_USD" src/product_app/costs.py
# -> present (costs.py:434)
grep -c "xml is missing — the gate suite never produced" Makefile   # -> 1
grep -c "could not derive executed/skipped counts" Makefile          # -> 1
```

**Reverse-apply evidence (proves nothing, for ALL FOUR):**

```bash
for i in 0 1 2 3; do
  git stash show -p "stash@{$i}" > /tmp/s$i.patch
  git apply -R --check /tmp/s$i.patch && echo "$i: on main" || echo "$i: NOT PROVEN"
done
# -> all four print NOT PROVEN
```

`git apply -R --check` requires the **surrounding context lines** to match, and
those files have been rewritten since 23–25 July. So it fails even where the
change demonstrably landed. **A clean reverse-apply would be proof; a failed one
is not disproof.** Do not treat it as a verdict either way.

An earlier pass also called `stash@{3}` "landed" because `ops.js` exists on
`main`. That is file existence, not content — 748 insertions are not verified by
one file being present. **That call was wrong and is retracted here.**

---

## 3. Your job

### Step 1 — ARCHIVE FIRST. Nothing is dropped before this succeeds.

A dropped stash is recoverable from the reflog only for a while, and only in
this clone. Pin each one under a permanent ref so `drop` becomes reversible:

```bash
git update-ref refs/archive/stash-0 a201f48fd51b267703a2c870d77a4f8e60df3c3f
git update-ref refs/archive/stash-1 339229272158beafe09674c75d17341c60e7870a
git update-ref refs/archive/stash-2 3ba73c089e118fad140b010a19e52444a0c643c2
git update-ref refs/archive/stash-3 acc2f7012a2e93cd5cd6586467d159852ee0f8dc
```

Then PROVE the archive works before trusting it:

```bash
git show --stat refs/archive/stash-2          # must print the Makefile diff
git stash show -p refs/archive/stash-2 | head # must print the patch
```

Also write each patch to a file outside the repo (`/tmp/stash-N.patch`) as a
second copy. **If either the ref or the patch file is missing for a stash, do
not drop that stash.**

### Step 2 — verify {1}, {2}, {3} hunk by hunk, not file by file

For each of the three, take `git stash show -p` and walk **every hunk**. For
each one, answer in writing:

- what behaviour does this hunk change?
- is that behaviour present in `main` today?
- what command shows it? (grep for the distinctive string, read the function,
  or run the test that covers it)

A hunk counts as landed only when a command shows the behaviour on `main`.
"The file exists" and "it looks similar" are not answers.

**Expect surprises in `stash@{3}`.** It is 748 insertions of ops-dashboard work
and the ops surface shipped through PRs #85/#87/#89 — but nobody has compared
them. If a hunk has NOT landed, say so and stop; do not drop it.

### Step 3 — drop ONLY the fully-verified ones, by SHA

```bash
git stash list --format="%gd %H"          # map SHA -> current index, EVERY time
git stash drop "stash@{<index-for-that-SHA>}"
git stash list                            # re-read; indices have now shifted
```

Drop one at a time, re-reading the list between each. If any hunk of a stash is
unverified, that whole stash stays.

### Step 4 — `stash@{0}`: INVESTIGATE AND REPORT. Do not drop it.

This is the interesting one and the reason for a dedicated session. **449
deletions against 184 insertions** across `costs.py`, `providers.py`,
`query_runs.py`, `synthesis.py` and `app.js` — a large *removal*, made on 25
July, three days before PR #96 (WP-A…WP-F) rewrote those same files.

Two possibilities, and they need different actions:

1. **It was superseded** — #96 did the same simplification a different way.
   Then it is safe to drop, once shown hunk by hunk.
2. **It was abandoned** — someone removed something deliberately (dead code, a
   misfeature, a cost path) and the work was lost when the branch moved on. Then
   the *idea* may still be worth having, and dropping it silently loses it.

Produce a written verdict per area (costs / providers / query_runs / synthesis /
app.js / fixtures / tests): superseded, or lost. Cite the command for each.

**Do not drop `stash@{0}` in this session under any circumstances.** Report, and
let the operator decide. If the verdict is "lost", file an issue describing what
was removed and why it might still be wanted.

---

## 4. Rules

1. **Verify by executing, never by reading.** State the command you ran and what
   it printed. If you did not run one, say UNVERIFIED. This exact task has
   already produced two wrong "landed" calls made from reading.
2. **A failed reverse-apply is not disproof.** See §2.
3. **Archive before you drop.** No exceptions.
4. **Drop by SHA→index lookup, re-read the list between every drop.**
5. **Never `git stash pop` or `git stash apply`.** They mutate the working tree
   and, on conflict, can leave it in a half-merged state. Everything here is
   answerable with `show`, `apply --check`, and `grep`.
6. **The working tree must be clean when you start and clean when you finish.**
   `git status --porcelain` — the three untracked `*-ULTRACODE-PROMPT.md` files
   at the repo root are pre-existing; leave them.
7. **Do not touch the two local branches** `feat/ui-pr5b-cost-guard-diff` and
   `worktree-wf_8fbedc6c-041-3`. An earlier handoff flagged both; they are not
   in scope.
8. **This changes no tracked file.** If you find yourself editing `src/` or
   `tests/`, stop — that is a different task.
9. **Fan out read-only subagents** for the hunk-by-hunk verification if useful.
   Tell every one **IN CAPITALS** not to write, edit, `git checkout`,
   `git stash`, `git update-ref` or `sed -i` anything. One tree-writer: you.

---

## 5. Definition of done

- `refs/archive/stash-0..3` all exist and `git show` prints each one.
- A written per-hunk verdict for `{1}`, `{2}`, `{3}`, each citing a command.
- Fully-verified stashes dropped; anything unverified still present.
- `stash@{0}` **still present**, with a written per-area verdict and an issue
  filed if anything was lost.
- `git status --porcelain` shows only the three pre-existing untracked files.

---

## 6. Paste this into a fresh chat

```text
ultracode

Read AGENTS.md, then STASH-TRIAGE-ULTRACODE-PROMPT.md in full before running
anything.

There are four git stashes from 23-25 July in this clone. They exist in NO
other copy and are not pushed anywhere. Your job is to decide, per stash,
whether its content reached main — and to drop only the ones you can prove.

ARCHIVE FIRST (§3 step 1). Do not drop anything until `git show
refs/archive/stash-N` prints the diff for all four AND a patch file exists
outside the repo. If either is missing for a stash, that stash is not eligible
to be dropped.

Then verify {1}, {2}, {3} HUNK BY HUNK. For each hunk say what behaviour it
changes, whether main has that behaviour today, and the command that shows it.
`git apply -R --check` FAILS on all four because of context drift — a clean
reverse-apply would be proof, a failed one is NOT disproof. Two earlier
"landed" calls on this task were made from reading and were both wrong.

Drop only fully-verified stashes, by SHA->index lookup, re-reading
`git stash list` between every drop because indices shift.

stash@{0} is 449 deletions across costs/providers/query_runs/synthesis/app.js,
made three days before PR #96 rewrote those files. INVESTIGATE AND REPORT ONLY
— do not drop it, whatever you conclude. Give a per-area verdict (superseded
vs lost) with the command behind each, and file an issue if anything was lost.

Never `git stash pop` or `git stash apply`. Use show / apply --check / grep.
Leave the tree clean; the three untracked *-ULTRACODE-PROMPT.md files at the
root are pre-existing.

Fan out read-only subagents if useful — tell every one IN CAPITALS not to
write, edit, git checkout, git stash, git update-ref or sed -i anything.
One tree-writer: you.

Report per stash: verdict, the command that proved it, and what you dropped.
```
