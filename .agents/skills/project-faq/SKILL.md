---
name: project-faq
description: Create a detailed, self-contained FAQ or question-and-answer wiki for a software project as a single tabbed HTML page with a grouped sidebar, deep links, and keyboard navigation. Every answer is multi-paragraph and carries two worked examples (one real from the project, one everyday analogy). Use this whenever the user wants an FAQ, Q&A page, knowledge base, help centre, project wiki, "common questions", or a page that answers "how does my project do X and why" for newcomers and teammates. Use it even if the user only says "make a page that answers questions about my project", "turn my notes into an FAQ", or "explain the decisions and the workflow for new joiners". Not a concepts course (learning-track), not the design-rationale doc (architecture-and-decisions), not a single-task how-to (usage-guide), not contributor onboarding (onboarding-companion). Includes a reusable Python generator so the HTML structure stays clean.
---

# Project FAQ / Q&A Wiki Builder

Build a **detailed FAQ** as one self-contained tabbed HTML file. The reader is a newcomer or a
teammate — a fresh graduate, a class-12 student, or a new joiner — who must come away able to (a)
say what the project is and why it matters, (b) set the tools up, (c) run it end to end, and (d)
describe how the pieces fit. Read `references/house-style.md` first, every time.

**Diátaxis mode:** a hybrid of *how-to* and *reference*, answering real questions in depth. The FAQ
is usually team-facing (`scope_project_faq` defaults to `internal`), so it **may** name the
day-to-day workflow and tools — unlike a public learning track. (`verify.py --skill project-faq`
resolves `scope_project_faq` and `grade_target_project_faq` from the profile.)

---

## Before you start (inputs, when to run, where it sits)

**Inputs it needs.** A populated repository to answer *from* — at least a README, the decision
records / decision log, the stack list, the day-to-day workflow and config files, the setup steps,
and any security/operations notes — plus the project profile (`assets/project-profile.md`, copied to
`docs/project-profile.md`). The FAQ surveys these; it does not invent answers. If a needed fact is
missing, say so rather than fabricate it.

**When to run it in a Claude-Code build.** *Not* on an empty repo, and *not* per commit. The FAQ is a
milestone artifact: run it once there is enough built and decided to answer real questions — in
practice after the architecture and the main workflow exist — and **refresh it per milestone** as the
project grows, not on every change. (Treat it like docs-as-code: it has a last-reviewed date and is
re-verified when the facts it cites change.)

**How it sequences with the other seven skills** (producers before consumers):

- **learning-track** (public concepts course, teach from zero) — the FAQ is internal Q&A *reference*,
  not a course. Use learning-track to teach a newcomer the field; use this to answer "how does my
  project do X and why" across breadth.
- **architecture-and-decisions** (the deep "why is it built this way" doc) — the FAQ *summarises and
  links* decisions in Q&A form; it does not replace the full decision treatment. Produce that first;
  the FAQ draws on it.
- **usage-guide** (single-task how-to) — the FAQ answers "what/why/how does the project do X" across
  many topics; a step-by-step for one task belongs in usage-guide.
- **operations-runbook** (operator recovery steps) — the FAQ is not an incident runbook; point to the
  runbook for run/restore procedures.
- **onboarding-companion** (contributor onboarding tutorial) — the FAQ's onboarding *tab* is a quick
  buddy; deep contributor onboarding is onboarding-companion's job.
- **doc-critic** (the independent critic gate) — the FAQ *authors* answers; doc-critic *reviews* what was
  produced, catching contradictions between answers, claims the code does not support, and broken
  cross-references, then gates publishing on unresolved blockers. Run it before Step 6.
- **publish-mirror** (the downstream publish step) — when the owner wants the finished page on a wiki
  or portal, the FAQ hands off to it (Step 6); it never authors in the target.

---

## What went wrong before (do not repeat)

- **One-liner answers.** Every answer must be several detailed paragraphs, not a sentence.
- **Dropped points.** Every agreed point and expert addition must appear; keep a checklist.
- **A generic onboarding tab.** It must be a true step-by-step buddy a brand-new reader can follow
  with zero help.

---

## The hard style rules (non-negotiable)

1. **Plain, simple English.** Short sentences, no flowery words (`house-style.md` Section 2).
2. **Detailed.** Each answer covers, where relevant: *what it is → why it matters → how it works (step
   by step) → how AI is used (if any) → the trade-off / what was not picked and why.* Depth, not
   padding.
