"""W29 (ADR-0148 decisions 7 and 8): the price of the judge reading pages.

Failure modes 6 and 7 of
``docs/analysis/2026-10-06-w29-judge-reads-pages-failure-modes.md``:

* 6 -- the judge's input grows past its reserve. With
  ``quorum_source_fetch_enabled`` on (and a judge configured, panel run) the
  reserve adds at most 8 items of at most 4,000 characters, both clamped to
  those LITERAL numbers, so raising the environment settings cannot outgrow it.
  With the setting off every pinned bound stays as it is -- those pins live in
  ``tests/unit/test_bound_covers_the_judge.py`` (0.2949 judge-off, 0.3283
  judge-on) and are not duplicated here.
* 7 -- the ``source_fetch`` receipt row is exactly $0 and stays $0 through
  ``_reconcile_usd_lines``.

The catalog is pinned exactly as ``test_bound_covers_the_judge.py`` pins it
(AGENTS.md rule 16a: the catalog is a process global), so the figures below
are deterministic in any test order: the judge is priced at $0.001 per 1,000
input tokens, and ``costs.CHARS_PER_TOKEN`` is 4.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from tests.unit.test_bound_covers_the_judge import QUERY, _enable_judge, _pin_catalog, _slots

from product_app.config import settings
from product_app.costs import CostEstimate, CostEstimationService, cost_estimation_service

#: 8 items x 4,000 characters / 4 characters per token = 8,000 input tokens,
#: at the pinned $0.001 per 1,000 = $0.0080. Written out, not computed from
#: the constants under test (AGENTS.md rule 7a).
_PAGES_TERM_FLOOR = Decimal("0.0080")
#: An upper limit on the same term: the floor, plus room for the v2 system
#: prompt's extra length (up to 8,000 more characters = $0.0020) and per-item
#: scaffolding. A reserve that priced 32,000 TOKENS instead of 32,000
#: characters ($0.032) lands far above it; that over-reserve moves panels
#: into confirmation or BLOCK for nothing.
_PAGES_TERM_CEILING = Decimal("0.0110")


def _estimate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    judge: bool,
    pages: bool,
    mode: str = "panel",
    max_text_chars: int | None = None,
    max_pages: int | None = None,
) -> CostEstimate:
    with monkeypatch.context() as mp:
        _pin_catalog(mp)
        if judge:
            _enable_judge(mp)
        else:
            mp.setattr(settings, "quorum_eval_judge_api_key", "")
            mp.setattr(settings, "quorum_eval_judge_model_id", "")
        mp.setattr(settings, "quorum_source_fetch_enabled", pages)
        if max_text_chars is not None:
            mp.setattr(settings, "quorum_source_fetch_max_text_chars", max_text_chars)
        if max_pages is not None:
            mp.setattr(settings, "quorum_source_fetch_max_pages", max_pages)
        slots = _slots()[:1] if mode == "quick" else _slots()
        return cost_estimation_service.estimate(query_text=QUERY, model_slots=slots, mode=mode)


def _bound(estimate: CostEstimate) -> Decimal:
    assert estimate.max_cost_usd is not None
    return estimate.max_cost_usd


def _stages(estimate: CostEstimate) -> dict[str, Decimal]:
    assert estimate.breakdown is not None
    return {line.stage: line.usd for line in estimate.breakdown.by_stage}


# ---------------------------------------------------------------------------
# Failure mode 6: the reserve.
# ---------------------------------------------------------------------------


def test_reading_pages_raises_the_judge_reserve_by_eight_pages_of_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED IF: the reserve has no page term (the delta is 0), prices fewer
    than 8 x 4,000 characters, or prices them as tokens (the delta passes
    the ceiling)."""
    judge_only = _bound(_estimate(monkeypatch, judge=True, pages=False))
    with_pages = _bound(_estimate(monkeypatch, judge=True, pages=True))
    # Partner: the judge-on, pages-off bound is the figure the existing pin
    # holds, so the delta below is measured from the right baseline.
    assert judge_only == Decimal("0.3283"), judge_only
    delta = with_pages - judge_only
    assert delta >= _PAGES_TERM_FLOOR, f"the page term is {delta}; it must cover 8 x 4,000 chars"
    assert delta <= _PAGES_TERM_CEILING, f"the page term is {delta}; chars priced as tokens?"


