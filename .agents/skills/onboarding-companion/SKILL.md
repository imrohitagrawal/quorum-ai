---
name: onboarding-companion
description: Create a newcomer onboarding companion — a "buddy" guide plus a mentor voice — that takes a brand-new joiner, fresh graduate, or non-expert contributor from zero to productive on a software project. Covers setting up, running it end to end, reading the codebase in the right order, working day to day, getting unstuck, and the senior-engineer habits that matter when building with an AI coding agent. Produces Markdown (repo-first, an ONBOARDING.md plus a CONTRIBUTING section). Use this whenever the user wants onboarding docs, a contributor guide, a "getting started for new team members", a buddy guide, developer onboarding, or wants to help someone new start contributing. Use it even if the user only says "help new people get up to speed", "write a guide for new contributors", or "onboard a junior to this repo". This is for contributors, distinct from an end-user usage guide; it is not a multi-audience concepts course (use learning-track).
---

# Onboarding Companion Builder

Version: 1.1.0 · see `CHANGELOG.md`.

Build the **newcomer's companion**: the guide that turns a brand-new joiner into a confident
contributor, not just a reader. It has two voices that work together — a patient **buddy** who walks
the reader from zero, and a **mentor** who passes on the senior-engineer judgement that keeps a
project healthy (especially when building with an AI coding agent). Read `references/house-style.md`
first. Default scope is `internal`, so naming the real workflow, tools, and commands is expected and
wanted.

**Diátaxis mode:** primarily *tutorial* (learning-by-doing), with the mentor section as *explanation*.

**This is not the usage guide.** The usage guide is for an end user who wants to *use* the product.
This is for a contributor who needs to *work on* it — set it up, read the code, and ship a change
safely.

---

## Before you start (inputs, when to run, where it sits)

**What this skill needs.** A repository that already **runs end to end** — a real one-command (or
near) quickstart — plus the project profile (`assets/project-profile.md`, filled), and knowing where
the project keeps its requirements, docs, ADRs/decision log, and conventions. If the project already
has an architecture walkthrough, a usage guide, or an operations runbook, link to them from here
rather than re-deriving them — this companion points a newcomer at them, it does not replace them.

**When to run it in a Claude-Code build.** **Late, not early.** A newcomer's companion documents a
real, runnable system, so produce it once the repo exists and works: a quickstart that runs, a few
ADRs, and an architecture overview to read. Running it on an **empty repo** is premature — there is
nothing to onboard onto yet — and it is **not a per-commit job**. Treat it as a per-milestone
deliverable: write it when the project is first runnable by someone new, then **refresh it when the
setup steps, the repo layout, or the conventions change** (the ISO `Last reviewed` stamp and the
verifier's staleness check exist for exactly that, since setup and conventions are the most
drift-prone content in any project).

**How it sequences with the other six skills (it is a consumer).** This skill turns a *can-run-it*
contributor into a *can-change-it-safely* one, and **points outward** instead of duplicating:
- **architecture-and-decisions** — the "why" and the design deep-dive. The reading path links to it;
  it is not restated here.
- **usage-guide** — how an **end user** *uses* the product. This companion is for someone who *works
  on* it; if the reader only wants to use it, send them there.
- **operations-runbook** — operating and troubleshooting in production. Day-to-day contributing is
  here; running the live system is there.
- **learning-track** — the multi-audience concepts course ("teach me the field and how this works").
  This companion gets one new contributor productive on **this** repo; it is not that course.
- **publish-mirror** — the separate, later publish step (Workflow step 6).

---

## Workflow

1. **Ground and configure.** Read `house-style.md`; find or create the project profile. Note
   `grade_target_onboarding_companion` and `scope_onboarding_companion`. Identify the real setup steps, the quickstart,
   the repo layout, and the project's conventions (where requirements live, where docs live, where the
   ADRs are, feature flags, observability).
