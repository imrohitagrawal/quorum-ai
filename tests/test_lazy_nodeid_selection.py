"""W23: a lazily-expanded test case must be selectable by its node id.

THE DEFECT. ``mutmut`` picks the tests that cover a changed function and
re-invokes pytest with their node ids. One of those ids is
``test_api_conforms_to_openapi_contract[GET /status]``, in
``tests/contract/test_api_contract_schemathesis.py``. pytest exited 4 on it —
``ERROR: not found`` — so ``mutmut`` raised
``BadTestExecutionCommandsException`` and the gate died BEFORE scoring a single
mutant. The gate is therefore blind to any diff touching a function reachable
from a documented endpoint, which is ``/status``, ``/ready``, ``/ui`` and
``/v1/*`` and everything under them. It fired again on PR #483.

THE CAUSE IS NOT THE SPACE IN THE ID, which is what the board said until this
change. MEASURED, under this repo's own pytest config: a plain parametrized id
containing a space selects fine (this module proves it below). What fails is a
node id whose case is produced by a LAZILY EXPANDED collector: schemathesis
returns ONE node named ``test_api_conforms_to_openapi_contract`` from
``Module.collect()``, and the 15 per-operation items appear only when that node
is expanded afterwards. pytest resolves a node id by matching the requested
name against the module's DIRECT children, so a bracketed schemathesis id never
matches. An ordinary parametrized test works because ``Metafunc`` puts its
parametrized ``Function`` items directly under the module.

THE FIX (``tests/lazy_nodeid_selection.py``): rewrite such an argument to its
parent function id before collection, then keep exactly the requested items
afterwards. It is not an exemption and not a superset — the named case runs,
and only it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.repo_root import find_repo_root
from tests.subprocess_env import env_without_coverage

REPO_ROOT = find_repo_root(Path(__file__))

#: MODULE-LEVEL, deliberately. Every test here spawns pytest against the real
#: REPO_ROOT, so it cannot run inside mutmut's ``./mutants/`` copy and can kill
#: no ``src/`` mutant. The first version carried the marker on each function
#: instead, which is invisible to ``test_the_deselected_set_is_exactly_the_pinned_set``
#: in ``tests/unit/test_mutation_test_set_integrity.py`` — that guard reads
#: MODULE-level markers — so this module exempted itself
#: from the mutation oracle without appearing in the pinned list. Found in
#: review, together with the commit body's false claim that no test was
#: exempted. It is pinned there now, with this reason.
pytestmark = pytest.mark.repo_introspection

#: The real, previously unselectable id. Chosen because ``GET /status`` is the
#: operation the gate actually tripped over on PR #476 and again on PR #483.
SCHEMATHESIS_CASE_ID = (
    "tests/contract/test_api_contract_schemathesis.py"
    "::test_api_conforms_to_openapi_contract[GET /status]"
)
SCHEMATHESIS_FUNCTION_ID = (
    "tests/contract/test_api_contract_schemathesis.py::test_api_conforms_to_openapi_contract"
)


def _collect(*args: str) -> subprocess.CompletedProcess[str]:
    """Run pytest --collect-only in a subprocess, from the repo root.

    A subprocess, not an in-process ``pytest.main``: the thing under test is
    argument resolution at STARTUP, which an in-process run cannot reproduce
    faithfully (the plugin is loaded by the outer run already).
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *args,
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("name", ["GET /status", "plain"])
def test_a_plain_parametrized_id_with_a_space_is_a_real_case(name: str) -> None:
    """The POSITIVE PARTNER, and the refutation of the board's stated cause.

    This test exists to be SELECTED BY ITS OWN NODE ID below, proving a space
    is not what breaks selection. Without it, the claim "the space is not the
    cause" would rest on an argument instead of a run.
    """
    assert name


