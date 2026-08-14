"""Decision SUPPORT, not a decision, for #105 / #268 / #203.

Reads the two durable JSONL streams commit ab4296c ships
(``telemetry-billing.jsonl``, ``telemetry-tokens.jsonl``) and prints, per
issue, exactly the counts and rule ADR-0031's "The reading that settles each
issue" section already specifies — nothing this script computes is new
policy, and nothing it prints changes ``_UNBILLED_HTTP_STATUSES`` or any
other constant. Below a rule's stated sample floor it prints
``insufficient data (N/required)`` and stops rather than guess from a small N.

See ``docs/analysis/2026-08-14-telemetry-inventory-105-268-203.md`` for the
call-site inventory and ``docs/adr/0031-*.md`` for the rules this mirrors.

Usage::

    python scripts/telemetry_classification_report.py [directory]

``directory`` defaults to ``$TELEMETRY_LOG_DIR``, the same variable
``telemetry_sink.py`` reads to decide where to write. Locally that variable
is normally unset, so the report reads two files that do not exist yet and
truthfully prints zero samples for all three issues — that is the expected
output until the operator's traffic plan (ADR-0031, "stated blocker") puts
real records on the volume.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

#: ADR-0031, "The reading that settles each issue" -> #105: "n < 30 -> not
#: enough. Do not decide."
MIN_N_105 = 30

#: ADR-0031 -> #268: "n < 50 searching calls -> not enough."
MIN_N_268_SEARCHING = 50

#: ADR-0031 -> #268 positive-partner check ("for search_enabled == false,
#: injected_p95 must be under 500"). The ADR states no separate sample floor
#: for the non-search group; this script requires at least one record to
#: compute a percentile at all, which is a floor this script imposes to
#: avoid a ZeroDivisionError / empty-sequence crash, not one the ADR states.
MIN_N_268_NONSEARCHING = 1

#: ADR-0031 -> #203: "does more than one distinct shape appear under status
#: 403?" No sample floor is stated; one record is the minimum needed to
#: observe a shape at all.
MIN_N_203 = 1

#: ADR-0031 -> #268 positive partner: "injected_p95 must be under 500."
_ESTIMATOR_PARTNER_CEILING = 500

#: ADR-0031 -> #268: "injected_p95 > 2000 -> cost_web_search_context_tokens
#: under-estimates ... raise it".
_RAISE_THRESHOLD = 2000

#: ADR-0031 -> #268: "injected_p95 < 1000 over n >= 200 -> over-estimating."
_LOWER_THRESHOLD = 1000
_LOWER_MIN_N = 200

#: ADR-0031 -> #105: "router_refusal/n >= 0.95 and provider_named == 0".
_ROUTER_REFUSAL_SHARE = 0.95

#: ADR-0031 -> #105: "unknown/n > 0.20 -> STOP."
_UNKNOWN_SHARE_STOP = 0.20

BILLING_FILE_NAME = "telemetry-billing.jsonl"
TOKENS_FILE_NAME = "telemetry-tokens.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL telemetry file. Missing file -> empty list, not an error.

    A missing file is the normal state everywhere except the production
    volume: no local run, no test, and no deployment with
    ``TELEMETRY_LOG_DIR`` unset ever creates one.
    """
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def _percentile(values: list[int], fraction: float) -> int:
    """``length * fraction | floor`` indexing, matching the ADR's jq exactly."""
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


