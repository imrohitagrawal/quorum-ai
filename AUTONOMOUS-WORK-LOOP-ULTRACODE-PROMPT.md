# Autonomous work loop — analyse, prioritise, execute, merge, repeat

A self-driving loop for clearing a backlog. Written 2026-08-25, encoding what
was **measured** in the session that produced it, not what sounds good.

**Read this whole file before spawning anything.**

---

## THE FOUR RULES THAT OVERRIDE EVERYTHING

These exist because each was violated in one session and cost real damage.

1. **A sub-orchestrator NEVER merges.** This is permanent and not negotiable —
   it is a role boundary, not a trust level. It hands back a green pull request.

   **Whether the MAIN orchestrator may merge without asking is separate, and
   starts at NO.** It asks every time until the human grants otherwise. That
   grant is session-scoped and spoken; it is never written into a config file,
   because the same words in a file grant the power in six months to a session
   nobody is watching. **Do not ask for the grant before five packages have
   been audited** (Phase F) and rules 4, 5, 9, 10 and 14 are each 5/5. Below
   that, the evidence does not exist. From outside, an agent
   merging on standing permission is indistinguishable from one merging on its
   own authority — and merge text is the one thing continuous integration never
   sees. Four issues in this repository have been closed by accident by a close
   keyword sitting next to an issue number in merge text.

2. **Every fix gets its own review round.** Measured: round-one fixes introduced
   **four** new false claims, and the round-two fixes that corrected those
   introduced **three** more. A correction is written under time pressure, from
   a reviewer's framing, without re-deriving the replacement. It is *more*
   suspect than the original, not less. Budget a round for it.

3. **At least one reviewer's only job is to RUN COMMANDS against the artefacts
   and the source tree.** Measured: three reviewers who read prose missed a live
   public credential-adjacent leak, a premise that had gone stale hours earlier,
   and a caveat that had been read off a command-line flag instead of executed.
   The reviewer told to run things found all three.

4. **Verify an item's PREMISE before selecting it.** Measured: three researchers
   examined three issue titles; **all three were materially wrong.** One
   described work as ready to build that was already merged and running in
   production. Selecting on a title wastes an entire package.

---

## HARD CONSTRAINTS

- **No paid API calls.** If a question can only be settled by spending, mark it
  UNVERIFIED, name the exact check, and move on. Never flip a live-execution
  switch to test something; drive it with a fixture.
- **Never `git clean -fdx`, `git clean -fd`, or `git stash -u`.** Delete named
  paths only.
- **Never revert a mutation with version control.** `cp` the file aside and
  restore from the copy, then `diff -q` to prove the restore.
- **Before committing any artefact, scrub it** of absolute paths, usernames,
  user IDs, session identifiers and private project names. A gate scoped to one
  directory will not see a file you add somewhere else. This is how a real leak
  reached a public repository.
- **Destructive or outward-facing actions stop the loop and ask**: deleting a
  repository, force-pushing, changing visibility, rotating anything, or any
  action whose blast radius exceeds one branch.

---

## PHASE A — DERIVE THE STATE. TRUST NOTHING WRITTEN DOWN.

Every number in any handoff document rots. Re-derive:

```bash
git fetch origin && git log --oneline -1 origin/main
git status --short && git worktree list && git branch -a
gh issue list --state open
gh pr list
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
curl -s <status-endpoint> | python3 -m json.tool     # free probes only
```

Confirm production matches `origin/main`. Confirm no other session holds a
worktree you are about to touch. **If a concurrent session is active, say so and
stay out of its branch and its files.**

## PHASE B — FIND THE GAPS BY EXECUTING

Fan out **3 read-only researchers**, one per area. Each must:

- Run the code, the gates and the checks. Reading is not evidence.
- **Test each candidate item's stated premise** and report REFUTED loudly if the
  defect is not present at `origin/main` today.
- Report severity concretely: does it block merges, cost money, hide defects
  silently, or is it cosmetic?
- Estimate size: files touched, does it need a test, does it touch a gate.
- **Check whether a gate that looks green actually measured anything.** Disable
  its detector in your own copy and see whether the output changes. A gate whose
  floor counts input rather than detections will pass over a dead detector.

**Every reviewer prompt carries this, in capitals: DO NOT WRITE, EDIT, REVERT,
STASH, `sed -i`, `git checkout`, OR PUSH ANYTHING. TAKE YOUR OWN COPY WITH
`git archive HEAD | tar -x -C <dir>` IF YOU MUST MUTATE, AND DELETE IT BY NAME.**

## PHASE C — PRIORITISE

Rank by this order, and write one line justifying the top item:

1. **Anything red in a required check**, or anything blocking merges for everyone.
2. **Money, auth, safety, data loss** — including anything currently exposed.
3. **A bounded, finishable defect** with a clear test — prefer these over
   open-ended measurement work.
