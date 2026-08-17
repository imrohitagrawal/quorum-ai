# ADR-0048: A positive partner must survive the defect class its file exists for

## Status

Accepted — 2026-08-17 (issue #226)

## Context

The #131 guard (`e2e/tools/check-negative-assertions.mjs`) fails a spec whose
negative assertion — "no X found", `toBeHidden()`, `toEqual([])`,
`.not.toContain()` — has no positive partner in the same `test()`.

Measured on clean `main` at `e3b31c0` (the tip this branch is merged up to;
`git rev-parse origin/main`). The count was first taken at `32c9f5e` and
**re-measured at `e3b31c0` on 2026-08-18 — still 13, same 13 sites**. Only the
ref moved:

```bash
# Point the guard at origin/main's OWN spec corpus, from a scratch copy
# outside the tree, so the number is about `main` and not about this branch:
git archive origin/main e2e | tar -x -C "$SCRATCH"
find "$SCRATCH/e2e" -name '*.spec.ts' | sort | xargs node e2e/tools/check-negative-assertions.mjs
# negative-assertion guard: checked 28 changed spec file(s) vs origin/main
# 13 negative assertion(s) with no positive partner in the same test:
```

**13 unpartnered sites across 5 files.** The guard only checks the files changed
in a pull request, so none of them blocked anything — the first future pull
request touching one of these files would have met them with no context.

### Two numbers have been attached to this, and only one is right today

The issue body says **20**; the escalation comment on it says **13**. The number
that matters is the one the command prints today, which is **13**, and it is
still 13 after `main` moved on to `e3b31c0`. Seven of the sites the issue lists —
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

### What was actually shipped, per file, stated plainly

An earlier draft of this ADR said every partner here is **row 3** of the table
above. That was wrong in both directions — two files ship less, two ship more —
and review round 2 caught it. What is actually in the diff, and what each shape
survives, measured by mutation on 2026-08-18 (the full table is under
Consequences):

| File | Partner shape shipped | Row |
|---|---|---|
| `csp-smoke.spec.ts` | two `expect.poll(...).toBeGreaterThan(0)` on a deliberately triggered violation — one per channel | not in the table: the subject is a live collector, not a DOM element |
| `degraded-banner.spec.ts` | `toBeVisible()` on the banner **+** `innerText().length > 0` on `#demo-mode-banner-title` **+** `toContainText("3 of 4 model answers")` on `[data-demo-mode-target]` | row 3, plus an exact-content leg stronger than row 4 |
| `readiness-banner.spec.ts` — offline control | `toBeVisible()` **+** `innerText().length > 0` on `#readiness-banner-message` **+** `toContainText("local simulation helpers")` | row 3, plus an exact-content leg stronger than row 4 |
| `readiness-banner.spec.ts` — ceiling control | `toBeVisible()` **+** exact `toHaveText("Today's shared demo budget has been used up")` on `#readiness-banner-title` | stronger than row 4 |
| `trust-score-invariants.spec.ts` (4 sites) | `toBeVisible()` **+** `innerText().length > 0` on `#result-trust-score`; the absent-evaluation site adds `toContain(DISCLOSURE)` on `#main-content` | row 3 |
| `parity-behavior.spec.ts` | none added — annotated waiver; the partner is the pre-existing `toHaveClass(/button-secondary/)` on line 523 | not applicable |

**Two content legs were added in review round 2 and are the reason this section
was rewritten.** `degraded-banner` and `readiness-banner` originally shipped
`toBeVisible()` **alone** — row 2's failure mode, not row 3's. Measured
2026-08-18, both survived EMPTIED: with the mixed-run branch of
`computeDemoModeBannerCopy` returning `{ title: "", message: "" }`, and with the
readiness renderer's two `textContent` writes replaced by `= ""`, each banner
still rendered and each `toBeVisible()` stayed GREEN. An empty banner discloses
nothing, which is precisely what those two files exist to prevent.

**Why the content leg does not target the banner itself.** Both banners contain
static markup the renderer never writes — a `.callout-icon` "!" glyph, and in
the readiness case a "Show more" button — so the BANNER's own `innerText` is
non-empty even with all copy gone. `innerText(banner).length > 0` would have
been row 3 in shape and row 2 in effect. The leg targets the specific nodes the
renderer writes, whose markup default is empty
(`workspace.html:192` and `:691`). The readiness TITLE was rejected for the same
reason in reverse: its markup default is the non-empty string
`"Live execution is unavailable"`, so a title assertion alone would pass on the
server-rendered default with the renderer doing nothing.

**The PLACEHOLDER gap, narrowed but not closed.** It now applies to the four
`trust-score-invariants` sites only — a surface rendering exactly `—` would
satisfy their `length > 0` leg. The three banner sites carry an exact-content
leg and would go RED. Whether the trust surface can actually reach an em-dash
state was NOT investigated here; the gap is recorded rather than argued away.

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

- **Every shipped partner was swept against all three defect classes, not two
  of twelve.** Review round 2 found the EMPTIED hole in two partners by
  inspection; the rest were then measured rather than assumed. Each mutation was
  applied to `src/`, the spec re-run exactly as CI runs it
  (`--project=chromium --workers=1 --retries=0`), and `src/` restored from a
  `cp` copy verified with `diff -q`. "RED" = the partner's own assertion
  produced the failure. Measured 2026-08-18.

  | # | Partner site | DELETION | CSS-HIDDEN | EMPTIED |
  |---|---|---|---|---|
  | 1 | `csp-smoke` — DOM `securitypolicyviolation` poll | RED | n/a | RED |
  | 2 | `csp-smoke` — console `isCspError` poll | RED | n/a | RED |
  | 3 | `degraded-banner` — `#demo-mode-banner` control | RED | RED | RED |
  | 4 | `readiness-banner` — offline control | RED | RED | RED |
  | 5 | `readiness-banner` — ceiling control, `toBeVisible()` | RED | RED | survives |
  | 6 | `readiness-banner` — ceiling control, title `toHaveText` | RED | RED | RED |
  | 7 | `trust-score` — GREEN-RULE loop, `toBeVisible()` | RED | RED | survives |
  | 8 | `trust-score` — GREEN-RULE loop, `innerText().length > 0` | RED | RED | RED |
  | 9 | `trust-score` — ARIA scan control | RED | RED | RED |
  | 10 | `trust-score` — absent-evaluation control | RED | RED | RED |
  | 11 | `trust-score` — verified-surface control | RED | RED | RED |
  | 12 | `parity-behavior` — `toHaveClass(/button-secondary/)` | RED | **survives** | RED |

  The mutations, one per class:
  - **DELETION** — rename the element's `id` in `workspace.html` so no such
    element exists, without breaking the drive path. For rows 1–2 the analogue
    is on the product: `main.py`'s `Content-Security-Policy` header removed.
  - **CSS-HIDDEN** — `#<id> { display: none !important; }` appended to `app.css`.
    Not applicable to rows 1–2: neither channel is a rendered element.
  - **EMPTIED** — the element stays present and visible while the renderer
    writes nothing. `computeDemoModeBannerCopy` returns `{title:"",message:""}`
    (row 3); the readiness renderer's `textContent` writes become `= ""` (rows
    4–6); `box.textContent = ""` immediately before `box.hidden = false` in
    `renderTrustScore` (rows 7–11); `class=""` on the button (row 12). For rows
    1–2, the collector fires but records nothing (`push` removed; console text
    pushed as `""`) — the product-side analogue, an empty
    `Content-Security-Policy: ""` header, is also RED.

  **Three cells are honest "survives", and none of them leaves a site
  unpartnered:**
  - Rows 5 and 7 are `toBeVisible()` legs whose EMPTIED coverage comes from the
    content leg beside them in the same test (rows 6 and 8). A visibility
    assertion cannot see emptiness; that is the whole finding, and it is why
    rows 3 and 4 needed fixing — those two had no row 6 or row 8 beside them.
  - Row 12 survives CSS-HIDDEN by design. Its defect class is the class
    ATTRIBUTE ("a solid secondary button, not a borderless ghost"), and the
    negative it partners reads that same attribute on that same element, so a
    hidden-but-correctly-classed button is outside the class of defect either
    line exists to catch. An element that does not exist fails both.

  **Environment trap, measured here and worth recording.** Two of these
  mutations first reported a FALSE GREEN. `lsof -ti tcp:18085 | xargs -r kill -9`
  did not always kill the app server, and `reuseExistingServer` is true locally,
  so Playwright reused a process still serving the PRE-mutation template —
  `curl /ui` showed `class="button button-secondary composer-cta"` while the file
  on disk said `class=""`. `pkill -f "uvicorn product_app.main:app"` plus a
  confirming `curl` is what makes a mutation run trustworthy. A mutation study
  that only ever sees RED is safe from this; one that reports a survivor is not.

