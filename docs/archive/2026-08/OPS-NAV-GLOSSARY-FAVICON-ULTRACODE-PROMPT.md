# ULTRACODE PROMPT — `/ui/ops` jump-bar TOC + "Used by" honesty + glossary + site favicon (ONE PR)

> Paste this whole file as the first message of a fresh session. It is self-contained.
> **Review is capped at TWO CYCLES total.** Each cycle may fan out multiple parallel reviewers,
> but there is never a third cycle — after cycle 2's fixes, ship on green gates.
> **Everything below lands in a SINGLE PR** (one CI gate, one deploy) — do not split.

---

## 0. Context you must verify first (evidence-first — do not trust this prose)

Prior sessions shipped `/ui/ops` (six SLO tiles + "Metrics, explained": what-/metrics-is,
live metric catalog, how-to-read, SLO table) via PRs #85/#87, deployed and prod-verified.
**Confirm the real state before doing anything — run, do not assume:**

```bash
git log --oneline -3 origin/main
curl -s https://quorum.stackclimb.com/ui/ops | grep -c "Metrics, explained"      # >0 expected
curl -s https://quorum.stackclimb.com/ui/ops | grep -c 'rel="icon"'               # 0 = favicon still missing
grep -c 'rel="icon"' src/product_app/templates/ops.html src/product_app/templates/workspace.html
```

