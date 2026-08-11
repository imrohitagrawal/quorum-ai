# ULTRACODE PROMPT — Ship the ops-metrics explainer + add per-tile relevance to `/ui/ops`

> Paste this whole file as the first message of a fresh session. It is self-contained.
> **Review fan-out is capped at 2 independent reviewers** (one correctness, one breaker) — do not exceed it.

---

## 0. Context you must verify first (evidence-first — do not trust this prose)

- The prior session built PR **#85** on branch `feat/ops-metrics-explained`: it (a) extracted the
  workspace design tokens verbatim into shared `src/product_app/static/tokens.css` (loaded by both
  `workspace.html` and `ops.html`), and (b) added a **"Metrics, explained"** section below the SLO
  tiles on `/ui/ops` (live-parsed metric catalog + how-to-read + SLO explainer).
- **As of handoff, #85 is OPEN and NOT deployed.** Prod `/ui/ops` still shows only the six tiles.
- **Confirm the real state before doing anything** — run, do not assume:
  ```bash
  gh pr view 85 --json state,mergedAt,mergeStateStatus
  git ls-remote origin main | cut -c1-12          # is #85's commit on main yet?
  curl -s https://quorum.stackclimb.com/ui/ops | grep -c "Metrics, explained"   # 0 = not deployed
  curl -s https://quorum.stackclimb.com/ui/ops | grep -c "tokens.css"
  ```
  Branch to your findings: if #85 is already merged/deployed, skip Task A and go straight to Task B
  on top of `main`. If not, land #85 first so you build on it, not a fork of it.

## 1. The task

**Goal:** every panel on `/ui/ops` should be self-explanatory to someone who has never seen Prometheus —
*what the number is, why it matters, and what to do when it's not green.*

**Task A — land the existing work.** Get PR #85 green and merged, then **verify the deploy** (see §5).

**Task B — add per-tile relevance to the six SLO tiles** (Request rate, HTTP p95 latency, 5xx error rate,
Readiness, Uptime, Version). For each tile add a short, plain-language **"why this matters"** line and,
where it applies, a **"when it's red"** hint (what a breach means / first action). Keep it calm and terse —
this is an operator surface, not marketing. Examples of the substance (reword as you see fit):
- **Request rate** — throughput the process is serving; a sudden drop to ~0 with traffic expected = an
  upstream/routing problem, not this box.
- **p95 latency** — 95% of requests finished at/under this; the SLO line is `< 1 s`. Bucket-derived and
  conservative (already noted). When red: check for a slow dependency or cold cache.
- **5xx error rate** — share of requests the server itself failed; SLO `< 1%`. When red: read structured
  logs by `request_id`, then the incident runbook in `docs/80-observability.md`.
- **Readiness** — whether live execution is actually available (real models + catalog reachable), not just
  "process up". `degraded`/`offline` means runs fall back to simulation — see the readiness reasons.
- **Uptime** — process lifetime; a reset means a deploy/restart (all counters above reset with it).
- **Version / environment** — which build is live; cross-check against the intended deploy SHA.

**Task C — record the CSP hardening as a tracked follow-up (do NOT bundle it here).** The app-wide CSP
(`_CSP_POLICY` in `src/product_app/main.py`) has no `base-uri` or `form-action` directive. It is
pre-existing and low-risk (other directives are host-exact; `/ui/ops` has no `<form>`/`<base>`), but it
governs **every** page, so it belongs in its own PR with its own testing. Open a Jira/issue or a
`docs/`-tracked line for it; do not widen the shared CSP inside this ops-page change.

## 2. Non-negotiable guardrails (carried from prior sessions — enforce mechanically, not by vibes)

- **`/metrics` response bytes are IMMUTABLE.** All human-facing work lives on `/ui/ops`. Keep the existing
  test that pins the exposition contract; if none asserts byte-stability for your change, add one.
- **Design-token single source of truth.** Do not re-declare palette/type/spacing tokens in `ops.css` or
  `app.css`; consume `tokens.css`. A token added for the tiles goes in `tokens.css` once.
- **Every current value stays computed live**, never hardcoded — a baked-in number fabricates a
  measurement. The new copy is *static explanation*; the *values* keep flowing from `/metrics`/`/status`/`/ready`.
- **Provider/metric text routes through safe sinks only** — `textContent`/`createElement`, never
  `innerHTML`/`insertAdjacentHTML`. (The catalog already obeys this; keep it that way.)
