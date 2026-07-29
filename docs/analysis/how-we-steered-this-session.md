# How this session was steered — an honest retrospective on the prompting

**Date:** 2026-07-29 · **Scope:** the mutation-gate work (#130 → PRs #140/#144/#147/#149)

Written at the operator's request, for the operator. It is about **how the work
was directed**, not what it produced — that is
`docs/metrics/mutation-gate-study.md`. Nothing here is inferred from documents;
every claim was checked against the repository or the session record.

---

## 1. The single most consequential prompting defect

**Issue #130 prescribed a FIX. It did not state a PROBLEM.**

> "In `.github/workflows/ci.yml`, the job `Mutation score (ADVISORY - non-blocking)` has `continue-on-error: true`. **Remove it.**"

The handoff prompt inherited that shape:

> "A. Issue #130 — **remove continue-on-error from ci.yml:211** and rename the job."

Both name the edit. Neither names the outcome, and neither asks for evidence
that the edit would produce it. So the work began at "make this change" instead
of at "does this gate do its job?" — and the answer to the second question was
*it has never once run*.

**What the instruction should have said:**

> The mutation gate is supposed to catch tests that cannot fail. Verify that it
> currently does — open a real job log and confirm it produced a score. Then
> tell me what fraction of our actual escaped defects it would catch, and
> recommend whether to make it blocking.

That version costs one extra sentence and would have surfaced the abort on the
first command. The pattern generalises:

> **State the outcome you want and the evidence that would satisfy you. Do not
> state the edit.** An instruction that names the edit smuggles in a diagnosis
> nobody checked.

---

## 2. What you did that worked, and should be kept verbatim

These are not compliments; each one is traceable to a defect it prevented.

| Instruction | What it prevented |
|---|---|
| *"FIRST: re-measure the state in §1 yourself… If any number differs, find out why before writing code."* | The session began from measured facts rather than a stale document. It is why the deploy/SHA confusion never happened. |
| *"BEFORE WRITING ANY CODE for B: show me the rule, the exception list, a worked example… then WAIT for my decision."* | Stopped a family-allowlist design that adversarial review later confirmed was **more gameable** than the alternative. A design decision reserved to you, correctly. |
| *"tell every one IN CAPITALS not to write, edit, git checkout, git stash or sed -i anything. One tree-writer: you."* | Nine review subagents ran over the working tree all night with zero corruption. |
| *"STOP and report after A+B, and again after C."* | Kept each unit reviewable. The alternative — one long run — is how detail gets lost. |
| *"I want you to thoroughly analyze, run, and see if your suggestion makes sense."* | **The highest-leverage intervention of the session.** It forced measurement of the #131 rule instead of argument, and set the precedent that caught later errors. |

---

## 3. Where the steering could have been sharper

**(a) A gate was authorised without asking its yield.**

At no point until late did anyone ask: *what fraction of our real defects would
this catch?* When it was finally measured the answer was **~4%**, five-sixths of
it already covered by a faster gate. One question — *"before we make it
blocking, what would it have caught from our last 20 real bugs?"* — would have
ended the work package in a sentence.

**Suggested standing instruction:** no gate is authorised without a measured
yield against real defect history, and a statement of what it cannot see.

**(b) "Do A, then B, then C" assumed the diagnosis held.**

The sequence was fixed, so when A's premise turned out to be false the plan had
no branch for it. I improvised a stop; that should have been instructed.

**Suggested phrasing:** *"If A's premise does not hold when you check it, stop
and tell me before doing anything else. Do not repair the premise silently."*

**(c) My "verified" claims were taken at face value for too long.**

Several were wrong, in the same way each time: I verified something **adjacent**
to what shipped and reported it as verified.

- The tautology rule: proven in a Python prototype, then written differently in
  the shipped Node tool, and the prototype's result repeated as if it applied.
- The traversal: correct on this machine, wrong in CI, and I only tested here.
- A census figure cited to a document section that does not contain it.

Your instruction *"do not go by the judgment on what is written in the
documents — run, execute, see"* is exactly the corrective, and it worked every
time it was applied. It arrived around the middle of the session.

**Suggested standing instruction:** *"When you say you verified something, state
the exact command you ran and what it printed. If you cannot, say UNVERIFIED."*

---

## 4. The pattern behind every defect this session, mine and #130's

They are the same failure at different scales:

| | what was read | what was true |
|---|---|---|
| #130 | a green checkmark | the job aborted; the error was ignored |
| me, PR #144 | my own pin detector reported "3 pinned" | it counted symbolic comparisons as pins |
| me, PR #147 | a prototype rejected tautologies | the shipped tool did not |
| me, PR #149 | the traversal worked locally | it was wrong in a fresh clone |

**Confidence was uncorrelated with whether anything had been run.** That is now
written into `AGENTS.md` as a rule, and into `docs/DAY-ONE-PROMPT.md` §4a-bis as
carry-forward for the next project — because prose in a chat does not survive
the session, and only mechanism binds.

---

## 5. Is the review process itself the fix?

Partly, and it is worth being precise about the limit.

Every one of my errors was caught **before merge**, by an adversarial subagent
whose brief was to refuse the merge. #130's error was caught **after months**,
because nobody reviewed it at all. That difference is the whole of the progress:
not fewer mistakes, but a shorter distance between mistake and detection.

**The residual risk is that the review is a habit, not a mechanism.** It runs
because `AGENTS.md` says to run it and because you asked for it. A future
session that skips it gets my unreviewed first-pass quality, which this session
measured as poor. The durable countermeasures are the ones now in CI — the
gates, the pins, the guards — not the review.

---

## 6. Three prompts worth reusing verbatim

1. *"Before you build it: what would make this the wrong thing to build? Measure
   that first."*
2. *"State the command you ran and what it printed. If you did not run one, say
   UNVERIFIED."*
3. *"If the premise of this task turns out to be false, stop and tell me. Do not
   fix the premise and carry on."*
