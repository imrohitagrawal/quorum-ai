# ADR-0072: A child process is denied the parent's coverage environment, in one place, and a gate keeps it that way

## Status

Accepted — 2026-08-25. Addresses issue #368.

Builds on [ADR-0047](0047-gate-detectors-resolve-ambiguity-toward-a-red-gate.md) —
the fail-closed posture this gate's classifier uses — and on
[ADR-0057](0057-the-mutation-gate-is-a-regression-detector-and-must-reach-the-real-tree.md),
whose `./mutants/` copy is one of the trees a leaking child measures. Nothing in
either is superseded.

## Context

### The defect

`pyproject.toml:125` reads:

```toml
addopts = "--cov=src --cov-report=term-missing --cov-fail-under=88"
```

`src` is a **relative** path, and this repository has never had a
`[tool.coverage]` section — verified, not assumed:

```
$ git log -S "tool.coverage" --oneline --all -- pyproject.toml
(no output)
```

(Scoped to `pyproject.toml` deliberately. Unscoped, that command now matches
**this ADR**, because the sentence naming the string contains the string — the
self-falsifying shape AGENTS.md rule 1a warns about.)

pytest-cov hands that string to every child process through a `.pth` file that
runs at interpreter start-up. Measured from inside a run of this suite:

```
VAL COV_CORE_CONFIG=':'
VAL COV_CORE_DATAFILE='/Users/.../quorum-ai/.coverage'
VAL COV_CORE_SOURCE='src'
```

`COV_CORE_SOURCE` is unqualified. A child launched with a working directory
outside the repository resolves it against **its own** cwd.
`coverage/inorout.py:579 find_possibly_unexecuted_files()` then walks that
directory at save time and records every importable `.py` file under it at 0%,
and because `COV_CORE_DATAFILE` is absolute the child's data lands beside the
parent's and is combined into it.

Measured on this repository, both directions, 2026-08-25 at `3f5d335`:

| Command | Statement TOTAL |
|---|---|
| `pytest tests/unit/test_stance_majority_flags_has_no_equivalent_mutants.py --cov=src --cov-report=term -q` | **5847** |
| `pytest tests/unit/test_replay_scope_matches_makefile_scope.py --cov=src --cov-report=term -q` | **10426** |

4,579 of those statements belong to a `git clone --local` of this repository
living under `/private/var/.../pytest-of-.../mutscope-clone0/repo/src/`. Divide
a healthy run's covered lines by the inflated denominator and 95.28% becomes
53%, below `--cov-fail-under=88`. `pytest (Python 3.12)` is a **required**
status check, so this blocks merges for a reason unrelated to the diff.

### Four conditions, not three

The leak is narrower than "a subprocess inherits the environment", and the
fourth condition is the one nobody had written down:

1. The child is a **CPython interpreter**. A `git`, `make`, `node` or
   `/bin/sh` child never loads the `.pth` hook.
2. `COV_CORE_*` survives into its environment.
3. Its `cwd` is outside the repository.
4. **`<cwd>/src/` contains a directory holding an `__init__.py`.**
   `coverage`'s `find_python_files()` only descends into importable
   directories. Measured, same tree, same command, adding an `__init__.py` to
   the probe tree's package the only change:

   ```
   == WITHOUT __init__.py ==   child recorded 0 files
   == WITH    __init__.py ==   child recorded 2 files -- the package's own
                               __init__.py and its one module
   ```

Condition 4 is why **four of the five** offending call sites cost zero
statements today while being every bit as armed as the fifth. It is also the
vacuity trap this decision had to design around: a regression test whose probe
tree lacks an `__init__.py` passes for every implementation, including one that
strips nothing.

### The real population

Two independent enumerations — one by hand from a `cwd=`/`env=` census, one by
the AST classifier that ships with this change — converged on the **same five**
offending call sites. (The classifier REACHES eight Python children at an
unproven cwd, printed by `_scan_test_suite()`; five of the eight were
offenders and the other three already stripped or used a scratch environment.) That agreement is the evidence the classifier is calibrated, and it
is why the classifier ships rather than a hand-maintained list:

