# House style — shared writing standard for project documentation

This file is the shared standard every documentation skill in this suite follows. It is
**internal build guidance**: it tells you *how* to write. It must never be copied into the
documents a reader sees. Read it before writing, and keep it open while you write.

Two ideas govern everything here:

1. **Student-first is the clarity floor.** Write so the least-experienced intended reader can
   follow every sentence. If a beginner understands a page, no one is shut out. Experts are
   served by optional depth layers, never by raising the floor.
2. **Honesty over polish.** Teach what is true, mark what is not yet built, label what is
   illustrative, and never invent a fact, a number, or a capability.

---

## 1. Read the project profile first

Every skill ships an editable `project-profile.md`. Before writing anything, find the live
profile for this project (look for `docs/project-profile.md`, `PROJECT-PROFILE.md`, or a path the
skill names). If none exists, copy the skill's template into the project, fill in what you can read
from the repository, and ask the owner to confirm the rest. The profile is the single place that
holds the owner, brand, contacts, licence, palette, audience targets, banned-word additions, and
the public-vs-internal setting. Read those values from the profile; do not hard-code them here.

---

## 2. Plain, simple English

- Short sentences. One idea per sentence. Prefer the common word over the impressive one.
- **Banned flowery words** (and close relatives): *leverage, seamless, robust, delve, supercharge,
  unlock, harness, elevate, cutting-edge, game-changer, effortless, empower, revolutionise/
  revolutionize.* The profile may add more.
- If a real technical term is genuinely needed, **use it and define it the first time it appears**
  — do not drop the information to avoid the word. A defined term is clarity; an undefined one is a
  wall.
- Active voice. Address the reader as "you" where natural.
- Do not pad for length. Depth comes from covering what matters, not from more words.

---

## 3. Audience and the public-vs-internal switch

The profile sets two things that change how you write:

- **Primary audience and reading-grade target** (e.g. grade 1–3 for a usage guide, grade 8–9 for a
  student-facing learning track). Write to that floor and check it (Section 11).
- **Audience scope: `public` or `internal`.**
  - **`public`** — the document stands alone as project documentation for outside readers. Apply the
    public-output rules (Section 8): no author motivation, neutral audience naming, and **no
    internal references** — do not name the tools used to build the project, the build process, or
    internal working files. If the project was built with AI assistance and that must be stated, use
    exactly one neutral factual line and no career or motivation framing.
  - **`internal`** — the document is for the team, new joiners, operators, or contributors. You
    **may** name the day-to-day workflow and the tools people will actually use, because they need
    them to do the job. Plain English, honesty, accessibility, and IP rules still apply in full.

When a skill produces both kinds (for example a team-facing FAQ with a public overview), label each
section's scope and apply the matching rules.

---

## 4. Honesty: built vs designed, and citing vs labelling

- **Built vs designed.** A project is built in stages. Teach the design and the ideas, and mark
  anything not yet finished. Put a `[designed, not yet built]` marker on any specific a reader would
  otherwise assume is already live. Never bury current build status in prose — link to the live
  status (roadmap, decision log, issue tracker) instead, so the teaching does not go stale.
- **Illustrative numbers.** Any sample figure whose final value is decided later (a chunk size, a
  threshold, a timeout) is labelled **"proposed, not yet locked."**
- **Cite field facts; label project facts.** General facts about software and the field are cited to
  a credible, verifiable source (author or title, year, and a stable link where one exists). Facts
  specific to this project are labelled as such and tied to the repository or the decision record.
- **Never fabricate.** If a fact, number, tool name, or capability is missing, say so plainly. A
  fact-check pass (Section 10) catches any claim that cannot be backed by the project or a cited
  source.

---

## 5. Teach the failure modes, not only the concepts

For every concept or choice that matters, do not stop at "what it is." Name the concrete things that
go wrong and why, give a short worked example, then show how the design addresses them. The bar is
question-and-example level. A reader who only learns the happy path has not understood the thing;
the value is in the edge cases, the trade-offs, and the failure modes.

---

## 5a. Lock the registers before writing (consistency across pages)

A multi-page document's worst failures are not bad sentences — they are inconsistencies *across*
pages: an analogy that teaches the wrong shape and is then reused, one word that means two things in
different pages, a safeguard stated as in-force on one page and disowned on another. These propagate:
a wrong choice made once reaches every page that builds on it. They are cheap to prevent and
expensive to chase after the fact, so decide them **before** writing and record them (in the project
profile, or a short `docs/<set>/registers.md`):

- **Analogy register** — one analogy per concept, its exact *shape*, and its direction (higher- or
  lower-is-better). Test each analogy against the real idea before adopting it; a two-point comparison
  must not be drawn as a slow trend, and direction must not invert.
- **Term register** — the canonical word for each concept, and any word reserved to one meaning (so a
  term that has a specific later sense is not used loosely earlier).
