"""W37 (ADR-0143): what a follow-up costs at different final-answer lengths.

Hermetic: no provider call, no network, no spend. It prints the posture, the panel and
the price source before any number, because every figure below moves with them.

    uv run python scripts/proofs/w37_follow_up_cost_sweep.py

It sets production's judge posture (judge on per `/status` on 2026-10-04; model
`openai/gpt-4.1-mini` per the 2026-09-10 telemetry, since `/status` does not report it)
with a dummy key — no call is made — and reads the built-in
price table (`_CATALOG_FALLBACK_ENTRIES`), never the live catalog, so two runs agree.
For the peer-critique posture, turn the peer-critique setting on in the environment
(`config.Settings.peer_critique_enabled`); the first line printed says which posture ran.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QUORUM_TOKEN_SECRET", "w37-sweep-" + "x" * 32)
os.environ.setdefault("QUORUM_EVAL_JUDGE_API_KEY", "dummy-no-call-is-made")
os.environ.setdefault("QUORUM_EVAL_JUDGE_MODEL_ID", "openai/gpt-4.1-mini")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from product_app import (  # noqa: E402
    costs,
    evaluation,
    model_slots,  # noqa: E402
)
from product_app.config import settings  # noqa: E402
from product_app.model_slots import DEFAULT_MODEL_IDS, ModelSlot  # noqa: E402


def _no_live_catalog() -> list:
    raise RuntimeError("the sweep reads the built-in price table only")


model_slots.openrouter_catalog_fetcher.list_models = _no_live_catalog

QUESTION = "How should a small team choose between Postgres and MySQL?"
LENGTHS = (0, 2_000, 8_000, 20_000, 38_000, 60_117)


def main() -> int:
    svc = costs.cost_estimation_service
    slots = [ModelSlot(slot_number=i + 1, model_id=m) for i, m in enumerate(DEFAULT_MODEL_IDS)]
    print(
        "POSTURE",
        f"peer_critique_enabled={settings.peer_critique_enabled}",
        f"judge_configured={evaluation.judge_configured()}",
        f"judge_model={settings.quorum_eval_judge_model_id or '-'}",
    )
    print("SLOTS", [s.model_id for s in slots])
    print("PRICES built-in table (_CATALOG_FALLBACK_ENTRIES), live catalog disabled")
    print("SOURCE src/product_app/costs.py:", Path(costs.__file__).resolve())
    print("length  typical  ceiling  band  runs_per_daily_cap")
    for length in LENGTHS:
        context = (
            None if length == 0 else {"prior_question": QUESTION, "prior_synthesis": "x" * length}
        )
        typical = svc._estimate_breakdown(
            query_text=QUESTION, model_slots=slots, context=context
        ).total
        ceiling = svc._estimate_bound_usd(query_text=QUESTION, model_slots=slots, context=context)
        band, _ = svc._threshold_for(ceiling)
        runs = int(costs.DAILY_CAP_USD // Decimal(str(typical)))
        print(f"{length:>6}  {Decimal(str(typical)):.4f}  {ceiling:.4f}  {band.value}  {runs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
