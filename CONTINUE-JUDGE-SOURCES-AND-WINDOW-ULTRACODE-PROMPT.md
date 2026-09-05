# CONTINUE — the clipped critique, then the window's three measurements

**Written 2026-09-05 by the session that shipped ADR-0099 and ADR-0100.**
Executable procedure. Read `AGENTS.md` FIRST — it overrides everything here.

**THIS IS THE CURRENT PROMPT.** It supersedes
`CONTINUE-WINDOW-MEASUREMENT-ULTRACODE-PROMPT.md`, whose Item 0 (the three
UI-truthfulness PRs) is now COMPLETE and merged. If you find that file at the
repo root still listing PR A/B/C as work to do, it is stale — prefer this one
and say so.

---

## RULE ZERO: THIS DOCUMENT IS A CLAIM, NOT A FACT

This repo has MEASURED the decay rate of handoff documents: roughly half of what
one asserts does not survive contact with the tree. The session that wrote THIS
file had **11 defects** found in work it had already reported locally green, and
**about a third of its own prose claims failed verification** — "five test
files" (three), "four false claims" (one), "five conjuncts" (fourteen).

So: **re-verify every numbered claim below before acting on it.** Each names the
command that settles it. If a premise turns out false, AGENTS.md rule 3 applies
— STOP and say so; do not repair it silently.

---

