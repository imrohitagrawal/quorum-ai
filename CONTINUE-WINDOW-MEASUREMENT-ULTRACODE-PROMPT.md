# CONTINUE — the clipped-critique defect, then the window's measurements

**Written 2026-09-03 by the session that merged #290, ADR-0096 and ADR-0097.**
Executable procedure. Read `AGENTS.md` first — it overrides everything here.

**THIS IS THE CURRENT PROMPT.** It supersedes two earlier ones, both of which
describe work that is now MERGED and would send you to build it again:

- `docs/archive/2026-09/CONTINUE-290-W3-ULTRACODE-PROMPT.md` — #290 peer
  critique, built and merged 2026-09-03 (`5aed777`, `5d53f16`, `6d13643`).
- `docs/archive/2026-09/CONTINUE-402-290-ULTRACODE-PROMPT.md` — #402 and #290,
  both closed.

If you find either of those at the repo ROOT again, something restored a stale
file — prefer this one and say so.

---

## THE ORDER IS AN OWNER DECISION, NOT A SUGGESTION

Recorded 2026-09-03, then REVISED the same day when the owner opened the running
product and found it describing a product that no longer exists. The revised
sequence:

0. **Item 0 — the UI tells users things that are FALSE.** First, and it is three
   separate PRs. Added after the owner observed it live. See below.
1. **Item 1 — the clipped-critique defect.** No spend, no further approval.
2. **Item 2 Phase 0 — the harvest harness.** Hermetic, `$0`. Validated against
   SIMULATED runs BEFORE any money is spent.
3. **Item 2 Phases 1-2 — the paid runs.** Authorised (budget note below).
4. **Item 3 — W3**, but verify the deferral premise first.
5. **Item 4 — the gate gaps.**

**Do not reorder this without saying why.** The ranking argument is at the
bottom of this file; if you find it false, rule 3 applies — STOP and say so.

### The paid-run budget, precisely

The owner's "go ahead" answered a message that quantified the spend as
**roughly `$0.50` total**, for a specific shape: **one validation run, then three
runs with varied question shapes.** Treat that as authorised, and only that:

- **Authorised:** up to `$0.50`, 1 + 3 runs, during the open window.
- **NOT authorised without a fresh go:** more runs, a bigger budget, or a
  materially different cost per run than the `~$0.06` typical / `$0.13` worst
  case measured on 2026-09-03. If `/estimate` disagrees with those figures,
  STOP and report before spending.
- Hard rails that bind regardless: `DAILY_CAP_USD = 0.20` per account per 24h,
  `GLOBAL_DAILY_CEILING_USD = 5.00`.

---

## RULE ZERO: THIS DOCUMENT IS A CLAIM, NOT A FACT

This repo has MEASURED the decay rate of handoff documents: **2 of 3** headline
findings refuted outright, **8 of 18** "would be lost outright" candidates
already done, already filed, or largely wrong. Roughly half of what a handoff
asserts does not survive contact with the tree.

So: **re-verify every numbered claim below before acting on it.** Each one names
the command that settles it. If a premise turns out false, AGENTS.md rule 3
applies — STOP and say so; do not repair it silently and carry on.

The session that wrote this made that exact mistake twice in one hour and caught
both by running a command. Assume you will too.

---

## THE AUTHORISATION CHANGE — read this before you ship anything

The product owner **explicitly overrode AGENTS.md rule 17b on 2026-09-03**:

> "My current verdict overrides and overrules 17b. You have the explicit
> approval to push, open a PR, merge, and deploy, provided everything has been
> properly tested, reviewed, and is successful, and CI gates are passing
> successfully."

**You may push, open a PR, merge and deploy without asking again.** But the
condition is load-bearing, and "CI gates are passing" is NOT sufficient on its
own — measured on 2026-09-03, on PR #433:

- All six required contexts were SUCCESS.
- `diff-cover` reported `Coverage: 100%` having measured **ZERO** executable
  lines ("NONE of their changed lines are executable statements").
