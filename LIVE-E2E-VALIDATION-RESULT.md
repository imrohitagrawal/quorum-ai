# Live production validation — one paid run, then the whole product as a user sees it

**Session date:** 2026-08-05
**Production build:** `bc38bbb` (unchanged throughout — nothing was deployed)
**The one paid run:** `qr_415a22cb476c4ee3969ed6ed39f0f6bb`, 1m 18s, **actual $0.0767**

---

## Status

- **Pushed:** NO. Two commits on `fix/config-discoverability`, local only.
- **Merged:** NO. **Deployed:** NO. Production still runs `bc38bbb`.
- **The live run:** DONE, once, as approved. $0.0767 of real money.
- **Judge:** was enabled by the operator for a watched window, then unset.
  Confirmed off: `fly secrets list | grep -c JUDGE` → `0`.
- **Issues opened:** none (needs your approval).
- **Pending on you:** whether to push/PR/merge; whether to file the findings
  below as issues.

---

## Part 1 — What is wrong in production RIGHT NOW

Ranked by what a user or the business actually loses. All measured today
against `https://quorum-ai.fly.dev`, none previously reported.

### F-1. The spend ledger meters ESTIMATES and never reconciles to actuals

**Behaviour before/after:** unchanged — this is live and nothing was fixed.

The run cost **$0.0767**. The ledger recorded **$0.0329** — the estimate.
**57% of real spend is invisible to both spend rails.**

```
actual_cost_usd            0.0767      (cost_source: "measured")
/status.global_daily_spend_usd  0.0329  ← the estimate, not the actual
```

Not an accident of one run — it is structural, and the code says so:

- `query_runs._record_run_billing` writes
  `estimated_cost_usd=query_run.cost_estimate.estimated_cost_usd`, and its own
  docstring says that event "is the only event type the two spend guards
  (`_cumulative_spend_for` and `daily_spend_for`) count".
- `feedback_store.daily_spend_for` docstring: *"Sum the `estimated_cost_usd`
  from cost events… **The daily cap reads from here.**"*
- The measured actual **is** computed and persisted — to `run_history_store`,
  a different table the caps never read. There is no reconciliation write.

**What it costs you:** the hardcoded `$5.00`/day global ceiling does not bind
$5.00 of spend. At this run's ratio it would admit **~$11.60**. The per-account
24 h cap is under-enforced by the same mechanism.

**This is strictly bigger than #216.** #216 says the *judge's* cost misses the
ledger. In fact *every* run's real cost misses it; the judge is one term.

### F-2. The UI calls the point estimate a "spend cap", then bills 2.3× it

Verbatim from the screen, before the run:

> "The approved figure becomes this run's spend cap."
> "The run stops itself if spend would pass the approved figure."
> Button: **Run · $0.033**

Verbatim after:

> Completed · 1m 18s · actual **$0.077** (approved **$0.033**)

**The guardrail is not broken — the label is.** The bound that actually held is
`max_cost_usd = $0.0775`, and the actual $0.0767 came in at **99.0%** of it.
So the fail-safe worked with 1% to spare. But the number shown to the user, on
the button they press and in the sentence calling it a cap, is the *point
estimate*, which is not a cap and was exceeded by 133%.

**What a user loses:** they approved $0.033 and were charged $0.077. On a
larger run the same 2.3× applies to a bigger base.

### F-3. The estimator under-prices the debate rounds ~3.3×

| Stage | Estimated | Actual | Ratio |
|---|---:|---:|---:|
| initial answers | $0.0099 | $0.0201 | 2.0× |
| debate round 1 | $0.0054 | $0.0175 | **3.2×** |
| debate round 2 | $0.0054 | $0.0196 | **3.6×** |
| synthesis | $0.0122 | $0.0086 | 0.7× |
| judge | *(not priced)* | $0.0109 | — |
| **total** | **$0.0329** | **$0.0767** | **2.33×** |

Synthesis is over-priced; the debate rounds carry the error. `n=1`, so the
*ratio* is not a constant — but the direction is consistent across both rounds
and the mechanism in F-1 is structural regardless.

### F-4. The estimate does not price the judge at all

$0.0109 — **33% of the entire approved figure** — is unmodelled. With the judge
on, every run necessarily exceeds its approved figure by at least the judge's
cost. `.env.example` now warns about this; the estimator still does not.

### F-5. Raw Markdown reaches the screen — three distinct defects, 13 occurrences

This is the class the project keeps saying simulated data hides, and it did
again: `rendering-invariants.spec.ts` is green in CI and all 196 invariant
tests pass locally, because the golden fixture never produces these shapes.

**(a) `.result-pos-text` is not routed through the prose renderer.** The
"How positions moved" table's OPENING column shows, verbatim:

```
Claude Haiku 4.5 →  # PostgreSQL Scaling Decision for Your B2B SaaS Based on your
                    profile (40-person B2B SaaS, ~400M rows, write timeouts),
                    **you should not sha…
Nemotron 3 Nano  →  ## TL;DR | Option | When it makes sense | Rough effort & risk |
                    Typical cost impact | |--------|--------------------|---…
```

Per AGENTS.md a provider-text surface must go through `setProse`/
`setInlineProse`. This one does not.

**(b) Markdown TABLES are not rendered at all.** 8 paragraphs inside
`.q-prose` containers (which *are* the rendered surfaces) contain raw
`| --- |` table syntax. The page has exactly **1** `<table>` element and that
one is app chrome — **zero** model-emitted tables rendered as tables. My
question invited a cost comparison; two of four models answered with a table;
both render as an unreadable wall of pipes. Inline bold *inside* the cells
renders correctly, so this is specifically missing block-level table support.

**(c) Literal `<br>` shown as text** — 6 occurrences, e.g.
`"…just a host upgrade. <br>Risk: you may still hit the same timeout…"`.