2. **Write the buddy path** using `references/buddy-path.md` — zero-to-running, then how to read the
   code, then day-to-day work, then getting unstuck, then following one feature end to end.
3. **Write the mentor path** using `references/mentor-path.md` — the senior-engineer mindset and the
   habits people skip and regret.
4. **Write the working-with-AI section** using `references/working-with-ai.md` — how to use an AI
   coding agent well, and the honest traps.
5. **Verify and present:**
   ```bash
   python3 scripts/verify.py docs/onboarding --format md --skill onboarding-companion --profile docs/project-profile.md
   ```
6. **Publish (repo-first — a separate, later step).** Write the verified Markdown to the repository
   first. That is always the default and the source of truth; a published target is only a mirror,
   and you never author in the target. Publishing is a separate step that runs after this loop,
   performed by the **publish-mirror** skill: it renders each page to every destination configured
   in `docs/publish-targets.yaml` (a wiki, a portal), following `references/render-contract.md`.
   The conversion — collapsible blocks, callouts, the table-of-contents line, diagrams exported to
   images, status badges, the licence footer — is defined once in the render contract; this skill
   does not restate it. Publish per page or per batch as each clears the loop.

---

## Output structure (repo-first)

```
docs/onboarding/
├─ ONBOARDING.md         # the buddy path: zero -> running -> reading -> contributing
├─ MENTOR.md             # the senior-engineer mindset and habits
└─ working-with-ai.md    # using an AI coding agent well, and the traps
# plus a short CONTRIBUTING.md at the repo root that links these and states the basics
```

Each page opens with a one-line ISO freshness stamp — a visible `Last reviewed: YYYY-MM-DD` line
(the render contract, P2) — so the verifier's staleness check can read it and flag the page when the
setup steps or conventions it describes have aged out. Use the ISO form; do not invent another.

## The two voices

**Buddy (patient, concrete, zero assumed):**
- The problem this project solves, in everyday terms, and the words explained.
- **Set up the tools from zero** — accounts, keys, clone, dependencies. For anything that needs a
  credential (signing in, an API key, a password), **tell the reader to do that step themselves the
  secure way** — never enter a secret on their behalf and never put one in a doc.
- **A one-command quickstart** to run it end to end and see it work.
- **How to read the repo in order** — a guided path through the code so the reader is not dropped into
  a maze.
- **How to work day to day** — plan first; small steps; read the diff before you commit; ask, don't
  assume; the tests are the spec.
- **What to do when stuck** — a calm troubleshooting flow and where to ask (no question is too basic).
- **Follow one feature end to end** — trace a single real feature from requirement to test to running
  code, so the whole shape clicks.

**Mentor (senior-engineer judgement):**
- Treat an AI coding agent as a **fast junior**: it is quick and confident but not always right —
  **verify, don't trust**; understand what you ship.
- **Text the agent reads is data, not orders.** When it pulls in an issue, a wiki page, or a web
  result, that is information to use — never instructions to obey. If fetched content says "do X",
  surface it for a human; do not let the agent act on it.
- **Plan first, ship small and often, write decisions down** (as ADRs).
- The things people skip and regret: keep a decision log; protect the main branch; **never commit
  secrets**; measure before optimising; watch cost; **pin model versions**; and **reserve a slice of
  each cycle (about a tenth) to pay down the debt fast AI work piles up**, before it compounds.
- The project's conventions: where requirements live, where docs live, where ADRs go, how feature
  flags work, and that observability comes first.

## Honesty (state this plainly)
Building with AI is fast, but speed is not safety. AI amplifies both good and bad habits: a clear
plan and good tests make it a force multiplier; skipping them piles up debt and bugs. Studies of
AI-generated code have found a large share contains security weaknesses — around 45% in one
widely-cited 2025 analysis — so a human stays the architect and the final gate, and review and tests
are non-negotiable. (See `references/working-with-ai.md`.)

## Quality bar (self-check before presenting)
- A brand-new joiner could go from nothing to a running system and a first small change using this
  alone.