- **Honesty/maturity register** — the built / `[designed, not yet built]` / measured-vs-illustrative
  markers (Section 4) and any maturity ordering, owned by one page and cross-linked, never restated
  verbatim.

Then check **each page** against the registers as you write it (a step in the authoring loop,
Section 10). The independent confirmation that the registers actually held across the whole set is the
job of the **doc-critic** skill's whole-document pass — not a same-context author loop, which is
structurally blind to cross-page drift.

---

## 6. Two examples, where the skill calls for it

Where a skill specifies it (the FAQ and most explanatory pages), every explanation carries **two**
worked examples, each in its own clearly marked box:

- **"In your project"** — the real, specific example from this project.
- **"Picture it in real life"** — an everyday analogy anyone relates to, with no jargon.

Both, every time. A definitions list (a glossary) is the only place this does not apply.

---

## 7. Visual language

Diagrams are part of the explanation, not decoration. Use the profile's palette (it defaults to the
values below) consistently across every diagram, sketch, and animation.

**Default palette** (override in the profile if the project has its own brand):

| Role | Hex |
|---|---|
| Primary / system steps (fill) | `#4338CA` (indigo) |
| Primary border | `#3730A3` |
| Success / outcome (fill) | `#15803D` (green) |
| Input / neutral (fill / text) | `#E2E8F0` / `#1E293B` |
| Lines, arrows | `#64748B` (slate) |
| Title text | `#0F172A` |
| Secondary text | `#334155` |

Font for text inside images: a permissively-licensed clean sans (DejaVu Sans / Helvetica / Arial
family).

**Three diagram registers, one palette:**

1. **Diagrams as code (primary).** Mermaid for flow, sequence, state, and C4-style structure;
   versioned in the repo. Paste this theme line at the top of every Mermaid block so colours match:
   ```
   %%{init: {"theme":"base","themeVariables":{"primaryColor":"#4338CA","primaryTextColor":"#ffffff","primaryBorderColor":"#3730A3","lineColor":"#64748B","fontFamily":"Helvetica, Arial, sans-serif"}}}%%
   ```
   For C4 architecture diagrams, Structurizr is the secondary tool; export to images recoloured to
   the palette.
2. **Hand-drawn conceptual sketches** (Excalidraw) — friendly, student-facing concept pictures.
   Export SVG (preferred) and PNG, commit the source, embed with alt text and a one-line description.
3. **Animated GIFs** — one per topic, only when motion adds meaning (a purely structural diagram is
   better static). Rules: the complete diagram is the **first frame** (so non-animating viewers see a
   clean image); a subtle reveal; a **long hold** on the finished picture; a gentle fade before the
   loop; always ship a **static PNG fallback** and **descriptive alt text**.

**Accessibility (required, not optional):**

- **Alt text and a static fallback** on every diagram and GIF.
- **Contrast** passes WCAG 2.2 AA (at least 4.5:1 for normal text, 3:1 for large). Check every new
  asset with a contrast checker before shipping.
- **Never colour alone** (WCAG 1.4.1). Meaning must also be carried by a label, icon, or shape. For
  pass/fail use **✓/✗ plus a word** ("✓ Passed"), never colour by itself.
- **Colour-blind-safe data visualisation.** The brand palette is for identity/chrome, where labels
  carry meaning. When a chart encodes *categorical data*, do not use the brand palette for the
  categories; use a recognised colour-blind-safe palette — **Okabe–Ito** (8 colours) or a
  ColorBrewer colour-blind-safe scheme — **plus direct labels and patterns/textures**, never a
  colour-only legend. Test with a colour-blindness simulator before shipping.
- **Structure for assistive tech** (HTML outputs): one `h1`, a sensible heading order, a `lang`
  attribute, link text that makes sense out of context (not "click here"), and a logical reading
  order.

---

## 8. Public-output rules (apply when scope is `public`)

- **No author intent or motivation.** Do not write why the author built it, or frame it around jobs,
  hiring, a portfolio, or "building in public."
- **Neutral audience naming.** Never "MAANG/FAANG"; use "Big Tech / Tier-1" or a plain description.
- **No internal references.** Do not name the build tools, the assistant used, internal working
  files, or the build/meta process on a public page.
- Use "Section N", not the section-sign symbol, in body text.

---

## 9. Intellectual property and trademarks

- **No third-party text reproduced.** Paraphrase and cite. Any unavoidable quote is **under 15
  words** and attributed.
- **All diagrams and images are original** work created for this document; text in images uses only
  permissively-licensed fonts (DejaVu).
- **No copyrighted screenshots, product UI, or logos** without rights — draw an original diagram
  instead. (This matters when later pages mention tools by name.)
- **Trademarks** are used nominatively (only to refer to the thing) and **acknowledged** on an
  about/credits page or footnote, e.g. naming the owner of a registered mark.
