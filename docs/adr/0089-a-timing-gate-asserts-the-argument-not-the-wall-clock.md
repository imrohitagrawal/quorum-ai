# ADR-0089: A timing gate asserts the argument, not the wall clock

## Status

Accepted — 2026-09-01 (board row W19)

## Context

`tests/unit/test_provider_call_time_budget.py::test_the_budget_covers_the_header_phase_not_only_the_body`
guards a real, expensive defect: the per-call time budget must start **before**
`urlopen`, because `urlopen` returns only once the whole header block has been
read, and that phase is bounded per-`recv` exactly like the body was. A header
block dribbled a byte at a time is unbounded in wall clock, so a budget that
starts afterwards cannot see it.

The test drove a loopback server that dribbles 72 header bytes at 0.05 s each
and asserted `wall < 4.0`.

**That bound failed on unmodified `origin/main` and passed in CI.** Board row
W19 records failures on 2026-08-28 and a paired, interleaved comparison on
2026-08-30. Re-measured here on 2026-09-01, 10 reps on a pristine
`origin/main` worktree at load average 5.6–6.0:

    4.112 4.093 4.102 4.069 4.125 4.159 4.093 4.154 4.137 4.021   -> 10 of 10 FAILED

The obvious reading is "the margin is too small, raise the number". That
reading is wrong, and the measurement that settles it is a comparison of the
two arms rather than of one arm against a threshold. The defect was introduced
by moving `call_started = time.monotonic()` to after `urlopen` returns, and the
budget actually handed to the body read was recorded by wrapping
`_iter_body_within_budget`. Paired and interleaved, 8 pairs alternating,
restoring `providers.py` from a `cp` copy between each, load average 4.7-5.1:

| | wall (s) | budget handed to the body read (s) | `answer_text` |
|---|---|---|---|
| clean `origin/main` | 4.008-4.106, mean **4.056** | **-2.508 … -2.606** | `''` |
| clock after `urlopen` | 4.049-4.157, mean **4.091** | **+1.4999905 … +1.4999957** | `'the answer'` |

**The wall figures do not separate the arms, and this is the load-bearing
finding.** Four independent measurement sessions on this box could not agree on
even the *sign* of the difference:

| session | clean arm (s) | defect arm (s) | ordering |
|---|---|---|---|
| this one, paired, n=8+8 | 4.008-4.106 | 4.049-4.157 | defect slower in 6 of 8 pairs |
| reviewer B, n=10+12 | 4.053-4.138 | **3.868-3.928** | defect reliably FASTER — an inverted detector |
| reviewer C, n=16 | 3.825-4.143 | 4.020-4.163 | straddles 4.0 from both sides |
| reviewer A, n=17 across load 4.6-65 | 3.730-4.105 | — | 9 red / 8 green; the *highest* load gave the *fastest* walls |

