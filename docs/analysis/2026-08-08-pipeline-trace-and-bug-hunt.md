# Pipeline trace, live cost measurement, and execution-verified bug hunt

Session of 2026-08-07/08. Everything here was produced by RUNNING something.
Where a claim is inherited or unverified it says so.

`main` at the time: `8ca6a98` (also what production served).

---

## 0. Paid spend this session

| what | cost |
|---|---|
| First fee/context probe (3 pairs + isolation pair) | $0.029541 |
| 12-query measurement | $0.087788 |
| **Total** | **$0.117329** |

OpenRouter account after: `total_credits 10`, available ~$4.57.
No production run was ever triggered; all calls were direct to OpenRouter on
`openai/gpt-4o-mini` with `max_tokens=16`.

---

## 1. What #268 actually is, measured

#268 says `max_cost_usd` bounds every call's OUTPUT but nothing bounds its
INPUT. It names constants. Measured, they are not equally guilty.

### 1a. `cost_system_prompt_tokens = 350` — OVER-reserves, no work needed

Measured every real system prompt on the tree:

| prompt | tokens (chars/4) |
|---|---|
| initial-answer base (`providers.py`) | 41.25 |
| `debate.ROUND_ONE_SYSTEM_PROMPT` | 225.5 |
| `debate.ROUND_TWO_SYSTEM_PROMPT` | 222 |
| `synthesis.UNTRUSTED_DATA_SYSTEM_RULE` | 144 |

Worst case 225.5 against 350 assumed — a 55% cushion, the safe direction.
The one input-varying part (`prior_question` / `prior_synthesis`) does NOT hide
inside the 350: `costs.py:1330-1335` prices it separately as `context_tokens`.

**Conclusion: strike this half from #268.**

### 1b. `cost_web_search_context_tokens = 2000` — UNDER-reserves. n=12, real API

The `:online` suffix makes OpenRouter inject search context server-side. We
never see it and set no `max_results` / `search_context_size`.

```
label          ctl_in  onl_in  INJECT srcs    fee($)
broad-tech         52    2306    2254    5  0.007000
version            48    3013    2965    5  0.007000
sport-event        50    1330    1280    5  0.007000
obscure            55    1672    1617    5  0.007000
narrow-fact        46    1011     965    5  0.007000
nonsense           57    2119    2062    5  0.007000
news               50    2176    2126    5  0.007000
longq              58    2302    2244    5  0.007000
non-english        49    1000     951    5  0.007000
code               57    2514    2457    5  0.007000
medical            51    1649    1598    5  0.007000
ambiguous          41    2012    1971    5  0.007000

INJECTED: min=951 max=2965 mean=1874   (app assumes 2000)
  over 2000 in 6/12 cases
```

**The real design finding:** ONE constant serves two different jobs — the
typical-case point estimate AND the worst-case bound. For the bound to be a
ceiling it must be >= **2965** observed. `costs.py` already does exactly this
split for output tokens (point uses the typical floor, the bound overrides with
the enforced cap); the search-context term does not.

**Remaining work on #268:** raise the bound's search-context term to a measured
ceiling; optionally keep ~1900 for the point estimate.

---

## 2. The web-search per-request fee — MEASURED, but NOT a bug

Measured, n=12, identical every time:

```
control (no :online):  billed $0.00001215   token cost $0.00001215   fee $0.00000000
online:                billed $0.00746860   token cost $0.00046860   fee $0.00700000
```

A flat **$0.007 per `:online` request**. Four searching slots = **$0.028/run**.
`cost_web_search_request_fee_usd` is `0.0`, so neither the estimate nor the
measured path accounts for it.

**This session first called that a bug. That was WRONG and is corrected here.**
`config.py:332-353` carries a 12-line docstring directly above the constant:

