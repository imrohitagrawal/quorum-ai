"""W54 pull request 1 (ADR-0150 decisions 1, 3 and 5): the served count P,
end to end, and a long page read through the whole judge path.

* ``evaluation.source_pages_preview`` is P when the judge read pages, and
  null whenever ``source_pages_read`` is null (failure mode 3 and 4).
* With the setting OFF the API body is today's plus that one null field
  (failure mode 4: ADR-0148's "nothing visible changes when off").
* ``openapi.yaml`` serves the field.
* A long page reaches the judge as its main area's most relevant passages,
  and those passages never leave the judge call (failure modes 5 and 16).

THE HARNESS is W29's (``tests/integration/test_w29_judge_reads_pages.py``):
loopback sites told apart by ``Host``, the real ``EvalJudgeService`` behind
the one provider seam, spies on the fetcher and the judge. Its standard five
sources give N = 1 (allowed), P = 2 (blocked and down: robots.txt refused,
excerpt sent), and F = 2 (bare: refused with no excerpt; pdf: failed),
M = 5.

Every test names what turns it red.
"""

from __future__ import annotations

import html
import itertools
import json
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml
from tests.integration.test_w29_judge_reads_pages import (  # noqa: F401 - _hermetic is autouse
    _NOT_FOUND,
    _enable_judge,
    _evaluate,
    _get,
    _hermetic,
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
from product_app.config import Settings
from product_app.debate import AgreementSummary
from product_app.evaluation import JUDGE_PAGES_PROMPT_ID, evaluate_run

ROOT = find_repo_root(Path(__file__))


def _key_paths(node: Any, prefix: str = "") -> set[str]:
    """Every key path in a JSON body; list items share the ``[]`` path."""
    out: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            out.add(path)
            out |= _key_paths(value, path)
    elif isinstance(node, list):
        for value in node:
            out |= _key_paths(value, prefix + "[]")
    return out


#: Today's (7e6c94c) off-path body, measured with this file's own
#: ``_key_paths`` on the W29 standard run with the judge on and the setting
#: off: the top-level keys, and every path under ``evaluation``.
TODAY_TOP_LEVEL = frozenset(
    {
        "actual_breakdown",
        "actual_cost_usd",
        "correlation_id",
        "cost_estimate",
        "cost_source",
        "demo_mode",
        "elapsed_time_ms",
        "evaluation",
        "failed_steps",
        "global_spend_ceiling_reached",
        "live_count",
        "local_count",
        "material_claim_count",
        "missing_steps",
        "mode",
        "model_slots",
        "partial_failure_notice",
        "progress",
        "provider_failure_notices",
        "query_run_id",
        "quick_verdict",
        "result",
        "result_generated_at_utc",
        "spend_metering_unavailable",
        "status",
    }
)
TODAY_EVALUATION = frozenset(
    {
        "evaluation",
        "evaluation.faithfulness_label",
        "evaluation.hallucination_risk",
        "evaluation.judge_status",
        "evaluation.label_confidence",
        "evaluation.schema_version",
        "evaluation.signals",
        "evaluation.signals.agreement_ratio",
        "evaluation.signals.citation_coverage_ratio",
        "evaluation.signals.citation_marker_grounding",
        "evaluation.signals.completeness",
        "evaluation.signals.decision_support_framing_present",
        "evaluation.signals.disagreement_suppressed",
        "evaluation.signals.false_consensus_preserved",
        "evaluation.signals.high_stakes_warning_present",
        "evaluation.signals.high_stakes_warning_required",
        "evaluation.signals.live_ratio",
        "evaluation.signals.polar_disagreement_detected",
        "evaluation.signals.refusal_detected",
        "evaluation.signals.run_wholly_refused",
        "evaluation.signals.uncertainty_surfaced",
        "evaluation.signals.unverifiable_marker_count",
        "evaluation.signals.unverifiable_marker_ratio",
        "evaluation.source_pages_cited",
        "evaluation.source_pages_read",
        "evaluation.trust",
        "evaluation.trust.band",
        "evaluation.trust.diagnostics",
        "evaluation.trust.diagnostics.contributions",
        "evaluation.trust.diagnostics.contributions[].contribution",
        "evaluation.trust.diagnostics.contributions[].signal",
        "evaluation.trust.diagnostics.contributions[].value",
        "evaluation.trust.diagnostics.contributions[].weight",
        "evaluation.trust.diagnostics.layer_a_composite_unverified",
        "evaluation.trust.diagnostics.panel_size_cap",
        "evaluation.trust.score",
        "evaluation.trust.support_verified",
    }
)


# ---------------------------------------------------------------------------
# OFF: one new null field, nothing else.
# ---------------------------------------------------------------------------


def test_off_the_body_is_todays_plus_one_null_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure mode 4. RED IF: the field is missing, is not null with the
    setting off, or anything else in the top level or the evaluation is
    added or removed. Partners: the evaluation is the verified one, and no
    page was fetched."""
    _enable_judge(monkeypatch)
    spies = _spies(monkeypatch)
    with _sites(_standard_routes()) as sites:
        body = _get(_run([_standard_sources(sites)]))
        assert list(sites.received) == []
    assert spies.fetch_calls == []
    ev = body["evaluation"]
    assert ev["trust"]["support_verified"] is True
    assert "source_pages_preview" in ev, sorted(ev)
    assert ev["source_pages_preview"] is None
    assert ev["source_pages_read"] is None and ev["source_pages_cited"] is None
    paths = _key_paths(body)
    assert {p for p in paths if "." not in p and "[" not in p} == TODAY_TOP_LEVEL
    assert {p for p in paths if p.startswith("evaluation")} == TODAY_EVALUATION | {
        "evaluation.source_pages_preview"
    }


# ---------------------------------------------------------------------------
# ON: the run's own P.
# ---------------------------------------------------------------------------


def test_on_the_standard_run_serves_one_of_five_with_two_previews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 1 on real loopback sites: N = 1, M = 5, P = 2. The blocked
    and down sites' excerpts reached the judge; the bare site had none; the
    pdf failed. RED IF: P is missing or null, counts the excerpt-less refusal
    or the failed page (3 or 4), or counts the fetched page. Partner: both
    excerpts really are in the judge's prompt."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    spies = _spies(monkeypatch)
    with _sites(_standard_routes()) as sites:
        body = _get(_run([_standard_sources(sites)]))
    ev = body["evaluation"]
    assert ev["trust"]["support_verified"] is True
    assert (ev["source_pages_read"], ev["source_pages_cited"], ev["source_pages_preview"]) == (
        1,
        5,
        2,
    )
    assert "EXCERPTBLOCKEDSENTINEL" in spies.user_prompt
    assert "EXCERPTDOWNSENTINEL" in spies.user_prompt


def test_on_every_page_read_serves_a_zero_not_a_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """P = 0 is a served 0 when pages were read: the sentence must be able to
    say no preview was used. RED IF: P is null (the page would then show the
    old W29 sentence) or non-zero."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    _spies(monkeypatch)
    with _sites(_standard_routes()) as sites:
        sources = [
            _source("Allowed page", sites.url("allowed.example")),
            _source("Allowed second page", sites.url("allowed.example", "/page2")),
        ]
        body = _get(_run([sources]))
    ev = body["evaluation"]
    assert (ev["source_pages_read"], ev["source_pages_cited"], ev["source_pages_preview"]) == (
        2,
        2,
        0,
    )


def test_on_with_no_cited_source_every_count_is_null(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "null whenever ``source_pages_read`` is null": with the setting on but
    nothing cited, the judge reads no page and all three counts are null.
    RED IF: P is 0 while N is null (an impossible pair the page would have to
    guess about). Partner: the judge did run."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    spies = _spies(monkeypatch)
    body = _get(_run([[]]))
    ev = body["evaluation"]
    assert len(spies.judge_calls) == 1
    assert (ev["source_pages_read"], ev["source_pages_cited"], ev["source_pages_preview"]) == (
        None,
        None,
        None,
    )


def _plain_result() -> Any:
    return evaluate_run(
        initial_answers=[],
        final_synthesis=None,
        agreement=AgreementSummary(aligned=0, total=4),
    )


def test_the_memo_carries_read_cited_and_preview_onto_the_evaluation() -> None:
    """Decision 5: "the judge's memo records (read, cited, preview)", and
    ``_with_source_pages`` puts all three on ``RunEvaluation``. RED IF: the
    third count is not carried (or the tuple is still a pair), or the counts
    are swapped. Partner: ``None`` leaves all three null and the prompt id
    v1."""
    result = _plain_result()
    assert result.evaluation.source_pages_preview is None
    on = orchestration._with_source_pages(result, (1, 5, 2))
    ev = on.evaluation
    assert (ev.source_pages_read, ev.source_pages_cited, ev.source_pages_preview) == (1, 5, 2)
    assert ev.judge_prompt_id == JUDGE_PAGES_PROMPT_ID
    off = orchestration._with_source_pages(result, None).evaluation
    assert (off.source_pages_read, off.source_pages_cited, off.source_pages_preview) == (
        None,
        None,
        None,
    )
    assert off.judge_prompt_id != JUDGE_PAGES_PROMPT_ID


def test_the_projection_serves_the_field() -> None:
    """RED IF: ``QueryRunEvaluationProjection`` has no ``source_pages_preview``
    field, or it is required (a stored run read back has no counts at all)."""
    fields = qr.QueryRunEvaluationProjection.model_fields
    assert "source_pages_preview" in fields
    assert fields["source_pages_preview"].is_required() is False
    assert fields["source_pages_preview"].default is None


def test_openapi_serves_the_field_as_a_nullable_integer() -> None:
    """Decision 5: "the same field in openapi.yaml". RED IF: the committed
    contract lacks it, types it otherwise, or marks it required. Partner: the
    two W29 counts beside it have the same shape."""
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    schema = spec["components"]["schemas"]["QueryRunEvaluationProjection"]
    nullable_int = [{"type": "integer"}, {"type": "null"}]
    for name in ("source_pages_read", "source_pages_cited", "source_pages_preview"):
        assert name in schema["properties"], name
        assert schema["properties"][name]["anyOf"] == nullable_int, name
        assert name not in schema.get("required", []), name


# ---------------------------------------------------------------------------
# A long page through the whole path (failure modes 5, 6 and 16).
# ---------------------------------------------------------------------------

_VOCAB = ("lorem", "ipsum", "dolor", "sitam", "tempor", "labore", "magna", "aliqua")


def _block(n: int, tag: str, extra: str = "") -> str:
    s = f"{tag} {extra}".strip()
    words = itertools.cycle(_VOCAB)
    while len(s) < n:
        s += " " + next(words)
    return s[:n].rstrip()


def _long_page() -> bytes:
    blocks = [_block(440, f"LONGBLOCK{c}") for c in "ABCDEFGHIJKLMNOP"]
    # Claim words from the run's answers ("The figure is 90 percent [1], per
    # the cited pages [2]."): figure, percent, cited, pages.
    blocks[13] = _block(440, "LATERELEVANTSENTINEL", "the cited pages give the figure in percent")
    nav = "<nav><ul>" + "".join(f"<li>NAVMENUSENTINEL {i}</li>" for i in range(30)) + "</ul></nav>"
    main = "<main>" + "".join(f"<p>{html.escape(b)}</p>" for b in blocks) + "</main>"
    footer = "<footer><p>FOOTERSENTINEL all rights reserved</p></footer>"
    return f"<html><body>{nav}{main}{footer}</body></html>".encode()


def test_a_long_page_reaches_the_judge_as_its_relevant_passages_and_nowhere_else(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Decision 3 end to end. A 7,000-character page whose only passage
    sharing the answers' words is its fourteenth block (past the first 4,000
    characters), behind a long menu. RED IF: the judge reads the first 4,000
    characters (the relevant block is then absent and the menu present), the
    item is over 4,000 characters or not joined with " … ", or the picked
    passage reaches the served body or a log record. Partners: the relevant
    passage IS in the judge's prompt, and the log capture saw records."""
    _enable_judge(monkeypatch)
    _pages_on(monkeypatch)
    spies = _spies(monkeypatch)
    caplog.set_level(logging.DEBUG)
    routes = {
        ("long.example", "/robots.txt"): _NOT_FOUND,
        ("long.example", "/page"): (
            "200 OK",
            {"Content-Type": "text/html; charset=utf-8"},
            _long_page(),
        ),
    }
    with _sites(routes) as sites:
        run = _run([[_source("Long page", sites.url("long.example"))]])
        assert _evaluate(run) is not None
        served = _get(run)
    (page,) = spies.pages
    assert "LATERELEVANTSENTINEL" in page
    assert "NAVMENUSENTINEL" not in page and "FOOTERSENTINEL" not in page
    assert " … " in page
    assert len(page) <= 4000
    assert "LATERELEVANTSENTINEL" in spies.user_prompt
    assert (
        served["evaluation"]["source_pages_read"],
        served["evaluation"]["source_pages_cited"],
    ) == (
        1,
        1,
    )
    assert served["evaluation"]["source_pages_preview"] == 0
    assert "LATERELEVANTSENTINEL" not in json.dumps(served)
    assert caplog.records, "the log capture saw nothing"
    leaks = [
        r.name
        for r in caplog.records
        if "LATERELEVANTSENTINEL" in r.getMessage() + json.dumps(r.__dict__, default=repr)
    ]
    assert leaks == []


def test_no_setting_switches_how_long_pages_are_read() -> None:
    """Decision 4, failure mode 15: the paid comparison builds both prompts in
    a script; no production switch is added for it. RED IF: a setting whose
    name mentions passages, long pages or the first-characters rule appears.
    Partner: the settings really are enumerated (the W29 switch is there)."""
    names = set(Settings.model_fields)
    assert "quorum_source_fetch_enabled" in names
    assert [n for n in names if any(k in n for k in ("passage", "long_page", "first_chars"))] == []
