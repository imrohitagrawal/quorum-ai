# Day-One Prompt — install enforced quality machinery before any feature work

> **Canonical.** This supersedes the embedded prompt in
> `docs/day-one-quality-standard.md` (now a pointer here). Paste this at the
> kickoff of **any new project**. Its job is to **convert itself into permanent
> machinery** — once the CI gates and hooks exist, they enforce the standard no
> matter what any future prompt, memory, or attention forgets.
>
> It fuses two sources: (a) the original Day-One Quality Standard (the
> below-the-line enforcement discipline, hard-won from shipping UI/UX bugs that
> *knowledge alone* failed to prevent), and (b) the R2 methodology session
> (spec-first, layered testing, mutation, doubt-driven review to fixpoint,
> evidence-artifact gates, UI visual depth, the metric ledger, portfolio
> communication). Nothing from the original is dropped.

---

## 0. Why this exists (the hard lesson — do not delete)

On the source project we repeatedly shipped UI/UX bugs — **raw Markdown in
rendered output, a non-monotonic run timer, a cramped transcript layout, empty
citations, a silent simulation fallback** — even though the knowledge to prevent
them was available the whole time (in testing skills, in `AGENTS.md`, in chat).
The bugs recurred because that knowledge lived **above the enforcement line**: it
was influence, not a gate. Later, the same pattern repeated on a *plan document*
that named gates but couldn't bind the agent to follow the process. **A rulebook
is influence. Only mechanism binds.**

---

## 1. The durability hierarchy (the core principle — carry verbatim)

```
chat instruction            ← evaporates; no persistence, no trigger
skill I must remember        ← opt-in; nothing invokes it on a change
memory                       ← persistent hint, still only influence
AGENTS.md / CLAUDE.md        ← always loaded, strong influence — NOT a guarantee
───────────────────────────── the line between "influence" and "enforcement"
tracked hook  (local, fast)  ← runs on every change — ONLY IF its settings file is tracked
CI test       (shared gate)  ← runs for everyone regardless — the real enforcement
evidence-artifact CI gate    ← fails when a diff lacks the artifact its change required
```

Everything **above** the line depends on a human or agent *choosing* correctly in
the moment. Everything **below** the line runs regardless. A standard only holds
if it lives **below the line**. Prose (chat, skill, memory, even AGENTS.md) is
necessary context but **never** sufficient enforcement.

**Critical hook caveat:** a hook is below-the-line only if the settings file that
defines it is **tracked in git**. If `.claude/` is gitignored (common), a
`.claude/settings.json` hook is **LOCAL-ONLY** — not shared, not in CI, not on a
teammate's clone. Treat the hook as a local fast-feedback convenience; the
**shared authoritative gate is CI**. To make a hook shared, deliberately un-ignore
its settings file.

**Corollary:** to make a practice automatic on every change *for everyone*, it
must be a **CI test** (a local hook automates it only on the machine whose tracked
settings define it).

**The evidence-artifact gate (the layer that binds *process*, not just code):** a
CI job that **fails when the diff lacks the artifact its change required** —
changed `src/` module with no mutation report → fail; UI diff with no new/changed
invariant/visual spec → fail; new `FR-` with no requirement-registry + traceability
row → fail. This is the only durable way to enforce the *workflow* (below), because
it gates on the *artifacts the workflow must produce*.

> **The ranking is stated here and only here (EN-4).** An evidence-artifact gate
> **is a CI gate** — a *specialization* of one, not a rival layer. It sits at the
> bottom of the ladder (most durable) because a plain CI gate binds only the code
> artifact, while an evidence-artifact gate additionally binds the *process* that
> produced it. Every other section of this document — and any project doc derived
> from it — must defer to this ladder rather than restate a ranking of its own.
> Anti-gaming caveat (finding EN-2): "artifact present" ≠ "artifact valid". Only
> claim enforcement strength for a rule whose *structure* is checkable (e.g. a new
> `FR-` must have a registry **and** matrix row that resolve); for artifacts whose
> quality cannot be structurally checked (a mutation report, an invariant spec),
> require the artifact to be **RED-proven** or drop the claim.

