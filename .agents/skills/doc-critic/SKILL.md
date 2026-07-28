---
name: doc-critic
description: Critically review the documentation a doc-suite skill produced — a learning track, architecture doc, runbook, FAQ, usage guide, or onboarding — before it is published, catching what a deterministic verifier cannot judge — cross-module contradictions, analogy and term collisions, code-vs-doc mismatches, undefined terms, simplifications that became false, honesty drift, and broken cross-references. It runs verify.py first, then a blind multi-axis agent critique (whole-document consistency, code-grounded correctness, the beginner floor, an adversarial adjudicator), writes a severity-ranked review register, and gates publishing on unresolved blockers. Use it after generating or editing docs, or to review, critique, QA, or harden the docs before publishing. It is the human-judgement layer on top of verify.py and an authoring skill's same-context critic loop, reviews the docs a skill produces rather than the skills themselves, and does not publish (use publish-mirror).
---

# Documentation Critic

Version: 0.1.0 · see `CHANGELOG.md`.

The independent **critic gate** for the documentation suite. After an authoring skill writes its
pages and the deterministic verifier (`scripts/verify.py`) passes, this skill runs a **blind,
multi-axis critical review** over what was produced, finds the defects a regex/readability verifier
cannot — contradictions across modules, analogies that teach the wrong shape, claims the code does
not support — and gates publishing on the serious ones.

This skill owns the *review method and the orchestration*. The shared writing standard it judges
against lives in `references/house-style.md` — **read it first, every time.** The project's facts,
audience targets, and scope live in the project profile (`docs/project-profile.md`; how to find or
create it is `references/house-style.md` Section 1).

**It is judgement, not a generator.** `verify.py` enforces the checkable rules and stays the hard
gate; this skill produces a *review register a human approves*. It never silently edits the docs.

---

## Before you start: what this needs, when to run it, where it fits

### What this skill needs (the inputs)
- **The produced documents** to review (e.g. `docs/learning/` for a learning track, plus its
  `glossary.md`).
- **The filled project profile** (`docs/project-profile.md`) — scope, audience, and the
  `grade_target_*` / `scope_*` keys the verifier reads.
- **The project source it teaches from** — the repository, the decision records (ADRs), and the
  commands the docs claim ("built / tested / measured", a CLI invocation). The correctness axis
  **reads and runs these**; without access it can only mark such claims unverified.
- **The registers**, if the authoring skill locked them (the analogy / term / honesty registers in
  `house-style.md` Section 5a). Their absence is itself a finding.

### When to run it in the build (the cadence)
- **Not per commit.** The per-change gate is `verify.py` in the CI hook, not this skill.
- **Per batch, and as a hard gate before publishing.** Run it after a batch of modules clears the
  authoring loop and the verifier, and again — in full — before the set goes public. A learning
  track's worst failures span modules, so a batch-and-gate cadence catches a propagating error
  (a wrong analogy, a reused term) before it reaches the next module.

### Where this fits among the documentation skills
The chain is **author → `verify.py` (deterministic) → doc-critic (this skill) → publish-mirror.**
Tell it apart from its neighbours:
- It is **not** `scripts/verify.py`. That enforces the *checkable* rules (banned words, internal-name
  leaks, reading grade, the licence footer, staleness). This is the *judgement* layer on top — the
  part `verify.py`'s own header calls "a human/critic judgement." Run the verifier first; this skill
  assumes it already passed.
- It is **not** an authoring skill's inline critic loop (e.g. learning-track Step 6). That loop runs
  *during* authoring, in one context, as sequential same-model critics — strong for drafting, but
  structurally blind to cross-module contradictions and to claims it cannot independently check. This
  skill runs **afterward, blind, across the whole set**, with a code-grounded axis and an adversarial
  adjudicator. The two are complementary: the loop prevents, this gate catches.
- It is **not** `per-skill-review-prompt.md`. That improves *the skills themselves* (the `SKILL.md`
  files). This reviews *the documents the skills produce*.
- It is **not** `publish-mirror`. That publishes the verified, reviewed source; it never reviews.

---

## Workflow

### 1. Ground yourself, and load the review profile
- Read `references/house-style.md` and the project profile. Read
  `references/review-playbook.md` — the method this skill executes.
- Load the **review profile** for the doc type from `references/review-profiles.md`. The
  **learning-track** profile is implemented; other doc types are stubs to fill as needed. The profile
  names the error classes to weight, the axes to run, and the stakes tier.

### 2. Run the deterministic gate first
Run the verifier over the target docs and fix any FAIL before spending the critique on them:
```bash
python3 scripts/verify.py docs/learning --format md --skill learning-track --profile docs/project-profile.md --license LICENSE
```
A document that leaks an internal name or fails the licence footer is not ready for the critic.