## FIRST MOVE — run these before anything else

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git fetch -q origin && git rev-list --left-right --count main...origin/main   # expect 0 0
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool
uv run python scripts/live_posture_check.py > /tmp/p.log 2>&1; echo "EXIT=$?"; cat /tmp/p.log
gh issue list --state open --limit 100
ls docs/adr/ | tail -3            # next free ADR number; 0100 is TAKEN
ls e2e/tests/review/ 2>/dev/null  # non-empty => make quality is RED locally, not your diff
```

Expected, so you can spot drift fast: `main` 0/0 at `6bcb49e` or later;
`build_sha` == main's tip; `live_execution`, `judge_enabled` and
`peer_critique_enabled` all `true`; watchdog EXIT=0 with
`decision=live_within_declared_window`.

**If the watchdog exits 1, deal with that BEFORE any feature work** — it means
the live posture is unsanctioned or unattended, which is money running without
cover.

---

## WHAT NEEDS THE HUMAN, EVERY TIME

1. **Re-affirm the window every 24h** until `2026-09-08T07:51:25Z`. Comment on
   issue **#290**, token STARTING the line, quoting the window's own
   `opened_at` (NOT today's date):
   ```
   REAFFIRM live-execution 2026-09-03T07:51:25Z
   ```
   GitHub types workflow tokens as `Bot` and the check refuses them. `gh` here
   is `imrohitagrawal`, type `User` — confirm with
   `gh api user --jq .type` — and the owner has authorised posting on their
   behalf when ASKED. Ask; do not assume a standing licence.
   Last posted `2026-09-05` (3 re-affirmations counted, watchdog EXIT=0).
2. **Any paid production run.** The 17b override covers push/PR/merge/deploy;
   it does NOT cover money.
3. **Closing the window** on 2026-09-08: `make close-window`. It makes BOTH
   edits atomically (flag false AND `expires_at` -> now). The obvious one-edit
   revert is REFUSED — #407 is a window that outlived its expiry by ~8.6h
   because that two-part edit was not made under pressure.

---

## THE AUTHORISATION, unchanged

The product owner overrode AGENTS.md rule 17b on 2026-09-03:

> "You have the explicit approval to push, open a PR, merge, and deploy,
> provided everything has been properly tested, reviewed, and is successful,
> and CI gates are passing successfully."

**The condition is load-bearing, and "CI is green" is NOT sufficient.** The bar:

1. All six required contexts SUCCESS — re-derive, never trust a table:
   `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`
2. **Open every advisory log and find the number.** Measured on 2026-09-05:
   `diff-cover` reported 100% having measured **ZERO** executable lines on one
   PR, and the mutation gate reported **100%** having scored **8 of 41** mutants
   with 33 excluded as timeouts. Both are honest — they SAY so — and both read
   as green ticks in the UI. Say out loud when a gate measured nothing.
3. Adversarial review fanned out, findings reproduced, blockers resolved.
   **Expect your own fix to introduce a defect — budget a round for it.** It
   happened TWICE on 2026-09-05.
4. A mutation proof with a STATED BASELINE, in a COMMITTED file a reviewer can
   re-run. See `scripts/proofs/mechanism_copy_mutations.py`. This is not
   ceremony: writing that file found **2 of 10 mutants SURVIVING** in fixes
   already hand-verified as done.
5. After merge: verify the deploy **JOB** (one merge yields ~3 runs and most are
   `cancelled` — read the job, not the rollup), `/status.build_sha` == the merge
   SHA, and that the thing you built actually fires.

---

## THE ORDER — owner-agreed, do not reorder without saying why

The owner's rationale, recorded 2026-09-04: run the paid measurement AFTER the
code fixes so the same ~$0.06 validates both.

1. **Item 1 — the clipped-critique defect.** Free, live in production, unblocked.
2. **Item 2 — file the judge-source-access issue** and design Route B on paper.
   Free, off the critical path.
3. **Item 3 — Phase 0, the harvest harness at $0**, validated against SIMULATED
   runs. **Must precede any spend.**
4. **Item 4 — one validation run (~$0.06).** NEEDS THE OWNER'S GO.
5. **Item 5 — build judge source access** on the decided route, shipping an
   INPUT bound with it (#268).
6. **Item 6 — three varied runs.** NEEDS THE OWNER'S GO.

Step 3 before step 4 is load-bearing: if the sink does not capture what is
needed, the money is gone and the window is not repeatable.

---

## ITEM 1 — THE CLIPPED-CRITIQUE DEFECT (start here)

**Claim, MEASURED per ADR-0093:** seven of eight critique calls returned
`finish_reason: "length"` — the 2000-token cap genuinely reached and the reply
clipped. Full price for a truncated critique, on a receipt that looks healthy.

**Verify before acting:**
```bash
grep -n "DEBATE_ROUND_MAX_TOKENS" src/product_app/debate.py     # expect 2000
sed -n '325,335p' docs/adr/0093-*.md
```

**THE TRAP — two unrelated "seven of eight" figures exist in this repo.** One is
`finish_reason: "length"` (this item). The other, in
`docs/analysis/2026-08-26-b3-timeout-probe.md:87`, counts wall-clock timeout
exceedance and has nothing to do with token caps. ADR-0093 says so explicitly
because a prior session nearly merged them. Do not cite one for the other.

**Why it is worse than measured:** ADR-0096 made round 2's reply LONGER — it now
returns a critique AND a self-assessment, rationale, sources and a **revised
answer** — and `synthesis` reads those revised answers as its PRIMARY input. So
the part most likely to be clipped off the tail is the source-backed answer the
owner asked to be protected. **Live in production right now.**

**What to do:**
1. Measure the real output length of a round-2 reply under ADR-0096's prompts.
   Do not guess a number.
2. Raising the cap raises cost. `_estimate_bound_usd` must remain the fail-safe
   bound; `tests/unit/test_peer_bound_is_a_true_ceiling.py` pins the arithmetic
   with literals on both sides.
3. **A pinned number may be a PUBLISHED REQUIREMENT.** One bound is written into
   21 files; the run deadline is NFR-001/AC-021 in six places including the
   operator dashboard. `grep` the value before changing it.
4. A decision gets an ADR in the same PR (rule 16d); regenerate the index with
   `python3 scripts/generate_adr_index.py`, never by hand.

---

## ITEM 2 — THE JUDGE CANNOT READ ITS SOURCES (file it; it is in no issue)

Raised repeatedly by the owner and tracked NOWHERE, which is why it keeps
slipping. The judge's evidence block is built as `f"[{i}] {title} :: {url}"` —
titles and URLs, no page content — and **nothing in `src/` resolves a cited
URL**. So it is asked whether an answer asserts only what its evidence supports,
about evidence it has never seen. ADR-0098 already corrected the UI copy that
called this "checked"; the underlying gap remains.

Two routes, and **the choice is decided by one unmeasured signal** — whether
OpenRouter's `:online` annotations carry passage CONTENT (window measurement 3):
- **Route A:** use the annotation content, if it exists. No new fetches.
- **Route B:** a credential-guarded fetcher that resolves cited URLs.

**A coupling nobody had written down:** judge input is bounded today at 32
source lines x 300 chars, and #268 says nothing bounds call INPUT. So source
access must ship **with** an input bound, or it widens exactly that exposure.

---

## ITEM 3 — PHASE 0, THE HARVEST HARNESS ($0, do it before any spend)

`TELEMETRY_LOG_DIR = "/data"` in `fly.toml`, mounted from volume `quorum_data`.
`src/product_app/telemetry_sink.py` defines `TELEMETRY_FIELD_NAMES`, which since
ADR-0093 decision 5 includes `query_run_id`, `stage`, `slot_number` and
`finish_reason` — the correlator that makes a critique row attributable at all.

Validate the harvester against SIMULATED runs, which cost nothing. It must
capture judge token counts as well as the critique correlator.

**THE STRUCTURAL RISK, and the thing to get right:** the window has been open
with live execution, peer critique AND the judge all `true` since
2026-09-03 and has measured NOTHING, because nobody executed a query. This
repo's single most-repeated failure is exactly that — a gate or window reaching
a terminal state having measured nothing.

---

## FACTS THIS SESSION PAID FOR — do not re-derive these

- **The moderator shape is still REACHABLE in production.**
  `_build_peer_round` returns `None` — falling back to the moderator — when the
  flag is off, when NO slot is eligible, or when a cancel lands before the first
  dispatch. Round 2 can be skipped entirely. `critique_shape` is stamped **per
  round**. Any copy describing a run must read the run's own shape.
- **A critic that returns nothing still yields a `SlotCritique`** with Quorum's
  template and `critique_mode` left at `"fallback"`, while the round stays
  shaped `"peer"`. So `critique_shape === "peer"` means critics were
  DISPATCHED, not that any ANSWERED. `describePeerCritique` counts
  `critique_mode === "live"` for exactly this reason.
- **`#cost-confirmation` is DEAD MARKUP.** `hidden` in the template, and
  `app.js` sets `.hidden = true` and never false. Its "10-30%" cost claim has
  never been shown to anyone. Four places in the repo already said so and a
  session still spent a review round rewriting it. **The LIVE cost copy is
  `#cost-gate-cap-note`, the `.cost-gate .lede`, and `renderLiveCap`'s
  `live-cap-note`** — and they are already careful.
