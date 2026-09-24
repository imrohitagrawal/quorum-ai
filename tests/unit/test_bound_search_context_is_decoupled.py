"""#268 option (b), ADR-0125: a truer web-search context constant cannot move
an affordable mix into BLOCK, because the fail-safe bound prices that term
from its own figure (``BOUND_WEB_SEARCH_CONTEXT_TOKENS``), not the setting.

Swept over every four-model mix of the pinned fallback catalog (C(13,4) =
715), at three query lengths, in BOTH peer-critique postures, at the values
ADR-0119 measured.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from decimal import Decimal
from time import monotonic

import pytest

from product_app import costs
from product_app.catalog_fetcher import _FALLBACK_CATALOG, openrouter_catalog_fetcher
from product_app.config import settings
from product_app.costs import CostEstimationService, CostThresholdAction
from product_app.model_slots import ModelSlot

# Query length decides WHICH mixes sit near a band edge, so one length is not
# enough. At the short query (ADR-0119's) the old coupled structure moves 44
# mixes into BLOCK with peer critique off; at 4,000 characters and above those
# mixes are BLOCK already, and a long-only sweep would read 0 in that posture.
_QUERIES = (
    "Compare durable storage options and justify the trade-offs.",
    "x" * 1_000,
    "x" * 16_000,
)
_VALUES = (2500, 2900, 3200)


@pytest.fixture(autouse=True)
def _pinned_fallback_catalog() -> Iterator[None]:
    """Prices are a process-global cache; pin the offline table for the sweep."""
    fetcher = openrouter_catalog_fetcher
    previous_entries = fetcher._cache_entries  # noqa: SLF001
    previous_expiry = fetcher._cache_expires_at  # noqa: SLF001
    fetcher._cache_entries = list(_FALLBACK_CATALOG)  # noqa: SLF001
    fetcher._cache_expires_at = monotonic() + 86_400.0  # noqa: SLF001
    try:
        yield
    finally:
        fetcher._cache_entries = previous_entries  # noqa: SLF001
        fetcher._cache_expires_at = previous_expiry  # noqa: SLF001


def _mixes() -> list[list[ModelSlot]]:
    ids = sorted({entry.model_id for entry in _FALLBACK_CATALOG})
    return [
        [
            ModelSlot(slot_number=i + 1, model_id=model_id, search=True)
            for i, model_id in enumerate(combo)
        ]
        for combo in itertools.combinations(ids, 4)
    ]


def _sweep(
    queries: tuple[str, ...] = _QUERIES,
) -> list[tuple[Decimal, Decimal, CostThresholdAction]]:
    service = CostEstimationService(binding_secret="x" * 32)
    rows = []
    for query, slots in itertools.product(queries, _mixes()):
        estimate = service.estimate(query_text=query, model_slots=slots)
        assert estimate.max_cost_usd is not None
        rows.append((estimate.estimated_cost_usd, estimate.max_cost_usd, estimate.threshold_action))
    return rows


def test_the_sweep_covers_every_four_model_mix() -> None:
    """Empty-input floor: a sweep over nothing would pass every check below."""
    assert len(_mixes()) == 715
    assert len(_sweep()) == 715 * 3


@pytest.mark.parametrize("peer", [False, True])
def test_a_truer_constant_moves_every_point_and_no_bound_or_band(
    monkeypatch: pytest.MonkeyPatch, peer: bool
) -> None:
    """The package's proof. RED IF: the bound reads the setting again (bands
    then move under peer critique), or the setting stops reaching the point
    estimate (the 'point moved' partner then reads 0).

    Not asserted here: ``point <= bound``. With peer critique off, a setting
    of 2900 or 3200 puts the point above the bound on 55 mixes at queries of
    12,000 characters and more, all of them already BLOCK. ADR-0125 leaves
    that to the decision that raises the setting; a test pinning it either
    way would lock in an undecided answer."""
    monkeypatch.setattr(settings, "peer_critique_enabled", peer)
    monkeypatch.setattr(settings, "cost_web_search_context_tokens", 2000)
    base = _sweep()
    for value in _VALUES:
        monkeypatch.setattr(settings, "cost_web_search_context_tokens", value)
        rows = _sweep()
        assert sum(1 for b, r in zip(base, rows, strict=True) if r[2] != b[2]) == 0, value
        assert sum(1 for b, r in zip(base, rows, strict=True) if r[1] != b[1]) == 0, value
        # Positive partner: the setting still reaches the displayed estimate.
        assert sum(1 for b, r in zip(base, rows, strict=True) if r[0] > b[0]) == len(rows), value


def test_under_the_old_structure_the_same_raise_blocks_affordable_mixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep reaches the mixes D5 is about: with the bound coupled back to
    the setting (the pre-ADR-0125 structure), raising it to 2900 moves
    affordable mixes into BLOCK in production's posture, peer critique off
    (44 on this table at the short query). RED IF this reads 0: the proof
    above would then pass over mixes no raise could tip."""
    monkeypatch.setattr(settings, "peer_critique_enabled", False)
    monkeypatch.setattr(settings, "cost_web_search_context_tokens", 2000)
    base = _sweep()
    monkeypatch.setattr(settings, "cost_web_search_context_tokens", 2900)
    monkeypatch.setattr(costs, "BOUND_WEB_SEARCH_CONTEXT_TOKENS", 2900)
    coupled = _sweep()
    newly_blocked = sum(
        1
        for b, r in zip(base, coupled, strict=True)
        if r[2] is CostThresholdAction.BLOCK and b[2] is not CostThresholdAction.BLOCK
    )
    assert newly_blocked > 0


def test_the_bound_constant_equals_the_shipped_setting() -> None:
    """At the shipped values the restructure changes nothing (ADR-0125):
    the bound's figure and the setting's default are both 2000. RED IF either
    moves without the other being decided (a value change is the owner's)."""
    from product_app.config import Settings

    assert costs.BOUND_WEB_SEARCH_CONTEXT_TOKENS == 2000
    assert Settings(_env_file=None).cost_web_search_context_tokens == 2000  # type: ignore[call-arg]
