"""The accumulation cost rails must be measured in the SAME unit as their meter.

The defect this pins (found by adversarial review of PR #96, introduced by
``59a4a8f`` "PR5b: cost guardrail uses bound instead of estimated"): the
cumulative and daily-cap guards in :mod:`product_app.costs` added the WORST-CASE
``bound`` of the incoming run to a meter that accumulates the realistic POINT
estimate. ``feedback_store.daily_spend_for`` sums ``estimated_cost_usd``, and
``_cumulative_spend_for`` sums recorded events — both point units.

Two user-visible consequences, both reproduced before the fix:

* An account that had spent **nothing** could be told "no further queries can be
  accepted until the window resets", because the incoming run's bound alone
  exceeded the cap.
* The daily cap admitted ``floor((CAP - bound) / unit) + 1`` runs instead of
  ``floor(CAP / unit)`` — one run of headroom permanently unusable, which is
  what `test_daily_cap_admits_the_number_of_runs_its_dollar_value_pays_for`
  was reporting as "7 runs completed, expected 8".

The per-call rail is deliberately NOT covered here: it keeps the bound on
purpose (issue #16 rec #2/#3 — a single call fails safe against its worst case).
The distinction is the whole point, so it is asserted explicitly below.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from product_app.costs import (
    DAILY_CAP_USD,
    CostThresholdAction,
    cost_estimation_service,
)
from product_app.model_slots import ModelSlot

#: An expensive-but-not-blocked mix: the point estimate sits in the ALLOW band
#: while the worst-case bound crosses the daily cap. That gap is exactly where a
#: bound-vs-point unit mismatch shows up.
_MIX = [
    "vendor/rail-expensive",
    "vendor/rail-mid",
    "vendor/rail-cheap",
    "vendor/rail-cheapest",
]

#: PRICES THIS FILE OWNS, not the catalog's (ADR-0102).
#:
#: These tests need a mix whose POINT estimate sits below a rail while its
#: BOUND crosses it — the gap where a bound-vs-point unit mismatch shows. When
#: the threshold ladder went 0.15/0.20/0.25 -> 0.30/0.40/0.50, that window
#: became UNREACHABLE with real models: every 4-model combination of the nine
#: catalog-stable ids, swept across query lengths 1000-9000, failed to put the
#: point under $0.30 while the bound cleared $0.40. The only model in the whole
#: 425-entry live catalog that managed it was ``openai/gpt-5-pro``, which is
#: absent from ``_FALLBACK_CATALOG`` — so the fixture would have asserted one
#: band offline and another live, the exact trap
#: ``test_cost_guardrails`` records paying for once already.
#:
#: Owning the prices removes the catalog from the question entirely, which is
#: the same reason ``test_peer_bound_is_a_true_ceiling`` supplies its own.
#: MEASURED at these values, with the caps the fixture below pins:
#:   long query  ($_QUERY):  point 0.2889, bound 0.4624  -> confirm
#:   short query:            point 0.2154, bound 0.4409  -> confirm
_FIXED_PRICES = {
    "vendor/rail-expensive": (Decimal("0.027"), Decimal("0.135")),
    "vendor/rail-mid": (Decimal("0.00027"), Decimal("0.00108")),
    "vendor/rail-cheap": (Decimal("0.00054"), Decimal("0.0045")),
    "vendor/rail-cheapest": (Decimal("0.00009"), Decimal("0.00036")),
}
_QUERY = "x" * 2500


def _slots() -> list[ModelSlot]:
    return [ModelSlot(slot_number=i + 1, model_id=m, search=True) for i, m in enumerate(_MIX)]


class _ZeroSpendStore:
    """A store that exists and reports the account has spent nothing."""

    def daily_spend_for(self, account_id: object, **_kwargs: object) -> Decimal:
        return Decimal("0")

    def global_daily_spend(self, **_kwargs: object) -> Decimal:
        return Decimal("0")


@pytest.fixture(autouse=True)
def _point_below_cap_bound_above(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the fixture in the gap this test needs, and make the rail REACHABLE.

    Two things are required or these tests are vacuous — the first draft was,
    and the mutation proof caught it:

    * Pin main's cost caps. With the branch's WP-D caps the bound clears the
      $0.25 hard limit and the per-call rail blocks first, hiding the
      accumulation rails entirely.
    * Install a store. ``costs.py`` reads the daily meter via
      ``feedback_store.get_store()``, which returns ``None`` when no durable
      store is configured — as in a bare unit run — and the whole daily-cap
      branch is then skipped. Without this the tests passed against the very
      defect they exist to catch.
    """
    from product_app import feedback_store
    from product_app.config import settings
    from product_app.model_slots import openrouter_model_catalog_service

    monkeypatch.setattr(settings, "cost_debate_output_tokens_cap", 700)
    monkeypatch.setattr(settings, "cost_synthesis_output_tokens", 800)
    monkeypatch.setattr(feedback_store, "get_store", lambda: _ZeroSpendStore())
    # Own the prices too — see _FIXED_PRICES for why the real catalog can no
    # longer place this fixture in the gap these tests need.
    monkeypatch.setattr(
        openrouter_model_catalog_service, "price_index", lambda: dict(_FIXED_PRICES)
    )


