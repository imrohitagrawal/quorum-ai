# ADR-0055: A durable audit row never asserts a verdict the run did not get

## Status

Accepted — 2026-08-18. Closes issue #342, a follow-up to #216.

Extends [ADR-0051](0051-the-judge-checks-the-spend-rails-instead-of-billing-from-a-read-path.md)'s
rule that "a refusal is scoped to the read that got it, not to the run" from the
in-memory evaluation memo to the durable audit row, and continues
[ADR-0018](0018-a-judge-that-produced-nothing-must-say-so-and-must-not-be-charged-for.md)
on the rule that a judge which produced nothing must say so. Constrained by
[ADR-0002](0002-sqlite-single-writer-ceiling.md) (single
writer) and
[ADR-0016](0016-the-spend-rails-meter-actuals-and-degrade-rather-than-fail-open.md)
(degrade, do not fail open).

## Context

#216 (ADR-0051) put a money pre-flight inside `_MemoisedRunJudge.evaluate`: the
Layer-B judge refuses to fire when the deployment ceiling or the per-account
daily cap is reached. On the SERVING path that refusal is correctly scoped to
the read that got it — `_evaluate_terminal_run` declines to memoise a
suppressed result, so a run refused at 23:59 is not frozen `unverified` past
the 24h rail reset.

`_persist_terminal_run` also runs the judge, at run COMPLETION, and that path
wrote the suppressed shape into the durable evaluation row.

Reproduced on clean `origin/main` (`21d8358`): `git archive origin/main` into a
throwaway directory, a printing probe written into its `tests/integration/`
(a scratch file, deliberately not committed — it prints rather than asserts),
run under the real pytest harness. Verbatim:

```
PERSISTED trust_json band/score/support = unverified None False
EVENT trust_band/support_verified/judge_status = unverified False None
update_evaluation calls = 1  judge dispatches = 0
LATER SERVED shape = ('high', 90, True)  dispatches = 1  update_evaluation calls after the later read = 1
```

Three things in that output matter:

1. The durable row claims `band="unverified", score=None,
   support_verified=False` for a run the judge was never allowed to look at
   (`judge dispatches = 0`).
2. Once the rail clears, the served body is `('high', 90, True)`, and
   `update_evaluation calls` is **still 1** — the durable row is never
   rewritten.
3. `judge_status` on the durable event is `None`, byte-identical to "no judge
   is configured" — the indistinguishability ADR-0018 exists to remove,
   re-introduced by a money refusal.

`_evaluate_terminal_run`'s own docstring claimed the evaluation memo made "the
served projection and the persisted row identical BY CONSTRUCTION". The
suppressed path skips that memo on purpose, so the stated guarantee was void on
exactly this path. That sentence is corrected in the same commit.

Before #216 the only cause of suppression was a rare in-flight timeout race.
#216 made it a deterministic consequence of an account reaching its cap.

**Liveness.** `curl -s https://quorum-ai.fly.dev/status` on 2026-08-18 returns
`build_sha 21d835870165fc4369bfa0db15d860c3b7eaaba9` and `judge_enabled:
false`, so production runs `main`'s tip with the judge OFF and no such row can
exist there today. It arms the moment the judge is switched on. The operator's
stated intent to run the judge permanently ON is **UNVERIFIED by any command**.
Six ADRs other than this one record it in prose —
`grep -rn "permanently ON" docs/ | grep -v 0055-` returns six lines, one each in
ADR-0017, ADR-0018, ADR-0019, ADR-0027, ADR-0029 and ADR-0051 — but a Status
header is a written-down operator statement, not a measurement, and no
EXECUTABLE artefact in the tree implies it: no config default and no deployed
setting turns the judge on. Only asking the owner settles it. (This paragraph
said "no artefact in the tree implies it", full stop, which those six files
contradict. It then enumerated only FIVE of them, omitting ADR-0051 two lines
before naming ADR-0051 as carrying the same over-broad wording — the
enumeration contradicted its own next sentence. The bare `grep` it quoted also
counts this ADR's own mentions of the phrase, so its answer changes every time
this paragraph is edited — it was wrong again within one commit of being
corrected. That is why the `grep -v` above excludes this file: the six stays
true however often this ADR says the phrase. No bare-grep total is quoted here,
deliberately. ADR-0051's copy of the over-broad
wording is left alone as pre-existing and outside this issue;
`grep -n "permanently ON" docs/adr/0051-*.md` locates it.)

