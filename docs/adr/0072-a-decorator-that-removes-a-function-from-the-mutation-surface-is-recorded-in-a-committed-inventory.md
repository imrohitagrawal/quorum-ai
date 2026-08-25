# ADR-0072: A decorator that removes a function from the mutation surface is recorded in a committed inventory

## Status

Accepted — 2026-08-25. Addresses issue #369, the follow-on that
[ADR-0069](0069-an-equivalent-mutant-is-removed-not-recorded.md) handed over
from its Open section. Nothing in ADR-0069 is superseded; its decision 4 closed
the pragma route and this record closes the decorator route next to it.

## Context

mutmut 3.6.0 generates **no mutants** for a decorated function. The rule is in
`mutmut/mutation/file_mutation.py` (`_skip_node_and_children`): a `FunctionDef`
with any decorators is skipped, together with everything inside it, unless it
carries exactly one decorator spelled as a bare name and that name is
`staticmethod` or `classmethod`; a decorated `ClassDef` is skipped with its
whole subtree. mutmut checks the *spelling*, not what the name is bound to.

So adding one ordinary line above a function deletes that function's entire
mutation surface — no pragma, no comment, no keyword a reviewer would stop on.
The guard shipped for the pragma route (`test_no_mutation_pragma_silences_a_survivor.py`)
scans comment tokens and cannot see it by construction: with `@functools.cache`
planted on `_stance_majority_flags` it prints `5 passed`. The Makefile's scope
step does write a `[decorated]` note to stderr for each skipped function, but
nothing reads it, it only covers functions changed in a diff-scoped run, and
the mutation job is advisory.

Adding a decorator is almost always legitimate. The population on this tree is
FastAPI routes, pydantic validators, properties and context managers — none of
which can be written without one. The problem is not the decorator; it is that
its effect on the mutation gate is invisible.

## Decision

**1. Keep a committed inventory of every function mutmut skips for a decorator,
and fail the merge-blocking test job when the tree and the inventory disagree in
either direction.** `tests/unit/mutation_surface_inventory.txt` holds one
`module:qualname` per line; `tests/unit/test_no_decorator_silences_a_mutation_surface.py`
scans every file `[tool.mutmut] only_mutate` selects, applies mutmut's rule, and
compares. Adding a decorator therefore shows up in review as a second hunk, in a
file whose name says what happened. That is the review signal #369 asked for.

**2. Make it visible, do not refuse it.** Unlike the pragma guard, this one has
a legitimate one-step resolution: add the line (the failure message prints it,
and `python -m tests.unit.test_no_decorator_silences_a_mutation_surface`
regenerates the file). Refusing decorators under `src/` would be absurd.

**3. Mirror mutmut by spelling, and prove the mirror against mutmut itself.**
The scanner records a `def` with any decorator other than a lone bare
`@staticmethod`/`@classmethod`, every `def` inside a decorated class, and a
decorated `def` nested inside a plain function (recorded once; its subtree is
not walked again). It resolves no aliases, because mutmut does not: `@cm` where
`cm = classmethod` is skipped by mutmut and recorded here; `@(staticmethod)` is
mutated by mutmut and not recorded. `test_the_scanner_agrees_with_the_installed_mutmut`
runs one synthetic module through `mutate_file_contents` and through the
scanner and requires the zero-mutant set to equal the recorded set, then strips
one decorator at a time and requires the mutant count to grow. That is the
"does a real mutant still turn the gate red" test the issue names, and it is
what makes the AST mirror honest rather than a second opinion.

**4. Stale entries fail too.** Equality, not subset. A subset check would let a
name be seeded in one pull request and the decorator added in the next with no
diff to the inventory, and would let entries outlive the functions they name
until the file stopped meaning anything.

## Measurements (2026-08-25, mutmut 3.6.0, Python 3.12.13, macOS)

All counts are from `mutmut.mutation.file_mutation.mutate_file_contents`, the
pure function `mutmut run` calls, on `src/product_app/synthesis_consensus.py`
unless stated.

