# Category 3 — Enforcement machinery (built + proven red this session)

The below-the-line gates that make the principles automatic. Unlike the rest of
this analysis, **this category is already implemented** — the files below exist,
run, and were proven RED against current code.

## What was built

| Sub-module | File | Purpose | Mechanism | Enforcement gate | Status |
|-----------|------|---------|-----------|------------------|--------|
| Golden realistic fixture | `e2e/fixtures/golden-run.ts` | One canonical blob of messy real-shaped output (line-start `##` headings, `**bold**`, ordered lists, bare URLs, a ~450-word answer, an empty-citation slot) mirroring the OpenAPI QueryRun* schema | Test data | Feeds every invariant + snapshot | **DONE** |
| Rendering invariants | `e2e/tests/invariants/rendering-invariants.spec.ts` | Walks the whole rendered DOM: (a) no raw Markdown, (b) no horizontal overflow, (c) monotonic elapsed across a decreasing poll sequence | Playwright test | CI — **BLOCKING** | **DONE — RED-PROVEN, now GREEN + hard** |
| Visual snapshots | `e2e/tests/invariants/visual-snapshots.spec.ts` | `toHaveScreenshot` baselines for result + transcript (masked dynamic regions) — the human-reviewed guard, primary catch for #33 | Playwright visual regression | CI — **BLOCKING** (Linux baselines seeded by `seed-visual-baselines.yml` and committed) | **DONE** |
| Real-integration smoke | `e2e/tests/invariants/real-integration-smoke.spec.ts` | Drives the REAL sim backend end-to-end with NO `page.route` mock; asserts a run reaches a populated verdict | Playwright test | CI — **BLOCKING** | **DONE — PASSING** |
| CI wiring | `.github/workflows/e2e.yml` | Smoke, rendering invariants and visual snapshots all run as **blocking** steps — `continue-on-error` appears nowhere in the file | GitHub Actions (tracked = shared) | The shared gate | **DONE** |

## CI gate enforcement status (the qualified truth, mechanised)

`continue-on-error` is **not** the only way a job fails to block, so this table
records the *effective* status of every registered gate. It is kept honest by
`tests/test_doc_gate_consistency.py`, which parses `.github/workflows/*.yml` and
fails the build if any doc's blocking/advisory wording contradicts reality
(ledger EN-7).

| Job (`ci.yml` unless noted) | Effective status | Why it is qualified |
|---|---|---|
| `fr-completeness` — *FR traceability completeness (blocking)* | blocking | — |
| `api-contract` — *Schemathesis API contract (blocking)* | blocking | — |
| `diff-cover` — *Changed-lines coverage >= 95% (blocking)* | blocking-on-pull-requests-only | `if: github.event_name == 'pull_request'`, so a direct push to `main` has no changed-lines gate (`docs/analysis/09-enforcement-hooks.md` records the same PARTIAL) |
| `perf-gate` | advisory | `continue-on-error: true` — macOS-derived budgets would false-fail a slower runner; DEBT-009 |
| `mutation-baseline` | advisory | `continue-on-error: true` — a MEASURED decision, not a default: yield 6/158 escaped defects, 7% false-abort, 8% silent pass (docs/metrics/mutation-gate-study.md). Also pull-request-only |
| `e2e` (`e2e.yml`) | blocking | — |

Update, 2026-08-03 (#166): `codex-review` — previously vacuous (no executable
step: the `openai/codex-action` step was commented out pending an
`OPENAI_API_KEY` secret, so the job only checked out and always passed) — was
**removed**, not repaired. Wiring the paid secret was out of scope for the
batch that closed it; a permanently-green job that checks nothing is worse
than no job. If it is ever reintroduced, add its row back here with a real
mechanism, not a restored placeholder.

## Can a gate here finish having measured nothing? (2026-07-29)

The table above records whether a gate *blocks*. It never recorded whether a
gate **measured**, and those are different questions — which is the whole content
of #130 and #158. Audited by execution and by reading real CI job logs:

- **`mutation-baseline`: 11 of the last 11 pull-request runs scored zero mutants.**
  Ten reported `success` (`no MUTATABLE changed functions ... nothing to mutate`),
  one reported `failure` (`failed to collect stats`, run `30436468037`). Green and
  red were equally uninformative.
