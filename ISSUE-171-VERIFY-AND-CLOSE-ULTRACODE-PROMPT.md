# ultracode — verify #171 by EXECUTION, close it if it holds, then proceed

> **HOW TO USE THIS FILE.** Do not paste it into a chat. Paste the block in
> **§7**. One short message from you; one long document for the session.
>
> **Anchor: written against `main` at `343956a`.** That commit is in the past and
> cannot change, so this line is never wrong. See everything since with
> `git log --oneline 343956a..origin/main`. **Every other claim in this file —
> including which commits closed which findings — is something you must
> re-verify, not something you may cite.**

---

## 1. Why this file exists

Issue #171 has had at least two merged fixes referencing it
(`e6c84ea`/`fix(providers)`, `b5f8fca`/`fix(debate)`), plus adjacent issues opened
and closed while working it (#175 closed, #177 closed, #176 partly closed via
#184). **The issue itself is still OPEN, with zero comments on it.** Nobody has
verified, by running anything, that the sum of those merged commits actually
closes what #171 described — and nobody has told the tracker either way.

**Your first job is not to trust that history. Re-derive it.** A pull request
title referencing an issue number is a claim, not proof. The only acceptable
evidence is your own execution against the code as it stands today.

---

## 2. The operator grant

`AGENTS.md` rule 17b normally requires explicit human approval to push, merge, or
close an issue. **For this task, that approval is granted in advance for §3 and
§4 — verifying #171 and, if it holds, closing it and proceeding to the next
ranked item — provided every condition in §5 holds.** If any condition fails,
stop and report instead of proceeding.

The grant does **not** extend to: any paid API call; inventing any threshold,
band, or predicate an issue has explicitly left for the operator (the
minimum-answers-before-debate floor from #171, the Unicode-category decision in
#178, the boilerplate measurement in #180); or closing any issue without the
execution evidence that it is actually closed.

---

## 3. Phase 0 — verify #171 by EXECUTION, not by reading

**Do not read the merged diffs and conclude they look right. Run the thing.**
Reading a fix and believing it works is exactly the failure mode #171 itself
documents — the original defect shipped past every existing test because they
asserted a clean-path outcome, never the cardinality that mattered.

### 3.1 Re-establish ground truth first

```bash
git branch -f main origin/main
git log --oneline 343956a..origin/main
gh issue view 171 --json state,body,comments
gh issue view 176 --json state,body   # partially closed via #184 — confirm which surfaces remain
uv sync --all-extras
make quality && make validate           # must be green BEFORE you draw any conclusion
```

If the suite is not green, that is a premise failure. Stop and report — do not
attribute #171's status to a tree that is already broken for an unrelated reason.

### 3.2 Re-run every numbered finding in the issue, live, against today's code

Read `gh issue view 171` in full — it has 8 numbered findings, a 5-point rule, and
a 3-rung fix ladder. For **each of the 8 findings**, do not ask "does this look
fixed" — ask **"can I still reproduce it"**, and answer with a command and its
output.

At minimum, reproduce the original fault-injection experiment the issue itself
used (patch the provider seam so exactly one slot fails; no network, no paid
call) and check, by execution:

1. Does the failing slot get reported as **missing**, or does a fabricated answer
   still appear with status `completed`?
2. Do debate and synthesis receive only the answers that actually arrived, with a
   correct denominator — or does the fabricated slot still get counted?
3. Does a simulated source still register as primary (`is_fallback=False`) and
   inflate source coverage — or is that closed?
4. Does the debate round now carry its own provenance (live vs. fallback), per
   `b5f8fca` — assert it structurally, not by reading the diff.
5. Is there still no minimum-answer floor before a debate runs? **Confirm this
   is STILL true and STILL unenforced** — it must remain an open operator
   question, not something silently invented by any of the merged commits. If
   you find a floor was invented anywhere, that is itself a defect: report it,
   do not treat it as done.
6. Run the actual test suite the merged PRs added — do not just check it
   exists. Confirm it currently passes, then **prove it still bites**: `cp` the
   relevant test file aside, revert the source fix by hand (or check out the
   pre-fix blob with `git show <pre-fix-sha>:<path>`, never `git checkout` on
   your working tree), confirm the test goes RED, restore from your copy.
7. Check whether the user-facing denominator-reporting rule shipped ("coverage
   100% (4 of 4 answers, 0 excluded)", never a bare "100%") — grep the UI and the
   golden fixture, then **drive it**: render the real UI against a fault-injected
   run and read the rendered text yourself.
8. Confirm rung 3 (the required provenance field, exhaustive `assert_never`
   switching, the provenance set derived from the enum) — is it fully shipped,
   partially shipped, or not shipped? Say which, with evidence. It is fine if
   only rungs 1–2 landed; it is not fine to report rung 3 as done without
   checking mypy actually fails on an unhandled provenance kind.

### 3.3 Check the adjacent issues honestly

`#175` and `#177` show as closed, and `#176` was reduced by `#184`. For each:
confirm by execution that the fix that closed it is present and working, and
check `#176`'s remaining surfaces (if any) — the last recorded state was
"three remaining surfaces" fixed by `#184`; verify none is left, or name exactly
which is.

### 3.4 Verdict

Write a table: **finding → still real? → command run → output → verdict.**
Then one paragraph: does the sum of merged work close what #171 described, in
full, partially, or not at all? **A partial close is a legitimate, useful
answer — say exactly which rung and which findings remain.**

---

## 4. Phase 1 — act on the verdict

**If #171 is NOT fully resolved:** do not close it. Post a comment on the issue
stating precisely what you verified, with evidence, what remains, and continue
building the remainder — following the same discipline as
`ISSUE-171-ULTRACODE-PROMPT.md` (still at the repo root if present; re-derive its
rules yourself if it is gone): plan, build serially with one tree-writer, two
review lenses (one executing, one a breaker) capped at two rounds, all six
required merge gates, deploy-verified three ways, and do not invent the
open floor. Then re-run Phase 0 against your own new work before closing anything.

**If #171 IS fully resolved:** post a comment on the issue naming every finding,
the commit that closed it, and the command that proved it — then close it:

```bash
gh issue close 171 --comment "<the verified evidence, not a summary>"
```

**Either way, do not skip the comment.** An issue closed with no evidence is the
same failure this whole file exists to prevent, just aimed at the tracker instead
of the code.

---

## 5. Conditions that must ALL hold before you close anything or merge anything

1. Every claim in §3 is backed by a command and its pasted output — no verdict
   from reading alone.
2. `make quality && make validate` green, and all six required merge-gate
   contexts re-derived and green on the real runner:
   ```bash
   gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
   ```
3. No threshold, band, or predicate was invented anywhere — including by a
   commit you are verifying, not just one you might write.
4. If you build anything in Phase 1, it passed two review rounds (one executing
   lens, one breaker), with the second round on the fix diff only, then stopped.
5. Any deploy is verified three ways: the Deploy **job** concluded `success`
   (resolve the newest run by `createdAt`, not the run rollup);
   `/status.build_sha` equals the merged SHA; prod `/ready` reports live.
6. Hermetic and $0 throughout — no paid API calls, no funded key, no live
   provider run, at any point.

If any condition fails, stop and report rather than proceeding.

---

## 6. Phase 2 — then move down the ranked backlog, re-verified

**Do not trust the ranking below — it is what was recorded on 2026-07-30/31 and
is already a day old.** Re-run selection:

```bash
gh issue list --state open --limit 300 --json number,title,labels,updatedAt
```

Recorded ranking, to re-verify rather than inherit:

1. **#182** — the mutation gate. Measured intermittently healthy (100% in one
   run, cancelled-having-scored-nothing in another) — confirm this is still true
   before treating it as "never works". If a real fix requires a threshold or
   scope change, verify the measured cost driver first (function size vs. diff
   size) rather than guessing.
2. **#178, #180 — OPERATOR-GATED. Do not pick a predicate or a measurement rule
   for these.** Bring the decision to the operator per the format in
   `AGENTS.md` (state it in one sentence, name the options, show a genuine
   worked example, list the trade-offs) — do not build a guess and call it done.
3. Anything newly filed since `343956a` that outranks these — check by severity
   and exposure, not by recency.

For whatever you pick, apply the full discipline from §4: plan, verify the defect
reproduces before you build, build with one tree-writer, two capped review
rounds, all required gates, deploy-verified three ways, hermetic and $0.

---

## 7. Phase 3 — report and stop

Write `ISSUE-171-VERIFY-AND-CLOSE-RESULT.md`:

1. The full verdict table from §3.4.
2. What you closed (with the comment you posted) or what remains open (with the
   comment you posted) and why.
3. Whatever you built in Phase 1 or Phase 2 — RED→GREEN evidence, bite proofs,
   review findings (real and refuted), all six gate results, deploy verification.
4. The operator queue — every threshold/predicate left undecided, named as a
   question with options, not an answer.
5. What is genuinely unknown, distinguishing settled-by-construction-but-never-
   measured from actually measured.
6. **The next action item**, ranked by what can hurt, with one line on why it
   outranks the alternatives — derived from a fresh `gh issue list`, not from
   this document.

Then **stop.** Do not start the next item without being asked.

---

## 8. Standing rules — apply all of them

1. **Verify by executing, never by reading.** This entire file exists because
   that rule was at risk of being skipped for an issue-closure decision, not
   just a code change — the rule applies there too.
2. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log and find the number.
3. **When you CORRECT a false claim (including "issue #171 is fixed"), verify
   the REPLACEMENT before writing it.**
4. **Assert cardinality, not clean-path outcomes**, for anything touching a
   trust number, a count, or a billing figure.
5. **A negative check needs a positive partner.**
6. **Prove every test bites by mutation** — `cp` aside, mutate or check out the
   pre-fix blob, confirm RED, restore from the copy. **Never `git checkout` your
   working tree.**
7. **Never fabricate a number, label, or threshold.** Absent means `—`, never a
   placeholder. This applies to floors, bands, and Unicode category lists as
   much as to cost figures.
8. **Fan out for review, never for building.** One tree-writer. Two lenses, not
   five, one of which executes. Two rounds, the second on the fix diff only,
   then stop.
9. **Line numbers are locators, not addresses** — confirm the quoted text; the
   issue's evidence was captured at an older commit.
10. **Close more than you open.** If something is bigger than it looked, say so
    and stop rather than filing and continuing.
11. **Plain English. No jargon, no invented shorthand.**

---

## 9. Paste this into a fresh chat

```
ultracode

FIRST: verify issue #171 is actually resolved by EXECUTING every check named in
ISSUE-171-VERIFY-AND-CLOSE-ULTRACODE-PROMPT.md section 3 — not by reading the
merged pull requests and concluding they look right. For every one of the 8
findings in the issue, reproduce it live against today's code (fault-injection,
no network, no paid call) and report a command plus its actual output. Read
AGENTS.md first — its operating rules bind.

If, and only if, the evidence shows #171 is fully resolved: post a comment on the
issue naming every finding, the commit that closed it, and the proof, then close
it with gh issue close. If it is only partially resolved, say exactly what
remains, post that as a comment, and finish the remaining work yourself following
the same discipline (plan, build with one tree-writer, two capped review rounds,
all required gates, deploy-verified three ways) before closing anything.

Do not invent the minimum-answers-before-debate floor, or any other threshold an
issue has left for the operator. Leave those in the operator queue.

Once #171 is honestly closed or honestly left open with accurate state, move to
the next ranked open item per section 6 — re-derive the ranking yourself from a
fresh gh issue list, do not trust yesterday's ordering. Apply the same
discipline: verify the defect reproduces before building, one tree-writer, two
review rounds (one lens must execute, one is a breaker), all six required merge
gates re-derived from gh api, deploy verified three ways, hermetic and $0
throughout.

Write ISSUE-171-VERIFY-AND-CLOSE-RESULT.md, tell me the next action item with one
line on why it outranks the alternatives, and stop.
```
