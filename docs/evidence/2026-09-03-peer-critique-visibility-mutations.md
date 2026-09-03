# Mutation proofs for the peer-critique visibility change (ADR-0097)

Every mutation below was applied by hand to the file named, with the source
`cp`'d aside first and restored from that copy afterwards, `diff -q` confirming
the tree came back byte-identical, and `__pycache__` purged between steps.
Re-proved after `make format` rewrote the assertions.

**Why this file exists.** A prior commit body claimed "16 killed / 16" without
listing the mutations, and an independent reviewer correctly refused to accept
it: their own re-derivation of one mutation produced a different failure count,
because they had guessed a different formulation. A mutation count nobody else
can re-run is an unfalsifiable number. These are the exact edits.

Run them with:

```bash
cd <worktree> && uv run python scripts/proofs/peer_critique_visibility_mutations.py
```

## Tests under proof

* `tests/unit/test_posture_reports_peer_critique.py`
* `tests/integration/test_peer_critique_is_observable.py`
* `tests/unit/test_live_posture_check.py` (the pre-existing suite, to catch
  collateral damage)

Baseline, before any mutation: **261 passed**. A kill count without a baseline
is a broken harness, not a result.

## Round 1 — the field and the wire

| # | File | Mutation | Result |
|---|---|---|---|
| 1 | live_posture_check.py | `main()` stops probing: `peer_states = {}` | KILLED |
| 2 | live_posture_check.py | `main()` passes `peer_states=None` to `evaluate_posture` | KILLED |
| 3 | main.py | drop the `peer_critique_enabled` key entirely | KILLED |
| 4 | main.py | hardcode the value `True` | KILLED |
| 5 | main.py | point it at `judge_configured()` instead | KILLED |
| 6 | live_posture_check.py | fetcher accepts any truthy value instead of a real bool | KILLED |
| 7 | live_posture_check.py | unreadable state reported as `false` | KILLED |
| 8 | live_posture_check.py | unprobed state reported as `false` | KILLED |
| 9 | debate.py | flip the flag's sense in `_build_peer_round` | KILLED |

## Round 2 — after review found the note reached only 6 of 12 return sites

| # | File | Mutation | Result |
|---|---|---|---|
| 10 | live_posture_check.py | wrapper returns `result` unchanged (reintroduces the original bug) | KILLED |
| 11 | live_posture_check.py | drop the flag-off caveat (`and not live` → `and not True`) | KILLED |
| 12 | live_posture_check.py | promise dispatch unconditionally ("therefore dispatches") | KILLED |
| 13 | live_posture_check.py | wrapper stops forwarding `peer_states` | KILLED |
| 14 | live_posture_check.py | `live = True` always | KILLED |

## Round 3 — after review found `any(())` turned "unread" into "off"

| # | File | Mutation | Result |
|---|---|---|---|
| 15 | live_posture_check.py | `_live_verdict` returns `False` instead of `None` when nothing is readable | KILLED |
| 16 | live_posture_check.py | `_live_verdict` drops the unknown-vocabulary guard | KILLED |
| 17 | live_posture_check.py | `_live_verdict` drops the partial-view guard | KILLED |
| 18 | live_posture_check.py | `_live_verdict` stops failing closed (a live host no longer settles it) | KILLED |
| 19 | live_posture_check.py | join with a bare space again (reintroduces the run-on) | KILLED |

## What is NOT proved here

`debate_system_prompt_max_chars`'s seven equivalent mutants are a separate
matter recorded in `tests/unit/test_peer_critique_reply_gates.py`. And no
mutation here can see the `/status` dict-literal line: `make diff-cover` reports
that NONE of the changed `src/` lines are executable statements, so that gate
measured zero of them. The evidence for the `/status` field is mutations 3-5,
not a coverage tick.
