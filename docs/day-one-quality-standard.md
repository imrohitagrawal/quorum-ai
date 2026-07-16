# Day-One Quality Standard

A reusable standard to install on **day one of any new project**, so quality
practices are **mechanically enforced** instead of depending on anyone
remembering to apply them.

It exists because of a hard lesson: on this project we repeatedly shipped UI/UX
bugs (raw Markdown in rendered output, a non-monotonic run timer, a cramped
transcript layout, empty citations, a silent simulation fallback) even though the
knowledge to prevent them was available the whole time — in testing skills, in
`AGENTS.md`, and in chat. The bugs recurred because that knowledge lived **above
the enforcement line**: it was influence, not a gate.

---

## The core principle: the durability hierarchy

```
chat instruction            ← evaporates; no persistence, no trigger
skill I must remember        ← opt-in; nothing invokes it on a change
memory                       ← persistent hint, still only influence
AGENTS.md / CLAUDE.md        ← always loaded, strong influence — NOT a guarantee
───────────────────────────── the line between "influence" and "enforcement"
tracked hook  (local, fast)  ← runs on every change — ONLY IF its settings file is tracked
CI test       (shared gate)  ← runs for everyone regardless — the real enforcement
```

Everything **above** the line depends on a human or an agent *choosing* correctly
in the moment. Everything **below** the line runs regardless. A standard only
holds if it lives **below the line** — as real tests in CI, optionally backed by a
hook. Prose (in chat, a skill, memory, or even AGENTS.md) is necessary context but
is **never** sufficient enforcement.

**Critical caveat about hooks:** a hook is below-the-line only if the settings
file that defines it is **tracked in git**. In many repos `.claude/` is
gitignored (it is in quorum-ai), so a `.claude/settings.json` hook is
**LOCAL-ONLY** — not shared, not in CI, not on a teammate's clone. Treat the hook
as a local fast-feedback convenience; the **shared, authoritative gate is CI**. To
make a hook shared you must deliberately un-ignore its settings file.

Corollary: to make a practice **automatic on every change for everyone**, it must
be a **CI test** (a local hook automates it only on the machine whose tracked
settings define it).

---

## The day-one prompt

Paste this at project kickoff. Its job is to **convert itself into permanent
machinery** — once the CI gates and hook exist, they enforce the standard no
matter what any future prompt says or forgets.

> **"Before any feature work, install quality-enforcement machinery as the first
> deliverable and treat it as a blocking gate for everything after.**
>
> **1. Working order is verify → implement → document, always.** Confirm ground
> truth (read the code, run the cheap check, look at the real output) BEFORE
> implementing. Never assume → implement → verify. Document decisions in the
> repo, not chat.
>
> **2. Enumerate this project's quality dimensions** — at minimum: correctness,
> UI/UX rendering, security (secrets / authz / injection), cost & resource
> guardrails, API / schema contracts, accessibility, data privacy,
> observability & health, and deploy / release safety. State which apply.
>
> **3. For EACH applicable dimension, install a mechanical gate below the
> influence line:** a **real test** exercising real behavior / real providers
> (not mocks or clean fixtures), wired into **CI to run on every PR**, plus —
> where the practice must be automatic on every relevant change — a
> **`settings.json` hook**. For UI/UX specifically: a realistic golden fixture,
> visual snapshot tests (`toHaveScreenshot`) per view, and global rendering
> invariants (no raw markdown, no overflow, monotonic timers / counters);
> rendered pixels + real behavior are the source of truth.
>
> **4. Prove every gate:** it must go **RED** on a deliberately-introduced defect
> in that dimension and **GREEN** when fixed, before setup is 'done'. A gate not
> proven red is assumed broken.
>
> **5. Define 'done' by the gates.** No change is complete until its dimension's
> gate exists, covers the change, and passes — and for anything user-facing,
> until you have captured and **visually reviewed** real-shaped output.
>
> **6. Write the standard and the dimension→gate map into AGENTS.md**, pointing
> at the relevant skills — as context, not as the enforcement.
>
> **7. Never assume a capability works until a test exercises it against reality;
> flag anything unverified explicitly."**

---

## Dimension → gate map (fill in per project)

The **In CI?** column is the authoritative gate; **Hook?** is an *optional local*
speed-up that only helps on a machine whose settings file is tracked (see the
hook caveat above) — never a substitute for the CI column.

| Dimension | Real test (not mocked) | In CI? (gate) | Hook? (local only) | Proven red? |
|---|---|---|---|---|
| Correctness | unit + integration on real logic | ✅ | — | |
| **UI/UX rendering** | visual snapshots + global invariants vs golden fixture | ✅ | optional, on UI-file change | |
| Real integration | one smoke against the actual backend (free/deterministic mode), not `page.route` mocks | ✅ | — | |
| Security | secret scan, authz tests, injection/XSS/CSP tests | ✅ | optional, on secret/auth files | |
| Cost / guardrails | estimate vs measured reconciliation; hard-cap cannot be breached | ✅ | — | |
| API / schema contract | generated-schema-in-sync check | ✅ | — | |
| Accessibility | axe (or equivalent) on every view | ✅ | — | |
| Data privacy | no PII in logs/URLs; redaction tests | ✅ | — | |
| Observability / health | `/health`, `/ready`, structured logs, error reporting wired | ✅ | — | |
| Deploy / release | deploy gated on green CI for the tested SHA; post-deploy smoke | ✅ | — | |

---

## UI/UX specifics (the slice most often skipped)

A driver like Playwright is **not a judge** — it only checks what you assert, and
asserting DOM structure on clean mocked data is blind to how real output renders.
So the UI gate needs three things a normal functional test lacks:

1. **A golden realistic fixture** — real, messy, production-shaped output
   (Markdown headings, `**bold**`, `1./2.` lists, bare URLs, long paragraphs,
   empty-state cases), captured once from a real run and committed. Every view
   renders against it.
2. **Global rendering invariants** — one test that walks the *entire* rendered
   DOM of each view and asserts class-wide truths, so you can't "forget a
   surface": no text node contains literal `##`/`**`/leading `1.`; no element
   overflows its container; any elapsed/counter readout is monotonic across a
   scripted poll sequence.
3. **Visual snapshot tests** (`toHaveScreenshot`) per view against the fixture —
   a human reviews the baseline; regressions surface as a pixel diff. Generate
   baselines in CI's own container, set a sane `maxDiffPixels`, and **mask
   dynamic regions** (timers, run IDs) to avoid flakiness.

**Definition of done for any UI change:** its affected views have visual snapshot
tests against the fixture; you have captured and **visually reviewed** a
screenshot of each with real-shaped data; the invariants pass. Rendered pixels +
real behavior are the source of truth — never DOM assertions or mocked JSON
alone.

---

## Why this breaks the cycle (and a chat prompt alone does not)

A chat prompt is above the line and evaporates — but *this* prompt's entire job
is to build the below-the-line gates as the first deliverable. Once they exist,
they run on every PR and every relevant change **regardless of any future prompt,
memory, or attention.** The prompt is a one-time bootstrap that installs durable
enforcement, then its own persistence stops mattering. Three properties make it
airtight:

- **Front-loaded** ("before any feature work") — the gate exists before there is
  anything to slip past it.
- **Proof-of-gate** (red-on-defect) — a hollow/no-op suite can't masquerade as
  coverage.
- **Done defined by the gate** — completion is contingent on the machinery, not
  on discretion.