- The mutation gate reported **green** having measured **ZERO** functions
  ("this job is green because there was nothing in scope, not because anything
  was measured").
- An earlier revision of that same PR passed every gate while telling operators
  "live execution is off" on a branch that had read nothing at all.

**So the bar you must clear before merging is:**

1. All six required contexts SUCCESS — re-derive the list, never trust a table:
   `gh api repos/:owner/:repo/branches/main/protection --jq '.required_status_checks.contexts[]'`
2. **Open every advisory log and find the number.** A green advisory job is not
   evidence it ran; a RED one is not evidence it measured. If a gate measured
   nothing, say so out loud and treat the mutation proof as the evidence.
3. Adversarial review fanned out, findings reproduced, blockers resolved.
   Expect your own fix to introduce a defect — it did twice on 2026-09-03.
4. A mutation proof with a STATED BASELINE, enumerated in a committed file so a
   reviewer can re-run it. See
   `scripts/proofs/peer_critique_visibility_mutations.py` for the shape; a count
   nobody can re-run was correctly rejected by a reviewer on that PR.
5. After merge: verify the deploy **JOB** (not the run rollup — one merge yields
   several runs and most are cancelled), `/status.build_sha` == the merge SHA,
   and that the thing you built actually fires.

**What the override does NOT cover** — do not assume either:
- **Paid production runs.** Money spend is a separate decision. Ask.
- **The window re-affirmation.** GitHub types workflow tokens as `Bot` and the
  check refuses them. A human account must post it (see below).

---

## VERIFIED STATE AS OF 2026-09-03 ~14:20 UTC

Each line names how it was verified. Re-run these first; they are cheap.

| Fact | Value | Command |
|---|---|---|
| `main` | `1b13767`, 0 ahead / 0 behind | `git rev-list --left-right --count main...origin/main` |
| production build | `1b13767…` == main's tip | `curl -s https://quorum-ai.fly.dev/status` |
| live execution | `true` | same |
| peer critique | `true` (NEW — ADR-0097 put it on `/status`) | same |
| judge | `true` | same |
| live runs inside this window | **ZERO** | `last_live_charge_at` = `2026-09-01T21:02:46Z`, BEFORE the window opened `2026-09-03T07:51:25Z` |
| spend so far | `global_daily_spend_usd = 0` | same |
| window expires | `2026-09-08T07:51:25Z` | `configs/live-execution-windows.json` |
| re-affirmed | once, `2026-09-03T14:10Z`, by `imrohitagrawal` | `uv run python scripts/live_posture_check.py` → `1 human re-affirmation(s)` |
| watchdog | quiet, `decision=live_within_declared_window`, EXIT=0 | same |
| `e2e/node_modules` | **DELETED** — restore with `cd e2e && npm ci` if you touch UI/specs | — |
| `.venv` | kept and working | `QUORUM_TOKEN_SECRET=x uv run pytest <path> -q --no-cov` |

**Deliberately NOT verified by that session, and still open:** the operational
angle (what the watchdog does against a rolled-back build; the extra `/status`
fetch's retry budget during an outage), performance, and **no human has read the
#433 diff.**

---

## ITEM 0 — THE UI TELLS USERS THINGS THAT ARE FALSE

Found 2026-09-03 by the OWNER, opening the running product, after this session
had turned peer critique on in production and shipped ADR-0096 without
retiring the copy that described the old shape. Two read-only audit agents then
swept ~130 claim-bearing strings; ~110 were true. These are the ones that are
not. **Every `file:line` below was read from disk — but they are claims, and
Rule Zero applies: re-verify before acting.**

### THE STRUCTURAL PROBLEM — read this before touching a single string

**Five test files ASSERT THE FALSE STATE and go RED when the bug is FIXED.**
That is the anti-pattern `AGENTS.md` forbids in its own words — *"Never write a
check that goes red when the bug is FIXED — that locks in the defect"* — and it
is why nothing went red when the flag flipped at 07:51 that morning.

| Gate | What it locks in |
|---|---|
| `e2e/tests/invariants/landing-cta-reachable.spec.ts` | pins the landing subhead BYTE-EXACT (`:209`), requires `"moderator model"` (`:213`, `:233`), requires `"planned, not yet built"` (`:274`), and **forbids 7 phrasings** of what the product now does (`:239-248`) — `"critique each other"`, `"revise its answer"`, … |
| `tests/unit/test_ui_honesty.py` | asserts in prose that *"the four answer models … never read one another. Real peer critique is #290 and is NOT built"*; `BANNED_EXCHANGE_CLAIMS` bans `"peer critique"`, `"each other"`, `"one another"`. Its failure message tells the engineer a falsehood. |
| `tests/integration/test_workspace_html_copy.py` | requires the FALSE caveat *"Templated by Quorum; no model generates this"* to be present, ×5 |
| `e2e/tests/invariants/trust-score-invariants.spec.ts:57` | pins the false "citation support was checked" sentence verbatim |
| `tests/integration/test_cost_gate_js.py:150` | pins `labels[4] == "Synthesis"` |

**Each fix must invert its own pinning gate IN THE SAME COMMIT**, with a
positive partner proving the OTHER shape still reads correctly — the pattern
`e2e/tests/invariants/peer-critique-copy.spec.ts:77-85` already gets right.

**ADR-0032 is still `Accepted` and is the decision that MANDATES the moderator
copy.** ADR-0093/0095/0096 each explicitly decline to retire it. Rule 16d: the
copy fix needs its own ADR superseding ADR-0032 (and ADR-0063's caption clause).

### PR A — the false EVIDENCE claims. Highest value. Do this one first.

**A1. `app.js:3891` — FALSE, and it gates the trust number.**
> *"Citation support was **checked** by an independent judge model — an
> automated review, not a human fact-check."*

It unlocks the numeric trust score and its low/moderate/high band
(`app.js:3988-4005`, gated on `trust.support_verified === true`). The judge is
ON in production.

Verified by command: the judge's evidence block is built at
`evaluation.py:1729-1732` as `f"[{i}] {title} :: {url}"` — **titles and URLs
only, no page content** — and **nothing in `src/` resolves a cited URL** (the
only `urlopen` call sites are the model catalog, the key probe, the provider
call, Tavily search and the feedback audit). So the judge is asked *"does the
answer assert only what its cited evidence supports?"* (`evaluation.py:1762`)
about evidence it has never seen.

This is L3 wording on L1 data, which **ADR-0096 Decision 1 forbids in those
words**: *"No UI copy may imply otherwise."* The product already owns the honest
sentence and uses it on the other branch — `app.js:3885` and `app.js:3914`
(*"citations were not verified against their sources"*), both TRUE.

**A2. The source classification is INVERTED.**
- a URL scraped out of the model's own prose (`providers.py:3465`,
  `_INLINE_MARKDOWN_LINK_RE`) → `is_fallback=False` → clickable, **counted in
  citation coverage** (`providers.py:759`), presented as a primary source
- a real Tavily web-search result (`providers.py:3266`) → `is_fallback=True` →
  badged `"fallback stub"` (`app.js:3345`), forced non-clickable
  (`app.js:3323-3325`), exported as **`"fallback stub, not a real source"`**
  (`app.js:3097-3098`)

So a URL a model may have hallucinated counts toward the coverage percentage the
verdict band leans on, and a genuinely retrieved page does not.

**UNVERIFIED, and it decides whether A2's Tavily half is live or latent:**
is `TAVILY_API_KEY` set in production? It is a Fly secret, absent from
`fly.toml`, unreported on `/status`. Settling command:
`fly secrets list -a quorum-ai | grep -i TAVILY`. **Ask the owner** — it needs
their `fly` auth.

### PR B — the MECHANISM copy. The landing page is the front door.

| Where | String | Pinned? |
|---|---|---|
| `workspace.html:760` | *"A moderator model audits them over two rounds"* — no moderator runs | **YES, byte-exact, blocking lane** |
| `workspace.html:840` | *"Peer critique between the four models is planned, not yet built"* — it is built, enabled and billed | **YES, blocking lane** |
| `workspace.html:488-489` | *"Per-model debate detail is **not captured**."* — it IS captured and the user is billed a `(critique)` row per critic. **Visible on EVERY run** (`data-view="live-run"`) | **NO — free to fix. Start here.** |
| `app.js:4598`, `:4957` | *"Each answer model critiqued the others, **in both rounds**."* — over-asserts; 3 reachable false states (skipped round 2 `debate.py:1052-1073`; per-round shape; `_eligible_critics` can leave one critic) | pin is `/critiqued the others/i` — a count-aware rewrite stays green. `eligible_critic_count` is already served (`openapi.yaml:620`) and read **nowhere** in `app.js` |
| `app.js:3242` | *"from the four refined answers"* — unconditional; `revised_answers` comes only from live critics | no |
| live-run card | `Focus: disagreement, weak_support, missing_reasoning` — `FOCUS_AREAS` (`debate.py:92`), a module constant stamped on BOTH rounds, now stale against ADR-0096's rewritten lenses. The result view already suppresses it (`app.js:4612`); the live view does not | no |

**Also `app.js:5004`** — `"Panel divided"` is the bare `else` of `isConsensus`,
so it fires on *undetermined* too (no debate, templated round, cancelled run,
fully simulated). This is the #247 defect `mayClaimDisagreement` closed for the
band and the export; the transcript chip never got the guard. Unpinned.

**ADR-0096 Decision 5 has NO implementation:** an evidenced `held_solution` must
prevent an unqualified consensus claim. Nothing does — a 3-of-4 majority paints
the green band while the fourth critic's *"Held its position"* pill renders on
the same page.

### PR C — the MONEY attribution

- **`costs.py:1541`/`:1548`** — the estimate's `Synthesis` row is
  `2 × debate_round_cost + synthesis_cost`, and `debate_round_cost`
  (`costs.py:1780`) is a **sum over all four slot models**. So on the approval
  screen the row named `Synthesis` holds every critique dollar and the four slot
  rows hold none. ADR-0093 decision 3 fixed this on the MEASURED path only.
  ADR-0095:198-204 already records the gap and says the resolution is **an
  estimate-side note in the UI, not a rename** — it explicitly rejects a
  shape-dependent label.
- **`app.js:4344`** — `"Cost by model · est → actual"` pairs those two
  differently-shaped rows, so the receipt reads *"Synthesis $0.052 → $0.035"*,
  which looks like a saving when the money merely moved.
- **`workspace.html:286`** — *"may be 10–30% higher or lower"*. Contradicted by
  this repo's own numbers: a live actual of `$0.0767` against a `$0.0329`
  estimate (**+133%**), and ADR-0094 measuring 6 of 6 debate calls exceeding
  priced output by 1.68x–4.40x. Unpinned.

### NOT user-visible — do not "fix", DELETE

`.panel.panel-section { display: none }` (`app.css:653-656`, unconditional)
hides `#model-grid`, `#debate-output` and `#synthesis-output`. Four false
moderator claims live in there (`app.js:5441`, `workspace.html:931`, `:939`,
`:951`). Harmless today, a landmine if that panel is ever un-hidden. Delete the
dead markup **and its pinning test** rather than rewording.

### One correction for AGENTS.md while you are here

`AGENTS.md:649` cites the degraded-banner condition at `app.js:2297`. At HEAD it
is `app.js:2700-2701`. The quoted condition is right; the line number is stale.

---

## ITEM 1 — THE CLIPPED-CRITIQUE DEFECT

**Claim (MEASURED, per ADR-0093):** the #290 probe found **seven of eight**
critique calls returning `finish_reason: "length"` — the `2000`-token cap
genuinely reached and the reply clipped. Full price for a truncated critique, on
a receipt that looks healthy.

**Verify before acting:**
```bash
grep -n "DEBATE_ROUND_MAX_TOKENS" src/product_app/debate.py     # expect 2000, line ~76
sed -n '325,335p' docs/adr/0093-a-peer-critique-nests-inside-its-round-and-a-critics-spend-gets-its-own-row.md
```

**THE TRAP — there are TWO unrelated "seven of eight" figures in this repo.**
One is `finish_reason: "length"` (this item). The other, in
`docs/analysis/2026-08-26-b3-timeout-probe.md:87`, counts **wall-clock timeout
exceedance** and has nothing to do with token caps. ADR-0093 says so explicitly
because a prior session nearly merged them; the session writing this DID
conflate them, and caught it only by grepping. Do not cite one for the other.

**Why this is now worse than measured, and why it is item 1:** ADR-0096 (merged
2026-09-03, `6d13643`) made round 2's reply LONGER — it now returns a critique
*and* a self-assessment, rationale, cited sources and a **revised answer**. And
`synthesis` reads those revised answers as its PRIMARY input. So the part most
likely to be clipped off the tail is the source-backed answer the product owner
specifically asked to be protected:

> "the main focus should be on the source-backed answers... Nothing should be
> cooked or hallucinated."

A clipped revised answer is silently truncated evidence reaching the user's
final answer, at full price. **This is live in production right now.**

**What to do:**
1. Measure the real thing, do not guess a number: what is the actual token
   length of a round-2 reply under ADR-0096's prompts? `debate.py` has
   `debate_system_prompt_max_chars(peer=True)` (=3695 chars) for the prompt
   side; the OUTPUT side is what the cap bounds and what needs measuring.
2. Raising a cap raises cost, and cost is bounded by ADR-0094's held constants
   and by `_estimate_bound_usd`, which MUST remain a TRUE CEILING. Check what
   moves before you move it — `tests/unit/test_peer_bound_is_a_true_ceiling.py`
   pins the arithmetic with literals on both sides.
3. A pinned number may be a PUBLISHED REQUIREMENT. A prior session found one
   bound written into 21 files, and the run deadline is NFR-001/AC-021 in six
   places including the operator dashboard. `grep` the value before changing it.
4. **A decision gets an ADR in the same PR** (rule 16d), and
   `python3 scripts/generate_adr_index.py` regenerates the index — never
   hand-edit it. **Next free ADR number: check `ls docs/adr/ | tail`; 0097 is
   taken.**

---

## ITEM 2 — THE WINDOW'S REMAINING MEASUREMENTS

The window (`configs/live-execution-windows.json`) was opened for THREE things.
Read its own `reason` field for the canonical list. Status as of writing:

1. **What eight critique calls actually cost** — NOT measured. Needs a real
   paid run. W3/ADR-0094 is blocked on it.
2. **Whether `DEBATE_ROUND_MAX_TOKENS=2000` still fits** — a measurement
   EXISTS (item 1: 7 of 8 clipped) and is now stale in the pessimistic
   direction, because ADR-0096 lengthened the reply. Re-measure under the
   current prompts.
3. **Whether OpenRouter's `:online` annotations carry passage CONTENT** —
   NOT measured. It decides whether L2 source verification (does the cited URL
   resolve? does it support the claim?) is possible without new fetches. Today
   the product is **L1**: a source was CITED, nothing is resolved or verified.

**THE STRUCTURAL RISK — this is the thing to get right.** The window has been
open with live execution, peer critique AND the judge all `true`, and has
measured NOTHING because nobody executed a query. This repo's single
most-repeated failure is exactly that: a gate or window reaching a terminal
state having measured nothing (13 of 21 CI jobs could do it, four of them
blocking; one CI gate ran green ~7 days while aborting before it measured).

**Do it in this order, and do not invert it:**
- **Phase 0 — hermetic, $0, FIRST.** Establish where each signal lands and
  write the harvest script. `TELEMETRY_LOG_DIR = "/data"` in `fly.toml`, mounted
  from volume `quorum_data`. `src/product_app/telemetry_sink.py` defines
  `TELEMETRY_FIELD_NAMES`, which as of ADR-0093 decision 5 includes
  `query_run_id`, `stage`, `slot_number` and `finish_reason` — the correlator
  that makes a critique row attributable at all. Validate the harvester against
  SIMULATED runs, which cost nothing.
  **Rationale: if you spend money first and the sink does not capture what you
  need, the money is gone and the window is not repeatable.**
- **Phase 1 — ONE deliberate live run.** Confirm end to end that all three
  signals were captured. Measured exposure: roughly `$0.06` typical, `$0.13`
  worst case (a reviewer drove `/estimate` on 2026-09-03: flag off →
  `max_cost_usd 0.1043`, flag on → `0.1286`).
- **Phase 2 — 3 runs, VARIED question shapes.** The #268 window's own write-up
  says n=8 sharing one query is "a start, not a bound". One shape will not do.
  The binding constraint is not money but `DAILY_CAP_USD = 0.20` per account per
  24h — about 3 runs/account/day.
- **Phase 3 — publish the numbers**, then unblock W3.

**Money spend needs the owner's explicit go.** The 17b override does not cover
it.

---

## ITEM 3 — W3, THE MONEY CONSTANTS

**Verify the premise first — it may not be merely "blocked".**
`docs/65-open-work.md:205` says: *"W3 — the money constants. STOP, and DEFERRED
by decision (ADR-0081). The product owner decided 2026-08-28: the three
constants do not move until..."* — **read the rest of that sentence and
ADR-0081 before treating W3 as available work.** A deferral by owner decision is
not the same as a blocker you may clear yourself.

Constants and their current values live in `costs.py`; ADR-0094 records what is
held and why. `SOFT_THRESHOLD_USD=0.15`, `HARD_LIMIT_USD=0.25`,
`DAILY_CAP_USD=0.20`, `GLOBAL_DAILY_CEILING_USD=5.00` — grep each before
changing it; they appear in many files and some are published requirements.

---

## ITEM 4 — THE GATE GAPS (found 2026-09-03, NOT filed, NOT verified by a second pass)

These were surfaced by the #433 review and are UNVERIFIED claims. Verify, then
decide whether to file or build. Rule 19: close more than you open.

1. **No coverage or mutation gate looks at `scripts/`.** CI runs `--cov=src`.
   `scripts/live_posture_check.py` is roughly 1700 lines of money-watchdog logic
   with, apparently, zero gate coverage. Also `scripts/security_scan.py`,
   `scripts/close_live_window.py`. **Verify:** read the Makefile's coverage
   invocation and the `mutation-baseline` scope, and count Python lines under
   `scripts/`.
2. **"Measured nothing" exits 0.** Both `diff-cover` and the mutation gate print
   an honest blind-spot notice and then exit 0, so a human must open the log.
   That is the #130/#158 failure mode still live in two gates. Making it a
   distinct or failing status is a small change with real yield.
3. **Nothing requires a totality test** (enumerating every branch/decision) for
   money or safety code. The #433 defect was exactly this: a note reached 6 of
   12 return sites while a comment claimed "every".

**Before adding any gate**, measure its yield against real defect history and
state what it cannot see: **0 of 16** `src/` defects were caught by an automated
check; **10 of 16** by adversarial review
(`docs/metrics/defect-discovery-audit.md`).

---

## ITEM 5 — OTHER OPEN ISSUES

`#268` (max_cost_usd bounds output but nothing bounds input) and `#105` (5xx
classified as possibly-billed on a premise with no evidence). Both untouched on
2026-09-03. Enumerate the real list yourself:
`gh issue list --state open --limit 100`.

Rule 17g: check whether several open issues are the SAME concern before
selecting a work package — but rule 17 still binds, one CONCERN per PR.

---

## WHAT NEEDS THE HUMAN, EVERY TIME

1. **Re-affirm the window every 24 hours** until `2026-09-08T07:51:25Z`. Last
   re-affirmation `2026-09-03T14:10Z`, so the next is due by `2026-09-04T14:10Z`.
   Comment on issue **#290**, the token must START the line:
   ```
   REAFFIRM live-execution 2026-09-03T07:51:25Z
   ```
   Quote the window's own `opened_at`, not today's date. If `gh` is
   authenticated as `imrohitagrawal` (`gh api user --jq .type` → `User`, not
   `Bot`) the owner has previously authorised posting it on their behalf — but
   confirm that authorisation still stands rather than assuming it.
   If it lapses, the watchdog alerts and the window stops sanctioning the live
   posture.
2. **Any paid production run.**
3. **Closing the window** on 2026-09-08: `make close-window`. It performs BOTH
   edits atomically (flag → false AND the open window's `expires_at` → now).
   The obvious one-edit revert is REFUSED — #407 is a window that outlived its
   expiry by ~8.6 hours because that two-part edit was not made under pressure.

---

## TRAPS THIS SESSION PAID FOR — read before you run anything

- **Never read a gate's exit status through a pipe.** `make X 2>&1 | tail`
  reports *tail's* status. Use
  `make X > /tmp/gate.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/gate.log`.
- **A mutation harness that string-matches source must assert its anchor is
  UNIQUE.** `text = "" if live is None` occurs THREE times in `debate.py`; a
  harness anchored on the first hit mutated the moderator path and reported
  **3 false survivors**, which reads as "your tests are decoration". It nearly
  cost three correct tests. `scripts/proofs/peer_critique_visibility_mutations.py`
  refuses to report if `count != 1` — keep that guard.
- **`make format` breaks those anchors.** It collapsed a condition onto one line
  and invalidated an anchor mid-proof. Re-run the proof AFTER formatting.
- **A surviving mutant may be EQUIVALENT, not a missing test.** Seven survivors
  on `debate_system_prompt_max_chars` were proved equivalent by computing the
  function under each mutant's iteration set (the directive is 152 chars in
  round 1 and 1106 in round 2 for EVERY slot 0..5). Do not restructure correct
  code to silence a gate — pin the invariant instead. See
  `tests/unit/test_peer_critique_reply_gates.py`.
- **Never move the tree under a running reader** (rule 9a). A read-only agent
  that runs the suite gets its own `git archive HEAD | tar -x -C <dir>` copy.
  On 2026-09-03 a reviewer ran `uv run --python 3.12`, which DELETED and
  recreated `.venv` in the shared worktree, while another reviewer was reading.
  Telling reviewers "read-only" IN CAPITALS was not sufficient.
- **`uv run` in a fresh worktree needs `uv sync --all-extras` first**, or you get
  a 3.14 venv with no pytest and shell-out tests fail for environmental reasons.
- **`PYTHONPATH=src`** is needed for `uv run python -c "import product_app..."`.
  A bare import failing is NOT a broken venv — confirm with pytest.
- **`e2e/tests/review/` makes `make quality` RED locally and green in CI** — it
  is gitignored and holds 7 local scratch specs. Measured 2026-09-03: main's own
  suite is `7 failed` locally for exactly this reason. Before blaming your diff,
  run `ls e2e/tests/review/`.
- **The visual lane fails 8/8 on a Mac on clean `main`** and that is not a
  regression — darwin baselines are stale and CI compares linux. Never
  `--update-snapshots` to go green.
- **A subagent fan-out can return NOTHING.** On 2026-09-03 a 15-agent workflow
  lost all 9 dispatched agents to API 529 Overloaded and returned an empty
  result. Read `journal.jsonl` before diagnosing, and never report an inventory
  you did not receive.

---

## FIRST MOVE — run these before anything else

```bash
cd /Users/rohitagrawal/Projects/quorum-ai
git fetch -q origin && git rev-list --left-right --count main...origin/main   # expect 0  0
curl -s https://quorum-ai.fly.dev/status | python3 -m json.tool               # posture + build_sha
uv run python scripts/live_posture_check.py > /tmp/p.log 2>&1; echo "EXIT=$?"; cat /tmp/p.log
gh issue list --state open --limit 100
ls docs/adr/ | tail -3                                                         # next free ADR number
grep -n "DEBATE_ROUND_MAX_TOKENS" src/product_app/debate.py                    # Item 1's subject
```

Expected, so you can spot drift fast: `main` 0/0 at `1b13767` or later;
`build_sha` == main's tip; `live_execution`, `peer_critique_enabled` and
`judge_enabled` all `true`; watchdog EXIT=0 with
`decision=live_within_declared_window`; the cap still `2000`.

**If the watchdog exits 1**, deal with that before any feature work — it means
the live posture is unsanctioned or unattended, and that is money running
without cover.

Then work **Item 1** in a dedicated `git worktree` (rule 17a), on a branch, with
`main` merged in FIRST (rule 17), and open the PR with a one-line statement of
why it outranks the top of the backlog (rule 20).

## THE RANKING ARGUMENT — check it, do not inherit it

Item 1 goes first because:

- It is a **live** defect in production right now, not a latent one:
  `peer_critique_enabled = true`, cap unchanged at `2000`, and 7 of 8 critique
  calls were measured clipped.
- ADR-0096 (merged 2026-09-03) made it **worse** by lengthening round 2's reply,
  and `synthesis` now reads that reply's `revised_answer` as its PRIMARY input.
  So the truncated tail is the source-backed answer the owner asked to protect:
  *"the main focus should be on the source-backed answers... Nothing should be
  cooked or hallucinated."*
- It costs **nothing** to start — the measurement already exists, so it needs no
  window run and no spend.
- Everything else is worse-placed: W3 is owner-deferred (ADR-0081, verify), the
  window's cost number needs money, and the gate gaps have no deadline.

**The one thing that would overturn this ranking:** if the `finish_reason` 7/8
figure turns out to be the *timeout* 7/8 misremembered. It is not — they are two
distinct measurements and ADR-0093:327-332 says so explicitly — but the session
that wrote this file conflated them once and caught it only by grepping. Verify
it yourself before you build on it.
