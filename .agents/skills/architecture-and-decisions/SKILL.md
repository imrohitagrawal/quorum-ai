---
name: architecture-and-decisions
description: Create an architecture and decision walkthrough that explains how a software project fits together and WHY each significant choice was made, with the alternatives, the trade-offs, and the failure modes. Takes a reader from "can use it" to "understands it well enough to change or extend it safely." Produces Markdown (repo-first) with C4-style diagrams and a decision treatment for every important choice. Use this whenever the user wants an architecture doc, design doc, technical deep-dive, decision record narrative, "why is it built this way", or to understand the system in depth. Use it even if the user only says "document the architecture and the reasoning", "explain the design decisions", or "write the technical overview for a new engineer". For one technical reader who can already use the system — NOT a newcomer course (use learning-track), NOT operator recovery steps (use operations-runbook), NOT a look-up Q&A page (use project-faq).
---

# Architecture & Decisions Walkthrough Builder

Version: 1.3.0 · see `CHANGELOG.md`.

Build the **depth artifact**: the document a new senior engineer reads to understand the system well
enough to change it safely. It explains *how the whole thing fits together* and, for every choice
that matters, *why it was made* — the alternatives considered, the trade-off accepted, and the
failure modes it guards against. Read `references/house-style.md` first.

**Diátaxis mode:** *explanation* (understanding-oriented). It is not a tutorial and not a step-by-step
how-to; it builds the reader's mental model and judgement.

**Sourcing — narrate, do not restate.** Draw from the repository, the decision records (ADRs), the
decision log, the contracts, and the runbooks. The terse ADR registry owns the canonical decision
*numbers and status* — link to it; this walkthrough teaches the *reasoning* a registry cannot. Apply
the single-source rule in two parts: never restate an ADR number or status here (point to the live
registry); and never copy a **tunable value** — a threshold, an `N`, a pixel ratio, a timeout — into
the walkthrough. Name the value's *key* and link the ADR or config file that owns it. A pasted number
drifts from its source the first time the source changes; a referenced key cannot.

---

## Before you start: what this needs, when to run it, where it fits

This walkthrough is the **first artifact the rest of the documentation set is built on** — the
learning track, the FAQ, the onboarding companion, and the runbook all teach *from* and link *to* the
architecture and the decision records this skill produces. So three questions come first: *do I have
what it needs, when in the build do I run it, and how does it sit next to the other skills?* Read this
before the workflow.

### What this skill needs (the inputs)

The walkthrough explains a *real* architecture and *real* decisions, so it has to read them first.
Before writing, make sure these exist and point the skill at them:

- **The filled project profile** (`docs/project-profile.md`) — owner, brand, licence, palette, the
  reading-grade target, the public-vs-internal scope, and the canonical worked example.
- **A designed architecture** — at least the system-context and container views (C4 Levels 1–2) and
  the worked example traced end to end. Component and code detail (Levels 3–4) can follow, and are
  better generated from the code (see the cadence below).
- **The accepted decision records (ADRs)** — the actual choices and their *reasoning*: context, the
  alternatives weighed, the trade-off, the consequences. The terse registry owns the numbers and
  status; the authored ADRs hold the substance the treatment narrates.
- **The decision log / ADR registry** — the live index to link each treatment to by number.
- **The contracts or interfaces** — the shape of the inputs and outputs, and the versioning rule
  (for example, whether contract changes must be additive).
- **The technology stack with the reason for each choice**, not just the names.
- **Any failure-mode analysis or runbook material**, and **the live status source** (roadmap,
  decision log, issue tracker) for the built-vs-designed markers to link to.

> **Status — the natural stop.** This skill is the *producer*, so its stop is the inverse of the
> others' "wait for the design": **you cannot write a decision treatment before the decision is made
> and recorded.** If you cannot give the alternatives and the trade-off for a choice, you do not yet
> understand it well enough to document it — read the ADR and the code first, or mark the section
> `[designed, not yet built]` and link the live status. Do not invent a rationale to fill the page.

### When to run it in the build (the cadence)

An architecture walkthrough is **not a per-commit check, and not a single pass at the very end.**

- **Not per commit.** The per-change gate — banned words, link-check, lint, secret-scan — is a
  deterministic hook, not this skill. Re-running the full authoring loop on every commit is churn.
- **Not only at the end.** Writing the whole thing after the build loses the link-back discipline and
  ships decision treatments that have already drifted from the code.
