# ADR-0183: A test leaves the tree's folder only through a folder mutmut can run in

## Status

Accepted — 2026-10-29, board row W116. It builds on the product owner's decisions CHG-099,
CHG-100 and CHG-101 (how W116 counts as done, the two throwaway probes, and what happens if the
second one fails); the helper, the guards, the deadline and the job limit are engineering choices
made in W116.

## Context

The advisory CI job "Mutation score on changed functions" printed no score on any pull request
that changed Python code from #578 (2026-10-18) on; #563 (2026-10-13) was the newest one checked
that printed one (`mutation score (killed / (killed+survived)) = 100.0% (threshold 80%)`, run
38459285859). Each time, mutmut's first run of the tests inside its copy (`./mutants/`) stopped
at a failing test, printed `failed to collect stats`, and scored nothing.

mutmut 3.6.0 (the version CI installs) finds its source by paths RELATIVE to the current folder.
Read in `.venv/lib/python3.12/site-packages/mutmut/`:

- `configuration.py:20` reads `Path("pyproject.toml")`; with none, `_guess_source_paths`
  (`:68-93`) looks for `lib` or `src` in the current folder and otherwise raises "Could not
  figure out where the code to mutate is".
- `__main__.py:120` runs `[p.resolve(strict=True) for p in Config.get().source_paths]` at each
  hit the trampoline records, and it records a hit on every call of a mutated function during
  the stats run (`mutation/trampoline.py:59-60`, when `MUTANT_UNDER_TEST` is `stats`), so a
  missing `src` raises `FileNotFoundError: 'src'` there.
- `__main__.py:446` and `:449-451` run the suite from `./mutants/`; every mutated file imports
  the trampoline, whose import reads the config (`utils/safe_setproctitle.py:15`).
- mutmut renames the original body of every wrapped function (`x…create__mutmut_orig`), and the
  mutated file holds that body plus renamed copies.

mutmut stops at the first failing test (`-x`), so each CI run showed one more cause. The product
owner decided to probe first (CHG-100): a throwaway draft pull request, #596, closed unmerged, added
`--maxfail=10000` and a harmless change to `src/product_app/pdf_text.py`, so one run listed every
test that fails inside the copy.

### Measured

