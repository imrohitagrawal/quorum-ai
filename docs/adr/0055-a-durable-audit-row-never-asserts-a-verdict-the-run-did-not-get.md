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

Reproduced on clean `origin/main` (`21d8358`) with a `git archive`-copied tree
and a probe under the real pytest harness
(`pytest tests/integration/test_probe342.py -s -q --no-cov`), verbatim:

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
stated intent to run the judge permanently ON is **UNVERIFIED by any command** —
it is an operator statement, and, as ADR-0051 also records, no artefact in the
tree implies it.

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
  one call site; `grep -rn "_persist_terminal_run(" src/` returns two, both
  POST/execution paths. Nothing re-visits a run: there is no sweeper and no
  read-path write.
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

1. does not call `_update_run_evaluation` at all — the durable trust columns
   stay empty rather than recording a verdict the run did not get;
2. still emits the `run_evaluated` audit event, with `trust_band` and
   `support_verified` set to `null` and the Layer-A telemetry
   (`layer_a_composite_unverified`, `signals`, `faithfulness_label`,
   `hallucination_risk`) intact, because Layer A is unaffected by a judge
   refusal;
3. carries the refusal cause on that event as a new `judge_refusal` key — a
   closed enum token (`JudgeSuppressionReason`) or `null`, never prose.

`_MemoisedRunJudge.served_without_verdict` becomes a property over a new
`suppression_reason` attribute, so every existing reader of the boolean is
unchanged while the persist path can see WHY.

Scope kept deliberately narrow: no schema change, no new store method, no
change to `JudgeCallOutcome`, `TrustScore`, `QueryRunEvaluationProjection` or
`openapi.yaml`. `trust_json` was already `TEXT` nullable and `RunHistoryRow`
already typed it `dict | None`. The `run_evaluated` payload is a free dict
(`grep -rn "run_evaluated" src/ scripts/` → one producer, no reader), so the
new key touches no contract gate.

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
| Does the durable row diverge from the served body? | `pytest tests/integration/test_probe342.py -s -q --no-cov` inside a `git archive origin/main` copy | persisted `unverified / None / False`; later served `('high', 90, True)`; `update_evaluation` still 1 |
| How many src call sites can write the evaluation columns? | `grep -rn "_update_run_evaluation" src/` | one CALL, `query_run_orchestration.py:1689`; the other hits are the import at line 105 and a docstring |
| How many call sites reach terminal persist? | `grep -rn "_persist_terminal_run(" src/` | `query_runs.py` and `query_run_orchestration.py`, both POST/execution paths — no GET |
| How many consumers does `run_evaluated` have? | `grep -rn "run_evaluated" src/ scripts/` | one producer (`event_type="run_evaluated"`, `query_run_orchestration.py:1696`); every other hit is a docstring, and no reader anywhere in `src/` or `scripts/` |
| Did the new tests fail before the fix? | `pytest tests/integration/test_persisted_evaluation_never_asserts_a_verdict_the_run_did_not_get.py -q --no-cov` on the unfixed tree | `7 failed, 6 passed` |
| Do they bite after it? | same file, three `cp`-aside mutations, restored and confirmed with `diff -q` | dropping the suppression guard → 4 failed; hard-coding `judge_refusal` to `None` → 2 failed; re-asserting the downgraded trust shape on the event → 3 failed |
| Store-lock cost of the fix | reading the diff | one FEWER durable write on the refusal path; unchanged elsewhere |

## Rejected alternatives

**Option 1 — write nothing and say nothing** (the issue's "smallest" option).
Rejected. `run_history_store` documents NULL evaluation columns as "`None`
until S2's evaluation engine fills them", i.e. *pending*, so on a terminal run a
silent absence reads as a broken pipeline. It also collides with F-5 (crash
mid-persist) and with a store outage, and takes the run out of the audit
denominator entirely (F-8). Its stated purpose — "so a later read can still
fill it" — rests on a mechanism that does not exist (F-3). The write
suppression is kept; the silence is not.

**Option 2a — a new `JudgeCallOutcome` member.** Rejected on two grounds. That
enum documents what one Layer-B judge CALL did, and on this path there was no
call. Worse, the only carrier of a `JudgeCallOutcome` is the entry in
`_judge_verdict_memo`, which is the "already paid, do not dispatch again"
record — writing a refusal into it would permanently suppress the later real
dispatch, re-creating exactly the freeze ADR-0051 exists to prevent. It is also
a served-schema change (`judge_status` is in `QueryRunEvaluationProjection` and
in `openapi.yaml`), which #216 deferred to its own issue.

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
support_verified=false` for a run that was never judged. The cause is recorded
and is distinguishable from "no judge configured" and from "the judge ran and
found nothing". A later refused persist can no longer clobber a verdict that
was already bought (F-2).

**What this does NOT fix — stated plainly, not buried.** The durable row still
does not equal the served projection. A run refused at 23:59 is served
`('high', 90, True)` tomorrow while its trust columns stay empty for the rest of
its life. That is F-3, and only option 3 closes it. Do not write "the row and
the projection now agree"; they do not. This converts a false statement into an
honest absence with a recorded cause, and claims nothing more.

Also still open: the SERVED payload is silent about a refusal (deferred by #216
to its own issue); F-1's within-one-persist rail flip is unaffected, since the
two dispatches still read the rails independently; F-9 is narrowed but not
closed; and F-10 means none of this reasoning holds on a second instance.

**Operational.** No configuration change, no schema change, no new constant, no
OpenAPI change. Unreachable in production while `judge_enabled: false`; it arms
with the judge.