- The licence and attribution line come from the profile (it defaults to a Creative Commons licence
  with the owner's name and a link).
- **Licensing and credits are mandatory on every document this suite produces — see
  `references/licensing-and-credits.md`.** Every page carries the licence footer (the © line); each
  document set ships a `LICENSE` file and an **About & credits** page that credits the owner with
  their GitHub and LinkedIn and gives the attribution line to use on reshare; and the warranty/
  liability disclaimer from the profile appears in the LICENSE. Use the **public** variant when
  `scope` is `public` and the **internal** variant when it is `internal`. The verifier enforces the
  footer as a hard failure on public pages, so this is not optional.

---

## 10. The authoring loop (run per page or batch)

Write, then criticise as a fresh reader, then verify. In a chat these are sequential passes by one
writer plus the owner as the independent gate; in an agent with isolated sub-agents they become
separate critics with no anchoring. Order:

1. **Writer** — draft to the skill's template and this house style.
2. **Beginner critic (the clarity gate, priority 1)** — re-read as the least-experienced intended
   reader. Every term defined; no unexplained jargon; analogies land; nothing assumed. Nothing passes
   until this is clean.
3. **Other-field critic** — bridges from everyday or professional life; "why it matters" is explicit.
4. **Expert critic** — technical claims are correct, complete, and not oversimplified into something
   false; failure modes are named; there is a real escape hatch to depth.
5. **IP / copyright critic** — no third-party text, images, or logos; trademarks nominative and
   acknowledged; sources cited and verifiable; assets original.
6. **Verifier** — run the automated checks (Section 11); built-vs-designed honesty correct; links and
   assets resolve; reading time honest; formatting renders.
7. **Owner review** — calibrate tone and depth early (a few iterations), then spot-check.

---

## 11. Verify before presenting

Each skill ships `scripts/verify.py`. Run it over the documents you produced **before** presenting
them. It checks: banned flowery words; (public scope) internal-reference and tool-name leaks;
author-intent/motivation; over-long quotes (possible reproduced text); raw HTML outside code fences
(Markdown); relative-link and asset resolution (Markdown); a basic structural check (HTML); and a
**reading-grade estimate** (Flesch–Kincaid) against the profile's target. Treat a failed grade as a
signal to simplify, not a number to game. The verifier enforces checkable rules; clarity is still the
critic's job.

```bash
# The skill name resolves the grade target and scope from the profile (single source of truth):
python3 scripts/verify.py <path-to-doc-or-dir> --format md   --skill <skill-name> --profile docs/project-profile.md
python3 scripts/verify.py <path-to-doc-or-dir> --format html --skill <skill-name> --profile docs/project-profile.md
# A --grade-target / --scope flag still overrides the profile when you need it.
```

---

## 12. Industry practices folded in

These lift the suite from "good house style" to current documentation practice. Apply the ones a
skill points to.

- **Diátaxis — write in the right mode.** Documentation serves four distinct needs and they should
  not be blended on one page: **tutorials** (learning-oriented, "teach me"), **how-to guides**
  (task-oriented, "help me do X"), **reference** (information-oriented, "tell me the facts"), and
  **explanation** (understanding-oriented, "help me understand why"). Each skill states which mode it
  is. Keeping the modes apart is the single biggest structural win in modern docs.
- **Quantitative readability.** Do not rely on "feels simple." Set a Flesch–Kincaid grade target in
  the profile and check it (the verifier computes it). Simplify until you hit it.
- **Docs as code, kept in lockstep.** Source the docs in the repository, versioned in Git, reviewed
  like code. Where a document describes a contract, an interface, or a number that lives in the code,
  add a check (a pre-commit hook or a CI gate) that fails when the code changes without the doc, and
  stamp each page with a **last-reviewed date**. A doc that drifts is worse than no doc. This suite
  ships that gate: see each skill's `ci/` folder for a ready pre-commit hook and CI workflow that run
  the verifier.
- **Inclusive, precise language.** Beyond the banned-words list, avoid metaphors that exclude or
  alienate; prefer plain technical terms (for example "allowlist/denylist"). Light touch, applied
  where it is easy.
- **Version the documents.** Keep a short changelog for the documentation set itself: what changed,
  when, and why, so readers and reviewers can see its history (Keep a Changelog format). Each skill in
  this suite is itself versioned this way — see its `CHANGELOG.md` — and the documents it produces
  should carry their own changelog too.
- **Information scent.** Front-load the key point of each section; use meaningful, scannable
  headings; let a reader find the one thing they came for without reading everything.
- **Localisation-readiness.** Short sentences and few idioms make a document far cheaper to translate
  later, and clearer for non-native readers now.
- **Close the feedback loop.** Every reader-facing page ends with a short feedback prompt, and there
  is a place to collect and act on what comes back — clarity for the first-time reader is the goal,
  and corrections are welcome.