4. **Advisory-gate and instrument work** — real, but blocks nothing.
5. **Anything needing a human decision** — do not start it. Present it.

Reject an item if: its premise is refuted, its test cannot be made to fail
without the fix, or finishing it requires a decision only the human can make.

## PHASE D — EXECUTE ONE PACKAGE

Main orchestrator spawns **one sub-orchestrator** for the top item. That
sub-orchestrator runs this and nothing else:

**D1. Confirm the premise itself** — one command, pasted. If refuted, stop and
hand back immediately. Do not repair the premise silently and continue.

**D2. Plan — fan out 3 read-only planners.** Different jobs, not different job
titles: one enumerates approaches, one enumerates failure modes, one designs the
test that would prove the fix. For money, auth or safety work, enumerate the
known failure modes on one page *before* any code exists.

**D3. Build — EXACTLY ONE WRITER.** Never fan out for building; subagents share
one working tree. Work in a dedicated worktree, merging the base branch in
first. Write the test first, watch it fail, then make it pass.

**D4. Prove the test bites.** `cp` the source aside, mutate it, run the test,
restore from the copy, `diff -q` to confirm the restore. Capture the verbatim
failure output. **A test that passes when the feature is absent is worthless.**

**D5. Review — fan out 3 lens-diverse reviewers**, chosen from what the change
touches. Not five similar ones; redundancy without diversity buys nothing.
Always include:
   - **Execution** — runs everything, re-derives every number, and is told
     explicitly that its job is to run rather than read.
   - **Prose** — for every number, superlative and causal claim in the diff,
     the comments, the commit body and the pull-request description, name the
     command that produces it or mark it UNVERIFIED.
   - **One risk lens** picked from the diff: breaker for money/auth/safety,
     vacuity for gates and workflows, compatibility for schema and stored data,
     rendered-experience for user interface work.

**D6. Fix the findings — then REVIEW THE FIX.** This round is not optional; see
rule 2. Verify each replacement is true before writing it. **Cap at two rounds
total**, then stop and escalate with the open findings listed. If two fixes in a
row add defects, change the approach rather than patching a third time.

**D7. Gates.** Run the project's full required set, serially where they share
coverage data, and commit before any diff-coverage target. Read a gate's job log
and find the number — a green advisory job is not evidence it ran, and a red one
is not evidence it measured.

**D8. Hand back a green pull request and a written report.** The package ends
here. **The sub-orchestrator does not merge.**

## PHASE E — MAIN ORCHESTRATOR VERIFIES AND MERGES

1. **Re-run two claims yourself**, chosen as the highest-consequence pair:
   the mutation proof, and a gate's actual number from its own log.
2. **Put the spec list and the implementation side by side and count.** Green
   measures what was built; it cannot measure what was omitted. One session
   shipped two of eight specified categories and reported it complete.
3. **Vet the merge text before merging.** A close keyword beside an issue number
   closes that issue, and the parser cannot read negation.
4. Squash-merge with an explicit subject and body — a bare squash concatenates
   every intermediate commit body onto the base branch.
