"""The band sweep must refuse a judge the price table cannot price.

On 2026-09-15 ``scripts/proofs/search_fee_band_sweep.py --fallback-prices`` was
run with ``QUORUM_EVAL_JUDGE_MODEL_ID=openai/gpt-4.1-mini`` — production's judge —
which is not in ``_FALLBACK_CATALOG``. ``costs.py`` priced it at the unknown-model
fallback, 2.58x its real price, and the resulting "production" table reached
ADR-0113 and CHG-007 before a reviewer showed that a nonsense judge id produced
the same numbers byte for byte. The sweep now refuses instead of guessing.

RED IF: the refusal is removed, or it stops returning a non-zero exit, or it
fires for a judge the table CAN price (the positive partner below), or ``main()``
stops restoring the process-global fee setting and the catalog singleton's
``price_index`` it overrides (``_assert_restored`` below).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_sweep() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "search_fee_band_sweep", REPO_ROOT / "scripts" / "proofs" / "search_fee_band_sweep.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("search_fee_band_sweep", module)
    spec.loader.exec_module(module)
    return module


def _assert_restored(sweep: ModuleType, fee_before: float) -> None:
    """``main()`` mutates two process globals; both must be back on every exit path."""
    assert sweep.config.settings.cost_web_search_request_fee_usd == fee_before
    assert "price_index" not in vars(sweep.openrouter_model_catalog_service), (
        "main() left the static price table overriding the catalog singleton"
    )


@pytest.mark.parametrize("judge_id", ["openai/gpt-4.1-mini", "nonsense/not-a-model"])
def test_the_sweep_refuses_a_judge_the_static_table_cannot_price(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], judge_id: str
) -> None:
    sweep = _load_sweep()
    monkeypatch.setattr(sweep, "judge_configured", lambda: True)
    monkeypatch.setattr(sweep.config.settings, "quorum_eval_judge_model_id", judge_id)
    assert judge_id not in {entry.model_id for entry in sweep._FALLBACK_CATALOG}
    fee_before = sweep.config.settings.cost_web_search_request_fee_usd
    rc = sweep.main(["--fallback-prices"])
    _assert_restored(sweep, fee_before)
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "REFUSED: judge model" in out and judge_id in out, out
    assert "change band" not in out, "the sweep printed figures after refusing"


def test_the_sweep_runs_for_a_judge_the_static_table_prices(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Positive partner: the refusal is not a blanket refusal."""
    sweep = _load_sweep()
    priced = "openai/gpt-4o-mini"
    assert priced in {entry.model_id for entry in sweep._FALLBACK_CATALOG}
    monkeypatch.setattr(sweep, "judge_configured", lambda: True)
    monkeypatch.setattr(sweep.config.settings, "quorum_eval_judge_model_id", priced)
    fee_before = sweep.config.settings.cost_web_search_request_fee_usd
    rc = sweep.main(["--fallback-prices"])
    _assert_restored(sweep, fee_before)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "REFUSED" not in out
    assert f"judge_model_id={priced}" in out
    assert "change band" in out
