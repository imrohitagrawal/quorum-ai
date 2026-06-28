"""One-shot helper: seed the feedback SQLite with synthetic data for a smoke test.

Run::

    uv run python scripts/seed_feedback_audit_data.py
    uv run python -m product_app.feedback_audit --output-dir feedback/

The synthetic data is *not* realistic traffic — it is a deterministic
fixture used to verify that the audit prompt receives well-formed
statistics and the report renderer does not blow up on edge cases
(zero events, only one event type, extreme quantile values).

This script is a development helper and is NOT part of the production
audit pipeline. Do not run it in production.
"""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# Make the product_app package importable when run from the repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from product_app.feedback_store import FeedbackStore, configure  # noqa: E402

random.seed(42)
DB_PATH = ROOT / ".data" / "feedback_events.sqlite3"


def _seed() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    store = FeedbackStore(str(DB_PATH))
    configure(store)
    now = datetime.now(UTC)
    # 50 distinct query runs over the last 24h.
    for _ in range(50):
        run_id = uuid4()
        account_id = uuid4()
        started = now - timedelta(hours=random.uniform(0, 24))
        # Per-run provider events (4 model slots, sometimes one falls back).
        models = [
            ("openai/gpt-4o-mini", "openrouter_search"),
            ("anthropic/claude-3-haiku", "openrouter_search"),
            ("google/gemini-2.5-flash-lite", "openrouter_search"),
            ("deepseek/deepseek-chat-v3.1", "openrouter_search"),
        ]
        # Force one model to fall back 30% of the time so the audit has
        # something to flag in the demo data.
        if random.random() < 0.30:
            models[1] = ("anthropic/claude-3-haiku", "local_simulation")
        for model_id, provider_path in models:
            store.record(
                recorder="provider",
                event_type="provider_initial_answer_completed",
                account_id=account_id,
                query_run_id=run_id,
                recorded_at=started,
                payload={
                    "model_id": model_id,
                    "provider_path": provider_path,
                    "duration_ms": random.randint(400, 4000),
                    "fallback_used": provider_path != "openrouter_search",
                    "source_count": random.randint(0, 5),
                    "credential_source": "app_owned",
                },
            )
        # Synthesis event with realistic citation coverage.
        coverage = round(random.uniform(0.20, 0.95), 2)
        store.record(
            recorder="synthesis",
            event_type="synthesis_completed",
            account_id=account_id,
            query_run_id=run_id,
            recorded_at=started + timedelta(seconds=8),
            payload={
                "status": "completed",
                "duration_ms": random.randint(3000, 9000),
                "citation_coverage_ratio": str(coverage),
                "false_consensus_preserved": random.random() > 0.3,
                "high_stakes_warning_required": random.random() < 0.1,
            },
        )
        # Cost event.
        store.record(
            recorder="cost",
            event_type="cost_guardrail_accepted",
            account_id=account_id,
            query_run_id=run_id,
            recorded_at=started,
            payload={
                "threshold_action": random.choice(["allow", "require_confirmation"]),
                "estimated_cost_usd": str(Decimal("0.05") + Decimal(str(random.random() * 0.15))),
                "confirmed": random.random() > 0.5,
            },
        )
        # Debate rounds.
        for round_num in (1, 2):
            store.record(
                recorder="debate",
                event_type="debate_round_completed",
                account_id=account_id,
                query_run_id=run_id,
                recorded_at=started + timedelta(seconds=4 + round_num * 2),
                payload={
                    "round_number": round_num,
                    "focus_areas": ["disagreement", "weak_support", "missing_reasoning"],
                    "duration_ms": random.randint(1500, 6000),
                    "status": "completed",
                    "timed_out": False,
                },
            )
    print(f"Seeded {store.event_count()} events into {DB_PATH}")
    store.close()


if __name__ == "__main__":
    _seed()
