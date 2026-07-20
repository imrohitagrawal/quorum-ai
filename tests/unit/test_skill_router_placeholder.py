"""Guard ``scripts/skill_router.py`` placeholder detection (DEBT-010).

``meaningful()`` decides which lifecycle phase ``make next`` / ``make
skill-route`` report, so a false positive mis-routes the whole factory for
every session. The bug: ``PLACEHOLDER_RE`` matched the bare English words
"pending"/"placeholder"/"todo" anywhere in prose, so a finished document that
merely *mentions* a marker (or asserts the opposite -- "not a pending
activation") was reported as an unfinished template.

These tests lock both directions, as AGENTS.md requires when a check is
loosened:

* prose that merely mentions a marker mid-sentence does NOT trip the check;
* every genuine template-placeholder form -- a standalone table cell, a bare
  bullet, a ``Field: TBD`` value, an imperative "Replace with ..." stub --
  still does;
* no document the router inspects is currently reported as a placeholder, so a
  newly introduced false positive cannot hide behind an existing one.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ROUTER_PATH = _ROOT / "scripts" / "skill_router.py"


def _load_router() -> ModuleType:
    spec = importlib.util.spec_from_file_location("skill_router_under_test", _ROUTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


router = _load_router()


def _trips(text: str) -> bool:
    return router.PLACEHOLDER_RE.search(text) is not None


def _inspected_docs() -> list[str]:
    """Every relative path ``route()`` / ``detect_risk_triggers()`` inspect."""
    paths: list[str] = []
    for phase in router.load_router()["phases"]:
        for rel in phase.get("evidence", []):
            if rel not in paths:
                paths.append(rel)
    for rel in _RISK_CANDIDATE_PATHS:
        if rel not in paths:
            paths.append(rel)
    return paths


# Mirrors ``skill_router.detect_risk_triggers`` candidate_paths.
_RISK_CANDIDATE_PATHS = [
    "PRODUCT_IDEA.md",
    "docs/04-problem-statement.md",
    "docs/10-functional-requirements.md",
    "docs/11-non-functional-requirements.md",
    "docs/20-architecture.md",
    "docs/42-ai-safety-grounding.md",
    "docs/59-backend-engineering-practices.md",
    "docs/96-study-artifact-publishing.md",
    "docs/97-faq-wiki-plan.md",
    "docs/98-technical-article-plan.md",
    "docs/99-linkedin-post-plan.md",
    "docs/100-industry-and-integration-practices.md",
]


# --------------------------------------------------------------------------
# Direction 1: the false positives are gone.
# --------------------------------------------------------------------------


def test_acceptance_criteria_doc_is_not_a_placeholder() -> None:
    """docs/12 line 271 says 'not a pending activation' -- the opposite of a stub."""
    text = router.read_text("docs/12-acceptance-criteria.md")
    assert text, "docs/12-acceptance-criteria.md must exist for this regression test"
    match = router.PLACEHOLDER_RE.search(text)
    assert match is None, f"docs/12 falsely tripped PLACEHOLDER_RE on {match.group(0)!r}"
    assert router.meaningful("docs/12-acceptance-criteria.md") is True


@pytest.mark.parametrize(
    "prose",
    [
        "The plumbing is retained as a dormant hook, not a pending activation.",
        "docs/12-acceptance-criteria.md is falsely reported as a placeholder.",
        "`PLACEHOLDER_RE` matches the bare word `Pending`, and line 271 says so.",
        "The word TODO appears in the debt register for historical reasons.",
        "Set `continue-on-error: true` (advisory). (todo) measure p50/p95 on CI.",
        "Nothing here is TBD-adjacent; the section is complete.",
        '| DEBT-010 | Fires on the bare word "Pending"/"pending" in prose. | Open |',
    ],
)
def test_prose_mentions_do_not_trip(prose: str) -> None:
    assert not _trips(prose), f"false positive on prose: {prose!r}"


def test_no_inspected_doc_is_reported_as_a_placeholder() -> None:
    """A new false positive must not be able to hide behind an existing one.

    Asserted through ``meaningful()`` -- the actual routing predicate. Note
    ``PRODUCT_IDEA.md`` legitimately still carries ``TBD`` field values outside
    its "Raw idea" section, which ``meaningful()`` deliberately ignores.
    """
    offenders = [rel for rel in _inspected_docs() if not router.meaningful(rel)]
    assert offenders == [], f"documents falsely flagged as placeholders: {offenders}"


# --------------------------------------------------------------------------
# Direction 2: every genuine placeholder form is still caught.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        "| Owner | Pending |\n",
        "| Product | PRD approved | Not started | TBD | TBD |\n",
        "| Owner | Placeholder |\n",
        "- Pending\n",
        "- TBD\n",
        "* TODO\n",
        "TBD\n",
        "## Summary\n\nTBD\n",
        "- Operator/support user: TBD.\n",
        "Status: draft | Owner: TBD | Evidence: TBD\n",
        "Owner: Pending\n",
        "- Summary: Replace with real product explanation.\n",
        "Replace with two plain-language sentences. Suggested draft:\n",
        "## Raw idea\n\nWrite the idea here\n",
        "Scope: Define after clarification\n",
        "Detail: To be written after idea clarification\n",
        "| Status | **TBD** |\n",
    ],
)
def test_genuine_placeholder_forms_still_trip(doc: str) -> None:
    assert _trips(doc), f"genuine placeholder went undetected: {doc!r}"


def test_regex_does_not_backtrack_catastrophically() -> None:
    """A Markdown horizontal rule must not blow up the matcher.

    The first cut of the anchored regex used a nested quantifier
    (``(?:[>*_`~#+-]+[ \\t]*)*``) and hung for minutes on long ``---``/``***``
    runs. Guard the flattened form: this input matches nothing and must return
    effectively instantly.
    """
    hostile = "-" * 4000 + "\n" + "*" * 4000 + "\n"
    start = time.monotonic()
    assert not _trips(hostile)
    assert time.monotonic() - start < 1.0


def test_product_idea_template_stub_is_not_meaningful(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """End-to-end through ``meaningful()``: a template stub still fails the gate."""
    monkeypatch.setattr(router, "ROOT", tmp_path)
    stub = tmp_path / "docs" / "stub.md"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(
        "# Problem statement\n\n## Context\n\nTBD\n\n## Impact\n\nTBD\n",
        encoding="utf-8",
    )
    assert router.meaningful("docs/stub.md") is False