| What | Result |
|---|---|
| File as-is | 384 mutants, 11 for `_stance_majority_flags` |
| `+ @functools.cache` (also `@functools.wraps(dict)`, `@some.custom.decorator`, `@property`, `@(functools.cache)`) | 373 mutants, 0 for the function |
| `+ @staticmethod`, `@classmethod`, `@(staticmethod)`, `@(classmethod)` | 384 mutants, 11 — mutmut's tolerated exception, parentheses included |
| Pragma guard with `@functools.cache` planted | `5 passed` |
| Whole `only_mutate` population through mutmut, 27 files | 11,680 mutants, 19.0 s; all 43 of the scanner's entries received zero mutants (0 exceptions). 26 other top-level functions also received zero, every one for the #146 inert-body reason (`clear`, `lost_billed_writes`, …), which no decorator causes and this guard does not cover |
| Same population through the AST scanner | 43 entries in 59 ms — 37 decorated (one of them nested), 6 methods inside `@dataclass` classes |
| Synthetic module in the binding test | 12 mutants in 15.7 ms |
| Plain `outer` with nested `inner`; then `@cache` on `inner` | 5 mutants → 3, all attributed to `x_outer` — the outer count never reaches zero, so a "went to zero" check cannot see the nested case |
| Guard under mutation, each restored byte-identical (`cp` aside, `diff -q`) | plant `@functools.cache` in `src/`: `2 failed, 4 passed`, gate names `product_app.synthesis_consensus:_stance_majority_flags [decorated]` as NEW; remove `@app.get` from `/health`: STALE `product_app.main:health`; invert the predicate: `4 failed`; `only_mutate` pointed at nothing: population floor red on `0 >= 20`; empty inventory: `2 failed`; scanner stops freezing classes: `3 failed`, binding test names `Frozen.method`/`Frozen.static` |

The planners' census before the build: 46 functions under `src/` carry a
decorator, 39 of them something other than a lone bare static/classmethod. The
Makefile's `unmutatable()` docstring says "34 of the 40" — a measurement that
was true when written and is stale now. It is left as is (a different concern);
the inventory is the current list and the test keeps it current.

## Consequences

* A decorator added under `only_mutate` costs one inventory line in the same
  diff. 43 entries accumulated over the repository's whole life, so the
  expected cost is well under one line per pull request.
* Adding a method to a `@dataclass` costs the same line, and that is
  deliberate: the method has zero mutants, and the author should know.
* Renames and moves of decorated functions change the inventory. That churn is
  the wanted kind — the line travels with the code it describes.
* The guard runs in the merge-blocking `pytest (Python 3.12)` context. The
  binding test is marked `repo_introspection` (it imports mutmut and reads the
  working directory's `pyproject.toml`), so it is deselected inside mutmut's
  own copy; the other five tests are not, and read the real tree through
  `find_repo_root`.
* When mutmut starts mutating decorated functions, the binding test goes red,
  and the right response is to delete this module and the inventory: the
  charter's WHEN TO REMOVE line says so.

## Rejected alternatives

* **Floor the `[decorated]` count the Makefile's scope step already emits.**
  Named as the fix in ADR-0069's Open section, and rejected on measurement of
  what it can see: the note covers only functions whose lines changed in the
  `origin/main...HEAD` diff, so it is empty on `main` itself (a `count > 0`
  floor there fails by construction, ADR-0065's lesson), it lives in an
  advisory job, and it is blind to a decorator added in the same pull request
  that deletes the function's changed lines from scope. Kept as a log line.
* **Per-function mutant-count baseline, compared against the previous count.**
  Would also catch a body edit that shrinks the count, which the issue floated.
  Rejected: every legitimate edit to any function changes its count, so the
  file churns on every pull request; regenerating it costs 19 s of mutmut per
  run; and a reviewer trained to rubber-stamp count changes will rubber-stamp
  the one that matters.
* **Derive the inventory from mutmut on every test run, no AST mirror.**
  Exact by definition, and 19 s per run against 59 ms. The AST mirror is kept
  and the binding test keeps it honest.
* **Refuse decorators, as the pragma guard refuses pragmas.** Absurd for a
  population made of routes and validators.
* **Record the decorator's spelling or line number in the inventory.** Both
  churn without carrying information mutmut acts on — a route path tweak or an
  edit above the function would change the entry. The key is
  `module:qualname`; the failure message gives the reason.

## Related

* Issue #369; ADR-0069 decision 4 (the pragma route) and its Open section.
* `tests/unit/test_no_decorator_silences_a_mutation_surface.py`,
  `tests/unit/mutation_surface_inventory.txt`, registered in
  `tests/unit/test_gates_carry_a_charter.py`.
* `Makefile` `unmutatable()` in `MUTMUT_SCOPE_PY` and
  `scripts/replay_mutation_scope.py` carry the same predicate for the scope
  step; the guard does not import either, because the Makefile's copy is not
  importable and the binding test is the shared proof.