---

## 2. THE DAY-ONE PROMPT (paste this)

> **"Before any feature work, install quality-enforcement machinery as the first
> deliverable and treat it as a blocking gate for everything after.**
>
> **1. Working order is verify → implement → document, always.** Confirm ground
> truth (read the code, run the cheap check, look at the real output) BEFORE
> implementing. Never assume → implement → verify. **Document decisions in the
> repo, not chat.**
>
> **1a. Plan and slice before coding (spec-first).** Write the spec/requirements
> (EARS-style "the system shall…", or GitHub Spec Kit / Kiro `requirements →
> design → tasks`) and agree it with the human first. Decompose **vertical → then
> horizontal** to the **smallest independently shippable + reviewable increment**
> (objective test: one reviewer reviews it in one pass AND it touches one primary
> review surface; else split). Timebox understand→plan to **≤2 iterations or until
> a fresh review adds no load-bearing item**, then plan.
>
> **1b. Make the subjective size/stop rules mechanical (they are otherwise
> unenforceable).** "One reviewer, one pass" and "load-bearing item" are
> judgement calls, so pair each with a checkable proxy and split/stop when the
> proxy trips — the proxy is the gate, the judgement is the tie-break:
>
> | Subjective rule | Mechanical proxy (set per project from a MEASURED baseline of your own merged PRs) |
> |---|---|
> | "one reviewer reviews it in one pass" | changed-line ceiling **and** changed-file ceiling on the slice diff (e.g. ≤400 changed lines / ≤10 non-generated files — measure your repo's merged-PR median first, then set) |
> | "touches one primary review surface" | the diff's files map to **one** top-level surface directory (`src/`, UI assets, `docs/`, CI config); a diff spanning two surfaces splits |
> | "a fresh review adds no load-bearing item" | a round adds no finding rated ≥MED **and** no finding that changes an interface, a gate, or a stored/persisted shape |
> | "review to fixpoint" | **max 3 review rounds.** If round 3 still yields a ≥MED finding, STOP and escalate to the human with the residual list — the human may override to merge, defer, or authorise more rounds. The loop is bounded so it always terminates; the override is recorded in the review record. |
>
> **1c. Parallel development, then sync.** When a phase's slices are genuinely
> **independent**, dispatch parallel implementer agents, each in an **isolated git
> worktree** so no two writers share a file; each runs the full per-slice loop.
> Then **sync** = an explicit integration step plus a **whole-branch adversarial
> review over the combined diff** before any merge — parallel work hides
> cross-slice defects that per-slice reviews cannot see. Use **sequential** slices
> whenever they share a seam or one depends on another. Fan-out review is
> orthogonal: it runs either way. Give each parallel agent an explicit **file
> ownership list**; a write outside it is a coordination bug, not a merge conflict.
>
> **1d. Choose the agent/model per task class** — cost and rigour are both real:
> cheap/mechanical work (search, enumeration, single-file lookup) → smallest model
> / low effort; an implementation slice → the session model in its own worktree;
> **adversarial verification, judging, and the hardest correctness work → the
> highest tier at high effort, in an independent context that never inherits the
> implementer's session** (a reviewer that shares the implementer's context shares
> its blind spots); research fan-out → the research harness.
>
> **2. Enumerate this project's quality dimensions** — at minimum: correctness,
> UI/UX rendering, security (secrets / authz / injection), cost & resource
> guardrails, API / schema contracts, accessibility, data privacy, observability
> & health, and deploy / release safety. State which apply.
>
> **3. For EACH applicable dimension, install a mechanical gate below the
> influence line:** a **real test** exercising real behavior / real providers
> (not mocks or clean fixtures), wired into **CI to run on every PR**, plus — where
> the practice must be automatic on every relevant change — a **`settings.json`
> hook**. For UI/UX specifically: a realistic golden fixture, visual snapshot
> tests (`toHaveScreenshot`) per view, and global rendering invariants (no raw
> markdown, no overflow, monotonic timers / counters); rendered pixels + real
> behavior are the source of truth.
>
> **3a. Match the test technique to the surface, and make tests *bite*.**
> logic → unit + **property-based (Hypothesis)**; persistence → round-trip +
> concurrency + idempotency; API → **contract fuzz (Schemathesis)** + schema-drift;
> UI → golden-fixture + rendering-invariants + **computed-style / element-overlap
> (`boundingBox` non-intersection) / multi-viewport** + snapshot + axe + drive-and-
> look; security → adversarial fuzz + real-data-leak probe. Then run **mutation
> testing (mutmut)** on the changed module — a test that passes but doesn't *catch
> a mutation* is not coverage. Enforce a **coverage floor** (`--cov-fail-under`)
> **set from a measured baseline, never below it** (a floor under today's number
> ratchets quality DOWN), plus **changed-lines coverage** (`diff-cover`) so the
> global floor cannot hide an untested new file.
>
> **3b. Every tool named above ships with a written config and a NUMBER.** "We use
> Schemathesis / snapshots / an eval gate" is not a gate until the checks, limits
> and thresholds are pinned in the repo — see §4a for the concrete parameter list
> and, for anything that must be measured, the **baseline-then-set** procedure.
>
> **4. Prove every gate:** it must go **RED** on a deliberately-introduced defect
> in that dimension and **GREEN** when fixed, before setup is 'done'. A gate not
> proven red is assumed broken.
>
> **5. Define 'done' by the gates and by evidence.** No change is complete until
> its dimension's gate exists, covers the change, and passes — and for anything
> user-facing, until you have captured and **visually reviewed** real-shaped
> output. **'Done' = the artifact exists AND is proven — never "doc written" or "I
> claim so."**
>
> **5a. Review is a loop to a fixpoint, not a step.** After implementing (and after
> every fix), run an **adversarial, executing** review — independent fresh-context
> reviewers, biased to *disprove*, each running tests/tools, one per angle
> (correctness, security/PII, API/contract, UI-visual, architecture/concurrency,
> docs/traceability). Fix findings **test-first**, then **re-review the fix diff**,
> and repeat **until a fresh pass finds nothing new** — bounded at **3 rounds**,
> after which unresolved ≥MED findings go to the human with an explicit override
> decision (§1b). Do not call it clean after one pass.
>
> **5b. Commit hygiene: branch first, always.** Never commit to the default
> branch. Open the slice's branch before the first edit, keep one branch per
> slice, and commit per slice with the evidence (RED output, gate run) referenced
> in the message. A branch created *after* the work has already been done on
> `main` loses the review surface the whole loop depends on.
>
> **5c. Persist the durable learnings to memory — as a HINT, not a gate.** At the
> end of a phase, write what generalises (the failure mode, not the incident) to
> agent memory. **Be honest about what this buys you:** memory is *above* the
> enforcement line (§1) — a persistent hint that still only influences. It is
> never a substitute for the CI gate, and no item may be marked done because "it
> is in memory." If a learning matters, the same pass must also land it as a
> mechanism below the line; the memory entry is the pointer, not the enforcement.
>
> **6. Write the standard and the dimension→gate map into AGENTS.md**, pointing at
> the relevant skills — as context, not as the enforcement. **Inventory the skills
> you already have BEFORE researching external ones** (nearest-population-first);
> audit any external skill (provenance/license/fit) and adopt reviewer-only first.
>
> **7. Never assume a capability works until a test exercises it against reality;
> flag anything unverified explicitly.** Surface honest gaps ("—"), never fabricate
> a value."**