## Failure modes enumerated first (AGENTS.md rule 16e)

Written before the fix, from the existing ADRs and from reading the call sites.

- **F-1 Read-modify-write on the rails.** One persist reads the rails twice —
  once via `_result_response`, once via `_persist_run_evaluation` — so the
  served body and the durable row can be decided under different rail states
  inside one persist. ADR-0016 measured this shape on the POST path
  ($0.9376 booked against a $0.20 cap at 32 threads).
- **F-2 Lost write / silent clobber.** `run_history_store.update_evaluation`
  is a blind `UPDATE runs SET eval_json = ?, trust_json = ? WHERE
  query_run_id = ?` with no rowcount check and no partial update. A re-persist
  after memo eviction, with the rail now closed, replaced a verdict the
  account had already bought.
- **F-3 No reconciliation.** `grep -rn "_update_run_evaluation" src/` returns
  three lines, of which **one is a call**, inside `_persist_run_evaluation`;
  the other two are the module's import and a docstring.
  `grep -rn "_persist_terminal_run(" src/` also returns three lines, of which
  **two are call sites** — one in `query_runs.py`, one in
  `_execute_query_run_safely` — and the third is the `def`. Nothing re-visits a
  run: there is no sweeper and no read-path write. (This row said "returns
  two"; the command prints three lines. It then pinned each hit to a line
  number, and every one of those numbers went stale inside this same branch —
  `1028`→`1031`, `1541`→`1544` — so the citation is now the grep itself. Run
  it; do not trust a number written here.)
- **F-4 Idempotency is narrower than the docstring implies.** The S1 metrics
  row is an upsert; the S2 evaluation attach is a pure function of the memo
  state at call time, and the memo is a bounded LRU.
- **F-5 Restart mid-persist.** `query_run_repository` is in-memory, so a
  restart between the metrics row and the evaluation attach already leaves
  `eval_json`/`trust_json` NULL forever. A NULL evaluation therefore already
  means "crashed mid-persist" and cannot also be made to mean "refused".
- **F-6 Concurrent GET during persist.** With the result unmemoised, the GET
  and the persist compute independently. ADR-0051 already records that the
  rail check and the call are not atomic and cannot be without serialising
  every read behind the SQLite lock (ADR-0002).
- **F-7 Absence is not a statement.** Deleting the row makes a money decision
  byte-identical to F-5 and to a store outage — a fourth indistinguishable
  state, not an escape from the first three.
- **F-8 Denominator erasure.** A row that says `unverified` is in the audit
  denominator and wrong; an absent row is not in it at all, so "how often did
  the spend rails cost a user their trust badge?" becomes unanswerable rather
  than merely wrong.
- **F-9 Fail-closed asymmetry.** `_judge_money_rails_allow_dispatch` refuses on
  an unreadable ledger as well as on a cap, so a storage fault also produces
  the divergent row.
- **F-10 Single-process reasoning.** Both memos, the run repository and the
  cost ring are process globals and `Dockerfile` pins `--workers 1`. None of
  the reasoning here survives a second instance.

## Decision

On a SUPPRESSED evaluation, `_persist_run_evaluation`:

1. does not call `_update_run_evaluation` — the durable **trust** column stays
   empty rather than recording a verdict the run did not get;
2. **still writes the durable Layer-A column**, through a new, narrower store
   method `fill_layer_a_evaluation_if_absent`. Layer A is deterministic, needs
   no I/O and no judge, and no spend rail changes what it says, so **AC-041
   holds for a refused run exactly as for any other**; only the verdict is
   withheld. This is not cosmetic: without it a refused row is `eval_json=None,
   trust_json=None`, which is byte-identical to F-5 (crashed mid-persist) — the
   exact indistinguishability this ADR exists to remove, re-introduced by the
   fix. Measured on the first draft of this change, which omitted it:
   `REFUSED eval_json = None` where `origin/main` printed the full signals
   payload;
