# ULTRACODE PROMPT — UI quick-fixes PR1: chip hand-off, start-fresh error, composer clearing, toast storm, run-id feedback, dark mode everywhere, notice copy (ONE PR)

> Paste this whole file as the first message of a fresh session. It is self-contained,
> but the full triage evidence lives in `UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md` — read it
> before editing; do not re-derive the analysis, VERIFY it (§0).
> **Review is capped at TWO CYCLES total.** Each cycle may fan out multiple parallel
> reviewers, but there is never a third cycle — after cycle 2's fixes, ship on green gates.
> **Everything below lands in a SINGLE PR** (one CI gate, one deploy) — do not split.
> **Sequencing:** this is PR1 of a 4-PR series (PR2 data-completeness, PR3 verdict band +
> markdown gate, PR4 follow-up context + model swap — scoped in the analysis file; their
> prompts are authored later, do NOT start them). Do not run other sessions concurrently on
> this working tree. A push to `main` cancels in-flight CI — land follow-ups via branch+PR.

---

## 0. Context you must verify first (evidence-first — do not trust this prose)

**Run, do not assume:**

```bash
git log --oneline -3 origin/main
sed -n '6516,6527p' src/product_app/static/app.js      # chip handler: instant goToComposer, no hand-off note
sed -n '6436,6463p' src/product_app/static/app.js      # typed path: hand-off note + dwell
grep -n "submissionAttempted" src/product_app/static/app.js   # expected: init l.~181, read ~4695, set-true ~5426/~5473, NO reset
grep -n 'queryTextarea.value = ""' src/product_app/static/app.js  # expected: only the Start-fresh path (~6561)
sed -n '5725,5737p' src/product_app/static/app.js      # 750ms poll; toast per rejection, no dedupe
sed -n '3963,3985p' src/product_app/static/app.js      # copyRunIdToClipboard: title/aria-only feedback
sed -n '597,602p' src/product_app/static/app.css       # topbar display:none on landing/result/live-run/transcript
grep -n 'data-theme' src/product_app/templates/workspace.html  # <html data-theme="light"> hardcoded
grep -rn "localStorage" src/product_app/static/app.js | grep -iv seen  # expected: no theme persistence
sed -n '317,345p' src/product_app/providers.py         # notice branches incl. ":online" wording at 335-338
grep -rn "no citation annotations" src/ tests/ e2e/    # every pinned consumer of the notice string
```

Facts established by the triage session (re-verify cheaply above, then trust):
- Both chip and typed paths DO end on the composer; the difference is only the missing
  hand-off note + dwell on the chip path. Neither path runs or estimates anything.
- The "Please enter a question" on Start-fresh is caused by `state.submissionAttempted`
  never resetting — the Start-fresh handler writes `""` and dispatches `input`, which trips
  the post-submit error branch (`app.js:4695-4697`).
- The toast storm is the 750 ms poll toasting each network rejection verbatim for 6 s each;
  a friendly `NETWORK_UNREACHABLE` mapping already exists at `app.js:989-1013` but the poll
  catch bypasses it. A prior toast-storm regression test exists for a *different* trigger
  (`e2e/tests/ui-parity/parity-behavior.spec.ts:274-295`) — good template.
- The Run-ID header button already copies; its success/failure feedback is invisible
  (title/aria only). The receipt `⧉` button has a visible `::after "Copied"` cue
  (`app.css:~2860`) — reuse that pattern. Clipboard can be unavailable/blocked (incognito).
- The theme toggle exists and works (`initThemeToggle`, `app.js:6202-6235`) but is hidden
  with the topbar on 4 of 6 views; theme is not persisted and ignores `prefers-color-scheme`.
- e2e infra: Playwright under `e2e/`, blocking invariants gate + visual snapshots seeded in
  CI (`.github/workflows/e2e.yml`, `seed-visual-baselines.yml`), golden messy fixture at
  `e2e/fixtures/golden-run.ts`. Existing behavior specs: `e2e/tests/ui-parity/parity-behavior.spec.ts`
  (chips 156-160, 706-712; follow-up prefill 427-455; start-fresh empty 581-587; run-id copy
  770-815 — note it grants clipboard permissions; topbar hidden-on-landing asserted at ~632,
  which this PR intentionally changes).

## 1. The task — seven fixes, one PR

**A. Chip hand-off parity (#1).** Suggested-question chips (landing `workspace.html:689-712`
and composer examples 273-279, shared handler `app.js:6516-6527`) must give the same
guidance as typed submits: route the chip click through the hand-off note (reuse
`handoffFromLanding`'s note; a shorter dwell is fine — pick one constant, don't invent two
timing systems). Chip-during-pending-dwell cancellation behavior must survive
(existing spec parity-behavior ~706-712).

