#!/usr/bin/env python3
"""Print external skill discovery guidance from the local research index."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    q = " ".join(sys.argv[1:]).lower().strip()
    data = json.loads(
        (ROOT / "configs" / "external-skill-research-index.json").read_text(encoding="utf-8")
    )
    print("External skill discovery: search existing skills first, then audit before use.\n")
    print("Install/search starting point when online and approved:")
    print("  DISABLE_TELEMETRY=1 npx skills add vercel-labs/skills")
    print("  npx skills add <owner/repo>   # only after review\n")
    for s in data.get("sources", []):
        hay = " ".join(
            [s.get("name", ""), s.get("type", ""), " ".join(s.get("use_for", []))]
        ).lower()
        if not q or any(term in hay for term in q.split()):
            print(f"- {s['name']} [{s['type']}] -> {', '.join(s.get('use_for', []))}")
            print(f"  url: {s['url']}")
            print(f"  default mode: {s['default_mode']} | risk: {s['risk']}\n")
    print(
        "Next: run python3 scripts/audit_external_skill.py <skill-folder> for any "
        "local skill before onboarding."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
