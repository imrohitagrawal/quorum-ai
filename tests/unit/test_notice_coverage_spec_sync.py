"""Issue #124 — every ``PROVIDER_NOTICES`` entry not already covered by
``answer-completeness.spec.ts`` (``NOTICE_NO_SOURCES_FOUND``) must have a case
in ``e2e/fixtures/notice-coverage-cases.ts``, pinned verbatim to the registry.

Same shape as ``test_golden_fixture_notice_sync.py``: a stale or incomplete
case table stays GREEN in Playwright while asserting text the product no
longer emits, or silently drops coverage for a tenth notice. Two directions
asserted: no case quotes text that is not in the registry (drift), and no
registry notice is left without a case, except the one already covered
elsewhere (completeness).
"""

from __future__ import annotations

import pathlib
import re

from product_app.providers import NOTICE_NO_SOURCES_FOUND, PROVIDER_NOTICES

_CASES_FILE = (
    pathlib.Path(__file__).resolve().parents[2] / "e2e" / "fixtures" / "notice-coverage-cases.ts"
)
_CASE_TEXT = re.compile(r'text:\s*"([^"]+)"')


def _case_texts() -> list[str]:
    assert _CASES_FILE.is_file(), f"missing {_CASES_FILE}"
    return _CASE_TEXT.findall(_CASES_FILE.read_text(encoding="utf-8"))


def test_the_case_table_is_not_empty() -> None:
    """A guard over zero cases proves nothing (the ``all([])`` trap)."""
    assert _case_texts(), "notice-coverage-cases.ts has no cases — issue #124 has regressed"


def test_every_case_is_registered_verbatim() -> None:
    registry = set(PROVIDER_NOTICES)
    for text in _case_texts():
        assert text in registry, (
            "e2e/fixtures/notice-coverage-cases.ts quotes a notice not in "
            f"PROVIDER_NOTICES verbatim:\n  case: {text!r}\n"
            "Update the case to match the registry in the same diff."
        )


def test_every_registry_notice_has_a_case_or_is_the_one_covered_elsewhere() -> None:
    """Completeness: a tenth notice cannot be added without coverage.

    ``NOTICE_NO_SOURCES_FOUND`` is the one exception — it already has
    browser-level coverage via
    ``e2e/tests/invariants/answer-completeness.spec.ts`` (issue #114), seeded
    through ``e2e/fixtures/golden-run.ts`` rather than this case table.
    """
    covered = set(_case_texts()) | {NOTICE_NO_SOURCES_FOUND}
    missing = set(PROVIDER_NOTICES) - covered
    assert not missing, (
        "PROVIDER_NOTICES has a notice with no browser-level coverage case: "
        f"{missing}. Add it to e2e/fixtures/notice-coverage-cases.ts."
    )
