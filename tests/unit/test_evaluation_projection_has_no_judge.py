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


#: Patterns that would constitute a judge-READING code path in the frontend:
#: property access (``ev.judge``), subscript (``ev["judge"]``), or a ``judge``
#: binding/key (``judge =``, ``judge:``). P1 deliberately loosened this from a
#: bare-word ban: the verified disclosure names the judge model in app-authored
#: PROSE (honest attribution), which reads nothing — the served projection
#: still has no ``judge`` key at any depth (test above), and no code may read
#: one. Both directions are pinned by
#: ``test_the_ban_still_catches_a_judge_reading_path``.
#: Scope note: these catch the accidental/habitual read shapes (property
#: access incl. optional chaining, quoted/backtick subscript, binding or
#: object key, destructuring shorthand). Deliberately-obfuscated reads
#: (computed keys built from fragments) are not greppable and remain a
#: review-time concern, which is honest about what a lexical guard can do.
_JUDGE_READ_PATTERNS = (
    r"\.judge\b",
    r"\[\s*[\"'`]judge[\"'`]\s*\]",
    r"\bjudge\s*[:=]",
    r"[{,]\s*judge\s*[,}]",
)


def test_the_frontend_reads_no_judge_field() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    for pattern in _JUDGE_READ_PATTERNS:
        match = re.search(pattern, source)
        assert match is None, (
            f"app.js matches judge-reading pattern {pattern!r} at "
            f"{match.start() if match else '?'} (D-5): the served projection "
            "has no judge field and no judge-reading path may exist"
        )


def test_the_ban_still_catches_a_judge_reading_path() -> None:
    """The genuine cases the loosened check must still catch, each red-proven
    against the patterns rather than trusted by inspection."""
    offenders = (
        "const v = ev.judge;",
        "const v = ev?.judge;",
        'const v = result.evaluation["judge"];',
        "const v = trust[ 'judge' ];",
        "const v = trust[`judge`];",
        "let judge = payload.evaluation;",
        "const cfg = { judge: verdict };",
        "const { judge } = payload.evaluation;",
        "const { signals, judge } = ev;",
        "const { judge, signals } = ev;",
    )
    for snippet in offenders:
        assert any(re.search(p, snippet) for p in _JUDGE_READ_PATTERNS), (
            f"loosened D-5 check no longer catches: {snippet!r}"
        )