3. still emits the `run_evaluated` audit event, with `trust_band` and
   `support_verified` set to `null` and the Layer-A telemetry
   (`layer_a_composite_unverified`, `signals`, `faithfulness_label`,
   `hallucination_risk`) intact, for the same reason;
4. carries the refusal cause on that event as a new `judge_refusal` key — a
   closed enum token (`JudgeSuppressionReason`) or `null`, never prose.

**Why the Layer-A write needs its own statement rather than a `trust_json=None`
argument to the existing one.** Two independent hazards, both measured:

* `update_evaluation` is a blind `UPDATE runs SET eval_json = ?, trust_json = ?`
  (F-2), so passing `trust_json=None` on a refused RE-persist nulls a verdict
  the account already bought. The new statement does not mention `trust_json`
  at all, so it cannot.
* A suppressed `result.eval_json()` carries `judge: null`, because no judge
  ran. Writing it over a row that already holds a real judge block leaves the
  row contradicting itself — a `high` trust column beside "no judge ran". The
  statement is therefore `UPDATE runs SET eval_json = ? WHERE query_run_id = ?
  AND eval_json IS NULL`: it fills an absence and never replaces a record.
  One atomic UPDATE, no read-modify-write, so ADR-0002's single-writer
  constraint is respected.

`_MemoisedRunJudge.served_without_verdict` becomes a property over a new
`suppression_reason` attribute, so every existing reader of the boolean is
unchanged while the persist path can see WHY.

Scope kept deliberately narrow: no schema change, no change to
`JudgeCallOutcome`, `TrustScore`, `QueryRunEvaluationProjection` or
`openapi.yaml`. `trust_json` was already `TEXT` nullable and `RunHistoryRow`
already typed it `dict | None`. The `run_evaluated` payload is a free dict
(`grep -rn "run_evaluated" src/ scripts/` → one producer, no reader), so the
new key touches no contract gate. The one addition is the store method above —
additive, and the only caller is the suppressed branch.

`docs/12-acceptance-criteria.md` AC-041 is amended in this PR, narrowly: it
required "a deterministic Layer-A evaluation **and a `TrustScore`** … stored on
that row via `update_evaluation`", which mandates precisely the false claim this
ADR removes. The Layer-A half is unchanged and still enforced; the `TrustScore`
half now carries the refusal exception.

`SPEND_RAIL_PREFLIGHT` does not distinguish "at the cap" from "the ledger could
not be read, so the pre-flight failed closed". `_judge_money_rails_allow_dispatch`
returns a bare `bool`, and narrowing the cause means changing that function's
contract — #216's surface, out of scope here. F-9 is therefore **narrowed, not
closed**: an operator can tell a refusal from a judged verdict, but not a cap
from a storage fault.

## Measured

Every row names the command that produced it. Run from
`/Users/rohitagrawal/Projects/quorum-ai-wt-342` unless stated.

