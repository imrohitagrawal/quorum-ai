# Session handoff — 2026-08-26 (overnight autonomous run)

An unattended run against `CONTINUE-DEMO-READINESS-ULTRACODE-PROMPT.md` and the approved plan
`i-think-you-did-quiet-stearns.md`. Scope was packages A–F; **A, B and C completed, D stopped
deliberately, E and F did not start.** Both non-starts were the prompt's own stop conditions
firing on measurements taken during the run, not time running out.

**Read this first:** the paid spike (package A) removed the premise under packages E and F. Nothing
downstream of it should be built until the decision in §6 is made.

---

## 1. What shipped, and what is running in production

`main` moved `34bbc64` → `e36bbe0` → **`80b5b27`**. Production serves `80b5b27`, verified three
ways per rule 18 for each merge: the Deploy **job** (not the run rollup) ran `success`,
`/status.build_sha` equals the merged SHA, and the built thing was observed firing.

| PR | What | Deploy job | Observed firing in production |
|---|---|---|---|
| #377 | Sessions are as durable as the cap that counts them | `success` (run 32912772282) | `/ui` at the cap serves a rendered 4448-byte page with a live-computed *"a slot frees up in about 17 hours"*, replacing 149 bytes of unstyled prose |
| #378 | The cost ledger tells live spend from simulated | `success` (run 32922727071) | `/status` answers `global_daily_simulated_spend_usd` and `last_live_charge_at` |

Both merges fired three Deploy runs each, two `cancelled` by concurrency de-duplication. Keying on
"newest completed run" would have read a cancelled one both times.

`OPENROUTER_LIVE_EXECUTION_ENABLED` was never flipped — `.env`, `fly.toml` and production all still
`false`. Production `/ready` 200, `feedback_lost_billed_writes` 0, all scheduled watchdogs green.

## 2. Money spent

**8 paid OpenRouter calls, $0.034170 total, against an authorised ceiling of 10.** Two unspent.
Every other package spent nothing. The probe was a standalone script — no app run, no `/ui` request,
no deploy.

## 3. Package A — the spike, and why it stops #290

`/private/.../scratchpad/a2_probe.py`, 4 default slot models × 2 repeats, `max_tokens=2000`, a prompt
that genuinely fills the cap (7 of 8 returned `finish_reason: "length"`).

| model | wall to LAST byte | max inter-chunk gap | completion tokens | cost |
|---|---|---|---|---|
| `openai/gpt-4o-mini` | 24.415 / **26.492s** | 22.440 / **25.055s** | 1965 / 2000 | $0.0012231 / $0.0012441 |
| `anthropic/claude-haiku-4.5` | 22.964 / 22.651s | 21.129 / 20.901s | 2000 / 2000 | $0.010308 ×2 |
| `google/gemini-2.5-flash` | 14.086 / 14.633s | 13.001 / 13.514s | 2000 / 2000 | $0.005087 ×2 |
| `nvidia/nemotron-3-nano-30b-a3b` | 6.385 / 8.694s | 5.722 / 7.589s | 2000 / 2000 | $0.00041 / $0.00050 |

Against `openrouter_timeout_seconds = 8.0`: **8 of 8 exceed it on wall clock, 6 of 8 on the
per-`recv` gap.**

**The per-`recv` number is the one that decides it, and it is not the same number as wall clock.**
`providers._post_messages` calls `urlopen(request, timeout=settings.openrouter_timeout_seconds)`, and
a socket timeout is per-`recv`, not cumulative — the same distinction `_read_within_budget`'s
docstring already records for the error path. OpenRouter answers `Transfer-Encoding: chunked`, headers
early, body in 3–4 chunks; what fires the timeout is the silence *between* chunks.

ADR-0037's time-to-first-byte figure reproduces here (0.663–1.974s on every call) and is exactly as
misleading as its own text warns.

**Consequence:** peer critique cannot be built against the current call path. Every critique would
time out, and `providers` classifies a post-dispatch timeout as possibly-billed — so it would pay for
tokens it discards *and* demote each run's receipt from `measured` to `estimated`. The feature would
make the honesty claims it exists to retire less true. Full table on issue #290.

## 4. A number this repo repeats that is wrong for production