---

## 3. Practice / dimension → skill → gate → artifact map (fill in per project)

**Read the checkmarks correctly — this table is a TARGET map, not a status
report (EN-1).** A ✅ in **Belongs in CI?** means *"this dimension's gate must be
a CI gate"* — it asserts **nothing** about whether that gate exists in your repo
today. Marking a target as though it were a delivery is exactly the
aspiration-marked-done failure this whole document exists to prevent.

**Existence is tracked separately, and only there.** Keep a per-project status
table (in this repo: `docs/R2-comprehensive-plan.md` Part B) where every row is
either **✅ = the artifact exists AND has been proven RED-then-GREEN**, or
**TODO = it does not exist yet**. Nothing else. The two tables answer two
different questions and must never be merged: *"should this be a gate?"* (here)
vs *"is it built and proven?"* (there). **Proven red?** below is a per-project
column: fill it from the status table, leave it blank while the gate is a target.

**Hook?** is an *optional local* speed-up that only helps on a machine whose
settings file is tracked (see §1) — never a substitute for CI.

| Dimension / Practice | Real test (not mocked) | Skill | Belongs in CI? (target) | Hook? (local) | Proven red? (per project) |
|---|---|---|---|---|---|
| Correctness | unit + integration on real logic | `test-driven-development` | ✅ | — | |
| Tests actually bite | **mutmut** score ≥ threshold on changed module | — | ✅ | — | |
| Coverage floor | `--cov-fail-under=N` | — | ✅ | — | |
| **UI/UX rendering** | visual snapshots + global invariants + computed-style + overlap + multi-viewport vs golden fixture | `e2e-testing-patterns` | ✅ | optional, on UI-file change | |
| Real integration | one smoke against the actual backend (free/deterministic mode), not `page.route` mocks | `webapp-testing` | ✅ | — | |
| Security | secret scan, authz tests, injection/XSS/CSP tests, PII-leak probe | `security-and-hardening` | ✅ | optional, on secret/auth files | |
| Cost / guardrails | estimate vs measured reconciliation; hard-cap cannot be breached | — | ✅ | — | |
| API / schema contract | generated-schema-in-sync check + **Schemathesis** fuzz | — | ✅ | — | |
| Property-based | **Hypothesis** on serializers / parsers / round-trips | — | ✅ | — | |
| Accessibility | axe (or equivalent) on every view | — | ✅ | — | |
| Data privacy | no PII in logs/URLs; redaction tests | — | ✅ | — | |
| Observability / health | `/health`, `/ready`, structured logs, error reporting wired | — | ✅ | — | |
| Deploy / release | deploy gated on green CI for the tested SHA; post-deploy smoke | `deploy-checklist` (re-fit to stack) | ✅ | — | |
| Spec-conformance | source diff ⇒ requirement/AC row required | `spec-driven-development` | ✅ (evidence-artifact) | — | |
| Verify-by-performing | drive the real flow; no claim without fresh evidence | `verify` + `verification-before-completion` | Stop/pre-commit hook | ✅ | |

