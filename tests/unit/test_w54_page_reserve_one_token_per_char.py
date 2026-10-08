"""W54 step 2 (ADR-0152 decisions 1 and 2): what the judge's page reading costs.

Failure modes 1, 2, 3 and 11 of
``docs/analysis/2026-10-08-w54-step2-previews-and-reserve-failure-modes.md``:

* 1 -- page text in Chinese, Japanese and similar scripts takes about one token
  per character, so the reserve prices the page block (8 items of 4,000
  characters, their framing and the 24 "same page as" lines) at ONE token per
  character instead of ``CHARS_PER_TOKEN`` (4). The v2 system prompt is still
  priced at 4 characters per token: decision 1 names the page block only.
* 2 -- with page reading in effect the displayed typical judge input is
  ``cost_judge_input_tokens_with_pages`` (8,400) plus the query, else
  ``cost_judge_input_tokens`` (7,300) plus the query.
* 3 -- the typical figure never exceeds the reserve (the clamp holds for the
  new setting too).
* 11 -- with page reading off, every estimate and bound is byte-identical to
  today. The figures in ``_TODAY_OFF`` were captured on ``9e97d74`` (the
  commit before this change) with the price index pinned exactly as below.

THE PAGE BLOCK, in characters, written out (rule 7a: not computed from the
constants under test): 8 items x (4,000 + 12 framing) + 40 for the section
header + 24 x 29 for the widest "PAGE [32]: same page as [32]" line and its
newline = 32,096 + 40 + 696 = **32,832**. Today the reserve prices it at
32,832 / 4 = **8,208** tokens; ADR-0152 prices it at **32,832** -- exactly 4x.

THE SYSTEM PROMPT TERM. Decision 3 rewords the v2 system prompt, so its length
is not known before the builder writes it. Every page-term figure below is
therefore the judge reserve with pages on, minus the reserve with pages off,
minus ``(len(v2) - len(v1)) / 4`` tokens measured on the prompts at run time.
What is left is the page block alone, pinned with a literal.

PRICES. The price index is a process global (AGENTS.md rule 16a); every test
here REPLACES it with an explicit dict for the duration of one
``monkeypatch.context()``, so the figures hold in any test order. The four
slots are ``vendor/model-N`` (absent from every index, so they price at the
module's fallback rate, as in ``tests/unit/test_bound_covers_the_judge.py``).

Every test names what turns it red.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from product_app.config import Settings, settings
from product_app.costs import CostEstimate, cost_estimation_service
from product_app.model_slots import ModelSlot, openrouter_model_catalog_service

QUERY = "Compare transparent model answers"  # 33 characters = 8.25 tokens
#: The judge model the repo's price tests pin (``test_bound_covers_the_judge``).
JUDGE_MODEL = "openai/gpt-5-mini"
#: Production's judge (CHG-032 (b), (f)), at its list price: $0.40 per million
#: input tokens, $1.60 per million output tokens.
PROD_JUDGE_MODEL = "openai/gpt-4.1-mini"
_TEST_PRICE = (Decimal("0.001"), Decimal("0.005"))  # per 1,000 tokens
_PROD_PRICE = (Decimal("0.0004"), Decimal("0.0016"))  # per 1,000 tokens

#: The page block at one token per character (see the module docstring).
PAGE_BLOCK_TOKENS = Decimal(32_832)
#: Today's page block, at four characters per token. Only quoted in messages.
TODAY_PAGE_BLOCK_TOKENS = Decimal(8_208)


def _slots(n: int = 4) -> list[ModelSlot]:
    return [ModelSlot(slot_number=i, model_id=f"vendor/model-{i}") for i in range(1, n + 1)]


def _pin(
    mp: pytest.MonkeyPatch,
    *,
    judge: str | None = JUDGE_MODEL,
    price: tuple[Decimal, Decimal] = _TEST_PRICE,
    pages: bool = False,
) -> None:
    """Replace the price index and set the judge and the page setting."""
    index = {JUDGE_MODEL: _TEST_PRICE}
    if judge is not None:
        index[judge] = price
    mp.setattr(openrouter_model_catalog_service, "price_index", lambda: dict(index))
    mp.setattr(settings, "quorum_eval_judge_api_key", "sk-not-a-real-key" if judge else "")
    mp.setattr(settings, "quorum_eval_judge_model_id", judge or "")
    mp.setattr(settings, "quorum_source_fetch_enabled", pages)


def _judge_term(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pages: bool,
    typical: bool,
    judge: str = JUDGE_MODEL,
    price: tuple[Decimal, Decimal] = _TEST_PRICE,
    query: str = QUERY,
    quick: bool = False,
) -> Decimal:
    """The raw (unquantised) judge term of ``_cost_components``."""
    with monkeypatch.context() as mp:
        _pin(mp, judge=judge, price=price, pages=pages)
        _, _, _, _, judge_cost, _ = cost_estimation_service._cost_components(
            query_text=query,
            model_slots=_slots(1 if quick else 4),
            init_output_tokens=Decimal(settings.initial_answer_max_tokens),
            price_judge=True,
            price_judge_pages=pages,
            judge_typical=typical,
            quick=quick,
        )
    return judge_cost


def _prompt_term_tokens() -> Decimal:
    """The v2 system prompt's extra length over v1's, at 4 characters per
    token -- measured on the prompts as they are when the test runs."""
    from product_app.evaluation import _JUDGE_PAGES_SYSTEM_PROMPT, _JUDGE_SYSTEM_PROMPT

    return Decimal(len(_JUDGE_PAGES_SYSTEM_PROMPT) - len(_JUDGE_SYSTEM_PROMPT)) / Decimal(4)


def _page_term_tokens(monkeypatch: pytest.MonkeyPatch, price_per_1k: Decimal, **kw: Any) -> Decimal:
    on = _judge_term(monkeypatch, pages=True, typical=False, **kw)
    off = _judge_term(monkeypatch, pages=False, typical=False, **kw)
    return (on - off) * Decimal(1000) / price_per_1k - _prompt_term_tokens()


def _estimate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    judge: bool,
    pages: bool,
    mode: str = "panel",
    query: str = QUERY,
    price: tuple[Decimal, Decimal] = _TEST_PRICE,
) -> CostEstimate:
    with monkeypatch.context() as mp:
        _pin(mp, judge=JUDGE_MODEL if judge else None, price=price, pages=pages)
        return cost_estimation_service.estimate(
            query_text=query, model_slots=_slots(1 if mode == "quick" else 4), mode=mode
        )


# ---------------------------------------------------------------------------
# Decision 1: the reserve counts page text at one token per character.
# ---------------------------------------------------------------------------


def test_the_page_block_is_reserved_at_one_token_per_character(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 1, failure mode 1. At $0.001 per 1,000 input tokens the page
    term of the judge reserve is exactly 32,832 tokens (today 8,208: 4x).
    RED IF: the block is still divided by 4 (8,208), only the 8 x 4,000 page
    text moves to one token per character but the framing or the 24 pointers
    do not (32,000 + 834/4 or similar), or the v2 system prompt is also moved
    to one token per character (the remainder then exceeds 32,832 by 3/4 of
    the prompt's extra length). Partner: pages really are in effect (the term
    is not zero)."""
    tokens = _page_term_tokens(monkeypatch, _TEST_PRICE[0])
    assert tokens != 0
    assert tokens == PAGE_BLOCK_TOKENS, (
        f"page term {tokens} tokens; ADR-0152 wants {PAGE_BLOCK_TOKENS} "
        f"(today: {TODAY_PAGE_BLOCK_TOKENS})"
    )


