# Product Repository Instructions

This repository was generated from Codex Product Factory Enterprise Edition.

## Operating rules — read these first

Placed first deliberately: instruction-following degrades as instruction count
rises, and earlier instructions are measurably better followed than later ones
(IFScale, arXiv:2507.11538). These are the non-negotiables. The reasoning behind
each one lives in `docs/evidence/` and `docs/103-incident-learnings.md`; this list
is the rule only.

**Truth**
1. **Verify by executing, never by reading.** State the command and what it
   printed, or say UNVERIFIED out loud.
2. **A green advisory job is not evidence it ran; a RED one is not evidence it
   measured.** Open the log and find the number.
3. **If a premise you were handed turns out to be false, STOP and say so.** Never
   repair it silently and carry on.
4. **Plain English. No jargon, no invented shorthand.**

**Tests**
5. **Every test ships with one line saying what turns it red.** Prove it by
   mutation: `cp` the file aside, mutate, restore from the copy, verify with
   `diff -q`. **Never `git checkout <file>`** — it discards uncommitted work.
   Confirm the run actually executed; a mutation that breaks collection proves
   nothing.
6. **A negative check needs a positive partner.** "No X found" is trivially true
   over nothing.
7. **Never parametrize a test over the constant it tests**; never assert a bound
   against the constant that defines it.
8. **Assert structure, not substrings** — a substring matches the prose that
   explains the thing. Use `tests/code_text.py` when you must read a file.

**Review**
9. **Fan out for review, never for building.** Subagents share one working tree.
   Tell every reviewer **IN CAPITALS** not to write, edit, `git checkout`,
   `git stash` or `sed -i` anything.
10. **Two lenses, not five.** Two reviewers ≈ four; one is worse (Porter et al.,
    *IEEE TSE* 1997). Spend the difference on verification, not more finders.
11. **Verify every reviewer claim before acting** — roughly a fifth do not
    survive. **Check the fix, not just the finding.**
12. **Cap review at TWO rounds**, then ship with leftovers filed. If two fixes in
    a row add defects, change the approach.

**Commands that bite if you get them wrong**
13. **Run e2e exactly as CI does**, or ~95 phantom failures appear:
    ```bash
    lsof -ti tcp:18085 | xargs -r kill -9
    cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 npx playwright test <spec> \
      --project=chromium --workers=1 --retries=0
    ```
14. **`make quality` / `make validate` do NOT include the blocking changed-lines
    coverage gate.** Run `make diff-cover DIFF_BASE=origin/main` before pushing.
