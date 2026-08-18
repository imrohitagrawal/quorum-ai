# ADR-0058: The negative-assertion guard's own tests run in a required pytest lane, and refuse to skip there

## Status

Accepted — 2026-08-19 (part of issue 226; the classifier half is a separate change)

## Context

`e2e/tools/check-negative-assertions.mjs` is the #131 guard: it fails a changed
Playwright spec whose negative assertion has no positive partner.
`tests/unit/test_negative_assertion_guard.py` is that tool's test suite — the
only thing that pins the tool's behaviour, since the mutation gate reads Python
only.

**Every test in that file was skipped in both required pytest contexts.** From
the log of run 32171719632 (`.github/workflows/test.yml`, push to `main`,
headSha `e4c58a2`, conclusion **success**), verbatim:

```
tests/unit/test_negative_assertion_guard.py ssssssssssssssssssssssssssss [ 68%]
ss                                                                       [ 68%]
```

The same log reports `3053 passed, 58 skipped ... in 236.67s`, so the job really
ran; this was a genuine skip, not an aborted job.

**The cause.** The module-scope autouse fixture `_needs_node` skipped when
`node` was absent **or** when `e2e/node_modules/@typescript-eslint/parser` was
not a directory. `e2e/node_modules` is gitignored (`.gitignore:45`) and no step
in `test.yml` or `ci.yml` ran `npm ci`, so the second condition was
unconditionally true in both pytest lanes.

Which of the two conditions fired on `ubuntu-latest` was recorded as UNVERIFIED
in the first draft — the progress line prints only `s`. It is now settled from
the same log, line 315:

```
tests/integration/test_app_js_fixes.py ..........                        [  6%]
```

Those ten tests are `@pytest.mark.skipif(shutil.which("node") is None)`
(`tests/integration/test_app_js_fixes.py:108` and seven more), and they RAN. So
**node was already on the runner; only the `e2e/node_modules` condition fired.**
That changes how Decision 1 should be read: `actions/setup-node` is buying a
*pinned version*, not node itself — the `npm ci` step is what actually unblocks
these tests.

It hit both required pytest contexts: `validate-and-test` (`ci.yml`) runs
`make test-report`, which is pytest (`Makefile:131-133`), and `ci.yml` has no
node either.

**The sharpest part.** The module docstring asserted that
`test_the_guard_is_wired_into_ci` "does not skip: an unregistered gate is not a
gate, and that check needs no node." The autouse fixture had no opt-out, so that
sentence was false: the one check designed to survive a node-less runner was
silenced by the node guard. Measured here on 2026-08-19, with `node` removed
from `PATH`, before the fixture was scoped (the line numbers are from the branch
mid-change, not from `main`):

```
SKIPPED [1] tests/unit/test_negative_assertion_guard.py:704: node is not installed
SKIPPED [1] tests/unit/test_negative_assertion_guard.py:729: node is not installed
2 skipped, 30 deselected in 0.04s
```

**Do not confuse the tool with its tests.** The guard tool *does* run in CI —
`.github/workflows/e2e.yml:139` invokes it. What never ran was its Python suite.

## Measured

Every row is a command run on 2026-08-19, except where marked UNVERIFIED.
Rows describing the state **before** this change were measured at `e4c58a2`
(`main`); rows describing the state **after** it were measured on this branch
at `d744b64`. An earlier draft of this table claimed a single worktree at
`e4c58a2` for every row, which cannot be true of a post-fix row — `main` does
not contain the fix.

