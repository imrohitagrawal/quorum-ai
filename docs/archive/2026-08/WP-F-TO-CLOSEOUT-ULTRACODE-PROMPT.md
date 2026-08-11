# UI Remediation — WP-F to close-out

> **Written:** 2026-07-28, at the close of the WP-E + issue-#111 session.
> **Branch:** `feat/ui-pr1-quickfixes` — **PR #96 open against `main`**, and
> **pushed** (remote is in sync at `522179d`).
> **Plan of record:** `UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md`
> (§4 work packages, §9 execution order, §10 locked decisions).
> **Previous handoff:** `WP-E-TO-CLOSEOUT-ULTRACODE-PROMPT.md` — still accurate
> for WP-A..WP-D detail. This file supersedes its §3 ordering.

---

## 1. State — measured at the close of this session

| Gate | Result |
|---|---|
| `make validate` / `lint` / `format-check` / `type-check` / `openapi-check` | **all green (exit 0)** |
| `uv run pytest tests -q --no-cov` | **1707 passed / 0 failed / 10 skipped** |
| e2e blocking invariants lane (6 specs) | **108 passed / 0 failed** |
| e2e axe + parity + docs + smoke + degraded + ops lane | **94 passed / 0 failed** |
| `make diff-cover DIFF_BASE=origin/main` | **98%** (blocking min 95) |

**Re-verify before building on this.** A stale baseline is how a regression
gets mistaken for a known failure.

**Do NOT run `pytest` and `make diff-cover` concurrently** — they race on a
fixed shared path and produce a phantom failure in
`test_makefile_gate_integrity`. That is **issue #113**, not a product bug. Run
them serially or you will chase a ghost, as this session did.

### Commits added this session

- `651349f` — **WP-E**: F-14 honest readiness (`offline_by_bad_key` from a
  zero-token `GET /api/v1/key` probe on a background daemon thread) + F-09
  (nine user-facing notices rewritten, moved into a `PROVIDER_NOTICES` registry).
- `522179d` — **issue #111**: the offline disclosure is now actually rendered.

### The visual-snapshot step is expected RED

`visual-snapshots.spec.ts` + `trust-score-visual.spec.ts` are a THIRD blocking
CI step inside the "e2e axe + parity" job. Linux baselines are deliberately
unseeded until WP-H. **Expect that step red; it is not your bug, and you must
not reseed baselines before WP-H.**

---

## 2. WP-F — frontend completeness (F-13, then F-12, F-19) + consume `shortened`

All five claims below were **re-verified against current code on 2026-07-28**,
because the previous handoff shipped stale line numbers that cost a recon agent
real time. Line numbers here are current as of `522179d`.

### The one claim you must prove yourself first

