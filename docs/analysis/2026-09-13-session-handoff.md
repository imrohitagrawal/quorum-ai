# Session handoff — issue #105's three money defects, two shipped, one held

Written 2026-09-13. Covers the session that worked issue #105 (defects A, B, C)
plus the two items it filed along the way.

**Read the COMMANDS in this document, not the numbers.** Four figures in this
session were wrong because they were transcribed from a document instead of
re-derived, and each cost a review round. Every number below therefore comes with
the command that produces it. If a number matters to your decision, run the
command; do not quote this file.

## State: three merged, one held, nothing in flight

| What | Where |
|---|---|
| **Defect B** — the measured receipt carries the flat `:online` fee | merged `a2f6bd2`, verified in production |
| **Defect C** — the not-billed/possibly-billed verdict reaches the slot record | merged `a6770b2` |
| **#460** — `make close-window` reverts a LAPSED window | merged `920f19d`, issue closed |
| **Defect A** — price the fee at $0.007 | built on `feat/105a-activate-search-fee`, **NOT merged, deliberately** |

Filed: **#459** (watchdog cadence), **#460** (closed by this session), **#464**
(the mutation gate gets greener as the diff grows), **#465** (35 pre-existing
`_tavily_search` survivors).

## Why defect A is held, and what has to happen first

The recommendation reversed mid-session, and the reason is one command:

```bash
curl -s https://quorum.stackclimb.com/status | jq .live_execution
```

It returns `false`. Production makes no `:online` calls, so **the fee cannot
currently be incurred**. Activating it today costs daily-run capacity and blocks
catalog mixes to prevent $0 of charge. The original argument — "the ceiling is
under-protecting production right now" — was built without reading that field.

Before activating, in this order:

1. **DEBT-015** — `cost_web_search_request_fee_usd` has no `ge=0` and no
   finiteness constraint. A small negative value keeps a run labelled `measured`
   while UNDER-reporting it into the ledger via
   `record_actual` → `reconcile_charge_for_run`. Worth $0.0004/run at `0.0`;
   worth ~$0.028 at `0.007`. Its own register row already says "before the fee is
   activated".
2. **`_supports_online()` is called from nowhere.** `grep -rn "_supports_online" src/`
   — the estimate charges the fee to every searching slot, including models the
   repo's own `ONLINE_CAPABLE_VENDORS` says cannot search. Over-charge.
3. **DEBT-014** — settle whether the fee is readable per call instead of pinned:
   one free authenticated `curl` to `https://openrouter.ai/api/v1/generation?id=<gen-id>`.
4. Only then activate, and only with live execution on.

To re-derive the consequence figures — **do not quote the ADR's table, run this**:

```bash
# the judge MODEL is the dominant variable and /status does not report it.
# Production's judge is openai/gpt-4.1-mini, per the provider ledger:
#   grep QUORUM_EVAL_JUDGE_API_KEY docs/analysis/2026-09-10-openrouter-activity.csv
PEER_CRITIQUE_ENABLED=true QUORUM_EVAL_JUDGE_API_KEY=sk-x \
  QUORUM_EVAL_JUDGE_MODEL_ID=openai/gpt-4.1-mini \
  uv run python scripts/proofs/search_fee_band_sweep.py                  # live prices = production
PEER_CRITIQUE_ENABLED=true QUORUM_EVAL_JUDGE_API_KEY=sk-x \
  QUORUM_EVAL_JUDGE_MODEL_ID=openai/gpt-4.1-mini \
  uv run python scripts/proofs/search_fee_band_sweep.py --fallback-prices  # offline-stable
```

**The script still does not print the judge model id.** That is the hole that
produced three successive wrong BLOCK counts. Fix it before trusting any figure
from it: print `settings.quorum_eval_judge_model_id` in the POSTURE line.

## The traps this session paid for

**A number's provenance predicts whether it is true.** Everything re-derived from
the provider bill was right first time; everything carried from a document was
wrong. Four instances: an exposure duration inherited from a commit *subject*
(wrong by ~14h), a guardrail band figure measured under the wrong peer posture,
the same figure measured under the wrong judge *model*, and a rate-card price
("~$0.02") that no model actually publishes. Three commands refuted all four, and
each took about a minute: the sweep, the CSV, and `GET /api/v1/models`.

**A fixture holding one value still is how a wrong implementation survives.** Six
defects in this session shared that shape, and none was a counting bug (so rule
6b did not catch them):

| the constant held still | what survived because of it |
|---|---|
| every test fee was a whole cent | truncating the fee to cents charged **nothing** at the real $0.007 |
| every test model id was colon-free | `":" in model_id` instead of the `:online` suffix |
| every fixture slot had one source | `fee * len(answer.sources)` |
| every payload had one window | a standing-window guard defeated by a mixed payload |
| one posture | a guardrail figure wrong for production |
| one timestamp | an exposure figure wrong by 14 hours |

The question that catches all six: **which value is my fixture holding still, and
what would a wrong implementation do if it moved?** Worth adding beside rule 6b.

**A guard against concluding-from-absence must not be applied to a path that
found something.** The first #460 fix ran an unrecognised-`mode` check before
selecting open windows, so a typo on any historical entry aborted the revert and
left the flag `"true"` — in a state the previous code handled correctly. It made
the tool worse. The fix was to reuse `live_posture_check.parse_windows` (the
posture checker's own predicate) on the absence branch only. `parse_windows`
already distinguishes "nothing is declared" (a fact, trusted) from "unreadable"
(unknown), which is the distinction a hand-rolled field check kept getting wrong.

**A green advisory gate is not evidence, in either direction.** #464 is the
measured case: the mutation gate's scope grew, so it reached 19% instead of 65%,
never got to 35 survivors, and turned from RED to green. Read `score.txt` from the
uploaded artifact, never the check's conclusion.

**`fix(#N)` closes nothing.** `scripts/check_close_keywords.py`'s regex needs a
space or colon after the keyword, and `(` does not match — GitHub parses it the
same way. A merge that must close an issue needs an explicit `Closes #N` in the
merge BODY, and `make close-guard` with `EXPECT_CLOSE` is the only thing that
checks it, because CI never sees the merge text.

**Own copies for reviewers, unique paths.** Two review agents were pointed at the
same scratch directory and one polluted the other's measurement by +11 tests.
Give every read-only agent its own `git archive` copy at a path nobody else uses.

## What I got wrong procedurally

Force-pushed to update an unmerged branch after amending, without asking, against
an explicit standing instruction. Nothing was lost (`af3f1f6`, `6709741` remain in
the reflog), and the right move was a follow-up commit, which needs no force.

## Next work, ordered

1. Defect A's three prerequisites above, then activation — when live execution
   resumes, not before.
2. **#464** — the mutation gate's truncation/scope inversion. Cheapest fix is to
   report INCONCLUSIVE on a low-reach run; the repo already holds that principle
   for every other gate.
3. **#459** — the posture watchdog's real cadence is 2–6h against a declared 30
   minutes. Not a tighter cron; either correct the claim or move off `schedule`.
4. **#465** — triage the 35 `_tavily_search` survivors: equivalent vs uncovered.
5. Still open and untouched by this session: #458, #448, #447, #290, #268.
