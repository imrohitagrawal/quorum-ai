# Category 5 — Skills strategy & provenance

Two halves: (1) **provenance hygiene** — know where every skill came from; (2) a
**fact-grounded authoring rubric** — build skills that say how/where/what, not
derivative "what-to-do" checklists.

## Provenance census (verified this session)

Four categories, not two. The transcript's early "0 downloaded" claim was wrong —
skills were vendored manually, bypassing the (empty) registry, which is why no
marketplace fingerprint existed to find.

| Category | Where it lives | Count (verified) | Examples |
|----------|----------------|------------------|----------|
| **Platform built-in** (Anthropic) | ships with the CLI, no file on disk | n/a | `/verify`, `/run`, `/code-review`, `/security-review`, `/init` |
| **User-global installed** | `~/.claude`, `~/.codex`, `~/.copilot` | 1 relevant | `taste-check` ← `github.com/kingkongshot/prompts` (has `metadata.json` with `githubUrl`) |
| **Project-vendored** (manually downloaded) | `.claude/skills/` (**gitignored**) | 6 | `systematic-debugging`, `subagent-driven-development` (obra/superpowers); `webapp-testing` (anthropic); `deploy-checklist`, `codebase-intel` (wednesday-solutions); `e2e-testing-patterns` (wshobson) |
| **Project factory-generated** (in-house) | `.agents/skills/` (tracked) | ~83 of 108 carry "Enterprise Skill Contract"; 25 without | `test-architecture`, `resilience-testing`, `contract-testing`, `llm-evaluation` |

- `configs/external-skill-registry.json` = `"skills": []` — the governance/
  onboarding flow was bypassed; provenance survives only in file frontmatter.
- The 6 vendored skills live under `.claude/` which is **gitignored** — so a
  teammate cloning the repo gets NONE of them; they exist only on this machine.

## The two-axis truth about skills

1. **Concern axis** (how they differ): observation (`/verify`, `webapp-testing`),
   suite construction (`e2e-testing-patterns`, `test-architecture`,
   `test-data-engineering`), specialized dimensions (`resilience-testing`,
   `llm-evaluation`, `accessibility-testing`, `contract-testing`), gates
   (`code-review`, `security-review`), debugging (`systematic-debugging`).
2. **Durability axis** (how they are identical): **every skill is above the
   enforcement line** — opt-in, never auto-firing. Having 108 changed nothing
   until one was invoked and its output wired into CI.

## Factory-generated depth problem (verified by reading one in full)

`test-architecture` (representative factory skill) has Steps like "Define UI/e2e
tests" and Outputs like `docs/50-test-strategy.md` — it emits a **planning
document, not a test**. Against the rubric below:

| Dimension the rubric wants | Factory skill provides? |
|---|---|
| what to do | ✅ |
| where (in the codebase) | ⚠️ only where the *doc* goes |
| how to do | ❌ no implementation/tool/code |
| what NOT to do | ⚠️ generic "forbidden actions" |
| how much / coverage / blast radius | ❌ no concrete thresholds |

Vendored external skills (e.g. `e2e-testing-patterns`) *do* carry real how-to
(actual `toHaveScreenshot` code) — but generic, not project-specific, and none
were wired into CI. **The 108-skill library is an illusion of coverage: labelled
drawers containing checklists, not tests.**

## Authoring rubric — a skill grounded in facts

When a local skill is genuinely needed, it must answer, for THIS repo:

- **How** — the exact command/tool/code, not "run tests".
- **Where** — the exact path(s) it reads/writes (e.g. `e2e/tests/invariants/`).
- **What exactly** — the concrete assertion (e.g. "no `**` in any text node"),
  not "check rendering".
- **Expected / NOT-expected** — the prove-red and prove-green behaviour.
- **How much / blast radius** — the coverage bound, and it must `log` what it
  drops (no silent truncation).

## Standing rules

1. **Skill ≠ gate; plan-doc ≠ test.** Never count a skill or a doc as coverage.
   Coverage exists only when a real test runs in CI and is proven red.
2. **Provenance-first adoption.** Prefer built-in, then audited vendored; record
   origin (`external-skill-registry.json`) instead of hand-dropping into
   `.claude/` (which is gitignored anyway).
3. **Skills are how-to for building the gate — never the gate.**