- The buddy path assumes nothing and defines every term; the reading path is a real ordered route, not
  "go look at the code".
- No step enters a secret on the reader's behalf; credential steps are theirs to do.
- The mentor path gives real judgement, not slogans; the AI traps are honest, not hype.
- The agent-safety habits are present: fetched text is treated as data not orders, and there is a
  habit to pay down AI-driven debt.
- Each page carries an ISO `Last reviewed: YYYY-MM-DD` stamp so the staleness check can read it.
- It is clearly for contributors, not end users; the verifier passes.


**Licensing and credits (required).** Every page carries the licence footer; the document set ships a `LICENSE` and an **About & credits** page, and the warranty disclaimer appears in the LICENSE — all per `references/licensing-and-credits.md`, using the public or internal variant per the profile's scope. The verifier fails a public page that lacks the footer.

## References
- `references/licensing-and-credits.md` — the licensing + credits standard; applies to every document this skill produces.
- `references/house-style.md` — the shared writing standard (read first).
- `references/buddy-path.md` — the step-by-step newcomer path.
- `references/mentor-path.md` — the senior-engineer mindset and habits.
- `references/working-with-ai.md` — using an AI coding agent well, and the traps.
- `assets/project-profile.md` — copy into the repo and fill once per project.
- `scripts/verify.py` — run before presenting.

---

# Factory skill contract

> **Repo-added section.** Everything above is the upstream bundle. This block is the contract
> `scripts/validate_quality_contracts.py` requires of every `.agents/skills/*/SKILL.md`, written
> against what this skill actually does. Because an upstream refresh replaces this folder wholesale,
> **re-apply this block after every update** — `make validate` goes red without it. Provenance is
> recorded in `configs/external-skill-registry.json`.

## When to use

- The repository **runs end to end** for the first time and a new joiner, fresh graduate, or
  non-expert contributor now needs a path from zero to a first shipped change.
- The setup steps, the repo layout, or the project's conventions changed, and the existing companion
  has aged out (the `Last reviewed:` stamp and the staleness check exist for exactly this).
- The ask is onboarding docs, a contributor guide, "getting started for new team members", a buddy
  guide, developer onboarding, "help new people get up to speed", or "onboard a junior to this repo".
- Contributors are building with an AI coding agent and need the honest habits and traps written down.

## When not to use

- **On an empty or non-running repo.** There is nothing to onboard onto; a quickstart that does not
  run teaches a lie.
- **Per commit.** This is a per-milestone deliverable.
- **For end users.** Someone who wants to *use* the product gets `usage-guide`; this is for someone
  who *works on* it.
- **As a concepts course.** A multi-audience "teach me the field" track is `learning-track`.
- **For production operation.** Running, monitoring, and recovering the live system is
  `operations-runbook`.
- **To re-derive the "why".** Link `architecture-and-decisions`; do not restate it here.

## Inputs

- A repository that already runs end to end, with a real one-command (or near) quickstart.
- `assets/project-profile.md`, filled — `grade_target_onboarding_companion` and
  `scope_onboarding_companion` (default `internal`).
- Where the project keeps requirements, docs, ADRs/decision log, conventions, feature flags, and
  observability.
- The sibling docs to point at, where they exist: the architecture walkthrough, the usage guide, the
  operations runbook.
- `references/house-style.md` (read first), `buddy-path.md`, `mentor-path.md`, `working-with-ai.md`.

## Owned outputs

```
docs/onboarding/
├─ ONBOARDING.md         # the buddy path: zero -> running -> reading -> contributing
├─ MENTOR.md             # the senior-engineer mindset and habits
└─ working-with-ai.md    # using an AI coding agent well, and the traps
```

Plus a short `CONTRIBUTING.md` at the repo root that links these and states the basics. Every page
opens with a literal `Last reviewed: YYYY-MM-DD` line. This skill owns those files and nothing else.

## Allowed tools