def test_a_space_in_a_node_id_is_not_what_breaks_selection(tmp_path: Path) -> None:
    """RED IF: the cause recorded in this module and on the board is wrong.

    THE PROBE LIVES OUTSIDE ``tests/`` ON PURPOSE. Inside it, this plugin
    rewrites the id and filters afterwards, so a pass would prove only that the
    plugin works — which is not the claim. Review caught exactly that: the
    first version asserted ``1/2 tests collected``, and that ``N/M`` split IS
    the plugin's own deselection. Outside the conftest's scope nothing
    rewrites anything, so ``1 test collected`` with no split is native pytest
    resolving a node id whose parameter contains a space.
    """
    probe = tmp_path / "test_space_id_probe.py"
    probe.write_text(
        "import pytest\n\n"
        '@pytest.mark.parametrize("name", ["GET /status", "plain"])\n'
        "def test_space(name):\n    assert name\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"{probe}::test_space[GET /status]",
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        # This child runs OUTSIDE the repository, so pytest-cov's subprocess
        # hooks would resolve the relative ``--cov=src`` against tmp_path and
        # fold a foreign tree into a REQUIRED gate's denominator (#368).
        env=env_without_coverage(),
    )
    assert result.returncode == 0, (
        f"NATIVE pytest failed to select a parametrized id containing a space, "
        f"so the board's original cause may be right after all:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    # No "N/M" split: nothing was deselected, because no plugin was involved.
    assert "1 test collected" in result.stdout, result.stdout
    assert "1/2" not in result.stdout, (
        f"something filtered this selection, so it is not a measurement of "
        f"native pytest:\n{result.stdout}"
    )


def test_a_schemathesis_case_is_selectable_by_its_node_id() -> None:
    """RED IF: the lazy-node-id plugin stops resolving schemathesis ids.

    This is W23 itself. Before the fix this command exited 4 with
    ``ERROR: not found: ...[GET /status]`` and ``(no match in any of [<Module
    test_api_contract_schemathesis.py>])``.
    """
    result = _collect(SCHEMATHESIS_CASE_ID)
    assert result.returncode == 0, (
        f"selecting one schemathesis case by node id still fails — the mutation "
        f"gate cannot run on any diff a documented endpoint covers:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    # EXACTLY one, not the whole function's 15. A superset would still let the
    # gate run, but it would also multiply every mutant's test time by 15 and
    # quietly change what "the tests that cover this mutant" means.
    assert "1/15 tests collected" in result.stdout, (
        f"expected exactly the requested case out of the function's fifteen, got:\n{result.stdout}"
    )
    assert "[GET /status]" in result.stdout, result.stdout


def test_the_parent_function_still_selects_every_case() -> None:
    """POSITIVE PARTNER: the plugin must not narrow an unbracketed selection.

    RED IF: the rewrite leaks into ids that never needed it, so asking for the
    function gives one case instead of all of them.
    """
    result = _collect(SCHEMATHESIS_FUNCTION_ID)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "15 tests collected" in result.stdout, (
        f"the bare function id no longer collects every operation:\n{result.stdout}"
    )


def test_two_schemathesis_cases_select_together() -> None:
    """The gate passes MANY ids at once, so one-at-a-time is not enough.

    RED IF: the plugin keeps only the last requested id, or drops items that
    belong to a second rewritten argument.
    """
    second = (
        "tests/contract/test_api_contract_schemathesis.py"
        "::test_api_conforms_to_openapi_contract[GET /ready]"
    )
    result = _collect(SCHEMATHESIS_CASE_ID, second)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2/15 tests collected" in result.stdout, result.stdout
    assert "[GET /status]" in result.stdout and "[GET /ready]" in result.stdout, result.stdout


def test_a_typo_in_a_lazy_id_still_fails_loudly() -> None:
    """THE VACUITY GUARD, and the one that matters most.

    A plugin that rewrote a bad id to its parent function would turn a typo
    into a silent full-function run — the test the caller named would never
    run, and pytest would report success. That is the failure mode this whole
    change could introduce, so it is pinned.

    RED IF: an unknown case id is swallowed instead of refused.
    """
    result = _collect(
        "tests/contract/test_api_contract_schemathesis.py"
        "::test_api_conforms_to_openapi_contract[GET /does-not-exist]"
    )
    # EXIT 4, not merely non-zero. Review demonstrated that replacing the
    # UsageError with ``warnings.warn`` empties the item list instead, pytest
    # exits 5 ("no tests collected"), and a "!= 0" assertion still passes —
    # while mutmut reads 5 as "no tests", a different verdict from a refusal.
    assert result.returncode == 4, (
        f"expected pytest's usage-error exit 4, got {result.returncode}:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    output = result.stdout + result.stderr
    assert "no test matched the requested case id(s)" in output, (
        f"the refusal is not the plugin's own, so something else failed:\n{output}"
    )
    assert "GET /does-not-exist" in output, (
        f"the failure does not name the id that was not found:\n{output}"
    )


def test_an_ordinary_unbracketed_selection_is_untouched() -> None:
    """The plugin must be invisible to every test that was already selectable.

    RED IF: the rewrite applies to arguments it has no business touching.
    """
    result = _collect("tests/test_lazy_nodeid_selection.py")
    assert result.returncode == 0, result.stdout + result.stderr
    # 12 = the eleven tests in this module plus the second case of the
    # parametrized probe. No "N/M" split, because nothing was rewritten.
    assert "12 tests collected" in result.stdout, (
        f"selecting this module by path no longer collects its own tests "
        f"untouched:\n{result.stdout}"
    )


def test_a_sibling_whose_name_extends_a_rewritten_one_is_not_deselected() -> None:
    """A rewritten ``path::test_alpha`` must not swallow ``path::test_alpha_extra``.

    The filter decides which items "came from" a rewritten argument. Matching
    that by raw string prefix made ``test_alpha_extra`` look like one of
    ``test_alpha``'s cases, so a sibling requested by its OWN argument was
    deselected silently — a test the caller asked for, not run, no error.
    Review demonstrated it with a failing sibling: the run reported success.

    There is no such pair anywhere else in the suite (censused in review: 0 of
    4561 node ids), which is why ``tests/test_w23_sibling_probe.py`` exists.

    RED IF: the boundary check goes back to ``node_id.startswith(parents)``.
    """
    result = _collect(
        "tests/test_w23_sibling_probe.py::test_alpha[a]",
        "tests/test_w23_sibling_probe.py::test_alpha_extra",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # The "N/M" split is the proof the plugin was in play at all: one of the
    # three items (``test_alpha[b]``) is deselected, and the sibling survives.
    assert "2/3 tests collected" in result.stdout, (
        f"expected the plugin to filter this selection; without the split it "
        f"never ran and this test proves nothing:\n{result.stdout}"
    )
    assert "test_alpha_extra" in result.stdout, (
        f"the sibling requested by its own argument was deselected:\n{result.stdout}"
    )


def test_two_runs_in_one_process_do_not_leak_requested_ids() -> None:
    """THE SHAPE ``mutmut`` ACTUALLY USES, and the defect review caught.

    ``mutmut`` calls ``pytest.main`` IN-PROCESS for its clean run over the
    union of every mutant's tests, then forks one child per mutant. The first
    version of this plugin kept the requested ids in a MODULE GLOBAL, so the
    second run in the same process — and every forked child — asked for ids it
    had never requested, got a ``UsageError`` and exited 4.

    What that cost, measured on the real gate before the fix: mutmut recorded
    those mutants as crashes and dropped them from the denominator, so the gate
    printed ``42 killed, 0 survived``, ``100.0%``, exit 0 on a diff whose
    honest score was ``52 killed, 24 survived`` = ``68.4%``, BELOW THRESHOLD,
    exit 2. A false pass on the gate whose whole job is to prove the tests
    bite.

    RED IF: the requested ids stop being per-run state (a module global, a
    class attribute, an lru_cache — anything a second ``pytest.main`` in the
    same process can see). MEASURED with the global restored: RC2 = 4 with
    "no test matched the requested case id(s)" naming the FIRST run's id.
    """
    script = (
        "import pytest\n"
        f"rc1 = pytest.main([{SCHEMATHESIS_CASE_ID!r}, '--collect-only', '-q', '--no-cov',\n"
        "                   '-p', 'no:randomly', '-p', 'no:cacheprovider'])\n"
        "rc2 = pytest.main(['tests/unit/test_feedback_audit.py', '--collect-only', '-q',\n"
        "                   '--no-cov', '-p', 'no:randomly', '-p', 'no:cacheprovider'])\n"
        "print('RC1', rc1, 'RC2', rc2)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert "RC1 0 RC2 0" in result.stdout, (
        "a second pytest run in the same process saw the first run's requested "
        f"ids — this is how the gate reported a false pass:\n{result.stdout}\n{result.stderr}"
    )
    # POSITIVE PARTNER: the first run really did filter, so RC1 == 0 is not
    # "the plugin did nothing".
    assert "1/15 tests collected" in result.stdout, result.stdout


def test_only_the_requested_case_actually_RUNS() -> None:
    """Collection is not execution, and this file was asserting the wrong one.

    Every other test here reads the ``N/M tests collected`` summary from
    ``--collect-only``. Review demonstrated that deleting ``items[:] = kept``
    — so the filter reports a deselection and then runs everything anyway —
    survives all of them: collection prints ``1/15 tests collected``, while a
    real run prints ``15 passed, 14 deselected``. That is the substring-vs-
    structure trap of rule 8 inside the guard meant to prevent it, and it is
    exactly the every-case-per-mutant outcome ADR-0117 rejected.

    RED IF: the filter stops being applied to the items pytest executes.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            SCHEMATHESIS_CASE_ID,
            "-q",
            "--no-cov",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    # ONE test ran. The other fourteen were deselected, not executed.
    assert "1 passed" in result.stdout, (
        f"expected exactly the requested case to run:\n{result.stdout[-3000:]}"
    )
    assert "14 deselected" in result.stdout, result.stdout[-3000:]
    assert "15 passed" not in result.stdout, (
        f"the whole function ran — the filter reported a deselection it did not "
        f"apply:\n{result.stdout[-3000:]}"
    )


def test_an_absolute_case_id_still_selects() -> None:
    """A human or an IDE passes absolute paths; pytest used to accept them.

    Items carry rootdir-relative node ids, so comparing the requested id as a
    raw string made an absolute id match nothing and raised the plugin's own
    UsageError — a selection that worked before this plugin existed. Found in
    review.

    RED IF: the absolute-path normalisation in ``_requested`` is removed.
    """
    absolute = str(REPO_ROOT / SCHEMATHESIS_CASE_ID)
    result = _collect(absolute)
    assert result.returncode == 0, (
        f"an absolute node id no longer selects:\n{result.stdout}\n{result.stderr}"
    )
    assert "1/15 tests collected" in result.stdout, result.stdout
