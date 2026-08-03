# AWAITING `/code-review ultra` — nothing below is merged to main yet

Integration branch: **`feature/major-issues-batch`** — open as **PR #240**.

**Tracked in git deliberately.** The ~40 `ISSUE-*-RESULT.md` files at the repo
root are all untracked, so the project's record of what was learned lives on one
laptop. This one is in `docs/analysis/` instead.

Run stopped at §8.4a of `MAJOR-ISSUES-BATCH-ULTRACODE-PROMPT.md`, as
instructed. `/code-review ultra` is user-triggered and billed; it was not
invoked, simulated, or substituted.

---

## Shipped (merged into the integration branch, NOT into main)

| # | What | Verified by |
|---|---|---|
| 103 | Dropped the vacuous nightly feedback-audit workflow — it opened an empty checkout-local DB and had never read production data | `FLY_API_TOKEN` is not available to a workflow of that shape, so the honest close was removal, not invention of a new secret |
| 124 | Browser-level coverage for 7 of 8 remaining provider notices | parameterised spec + a registry-sync guard, both directions |
| 127 | Wired 4 orphaned e2e spec dirs into CI and fixed the specs | the issue said 3 files / 42 tests; a 4th (`navigation.spec.ts`, 10 tests) was in the identical state — corrected in the PR rather than silently absorbed |
| 162 + 166 | Six gate-liveness fixes; deleted the dead codex-review job | each bite-proofed by reverting the real workflow YAML on a copy |
| 182 | `mutation-baseline` always prints a partial score, even on timeout | orphan-process-group kill proven; the post-SIGKILL wait is bounded too (review finding) |
| 123 | A recovered volume no longer needs a process restart | background reconnect keyed on #109's write-health signal, not on `store is None` |
| 122 | The daily spend cap fails **closed** on a ledger a reopen could not restore | see the correction record below |
| 155 | High-stakes wording in `context` no longer skips the acknowledgement | the review agent reported 1,836 structured attack attempts with 0 bypasses — that is *its* measurement, reproducible from its method but not asserted by any test in this repo, so read it as reviewer testimony rather than a checked-in fact |
| 117 | The readiness banner no longer flashes — and cannot be silenced | MutationObserver installed before `app.js`; `toBeHidden()` auto-retries and structurally cannot see a ~100ms flash |

### §8.4 holistic review — it found a merge blocker

Two reviewers looked only for defects in the **interaction** between the
landed fixes. Both independently found the same one, and it is the single
most important thing on this page.

**#122 × #123 deadlocked: a fully recovered store 402'd forever.** Neither
per-issue review could see it — #122 owns the trust predicate, #123 owns the
reopen trigger, so each pass saw half. Reproduced against a real SQLite
RESERVED lock:

```
fault begins        health=failing    lost=1  stale=True   flag=False
after reopen        health=unverified lost=0  stale=False  flag=True
new handle loses 1  health=failing    lost=1  stale=True   flag=True
OPERATOR FIXES IT   health=ok         lost=1  stale=False  flag=True
+5 more requests    health=ok         lost=1  stale=False  flag=True
```

`lost_billed_writes` is monotonic per handle, so once the reopened handle
lost a charge it could never become trustworthy; the clear-path needed
`trustworthy`, and the reopen that would supply a clean handle needed
`stale`, which recovery had just cleared. **Every priced request 402'd until
a process restart** — reintroducing the exact "no way back short of a
restart" that #123 exists to remove, via its own sibling fix.

The mistake was mine: I used `lost_billed_writes` — a **completeness**
signal, permanently true once anything is lost — to answer a **liveness**
question. Fixed by also retrying while `flag and not trustworthy`.

A **second path into the same wedge**: `_spawn` swallows a thread-start
failure while the cooldown is already stamped, and the flag is set *inside*
the reopen body, which never runs. Measured with `Thread.start` raising (real
container thread exhaustion): **25 of 25 requests allowed** against a frozen
ledger, `daily_spend_for` consulted zero times. Now recorded as a tried
reopen — for the feedback store only.

Two more of my claims were false where they stood, corrected in place:
`store_reconnect.py` said *"No permanent block"* (it was permanent), and the
operator ERROR said *"the block clears itself on the next write that lands"*
(in the wedge, writes **were** landing and it did not clear). The 402 reason
also said the cap *"for this account"* could not be verified — the store is
global, so one account's fault blocks everyone; it now says so.

Ruled out by the same pass, with evidence: #122 × #155 precedence (422 before
402, `/warnings` stays reachable and correct while the cap blocks — no
unbreakable loop), #122 × #117, `/estimate` as a #155 evasion route, ReDoS /
amplification on the new request-path regexes (≤1 ms at max accepted sizes),
import cycles, and all four e2e floor numbers verified by `--list` per lane.

### Gates, re-run fresh after the holistic fixes

