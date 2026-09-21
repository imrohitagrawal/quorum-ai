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
named. So a rewritten argument that matches NO item is a usage error (exit 4),
named id and all. ``tests/test_lazy_nodeid_selection.py`` pins that case,
including the exit code — a ``warnings.warn`` in its place exits 5, which
mutmut reads as "no tests", a different verdict from a refusal.

ONE NARROWER GUARANTEE THAN IT LOOKS: when the FILE in the id does not exist,
pytest fails before this plugin's filter runs, and its message names the
REWRITTEN id with the case stripped — "file or directory not found", then the
path and function without the ``[case]`` part. The run still fails loudly; the
id you typed is just not echoed back in full.
"""

from __future__ import annotations

import os
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

#: Node ids this run asked for that had to be rewritten, keyed off the RUN's
#: own ``Config`` rather than held in a module global.
#:
#: THE MODULE GLOBAL WAS A FALSE-ACCEPTANCE BUG, found in review and measured.
#: ``mutmut`` calls ``pytest.main`` IN-PROCESS for its clean run over the union
#: of every mutant's tests, and only then forks one child per mutant
#: (``mutmut/__main__.py``: ``execute_pytest`` -> ``pytest.main``, then
#: ``os.fork``). A global populated by the parent is inherited by every child,
#: which then asks for ids it never requested, gets ``UsageError`` and exits 4.
#: mutmut records those mutants as crashes and DROPS THEM FROM THE
#: DENOMINATOR, so the gate printed ``42 killed, 0 survived`` and
#: ``100.0%``, exit 0, on a diff whose honest score was ``52 killed, 24
#: survived`` = ``68.4%``, BELOW THRESHOLD, exit 2. A gate reporting a pass for
#: work it never scored is the one outcome this whole file exists to prevent.
#:
#: MEASURED, two ``pytest.main()`` calls in one process: the first selects
#: ``1/13``, the second exits 4 with "no test matched the requested case
#: id(s)" naming the FIRST call's id.
_REQUESTED_KEY: pytest.StashKey[dict[str, list[str]]] = pytest.StashKey()


def _looks_like_a_lazy_case(arg: str) -> re.Match[str] | None:
    """Match ``path::func[case]``, ignoring anything that is not a node id."""
    if "::" not in arg or not arg.endswith("]"):
        return None
    return _BRACKETED_NODE_ID.match(arg)


def rewrite_lazy_case_args(config: Config, args: list[str]) -> None:
    """Rewrite unresolvable case ids to their parent function, before collection.

    Called from ``tests/conftest.py``'s ``pytest_collection`` hook, which runs
    before pytest reads ``session.config.args`` and which a conftest may
    implement. Two earlier wirings were tried and measured:
    ``pytest_load_initial_conftests`` (documented as never called for conftest
    files — registering this module through ``pytest_plugins`` left the
    selection still exiting 4), and ``-p tests.lazy_nodeid_selection`` in
    ``addopts``, which raised ``ImportError: No module named 'tests'`` under
    ``uv run pytest`` — the console script ``make test`` uses. Review measured
    that the same ``-p`` DOES import under ``python -m pytest``, where the cwd
    is on ``sys.path``, so that failure is about ``sys.path`` at plugin-load
    time rather than about the rootdir being unimportable in general.
    ``pytest_configure`` would also work; this is not the only possible hook,
    and an earlier revision called it "the earliest", which nothing measured.

    Deliberately cheap and conservative: it touches only arguments that look
    like ``path::func[case]``. Whether the rewrite is NEEDED cannot be known
    without collecting, so it is applied to all of them and the
    post-collection filter restores exact selection either way — which makes
    the behaviour identical for ordinary parametrized ids.

    The requested ids live on ``config.stash``, so they belong to THIS run and
    cannot leak into the next one in the same process. See ``_REQUESTED_KEY``.
    """
    requested: dict[str, list[str]] = {}
    for index, arg in enumerate(args):
        match = _looks_like_a_lazy_case(arg)
        if match is None:
            continue
        parent = f"{match.group('path')}::{match.group('func')}"
        requested.setdefault(parent, []).append(arg)
        args[index] = parent
    config.stash[_REQUESTED_KEY] = requested


def keep_requested_cases(config: Config, items: list[Any]) -> None:
    """Keep exactly the requested cases, and refuse an id that matched nothing."""
    requested = config.stash.get(_REQUESTED_KEY, {})
    if not requested:
        return

    wanted: set[str] = {node_id for ids in requested.values() for node_id in ids}
    parents = tuple(requested)

    def _satisfied(node_id: str) -> str | None:
        """The requested id this item answers, or ``None``.

        An ABSOLUTE id has to match too. Items carry rootdir-relative node ids,
        so comparing raw strings made an absolute bracketed id
        — a selection pytest resolved fine before this plugin existed — fail
        with the UsageError below. Found in review. One matcher, used for BOTH
        "keep this item" and "was this id matched at all": computing those two
        answers separately is what made the first attempt at absolute support
        keep the item and then refuse the run anyway.
        """
        for candidate in (
            node_id,
            node_id.replace("\\", "/"),
            os.path.join(str(config.rootpath), node_id),
            os.path.join(str(config.rootpath), node_id).replace("\\", "/"),
        ):
            if candidate in wanted:
                return candidate
        return None

    def _from_a_rewritten_arg(node_id: str) -> bool:
        # Items that came from a DIFFERENT argument must pass through
        # untouched: a run may mix a rewritten id with a plain path.
        #
        # Matched on the node-id BOUNDARY, not a raw prefix. A raw
        # ``startswith`` made ``path::test_foo_bar`` look like it came from a
        # rewritten ``path::test_foo``, so a separately requested sibling whose
        # name merely EXTENDS the rewritten one was deselected with no error.
        # Found in review; there is no such pair in the suite today (censused:
        # 0 of 4561 node ids), which is exactly why it needed a test.
        spellings = (node_id, os.path.join(str(config.rootpath), node_id))
        for parent in parents:
            for spelling in spellings:
                if spelling == parent or spelling.startswith((f"{parent}[", f"{parent}::")):
                    return True
        return False

    kept: list[Any] = []
    satisfied: set[str] = set()
    for item in items:
        answer = _satisfied(item.nodeid)
        if answer is not None:
            satisfied.add(answer)
            kept.append(item)
        elif not _from_a_rewritten_arg(item.nodeid):
            kept.append(item)

    missing = sorted(node_id for node_id in wanted if node_id not in satisfied)
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
