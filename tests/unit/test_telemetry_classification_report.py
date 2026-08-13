"""Guard ``scripts/telemetry_classification_report.py``.

That script reads the two durable telemetry JSONL streams shipped by
commit ab4296c (#105/#268/#203) and prints the decision-support numbers
ADR-0031 already spells out per issue. **It never decides anything** — it
prints the counts and, once a rule's stated sample floor is met, the verdict
that rule produces. Below the floor it must say so honestly rather than
guess from a small N.

These tests build synthetic JSONL records (never real production data, none
exists yet) and assert the exact classification/insufficiency behaviour so a
change to the thresholds or the grouping logic is caught.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "telemetry_classification_report.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "telemetry_classification_report_under_test", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


report: Any = _load_script()


def _billing_5xx(status_code: int, *, provider_named: bool) -> dict[str, object]:
    """One ``upstream_provider_http_error`` record on the 5xx branch.

    ``provider_named`` mirrors the ADR-0031 §"reading that settles #105"
    grouping: True means the body or a header named the provider (so the
    router did NOT refuse before dispatch); False means neither did (a
    router-level refusal, on the evidence).
    """
    return {
        "message": "upstream_provider_http_error",
        "status_code": status_code,
        "provider_name_present": provider_named,
        "provider_name_header": False,
        "error_metadata_present": provider_named,
    }


def _billing_5xx_unknown(status_code: int) -> dict[str, object]:
    return {
        "message": "upstream_provider_http_error",
        "status_code": status_code,
        "provider_name_present": None,
        "provider_name_header": False,
        "error_metadata_present": False,
    }


def _token_record(*, search_enabled: bool, injected_tokens_est: int) -> dict[str, object]:
    return {
        "message": "provider_call_tokens",
        "search_enabled": search_enabled,
        "injected_tokens_est": injected_tokens_est,
    }


def _refusal_record(
    *, status_code: int, content_type_main: str, server_class: str, expose: object
) -> dict[str, object]:
    return {
        "message": "key_probe_credential_refused",
        "status_code": status_code,
        "content_type_main": content_type_main,
        "server_class": server_class,
        "expose_headers_names_openrouter": expose,
    }


# ---------------------------------------------------------------------------
# #105 — router-refusal vs provider-named 5xx classification
# ---------------------------------------------------------------------------


def test_105_reports_insufficient_below_the_stated_floor_of_30() -> None:
    # RED-if: replacing "< report.MIN_N_105" with "< 1" (i.e. deleting the
    # floor) makes this assert a verdict string instead, and the test fails.
    records = [_billing_5xx(503, provider_named=False) for _ in range(29)]
    result = report.classify_billing_5xx(records)
    assert result[503]["n"] == 29
    assert result[503]["verdict"] == f"insufficient data (29/{report.MIN_N_105})"


def test_105_recommends_reclassification_once_router_refusal_dominates() -> None:
    # RED-if: the >=0.95 threshold is loosened to >=0.50 — a 60% router-refusal
    # sample would then wrongly recommend reclassifying.
    records = [_billing_5xx(503, provider_named=False) for _ in range(30)]
    result = report.classify_billing_5xx(records)
    assert result[503]["n"] == 30
    assert result[503]["router_refusal"] == 30
    assert result[503]["provider_named"] == 0
    assert "reclassify 503 to unbilled" in result[503]["verdict"]


def test_105_does_not_reclassify_below_the_95_percent_router_refusal_bar() -> None:
    # RED-if: the >=0.95 threshold is loosened to >=0.80 — this 80%
    # router-refusal, 20% "neither present nor named" sample would then
    # wrongly recommend reclassifying instead of leaving it possibly-billed.
    records = [_billing_5xx(503, provider_named=False) for _ in range(24)] + [
        {
            "message": "upstream_provider_http_error",
            "status_code": 503,
            "provider_name_present": False,
            "provider_name_header": False,
            "error_metadata_present": True,  # present, so not a router refusal
        }
        for _ in range(6)
    ]
    result = report.classify_billing_5xx(records)
    assert result[503]["n"] == 30
    assert result[503]["router_refusal"] == 24
    assert result[503]["provider_named"] == 0
    assert result[503]["verdict"] == "leave possibly-billed (router-refusal share under 0.95)"


def test_105_leaves_status_possibly_billed_when_provider_is_ever_named() -> None:
    records = [_billing_5xx(503, provider_named=False) for _ in range(29)] + [
        _billing_5xx(503, provider_named=True)
    ]
    result = report.classify_billing_5xx(records)
    assert result[503]["provider_named"] == 1
    assert result[503]["verdict"] == "leave possibly-billed (provider named at least once)"


def test_105_stops_when_unknown_share_exceeds_20_percent() -> None:
    # RED-if: the 0.20 unknown-share guard is removed — a 21%-unknown sample
    # would then fall through to a router-refusal verdict instead of STOP.
    records = [_billing_5xx(503, provider_named=False) for _ in range(23)] + [
        _billing_5xx_unknown(503) for _ in range(7)
    ]
    result = report.classify_billing_5xx(records)
    assert result[503]["n"] == 30
    assert result[503]["unknown"] == 7
    assert "STOP" in result[503]["verdict"]


def test_105_groups_per_status_code_never_pooled() -> None:
    # RED-if: status codes are pooled into one group instead of grouped —
    # the two status codes below would collapse into a single n=31 bucket.
    records = [_billing_5xx(503, provider_named=False) for _ in range(30)] + [
        _billing_5xx(500, provider_named=False)
    ]
    result = report.classify_billing_5xx(records)
    assert result[500]["n"] == 1
    assert result[500]["verdict"] == f"insufficient data (1/{report.MIN_N_105})"
    assert result[503]["n"] == 30


# ---------------------------------------------------------------------------
# #268 — injected input-token estimation
# ---------------------------------------------------------------------------


def test_268_voids_the_whole_reading_when_the_estimator_partner_check_fails() -> None:
    # RED-if: the p95-under-500 non-search partner check is deleted — a
    # broken estimator (p95 way over 500 on non-search calls) would then be
    # reported as a normal reading instead of VOID.
    non_search = [_token_record(search_enabled=False, injected_tokens_est=900) for _ in range(30)]
    searching = [_token_record(search_enabled=True, injected_tokens_est=1500) for _ in range(60)]
    result = report.classify_token_injection(non_search + searching)
    assert result["estimator_partner_check"] == "FAILED"
    assert "VOID" in result["verdict"]


def test_268_reports_insufficient_below_the_stated_floor_of_50_searching_calls() -> None:
    non_search = [_token_record(search_enabled=False, injected_tokens_est=100) for _ in range(30)]
    searching = [_token_record(search_enabled=True, injected_tokens_est=1500) for _ in range(49)]
    result = report.classify_token_injection(non_search + searching)
    assert result["estimator_partner_check"] == "passed"
    assert result["searching_n"] == 49
    assert result["verdict"] == f"insufficient data (49/{report.MIN_N_268_SEARCHING})"


def test_268_recommends_raising_the_constant_when_p95_exceeds_2000() -> None:
    non_search = [_token_record(search_enabled=False, injected_tokens_est=100) for _ in range(30)]
    # 50 calls, p95 (index 47 of a 0-indexed sorted 50-length list under the
    # ADR's `length*0.95|floor` rule) is comfortably above 2000.
    searching = [_token_record(search_enabled=True, injected_tokens_est=2500) for _ in range(50)]
    result = report.classify_token_injection(non_search + searching)
    assert result["injected_p95"] > 2000
    assert "raise cost_web_search_context_tokens" in result["verdict"]


def test_268_reports_injected_max_regardless_of_verdict() -> None:
    non_search = [_token_record(search_enabled=False, injected_tokens_est=100) for _ in range(30)]
    searching = [_token_record(search_enabled=True, injected_tokens_est=n) for n in range(1, 51)]
    result = report.classify_token_injection(non_search + searching)
    assert result["injected_max"] == 50


# ---------------------------------------------------------------------------
# #203 — credential-refusal shape diversity
# ---------------------------------------------------------------------------


def test_203_reports_insufficient_with_zero_403_records() -> None:
    result = report.classify_credential_refusal_shapes([])
    assert result["n"] == 0
    assert result["verdict"] == f"insufficient data (0/{report.MIN_N_203})"


def test_203_reports_single_shape_as_no_evidence_of_a_second_answerer() -> None:
    records = [
        _refusal_record(
            status_code=403,
            content_type_main="application/json",
            server_class="cloudflare",
            expose=True,
        )
        for _ in range(5)
    ]
    result = report.classify_credential_refusal_shapes(records)
    assert result["distinct_shapes"] == 1
    assert "no evidence of a second answerer" in result["verdict"]


def test_203_flags_two_or_more_distinct_shapes_under_403() -> None:
    # RED-if: shape grouping keys off status_code alone (dropping the other
    # three fields) — these two records would then collapse into one shape.
    records = [
        _refusal_record(
            status_code=403,
            content_type_main="application/json",
            server_class="cloudflare",
            expose=True,
        ),
        _refusal_record(
            status_code=403, content_type_main="text/html", server_class="other", expose=False
        ),
    ]
    result = report.classify_credential_refusal_shapes(records)
    assert result["distinct_shapes"] == 2
    assert "something to disambiguate" in result["verdict"]


def test_203_ignores_non_403_records() -> None:
    records = [
        _refusal_record(
            status_code=401,
            content_type_main="application/json",
            server_class="cloudflare",
            expose=True,
        )
    ]
    result = report.classify_credential_refusal_shapes(records)
    assert result["n"] == 0


# ---------------------------------------------------------------------------
# JSONL reading + CLI surface
# ---------------------------------------------------------------------------


def test_read_jsonl_skips_blank_lines_and_parses_each_record(tmp_path: Path) -> None:
    path = tmp_path / "telemetry-billing.jsonl"
    path.write_text(
        json.dumps({"message": "upstream_provider_http_error", "status_code": 503})
        + "\n\n"
        + json.dumps({"message": "key_probe_credential_refused", "status_code": 403})
        + "\n"
    )
    records = report.read_jsonl(path)
    assert len(records) == 2
    assert records[0]["status_code"] == 503


def test_read_jsonl_returns_empty_list_for_a_missing_file(tmp_path: Path) -> None:
    # RED-if: a missing file raises instead of reporting zero samples — the
    # whole point is running this before any production data exists.
    records = report.read_jsonl(tmp_path / "does-not-exist.jsonl")
    assert records == []


def test_main_prints_a_report_section_for_each_of_the_three_issues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    billing = tmp_path / "telemetry-billing.jsonl"
    tokens = tmp_path / "telemetry-tokens.jsonl"
    billing.write_text("")
    tokens.write_text("")
    report.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "#105" in out
    assert "#268" in out
    assert "#203" in out
    assert "insufficient data (0/" in out
