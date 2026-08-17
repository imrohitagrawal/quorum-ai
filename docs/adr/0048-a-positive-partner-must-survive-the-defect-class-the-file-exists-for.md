# ADR-0048: A positive partner must survive the defect class its file exists for

## Status

Accepted — 2026-08-17 (issue #226)

## Context

The #131 guard (`e2e/tools/check-negative-assertions.mjs`) fails a spec whose
negative assertion — "no X found", `toBeHidden()`, `toEqual([])`,
`.not.toContain()` — has no positive partner in the same `test()`.

Measured on clean `main` at `32c9f5e`:

```bash
cd e2e && node tools/check-negative-assertions.mjs --all
# negative-assertion guard: checked 28 changed spec file(s) vs origin/main
# 13 negative assertion(s) with no positive partner in the same test:
```

**13 unpartnered sites across 5 files.** The guard only checks the files changed
in a pull request, so none of them blocked anything — the first future pull
request touching one of these files would have met them with no context.

### Two numbers have been attached to this, and only one is right today

The issue body says **20**; the escalation comment on it says **13**. The number
that matters is the one the command prints today, which is **13**, and it is
still 13 after `main` moved to `32c9f5e`. Seven of the sites the issue lists —
all three in `workspace.spec.ts`, all three in `rendering-invariants.spec.ts`,
and `accessibility.spec.ts:177` — are simply not reported any more; the guard
run above names none of those files. **Why** they stopped being reported is not
established here: the tree and the guard have both moved since the issue was
filed, and this pull request did not separate the two causes for those seven.

### The issue body's causal claim is wrong for 7 of the 13

The issue says these sites "rely on matchers/shapes #148 newly recognizes". That
is a claim about what a tool used to do, and it was never run. Extract each
guard version and point both at the same 28 files:

Both scratch copies below live outside the repository on purpose; nothing here
adds a file to the tree.

The two extracted guards are deliberately kept in a `guards/` directory OUTSIDE
the copied `e2e/` tree, so nothing here reads as a path in this repository:

```bash
C=/tmp/corpus                                  # scratch, not part of the repo
mkdir -p "$C/guards" && git archive origin/main | tar -x -C "$C"
ln -s "$PWD/e2e/node_modules" "$C/node_modules"
git show bfae77c:e2e/tools/check-negative-assertions.mjs > "$C/guards/pre.mjs"
git show 3032282:e2e/tools/check-negative-assertions.mjs > "$C/guards/post.mjs"
SPECS=$(find "$C/e2e/tests" -name '*.spec.ts' | sort)   # 28 files
cd "$C"
node "$C/guards/pre.mjs"  $SPECS   #  8 negative assertion(s) with no partner
node "$C/guards/post.mjs" $SPECS   # 13 negative assertion(s) with no partner
```

Re-run 2026-08-17, and the two site lists compared:

- **7 of the 13 were already reported before #148** — `csp-smoke:100` and `:105`,
  `trust-score-invariants:160`, `:173`, `:193`, `:266` and `:382`.
- **#148 newly exposed 6** — `degraded-banner:323`, `readiness-banner:219` and
  `:261`, `trust-score-invariants:261` and `:265`, `parity-behavior:524`.
- **#148 also STOPPED reporting one** — `markdown-corpus:174`.

So "the widening exposed these" is true of under half of them. The majority were
sitting there before #148 ran at all.

### What counts as an acceptable partner is the question with teeth

The guard's own header concedes its limit: *"element-presence is not
text-non-emptiness"*. The obvious cheap partner — `toBeAttached()` — satisfies
the guard everywhere and looks like proof. It is not, and the difference is
measurable rather than a matter of taste.

Four defect classes, applied to a minimal surface, with every candidate partner
run against each:

- **DELETION** — `el.remove()`; the element leaves the DOM entirely.
- **CSS-HIDDEN** — `el.style.display = "none"`; the element exists and the code
  keeps it up to date, but a rule makes it invisible. Not hypothetical: this is
  the literal #111 and #115 defect, where `#readiness-banner` sat inside a
  `display: none` panel and no user had ever seen it in any offline state.
- **EMPTIED** — `el.textContent = ""`; the surface renders and holds no text.
- **PLACEHOLDER** — `el.textContent = "—"`; the em-dash stand-in that
  `trust-score-invariants.spec.ts` names in its own header.

Measured 2026-08-17 on chromium (Playwright 1.61.1, from `npx playwright
--version`) by a small self-contained script that sets a one-element page
(`<div id="surface" class="panel">a real answer</div>`), applies each mutation
via `page.evaluate`, and runs each candidate, recording whether it threw. The
table below is that script's stdout, unedited. "caught" = the candidate went RED
under that mutation. The `control` column asks the separate question of whether
the candidate is usable at all on a healthy page.

| Candidate partner | control | DELETION | CSS-HIDDEN | EMPTIED | PLACEHOLDER |
|---|---|---|---|---|---|
| the shipped negative alone (toBeHidden()) | FAILS (unusable) | **not caught** | **not caught** | **not caught** | caught |
| toBeAttached() | passes | caught | **not caught** | **not caught** | **not caught** |
| toBeVisible() + innerText().length > 0 | passes | caught | caught | caught | **not caught** |
| toBeVisible() + .not.toHaveText("—") | passes | caught | caught | caught | caught |

`toBeAttached()` passes under the exact defect class two of these files were
written to catch. It clears the guard while proving nothing about the bug that
actually shipped.

The PLACEHOLDER column matters because `innerText().length > 0` does **not**
catch it: `"—"` has length 1. Any table that folds PLACEHOLDER into EMPTIED
credits row 3 with a mutation it does not see.

That measurement was reproduced against the real application, not only the
minimal fixture:

- `#demo-mode-banner { display: none }` added to `app.css`: the shipped control
  in `degraded-banner.spec.ts` **passed** as `toBeAttached()` and **went red** as
  `toBeVisible()`.
- `#readiness-banner { display: none }` added to `app.css`: same result on both
  `readiness-banner` controls.

## Decision

**A positive partner must be an assertion that goes RED under the defect class
the file exists for. Rank the options and take the strongest one that is cheap;
do not stop at the first shape that satisfies the guard.**

In practice, for these 13 sites:

- **Prefer an A/B contrast.** Re-drive the one input that should flip the
  behaviour and assert the other outcome, in the same test. This is what turns a
  test whose title makes a causal claim — "the flag, not the state alone, drives
  it" — into a test that actually asserts causation. Used in four places here.
- **Otherwise assert visibility AND non-empty text**, never presence alone.
- **`toBeAttached()` is not an acceptable partner** for a surface whose
  historical defect is invisibility. It stays fine where absence-versus-presence
  really is the whole question.

### What was actually shipped, stated plainly

The partners added here use **row 3** of the table above
(`toBeVisible()` + `innerText().length > 0`), not the strongest row 4. Row 4
would additionally catch PLACEHOLDER. Row 3 was taken because row 4 hard-codes
one specific placeholder string, so it stops matching the moment that character
changes and gives a false sense of coverage while doing so. **This is a real
gap, not a claim of completeness: a surface that rendered exactly `—` would
satisfy every partner added in this pull request.** Whether any of these five
surfaces can actually reach an em-dash state was NOT investigated here; the gap
is recorded rather than argued away.

The exemption count in `e2e/tests/` goes from **0** to **1**
(`grep -rn "no-positive-partner" e2e/tests/ | wc -l`, run against `origin/main`
and against this branch).

### The one exemption, and why

`e2e/tests/ui-parity/parity-behavior.spec.ts:524` is a **guard false positive,
not a vacuous test**. Line 523 immediately above it asserts
`toHaveClass(/button-secondary/)` on the same locator — a real partner. #148
added `toHaveClass` to the guard's `.not`-direction set and never taught
`classify()` the plain direction, while `toHaveAttribute` — a strictly broader
claim, since `class` is an attribute — was already accepted.

The honest fix is in the classifier. Changing the guard's acceptance predicate
is a separate and adversarial concern (each widening to remove a false positive
is a chance to open a new way to satisfy the guard vacuously), so it is deferred
to its own pull request and this site carries a `// no-positive-partner:`
annotation pointing there.

**So the count is 12 sites closed by a real spec partner and 1 by an annotated
waiver.** The bar for an exemption stays high: it is legitimate only when the
subject provably cannot be shown non-empty in that test, or when the guard is
demonstrably wrong about a partner that exists.

## Rejected alternatives

- **`toBeAttached()` everywhere.** Cheapest, and it clears the guard on all 13
  sites. Rejected on the measurement above: it passes under CSS-HIDDEN, the
  defect that actually shipped in #111/#115.
- **Exempt the hard ones.** Would have closed the issue with roughly four
  annotations and no new coverage. Rejected — the problem is that these tests
  cannot fail, and an exemption does not change that; it only records that
  someone noticed.
- **Fix the guard's `toHaveClass` blind spot in this pull request.** It is the
  correct fix and it is one line. Rejected here on process grounds. The previous
  attempt at #226 (branch `fix/226-vacuous-e2e-negative-assertions`) did exactly
  this and hit the two-round review cap unmerged. Per its own escalation comment
  on the issue — reported there, not re-measured here — **every blocking finding
  across both rounds came from the classifier change rather than from the spec
  fixes**, including a widening that let the guard report 0 violations on a
  synthetic file where `main` reported 4. Mixing a low-risk spec change with an
  adversarial predicate change cost that attempt its merge. See rule 17: one
  concern per pull request.
- **Add a decorative assertion to `parity-behavior.spec.ts`.** Would have kept
  the diff inside the spec files and needed no annotation. Rejected: the test is
  already correct, and bolting a meaningless assertion onto it to silence a
  false positive is the same vacuity this guard exists to remove, one level up.
- **Same-subject partner matching in the guard.** Would close the guard's stated
  "element-presence is not text-non-emptiness" limit mechanically rather than by
  this policy. Rejected for now: the guard's header already judged it "markedly
  more false-alarm-prone", and this pull request adds no evidence either way.
  The policy above is influence; the guard stays a shape check.
- **Run the guard corpus-wide (`--all`) in CI, blocking.** Would stop a violation
  sitting indefinitely in a file nobody touches — the exact condition that let
  these 13 accumulate. Rejected here: it changes the gate's scope from "the files
  this pull request touched" to "every file", which would block unrelated pull
  requests on defects they did not introduce. The #226 issue body records the
  same reasoning for why these were filed rather than fixed inside #148.

## Consequences

- Several tests now drive their page twice. Measured 2026-08-17, chromium,
  `--workers=1`, **one run of each spec file before and after** — the baseline is
  the same spec file restored to its `origin/main` content and run through the
  identical command, so the delta is the added leg and nothing else.

  | Test | on `origin/main` | on this branch | delta |
  |---|---|---|---|
  | `degraded-banner` — a fully-LIVE run does NOT show the transcript disclosure banner | 1.12s | 1.91s | +0.79s |
  | `readiness-banner` — live: no offline disclosure anywhere | 0.56s | 0.60s | +0.04s |
  | `readiness-banner` — live without the ceiling flag stays hidden | 0.54s | 0.63s | +0.09s |
  | `trust-score-invariants` — an absent evaluation renders nothing | 1.84s | 2.40s | +0.56s |
  | `trust-score-invariants` — no ARIA value-widget lie | 0.76s | 0.84s | +0.08s |
  | `trust-score-invariants` — GREEN RULE, no green paint anywhere (×6) | 0.77–0.89s | 0.81–0.91s | +0.00–0.06s |
  | whole file: `degraded` + `readiness` + `trust-score` (76 tests) | 1.1m | 1.2m | — |

  **These are single-run wall-clock figures on one laptop, not a benchmark**, and
  a re-run will move them by tens of milliseconds. They are recorded for the
  ratio, not the absolute: the legs that re-drive the whole page cost roughly
  +30–70%, the ones that only add an assertion to a page already driven cost
  single-digit percent.

- **Flake rate, measured rather than asserted.** `--repeat-each=10`,
  `--workers=1`, `--retries=0`:

  | Specs | Runs | Failures |
  |---|---|---|
  | `degraded-banner` + `readiness-banner` + `trust-score-invariants`, chromium | **760** | **0** (10.8m) |
  | `csp-smoke`, chromium + firefox + webkit | **60** | **0** (1.4m) |

  **These repeat runs need a raised session cap and that is a trap worth
  recording.** The first attempt used the documented local values
  (`SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600`) and
  collapsed part-way through with 123 failures, none of them real: the page
  rendered *"This IP has reached today's limit on new sessions"*. 760 boots
  against a 600 cap exhausts the DURABLE per-IP counter, which persists in the
  gitignored `.data/feedback_events.sqlite3` and therefore survives across runs.
  Deleting that file and raising the override to its own maximum (10000; the
  setting rejects anything higher) gave the clean run above. A flake number
  taken without this is measuring the rate limiter, not the product.

- The guard reports **0** unpartnered sites, from 13 on `main`, over the same
  28 committed spec files — **with the one annotated waiver described above**,
  not without it. Both modes were run:

  ```bash
  cd e2e && node tools/check-negative-assertions.mjs --all           # 28 files, exit 0
           node tools/check-negative-assertions.mjs --base origin/main  # 5 files, exit 0
  ```

  The file counts are reported by the guard itself, so this is not a gate
  passing over an empty input. Deleting the waiver comment takes it straight
  back to 1 violation, which is how that 0 was shown to mean something.

- This ADR is influence, not enforcement. The guard mechanically enforces *that*
  a partner exists; nothing mechanically enforces that the partner is a good one.
  If this rule is seen being skipped, that is the signal to look for a mechanical
  check, not to restate it louder.

- **Not fixed here**, and still true: the guard's `--all` mode uses
  `git ls-files`, so it is blind to the gitignored `e2e/tests/review/` scratch
  directory; and CI runs it only over a pull request's changed files, so a
  violation can sit indefinitely in a file nobody touches. Two prose counts are
  also stale — `e2e/tools/check-negative-assertions.mjs:28` and
  `.github/workflows/e2e.yml:129` both say "21 pre-existing violations across 7
  files". No test pins either number, so nothing goes red; both live in files
  this pull request deliberately does not touch, and both belong with the
  classifier work.

- **What no measurement here covers:** whether the partners hold on firefox and
  webkit. Only `csp-smoke.spec.ts` runs cross-engine (its own advisory workflow,
  verified green on all three); the other four specs are chromium-only in CI, and
  were only ever run on chromium here.
