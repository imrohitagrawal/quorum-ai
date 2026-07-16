# Category 4 — Mechanism map (where each practice lives)

For every practice/finding: which mechanism carries it, and whether that mechanism
is **influence** (depends on someone remembering) or a **gate** (runs regardless).
The recurring failure was placing UI-testing entirely in the influence column.

## The four mechanisms, ranked by durability

| Mechanism | Durability | Shared? | Notes (verified) |
|-----------|-----------|---------|------------------|
| **CI-CD** (`.github/workflows/*`) | **Gate** | Yes (tracked) | The only always-runs-for-everyone layer. Existing: `ci.yml`, `test.yml`, `e2e.yml`, `deploy.yml`, `feedback-audit.yml` |
| **Hook** (`.claude/settings.json`) | Gate (local) | **NO** | `.claude/` is **gitignored** (`git check-ignore .claude` → ignored); `settings.json` has no `hooks` key today. A hook here runs only on the author's machine |
| **AGENTS.md / CLAUDE.md** | Influence | Yes (tracked) | Always loaded, strongest influence — but not a guarantee. **Verified: contains NO UI/visual/e2e testing rule** |
| **Skill** (built-in / vendored / factory) | Influence | Varies | Opt-in; nothing auto-invokes a skill on a code change. `/verify` exists but was never invoked on a UI change |

## Practice/finding → mechanism → influence-vs-gate

| Practice / finding | Mechanism today | Should be | Influence or gate | Action |
|--------------------|-----------------|-----------|-------------------|--------|
| No raw Markdown in rendered text (#30) | none | CI invariant | **Gate** | Built (`rendering-invariants.spec.ts`), flip to blocking on fix |
| Monotonic live timer (#29) | none | CI invariant | **Gate** | Built (RED-proven) |
| Transcript uses available width (#33) | none | CI visual snapshot (human-reviewed) | **Gate** | Built; seed baselines |
| Real-integration (not page.route) | mocked "e2e" only | CI smoke on real sim backend | **Gate** | Built + blocking |
| Verify → implement → document | chat + memory | `/verify` on nontrivial diffs + CI | Influence → Gate | Add `/verify` to the flow; the CI tests are the gate |
| "Use the e2e skill on UI changes" | chat only (evaporated) | AGENTS.md line + CI gate | Influence | Add AGENTS.md UI-testing section (influence) + rely on CI (gate) |
| Deploy gates on green CI | `workflow_run: ["CI"]` on **ci.yml only** | gate on CI + Tests + E2E | Gate (too narrow) | Widen `workflow_run` (UNFILED-B) |
| `/metrics` served | `fly.toml` scrapes it, app 404s | route exists or block removed | Gate (broken) | Fix + smoke (UNFILED-A) |
| Skill ≠ coverage | 108 skills present, ~0 wired | tests in CI | Influence vs Gate | Treat skills as how-to only (Cat 5) |

## The critical placement rule (the session's correction of its own plan)

Two topics in the transcript proposed "put the enforcement hook in
`settings.json`". That was **wrong here**: `.claude/settings.json` is gitignored,
so such a hook is local-only — not shared, not in CI, not reproducible on a fresh
clone. Below-the-line has two tiers:

```
.github/workflows/**   ← TRACKED, shared, runs for everyone  ← the REAL gate
─────────────────────────────────────────────────────────────
.claude/settings.json  ← gitignored here → LOCAL-ONLY  ← convenience only
```

**Rule:** shared enforcement must live in CI. A hook is a local fast-feedback
convenience. To make a hook shared you would have to un-ignore the settings file
(e.g. a `.gitignore` negation `!/.claude/settings.json`, matching Claude Code's
convention of `settings.json` = shared / `settings.local.json` = personal) — a
deliberate, separate decision, not a default.

## AGENTS.md's real job

Add a short UI-verification section to `AGENTS.md` pointing at the harness and the
`e2e-testing-patterns` / `webapp-testing` skills — as the human "why". Label it
explicitly: **influence, not the enforcement.** The enforcement is `e2e.yml`.
