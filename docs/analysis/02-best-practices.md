# Category 2 — Best practices / principles

The durable rules the session distilled. Each is stated with the failure it
prevents and — crucially — **how it becomes a gate**, because a principle that
lives only as prose is influence, not enforcement (that is itself principle #3).

| Principle | What it means | Failure it prevents | Source | How it becomes a gate (not prose) |
|-----------|---------------|---------------------|--------|-----------------------------------|
| **Verify → implement → document** | Confirm ground truth (read code, run the cheap check, look at real output) before implementing; document the decision in the repo after | Assume→implement→verify: confident action on an unchecked premise | memory `verify-first-then-implement` | `/verify` per change + CI tests; the order is enforced by the gate defining "done", not by remembering |
| **Enumerate the full population before "all/none/it-works"** | Never generalize from one sample; list the real set first | Narrow-sample → confident-wrong conclusion (the session's fractal root failure: clean sim → "works"; empty registry → "0 downloaded"; one skill → "all hollow") | memory `narrow-sample-wrong-conclusion` | A finding must cite the enumerated population (e.g. this ledger cites every issue, the harness walks the *whole* DOM) |
| **Real-eye VISUAL testing, not just functional/API** | Assert what renders (markdown, layout, color, alignment, timer sanity), not only bounding boxes and JSON shapes | "Tested the box, not the content" — geometry green while `##` shows raw | memory `simulated-data-hides-real-bugs`, `tdd-and-live-verification` | Visual snapshots (`toHaveScreenshot`) + rendering invariants over real-shaped data |
| **Realistic data, not clean mocks** | Feed real, messy provider output (markdown, long text, empty citations, long runs) | Clean sim data hides the whole class of real-data bugs (#29/#30/#33) | memory `simulated-data-hides-real-bugs` | The committed golden fixture `e2e/fixtures/golden-run.ts` |
| **Below-the-line enforcement** | Only CI tests + tracked hooks *guarantee* a behaviour; chat/skill/memory/AGENTS.md are influence | A rule that depends on remembering will eventually be forgotten at the moment it matters | `docs/day-one-quality-standard.md`; memory `verify-first-then-implement` | Put the rule in `.github/workflows/*` (tracked); a `.claude/` hook is local-only (gitignored) |
| **Skill ≠ gate; plan-doc ≠ test** | Owning a skill or emitting a plan document is not coverage | The 108-skill "illusion of coverage": drawers labelled "e2e/resilience/a11y" that contain checklists, not tests | transcript blast-radius audit | Coverage counts only when a real test runs in CI and is proven red on a real defect |
| **Prove-red before trusting a gate** | A gate must fail on a deliberately-introduced (or existing) defect before it is believed | A hollow/no-op suite masquerading as coverage | `docs/day-one-quality-standard.md` (anti-illusion clause) | This session proved the invariant gate RED on #29/#30 before wiring it |
| **Collapse ad-hoc paths into one** | When a bug is "forgot surface #N" shaped, route all instances through one path so the bug becomes unrepresentable | #30 exists because ~11 surfaces each render text ad-hoc | transcript #30 audit | The #30 fix routes all provider text through one `renderProse()`; then there is one thing to test |
| **Flag provider-only features as unverified** | Anything that only behaves against a real provider (search, citations, live cost) is unverified until a real-provider test exists | Silently assuming `:online`/citations/fallback work | memory `minimize-paid-production-runs` | Explicit UNVERIFIED marking (see the ledger + `08-unverified`) |
| **Plans foreground prevention playbooks** | A plan must spell out new-project + existing-project prevention in substance, not bury it | The forward-looking core read as "missing" when compressed to a line | memory `plans-foreground-prevention-playbooks` | `06-application-playbooks.md` gives each playbook ordered, gate-tied steps |
| **Decompose vertical → horizontal, measure each** | Slice into canonical vertical deliverables, then split horizontally; categorize, measure, and quality-gate each | One big undifferentiated change with no per-piece measurement | memory `plans-highlight-skills`; brief | `07-methodology.md` + per-deliverable prove-red |

## The one idea under all of them — the durability hierarchy

```
chat instruction        ← evaporates
skill I must remember    ← opt-in
memory                   ← persistent hint, still influence
AGENTS.md / CLAUDE.md    ← always-loaded, strong influence — NOT a guarantee
──────────────────────────  the line between influence and enforcement
CI test + tracked hook   ← runs whether anyone remembers or not
```

The recurring UI-bug cycle happened because the UI-testing rule lived **entirely
above the line** (chat + an opt-in skill) with nothing below it. The fix is not
better words above the line — it is putting the actual gate below it. Every
principle above is paired with its below-the-line mechanism in
[04-mechanism-map.md](04-mechanism-map.md).
