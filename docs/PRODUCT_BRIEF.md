# Quorum-AI Product Brief

**Date:** 2026-06-23
**Status:** Locked — see "Decisions" below.
**Source of truth for:** PR-1 (`PR1_COPY_LEDE_PROMPT.md`).

This brief is the source of truth for the user-facing copy, brand, and lede decisions. It is intentionally short — a Claude instance reading `PR1_COPY_LEDE_PROMPT.md` should be able to copy-paste from this file rather than re-deriving the answers.

---

## Decisions (locked 2026-06-23)

### 1. Product name: **Quorum AI** (keep)

No rename. The product is already deployed at `https://quorum-ai.fly.dev`, the name is established, and the disruption cost of a rename is higher than the upside.

- `settings.app_name` in `src/product_app/config.py` keeps `"Quorum AI"`.
- `app.title` in `src/product_app/main.py` keeps `"Quorum AI"`.
- The Fly.io URL stays `quorum-ai.fly.dev` (no redirect needed).
- `CHANGELOG.md` should record: "PR-1: copy + lede refresh; product name unchanged. See `docs/PRODUCT_BRIEF.md` for the decision rationale."

### 2. Brand lede: **"Four models, one sourced answer."** (tagline) + **"See the cost before you run."** (value prop)

The brand area in `src/product_app/templates/workspace.html` (lines 25-28) should be split into two visually distinct lines:

- **Tagline** (≤90 chars): "Four models, one sourced answer."
- **Value prop** (≤90 chars): "See the cost before you run."

Drop the current 142-character single-line copy ("Stop hopping between multiple AI chatbots. Get one sourced, synthesized answer you can trust — and see the cost before you run it").

### 3. Workspace lede (under "Workspace" h2, workspace.html line 61)

Current: "Execution uses server-configured provider access. Results are ephemeral and may be lost on refresh or restart."

Replace with two plain-language sentences. Suggested draft:

> "Quorum runs your question against four AI models in parallel, then synthesizes a single answer. Results live in your browser session and aren't stored on our servers."

(Tighten further if the brief reviewer wants a shorter version. Acceptance: anyone can answer "what does this app do, and what happens to my data?" within 5 seconds.)

### 4. Stance on AI-generated text, hallucinations, and source citations

Quorum-AI's stance, in one sentence: **"Quorum synthesizes a sourced answer from four models and is honest about what each model contributed and where the sources came from. It is decision support, not a substitute for professional advice in high-stakes domains."**

The synthesis tooltips (workspace.html lines 1045-1059 area, JS lines 1051-1059) already align with this stance. PR-1 should keep the tooltips, tighten the wording, and add the "see the cost before you run" message into the cost callout so the workspace lede and the cost gate are consistent.

### 5. Three supporting copy points (reused across surfaces)

These three lines should appear, in spirit, on the workspace lede, the cost callout, and the synthesis caveats:

- **"see the cost before you run"** — value prop; reinforces trust.
- **"results live in your browser session"** — honesty about ephemerality, replaces the jargon "execution uses server-configured provider access".
- **"decision support, not professional advice"** — the mandatory caveat for high-stakes domains.

---

## Things this brief does NOT decide

- **The new synthesis copy** (Item 5 in PR-1) — that's a follow-up after the brand decisions are in.
- **The OpenAPI metadata** (Item 6) — review after the brand copy is final.
- **The polishable findings from the walkthrough** (M-4, M-6, L-2, L-3, L-4) — these are not in PR-1 scope.

## Reference

- Walkthrough output: `/tmp/qai_walkthrough/REVIEW.md` — synthesized PR-1 priority stack
- Walkthrough report: `/tmp/qai_walkthrough/REPORT.md` — 12 raw findings
- PR-1 prompt: `PR1_COPY_LEDE_PROMPT.md` (in repo root)
- Prior cost-cap work this builds on: see memory `quorum-workstream-3-honesty`
- Walkthrough priority stack memory: `quorum-walkthrough-landed-2026-06-23`
