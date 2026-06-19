#!/usr/bin/env python3
"""Deterministic skill router for Codex Product Factory."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_RE = re.compile(
    r"\b(TBD|Placeholder|Replace with|TODO|Define after clarification|"
    r"To be written after idea clarification|Pending|Write the idea here)\b",
    re.I,
)


def read_text(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def meaningful(rel: str) -> bool:
    text = read_text(rel).strip()
    if len(text) < 40:
        return False
    if rel == "PRODUCT_IDEA.md":
        raw = re.search(r"## Raw idea\s+(.*?)(\n## |\Z)", text, re.S)
        if raw:
            text = raw.group(1).strip()
        return len(text) > 40 and not PLACEHOLDER_RE.search(text)
    return PLACEHOLDER_RE.search(text) is None


def load_router() -> dict[str, Any]:
    return json.loads((ROOT / "configs" / "skill-router.json").read_text(encoding="utf-8"))


def detect_risk_triggers() -> list[str]:
    # Only inspect artifacts that already contain meaningful product-specific content.
    # Template placeholders mention many enterprise topics and should not trigger every reviewer.
    if not meaningful("PRODUCT_IDEA.md"):
        return []
    candidate_paths = [
        "PRODUCT_IDEA.md",
        "docs/04-problem-statement.md",
        "docs/10-functional-requirements.md",
        "docs/11-non-functional-requirements.md",
        "docs/20-architecture.md",
        "docs/42-ai-safety-grounding.md",
        "docs/59-backend-engineering-practices.md",
        "docs/96-study-artifact-publishing.md",
        "docs/97-faq-wiki-plan.md",
        "docs/98-technical-article-plan.md",
        "docs/99-linkedin-post-plan.md",
        "docs/100-industry-and-integration-practices.md",
    ]
    texts = [read_text(p) for p in candidate_paths if meaningful(p)]
    combined = "\n".join(texts).lower()
    found: list[str] = []
    if any(
        k in combined
        for k in ["ai", "llm", "rag", "agent", "prompt", "model", "embedding", "hallucination"]
    ):
        found.append("ai_llm_rag_agentic")
    if any(
        k in combined
        for k in [
            "auth",
            "permission",
            "personal data",
            "privacy",
            "secret",
            "token",
            "encryption",
            "compliance",
        ]
    ):
        found.append("security_privacy_data")
    if any(
        k in combined
        for k in ["jira", "confluence", "mcp", "external skill", "skills.sh", "atlassian"]
    ):
        found.append("external_skill_or_mcp")
    if any(
        k in combined
        for k in ["ui", "ux", "screen", "dashboard", "user journey", "onboarding", "accessibility"]
    ):
        found.append("ux_customer_loved")
    if any(
        k in combined
        for k in [
            "slo",
            "observability",
            "grafana",
            "alert",
            "incident",
            "runbook",
            "latency",
            "throughput",
        ]
    ):
        found.append("operations_reliability")
    if any(
        k in combined
        for k in [
            "study",
            "faq",
            "wiki",
            "article",
            "linkedin",
            "confluence page",
            "publish",
            "watermark",
            "gif",
            "video",
            "diagram",
            "knowledge base",
        ]
    ):
        found.append("content_study_publishing")
    if any(
        k in combined
        for k in [
            "fastapi",
            "python api",
            "backend",
            "pydantic",
            "apirouter",
            "sqlalchemy",
            "async",
            "database",
            "api endpoint",
        ]
    ):
        found.append("backend_api_python")
    return found


def route() -> dict[str, Any]:
    config = load_router()
    selected = None
    for phase in config["phases"]:
        if not all(meaningful(rel) for rel in phase.get("evidence", [])):
            selected = dict(phase)
            break
    if selected is None:
        selected = {
            "id": "operate-improve",
            "label": "Operate, learn, and improve",
            "evidence": [],
            "driver": "production-feedback-loop",
            "reviewers": [
                "post-release-operations",
                "support-readiness",
                "product-discovery",
                "fanatic-critic",
            ],
            "blocking_gates": ["production-readiness-review"],
            "triggers": ["all core evidence exists"],
            "prompt": (
                "Review production signals, incidents, support feedback, and product "
                "metrics. Propose the next iteration with evidence."
            ),
        }
    risks = detect_risk_triggers()
    triggered_skills: list[str] = []
    for risk in risks:
        triggered_skills.extend(config.get("risk_triggers", {}).get(risk, []))
    # Preserve order, remove duplicates, and keep driver separate.
    reviewers = []
    for skill in selected.get("reviewers", []) + triggered_skills:
        if skill != selected.get("driver") and skill not in reviewers:
            reviewers.append(skill)
    selected["reviewers"] = reviewers
    selected["risk_triggers_detected"] = risks
    selected["conflict_precedence"] = config.get("conflict_precedence", [])
    selected["external_skill_rule"] = config.get("external_skill_rule", "")
    selected["orbi_profile_rule"] = config.get("orbi_profile_rule", "")
    selected["missing_or_placeholder_evidence"] = [
        rel for rel in selected.get("evidence", []) if not meaningful(rel)
    ]
    return selected


def format_route(r: dict[str, Any]) -> str:
    reviewers = ", ".join(r.get("reviewers", [])) or "None"
    blockers = ", ".join(r.get("blocking_gates", [])) or "None"
    missing = ", ".join(r.get("missing_or_placeholder_evidence", [])) or "None"
    risks = ", ".join(r.get("risk_triggers_detected", [])) or "None"
    return f"""Skill route
===========
Phase: {r.get("label")}
Driver skill: {r.get("driver")}
Reviewer skills: {reviewers}
Blocking gates: {blockers}
Missing/placeholders: {missing}
Risk triggers: {risks}

Suggested Codex prompt:
{r.get("prompt")}
"""


def main() -> int:
    print(format_route(route()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