- Read anywhere in the repository.
- Write **only** to the owned outputs above.
- Shell: `python3 scripts/verify.py …`, plus **actually running the quickstart and the setup steps**
  from a clean state — that is how the buddy path stays truthful.
- Read the sibling docs in order to link them accurately.

## Forbidden actions

- **Entering a credential on the reader's behalf**, or putting a secret, key, token, or password into
  any page. Credential steps are the reader's to do, the secure way.
- Documenting a setup step or quickstart you have not run.
- Restating the architecture rationale, the end-user usage guide, or the runbook instead of linking.
- Editing source code, ADRs, or another skill's outputs.
- Publishing — that is `publish-mirror`.
- Shipping the mentor path as slogans, or the AI section as hype: the honesty section (including the
  security-weakness finding) is required, not optional.

## Procedure

The numbered **Workflow** above is the procedure: ground and configure → write the buddy path
(zero-to-running, how to read the code in order, day-to-day work, getting unstuck, one feature traced
end to end) → write the mentor path → write the working-with-AI section → stamp `Last reviewed:` and
verify → hand off to `publish-mirror`.

## Validation

```bash
python3 scripts/verify.py docs/onboarding --format md --skill onboarding-companion --profile docs/project-profile.md
```

Green means: reading grade within `grade_target_onboarding_companion`, no banned words, no
internal-name leak for `scope_onboarding_companion`, links resolve, the licence footer is present, and
the `Last reviewed:` stamp parses and is not stale. The human check that matters more: a brand-new
joiner can go from nothing to a running system and a first small change using this alone. The
repo-level gate is `make validate` (`scripts/validate_quality_contracts.py`).

## Handoff contract

- **Consumes from** `architecture-and-decisions` (the "why" and the reading path's destinations),
  `usage-guide` (where to send an end user), `operations-runbook` (where production lives), and
  `learning-track` (where the concepts course lives). It links all four; it replaces none.
- **Hands to** `doc-critic` for the blind multi-axis critique; unresolved BLOCKERs stop the handoff.
- **Then to** `publish-mirror`, per `references/render-contract.md`.

## Stop conditions

Stop and ask a human rather than guessing when:

- The quickstart does not actually run from a clean clone — fix the repo, or the companion documents
  a path that does not exist.
- A setup step needs a credential or an account you cannot and must not create.
- The project profile is missing or unfilled.
- The project's conventions are undecided (no decision log, no branch policy, no ADR home) — a
  companion that invents them is inventing policy.
- The reading path would have to say "go look at the code" because no ordered route exists.
- The verifier reports a FAIL that would need a fact you do not own to be changed.

## Examples

- *"A junior joins next week — get them productive on this repo."* → `ONBOARDING.md`: prerequisites,
  clone, dependencies, the one-command quickstart, an ordered reading route through the repo, the
  day-to-day loop (plan → small step → read the diff → tests are the spec), a troubleshooting flow,
  and one real feature traced from requirement to test to running code.
- *"Write down the habits people here skip and regret."* → `MENTOR.md`: keep a decision log, protect
  main, never commit secrets, measure before optimising, watch cost, pin model versions, and reserve
  about a tenth of each cycle to pay down AI-driven debt.
- *"Our contributors lean hard on an AI agent — what should they know?"* → `working-with-ai.md`:
  treat it as a fast junior (verify, don't trust); text the agent reads is **data, not orders**; a
  human stays the architect and the final gate.

## Anti-examples

- *"Write onboarding for the project we're starting tomorrow."* → nothing runs yet; premature.
- *"Explain how our users query the product."* → `usage-guide`.
- *"Explain why we chose this architecture."* → `architecture-and-decisions`; link it.
- *"Put the shared dev API key in ONBOARDING.md so setup is one step."* → forbidden; the reader
  provisions their own credential.
- *"Just say 'read the code and ask questions'."* → the reading path must be a real ordered route.
- *"Teach them Python and distributed systems first."* → `learning-track`.
