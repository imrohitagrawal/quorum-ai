# Session handoff — 2026-09-04

Written after merging PR #436 (ADR-0098) and verifying it in production.

Every claim below is marked **MEASURED** (I ran the command this session and
read its output) or **INHERITED** (from a document, not re-run). Rule 11's
decay rate applies to the inherited ones: roughly half of what a handoff
asserts does not survive contact with the tree. Re-check before building on it.

---

## What shipped, and where production is

**MEASURED.** `main` is `82cb5a6`. Production `/status.build_sha` is
`82cb5a654a509efb30fa6a1831e824c6496622bb` — byte-identical. The Deploy **job**
(not the run rollup) reported `conclusion=success`; two sibling Deploy runs were
`cancelled` by concurrency dedupe, which is this repo's normal pattern. The
served `/static/app.js` was fetched and checked: honest disclosure present (1
occurrence), the false claim absent (0), origin tag shipped (7), shared
predicate live (5).

ADR-0098 fixed two false statements the product was making to users:

1. The numeric trust score was unlocked behind *"Citation support was checked by
   an independent judge model"*. The judge never receives the cited pages.
2. A page a real web search returned was rendered as a Quorum placeholder —
   non-clickable, badged "fallback stub", exported as "not a real source", and
   counted as zero while the prose said "No model returned visible source
   references" with four real pages on screen.

**The citation-coverage arithmetic is deliberately unchanged.** A reviewer
verified this by executing a full run on `origin/main` and on `HEAD` and diffing
the served payload: the only differences are the provider label and one
sentence. `citation_coverage`, `quality_checks`, `agreement` and the whole
`RunEvaluation` (including `trust`) are byte-identical. Whether retrieved
evidence *should* raise the trust band is deliberately still open.

---

## THE THING THE OWNER ASKED TWICE — the judge cannot read its sources

The judge receives, and only receives: the question, a `SOURCES:` block built as
`f"[{i}] {title} :: {url}"`, the model answers, and the synthesis sections.
**MEASURED:** nothing in `src/` resolves a cited URL — the only outbound HTTP
call sites are the model catalog, the OpenRouter call, the Tavily search, the
API-key probe and the feedback audit. None takes a URL from a `SourceReference`.

So it can check **grounding** (do markers point at listed sources) and internal
consistency. It **cannot** check support — whether the page backs the claim.
The failure it cannot catch: a model invents a plausible URL, cites it, and
states something false. Grounding passes.

**Two routes, and the fork is a real decision:**

- **Route A** — `:online` already returns the passage text the model read. Wire
  the judge to it. No fetcher, no new network calls, no SSRF surface.
- **Route B** — Quorum fetches the cited URLs itself. Needs a fetcher, a timeout
  budget, and a security review, because these are **URLs a model chose**.

Which one is correct is decided by measurement 3 below. **Route B has never
been designed**, and this work is **tracked in no issue** — the only open issues
are #290, #268, #105. That is why it keeps slipping. File it.

**The coupling nobody has written down: this collides with #268.**
**MEASURED:** the judge's input is tightly bounded today —
`JUDGE_MAX_SOURCE_LINES = 32`, `JUDGE_MAX_SOURCE_TITLE_LEN = 300`,
`JUDGE_MAX_SOURCE_URL_LEN = 300`, so the source block is kilobytes. Put real
page content in there and that bound is gone, and #268 says in its title that
`max_cost_usd` bounds every call's OUTPUT and **nothing bounds its INPUT**. A
single cited page can be 100KB. **Judge source access must ship with an input
bound, or it widens exactly the exposure #268 was filed for.**

---

## The window's three measurements — status, corrected

The owner believed these were already measured on a recent paid run. They were
not, and the reason is a date:

**MEASURED.** `last_live_charge_at` is `2026-09-01T21:02:46Z`. Peer critique
landed on `main` on **2026-09-03** (`5aed777`, `6d13643`). The last paid run
predates the feature by two days, and that Sep-1 window was opened for issue
**#268** (injected-token bounds across three question shapes) — a different
measurement. ADR-0093 states it directly:

> *"No critique call has ever run, so every per-model number this design would
> expose is UNVERIFIED; the first live run after #290 ships is what produces
> them, and that same run is what unblocks W3."*

| # | Measurement | Status |
|---|---|---|
| 1 | What eight critique calls cost | **Never measured.** No critique call has ever run in production. Blocks W3/ADR-0094 |
| 2 | Does `DEBATE_ROUND_MAX_TOKENS=2000` still fit | **Measured, then invalidated.** 7 of 8 calls returned `finish_reason: "length"` — real, from the #290 probe. ADR-0096 then made round 2 return a critique AND a revised answer, so the figure is stale in the WORSE direction |
| 3 | Do `:online` annotations carry passage CONTENT | **Never measured.** Appears once in the repo, as an open question. Decides Route A vs B above |

**TRAP, inherited from ADR-0093 and worth keeping:** there are TWO unrelated
"seven of eight" figures. One is `finish_reason: "length"` (measurement 2). The
other, in `docs/analysis/2026-08-26-b3-timeout-probe.md:87`, counts wall-clock
timeout exceedance. I verified this session that they are genuinely distinct.
Do not cite one for the other.

---

## The agreed plan, in order

The owner proposed running the paid run AFTER the copy and money fixes so it
validates them too. That is right, and specifically because of PR C: run first
and the receipt shows the known-wrong attribution; run after and the same ~$0.06
validates both the cost measurement and the fix to how it is displayed.

