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
``Module.collect()``, and the 13 per-operation items appear only when that node
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

REPO_ROOT = find_repo_root(Path(__file__))

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


@pytest.mark.repo_introspection
@pytest.mark.parametrize("name", ["GET /status", "plain"])
def test_a_plain_parametrized_id_with_a_space_is_a_real_case(name: str) -> None:
    """The POSITIVE PARTNER, and the refutation of the board's stated cause.

    This test exists to be SELECTED BY ITS OWN NODE ID below, proving a space
    is not what breaks selection. Without it, the claim "the space is not the
    cause" would rest on an argument instead of a run.
    """
    assert name


@pytest.mark.repo_introspection
def test_a_space_in_a_node_id_is_not_what_breaks_selection() -> None:
    """RED IF: the cause recorded in this module and on the board is wrong.

    Selects the plain parametrized case above — whose id contains the same
    ``GET /status`` text — by its full node id.
    """
    result = _collect(
        "tests/test_lazy_nodeid_selection.py"
        "::test_a_plain_parametrized_id_with_a_space_is_a_real_case[GET /status]"
    )
    assert result.returncode == 0, (
        f"a plain parametrized id containing a space failed to select, so the "
        f"board's original cause may be right after all:\n{result.stdout}\n{result.stderr}"
    )
    # pytest reports a filtered selection as "kept/total": the plugin keeps the
    # one case and deselects its sibling.
    assert "1/2 tests collected" in result.stdout, result.stdout


@pytest.mark.repo_introspection
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
    # EXACTLY one, not the whole function's 13. A superset would still let the
    # gate run, but it would also multiply every mutant's test time by 13 and
    # quietly change what "the tests that cover this mutant" means.
    assert "1/13 tests collected" in result.stdout, (
        f"expected exactly the requested case out of the function's thirteen, got:\n{result.stdout}"
    )
    assert "[GET /status]" in result.stdout, result.stdout


@pytest.mark.repo_introspection
def test_the_parent_function_still_selects_every_case() -> None:
    """POSITIVE PARTNER: the plugin must not narrow an unbracketed selection.

    RED IF: the rewrite leaks into ids that never needed it, so asking for the
    function gives one case instead of all of them.
    """
    result = _collect(SCHEMATHESIS_FUNCTION_ID)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "13 tests collected" in result.stdout, (
        f"the bare function id no longer collects every operation:\n{result.stdout}"
    )


@pytest.mark.repo_introspection
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
    assert "2/13 tests collected" in result.stdout, result.stdout
    assert "[GET /status]" in result.stdout and "[GET /ready]" in result.stdout, result.stdout


@pytest.mark.repo_introspection
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
    assert result.returncode != 0, (
        f"a node id naming a case that does not exist was accepted:\n{result.stdout}"
    )
    assert "GET /does-not-exist" in (result.stdout + result.stderr), (
        f"the failure does not name the id that was not found:\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.repo_introspection
def test_an_ordinary_unbracketed_selection_is_untouched() -> None:
    """The plugin must be invisible to every test that was already selectable.

    RED IF: the rewrite applies to arguments it has no business touching.
    """
    result = _collect("tests/test_lazy_nodeid_selection.py")
    assert result.returncode == 0, result.stdout + result.stderr
    # 8 = the six tests in this module plus the two-case parametrization of
    # the probe above. No "N/M" split, because nothing was rewritten.
    assert "8 tests collected" in result.stdout, (
        f"selecting this module by path no longer collects its own tests "
        f"untouched:\n{result.stdout}"
    )
