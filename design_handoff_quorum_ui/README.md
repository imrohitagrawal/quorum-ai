# Handoff: Quorum — Release 1 UI

## Overview
Quorum is a public web app that sends one question to four configurable frontier AI models (via OpenRouter), runs two structured critique/debate rounds, and returns a synthesized answer that separates consensus, disagreement, source support, uncertainty, and recommendation — with an explicit estimate → confirm → block cost workflow before any provider spend.

This package hands off the approved Release 1 UI. It was designed against, and cross-checked with, the `quorum-ai` repo specs: `docs/01-product-brief.md`, `docs/10-functional-requirements.md` (FR-001…013), `docs/12-acceptance-criteria.md` (AC-001…036), `docs/22-api-contract.md`, `docs/29-state-machines.md`, `docs/30-ux-design.md` (incl. the 2026-06-17 correction), `docs/31-accessibility-plan.md`, `docs/33-content-design.md` (COPY-001…006), `docs/11-non-functional-requirements.md`.

## About the Design Files
The files in this bundle are **design references created in HTML** — high-fidelity prototypes showing intended look and behavior, **not production code to copy directly**. The task is to **recreate these designs in the quorum-ai codebase's existing environment and patterns** (the `/ui` workspace, its templating/framework, and its already-implemented accessibility scaffolding — skip link, `fieldset`/`legend` model grouping, polite live regions). `support.js` is the preview runtime for the `.dc.html` file only — never ship it.

Open `Quorum Final Review.dc.html` in a browser. It contains all screens at 1440px width, labeled 01–08. Sections marked with dashed "spec note" tags are annotations for you, not UI.

## Fidelity
**High-fidelity.** Colors, type, spacing, radii, copy, and states are final and approved. Recreate pixel-faithfully with the codebase's stack. The HTML file is the source of truth for any measurement not listed here.

## Screens / Views

