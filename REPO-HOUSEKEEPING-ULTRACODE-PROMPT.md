ultracode

You are the **main orchestrator**. You own the working tree, the git history, and every gate.
You do not delegate the gates to a subagent — you run them and read their output.

Read `AGENTS.md` in full before anything else. It overrides this file wherever they disagree.

---

# The task

This repository has accumulated structural debt that measurably obstructs work. Audit it as a
principal architect, an engineering manager and a hygiene auditor; synthesise the three views
against the tree; then execute the cleanup as a sequence of small, individually-gated pull
requests — and add the gates that stop the debt returning.

**This is housekeeping, not refactoring.** The distinction is load-bearing and is enforced
below.

---

# 0. Guardrails — read these before anything else

These are not advice. Violating one is a stop-and-report event.

## 0.1 Forbidden without stopping and asking the human

- **Deleting anything untracked.** **19** root `.md` files have no git history — see 1.2.
  (An earlier draft of this line said 55. It was wrong; the corrected split is in 1.2.)
  PR 1 gives the only sanctioned route: commit first, delete second.
- **Deleting or moving anything named in 0.1a.** Read that list first.
- **Moving or renaming a top-level directory**, and in particular any of
  `docs` `src` `tests` `scripts` `e2e` `profiles` — `tests/unit/test_cited_paths_resolve.py`
  pins those six names in a regex.
- **Rewriting git history.** Nothing here warrants it.
- **Touching `.env`.** It is gitignored, mode 600, and was never committed. Leave it alone.
- **Lowering any threshold, adding `# pragma: no cover`, or deleting a test** to go green.
- **Any change under `src/product_app/`.** See 0.2.

## 0.1a Never delete or move these — they carry state you cannot rebuild

