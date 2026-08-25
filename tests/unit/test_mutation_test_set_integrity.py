"""Guards on WHICH TESTS the mutation gate is allowed to use as its oracle.

`test_mutation_gate_integrity.py` guards the scoring arithmetic.
`test_mutation_gate_blocking.py` guards the two advisory switches.
This module guards the thing both of those assume: that the set of tests
deselected from the mutant run is a small, reviewed, deliberately-chosen list —
not something a developer can extend to make their own change unmeasurable.

**The evasion this exists to stop**, found by an adversarial red-team pass on
the #130 promotion and CONFIRMED by a real `mutmut run`:

    mutmut deselects markers listed in [tool.mutmut].pytest_add_cli_args when it
    builds `tests_by_mangled_function_name`. A mutant with no covering test is
    recorded as exit code 33 = `no_tests`, and `no_tests` is EXCLUDED from the
    score's denominator. So deselecting the only tests that cover a function
    does not make its mutants survive — it deletes them from the score.

    Measured on a scratch tree: identical source, one added marker line.
      before:  7 killed, 4 survived, 0 no-tests →  63.6%  BELOW THRESHOLD, exit 1
      after:   2 killed, 0 survived, 9 no-tests → 100.0%  pass,            exit 0

One line, and a red gate is green — while `--cov-fail-under` and `diff-cover`
see no change at all, because the test still runs in the ordinary suite.

Two independent guards, because either alone is evadable:

1. **The deselected set is pinned** (below). Adding a ninth module is an
   explicit edit to this file that a reviewer sees, exactly as
   `PERF_REQUIRED_SPECS` pins the perf gate's load-bearing specs.
2. **`no_tests > 0` fails the run** (`report()` in the Makefile, guarded in
   `test_mutation_gate_integrity.py`). That closes the same hole from the other
   end: however a function loses its oracle — this marker, `env_oracle`, a
   `--ignore` path, or simply never having had a test — the gate says so
   instead of quietly shrinking its own denominator.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from tests.repo_root import find_repo_root

#: The REAL repository root, not ``parents[2]``.
#:
#: mutmut runs this suite from inside ``./mutants/``, where ``parents[2]`` is
#: the copy. ``test_the_decorated_function_blind_spot_is_recorded`` then walked
#: ``mutants/src/product_app`` — which carries one generated ``x_<name>__mutmut_N``
#: variant per mutant — and counted **514** decorated functions against a
#: threshold of 55. With ``-x`` in force that killed collection, so the gate
#: exited non-zero having scored no mutant at all, on every pull request that
#: touched ``src/`` Python (#158). See ``tests/repo_root.py``.
REPO_ROOT = find_repo_root(Path(__file__))
TESTS_DIR = REPO_ROOT / "tests"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Every module deselected from the mutant run by `repo_introspection`, pinned.
#:
#: Each one drives `git`, `make` or `pytest` against the real ``REPO_ROOT``,
#: which does not exist inside mutmut's ``./mutants/`` copy — measured when the
#: list held 8 entries: with those 8 present the suite failed 41 times in the
#: copy and mutmut aborted at
#: "failed to collect stats" before scoring a single mutant; with them
#: deselected the copy runs 1660 passed / 0 failed and the gate completes.
#:
#: They still run BLOCKING in the ordinary suite. Deselection here removes them
#: only from the set of tests mutmut may use to kill a mutant.
#:
#: **Adding to this list is a reviewed decision, never a convenience.** Before
#: adding one, check it cannot kill a `src/` mutant — if it can, the honest fix
#: is to make the test hermetic, not to exempt it.
DESELECTED_FROM_THE_MUTANT_RUN = (
    "tests/test_findings_ledger_consistency.py",
    "tests/unit/test_contract_gate_collection_floor.py",
    "tests/unit/test_e2e_flake_policy.py",
    "tests/unit/test_makefile_gate_integrity.py",
    "tests/unit/test_mutation_copy_completeness.py",
    # Drives git and pytest against the real repository and copies it twice per
    # test, across two such tests — FOUR full project copies per suite run
    # (measured by counting `_copy_project` calls). It imports nothing from the
    # application, so it can kill no `src/` mutant; and left selected it would
    # build those four copies per MUTANT against a 1440-second deadline
    # (Makefile MUTATION_RUN_DEADLINE_SECONDS), which is the "gate produces no
    # number" outcome it exists to prevent.
    "tests/unit/test_mutation_gate_root_resolution.py",
    "tests/unit/test_perf_gate_collection_floor.py",
    "tests/unit/test_perf_gate_required_specs.py",
    "tests/unit/test_perf_gate_runs_clean.py",
    "tests/unit/test_negative_assertion_guard.py",
    # Runs `test_negative_assertion_guard.py` as a child pytest against the real
    # REPO_ROOT (ADR-0058). That path does not exist inside mutmut's ./mutants/
    # copy, and the module touches no `src/` code, so it can kill no mutant.
    "tests/unit/test_guard_suite_is_not_skipped.py",
    "tests/unit/test_replay_mutation_scope.py",
    "tests/unit/test_replay_scope_matches_makefile_scope.py",
    # #368. Parses every file under the real `tests/` and shells out to TWO
    # nested `pytest --cov=src` runs over the real `src/`. Inside
    # `./mutants/` it would parse the COPY, and the nested runs would be
    # paid once per MUTANT. It imports nothing from the application — the
    # only non-stdlib names it binds are `pytest`, `tests.repo_root` and
    # `tests.subprocess_env` — so it can kill no `src/` mutant.
    "tests/unit/test_subprocess_env_hygiene.py",
    # ``rglob``s ``e2e/tests`` and reads every ``.github/workflows/*.yml``, so
    # inside ``./mutants/`` it measures the COPY. ``[tool.mutmut].also_copy``
    # includes ``e2e/tests``, which carries the GITIGNORED ``e2e/tests/review/``
    # scratch specs (AGENTS.md rule 13a) into that copy; no workflow references
    # them, so this module failed there and ``-x`` killed stats collection —
    # "failed to collect stats. runner returned 1", 83 seconds in, ZERO mutants
    # scored (measured 2026-08-20 on a real 3-function scope, #337). It imports
    # only ``re``/``pathlib``/``pytest`` and names ``product_app`` nowhere, so it
    # can kill no ``src/`` mutant.
    "tests/unit/test_no_orphaned_e2e_specs.py",
    # #365. Reads the repository's own `src/` as TEXT and re-runs mutmut's
    # mutator over it. It names no `product_app` import of its own, but that is
    # NOT the reason it is safe and an earlier version of this comment wrongly
    # said it imported nothing: `exec`ing the file's source runs that file's own
    # module-level imports, which adversarial review traced to 15 `product_app`
    # modules and 8 mutatable functions called at import time. What actually
    # settles it is that it reaches the function it guards by `exec`ing the
    # source into a FRESH namespace. mutmut's trampoline replaces the function
    # ON THE MODULE
    # OBJECT, and an `exec`'d copy does not see that replacement. Demonstrated
    # 2026-08-25: with `synthesis_consensus._stance_majority_flags` swapped for
    # a stand-in, the `exec`'d copy still ran the ORIGINAL body and was `is not`
    # the module attribute. So this module cannot register a kill for the very
    # function it guards, and deselecting it removes no kill from the score.
    # Left selected it would also re-mutate a 391-mutant file every time mutmut
    # used it as an oracle, against a 1440-second deadline.
    "tests/unit/test_stance_majority_flags_has_no_equivalent_mutants.py",
    # #365. Tokenises every file under the real `src/` looking for
    # `# pragma: no mutate`, and parses `pyproject.toml`. Inside `./mutants/`
    # that tree carries one generated `x_<name>__mutmut_N` variant per mutant,
    # so a census of it measures the copy — the #158 shape exactly. Its own body
    # only ever reads file text; the 12 `product_app` calls adversarial review
    # traced under it all come from conftest AUTOUSE fixtures (store setup and
    # teardown), which every module in the suite pays and which no module kills
    # a mutant with. So it can register no `src/` kill of its own.
    "tests/unit/test_no_mutation_pragma_silences_a_survivor.py",
)

MARKER = "repo_introspection"


def _module_level_markers(path: Path) -> set[str]:
    """Marker names in a module-level ``pytestmark`` assignment.

    Parsed with ``ast`` rather than grepped: this module's own docstring quotes
    the marker name, and `test_makefile_gate_integrity.py` embeds
    ``pytestmark = pytest.mark.skip(...)`` inside a string literal it writes to
    a temp file. A substring search reports both as marked. Neither is.
    """
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        for attr in ast.walk(node.value):
            if isinstance(attr, ast.Attribute):
                names.add(attr.attr)
    return names


def _marked_modules() -> list[str]:
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for path in TESTS_DIR.rglob("test_*.py")
        if MARKER in _module_level_markers(path)
    )


def test_the_pin_is_not_empty() -> None:
    """A pinned list of nothing would make every assertion below vacuous.

    `all([])` being True is how F-06's cost gate went vacuous; the same shape
    here would let the whole guard pass over an empty repository.

    Turns red if: DESELECTED_FROM_THE_MUTANT_RUN is emptied.
    """
    assert len(DESELECTED_FROM_THE_MUTANT_RUN) >= 8
    assert TESTS_DIR.is_dir()
    assert list(TESTS_DIR.rglob("test_*.py")), "no test modules found — the glob is wrong"


def test_the_deselected_set_is_exactly_the_pinned_set() -> None:
    """No module may quietly exempt itself from the mutation gate's oracle.

    Turns red if: `pytestmark = pytest.mark.repo_introspection` is added to any
    module not named above (verified by adding it to a 9th), or removed from
    one that is named.
    """
    actual = _marked_modules()
    expected = sorted(DESELECTED_FROM_THE_MUTANT_RUN)

    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    assert not added, (
        f"these modules deselected themselves from the mutant run without being "
        f"added to the pinned list in {Path(__file__).name}: {added}. A module "
        "marked this way can no longer kill a mutant, so its coverage silently "
        "leaves the mutation score. If the exemption is genuine, add it here "
        "with the reason; if not, make the test hermetic instead."
    )
    assert not removed, (
        f"the pinned list names modules that are no longer marked: {removed}. "
        "Delete them from the pin if that was deliberate."
    )


def test_every_pinned_module_actually_exists() -> None:
    """A pin naming a deleted file rots into a comment.

    Turns red if: a pinned module is renamed or deleted without updating the pin.
    """
    missing = [name for name in DESELECTED_FROM_THE_MUTANT_RUN if not (REPO_ROOT / name).is_file()]
    assert not missing, f"pinned modules that do not exist: {missing}"


def test_the_decorated_function_blind_spot_is_recorded() -> None:
    """mutmut 3.6.0 cannot mutate most decorated functions.

    Measured live against `@property api_docs_enabled`: the scope names the
    glob, mutmut matches nothing, and the run dies with

        AssertionError: Filtered for specific mutants, but nothing matches

    surfaced to the author as the recipe's "missing from also_copy" message,
    which is the wrong cause. mutmut skips a decorated function unless its ONLY
    decorator is a bare @staticmethod/@classmethod
    (mutmut/mutation/file_mutation.py:230-235). Of the 40 decorated functions
    under src/product_app, 34 are unmutatable — every FastAPI route, every
    Pydantic validator. Replayed over history: **7%** of pull requests with a
    non-empty scope would abort this way, and **38%** have unmutatable
    functions silently unmeasured.

    This is the single biggest reason the gate is advisory rather than
    blocking, so the count is pinned. If it moves, the study's §3.2 numbers are
    stale and must be re-measured before anyone argues for promotion again.

    Turns red if: decorated functions are added or removed in bulk, or someone
    fixes the underlying issue (mutmut #387) and the blind spot shrinks —
    both of which should force a re-read of the study.
    """
    decorated = []
    for path in sorted((REPO_ROOT / "src" / "product_app").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.decorator_list:
                decorated.append(f"{path.name}:{node.name}")

    assert decorated, "no decorated functions found — the walk is wrong"
    assert 30 <= len(decorated) <= 55, (
        f"{len(decorated)} decorated functions under src/product_app; the study "
        "(docs/metrics/mutation-gate-study.md §3.2) measured 40 and derived a 7% "
        "false-abort rate from it. Re-measure with "
        "scripts/replay_mutation_scope.py before relying on that number"
    )


def test_the_marker_is_registered_and_deselected_under_mutmut() -> None:
    """The pin means nothing unless mutmut actually honours the marker.

    Turns red if: `repo_introspection` is dropped from
    `[tool.mutmut].pytest_add_cli_args` (the modules would then run inside
    ./mutants/ and abort the gate) or from `[tool.pytest.ini_options].markers`
    (pytest treats an unregistered marker as an error under `--strict-markers`
    and as a silent typo without it).
    """
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith(f"{MARKER}:") for m in markers), (
        f"{MARKER} is not registered in [tool.pytest.ini_options].markers: {markers}"
    )

    args = config["tool"]["mutmut"]["pytest_add_cli_args"]
    selector = args[args.index("-m") + 1]
    assert f"not {MARKER}" in selector, (
        f"mutmut no longer deselects {MARKER}, so these modules run inside "
        f"./mutants/ and abort the gate at stats collection: {selector!r}"
    )
    # Positive partner: the pre-existing deselection must still be there too, so
    # this assertion is not passing over a selector that was rewritten wholesale.
    assert "not env_oracle" in selector, f"env_oracle deselection was lost: {selector!r}"
