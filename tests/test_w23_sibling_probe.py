"""A fixture module for W23's sibling-name case. Not a guard of its own.

``tests/test_lazy_nodeid_selection.py`` selects
``test_alpha[a]`` and ``test_alpha_extra`` together and asserts the second one
survives. The filter in ``tests/lazy_nodeid_selection.py`` decides which items
"came from" a rewritten argument; matching that by raw string prefix made
``test_alpha_extra`` look like one of ``test_alpha``'s cases, so a separately
requested sibling was deselected with no error.

There is no such (parametrized parent, name-extending sibling) pair anywhere
else in the suite — censused in review: 0 of 4561 node ids — so the case has to
be constructed. It lives here, as a checked-in module, rather than being
written at runtime: a path cited in a test but absent from the tree is exactly
what ``tests/unit/test_cited_paths_resolve.py`` refuses.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("value", ["a", "b"])
def test_alpha(value: str) -> None:
    assert value


def test_alpha_extra() -> None:
    assert True