| Question | Command | Result |
|---|---|---|
| How many tests are in the module? | `pytest tests/unit/test_negative_assertion_guard.py --collect-only -q` | **30** before this change (a handoff said 28, having read only the first wrapped progress line) |
| What did they do in this worktree before the fix? | `pytest tests/unit/test_negative_assertion_guard.py -q` | `30 skipped in 0.05s`, reason `e2e/node_modules is absent` |
| Cost of `npm ci` in `e2e/`, warm npm cache | `time npm ci --no-audit --no-fund` | `added 88 packages in 819ms`; only `fsevents` has an install script (no browser download) |
| Do the tests pass after a plain `npm ci`? | `pytest tests/unit/test_negative_assertion_guard.py -q` | `30 passed in 9.03s` |
| Node setup cost in CI, **warm** cache | run 32169799819 job log | `Set up Node` 3s; `Install e2e dependencies` 1s (`added 87 packages … in 1s`) |
| Node setup cost in CI, **cold** cache | — | **UNMEASURED.** Not estimated here. |
| Lane durations before the change | run logs | `pytest (Python 3.12)` 4m51s; `e2e axe + parity (chromium)` 12m19s |
| Node version the 30 passes were measured on | `node --version` | v26.4.0 locally. CI pins 22 — the result on 22 is **UNVERIFIED until this change's own required run** |
| Lanes that run the full suite | `Makefile:123,133,795` | three: `test.yml:test`, `ci.yml:validate-and-test`, `ci.yml:diff-cover` |
| Local behaviour after the fix, node hidden from `PATH` | `PATH=/usr/bin:/bin pytest … -q` | `9 passed, 28 skipped` (was 30 skipped, 0 passed) |
| Behaviour with the lane flag set and tooling absent | `PATH=/usr/bin:/bin QUORUM_REQUIRE_E2E_NODE_TOOLING=1 pytest … -q` | `9 passed, 28 errors` — red, as intended |
| Was node itself missing on the runner, or only `node_modules`? | `gh run view 32171719632 --log \| grep test_app_js_fixes` | `tests/integration/test_app_js_fixes.py ..........` — ten `skipif(which("node") is None)` tests RAN. Node was present; only `node_modules` was missing |
| Does a warm npm cache really avoid the registry? | `npm ci --no-audit --no-fund --registry http://127.0.0.1:1` in `e2e/` | exit 0, `added 88 packages in 772ms`. 88 locally vs 87 in CI: macOS-only `fsevents` |

### Round 2 — what the review fan found, and what it cost

Five review lenses ran against the first draft of this change. Three mutations
survived it. Each row is `cp` the file aside, mutate, run, restore, `diff -q`.

| Mutation of the FIRST draft | Result then | Result now |
|---|---|---|
| Module-level `pytest.mark.skip` on the guard module | `35 skipped`, **exit 0** — the original defect, restored, undetected | `AssertionError: 37 of 37 tests in test_negative_assertion_guard.py skipped with the node tooling installed` |
| Unguarded `pytest.skip(...)` at the top of the autouse fixture | `35 skipped`, **exit 0** | same assertion, red |
| Fixture's `pytest.fail(` → `pytest.skip(` (reverting Decision 2 on the wire) | `35 passed` — **survived** | `AssertionError: with the flag set and node unreachable the fixture must FAIL, not skip: {'tests': 37, 'skipped': 28, …}` |
| `no_node_required` early return deleted from the fixture | `35 passed` — **survived** | `AssertionError: the node-free tests must still run when node is absent: {…'errors': 37, 'passed': 0}` |
| `QUORUM_REQUIRE_E2E_NODE_TOOLING: "1"` → `"0"` in `test.yml` | `3 passed` — **survived** | `AssertionError: pytest (Python 3.12) is missing ['require-flag-on-make-test']` |
| The flag gated on `${{ steps.npm.outcome … }}` — the variant this ADR rejects by name | `35 passed` — **survived** | same assertion, red |
| `node-version: "22"` → `"18"` in `test.yml` only | `38 passed` — **survived** | `AssertionError: the two lanes pin different node versions: ['18', '22']` |
| `timeout=` dropped from `_run`, against a `node` that never exits | did not return in 45s (killed, exit 142) | `AssertionError: _run did not return within 15s …`, red in 15.22s |

The first two rows are the important ones: **the anti-regression check was
inside the module it guarded**, so both routes that reproduce the original
defect silenced the watchdog along with everything else, at exit 0.

## Decision

