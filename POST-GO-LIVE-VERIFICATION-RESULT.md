# Post-go-live verification — what survived execution

Session of 2026-08-06, on `bbe47a1`. **Read-only. Nothing built, nothing pushed,
$0 spent.** Every line below was produced by running a command; where a claim
could not be executed it says UNVERIFIED and names the command that would settle it.

Method: four independent read-only lenses plus an adversarial adjudicator, then
the lead re-ran every pivotal claim personally. Two of the four lenses refuted
the very issue they were sent to confirm.

---

## 1. Headline

**The judge cluster is not what the handoff says it is.**

`#216`'s stated premise — "a judge cost realized on the request path never
reaches the daily spend ledger" — is **FALSE for the normal path**, and three
places in the tree assert it as fact. The judge fires from `_result_response`
(`query_runs.py:2401`), **21 lines BEFORE** `_reconcile_run_billing` (`:2422`),
so its dollar is already inside the reconciled figure that gets booked.

Established by a runtime stack capture, reproduced independently three times:

```
paid judge HTTP dispatches during _persist_terminal_run: 1
--- dispatch #1 stack (product_app frames only, outermost first) ---
    _persist_terminal_run (query_runs.py:2401)
    _result_response      (query_runs.py:2911)
    _evaluation_projection(query_runs.py:2787)
    _evaluate_terminal_run(query_runs.py:2764)
    evaluate_run          (evaluation.py:1655)
    evaluate              (query_runs.py:2679)
    evaluate              (evaluation.py:1395)
```

and confirmed at the ledger by driving a run to fully-captured `measured` state:

```
cost_reconciled {... 'actual_cost_usd': '0.0042'}
daily_spend_for: 0.0042
served by_stage: [('initial_answers','0.0031'), ..., ('judge','0.0011')]
0.0031 + 0.0011 = 0.0042
```

**Three surfaces state the refuted claim and need correcting:**
`src/product_app/query_runs.py:2408-2420`, `src/product_app/main.py:917-918`,
`docs/adr/0016-…md:157-162` — plus issue #216's own body.

