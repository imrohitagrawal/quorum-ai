#!/usr/bin/env python3
"""Regenerate ``openapi.yaml`` from the live FastAPI application.

The checked-in ``openapi.yaml`` is a GENERATED artifact, not a hand-edited
one: it is the canonical serialization of ``app.openapi()`` for a fresh
application instance. Hand-editing it is a bug — the edit will be reverted
the next time this script runs and, more importantly, the CI drift-guard
(:mod:`scripts.validate_openapi_contract` and
``tests/contract/test_openapi_contract.py``) will fail because the
checked-in bytes no longer match what the app produces.

To change the contract, change the FastAPI routes / Pydantic models in
``src/product_app`` and then re-run this script:

    python scripts/export_openapi.py

The single :func:`render_openapi_yaml` renderer is the ONE canonical way
the spec is serialized, so the generator and the guard can never disagree
about formatting — the guard is an exact-bytes comparison against this
renderer's output.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "openapi.yaml"

# The generated header is a comment block prepended to the YAML so a human
# opening the file sees immediately that it must not be hand-edited. It is
# part of the canonical bytes, so the guard checks it too.
_GENERATED_HEADER = (
    "# GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "# Regenerate with: python scripts/export_openapi.py\n"
    "# The CI drift-guard (scripts/validate_openapi_contract.py and\n"
    "# tests/contract/test_openapi_contract.py) fails if this file drifts from\n"
    "# app.openapi(). Change the FastAPI routes/models, then regenerate.\n"
)


def load_openapi_schema() -> dict[str, Any]:
    """Return ``app.openapi()`` for a freshly imported application.

    ``src`` is placed on ``sys.path`` so the module imports the same way it
    does under pytest (``pythonpath = ["src"]``). Importing
    ``product_app.main`` constructs the module-level ``app`` fresh, and
    ``app.openapi()`` computes (and caches) the schema for that instance.
    """
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from product_app.main import app

    return app.openapi()


def render_openapi_yaml(schema: dict[str, Any]) -> str:
    """Serialize an OpenAPI schema to the canonical ``openapi.yaml`` text.

    This is the SINGLE source of truth for how the spec is serialized:
    both the generator (this script) and the drift-guard render through
    here, so a formatting mismatch can never cause a spurious drift or mask
    a real one.

    ``sort_keys=False`` preserves FastAPI's natural insertion order (which
    mirrors the route/model declaration order); ``allow_unicode=True`` keeps
    any non-ASCII characters literal rather than ``\\uXXXX``-escaped; the
    wide ``width`` avoids YAML line-wrapping long description strings, which
    would otherwise make the output sensitive to string length.
    """
    body = yaml.safe_dump(
        schema,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,
    )
    return _GENERATED_HEADER + body


def render_current() -> str:
    """Render the canonical spec text for the current application."""
    return render_openapi_yaml(load_openapi_schema())


def main() -> int:
    text = render_current()
    OPENAPI_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OPENAPI_PATH.relative_to(ROOT)} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
