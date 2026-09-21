"""Make a lazily-expanded test case selectable by its node id (W23).

WHAT IS BROKEN WITHOUT THIS. ``mutmut`` runs the tests that cover a changed
function by passing their node ids to pytest. When one of those ids belongs to
a schemathesis case — ``test_api_conforms_to_openapi_contract[GET /status]``
in ``tests/contract/test_api_contract_schemathesis.py`` — pytest exits 4 with
``ERROR: not found``, ``mutmut`` raises
``BadTestExecutionCommandsException``, and the mutation gate dies before
scoring a single mutant. Every diff touching a function reachable from a
documented endpoint is affected: ``/status``, ``/ready``, ``/ui``, ``/v1/*``.

WHY, EXACTLY — and it is NOT the space in the id. Under this repo's own pytest
config a plain parametrized id containing a space selects fine
(``tests/test_lazy_nodeid_selection.py`` proves it by selecting one). pytest
resolves ``path::name`` by matching ``name`` against the DIRECT children of the
module collector. For an ordinary parametrized test those children are the
parametrized ``Function`` items themselves, so ``func[param]`` matches. A
schemathesis module instead returns ONE child named
``test_api_conforms_to_openapi_contract``; its 13 per-operation items are
produced later, when that child is expanded. So the bracketed id matches
nothing at selection time. MEASURED (``Module.collect()`` during a selection
run): ``['TestClient', 'test_api_conforms_to_openapi_contract', ...]`` — the
bare name, never a bracketed one.

WHAT THIS DOES. Before collection, an argument of the form ``path::func[case]``
whose ``func[case]`` is not a direct child of the module is rewritten to
``path::func``. After collection, only the items whose node ids were actually
asked for are kept. The named case runs — exactly it, not the other twelve.

WHY NOT THE OBVIOUS ALTERNATIVES:

* **Exempt the schemathesis tests from the gate.** That is what the failure
  tempts you into, and it is forbidden: an exempted test must be one that
  cannot kill a ``src/`` mutant, and these can. It would also leave every
  endpoint-adjacent function unmutated while the gate reported green.
* **Rewrite to the parent function and run all 13.** Simpler, and it keeps the
  gate alive, but it multiplies every mutant's runtime by thirteen — straight
  into the truncation the gate already suffers (#464) — and it quietly changes
  what "the tests covering this mutant" means.
* **Re-parametrize the contract test ourselves** so the items are ordinary
  ``Function`` nodes. That is the deepest fix, and it rewrites a BLOCKING gate's
  hypothesis wiring (strategies, ``max_examples``, checks, phases) to solve a
  tooling problem. Rejected as disproportionate, and recorded in ADR-0117.

THE FAILURE MODE THIS COULD HAVE INTRODUCED, and how it is closed: a rewrite
that silently fell back to the parent function would turn a typo'd id into a
full-function run that reports success while never running what the caller
named. So a rewritten argument that matches NO item is a usage error, named id
and all. ``tests/test_lazy_nodeid_selection.py`` pins that case.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from _pytest.config import Config

#: ``path::name[case]``. The case part may contain anything but ``]``, which is
#: how ``GET /status`` survives — the space was never the problem.
_BRACKETED_NODE_ID = re.compile(
    r"^(?P<path>[^:]+(?::[^:][^:]*)?)::(?P<func>[^:\[]+)\[(?P<case>.+)\]$"
)

#: Node ids this run asked for that had to be rewritten, and therefore must be
#: filtered back down after collection. Empty on every ordinary run, which is
#: what keeps this plugin invisible.
_REQUESTED: dict[str, list[str]] = {}


def _looks_like_a_lazy_case(arg: str) -> re.Match[str] | None:
    """Match ``path::func[case]``, ignoring anything that is not a node id."""
    if "::" not in arg or not arg.endswith("]"):
        return None
    return _BRACKETED_NODE_ID.match(arg)


def rewrite_lazy_case_args(args: list[str]) -> None:
    """Rewrite unresolvable case ids to their parent function, before collection.

    Called from ``tests/conftest.py``'s ``pytest_collection`` hook, which is
    the earliest point a CONFTEST can reach the argument list:
    ``pytest_load_initial_conftests`` is documented as never being called for
    conftest files, and MEASURED here — registering this module through
    ``pytest_plugins`` left the selection still exiting 4. Loading it with
    ``-p`` from ``addopts`` fails earlier still, because ``tests`` is not yet
    importable when plugin arguments are consumed (``ImportError: No module
    named 'tests'``).

    Deliberately cheap and conservative: it touches only arguments that look
    like ``path::func[case]``. Whether the rewrite is NEEDED cannot be known
    without collecting, so it is applied to all of them and the
    post-collection filter restores exact selection either way — which makes
    the behaviour identical for ordinary parametrized ids.
    """
    for index, arg in enumerate(args):
        match = _looks_like_a_lazy_case(arg)
        if match is None:
            continue
        parent = f"{match.group('path')}::{match.group('func')}"
        _REQUESTED.setdefault(parent, []).append(arg)
        args[index] = parent


def keep_requested_cases(config: Config, items: list[Any]) -> None:
    """Keep exactly the requested cases, and refuse an id that matched nothing."""
    if not _REQUESTED:
        return

    wanted: set[str] = {node_id for ids in _REQUESTED.values() for node_id in ids}
    parents = tuple(_REQUESTED)

    def _requested(node_id: str) -> bool:
        return node_id in wanted or node_id.replace("\\", "/") in wanted

    def _from_a_rewritten_arg(node_id: str) -> bool:
        # Items that came from a DIFFERENT argument must pass through
        # untouched: a run may mix a rewritten id with a plain path.
        return node_id.startswith(parents)

    kept = [
        item for item in items if _requested(item.nodeid) or not _from_a_rewritten_arg(item.nodeid)
    ]

    matched = {item.nodeid for item in kept}
    missing = sorted(node_id for node_id in wanted if node_id not in matched)
    if missing:
        # Not a warning, and not a silent fallback to the parent function: the
        # caller named a case that does not exist, and a gate that accepted it
        # would report a pass for a test it never ran.
        raise pytest.UsageError(
            "no test matched the requested case id(s): "
            + ", ".join(missing)
            + ". The parent function exists, so the case name is wrong or the "
            "operation is no longer generated."
        )

    deselected = [item for item in items if item not in kept]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
