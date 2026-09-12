"""Re-derivable sweep: what activating the :online search fee does to the bands.

ADR-0110 escalates ONE decision to the product owner — whether to set
``cost_web_search_request_fee_usd`` to the measured $0.007 — and that decision
turns on two numbers: how many model mixes change cost-guardrail band, and how
many runs a day the per-account cap still admits.

The first version of that ADR stated those numbers with no committed script, and
adversarial review could not reproduce them: the figure moves with the QUERY
LENGTH (the bound scales with prompt tokens), with the PEER-CRITIQUE and JUDGE
postures, and with whether prices come from the live catalog or the static
fallback. Three reviewers got three different answers, all of them defensible.
A money decision cannot rest on a number nobody else can re-derive, so this
script exists and the ADR cites it.

    uv run python scripts/proofs/search_fee_band_sweep.py

WITHOUT ``--fallback-prices`` THIS FETCHES THE LIVE CATALOG. ``price_index()``
calls ``GET https://openrouter.ai/api/v1/models`` on a cold cache — free, no
completion, no tokens, but a network call, and it returns ~440 models rather
than the 13 static ones. Run offline it falls back to the static table and
silently reproduces the ``--fallback-prices`` figures instead. Pass
``--fallback-prices`` for a figure that is reproducible offline forever.

Every run prints its POSTURE and its PRICE SOURCE before any number, because a
band figure without its posture is worthless. An earlier version printed a bogus
judge field that always read ``n/a``, and that is exactly how a "production"
figure measured with the judge OFF reached an ADR — production runs the judge
ON, and turning it on moves both the band counts and the daily envelope.

No completion is ever requested, so nothing here spends money.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from collections import Counter
from decimal import ROUND_FLOOR, Decimal

from product_app import config
from product_app.catalog_fetcher import _FALLBACK_CATALOG
from product_app.costs import DAILY_CAP_USD, cost_estimation_service
from product_app.evaluation import judge_configured
from product_app.model_slots import (
    DEFAULT_MODEL_IDS,
    ModelSlot,
    openrouter_model_catalog_service,
)

#: The 59-character query the figures in ADR-0110 were measured on. The bound
#: grows with the prompt, so a longer question moves every mix further from the
#: band edges and LOWERS the flip count. Stated as a constant, not buried.
DEFAULT_QUERY = "Compare durable storage options and justify the trade-offs."

OFF = 0.0
#: Measured on the owner's OpenRouter activity export for 2026-09-10: 8 of 27
#: generation rows carry a ``cost_web_search`` and every one is exactly this.
MEASURED_FEE = 0.007


def _band(*, fee: float, model_ids: tuple[str, ...], search: bool, query: str) -> str:
    config.settings.cost_web_search_request_fee_usd = fee
    slots = [
        ModelSlot(slot_number=i + 1, model_id=m, search=search) for i, m in enumerate(model_ids)
    ]
    bound = cost_estimation_service._estimate_bound_usd(query_text=query, model_slots=slots)
    action, _reasons = cost_estimation_service._threshold_for(bound)
    return action.value


def _point(*, fee: float, model_ids: tuple[str, ...], query: str) -> Decimal:
    config.settings.cost_web_search_request_fee_usd = fee
    slots = [ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(model_ids)]
    return cost_estimation_service.estimate(query_text=query, model_slots=slots).estimated_cost_usd


def sweep(*, query: str, search: bool) -> tuple[int, Counter[tuple[str, str]]]:
    ids = tuple(entry.model_id for entry in _FALLBACK_CATALOG)
    mixes = list(itertools.combinations_with_replacement(ids, 4))
    transitions: Counter[tuple[str, str]] = Counter()
    for mix in mixes:
        before = _band(fee=OFF, model_ids=mix, search=search, query=query)
        after = _band(fee=MEASURED_FEE, model_ids=mix, search=search, query=query)
        transitions[(before, after)] += 1
    return len(mixes), transitions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument(
        "--fallback-prices",
        action="store_true",
        help="force the static _FALLBACK_CATALOG price table (offline-reproducible).",
    )
    args = parser.parse_args(argv)

    if args.fallback_prices:
        # Point the price index at the static table so the result never depends
        # on what OpenRouter charges today.
        table = {
            entry.model_id: (entry.input_price_per_1k, entry.output_price_per_1k)
            for entry in _FALLBACK_CATALOG
        }
        openrouter_model_catalog_service.price_index = lambda: table  # type: ignore[method-assign]

    # POSTURE FIRST, always. ``judge_configured()`` is the single real predicate
    # (a key AND a pinned model id), and ``/status.judge_enabled`` reports that
    # same one. Production runs peer critique AND the judge ON, and both move
    # every number below.
    price_source = "static _FALLBACK_CATALOG, 13 models (offline-reproducible)"
    if not args.fallback_prices:
        price_source = (
            f"LIVE OpenRouter catalog, {len(openrouter_model_catalog_service.price_index())} "
            "models — drifts with their pricing, and falls back to the static table offline"
        )
    print(f"query ({len(args.query)} chars): {args.query!r}")
    print(f"fee: {OFF} -> {MEASURED_FEE}")
    print(
        f"POSTURE: peer_critique_enabled={config.settings.peer_critique_enabled} "
        f"judge_configured={judge_configured()}"
    )
    print(f"PRICES:  {price_source}")
    print()

    lanes = ((True, "search ON (every slot searching)"), (False, "search OFF (control)"))
    for search, label in lanes:
        total, transitions = sweep(query=args.query, search=search)
        changed = sum(n for (a, b), n in transitions.items() if a != b)
        print(f"{label}: {total} mixes, {changed} change band")
        for (a, b), n in sorted(transitions.items(), key=lambda kv: -kv[1]):
            flag = "  <-- FLIP" if a != b else ""
            print(f"    {a:22} -> {b:22} {n:5}{flag}")
        if not search and changed != 0:
            print("    CONTROL FAILED: a non-searching slot must never owe a fee.")
            return 1
        print()

    ids = tuple(DEFAULT_MODEL_IDS)
    print(f"per-account daily envelope on the SHIPPED default mix {list(ids)}:")
    for fee in (OFF, MEASURED_FEE):
        unit = _point(fee=fee, model_ids=ids, query=args.query)
        runs = int((DAILY_CAP_USD / unit).to_integral_value(rounding=ROUND_FLOOR))
        print(
            f"    fee={fee}: point estimate {unit}  ->  floor({DAILY_CAP_USD}/{unit}) = {runs} runs"
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # _band/_point mutate a process-global setting; undo it on EVERY exit
        # path, including the control-failure return and any exception.
        config.settings.cost_web_search_request_fee_usd = OFF