5. **Verify the deploy**: the deploy job actually ran (not skipped or
   cancelled — read the job, not the run's rollup), the served build identifier
   equals the merged commit, and the thing you built actually fires.
6. **Close out**: delete the branch local and remote, remove the worktree
   (worktree first, then branch), delete residue **by name**.
7. Then spawn the next sub-orchestrator. **One package at a time.**

## PHASE F — COMPLIANCE AUDIT. THE POINT OF THE WHOLE LOOP.

**Do not audit the protocol's CONTENT. Audit whether it was FOLLOWED.**

Measured 2026-08-25: an independent content audit of the governing skill found
nothing — every rule a reviewer proposed adding was already in it, verbatim. Yet
in the same session **every one of those rules was broken while the skill was
installed and active**: three reviewers read instead of running, a fix round was
budgeted and still shipped four false claims, a frozen backlog was used despite
the rule forbidding it, and in a controlled test the subagent tool was available
and permitted and **0 of 3 runs used it**.

So the gap is never the text. It is the distance between the text and behaviour,
and nobody has ever measured it.

### After every package, spawn ONE auditor

It reads the package's transcript and the diff. It is **not** the agent that did
the work, and it does not self-assess. For each rule below it returns
`FOLLOWED` / `BROKEN` / `NOT APPLICABLE`, plus the evidence — a command, a quoted
line, or the absence of a tool call.

| # | Rule | How the auditor decides |
|---|---|---|
| 1 | One writer during build | Count distinct agents that wrote files |
| 2 | Every lens executed, none only read | Did each reviewer issue tool calls, or only produce prose? |
| 3 | Lenses were diverse, 3 not 5 | Were their JOBS distinct, or the same pass renamed? |
| 4 | The test was proven to bite | Is there a mutation, a captured failure, and a verified restore? |
| 5 | The fix got its own review round | Was there a review AFTER the fix, or did it go straight to gates? |
| 6 | Review capped at two rounds | Count rounds; was escalation used if findings stayed open? |
| 7 | The item's premise was verified first | Is there a command output confirming the defect existed? |
| 8 | Inherited claims marked measured or assumed | Any unmarked number taken from a document? |
| 9 | A gate's number was read from its log | Or was a green tick treated as evidence? |
| 10 | Merge text vetted before merging | Was the close-guard check run? |
| 11 | Sub-orchestrator did not merge | Who pressed the button? |
| 12 | Cleanup deleted residue BY NAME | Any wildcard clean, any `git stash -u`? |
| 13 | Artefacts scrubbed before commit | Any absolute path, username, or session id committed? |
| 14 | Spec list counted against implementation | Was anything specified but silently omitted? |

### Accumulate, then act on the rate

Append one row per package to `docs/analysis/protocol-compliance.md`: the date,
the package, and each rule's verdict. **After five packages, compute the rate per
rule.** A rule that is followed 5/5 is working. A rule below that has exactly
three possible fixes, and choosing between them is the deliverable:

- **Wrong** — the rule does not survive contact with real work. Delete it.
- **Unclear** — it was misread, not ignored. Rewrite it.
- **Right but ignored** — prose has now demonstrably failed to enforce it, so it
  must become mechanical: a gate, a hook, or a check in the harness.

That third branch is the entire value of this exercise. This project's own
doctrine says enforcement belongs in continuous integration and hooks and never
in prose — **this is how you find out which rules have earned one.**

**Report the rate honestly, including when it indicts the protocol itself.** A
protocol whose most distinctive instruction is followed zero times out of three
is decoration, and the measurement saying so is worth more than the protocol.

## WHAT REACHES THE HUMAN — DO NOT BURY ANY OF THIS

The failure mode this prevents: a long autonomous run where everything important
is technically written down somewhere and none of it is read. **Put the block
below at the END of every package report, as its own section, even when every
line is "none".** An empty line is information; a missing line is not.

```
## HUMAN CHECK — package <n>
Merge authority used:      asked / granted this session / NOT MERGED
Compliance rate this run:  <n> followed, <n> broken, <n> n/a   (rules broken: ...)
Rules broken 2+ packages running:  <list, or none>
Premise refuted:           <which item, or none>
Fix introduced a defect:   yes/no  (which round)
Gate green having measured nothing:  <which, or none>
Anything committed that I could not scrub: <list, or none>
Decisions now owed by you: <list, or none>
Blocked / stopped on:      <reason, or nothing>
```

**Four of those lines exist because they were missed in a real session and cost
something. Never omit a line because it seems minor:**

- **"Rules broken 2+ packages running"** is the whole point of Phase F. One
  break is noise; a repeat is a rule that needs to become a gate or be deleted.
  **The agent must not decide which — surface it and let the human choose.**
- **"Gate green having measured nothing"** — a gate was found green over 766
  lines with every detector disabled, output byte-identical. A tick is not
  evidence.
- **"Anything committed that I could not scrub"** — local paths carrying a
  username, a user id, a private project name and a session id reached a public
  repository this way, and the first fix for it did not work.
- **"Fix introduced a defect"** — measured at four in one round and three in the
  next. If this says yes twice running, **stop and change the approach.**

**Report the compliance rate even when it indicts this protocol.** If the
protocol's most distinctive instruction is followed zero times out of three, it
is decoration, and saying so is worth more than the protocol. An agent that
quietly rounds its own compliance up has destroyed the only measurement here.

## STOP THE LOOP AND ASK WHEN

- A required check is red for a reason you did not cause.
- The next step needs money, or sets a cost, safety or guardrail value that only
  real measurement could justify.
- A premise you were handed turns out false and the package depends on it.
- Two consecutive fixes introduce defects.
- The review cap is reached with findings open.
- The item is bigger than it looked. Say so and stop; do not file and continue.
- Anything destructive or outward-facing, per HARD CONSTRAINTS.
- **You notice you have exceeded the number of packages you can hold in
  context.** Write the handoff and stop; do not rush the last one.

## REPORT AFTER EVERY PACKAGE

```
## Done
## Verified myself      (the command, and what it printed)
## Cleanup              (each line confirmed by a command)
## Pending              (nothing tidied away)
## Next action
```

Say explicitly whether work is **pushed**, **merged**, and **running in
production**. Keep what you ran separate from what a subagent reported. If a
gate was green having measured nothing, say that rather than calling it a pass.
If nothing is outstanding, say **"nothing pending — safe to close this session"**.