def test_a_spend_free_account_is_never_blocked_by_the_daily_cap() -> None:
    """The rail must key off what the account has actually SPENT.

    Before the fix this returned BLOCK with a null confirmation token for an
    account whose recorded spend was zero, because ``0 + bound > DAILY_CAP``.
    """
    estimate = cost_estimation_service.estimate(
        query_text=_QUERY, model_slots=_slots(), account_id=uuid4()
    )

    # Precondition: the fixture must actually straddle the cap, or this proves
    # nothing. Point below, bound above.
    assert estimate.max_cost_usd is not None
    assert estimate.estimated_cost_usd < DAILY_CAP_USD, "precondition: point must be under the cap"
    assert estimate.max_cost_usd > DAILY_CAP_USD, "precondition: bound must exceed the cap"

    assert estimate.threshold_action is not CostThresholdAction.BLOCK, (
        "an account that has spent nothing was refused on the daily cap: "
        f"{[r for r in estimate.reasons]}"
    )
    assert not any("last 24 hours" in reason for reason in estimate.reasons)


def test_the_confirmation_band_stays_reachable_above_the_daily_cap() -> None:
    """A run whose bound exceeds the daily cap must still be confirmable.

    With the bound on the accumulation rail, every such run BLOCKed with
    ``confirmation_token=None``, so the REQUIRE_CONFIRMATION band above
    ``DAILY_CAP_USD`` was dead code and the effective ceiling became the daily
    cap rather than ``HARD_LIMIT_USD``.
    """
    estimate = cost_estimation_service.estimate(
        query_text=_QUERY, model_slots=_slots(), account_id=uuid4()
    )
    assert estimate.max_cost_usd is not None and estimate.max_cost_usd > DAILY_CAP_USD
    assert estimate.threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION
    assert estimate.confirmation_token, "a confirmable estimate must carry a token"


def test_the_per_call_rail_still_keys_off_the_worst_case_bound() -> None:
    """The other direction: fixing the units must NOT weaken the per-call rail.

    Issue #16 rec #2/#3 deliberately evaluates the single-call threshold against
    ``max_cost_usd``. A mix whose point estimate is in the ALLOW band but whose
    bound crosses the soft threshold must still require confirmation.
    """
    estimate = cost_estimation_service.estimate(
        query_text="Compare frontier model safety features.", model_slots=_slots()
    )
    assert estimate.max_cost_usd is not None
    assert estimate.estimated_cost_usd < Decimal("0.30"), "precondition: point is in ALLOW"
    assert estimate.max_cost_usd > Decimal("0.30"), "precondition: bound crosses the soft band"
    assert estimate.threshold_action is CostThresholdAction.REQUIRE_CONFIRMATION