- **Accessibility:** no new critical/serious axe violations; scrollable regions keep `tabindex`/`role`/
  `aria-label`; no horizontal page overflow at 1440px **or** 375px (wide content scrolls inside its own box).

## 3. TDD discipline (RED → GREEN → prove it BITES)

- **Write the failing test first** for each behavioural addition, then make it pass. A test that passes
  with the feature absent is worthless — show it RED on the missing copy, GREEN after.
- **Unit** (`tests/unit/test_ops_dashboard.py`): assert each tile carries its relevance copy (key off a
  stable `data-*` hook, not brittle prose); assert no hardcoded current values leak in.
- **E2E** (`e2e/tests/ops/ops-dashboard.spec.ts`): drive the **real** local server; assert the copy is
  visible and the tiles still cross-check against a live `/metrics`/`/status` fetch. **Prove RED then
  GREEN** for any gate change (revert-and-rerun). Run any timing-sensitive spec **N≥10×** to establish a
  real flake rate — do not assert once.
- **Security checks key off the matched value, never a whole-line substring.** (The same-origin host guard
  in the prior PR parses each URL's real host and compares by equality — keep that pattern; if you touch
  it, re-prove both directions: legit hosts pass AND look-alikes `…com.evil.com` / `…@evil.com` /
  `//evil` / mixed-case are caught.)

## 4. Live verification — look at it as a user (a green test is not enough)

- Render the real page at **1440px** and screenshot it; read it as an operator would. Prior sessions
  repeatedly caught real bugs (raw markdown, non-monotonic timer, cramped layout, clipped tokens) that
  clean unit tests on sim data missed.
- Exercise the **empty-state / degraded** paths too (e.g. `process_*` absent off-Linux; readiness
  `degraded`) — the copy must stay honest, never imply data that isn't there.
- A manual single-browser spot-check can give a false all-clear (CSP differs per browser) — rely on the
  cross-browser e2e (chromium + firefox + mobile) for the binding signal.

## 5. Ship & deploy verification (truth = the job ran, not `/health` 200)

- Green gates are necessary, not sufficient. Merge only after review (see §6).
- **Confirm the deploy JOB actually ran** (`success`, not `skipped`/`cancelled`) for the merged SHA, and
  confirm the *running build's* health — not an unchanged `/health` 200. Known repo quirks:
  - `gh run list --commit <SHA>` silently returns `[]`; use `--branch main` and filter by `startsWith(SHA)`.
  - A follow-up push to `main` **cancels the just-merged commit's CI** (concurrency) and moves the deploy
    to the new SHA — land follow-ups via branch+PR, not a direct push.
- **Verify on prod by content, not status code:**
  ```bash
  curl -s https://quorum.stackclimb.com/ui/ops | grep -c "why this matters"   # >0 once live
  ```
- **Hermetic / $0 by default:** no paid API calls, no secret rotation, no paid runs for routine checks.
  Never fabricate a number, label, or baseline — flag the gap instead.

## 6. Review before "done" — FAN-OUT CAPPED AT 2

After gates are green and before declaring complete, run **exactly two independent reviewers in parallel**
on the staged diff — no more:
1. **Correctness reviewer** — token move is verbatim/complete, no stale DOM across refreshes, copy matches
   the actual metric semantics, tests genuinely bite.
2. **Breaker (security/evasion)** — attack any loosened check, any new text sink, the CSP surface, and
   XSS/DoS via `/metrics` content. Default to "refuted" unless the exploit is demonstrated.

Verify each finding before acting; fix real ones, drop what doesn't survive verification. Iterate to a
fixpoint (a fresh pass finds nothing new). Do **not** expand the reviewer fan beyond 2.

## 7. Definition of done

- [ ] Real deploy state verified up front (not assumed); #85 landed or confirmed already-live.
- [ ] Each of the six tiles has honest "why it matters" (+ "when red" where apt), RED-proven tests.
- [ ] `/metrics` bytes unchanged (pinned); tokens single-source; values still computed live; safe sinks only.
- [ ] `make validate` and `make quality` green; ops e2e green across chromium/firefox/mobile; 1440px
      screenshot reviewed by eye; any timing spec run N≥10×.
- [ ] Two-reviewer pass done, findings resolved to a fixpoint.
- [ ] Merged, **deploy job confirmed run**, prod verified by content.
- [ ] CSP `base-uri`/`form-action` hardening tracked as its own follow-up (not bundled).
- [ ] `docs/80-observability.md` inventory + `docs/00-factory-console.md` / session-handoff updated.
