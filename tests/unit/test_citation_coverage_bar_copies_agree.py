"""Every written-down copy of the coverage bar agrees with the code (ADR-0106).

RED WHEN: a ``target_ratio`` literal in an e2e fixture or spec states a bar the
implementation does not apply for that payload's own ``answer_count``, or the
served schema regains a fixed default for it.

WHY THIS EXISTS. The bar used to be one constant, ``CITATION_COVERAGE_TARGET =
Decimal("0.80")``, copied by hand into e2e fixtures, spec payloads, the OpenAPI
default and four requirement documents. Nothing compared the copies to the
source, so the number drifted in one direction only: it was written once and
never re-derived. ADR-0106 made the bar a FUNCTION of the run's size, which
makes a single hardcoded copy wrong for every ``answer_count`` but one -- so the
drift is now mechanically detectable, and this is the check that detects it.

WHAT THIS CANNOT SEE, stated plainly. It proves the copies agree with the code.
It says NOTHING about whether the rule itself is the right one -- that judgement
is ADR-0106's and no gate can make it. It also does not read prose: the "at most
one unsourced answer" wording in NFR-003, AC-031 and ``docs/114`` is a human
step, because a sentence has no field to compare against.

DELIBERATELY OUT OF SCOPE, and not a gap:
  * ``docs/validation/*.json`` -- frozen records of runs that really did report
    ``target_ratio: "0.80"``. Editing them to satisfy a gate would be forging
    evidence.
  * ``tests/resilience/test_fault_injection_lane.py`` -- its ``0.80`` literals
    are inside docstrings quoting output "measured on origin/main (e6c84ea)
    before the fix, verbatim". Same reason.
Only ``e2e/`` is scanned, which is exactly the set the browser is served.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from product_app.providers import (
    CITATION_COVERAGE_MAX_UNSOURCED_ANSWERS,
    calculate_citation_coverage,
    citation_coverage_required_count,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_E2E = _REPO_ROOT / "e2e"

#: An object literal carrying BOTH an ``answer_count`` and a ``target_ratio``,
#: in either TS or JSON style, on one line or several. Non-greedy and bounded to
#: a single braced literal so two adjacent payloads cannot be spliced together.
_PAYLOAD_RE = re.compile(
    r"\{(?P<body>[^{}]*?\btarget_ratio\b[^{}]*?)\}",
    re.DOTALL,
)
_ANSWER_COUNT_RE = re.compile(r"\banswer_count\b\s*:\s*(\d+)")
_TARGET_RATIO_RE = re.compile(r"\btarget_ratio\b\s*:\s*[\"'](\d+\.\d+)[\"']")


def _expected_bar(answer_count: int) -> Decimal:
    """The bar the CODE applies -- read from the implementation, not restated."""
    return calculate_citation_coverage(
        answer_count=answer_count, sourced_answer_count=0
    ).target_ratio


def _scan() -> list[tuple[Path, int, int, Decimal]]:
    """Every (file, answer_count, target_ratio) literal pair under ``e2e/``."""
    found: list[tuple[Path, int, int, Decimal]] = []
    for path in sorted(_E2E.rglob("*.ts")) + sorted(_E2E.rglob("*.json")):
        if "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _PAYLOAD_RE.finditer(text):
            body = match.group("body")
            count = _ANSWER_COUNT_RE.search(body)
            ratio = _TARGET_RATIO_RE.search(body)
            if not count or not ratio:
                continue
            line = text.count("\n", 0, match.start()) + 1
            found.append((path, line, int(count.group(1)), Decimal(ratio.group(1))))
    return found


def test_the_scan_finds_the_fixtures_it_is_supposed_to_guard() -> None:
    """The positive partner (AGENTS.md rule 7).

    Every assertion below is "no copy disagrees", which is trivially true over an
    empty scan -- and the scan is a regex over files that move. If a rename or a
    formatting change silences it, this is the test that goes red instead of the
    gate quietly passing over nothing.
    """
    found = _scan()
    assert len(found) >= 8, f"the payload scan collapsed; it found only {found!r}"
    files = {path.name for path, _, _, _ in found}
    assert "golden-run.ts" in files, f"the golden fixture was not scanned: {files}"
    assert "verdict-band.spec.ts" in files, f"verdict-band was not scanned: {files}"
    # And it must be reading REAL numbers, not defaulting everything to one value.
    assert len({ratio for _, _, _, ratio in found}) >= 2, (
        "every scanned target_ratio is identical, which is what a broken regex "
        "looks like from the inside"
    )


@pytest.mark.parametrize("case", _scan(), ids=lambda c: f"{c[0].name}:{c[1]}")
def test_every_e2e_target_ratio_matches_the_bar_the_code_applies(
    case: tuple[Path, int, int, Decimal],
) -> None:
    """RED WHEN: a fixture states a bar the implementation would not produce."""
    path, line, answer_count, written = case
    expected = _expected_bar(answer_count)
    assert written == expected, (
        f"{path.relative_to(_REPO_ROOT)}:{line} declares target_ratio {written} "
        f"for answer_count={answer_count}, but the code applies {expected}. "
        "The bar is derived (ADR-0106); a hand-written copy must not disagree."
    )


def test_the_served_schema_carries_no_fixed_default_for_the_bar() -> None:
    """RED WHEN: ``target_ratio`` regains a constant default in the API schema.

    A default is how the old constant reached clients. Because the bar now
    depends on ``answer_count``, ANY fixed default is wrong for at least three
    of the four run sizes the product can emit, and would be served on exactly
    the payloads that omitted the field.
    """
    import yaml  # local: only this test needs it

    spec = yaml.safe_load((_REPO_ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    schema = spec["components"]["schemas"]["CitationCoverage"]
    prop = schema["properties"]["target_ratio"]
    assert "default" not in prop, (
        f"CitationCoverage.target_ratio regained a default ({prop.get('default')!r}); "
        "the bar is a function of answer_count and has no constant value. This "
        "fired for real on a sentinel default of '-1' -- see ADR-0106."
    )
    assert prop.get("readOnly") is True, (
        "the bar is computed; a writable field invites a client to send one"
    )
    # Positive partner: prove we are reading the real schema, not an empty dict.
    assert schema["properties"]["target_met"]["type"] == "boolean"
    assert "target_ratio" in schema["required"], (
        "target_ratio fell out of required; the server always sends it"
    )


def test_the_bar_is_stated_once_and_the_rule_is_a_count() -> None:
    """RED WHEN: a percentage threshold is reintroduced as the decision.

    Pinned with LITERALS on both sides, never against the constant that defines
    the bound (AGENTS.md rule 7a). ``1/2`` and ``2/4`` are the measurement that
    forced a count: both quantize to ``0.50``, so no threshold can pass one and
    fail the other, and asserting them here is what makes that irreversible.
    """
    assert CITATION_COVERAGE_MAX_UNSOURCED_ANSWERS == 1
    assert citation_coverage_required_count(4) == 3
    assert citation_coverage_required_count(1) == 1

    one_of_two = calculate_citation_coverage(answer_count=2, sourced_answer_count=1)
    two_of_four = calculate_citation_coverage(answer_count=4, sourced_answer_count=2)
    assert one_of_two.sourced_answer_ratio == two_of_four.sourced_answer_ratio == Decimal("0.50")
    assert one_of_two.target_met is True
    assert two_of_four.target_met is False


def test_the_bar_cannot_be_declared_at_all() -> None:
    """RED WHEN: ``target_ratio`` becomes a settable field again.

    It is a ``computed_field``. A caller cannot state a bar the code does not
    apply, because there is nowhere to state it -- strictly stronger than
    validating a stored copy, and the reason the stored version was abandoned.

    THAT VERSION SHIPPED A REAL DEFECT, and this test exists because of it. To
    satisfy the type checker it declared ``default=Decimal("-1")``; the export
    then published ``default: '-1'`` on the field -- a value outside its own
    ``[0, 1]`` bound, advertised to API clients -- while ``target_ratio``
    silently dropped out of the schema's ``required`` list. The sibling test
    above caught it on the full-suite run.
    """
    from product_app.providers import CitationCoverage

    assert "target_ratio" not in CitationCoverage.model_fields, (
        "target_ratio is a settable field again; a hand-written bar can now disagree with the code"
    )
    assert "target_ratio" in CitationCoverage.model_computed_fields

    # Supplying it changes nothing -- the computed value wins.
    coverage = CitationCoverage(
        answer_count=4,
        sourced_answer_count=3,
        sourced_answer_ratio=Decimal("0.75"),
        target_ratio=Decimal("0.80"),  # type: ignore[call-arg]
        target_met=True,
    )
    assert coverage.target_ratio == Decimal("0.75"), (
        "a supplied target_ratio reached the served value"
    )

    # Derived at more than one run size -- a single case would also pass
    # against a hardcoded constant.
    assert calculate_citation_coverage(
        answer_count=4, sourced_answer_count=3
    ).target_ratio == Decimal("0.75")
    assert calculate_citation_coverage(
        answer_count=1, sourced_answer_count=1
    ).target_ratio == Decimal("1.00")
    # SERIALIZED, not merely present on the object: the point is that a client
    # sees the bar that was applied.
    assert coverage.model_dump()["target_ratio"] == Decimal("0.75")