**The two verification skills are not duplicates (CF-3):** `verify` is the
**mechanism** — go run the thing and capture the output; `verification-before-completion`
is the **Iron-Law doctrine** — no completion claim may be made *at all* until that
fresh output exists. Mechanism answers *how you check*; doctrine answers *when you
are allowed to say "done"*. You need both: the mechanism without the doctrine gets
skipped under time pressure, the doctrine without the mechanism is just a slogan.

| Review-to-fixpoint | fan-out adversarial review; merge blocked until clean | `doubt-driven-development`, `subagent-driven-development`, `code-review`, `taste-check` (code-quality; may be non-English) | ✅ (evidence-artifact: review record) | — | |

---

## 4. UI/UX specifics (the slice most often skipped — carry in full)

A driver like Playwright is **not a judge** — it only checks what you assert, and
asserting DOM structure on clean mocked data is blind to how real output renders.
So the UI gate needs things a normal functional test lacks:

1. **A golden realistic fixture** — real, messy, production-shaped output (Markdown
   headings, `**bold**`, `1./2.` lists, bare URLs, long paragraphs, empty-state
   cases), captured once from a real run and committed. Every view renders against
   it.
2. **Global rendering invariants** — one test that walks the *entire* rendered DOM
   of each view and asserts class-wide truths, **so you can't "forget a surface"**:
   no text node contains literal `##`/`**`/leading `1.`; no element overflows its
   container; any elapsed/counter readout is monotonic across a scripted poll
   sequence.
