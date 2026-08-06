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
#: #258 note. `judge_status` is the FIRST judge-bearing field the served
#: projection has ever carried, and it defeated every pattern below: `_` is a
#: word character, so `\.judge\b` never matches `.judge_status`. Review
#: demonstrated that by appending `const leaked = ev.judge_status;` to a copy
#: of `app.js` and watching this file stay green — in the very file whose
#: stated purpose is that "no judge-reading code path can be added by habit".
#: The patterns therefore cover an optional `_status` suffix, and this guard
#: FAILS CLOSED: `app.js` reads no judge field today and may not start reading
#: one by accident. #267 is expected to give the frontend an honest line for a
#: judge that ran and produced nothing, and when it does it must DELETE the
#: `(?:_status)?` group here deliberately, with its own justification — which
#: is the whole point of a guard that has to be opened on purpose.
_JUDGE_READ_PATTERNS = (
    r"\.judge(?:_status)?\b",
    r"\[\s*[\"'`]judge(?:_status)?[\"'`]\s*\]",
    r"\bjudge(?:_status)?\s*[:=]",
    r"[{,]\s*judge(?:_status)?\s*[,}]",
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
        # #258: the same shapes against the new judge-bearing field. Each of
        # these passed the pre-#258 patterns; review proved the first one live.
        "const v = ev.judge_status;",
        "const v = ev?.judge_status;",
        'const v = result.evaluation["judge_status"];',
        "const v = trust[ 'judge_status' ];",
        "const v = trust[`judge_status`];",
        "let judge_status = payload.evaluation;",
        "const cfg = { judge_status: verdict };",
        "const { judge_status } = payload.evaluation;",
        "const { signals, judge_status } = ev;",
    )
    for snippet in offenders:
        assert any(re.search(p, snippet) for p in _JUDGE_READ_PATTERNS), (
            f"loosened D-5 check no longer catches: {snippet!r}"
        )


def test_the_ban_does_not_fire_on_app_authored_prose() -> None:
    """POSITIVE PARTNER (rule 7): the patterns must still be narrow enough to
    let the app NAME the judge in its own disclosure copy, which is the
    loosening P1 deliberately made. Without this, tightening the patterns for
    #258 could have quietly re-banned honest attribution and nothing would
    have said so."""
    allowed = (
        'const D = "Citation support was checked by an independent judge model.";',
        "// the judge is advisory and never enters the composite",
        "// judge_status is served but deliberately not read here",
    )
    for snippet in allowed:
        assert not any(re.search(p, snippet) for p in _JUDGE_READ_PATTERNS), (
            f"D-5 check now fires on app-authored prose: {snippet!r}"
        )
