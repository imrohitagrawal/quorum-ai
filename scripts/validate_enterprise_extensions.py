#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: str) -> str:
    p = ROOT / path
    if not p.exists():
        fail(f"Missing required file: {path}")
    text = p.read_text(encoding="utf-8")
    if len(text.strip()) < 20:
        fail(f"Required file is too small or empty: {path}")
    return text


def require_text(path: str, required: list[str]) -> str:
    text = read(path)
    for item in required:
        if item not in text:
            fail(f"{path} missing required text: {item}")
    return text


def main() -> int:
    require_text(
        "docs/00-start-here.md",
        ["# Start Here", "PRODUCT_IDEA.md", "make next", "docs/00-factory-console.md"],
    )
    require_text(
        "configs/skill-router.json",
        ["driver", "reviewers", "blocking_gates", "conflict_precedence"],
    )
    require_text(
        "configs/atlassian-artifact-map.json",
        ["Jira", "Confluence", "free_tier_fallback", "mcp_mode"],
    )
    require_text(
        "docs/38-atlassian-integration-roadmap.md",
        [
            "# Atlassian Integration Roadmap",
            "Free-tier-safe",
            "Assisted Atlassian MCP",
            "Roadblocks",
        ],
    )
    require_text(
        "docs/39-skill-router-and-conflict-rules.md",
        ["# Skill Router", "Driver / reviewer rule", "Conflict precedence"],
    )
    require_text(
        "docs/00-factory-console.md",
        [
            "# Factory Console",
            "Current phase",
            "Next best action",
            "Suggestions dropped by the factory",
        ],
    )
    require_text(
        "docs/04-problem-statement.md",
        [
            "# Problem Statement",
            "One-line problem",
            "Target user",
            "Success metrics",
            "Decision log",
        ],
    )
    require_text(
        "configs/jira-statuses.json",
        ["Backlog", "Ready For Dev", "CI Validation", "QA Ready", "Cancelled", "Duplicate"],
    )
    require_text(
        "configs/jira-issue-template.json",
        ["problem_statement", "expected_behaviour", "acceptance_criteria", "test_mapping"],
    )
    require_text(
        "configs/external-skill-map.json",
        ["External skills are optional accelerators", "driver_reviewer_rule"],
    )
    require_text(
        "docs/34-jira-issue-authoring.md",
        [
            "# Jira Issue Authoring",
            "Problem Statement",
            "Expected Behaviour",
            "Acceptance Criteria",
            "Test Mapping",
            "Definition of Ready",
            "Definition of Done",
        ],
    )
    require_text(
        "docs/35-confluence-operational-guide.md",
        [
            "# Confluence Operational Guide",
            "Jira Page Request",
            "Educational Awareness Section",
            "Technology Used",
            "Design Pattern Used",
            "AI Used",
        ],
    )
    require_text(
        "docs/36-educational-awareness-section.md",
        [
            "# Educational Awareness Section",
            "Technology Used",
            "Design Pattern Used",
            "Build Approach",
            "Testing Approach",
            "Observability Approach",
            "AI Used",
        ],
    )
    require_text(
        "docs/62-delivery-decomposition.md",
        ["# Delivery Decomposition", "Smallest deliverable chunk", "VS-001", "FR-001", "TEST-001"],
    )
    naming = require_text(
        "docs/91-product-naming.md",
        [
            "# Product Naming",
            "Name Option 1",
            "Name Option 2",
            "Name Option 3",
            "Business Meaning",
            "What The Product Does",
        ],
    )
    if len(re.findall(r"^## Name Option", naming, flags=re.MULTILINE)) != 3:
        fail("docs/91-product-naming.md must contain exactly three name options")
    require_text(
        "docs/92-visual-asset-plan.md",
        [
            "HERO Diagram",
            "C4 Diagrams",
            "GIF Storyboards",
            "Demo Video Storyboard",
            "Mermaid Diagrams",
            "Excalidraw Diagrams",
        ],
    )
    require_text("docs/93-demo-gif-storyboards.md", ["# Demo GIF Storyboards", "GIF 1", "GIF 2"])
    require_text(
        "docs/94-demo-video-storyboard.md", ["# Demo Video Storyboard", "Scene 1", "Scene 6"]
    )
    for path in [
        "diagrams/00-hero-diagram.md",
        "diagrams/01-c4-context.md",
        "diagrams/02-c4-container.md",
        "diagrams/03-c4-component.md",
        "diagrams/04-c4-module.md",
        "diagrams/10-mermaid-high-level.md",
        "diagrams/11-mermaid-low-level.md",
        "diagrams/12-mermaid-module-level.md",
        "diagrams/13-mermaid-sub-module-level.md",
    ]:
        require_text(path, ["```mermaid", "FR-001"])
    for path in [
        "diagrams/excalidraw/10-high-level.excalidraw",
        "diagrams/excalidraw/11-low-level.excalidraw",
        "diagrams/excalidraw/12-module-level.excalidraw",
        "diagrams/excalidraw/13-sub-module-level.excalidraw",
    ]:
        data = json.loads(read(path))
        if data.get("type") != "excalidraw":
            fail(f"{path} is not an Excalidraw file")
    print("enterprise extensions validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