3. **Visual snapshot tests** (`toHaveScreenshot`) per view against the fixture — a
   human reviews the baseline; regressions surface as a pixel diff. **Generate
   baselines in CI's own container, set `maxDiffPixels` from a measured baseline
   (§4a), and mask dynamic regions** (timers, run IDs) to avoid flakiness.
4. **Computed-style / design-token assertions** — pin load-bearing tokens (e.g. a
   "consensus-only" color that must never appear on a status/quality surface);
   assert the element's computed `color`/font, not a class name. The expected
   values come from **one machine-readable token source** (§4a), never from a
   number retyped into the spec.
5. **Element-overlap / collision** — `boundingBox()` non-intersection for text +
   interactive elements (catches overlap even on a dirty baseline).
6. **Multi-viewport** — run invariants + snapshots at mobile / tablet / desktop
   (e.g. 375 / 768 / 1440px) in the pinned CI environment (baselines are
   platform/browser-specific — a macOS baseline never matches on Linux).

**Definition of done for any UI change:** its affected views have visual snapshot
tests against the fixture; you have captured and **visually reviewed** a screenshot
of each with real-shaped data; the invariants (incl. computed-style, overlap,
multi-viewport) pass. Rendered pixels + real behavior are the source of truth —
never DOM assertions or mocked JSON alone. **Hosted AI-visual tools (Percy,
Applitools, Argos) are an approval-gated add-on** — default to self-hosted
pixelmatch; before adopting, bring the human the use-case, expected screenshot
volume, and a free-tier check (e.g. Percy free = 5,000 shots/mo; verify current
limits, CI-parallelism, and data-privacy terms).

---

## 4a. Named tool ⇒ named number (no gate without a config) — RB-8

A tool name is a *plan*; a gate needs pinned parameters. For each, either the
value is a **policy choice** (write it down now) or it is a **property of your
system** — in which case do **NOT invent it**: run the *baseline-then-set*
procedure, record the raw measured numbers next to the threshold, and set the
threshold from that data. An unmeasured guardrail number is a fabricated one.

| Tool / gate | Must be pinned | How to arrive at the value |
|---|---|---|
| **Schemathesis** (API contract fuzz) | which checks run; example budget; stateful on/off; auth + base URL; what a failure means | **Policy, then measure runtime.** Start from all built-in response/schema-conformance checks against the app's own generated `openapi.json`; keep it **hermetic** (app self-started in deterministic/sim mode, no live provider calls, no secrets). Choose the example budget by **measuring wall-clock at 2–3 candidate budgets** and picking the largest that keeps the PR job inside your CI time budget; record both numbers. Enable **stateful** sequences only once the single-operation lane is green and its runtime is known. Pin the **major version** in the dependency extra — the CLI/pytest API is not stable across majors. |
| **Visual snapshots** `maxDiffPixels` | a per-spec integer (plus `maxDiffPixelRatio` if used) | **Measure.** Seed the baselines in the CI container, then re-run the *unchanged* spec **N≥10×** in that same container and record the max observed diff for each view. Set the threshold just above that observed noise floor — never a round number chosen by feel. If observed noise is 0, set it to 0 and let masking (timers, run IDs, cost) absorb the dynamic regions. |
| **Computed-style baseline source** | the single source the expected values are read from | **Policy.** One machine-readable token source (the CSS custom-property block / design-token file) is authoritative; the spec reads the token and asserts the element's computed value equals it. A literal hex/px retyped into a spec is a second source of truth and will drift — the only literals allowed are **negative** constraints (a token that must NOT appear on a surface). |
| **Eval-regression delta** | the per-metric drop that fails a PR | **Baseline-then-set, and ship ADVISORY first.** You cannot know the tolerable delta before you know the metric's run-to-run variance. Run the frozen golden set **N times unchanged**, record each metric's mean and spread, and set the failing delta above that noise band. Until that measurement exists the gate reports but does not block. |
| **Coverage floor / changed-lines coverage** | `--cov-fail-under=N`; `diff-cover --fail-under=M` | **Measure `N` from today's actual total** and never set it below (a lower floor ratchets quality down); `M` is a policy choice for *new* lines and can be strict from day one. |
| **Mutation score** | threshold + scope + window | **Baseline-then-set.** Measure a real score per core module first; set the threshold from that data, scope it to changed code, and run **advisory (non-blocking)** until the baseline exists and the CI runtime is known. |