**D-1, INHERITED AND UNVERIFIED.** The prior handoff states `formatAnswerText`
can NEVER emit `<ul>`/`<ol>` because `flushParagraph()` and `flushList()` share
one buffer and `flushParagraph()` always runs first. The *structure* is
confirmed — `formatAnswerText` is at `app.js:4509`, and the pairs are at
`4577/4578`, `4583/4584`, `4605/4606` (the handoff's `4513`/`4541` are stale) —
but **the behavioural claim itself has not been demonstrated by anyone.**

Do not inherit it. **Write the RED test that proves it before you change a
line.** If the claim is false, you have just avoided a fix for a bug that does
not exist; if it is true, you have the bite proof. This project has twice
recorded a confidently-stated root cause that measurement refuted.

### Verified facts

- **`MESSY_BULLET_LIST` is dead** — exactly ONE occurrence,
  `e2e/fixtures/golden-run.ts:112`, referenced by no spec. Wire it or delete
  it; do not leave it as decoration.
- **The golden fixture has 2 unique source URLs.** F-19's "+N more" is
  therefore invisible to every test that exists. Extend to >3 unique sources
  **in the same change**, or the gate cannot see the feature.
- **`shortened` is inert** — `grep -c shortened src/product_app/static/app.js`
  → **0**. It has crossed the API boundary since WP-D and nothing renders it.
- **`DEFAULT_SECTION_MAX_CHARS = 4000`** at `synthesis_length.py:30`. A
  3000-token section is ~12 000 chars, so storage discards ~67% of output the
  user is BILLED for. Raise it here, alongside the expanders that make long
  sections readable.

### Scope

Full Markdown export; expanders for synthesis sections / transcript rounds /
trust captions; "+N more" as an inline expander; the stray-asterisk fix plus a
**greenable** new `RAW_MARKDOWN_PATTERNS` entry.

### Order within the WP (non-negotiable)

Land **fixture seeds + the new `RAW_MARKDOWN_PATTERNS` entry ALONE first, and
record the RED run.** The bite proof cannot be reconstructed afterwards.

---

## 3. Practices that earned their place — most of them the hard way, this session

1. **RED before GREEN, always**, and prove the bite by mutation. **Copy the
   file aside (`cp`) and restore from the copy. NEVER `git checkout <file>`** —
   the tree carries uncommitted work.
2. **A green test is not proof. Look at a screenshot.** This session the suite
   was green TWICE while the UI was broken: once when a moved banner was still
   invisible on first visit, once when a notice claimed a model "was asked" on
   paths where no request ever left. Both were caught by driving the real UI.
3. **For any UI gate: `toBeVisible()`, never `toBeAttached()`**, and assert
   **PER VIEW**. `boot()` sets `quorum.workspaceSeen`, so every spec starting
   from `boot()` is **blind to the landing view by construction** — which is
   exactly how an invisible banner passed. Note `toBeVisible()` still does not
   mean *on screen*; use `toBeInViewport()` when that is the claim.
4. **Register every new spec in `.github/workflows/e2e.yml`'s blocking lane.**
   An unregistered gate is not a gate (this was F-15; `tests/invariants/` has a
   guard test that will red until you do).
5. **Fan out review — it is mandatory, and it works.** Five reviews over this
   session found, in code that was already RED/GREEN-proved and
   browser-checked: a security defect (an `Authorization: Bearer` header
   forwarded across redirects), a false claim in my own code comment, an
   authenticated network call added to a codegen step, **four of my own tests
   that could not fail**, and a view left with zero honesty disclosure.
   **Review the FIXES too** — the second round found a defect the first round's
   fix introduced.
6. **Reviewers are read-only. Enforce it in the prompt, in capitals.** This
   session a reviewer mutated `src/` in the shared tree and restored from a
   stale copy, **silently reverting my work twice**. Tell every reviewer: do
   not write, edit, `git checkout`, `git stash`, or `sed -i` anything in the
   repo; copy to `/tmp` to analyse. Snapshot your own diff (`git diff >
   /tmp/x.patch`) before fanning out.
7. **Verify every reviewer claim before acting.** Roughly a fifth do not
   survive inspection — but the ones that do are the ones you would never have
   found alone.
8. **Assert on programmatic edits.** A Python `str.replace()` that silently
   matched nothing produced a "fix" that was never applied, and the mutation
   test that should have caught it passed. Always `assert old in s`.
9. **Measurement beats reasoning, every time.** A plausible argument that an
   unfunded key would surface as a 402 was refuted by one `curl`: it returns
   **401**, indistinguishable from an invalid key. The argument had already
   persuaded a reviewer and me, and had changed user-facing copy. Run the check.
10. **`make quality` / `make validate` do NOT include the blocking changed-lines
    coverage gate.** Run `make diff-cover DIFF_BASE=origin/main` before pushing.
11. **Adding a UI surface means adding its shape to `e2e/fixtures/golden-run.ts`
    in the SAME change**, or the gate cannot see it.
12. **Ask before starting the next work package.** The operator wants a
    report and an explicit go between WPs.

### Run e2e exactly as CI does

```bash
lsof -ti tcp:18085 | xargs -r kill -9
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> --project=chromium --workers=1 --retries=0
```

Without both flags ~95 phantom failures appear.

---

## 4. Open issues — filed, with measurements, not fixed

| # | Item | Owner |
|---|---|---|
| **#112** | Credential probe runs once per process → a key revoked or **drained** mid-life keeps reporting `live`; a proxy 403 is indistinguishable from a provider 403 | follow-up |
| **#113** | `test_makefile_gate_integrity` races on a fixed shared path | WP-H |
| **#114** | **Golden fixture carries no `provider_notice`** — the blocking gate never renders any of the nine notice strings | **WP-F (yours)** |
| **#115** | `#demo-mode-banner` is the same dead-markup bug as #111, **and its blocking gate uses `toContainText`, which does not require visibility** — a green gate over a 0×0 element. Needs a design call: delete as redundant with `#result-degraded`, or move it | WP-F or WP-H |
| **#116** | Readiness banner is 48% of a 390×664 mobile viewport, pushing the landing hero below the fold | WP-H |
| **#117** | Banner flashes + shifts layout when the page-load seed disagrees with `/ready` | WP-H |

**#114 is squarely yours** — you are already extending the fixture for F-19, so
add `provider_notice` shapes in the same pass.

**#115 is worth reading before you touch any banner.** It is the same defect
class you will be working next to, and its gate cannot fail.

---

## 5. Boundaries — do not cross without asking

- **Do NOT start the remaining cost-layer work** (the fail-open spend cap,
  positive evidence in `_actual_cost`, the five stale `_FALLBACK_CATALOG`
  prices). A separate chat owns Stream B and holds the design context. F-01,
  F-02, F-05 and F-06 are already merged here. **If you find something in that
  area, file it rather than fixing it.**
- **Do not reseed visual baselines.** That is WP-H, once, at the very end.
- **Do not start WP-G2 or WP-H** without an explicit go.

### Still true from WP-D/WP-E, and easy to trip over

- `untrusted_text.fence()` + `UNTRUSTED_DATA_SYSTEM_RULE` are inseparable: any
  new provider text reaching any prompt needs **both** halves.
- Excerpt sizes are **DERIVED** constants — never hardcode 8000.
- `max_cost_usd` is priced on the **BOUND path only**. Moving that term to the
  point path either hard-refuses affordable runs or breaks the breakdown's
  reconciliation invariant. Both were measured.
- Cost-band fixtures may only use **price-exact** models; a test enforces it.
- Provider notices now live in the `PROVIDER_NOTICES` registry
  (`providers.py`). An `ast`-based test rejects any `provider_notice=` assigned
  an inline literal, and another requires every registered notice to be
  emitted. Add copy **there**, not inline.

---

## 6. Operator-gated (needs a human, not an agent)

- **A funded OpenRouter key.** MEASURED 2026-07-28: a funded valid key returns
  `200` from `GET /api/v1/key`; a valid but **UNFUNDED** key returns `401`. The
  readiness probe therefore treats "no credit" and "bad key" identically — by
  necessity, not by choice.
- **Before funding: issue #100** (no deployment-wide spend ceiling).
- Batch everything needing the key into ONE deliberate ~$0.02 run: verify nvidia
  auth, whether `:online` works for nvidia, and **measure real latency at the
  new caps** (the 180s deadline at 2000/3000 is still UNPROVEN).
- **Visual baseline seeding** via `seed-visual-baselines.yml` — once, at WP-H.
- Confirm any deploy by `/status.build_sha == merged SHA` **and** the deploy JOB
  actually running — never by an unchanged `/health` 200.

---

## 7. Fresh-session prompt

> The leading `ultracode` is deliberate and must not be stripped. It turns the
> multi-agent opt-in on for the WHOLE session, which is what §3 rule 5 requires:
> fan out for read-only recon, again over the build, and again over the fixes
> that review produces.

```text
ultracode

Read AGENTS.md, then UI-REMEDIATION-MASTER-PLAN-ULTRACODE-PROMPT.md, then
WP-F-TO-CLOSEOUT-ULTRACODE-PROMPT.md in full before editing anything.

STATE: branch feat/ui-pr1-quickfixes, PR #96 open against main and PUSHED
(remote in sync at 522179d). WP-A, WP-B, Task 0, WP-C, WP-G1, WP-D and WP-E are
COMPLETE and committed; issue #111 is fixed (522179d). main is merged in, so
Stream B's F-05 and F-06 are already here.

FIRST: re-verify that state yourself — make validate lint format-check
type-check openapi-check, then pytest, then BOTH e2e lanes, then
make diff-cover DIFF_BASE=origin/main. Expect 1707 pytest, 108/0 and 94/0 e2e,
diff-cover 98%. Run pytest and diff-cover SERIALLY, never concurrently — they
race on a shared path (issue #113) and produce a phantom failure. If the numbers
differ from §1, find out why before writing code.

THEN WP-F (F-13, then F-12, F-19, consume `shortened`, raise
synthesis_length.DEFAULT_SECTION_MAX_CHARS).

Order within the WP is non-negotiable: land the fixture seeds + the new
RAW_MARKDOWN_PATTERNS entry ALONE FIRST and record the RED run. The bite proof
cannot be reconstructed afterwards.

D-1 IS INHERITED AND UNVERIFIED. The claim is that formatAnswerText
(app.js:4509) can never emit <ul>/<ol> because flushParagraph() and flushList()
share a buffer and flushParagraph() runs first (pairs at 4577/4578, 4583/4584,
4605/4606). Nobody has demonstrated it. PROVE IT WITH A RED TEST BEFORE
CHANGING A LINE. This project has twice had a confidently-stated root cause
refuted by measurement.

VERIFIED FACTS (re-checked 2026-07-28): MESSY_BULLET_LIST has exactly one
occurrence (golden-run.ts:112) and is referenced by no spec — wire it or delete
it. The golden fixture has only 2 unique source URLs, so F-19's "+N more" is
invisible to every test; extend to >3 in the same change. `shortened` appears 0
times in app.js. DEFAULT_SECTION_MAX_CHARS is 4000 (synthesis_length.py:30)
while a 3000-token section is ~12000 chars, so ~67% of BILLED output is
discarded. Also close issue #114 here: the golden fixture carries no
provider_notice, so the blocking gate never renders any of the nine notice
strings rewritten in WP-E.

RULES:
  - RED test before each fix; bite-proof by mutation, copying the file aside
    and restoring from the copy, NEVER git checkout.
  - A green test is not proof — look at a screenshot. The suite was green twice
    last session while the UI was broken.
  - UI gates assert toBeVisible(), never toBeAttached(), and assert PER VIEW.
    boot() sets quorum.workspaceSeen, so any spec starting from boot() is blind
    to the landing view. toBeVisible() does not mean on-screen; use
    toBeInViewport() when that is the claim.
  - Register every new spec in .github/workflows/e2e.yml's blocking lane.
  - Assert on every programmatic edit (assert old in s) — a silent no-op
    replace produced a fix that was never applied and a mutation test that
    passed anyway.
  - ONE tree-writer. Fan out subagents ONLY for read-only recon and adversarial
    review, and tell every one of them IN CAPITALS not to write, edit,
    git checkout, git stash or sed -i anything in the repo — last session a
    reviewer mutated src/ and silently reverted my work twice. Snapshot your
    diff to /tmp before fanning out.
  - Verify every reviewer claim before acting: about a fifth do not survive.
  - make quality/validate do NOT include the blocking changed-lines coverage
    gate: run make diff-cover DIFF_BASE=origin/main before pushing.
  - Run e2e as:
      lsof -ti tcp:18085 | xargs -r kill -9
      cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> \
        --project=chromium --workers=1 --retries=0

MANDATORY before calling WP-F done: run an adversarial fan-out over it (4-6
read-only refuters with distinct lenses + an adjudicator told to reject its own
reviewers), and review the FIXES it produces too. Five such reviews last
session found, in code already RED/GREEN-proved and browser-checked: a security
defect, a false claim in a code comment, an authenticated network call added to
a codegen step, four tests that could not fail, and a view with zero honesty
disclosure.

The visual-snapshot CI step is EXPECTED RED until WP-H. Do not reseed baselines.

Stop after WP-F is green AND reviewed, then report and WAIT FOR EXPLICIT
PERMISSION before starting WP-G2 or WP-H.

DO NOT start the remaining cost-layer work (the fail-open spend cap, positive
evidence in _actual_cost, the five stale catalog prices). A separate chat owns
Stream B and holds the design context. If you find something there, file it
rather than fixing it.
```

---

## 8. Remaining order after WP-F

```
WP-G2  Context carry        F-10   (same-commit trap: estimate + create bodies
                                   together, or a permanent 402 loop)
WP-H   UX polish + gates    F-20 F-17 F-24 F-16 + issues #113 #115 #116 #117
                                   -> seed visual baselines LAST
--- operator: funded key -> one ~$0.02 live run -> deploy-verify ---
Stream B (separate branch off main): P1 fail-open spend cap, E2 positive
evidence in _actual_cost, the five stale _FALLBACK_CATALOG prices
```