The N=4 baseline quoted across the suite as **`point 0.0547 / bound 0.1043`** is the **judge-OFF**
figure. `tests/conftest.py` forces `QUORUM_EVAL_JUDGE_MODEL_ID = ""`; **production runs judge-ON**
(`/status.judge_enabled: true`). With the judge configured the shipped estimator returns
**`bound 0.1134`**. Both reproduced from `CostEstimationService._estimate_bound_usd`, varying nothing
but that one variable:

```
judge OFF -> raw 0.104287 -> 0.1043
judge ON  -> raw 0.113393 -> 0.1134
```

Every occurrence of `0.1043` is a **comment**, never an assertion, which is why nothing went red when
#265/ADR-0064 priced the judge in. The population is **21 files** (16 carrying one boilerplate
comment). PR #378 corrected the canonical statement only; the rest were left deliberately, and four
are historical run records that must not be back-dated.

Projected peer-critique bound (arithmetic only, judge-ON, reproducing the shipped estimator before
varying it): **0.1419 – 0.1599** depending on how much prior context round 2 and synthesis carry —
**×1.25 to ×1.41**, not the planning assumption of ~57%. The spread matters more than the midpoint:
whether every default run demands a confirmation click turns on that design choice.

## 5. Package D — stopped, and why that is the right outcome

Nothing built, nothing committed, branch and worktree removed. **The blocker is not volume; it is an
unmeasured product decision.**

`docs/adr/0067-*.md:474-477` already names this exact case under *"What this gate still cannot see"*:

> **A panel of exactly two.** With one group of two the panel reads `agreed` and `strong`; with two
> groups of one it reads `split` and `divided`. Both are defensible, **neither is measured against
> real two-model traffic**, and the product runs exactly four slots today.

Shipping N=2 promotes a recorded blind spot to a shipped path. N=2 is broken in **both** directions
today:

* **live execution OFF** (production now): `_usable_stance` needs `debate_mode == LIVE`, and
  `_has_strong_overlap` returns `False` at N=2 (`synthesis_consensus.py:420`, `len < 3`). Only
  `"weak"`/`"divided"` are reachable — and the `"weak"` prose at `synthesis.py:884` reads *"Some
  models disagreed on points"*, a **fabricated disagreement on a unanimous panel**.
* **live execution ON**: `len(sizes) == 1` → `"strong"` (`:322`), `panel_agreement` → `"agreed"` with
  no minimum count, and `app.js:4638` paints the large green *"panel's verdict"* band. **2-of-2 earns
  the same visual authority as 4-of-4** — the #354 / ADR-0062 class.

ADR-0071 records live execution as the intended steady state, so the overclaim is one env flag away.

**A cost finding that may change whether the feature is wanted at all:** a 2-model panel is **not**
half price. Bounds across N-subsets of the default slate: N=2 `0.0732–0.0892`, N=3 `0.0854–0.0973`,
N=4 `0.1043` (judge-OFF). The two debate rounds and five synthesis sections barely move with N —
**15–30% cheaper, not 50%**, and *which* models you drop matters more than how many (the defaults
span 8× in input price). If "save money" is the user-facing reason, the arithmetic does not support
it, especially paired with "and you can never get a consensus verdict at N=2."

**A subset was proposed and I declined it.** The suggestion was to ship only the `costs.py`
`Decimal(4)` → `Decimal(len(model_slots))` fix (a real latent mis-pricing: +15.3% at N=2, +6.7% at
N=3, **0 at N=4**, so no production figure moves). It is genuinely small and safe. I declined because
making it testable requires relaxing the `len(model_slots) != 4` guard to `2..4`, and **that bound is
the blocked decision.** If N=2 turns out not to be shippable the right bound is `3..4`, and the pinned
test changes with it. A subset that pre-commits the decision it is waiting on is not a safe subset.
It should be built *with* the decision, not before it.

## 6. Decisions now owed by the human — nothing proceeds without these

1. **#290: streaming, or a lower critique cap?** Measured in §3. Streaming (`"stream": true`) makes
   the inter-chunk gap per-token and preserves the 2000-token cap the design leans on. A lower cap
   means roughly 600–700 output tokens for the slowest model — below the value WP-D/F-07 raised it
   *from*, reopening the truncation defect that raise fixed. **Either must land before the feature.**
