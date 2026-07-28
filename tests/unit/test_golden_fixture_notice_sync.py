"""WP-F / issue #114 — the e2e golden fixture quotes a provider notice VERBATIM.

Issue #114: ``e2e/fixtures/golden-run.ts`` carried no ``provider_notice`` at
all, so the blocking rendering gate never rendered a single one of the nine
user-facing notice strings rewritten in WP-E. They shipped with no
browser-level coverage. WP-F seeds one into the fixture — which immediately
creates a SECOND copy of a user-facing string, and a second copy is a copy
that drifts.

The same trap already bit this repo once: the operations runbook quotes notice
copy verbatim, and a WP-E notice rewrite had to update both halves in one diff
or the doc would have started describing text no user would ever see. A test
fixture is worse than a doc, because a stale fixture stays GREEN — the gate
would go on asserting that the UI renders a string the product no longer emits.

So: every notice-shaped string the fixture quotes must exist verbatim in the
``PROVIDER_NOTICES`` registry. Edit ``providers.py``; this test tells you the
fixture needs the same edit.
"""

from __future__ import annotations

import pathlib
import re

from product_app.providers import PROVIDER_NOTICES

_FIXTURE = pathlib.Path(__file__).resolve().parents[2] / "e2e" / "fixtures" / "golden-run.ts"

#: Locates each notice-carrying key in the fixture. BOTH the per-answer
#: ``provider_notice`` and the run-level ``provider_failure_notices`` roll-up —
#: the first version of this guard matched only the former, so the run-level
#: copy added in the SAME commit was invisible to it and could drift freely.
_NOTICE_KEY = re.compile(r"provider_notice:|provider_failure_notices:")

#: The end of that key's value: the next line opening a sibling object key at
#: the same or shallower indentation. A ternary's branches are indented deeper,
#: so they stay inside the window.
_NEXT_KEY = re.compile(r"\n {0,4}[A-Za-z_][A-Za-z0-9_]*:")

#: Every quoted string literal inside the captured window, single or double
#: quoted. ``null`` (the no-notice branch) carries no quotes and is ignored by
#: construction.
_QUOTED = re.compile(r'"([^"\n]+)"' + r"|'([^'\n]+)'")

#: A value that is neither a quoted literal nor ``null`` — e.g. a bare constant
#: reference. The guard cannot resolve those, and silently capturing nothing
#: would be a false green, so it FAILS and says why.
_UNRESOLVABLE = re.compile(r"^[\s?:]*([A-Za-z_$][\w$.]*)\s*[,\n]")


def _fixture_text() -> str:
    assert _FIXTURE.is_file(), f"golden fixture not found at {_FIXTURE}"
    return _FIXTURE.read_text(encoding="utf-8")


def _quoted_notices() -> list[str]:
    """Every string literal assigned to a ``provider_notice`` in the fixture.

    Covers the plain form and the ternary form (a notice on one slot, ``null``
    on the rest), including both branches of a ternary that names two notices.
    """
    text = _fixture_text()
    found: list[str] = []
    for key in _NOTICE_KEY.finditer(text):
        rest = text[key.end() :]
        end = _NEXT_KEY.search(rest)
        window = rest[: end.start()] if end else rest
        unresolvable = _UNRESOLVABLE.match(window)
        if unresolvable and unresolvable.group(1) not in ("null", "undefined"):
            raise AssertionError(
                "golden-run.ts assigns a provider notice from the identifier "
                f"{unresolvable.group(1)!r} rather than a literal. This guard "
                "compares literal text against the PROVIDER_NOTICES registry "
                "and cannot resolve identifiers, so it would silently pass. "
                "Inline the string, or teach this guard to resolve it."
            )
        for double, single in _QUOTED.findall(window):
            found.append(double or single)
    return found


def test_the_fixture_quotes_at_least_one_notice() -> None:
    """A guard over zero quoted notices proves nothing.

    This is the ``all([])`` failure mode that made F-06's cost gate vacuous.
    If the fixture stops seeding a notice, issue #114 has regressed and this
    test must say so rather than pass by default.
    """
    quoted = _quoted_notices()
    assert quoted, (
        "e2e/fixtures/golden-run.ts no longer seeds any provider_notice. "
        "That re-opens issue #114: the blocking rendering gate would render "
        "none of the PROVIDER_NOTICES strings."
    )


def test_every_notice_quoted_by_the_fixture_is_registered_verbatim() -> None:
    registry = set(PROVIDER_NOTICES)
    for quoted in _quoted_notices():
        assert quoted in registry, (
            "e2e/fixtures/golden-run.ts quotes a provider notice that is not "
            "in the PROVIDER_NOTICES registry verbatim:\n"
            f"  fixture:  {quoted!r}\n"
            "The registry in src/product_app/providers.py is the source of "
            "truth. If the copy changed there, update the fixture in the SAME "
            "diff — a stale fixture keeps the gate GREEN while asserting text "
            "the product no longer emits."
        )