| Site | env today | `src/` package at cwd? | Cost today |
|---|---|---|---|
| `test_replay_scope_matches_makefile_scope.py:69` | none | **yes** (a full clone) | **LIVE: 5847 → 10426** |
| `test_mutation_gate_integrity.py:67` | `{**os.environ, ...}` | no `__init__.py` | armed, +0 |
| `test_repo_root_resolution.py:154` | `{**os.environ, ...}` | **yes**, but empty | armed, +0 statements |
| `test_run_with_deadline.py:484` | `{**os.environ, ...}` | no | armed, +0 |
| `test_session_hygiene.py:159` | `env = dict(os.environ)`, passed by NAME | no | armed, +0 |

Two further sites — `test_mutation_copy_completeness.py:192` and
`test_mutation_gate_root_resolution.py:542` — already stripped correctly, each
with its own hand-copied five-line dict comprehension and a comment naming the
hazard. **That duplication is the actual defect.** The mitigation existed, was
correct, and was copied by hand to two of seven places.

### Two call sites that must NOT be stripped

`test_telemetry_sink.py:780` binds `repo_root = Path(__file__).resolve().parents[2]`
**inside a function** and runs a child there with `PYTHONPATH=<real src>`; that
child imports the real `product_app.telemetry_sink` and its measured lines are
**genuine coverage**. `test_logging_config_sentry_redaction.py:677` is the same
shape behind a `cwd="."`. A classifier reading only module-level roots would
have called both offenders, and "fixing" them by stripping the environment
would have **deleted real coverage to make a gate green** — exactly what rule 14
forbids. Both were caught before any edit was written, and both are pinned as
SAFE cases in the classifier's table.

## Decision

1. **One home for the strip.** `tests/subprocess_env.py` exports
   `env_without_coverage(base=None, **overrides)`. It is a new, dependency-free
   module rather than a member of `tests/helpers.py`, which imports
   `fastapi.testclient` and `product_app` at module scope and would drag the
   application into every repo-introspection guard. Overrides are applied
   **after** the strip, so a caller can add `PYTHONPATH` or a redirected
   `COVERAGE_FILE` in one expression.
2. **All seven call sites use it** — the five that leaked and the two that had
   hand-copied the comprehension.
3. **A gate keeps it that way.** `tests/unit/test_subprocess_env_hygiene.py`
   parses every file under `tests/` and fails when a subprocess call launches a
   Python interpreter at a `cwd` it cannot prove is the repository root while
   handing it an environment it cannot prove is clean. It ships with three
   anti-vacuity floors that report what they counted — measured 271 files, 92
   recognised subprocess calls and 8 Python children at an unproven cwd — a
   positive partner naming two modules the scan must reach, a thirty-four-entry
   classifier table of paired safe/offending shapes (18 that must be flagged,
   16 that must not), and an executable test
   that measures the statement TOTAL of a nested coverage run in both
   directions.

## Rejected alternatives

### Pin the coverage source to an absolute path

The obvious structural fix, and it is **inert**. Measured on a purpose-built
synthetic rig (a parent package of 10 statements, a clone of 100 with the same
package name) where a clean result is 10 and a leak is 110. PROVENANCE: the rig
rows below were measured by a planning lens, not by the author; the two rows
naming this repository's own 5847/10426, and the pytest-cov behaviour the
argument turns on, were re-derived directly and are marked as such:

| Configuration | TOTAL |
|---|---|
| `--cov=src` (today) | 110 |
| `--cov=src` **plus** `[tool.coverage.run] source=["<ABS>"]` | **110 — the config pin does nothing** |
| `--cov=<ABS>` in `addopts` | 10 |
| bare `--cov` + `source_pkgs=["mypkg"]` | 110 |
| `[tool.coverage.run] relative_files = true` | 114, **and it corrupts** |

Three reasons it was rejected:

* **A `[tool.coverage.run] source` is overridden.** pytest-cov passes `--cov`'s
  values to `coverage.Coverage(source=...)` as a constructor argument, and in
  `read_coverage_config` constructor arguments beat the config file.