def test_the_page_term_at_productions_judge_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 1 with production's judge (``openai/gpt-4.1-mini``, $0.40 per
    million input tokens): the page block adds exactly $0.0131328 to the raw
    judge reserve (32,832 tokens), against $0.0032832 today -- a rise of
    $0.0098496 (24,624 tokens). ADR-0152 states this as "$0.0098 (24,624
    more tokens)".
    RED IF: the page block is priced at 4 characters per token ($0.0032832),
    or at any rate other than one token per character."""
    on = _judge_term(
        monkeypatch, pages=True, typical=False, judge=PROD_JUDGE_MODEL, price=_PROD_PRICE
    )
    off = _judge_term(
        monkeypatch, pages=False, typical=False, judge=PROD_JUDGE_MODEL, price=_PROD_PRICE
    )
    prompt_usd = _prompt_term_tokens() * _PROD_PRICE[0] / Decimal(1000)
    assert on - off - prompt_usd == Decimal("0.0131328"), on - off - prompt_usd


def test_the_bound_shown_before_a_run_carries_the_new_page_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire: ``estimate()``'s ``max_cost_usd`` (the "up to" figure and
    the guardrail's input), not only ``_cost_components``. At $0.001 per
    1,000 the bound rises with pages by the page block ($0.032832) plus the
    prompt term, within one display quantum ($0.0001); today it rises by
    $0.008208 plus the prompt term, $0.0246 short.
    RED IF: the estimate's bound path does not carry the one-token-per-
    character block (for example only one of the two callers of
    ``_cost_components`` was changed). Partner: the pages-off bound is the
    figure pinned on today's code (0.3283)."""
    off = _estimate(monkeypatch, judge=True, pages=False).max_cost_usd
    on = _estimate(monkeypatch, judge=True, pages=True).max_cost_usd
    assert off == Decimal("0.3283"), off
    assert on is not None
    expected = (PAGE_BLOCK_TOKENS + _prompt_term_tokens()) * _TEST_PRICE[0] / Decimal(1000)
    assert abs((on - off) - expected) <= Decimal("0.0001"), (on - off, expected)