| Question | Command | Measured |
|---|---|---|
| Does the durable row diverge from the served body? | the printing probe above, in a `git archive origin/main` copy | persisted `unverified / None / False`; later served `('high', 90, True)`; `update_evaluation` still 1 |
| The same, re-runnable from a committed file | copy `tests/integration/test_persisted_evaluation_never_asserts_a_verdict_the_run_did_not_get.py` into a `git archive origin/main` copy (`21d8358`) and run it | `10 failed, 7 passed in 0.96s` over the file's 17 cases. Re-derive the split with `--no-cov -v \| grep -E 'PASSED\|FAILED'` rather than trusting a hand-written taxonomy — this row has now been wrong twice. The 7 that pass on `main` are the ones whose assertions do not depend on the fix: `…still_writes_its_full_verdict`, `…event_still_carries_its_layer_a_telemetry`, `…writes_exactly_one_ledger_row`, `…counter_moves_for_a_deliberate_write`, `…is_one_memoised_object`, `…deliberately_not_memoised`, `…records_both_evaluation_columns_on_the_durable_row`. Note `test_a_clean_run_records_no_refusal` is a CLEAN-path case that FAILS on `main`, with `KeyError: 'judge_refusal'` — on `main` the key does not exist at all, so the earlier claim that the clean-path partners "pass on `main`" was false for that one |
| Does a refused run keep its Layer-A row? | the same printing probe, run once in this worktree and once in a `git archive origin/main` copy | `origin/main`: `REFUSED eval_json = {'schema_version': 's3-eval-v5', 'signals': {...}, 'judge': None}`. The FIRST draft of this fix: `REFUSED eval_json = None` — a regression against AC-041, found in review and closed by decision item 2 |
| Does the Layer-A write clobber a bought verdict? | `pytest …::test_a_refused_re_persist_does_not_erase_the_judge_block_already_bought` with `AND eval_json IS NULL` deleted from the statement (`cp`-aside, restored, `diff -q` → identical) | `AssertionError: a refused re-persist erased the judge block the account had already bought` — so the guard, not luck, is what prevents it |
| How many src call sites can write the evaluation columns? | `grep -rn "_update_run_evaluation" src/` | three lines, of which exactly one is a CALL, inside `_persist_run_evaluation`; the other two are the module's `from product_app.run_history_store import update_evaluation as _update_run_evaluation` and a docstring. Line numbers are deliberately omitted: this row cited the call as `:1689` and the import as `line 105`, and at this branch's tip they are `1701` and `108` — worse, `105` is now a DIFFERENT import (`fill_layer_a_evaluation_if_absent`), so the stale citation pointed at real code that was not the thing named |
| How many call sites reach terminal persist? | `grep -rn "_persist_terminal_run(" src/` | `query_runs.py` and `query_run_orchestration.py`, both POST/execution paths — no GET |
| How many consumers does `run_evaluated` have? | `grep -rn "run_evaluated" src/ scripts/` | one producer — `grep -n 'event_type="run_evaluated"' src/product_app/query_run_orchestration.py` returns a single line, inside `_persist_run_evaluation`; every other hit of the bare string is a docstring, and there is no reader anywhere in `src/` or `scripts/`. (This row cited the producer as `:1696`; it is `1713` on this branch, which is why the anchor is now a grep) |
| Did the new tests fail before the fix? | `pytest tests/integration/test_persisted_evaluation_never_asserts_a_verdict_the_run_did_not_get.py -q --no-cov` on the unfixed tree | `10 failed, 7 passed in 0.96s` |
| Do they bite after it? | same file, seven `cp`-aside mutations in a `git archive HEAD` copy, each restored and confirmed with `diff -q` (baseline `17 passed` before and after every one) | dropping the persist-path suppression guard — the `if suppression is None: … else: …` branch in `_persist_run_evaluation`, replaced by an unconditional `_update_run_evaluation(eval_json=…, trust_json=…)` → **7 failed**; dropping the OTHER suppression guard, `if judge.served_without_verdict:` in `_evaluate_terminal_run_with_suppression` → **9 failed**; hard-coding `judge_refusal` to `None` → **3 failed**; re-asserting the downgraded trust shape on the event, i.e. `"trust_band": result.trust.band` and `"support_verified": result.trust.support_verified` → **2 failed**; dropping `AND eval_json IS NULL` → 1 failed; mislabelling the timeout token as `SPEND_RAIL_PREFLIGHT` → 1 failed; the naive "write both columns with `trust_json=None`" repair → 6 failed. **Both suppression guards are named because "the suppression guard" is ambiguous and the two numbers differ** — an earlier draft of this row said "4 failed" for an unspecified one of them, which is neither |
| Was the timeout token covered before this round? | change `INFLIGHT_TIMEOUT` to `SPEND_RAIL_PREFLIGHT` at the one assignment, then `pytest tests/integration/ tests/unit/test_enum_membership_pins.py --ignore=tests/integration/test_persisted_evaluation_never_asserts_a_verdict_the_run_did_not_get.py` | `415 passed, 1 skipped` — **green**. A regression writing a false MONEY attribution into the durable audit stream was invisible to every test that existed before this round. `test_a_judge_wait_that_times_out_records_the_timeout_token` closes it: drop the `--ignore` and the same mutation is `1 failed, 431 passed, 1 skipped` — exactly one case catches it. (This row said `428 passed, 1 skipped`, measured with this file INCLUDED when it held 13 cases; that figure moves every time the file grows, so the number to trust is the `--ignore` one) |
| Store-lock cost of the fix | reading the diff | one FEWER durable write on the refusal path; unchanged elsewhere |