* **Even the `addopts` form does not reach the gate that matters.** (Re-derived
  from the installed source: `pytest_cov/plugin.py`'s `--cov` is declared
  `action='append'`, and `_prepare_cov_source` returns `['foo', 'bar']` for
  `--cov=foo --cov=bar`.)
  `Makefile:133` (`test-report`) and `Makefile:1002` (`diff-cover`) each pass
  `--cov=src` on the **command line**, and pytest-cov *appends* rather than
  replaces. Measured: `-o addopts="--cov=<ABS>/src ..." --cov=src` restores the
  leak in full — 10426. `Changed-lines coverage >= 95% (blocking)` runs
  `make diff-cover`, so an `addopts`-only pin would leave a required merge gate
  exactly as broken as it is today.
* **It is not portable.** Coverage has no relative-to-config-file resolution:
  `SERIALIZE_ABSPATH` resolves against cwd, not the config file's directory, so
  the absolute path would have to be machine-specific or computed at runtime.
  The only hook early enough to compute it is `PYTEST_PLUGINS` — an environment
  variable, which cannot be committed to `pyproject.toml` and would have to be
  set at every invocation, including a bare `pytest`. Measured: a root
  `conftest.py` hook never runs, and a `-p` in `addopts` runs too late
  (pytest-cov's hook is `tryfirst` and builds its plugin inside it).

`relative_files = true` deserves its own sentence: it stores paths relative to
cwd, so a file in the clone **collides with and overwrites** the parent's file
at the same relative path. Measured, foreign execution laundered into the parent's numbers — a
line that never ran in the parent reported as covered. In this repository the
clone is an exact copy, so every file would collide. It is worse than the
disease.

### Fix only the filed call site

One line, and it fixes today's symptom. Rejected because it leaves four armed
sites — one of them, `test_mutation_gate_integrity.py`'s `_run` helper, reached
from 64 call sites in that file (counted by AST, not grep) — and nothing prevents the sixth. The asymmetry between a site that
strips and a site that does not IS the defect; repairing one instance of it
reproduces the situation that produced #368.

### A hand-maintained list of approved call sites

The failure mode is already recorded in this repository:
`test_mutation_copy_completeness.py`'s `ROOT_READING_MODULES` is a
hand-maintained tuple, and #338 walked straight past it because a guard whose
input is an allowlist cannot see a module added after the allowlist was
written. The scan is derived from the tree instead.

### A waiver comment (`# cov-env-ok: <reason>`)

Considered and not built. Zero sites need one after this change, and an escape
hatch nothing exercises is untested machinery. Two escape hatches already
exist and are load-bearing: give the call a `cwd` derived from `__file__` or
`find_repo_root` (correct when the child is genuinely meant to measure this
repository), or hand it an environment assembled from scratch.

## Consequences

* The statement denominator of `pytest (Python 3.12)` no longer depends on
  which tests ran, or on whether a temporary tree happened to hold an
  `__init__.py`.
* A new subprocess call that would reopen the leak fails a blocking test with a
  message naming the helper, instead of moving a required gate's denominator.
* The gate is **not total**, and says so. It inherits the four spellings
  documented as KNOWN AND UNCLOSED on
  `test_mutation_gate_root_resolution.py::_cwd_scoped_git_calls` — a
  dynamically built argv, a runner bound indirectly, a star import, and a
  wrapper in another module — and adds a fifth of its own: it reads the
  interpreter from literals in the argv, so a child whose interpreter path is
  computed at runtime is not seen. Each was re-measured on this tree and
  returns no offender today.
* Two guards now recognise subprocess calls with near-identical code. That
  duplication is deliberate for one change: the existing recogniser lives
  inside a 653-line guard with a delicate contract, and refactoring it is a
  second concern. Extracting a shared subprocess-recognition module under `tests/` is the
  natural follow-on.
* The nested-coverage regression test costs two extra `pytest --cov=src` runs
  (~4s each, measured). That is the price of asserting on the real number
  rather than on a proxy.