3. **Two examples in every answer.** A box **"In your project"** (the real example) and a box
   **"Picture it in real life"** (an everyday analogy). Both, every time. The glossary tab is the only
   exception.
4. **Zero prior knowledge.** Define every technical word the first time it appears (repo, commit,
   branch, tag, pull request, CI, hook, API, API key, model, token, schema, contract, agent,
   retrieval, orchestration, mutation testing, and so on). Keep a glossary tab too.
5. **Honesty.** Built-vs-designed markers; "proposed, not yet locked" labels; cite field facts; never
   fabricate a number, a tool name, or a capability. A fact-check pass flags any unbacked claim.

---

## Workflow

### 1. Ground and configure
Read `house-style.md`; find or create the project profile. Read `scope_project_faq` and
`grade_target_project_faq` (the verifier resolves these from `--skill project-faq`).

### 2. Derive the question inventory and tab groups
Use `references/faq-method-and-question-bank.md`. Survey the repository, ADRs, decision log, stack,
workflow, setup, security, and operations, then group questions into tabs. A reusable grouping:
- **Start here** — overview (what it is, the problem, the design, how AI is used, phases,
  deliverables) and a glossary.
- **Working with the tools** — which tool for what; working with AI without losing quality;
  skills/config; the day-to-day workflow files.
- **Architecture and decisions** — the stack and *why this, not the alternatives*; the components;
  the agent/processing design.
- **Quality, security, operations** — the testing approach; automated checks and security; behaviour
  rules; how to run/test/deploy/verify/debug.
- **Sharing and people** — shipping each piece; visual standards.
- **People tabs** — **onboarding** (the step-by-step buddy) and **mentor** (the senior-engineer
  voice). These are the most important tabs.

### 3. Write every answer to the depth bar
Match `references/depth-bar-sample.md` — a fully-worked sample answer that sets the standard.
Multi-paragraph; both example boxes; every term defined. The **onboarding tab** must be a real
step-by-step guide (problem in plain words → words explained → set the tools up from zero → a
one-command quickstart to run it end to end → how to read the repo in order → how to work day to day
→ what to do when stuck → following one feature end to end). The **mentor tab** is practical senior
advice (treat the AI as a fast junior, verify don't trust; plan first, small steps, tests are the
spec, ship small and often, write decisions down; protect the main branch, never commit secrets,
measure before optimising, watch cost, pin model versions).

> **On context and quality, be honest.** A context window is the chat's working memory; when it
> fills, the system compacts (summarises older turns), and answers can thin. In a consumer chat the
> model **cannot** reliably report "you are at 70%." Do not claim it can. What works: one topic per
> chat, a standing instruction to flag when answers thin and hand off, and keeping a current
> handoff/profile so a fresh chat is instantly grounded. (An AI coding agent's session does expose a
> context meter and compact/clear commands; a consumer chat does not.)

### 4. Build the HTML with the generator
Author the content as a Python data structure and render it with `assets/faq_generator.py` (clean
structure for many tabs, grouped sidebar, hash deep-links, arrow-key navigation, optional watermark).
**Set `footer` to the licence line** from `references/licensing-and-credits.md` (the internal variant
for a team FAQ; the public variant if `scope_project_faq` is `public`), built from the profile's
`{{licence_footer}}` / `{{year}}` / `{{owner_name}}` — so the page carries the `©` line. The optional
decorative `watermark` does **not** replace it; if `footer` is unset the generator writes the page but
prints a notice and the verifier will fail it. **Set `last_reviewed` to the date the facts were last
checked** (`YYYY-MM-DD`): the generator emits a machine-readable `<meta name="last-reviewed">` plus a
visible stamp, and the verifier WARNs once it is older than the staleness threshold (profile
`max_doc_age_months`, default 6) — so "refresh per milestone" is enforced, not just asked. Build the
**About & credits** panel with the first-class **`credits` block** (heading, optional intro, and
label/value rows for maintainer, licence link, and the attribution line) rather than hand-composing it
from paragraphs — keep it to the short licence line, never the full disclaimer. **Write the page to the
repository first** (the repo-first source, e.g. `docs/faq/index.html`;
`outputs/{{project_name}}-faq.html` when running in this tool). A distinctive, readable design: a
characterful display font + a readable body font + a mono font (avoid Inter/Roboto/Arial defaults and
purple-on-white). See `references/faq-method-and-question-bank.md` for how to drive the generator.

