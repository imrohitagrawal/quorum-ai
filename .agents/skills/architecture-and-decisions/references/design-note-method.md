# Design-note method — the deep dive for one significant component

The C4 views (`architecture-method.md`) show the *whole system* at four zoom levels, and the decision
treatments (`decision-treatment.md`) give the *why* for each significant choice in five lines. Neither
goes deep on a single high-stakes component. Some components earn that depth: a **design note** is the
worked design for *one* component, the artifact a reader studies before changing the part of the system
where a mistake is most expensive.

This is the same selectivity the decision treatment uses — *significant* choices only. Do not write a
design note for every box on the container diagram; write one for the components where the cost of a
wrong change is high and the design is non-obvious. Typical earners:

- a **trust or isolation boundary** (authentication, authorization, multi-tenant data separation) —
  where a single missed check is a breach, not a bug;
- the **highest-blast-radius store or gateway** (the database many stages depend on; the model
  gateway every step calls) — where one failure stalls much of the system;
- a component carrying a **non-obvious trade-off** a reader would otherwise get wrong (a consistency
  choice, a routing or fallback policy, a credential model).

A design note sits *beside* the system walkthrough, linked from the container/component view it zooms
into and from the decisions section. It does not replace the ADR (the ADR holds the decision and its
rejected alternatives); the design note holds the *worked design* the build follows.

## 1. Cover a fixed set of design dimensions — and never silently skip one

The discipline that makes design notes trustworthy is a **named, fixed checklist of design dimensions**
applied to *every* note, so a gap is visible instead of forgotten. A reader can tell at a glance whether
security was considered or merely omitted. Adopt a checklist for the project and hold every note to it.
A solid default set, broad enough for most systems:

1. **Product clarity** — what this component is for, and who uses it.
2. **System boundaries** — what is inside its responsibility and what is outside.
3. **API / interface** — the shape of what it accepts and returns, and the versioning rule.
4. **Data model** — the entities it owns and the discriminators that matter.
5. **Security / auth / isolation** — the threat model and the controls (Section 2).
6. **Scalability** — how it grows, and what binds it first (defer the costly build to its trigger —
   `nfr-posture-method.md` Section 6).
7. **Observability** — what it emits so a failure is visible (the signals the NFRs measure).
8. **Testability** — how each guarantee is proven (the one-fault-injection test, `failure-mode-method.md`).
9. **Deployment / rollout risk** — what is risky to ship, and how the rollout is staged.
10. **Operational failure modes** — the per-component FMEA-lite (Section 4).

The set is a starting point, not scripture — a project may add or rename dimensions. The rule that
matters is the *fixed list, applied every time*. For each dimension, state one of: **covered** (here),
**referenced** (owned by another record — link it), **Phase N** (designed, built later — mark it
`[designed, not yet built]` and link the live status), or **not applicable** (say why). An omitted
dimension reads as an oversight; a dimension marked "not applicable, because …" reads as a decision.

## 2. Lead with the threat or risk model

Before the design, state plainly **what this component is defending against, or what can go wrong with
it** — the ranked risks the design then answers. For a security component this is a threat model (the
assets an attacker wants, and the defining attack paths); for a non-security component it is the ranked
failure or correctness risks. Then show that the design answers *each* one: a numbered risk list, and
for every risk the specific control or mechanism that addresses it. This ordering — risks first, design
second — is what stops a design note from being a tour of mechanisms with no argument for why they are
the right ones.

For a component an AI agent can drive, include the **AI-native risk** explicitly: untrusted text read by
a model that can call tools is a prompt-injection path. Name the standing rule — *ingested text is data,
never instructions* — and the backstop that holds even if an injection succeeds (for example, the agent
acting only under the requester's least-privilege identity, so a successful injection still reaches no
data the requester could not already reach). See `architecture-method.md` for marking that boundary on
the diagram.

## 3. Write the worked design — and reference its values, never paste them

