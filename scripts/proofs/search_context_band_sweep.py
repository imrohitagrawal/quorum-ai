"""What ``cost_web_search_context_tokens`` moves, across every four-model mix.

Neither existing sweep can do this: ``debate_output_band_sweep.py`` sweeps
``cost_debate_output_tokens`` and ``search_fee_band_sweep.py`` sweeps
``cost_web_search_request_fee_usd``. This one prices every four-model
combination of ``_FALLBACK_CATALOG`` (C(13,4) = 715) at each value of
``cost_web_search_context_tokens``, through the repo's own estimator. It prices
nothing itself and requests no completion.

UNLIKE THE DEBATE CONSTANT, THIS ONE FEEDS THE FAIL-SAFE BOUND, so a higher
value can move a mix into ``block``. That is why the output counts, per value,
the mixes that change band and the mixes that newly become ``block``, and why
it prints the default panel's runs per day.

WITHOUT ``--fallback-prices`` THIS FETCHES THE LIVE CATALOG (free, no key), and
offline it silently falls back to the static table. Pass ``--fallback-prices``
for a figure that is reproducible offline forever.

Every run prints its POSTURE and its PRICE SOURCE before any number, and
REFUSES to run when the configured judge is not in the price table it was told
to use: a judge priced at the unknown-model fallback makes every figure an
artefact (that reached ADR-0113 once, on 2026-09-15).

    PYTHONPATH=src uv run python scripts/proofs/search_context_band_sweep.py --fallback-prices
    PYTHONPATH=src uv run python scripts/proofs/search_context_band_sweep.py --values 2000 2900
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from collections import Counter
from decimal import ROUND_FLOOR, Decimal

from product_app import config
from product_app.catalog_fetcher import _FALLBACK_CATALOG
from product_app.costs import (
    DAILY_CAP_USD,
    HARD_LIMIT_USD,
    SOFT_THRESHOLD_USD,
    cost_estimation_service,
)
from product_app.evaluation import judge_configured
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    ModelSlot,
    openrouter_model_catalog_service,
)

#: The same query the other two sweeps use, so the three are comparable.
DEFAULT_QUERY = "Compare durable storage options and justify the trade-offs."

#: The first value is the baseline every other value is compared against.
DEFAULT_VALUES = (2000, 2500, 2900, 3200)

_NO_OVERRIDE = object()


def _slots(model_ids: tuple[str, ...]) -> list[ModelSlot]:
    return [
        ModelSlot(slot_number=index + 1, model_id=model_id, search=True)
        for index, model_id in enumerate(model_ids)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--values",
        type=int,
        nargs="+",
        default=list(DEFAULT_VALUES),
        help="cost_web_search_context_tokens values to sweep (first is the baseline)",
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument(
        "--fallback-prices",
        action="store_true",
        help="force the static _FALLBACK_CATALOG price table (offline-reproducible).",
    )
    args = parser.parse_args(argv)
    # Put back what this run found, on EVERY exit path. The sweep mutates a
    # process-global setting and may override the catalog singleton's
    # ``price_index``; restore the VALUE that was there, not "no override"
    # (``search_fee_band_sweep.py`` records why).
    value_before = config.settings.cost_web_search_context_tokens
    singleton_attrs = vars(openrouter_model_catalog_service)
    override_before = singleton_attrs.get("price_index", _NO_OVERRIDE)
    try:
        return _run(args)
    finally:
        config.settings.cost_web_search_context_tokens = value_before
        if override_before is _NO_OVERRIDE:
            singleton_attrs.pop("price_index", None)
        else:
            singleton_attrs["price_index"] = override_before


def _run(args: argparse.Namespace) -> int:
    if args.fallback_prices:
        table = {
            entry.model_id: (entry.input_price_per_1k, entry.output_price_per_1k)
            for entry in _FALLBACK_CATALOG
        }
        openrouter_model_catalog_service.price_index = lambda: table  # type: ignore[method-assign]
        price_source = "static _FALLBACK_CATALOG (--fallback-prices)"
    else:
        price_source = "catalog service (LIVE when reachable, static table when offline)"
    prices = openrouter_model_catalog_service.price_index()

    print(
        f"POSTURE: peer_critique_enabled={config.settings.peer_critique_enabled} "
        f"judge_configured={judge_configured()} "
        f"judge_model_id={config.settings.quorum_eval_judge_model_id or '(unset)'}"
    )
    print(f"PRICES:  {price_source}; {len(prices)} models priced")
    judge_id = config.settings.quorum_eval_judge_model_id
    if judge_configured() and judge_id not in prices:
        print(
            f"REFUSED: judge model {judge_id!r} is not in the price table ({price_source}); "
            "it would be priced at the unknown-model fallback and every figure below would "
            "be an artefact of that fallback, not of production. Use the live catalog, or a "
            "judge id the static table prices."
        )
        return 2
    print(
        f"THRESHOLDS: SOFT={SOFT_THRESHOLD_USD} DAILY_CAP={DAILY_CAP_USD} HARD={HARD_LIMIT_USD} "
        f"fee={config.settings.cost_web_search_request_fee_usd}"
    )
    model_ids = tuple(entry.model_id for entry in _FALLBACK_CATALOG)
    mixes = list(itertools.combinations(model_ids, 4))
    print(f"QUERY: {len(args.query)} chars, search=True on every slot")
    print(f"MIXES: {len(mixes)} (four distinct models from {len(model_ids)} in _FALLBACK_CATALOG)")
    print()

    baseline: dict[tuple[str, ...], tuple[Decimal, Decimal, str]] = {}
    for value in args.values:
        config.settings.cost_web_search_context_tokens = value
        priced: dict[tuple[str, ...], tuple[Decimal, Decimal, str]] = {}
        for mix in mixes:
            estimate = cost_estimation_service.estimate(
                query_text=args.query, model_slots=_slots(mix)
            )
            priced[mix] = (
                estimate.estimated_cost_usd,
                estimate.max_cost_usd or Decimal(0),
                estimate.threshold_action.value,
            )
        if not baseline:
            baseline = priced

        bands = Counter(action for _, _, action in priced.values())
        transitions = Counter(
            (baseline[mix][2], priced[mix][2])
            for mix in mixes
            if baseline[mix][2] != priced[mix][2]
        )
        newly_blocked = [
            mix for mix in mixes if priced[mix][2] == "block" and baseline[mix][2] != "block"
        ]
        new_blocks = len(newly_blocked)
        bound_moved = sum(baseline[mix][1] != priced[mix][1] for mix in mixes)
        point_moved = sum(baseline[mix][0] != priced[mix][0] for mix in mixes)
        points = sorted(point for point, _, _ in priced.values())

        default = cost_estimation_service.estimate(
            query_text=args.query, model_slots=_slots(tuple(DEFAULT_MODEL_IDS))
        )
        runs_per_day = int(
            (DAILY_CAP_USD / default.estimated_cost_usd).to_integral_value(rounding=ROUND_FLOOR)
        )

        print(f"== cost_web_search_context_tokens={value}")
        print(f"   bands {dict(sorted(bands.items()))}")
        print(
            f"   vs {args.values[0]}: {sum(transitions.values())} mixes change band, "
            f"{new_blocks} newly 'block'  {dict(sorted(transitions.items()))}"
        )
        # Rule 7: say what moved, so a row of zeros cannot be a sweep that
        # never reached the constant.
        print(
            f"   point estimate moved on {point_moved}/{len(mixes)} mixes, "
            f"fail-safe bound moved on {bound_moved}/{len(mixes)}"
        )
        print(f"   point min/median/max: {points[0]} / {statistics.median(points)} / {points[-1]}")
        print(
            f"   DEFAULT panel: point {default.estimated_cost_usd} bound {default.max_cost_usd} "
            f"band {default.threshold_action.value} runs/day {runs_per_day}"
        )
        for mix in newly_blocked:
            was, now = baseline[mix][1], priced[mix][1]
            print(f"   newly 'block': bound {now} (was {was})  {', '.join(mix)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
