# Session handoff — 2026-08-25, second session (autonomous work loop)

The first 2026-08-25 narrative (`docs/analysis/2026-08-25-session-handoff.md`) is Lane 1's. This one is
the autonomous work-loop session that ran beside it and after it. Read both; this one is later.

## State at hand-off (re-derive before trusting)

- `origin/main` = `6f0ed3a` (#372). Production `build_sha` = `6f0ed3a` (`curl -s https://quorum.stackclimb.com/status`, 2026-08-25 ~15:30 UTC). Live execution off, spend $0, no paid call made this session.
- Two pull requests open, both green and vetted, both waiting on a human merge: **#373** (docs — this
  ledger, three audit rows, the archived session prompts and analyses, this handoff) and **#375**
  (`make close-guard` refuses an unlisted close; fixes #374).
- Issues closed this session with evidence: #337 (score line in job 97606765828), #369 (the re-scoped
  ask already existed since `e693ac5`). Retitled: #368 (the "blocking gate flakes" claim was refuted — `gh run list --workflow test.yml --limit 60`
  at 09:52 UTC: 56 success / 1 failure / 3 cancelled, 0 SHAs with two outcomes); Lane 1 then closed it at 11:23 UTC. Filed: #374. Open backlog after merges: #105, #268, #290
  (all "stop and ask" items, untouched). `gh issue list --state open` at hand-off: #105, #268, #290, #374 —
  #374 closes when #375 merges.

## What the loop measured — the point of the session

`docs/analysis/protocol-compliance.md` has three audited rows: 12/1/1, 6/0/9, 11/3/1
(followed / broken / not applicable). No rule broken twice running. Three issue premises were refuted by
command in one day (#368's title; #369's re-scope, already on main; the loop prompt's own "start with #368",
already claimed by another live session) and a fourth — #369's original scope — fell to the human's
proportionality ruling rather than to a command. The rule that paid for itself is D1: verify the premise by command before spending anything.

Two things the fourteen rules did not cover, now recorded: **proportionality** (rule 15 — an 867-line
fully reviewed, all-green PR #371 was closed unmerged as disproportionate to an advisory gate) and the
**close-keyword trap in quoted prose** (both guards passed a non-negated unintended closer; two PR bodies
tripped it in one day, one of them while documenting the other — #374, fixed in #375).

## Merge steps for the human (in this order)

1. `#373` first (docs). Vet: `PR=373 MERGE_SUBJECT="…" MERGE_BODY="$(cat body.md)" make close-guard`
   (the OLD guard on main today; expect `0 closing reference(s)`). Squash-merge with an explicit body.
2. `#375` second. Its merge body says it closes #374 on purpose. After #373 merges, run the vet from
   the #375 worktree with the NEW guard: `PR=375 EXPECT_CLOSE=374 … make close-guard` → expects
   `closes exactly the expected set: [374]`.
3. Verify each deploy per AGENTS.md rule 18 (the deploy JOB, `build_sha`, the thing firing — for #375,
   `make close-guard` on main with an unlisted closer must refuse).
4. Remove worktree `quorum-ai-wt-374` and branch `fix/374-close-guard-expected-closes` (local + remote)
   after #375 merges; the docs branch after #373.
5. **Before `git merge --ff-only origin/main` in the main checkout:** it holds untracked originals of the 13
   files #373 tracks (the six `*-ULTRACODE-PROMPT.md` at root and seven under `docs/analysis/`), and git
   refuses to fast-forward over an untracked file at a path the merge adds, even when the content is
   identical. Compare each to `git show origin/main:<path>` (five are byte-identical; eight differ — seven scrubbed, one carrying an editor's note),
   then delete the 13 by name — never `git clean`. Then fast-forward.

## Traps met this session

- **Another session was live on the item the prompt said to start with.** `git worktree list` shows the
  tree, not who is in it; the transcript mtimes and `ps` do. Stay out of what another session owns.
- **The permission classifier blocks `gh pr merge` in this harness mode** even with spoken merge
  authority; the human ran the merges. Nothing was routed around.
- **A fresh worktree's `uv sync` produced Python 3.14.5**; CI is 3.12. Use `uv sync --all-extras --python 3.12`.
- **Quoting the closing phrase reproduces it.** GitHub reads `close #N` inside quotation marks, code
  spans in a PR body, and explanatory prose. Describe it; never quote it next to a real number.
- **A sub-orchestrator that launches its gate chain in the background returns early**; it resumes on the
  chain's completion, so do not re-run its gates yourself — check `ps` and wait.
- **ADR numbers collide across concurrent sessions** (#372 and #371 both took 0072). Check
  `ls docs/adr | tail -1` on `origin/main` right before committing an ADR, and again before pushing.

## Residue

- Scratch for this session (session-scoped, outside the repo): three package logs kept as the audit
  evidence; everything else deleted by name. Nothing of this session's is untracked in the repo.
- `refs/pull/371/head` (`ada74dd`) holds the rejected inventory-guard approach, should it ever be wanted.