1. **Provision node in `.github/workflows/test.yml`'s `test` job only** —
   `actions/setup-node@v4` pinned to `node-version: "22"` with `cache: "npm"`
   and `cache-dependency-path: e2e/package-lock.json`, then `npm ci` with
   `working-directory: e2e`. Copied from `e2e.yml`, and the two `node-version`
   literals are now COMPARED by `test_the_two_lanes_pin_the_same_node_version`,
   so "the lanes cannot disagree" is a property rather than a promise. The
   first draft asserted it and nothing checked it: dropping this lane to 18
   left every test green.
2. **Set `QUORUM_REQUIRE_E2E_NODE_TOOLING: "1"` on that job's `make test`
   step, unconditionally.** Where it is set, absent tooling is a FAILURE, not a
   skip. It must not be gated on the install step's outcome — that would restore
   the silent green this ADR exists to end. `_node_lane_wiring` now pins the
   VALUE, not just the key: `"0"`, `""`, and a `${{ ... }}` expression are all
   rejected. The first draft checked only that the key was present, so the
   one-character edit that disarms the whole mechanism passed every check in
   the repo.
3. **Scope the autouse fixture** so tests marked `no_node_required` never
   consult node. Those tests need no node tooling — they read repo text, or
   drive a stub `node` they create themselves.
4. **Correct the docstring, and check the correction.** The list of node-free
   tests in the docstring is compared against the markers in both directions by
   a test, so prose and code cannot drift apart again (AGENTS.md rule 1a:
   prefer a check to a corrected sentence).
5. **Put the count-free anti-regression check in a SEPARATE file** —
   `tests/unit/test_guard_suite_is_not_skipped.py`. It runs the guard module as
   an inner pytest with the flag set and requires `skipped == 0` over
   `tests > 0`; no literal test count appears anywhere, because the count in
   the handoff that opened this work was already wrong.
   The separate file is the whole point. The first draft put this check inside
   the module it guards, and a review round proved that worthless by mutation:
   a module-level `pytest.mark.skip`, or an unguarded `pytest.skip` in the
   fixture — the exact original defect — silenced the watchdog along with
   everything it was watching, and pytest exited 0.
6. **Drive the fail-versus-skip decision on the wire, not only in a helper.**
   The same file runs the guard module twice with `PATH` pointed at an empty
   directory, so `node` cannot be found: with the flag set it requires
   `errors > 0` and `skipped == 0`; without it, `skipped > 0` and no errors.
   Both halves require `passed > 0`, which is what pins the `no_node_required`
   opt-out. The first draft covered only the pure `_tooling_verdict` table, and
   reverting the fixture itself to `pytest.skip` survived the whole suite.
7. **Bound the checker subprocess in TIME.** `_run` passes
   `timeout=NODE_TIMEOUT_SECONDS` (120s; the whole module is ~17s on node 22).
   Before this change those tests never executed in a required lane, so an
   unbounded `subprocess.run` cost nothing; now a wedged `node` would burn the
   job to `timeout-minutes: 15` and GitHub would report only "exceeded the
   maximum execution time" — no test name, no output.

`ci.yml` is deliberately left alone.

## Rejected alternatives

1. **Move the tests to the `e2e axe + parity (chromium)` lane**, which already
   has both pytest and node. Rejected: that lane is 12m19s against the pytest
   lane's 4m51s, and it is the slowest required context. Nothing else under
   `tests/` runs there, so the module would become the sole exception, invisible
   to `make quality`, and the next person looking for it would not find it.
2. **Add node to all three full-suite lanes.** Rejected: it triples the npm
   coupling of required gates for no extra signal — the same tests, three times.
   Gating the require flag on an explicit variable that only `test.yml` sets
   keeps the new npm dependency to exactly one required job.
   A related but DIFFERENT option, keying the flag on `GITHUB_ACTIONS` instead
   of an explicit variable, was also rejected, for the opposite reason: it adds
   node nowhere, so `ci.yml`'s two node-less lanes would turn from silently
   skipping to loudly failing. (The first draft ran these two together in one
   sentence, which made the parenthetical a non-sequitur.)