- `make quality` — **2272 passed**, 25 skipped; ruff + mypy clean
- `make validate`, `make openapi-check`, `make api-contract` (43, floor 22),
  `make security-scan` (1313 files, 0 findings) — all green
- `make diff-cover DIFF_BASE=origin/main` — **100%, 172 changed lines**, all 8
  changed `src/` files present
- Full e2e (invariants + ops + degraded) — **197 passed, 8 failed**; all 8 are
  the Linux-seeded visual baselines that cannot pass on macOS. Verified on the
  **unchanged** tree that the same 8 fail there too. **Zero non-visual failures.**

---

## Held — ready, but must not merge without an operator action

**#193 — source-support denominator** (PR #236)
Renders `75% (3 of 4 answers)` instead of a bare `75%`. Held under §5.1:
`visual-snapshots.spec.ts` screenshots the result view with `fullPage: true`,
so this text change moves `result-verdict.png`, and only an operator can
reseed baselines.
**Needs:** run `seed-visual-baselines.yml`, review the PNGs, merge, re-run the
e2e lane.
Checked rather than assumed: the card renders into `#result-trust`, *not* the
`#result-trust-score` element the trust-score baselines snapshot — so those 6
are expected unaffected.

**#222 — landing mobile density** (PR #238)
Two real improvements are ready; the issue's goal is not robustly met, and the
decision is a design one. **Your call, three options in the PR.**
- Delivered: the CTAs were **100% covered** by the fixed session-trail panel
  (a real click hit the trail and did nothing) — now 0%. Page density 830 → 660.
- Not delivered: the fold holds *only* at 390×664 with default text. It fails
  at 375×667, 360×640, 320×568, 390×600, at an 18px user font, and with the
  font CDN blocked.
- Why it isn't a formality: that fold assertion sits in a **blocking** lane
  with 4px of slack and a dependency on `fonts.googleapis.com`. A CDN outage
  would redden a merge gate for reasons unrelated to any diff.

---

## Dropped

**#180 — consensus reads "strong, 4/4" on shared boilerplate** (PR #239)
Fourth attempt; did not clear review, so it was stopped per §7.4 rather than
guessed at a fifth time. Branch pushed with findings recorded, **not merged**,
issue stays open.

Two independent reviews established, by execution:
1. **The premise is false for the code being changed.** `_excerpt` clusters
   `InitialModelAnswer.answer_text`. The caveat is mandated for the synthesis
   *recommendation* (`synthesis.py:1070`, `:1079-1080`); the initial-answer
   prompt mandates nothing — `grep -c "decision support" providers.py` → **0**.
2. **The reachable instance is untouched.** `_local_simulation_text` returns
   text identical across slots but for the model id. Measured on the real
   method: pair Jaccard **0.541** vs a 0.1 threshold, strong overlap True.
   **Four models that were never invoked read as "strong consensus, 4 of 4
   aligned"** — on every deployment with live execution off. That is where the
   next attempt should start.
3. **The strip is evadable** where it would matter: no trailing period, ending
   `!`, or continuing past "advice" all restore the false positive.

---

## Corrections — claims of mine that review proved wrong

Recorded because the pattern matters more than any single fix: **three
consecutive PRs had a first implementation that was wrong in a way only
execution caught.**

- **#122, my fix didn't fix the issue.** `FeedbackStore.from_env()` on an
  already-migrated database attempts zero writes, so it opens *without
  raising* against a still-read-only volume. Keying on "did the reopen raise"
  cleared the flag on a reopen that fixed nothing — the BLOCK could never fire
  for the exact fault shape #122 exists for.
- **#122 again**, round 2: I gated recovery on `write_health()`, which
  `feedback_store` documents *in capitals* as **not the money signal** — a
  landed telemetry write re-stamps success over a lost charge. Now also
  requires `lost_billed_writes() == 0`.
- **#155**, my caveat stripper was broken 4 attempts out of 4. A greedy
  `[^.!?]*` ran backwards over hostile text in the same sentence, deleting
  every high-stakes word — a *cleaner* bypass than the one being fixed. My own
  test missed it because its payload didn't end in `advice.`
- **#117**, twice: a throw in `boot()`'s unguarded region left the disclosure
  permanently hidden; and `api()` has no timeout, so a hung probe suppressed it
  forever. Both traded a cosmetic flash for a silent safety failure.
- **#155**, a false claim in my own comment: "the verbatim sentence is the
  guaranteed floor… covered exactly" — false on the truncation path, which
  drops the caveat's opening clause.
- **#222**: three CSS declarations I added were **inert** (0px at every width);
  and I wrote that the old h1 clamp "responded to CONTAINER width" — it was
  `clamp(2.2rem, 5vw, 3.25rem)`, and `5vw` is viewport width.
