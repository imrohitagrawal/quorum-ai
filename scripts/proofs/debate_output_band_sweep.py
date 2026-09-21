"""Reproduce ADR-0115's tables: what ``cost_debate_output_tokens`` moves.

``search_fee_band_sweep.py`` cannot do this. It enumerates
``combinations_with_replacement`` (1,820 mixes, a model allowed twice) and
sweeps the web-search fee, not the debate typical.

This script prices every four-model combination of ``_FALLBACK_CATALOG``
(C(13,4) = 715) at each value of ``cost_debate_output_tokens``, through the
repo's own estimator — it prices nothing itself and requests no completion.

Read the POSTURE and PRICES lines it prints before quoting any number: the
same sweep gives materially different figures under a different posture or
price source, which is why ADR-0115 states both beside its tables.

    uv run python scripts/proofs/debate_output_band_sweep.py
    PEER_CRITIQUE_ENABLED=false uv run python \
        scripts/proofs/debate_output_band_sweep.py --query-chars 16000

The second form is the one that produces ADR-0115's first-run refusal table:
the daily cap meters the POINT estimate while the per-call band keys off the
BOUND, so at long query lengths a mix can be refused outright on a zero-spend
account while its band says ``require_confirmation``. That column is the
reason this script sweeps query length at all.
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
from product_app.debate import DEBATE_ROUND_MAX_TOKENS
from product_app.evaluation import judge_configured
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    ModelSlot,
    openrouter_model_catalog_service,
)

#: The query ADR-0115's main table was measured with, taken from
#: ``search_fee_band_sweep.DEFAULT_QUERY`` so the two sweeps are comparable.
DEFAULT_QUERY = "Compare durable storage options and justify the trade-offs."

DEFAULT_VALUES = (400, 2200)


def _slots(model_ids: tuple[str, ...], *, search: bool) -> list[ModelSlot]:
    return [
        ModelSlot(slot_number=index + 1, model_id=model_id, search=search)
        for index, model_id in enumerate(model_ids)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--values",
        type=int,
        nargs="+",
        default=list(DEFAULT_VALUES),
        help="cost_debate_output_tokens values to sweep (first is the baseline)",
    )
    parser.add_argument("--query-chars", type=int, default=len(DEFAULT_QUERY))
    parser.add_argument("--no-search", action="store_true")
    args = parser.parse_args()

    search = not args.no_search
    query = DEFAULT_QUERY if args.query_chars == len(DEFAULT_QUERY) else "x" * args.query_chars
    prices = openrouter_model_catalog_service.price_index()
    model_ids = tuple(entry.model_id for entry in _FALLBACK_CATALOG)
    mixes = list(itertools.combinations(model_ids, 4))

    print(
        f"POSTURE: peer_critique_enabled={config.settings.peer_critique_enabled} "
        f"judge_configured={judge_configured()} "
        f"judge_model_id={config.settings.quorum_eval_judge_model_id or '(unset)'}"
    )
    print(f"PRICES:  {len(prices)} models from the catalog service (live unless offline)")
    print(
        f"THRESHOLDS: SOFT={SOFT_THRESHOLD_USD} DAILY_CAP={DAILY_CAP_USD} "
        f"HARD={HARD_LIMIT_USD} debate cap={config.settings.cost_debate_output_tokens_cap} "
        f"DEBATE_ROUND_MAX_TOKENS={DEBATE_ROUND_MAX_TOKENS}"
    )
    print(f"QUERY: {len(query)} chars, search={search}")
    print(f"MIXES: {len(mixes)} (C(13,4) over _FALLBACK_CATALOG)")
    print()

    original = config.settings.cost_debate_output_tokens
    baseline: dict[tuple[str, ...], tuple[Decimal, Decimal, str]] = {}
    try:
        for value in args.values:
            config.settings.cost_debate_output_tokens = value
            rows = {
                mix: cost_estimation_service.estimate(
                    query_text=query, model_slots=_slots(mix, search=search)
                )
                for mix in mixes
            }
            priced = {
                mix: (
                    estimate.estimated_cost_usd,
                    estimate.max_cost_usd or Decimal(0),
                    estimate.threshold_action.value,
                )
                for mix, estimate in rows.items()
            }
            if not baseline:
                baseline = priced

            bands = Counter(action for _, _, action in priced.values())
            flips = sum(baseline[mix][2] != priced[mix][2] for mix in mixes)
            bound_moved = sum(baseline[mix][1] != priced[mix][1] for mix in mixes)
            over_bound = sum(point > bound for point, bound, _ in priced.values())
            # The whole point of the script: refused outright on a zero-spend
            # account by the daily cap, although the per-call band did not
            # refuse it. A gate that counts zero must say so (rule 7).
            cap_refused = sum(point > DAILY_CAP_USD for point, _, _ in priced.values())
            cap_refused_unblocked = sum(
                point > DAILY_CAP_USD and action != "block" for point, _, action in priced.values()
            )
            points = sorted(point for point, _, _ in priced.values())

            default = cost_estimation_service.estimate(
                query_text=query, model_slots=_slots(tuple(DEFAULT_MODEL_IDS), search=search)
            )
            assert default.breakdown is not None
            runs_per_day = int(
                (DAILY_CAP_USD / default.estimated_cost_usd).to_integral_value(rounding=ROUND_FLOOR)
            )

            print(f"== cost_debate_output_tokens={value}")
            print(
                f"   bands {dict(sorted(bands.items()))}  band flips vs {args.values[0]}: {flips}"
            )
            print(f"   fail-safe bound changed on {bound_moved}/{len(mixes)} mixes")
            print(f"   point estimate above the bound on {over_bound}/{len(mixes)} mixes")
            print(
                f"   refused on first run by the daily cap: {cap_refused}"
                f"   of those NOT already 'block': {cap_refused_unblocked}"
            )
            print(
                f"   point min/median/max: {points[0]} / {statistics.median(points)} / {points[-1]}"
            )
            print(
                f"   DEFAULT panel: point {default.estimated_cost_usd} "
                f"bound {default.max_cost_usd} band {default.threshold_action.value} "
                f"runs/day {runs_per_day}"
            )
            print(
                "   DEFAULT by_stage: "
                + " ".join(f"{line.stage}={line.usd}" for line in default.breakdown.by_stage)
            )
    finally:
        config.settings.cost_debate_output_tokens = original
    return 0


if __name__ == "__main__":
    sys.exit(main())