15. **Run `pytest` and `make diff-cover` serially** — they race on a shared path
    (#113).
16. **`make format` reformats test assertions** and breaks `sed`-style anchors.
    Grep for the real text before any programmatic edit.

**Shipping**
17. **One work package, one pull request**, merged before the next starts. Merge
    `main` into your branch **before** starting. Check you are on your branch
    before committing.
18. **Done means merged AND running in production.** Verify three ways: the
    deploy **job** ran (not `skipped`/`cancelled` — check the job, not the run's
    rollup), `/status.build_sha` equals the merged SHA, and the thing you built
    actually fires. Probe production only where it costs nothing.
    Two traps, both paid for:
    - **`gh run list --commit <SHA>` silently returns `[]` in this repo.** Use
      `--branch main` and match on the SHA prefix.
    - **A merge produces two runs; one is `cancelled` by concurrency dedupe.** A
      wait-loop keyed on "any completed run for this SHA" fires on the cancelled
      one and reports done while production is still on the old build. Resolve
      the **newest run by `createdAt`**, then read its Deploy **job**.
19. **Close more than you open.** If an item is bigger than it looked, say so and
    stop — do not file and continue.
20. **A pull request opens with one line saying why this item outranks the top of
    the backlog.** If that line cannot be written honestly, the ranking is wrong.
    Discovering a higher-ranked item mid-work is a **mandatory stop**: park the
    branch, re-run selection, record it.

**Before adding a gate**, measure its yield against real defect history and state
what it cannot see. Measured here: **0 of 16** `src/` defects were caught by an
automated check; **10 of 16** by adversarial review
(`docs/metrics/defect-discovery-audit.md`).


## Simplified start

The user may start in either way:

1. Fill `PRODUCT_IDEA.md`; or
2. Tell the idea directly in the Codex prompt.

If the idea is supplied in the prompt, first write it into `PRODUCT_IDEA.md`. Then run the `idea-intake-clarifier` skill. Ask the smallest useful set of clarifying questions before generating requirements, architecture, Jira issues, Confluence pages, tests, or implementation code.

Maintain `docs/00-factory-console.md` after every meaningful step. It must show current phase, next best action, suggested prompt, questions, assumptions, suggestions, and validation status.

## Mandatory lifecycle

Run `.agents/skills/factory-orchestrator/SKILL.md` before implementation.

Do not code until these exist and validate:

- `docs/01-product-brief.md`
- `docs/03-source-of-truth.md`
- `docs/10-functional-requirements.md`
- `docs/11-non-functional-requirements.md`
- `docs/12-acceptance-criteria.md`
- `docs/17-requirement-registry.md`
- `docs/18-requirement-traceability-matrix.md`
- `docs/20-architecture.md`
- `docs/21-domain-model.md`
- `docs/40-threat-model.md`
- `docs/42-ai-safety-grounding.md`
- `docs/50-test-strategy.md`
- `docs/60-implementation-plan.md`
- `docs/70-ci-cd-plan.md`
- `docs/80-observability.md`

## Jira workflow

Use only statuses defined in `configs/jira-statuses.json`:

Backlog → To Do → Ready For Dev → In Development → Code Review → CI Validation → QA Ready → In QA → QA Verified → Closed.

`Cancelled` and `Duplicate` are terminal. `Closed` can be reopened only with explicit human approval and reason.

## Validation

Run:

```bash
make validate
make quality
```

Stop on failed validation gates.


## Review before "done"

Green gates are necessary but not sufficient — they catch known failures, not
new bugs a change introduces. Before declaring any non-trivial change complete:

- **Adversarially review the diff with independent subagents.** At minimum a
  correctness pass; and for anything touching security, secret handling, auth,
  or detection/validation logic, a reviewer whose explicit job is to *break*
  the change and find an evasion. Do this proactively — do not wait to be
  asked, and do not rely on a single self-assessment.
- **A behavioural change ships with a test that would fail without it.** This
  applies to helper scripts too (e.g. `scripts/security_scan.py`), not only
  `src/` — CI coverage (`--cov=src`) does not see them.
- **When you loosen or suppress a check, prove both directions:** the false
  positive is gone AND every genuine case the check must still catch is still
  caught. Never gate a secret/threat check on whole-line substrings; key off
  the matched token or value.
- **Verify by executing, never by reading.** A statement about what a tool,
  gate, or test does is UNVERIFIED until you have run it and read its output.
  This is not a style preference — it is the failure mode that has cost this
  project the most, and it applies to human and AI contributors equally.
  Measured examples, all from one work package
  (`docs/metrics/mutation-gate-study.md` §8): a CI gate reported green for
  months while aborting before it measured anything, and the issue to promote it
  cited that abort as a passing run; two freshly-written tests asserted only on
  printed text and stayed green under the mutation they existed to catch; a
  guard asserting `"sys.platform" in source` survived the constant being flipped
  to the wrong value. In each case the reading was confident and the run
  disagreed.
  - Before promoting an advisory gate, **open its job log** and confirm it
    produced its number.
  - **A RED gate is not evidence it measured either.** A non-zero exit can mean
    the gate fell over before measuring anything — which is what #158 was, and
    the failure message named the wrong cause. Read the log and find the number
    before attributing a red gate to the diff in front of you.
  - Before excluding tests from a gate, **measure** what that removes.
  - Before claiming a check bites, **mutate the code and watch it go red** —
    `cp` the file aside and restore from the copy, never `git checkout`.
- **Every gate must report what it counted, and refuse to pass on an empty
  input.** Nearly every gate here is a negative check ("no line uncovered", "no
  secret matched", "no requirement lacks a row"), and all of those are trivially
  true over nothing. Measured 2026-07-29: **13 of 21 CI jobs could reach a
  terminal status having measured nothing, four of them blocking** — including
  `diff-cover`, reproduced exiting **0** on a diff with genuinely uncovered new
  lines because its coverage report mapped none of them. Floors now exist
  (`docs/analysis/03-enforcement-machinery.md`); when you add a gate, add its
  floor in the same commit and prove it red against an empty input.
- **Do not add a new gate before checking how the last N real defects were
  found.** Measured over every fix commit touching `src/`: **0 of 16 were caught
  by an automated check**; 10 of 16 came from adversarial review. The
  per-commit table, the method and its limits: `docs/metrics/defect-discovery-audit.md`. Gates here
  prevent regressions; they do not detect new defects. The multi-lens review fan
  is what does, and the slice built without one leaked 10 escaped defects against
  0 for the two built with one.


## UI verification (the built workspace)

This is **influence, not enforcement** — the binding gate is CI (see below), not
this file. But when you touch the workspace UI (`src/product_app/static/app.js`,
`app.css`, `templates/workspace.html`):

- **Drive the real UI, don't just read the code or run a green test.** A passing
  unit test on clean sim data has repeatedly hidden real-LLM-output bugs
  (raw Markdown, a non-monotonic timer, cramped layout). Render against the
  **golden messy fixture** (`e2e/fixtures/golden-run.ts`) — real-shaped provider
  output with headings, bold/italic (both `*` and `_`), inline code, links,
  ordered lists, blockquotes, long multi-paragraph answers, an empty-citation
  slot — and look at it as a user would (screenshot at 1440px).
- **The below-the-line gate is `e2e/tests/invariants/`** — driven in CI by
  `.github/workflows/e2e.yml`:
  - `rendering-invariants.spec.ts` — walks `#main-content` and asserts NO raw
    Markdown survives in any text node (`**`, `##`, `` `code` ``, `](url)`,
    `_ _`/`__ __`, line-start `>`), a **monotonic** elapsed timer, no horizontal
    overflow, and inline code stays verbatim. **Blocking.**
  - `visual-snapshots.spec.ts` — human-reviewed `toHaveScreenshot` baselines for
    the result + transcript views (Linux baselines seeded in CI; see
    `.github/workflows/seed-visual-baselines.yml`).
  - `degraded-banner.spec.ts` — the result view must surface a degraded banner
    whenever the panel came up SHORT, so an incomplete run is never shown as a
    complete one. Note this line **described a contract the code did not have**
    until WP-H: the banner was keyed on `local_count > 0` — "were any answers
    simulated?" — which is blind to a slot that produced *no* answer (cancelled,
    or the run deadline expired). Such a slot is counted in neither `live_count`
    nor `local_count`, so a run with three live answers and one missing showed no
    banner at all while the headline read "3 of 4 models aligned". The condition
    is now `local_count > 0 || missing > 0` — equivalent to
    `live_count < slot_count` **whenever `live + local <= slot_count`**, which is
    all the server can emit. So the sentence above is true as written *now*, and
    was not before. A doc asserting a contract is not the contract.
- **A new provider-text surface must route through the markdown renderer**
  (`setProse` for block prose, `setInlineProse` for inline/cell surfaces) — never
  raw `textContent`/`mkEl`. Source titles are the one exception (provider
  metadata → plain text). Add its shape to the golden fixture so the gate covers
  it; the gate only catches surfaces the fixture exercises.
- **Prove RED then GREEN.** Any UI-gate change must be shown failing on the defect
  and passing after the fix (revert-and-rerun), and any timing-sensitive spec run
  N≥10× to establish a real flake rate — not asserted once.


## V5 deterministic skill routing

Before choosing a skill manually, run or simulate:

```bash
make skill-route
make next
```

Use the recommended driver skill as the single writer for the next missing artifact. Use reviewer skills only to critique and request changes. If skills conflict, apply this precedence: safety/security/privacy/compliance, explicit user approval within policy, approved Jira/Confluence source of truth, local factory policies, ADRs, driver skill output, reviewer findings, external skill suggestions.

ORBI-specific rules are not global defaults. Activate them only through `make apply-orbi-profile` or explicit user instruction, then read `AGENTS.ORBI.md`.


## V5.1 study, publishing, and public-artifact backbone

After the MVP, requirements, architecture, tests, and release evidence are clear enough, the factory must also prepare study and communication artifacts:

- `docs/96-study-artifact-publishing.md`
- `docs/study/00-study-index.md`
- `docs/study/M1-problem-and-mvp.md`
- `docs/study/M2-ai-solution-and-work-easing.md`
- `docs/study/M3-security-scalability-enterprise.md`
- `docs/97-faq-wiki-plan.md`
- `docs/98-technical-article-plan.md`
- `docs/99-linkedin-post-plan.md`
- `docs/100-industry-and-integration-practices.md`

The first question is always: what is the MVP and most valued outcome? Public and Confluence artifacts must explain how the product solves a real problem using AI, how it eases work, how it is secure and scalable, and how it meets enterprise standards.

For Git or Confluence publication, draft first, show the exact diff/page payload, require explicit human confirmation, publish only through approved tools, re-read after publish, and update `docs/37-jira-confluence-sync-log.md`.


## V5.2 external-skills-first and skill onboarding

When a new capability is needed, do not immediately invent a local custom skill. First use `external-skill-discovery-advisor` and `skill-research-librarian` to check existing skills from skills.sh, official providers, and reputable GitHub sources.

The adoption flow is:

```text
find existing skill -> audit provenance/security/license -> approve mode -> register -> route -> validate -> optionally wrap locally
```

Default activation mode for external skills is `reviewer-only`. External skills can help with Superpowers-style planning/worktrees/handoff, Addy-style SDLC, PM discovery, AI PM evaluation, UI/UX, testing, database/platform, and publishing. They still cannot override local policies, source-of-truth records, validation gates, or explicit human approval for side effects.

Use these commands:

```bash
make skill-discover
make skill-onboarding-check
python scripts/audit_external_skill.py <skill-folder>
python scripts/onboard_external_skill.py --name <name> --source-url <url>
```

## Session continuity

Before ending or handing off a session:

```bash
make next
make skill-route
make handoff
```

A new session must read `AGENTS.md`, `docs/00-factory-console.md`, and `docs/session-handoff.md` before editing. Use git worktrees for parallel sessions and keep one owner per artifact family.

## User-guided start

If `PRODUCT_IDEA.md` is empty, placeholder-only, or the user gives the idea in chat, ask for the problem in plain language first. Then suggest the next best action. The user should not have to guess which skill or file to use.
