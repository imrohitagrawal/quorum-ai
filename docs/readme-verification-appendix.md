# README verification appendix

The main [README.md](../README.md) states its claims plainly and links here for
the proof. This file exists so the README reads fast without hiding *how* each
claim was checked — every command below was actually run against this repo,
not inferred from a comment or docstring.

## Test counts (the "2,896 total tests" line)

`uv run pytest -q` on a clean checkout with no `.env`:
```
2841 passed, 55 skipped, 95.05% coverage
```
On a machine with `QUORUM_TEST_LIVE_CREDENTIALS=1` and the optional Tavily /
eval-judge keys set:
```
2885 passed, 11 skipped, 95.05% coverage
```
Same total (2,896), same coverage, different split — `tests/conftest.py`
blanks live-provider credentials by default and a handful of tests key their
skip condition off that flag. Neither number is "the" count; report whichever
your own run shows, the total and coverage are what's stable.

The 7 failures you may see locally under
`tests/unit/test_no_orphaned_e2e_specs.py` come from `e2e/tests/review/` —
gitignored scratch Playwright specs (`git check-ignore e2e/tests/review`
confirms they're untracked) that exist on disk but run in no CI workflow. The
gate walks the filesystem, finds them, and fails outside CI. Not a regression.

## `cheapest_per_vendor` is unwired

```
$ grep -rn "cheapest_per_vendor(" src/
src/product_app/catalog_fetcher.py:464:    def cheapest_per_vendor(
$ grep -rn "_is_unauthenticated_variant(" src/
src/product_app/model_slots.py:378:def _is_unauthenticated_variant(model_id: str) -> bool:
```
Both only return their own definition — no caller anywhere in `src/`. Both
are fully unit-tested in isolation. `catalog_fetcher.py`'s own module
docstring describes this pair as feeding "the four families the UI [...]
uses," but nothing wires them together today; `DEFAULT_MODEL_IDS` is the
actual default, confirmed live by `tests/integration/test_model_slot_configuration.py::test_replacement_model_slots_are_persisted_with_query_run`,
which submits a fifth, non-default model id and gets it back unchanged.

## Why the per-slot-failure behavior changed

Issue [#171](https://github.com/imrohitagrawal/quorum-ai/issues/171) —
"Simulated answers are substituted per model and fed to debate, synthesis,
agreement and source coverage as real" — is why a failed *individual* live
call now reports a failed slot instead of silently substituting simulated
text. A comment in `model_slots.py` on `_is_unauthenticated_variant`
predates that fix and still describes the old (pre-#171) collapse-into-
`local_simulation` behavior; it does not describe current behavior.

## The startup smoke-probe

Commit `b42f0aa` added the readiness probe that surfaces a flag/key mismatch
at `/ready` and at process start, rather than only at the first live request.
