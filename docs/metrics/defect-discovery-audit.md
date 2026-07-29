# How the last 16 src/ defects were actually found

Recorded because the aggregate ("0 of 16 caught by an automated check") is
cited in `AGENTS.md` and `docs/DAY-ONE-PROMPT.md`, and an audit whose
population lives nowhere cannot be checked by the next reader. That is the
same failure as a gate that cannot state its denominator.

## Method, reproducible

```bash
# the population: conventional-commit fix commits that touched src/ Python
git log --format='%H %s' --first-parent origin/main \
  | grep -iE ' (fix|hotfix)(\(|:)' | cut -d' ' -f1 \
  | while read s; do git show --name-only --format='' $s \
      | grep -q '^src/.*\.py$' && echo $s; done
```

Yields **16** commits (also 16 under the looser `^<sha> fix` grep — checked,
because a reviewer re-derived 24 with a variant that did not filter to
first-parent `src/` Python).

Each was traced to the commit that INTRODUCED the defect with `git blame` over
the old-side lines of the fix, then classified by reading the commit body and
any linked issue. Classification is a READ, not an execution — it is the one
judgement step here and is marked as such.

| # | fix | introduced by | how it was found |
|---|---|---|---|
| 1 | `526758a2` fix(ops): #109 — a writable-looking feedback DB that | `3b9bb9d6` | adversarial review — issue #109: *"Sibling of #101, found while closing it"* |
| 2 | `43f5d659` fix(costs): E2 #102 — a stage that BILLED but never  | `d3bbec2b (root)` | adversarial review — issue #102: *"Follow-up to #99... The gate is unchanged and still trusts an empty list"* |
| 3 | `3b9bb9d6` fix(ops): P1 #101 — a locked feedback DB silently sk | `7f085b79` | adversarial review — issue #101: *"Found while closing Stream B"*; *"No test covers the locked path at all"* |
| 4 | `17926559` fix(costs): F-06 — classify a provider failure by wh | `3580658e` | adversarial review — one of four P0s from a 10-agent bug-hunt fan-out |
| 5 | `651cbb99` fix(runs): F-05 — a terminal run is final in EVERY f | `d3bbec2b (root)` | adversarial review — same fan-out; issue #98 names the test gap |
| 6 | `025bd83b` fix(costs): F-01 — bill one query run once, not once | `618ef036` | adversarial review — same fan-out; issue #95: *"Three independent adversarial reviewers"* |
| 7 | `b95a5ee9` fix(security): F-02 read the session cookie strictly | `3735a7f5` | adversarial review — same fan-out, security lens; confirmed live before the fix |
| 8 | `829ec5e4` fix(costs): per-request web-search fee mechanism (#1 | `8993fa2c` | adversarial review — issue #18: *"Surfaced by the guardrail-evasion review pass on #17"* |
| 9 | `57233f68` fix(costs): model all 5 synthesis sections in the pr | `8993fa2c` | UNKNOWN — neither the commit nor #24/#25 records the route |
| 10 | `8993fa2c` fix(costs): realistic pre-run cost estimate + fail-s | `d3bbec2b (root)` | production measurement — issue #16: a real live run, estimate $0.0016 vs measured $0.0123 |
| 11 | `5da7ac36` fix(ci): resolve all pre-existing pytest failures on | `d3bbec2b (root)` | CI gate — but its own body says *"test-vs-code drift, not a masked real bug"* |
| 12 | `59d48f58` fix(model): update gemini-2.0-flash-lite to gemini-2 | `d3bbec2b (root)` | code review — commit: *"identified in code review"* |
| 13 | `eee93ca4` fix(synthesis): PR-2 items 1-9 — honest coverage, le | `d3bbec2b (root)` | manual audit — a driven synthesis audit, executed not read |
| 14 | `e0ac7b52` fix(copy): PR-1 — brand lede, workspace lede, synthe | `d3bbec2b (root)` | manual walkthrough — copy judged against the product brief |
| 15 | `51b450f2` fix(ui): PR-0.1 — review follow-ups (time-machine, d | `3735a7f5` | adversarial review — *"the three medium-severity review findings from PR-0"* |
| 16 | `ef97f9b1` fix(ui): PR-0 — 12 verified UI/UX bugs | `cb66e91c` | manual testing — INFERRED, low confidence: the body is a title only |

## Aggregate

| Route | Count |
|---|---:|
| Adversarial review / bug-hunt fan-out (incl. code review) | **10** |
| Manual testing, driven audit, product walkthrough | 3 |
| Production measurement | 1 |
| A CI gate | 1 — and it caught test-vs-code drift, not a product defect |
| Unknown | 1 |
| **Total** | **16** |

**0 of 16 were caught by an automated check that existed to catch them.**

## Honest limits

- Classification is a read of commit bodies and issues, not an execution. 13
  of 16 quote the route in words; `59d48f58` says "code review" without
  naming whose; `ef97f9b1` has an empty body and is **inferred** from the bug
  shapes (all browser-observable) — treat that row as low confidence;
  `57233f68` is genuinely unknown and was not guessed.
- Six of the sixteen were introduced by `d3bbec2b`, the **root commit** — one
  drop of 359 files and 29,655 insertions. No changed-lines gate (mutation,
  diff-cover) can scope anything in a greenfield import, because everything
  is changed. That is a structural limit, not a tuning problem.
- Several fixes corrected MORE defects than the one that named them; counting
  those separately would raise the review share, not lower it.