**B. Start-fresh false error (#14).** Reset `state.submissionAttempted = false` on the
Start-fresh navigation and on run terminal state, so arriving at an empty composer never
shows "Please enter a question before running." The error must STILL appear when the user
actually submits empty (prove both directions).

**C. Composer clearing (#10).** When a run reaches a terminal state (result view entered),
clear `#query-text` so the answered question doesn't linger. KEEP the text on: cost-gate
"Back to edit" (`app.js:5137-5142`), Esc-from-cost-gate, and the follow-up prefill path
(`app.js:6554-6570` — existing spec asserts prefill `toHaveValue`, keep it green).

**D. Network-failure toast dedupe (#9).** In the poll error path (`app.js:5725-5737`):
map raw fetch errors ("Failed to fetch" et al.) to the existing friendly
`NETWORK_UNREACHABLE` copy, and replace per-tick toasts with ONE sticky
"connection lost — retrying" indicator that persists while consecutive poll failures
continue and clears on the first success (or run-terminal). No stacking, ever. Non-network
poll errors (e.g. 4xx/5xx API errors) keep their current behavior — do not swallow them.

**E. Run-ID copy feedback (#13).** Visible "Copied" cue on the header run-id button
(mirror the receipt button's `::after` pattern) + on clipboard rejection/unavailability a
visible failure path (error toast or inline "select & copy manually" cue — pick one,
consistent with the receipt button). Keep the existing aria-label announcements
(WCAG 4.1.3 work at parity-behavior 770-815) intact.

**F. Dark mode on every view (#6).** Make the theme toggle reachable on ALL views —
landing, result, live-run, transcript included (`app.css:597-602` hides the topbar there;
either a compact floating toggle on those views or a slimmed topbar variant — choose the
smaller diff that doesn't wreck the landing design). Persist the choice to localStorage;
bootstrap from stored value, else `prefers-color-scheme`; `<html data-theme="light">`
(`workspace.html:2`) becomes the pre-JS default only. Flash-of-wrong-theme: set the theme
early (inline snippet or first script statement). Update the spec that asserts the topbar
is hidden on landing (~632) to the new intended behavior — that assertion flip is part of
the RED→GREEN proof, not collateral damage.

**G. Run-notice plain language (#2).** Reword the citation-fallback notice
(`providers.py:335-338`) to user-facing copy, e.g. "The models didn't include their own
source citations, so the sources below come from a supplementary web search." Sweep the
sibling notice branches (317-345) for the same jargon (`:online`, "citation annotations").
Follow the reason-vocabulary conventions from the ops-hardening work. Update EVERY pinned
test/consumer found by the §0 grep in the same diff.

## 2. Non-negotiable guardrails

- **$0 / hermetic:** no paid API calls, no live prod query-runs. All verification via unit
  tests, Playwright against the local app (sim mode), and free prod GETs.
- **Prove both directions on every loosened check:** B (error gone on Start-fresh AND still
  fires on real empty submit), D (storm gone AND genuine API errors still surface), C
  (cleared after terminal run AND preserved on Back-to-edit/follow-up).
- **A new provider-text surface must route through the markdown renderer** (`setProse`/
  `setInlineProse`) — applies to any new notice/indicator copy that carries provider text.
  Static app copy may be plain text.
- **Visual baselines:** the toggle appearing on snapshotted views (result, transcript) WILL
  shift `visual-snapshots.spec.ts` baselines — regenerate via the seeding workflow
  (`.github/workflows/seed-visual-baselines.yml`), human-review the new images, never
  hand-edit or blindly `--update-snapshots` into the PR.
- **Never fabricate:** if a timing constant (dwell) changes, state the chosen value and why.
- Behavioral changes ship with a test that fails without them — including any helper script.

## 3. Plan first, then parallelize correctly

- Short written plan (tasks → files → tests → skills) before editing; `make skill-route`
  where apt. Recon/review fan out in parallel; **writing = one tree-writer** — the seven
  pieces all touch `app.js`/`app.css`/`workspace.html`, so build serially in order
  **B → C → D → E → A → F → G** (smallest, least-coupled first; F last of the UI pieces
  because it flips a spec assertion + baselines; G independent backend copy, any time).
- Drive the REAL UI while building (webapp-testing / claude-in-chrome): render against the
  golden messy fixture and look at each fix as a user would at 1440px — a green unit test
  on clean sim data has repeatedly hidden real bugs in this repo.

## 4. TDD discipline (RED → GREEN → prove it BITES)

Every piece gets a failing test first; run timing-sensitive specs N≥10× for a flake rate:
- A: e2e — chip click shows the hand-off note before the composer (RED now: instant jump).
- B: e2e — Start fresh → composer shows NO `#query-error`; then submit empty → error shows.
- C: e2e — after terminal run the composer is empty; Back-to-edit keeps text; follow-up
  prefill spec stays green.
- D: e2e with mocked failing poll (Playwright route abort) — exactly ONE network indicator
  visible after N poll ticks; recovers on success; a 500-response poll still surfaces its
  own error. RED now: multiple stacked toasts.
- E: e2e — visible "Copied" cue with clipboard granted; with clipboard blocked, the visible
  failure cue appears (existing aria specs stay green).
- F: e2e — toggle visible + functional on landing, result, live-run, transcript, composer;
  choice persists across reload; `prefers-color-scheme: dark` yields dark on first visit.
  RED now on all counts. Flip the hidden-topbar-on-landing assertion deliberately.
- G: unit test pinning the NEW notice copy (and absence of `:online` jargon in any
  user-facing notice string); all previously-pinned tests updated.
- Gates: `make validate && make quality`, full local e2e invariants + new specs green.

## 5. Ship & deploy verification (truth = the job ran, not `/health` 200)

- ONE PR, merged after the review cycles.
- **Confirm the deploy JOB actually ran** (`success`, not `skipped`/`cancelled`):
  `gh run list --branch main` + filter `startsWith(<merged SHA>)` — `--commit` silently
  returns `[]` in this repo.
- `curl -s https://quorum.stackclimb.com/status | jq -r .build_sha` == merged SHA.
- Prod spot-check by content, automated + cross-browser (not one manual look): landing shows
  the theme toggle; a chip click shows the hand-off note; notice copy (if reachable in sim)
  has no `:online` jargon. No paid runs for this — UI-level checks only.

## 6. Review — MAX TWO CYCLES, then ship

**Cycle 1 (parallel fan-out on the staged diff):**
1. **Breaker** — attack the state machine: can `submissionAttempted` reset hide a genuine
   empty-submit error? can the composer clear eat text the user typed during a run? can the
   sticky network indicator mask a real API failure or never clear? does the early-theme
   snippet break CSP (`main.py` `_CSP_POLICY` — no inline-script violations; verify against
   the actual policy, csp-smoke exists)? does the landing toggle break the first-visit
   gate/localStorage flow? Default "refuted" unless demonstrated.
2. **Correctness reviewer** — every pinned notice-string consumer updated; flipped spec
   assertions are intentional and documented; visual baselines regenerated via the seeding
   workflow, not hand-rolled; no new raw-`textContent` provider surface; timer/dwell specs
   run N≥10×.

Verify findings before acting; fix real ones.
**Cycle 2 (fresh eyes, fixed diff only).** Fix what survives. **Stop — no cycle 3**;
leftovers become follow-up notes for PR2-4.

## 7. Definition of done

- [ ] Real state verified up front (§0), not assumed.
- [ ] A: chips show the same hand-off guidance as typed submits; dwell-cancel behavior intact.
- [ ] B: no false error on Start-fresh; genuine empty-submit error still fires (both proven).
- [ ] C: composer clears on terminal run; Back-to-edit + follow-up prefill preserved.
- [ ] D: one sticky network indicator, friendly copy, recovers on success; API errors still surface.
- [ ] E: visible copy success AND failure feedback; a11y announcements intact.
- [ ] F: toggle on all six views, persisted, `prefers-color-scheme` bootstrap, no theme flash, CSP-clean.
- [ ] G: plain-language notices everywhere; zero `:online`/"citation annotations" jargon user-facing; all pinned tests updated in-diff.
- [ ] Visual baselines regenerated + human-reviewed; invariants gate green; `make validate`/`quality` green.
- [ ] Exactly ≤2 review cycles; findings verified then fixed.
- [ ] ONE PR merged; **deploy job confirmed run**; `/status build_sha` == merged SHA; automated cross-browser prod check.
- [ ] `docs/00-factory-console.md` + `docs/session-handoff.md` updated; `UI-PR1-QUICKFIXES-RESULT.md` ledger written; **author `UI-PR2-DATA-COMPLETENESS-ULTRACODE-PROMPT.md`** from `UI-BUG-TRIAGE-2026-07-23-ANALYSIS.md` (PR2 scope: issues 3/4/7 + export + expanders) incorporating this session's learnings; `make handoff` run.
