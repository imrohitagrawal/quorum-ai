# Analysis — verified plan index (taxonomy)

This folder turns a long working-session transcript into a **granular, verified,
categorized plan**. Its governing rule — the session's own hardest lesson — is:
**enumerate and verify the full population before any "all / none / it-works"
claim.** Every factual claim here was re-checked against ground truth in a clean
session; claims that could not be verified are marked **UNVERIFIED**, never guessed.

Source brief: `docs/analysis-plan-brief.md`. Companion standard:
`docs/day-one-quality-standard.md`.

## How this was verified (not trusted from the transcript)

- **Issues/PRs:** `gh issue list --state all`, `gh pr list --state all`, per-issue
  `gh issue view`.
- **Bugs:** opened each cited file and re-derived the current line numbers.
- **CI / gitignore / skills:** read `.github/workflows/*`, `git check-ignore .claude`,
  `configs/external-skill-registry.json`, the skill trees, and the memory dir.
- **The enforcement harness in category 3 was actually built and PROVEN RED** in
  this session against current code (see `03-enforcement-machinery.md`).

The transcript contained claims later corrected inside it (e.g. "0 skills
downloaded" was wrong) and one correction in the brief that ground truth does not
support ("close #21" — see the ledger). Those corrections are applied here.

## The taxonomy (7 categories — every item maps to exactly one)

| # | Category | One-line definition | File |
|---|----------|---------------------|------|
| 1 | **Bug ledger** | Every concrete defect/finding, verified against tracker + code | [01-bug-ledger.md](01-bug-ledger.md) |
| 2 | **Best practices / principles** | The durable *why / what-good-looks-like* rules distilled | [02-best-practices.md](02-best-practices.md) |
| 3 | **Enforcement machinery** | The below-the-line *gates* that make principles automatic (built + proven red) | [03-enforcement-machinery.md](03-enforcement-machinery.md) |
| 4 | **Mechanism map** | Each practice/finding → skill / AGENTS.md / hook / CI-CD, with influence-vs-gate rationale | [04-mechanism-map.md](04-mechanism-map.md) |
| 5 | **Skills strategy** | Fact-grounded skill authoring + provenance hygiene (built-in/user-global/vendored/factory) | [05-skills-strategy.md](05-skills-strategy.md) |
| 6 | **Application playbooks** | How to apply it all: new project, quorum-ai retrofit, any existing project | [06-application-playbooks.md](06-application-playbooks.md) |
| 7 | **Methodology** | The operating loop: plan-first → verify↔implement → document; decompose + measure + gate | [07-methodology.md](07-methodology.md) |
|   | **Unverified + next step** | What remains unverified and the single next execution step | [08-unverified-and-next-step.md](08-unverified-and-next-step.md) |

## Exhaustiveness proof (nothing left uncategorized)

- Every issue (#16 CLOSED; #18,#19,#20,#21,#24,#26,#27,#29–#33 OPEN — the gaps in
  the range are MERGED PRs #22/#23/#25/#28, not issues) + the two unfiled findings
  (`/metrics` 404, deploy-gate scope) → **Cat 1**.
- Transcript principles (durability hierarchy; verify-first; "test the box, not the
  content"; skill ≠ gate; doc ≠ test; narrow-sample → wrong conclusion) → **Cat 2**.
- Every test artifact (golden fixture, rendering invariants, visual snapshots,
  real-integration smoke, CI job) → **Cat 3**.
- Every "put it in X" placement decision → **Cat 4**.
- The 9 memory files (8 indexed in MEMORY.md + `plans-foreground-prevention-playbooks`),
  the 108/6 skill census, `/verify` + `taste-check` provenance → **Cat 5**
  (principle-bearing memories cross-referenced into Cat 2).
- The three "apply next time / here / elsewhere" asks → **Cat 6**.
- The plan→loop→document + decompose/measure/gate operating rules → **Cat 7**.

No transcript item or ground-truth finding falls outside these seven.

## Status legend (used across the tables)

- **VERIFIED** — re-checked against code/tracker this session.
- **UNVERIFIED** — plausible but not confirmed; do not act on as fact.
- **RED-PROVEN** — a committed test fails on current code, demonstrating the bug.
- **OPEN / CLOSED** — GitHub issue state as of verification.