def test_raising_the_fetch_settings_still_does_not_raise_the_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0148 decision 7, kept by ADR-0152: the 1-token-per-character block
    is still 8 items of 4,000 characters, the LITERALS, whatever the
    environment says. RED IF: the new term reads
    ``quorum_source_fetch_max_text_chars`` or ``quorum_source_fetch_max_pages``
    unclamped. Partner: the default-settings term is the full block."""
    default = _page_term_tokens(monkeypatch, _TEST_PRICE[0])
    with monkeypatch.context() as mp:
        mp.setattr(settings, "quorum_source_fetch_max_text_chars", 40_000)
        mp.setattr(settings, "quorum_source_fetch_max_pages", 80)
        raised = _page_term_tokens(mp, _TEST_PRICE[0])
    assert default == PAGE_BLOCK_TOKENS
    assert raised == default, (default, raised)


# ---------------------------------------------------------------------------
# Decision 2: the typical judge input, and the clamp.
# ---------------------------------------------------------------------------


def test_the_new_setting_exists_with_the_owners_figure() -> None:
    """CHG-032 (d): ``cost_judge_input_tokens_with_pages`` defaults to 8,400;
    ``cost_judge_input_tokens`` stays 7,300. RED IF: the setting is missing,
    its default is not 8,400, or the old figure moved. Like its sibling it
    refuses zero (a $0 judge row beside a firing judge, ADR-0114's review
    finding); partner: 1 is accepted."""
    from pydantic import ValidationError

    fresh = Settings()
    assert fresh.cost_judge_input_tokens_with_pages == 8400
    assert fresh.cost_judge_input_tokens == 7300
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            Settings(cost_judge_input_tokens_with_pages=bad)
    assert Settings(cost_judge_input_tokens_with_pages=1).cost_judge_input_tokens_with_pages == 1


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        # 8,400 + 8.25 tokens at $0.001/1k + 150 output tokens at $0.005/1k.
        (True, Decimal("0.00915825")),
        # 7,300 + 8.25 tokens + the same output: today's figure, unchanged.
        (False, Decimal("0.00805825")),
    ],
    ids=["pages-in-effect-8400", "pages-off-7300"],
)
def test_the_typical_judge_input_follows_page_reading(
    monkeypatch: pytest.MonkeyPatch, pages: bool, expected: Decimal
) -> None:
    """Decision 2, failure mode 2. RED IF: with pages in effect the typical
    input is still 7,300 (0.00805825), or with pages off it is 8,400
    (0.00915825), or the query is no longer added."""
    assert _judge_term(monkeypatch, pages=pages, typical=True) == expected


def test_each_typical_setting_is_read_only_on_its_own_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 2: ``cost_judge_input_tokens_with_pages`` is read when page
    reading is in effect, ``cost_judge_input_tokens`` otherwise. Each setting
    is moved to 100 while the other path is measured.
    RED IF: the pages-off typical reads the new setting, or the pages-on
    typical reads the old one. Partner: each path does move with its own
    setting (100 + 8.25 tokens -> $0.00085825)."""
    with monkeypatch.context() as mp:
        mp.setattr(settings, "cost_judge_input_tokens_with_pages", 100)
        assert _judge_term(mp, pages=False, typical=True) == Decimal("0.00805825")
        assert _judge_term(mp, pages=True, typical=True) == Decimal("0.00085825")
    with monkeypatch.context() as mp:
        mp.setattr(settings, "cost_judge_input_tokens", 100)
        assert _judge_term(mp, pages=True, typical=True) == Decimal("0.00915825")
        assert _judge_term(mp, pages=False, typical=True) == Decimal("0.00085825")