Facts established last session (re-verify cheaply, don't re-derive from scratch):
- Tiles consume **only** `http_requests_total` + `http_request_duration_seconds_bucket` from
  `/metrics` (see `ops.js` `parseMetrics`), plus `/status` and `/ready`. The `process_*` and
  `python_*` catalog groups are **informational only — no tile reads them**.
- Catalog "What it measures" text is the raw `# HELP` line parsed live (`parseFamilies`) and
  rendered via `textContent` — it is machine text, NOT page-authored copy.
- No favicon exists for the product UI; the only one in-repo is Swagger's vendored
  `favicon-32x32.png` used solely on `/docs` (`main.py`).
- All explainer sections already have stable `id`s (`#tile-*`, `#metrics-explained`,
  `#explainer-about|catalog|howto|slo`) — the TOC needs no restructuring.

## 1. The task — four additive pieces, one PR

**A. Sticky jump-bar TOC on `/ui/ops`.** A slim horizontal strip under the existing header
(below the last-refresh/error status line — live status stays most prominent):
`Live tiles · What /metrics is · Catalog · How to read it · SLOs · Glossary`.
- Anchor links to the existing `id`s; scroll-spy via `IntersectionObserver` (no scroll-handler
  jank) setting `aria-current` on the active link.
- `scroll-margin-top` on every target so the sticky bar never covers a jumped-to heading.
- Respect `prefers-reduced-motion` for smooth-scroll; keyboard-reachable, no focus trap,
  ordered after the existing skip-link.
- Mobile (375px): the bar horizontally scrolls inside its own box or wraps — **no page-level
  horizontal overflow** (this is a blocking e2e invariant).

**B. "Used by" honesty in the catalog.** Answer "are we using these?" for every viewer:
- Per-family badge/marker: the two families that feed tiles get "→ feeds the rate / p95 /
  error tiles"; all others get "informational — not read by any tile".
- One sentence in the catalog intro: this page's SLOs are computed from the `http_*` group
  only; the rest is exposed for external monitoring (future Prometheus/Grafana) and diagnosis.
- Key the badge off the **family name** the page actually parses (`http_requests_total`,
  `http_request_duration_seconds_bucket`) so it stays true if families come or go; unknown/new
  families default to "informational". Do NOT remove any family from the catalog — its
  "never silently drops a metric" guarantee stands.

**C. Glossary panel (last TOC entry) + jargon links.** ~8 entries, plain language, terse:
GC (garbage collection), histogram & bucket, p95/percentile, cardinality, resident memory
(RSS), file descriptor, scrape & exposition, counter vs gauge.
- Each term gets its own `id`; first use of each term in **page-authored** copy becomes a
  dotted-underline link (`<a class="term">`/`<dfn>`-style) jumping to its glossary entry.
- **Do NOT rewrite or annotate the machine `# HELP` text** — it renders verbatim by design
  ("nothing below is hardcoded" is a stated guarantee). The glossary sits beside it.
- No hover-only tooltips (invisible on touch, hurts snapshot gates, hides content).

**D. Favicon, site-wide.** A simple "Q" mark SVG served same-origin from `/static/` with an
`<link rel="icon">` in **both** `ops.html` and `workspace.html` (add a PNG fallback if
trivial). Same-origin only — the CSP allows no external hosts; do not touch `_CSP_POLICY`
(CSP hardening is already tracked separately as issue #86 — leave it alone).

## 2. Non-negotiable guardrails (carried from prior sessions)

- **`/metrics` response bytes are IMMUTABLE.** All work is on `/ui/ops` + templates/static.
- **Design tokens single-source:** consume `tokens.css`; never re-declare palette/type/spacing
  in `ops.css`/`app.css`.
- **Every current value stays computed live** — new copy is static *explanation*; values keep
  flowing from `/metrics`/`/status`/`/ready`. Never fabricate a number or label.
- **Provider/metric text through safe sinks only** — `textContent`/`createElement`, never
  `innerHTML`. The "Used by" badge is page-authored, but build it with the same safe pattern.
- **Accessibility:** no new critical/serious axe violations; scrollable regions keep
  `tabindex`/`role`/`aria-label`; no horizontal page overflow at 1440px or 375px.
- **Honest empty states:** scroll-spy and badges must not break when a group is empty
  (e.g. `process_*` absent off-Linux).

## 3. Plan first, then parallelize correctly

- Produce a short written plan (tasks, files, test list, which skills drive what) before
  editing. Use `make skill-route` / repo skills where they fit.
- **READ-ONLY phases (recon, review) → fan out parallel subagents.**
  **WRITE phases → ONE tree-writer at a time.** The whole change is one tightly-coupled UI
  surface + its specs — build it as ONE focused builder; fan out the *review*, not the build.

## 4. TDD discipline (RED → GREEN → prove it BITES)

- Failing test first for each behavioural piece; show RED with the feature absent, GREEN after.
- **Unit** (`tests/unit/test_ops_dashboard.py` or sibling): TOC links present and target real
  `id`s; glossary entries present; favicon `<link>` present in both templates and the asset
  route serves 200 with an image content-type; badge logic keys off family names.
- **E2E** (`e2e/tests/ops/`): drive the real local server — clicking a TOC link scrolls its
  section into view and sets `aria-current`; the two consuming families show the "feeds"
  badge and a non-consuming family shows "informational"; a jargon link lands on its glossary
  entry; no horizontal overflow at 375px with the sticky bar present.
- Visual snapshot baselines (`e2e/tests/invariants/`) will change — re-seed deliberately via
  the seeding workflow and eyeball the new baselines; never hand-wave a diff through.
- Any timing/scroll-sensitive spec: run **N≥10×** for a real flake rate — never assert once.
- Prove RED-then-GREEN for any gate change by revert-and-rerun.

## 5. Live verification — look at it as a user (a green test is not enough)

- Render the real page at **1440px and 375px**, screenshot, and read it as an operator would:
  does the jump-bar map the page at a glance? does scroll-spy track correctly? does the
  favicon actually show in the tab? Prior sessions repeatedly caught real bugs green tests
  missed (raw markdown, non-monotonic timer, cramped layout).
- Check the degraded/empty paths (readiness `degraded`, missing `process_*` group).
- Cross-browser e2e (chromium + firefox + mobile) is the binding signal, not one manual look.

## 6. Review — MAX TWO CYCLES, then ship

**Cycle 1 (parallel fan-out on the staged diff):**
1. **Correctness reviewer** — TOC targets real anchors; scroll-spy has no races/leaks
   (observer disconnected on refresh re-render); badge logic truthful against `ops.js`
   parsing; glossary copy technically accurate; tests genuinely bite.
2. **Breaker (security/evasion)** — new text sinks, the favicon route, any `href` built from
   data, CSP interaction of the SVG icon, XSS/DoS via `/metrics`-derived content in badges.
   Default to "refuted" unless the exploit is demonstrated.
3. **UX/a11y reviewer** — keyboard path, `aria-current` semantics, contrast of the dotted
   links and badges, 375px behaviour, reduced-motion.

Verify each finding before acting; fix the real ones.
**Cycle 2 (parallel, fresh eyes):** re-review the *fixed* diff only. Fix what survives
verification. **Then stop — no cycle 3.** Remaining nits become follow-up notes, not code.

## 7. Ship & deploy verification (truth = the job ran, not `/health` 200)

- `make validate` && `make quality` green; e2e green across browsers. Single PR, merged once
  review cycles are done.
- **Confirm the deploy JOB actually ran** (`success`, not `skipped`/`cancelled`) for the
  merged SHA. Repo quirks: `gh run list --commit <SHA>` silently returns `[]` — use
  `--branch main` + filter `startsWith(SHA)`. A follow-up push to `main` cancels the
  just-merged CI — land follow-ups via branch+PR. A duplicate cancelled Deploy run is
  concurrency dedupe, not failure.
- **Verify prod by content, not status code:**
  ```bash
  curl -s https://quorum.stackclimb.com/ui/ops | grep -c 'rel="icon"'        # >0 once live
  curl -s https://quorum.stackclimb.com/ui/ops | grep -ci 'glossary'          # >0 once live
  curl -s https://quorum.stackclimb.com/ui/ops | grep -c 'informational'      # >0 once live
  ```
- **Hermetic / $0:** no paid API calls, no secret rotation, no paid runs for routine checks.

## 8. Definition of done

- [ ] Real state verified up front (not assumed).
- [ ] Jump-bar TOC with scroll-spy, sticky, a11y-clean, no overflow at 375px — RED-proven tests.
- [ ] Catalog "Used by" badges truthful to `ops.js` parsing; no family removed; intro sentence added.
- [ ] Glossary panel + jargon links in page-authored copy only; machine `# HELP` text untouched.
- [ ] Favicon on both `ops.html` and `workspace.html`, served same-origin, visible in a real tab.
- [ ] `/metrics` bytes unchanged; tokens single-source; safe sinks only; values still live.
- [ ] Visual baselines re-seeded deliberately and eyeballed; timing specs run N≥10×.
- [ ] Exactly ≤2 review cycles run; findings verified then fixed; leftovers noted as follow-ups.
- [ ] ONE PR merged; **deploy job confirmed run**; prod verified by content.
- [ ] `docs/00-factory-console.md` + `docs/session-handoff.md` updated; `make handoff` run.