def classify_billing_5xx(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per-status-code #105 read: router-refusal share vs provider-named.

    Mirrors ADR-0031's ``jq`` grouping over ``upstream_provider_http_error``
    records with ``status_code >= 500``, grouped **per status code, never
    pooled**.
    """
    by_status: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("message") != "upstream_provider_http_error":
            continue
        status = record.get("status_code")
        if not isinstance(status, int) or status < 500:
            continue
        by_status[status].append(record)

    result: dict[int, dict[str, Any]] = {}
    for status, group in by_status.items():
        n = len(group)
        unknown = sum(1 for r in group if r.get("provider_name_present") is None)
        provider_named = sum(
            1
            for r in group
            if r.get("provider_name_present") is True or r.get("provider_name_header") is True
        )
        router_refusal = sum(
            1
            for r in group
            if r.get("provider_name_present") is False
            and r.get("error_metadata_present") is False
            and r.get("provider_name_header") is False
        )

        if n and unknown / n > _UNKNOWN_SHARE_STOP:
            verdict = (
                "STOP: unknown/n exceeds 0.20 — ADR-0012's "
                "error.metadata.provider_name schema is refuted for this status, "
                "nothing further may proceed"
            )
        elif n < MIN_N_105:
            verdict = f"insufficient data ({n}/{MIN_N_105})"
        elif provider_named > 0:
            verdict = "leave possibly-billed (provider named at least once)"
        elif router_refusal / n >= _ROUTER_REFUSAL_SHARE:
            verdict = (
                f"reclassify {status} to unbilled in _UNBILLED_HTTP_STATUSES "
                f"(own PR, with this count recorded: n={n}, router_refusal={router_refusal})"
            )
        else:
            verdict = "leave possibly-billed (router-refusal share under 0.95)"

        result[status] = {
            "n": n,
            "unknown": unknown,
            "provider_named": provider_named,
            "router_refusal": router_refusal,
            "verdict": verdict,
        }
    return result


def classify_token_injection(records: list[dict[str, Any]]) -> dict[str, Any]:
    """#268 read: the non-search estimator partner check, then the searching verdict."""
    token_records = [r for r in records if r.get("message") == "provider_call_tokens"]
    non_search = [r for r in token_records if r.get("search_enabled") is False]
    searching = [r for r in token_records if r.get("search_enabled") is True]

    non_search_values = [r["injected_tokens_est"] for r in non_search if "injected_tokens_est" in r]
    searching_values = [r["injected_tokens_est"] for r in searching if "injected_tokens_est" in r]

    if len(non_search_values) < MIN_N_268_NONSEARCHING:
        n = len(non_search_values)
        insufficient = f"insufficient data ({n}/{MIN_N_268_NONSEARCHING})"
        return {
            "estimator_partner_check": insufficient,
            "searching_n": len(searching_values),
            "verdict": insufficient,
        }

    non_search_p95 = _percentile(non_search_values, 0.95)
    if non_search_p95 >= _ESTIMATOR_PARTNER_CEILING:
        return {
            "estimator_partner_check": "FAILED",
            "non_search_p95": non_search_p95,
            "searching_n": len(searching_values),
            "verdict": (
                "VOID: non-search injected_p95 "
                f"({non_search_p95}) is not under {_ESTIMATOR_PARTNER_CEILING} — "
                "sent_tokens_est (CHARS_PER_TOKEN) is wrong; fix the estimator "
                "before reading anything else"
            ),
        }

    searching_n = len(searching_values)
    if searching_n < MIN_N_268_SEARCHING:
        return {
            "estimator_partner_check": "passed",
            "non_search_p95": non_search_p95,
            "searching_n": searching_n,
            "verdict": f"insufficient data ({searching_n}/{MIN_N_268_SEARCHING})",
        }

    injected_p95 = _percentile(searching_values, 0.95)
    injected_max = max(searching_values)

    if injected_p95 > _RAISE_THRESHOLD:
        verdict = (
            f"raise cost_web_search_context_tokens to the observed p95 ({injected_p95}), "
            "own PR — the fail-safe hole"
        )
    elif injected_p95 < _LOWER_THRESHOLD and searching_n >= _LOWER_MIN_N:
        verdict = (
            f"over-estimating (p95={injected_p95} over n={searching_n}) — lower "
            "cost_web_search_context_tokens ONLY with the operator (config.py:315-319 "
            "is calibrated deliberately conservative)"
        )
    else:
        verdict = f"no action indicated (p95={injected_p95}, n={searching_n})"

    return {
        "estimator_partner_check": "passed",
        "non_search_p95": non_search_p95,
        "searching_n": searching_n,
        "injected_p95": injected_p95,
        "injected_max": injected_max,
        "verdict": verdict,
    }


def classify_credential_refusal_shapes(records: list[dict[str, Any]]) -> dict[str, Any]:
    """#203 read: distinct response shapes observed under a 403."""
    refusals = [
        r
        for r in records
        if r.get("message") == "key_probe_credential_refused" and r.get("status_code") == 403
    ]
    n = len(refusals)
    if n < MIN_N_203:
        return {"n": n, "distinct_shapes": 0, "verdict": f"insufficient data ({n}/{MIN_N_203})"}

    shapes = {
        (
            r.get("status_code"),
            r.get("content_type_main"),
            r.get("server_class"),
            r.get("expose_headers_names_openrouter"),
        )
        for r in refusals
    }
    distinct = len(shapes)
    if distinct <= 1:
        verdict = (
            "single shape observed — no evidence of a second answerer; "
            "the known proxy/WAF gap stays open honestly"
        )
    else:
        verdict = (
            f"{distinct} distinct shapes observed under 403 — there is "
            "something to disambiguate; only now is designing a signal a real task"
        )
    return {"n": n, "distinct_shapes": distinct, "verdict": verdict}


def _format_105(result: dict[int, dict[str, Any]]) -> str:
    if not result:
        return f"  no upstream_provider_http_error 5xx records — insufficient data (0/{MIN_N_105})"
    lines = []
    for status in sorted(result):
        row = result[status]
        lines.append(
            f"  status={status} n={row['n']} unknown={row['unknown']} "
            f"provider_named={row['provider_named']} router_refusal={row['router_refusal']}\n"
            f"    -> {row['verdict']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    directory = args[0] if args else os.environ.get("TELEMETRY_LOG_DIR", "")
    if not directory:
        print(
            "no directory given and TELEMETRY_LOG_DIR is unset — "
            "pass the directory explicitly, e.g. the mounted /data path"
        )
        return 1

    root = Path(directory)
    billing_records = read_jsonl(root / BILLING_FILE_NAME)
    token_records = read_jsonl(root / TOKENS_FILE_NAME)

    print(f"Telemetry classification report — {root}")
    print()
    print("#105 — 5xx billing evidence (per status code, never pooled)")
    print(_format_105(classify_billing_5xx(billing_records)))
    print()
    print("#268 — injected input tokens (web-search context)")
    r268 = classify_token_injection(token_records)
    print(f"  -> {r268['verdict']}")
    print()
    print("#203 — credential-refusal response shape under 403")
    r203 = classify_credential_refusal_shapes(billing_records)
    print(f"  n={r203['n']} distinct_shapes={r203['distinct_shapes']}")
    print(f"  -> {r203['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