- **Run it at design time, per significant decision and per milestone:**
  - **A decision treatment is written when its ADR is accepted** — one treatment per accepted
    decision. The design is "done" for a choice when its ADR is accepted, not when the feature is
    built; that is the moment to narrate it, while the reasoning is fresh.
  - **The context and container views (Levels 1–2) are drawn when the architecture is decided** — at
    design time, on a near-empty repository, not after the code lands.
  - **The component and code views (Levels 3–4) are generated from the code and kept in lockstep** —
    a CI gate that fails when the code changes without the diagram updating — rather than hand-drawn
    here, because those are the levels most prone to drift. Hand-draw Level 3 only for the one or two
    containers a reader most needs, and mark it a point-in-time snapshot (see `architecture-method.md`).
  - **The failure-mode and non-functional-posture sections are revisited each phase** as the system
    grows. Provisional service-level targets are committed and *labelled* now, then validated against
    a baseline in the phase that owns the telemetry (see `nfr-posture-method.md`).
- **The link-back rule (this is what keeps it from going stale).** Teach the stable structure and the
  reasoning; link every volatile specific — a current status, a tunable value — to its live source.
  When the source changes, the walkthrough is still correct because it pointed instead of copying.

### Where this fits among the documentation skills

- **This skill runs first, or in lockstep with design.** It produces the architecture, the ADR
  sequence, and the contracts the other five skills consume. Without them, a learning track or an
  onboarding guide has nothing to anchor to.
- **Tell it apart from its neighbours by what the reader wants:**
  - "I can already use it — explain the *design and the decisions* in depth so I can change, debug, or
    extend it" → **this skill**: a focused walkthrough for one technical reader.
  - "Take me from zero to understanding the *whole* system and *why*, with a path to build my own" →
    **learning-track**: a mixed-audience, foundations-first course with a practice ladder. Both cover
    *why*; the split is audience and arc.
  - "What do I do, step by step, when it breaks" → **operations-runbook**. This skill documents
    failure modes to build *understanding of the design's resilience* (what breaks, how the design
    copes, the invariant a change must not break); the runbook owns the *operator procedure* (symptom
    → first response → escalation). Teach the resilience here; link the runbook for the steps.
  - "Tell me the *facts* / answer a specific question" → **project-faq** (look-up Q&A, usually
    internal). A decision *narrative* belongs here; a quick *fact* belongs there.
  - "Help me *do* a task" → **usage-guide**; "help me start *contributing*" → **onboarding-companion**.

---

## Workflow

1. **Ground and configure.** Read `house-style.md`; find or create the project profile. Note
   `grade_target_architecture_and_decisions` and `scope_architecture_and_decisions`. Pick the same
   canonical worked example the rest of the docs use so the data-flow section is concrete.
2. **Build the architecture views** using `references/architecture-method.md` (C4-style: context →
   container → component → runtime/data-flow for the worked example end to end).
3. **Write a decision treatment for every significant choice** using
   `references/decision-treatment.md` — five lines each: what it is; the alternatives; why this one;
   when you would choose differently; how it serves the purpose — with honest pros and cons, and a
   link to the ADR by number.
4. **Write a deep design note for each significant component** using
   `references/design-note-method.md` — only for the components that earn it (a trust or isolation
   boundary, the highest-blast-radius store or gateway, a non-obvious trade-off). Cover a fixed
   design-dimension checklist, lead with the threat/risk model, reference tunable values by key, name
   the invariant, state the component's own NFRs (single-sourced with the register) and a
   per-component failure table, and close with the phased build by temporal decomposition. Skip it for
   ordinary components; the C4 views and the decision treatments already carry those.
5. **Document failure modes and recovery** using `references/failure-mode-method.md` — what goes
   wrong, why, how it is detected, how it is handled (idempotency, resume, retries), and what the
   reader must not break. This is the *system-wide* map (the shared dependencies, what stops vs
   degrades); the *per-component* failure table lives inside that component's design note (Step 4) —
   link the two, do not duplicate.
6. **State the non-functional posture** — scalability, service-level objectives, security, and
   observability — using `references/nfr-posture-method.md`. Commit and **label** provisional targets,
   pick the right control mode for each (an error budget is not a spend ceiling, and neither is a
   correctness gate), name each SLI's measurement signal, and keep built-vs-designed honesty: mark
   anything `[designed, not yet built]` and link the live status. Do not imply unbuilt capability is
   live, and do not put a measurable SLO on a component that does not exist yet.
7. **Close with the mental model** — a short "how it all fits" summary the reader can hold in their
   head, tied to the worked example.
8. **Verify and present.** Pass `--skill architecture-and-decisions` so the grade target and scope
   come from the profile, and `--license LICENSE` so the same run confirms the `LICENSE` carries the
   warranty disclaimer and names the content licence (the check the CI gate runs, kept in your own
   pre-present pass):
   ```bash
   python3 scripts/verify.py docs/architecture --format md --skill architecture-and-decisions --profile docs/project-profile.md --license LICENSE
   ```