### 3. Confirm the registers (the shift-left check)
Confirm the authoring skill locked the analogy / term / honesty registers (`house-style.md`
Section 5a). If they are missing, that is the **first finding** — a track written without them is the
one most prone to the propagating errors below.

### 4. Run the blind multi-axis critique
Spawn the review axes from `references/reviewer-prompts.md`, **each in its own fresh context, blind**
— give each the docs + the **neutralized writing contract** (the shared brief in
`references/reviewer-prompts.md`, a paraphrase of the rules — not the house-style file itself), never
your own conclusions or a prior reviewer's findings (anchoring defeats independence). Size the crew
to the stakes tier (the profile says how many):
1. **Whole-document consistency** (the centerpiece — run it on the *whole set at once*): internal
   contradictions, term collisions, analogy drift, broken cross-references, honesty-posture drift.
2. **Code-grounded correctness** — *verify, don't recall*: recompute any stated figure, read the
   source/ADRs, run the commands the docs claim, and check each analogy for technical fidelity. Tag
   each claim VERIFIED / ASSERTED / NEEDS-CODE-CHECK.
3. **Beginner floor** — every term defined on first use; every self-check answerable from the prose;
   every optional depth box skippable without leaving a hole.
4. **Adversarial adjudicator** (runs last, sees 1–3): what did they all miss, where are they wrong,
   which agreement is just shared bias? It reconciles into one ranked list.

### 5. For a flagship / public gate: the different-vendor pass
The strongest decorrelation — a different vendor's model — **is not automatable from inside this
skill.** For a public or high-stakes gate, emit the ready-to-paste blind prompt from `references/reviewer-prompts.md`
(the different-vendor template, filled from the profile), hand it to the owner, and **pause** until
its findings come back. Then verify any NEEDS-CODE-CHECK item it raises against the source.

### 6. Write the review register (repo-first)
Merge every axis into one **severity-ranked review register** written to the repo (e.g.
`docs/<set>/REVIEW.md`). Give each finding a **stable id** (`B1`, `M1`, `N1`, …) so the gate is
mechanically checkable, then: severity (BLOCKER / MAJOR / MINOR / NIT), an exact quote + location,
which axis raised it, a doc-vs-code split, status (open / resolved), and a concrete fix. This is the
single source the owner acts on — the same repo-first discipline the rest of the suite uses.
**Route systemic findings outward.** If a finding is a defect *class* likely to recur in other doc
types (a wrong analogy pattern, a systemic honesty-marker gap, a missing glossary convention), also
append it to the suite's `CROSS-SKILL-FINDINGS.md` so the next doc type inherits it — the suite's
established two-way carry-over log.

### 7. Gate, then re-verify
- **Gate:** unresolved **BLOCKERs** (a reader left believing something false, or an internal
  self-contradiction) block publishing. MAJOR/MINOR/NIT are recommended fixes.
- After the owner applies fixes in one cycle, **re-run `verify.py` and confirm every BLOCKER id is
  marked resolved** (the stable ids make "are all blockers closed?" answerable without re-reading the
  prose) before handing off to `publish-mirror`.

---

## The error taxonomy (what every axis hunts)
Weighted by the profile; these are the classes that recur in suite output:
1. **Internal contradictions** — a claim made on one page, disowned on another.
2. **Analogy-shape errors + term collisions** — an analogy teaching the wrong shape; one word, two
   meanings across pages.
3. **Code-vs-doc mismatches** — "the tool does X / built / tested / measured" the source does not support.
4. **Term-definition gaps + glossary incompleteness** — a term used before it is defined; the
   glossary not actually the single reference.
5. **Simplification-gone-false** — a nuance flattened into something untrue.
6. **Honesty-posture drift** — built / `[designed, not yet built]` / measured-vs-illustrative
   inconsistent across pages.
7. **Broken forward/cross-references** — a promise a later page never keeps (the *semantic* half;
   `verify.py` already catches a link to a missing file — this axis catches the unkept promise).

Five of these are cross-page — which is why the whole-document axis is the centerpiece, not one of N.

## Output structure
```
docs/<set>/REVIEW.md          # the severity-ranked register (repo-first, the owner acts on this)
```
The method, the axis prompts, and the per-doc-type profiles ship as references (below).