def test_raising_the_fetch_settings_does_not_raise_the_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0148 decision 7: the item count and the item length are clamped to
    the LITERALS 8 and 4,000, not read from the environment-tunable settings.
    RED IF: the reserve reads ``quorum_source_fetch_max_text_chars`` or
    ``quorum_source_fetch_max_pages`` unclamped (the bound then grows ~10x
    the page term here)."""
    default = _bound(_estimate(monkeypatch, judge=True, pages=True))
    raised = _bound(
        _estimate(monkeypatch, judge=True, pages=True, max_text_chars=40_000, max_pages=80)
    )
    # Partner: the default-settings figure really carries a page term.
    assert default - Decimal("0.3283") >= _PAGES_TERM_FLOOR, default
    assert raised == default, f"raised settings moved the bound {default} -> {raised}"


def test_the_setting_without_a_judge_prices_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pages are read only when a judge is configured (decision 1). RED IF:
    the page term is gated on the setting alone. Partner: the same setting
    with a judge DOES move the bound."""
    off = _bound(_estimate(monkeypatch, judge=False, pages=False))
    setting_only = _bound(_estimate(monkeypatch, judge=False, pages=True))
    assert setting_only == off
    assert _bound(_estimate(monkeypatch, judge=True, pages=True)) > _bound(
        _estimate(monkeypatch, judge=True, pages=False)
    )


def test_a_quick_runs_reserve_does_not_move_with_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick mode never fetches (decision 1, failure mode 10), so its judge
    reads no page and its bound must not reserve for one. RED IF: the page
    term is added to the quick bound. Partner: the quick bound does price a
    judge (it is above the judge-off quick bound)."""
    quick_off = _bound(_estimate(monkeypatch, judge=True, pages=False, mode="quick"))
    quick_on = _bound(_estimate(monkeypatch, judge=True, pages=True, mode="quick"))
    quick_no_judge = _bound(_estimate(monkeypatch, judge=False, pages=False, mode="quick"))
    assert quick_on == quick_off
    assert quick_off > quick_no_judge


# ---------------------------------------------------------------------------
# Failure mode 7: the $0 receipt row, estimate side.
# ---------------------------------------------------------------------------


def test_the_estimate_carries_a_zero_source_fetch_row_when_pages_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 8. RED IF: the row is missing, is priced, or breaks the
    partition (the stages no longer sum to the total). Partner: the judge row
    beside it is a real, non-zero figure."""
    estimate = _estimate(monkeypatch, judge=True, pages=True)
    stages = _stages(estimate)
    assert "source_fetch" in stages, sorted(stages)
    assert stages["source_fetch"] == Decimal("0")
    assert list(stages).count("source_fetch") == 1
    assert stages["judge"] > 0
    assert estimate.breakdown is not None
    assert sum(stages.values()) == estimate.breakdown.total == estimate.estimated_cost_usd


@pytest.mark.parametrize(
    ("judge", "pages", "mode"),
    [
        (True, False, "panel"),  # setting off
        (False, True, "panel"),  # no judge
        (True, True, "quick"),  # quick never fetches
    ],
)
def test_no_source_fetch_row_unless_pages_are_read(
    monkeypatch: pytest.MonkeyPatch, judge: bool, pages: bool, mode: str
) -> None:
    """RED IF: the row appears when pages are not read. Partner: the
    estimate has its stage rows (the absence is not of an empty list)."""
    stages = _stages(_estimate(monkeypatch, judge=judge, pages=pages, mode=mode))
    assert "initial_answers" in stages
    assert "source_fetch" not in stages


@pytest.mark.parametrize(
    "query",
    [
        "x",
        "Compare transparent model answers",
        "How should a five-person team choose a managed database? " * 40,
    ],
    ids=["one-char", "fixture-query", "long-query"],
)
def test_the_row_stays_zero_whatever_the_total(monkeypatch: pytest.MonkeyPatch, query: str) -> None:
    """Different query lengths give different totals and rounding residues.
    RED IF: reconciliation hands the zero row a quantum on any of them."""
    with monkeypatch.context() as mp:
        _pin_catalog(mp)
        _enable_judge(mp)
        mp.setattr(settings, "quorum_source_fetch_enabled", True)
        estimate = cost_estimation_service.estimate(query_text=query, model_slots=_slots())
    assert estimate.breakdown is not None
    stages = {line.stage: line.usd for line in estimate.breakdown.by_stage}
    assert stages.get("source_fetch") == Decimal("0"), stages
    assert sum(stages.values()) == estimate.breakdown.total


@pytest.mark.parametrize(
    ("raw", "total"),
    [
        ([Decimal("0.00004"), Decimal("0.00005"), Decimal("0")], Decimal("0.0001")),
        (
            [
                Decimal("0.05153"),
                Decimal("0.01417"),
                Decimal("0.01417"),
                Decimal("0.04048"),
                Decimal("0.00795"),
                Decimal("0"),
            ],
            Decimal("0.1283"),
        ),
        (
            [Decimal("0.13333"), Decimal("0.13333"), Decimal("0.13334"), Decimal("0")],
            Decimal("0.4"),
        ),
    ],
)
def test_reconciliation_never_moves_a_zero_line(raw: list[Decimal], total: Decimal) -> None:
    """The arithmetic the row relies on, at three totals. GREEN TODAY: it pins
    the existing ``_reconcile_usd_lines`` (largest remainder), so a future
    change there that hands residue to a zero line (for example "ties go to
    the last line") goes red here before it reaches a receipt.
    RED IF: the zero line receives any quantum, or the lines stop summing."""
    assert sum(raw, Decimal(0)).quantize(Decimal("0.0001")) == total  # the input is coherent
    lines = CostEstimationService._reconcile_usd_lines(raw, total)
    assert lines[-1] == Decimal("0")
    assert sum(lines) == total


