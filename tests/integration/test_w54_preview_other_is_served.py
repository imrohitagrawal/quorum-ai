"""W54 step 2 (ADR-0152 decision 3): the served count Q, end to end, and
previews for pages a real fetch could not read.

* ``evaluation.source_pages_preview_other`` is Q when the judge read pages,
  and null whenever ``source_pages_read`` is null.
* The memo records ``(read, cited, preview, preview_other)``, and
  ``_with_source_pages`` puts all four on ``RunEvaluation``.
* ``openapi.yaml`` serves the field as a nullable integer, not required.
* On real loopback sites, a page that answers 500, a PDF, a page too short to
  use and a page over the per-site limit each send their search preview to
  the judge and are counted in Q.

THE HARNESS is W29's (``tests/integration/test_w29_judge_reads_pages.py``):
loopback sites told apart by ``Host``, the real ``EvalJudgeService`` behind
the one provider seam, spies on the fetcher and the judge. Its standard five
sources now give N = 1 (allowed), P = 1 (blocked), Q = 2 (down: robots.txt
answers 503, preview sent; pdf: not text, preview sent), and the bare page
(refused, no preview) in none, M = 5.

The off-path body (today's plus the null fields) is pinned in
``tests/integration/test_w54_preview_count_is_served.py``.

Every test names what turns it red.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.integration.test_w29_judge_reads_pages import (  # noqa: F401 - _hermetic is autouse
    _FILLER,
    _NOT_FOUND,
    _enable_judge,
    _evaluate,
    _get,
    _hermetic,
    _html,
    _pages_on,
    _run,
    _sites,
    _source,
    _spies,
    _standard_routes,
    _standard_sources,
)
from tests.repo_root import find_repo_root

from product_app import query_run_orchestration as orchestration
from product_app import query_runs as qr
from product_app.debate import AgreementSummary
from product_app.evaluation import JUDGE_PAGES_PROMPT_ID, RunEvaluation, evaluate_run

ROOT = find_repo_root(Path(__file__))


def _four(ev: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    """(N, M, P, Q) as served."""
    return (
        ev["source_pages_read"],
        ev["source_pages_cited"],
        ev["source_pages_preview"],
        ev["source_pages_preview_other"],
    )


# ---------------------------------------------------------------------------
# Served on the standard run.
# ---------------------------------------------------------------------------


def test_on_the_standard_run_serves_q_and_sends_the_pdfs_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 3 on real loopback sites: (N, M, P, Q) = (1, 5, 1, 2). The
    down site's robots.txt answered 503 and the pdf site's page is not text;
    both previews reach the judge and both count in Q. RED IF: Q is missing
    or null, the PDF's preview is still withheld (ADR-0148 call (iii)), either
    is counted in P, or the bare page (no preview) is counted. Partner: all
    three previews are in the judge's prompt, the bare page's text is not."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    spies = _spies(monkeypatch)
    with _sites(_standard_routes()) as sites:
        body = _get(_run([_standard_sources(sites)]))
        assert len(sites.requests_for("pdf.example", "/page")) == 1  # it was tried
    ev = body["evaluation"]
    assert ev["trust"]["support_verified"] is True
    assert _four(ev) == (1, 5, 1, 2)
    user = spies.user_prompt
    for sentinel in ("EXCERPTBLOCKEDSENTINEL", "EXCERPTDOWNSENTINEL", "EXCERPTPDFSENTINEL"):
        assert sentinel in user, sentinel
    assert "PAGEBARESENTINEL" not in user


def _failing_routes() -> dict[tuple[str, str], Any]:
    return {
        ("ok.example", "/robots.txt"): _NOT_FOUND,
        ("ok.example", "/a"): _html(f"PAGEOKA {_FILLER}"),
        ("ok.example", "/b"): _html(f"PAGEOKB {_FILLER}"),
        ("ok.example", "/c"): _html(f"PAGEOKC {_FILLER}"),
        ("err.example", "/robots.txt"): _NOT_FOUND,
        ("err.example", "/page"): (
            "500 Internal Server Error",
            {"Content-Type": "text/html"},
            b"x",
        ),
        ("pdf.example", "/robots.txt"): _NOT_FOUND,
        ("pdf.example", "/page"): ("200 OK", {"Content-Type": "application/pdf"}, b"%PDF-1.7 x"),
        ("thin.example", "/robots.txt"): _NOT_FOUND,
        ("thin.example", "/page"): _html("Please enable cookies."),
    }


def test_on_real_failures_send_their_previews_and_count_in_q(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 3 through the real fetcher: a 500 (``http_error``), a PDF
    (``refused_content_type``), a page under 200 characters (``unusable``) and
    a third page on one host (``skipped_cap``, the per-site limit), each with
    a preview; two pages on that host are read. (N, M, P, Q) = (2, 6, 0, 4).
    RED IF: any of the four previews is withheld or uncounted, N moves, or
    the third page on the host is requested. Partner: each failure really was
    a failure on the wire (the 500, PDF and thin pages were requested once;
    the third ok.example page never), and each preview is in the prompt."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    spies = _spies(monkeypatch)
    with _sites(_failing_routes()) as sites:
        sources = [
            _source("A", sites.url("ok.example", "/a"), "EXCERPTOKA the a passage"),
            _source("B", sites.url("ok.example", "/b"), "EXCERPTOKB the b passage"),
            _source("C", sites.url("ok.example", "/c"), "EXCERPTOKC the third page"),
            _source("Err", sites.url("err.example"), "EXCERPTERR the server failed"),
            _source("Pdf", sites.url("pdf.example"), "EXCERPTPDF the document"),
            _source("Thin", sites.url("thin.example"), "EXCERPTTHIN the short page"),
        ]
        run = _run([sources])
        assert _evaluate(run) is not None
        body = _get(run)
        for host in ("err.example", "pdf.example", "thin.example"):
            assert len(sites.requests_for(host, "/page")) == 1, host
        assert sites.requests_for("ok.example", "/c") == []
    assert _four(body["evaluation"]) == (2, 6, 0, 4)
    user = spies.user_prompt
    for sentinel in ("EXCERPTOKC", "EXCERPTERR", "EXCERPTPDF", "EXCERPTTHIN"):
        assert sentinel in user, sentinel
    # The two pages read send their text, not their preview.
    assert "PAGEOKA" in user and "EXCERPTOKA" not in user


def test_on_every_page_read_serves_q_as_zero_not_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q = 0 is a served 0 when pages were read, so the sentence can say no
    other preview was used. RED IF: Q is null beside a non-null N."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    _spies(monkeypatch)
    with _sites(_standard_routes()) as sites:
        sources = [
            _source("Allowed page", sites.url("allowed.example")),
            _source("Allowed second page", sites.url("allowed.example", "/page2")),
        ]
        body = _get(_run([sources]))
    assert _four(body["evaluation"]) == (2, 2, 0, 0)


def test_on_with_no_cited_source_every_count_is_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "null whenever ``source_pages_read`` is null". RED IF: Q is 0 while N
    is null. Partner: the judge did run."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    spies = _spies(monkeypatch)
    body = _get(_run([[]]))
    assert len(spies.judge_calls) == 1
    assert _four(body["evaluation"]) == (None, None, None, None)


def test_off_q_is_served_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """With page reading off nothing is fetched and the new field is null
    (the key set is pinned in ``test_w54_preview_count_is_served.py``). RED
    IF: the field is missing from the served evaluation, or not null.
    Partner: the evaluation is the verified one."""
    _enable_judge(monkeypatch)
    spies = _spies(monkeypatch)
    with _sites(_standard_routes()) as sites:
        body = _get(_run([_standard_sources(sites)]))
    assert spies.fetch_calls == []
    ev = body["evaluation"]
    assert ev["trust"]["support_verified"] is True
    assert "source_pages_preview_other" in ev, sorted(ev)
    assert _four(ev) == (None, None, None, None)


# ---------------------------------------------------------------------------
# The memo, the evaluation, the projection, the contract.
# ---------------------------------------------------------------------------


def _plain_result() -> Any:
    return evaluate_run(
        initial_answers=[],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=4),
    )


def test_the_memo_carries_all_four_counts_onto_the_evaluation() -> None:
    """ "the memo records (read, cited, preview, preview_other)", and
    ``_with_source_pages`` puts all four on ``RunEvaluation``. RED IF: the
    fourth count is not carried, the tuple is still three long, or the counts
    are swapped (all four differ here). Partner: ``None`` leaves all four null
    and the prompt id v1."""
    result = _plain_result()
    assert result.evaluation.source_pages_preview_other is None
    ev = orchestration._with_source_pages(result, (1, 7, 2, 3)).evaluation
    assert (
        ev.source_pages_read,
        ev.source_pages_cited,
        ev.source_pages_preview,
        ev.source_pages_preview_other,
    ) == (1, 7, 2, 3)
    assert ev.judge_prompt_id == JUDGE_PAGES_PROMPT_ID
    off = orchestration._with_source_pages(result, None).evaluation
    assert off.source_pages_preview_other is None and off.source_pages_read is None
    assert off.judge_prompt_id != JUDGE_PAGES_PROMPT_ID


def test_the_judge_memo_records_q_from_the_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner branch writes Q into the memo from ``judge_source_pages``'s
    ``preview_other``, and ``_judge_source_pages_for`` returns all four.
    RED IF: the memo still records three counts, or records Q from another
    field. Partner: the standard run's counts, as served above."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    _spies(monkeypatch)
    with _sites(_standard_routes()) as sites:
        run = _run([_standard_sources(sites)])
        assert _evaluate(run) is not None
    assert orchestration._judge_source_pages_for(run.query_run_id) == (1, 5, 1, 2)


def test_run_evaluation_has_the_field_defaulting_to_null() -> None:
    """RED IF: ``RunEvaluation.source_pages_preview_other`` is missing, is
    required, or defaults to anything but None. Partner: its W54 sibling has
    the same shape."""
    for name in ("source_pages_preview", "source_pages_preview_other"):
        field = RunEvaluation.model_fields[name]
        assert field.is_required() is False, name
        assert field.default is None, name


def test_the_projection_serves_the_field() -> None:
    """RED IF: ``QueryRunEvaluationProjection`` has no
    ``source_pages_preview_other`` field, or it is required (a stored run read
    back has no counts)."""
    fields = qr.QueryRunEvaluationProjection.model_fields
    assert "source_pages_preview_other" in fields
    assert fields["source_pages_preview_other"].is_required() is False
    assert fields["source_pages_preview_other"].default is None


def test_openapi_serves_the_field_as_a_nullable_integer() -> None:
    """ "the same field in openapi.yaml". RED IF: the committed contract lacks
    it, types it otherwise, or marks it required. Partner: the three counts
    beside it have the same shape."""
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    schema = spec["components"]["schemas"]["QueryRunEvaluationProjection"]
    nullable_int = [{"type": "integer"}, {"type": "null"}]
    for name in (
        "source_pages_read",
        "source_pages_cited",
        "source_pages_preview",
        "source_pages_preview_other",
    ):
        assert name in schema["properties"], name
        assert schema["properties"][name]["anyOf"] == nullable_int, name
        assert name not in schema.get("required", []), name