The discovery probe, run 40753467337, job 123046015008. Its step "Mutation score on changed
functions" ran 2026-10-28T19:21:03Z to 19:43:56Z, 1,373 s
(`gh api repos/:owner/:repo/actions/runs/40753467337/jobs`); about 36 s of it was mutant generation
(`run.log`: `Generating mutants ... done in 35561ms`). The short summary of mutmut's first
test run listed 26 failing tests (the run's `mutation-report` artifact, `run.log`).

| Cause | Tests | Where |
|---|---|---|
| A. src code called after `chdir` to a folder with no `src` (`FileNotFoundError: 'src'`) | 5 | `tests/integration/test_end_sessions_command.py` |
| B. a Python child that imports the copied src, started in a folder with no `src` ("Could not figure out where the code to mutate is") | 17 | `test_end_sessions_command.py` 7, `tests/security/test_signed_in_cutoff_on_cache_hits.py` 8 (both through `tests/end_sessions_harness.py`), `tests/unit/test_history_sweep_daemon.py` 2 |
| C. a function recognised by its frame's name (`f_code.co_name == "create"`) | 1 | `tests/integration/test_late_run_refusal.py` |
| D. a structural count over the MUTATED source, read through a module's `__file__` | 2 | `tests/unit/test_fetch_site.py`, `tests/unit/test_history_sweep_daemon.py` |
| E. a root path missing from `[tool.mutmut].also_copy` | 1 | `tests/unit/test_w105_tabs_share_token.py` reads `e2e/servers/signed_in_server.py` |
| **Total** | **26** | |

The probe could not reach mutmut's next step, the clean-test run, because the first run failed.
One failure there is already known: #564 (run 38492525198) printed `FAILED
tests/unit/test_run_history_store.py::test_configure_for_tests_isolation - assert
<product_app.run_history_store.RunHistoryStore object at 0x...> is None` and `Failed to run clean
test`. Reproduced locally on 2026-10-29: `pytest -p no:randomly
tests/unit/test_sentry_init.py::test_sentry_inactive_when_dsn_absent
tests/unit/test_run_history_store.py::test_configure_for_tests_isolation` gave `1 failed, 1
passed`. The test assumed no process-wide store, which importing `main` sets.

## Decision

1. **A test leaves the tree's folder only through `tests/mutmut_cwd.py`'s
   `mutmut_can_run_in(folder)`.** It makes an empty `folder/src` and returns `folder`. Empty on
   purpose: nothing in it can be imported, and the folder still lacks what the test needs it to
   lack (`.env`, `.data`). Every `chdir` and every Python child's `cwd=` in a test module that
   reaches `product_app` goes through it (causes A and B: two `chdir` sites, the two `cwd=` sites
   in the end-sessions harness, the two in the history-sweep daemon tests).
2. **A test recognises a function by a wrapper, not by its frame** (cause C). The lock double in
   `test_late_run_refusal.py` wraps the store's `create`, records the thread while it runs, and
   counts the first lock entry on that thread.
3. **A structural read of src uses the real file through `tests.repo_root.find_repo_root`**, not
   a module's `__file__` (cause D, and every other site the guard found: seven in all).
   `./mutants/` has no `.git`, so `find_repo_root` returns the real root.
4. **`also_copy` gains `e2e/servers`** (cause E).
5. **`test_configure_for_tests_isolation` sets its own starting state** with `monkeypatch`
   instead of asserting it (the clean-test failure).
6. **A proposed budget: `MUTATION_RUN_DEADLINE_SECONDS` 1440 → 2400 s and the job's
   `timeout-minutes` 30 → 50.** The 1,373 s above was the whole step of a FAILING run, about 36 s of
   it mutant generation; at 1440 s it would have left about 67 s for the clean-test run, the forced-fail run and the mutants. This is
   not a prediction of how long a passing run takes. 50 × 60 − 2400 = 600 s stays for setup and the
   report (580 s after `scripts/run_with_deadline.py`'s two 10 s kill waits), the rule the
   Makefile comment states: the deadline ends `mutmut run` before the job limit, so the report
   step still prints. The job is pull-request-only
   (`tests/unit/test_deploy_gate_no_slow_push_jobs.py::test_the_mutation_job_is_pull_request_only`),
   so the deploy gate's wait does not move. The job stays advisory.

The guards, in `tests/unit/test_w116_tests_run_inside_the_mutation_copy.py`: G1a (every `chdir`
and Python child `cwd=` goes through the helper, or is one of five pinned children that run from
the tree's own root), G1b (no frame-name reads), G2 (mutmut's own behaviour, with a real child:
it fails in a bare folder, starts in the helper's folder, and needs `src` again at every hit), G3
(no `ast.parse` of a `product_app` module's `__file__`). `tests/unit/test_mutation_copy_completeness.py`
now reads the full path of a chained `ROOT / "a" / "b"` and requires an `also_copy` entry that is
that path or one of its parent folders.

## Rejected alternatives

- **Patch `Config.source_paths` from `conftest.py`.** It is mutmut's private global
  (`Config.get()`), and mutmut reads the same value to walk and copy the source
  (`walk_all_files`, `__main__.py:142`). Patching it from the test run ties the suite to
  mutmut's internals, as matching its renamed function names would (the last item below).
- **An absolute `source_paths` in `pyproject.toml`.** `copy_src_dir` (`__main__.py:188-200`)
  writes each file to `Path("mutants") / root / name`, and with an absolute `root` that is the
  original file: `Path('mutants') / '/abs/code' / 'm.py'` prints `/abs/code/m.py`. Nothing would be
  copied, and mutants would be written into the real tree.
- **Run each child from the parent's folder.** Locally that is the repository root, and a
  developer checkout can hold a `.env` with real keys, which the children would read
  (`src/product_app/config.py`: `env_file=".env"`); the children are run elsewhere to keep it away.
- **Mark the tests `repo_introspection`** (deselected from the mutant run). They import
  `product_app` and can kill mutants; `test_mutation_test_set_integrity.py` says the honest fix
  is to make the test hermetic.
- **Match mutmut's renamed function name in the lock double** (`co_name.endswith("create__mutmut_orig")`).
  It ties the test to mutmut's naming, which can change in any upgrade; the wrapper does not read
  a name at all.

## What this cannot see

- No mutmut run here: only the confirmation probe after merge (CHG-100) shows a score. If it
  fails in the clean-test step, one fix pull request and one more probe; in the first test run,
  work stops for a product-owner decision (CHG-101).
- The clean-test step re-runs the covering tests in one process in Python set order, which
  changes between runs; other tests that assume process-wide state they never set may fail
  there.
- The probe ran each test once inside the copy, in one order.
- Daemon threads: a `session-gc` tick while a test in an exempt module sits in a bare folder.
- `src/product_app/source_fetcher.py` starts the PDF child with `cwd=src`; inside the copy that
  folder has no `src` and no `pyproject.toml`. Only `env_oracle` tests reach it.
- `logging_config.py` logs `record.funcName`, which mutmut renames; G1b only stops tests from
  relying on it.
- G1a sees a list literal whose first item is `*.executable`, and one level of `tests.*`
  imports; an argument list built in a variable escapes. G1b knows the spellings it lists. G3
  tracks a module's `__file__` through simple assignments, `with … as`, `Path`/`str`/`open`,
  `/` joins, `.parent(s)` and the read methods.
- **Advisory:** some tests parse src through a root built from the test's own path
  (`Path(__file__).resolve().parents[2]`): `tests/unit/test_enum_membership_pins.py:135` and
  `tests/unit/test_risk_constant_pins.py:1099`, `:1154`, `:1513`. Inside the copy that root reads
  the MUTATED files. They did not fail on the probe (their module-level walks may still hold on
  the mutated file; UNVERIFIED), and G3 does not track that spelling.

## Consequences

- A new test that moves to a temporary folder, or starts a Python child there, must use
  `mutmut_can_run_in`, or G1a fails and names the line.
- Each such temporary folder gets an empty `src`. Nothing reads it outside mutmut.
- A mutation job can now run up to 50 minutes instead of 30: 20 more runner-minutes when a job
  hangs.
- W116's own pull request changes tests only, so its mutation job will print "NO SCORE WAS
  PRODUCED" (nothing in scope). The board row derives DONE at merge from its needle; W116 counts
  as done only when the confirmation probe prints a score (CHG-099).

## Related

ADR-0057 (the mutation gate must reach the real tree), ADR-0065 (a truncated run is not a score),
ADR-0182 (the full-suite job limits), `tests/repo_root.py` (#158).