def test_the_page_reserve_covers_the_widest_block_the_builder_can_emit() -> None:
    """Bucket B pin for ``costs._JUDGE_PAGE_ITEM_OVERHEAD_CHARS`` and
    ``costs._JUDGE_PAGES_SECTION_OVERHEAD_CHARS``: measured against the REAL
    v2 user prompt, not restated as numbers. The widest block is 8 pages of
    4,000 characters numbered on two-digit SOURCES lines (25-32 of 32). The
    block's size is the v2 user prompt minus the v1 user prompt of the same
    evidence (v1 carries no page block).

    Turns red if: the page format grows (a longer header, an extra separator)
    past what the two constants reserve, or either constant is lowered below
    what the format costs. Partner: the reserve is not slack by more than a
    few characters, so an inflated constant is caught too."""
    from product_app.costs import (
        _JUDGE_PAGE_ITEM_OVERHEAD_CHARS,
        _JUDGE_PAGES_SECTION_OVERHEAD_CHARS,
    )
    from product_app.evaluation import (
        JudgeEvidence,
        build_judge_pages_prompt,
        build_judge_prompt,
    )

    lines = tuple(f"[{n}] Title {n} :: https://site{n}.example/page" for n in range(1, 33))
    widest = tuple("" if n < 25 else "p" * 4000 for n in range(1, 33))
    empty = ("",) * 32

    def block(pages: tuple[str, ...]) -> int:
        evidence = JudgeEvidence(
            query_text="Q?",
            answer_texts=("A [1].",),
            source_lines=lines,
            synthesis_sections=(),
            source_pages=pages,
        )
        return len(build_judge_pages_prompt(evidence)[1]) - len(build_judge_prompt(evidence)[1])

    reserve = 8 * (4000 + int(_JUDGE_PAGE_ITEM_OVERHEAD_CHARS)) + int(
        _JUDGE_PAGES_SECTION_OVERHEAD_CHARS
    )
    widest_block = block(widest)
    assert widest_block > 8 * 4000  # the pages really are in the block
    assert widest_block <= reserve, (widest_block, reserve)
    assert widest_block >= reserve - 40, (widest_block, reserve)
    no_page_block = block(empty)
    assert 0 < no_page_block <= int(_JUDGE_PAGES_SECTION_OVERHEAD_CHARS), no_page_block


def test_the_page_reserve_prices_the_v2_system_prompt_not_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 7: "plus the v2 system prompt's length in place of v1's".
    Review round 1. The judge's input is priced at $1 per 1,000 tokens here
    (a dedicated pin, 1,000 times the file's usual one) so a few hundred
    characters move the bound by whole cents and quantisation cannot hide them.

    With pages on, the judge sees the v2 system prompt instead of v1's, plus up
    to 8 pages of 4,000 characters. So the bound must rise by at least
    (32,000 + len(v2) - len(v1)) characters / 4 per token. RED IF: the reserve
    still counts v1's length (it then rises by 32,000 + scaffolding only, which
    is 552 characters short today). Partner: v2 really is longer than v1, so
    the assertion is not satisfied by a zero difference."""
    from product_app.evaluation import _JUDGE_PAGES_SYSTEM_PROMPT, _JUDGE_SYSTEM_PROMPT
    from product_app.model_slots import openrouter_model_catalog_service

    extra_prompt_chars = len(_JUDGE_PAGES_SYSTEM_PROMPT) - len(_JUDGE_SYSTEM_PROMPT)
    assert extra_prompt_chars > 0

    def bound(pages: bool) -> Decimal:
        with monkeypatch.context() as mp:
            real = openrouter_model_catalog_service.price_index
            mp.setattr(
                openrouter_model_catalog_service,
                "price_index",
                lambda: {**real(), "openai/gpt-5-mini": (Decimal("1.0"), Decimal("0.005"))},
            )
            _enable_judge(mp)
            mp.setattr(settings, "quorum_source_fetch_enabled", pages)
            estimate = cost_estimation_service.estimate(query_text=QUERY, model_slots=_slots())
        assert estimate.max_cost_usd is not None
        return estimate.max_cost_usd

    delta = bound(True) - bound(False)
    floor = (Decimal(32_000) + Decimal(extra_prompt_chars)) / Decimal(4) / Decimal(1000)
    assert delta >= floor, f"pages raised the bound by {delta}; v2's prompt needs {floor}"