- **`diff-cover` — a BLOCKING gate — exits 0 on an empty denominator.** Reproduced
  locally: two genuinely uncovered new lines in `fence()` plus a coverage report
  containing no packages gave `No lines with coverage information in this diff.`
  and `rc=0`. `--fail-under=95` does not fire when it maps nothing.
- **13 of 21 jobs could reach a terminal status having measured nothing**, four of
  them blocking (`diff-cover`, `fr-completeness`, the security scan inside
  `validate-and-test`, `e2e`).
- The repair pattern already existed — `gate-min-collected` and `gate-min-executed` in the `Makefile` — and was wired to exactly two gates
  (`perf-gate`, `api-contract`), whose logs do show their numbers.

### Floors added, and what each is proven to catch

| Gate | Floor | Proven RED by |
|---|---|---|
| `diff-cover` (blocking) | every changed `src/**.py` file must be present in the coverage report (`scripts/check_diff_cover_measured.py`) | a real `src/` edit plus a report with no packages → rc=1; the same edit with the real report → rc=0; a comment-only edit → rc=0 (no false fire) |
| `validate-and-test` security scan (blocking) | ≥50 files actually read | a 1-file tree → `FAILED TO MEASURE`, rc=1; the real tree → ~1369 files, rc=0 (the exact count moves with untracked files, so only the order of magnitude is meaningful against a floor of 50) |
| `fr-completeness` (blocking) | ≥25 requirements actually parsed | doc 10 truncated to 2 sections → 14 parsed → rc=1; **without** the floor the same truncation printed `OK` and rc=0 |
| `e2e` FOUR lanes (blocking) | executed-count floors 167 / 96 / 51 / 8 — the EXACT measured counts, zero skips (`scripts/check_e2e_executed.py`) | missing report, all-skipped, and zero-matched all → rc=1; a real lane at its floor → rc=0 |
| `mutation-baseline` (advisory) | a non-empty scope must leave a score or an explicit `UNMEASURED` in `score.txt`; the empty-scope branch now says in words that no score was produced | the recipe's own failure branch |

