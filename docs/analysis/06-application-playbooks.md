# Category 6 — Application playbooks

The forward-looking core: how to apply everything so the cycle does not repeat.
Three playbooks, each an ordered sequence tied to below-the-line enforcement.
Reuse the reusable standard in `docs/day-one-quality-standard.md`.

---

## Playbook A — NEW project, day one (greenfield)

Goal: the enforcement machinery exists **before the first feature**, so nothing
can slip past a gate that isn't there yet.

1. **Commit `docs/day-one-quality-standard.md` into the new repo first.** Paste
   its 7-point day-one prompt as the kickoff instruction. (It must be *tracked* —
   this PR is the commit that finally tracks it in quorum-ai.)
2. **Enumerate the project's quality dimensions** and state which apply:
   correctness, UI/UX rendering, real integration, security, cost/guardrails,
   API/schema contract, accessibility, data privacy, observability/health,
   deploy/release.
3. **For each applicable dimension, install a mechanical gate on day one, before
   features** — a real test against realistic data (a golden fixture, not clean
   mocks), wired into CI to run every PR. Add a hook only where "automatic on
   every change" is required, and only if its settings file is *tracked*.
4. **UI/UX specifically:** golden realistic fixture + `toHaveScreenshot` per view
   + global rendering invariants (no raw `##`/`**`, no overflow, monotonic
   counters) + a real-integration smoke (no `page.route`).
5. **Prove every gate RED-on-defect** before calling setup done. A gate not proven
   red is assumed broken. Define "done" by the gates.
6. **Write the standard + dimension→gate map into that repo's `AGENTS.md`** as the
   human "why" — labelled influence, not the enforcement.
7. **Never assume a capability works until a test exercises it against reality.**
   Flag anything unverified. Working order is always verify → implement → document.

---

## Playbook B — the CURRENT project (quorum-ai retrofit)

Goal: reach the enforced state without a rewrite, worst-gap-first. Much of the
audit and the UI harness are **already done this session**; the remaining steps
are ordered below.

1. **Audit the durability gap — DONE.** Verified (at audit time): no
   `toHaveScreenshot`; "e2e" uses `page.route` + sim backend; `AGENTS.md` has no
   UI-testing rule; `.claude/settings.json` is gitignored/local-only;
   `day-one-quality-standard.md` was untracked (this PR tracks it).
2. **Enumerate the real bug population — DONE.** See `01-bug-ledger.md` (all
   issues verified; two unfiled findings added).
3. **Golden fixture from real-shaped output — DONE.** `e2e/fixtures/golden-run.ts`.
4. **Highest-leverage gate first, proven RED — DONE.** Rendering invariants +
   smoke wired into `e2e.yml`; invariants RED-proven on #29/#30.
5. **Land the fixes under the gate (NEXT), blast-radius order:**
   - **#30 markdown** — route each prose surface through the appropriate renderer
     (block `formatAnswerText` / inline `mdInline`, both already HTML-escape → no
     XSS regression); source titles stay plain. Turns the invariant green; then
     **remove `continue-on-error` in `e2e.yml`** (the enforcement flip).
   - **#29 timer** — monotonic clamp on the elapsed base.
   - **#33 layout** — widen the transcript container / responsive columns; seed
     the visual baseline.
6. **Backend dimensions:** #26 degraded-mode signal + "simulated" banner; #31/#32
   real search (Tavily) as its own effort with #18/#20 cost accounting; #27 Fly
   volume; #19 cosmetic.
7. **Retrofit the influence layer:** ✅ `day-one-quality-standard.md` tracked (this
   PR); still TODO — add the UI-verification section to `AGENTS.md`; optional local hook.
8. **Tracker hygiene:** file UNFILED-A (`/metrics` 404) + UNFILED-B (deploy-gate
   scope); widen `deploy.yml` `workflow_run` to Tests + E2E; verify a deploy then
   close #21; run #24 staging smoke then close.

---

## Playbook C — ANY other existing project (generalized retrofit)

1. **Grep for what's MISSING, not what's present** — the fastest durability audit:
   `grep -r toHaveScreenshot`, look for `page.route` in "e2e" specs, check whether
   `AGENTS.md` mentions the practice, check whether the hook/settings file is even
   tracked (`git check-ignore`, `git ls-files`).
2. **Enumerate the real defect population from production**, not a sample, before
   concluding anything.
3. **Capture a golden fixture from a REAL run** so real-data bugs become catchable
   offline (no repeated paid runs).
4. **Install the single highest-leverage gate**, wire it into the *existing* CI
   workflow (tracked = shared), and **prove it RED on a currently-shipping bug.**
5. **Collapse ad-hoc paths into one** wherever a bug is "forgot surface #N" shaped.
6. **Burn down the backlog under the new gate** (red→green per fix).
7. **Add the influence layer last** (`AGENTS.md` + optional tracked hook).

---

## Why these break the cycle (and a chat instruction did not)

All three front-load the **below-the-line** work as the first deliverable, demand
**proof-of-gate** (red-on-defect), and **define "done" by the gate** — the three
properties that stop a hollow suite from masquerading as coverage. A chat
instruction ("use the e2e skill") lived above the line and evaporated; these
playbooks' whole job is to build the gate that runs whether anyone remembers or
not. See the durability hierarchy in [02-best-practices.md](02-best-practices.md).
