# ADR-0117: A lazily expanded test case is selectable by its node id

## Status

Accepted — 2026-09-21. Test tooling only: no `src/` behaviour changes, no gate
threshold moves, no test is exempted. **Authorises nothing.**

## Context

The mutation gate runs the tests that cover a changed function by passing their
node ids to pytest. When one of those ids belongs to a schemathesis case —

```
tests/contract/test_api_contract_schemathesis.py::test_api_conforms_to_openapi_contract[GET /status]
```

— pytest exits 4 with `ERROR: not found`, `mutmut` raises
`BadTestExecutionCommandsException`, and the gate dies **before scoring a
single mutant**. So the gate has been blind to any diff touching a function
reachable from a documented endpoint: `/status`, `/ready`, `/ui`, `/v1/*` and
everything under them. It fired on PR #414, again on PR #476, and again on
PR #483 in this session.

**The cause recorded on the board was wrong**, and this ADR corrects it. The
board said *"pytest cannot select a node id containing a space"*. Measured,
under this repo's own pytest config, a plain parametrized id containing exactly
the same `GET /status` text selects fine:

```
$ uv run pytest 'tests/test_lazy_nodeid_selection.py::test_a_plain_parametrized_id_with_a_space_is_a_real_case[GET /status]' \
    --collect-only -q --no-cov
  -> 1/2 tests collected, exit 0
```

The real cause is **how the case is produced**. pytest resolves `path::name` by
matching `name` against the module collector's DIRECT children. For an ordinary
parametrized test those children are the parametrized `Function` items, so
`func[param]` matches. Schemathesis instead returns ONE child named
`test_api_conforms_to_openapi_contract`; the 13 per-operation items appear only
when that child is expanded afterwards. Measured — `Module.collect()` during a
selection run returns:

```
['TestClient', 'test_api_conforms_to_openapi_contract', 'test_every_spec_operation_is_covered_or_explicitly_excluded', ...]
```

No bracketed name, so nothing matches, and pytest says
`(no match in any of [<Module test_api_contract_schemathesis.py>])`.

## Decision

`tests/lazy_nodeid_selection.py`, wired from `tests/conftest.py`:

1. **Before collection** (`pytest_collection`), an argument shaped
   `path::func[case]` is rewritten to `path::func`, and the original id is
   remembered.
2. **After collection** (`pytest_collection_modifyitems`), only the items whose
   node ids were actually requested are kept; the siblings are deselected
   through pytest's own `pytest_deselected` hook, so the run reports
   `1/13 tests collected (12 deselected)`.
3. **A requested id that matches nothing is a `UsageError` naming it.** Not a
   warning, and not a silent fallback to the parent function.

`pytest_collection` is used because it is the earliest hook a CONFTEST may
implement that still runs before the arguments are resolved. Two earlier
attempts are recorded because each looked right and was not:

- `pytest_load_initial_conftests` in the plugin, registered via
  `pytest_plugins` in `tests/conftest.py` — measured: selection still exited 4.
  That hook is documented as never being called for conftest files.
- Loading the plugin with `-p tests.lazy_nodeid_selection` from `addopts` —
  measured: `ImportError: Error importing plugin "tests.lazy_nodeid_selection":
  No module named 'tests'`. Plugin arguments are consumed before the rootdir is
  importable.

## Measurements

RED then GREEN on the real gate, same diff both times (an edit inside a
`/status`-covered function, which is what PR #483 had):

| | `make mutation-baseline DIFF_BASE=origin/main` |
|---|---|
| without the fix | exit **2**, `BadTestExecutionCommandsException`, **no score produced** |
| with the fix | exit **0**, `mutants scored: 1 killed, 0 survived`, score 100% |

Selection behaviour, from `tests/test_lazy_nodeid_selection.py`:

| command | before | after |
|---|---|---|
| one schemathesis case by node id | exit 4, `ERROR: not found` | exit 0, `1/13 tests collected` |
| two schemathesis cases by node id | exit 4 | exit 0, `2/13 tests collected` |
| the bare function id | 13 collected | 13 collected (unchanged) |
| a case id that does not exist | exit 4 | exit 4, naming the id |
| an ordinary module path | 8 collected | 8 collected (unchanged) |

## Consequences

- The mutation gate can run on endpoint-adjacent diffs for the first time.
  What it then reports is a separate question: **#464 records that a truncated
  run still exits 0**, so a gate that now runs is not yet a gate that can be
  trusted to fail. This change deliberately does not touch that.
- Exactly one case runs per requested id, not the function's thirteen. A
  superset would have kept the gate alive too, but it would multiply every
  mutant's runtime by thirteen — straight into #464's truncation — and it would
  quietly change what "the tests covering this mutant" means.
- The rewrite applies to every `path::func[case]` argument, including ordinary
  parametrized ones, because whether it is needed cannot be known before
  collection. The post-collection filter makes the two cases identical, and the
  "ordinary selection is untouched" tests pin that.
- One more thing to know when reading a failure: a case id that no longer
  exists now fails with a `UsageError` naming it, rather than pytest's
  `ERROR: not found`.

## Rejected alternatives

- **Exempt the schemathesis tests from the gate.** Forbidden by the list in
  `tests/unit/test_mutation_test_set_integrity.py`, whose comment requires that
  an exempted test cannot kill a `src/` mutant — these can. It would also leave
  every endpoint-adjacent function unmutated while the gate reported green.
- **Rewrite to the parent function and run all 13.** See Consequences.
- **Re-parametrize the contract test ourselves** so the cases are ordinary
  `Function` nodes. The deepest fix, and the only one that would need no
  plugin — but it rewrites a BLOCKING gate's hypothesis wiring (strategies,
  `max_examples`, the three checks, phases) to solve a tooling problem.
  Disproportionate to a ~60-line plugin with its own tests.
- **Raise the deadline.** Addresses a different symptom, and #464 already
  records that raising it moves the line without removing the inversion.

## Related

- W23 on `docs/65-open-work.md` (whose stated cause this corrects).
- Issue #464 (the gate's verdict inverts under truncation) — next, and separate.
- Rule 2: a red gate is not evidence it measured; the gate's own failure text
  says so, and it was right.
