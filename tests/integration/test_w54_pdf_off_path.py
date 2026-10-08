"""W54 step 3 (ADR-0153, Consequences: "With page reading off, nothing
changes"), failure mode 14 of
``docs/analysis/2026-10-08-w54-step3-pdf-reading-failure-modes.md``.

THE HARNESS is W29's (``tests/integration/test_w29_judge_reads_pages.py``):
loopback sites told apart by ``Host``, the real ``EvalJudgeService`` behind
the one provider seam, spies on the fetcher and the judge. Its ``pdf.example``
route is replaced here by a REAL, readable PDF, so "nothing was parsed" is the
product's choice and not an unreadable file. ``ChildLaunches``
(``tests.pdf_fixtures``) counts PDF children (rule 6b).

Every test names what turns it red.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests import pdf_fixtures as pdfs
from tests.integration.test_w29_judge_reads_pages import (  # noqa: F401 - _hermetic is autouse
    QUERY,
    _enable_judge,
    _evaluate,
    _hermetic,
    _run,
    _sites,
    _spies,
    _standard_routes,
    _standard_sources,
)

from product_app import evaluation, source_fetcher
from product_app.evaluation import build_judge_evidence, build_judge_prompt

pytestmark = pytest.mark.env_oracle


def _routes_with_a_real_pdf() -> dict[tuple[str, str], Any]:
    routes = _standard_routes()
    routes[("pdf.example", "/page")] = (
        "200 OK",
        {"Content-Type": "application/pdf"},
        pdfs.valid_pdf(),
    )
    return routes


def test_off_no_pdf_is_fetched_or_parsed_and_the_prompts_are_todays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: with page reading off, any request reaches a site, the
    fetcher or ``read_pdf_text`` is called, a PDF child is started, or the
    judge is sent anything but today's v1 system and user prompts.
    Partner: the same run's sources, read by ``judge_source_pages`` directly,
    DO read the PDF (N counts it and one child starts), so zero is the
    setting's doing, not a dead harness."""
    _enable_judge(monkeypatch)
    spies = _spies(monkeypatch)
    pdf_reads: list[Any] = []
    real_read = source_fetcher.read_pdf_text

    def read_spy(*args: Any, **kwargs: Any) -> Any:
        pdf_reads.append(args)
        return real_read(*args, **kwargs)

    monkeypatch.setattr(source_fetcher, "read_pdf_text", read_spy)
    children = pdfs.ChildLaunches().install(monkeypatch)
    with _sites(_routes_with_a_real_pdf()) as sites:
        run = _run([_standard_sources(sites)])
        result = _evaluate(run)
        assert result is not None and result.trust.support_verified is True
        assert list(sites.received) == []
        assert spies.fetch_calls == []
        assert pdf_reads == []
        assert children.launches == []
        assert spies.system_prompt == evaluation._JUDGE_SYSTEM_PROMPT
        expected_user = build_judge_prompt(
            build_judge_evidence(
                query_text=QUERY, initial_answers=run.initial_answers, final_synthesis=None
            )
        )[1]
        assert spies.user_prompt == expected_user

        # Partner: the PDF on this harness is readable when pages are read.
        pages = evaluation.judge_source_pages(list(run.initial_answers))
    assert pages.read == 2, pages  # allowed.example's page and the PDF
    assert len(pdf_reads) == 1 and len(children.launches) == 1
    assert any("PDFSENTINEL" in page for page in pages.pages)