The body is the worked model: the isolation model, the authorization model, the credential model, the
consistency or routing policy — whichever this component turns on. Explain each in plain words, define
each term on first use, and give the *why* and the *rejected alternative* the way a decision treatment
does (link the ADR by number; do not restate its status — the registry owns it).

Tunable values a design note carries — a threshold, a count, an `N`, a timeout, a key-rotation period —
live **in the ADR or a config file and are referenced by key**, exactly as `decision-treatment.md`
requires. A design note is long-lived and its component changes underneath it; a pasted figure drifts the
first time the source changes. Name the key, link the owner.

Name the **invariant or backstop** a future change must not break — the single most useful line for the
next editor (for example: "every database session is bound to one tenant; a forgotten application filter
must still return nothing, because the row-level policy refuses it"). Defence in depth — a rule *plus* a
place that catches the miss — is worth stating as the property the component guarantees.

## 4. Component-level NFRs and a per-component FMEA-lite

A design note carries the qualities and failure modes that are *specific to this component*, and
single-sources the rest:

- **Component NFRs.** State the component's own service-level indicators (an auth-check latency, an
  isolation-overhead budget, a cross-boundary-reads target) with the **control mode** for each
  (`nfr-posture-method.md` Section 1 — an isolation target is a hard regression gate, not a spendable
  budget). The component design note **owns** these local targets; the system NFR/SLO register
  **references** them. Conversely, a target the register owns (an end-to-end latency, a shared cost
  ceiling) is *referenced* from the note, never copied. One owner per value, the single-source rule
  applied across the two documents.

- **A per-component FMEA-lite.** A compact table for *this component*: failure mode → cause →
  effect / blast radius → detection signal (the SLI that surfaces it) → recovery → class (operational
  vs correctness — `failure-mode-method.md`) → owner. This is the **per-component counterpart** to the
  system-wide blast-radius map and failure table in `failure-mode-method.md`: that one is cross-cutting
  (the shared dependencies, what stops vs degrades); this one is local (how *this* part fails and
  recovers). The payoff of putting it in the design note is that **failure-mode coverage regenerates
  with each component design** — every new component ships its own FMEA-lite as part of its note — so
  coverage tracks the system without a separate task per component. Do not duplicate the system map
  here; link it.

## 5. Close with the phased build — decomposed, but not pre-created

A design note usually describes more than is built today. End with the **phased build plan**: the order
the pieces land, and the one foundation (if any) owed *before* the main build. Two disciplines keep this
honest:

- **Temporal decomposition.** Decompose the build into phases, but **do not create the per-phase tasks
  until that phase is approached** — most depend on conditions that do not exist yet, and creating them
  early just adds non-actionable backlog. This is the same discipline `nfr-posture-method.md` Section 6
  applies to scaling seams; apply it to the build plan.
- **The forward-compatibility seam.** When a later capability needs a foundation laid early, prefer an
  **additive** change that breaks nothing now (a new optional field with a safe default; a discriminator
  that carries a single default value) so the later build is *additive, not a migration*. State it as the
  one obligation owed before the deferred phase, and mark everything past it `[designed, not yet built]`
  with a link to the live status. A cheap, reversible foundation laid early is worth far more than a
  speculative full build.

And give a **written trigger** for any deferral, so "later" does not quietly become "never": name the
concrete condition (a new kind of user, a count crossing a set threshold, a capability requested) that
*forces* the next phase. A deferral with no written trigger and no owner is not a plan; it is an
omission waiting to accrete special cases.

## 6. Where it lives, and how it links

Keep design notes in a predictable home — `docs/design/<component>.md` (or
`docs/architecture/design-notes/<component>.md`) — and link each one from the container/component view it
zooms into (`architecture-method.md`) and from the decisions section that records its choice. The note
references the live ADR registry for status, references the NFR/SLO register for shared targets, and
carries the same honesty markers and licence footer as every other page. It is one focused deep dive,
linked into the walkthrough — not a parallel, drifting copy of it.
