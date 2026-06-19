#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRICT = os.getenv("FACTORY_STRICT", "").lower() in {"1", "true", "yes"} or "--strict" in sys.argv


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: Path) -> str:
    if not path.exists():
        fail(f"Missing required file: {path.relative_to(ROOT)}")
    text = path.read_text(encoding="utf-8")
    if len(text.strip()) < 10:
        fail(f"File is too small/empty: {path.relative_to(ROOT)}")
    return text


def load_rules() -> dict:
    p = ROOT / "configs" / "enterprise-quality-rules.json"
    if not p.exists():
        fail("Missing configs/enterprise-quality-rules.json")
    return json.loads(p.read_text(encoding="utf-8"))


def validate_skill_contracts(rules: dict) -> None:
    skills_dir = ROOT / ".agents" / "skills"
    if not skills_dir.exists():
        fail("Missing .agents/skills")
    required = rules.get("required_skill_sections", [])
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if len(skill_files) < 50:
        fail(f"Expected at least 50 skills after V4 upgrade, found {len(skill_files)}")
    for path in skill_files:
        text = read(path)
        if not text.startswith("---"):
            fail(f"{path.relative_to(ROOT)} missing YAML frontmatter")
        if not re.search(r"(?m)^name:\s*\S+", text):
            fail(f"{path.relative_to(ROOT)} missing name frontmatter")
        if not re.search(r"(?m)^description:\s*.{20,}", text):
            fail(f"{path.relative_to(ROOT)} missing meaningful description")
        missing = [section for section in required if f"## {section}" not in text]
        if missing:
            fail(f"{path.relative_to(ROOT)} missing skill contract sections: {missing}")


def validate_configs_and_schemas() -> None:
    required = [
        "configs/enterprise-quality-rules.json",
        "configs/source-of-truth-sync.json",
        "configs/skill-catalog.json",
        "schemas/skill-contract.schema.json",
        "schemas/traceability-link.schema.json",
        "schemas/quality-gate.schema.json",
        "docs/factory/12-final-critique-and-v4-upgrade.md",
        "docs/factory/14-skill-contract-standard.md",
        "docs/factory/15-jira-confluence-mcp-integration-model.md",
        "docs/factory/16-quality-gate-contracts.md",
    ]
    # In the factory root, docs are not under docs/factory. In generated product repos,
    # bootstrap copies them there.
    for rel in required:
        path = ROOT / rel
        alt = ROOT / rel.replace("docs/factory/", "docs/")
        if not path.exists() and not alt.exists():
            fail(f"Missing required V4 file: {rel}")

    gates = json.loads(read(ROOT / "configs" / "factory-gates.json"))
    for gate in gates.get("gates", []):
        if "evidence_required" not in gate or "blocking" not in gate:
            fail(f"Gate missing evidence/blocking fields: {gate.get('id')}")


def validate_product_docs(rules: dict) -> None:
    for rel in rules.get("strict_required_docs", []):
        read(ROOT / rel)

    # These docs must exist even in non-strict mode because they define enterprise
    # readiness surface area.
    required_any_mode = [
        "docs/14-learner-spec.md",
        "docs/15-domain-glossary.md",
        "docs/16-edge-case-catalog.md",
        "docs/37-jira-confluence-sync-log.md",
        "docs/44-model-risk-register.md",
        "docs/46-prompt-registry.md",
        "docs/54-ac-to-test-map.md",
        "docs/63-technical-debt-register.md",
        "docs/64-feature-flag-plan.md",
        "docs/95-production-readiness-review.md",
    ]
    for rel in required_any_mode:
        read(ROOT / rel)


def validate_strict_no_placeholders(rules: dict) -> None:
    if not STRICT:
        return
    banned = rules.get("placeholder_terms", [])
    failures: list[str] = []
    for path in sorted((ROOT / "docs").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for term in banned:
            if re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE):
                failures.append(f"{path.relative_to(ROOT)} contains placeholder term: {term}")
                break
        # Strict mode expects at least one evidence-like marker in key product docs.
        if path.name not in {"README.md"} and not any(
            k in text for k in rules.get("evidence_keywords", [])
        ):
            failures.append(f"{path.relative_to(ROOT)} lacks evidence/owner/metric/test markers")
    if failures:
        for f in failures[:50]:
            print(f"ERROR: {f}", file=sys.stderr)
        if len(failures) > 50:
            print(
                f"ERROR: plus {len(failures) - 50} more strict validation failures", file=sys.stderr
            )
        raise SystemExit(1)


def main() -> int:
    rules = load_rules()
    validate_configs_and_schemas()
    validate_skill_contracts(rules)
    validate_product_docs(rules)
    validate_strict_no_placeholders(rules)
    mode = "strict" if STRICT else "template"
    print(f"enterprise quality contracts validation passed ({mode} mode)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
