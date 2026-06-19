#!/usr/bin/env python3
"""Create a reviewed registry entry stub for an external skill."""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--source-url", required=True)
    ap.add_argument(
        "--mode",
        default="reviewer-only",
        choices=[
            "discovery-only",
            "reviewer-only",
            "sandbox",
            "workspace-approved",
            "local-wrapper",
            "rejected",
        ],
    )
    ap.add_argument("--owner", default="TBD")
    ap.add_argument("--reason", default="TBD")
    args = ap.parse_args()
    reg_path = ROOT / "configs" / "external-skill-registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    entry = {
        "name": args.name,
        "source_url": args.source_url,
        "activation_mode": args.mode,
        "trust_tier": "unverified-until-reviewed",
        "risk_rating": "TBD",
        "allowed_operations": ["reviewer_input_only"],
        "forbidden_operations": ["external_write", "secrets", "deployment", "destructive_git"],
        "review_owner": args.owner,
        "review_date": datetime.date.today().isoformat(),
        "validation_command": (
            "python3 scripts/audit_external_skill.py <skill-folder>"
            "  # or python if it points to Python 3"
        ),
        "reason": args.reason,
        "status": "proposed",
    }
    reg.setdefault("skills", []).append(entry)
    reg_path.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Added proposed registry entry for {args.name}. Review before activation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
