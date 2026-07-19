"""The contract gate's floor must sit above every single contract module.

`CONTRACT_MIN_TESTS` cannot be pinned to the exact collected count the way
`PERF_MIN_TESTS` is: schemathesis parametrises off the live OpenAPI schema, so
the count legitimately moves with the API surface. But "deliberately slack" is
not the same as "arbitrary" — the floor still has to do the one job it is
documented to do, which is fail when a contract suite is deleted or emptied.

A floor of 10 did not do that job. `tests/contract` collects 23 = 17
schemathesis + 6 hand-authored OpenAPI cases, so deleting the hand-authored
module left 17 >= 10 and `api-contract` stayed green with nothing asserting the
response schemas. The floor therefore has to exceed the *largest* single
module, which is measured here rather than copied into a constant.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

CONTRACT_MODULES = (
    "tests/contract/test_api_contract_schemathesis.py",
    "tests/contract/test_openapi_contract.py",
)


def _make_variable(name: str) -> str:
    """Read a `NAME ?= value` assignment out of the Makefile."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\s*\?=\s*(.+)$", text, flags=re.MULTILINE)
    assert match, f"{name} is not defined in the Makefile"
    return match.group(1).strip()


def _collected_count(paths: str) -> int:
    """Collect exactly as `gate-min-collected` does, and count the same way."""
    result = subprocess.run(
        ["uv", "run", "pytest", *paths.split(), "-q", "--no-cov", "--collect-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SENTRY_DSN": "",
            "OPENROUTER_LIVE_EXECUTION_ENABLED": "false",
            "QUORUM_RUNTIME_ENVIRONMENT": "ci",
        },
    )
    assert result.returncode == 0, f"contract collection failed:\n{result.stdout}"
    return sum(1 for line in result.stdout.splitlines() if "::" in line)


@pytest.fixture(scope="module")
def contract_floor() -> int:
    return int(_make_variable("CONTRACT_MIN_TESTS"))


def test_contract_floor_is_reachable(contract_floor: int) -> None:
    collected = _collected_count(_make_variable("CONTRACT_TEST_PATHS"))
    assert contract_floor <= collected, (
        f"CONTRACT_MIN_TESTS is {contract_floor} but tests/contract collects "
        f"{collected}: api-contract cannot pass at all."
    )


@pytest.mark.parametrize("module", CONTRACT_MODULES)
def test_contract_floor_bites_when_a_module_is_deleted(contract_floor: int, module: str) -> None:
    surviving = _collected_count(module)
    assert contract_floor > surviving, (
        f"CONTRACT_MIN_TESTS is {contract_floor}, but {module} alone collects "
        f"{surviving} — deleting the other contract module would leave "
        "api-contract green while that half of the contract goes unasserted."
    )
