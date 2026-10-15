"""The context-token sweep must refuse a judge the price table cannot price,
must put back the two process globals it touches, and must actually reach the
constant it claims to sweep.

Same contract as ``test_search_fee_band_sweep_refuses_an_unpriced_judge.py``,
for ``scripts/proofs/search_context_band_sweep.py`` (#268's input half). A
figure whose judge is priced at the unknown-model fallback is an artefact, and
that reached an ADR once (2026-09-15).

RED IF: the refusal is removed or returns 0, it fires for a judge the table CAN
price, ``main()`` stops restoring ``cost_web_search_context_tokens`` or the
catalog singleton's ``price_index``, or the sweep stops setting the constant
before it prices (the "moved on" line would then read 0).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_ABSENT = object()

#: A value no code path sets: not the shipped default and not a swept value, so
#: a missing restore cannot pass by coincidence.
DISTINCTIVE_TOKENS = 2345


def _load_sweep() -> ModuleType:
    name = "search_context_band_sweep"
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / "proofs" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


def _globals_before(sweep: ModuleType, monkeypatch: pytest.MonkeyPatch) -> tuple[int, object]:
    monkeypatch.setattr(sweep.config.settings, "cost_web_search_context_tokens", DISTINCTIVE_TOKENS)
    return (
        sweep.config.settings.cost_web_search_context_tokens,
        vars(sweep.openrouter_model_catalog_service).get("price_index", _ABSENT),
    )


def _assert_restored(sweep: ModuleType, before: tuple[int, object]) -> None:
    tokens_before, override_before = before
    assert sweep.config.settings.cost_web_search_context_tokens == tokens_before
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
    rc = sweep.main(["--fallback-prices", "--values", "2000", "2900"])
    _assert_restored(sweep, before)
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "REFUSED: judge model" in out and judge_id in out, out
    assert "POSTURE:" in out and "PRICES:" in out, "posture and price source come first"
    assert "change band" not in out, "the sweep printed figures after refusing"


def test_the_sweep_runs_and_reaches_the_constant_for_a_priced_judge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Positive partner: not a blanket refusal, and not a sweep over nothing."""
    sweep = _load_sweep()
    priced = "openai/gpt-4o-mini"
    assert priced in {entry.model_id for entry in sweep._FALLBACK_CATALOG}
    monkeypatch.setattr(sweep, "judge_configured", lambda: True)
    monkeypatch.setattr(sweep.config.settings, "quorum_eval_judge_model_id", priced)
    before = _globals_before(sweep, monkeypatch)
    rc = sweep.main(["--fallback-prices", "--values", "2000", "2900"])
    _assert_restored(sweep, before)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "REFUSED" not in out
    assert out.index("POSTURE:") < out.index("PRICES:") < out.index("== cost_web_search")
    assert f"judge_model_id={priced}" in out
    assert "MIXES: 715 " in out, out
    # CARDINALITY: the baseline moves nothing against itself, and the second
    # value moves the point estimate on every one of the 715 mixes. A sweep
    # that never set the constant would print 0 for both.
    moved = re.findall(r"point estimate moved on (\d+)/715 mixes", out)
    assert moved == ["0", "715"], out