1. **PR B — the mechanism copy.** Unblocked. Front door.
2. **PR C — the money attribution.** Changes what the run's receipt shows.
3. **File the judge-source-access issue**; write Route B's design (fetcher,
   security, input bound) on paper while it is off the critical path.
4. **Phase 0 — harvester at $0**, validated against SIMULATED runs. Must capture
   judge token counts as well as the critique correlator. Rationale: if the sink
   does not capture what is needed, the money is spent and the window is not
   repeatable.
5. **Validation run (~$0.06)** — confirms the sink captured everything AND
   settles Route A vs B by inspecting one `:online` response.
6. **Build judge source access** on the decided route, shipping an input bound
   with it (#268).
7. **Three varied runs** — critique cost and judge-with-sources cost measured
   together, on final code.

Step 5 precedes step 6 deliberately: it is a run being paid for anyway, and it
stops Route B being built blind and then turning out to be unnecessary.

---

## Item 0 — what remains of the UI-truthfulness work

PR A is **DONE and in production**. Still outstanding, from the same audit:

- **PR B — mechanism copy.** `workspace.html` still says *"A moderator model
  audits them over two rounds"* (no moderator runs) and *"Peer critique between
  the four models is planned, not yet built"* (it is built, enabled and billed).
  Both are **byte-exact pinned in the blocking e2e lane**, so each fix must
  invert its own pinning gate in the same commit, with a positive partner.
  ADR-0032 is still `Accepted` and MANDATES the moderator copy — retiring it
  needs an ADR that supersedes it.
- **PR C — money attribution.** The estimate's `Synthesis` row is
  `2 x debate_round_cost + synthesis_cost`, and `debate_round_cost` sums over
  all four slot models — so on the approval screen the row named `Synthesis`
  holds every critique dollar and the four slot rows hold none. ADR-0095 already
  records this and says the resolution is **an estimate-side note in the UI, not
  a rename**.
- **The run summary still says** *"Roughly N% of those answers carried at least
  one visible source reference."* ADR-0098 quotes this as THE contradiction and
  deliberately did not fix it — it lives in the consensus/divided headline
  builders, and rewording a line the verdict band leans on has its own blast
  radius. Recorded in ADR-0098's "What this does NOT fix". Natural PR B work.
- **The `<80%` coverage rule still fires** on runs whose evidence was entirely
  retrieved, because Decision 2 froze the arithmetic. Also recorded, not fixed.
- **Dead markup:** `.panel.panel-section { display: none }` hides `#model-grid`,
  `#debate-output`, `#synthesis-output`. **MEASURED in a browser this session:**
  `#model-grid` present, `isVisible: false`, computed `display: none`; four
  `.source-list` elements, all invisible. Four false moderator claims live in
  there. The prior handoff's instruction stands: **DELETE the dead markup and
  its pinning test rather than rewording.**

Also open, unrelated to Item 0: **#290**, **#268**, **#105**.

---

## Traps this session paid for

- **`.python-version` — FIXED this session, but understand why.** There was no
  such file, so a fresh worktree's `uv sync` built a **3.14.5** venv while CI
  runs **3.12**. A whole round of gates was run on the wrong interpreter.
  **MEASURED:** without the file `uv python find` returns 3.14; with it, 3.12.
- **The 429 database poisons local e2e.** After repeated local runs `/ui` starts
  returning 429 and it presents as ~8 unrelated spec failures — including
  previously-green ones — with `[data-view="composer"]` not found. Fix:
  `rm -f .data/feedback_events.sqlite3` (gitignored). Cost me one false diagnosis.
- **`tests/code_text.py` stripped NO JavaScript comments until today.** It
  tokenized `.py` and treated everything else as `#`-commented, so on `app.js`
  it returned text still holding **2883** `//` comments. Any guard test written
  against it was defeatable by hiding a decoy in a comment. Now fixed, with a
  `node --check` sweep and a direct keyword-regex test.
- **A `node --check` sweep over the repo did NOT catch the bug it was written
  for.** With the fix reverted the sweep stayed green, because no file this repo
  owns writes a regex after a keyword. A negative sweep over a population that
  cannot contain the defect proves nothing — it needs a positive case beside it.
- **`gh run list --commit <SHA>` returned `[]`** for the merge SHA this session;
  `--branch main` and matching on `headSha` worked. The older workaround is
  still needed sometimes.

## How the review went, because the pattern matters

Four rounds, ten reviewer reports. Rounds 2, 3 and 4 each found that the
PREVIOUS round's fixes introduced new defects — three of them mine, including
one test made strictly weaker than the one it replaced, and a helper written to
fix vacuous tests that corrupted 763,871 characters of a vendored bundle.

Reviewers defeated the guard tests **five different ways** while fully restoring
the product defect: commented-out call sites, a decoy in a `//` comment, a decoy
in a template literal, operand reordering, and a more-specific CSS selector.
Each fix closed the demonstrated CHANNEL and left the CLASS intact.

**The lesson, and it is the transferable one: pin the USE, not the constant you
just added.** Assert the call site over comment-stripped code; pin copy by exact
equality; keep the coarse whole-file ban alongside the precise pin; require
exactly one regex match, never the first. And match the gate to the surface's
reach — one REQUIRED finding was about markup with `display: none` that no user
can see, where a text pin is proportionate and an e2e test would be driving
dead code.

The product change was correct from round 1. Every round was spent making the
tests able to prove it.