- Several tests now drive their page twice. Measured 2026-08-17, chromium,
  `--workers=1`, **one run of each spec file before and after** — the baseline is
  the same spec file restored to its `origin/main` content and run through the
  identical command, so the delta is the added leg and nothing else.

  | Test | on `origin/main` | on this branch | delta |
  |---|---|---|---|
  | `degraded-banner` — a fully-LIVE run does NOT show the transcript disclosure banner | 1.12s | 1.91s → **2.1s** after round 2 | +0.79s → +1.0s |
  | `readiness-banner` — live: no offline disclosure anywhere | 0.56s | 0.60s → **0.79s** after round 2 | +0.04s → +0.23s |
  | `readiness-banner` — live without the ceiling flag stays hidden | 0.54s | 0.63s → **0.76s** after round 2 | +0.09s → +0.22s |
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

  | Specs | Runs | Failures | When |
  |---|---|---|---|
  | `degraded-banner` + `readiness-banner` + `trust-score-invariants`, chromium | **760** | **0** (10.8m) | round 1 |
  | `csp-smoke`, chromium + firefox + webkit | **60** | **0** (1.4m) | round 1 |
  | `degraded-banner` + `readiness-banner`, chromium — the two specs round 2 changed | **390** | **0** (6.6m) | round 2, 2026-08-18 |

  The round-2 re-scan covers only the two specs round 2 edited.
  `trust-score-invariants` took a comment-only change in round 2 (no assertion
  added or altered), so its round-1 figure still describes the code that ships.

  **A second environment trap, measured while doing this.** The first round-2
  scan attempt reported ~100 failures, every one of them
  `page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:18085/ui`. Cause:
  a Playwright `test-server` belonging to a DIFFERENT worktree on the same
  machine (`pgrep -f playwright` named it) contends for the fixed port 18085,
  and the app server under it died part-way through. Nothing product-side.
  Before believing a flake number, check that the failures are assertions and
  not connection errors — a shared fixed port makes "flaky" and "someone else's
  session" look identical.

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

- The guard reports **0** unpartnered sites **among committed specs**, from 13
  on `main` over the same 28 committed spec files — **with the one annotated
  waiver described above**, not without it. "Among committed specs" is the exact
  claim and not a hedge: `--all` enumerates with `git ls-files`
  (`e2e/tools/check-negative-assertions.mjs:380`), so it never sees the
  gitignored `e2e/tests/review/` scratch directory, and a review lens reported
  one real unpartnered site sitting there — reported, not re-measured here, since
  that directory does not exist in this worktree. Whatever its contents, the
  blindness does not flatter the result: it applied identically to the 13
  measured on `main`. Both modes were run
  (re-run 2026-08-18, after the round-2 content legs landed):

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