2. **What may a 2-model panel claim?** §5. This gates variable panel size *and* its cost subset.
3. **The money constants (item 5).** Not moved. Their target shape (`SOFT ≈ 0.20`, `DAILY ≈ 0.60`,
   `HARD ≈ 0.75`) was derived from an assumed ~57% rise; measured is +25–41%, and it prices a #290
   shape that cannot currently be built. The approved shape still clears the measured bound with
   margin, but setting a guardrail from a surprise is a guess, so nothing moved.

## 7. Open issues after this session

Closed **#376** (by hand, after deploy verification — never by merge keyword). Opened **#379** and
**#380**. Net +1, stated plainly rather than hidden.

| # | What | Found by |
|---|---|---|
| 290 | Peer critique — **blocked** on decision 1 above; probe results posted as a comment | this session |
| 268 | `max_cost_usd` bounds OUTPUT but nothing bounds INPUT | pre-existing |
| 105 | 5xx classified possibly-billed on a premise with no evidence | pre-existing |
| **379** | `last_live_charge_at` reports a pre-#376 row as a live charge, and unlike the 24h totals never self-heals | verifying #378 in production **after** merge |
| **380** | `completeness`/`live_ratio` divide by answers RECORDED, so a slot that produced nothing scores 1.0 | package D's planning |

**#380 is live at the shipped N=4 today** and is the same hole `AGENTS.md` already documents for the
degraded banner — fixed there (`app.js:2297` uses the requested count), never fixed for the signal.
The product's own copy (`app.js:5387`) states completeness *is* what reports a missing slot.

**#379 was found only because production was checked after the merge**, not before. No gate reads
`/status` and compares it against the issue's own premise.

## 8. What could not be verified, and the exact command for each

* **What actually put `$0.0676` on production's meter** — and therefore whether #379's timestamp
  reflects a real live charge. Needs a Fly token this machine lacks (`fly auth whoami` → `Error: no
  access token available`):
  `fly ssh console -a quorum-ai -C "sqlite3 /data/feedback_events.sqlite3 \"select event_type, query_run_id, recorded_at from events where recorder='cost' order by id desc limit 20\""`
* **Which judge model production pins.** `/status` reports `judge_enabled: true`, not the id:
  `fly ssh console -a quorum-ai -C 'printenv QUORUM_EVAL_JUDGE_MODEL_ID'`
* **#380 end-to-end.** The arithmetic, the three skip paths and the contradicting copy were verified
  by reading; a run losing a slot down one of those paths was not driven. That reproduction is also
  the regression test.
* **The advisory mutation gate's root cause is now established** (it was not at the start of the
  night): `--cov-fail-under=88` leaks into mutmut's subset run, so it exits non-zero and mutmut
  raises `BadTestExecutionCommandsException` **before scoring a single mutant**. Same family as
  PR #372. It was green on PR #375 and red on both of tonight's PRs; it is advisory, not required,
  and **it measured nothing on either**. A red gate is not evidence it measured — this is that case.

## 9. Two process notes worth keeping

**Sub-orchestrators refusing a brief was the highest-value behaviour of the night, again.** All three
did it: B refuted its own briefed claim that `min_machines_running = 0` implies hourly restarts
(measured `uptime_seconds` 5.56h against a 5.78h-old deploy) and relabelled the argument inferred;
C rejected the design steer on the per-account rails, correctly — narrowing them would have left
`DAILY_CAP_USD` bounding nothing on a live-off deployment, which is every deployment today — and
found that two of the three "meters" in its brief were not meters, plus one nobody had named
(`feedback_audit._aggregate_cost` filters on no event type at all); D refused to build.

**Independent verification before merge caught what green did not.** Every merge was gated on
mutations run by the orchestrator, not on the sub-orchestrator's report — including, for #378,
forcing the discriminator to book everything as *simulated* (the direction that loses real money,
3 tests red) and everything as *live* (the fix shipping inert, 7 red). C also hit rule 12's trigger
honestly: two consecutive fix rounds each introduced a new false money claim, both into
`openapi.yaml`, both refuted by text already in this repo — so it changed approach rather than
rewording a third time.
