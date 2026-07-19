"""RB-7's ledger row must name the extra mutmut is *actually* declared in.

The existing ledger gates check status tokens and cited paths; none of them
checks *tool placement*, so the RB-7 row was free to say "mutmut in the dev
extra" while `pyproject.toml` deliberately keeps it in a separate ``quality``
extra — with an explicit comment that it is "not in ``dev``" so the runtime
image never ships a mutation engine or a fuzzer. That single word encodes a
supply-chain decision, and the ledger is the designated work list: a session
following it runs ``uv sync --extra dev``, gets no mutmut/schemathesis/
diff-cover, and sees `make mutation-baseline` fail for an invisible reason —
or, worse, "reconciles" pyproject.toml *to* the ledger and silently moves the
mutation engine into the runtime dependency set.

The source of truth here is `pyproject.toml` itself, not a hardcoded name, so
the test keeps holding if the extra is ever renamed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "docs" / "analysis" / "R2-plan-review-findings.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
METRIC_DOC = REPO_ROOT / "docs" / "metrics" / "mutation-baseline.md"


@pytest.fixture(scope="module")
def extras() -> dict[str, list[str]]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    found: dict[str, list[str]] = data["project"].get("optional-dependencies", {})
    return found


@pytest.fixture(scope="module")
def mutmut_extra(extras: dict[str, list[str]]) -> str:
    """The one optional-dependencies extra that declares mutmut."""
    owners = [
        name
        for name, specs in extras.items()
        if any(spec.split(">")[0].split("=")[0].strip() == "mutmut" for spec in specs)
    ]
    assert len(owners) == 1, f"expected exactly one extra to declare mutmut: {owners}"
    return owners[0]


@pytest.fixture(scope="module")
def rb7_row() -> str:
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("| RB-7 |"):
            return line
    pytest.fail(f"no RB-7 row in {LEDGER_PATH}")


def test_rb7_names_the_extra_mutmut_is_declared_in(rb7_row: str, mutmut_extra: str) -> None:
    assert f"`{mutmut_extra}`" in rb7_row, (
        f"pyproject.toml declares mutmut in the `{mutmut_extra}` extra, but the "
        f"RB-7 row does not name it: {rb7_row}"
    )


def test_rb7_does_not_claim_mutmut_is_in_another_extra(
    rb7_row: str, extras: dict[str, list[str]], mutmut_extra: str
) -> None:
    """ "mutmut in the dev extra" is the exact misdirection this gate exists for."""
    for name in extras:
        if name == mutmut_extra:
            continue
        assert f"mutmut in the {name} extra" not in rb7_row, (
            f"RB-7 claims mutmut lives in the `{name}` extra; pyproject.toml "
            f"declares it in `{mutmut_extra}`: {rb7_row}"
        )


def test_rb7_agrees_with_the_mutation_baseline_metric_doc(mutmut_extra: str) -> None:
    """The sibling metric doc already states the correct location; keep them one."""
    assert f"optional-dependencies].{mutmut_extra}" in METRIC_DOC.read_text(encoding="utf-8"), (
        f"{METRIC_DOC} no longer names the `{mutmut_extra}` extra"
    )