**(d) Truncation severs a bold span.** One paragraph contains exactly **one**
unpaired `**` and ends mid-sentence ("…failure modes unique"), so the renderer
prints the orphan marker. Server-side truncation cuts inside the span.

*Not* found, i.e. these invariants held: **no horizontal overflow**
(`scrollWidth == clientWidth == 1440`), and the **elapsed timer is strictly
monotonic** (12 consecutive samples, +1s each).

### F-6. The judge cost $0.0109 and changed nothing the user can see

With the judge fully configured and a verdict produced, the served result still
had `band: "unverified"`, `score: null`, `support_verified: false`, and the
page still read *"Structural checks passed — citations were not verified
against their sources."* The user paid for a verification that the UI then
says did not happen.

### F-7. #216 is latent *in practice* on low traffic — a priority correction

Three repeated `GET`s of the same run returned `actual_cost_usd` = `0.0767`,
unchanged. The 512-entry memo held; no judge call refired. #216 needs **512
runs of churn or a process restart** to bite. Real, but not urgent on a
low-traffic deployment — worth recording, because nothing said so before.

### F-8. `.gitignore:44` is `e2e/node_modules/` and does not cover a symlink

The trailing slash matches a directory only. A symlink named `e2e/node_modules`
is *not* ignored, and `git add -A` commits it. This bit me during this session
(caught and amended out before any push). One-character fix.

---

## Part 2 — Handoff claims that did not survive execution

The handoff asked to be treated as unverified. It was right to.

| Claim | Measured |
|---|---|
| "e2e specs on disk **26**", via `find e2e/tests -name '*.spec.ts' \| wc -l` | That command prints **33**. 26 is the *tracked* count; 7 are the gitignored `e2e/tests/review/` scratch specs |
| Lane 2 is 6 specs, floor 96 | The list **omits `tests/ops/ops-navigation.spec.ts`** (`e2e.yml:255`). The 6 listed give **95** — one short of the floor. The real 7-spec lane gives **102** |
| `GET /feedback/audit` is a free probe | Returns `{"code":"AUTH_REQUIRED"}` without a browser session |
| 4th default model is `deepseek/deepseek-chat-v3.1` | Production serves **`nvidia/nemotron-3-nano-30b-a3b`** |
| Production key may need rotating | Not needed — `/ready` → `{"state":"live","reasons":[]}` before and after |

Confirmed true: 15 open issues; 6 required contexts; 5 pre-existing Fly
secrets; both Phase 0 gaps real; `.env.example` had 0 mentions of the judge and
0 of Tavily.

---

## Part 3 — What was built ($0, no keys, before any secret was touched)

Two local commits on `fix/config-discoverability`. **Not pushed.**

`3461369` — configuration discoverability. `.env.example` documented **19 of
44** `Settings` fields; four of the names it *did* document were read by
nothing. Both directions are now gated from `Settings.model_fields`.

The headline find here: **`ENVIRONMENT` was documented as "controls security
defaults and validation behavior" and is read by nothing.** The field is
`runtime_environment`, so the variable is `RUNTIME_ENVIRONMENT`, and
`extra="ignore"` discards the wrong name silently. Measured: a `.env` with
`ENVIRONMENT=production` yields `runtime_environment=local` and
`session_cookie_secure=False` — someone hardening a box from this file gets
local security defaults and `validate_production_environment()` never fires.
Production was never exposed (`fly.toml` sets both names); the exposure was
anyone configuring from `.env`. The other three dead knobs are the pre-#16 cost
model's, still carrying tuning advice for an estimator that no longer reads them.

`/status.judge_enabled` now reports the judge, computed by
`evaluation.judge_configured()` — the same predicate the run path gates on, so
the signal cannot drift from the behaviour. ADR-0013 records why #216's ledger
fix is deferred (it crosses ADR-0002's single-writer constraint on the
most-polled endpoint, and the attribution question is unanswered).

`b10f4af` — **the four holes two review lenses found in `3461369`.** Rule 12's
"expect your own fix to add a defect" held; the first commit's headline claim
was itself defeated:

- Tightening the pattern pinned the *pattern*, not the *file*. Reflowing the
  header's indentation re-opened the prose-vouching hole with every gate green.
- Part E2 vouched for any token anywhere in `src/` — so `DAILY_CAP_USD` and
  `GLOBAL_DAILY_CEILING_USD`, hardcoded constants, passed as documentable knobs.
- The loadability gate was silently vacuous for any field already in
  `os.environ` — including `OPENROUTER_LIVE_EXECUTION_ENABLED`.
- Nothing pinned the 40 documented values to the code's defaults.
- **"One predicate" was three copies.** `EvalJudgeService.evaluate`
  re-implemented the rule; deleting half of it was invisible to the entire
  suite. Now one predicate, and the new test asserts on the provider seam.

Seven false prose claims were corrected, all measured — including
"30/min" (it is 10/min), "makes no API call" (a cold catalog cache fetches),
and ADR-0013's "its contract test uses a superset check" (no test pins
`/status`'s keys at all).

**Gates:** 2410 passed, coverage 94.36%; `validate`, `api-contract`,
`openapi-check`, `security-scan`, `diff-cover` (100%, 5 lines) all exit 0.
e2e **351 passed** across all four lanes (196 / 102 / 51 / 2). The visual lane
was not run — it fails 8/8 on macOS on clean `main` by design (`AGENTS.md` 13e).

---

## Part 4 — Rule 19

**This session closed zero issues and opened none.** It found eight live
defects, two of which are money defects, and shipped one work package that is
not merged. Saying that plainly rather than dressing it up is what rule 19 asks
for. F-1 and F-2 are the ones worth scheduling first.