**Rule:** any threshold in this table that has not yet been measured is written in
the repo as `baseline-then-set` with its measurement step spelled out — never as a
placeholder number. A number in a config is read as evidence by everyone after you.

---

## 5. Enforcement & accountability

- **Three enforcement layers + a human backstop.** The layers, weakest to
  strongest, are exactly the below-the-line rungs of §1's ladder — **§1 is the
  single statement of the ranking; this list does not restate it (EN-3, EN-4):**
  (1) **tracked hooks** — bind the agent's live behavior on the machine whose
  settings file is tracked (pre-commit runs the gates; a Stop hook blocks a
  "done/passing" claim without fresh test output; `block-no-verify-hook` prevents
  bypass); (2) **CI gates** — run for everyone regardless of any claim, binding
  the code artifact; (3) **evidence-artifact CI gates** — a specialization of (2)
  that additionally binds the *process*, by failing when the diff lacks the
  artifact its change required. **Plus a human review backstop** for the
  unmechanizable — a backstop, not a fourth mechanism: it depends on a person
  choosing correctly, so it sits above the line.
- **"Done" = artifact exists AND proven.** Every gate row in the *status* table is
  ✅ (exists + verified) or TODO (does not) — no aspiration is marked done. The
  §3 dimension map is a target map and does not carry status (EN-1).
- **Honest limit:** hooks have gaps and drift is possible within what isn't
  mechanized; that is why the evidence-artifact gate + human review exist. No
  system is fully self-enforcing — the goal is that drift is caught fast and cheap.

---

## 6. The metric ledger (make the methodology falsifiable)

Commit `docs/metrics/quality-ledger.md`, updated each slice:
**review-findings-per-slice** (should trend down), **mutation score** per changed
module (should trend up), **escaped-defects** = findings a later phase raises about
an earlier merged slice (target → 0), **rework commits** per slice. A downward
escaped-defect + rework trend is the *evidence* the methodology works; flat/rising
refutes it. **No metric ⇒ no claim** (evidence-first applies to our own process).

---

## 7. Communicate the rigor (for portfolio / enterprise projects)

Rigor is invisible to a reviewer/hiring-manager unless it's communicated. Feed each
completed phase into the study/publishing backbone (draft-first, human-approved,
never auto-published): a **study module** (problem → AI solution → enterprise
readiness), a **technical article** ("enforcing evidence-first quality on an
AI-built product"), and a **short post**. Make a study/publish deliverable part of
each release-phase's Definition of Done.

---

## 8. Why this breaks the cycle (and a chat prompt alone does not)

A chat prompt is above the line and evaporates — but *this* prompt's entire job is
to build the below-the-line gates as the first deliverable. Once they exist, they
run on every PR and every relevant change **regardless of any future prompt,
memory, or attention.** The prompt is a one-time bootstrap that installs durable
enforcement, then its own persistence stops mattering. Three properties make it
airtight:

- **Front-loaded** ("before any feature work") — the gate exists before there is
  anything to slip past it.
- **Proof-of-gate** (red-on-defect) — a hollow/no-op suite can't masquerade as
  coverage.
- **Done defined by the gate** — completion is contingent on the machinery, not on
  discretion.

_Fourth property, added from the R2 session:_ **Review-to-fixpoint** — one review
pass proves nothing; "clean" means a fresh adversarial pass finds nothing new.