| File | Why it survives |
|---|---|
| `docs/analysis/2026-08-11-session-handoff.md` | **The continuation plan.** Names the next work package (#290), what is blocked and why, and the traps a prior session paid for. Losing it loses the thread. |
| `R2-S2-S4-ULTRACODE-PROMPT.md` | Pinned by three tests; its docstring calls it the executable a future session pastes. |
| `REPO-HOUSEKEEPING-ULTRACODE-PROMPT.md` | This file. |
| Anything `validate_*.py`, `configs/*.json` `required_docs`, or `pyproject.toml also_copy` names by path | A gate hard-fails on its absence. |

**Before moving or deleting ANY file, check it is not load-bearing:**

```bash
grep -rn "<filename>" scripts/ tests/ configs/ pyproject.toml .github/ Makefile
```

A hit means something asserts that path. Update it in the same commit or leave the file alone.

**A trap that already caught this repo once:** the continuation handoff used to live at root as
`HANDOFF-2026-08-11-NEXT-SESSION.md`, where `.gitignore:31` (`HANDOFF-*.md`) kept it out of git
— unrecoverable, absent from a fresh clone, and sitting in the group this prompt marks as safe
to delete locally. It was moved to `docs/analysis/` and committed for exactly that reason.
**The ignore pattern has no directory anchor**, so restoring a `HANDOFF-*` name silently
un-tracks the file again at any path, `docs/` included.

## 0.2 `src/` is out of scope, entirely

`src/product_app/` is flat: 24 modules, no sub-packages. Four files —
`query_runs.py` (3,509), `providers.py` (2,391), `evaluation.py` (2,259), `costs.py` (2,049) —
are **45% of 22,506 lines**. That is a real finding and the audit should record it.

**Do not act on it.** Splitting them is a refactor, every import path is asserted somewhere, and
mixing it with a file-move cleanup produces an unreviewable diff. File it as an issue with the
measurement and move on.

## 0.3 Do not repeat these measured mistakes

- **Check exit codes, never grep output.** `make quality | grep passed` hid a failing
  `make type-check` in the session that produced this prompt. Use `make X >/dev/null 2>&1; echo $?`.
- **Re-derive the required merge contexts** from
  `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`.
  The table in `AGENTS.md` has been wrong twice.
- **Delete `.data/feedback_events.sqlite3` before any e2e sweep.** It accumulates a durable
  per-IP mint cap until `/ui` returns 429, and `SESSION_MINT_CAP_OVERRIDE=600` does **not**
  prevent it. Measured: 61 failed / 180 passed → `32 passed` after deleting the file, nothing
  else changed.
- **The visual e2e lane is flaky in CI.** Observed one failure (8,353 px diff) on a branch that
  changed only a workflow and a test file, passing on re-run. Re-run before believing it. Never
  run it locally; never `--update-snapshots`.
- **`e2e/tests/review/` exists locally, is gitignored, and makes `make quality` RED on this
  machine while green in CI.** Before blaming your diff, run `ls e2e/tests/review/`.
- **Mutation proof is `cp` aside → mutate → restore → `diff -q`.** Never `git checkout <file>`.

## 0.4 Review posture

- Fan out for **review**, never for building. One sole tree-writer per build phase.
- Tell every reviewer **IN CAPITALS** not to write, edit, `git checkout`, `git stash`, `git reset`
  or `sed -i` anything. A reviewer that must mutate gets its own `git archive HEAD | tar -x` copy.
- Two lenses, not five. Verify every reviewer claim by execution before acting on it.
- Cap review at **two rounds**, then ship with the leftovers written down.
- Tell reviewers, verbatim: *"for every number, superlative, and causal claim in the diff's
  comments, commit body and PR description, name the command that produces it — or mark it
  UNVERIFIED."*

---

# 1. What is already measured

Verified on `5d9eec8`. Treat as **assumed** and re-check the cheap ones — roughly half of what a
handoff asserts does not survive contact with the tree.

| Finding | Measured |
|---|---|
| Root `.md` files | **101** — see 1.2, the split matters more than the total |
| Duplicate `docs/` numbers | **14 collisions, 28 files**; two whole series collide at 70–73 |
| `design_handoff_quorum_ui/` vs `docs/design-handoff/` | shared files **byte-identical** (md5) |
| `docs/factory/` vs `docs/` root | **6 byte-identical, 2 diverged** — same number, different content |
| `e2e/undefined/` | directory literally named `undefined`, **2 tracked PNGs**, ~500 KB |
| `diagrams/excalidraw/` | **4 differently-named files, identical content** |
| Root junk | `.coverage` ×7 (macOS copy collisions, 372 KB), `.DS_Store`, 3.8 MB PNG, a stray test |
| `tests/` | `perf/` **and** `performance/`; **28 uncategorised files** at `tests/` root |
| `.gitignore` | **`.hypothesis/` is not ignored** (1.1 MB on disk) |
| `docs/` numbering scheme | **documented nowhere** — grep for range language returns zero hits |

**Explicitly NOT found — do not claim otherwise.** `.env` was never committed (no adding commit
on any branch). No virtualenv, `.pyc`, `__pycache__` or `node_modules` is tracked. Only
`.env.example` is tracked, correctly — a doc gate asserts it stays in sync with `Settings`.
**There is no credential exposure and no history to purge.**

## 1.2 The root-file split, and a correction this prompt owes you

**The first draft of this prompt said "77 `*ULTRACODE-PROMPT*`, 55 untracked". That was wrong**,
and it was wrong in a way that would have made the procedure below fail silently. It is corrected
here rather than quietly fixed, because this prompt spends section 0.3 telling you not to trust
inherited numbers and must be held to the same standard.

Measured on `d3c860c`:

```bash
git ls-files --full-name | grep -cE '^[^/]+\.md$'                          # 45  tracked
git ls-files --others --exclude-standard | grep -cE '^[^/]+\.md$'          # 19  untracked, NOT ignored
git ls-files --others --ignored --exclude-standard | grep -cE '^[^/]+\.md$' # 37  gitignored
```

45 + 19 + 37 = **101**. Three groups, three different correct treatments:

| Group | n | Treatment | Why |
|---|---|---|---|
| **Tracked** | 45 | plain `git mv` to `docs/archive/2026-08/` | already in history, fully reversible |
| **Untracked, not ignored** | 19 | `security_scan.py` → `git add` → commit → delete in a second commit | no history today; this is the only group needing the scan gate |
| **Gitignored** (`HANDOFF-*.md`) | 37 | **leave them, or delete locally. Do NOT force-add.** | see below |

**The gitignored group is the trap.** `.gitignore:31` is `HANDOFF-*.md`, with no directory
anchor — so the pattern **follows the files into the archive**. Verify it yourself before
relying on this; the destination does not exist yet, so use variables rather than literals:

```bash
DEST=docs/archive/2026-08          # not created yet
for f in HANDOFF-2026-08-11-NEXT-SESSION NEXT-SESSION-ULTRACODE-PROMPT-2026-08-09; do
  printf '%-46s ' "$f"
  git check-ignore -q "$DEST/$f.md" && echo "STILL IGNORED at the destination" || echo "trackable there"
done
```

Measured on `d3c860c`: the `HANDOFF-*` name comes back **STILL IGNORED**; the
`NEXT-SESSION-ULTRACODE-PROMPT-*` name comes back **trackable**. Same directory, opposite
outcome, decided entirely by the filename.

So `git mv` on a `HANDOFF-*.md` moves the file and commits nothing. Archiving them into git needs
`git add -f`, and **that is a decision, not a mechanic**: someone deliberately excluded these from
version control. Overriding that without knowing why is not housekeeping.

They are also **local-only clutter** — invisible to CI, absent from a fresh clone. From the
repository's point of view the root problem is 45 + 19 = 64 files, not 101.

**Therefore: do not force-add the 37.** Report them with a recommendation and let the human
decide. Deleting them locally is safe and affects nobody else.

## 1.1 The constraint that shapes everything: ~60 gates assert literal file paths

1. **`tests/unit/test_cited_paths_resolve.py`** turns every stale prose path *on a line your
   branch adds* into a merge blocker. Its `_EXEMPT` names itself by path; its `_CITATION` regex
   pins the six top-level directory names.
2. **`tests/unit/test_mutation_copy_completeness.py`** statically greps the suite for path
   literals and requires each top-level entry in `pyproject.toml` `[tool.mutmut].also_copy`.
   A new top-level directory is a two-file change minimum.
3. **Ten `validate_*.py` scripts hard-code ~60 doc filenames**; `configs/*.json` carries **149
   more** `docs/...` references, and `factory-gates.json`'s `required_docs` are existence-checked.
4. **`AGENTS.md` states the invariant-spec count (17)**, compared against the filesystem by
   `tests/test_doc_gate_consistency.py`. Keep it a digit — the gate cannot read "seventeen".
5. **`validate_tests.py` hard-fails if `tests/performance/` or `tests/e2e/` is missing**, so
   merging the duplicate perf directories is a four-file change (`validate_tests.py`, `Makefile`
   `PERF_TEST_PATHS` and `PERF_MIN_TESTS`, `pyproject.toml`).

---

# 2. Phase A — architect analysis (read-only fan, 3 agents, parallel)

Each agent is **READ-ONLY, IN CAPITALS**. Each returns **evidence, not proposals** — file paths,
counts, and the command that produced each number. A claim without a command is not a finding.

**A1 — Principal architect.** Read `docs/20-architecture.md`, `docs/21-domain-model.md` and the
ADR index *before* judging anything; do not reason around them. Where does the structure fight
the work? Module boundaries, coupling, what a change to one concern forces you to touch. Include
`src/` in the *analysis* — it is excluded from action, not from observation.

**A2 — Engineering manager.** Onboarding and discoverability. A new contributor lands here: what
can they not find? Which of the 101 root files would they read first, and is it the right one?
Is `docs/00-start-here.md` accurate? Where would they waste a day? Read `README.md`,
`docs/00-start-here.md`, `AGENTS.md` and `docs/analysis/2026-08-11-session-handoff.md` as a
newcomer would.

**A3 — Repo-hygiene auditor.** Mechanical and exhaustive: duplicates by **md5** (not by name),
dead and orphaned files, `.gitignore` gaps, numbering collisions, tracked-but-generated
artifacts, files whose location contradicts their kind. Produce a table with sizes and hashes.

---

# 3. Phase B — synthesis against the claims (1 agent)

One synthesiser receives all three reports. It must:

1. **Verify every claim by executing it** before accepting it. Report any that evaporate — that
   list is itself valuable.
2. **Reconcile contradictions explicitly.** Where two lenses disagree, say which is right and
   why. Do not average them.
3. For each surviving finding, record:
   - **blast radius** — exactly which gates assert the path (`file:line`),
   - **reversibility** — tracked (git recovers it) / untracked (unrecoverable) / config-only,
   - **value ÷ blast radius** rank.
4. Write `docs/analysis/<today>-repo-structure-audit.md`.

**The synthesiser proposes the action list. It changes nothing else.**

---

# 4. Phase C — execution, one concern per pull request

Sequential. Each PR fully gated and merged before the next starts. Ordered by risk, lowest first.
**If any PR's blast radius turns out larger than the audit said, STOP and report** — do not push
through.

### PR 1 — Clear the repo root

**Re-derive the three groups first** with the three commands in 1.2. Do not trust the counts —
they are a snapshot and the first draft's were wrong.

**Group 1 — tracked (45).** Plain `git mv` to `docs/archive/2026-08/`, one commit. Already in
history, fully reversible, no scan gate needed.

**Group 2 — untracked, not ignored (19).** This is the only group that needs the safety dance,
because these files have no history at all:

1. **`python3 scripts/security_scan.py` over them first. If it reports ANY finding, STOP and
   report** — do not commit. Committing never-scanned files is the one way this task can leak a
   secret into history, and history is hard to purge.
2. `git mv` to `docs/archive/2026-08/`, `git add`, **commit**. They now have git history.
3. A **second commit** removes them from `HEAD` (`git rm`).

**Group 3 — gitignored `HANDOFF-*.md` (37). Do NOT force-add them.** Per 1.2 the ignore pattern
follows them into the archive, so `git mv` would move the file and commit nothing. Force-adding
overrides a deliberate prior decision to keep them out of version control. They are local-only
and invisible to CI. **Report them with a recommendation and let the human decide.**

### Exceptions — leave these at root

- **`R2-S2-S4-ULTRACODE-PROMPT.md`** — tracked and pinned by three tests
  (`tests/test_ultracode_prompt_enforcement_contract.py`, `tests/test_findings_ledger_fs5_status.py`,
  `tests/test_findings_ledger_consistency.py`) plus `pyproject.toml also_copy`. Its docstring says
  it is the executable a future session pastes. Moving it is a separate concern with its own PR.
- **`REPO-HOUSEKEEPING-ULTRACODE-PROMPT.md`** — this file. It is an executable procedure, not
  session output. See PR 6's distinction.
- **`README.md`, `AGENTS.md`, `CLAUDE.md`, `CHANGELOG.md`, `DEPLOY.md`, `PRODUCT_IDEA.md`** and
  anything else `validate_*.py` or `pyproject.toml also_copy` names by path. **Check before
  moving anything**: `grep -rn "<filename>" scripts/ tests/ pyproject.toml .github/`.

Net effect: root drops from 101 `.md` to roughly 8 tracked plus whatever the human decides about
group 3. Nothing is unrecoverable — `git show <sha>:<path>` retrieves any archived file forever.

Write a manifest (file, group, date, size) into the audit document — as a convenience, not as the
safety mechanism. **Git is the safety mechanism.**

### PR 2 — Delete tracked junk, and close the gap that let it in

- `e2e/undefined/` (2 tracked PNGs from an unset path variable)
- the 3 redundant `diagrams/excalidraw/` duplicates (keep one, verify by md5 which)
- any tracked `.coverage`, `.DS_Store` or copy-collision file
- **`.gitignore`: add `.hypothesis/`** and anything else the auditor found missing
- **A guard test** that fails when a generated-artifact pattern becomes tracked. This is the
  point of the PR — deleting `e2e/undefined/` without it just waits for the next one.

### PR 3 — Dedupe byte-identical trees

`design_handoff_quorum_ui/` vs `docs/design-handoff/`; the 6 identical `docs/factory/` copies.

**The 2 diverged pairs are a decision, not a dedupe.** Same number, different content, nothing
declares which is canonical. Pick with evidence, record the choice and the loser's unique content
in an **ADR**.

### PR 4 — Resolve the 14 duplicate `docs/` numbers

Start with the 70–73 double series. The ~60 validator literals and 149 config references move
**in the same commit** — a half-done rename is a red `make validate`.

**This is the widest-blast PR.** Consider splitting it further if the audit says so, and report
to the human before merging rather than self-merging if the diff exceeds what a reviewer can hold.

### PR 5 — `tests/` structure

Merge `tests/perf/` + `tests/performance/`; categorise the 28 loose files at `tests/` root.
`validate_tests.py`'s directory list, `Makefile` `PERF_TEST_PATHS`/`PERF_MIN_TESTS` and
`pyproject.toml` move in lockstep.

### PR 6 — Document the scheme, and gate it

- An **ADR defining the `docs/` numbering ranges** — currently written down nowhere, which is
  why 14 collisions accumulated unnoticed.
- **A test that fails on a new duplicate `docs/` number.**
- A convention note in `AGENTS.md` drawing **the distinction that matters**:

  | Kind | Example | Home |
  |---|---|---|
  | Session **output** — a record of what happened | `HANDOFF-*`, `*-RESULT.md`, dated triage docs | `docs/archive/` |
  | Executable **procedure** — text a future session runs | `*-ULTRACODE-PROMPT.md` | root, or `.agents/skills/` once generalised |

  **Write the rule as "session output never accumulates at root", not "session artifacts never
  at root".** The blunt version forbids this very file, and a convention that forbids the thing
  you are holding gets ignored rather than followed. The gate must enforce the first row without
  catching the second.

This PR is what stops the debt returning. Do not drop it if the earlier ones run long.

## Per-PR procedure

Dedicated `git worktree`, never the main checkout (it carries unrelated uncommitted work).
One line in the PR body saying why this item outranks the top of the backlog.

```bash
gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'
uv sync --all-extras
for t in quality validate openapi-check security-scan api-contract; do
  make $t >/dev/null 2>&1; echo "$t exit: $?"      # EXIT CODE, not grep
done
git commit                                          # BEFORE diff-cover
make diff-cover DIFF_BASE=origin/main
```

e2e only when specs, fixtures or UI move — and then:

```bash
rm -f .data/feedback_events.sqlite3
lsof -ti tcp:18085 | xargs -r kill -9
cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
  npx playwright test <specs> --project=chromium --workers=1 --retries=0
```

Then: two-lens adversarial review → verify findings → single fixer → merge with an explicit
`gh pr merge --squash --subject --body` → verify the deploy **job** (not the run's rollup) on the
**newest** of the **three** runs a merge fires (two are cancelled by concurrency) → confirm
`/status.build_sha` → `git branch -f main origin/main` → delete branch and worktree.

**Before every merge, run `gh pr view <N> --json closingIssuesReferences`.** `[]` means it closes
nothing. GitHub ignores negation, so "does not close #N" closes #N.

---

# 5. Phase D — the report

Post a final report covering: what merged with SHAs; what each PR changed and its measured
before/after; every claim from Phase A that did **not** survive verification; what was left open
and why; and the `src/` finding filed as an issue rather than actioned.

---

# 5a. Phase E — capture what generalises

**This prompt is deliberately NOT reusable.** It hardcodes this repository's measured findings —
the counts, `e2e/undefined/`, `.data/feedback_events.sqlite3`, named gate files, `AGENTS.md` rule
numbers. Point it at another repository and every number is wrong. Front-loading the measurement
is what makes the run safe *here*, and it is exactly what makes it non-portable.

A portable version is worth having, and it is written **after** this run, from what actually
happened — not from theory. Writing it beforehand would be generalising from a guess, which
section 0.3 exists to prevent.

**Before finishing, append `## What generalises` to the audit document, recording:**

1. **Which phases earned their cost.** Did three analysis lenses beat two? Did the synthesiser
   change any conclusion, or just concatenate? Name the phase you would cut.
2. **Which guardrails actually fired.** Every stop-condition in section 0.1 that triggered, and
   every one that never did. A guardrail that never fires in a run this messy is probably noise.
3. **Which Phase-A findings evaporated on verification.** *This is the most valuable output.*
   A generic procedure cannot be handed measurements, so it must be defensive about exactly the
   claim-shapes that turned out false here.
4. **Repo-specific versus universal.** For each step: would it hold in any repository, or does it
   depend on this one's gates? Mark each. The universal ones are the skill; the rest become
   "discover this yourself first" instructions.
5. **What the discovery phase must measure** that this prompt was simply told. Write it as
   commands, so the future skill measures rather than assumes.

**The skill contract, so the future author does not rediscover it.** A skill lives at
`.agents/skills/<name>/SKILL.md` and `scripts/validate_quality_contracts.py` requires:

- YAML frontmatter starting at byte 0, with `name:` and a `description:` of **at least 20 chars**;
- **13 `##` headings, at H2 exactly, anchored at line start** — a demoted `###` fails the check:

  `When to use`, `When not to use`, `Inputs`, `Owned outputs`, `Allowed tools`,
  `Forbidden actions`, `Procedure`, `Quality bar`, `Validation`, `Handoff contract`,
  `Stop conditions`, `Examples`, `Anti-examples`

**For portability, follow the vendored-skill pattern** — the only pattern in this repo that
actually travels. Write a generic body with **zero** references to `make validate`, `AGENTS.md`,
`docs/NN-*.md` or any quorum-ai path, then append a clearly fenced block:

```markdown
# Factory skill contract
> **Repo-added section.** Everything above is portable. This block is what
> `scripts/validate_quality_contracts.py` requires of every skill here.
```

Delete that block and the skill works in another repository. The 112 in-house skills do **not**
do this — they hardcode `docs/20-architecture.md` and `make validate`, which is why none of them
are portable. Do not copy their shape.

**Do not write the skill in this run.** Phase E produces its input, nothing more.

---

# 6. Explicitly out of scope

- **`src/product_app/` restructure** — record the measurement, file the issue, do not start.
- **Deleting `.venv` (326 MB) or `e2e/node_modules` (79 MB)** — correctly gitignored,
  regenerable, part of the working environment. If disk is the concern, the real target is
  Docker: **~14 GB reclaimable** against 405 MB here. Report it; do not act.
- **Any git-history rewrite.**
- **The open product backlog** — #290 (peer critique), #180 (false consensus), #105, #268, #203.
  `docs/analysis/2026-08-11-session-handoff.md` covers those and is a different session's work.

---

# 7. Mandatory stops

Stop and report rather than working around:

- A premise in section 1 turns out false. Say so; never repair it silently and carry on.
- Two fixes in a row add defects — change the approach.
- An item is bigger than it looked — say so and stop, do not file-and-continue.
- Any forbidden action in 0.1 looks necessary.
- A gate goes red for a reason you cannot explain. A red gate is not evidence it measured; open
  the log and find the number.

**Hermetic and $0 throughout.** No paid API calls. Production live execution is currently OFF by
design (`/ready` → `offline_by_config`); leave it that way. Never fabricate a number, a label or
a baseline — flag the gap instead.