### 5. Self-evaluate, verify, present
Run the self-evaluation checklist below and the verifier:
```bash
python3 scripts/verify.py outputs/{{project_name}}-faq.html --format html --skill project-faq --profile docs/project-profile.md
```
Fix every FAIL, then present the file.

### 6. Publish (optional, repo-first — a separate step)
The repository is the source of truth; the verified page is always written there first (Step 4), and
you never author in the target. Publishing the FAQ is optional and a separate, later step. When the
owner wants it, hand the finished page to the **publish-mirror** skill, which follows
`references/render-contract.md`. The FAQ is a finished HTML page, so publish-mirror takes the
HTML-source path (`render-contract.md` Section 1a): a **portal that hosts HTML is the faithful
target** — the tabs, sidebar, and keyboard navigation survive — while a **wiki such as Confluence is
a lossy target**: it does not run the page's own code, so the live tabbed widget is not available
there. State that on the page; the per-target degradation is defined once in `render-contract.md`
Section 1a, not restated here.

---

## Quality bar (self-evaluation checklist, run before presenting)
- The newcomer test: a class-12 student / fresh graduate, new to the project, can understand what it
  is, set it up, run it end to end, and describe how the pieces fit. If not, go deeper.
- Every answer (except the glossary) has **both** an "In your project" box **and** a "Picture it in
  real life" box.
- Every answer is multi-paragraph and detailed (no one-liners).
- No flowery words anywhere (scan the banned list).
- Every planned question and sub-point is covered; the dropped-points checklist is clear.
- The onboarding tab is a real step-by-step buddy; the mentor tab is practical, not slogans.
- The context-and-quality answer is honest about what the model can and cannot self-measure.
- Tab count matches the sidebar; HTML tags balanced; deep links and arrow keys work; the watermark
  (if set) is present and non-overlapping.
- The licence `©` footer line is present in the page (`footer` was set); the watermark alone is not
  enough. The verifier fails a page/set with no `©`.
- A `last_reviewed` date (`YYYY-MM-DD`) is set, so the page carries the freshness stamp and the
  staleness check has something to read (it WARNs once the date is older than the threshold).
- No real secrets or personal data on the page: no live tokens, keys, or private emails (the verifier
  fails near-certain credential shapes and warns on softer ones). Redact before publishing; use
  placeholders and example domains in worked examples.
- Every fact traces to the repository, the profile, or a cited source; nothing invented.


**Licensing and credits (required).** The FAQ is one HTML page, so it *is* its own document set:
carry the licence footer in the page by setting the generator's `footer` (Step 4) — the `©` line in
the internal variant for a team FAQ, the public variant if scope is `public` — and include an
**About & credits** panel built with the generator's first-class **`credits` block** (carrying the
attribution line, maintainer, and the licence link). The repository also ships a `LICENSE` carrying
the warranty disclaimer. All of this is defined once in `references/licensing-and-credits.md`
(referenced, never restated); the disclaimer text lives only in the profile (`{{licence_disclaimer}}`),
and the footer/title are built from `{{project_name}}` / `{{owner_name}}` / `{{year}}`, never a
hard-coded name. The verifier fails a public page with no footer and, in CI with `--license LICENSE`, a
LICENSE that drops the disclaimer or does not name the content licence. It also runs a low-false-
positive secret/PII scan on the page (every scope) and a staleness check on the `last_reviewed` stamp.

---

*Skill version: v1.2.0 — see `CHANGELOG.md` in this folder. Earlier passes are recorded there.*

## References and assets
- `references/licensing-and-credits.md` — the licensing + credits standard; applies to every document this skill produces.
- `references/house-style.md` — the shared writing standard (read first).
- `references/faq-method-and-question-bank.md` — deriving questions, tab groups, and driving the
  generator.
- `references/depth-bar-sample.md` — a fully-worked sample answer (the depth standard).
- `references/render-contract.md` — how the finished page maps to each publish target (Step 6); the
  conversion lives here, not in this skill.
- `assets/faq_generator.py` — the reusable tabbed-HTML generator.
- `assets/project-profile.md` — copy into the repo and fill once per project.
- `assets/publish-targets.yaml` — the publish destinations manifest used by `publish-mirror` (Step 6).
- `scripts/verify.py` — run before presenting.

---

## When to use

- The ask is an FAQ, Q&A page, knowledge base, help centre, project wiki, "common questions" page, or
  a page that answers "how does my project do X and why" for newcomers and teammates.