## Rejected alternatives

**Option 1 — write nothing and say nothing** (the issue's "smallest" option).
Rejected. `run_history_store` documented NULL evaluation columns as "`None`
until S2's evaluation engine fills them", i.e. *pending*, so on a terminal run a
silent absence reads as a broken pipeline. It also collides with F-5 (crash
mid-persist) and with a store outage, and takes the run out of the audit
denominator entirely (F-8). Its stated purpose — "so a later read can still
fill it" — rests on a mechanism that does not exist (F-3). The write
suppression is kept; the silence is not — which is what decision item 2 buys:
a refused row still carries `eval_json`, so it is not NULL/NULL and the F-5
collision above does not apply to it. The `RunHistoryRow` docstring quoted here
is corrected in this PR to describe both ways `trust_json` can be empty; an ADR
that argues from a docstring must not leave that docstring saying the old thing.

**Option 1b — write both columns, passing `trust_json=None`** (the smallest
repair for the Layer-A loss). Rejected, and MEASURED as wrong twice: it walks
straight back into F-2 (a refused re-persist nulls a bought verdict), and it
overwrites a row's real judge block with the `judge: null` a suppressed
evaluation carries. Applied as a mutation, six of the file's cases go red,
including `test_a_later_refusal_cannot_overwrite_a_verdict_already_written`.
The narrow `fill_layer_a_evaluation_if_absent` statement is the version that
survives both.

**Option 2a — a new `JudgeCallOutcome` member.** Rejected on two grounds. That
enum documents what one Layer-B judge CALL did, and on this path there was no
call. Worse, the only carrier of a `JudgeCallOutcome` is the entry in
`_judge_verdict_memo`, which is the "already paid, do not dispatch again"
record — writing a refusal into it would permanently suppress the later real
dispatch, re-creating exactly the freeze ADR-0051 exists to prevent. It is also
a served-schema change (`judge_status` is in `QueryRunEvaluationProjection` and
in `openapi.yaml`), which #216 left for separate work.

**Option 3 — let terminal persist re-evaluate once the rail clears.** Rejected.
It is the only option that would make the durable row converge on the served
one, and it needs a trigger that does not exist. The two candidates are a write
from the GET path — which makes a read state-mutating and adds SQLite writes on
the hot read path against ADR-0002's single connection and single lock, and
which, if it also re-dispatches, is ADR-0051's rejected Option A with its named
failure modes — or a background sweeper plus a durable re-judge queue, for runs
that leave the in-memory repository after `QUERY_RUN_TERMINAL_TTL` anyway.

## Consequences

**What this fixes.** The durable row stops asserting `band="unverified",
support_verified=false` for a run that was never judged. The row still carries
its Layer-A record, so it is not an empty row and does not collide with F-5.
The cause is recorded and is distinguishable from "no judge configured" and
from "the judge ran and found nothing". A later refused persist can no longer
clobber a verdict that was already bought (F-2), nor erase a judge block from
`eval_json`.

**What this does NOT fix — stated plainly, not buried.** The durable row still
does not equal the served projection. A run refused at 23:59 is served
`('high', 90, True)` tomorrow while its trust columns stay empty for the rest of
its life. That is F-3, and only option 3 closes it. Do not write "the row and
the projection now agree"; they do not. This converts a false statement into an
honest absence with a recorded cause, and claims nothing more.

Also still open, each stated because a reader would otherwise assume otherwise:

* **The SERVED payload is silent about a refusal.** ADR-0051 says this "belongs
  with its own issue" — an intention, not a filing. Checked on 2026-08-18:
  `gh issue list --state all --limit 300` returns 115 issues and **none** of
  them is that one. Do not read "deferred to its own issue" anywhere as
  "tracked"; it is not filed.
* **`judge_refusal` has a producer and no reader.** `grep -rn "judge_refusal"
  src/ scripts/` returns four lines, of which exactly one is a WRITE — the
  event payload key in `_persist_run_evaluation` — and the rest are docstring
  and comment mentions. There is no READ. The load-bearing claim is
  "one write, no read", not the line count: the count moves whenever prose
  mentions the key, and it did, in this very correction pass. (This bullet said
  the command "returns only the one write site"; it never returned one line.)
  `feedback_audit.py` has
  aggregators for `provider`/`synthesis`/`cost`/`safety`/`debate` and none for
  `evaluation`, so the token reaches no report, no `/status` field and no UI.
  Today it is a JSON key an operator must query by hand:
  `sqlite3 $FEEDBACK_DB_PATH "select json_extract(payload,'\$.judge_refusal')
  from events where event_type='run_evaluated'"`. Building a surface for it is
  its own work; this ADR only guarantees the value is written and durable
  (`feedback_store.py` records that nothing prunes that table).
* **The explanation and the row live in different databases.** The empty trust
  column is in `run_history.sqlite3`; the `judge_refusal` cause is in
  `feedback_events.sqlite3`, written best-effort — `FeedbackStore.record`
  swallows write failures, and `("evaluation", "run_evaluated")` is not in
  `_METERED_WRITES`, so a lost one moves no billed-loss counter (it does stamp
  `_last_write_failure_at`, which `/status` reads). Worse, the two are
  CORRELATED: an unreadable feedback ledger is itself one of the things the
  money pre-flight refuses on (F-9), so the fault that causes the refusal can
  also lose its explanation. **And the ORDER makes that the losing order**: in
  `_persist_run_evaluation` the row write (`_fill_run_layer_a_evaluation`)
  runs BEFORE `_record_feedback_event`, both inside the one
  `except Exception` that logs and swallows — and `FeedbackStore.record` is
  itself documented "best-effort: a failed write is logged and swallowed",
  returning a `bool` this call site ignores. So a lost event needs no exception
  at all: the empty `trust_json` lands durably first and the cause is dropped
  silently after it. Decision item 2 is what keeps that case from being a total
  silence — the run-history row still holds Layer A either way, so it is
  distinguishable from F-5 even when the cause is gone. Reversing the order
  would not help; it would only trade a cause-less absence for an
  absence-less cause.
* **The row and its own latest event can disagree.** After a clean persist and
  a later refused re-persist, the row keeps `high` (correct, F-2) while the
  newest `run_evaluated` event for that run reports `trust_band: null`. An
  auditor reducing the event stream by "last event per run" would read "no
  verdict" for a run whose row holds one. The event stream is a trail of what
  each persist DECIDED, not a projection of current state; read the row for
  state.
* **A transient judge failure still downgrades a bought verdict.** Suppression
  is not the only way `trust_json` goes from `high` to `unverified`: a
  re-persist whose judge returns unparseable output produces a real (NOT
  suppressed) `unverified` result, so it takes the ordinary write path and
  lands on the row. A printing probe — clean persist, both memos cleared, the
  provider seam then returning `"not json at all"` — printed the same thing in
  this worktree and in a `git archive origin/main` copy:

  ```
  AFTER CLEAN  trust band = high
  AFTER GARBAGE trust band = unverified
  AFTER GARBAGE eval judge = None
  dispatches = 2
  ```

  Pre-existing, unchanged by this fix, and out of scope for #342 — named here
  so nobody reads this ADR as having closed durable-row integrity generally.
  Note `dispatches = 2`: the account paid for the second call as well.
* F-1's within-one-persist rail flip is unaffected, since the two dispatches
  still read the rails independently; F-9 is narrowed but not closed; and F-10
  means none of this reasoning holds on a second instance.

**Operational.** No configuration change, no schema change, no new constant, no
OpenAPI change. Unreachable in production while `judge_enabled: false`; it arms
with the judge.
