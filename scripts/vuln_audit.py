#!/usr/bin/env python3
"""Audit the locked runtime libraries for known vulnerabilities (W68, ADR-0164).

Exports what ``uv.lock`` pins for production (no dev or optional extras, no
project, no hashes) and hands exactly that list to a pinned ``pip-audit``,
with ``--no-deps`` so nothing is resolved again.

Exit codes:
  0  every audited package is free of known vulnerabilities
  1  at least one known vulnerability; each is printed
  2  refusing: the export or the audit produced nothing to judge (a failed
     export, an export with no pinned package, output that is not JSON, or a
     report that lists no audited package). A gate over nothing must not pass.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

Run = Callable[..., Any]

EXPORT = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"]
#: Python 3.12, the image's: pip-audit evaluates each line's marker for the
#: interpreter it runs on and silently leaves out lines whose marker fails.
PIP_AUDIT = ["uvx", "--python", "3.12", "--from", "pip-audit==2.10.1", "pip-audit"]


def count_pinned(text: str) -> int:
    """Count ``name==version`` lines, ignoring comments, options and blanks."""
    count = 0
    for line in text.splitlines():
        requirement = line.split(";", 1)[0].strip()
        if requirement and not requirement.startswith(("#", "-")) and "==" in requirement:
            count += 1
    return count


def locked_runtime_requirements(run: Run = subprocess.run) -> str:
    """The production requirement set as ``uv.lock`` pins it."""
    result = run(EXPORT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"`{' '.join(EXPORT)}` exited {result.returncode}: {result.stderr}")
    return str(result.stdout)


def main(argv: Sequence[str] | None = None, run: Run = subprocess.run) -> int:
    del argv  # no options; the parameter keeps the call shape of the other scripts
    try:
        requirements = locked_runtime_requirements(run=run)
    except RuntimeError as error:
        print(f"vuln-audit: refusing: {error}", file=sys.stderr)
        return 2
    pinned = count_pinned(requirements)
    print(f"vuln-audit: checked {pinned} locked runtime packages")
    if pinned == 0:
        print("vuln-audit: refusing: the export pins no package", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "requirements.txt"
        path.write_text(requirements, encoding="utf-8")
        command = [*PIP_AUDIT, "-r", str(path), "--no-deps", "--disable-pip", "--format", "json"]
        result = run(command, capture_output=True, text=True, check=False)

    try:
        dependencies = json.loads(result.stdout)["dependencies"]
    except (ValueError, KeyError, TypeError):
        print(
            f"vuln-audit: refusing: pip-audit exited {result.returncode} without a JSON report\n"
            f"{result.stdout}{result.stderr}",
            file=sys.stderr,
        )
        return 2

    audited = [d for d in dependencies if "vulns" in d]
    skipped = [d for d in dependencies if "vulns" not in d]
    for dep in skipped:
        print(f"vuln-audit: skipped {dep.get('name')}: {dep.get('skip_reason', 'no reason given')}")
    vulns = 0
    for dep in audited:
        for vuln in dep["vulns"]:
            vulns += 1
            fixed = ", ".join(vuln.get("fix_versions") or []) or "no release"
            print(f"{dep['name']} {dep['version']} {vuln['id']} fixed in {fixed}")
    if len(dependencies) != pinned:
        print(
            f"vuln-audit: pip-audit listed {len(dependencies)} of {pinned} pinned lines; "
            "it leaves out lines whose marker does not hold for Python 3.12 here"
        )
    print(f"vuln-audit: {len(audited)} packages, {vulns} known vulnerabilities")
    if not audited:
        print("vuln-audit: refusing: pip-audit audited no package", file=sys.stderr)
        return 2
    return 1 if vulns else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