9. **Publish (repo-first — a separate, later step).** Write the verified Markdown to the repository
   first. That is always the default and the source of truth; a published target is only a mirror,
   and you never author in the target. Publishing is a separate step that runs after this loop,
   performed by the **publish-mirror** skill: it renders each page to every destination configured
   in `docs/publish-targets.yaml` (a wiki, a portal), following `references/render-contract.md`.
   The conversion — collapsible blocks, callouts, the table-of-contents line, diagrams exported to
   images, status badges, the licence footer — is defined once in the render contract; this skill
   does not restate it. Publish per page or per batch as each clears the loop.

---

## Document structure (use this order)

```
docs/architecture/
├─ 00-overview.md        # what the system is; the system context (who/what/boundaries)
├─ 10-containers.md      # the major parts and how they communicate (container view)
├─ 20-components.md      # inside the key parts (component view; Level 3 — prefer generated-from-code, see method)
├─ design-notes/         # one deep design note per *significant* component (threat/risk model, the worked
│                        #   models, component-level NFRs, a per-component FMEA-lite, the phased build) — see
│                        #   design-note-method.md; link each from 20-components.md and 40-decisions.md
├─ 30-runtime.md         # the worked example, followed end to end (data flow)
├─ 40-decisions.md       # a five-line treatment per significant choice, linking the ADRs
├─ 50-failure-modes.md   # what breaks, how it is detected, how it recovers
├─ 60-nfr-posture.md     # scalability, SLOs, security, observability (built vs designed)
└─ 70-mental-model.md    # the short "how it all fits" summary
```
(Combine into fewer files for a small project; keep the section order.)

## Quality bar (self-check before presenting)
- A new senior engineer could read it and safely make a first change.
- Every significant choice has its alternatives and the trade-off, not just the decision.
- Each high-stakes component (a trust/isolation boundary, the highest-blast-radius store or gateway, a
  non-obvious trade-off) has a deep design note that covers a fixed design-dimension checklist, leads
  with its threat/risk model, and carries its own per-component failure table — coverage that
  regenerates as components are added.
- Failure modes are documented, with detection and recovery — not only the happy path — and the
  section leads with a blast-radius/dependency map (what stops vs what degrades).
- Diagrams follow the C4 levels and the palette; container views stay at or under eight nodes (split
  a crowded view); each diagram has alt text and a static fallback.
- Decision numbers/status are linked to the live ADR registry, not restated; **tunable values are
  referenced by key, never pasted** into the walkthrough.
- The non-functional posture labels provisional targets, names each SLI's signal, and uses the right
  control mode (error budget vs spend ceiling vs correctness gate).
- Built-vs-designed honesty is correct; the verifier passes (no FAIL), including `--license`.


**Licensing and credits (required).** Every page carries the licence footer; the document set ships a `LICENSE` and an **About & credits** page, and the warranty disclaimer appears in the LICENSE — all per `references/licensing-and-credits.md`, using the public or internal variant per the profile's scope. The verifier fails a public page that lacks the footer.

## References
- `references/licensing-and-credits.md` — the licensing + credits standard; applies to every document this skill produces.
- `references/house-style.md` — the shared writing standard (read first).
- `references/architecture-method.md` — the C4 views and how to derive them (node cap, levels generated from code, trust boundaries, semantic colour).
- `references/decision-treatment.md` — the five-line decision treatment, ADR linkage, and the reference-values-by-key rule.
- `references/design-note-method.md` — the deep dive for one significant component: the fixed design-dimension checklist, the threat/risk model, component-level NFRs single-sourced with the register, the per-component FMEA-lite, and the phased build by temporal decomposition.
- `references/failure-mode-method.md` — documenting what breaks and how it recovers (blast-radius map, the detection layer's own failure, bounded resume, proving a guarantee).
- `references/nfr-posture-method.md` — scalability, SLOs, security, and observability: control modes, provisional-then-ratify, and single-source ownership.
- `assets/project-profile.md` — copy into the repo and fill once per project.
- `scripts/verify.py` — run before presenting (pass `--skill architecture-and-decisions`).
- `ci/` — a ready pre-commit hook and CI job that run the verifier (docs-as-code, in lockstep).

## Versioning
This skill is versioned like code. Record every change in `CHANGELOG.md` (Keep a Changelog format)
and bump the version in this file's header. An architecture walkthrough that drifts from the project
is worse than none — the link-back rule (reference, do not copy) and a stamped, changelogged skill are
how the two stay in step.
