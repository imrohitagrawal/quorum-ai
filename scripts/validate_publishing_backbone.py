#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        fail(f"Missing required file: {rel}")
    text = p.read_text(encoding="utf-8", errors="ignore")
    if len(text.strip()) < 20:
        fail(f"Required file is too small: {rel}")
    return text


def require(rel: str, terms: list[str]) -> None:
    text = read(rel)
    for term in terms:
        if term not in text:
            fail(f"{rel} missing required text: {term}")


def main() -> int:
    require(
        "docs/96-study-artifact-publishing.md",
        [
            "MVP",
            "most valued outcome",
            "Confluence",
            "Git",
            "How does it solve the problem using AI",
            "secure",
            "scalable",
            "enterprise-grade",
        ],
    )
    require("docs/study/00-study-index.md", ["Study Index", "MVP", "AI", "Confluence"])
    require(
        "docs/study/M1-problem-and-mvp.md",
        ["Problem solved", "MVP value outcome", "Success signal"],
    )
    require(
        "docs/study/M2-ai-solution-and-work-easing.md",
        [
            "How it solves the problem using AI",
            "How it eases human work",
            "Where human approval is required",
        ],
    )
    require(
        "docs/study/M3-security-scalability-enterprise.md",
        ["Security", "Scalability", "Enterprise standards met", "Testing and release evidence"],
    )
    require(
        "docs/97-faq-wiki-plan.md",
        ["FAQ Wiki Plan", "plain English", "project example", "real-life analogy"],
    )
    require(
        "docs/98-technical-article-plan.md",
        ["Technical Article Plan", "engineering-first", "Sources used", "Do not invent"],
    )
    require(
        "docs/99-linkedin-post-plan.md",
        ["LinkedIn Post Plan", "Hook", "Tradeoff", "hashtags", "No fake"],
    )
    require(
        "docs/100-industry-and-integration-practices.md",
        [
            "Industry practices baseline",
            "Integration practices baseline",
            "human approval",
            "post-write",
        ],
    )
    require(
        "docs/59-backend-engineering-practices.md",
        ["Pydantic v2", "thin", "Tests", "Never hardcode secrets"],
    )
    for rel in [
        "configs/study-artifact-map.json",
        "configs/visual-media-standards.json",
        "configs/backend-engineering-rules.json",
        "configs/content-publishing-rules.json",
    ]:
        json.loads(read(rel))
    for skill in [
        "mvp-value-outcome-finder",
        "study-artifact-publisher",
        "project-knowledge-base-publisher",
        "diagram-media-standards-governor",
        "faq-wiki-generator",
        "technical-article-writer",
        "linkedin-technical-post-writer",
        "python-fastapi-backend-guardrails",
        "industry-practices-governor",
        "software-integration-engineering",
        "git-confluence-publish-reviewer",
    ]:
        require(
            f".agents/skills/{skill}/SKILL.md",
            ["## When to use", "## Procedure", "## Quality bar", "## Stop conditions"],
        )
    router = json.loads(read("configs/skill-router.json"))
    ids = [p.get("id") for p in router.get("phases", [])]
    if "study-publish-share" not in ids:
        fail("configs/skill-router.json missing study-publish-share phase")
    print("publishing backbone validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