The claim was shipped in the go-live PR (#263) as a code comment explaining why
#216 stays open. It was reasoned from the two call sites and never executed.

---

## 2. The real judge defects, restated

### #216 — re-scope, do not build as written
The genuine leak is **narrow**: a *second* judge dispatch after reconciliation.
`_judge_verdict_memo` is a process global bounded at 512
(`_JUDGE_VERDICT_MEMO_MAX`, `query_runs.py:2572` — ADR-0013 cites `:2365`, stale).
On LRU eviction *or a process restart*, a later `GET` refires a real paid call,
and `try_record_cost_reconciliation` is one-shot, so the ledger cannot move again:

```
after _persist_terminal_run:              judge calls = 1 | ledger = 0.0042
after a later GET with the memo evicted:  judge calls = 2 | ledger = 0.0042
2nd paid judge call the ledger never sees: 0.0011
late reconciliation with the judge-inclusive figure -> False
```

Guard: `feedback_store.py:1183`. `_request_path_judge` (`query_runs.py:2725`)
has **no pre-flight cost or cap check** — it gates only on `judge_configured()`,
run status, and having ≥1 COMPLETED initial answer.

### #258 — true in substance, and its own hypothesis list is wrong
The issue offers "the judge returned `verifies_support=false`" as a candidate
reading. **That state is unreachable.** `verifies_support` is a hard-coded class
attribute `True` (`evaluation.py:1371`); `support_verified = verdict is not None
and judge.verifies_support` (`:1656`). A conforming verdict *always* sets it true
— even one scoring 0/0/high.

So the 2026-08-05 event ($0.0109 billed, nothing changed) was necessarily a
**paid, unparseable verdict**. The mechanism: `evaluate()` sets
`self.last_usage = result.usage` on the line **before** `parse_judge_verdict`,
and that parser collapses four distinct failures (empty / non-JSON / non-dict /
schema-invalid) into a bare `None`. The run is billed, then the verdict is
discarded silently.

Measured outcome × user-visible field (real `POST`+`GET` through `TestClient`):

| outcome | support_ver | band | score | judge cost line | cost_source |
|---|---|---|---|---|---|
| O1 judge NOT configured | False | unverified | None | no | measured |
| O2 conforming verdict | True | moderate | 50 | yes | measured |
| O3 conforming DAMNING verdict (0/0/high) | True | moderate | 50 | yes | measured |
| O4 judge call RAISES | False | unverified | None | no | **estimated** |
| O5 seam returns None | False | unverified | None | no | **estimated** |
| **O6 paid, unparseable** | **False** | **unverified** | **None** | **yes** | measured |
| O7 verdict but usage omitted | True | moderate | 50 | no | **estimated** |
| **O8 paid, empty body** | **False** | **unverified** | **None** | **yes** | measured |

**O6/O8 vs O1 are byte-identical in every trust field.** The only tell is the
cost line. Two consequences the issue does not name:
1. A judge that **raises** silently demotes the *whole run's* `cost_source` to
   `estimated` — the user loses their measured cost because an advisory
   subsystem failed.
2. `_JudgeOutcome` (`query_runs.py:2580`) already carries `verdict`, `usage` and
   `model_id`, so billed-but-no-verdict **is already distinguishable in memory**.
   It simply is not surfaced. That is the cheap seam for a fix.

### #265 — confirmed exactly as filed
`estimate()` returns `by_stage = ['initial_answers','debate_round_1',
'debate_round_2','synthesis']`, `by_model` kinds `['model','synthesis']`. No
judge term. The measured actual builds a fifth `judge` row
(`costs.py:1878-1879`, `:1894-1896`) the bound's four-stage vocabulary has no
counterpart for.

The shipped UI copy is already safe and hedged deliberately (`app.js:1999-2013`
names this exact gap in a comment). **Two prose surfaces still make the absolute
claim the UI refused:**
- `src/product_app/costs.py:299-300` — "real cost never exceeds it"
- `docs/faq/index.html:638` and `:1083` — "real cost can never exceed a limit
  the run was waved through under"

Neither is live-user-visible: the FAQ is not published (`gh api …/pages` → 404;
prod `/faq` → 404). Both are false only once a judge is configured.

---

## 3. A finding outside the judge, needing its own issue

**`max_cost_usd` is a true ceiling on OUTPUT tokens only, not on INPUT.** The
bound prices input from two *assumptions* that nothing in the provider call path
enforces:

```
config.py:326  cost_system_prompt_tokens: int = 350
config.py:331  cost_web_search_context_tokens: int = 2000
```
Both appear ONLY in `costs.py:1436-1437` (the pricing model) and `main.py:566-567`
(an informational endpoint). The web-search context is injected upstream by
OpenRouter and billed as input; nothing on our side bounds it to 2000.

**I refuted the adjudicator's supporting arithmetic before adopting the claim.**
It stated `_RECOMMENDATION_PROMPT` is 446 tokens against an assumed 350 and that
synthesis prompts run 69 tokens over in aggregate. Measured with the repo's own
`CHARS_PER_TOKEN=4`, and the prompts are passed verbatim with no composition:

```
synthesis  _RECOMMENDATION_PROMPT     302.2 tok   delta=  -47.8
debate     ROUND_ONE_SYSTEM_PROMPT    225.5 tok   delta= -124.5
debate     ROUND_TWO_SYSTEM_PROMPT    222.0 tok   delta= -128.0
synthesis  _DISAGREEMENT_PROMPT       207.0 tok   delta= -143.0
synthesis  _CONSENSUS_PROMPT          201.8 tok   delta= -148.2
synthesis  _SOURCE_SUPPORT_PROMPT     195.2 tok   delta= -154.8
synthesis  _UNCERTAINTY_PROMPT        192.5 tok   delta= -157.5
TOTAL over-assumption: 0.0 tokens
```

**No system prompt exceeds 350.** So the "ceiling holds by only 0.28%" figure is
not reproducible and the exposure is *not* in the system prompts. The structural
claim stands; the quantification does not. **UNVERIFIED: whether a real run
crosses `max_cost_usd`.** Settling command: one live run driven to fully-captured
`measured` state with real prompt-token counts logged and compared to its own
`max_cost_usd`. That costs money — a deliberate single run, not a routine check.

---

## 4. The owner's bar — met, with one judgement call

Bar: *no defect that is live in production and visible to a real user.*
All 16 open issues were classified against the code, not their own self-labels.

- **15 of 16** are developer-only or latent. Judge issues (#216/#258/#265) are
  latent behind `judge_enabled: false` — verified via `/status`, which reports
  the *same* `judge_configured()` predicate `_request_path_judge` gates on
  (`main.py:926`), so the signal cannot drift from the gate that spends money.
- **#203 latent**: prod `/ready` → `state: "live"`, `reasons: []`. Four curl
  variants against the real endpoint (bad key / no header / garbage / empty
  bearer) all returned **401**, never 403. And `offline_by_bad_key` reaches no
  execution path (`grep` over `providers,query_runs,main` → no matches).
- **#245**: a red `main` **cannot** ship. Both its defects make a failed deploy
  *quiet* rather than *red*. Not user-visible.
- **#105 is the judgement call.** A real user today can be shown a cost figure
  the issue measured at 4.2× actual (in-code comment says 5.27×), with no switch
  in the way — `live_execution: true`. It is labelled `(estimated)`, and
  **ADR-0012 (accepted 2026-08-05) explicitly rules "the direction is deliberate
  and is not itself the defect."** New consequence found this session, not in the
  issue: `_reconcile_run_billing` returns early on non-`measured`, so the durable
  daily-spend ledger keeps the overstated figure too — the cap binds earlier than
  real spend warrants.
  **UNVERIFIED: how often it fires.** `/metrics` shows **zero** `/v1/query-runs`
  requests across 22,050s of uptime; production has served essentially no real
  runs recently. Settling command is step 2 of the issue itself: a week of
  `fly logs` grepped for `upstream_provider_http_error` (clock started ~2026-08-05).

---

## 5. Handoff claims that did NOT survive

| Claim | Verdict |
|---|---|
| "backlog moved 18 → **15** open issues" | **REFUTED** — it is **16**. #242 (filed 2026-08-03) was missed |
| §2.3 "#216 is not a subset of #255 because the judge lands after reconciliation" | **REFUTED** — the judge lands *before* it (§1) |
| §2.1 boundary "n=71495, est=$0.1297, max=$0.1501" | **PARTLY REFUTED** — right dollars, wrong `n`. Real boundary is **n=68671** → est `$0.1297`, max `$0.1501`, 86.4%. At n=71495: `$0.1327`/`$0.1531` |
| §1.1 "older than three skipped runs" | undercount — it is **four** (7 Deploy runs on `b2da723`; deploying run `31059886779` at 00:29:53Z, newest at 00:40:17Z was `skipped`) |
| ADR-0013 cites `_JUDGE_VERDICT_MEMO_MAX` at `query_runs.py:2365` | stale line — actual **2572**. Value 512 correct |
| #226 "20 vacuous specs" | **13**, not 20 (`node e2e/tools/check-negative-assertions.mjs --all`) |
| #160 "11 of 14 production enums" | **16** enums, not 14 |

**Claims that DID survive, re-derived:** three-way SHA match `bbe47a1`; #264's
Deploy **job** `success` (run `31061066794`); §1.1's corrected deploy rule; §6's
stale `docs/00-factory-console.md` (`dec70010`, 2026-07-23); rule-14's six
required contexts; AGENTS.md's 17 invariant specs; **ADR-0016's ratio table to
all seven digits** (2.440/2.425/2.393/2.265/2.118/1.559/1.265).

**A methodology error against myself:** my first re-derivation of that ratio
table used synthetic `vendor/model-N` ids, which fall back to default prices, and
produced 2.328/…/1.173 — a *false* refutation of ADR-0016. The ADR says
`default_model_slots()`; with those it matches exactly. Check your own method
before publishing a refutation.

## 6. Traps confirmed live
- **Rule 13a is biting right now**: `e2e/tests/review/` holds **7** gitignored
  scratch specs, so `make quality` is red locally and green in CI for that reason
  alone. Verify before blaming a diff.
- Test `__pycache__` is `cpython-313`; the venv is 3.12.13. Stale bytecode.
