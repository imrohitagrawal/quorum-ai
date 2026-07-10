#!/usr/bin/env python3
"""Drift-guard: the checked-in ``openapi.yaml`` must equal ``app.openapi()``.

This is the self-enforcing half of the OpenAPI contract governance. The
checked-in spec is a generated artifact (see
``scripts/export_openapi.py``); if the FastAPI routes/models change without
a regen — or if the spec is hand-edited — the checked-in bytes stop
matching what the app produces and this validator fails.

The comparison is an exact-bytes check against the ONE canonical renderer
(:func:`scripts.export_openapi.render_openapi_yaml`), so the guard and the
generator can never disagree about formatting. It is enforced two ways: the
dedicated ``make openapi-check`` step in the ``validate-and-test`` CI job runs
this script, and ``tests/contract/test_openapi_contract.py`` asserts the same
invariant from the pytest suite (both required checks). It is NOT part of
``make validate`` (those gates run on bare stdlib Python without FastAPI).

Fix a failure with:

    python scripts/export_openapi.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(openapi_path: Path | None = None) -> int:
    """Return 0 if the spec at ``openapi_path`` equals a fresh render, else 1.

    ``openapi_path`` defaults to the checked-in ``openapi.yaml``; the
    parameter exists so the contract test can drive this exact guard against a
    deliberately-tampered temp copy (proving the failure direction) without
    touching the real file.
    """
    # Import the shared renderer. ``scripts`` is a plain directory (not a
    # package), so add it to the path the same way the CI job's working
    # directory makes it importable.
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from export_openapi import OPENAPI_PATH, render_current

    target = openapi_path if openapi_path is not None else OPENAPI_PATH
    if not target.exists():
        print(
            "ERROR: openapi.yaml is missing. Run: python scripts/export_openapi.py",
            file=sys.stderr,
        )
        return 1

    expected = render_current()
    actual = target.read_text(encoding="utf-8")
    if actual != expected:
        print(
            "ERROR: openapi.yaml has drifted from app.openapi().\n"
            "       The checked-in spec no longer matches the live FastAPI schema.\n"
            "       Regenerate it with: python scripts/export_openapi.py",
            file=sys.stderr,
        )
        return 1

    print("openapi contract validation passed (openapi.yaml == app.openapi())")
    return 0


def main() -> int:
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