- **`max_cost_usd` is NOT an unqualified ceiling.** `costs.py` says in its own
  words: *"Do not restore an unqualified 'true ceiling' wording while these
  hold."* It bounds OUTPUT only; the `:online` search fee is priced at `0.0` by
  accepted decision, measured at 76.7% of the approved figure on one run. Review
  has refused that wording twice. Do not write it a third time.
- **`debate_round_cost` is `max(peer_round_cost, moderator_round_cost)`**, not
  an unconditional sum over four slots. With cheap enough slots the max picks
  the moderator and the estimate prices ZERO critique calls.
- **`by_stage` attributes critique spend CORRECTLY on both paths.** Only
  `by_model` mis-attributes, and only on the estimate side.
- **`/openapi.json` and `/docs` are 404 in production** (`api_docs_enabled` is
  LOCAL-only). OpenAPI prose is a correctness surface, not a user-facing one.

---

## TRAPS THAT COST THIS SESSION DIRECTLY

- **Never read a gate's exit status through a pipe OR after another command.**
  `make X 2>&1 | tail` reports *tail's* status, and `make X; echo "EXIT=$?"`
  reports *echo's*. A Playwright run with **8 failed** came back as "exit code
  0" through that idiom. Write it as:
  ```bash
  make <target> > /tmp/gate.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/gate.log
  ```
  and read the number from the FILE.