### 01 Landing (anonymous / empty state)
- **Scope note:** per the UX correction (2026-06-17), R1's first screen is the workspace (02); this landing is the anonymous/empty state of `/ui` and can ship later as a marketing front. Do not block R1 on it.
- Header 64px: green Q tile (30px, radius 8) + "Quorum" wordmark (650 weight, 17px, ink); right: "How it works" text link + "Open the workspace" outline button.
- Centered 800px column: green uppercase eyebrow (12.5px, letter-spacing 0.14em, #0E6B50) "Four AI models · two debate rounds · one sourced answer"; serif H1 52px "Ask once. Let four minds argue it out."; body 17.5px #565C66.
- Composer teaser card (white, radius 18, shadow): placeholder question; footer row = mono price "≈ $0.05–0.20" + "· you approve the estimate first — hard cap $0.25/run" (one line, `white-space: nowrap`), "Estimate" outline + "Run the debate →" **ink** button.
- Sample-question chips (pill, 40px): active chip = green 1.5px border + green dot; rest neutral.
- Preview strip: green "PREVIEW" badge + one-line result summary. Disclaimers row: 3 pills (decision support / no sensitive data / ephemeral).

### 02 Composer (workspace, `draft` state) — FR-001, FR-003, FR-004; AC-005…008; COPY-001/002
- Single centered reading column on cool paper #F6F5F2. Header: logo + "Workspace" + ◐ theme toggle.
- Privacy warning (amber panel, COPY-001) always visible above the question field.
- Question field: white card, label "YOUR QUESTION" + mono char counter "163 / 20,000".
- High-stakes gate (COPY-002): appears **only when a safety topic is detected**; red uppercase label "DECISION SUPPORT ONLY", body text, and an explicit acknowledgement checkbox "I understand this is not professional advice." **Run stays disabled until checked.** Send acknowledgements as `safety_acknowledgements[]` on estimate + create.
- Four model slots (2×2 grid): avatar circle, display name, mono OpenRouter ID (`openai/gpt-4o-mini`, `anthropic/claude-haiku-4.5`, `google/gemini-2.5-flash`, `deepseek/deepseek-chat-v3.1`), per-model mono estimate, ▾ swap from live catalog (`GET /v1/models/defaults` + catalog). Unknown IDs → field-level error naming the slot (see 07). Duplicates allowed but visibly flagged.
- Footer: total estimate + "Estimate & run →" ink button; one-run-at-a-time notice.

### 03 Cost gate (`cost_review`) — FR-005; AC-009/010; COPY-003/004; `POST /v1/query-runs/estimate`
- Itemized estimate **by model AND by stage** (initial / round 1 / round 2 / synthesis), mono amounts.
- Threshold rail: $0 → runs on approval · $0.15 → explicit confirmation · $0.25 → blocked, no override. Maps to `threshold_action: proceed | confirm_required | blocked` + `reasons[]`.
- Confirm band (this mock: $0.19): reason sentence + "Approve $0.19 & run" ink button + "Change models" secondary. Approved figure becomes the run's cap.
- Blocked state is in 07 (Cost blocked card).

### 04 Live run (`accepted` → `synthesis_running`) — FR-006/008/010; AC-011/012/027; COPY-005
- Stage list with per-stage timing + cost accruing live; both debate rounds visible as two lanes (the only two-column moment in the app).
- Search-fallback notice (COPY-005, informational tone, blue); running = **blue** #47689E pulse — green never appears until agreement.
- Live spend vs approved cap; Stop button always available (`DELETE /v1/query-runs/{id}`).
- Progress changes announced via the existing polite live regions.

### 05 Result (`completed`) — FR-009/013; AC-018…020, 027/028
- Meta row under the question: Completed dot (green) · 41.2s · **Jul 7, 2026 · finished 09:41:44 UTC** (current-time context, FR-013) · actual $0.171 (approved $0.19) · `qr_7f3a2c91` · "Run details ▴" toggle.
- **Run details** (collapsed by default), 4 columns: Run receipt (Run ID + copy, **Correlation `req_…`** + copy, Session, Started, Finished, Search providers, "quote run ID + correlation ID when reporting" note) · Cost by model est→actual · Cost by stage est→actual + under-approval delta (green) · Pipeline timings vs 180s timeout.
- **Verdict band** — the app's ONLY large green surface (#0E6B50, radius 18): 4/4 ring (animated SVG stroke), uppercase kicker, serif verdict 25px white, one-line subtext.
- Trust triangle: 3 cards — Agreement (green) · Source support 83% · 12 sources (blue) · Open uncertainty 1 flag (amber).
- "How positions moved" table: 4 model rows × opening / after round 1 / final; concessions get green outline chips "✓ Revised → …" (AC-028: model-level vs debate vs synthesis stays distinguishable).
- Synthesis card rows: Consensus (green label) / Disagreement (amber) / Uncertainty (red) / Sources (blue chips w/ numbers, near the claims they support — AC-013) / Recommendation (green-tinted row, includes "Decision support, not professional advice.").
- Next-question composer: "Follow up on this" (carries context, ≈ +$0.03) vs "Start fresh"; estimate line + hard-cap reminder.
- Footer: ephemerality + decision-support lines.

### 06 Transcript — FR-007/008; AC-014/016/017
- The only drill-down. Chronological: opening positions (4 model cards with per-model sources), round-1 challenges, round-2 concessions (green chips), hand-off to synthesis. Capture per-model latency + status in data (AC-014) even where not displayed.

### 07 Edge states (seven cards, 690px each)
1. **Anonymous** (AC-001): "Start a session to run a query" — secure-cookie session, one click, **no signup/password/API key**; workspace visible, execution disabled.
2. **Active run exists** (AC-003, 409 `ACTIVE_QUERY_EXISTS`): link back to the running query + "Stop it & start new".
3. **Invalid model slot** (AC-008, 422): field-level error naming slot 3, "did you mean …" suggestion, estimate disabled until valid.
4. **Cost blocked** (AC-010, COPY-004, 402): estimate $0.31 vs $0.25 cap, reasons, cheaper-models / shorten-question actions, `threshold_action: blocked`, correlation ID.
5. **Provider failure** (AC-015, 502): names failed step + model, "no secrets exposed", retry / continue-with-3, correlation ID.
6. **Partial result** (AC-022, COPY-006): step checklist with 2/4 timed out, synthesis from available evidence, run + correlation IDs.
7. **Wrong session** (AC-032, 403): denies without confirming the run exists; correlation ID in footer.

### 08 Dark theme (◐ toggle)
Full token mapping of 05. Verdict band unchanged (#0E6B50 works on both). Primary buttons invert to paper-on-ink (#E8EAEE bg, #101215 text).

## Interactions & Behavior
- Buttons: hover = subtle bg shift or translateY(-1px) + shadow, .16–.18s ease. Primary CTA is always **ink** — money never moves on a green button.
- Verdict ring animates once on result load (stroke-dashoffset, 1.4s cubic-bezier(0.22,1,0.36,1)).
- Run details, transcript rounds: collapse/expand. High-stakes checkbox gates Run. Stop confirms before cancel.
- Live run polls `GET /v1/query-runs/{id}`; state names map 1:1 to `docs/29-state-machines.md` (`draft → cost_review → accepted → initial_answers_running → debate_round_1_running → debate_round_2_running → synthesis_running → completed | partial | failed | timed_out | blocked_by_cost | cancelled`).
- Results are ephemeral (session-scoped); Export/Copy on the result header; no history UI.
- Responsive: stack columns under ~900px; long model IDs/URLs truncate with accessible full-value disclosure.

## State Management
Session (`GET /v1/session`, CSRF token) · active run (`GET /v1/query-runs/active` on load → resume banner) · composer draft (question, 4 slots, acknowledgements) · estimate response (`threshold_action`, `reasons`, approved figure) · run polling (status, per-stage progress, accruing cost) · result payload (answers, debate rounds, synthesis, cost, `elapsed_ms`, notices, `query_run_id`, `correlation_id`) · theme (Light default / Dark; persist).

## Design Tokens

**Light (default, cool paper)** — paper #F6F5F2 · surface #FFFFFF · ink #14171C · body #3C4148 · secondary #565C66 · muted #7A8089 · borders rgba(20,23,28,.07/.10/.14/.16)
**Semantic (both themes by role):** green #0E6B50 = brand mark + agreement/consensus/completed ONLY · blue #47689E = sources + running · amber #8A5F16 = caution/uncertainty · red #A83A2A = error/decision-support boundary. Dark variants: #4EC28C / #9FB6DF / #D9A954 / #DB8070.
**Dark:** bg #101215 · header #15181D · card #191C22 · inset #22262D · text #E8EAEE · body #C3C7CE · secondary #9AA0AA · muted #737A85 · borders rgba(232,234,238,.07–.14).
**Warm paper (appearance option):** paper #F2EEE7 · ink #23201B · body #3A342C · secondary #4E483F · muted #8A8275 · borders rgba(38,32,26,…).
**The green rule (non-negotiable):** one large green surface per journey — the verdict band. Small green only for agreement semantics. Never buttons, links, or decoration.
**Type:** Newsreader (serif, 500) for display/verdicts/wordmark Q; Geist for UI (600–650 buttons/labels); Geist Mono for money, IDs, timings, counters. Landing H1 52/1.06; result H1 29/1.28; verdict 25/1.3; body 13.5–17.5; uppercase labels 11–12.5 w/ 0.05–0.14em tracking.
**Radii:** pills 999 · buttons 8–11 · cards/panels 10–18. **Shadows:** screens 0 24px 60px rgba(20,23,28,.12); cards 0 12–16px 32–40px .08; verdict band 0 16px 40px rgba(14,107,80,.30).

## Accessibility (NFR-009, WCAG 2.2 AA)
Keep the repo's implemented scaffolding: skip link → `#main-content`, focusable main, `fieldset`/`legend` for model slots, polite live regions for run state/results/notices. All status colors pass AA on their papers (green on cream 5.7:1; white on green 6.5:1). Never color-alone: every state pairs color + label/icon. Warnings adjacent to the actions they gate.

## Copy
All warning/notice copy in the mocks follows `docs/33-content-design.md` (COPY-001…006) — treat that file as the copy source of truth. Product name: **Quorum** (no "-AI" suffix; `quorum-ai` for domains/repos). Tagline: "Four AI models, one sourced answer." Record in `docs/19-signoff-record.md`; `docs/91-product-naming.md` still holds placeholder names.

## Assets
No image assets. Logo is typographic: green rounded square + serif "Q" (Newsreader 700) + wordmark. Fonts: Newsreader, Geist, Geist Mono (Google Fonts).

## Files
- `Quorum Final Review.dc.html` — all screens 01–08 (source of truth for measurements)
- `support.js` — preview runtime for the HTML file (do not ship)
- Full exploration history lives in the design project (`Quorum Final UI.dc.html`), not in this bundle.

## Known repo follow-ups (not UI work)
- `docs/32-ui-state-matrix.md` is a TBD stub — this package's screens/states can fill it.
- `docs/10-functional-requirements.md` FR-012: title says "Required bring-your-own OpenRouter key" but behavior/ACs (AC-026) specify server-configured keys with **no** user key field. The UI follows the behavior + AC-026. Reconcile the FR title.
- `docs/91-product-naming.md` contains placeholder names pending sign-off; record "Quorum".
