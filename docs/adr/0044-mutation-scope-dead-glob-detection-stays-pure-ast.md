# ADR-0044: Dead-glob detection in the mutation scope stays pure-`ast`, not `mutmut` internals

## Status

Accepted — 2026-08-14 (#146)

## Context

#136/#144 fixed the mutation gate's `scope()` (the `MUTMUT_SCOPE_PY` block in
the Makefile) so a changed **decorated** function is excluded and reported
instead of silently naming a mutmut mutant-name glob that matches zero
mutants (`mutmut run` then dies with "Filtered for specific mutants, but
nothing matches", and the recipe blames `also_copy` — the wrong cause).

#146 measured two more classes of dead glob, both real, not decoration:

1. **Nested functions.** mutmut attributes every mutation inside a `def`
   nested inside another `def` — at any depth, including inside a class
   method — to the SAME enclosing **top-level** name
   (`mutmut/mutation/file_mutation.py::OuterFunctionProvider`). Naming the
   nested function's own name produces a glob nothing matches.
2. **No mutable content.** Some changed functions have nothing any mutmut
   operator can touch at all: `return _store`, a `...` stub, an `IfExp` over
   bare names, a zero-arg call chain, a pure f-string, a comprehension over
   safe sub-expressions.

Fixing (2) requires knowing, for a given function body, whether mutmut's real
operator table (`mutmut/mutation/mutators.py::mutation_operators`) would
produce at least one mutant. Two ways to answer that:

- **A.** Call mutmut's own libcst-based `create_mutations()` (mutation
  *generation* only — no test execution, ~20ms/file measured) and read
  `Mutation.contained_by_top_level_function` off the real result.
- **B.** Write a static `ast`-only predicate that mirrors the parts of
  `mutation_operators` this repo's dead functions actually exercise.

## Decision

**B. `no_mutable_content()`/`_safe_expr()` are pure stdlib `ast`, calling
nothing from `mutmut`.** They mirror `mutation_operators` by hand for the
node shapes measured on this tree (name/attribute chains, `None`/`...`, a
zero-arg call, `IfExp`, a pure f-string via `ast.JoinedStr` with a
`tokenize`-based check for an implicitly-concatenated plain string segment,
and `DictComp`/`ListComp`/`SetComp`/`GeneratorExp` over safe sub-expressions)
and **fail closed**: any expression or statement shape not explicitly
recognised keeps the function in scope rather than risking a false exclusion.

## Why not A

- `MUTMUT_SCOPE_PY` runs under `$(PYTHON)` — plain system `python3`, deliberately
  **not** `uv run python` — so the script works before `uv sync` and has no
  runtime dependency on the `quality` extra (`mutmut`/`libcst` are dev-only,
  never shipped in the Docker image, per `pyproject.toml`'s C14 comment).
  Depending on `create_mutations()` would mean either switching the whole
  scope step to `uv run python` (a bigger, unrelated change to a recipe two
  lines away from an existing `uv run mutmut` call, but still a scope change
  to a script whose entire design point until now was "no uv, no venv, just
  stdlib") or duplicating mutmut's private internals into the Makefile
  anyway.
- `create_mutations` and `mutation_operators` are **not** part of `mutmut`'s
  public API (nothing re-exports them from `mutmut/__init__.py`). Pinning the
  gate's correctness to an internal module path is a silent-break risk on
  any future `mutmut` release inside the `>=3.0.0,<4.0` range this repo
  already allows.
- The fail-closed design means B's failure mode is **the status quo** (a
  still-dead glob, same as before #146) rather than a new one. A's failure
  mode on an internal-API break would be an import error that aborts the
  gate outright, or (worse, silently) a `contained_by_top_level_function`
  shape change that mis-maps names the same way the original bug did.

## Consequences

- **Under-detection is expected and acceptable.** A function shape not yet
  in `_safe_expr`'s allowlist stays in scope even if it is truly dead;
  the failure mode is the same "matches nothing" abort #136/#144 already
  handle, not a regression.
- **Verified once, not enforced continuously.** Correctness against the real
  `mutmut` was established by cross-checking `no_mutable_content()`'s
  decisions against a live `create_mutations()` run over every file in
  `src/product_app` (0 remaining dead globs, 0 false exclusions, measured
  2026-08-14) — a one-time measurement, not a gate. A future `mutmut`
  release changing `mutation_operators` could silently invalidate this
  mirror without any test in this repo catching it; re-run the same
  cross-check after any `mutmut` version bump.
- If a THIRD class of dead glob is found, extend `_safe_expr`/
  `no_mutable_content` with the same fail-closed discipline, or revisit this
  decision if the hand-mirrored operator table becomes too large to trust.
