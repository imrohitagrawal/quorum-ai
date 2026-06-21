"""Nightly feedback audit runner.

This module is the "the system improves itself" piece. It reads the
durable event trail written by :mod:`product_app.feedback_store`,
aggregates the events into per-category statistics, asks a cheap LLM
(Haiku 4.5 by default) to find actionable patterns, and writes a
Markdown report with proposed code changes as unified diffs.

The audit is read-only against the application — it never mutates any
in-memory state. It is also intentionally separated from the main
application process: the recommended deployment is a separate ``fly
machine run`` invocation (or a GitHub Actions scheduled workflow) once
per day, not a thread inside the main process.

Output:

* ``feedback/audit-YYYY-MM-DD.md`` — the report an operator reads
* ``feedback/audit-YYYY-MM-DD.json`` — the raw LLM response, kept for
  reproducibility and to make the audit prompt easy to re-run with a
  different model

Run::

    uv run python -m product_app.feedback_audit
    uv run python -m product_app.feedback_audit --window-hours 48
    uv run python -m product_app.feedback_audit --output-dir feedback/

If ``OPENROUTER_API_KEY`` and ``OPENROUTER_LIVE_EXECUTION_ENABLED`` are
not set, the audit falls back to a deterministic local-only mode that
emits a placeholder report containing the aggregated statistics and no
LLM-generated findings. This keeps the cron job useful even when the
operator has not configured a key.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Aggregated statistics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderStats:
    """Per-model aggregations over provider call events."""

    total_calls: int
    fallback_count: int
    simulation_count: int
    avg_duration_ms: float
    p95_duration_ms: float


@dataclass(frozen=True)
class SynthesisStats:
    """Aggregations over synthesis events."""

    total: int
    completed: int
    avg_citation_coverage: float  # ratio in [0, 1]
    avg_duration_ms: float
    high_stakes_required_count: int
    false_consensus_preserved_count: int


@dataclass(frozen=True)
class CostStats:
    """Aggregations over cost guardrail events."""

    total: int
    allowed: int
    required_confirmation: int
    blocked: int
    avg_estimated_cost_usd: float


@dataclass(frozen=True)
class SafetyStats:
    """Aggregations over safety warning events."""

    total: int
    impressions: int
    acknowledgements: int


@dataclass(frozen=True)
class DebateStats:
    """Aggregations over debate round events."""

    total: int
    round_one_count: int
    round_two_count: int
    skipped_round_two_count: int
    avg_round_one_ms: float
    avg_round_two_ms: float


@dataclass(frozen=True)
class AuditStatistics:
    """The aggregated statistics the audit LLM sees.

    The LLM does NOT see raw events. It sees these numbers plus the
    relevant source files (the static defaults, the safety regex).
    Numbers are redacted of any account/run identifiers.
    """

    window_hours: float
    run_started_at: datetime
    run_finished_at: datetime
    provider: dict[str, ProviderStats]
    synthesis: SynthesisStats
    cost: CostStats
    safety: SafetyStats
    debate: DebateStats
    total_runs: int


def _quantile(values: list[int] | list[float], q: float) -> float:
    """A small, dependency-free quantile helper.

    ``statistics.quantiles`` returns cut points; this returns the value
    at a single quantile via linear interpolation between the two
    nearest sorted samples. The audit does not need statistical rigor
    — only a useful "the slowest 5% of calls were above X" summary.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    sorted_values: list[float] = sorted(float(v) for v in values)
    idx = q * (len(sorted_values) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = idx - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def _aggregate_provider(events: Iterable[Any]) -> dict[str, ProviderStats]:
    by_model: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        model_id = event.payload.get("model_id") or "unknown"
        by_model[model_id].append(event)
    stats: dict[str, ProviderStats] = {}
    for model_id, model_events in by_model.items():
        durations = [int(e.payload.get("duration_ms") or 0) for e in model_events]
        provider_paths = [str(e.payload.get("provider_path") or "") for e in model_events]
        stats[model_id] = ProviderStats(
            total_calls=len(model_events),
            fallback_count=sum(1 for p in provider_paths if "fallback" in p.lower()),
            simulation_count=sum(1 for p in provider_paths if "local_simulation" in p.lower()),
            avg_duration_ms=statistics.fmean(durations) if durations else 0.0,
            p95_duration_ms=_quantile(durations, 0.95),
        )
    return stats


def _aggregate_synthesis(events: Iterable[Any]) -> SynthesisStats:
    payload_list = [e.payload for e in events]
    if not payload_list:
        return SynthesisStats(
            total=0,
            completed=0,
            avg_citation_coverage=0.0,
            avg_duration_ms=0.0,
            high_stakes_required_count=0,
            false_consensus_preserved_count=0,
        )
    coverages = []
    durations = []
    completed = 0
    high_stakes = 0
    false_consensus = 0
    for payload in payload_list:
        ratio = payload.get("citation_coverage_ratio") or "0"
        try:
            coverages.append(float(ratio))
        except (TypeError, ValueError):
            coverages.append(0.0)
        durations.append(int(payload.get("duration_ms") or 0))
        if payload.get("status") == "completed":
            completed += 1
        if payload.get("high_stakes_warning_required"):
            high_stakes += 1
        if payload.get("false_consensus_preserved"):
            false_consensus += 1
    return SynthesisStats(
        total=len(payload_list),
        completed=completed,
        avg_citation_coverage=statistics.fmean(coverages) if coverages else 0.0,
        avg_duration_ms=statistics.fmean(durations) if durations else 0.0,
        high_stakes_required_count=high_stakes,
        false_consensus_preserved_count=false_consensus,
    )


def _aggregate_cost(events: Iterable[Any]) -> CostStats:
    payload_list = [e.payload for e in events]
    if not payload_list:
        return CostStats(
            total=0,
            allowed=0,
            required_confirmation=0,
            blocked=0,
            avg_estimated_cost_usd=0.0,
        )
    actions = Counter(str(p.get("threshold_action") or "") for p in payload_list)
    costs: list[float] = []
    for p in payload_list:
        value = p.get("estimated_cost_usd")
        try:
            costs.append(float(value))
        except (TypeError, ValueError):
            costs.append(0.0)
    return CostStats(
        total=len(payload_list),
        allowed=actions.get("allow", 0),
        required_confirmation=actions.get("require_confirmation", 0),
        blocked=actions.get("block", 0),
        avg_estimated_cost_usd=statistics.fmean(costs) if costs else 0.0,
    )


def _aggregate_safety(events: Iterable[Any]) -> SafetyStats:
    payload_list = [e.payload for e in events]
    impressions = sum(1 for p in payload_list if not p.get("acknowledged"))
    acknowledgements = sum(1 for p in payload_list if p.get("acknowledged"))
    return SafetyStats(
        total=len(payload_list),
        impressions=impressions,
        acknowledgements=acknowledgements,
    )


def _aggregate_debate(events: Iterable[Any]) -> DebateStats:
    by_round: dict[int, list[int]] = defaultdict(list)
    skipped_round_two = 0
    total = 0
    for event in events:
        total += 1
        payload = event.payload
        if payload.get("status") == "skipped":
            skipped_round_two += 1
            continue
        round_num = int(payload.get("round_number") or 0)
        if round_num:
            by_round[round_num].append(int(payload.get("duration_ms") or 0))
    return DebateStats(
        total=total,
        round_one_count=len(by_round.get(1, [])),
        round_two_count=len(by_round.get(2, [])),
        skipped_round_two_count=skipped_round_two,
        avg_round_one_ms=statistics.fmean(by_round.get(1, [0])) if by_round.get(1) else 0.0,
        avg_round_two_ms=statistics.fmean(by_round.get(2, [0])) if by_round.get(2) else 0.0,
    )


def _count_distinct_runs(events_by_recorder: dict[str, list[Any]]) -> int:
    """Return the number of distinct query_run_id values across all events."""
    run_ids: set[str] = set()
    for events in events_by_recorder.values():
        for event in events:
            run_id = event.query_run_id
            if run_id:
                run_ids.add(run_id)
    return len(run_ids)


def collect_statistics(
    *,
    events_by_recorder: dict[str, list[Any]],
    window_hours: float,
    started_at: datetime,
    finished_at: datetime,
) -> AuditStatistics:
    """Build the AuditStatistics payload from a recorder-keyed event dict.

    The recorder keys are the names written by the recorders'
    ``_record_feedback_event`` calls: ``"synthesis"``, ``"provider"``,
    ``"model_slot"``, ``"cost"``, ``"safety"``, ``"debate"``.
    """
    return AuditStatistics(
        window_hours=window_hours,
        run_started_at=started_at,
        run_finished_at=finished_at,
        provider=_aggregate_provider(events_by_recorder.get("provider", [])),
        synthesis=_aggregate_synthesis(events_by_recorder.get("synthesis", [])),
        cost=_aggregate_cost(events_by_recorder.get("cost", [])),
        safety=_aggregate_safety(events_by_recorder.get("safety", [])),
        debate=_aggregate_debate(events_by_recorder.get("debate", [])),
        total_runs=_count_distinct_runs(events_by_recorder),
    )


# ---------------------------------------------------------------------------
# Audit prompt
# ---------------------------------------------------------------------------


# Categories the audit LLM may produce. The constants are exported so
# the report renderer can validate the LLM's output before rendering.
CATEGORY_MODEL_SLOT = "model_slot"
CATEGORY_SAFETY_REGEX = "safety_regex"
CATEGORY_CITATION_THRESHOLD = "citation_threshold"
CATEGORY_COST_THRESHOLD = "cost_threshold"
CATEGORY_PIPELINE_TIMING = "pipeline_timing"
CATEGORY_PROVIDER_FALLBACK = "provider_fallback"
CATEGORY_PROMPT_QUALITY = "prompt_quality"

CATEGORIES: tuple[str, ...] = (
    CATEGORY_MODEL_SLOT,
    CATEGORY_SAFETY_REGEX,
    CATEGORY_CITATION_THRESHOLD,
    CATEGORY_COST_THRESHOLD,
    CATEGORY_PIPELINE_TIMING,
    CATEGORY_PROVIDER_FALLBACK,
    CATEGORY_PROMPT_QUALITY,
)

SEVERITIES: tuple[str, ...] = ("high", "medium", "low")


#: System prompt for the audit model. Tells the LLM what to look for
#: and the JSON envelope it must produce. Kept narrow so a small model
#: can hit it consistently.
AUDIT_SYSTEM_PROMPT = """You are the Quorum-AI feedback auditor. Your job is to read
aggregated production statistics from the multi-model LLM orchestrator and
produce 0-5 actionable findings. Each finding is a single concrete change
that would improve the application's correctness, safety, cost, or latency.

Findings you should look for:

1. model_slot — A default model slot has high failure rate, high latency,
   high fallback rate, or consistently low citation coverage. Suggest a
   replacement from the same vendor family if possible.
2. safety_regex — Production traffic contains queries that *should* trigger
   a high-stakes warning but the current regex pattern does not match them.
   You are NOT given query text (it is redacted); you can only flag a gap
   when the statistics show high_stakes_required_count is non-zero in
   synthesis (meaning the application code already detected it) AND the
   safety impressions show no matching event_type=safety_warning_impression
   for that pattern. Without that correlation, do not flag safety.
3. citation_threshold — Average citation coverage is consistently below
   the 80% target. Suggest either lowering the target or rewriting the
   synthesis prompt to demand citations.
4. cost_threshold — The average estimated cost is climbing, OR the
   BLOCK rate is unusually high, OR the ALLOW-to-REQUIRE_CONFIRMATION
   ratio is upside-down (most requests require confirmation).
5. pipeline_timing — A debate round or synthesis stage is consistently
   slow (>2x the other stages).
6. provider_fallback — A specific model_id has a high local_simulation
   rate (>30%) suggesting it does not authenticate with the demo key.
7. prompt_quality — Synthesis sections consistently fall back to
   templates (a separate signal would be needed; skip if not visible
   from the stats given).

Output envelope (MUST be valid JSON). Use one of these category values:
"model_slot", "safety_regex", "citation_threshold", "cost_threshold",
"pipeline_timing", "provider_fallback", "prompt_quality".

{
  "findings": [
    {
      "category": "<category string from the list above>",
      "severity": "high" | "medium" | "low",
      "title": "<short, specific, < 100 chars>",
      "evidence": "<the specific numbers from the statistics that motivated this finding>",
      "recommendation": "<what the operator should change, in one or two sentences>",
      "proposed_diff": "<unified diff string targeting a specific file, or empty>",
      "confidence": <float in [0, 1]>
    }
  ],
  "negative_findings": [
    "<a brief statement of a failure mode you CHECKED FOR and did NOT find>"
  ]
}

Hard rules:
* Produce 0-5 findings. Quality over quantity. If the statistics look
  healthy, return an empty findings list and a few negative_findings.
* Never propose changes that touch user data, secrets, or auth tokens.
* Never invent numbers; cite the exact figure from the statistics block.
* proposed_diff MUST target a real file in the repository. Do not
  produce diffs for files you were not shown.
* If you are not confident a finding is real, set confidence below 0.5
  or omit it entirely.
"""


def build_audit_user_prompt(
    *,
    statistics: AuditStatistics,
    default_model_ids: tuple[str, ...],
    safety_regex_pattern: str,
) -> str:
    """Build the user prompt from aggregated statistics + current source.

    The prompt carries three blocks:
    1. Aggregated statistics (numbers only — no PII, no query text).
    2. The current ``DEFAULT_MODEL_IDS`` tuple (so the LLM can propose
       replacements in the same vendor family).
    3. The current safety regex (so a safety_regex finding can include
       a concrete diff).
    """
    stats_block = json.dumps(asdict_dict(statistics), indent=2, default=str)
    return f"""# Quorum-AI Feedback Audit

Window: {statistics.window_hours:g} hours
Runs analyzed: {statistics.total_runs}
Started at (UTC): {statistics.run_started_at.isoformat()}
Finished at (UTC): {statistics.run_finished_at.isoformat()}

## Aggregated statistics

```json
{stats_block}
```

## Current default model slot tuple

```python
DEFAULT_MODEL_IDS = (
    {",".join(f'"{m}"' for m in default_model_ids)},
)
```

## Current high-stakes safety regex pattern

```python
HIGH_STAKES_PATTERN = re.compile(r{json.dumps(safety_regex_pattern)})
```

Produce your JSON response."""


def asdict_dict(instance: Any) -> dict[str, Any]:
    """``dataclasses.asdict`` with ``Decimal`` and ``datetime`` rendered as primitives.

    ``asdict`` keeps ``Decimal`` and ``datetime`` as-is; ``json.dumps``
    cannot serialise them. The audit prompt is built from this dict,
    so we coerce the non-primitive types to strings up front.
    """
    raw = asdict(instance)
    coerced: dict[str, Any] = _coerce(raw)
    return coerced


def _coerce(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce(v) for v in value]
    if isinstance(value, tuple):
        return [_coerce(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Audit model invocation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A single audit finding from the LLM."""

    category: str
    severity: str
    title: str
    evidence: str
    recommendation: str
    proposed_diff: str
    confidence: float

    def to_markdown(self, index: int) -> str:
        """Render the finding as Markdown for the report."""
        severity_badge = {
            "high": "🟥 **HIGH**",
            "medium": "🟧 **MEDIUM**",
            "low": "🟨 **LOW**",
        }.get(self.severity, self.severity)
        diff_block = (
            f"```diff\n{self.proposed_diff}\n```"
            if self.proposed_diff
            else "_(no code change proposed — manual review only)_"
        )
        return (
            f"### Finding {index} — {self.category} — {severity_badge}\n\n"
            f"**Title**: {self.title}\n\n"
            f"**Evidence**: {self.evidence}\n\n"
            f"**Recommendation**: {self.recommendation}\n\n"
            f"**Confidence**: {self.confidence:.2f}\n\n"
            f"{diff_block}\n"
        )


@dataclass(frozen=True)
class AuditResponse:
    findings: list[Finding]
    negative_findings: list[str]
    raw_response: str
    used_model: str


def _parse_audit_response(raw_text: str) -> AuditResponse:
    """Parse the LLM JSON envelope. Tolerant of trailing prose / code fences.

    Some models wrap their JSON in ```json ... ``` fences or append a
    short note after the closing brace. We strip both before parsing.
    A parse failure raises ``ValueError`` so the caller can fall back
    to the no-LLM report path.
    """
    text = raw_text.strip()
    # Strip ```json fences (some models add them despite instructions).
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # Trim any trailing prose after the JSON object.
    if text.startswith("{"):
        depth = 0
        end = -1
        for index, char in enumerate(text):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end > 0:
            text = text[:end]
    parsed = json.loads(text)
    findings_raw = parsed.get("findings") or []
    findings: list[Finding] = []
    for item in findings_raw:
        if not isinstance(item, dict):
            continue
        try:
            findings.append(
                Finding(
                    category=str(item.get("category") or ""),
                    severity=str(item.get("severity") or "low"),
                    title=str(item.get("title") or ""),
                    evidence=str(item.get("evidence") or ""),
                    recommendation=str(item.get("recommendation") or ""),
                    proposed_diff=str(item.get("proposed_diff") or ""),
                    confidence=float(item.get("confidence") or 0.0),
                ),
            )
        except (TypeError, ValueError):
            continue
    negatives_raw = parsed.get("negative_findings") or []
    negatives = [str(item) for item in negatives_raw if isinstance(item, str)]
    return AuditResponse(
        findings=findings,
        negative_findings=negatives,
        raw_response=raw_text,
        used_model="",
    )


def _call_audit_model(
    *,
    openrouter_key: str,
    model_id: str,
    user_prompt: str,
) -> str | None:
    """Call the audit model. Returns ``None`` on any failure.

    The audit is best-effort. A failed call falls back to the local-only
    report path; the operator still gets a useful artefact (the
    aggregated statistics in Markdown form).
    """
    import json as _json
    import urllib.error
    import urllib.request

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    request = urllib.request.Request(
        url=f"{os.environ.get('OPENROUTER_API_BASE_URL', '')}/chat/completions",
        data=_json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://quorum-ai.fly.dev",
            "X-Title": "Quorum-AI Feedback Audit",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw_body = response.read().decode()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        _log.warning("feedback_audit: audit model call failed: %s", exc)
        return None
    try:
        parsed = _json.loads(raw_body)
        return str(parsed["choices"][0]["message"]["content"])
    except (KeyError, ValueError, _json.JSONDecodeError, IndexError) as exc:
        _log.warning("feedback_audit: could not parse audit response: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _read_static_defaults() -> tuple[str, ...]:
    """Read the current DEFAULT_MODEL_IDS tuple from the source file.

    The audit prompt carries the live values so the LLM can suggest
    replacements in the same vendor family. We do not import the
    module directly (the audit is meant to run independently of the
    application's runtime state) — we read the file and parse the
    tuple literal.
    """
    import re as _re

    path = Path(__file__).parent / "model_slots.py"
    source = path.read_text(encoding="utf-8")
    match = _re.search(r"DEFAULT_MODEL_IDS:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(([^)]+)\)", source)
    if not match:
        return ()
    return tuple(
        item.strip().strip('"').strip("'")
        for item in match.group(1).split(",")
        if item.strip()
    )


def _read_safety_regex() -> str:
    """Read the current ``HIGH_STAKES_PATTERN`` from the safety module."""
    import re as _re

    path = Path(__file__).parent / "safety.py"
    source = path.read_text(encoding="utf-8")
    match = _re.search(r"HIGH_STAKES_PATTERN\s*=\s*re\.compile\(r[\"']([^\"']+)[\"']\)", source)
    if not match:
        return ""
    return match.group(1)


def render_report(
    *,
    statistics: AuditStatistics,
    audit_response: AuditResponse | None,
) -> str:
    """Render the audit as a Markdown document."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    severity_counts: Counter[str] = Counter()
    for finding in audit_response.findings if audit_response else []:
        severity_counts[finding.severity] += 1

    lines: list[str] = []
    lines.append(f"# Quorum-AI Feedback Audit — {today}\n")
    lines.append(
        f"**Window**: last {statistics.window_hours:g} hours "
        f"({statistics.run_started_at.isoformat()} → {statistics.run_finished_at.isoformat()})\n"
    )
    lines.append(f"**Total runs analyzed**: {statistics.total_runs}\n")
    lines.append("**Generated by**: feedback_audit.py v0.1\n")
    audit_model_label = (
        audit_response.used_model
        if audit_response
        else "(no LLM — local-only mode)"
    )
    lines.append(f"**Audit model**: {audit_model_label}\n")
    lines.append("")

    # -- Summary table ----------------------------------------------------
    lines.append("## Summary\n")
    if audit_response is None or not audit_response.findings:
        lines.append(
            "No findings were generated. "
            + (
                "Statistics are below."
                if audit_response is None
                else "The audit model reported a healthy window."
            )
            + "\n"
        )
    else:
        lines.append("| Category | Findings | High | Medium | Low |")
        lines.append("|---|---|---|---|---|")
        by_category: dict[str, Counter[str]] = defaultdict(Counter)
        for finding in audit_response.findings:
            by_category[finding.category][finding.severity] += 1
        for category in CATEGORIES:
            counts = by_category.get(category, Counter())
            total = sum(counts.values())
            if not total:
                continue
            lines.append(
                f"| {category} | {total} | {counts.get('high', 0)} | "
                f"{counts.get('medium', 0)} | {counts.get('low', 0)} |"
            )
        lines.append("")
        if severity_counts.get("high", 0) > 0:
            lines.append("**Overall health**: DEGRADED")
            lines.append("**Action required**: YES\n")
        elif severity_counts.get("medium", 0) > 0:
            lines.append("**Overall health**: FAIR")
            lines.append("**Action required**: REVIEW\n")
        else:
            lines.append("**Overall health**: GOOD")
            lines.append("**Action required**: NO\n")

    # -- Findings ---------------------------------------------------------
    if audit_response is not None and audit_response.findings:
        lines.append("## Findings\n")
        for index, finding in enumerate(audit_response.findings, start=1):
            lines.append(finding.to_markdown(index))
            lines.append("")

    # -- Negative findings ------------------------------------------------
    if audit_response is not None and audit_response.negative_findings:
        lines.append("## Negative findings (checked, not present)\n")
        for negative in audit_response.negative_findings:
            lines.append(f"- {negative}")
        lines.append("")

    # -- Statistics appendix ---------------------------------------------
    lines.append("## Statistics\n")
    lines.append("```json")
    lines.append(json.dumps(asdict_dict(statistics), indent=2, default=str))
    lines.append("```\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _load_events_by_recorder(*, window_hours: float) -> dict[str, list[Any]]:
    """Load the persisted events within the window, grouped by recorder."""
    from product_app.feedback_store import FeedbackStore, get_store

    store: FeedbackStore | None = get_store()
    if store is None:
        store = FeedbackStore.from_env()
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in store.iter_events(since=since):
        grouped[row.recorder].append(row)
    return dict(grouped)


def _audit_enabled() -> bool:
    """True if the audit model call is configured."""
    return bool(
        os.environ.get("OPENROUTER_API_KEY")
        and os.environ.get("OPENROUTER_LIVE_EXECUTION_ENABLED", "").lower() == "true"
    )


def run_audit(
    *,
    window_hours: float = 24.0,
    output_dir: Path | str = Path("feedback"),
) -> tuple[Path, Path]:
    """Run the audit end-to-end and return the report and JSON paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(UTC)
    events_by_recorder = _load_events_by_recorder(window_hours=window_hours)
    statistics = collect_statistics(
        events_by_recorder=events_by_recorder,
        window_hours=window_hours,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )

    audit_response: AuditResponse | None = None
    if _audit_enabled():
        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
        model_id = os.environ.get("AUDIT_MODEL_ID", "anthropic/claude-haiku-4.5")
        user_prompt = build_audit_user_prompt(
            statistics=statistics,
            default_model_ids=_read_static_defaults(),
            safety_regex_pattern=_read_safety_regex(),
        )
        raw = _call_audit_model(
            openrouter_key=openrouter_key,
            model_id=model_id,
            user_prompt=user_prompt,
        )
        if raw is not None:
            try:
                parsed = _parse_audit_response(raw)
                audit_response = AuditResponse(
                    findings=parsed.findings,
                    negative_findings=parsed.negative_findings,
                    raw_response=parsed.raw_response,
                    used_model=model_id,
                )
            except ValueError as exc:
                _log.warning("feedback_audit: could not parse LLM response: %s", exc)

    report = render_report(statistics=statistics, audit_response=audit_response)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    report_path = output_dir / f"audit-{today}.md"
    json_path = output_dir / f"audit-{today}.json"
    report_path.write_text(report, encoding="utf-8")
    json_payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_hours": window_hours,
        "statistics": asdict_dict(statistics),
        "raw_response": audit_response.raw_response if audit_response else "",
        "findings": [
            {
                **asdict(finding),
                "proposed_diff": finding.proposed_diff,
            }
            for finding in (audit_response.findings if audit_response else [])
        ],
        "negative_findings": audit_response.negative_findings if audit_response else [],
        "used_model": audit_response.used_model if audit_response else "",
    }
    json_path.write_text(json.dumps(json_payload, indent=2, default=str), encoding="utf-8")
    return report_path, json_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Quorum-AI nightly feedback audit and write a Markdown report."
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=24.0,
        help="Time window to aggregate events over (default: 24).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("feedback"),
        help="Directory to write the audit report into (default: feedback/).",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    args = _parse_args()
    report_path, json_path = run_audit(
        window_hours=args.window_hours,
        output_dir=args.output_dir,
    )
    print(f"feedback_audit: wrote report to {report_path}")
    print(f"feedback_audit: wrote raw JSON to {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
