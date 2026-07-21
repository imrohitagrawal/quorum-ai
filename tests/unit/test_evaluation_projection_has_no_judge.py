"""D-5: the judge is OUT of S3 scope, structurally.

The served ``QueryRunEvaluationProjection`` has no ``judge``/``rationale`` field
at any depth — a rationale is free text written ABOUT provider prose, and there
must be no path, present or future, by which it reaches a client. And the
frontend must contain no ``judge`` identifier at all, so no judge-reading code
path can be added by habit. Building one would manufacture an API shape that
does not exist and create standing pressure to add it.
"""

from __future__ import annotations

import re
from pathlib import Path

from product_app.query_runs import QueryRunResultResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_JS = REPO_ROOT / "src" / "product_app" / "static" / "app.js"

_BANNED_KEYS = {"judge", "rationale"}


def _keys_at_any_depth(schema: dict[str, object], defs: dict[str, object]) -> set[str]:
    """Collect every property key reachable from a JSON schema, following $ref."""
    seen_refs: set[str] = set()
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.split("/")[-1]
                if name not in seen_refs:
                    seen_refs.add(name)
                    walk(defs.get(name, {}))
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    found.update(value.keys())
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return found


def test_the_served_result_schema_has_no_judge_or_rationale_anywhere() -> None:
    schema = QueryRunResultResponse.model_json_schema()
    defs = schema.get("$defs", {})
    # Resolve the evaluation sub-schema specifically, then the whole response.
    keys = _keys_at_any_depth(schema, defs)
    leaked = keys & _BANNED_KEYS
    assert not leaked, f"served schema exposes forbidden key(s): {sorted(leaked)}"


def test_the_frontend_contains_no_judge_identifier() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    # Word-boundary match so "judgement" in a comment would flag, but we assert
    # the bare identifier is entirely absent from the shipped script.
    assert not re.search(r"\bjudge\b", source), (
        "app.js must not reference a 'judge' identifier (D-5): the served "
        "projection has no judge field and no judge-reading path may exist"
    )