**Update, 2026-08-03 (issue #162, worked as the follow-up work package #166):
all six of the above, closed.**

| Gate | What changed | Proven RED by |
|---|---|---|
| `visual-snapshots` step (`e2e.yml`, blocking) | executed-count floor added, `--min 8` (6 `trust-score-visual.spec.ts` + 2 `visual-snapshots.spec.ts`) — measured via `--update-snapshots`, which executes every test regardless of platform-specific baseline availability without touching the committed `*-chromium-linux.png` files the real gate compares against | floor step removed → the guard test reds |
| `csp-smoke` (advisory, `csp-smoke.yml`) | executed-count floor added per matrix engine, `--min 2` (both tests in `csp-smoke.spec.ts`, run once per browser) | floor step removed → the guard test reds |
| `flake-scan` (advisory) | both the "no junit report" branch and the "every repetition skipped" (`executed <= 0`) branch now `sys.exit(1)` instead of falling through / exiting 0 | either `sys.exit(1)` reverted → the guard test reds |
| `perf-sample` (advisory, nightly) | the missing-JSON `else` branch now `exit 1`s | `exit 1` removed → the guard test reds |
| `perf-gate` missing-JSON branch (`ci.yml`, advisory) | same fix, same shape, in the CI (not nightly) copy of the perf gate | `exit 1` removed → the guard test reds |
| `check-error-rate` / `skip_low_traffic` | `exit_code_for()`'s contract is UNCHANGED (alert is still the only exit-1 path — an abstention must never fire the alert email, and an alert must never go silent); instead the workflow step now writes an explicit, visually separate `$GITHUB_STEP_SUMMARY` section labelled `ABSTAINED` whenever the probe prints `SKIP_LOW_TRAFFIC:`/`SKIP_COUNTER_RESET:`, so an abstention is no longer indistinguishable from a verified-healthy run at a glance | the `ABSTAINED` marker / grep pattern / `exit $code` propagation removed → the guard test reds |

Every row proven RED-then-GREEN in `tests/unit/test_gate_liveness_wp166.py`
(codex-review's removal is guarded there too): each fix reverted on a copy of
the real workflow file, the corresponding test confirmed red, the file
restored from the copy (never `git checkout`), the test confirmed green again.

**What none of these floors can see:** whether the tests that ran assert anything
worth asserting. A lane of 138 vacuous specs satisfies its floor completely. These
close "the gate stopped running", not "the gate never bit".

## An evidence-artifact gate was built, measured, and NOT shipped

`docs/DAY-ONE-PROMPT.md` §1 specifies one ("changed `src/` module with no
mutation report → fail"). The structurally checkable version — a `src/` change
with no added-or-modified test file — was built and replayed before shipping, as
§4a-bis requires.

Replay over the last 200 first-parent commits: 67 changed `src/` Python, **5 (7%)**
touched no test file, and four of those five look like genuine gaps. But over the
last **60** commits — current practice rather than June's — 17 changed `src/`
Python and exactly **one** would have fired: `c88715ae`, which changed a single
attribution header string and needed no test. **A false block.**

A gate whose only firing in current practice would have been wrong is not worth
its noise, so it was **deleted rather than shipped advisory-and-ignored**. Recorded
here because "measured and declined" is a result, and the next person should not
have to re-derive it. Re-measure with a fresh window before proposing it again.

## Prove-red evidence (recorded this session, against current `app.js`/`app.css`)

Running `rendering-invariants.spec.ts` on chromium: **3 failed, 1 passed.**

- **#30 (no raw Markdown) — RED.** `**`/`## ` leaked into rendered text on
  every genuine provider-**prose** surface: `.result-verdict-text`
  ("## Recommendation / **Proceed**"), `.result-verdict-caveat`
  ("**High-stakes:**"), `.result-trust-caption`, `.result-positions-cell`
  ("**Position:**"), `.result-synth-body`, `.callout-high-stakes .callout-body`,
  and the transcript `.transcript-opening-body` / `.transcript-round-body`.
  The `.live-round-body` (app.js:1579) content is ALSO flagged because the
  populated live-debate DOM persists in `#main-content` after the run — so the
  walk catches it incidentally. It is NOT RED-proven via a dedicated live-run
  driver (there is none); treat 1579's coverage as opportunistic, not asserted.
- **Greenability was hardened after adversarial review.** Source-citation
  titles/labels are provider *metadata*, not prose — a prose formatter must not
  (and structurally cannot) render bold inside a link label. Seeding `**` there
  would make the gate **non-greenable**, so the fixture now keeps source titles
  plain text; the gate flags only prose surfaces. Verified: **zero**
  `result-source-label` / `source-list` offenders remain after the fix.
- **#29 (monotonic timer) — RED.** Sampled `#live-elapsed` across a scripted
  poll sequence `12s → 3s → 4s → 5s → 6s`: samples `[12000,…,3300,…]`, a **8700ms
  backward jump** (> the 150ms parse tolerance).
- **no-horizontal-overflow — PASSED** (correct: today's layout does not overflow;
  #33 is *under-use* of width, caught by the visual snapshot, not this invariant).

**Measured determinism (adversarial reviewer ran the specs 3×, not predicted):**
the three runs were bit-identical — `worstDrop = 8700ms` (12000→3300) on runs
1/2/3, backward jump detected 3/3, `#30` failing 3/3, overflow passing 3/3. The
real-integration smoke ran in **1.2–2.4s** vs its 90s verdict budget (~36×
headroom; sim `stage_delay_ms`=5ms). Two false-green holes the reviewer found
were then fixed: the timer test now asserts it witnessed the ~12s pre-drop value,
and `driveToResult` waits on a late-rendered surface before the markdown walk.

Crucially, the gate is **greenable**: the already-formatted answer surface
(`.answer-section-body.q-prose`) produced **zero** false positives, and the
fixture uses only valid Markdown (line-start headings + inline bold) on genuine
prose surfaces — which a correct #30 fix provably converts. The fix is not "route
everything through the block formatter" but **route each surface through the
appropriate renderer**: the block formatter (`formatAnswerText`) for prose blocks
(verdict/synthesis/critiques/transcript answers/caveat), and an *inline* renderer
(`mdInline`) for inline/cell surfaces (the positions cell). Source titles stay
plain. With that fix every flagged surface loses its raw markers and the test
turns GREEN.

**Greenability — empirically proven (not just argued).** A throwaway fix that
routes the flagged prose surfaces through `formatAnswerText` was applied to
`app.js`, the gate re-run, then reverted (app.js left pristine). Result: **#30
RESULT and #30 TRANSCRIPT flipped RED → GREEN**, while **#29 (timer) stayed RED**
— proving the gate both *can* go green on a correct fix AND *discriminates*
(it is not a blanket always-fail). This is the "perform, don't preach" evidence
that the gate is honest.

**EXACT coverage (do NOT read the gate as "no raw Markdown, full stop").** A
performing adversarial hunt (probes injected one marker at a time, driven through
the real UI) proved the gate's true reach. It now asserts **six** constructs, all
greenable via the real renderer (`mdInline`/`formatAnswerText` convert each) —
verified against `RAW_MARKDOWN_PATTERNS` in `e2e/fixtures/golden-run.ts`:
`**bold**`, line-start `#{1,6}` heading, `` `inline code` ``, `[link](url)`
(`](`), `_underscore_` / `__underscore__` emphasis, and line-start `>` blockquote.
It is a snapshot of `#main-content` text nodes, and it skips any node inside
`<code>`/`<pre>` — literal markers in inline code (`__init__`) are *correct*, not
a bypassed formatter.

**Widened after the formatter extension (was a documented gap).** Underscore
emphasis and blockquotes originally rendered raw even in the *formatted* answer
surfaces, because `mdInline` handled only asterisk emphasis and `formatAnswerText`
had no blockquote block — asserting them then would have been **non-greenable**.
The #30 fix extended the formatter, so the gate was widened to cover both; the
inline-code exemption keeps it honest.

**Not asserted — real gaps, documented not hidden:**
- **Ordered/bulleted list markers** (`1.`, `- `, `* `) are not asserted (a correct
  `<ol>`/`<ul>` exposes markers as `::marker` pseudo-elements, not text; a partial
  fix that skips lists would pass). Lists are covered by the visual snapshot.
- **Scope:** the walk covers `#main-content` (where provider prose renders). App
  chrome (toasts, header, `aria-live`, error banners) is app-authored text, not
  provider markdown — intentionally out of scope.
- **Timing:** single post-hydration snapshot; streamed/late renders after the walk
  are not covered (the anchored waits cover result/transcript hydration only).
- `renderStubSource` titles (`app.js:3369`, `local_simulation`/`fallback_search`
  providers) are not exercised — golden sources use `openrouter_search`.

## The invariants are BLOCKING (the enforcement handoff is DONE)

> **Corrected 2026-07-19 (finding EN-6).** This section previously said the
> invariants were wired NON-BLOCKING. That is **stale and was false** — a stale
> "non-blocking" note undercuts a gate that is in fact hard, and teaches readers
> to discount it. Verified against the actual workflow: **`continue-on-error`
> appears nowhere in `.github/workflows/e2e.yml`** (only inside two header/step
> comments describing its removal), and the two steps are literally named
> `Run UI rendering invariants (BLOCKING)` and `Run visual snapshots (BLOCKING)`.

The original reasoning, kept for the record: the invariants started RED on
purpose (#29/#30/#33 were unfixed) and making them blocking then would have
frozen `main`, so they ran under `continue-on-error: true` — red surfaced in logs
without blocking merges. **That handoff has since happened.** The #29 (monotonic
timer) and #30 (route every provider-prose surface through the markdown renderer,
plus the underscore/blockquote formatter extension) fixes landed, the specs went
green, and `continue-on-error` was deleted. The visual-snapshot baselines were
seeded as `*-linux.png` in the CI container by `seed-visual-baselines.yml`,
committed, and are now compared like-for-like — so that step is blocking too.
Every invariant step, plus the real-integration smoke, now fails the build.

**Consequence for anyone editing the UI:** a red rendering invariant or a pixel
diff is a real regression and blocks the merge. It cannot be waved through; fix
the defect, or change the baseline deliberately with a human review of the new
screenshot.

## Follow-ups to fully close the machinery

1. ~~**Seed visual-snapshot baselines in CI.**~~ **DONE** — `seed-visual-baselines.yml`
   generated the Linux baselines in the CI container (mac baselines are
   platform-suffixed and unused on ubuntu, per memory
   `manual-live-check-is-browser-dependent`), the `*-linux.png` files are
   committed, the spec runs in `e2e.yml`, and timer/run-id/cost regions are
   masked. Remaining: `maxDiffPixels` is not yet set from a **measured** noise
   floor — re-run the unchanged spec N≥10× in the CI container and set the
   threshold just above the observed max diff (`DAY-ONE-PROMPT.md` §4a).
2. ~~**Land #30/#29/#33 fixes and flip the invariants to blocking.**~~ **DONE** —
   #30 routed each prose surface through the appropriate renderer (block
   `formatAnswerText` / inline `mdInline`, both already HTML-escaping, so no XSS
   regression; source titles stay plain) and extended the formatter for
   underscore emphasis + blockquotes; #29 clamped the elapsed base monotonic;
   #33 widened the transcript container. `continue-on-error` was then removed.
3. **Optional local speed-up:** a `.claude/settings.json` hook that runs the
   invariants on UI-file changes — but note `.claude/` is gitignored, so it is
   LOCAL-ONLY, never a substitute for the CI gate (see `04-mechanism-map.md`).

## Note on backend-dimension gates (not built this run)

The search (#31/#32), cost (#18–#20), observability (#26), and persistence (#27)
dimensions need their own gates (contract test, cost unit tests, degraded-mode
signal, post-deploy persistence smoke). They are specified in the ledger and
mechanism map but were out of scope for this run's UI-focused harness.


---

## Gates added 2026-08-03, with charters

Every gate below carries a **charter** in its own module docstring answering
four questions, and `tests/unit/test_gates_carry_a_charter.py` fails if one is
dropped. The charter lives in the gate file rather than here on purpose: the
person who needs it is the one standing in that file with a red test.

**Why this section exists.** The table above records *what* each gate does. It
does not record why it was added, what it cannot see, or when it has done its
job — so a future session hitting one red cannot tell load-bearing from
leftover, and will either delete it or exempt it. Both lose.

**The field that matters is WHEN TO REMOVE.** A gate without a removal
condition is permanent by default, and that is how a gate suite becomes sludge.

| Gate | Bridges | Cannot see | Removal condition |
|---|---|---|---|
| `tests/unit/test_adr_index_matches_directory.py` | the ADR index rotted by hand twice (0002 unlisted 11 days; 0004-0007 unlisted) | whether an ADR *should* have been written — it would have caught **0 of the 6** this batch missed | the index stops being hand-maintainable (generated at docs-build time, or a tool owns it) |
| `tests/unit/test_spend_cap_state_table.py` | 6 defects in a ~40-line predicate across 4 passes; 3 were dead ends. Found the 6th itself, in code hours old | whether production wires the *right* predicate (the integration test does); thread interleavings | the ledger moves to reserve-then-commit (ADR-0004) — the state space collapses and this file goes with it |
| `tests/unit/test_cited_paths_resolve.py` | 38 of 1,352 repo-path citations unresolved (2.8%), incl. a phantom ADR filename | whether the *claim* around the path is true — nothing mechanical can | prose stops carrying repo paths, or a docs toolchain resolves links at build time |
| `tests/unit/test_gates_carry_a_charter.py` | a gate whose rationale is lost becomes cargo cult or casualty | quality — it checks the four sections are present, not honest. "WHEN TO REMOVE: never" would pass | gate rationale gets its own tooling (an ADR per gate, or a register generated from source) |

**Scope note.** The charter check registers only these four. The ~30 gates in
the table above are **not** retrofitted: a meta-gate that opens red against
unrelated history gets deleted, which is the exact failure it exists to
prevent. Retrofit opportunistically, when touching a gate for another reason.

**What is still missing, honestly.** None of these records *yield* — whether
the gate has ever caught anything since it was added. Without that you cannot
distinguish a gate that saved you three times from one that has never fired,
which is the data that should drive removal. `docs/metrics/defect-discovery-audit.md`
is the closest thing (0 of 16 src/ defects caught by any gate, 10 of 16 by
adversarial review) and it is what makes this repo's scepticism about gates
correct. Add a dated line here when a gate catches something real.
