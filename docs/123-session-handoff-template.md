# Session handoff — the template, and why it is shaped this way

Copy `## THE TEMPLATE` below into a new file for each handoff. Delete it on merge.

---

## Why this exists

Handoff between work sessions was, until now, a long prose document written at the
end of a session and read at the start of the next. **Thirty-two** of them
accumulated in this repository's root, and they stay there — 19 are referenced by
tracked files outside the set, and moving them out broke 18 tests on 2026-07-30. Every one carried
facts that expired — commit hashes, test counts, line numbers — and a later session
that trusted them was wrong. Measured
on 2026-07-30: three line-number references in the previous handoff were stale, and
one premise it stated as fact ("that banner is redundant") was false in a way that
would have caused a needed warning to be deleted.

**Handoff is close to a solved problem outside software, and the evidence is much
better than anything in our field.** The structure below is adapted from **I-PASS**
(Starmer et al., *New England Journal of Medicine* 2014;371(19):1803–12), a
prospective study across 9 sites and **10,740 admissions**: medical errors fell
**23%**, preventable adverse events **30%**, and handoff took no longer (2.4 → 2.5
minutes, not significant). Its negative control held — *non*-preventable adverse
events did not move (p=0.79) — which is why the result is credible rather than an
artefact of people paying more attention.

Two caveats, stated so nobody inherits them as more than they are. I-PASS was a
**bundle** (mnemonic + training + faculty development), not a template alone; and
it is medicine, not software. What transfers is the *shape*, and the shape is
independently corroborated: UK HSE shift-handover guidance for high-hazard
industry arrives at the same elements from accident inquiries (Piper Alpha,
Sellafield), and an observational study of NASA, nuclear, rail and ambulance
handoffs (Patterson et al., *Int J Qual Health Care* 2004;16(2):125–32) found 19 of
21 strategies in use across domains. That last one measured **no** error reduction —
it is a catalogue, not evidence.

---

## The three rules that keep it from rotting

**1. Never write a derived fact into prose. Write the command that produces it.**
A derived fact is anything a machine can compute: a commit hash, a test count, a
line number, an issue's status, what is deployed. Every one of them starts decaying
the moment it is typed. Write `run: make next` instead of `main is at abc1234`.

The honest basis: it is **not** established that derived facts decay faster than
rationale — nobody has measured that, and assuming it would be the same
narrow-sample error this repository keeps paying for. What *is* established is that
derived facts are the only class of staleness anyone can detect mechanically, and
that it is common: **more than 25% of the top 1,000 GitHub projects contain at least
one outdated code-element reference** — a documentation reference to code that no
longer exists (Tan, Wagner & Treude, *Empirical Software Engineering* 28, 2023).
Rationale may well decay too; it just fails quietly, by going irrelevant rather than
wrong, which is arguably worse and definitely harder to catch.

**2. The receiver confirms before editing.** This is I-PASS's *Synthesis by
receiver* and HSE's *cross-checking by incoming personnel* — the one element both
arrived at independently, and the one with **no equivalent in any software handoff
practice found**. Every software handoff we looked at is write-only. A handoff is
not complete when the sender finishes writing; it is complete when the receiver
re-measures and says what they found.

**3. It is ephemeral by construction.** A handoff's purpose ends when the next
session ends. It lives in the working tree, never in the repository root, and it is
deleted in the pull request that consumes it. Anything worth keeping longer is not
a handoff — it is an issue (state), a decision record (rationale), or a gate
(enforcement).

---

## THE TEMPLATE

```markdown
# Handoff — <work package name>

Written <date>. DELETE THIS FILE in the pull request that consumes it.

## 1. State — is anything on fire?

Do not write values here. Write the command and the expected shape, so the
receiver produces the value themselves.

| What | Command | Expected |
|---|---|---|
| main's tip | `git log -1 --format=%H` | anything; do not assume the one I saw |
| what is deployed | `curl -s <status-url>` | `build_sha` should equal main's tip |
| the deploy JOB ran | `gh run list --workflow=... --branch main` | conclusion `success` — NOT `skipped`/`cancelled`, and NOT the run's rollup |
| tests | `<the command>` | <count as of writing — if it differs, find out why BEFORE writing code> |
| open issues | `<the command>` | <count as of writing> |

**Anything actively broken right now:** <one line, or "nothing">

## 2. Summary — what this is, in five sentences

What the work package is, why it exists, and what "done" means for it.
No history. No narration of how we got here.

## 3. Action list — what to do, in order

Ranked by exposure (what can hurt), not by readiness (what is easy to start).

| # | Do this | Why it outranks the next one |
|---|---|---|
| 1 | | |
| 2 | | |

**One line per item on why it outranks the next.** If that line cannot be written
honestly, the ranking is wrong. This is the check that would have caught the
2026-07-30 mistake of building the lower-value item because it was already started.

## 4. What might go wrong, and what NOT to do

The element most often missing from a software handoff, and the one I-PASS makes
mandatory ("situation awareness and contingency planning").

- **Traps in this area:** <things that look right and are not>
- **Do NOT do:** <named actions that are wrong, with the reason>
- **Known-unknown:** <what nobody has measured yet, and the command that would settle it>
- **Premises I am asserting that could be wrong:** <list them. If one turns out
  false, STOP and say so — do not repair it silently.>

## 5. Synthesis by receiver — fill this in BEFORE editing anything

The incoming session completes this section. The handoff is not done until it is.

- [ ] Re-ran every command in §1. Numbers that differed: <list, or "none">
- [ ] Checked each premise in §4. Refuted: <list, or "none">
- [ ] I am starting item <N> because <one line on why it outranks the top of the list>
- [ ] Anything in §1–4 I believe is wrong: <list, or "none">
```

---

## What this template deliberately does not do

- **It does not carry the project's rules.** Those live in `AGENTS.md` (influence)
  and in CI (enforcement). A handoff that restates them is duplication, and
  duplication is what rots. DRY was written to cover documentation, explicitly:
  *"Every piece of knowledge must have a single, unambiguous, authoritative
  representation within a system"* — Hunt & Thomas, *The Pragmatic Programmer*, and
  they confirmed on the record that documentation was in scope.
- **It does not carry status.** Status lives in the issue tracker. Google SRE
  practice makes the same split: live state belongs in a dashboard that queries it;
  prose is for the procedure and the judgement a query cannot produce.
- **It does not claim a freshness date makes it true.** Docs-as-code and review
  dates enforce *attention*, not *accuracy* — Google's own documentation chapter
  does not claim more than that. A reviewed, recently-dated document can be
  entirely false; this one was, three times, on 2026-07-30.
