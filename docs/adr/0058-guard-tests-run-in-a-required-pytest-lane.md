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
unconditionally true in both pytest lanes. Which of the two conditions fired on
`ubuntu-latest` is **UNVERIFIED** — the log prints only `s` and does not say.

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

Every row is a command run on 2026-08-19 in a worktree at `e4c58a2`, except
where marked UNVERIFIED.

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
| Local behaviour after the fix, node hidden from `PATH` | `PATH=/usr/bin:/bin pytest … -q` | `6 passed, 29 skipped` (was 30 skipped, 0 passed) |
| Behaviour with the lane flag set and tooling absent | `PATH=/usr/bin:/bin QUORUM_REQUIRE_E2E_NODE_TOOLING=1 pytest … -q` | `6 passed, 1 skipped, 28 errors` — red, as intended |

## Decision

1. **Provision node in `.github/workflows/test.yml`'s `test` job only** —
   `actions/setup-node@v4` pinned to `node-version: "22"` with `cache: "npm"`
   and `cache-dependency-path: e2e/package-lock.json`, then `npm ci` with
   `working-directory: e2e`. Identical to what `e2e.yml` already does, so the
   two lanes cannot disagree about the node version.
2. **Set `QUORUM_REQUIRE_E2E_NODE_TOOLING: "1"` on that job's `make test`
   step, unconditionally.** Where it is set, absent tooling is a FAILURE, not a
   skip. It is never gated on the install step's outcome — that would restore
   the silent green this ADR exists to end.
3. **Scope the autouse fixture** so tests marked `no_node_required` never
   consult node. Those tests read repo text only.
4. **Correct the docstring, and check the correction.** The list of node-free
   tests in the docstring is compared against the markers in both directions by
   a test, so prose and code cannot drift apart again (AGENTS.md rule 1a:
   prefer a check to a corrected sentence).
5. **Gate the whole thing with a count-free anti-regression check.** An inner
   pytest run of this module, with the flag set, must report `skipped == 0` over
   `tests > 0`. No literal test count appears anywhere — the count in the
   handoff that opened this work was already wrong.

`ci.yml` is deliberately left alone.

## Rejected alternatives

1. **Move the tests to the `e2e axe + parity (chromium)` lane**, which already
   has both pytest and node. Rejected: that lane is 12m19s against the pytest
   lane's 4m51s, and it is the slowest required context. Nothing else under
   `tests/` runs there, so the module would become the sole exception, invisible
   to `make quality`, and the next person looking for it would not find it.
2. **Add node to all three full-suite lanes** (by keying the flag on
   `GITHUB_ACTIONS` rather than an explicit variable). Rejected: it triples the
   npm coupling of required gates for no extra signal — the same tests, three
   times. Keying on an explicit variable that only `test.yml` sets keeps the new
   npm dependency to exactly one required job.
3. **`continue-on-error` on the `npm ci` step.** Rejected, and worth recording
   as a trap. On the *step* it changes nothing useful: the job continues, the
   fixture then sees the tooling absent with the flag set, and fails anyway —
   same redness, worse message. The genuinely dangerous variant is gating the
   flag on the install step's outcome, or `continue-on-error` on the *job*:
   either silently restores the all-skipped state while the lane reports green.
4. **Vendor `@typescript-eslint/parser`, or rewrite the checker without a real
   TypeScript parser.** Rejected: the module docstring already records why a
   real parser is needed, and this change must not touch the checker — that is
   the second half of issue 226.
5. **A floor of "at least N tests in this file must not skip."** Rejected under
   AGENTS.md rule 1a. The count went stale once inside this investigation alone
   (28 asserted, 30 collected). The check asserts zero skips over a non-zero
   number of tests instead, which needs no literal.

## Consequences

- **One more required job now depends on npm.** Framed honestly: `e2e.yml:120`
  already runs a bare `npm ci` inside the required `e2e axe + parity (chromium)`
  context, so an npm outage already blocks merges. This widens the blast radius
  from one required job to two; it does not create the failure mode.
  `cache: "npm"` means a warm cache restores without reaching the registry.
- **`ci.yml`'s two full-suite lanes still skip these tests.** Deliberate, per
  rejected alternative 2.
- **Runtime.** The node-driven tests cost ~9s (measured: `30 passed in 9.03s`)
  and the inner-pytest check ~10s, on a 4m51s job. Warm-cache node setup was 3s
  + 1s in run 32169799819; the **cold**-cache cost is unmeasured.
  `timeout-minutes` stays at 15 —
  `tests/unit/test_deploy_gate_no_slow_push_jobs.py` measures each required push
  job's declared ceiling against the deploy gate's wait, so raising it here
  would trip a different blocking invariant.
- **Local developers without node are better off, not worse.** Before: 30
  skipped, 0 run. After: 29 skipped, 6 passed — the text-only checks now run on
  every machine.
- **Left open, deliberately:** the guard step in `e2e.yml` carries
  `if: github.event_name == 'pull_request'`, so the guard tool never runs on a
  push to `main`. That is a separate decision with its own shape and its own
  ADR, and is not changed here (AGENTS.md rule 17, one concern per change).
- This covers half of issue 226. The classifier fix is a later change.