> DEFAULT 0.0 — INTENTIONALLY, PERMANENTLY OFF (accepted decision, 2026-07-17;
> see AC-037 ... The plumbing is retained ONLY as a dormant repo-tracking hook,
> not a pending TODO ... Activating it would shift the CONFIRM/BLOCK bands and
> is deliberately NOT done. Leave at 0.0.

`docs/12-acceptance-criteria.md:269` AC-037 covers the measured path explicitly.
So it is an accepted cost-accounting exclusion, not an oversight.

**The failure mode to learn from:** the value was checked, the twelve lines
immediately above it were not. Read the block a constant lives in, not the line.

**What IS new, and belongs back at that decision:** the 2026-07-17 decision does
not appear to have had a measurement. $0.028/run is ~36% of a real run's billed
cost (#256 measured $0.0767 actual). Whether the exclusion remains acceptable at
that magnitude is a product call.

**Adjacent, unresolved:** OpenRouter publishes PER-MODEL `web_search` prices
(`anthropic/claude-haiku-4.5` 0.01, `google/gemini-2.5-flash` 0.014) and
`_parse_catalog_row` drops the field. `openai/gpt-4o-mini` advertises `None`
yet was measured charging $0.007. Unexplained.

---

## 3. The pipeline, traced by execution

Method: instrumented `provider_execution_service.produce_initial_answer` and
`.call_with_prompt`, drove the real `_execute_query_run`, network faked (no paid
calls). Example query: *"Compare durable storage options for a small team."*

| t (s) | thread | stage | model | prompt |
|---|---|---|---|---|
| 0.0005 | initial-answer_0 | initial answer | openai/gpt-4.1 | search=True |
| 0.0007 | initial-answer_1 | initial answer | anthropic/claude-haiku-4.5 | search=True |
| 0.0008 | initial-answer_2 | initial answer | google/gemini-2.5-flash | search=True |
| 0.0009 | initial-answer_3 | initial answer | google/gemini-2.5-pro | search=True |
| 0.344 | MainThread | debate round 1 | anthropic/claude-haiku-4.5 | 559 ch, max_tokens 2000 |
| 0.600 | MainThread | debate round 2 | anthropic/claude-haiku-4.5 | 846 ch, max_tokens 2000 |
| 0.864–0.867 | synthesis-section_0..4 | synthesis x5 | openai/gpt-4o-mini | 1183 ch each, max_tokens 3000 |
| on RESULT FETCH | MainThread | judge | openai/gpt-5-mini | max_tokens 1024 |

**11 outbound calls during the run, +1 judge on result fetch.**

Established facts:

- **No agents.** No tool-use loop, no agent framework, no planner. A fixed
  4-stage pipeline of one-shot completions, hard-coded in `_execute_query_run`.
- **Initial answers are genuinely parallel** — four distinct threads within 0.4ms.
- **Debate is strictly sequential** — round 2 began only after round 1 returned.
- **Synthesis is genuinely parallel** — five distinct threads (`synthesis-section_0..4`).
  A first trace with an instant stub showed one thread and was misleading; a
  0.25s stub revealed the real fan-out. Slow the seam before concluding serial.
- **The judge is lazy** — it fires on `get_query_run_result`, not during the run,
  and is memoised.
- A first trace with `OPENROUTER_LIVE_EXECUTION_ENABLED=false` showed NO debate
  or synthesis calls at all (local-simulation path). Trace on the live path or
  you measure the wrong pipeline.

### Models per stage (dedicated settings, NOT the user's four slots)

```
debate_model_id            = anthropic/claude-haiku-4.5
synthesis_model_id         = openai/gpt-4o-mini
quorum_eval_judge_model_id = openai/gpt-5-mini
```

---

## 4. Two defects found in the prompts themselves

### 4a. "The four models critique each other" is FALSE, and it is user-facing

The four slot models are called ONCE each, in parallel, and never again. They
never see each other's answers. One separate moderator model reads a transcript
of all four and writes a critique.

Round 1 system prompt: *"You are a debate moderator. Read the four model answers
below..."* Round 2: *"You are a debate moderator refining the round 1
critique..."* Both end *"The output is for a human reviewer, not the user."*

Places asserting otherwise:

| location | text | user-visible |
|---|---|---|
| `templates/workspace.html:923` | "run a query to see how the four models critique each other" | YES |
| `README.md:31` | "each model reads the others' answers and writes a critique" | repo |
| `docs/10-functional-requirements.md:109` (FR-008) | "selected models evaluate disagreement ... in the other model answers" | spec |
| `docs/01-product-brief.md:5,33,47` | "two model critique/debate rounds" | spec |

Precedent for the fix already exists: `workspace.html:915` is honest about
synthesis — *"written by a single configured model (currently openai/gpt-4o-mini)
... It is not a vote or a quote — it is one model's interpretation of the four."*
Debate never received the same treatment.

### 4b. The RECOMMENDATION is written without the sections it claims to use

All five synthesis calls run in parallel and receive **byte-identical user
prompts** (verified: same sha256 across calls 2-6). The recommendation's system
prompt opens:

> *"Write a one-paragraph recommendation using the consensus, disagreement,
> sources, and uncertainty above."*

Those four sections are being computed **at the same time** and are absent from
its prompt. The only "CONSENSUS" text present is the debate critique.

So the paragraph a user acts on is derived from the raw answers + debate, NOT
from the consensus displayed above it. The two can contradict.

Its other rules DO work — `failed_count` and `Source coverage: N%` are in the
prompt, as is the verbatim disclaimer requirement.

---

## 5. Bug hunt — 31 agents, 23 confirmed, 1 refuted

Every finding reproduced by command, then independently attacked by a separate
agent instructed to refute by default. **17 live in production.**

By severity: 2 HIGH, 10 MEDIUM, 11 LOW.
By category: AVAILABILITY 5, SECURITY 5, CORRECTNESS 5, VACUOUS_TEST 4,
DATA_INTEGRITY 2, MONEY 2.

### HIGH

1. **Fabrication scores as well-grounded.** `evaluation.py:248`
   `extract_citation_markers` counts code blocks, JSON output and array indices
   as citation markers, so an answer with ZERO real citations scores grounding
   1.0 and is presented as well-sourced. Strikes at the core product claim.
2. **`/ready` can take 8s under concurrent load**, past `fly.toml`'s 5s health
   check. `catalog_fetcher.py:388-391` — the single-flight collapses on the
   fetch-FAILURE path, so N concurrent callers make N outbound fetches.

### MEDIUM (selected)

3. **Permanent account lockout.** The cumulative-spend rail (`costs.py:1805` +
   `:664`) is metered off an in-process ring with NO timestamp and pruning by
   COUNT only (`MAX_EVENTS=1024`), never cleared in `src/`. After ~7 runs every
   POST `/v1/query-runs` 402s for the life of the process, saying "until the
   window resets" when no window exists — while the durable 24h ledger reads
   $0.00. Reproduced through the real production cookie path.
4. **A malformed Tavily reply destroys an already-billed OpenRouter answer**
   (`providers.py:1573`) — billed, user gets nothing.
5. **Unbounded success-path body read** (`providers.py:1201`) — one dribbling
   upstream holds an initial-answer pool thread indefinitely.
6. **Judge sees one globally renumbered SOURCES list**, so each answer's `[1]`
   points at another slot's source (`evaluation.py:1440`). Interacts directly
   with the grounding score the judge assigns.
7. **A lone Unicode surrogate in `model_slots` → HTTP 500** (should be 422).
8. **`/ready` 500s on any feedback-store READ fault** while `/status` survives
   the identical call (`main.py:760`).
9. **`RECOMMENDATION_MAX_CHARS` unenforced** when the caveat appears early, and
   the model's opening prose is silently deleted (`synthesis_length.py:143`).

### Vacuous tests (delete the control, suite stays green)

10. Legacy `X-Account-Id` auth-bypass kill-switch (`auth.py:341`) — delete it and
    anonymous requests authenticate; **2,513 tests still pass**.
11. Session cookie `HttpOnly` / `SameSite` and the `SESSION_COOKIE_SECURE`
    startup guard (`auth.py:505`, `:266`).
12. 4 of 5 confirmation-token guardrails — single-use, cost binding, TTL.
13. The blocking Schemathesis gate never validates a single SUCCESS response of
    the three query-run operations.

### LOW (selected)

14. CSRF token leaves the process to Sentry in cleartext (`main.py:114`).
15. `_sanitize_source_url` host denylist bypassed by decimal/octal/short-form/
    full-width host spellings that browsers resolve to loopback.
16. `try_record_cost_reconciliation` and `try_record_session_mint` both return
    `True` on a FAILED write — the per-IP mint cap fails open (25 mints against
    a cap of 2).
17. 8 of 11 operations return status codes `openapi.yaml` does not declare.

### The one refuted

The web-search fee finding — dissolved by AC-037, see §2.

---

## 6. Model allocation

Live pricing, $/1M tokens (in/out), fetched from OpenRouter:

| model | in | out |
|---|---|---|
| openai/gpt-4o-mini | 0.150 | 0.600 |
| openai/gpt-5-mini | 0.250 | 2.000 |
| anthropic/claude-haiku-4.5 | 1.000 | 5.000 |
| openai/gpt-5 | 1.250 | 10.000 |

Per-run cost by stage, at the enforced caps:

| model | debate (2 calls) | synthesis (5 calls) | judge (1 call) |
|---|---|---|---|
| claude-haiku-4.5 | $0.0260 | $0.0900 | $0.0331 |
| gpt-4o-mini | $0.0033 | $0.0112 | $0.0048 |
| gpt-5-mini | $0.0095 | $0.0338 | $0.0090 |
| gpt-5 | $0.0475 | $0.1688 | $0.0452 |

**Decision taken (operator approved 2026-08-08): swap debate and synthesis.**

- Debate `claude-haiku-4.5` -> `gpt-4o-mini`: -$0.0227/run. Its output is never
  shown to the user; it was on the most expensive model of the three.
- Synthesis `gpt-4o-mini` -> `gpt-5-mini`: +$0.0226/run. It is the ONLY stage the
  user reads and was on the cheapest model.
- Net ~$0.0001/run. Spend moves to the stage users actually read.
- Judge stays `gpt-5-mini`: it must emit strict JSON or the verdict is discarded
  and billed anyway (ADR-0021 records exactly that failure). Do NOT downgrade.

**UNMEASURED:** output QUALITY for any model on any stage. The instrument exists
— `tests/evals/golden/cases/` (10 cases), estimated under $0.50 to run both
sides. This swap is reasoned from prompt roles and price, not from an eval.
