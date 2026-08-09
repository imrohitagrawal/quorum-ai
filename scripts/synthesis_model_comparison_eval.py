"""ADR-0028: reproduce the synthesis quality comparison between two models.

NOT run by CI, NOT run by ``make quality``/``make validate``, NOT hermetic.
This makes REAL, BILLED calls to OpenRouter (~$0.10-0.20 for the default 10
golden cases x 2 models x 5 sections each). It exists so the ADR's quality
claim (gpt-5-mini vs gpt-4o-mini: verbatim quotes and cited source URLs) is a
CHECKABLE claim, not just an assertion in prose -- run this script yourself,
with your own OPENROUTER_API_KEY, to verify or refresh it.

Usage:

    OPENROUTER_API_KEY=sk-... uv run python scripts/synthesis_model_comparison_eval.py \\
        --model-a openai/gpt-4o-mini --model-b openai/gpt-5-mini

    # See the plan and the estimated cost without spending anything:
    uv run python scripts/synthesis_model_comparison_eval.py --dry-run

CAVEAT ON EXACT REPRODUCIBILITY: the original ADR-0028 numbers (140 -> 238
quotes, 24 -> 64 URLs) were a one-off manual measurement with no committed
script or raw output -- there is nothing to byte-for-byte reproduce. This
script is the closest faithful substitute available: it drives the SAME
production code path (``SynthesisOrchestrationService.produce_final_synthesis``)
over the SAME 10 golden cases (``tests/evals/golden/cases/``) used for that
measurement, with the SAME counting method (double-quoted substrings for
verbatim quotes, ``https?://`` occurrences for cited URLs). It will not
reproduce the exact 140/238/24/64 figures -- the golden fixtures carry no
debate-round text (``debate_outputs=[]``, see ``tests/evals/golden/loader.py``),
so this measures synthesis quality given initial answers alone, a narrower
input than a live four-model run with two debate rounds. What it DOES let a
reader check is the qualitative claim: does gpt-5-mini quote and cite more
than gpt-4o-mini on this repo's own golden set, right now, with today's
prompts.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

QUOTE_PATTERN = re.compile(r'"[^"]{8,}"')
URL_PATTERN = re.compile(r"https?://\S+")


def _load_golden_cases() -> list[object]:
    loader_path = ROOT / "tests" / "evals" / "golden" / "loader.py"
    spec = importlib.util.spec_from_file_location("golden_loader_for_eval", loader_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["golden_loader_for_eval"] = module
    spec.loader.exec_module(module)
    return module.load_cases()


def _count_quotes_and_urls(text_parts: list[str]) -> tuple[int, int]:
    joined = "\n".join(part for part in text_parts if part)
    return len(QUOTE_PATTERN.findall(joined)), len(URL_PATTERN.findall(joined))


def _run_one(case: object, model_id: str, api_key: str) -> tuple[int, int, int]:
    """Returns (quotes, urls, errors) for one case run against one model."""
    from product_app.config import settings
    from product_app.synthesis import SynthesisOrchestrationService

    original_model_id = settings.synthesis_model_id
    settings.synthesis_model_id = model_id
    try:
        service = SynthesisOrchestrationService()
        result = service.produce_final_synthesis(
            account_id=uuid4(),
            query_run_id=uuid4(),
            query_text=case.question,
            initial_answers=case.initial_answers,
            debate_outputs=[],
            openrouter_key=api_key,
        )
    finally:
        settings.synthesis_model_id = original_model_id

    if result.final_synthesis is None:
        return 0, 0, 1

    fs = result.final_synthesis
    quotes, urls = _count_quotes_and_urls(
        [fs.consensus, fs.disagreement, fs.source_support, fs.uncertainty, fs.recommendation]
    )
    errors = 1 if result.failed_steps else 0
    return quotes, urls, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-a", default="openai/gpt-4o-mini")
    parser.add_argument("--model-b", default="openai/gpt-5-mini")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and estimated cost, make no network calls",
    )
    args = parser.parse_args()

    cases = _load_golden_cases()
    n_calls = len(cases) * 2 * 5  # 2 models x 5 synthesis sections per case
    print(f"{len(cases)} golden cases x 2 models x 5 sections = {n_calls} live LLM calls.")
    print("Estimated cost: ~$0.10-0.20 (see ADR-0028 for the original run's $0.14 basis).")

    if args.dry_run:
        print("--dry-run: stopping before any network call.")
        return 0

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: set OPENROUTER_API_KEY to run this for real.", file=sys.stderr)
        return 1

    os.environ.setdefault("OPENROUTER_LIVE_EXECUTION_ENABLED", "true")

    for model_id in (args.model_a, args.model_b):
        total_quotes = total_urls = total_errors = 0
        for case in cases:
            quotes, urls, errors = _run_one(case, model_id, api_key)
            total_quotes += quotes
            total_urls += urls
            total_errors += errors
        print(
            f"{model_id:30s} quotes={total_quotes:4d} urls={total_urls:4d} "
            f"errors={total_errors}/{len(cases)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