Reviewer B's arm is the most damaging reading: there `wall < 4.0` was **green on
the defect and red on healthy code**, which AGENTS.md forbids outright ("Never
write a check that goes red when the bug is FIXED"). The sessions disagree
because the quantity is noise, and that is the point — a bound whose two arms
cannot be reliably ordered has no usable discriminating power, whichever way a
given afternoon happens to fall.

(Rows 2-4 are reviewer-reported and are labelled as such; rows 1 and the
10-of-10 baseline are this session's own runs.)

The reason is structural, not statistical. The wall clock here is set by the
**server**: 72 header bytes at 0.05 s is ~3.55 s of headers before the client
can act, and no client-side budget can shorten a phase that is already over by
the time the client regains control. The budget's only observable effect is on
what happens *next* — and that is the argument, not the elapsed time. The
argument, unlike the wall, separated the arms completely in **every session
that measured two arms** — three of the four above; reviewer A's run measured
only the clean arm, so it has neither a sign nor a separation.

## Decision

**Assert on the argument the code computes, not on the wall clock it happens to
run for.** The test now wraps `_iter_body_within_budget`, records the budget it
is handed, and asserts that the clock charged at least 3.0 s to connect +
request + headers.

Three assertions, each with a stated job:

- `len(budget_handed_to_body_read) == 1` — the anti-vacuity floor. Without it,
  an implementation that never reaches the body read leaves the list empty and
  every assertion below is over nothing (AGENTS.md rule 7).
- `charged_for_the_header_phase >= 3.0` — the load-bearing gate. The structural
  floor is ~3.55 s (the client holds the complete header block after 71 sleeps,
  not 72 — the 72nd precedes the body, not the headers); the defect produces
  0.0 s. A literal on both sides, and never
  the constant under test (rule 7a).
- `charged_for_the_header_phase <= wall` — the positive partner, proving the
  charge is a real elapsed slice of *this* call rather than a constant.

A generous `wall < 30.0` liveness ceiling remains. It is the difference between
"returns" and "never returns", following the precedent already in this file at
`test_a_body_read_that_returns_something_other_than_bytes_does_not_hang`; it is
not a speed measurement and cannot flake at a 2 % margin.

**This test cannot flake on the quantity it measures, and the reason is
structural rather than statistical.** The charge is floored by 71
`time.sleep(0.05)` calls that never return early, so it cannot fall below
~3.55 s whatever the machine is doing. Measured here across **28 clean reps**
spanning load average 3.6 to 20.9 — 12 ambient, 8 under 24 `yes` load
generators, 8 paired against the mutant — the charge ranged **3.762 – 4.106 s**,
low **3.7617 s**. It is load-INSENSITIVE rather than load-monotonic: the lowest
values occurred at *ambient* load, and the loaded arm's low (3.7786 s) was
HIGHER than the ambient low. An earlier draft of this ADR claimed "load makes
the charge larger" (wrong mechanism) and then "±0.08 s, low 3.967 s" (a
reviewer's figure this session inherited without measuring, and which neither
this session nor a later reviewer could reproduce — see Consequences). Against
the 3.0 literal the observed low is **25 % headroom**, where the old bound had
about 2 % and an unstable sign. The defect drives the charge to exactly zero,
which no amount of load can imitate.

Independently reproduced by reviewers, and reported as theirs rather than as
this session's measurement: the new test passed **34 of 34** reps across load
4.7-96 (reviewer B) and **10 of 10** at load 77.11 (reviewer C), where the old
bound was 10 of 10 red at load 4.79. A round-two reviewer instrumenting the
charge over 29 reps at load 3.7-42 saw a low of **3.7146 s** — below anything
this session observed, and still 24 % above the 3.0 literal.

One residual, non-load failure mode the old test did not have: `assert
len(budget_handed_to_body_read) == 1` goes red if `urlopen` never returns a
response at all — a loopback connect failure or a dead server thread. That is
environmental, and it reports `this test measured nothing` rather than a false
budget claim, but "cannot flake" is hedged to "cannot flake on the quantity it
measures" for that reason.

## What this stops catching, stated plainly

An earlier draft of this section named a loss that is not real, and an
adversarial reviewer disproved it. It claimed the test no longer proves the
body read **honours** the budget it was handed. Under a mutant that disables
that deadline entirely, one reviewer measured the OLD test's `wall < 4.0`
**passing 3 of 3** and dying instead on `assert result.answer_text == ""` — the
assertion this change keeps verbatim. A round-two reviewer running the same
mutant measured it **failing 4 of 4** on the wall bound. Both results are real,
and their disagreement is the point: the bound is red 10 of 10 on CLEAN code
too, so it discriminates nothing in either direction, and whichever assertion
happens to fire first is a coin toss. What is settled is that the wall bound
never *proved* the body-read claim — `answer_text` did. Naming a covered
non-loss in place of the real one is exactly the self-serving shape an honesty
section must not have.

**The real loss is the wall-clock ceiling itself.** `header_tick` has exactly
one call site in the whole suite — this test — so after this change **no test
in the repo pins an upper bound on the total wall clock of a call whose header
block dribbles.** `wall < 30.0` is liveness only and will not catch a
regression that takes, say, twelve seconds.

That is a smaller loss than it sounds, for the reason in Context: the budget
can only **charge** for the header phase, it cannot **cut** it. `urlopen` has
already returned by the time any client-side code runs, so there was never a
mechanism by which a correct implementation made this call finish sooner. The
ceiling was measuring the server's dribble loop, not the product. But it is
gone, and a reader deserves to be told that here rather than infer it.

**Two further limits, both demonstrated:**

- A behaviour-preserving refactor can now produce a false red. Clamping the
  remaining budget with `max(0.0, remaining)` changes nothing observable —
  `_iter_body_within_budget` raises `TimeoutError` for any `remaining <= 0`
  at `providers.py:2176` — yet the new test goes red on it (`assert 1.5 >= 3.0`).
  The ADR's position is that the argument *is* the contract, so this is
  intended; it is recorded because a future refactorer will meet it.
- Of the two tests that cover the body-read-honours-its-budget claim,
  `test_a_slow_dribble_is_cut_at_the_budget` bites cleanly (RED at 6.42 s
  against its 4.0 s bound), but
  `test_the_deadline_still_bounds_the_read_when_the_socket_cannot_be_reached`
  **hangs** rather than going red under the same mutant, and `pytest-timeout`
  is not installed, so nothing converts that hang into a failure. That is
  pre-existing and out of scope here, but it means only one of the two is a
  working fallback.

The rule 8b error path (`_read_within_budget`) remains gated by three tests in
`tests/unit/test_provider_billing_evidence.py` —
`test_the_evidence_read_is_time_bounded`,
`test_a_slow_body_cannot_overrun_the_total_budget` and
`test_each_chunk_gets_the_REMAINING_budget_not_a_fresh_one` — all three proved
to bite by mutation, and none touched by this diff. So the **repo** still covers
that defect class end to end. (An earlier draft said "the file", which is false:
those tests are in a different file.)

## Rejected alternatives

**Raise 4.0 to a larger number.** Rejected. AGENTS.md rule 14 forbids lowering a
threshold to go green, and this is the same move. Worse, the measurement above
shows it would not help: four sessions could not agree on the SIGN of the
difference between the arms, and in one of them the defect ran reliably FASTER
than healthy code. Any number large enough to stop the flake is also large
enough to admit the defect — and on that session's data the bound was already
inverted, passing on the defect and failing on the fix.

**Delete the test.** Rejected. It descends from the rule 8b work, where an
`HTTPError` body read on a 503 with the socket held open cost the full
`openrouter_timeout_seconds` — 0.008–0.013 s on the happy path against 8.009 s
on the error path — and no unit test could see it. Deleting the descendant of
that finding to quiet a flake would give the time back to the defect.

**Re-derive the margin from a fresh distribution.** Rejected on the data. This
was the plan the board recorded, and it is the reasonable-looking option, but a
re-derived margin is still a threshold on a quantity whose two arms overlap. The
measurement that killed it is the paired comparison, not more reps of one arm.

**Mark the test `xfail` locally or skip it under load.** Rejected. It would
leave the header-phase claim ungated on the only machine that runs it before CI,
and "skip when the machine is busy" is a check that counts nothing.

## Consequences

- The row's Evidence needle had to be **re-pinned**. It was
  `PRESENT … :: assert wall < 4.0,`, which also matches
  `test_a_slow_dribble_is_cut_at_the_budget` at line 209 — a healthy assertion
  this change deliberately leaves alone. The needle would therefore have stayed
  PENDING after a correct fix and the row would have lied. It is now
  `ABSENT … :: budget_handed_to_body_read`, a symbol this change adds.
- Local `make quality` stops going red on a false signal. The board records
  **one** occasion by name where this came close to licensing the dismissal of
  a real regression — while shipping W1, which rewrites this exact code path
  (`docs/65-open-work.md` at `origin/main`, the "Hit while shipping W1" note).
  An earlier draft of this line said "twice" and "cost several sessions time";
  neither is produced by a command, and the second encounter (ADR-0087) was a
  red *correctly* verified against a clean archive — the opposite of a
  near-dismissal.
- The pattern generalises: where a test drives a server that controls the clock,
  the client's bound is observable in what the client *computes*, not in how
  long the exchange took.
