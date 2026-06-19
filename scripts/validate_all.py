#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    "validate_docs.py",
    "validate_architecture.py",
    "validate_tests.py",
    "validate_security.py",
    "validate_release.py",
    "validate_traceability.py",
    "validate_enterprise_extensions.py",
    "validate_quality_contracts.py",
    "validate_publishing_backbone.py",
    "validate_skill_onboarding.py",
]


def main() -> int:
    for script in SCRIPTS:
        print(f"==> {script}")
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT)
        if result.returncode != 0:
            return result.returncode
    print("all validation gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
