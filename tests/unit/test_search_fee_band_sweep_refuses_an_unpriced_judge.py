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
from collections.abc import Callable
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


_ABSENT = object()


#: A fee no code path sets: the sweep ends at MEASURED_FEE (0.007), which is
#: also the shipped default, so a missing restore would be invisible against
#: the default. Measured 2026-09-15: the "no fee restore" mutant survived until
#: the tests started from this value instead.
DISTINCTIVE_FEE = 0.0123


def _globals_before(sweep: ModuleType, monkeypatch: pytest.MonkeyPatch) -> tuple[float, object]:
    """The two process globals ``main()`` mutates, as they are before the call.

    The catalog singleton may already carry an instance-level ``price_index``
    override left by an earlier test in the same process; ``main()`` must put
    back whatever it found, not a clean slate — so the contract is "after equals
    before", by identity, not "no override". The fee is set to a value the
    sweep never ends at, so "not restored" cannot pass by coincidence.
    """
    monkeypatch.setattr(sweep.config.settings, "cost_web_search_request_fee_usd", DISTINCTIVE_FEE)
    return (
        sweep.config.settings.cost_web_search_request_fee_usd,
        vars(sweep.openrouter_model_catalog_service).get("price_index", _ABSENT),
    )


def _assert_restored(sweep: ModuleType, before: tuple[float, object]) -> None:
    fee_before, override_before = before
    assert sweep.config.settings.cost_web_search_request_fee_usd == fee_before
    override_after = vars(sweep.openrouter_model_catalog_service).get("price_index", _ABSENT)
    assert override_after is override_before, (
        "main() did not put the catalog singleton's price_index back the way it found it: "
        f"before={override_before!r} after={override_after!r}"
    )


@pytest.mark.parametrize("judge_id", ["openai/gpt-4.1-mini", "nonsense/not-a-model"])
def test_the_sweep_refuses_a_judge_the_static_table_cannot_price(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], judge_id: str
) -> None:
    sweep = _load_sweep()
    monkeypatch.setattr(sweep, "judge_configured", lambda: True)
    monkeypatch.setattr(sweep.config.settings, "quorum_eval_judge_model_id", judge_id)
    assert judge_id not in {entry.model_id for entry in sweep._FALLBACK_CATALOG}
    before = _globals_before(sweep, monkeypatch)
    rc = sweep.main(["--fallback-prices"])
    _assert_restored(sweep, before)
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
    before = _globals_before(sweep, monkeypatch)
    rc = sweep.main(["--fallback-prices"])
    _assert_restored(sweep, before)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "REFUSED" not in out
    assert f"judge_model_id={priced}" in out
    assert "change band" in out


def test_the_sweep_preserves_an_override_a_caller_already_installed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The full suite runs this file after tests that leave an instance-level
    ``price_index`` on the catalog singleton. ``main()`` must hand that exact
    object back, not delete it — measured 2026-09-15: the first version of
    ``_assert_restored`` demanded "no override" and went red in the full suite
    while green alone.

    RED IF: ``main()`` pops a pre-existing override, or replaces it with its own.
    """
    sweep = _load_sweep()
    priced = "openai/gpt-4o-mini"
    monkeypatch.setattr(sweep, "judge_configured", lambda: True)
    monkeypatch.setattr(sweep.config.settings, "quorum_eval_judge_model_id", priced)
    installed: Callable[[], dict[str, object]] = lambda: {}  # noqa: E731 - identity is the point
    monkeypatch.setitem(vars(sweep.openrouter_model_catalog_service), "price_index", installed)
    before = _globals_before(sweep, monkeypatch)
    assert before[1] is installed
    rc = sweep.main(["--fallback-prices"])
    capsys.readouterr()
    assert rc == 0
    _assert_restored(sweep, before)