## Quality bar (self-check before presenting)
- The verifier passed before the critique ran (no FAIL).
- Each axis ran **blind** and in its **own context**; none saw another's findings before the adjudicator.
- The whole-document axis ran over the **entire set at once**, not module-by-module.
- Every finding has a severity, an exact location, the axis that raised it, and a concrete fix.
- BLOCKERs are called out distinctly and gate publishing; code claims are tagged VERIFIED /
  ASSERTED / NEEDS-CODE-CHECK, never assumed.
- For a public gate, the different-vendor prompt was emitted (the honest limit is stated, not hidden).

## Honest limitations
- **Non-deterministic.** The critique is agent judgement; `verify.py` stays the hard, repeatable
  gate, and this skill outputs a register a human approves — it does not auto-edit.
- **The different-vendor axis is not automatable here** (Step 5 hands off a prompt).
- **Independence needs the harness.** The blind, each-axis-in-its-own-context decorrelation this
  method depends on (Step 4) is real only in an **isolated-subagent** run. In a plain single chat the
  axes run sequentially in one context and lose most of their independence — treat such a run as a
  **structured self-review, not an independent gate**, and lean harder on the different-vendor pass
  (Step 5), whose decorrelation is from different model weights rather than from context isolation.
- **Skills do not auto-chain.** This runs when **doc-critic's own** description matches a review
  request, or when an authoring skill's end-of-workflow body handoff points to it. An authoring
  skill's *description* does not (and cannot) trigger this skill — only doc-critic's own does.

## References
- `references/house-style.md` — the shared writing standard this skill judges against (read first).
- `references/review-playbook.md` — the review method: the phases, the axes, the taxonomy, the rules.
- `references/reviewer-prompts.md` — the blind per-axis prompt templates (and the different-vendor template).
- `references/review-profiles.md` — per-doc-type review profiles (learning-track implemented; others stub).
- `references/licensing-and-credits.md` — the licensing/credits standard the docs must satisfy.
- `scripts/verify.py` — the deterministic gate; run it in Step 2 before the critique.
- `assets/project-profile.md` — copy into the repo and fill once per project.

## Versioning
Versioned like code. Record every change in `CHANGELOG.md` (Keep a Changelog format) and bump the
header version. The review method is itself reviewable — when the suite learns a new failure class,
add it to the taxonomy and a profile, and changelog it.

---

# Factory skill contract

> **Repo-added section.** Everything above is the upstream bundle. This block is the contract
> `scripts/validate_quality_contracts.py` requires of every `.agents/skills/*/SKILL.md`, written
> against what this skill actually does. Because an upstream refresh replaces this folder wholesale,
> **re-apply this block after every update** — `make validate` goes red without it. Provenance is
> recorded in `configs/external-skill-registry.json`.

## When to use

- A batch of documents has cleared its authoring loop **and** `scripts/verify.py`, and needs the
  judgement layer before anyone reads it as truth.
- Immediately before publishing a document set — this is the hard gate on that step.
- The ask is to review, critique, QA, or harden docs; or to find contradictions, unsupported claims,
  or honesty drift across a set.
- After edits that span modules, where a wrong analogy or a reused term can propagate.

## When not to use

- **Per commit.** The per-change gate is `verify.py` in the CI hook.
- **Before the verifier passes.** A document that leaks an internal name or fails the licence footer
  is not ready for a critique; fix the FAILs first.
- **To review the skills themselves** — that is `per-skill-review-prompt.md`. This reviews the
  *documents skills produce*.
- **To publish** — that is `publish-mirror`.
- **As a substitute for the authoring skill's inline critic loop.** That loop *prevents* during
  drafting; this gate *catches* afterwards. Both run.
- **In a plain single chat when an independent gate is what is needed.** Without isolated subagents
  the axes lose their independence — see *Honest limitations*.

## Inputs

- The produced document set to review (for example `docs/learning/` plus its `glossary.md`).
- `docs/project-profile.md`, filled — scope, audience, and the `grade_target_*` / `scope_*` keys.
- **The project source the docs teach from** — repository, ADRs, and the commands the docs claim.
  The correctness axis reads and runs these; without access it can only mark claims unverified.
- The locked analogy / term / honesty registers (`house-style.md` §5a). Their absence is itself the
  first finding.
- `references/review-playbook.md`, `reviewer-prompts.md`, `review-profiles.md`.

## Owned outputs

- `docs/<set>/REVIEW.md` — the severity-ranked review register, every finding carrying a **stable id**
  (`B1`, `M1`, `N1`, …), a severity (BLOCKER / MAJOR / MINOR / NIT), an exact quote and location, the
  axis that raised it, a doc-vs-code split, a status, and a concrete fix.
- Appended entries in the suite's `CROSS-SKILL-FINDINGS.md` for findings that are a defect *class*
  likely to recur in another doc type.
