# ADR-0118: A truncated mutation run is inconclusive, and does not pass

## Status

Accepted — 2026-09-22. Test tooling only: no `src/` behaviour changes and no
gate threshold moves. **Authorises nothing.**

Reverses one rejected alternative of
[ADR-0065](0065-the-mutation-scope-names-its-oracle-tests-and-a-truncated-run-is-not-a-score.md)
("Fail a truncated run"). The rest of ADR-0065 stands. The product owner asked
for this behaviour in the 2026-09-22 session prompt: *"A truncated run must not
pass."* Refs #464.

## Context

`make mutation-baseline` stops at a wall-clock deadline
(`MUTATION_RUN_DEADLINE_SECONDS`, 1440). ADR-0065 made such a run print
`UNMEASURED` instead of a percentage, fail if it had found a survivor, and
otherwise **exit 0**, reasoning that a partial run is "a budget event, not a
statement about the diff".

That reasoning holds for the percentage. It does not hold for the exit code. A
run that stops early reaches fewer mutants, so it can find fewer survivors, so
"no survivor found" gets MORE likely as the run measures LESS.

## Measured

Two heads of PR #463, read on 2026-09-22 from the mutation job's own log
(`gh run view --job <id> --log`):

| | run `34712754992` (head `af3f1f6b`) | run `34714933047` (head `74945113`) |
|---|---|---|
| mutants in scope | 720 | 1277 |
| reached before the deadline | 465 (65%) | 249 (19%) |
| scored (killed + survived) | 394 | 170 |
| survivors | 35 | 0 |
| job conclusion | `failure` | `success` |

Whether any of the 35 survivors was fixed between the two heads was not
checked here; #464 says none was. #465 tracks them.

**#464's second flaw did not reproduce, and this ADR records that.** The issue
inferred that the scope pulled in functions the diff never touched, because
`git diff -U0 ... | grep -c _tavily_search` printed `0`. With `-U0` the hunk
header names the enclosing class, so a method's name does not appear even when
its body changed. On the merge commit `a6770b2`, the same diff with `-W` shows
`def _tavily_search` once, with `"billing_class": "not_billed"` replaced by
`BILLING_NOT_BILLED` inside it. A reviewer's check found the same for the other
two functions the issue named (`_post_messages`, `_log_post_dispatch_failure`)
and reported that all nine functions in scope had changed lines; only the
`_tavily_search` command above was run by the author. So on that pull request
the issue's fix 2 (derive the scope from AST bodies) and fix 3 (order the
diff's own functions first) had nothing to act on, and neither is built.

## Decision

In `report()` (the `MUTMUT_SCOPE_PY` block of the `Makefile`), a truncated run
that scored at least one mutant and found no survivor prints a line starting
`INCONCLUSIVE:` and exits 1. It was a bare `return`.

The word is `INCONCLUSIVE` and the exit code is non-zero because `make` has
only pass and fail, and of those two, "did not pass" is the true one.

## Rejected alternatives

**Pass when the reach is above some percentage.** Any such number would be
invented: nothing here measures what share of a scope must be reached before
"no survivor" means something, and the survivors in the table above all sat in
one function, so where the deadline falls matters more than how far it got.

**Raise the deadline.** It moves the line and keeps the inversion. The CI job's
own `timeout-minutes` also bounds it.

**Keep exit 0 and rely on the `UNMEASURED` line.** That is what shipped, and the
table above is the result: the check's conclusion read `success`.

## Consequences

* The mutation job is advisory in CI (`continue-on-error: true` on the job in
  `ci.yml`, and not a required status check), so this cannot block a merge. A
  pull request whose scope the deadline cannot finish now shows that job red
  where it showed green.
* Locally the target is blocking, so a large diff fails it until the scope is
  narrowed or the deadline widened. That is the intended reading: not measured.
* **Not changed, and the same shape:** a run in which every reached mutant
  timed out or crashed still prints `UNMEASURED` and exits 0, truncated or not.
  That was decided earlier and separately (the all-timeout branch of the same
  function says why); it is left alone here.
* `tests/unit/test_mutation_gate_integrity.py::test_a_truncated_run_reports_no_percentage_however_good_the_prefix_looks`
  pinned `returncode == 0` and now pins non-zero plus the word `INCONCLUSIVE`.
  Turns red if the branch goes back to a bare `return`, or the word is dropped.