3. **`continue-on-error` on the `npm ci` step.** Rejected, and worth recording
   as a trap. On the *step* it changes nothing useful: the job continues, the
   fixture then sees the tooling absent with the flag set, and fails anyway —
   same redness, worse message. The genuinely dangerous variant is gating the
   flag on the install step's outcome, or `continue-on-error` on the *job*:
   either silently restores the all-skipped state while the lane reports green.
   The first of those is now rejected mechanically, not just in prose — see
   Decision 2.
4. **Vendor `@typescript-eslint/parser`, or rewrite the checker without a real
   TypeScript parser.** Rejected: the module docstring already records why a
   real parser is needed, and this change must not touch the checker — that is
   the second half of issue 226.
5. **A floor of "at least N tests in this file must not skip."** Rejected under
   AGENTS.md rule 1a. The count went stale once inside this investigation alone
   (28 asserted, 30 collected). The check asserts zero skips over a non-zero
   number of tests instead, which needs no literal.
6. **Keep the anti-regression check inside the module it guards.** This is what
   the first draft did, and it was REFUTED by mutation rather than reasoned
   away: a module-level `pytest.mark.skip` and an unguarded `pytest.skip` in
   the autouse fixture each returned the file to wholly-skipped at exit 0, with
   the watchdog skipped along with everything else. A watchdog inside the
   kennel it guards is not a watchdog.
7. **Assert on the `timeout` keyword by reading `_run`'s source.** Rejected:
   that is the substring-versus-structure trap of AGENTS.md rule 8, in a gate.
   The check drives a stub `node` that never exits instead, and a SIGALRM turns
   the missing-timeout case into a named failure in 15s rather than a hang.

## Consequences

- **One more required job now depends on npm.** Framed honestly: `e2e.yml:120`
  already runs a bare `npm ci` inside the required `e2e axe + parity (chromium)`
  context, so an npm outage already blocks merges. This widens the blast radius
  from one required job to two; it does not create the failure mode.
  `cache: "npm"` restores `~/.npm`, and a warm cache genuinely avoids the
  registry — measured, not assumed: `npm ci --registry http://127.0.0.1:1` in
  `e2e/` exited 0 with `added 88 packages in 772ms`. On a COLD cache an npm
  outage can redden this required context; `.github/workflows/test.yml`'s
  header comment now says so, where it used to claim the job needed no
  external services at all.
- **`ci.yml`'s two full-suite lanes still skip these tests.** Deliberate, per
  rejected alternative 2.
- **Runtime.** The node-driven tests cost ~9s (measured: `30 passed in 9.03s`
  before the split) and the separate watchdog file adds three more inner pytest
  runs — one full and two with `PATH` emptied, so cheap. Measured on this Mac
  at node v26.4.0: `39 passed in 22.36s` for both files together. Warm-cache
  node setup was 3s + 1s in run 32169799819; the **cold**-cache cost is
  unmeasured. `timeout-minutes` stays at 15 —
  `tests/unit/test_deploy_gate_no_slow_push_jobs.py` measures each required push
  job's declared ceiling against the deploy gate's wait, so raising it here
  would trip a different blocking invariant.
- **Local developers without node are better off, not worse.** Before: 30
  skipped, 0 run. After the split: the node-free checks run on every machine
  and the watchdog skips (or, where the lane flag is set, FAILS rather than
  going quiet).
- **Honest limit.** A `pytest.mark.skip` applied to
  `tests/unit/test_guard_suite_is_not_skipped.py` itself is not caught by
  anything. Nothing can self-guard against that. What is caught is every route
  that silences the guard module, which is where the defect actually happened.
- **Left open, deliberately:** the guard step in `e2e.yml` carries
  `if: github.event_name == 'pull_request'`, so the guard tool never runs on a
  push to `main`. That is a separate decision with its own shape and its own
  ADR, and is not changed here (AGENTS.md rule 17, one concern per change).
- This covers half of issue 226. The classifier fix is a later change.