- For a flagship/public gate: the emitted, ready-to-paste different-vendor prompt.

## Allowed tools

- Read the documents under review, the project profile, the repository source, and the ADRs.
- Shell: `python3 scripts/verify.py …` (Step 2), and the commands the docs themselves claim — run
  them to confirm the claim, in a non-destructive way.
- Spawn isolated, **blind** subagents for the review axes, each in its own fresh context.
- Write **only** to `docs/<set>/REVIEW.md` and `CROSS-SKILL-FINDINGS.md`.

## Forbidden actions

- **Silently editing the documents under review.** This skill produces a register a human approves;
  it never auto-fixes.
- Giving any axis your own conclusions, or another axis's findings, before the adjudicator runs —
  anchoring destroys the independence the method depends on.
- Handing an axis `references/house-style.md` itself instead of the neutralized writing contract.
- Recalling a figure instead of recomputing it, or marking a claim VERIFIED without reading the
  source or running the command.
- Running the critique before `verify.py` is green.
- Claiming an independent gate when the run was sequential in one context.
- Publishing, or clearing a BLOCKER on the author's say-so without re-verifying.

## Procedure

The numbered **Workflow** above is the procedure: ground and load the review profile → run
`verify.py` first → confirm the registers → run the blind multi-axis critique (whole-document
consistency, code-grounded correctness, beginner floor, then the adversarial adjudicator) → emit the
different-vendor pass for a flagship gate → write the severity-ranked register → gate on unresolved
BLOCKERs and re-verify.

## Validation

```bash
python3 scripts/verify.py docs/learning --format md --skill learning-track \
  --profile docs/project-profile.md --license LICENSE
```

Run it in Step 2 (before the critique) and again in Step 7 (after fixes). The critique itself is
validated structurally: every axis ran blind in its own context, the whole-document axis ran over the
entire set at once, every finding has a severity + location + axis + fix, every code claim is tagged
VERIFIED / ASSERTED / NEEDS-CODE-CHECK, and every BLOCKER id is marked resolved before handoff. The
repo-level gate is `make validate` (`scripts/validate_quality_contracts.py`).

## Handoff contract

- **Consumes from** any authoring skill (`architecture-and-decisions`, `operations-runbook`,
  `onboarding-companion`, `learning-track`, `usage-guide`, `project-faq`) — its produced pages, after
  `verify.py` is green.
- **Hands back to the author/owner**: `docs/<set>/REVIEW.md`. The owner applies fixes in one cycle.
- **Hands to** `publish-mirror` — but **only** once every BLOCKER id is marked resolved and
  `verify.py` is green again. Unresolved BLOCKERs block publishing.
- **Hands outward** to `CROSS-SKILL-FINDINGS.md` so the next doc type inherits a systemic defect
  class.

## Stop conditions

Stop and hand back to a human rather than proceeding when:

- `verify.py` reports a FAIL — fix that first; the critique is wasted on it.
- You cannot read the source or run the commands the docs claim — the correctness axis degrades to
  "unverified" and the gate is not honest without saying so.
- The harness cannot give each axis its own isolated context — declare the run a **structured
  self-review, not an independent gate**.
- A flagship/public gate needs the different-vendor pass — emit the prompt and **pause** until its
  findings return.
- A BLOCKER is disputed on judgement, not fact. The register is the artefact; the human decides.
- No review profile exists for the doc type and the stakes are high — write the profile first.

## Examples

- *"Review the learning track before we publish it."* → verify → confirm registers → four blind axes
  over `docs/learning/` → `docs/learning/REVIEW.md` with `B1: Module 3 says the cap is enforced
  server-side, Module 6 says client-side — one of them leaves the reader believing something false.`
- *"The runbook says 'measured $0.02 per run' — is that true?"* → correctness axis recomputes from
  the source, tags the claim ASSERTED, and files it as a code-vs-doc mismatch with the exact quote.
- *"We changed the architecture doc's analogy — check nothing else broke."* → whole-document axis over
  the entire set at once, hunting analogy drift and term collisions across pages.

## Anti-examples

- *"Just fix the docs for me."* → out of scope; this produces a register, not edits.
- *"Skip the verifier, go straight to the critique."* → forbidden; Step 2 is a precondition.
- *"Run all four axes in this chat, one after another, and call it independent."* → that is a
  structured self-review; say so.
- *"Tell the reviewers what you think is wrong so they focus."* → anchoring; defeats the method.
- *"Review the SKILL.md files."* → `per-skill-review-prompt.md`.
- *"Publish it once the register is written."* → only after every BLOCKER is resolved and re-verified.