@pytest.mark.parametrize(
    ("chars", "expected"),
    [
        # (8,400 + 1,000) input tokens at $0.001/1k + 150 output at $0.005/1k.
        (4_000, Decimal("0.01015000")),
        # (8,400 + 5,000) input tokens + the same output.
        (20_000, Decimal("0.01415000")),
    ],
)
def test_the_pages_typical_still_follows_query_length(
    monkeypatch: pytest.MonkeyPatch, chars: int, expected: Decimal
) -> None:
    """ADR-0114's review finding carried to the new figure: the query is in
    the judge prompt verbatim, so the typical grows with it. RED IF: the
    pages typical is a flat 8,400 (both cases then read $0.00915825), or
    is 7,300 (they read $0.00905 and $0.01305)."""
    assert _judge_term(monkeypatch, pages=True, typical=True, query="x" * chars) == expected


def test_the_typical_with_pages_is_clamped_to_the_pages_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mode 3. With the shipped constants 8,400 + the longest query
    (5,000 tokens) can never reach the pages-on reserve (over 61,000 tokens),
    so the clamp is pinned by moving the SETTING to the reserve's boundary.
    The reserve in tokens is 28,232.25 (today's pages-off reserve for this
    query, pinned in ``test_estimate_prices_the_judge.py``) + 32,832 (the page
    block) + the prompt term. RED IF: the ``min(...)`` clamp is not applied
    to the new figure (the typical then prices above the bound's judge term).
    Partner: a setting just below the boundary is priced as set, not clamped,
    so the clamp is a boundary and not a constant."""
    import math

    reserve_tokens = Decimal("28232.25") + PAGE_BLOCK_TOKENS + _prompt_term_tokens()
    bound_term = _judge_term(monkeypatch, pages=True, typical=False)
    # Output pinned at its cap (1,024) so only the input clamp is measured.
    out_usd = Decimal(1024) * _TEST_PRICE[1] / Decimal(1000)
    assert bound_term == reserve_tokens * _TEST_PRICE[0] / Decimal(1000) + out_usd
    # The setting at which the typical (setting + 8.25) meets the reserve.
    boundary = reserve_tokens - Decimal("8.25")
    below = math.floor(boundary) - 1
    over = math.ceil(boundary) + 1

    def priced(setting: int) -> Decimal:
        return (Decimal(setting) + Decimal("8.25")) * _TEST_PRICE[0] / Decimal(1000) + out_usd

    assert priced(below) < bound_term < priced(over)
    for setting, expected in (
        (below, priced(below)),
        (over, bound_term),
        (10**9, bound_term),
    ):
        with monkeypatch.context() as mp:
            mp.setattr(settings, "cost_judge_input_tokens_with_pages", setting)
            mp.setattr(settings, "cost_judge_output_tokens", 1024)
            got = _judge_term(mp, pages=True, typical=True)
        assert got == expected, (setting, got, expected)
        assert got <= bound_term


def test_the_estimates_judge_row_shows_the_pages_typical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire: the displayed estimate, not only ``_cost_components``. With
    pages in effect the headline is $0.2019 (raw $0.19273875 + $0.00915825),
    with them off $0.2008 (today's pin). RED IF: ``estimate()`` still shows
    7,300 with pages in effect, or shows 8,400 with them off. Partner: the
    judge row is present on both."""
    on = _estimate(monkeypatch, judge=True, pages=True)
    off = _estimate(monkeypatch, judge=True, pages=False)
    assert on.estimated_cost_usd == Decimal("0.2019"), on.estimated_cost_usd
    assert off.estimated_cost_usd == Decimal("0.2008"), off.estimated_cost_usd
    for est in (on, off):
        assert est.breakdown is not None
        assert "judge" in {line.stage for line in est.breakdown.by_stage}
    assert on.max_cost_usd is not None and on.estimated_cost_usd <= on.max_cost_usd


def test_a_quick_runs_typical_does_not_move_with_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick runs never read pages (ADR-0148 decision 1), so page reading is
    not in effect for them and their typical stays 7,300, as their reserve
    already does. RED IF: the 8,400 figure is keyed on the setting alone
    rather than on pages being read for this run. Partner: the quick estimate
    does price a judge."""
    quick_on = _estimate(monkeypatch, judge=True, pages=True, mode="quick")
    quick_off = _estimate(monkeypatch, judge=True, pages=False, mode="quick")
    no_judge = _estimate(monkeypatch, judge=False, pages=False, mode="quick")
    assert quick_on.estimated_cost_usd == quick_off.estimated_cost_usd == Decimal("0.0209")
    assert quick_on.max_cost_usd == quick_off.max_cost_usd == Decimal("0.0467")
    assert quick_off.estimated_cost_usd > no_judge.estimated_cost_usd


# ---------------------------------------------------------------------------
# Failure mode 11: page reading off changes nothing.
# ---------------------------------------------------------------------------

_Summary = tuple[str, str, str, tuple[tuple[str, str], ...]]

#: Captured on 9e97d74 (today's code) with this file's ``_pin``: for each case,
#: (estimated, max, threshold action, by_stage). Page reading is NOT in effect
#: in any of them: the setting is off, or there is no judge, or the run is quick.
_TODAY_OFF: dict[tuple[bool, bool, str, int], _Summary] = {
    (True, False, "panel", 1): (
        "0.2005",
        "0.3282",
        "require_confirmation",
        (
            ("initial_answers", "0.0515"),
            ("debate_round_1", "0.0141"),
            ("debate_round_2", "0.0141"),
            ("synthesis", "0.1128"),
            ("judge", "0.0080"),
        ),
    ),
    (True, False, "panel", 33): (
        "0.2008",
        "0.3283",
        "require_confirmation",
        (
            ("initial_answers", "0.0515"),
            ("debate_round_1", "0.0142"),
            ("debate_round_2", "0.0142"),
            ("synthesis", "0.1129"),
            ("judge", "0.0080"),
        ),
    ),
    (True, False, "panel", 20000): (
        "0.3229",
        "0.3882",
        "require_confirmation",
        (
            ("initial_answers", "0.0974"),
            ("debate_round_1", "0.0244"),
            ("debate_round_2", "0.0244"),
            ("synthesis", "0.1637"),
            ("judge", "0.0130"),
        ),
    ),
    (True, False, "quick", 33): (
        "0.0209",
        "0.0467",
        "allow",
        (
            ("initial_answers", "0.0129"),
            ("judge", "0.0080"),
        ),
    ),
    (True, True, "quick", 20000): (
        "0.0374",
        "0.0567",
        "allow",
        (
            ("initial_answers", "0.0244"),
            ("judge", "0.0130"),
        ),
    ),
    (False, False, "panel", 33): (
        "0.1927",
        "0.2949",
        "allow",
        (
            ("initial_answers", "0.0515"),
            ("debate_round_1", "0.0142"),
            ("debate_round_2", "0.0142"),
            ("synthesis", "0.1128"),
        ),
    ),
    (False, True, "panel", 33): (
        "0.1927",
        "0.2949",
        "allow",
        (
            ("initial_answers", "0.0515"),
            ("debate_round_1", "0.0142"),
            ("debate_round_2", "0.0142"),
            ("synthesis", "0.1128"),
        ),
    ),
    (False, True, "panel", 4000): (
        "0.2275",
        "0.3059",
        "require_confirmation",
        (
            ("initial_answers", "0.0654"),
            ("debate_round_1", "0.0172"),
            ("debate_round_2", "0.0172"),
            ("synthesis", "0.1277"),
        ),
    ),
    (False, False, "quick", 20000): ("0.0244", "0.0244", "allow", (("initial_answers", "0.0244"),)),
    (False, True, "quick", 1): ("0.0129", "0.0194", "allow", (("initial_answers", "0.0129"),)),
}


def _summary(est: CostEstimate) -> _Summary:
    assert est.breakdown is not None
    stages = tuple((line.stage, str(line.usd)) for line in est.breakdown.by_stage)
    return (str(est.estimated_cost_usd), str(est.max_cost_usd), est.threshold_action.value, stages)


@pytest.mark.parametrize(
    "case", list(_TODAY_OFF), ids=[f"judge{j}-setting{p}-{m}-q{q}" for j, p, m, q in _TODAY_OFF]
)
def test_with_page_reading_not_in_effect_every_figure_is_todays(
    monkeypatch: pytest.MonkeyPatch, case: tuple[bool, bool, str, int]
) -> None:
    """Failure mode 11. RED IF: any figure moves when pages are not read --
    for example 8,400 used with the setting off, or the one-token-per-
    character block added without a judge or on a quick run. Partner: the
    judge cases really price a judge (their stages carry a judge row) and
    the no-judge cases do not."""
    judge, pages, mode, qlen = case
    est = _estimate(monkeypatch, judge=judge, pages=pages, mode=mode, query="x" * qlen)
    assert _summary(est) == _TODAY_OFF[case]
    assert ("judge" in {stage for stage, _ in _TODAY_OFF[case][3]}) is judge
