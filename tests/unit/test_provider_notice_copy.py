"""F-09 (triage issue #2) — provider notices are read by USERS.

The reported symptom, verbatim from the triage doc: *"Run notices … no
citation annotations … fallback web search … :online results" confusing*,
verdict **BY DESIGN (bad copy)**, root cause *"Developer-speak
(`:online`, 'citation annotations') leaks to users."*

``:online`` is an OpenRouter model-id suffix. "Citation annotations" is
the name of a field in a provider response. Neither is a thing a user of
this product has any way to know, and both appeared in notices rendered
directly onto the model cards.

This guard is deliberately a REGISTRY walk rather than a set of pinned
strings: pinning the new copy would only restate it, and the next notice
someone adds is exactly where the old habit would come back. Every
user-facing notice must be registered in ``PROVIDER_NOTICES`` and every
registered notice must survive these rules — the same shape as
``readiness.APPROVED_REASON_PREFIXES``.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from product_app import providers
from product_app.providers import PROVIDER_NOTICES

#: Vocabulary that only means something to someone holding the provider
#: API docs. Each entry is a substring match, case-insensitive.
_DEVELOPER_SPEAK = (
    ":online",
    "citation annotation",
    "local_simulation",
    "openrouter",
    "finish_reason",
    "http",
    "api key",
    "null",
    "none",
)


def _declared_notice_names() -> set[str]:
    """Every ``NOTICE_*`` constant ``providers.py`` declares, read from its AST.

    Derived from the module, never retyped here — a hand-copied count goes
    stale silently the moment a notice is added or removed.
    """
    tree = ast.parse(pathlib.Path(providers.__file__).read_text(encoding="utf-8"))
    return {
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("NOTICE_")
    }


def test_the_registry_lists_every_notice_the_module_declares() -> None:
    """A guard over an empty collection proves nothing.

    ``all([])`` being True is precisely how F-06's cost gate went
    vacuous; this suite refuses to repeat it. So the registry must be
    non-empty AND complete.

    This replaced a hand-typed ``>= 9``. #171 deleted a notice that no branch
    can emit any more, which would have made a retyped floor red for the wrong
    reason — and the only honest repair to a retyped floor is to retype it,
    which is how a floor stops measuring anything. Derived from the AST, it
    tracks additions and deletions on its own, and because it compares CONTENTS
    rather than counts it catches a notice declared but never registered — which
    neither the old floor nor a length comparison can see.

    What turns it red: add ``NOTICE_ANYTHING = "..."`` to ``providers.py`` and
    leave it out of ``PROVIDER_NOTICES`` — even if you also register some other
    literal to keep the two counts equal.
    """
    names = _declared_notice_names()
    assert names, "no NOTICE_* constants found — the walk is looking in the wrong place"
    declared = {getattr(providers, name) for name in names}
    # MEMBERSHIP, not a count. An earlier draft compared lengths, and review
    # broke it in one move: declare a jargon-carrying notice, reference it twice
    # so the reachability guard is satisfied, register some unrelated literal,
    # and the two counts stay equal while the new notice is unguarded. Equal
    # cardinality is not the property; equal contents is.
    assert set(PROVIDER_NOTICES) == declared, (
        "PROVIDER_NOTICES and the module's NOTICE_* constants disagree.\n"
        f"declared but not registered: {sorted(declared - set(PROVIDER_NOTICES))}\n"
        f"registered but not declared: {sorted(set(PROVIDER_NOTICES) - declared)}"
    )


@pytest.mark.parametrize("notice", PROVIDER_NOTICES)
def test_no_notice_speaks_to_developers(notice: str) -> None:
    lowered = notice.lower()
    for token in _DEVELOPER_SPEAK:
        assert token not in lowered, (
            f"user-facing notice leaks developer vocabulary {token!r}: {notice!r}"
        )


@pytest.mark.parametrize("notice", PROVIDER_NOTICES)
def test_no_notice_has_collapsed_whitespace(notice: str) -> None:
    """The fallback notice read "because  search results" in production.

    A brand name was removed from the copy and the space it sat in was
    left behind. Cosmetic, and visible to every user who hit that path.
    """
    assert "  " not in notice, f"double space in notice: {notice!r}"
    assert notice == notice.strip()


@pytest.mark.parametrize("notice", PROVIDER_NOTICES)
def test_every_notice_is_a_complete_sentence(notice: str) -> None:
    """Notices render as standalone prose next to an answer."""
    assert notice.endswith("."), notice
    assert notice[0].isupper(), notice


@pytest.mark.parametrize("notice", PROVIDER_NOTICES)
def test_no_notice_carries_markup_or_identifiers(notice: str) -> None:
    """These surfaces render through ``textContent``, not the Markdown
    renderer, so any markup would be shown to the user literally."""
    assert not re.search(r"[<>{}`*_]|\]\(", notice), notice


def test_no_notice_is_written_inline_instead_of_registered() -> None:
    """The registry only guards the copy that is IN it.

    Found by adversarial review: replacing a ``provider_notice=NOTICE_*``
    reference with a bare string literal put developer jargon back on the
    model card while every test above stayed green, because the walk
    never sees a string that was never registered.

    So the guard is closed at the assignment site: every
    ``provider_notice=`` in the provider layer must reference a name, not
    a literal. Parsed with ``ast`` rather than grepped, so a multi-line
    or implicitly-concatenated literal cannot slip past.
    """
    source = pathlib.Path(providers.__file__).read_text(encoding="utf-8")
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "provider_notice":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                offenders.append(f"line {keyword.value.lineno}: {keyword.value.value[:60]!r}")
            elif isinstance(keyword.value, ast.JoinedStr):
                # An f-string is a JoinedStr, not a Constant — it would
                # otherwise slip past, and interpolating runtime data into
                # user-facing copy is worse than a plain literal.
                offenders.append(f"line {keyword.value.lineno}: f-string notice")

    assert offenders == [], (
        "provider_notice assigned an inline string literal; register it in "
        f"PROVIDER_NOTICES instead so the copy guard can see it: {offenders}"
    )


def test_every_registered_notice_is_reachable_from_the_provider_layer() -> None:
    """A notice nobody emits is dead copy the guard still blesses.

    Pairs with the test above: that one stops copy escaping the registry,
    this one stops the registry accumulating copy no branch produces.
    """
    source = pathlib.Path(providers.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    registered = {
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("NOTICE_")
    }
    # Every NOTICE_* must be used somewhere beyond its own assignment and
    # the PROVIDER_NOTICES tuple; count usages to catch "declared, listed,
    # never emitted".
    emitted = {
        name
        for name in registered
        if sum(1 for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == name) > 2
    }
    assert registered, "no NOTICE_* constants found — the walk is looking in the wrong place"
    assert registered == emitted, f"registered but never emitted: {sorted(registered - emitted)}"