- Enough of the project is built and decided to answer real questions — in practice, once the
  architecture and the main workflow exist (`architecture-and-decisions` output is a strong input).
- A milestone closed and the existing FAQ (if any) has a confirmed stale or missing answer — this
  skill is also the right tool for a **targeted** refresh, not only a first-time build.

## When not to use

- **Per commit.** This is a milestone artifact, refreshed per milestone, not on every change.
- **Wrong reader:** a public concepts course → `learning-track`; the deep "why is it built this way"
  design-rationale doc → `architecture-and-decisions`; a single-task how-to → `usage-guide`; deep
  contributor onboarding → `onboarding-companion`; an incident runbook → `operations-runbook`.
- **To replace a working, broader hand-authored page on the strength of one trial pass.** A full-page
  regeneration must at least match the existing page's tab/question coverage and its reading-grade
  target before it is treated as a replacement rather than a comparison (see
  `configs/external-skill-registry.json`'s `project-faq` entry for the measured 2026-08-12 trial that
  established this).

## Inputs

- `assets/project-profile.md`, filled — including `grade_target_project_faq`, `scope_project_faq`
  (`docs/project-profile.md` in this repository).
- A populated repository to answer from: README, decision records/ADRs, the stack list, day-to-day
  workflow and config files, setup steps, and security/operations notes.
- `references/house-style.md` (read first) plus `faq-method-and-question-bank.md` and
  `depth-bar-sample.md`.

## Owned outputs

`docs/faq/index.html` (or the project's equivalent repo-first FAQ path) in this repository. This
skill authors that page's content; it does not own the ADRs, the architecture docs, or any source
code it cites.

## Allowed tools

- Read anywhere in the repository, including source, ADRs, and docs, to ground answers.
- Write **only** the FAQ output file(s) it is asked to produce.
- Shell: `python3 scripts/verify.py … --skill project-faq --profile docs/project-profile.md`, plus
  read-only commands used to verify a claim.

## Forbidden actions

- Inventing a fact, tool name, capability, or number not backed by the repository or the profile.
- Editing source code, ADRs, or another skill's outputs.
- Overwriting an existing hand-authored FAQ in place without a comparison — generate to a second file
  first when a real page already exists, per the licensing-and-credits and honesty rules above.
- Publishing to a wiki or portal — that is `publish-mirror`.

## Procedure

The numbered **Workflow** above is the procedure: ground and configure → derive the question inventory
and tab groups → write every answer to the depth bar → build the HTML with the generator → self-evaluate
and verify → optionally hand off to `publish-mirror`.

## Validation

```bash
python3 scripts/verify.py docs/faq/index.html --format html --skill project-faq \
  --profile docs/project-profile.md
```

Green means: reading grade within target, no banned words, the licence footer (`©`) present, a
`last_reviewed` stamp set, no secrets/PII, every fact traceable. **Known verifier gap** (found
2026-08-12, not yet fixed upstream): `has_copyright = "©" in raw` checks for the literal Unicode `©`
character and does not recognise the `&copy;` HTML entity — a page using `&copy;` reports a false
FAIL. Read the actual footer before trusting that specific check. The repo-level gate is
`make validate` (`scripts/validate_quality_contracts.py`).

## Handoff contract

- **Consumes from the suite.** Reads `architecture-and-decisions`' decision treatments to summarise
  them in Q&A form rather than re-deriving the reasoning; does not replace that skill's output.
- **Produces for.** A reader (newcomer or teammate); optionally hands off the finished page to
  `publish-mirror` for a wiki/portal target.
- No other skill in the suite consumes this skill's raw output as an input.

## Stop conditions

- A needed fact is missing from the repository and the profile — say so rather than fabricate it.
- `verify.py` reports a FAIL that isn't a known false positive (see the `&copy;` note above) — fix
  before presenting.
- The trial-vs-existing-page comparison (when a real page already exists) shows the new draft losing
  coverage the existing page has — stop and report the comparison rather than shipping a regression.

## Examples

- This repository's own `docs/faq/index.html`, Architecture tab, "Where can I read the architectural
  decisions?" answer — grown from naming 2 of 34 ADRs to representing all 34, grouped by theme, on
  2026-08-12.

## Anti-examples

- Regenerating a whole existing FAQ page from scratch and shipping it without comparing it
  question-by-question against what it replaces — the 2026-08-12 trial on this exact page produced a
  rewrite with a missing tab and denser prose than the page it would have replaced.