- **#180**: I labelled a synthetic injection **MEASURED**, quoted `0.267` as a
  Jaccard when it was containment, and cited "1,836 attack attempts" — a
  reviewer's report that exists nowhere in this repo. A citation is not a check.
- **#122 × #123**, at §8.4: the deadlock above, plus two shipped comments that
  asserted the opposite of what the code did.

The pattern is the point: **five of the nine landed issues had a first
implementation that was wrong, and every one was caught by executing the code
rather than reading it.** Four of those five were on the money or safety
paths. Where a reviewer disagreed with me, the reviewer was right every time.

---

## Discovered but out of scope — not filed, per rule 19

1. **Four simulated answers read as "strong consensus, 4 of 4 aligned."**
   Jaccard 0.541. Live on every offline deployment. Same defect class as #180
   and strictly more reachable. **The most valuable item here.**
2. **#122's 402 tells the user the wrong cause.** `app.js` renders "Over the
   hard cap — this run won't start" and a `$0.25` note for a *storage* fault.
   The issue itself called for new copy; it needs a discriminator field on
   `CostEstimate`, an OpenAPI change, UI branching and e2e — its own work
   package. **#122 should not be closed on this batch alone.**
3. **`connectedPillLabel()`** (`app.js:1048`) reads `window.LIVE_READINESS`
   directly and never re-evaluates, so on the same stale-seed race #117 fixes,
   the pill can say "local simulation" permanently on a healthy deployment.
4. **Turning `store_reconnect_enabled` off also disables #122's fail-closed
   cap.** A consequence of the confirmed policy ("block only after a reopen was
   tried"), documented on the setting rather than silently patched. Default is
   `True`.
5. **The e2e observer in `readiness-no-flash.spec.ts`** under-counts
   ancestor-driven visibility changes for the result-view CSS rule.
6. **Test-suite process-global churn (latent flake, green today).** The
   holistic review instrumented a full run: **47 real background reopen
   threads** and **35 global `configure()` installs**, three landing *between*
   tests. `conftest._reset_state` clears the cooldown stamps every test, which
   removes the 60s damper and lets a thread spawn per test. Green in both
   alphabetical and shuffled order; unguarded, not broken.
7. **Local-testing trap, cost a diagnosis:** `/ui` starts returning **429**
   once repeated local e2e runs poison the durable per-IP daily session-mint
   cap. It presents as ~12 unrelated spec failures and a webServer timeout.
   Clearing the gitignored `.data/feedback_events.sqlite3` fixes it.

---

## What I need from you

1. Run `/code-review ultra` against `feature/major-issues-batch`.
2. Decide **#222** (PR #238) — merge with the fold test demoted, merge as-is,
   or hold for a landing redesign.
3. Decide **#193** (PR #236) — reseed visual baselines, then merge.
4. Nothing is merged to `main` and nothing is deployed.


---

## Addendum — the process work that followed (2026-08-03)

The batch closed, and the review of *how* it went produced more than the batch
did. Recorded here because the pattern matters more than any single fix.

**Five of the nine landed issues had a first implementation that was wrong**,
four of them on the money or safety paths. Every one was caught by executing
the code, never by reading it. Where a reviewer disagreed with me, the reviewer
was right every time.

**Root cause, named precisely by review:** every defect was a signal whose
subject, timescale or monotonicity did not match the question, composed with
booleans as if commensurable. I added a *term* to an expression where I should
have added a *row* to a table — which is why each fix revealed the next.

**What was already there and unused:** `docs/adr/`, the ADR index, and a
`architecture-and-decisions` skill. The batch made ~6 decisions and recorded
zero. ADR-0002 pinned the exact SQLite constraint the money work then reasoned
on top of without re-reading.

### Now mechanical

| Gate | Bridges | Bite-proof |
|---|---|---|
| `test_adr_index_matches_directory.py` | index rotted by hand twice | deleting a row turns 2 of 3 red |
| `test_risk_constant_pins.py` (extended) | the state-bearing modules were unlisted | surfaced 25 untriaged constants |
| `test_spend_cap_state_table.py` | 6 defects, 3 of them dead ends | found the 6th itself, in hours-old code |
| `test_cited_paths_resolve.py` | 38 of 1,352 citations unresolved | a phantom path turns it red |
| `test_gates_carry_a_charter.py` | a gate whose rationale is lost | "WHEN TO REMOVE: never" is rejected |

Plus ADRs 0004–0007, AGENTS.md rules 11a / 16d / 16e, and three memory entries.

### Honest limits, stated rather than discovered later

- The ADR-index gate would have caught **zero** of the 6 missing ADRs.
- `"MEASURED: 0.267"` is **not** mechanically catchable — no tool anywhere
  flags an unverified claim in prose. The defence is provenance plus review.
- The charter check verifies sections are **present**, not honest.
- **No gate records its own yield.** You cannot yet tell one that saved you
  three times from one that has never fired — and that is the data that should
  drive removal.