- **`make quality` is `format-check lint type-check test`.** It failed three
  times before reaching the tests, and every time the last cheerful line on
  screen was ruff's `All checks passed!`.
- **`e2e/playwright-report/` breaks `test_code_text_strips_js_comments`.** It is
  gitignored, so that guard finds it by `rglob` and CI never sees it. Reads
  exactly like a diff regression. `rm -rf e2e/playwright-report e2e/test-results`
  after any local Playwright run.
- **A `git archive HEAD` copy does NOT contain uncommitted work.** A mutation
  proof run against one silently measured 2 tests instead of 6 and looked fine.
- **`make format` rewrites your mutation-proof script** and can invalidate its
  anchors. Re-run the proof AFTER formatting.
- **The visual baselines did NOT need re-seeding**, contrary to a prediction
  made from a stale darwin baseline. Darwin expects 3137px against a page
  rendering ~3360-3385; that gap says NOTHING about whether the LINUX comparison
  exceeds its 1% tolerance. Do not infer one from the other.
- **Adding an e2e spec moves `--min` in `e2e.yml`.** Raise it in the SAME PR and
  MEASURE it by running the 17-spec lane — never compute it. It went
  267 -> 269 -> 271 this session, each measured.
- **Run e2e exactly as CI does**, or ~95 phantom failures appear:
  ```bash
  lsof -ti tcp:18085 | xargs -r kill -9
  rm -f .data/feedback_events.sqlite3
  cd e2e && SESSION_RATE_LIMIT_PER_MINUTE=600 SESSION_MINT_CAP_OVERRIDE=600 \
    npx playwright test <spec> --project=chromium --workers=1 --retries=0
  ```

---

## THE REVIEW LESSON, measured 2026-09-05

Two adversarial review rounds found **seven contract-level defects** in work
already locally green, and **most were in the TESTS, not the code**:

- a gate silently **weakened** — moving copy out of an `mkEl(...)` literal put it
  beyond `_extract_mkel_literals`, so the banned-phrase list stopped covering
  the served sentence;
- the entire user-visible fix **revertible green** — helper left as dead code,
  both call sites restored, 9 of 9 passing;
- a fix that **reproduced its own defect with the sign flipped**;
- a fixture that **inverted the server's arithmetic**, so a spec named "explains
  why the row looks like a saving" was green over a receipt showing no saving;
- a note asserting "the totals agree" directly above a row reading
  `$0.19 -> $0.202`.

**So: fan out review, and tell every reviewer IN CAPITALS not to write, edit,
`git checkout`, `git stash` or `sed -i` anything, and to make its own
`git archive HEAD | tar -x -C <dir>` copy if it must mutate.** Also tell it, in
these words: *"for every number, superlative and causal claim in the diff's
comments, commit body and PR description, name the command that produces it — or
mark it UNVERIFIED."* That instruction is the highest-yield mitigation available
and it costs nothing.

---

## CLOSE-OUT, in this order, every time

1. Local gates green (rule 14) and every review finding resolved.
2. Merge with an explicit message and `make close-guard` FIRST:
   ```bash
   PR=<n> EXPECT_CLOSE="<issues to close, or empty>" \
     MERGE_SUBJECT="..." MERGE_BODY="$(cat body.md)" make close-guard
   ```
   CI never sees the MERGE text; this command is the only thing that does. Four
   issues have been closed by accident this way.
3. Verify the deploy per the bar above — the JOB, on the newest run.
4. `git merge --ff-only origin/main` from the main checkout (`git branch -f`
   FAILS when `main` is the branch you have checked out), remove the worktree
   FIRST, then delete the branch local and remote.
5. `rm -rf e2e/playwright-report e2e/test-results` and any scratch copies.
