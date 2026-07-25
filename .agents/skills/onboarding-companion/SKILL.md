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
