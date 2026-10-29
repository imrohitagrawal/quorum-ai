"""W116: a test must still work when mutmut runs it inside ``./mutants/``.

mutmut 3.6.0 finds its config and its source by paths RELATIVE to the current
folder (``Path("pyproject.toml")``, then ``source_paths = ["src"]`` resolved
with ``strict=True``), and every mutated ``src/product_app`` file imports its
trampoline first, which reads that config. Measured on the discovery probe
(#596, run 40753467337): 26 tests failed inside the copy, in five causes, A to
E in ADR-0183. This module pins four of them statically (A and B in G1a, C in
G1b, D in G3) and the mutmut behaviour behind A and B at run time (G2); the
fifth, E, a root path missing from ``also_copy``, is pinned in
``test_mutation_copy_completeness.py``:

* **G1a** — a test moved the process, or started a Python child, in a folder
  with no ``src``: ``FileNotFoundError: 'src'`` in process, "Could not figure
  out where the code to mutate is" in a child. The safe form is
  ``tests.mutmut_cwd.mutmut_can_run_in(folder)``, which makes an empty
  ``src`` there.
* **G1b** — a test recognised a function by its frame. mutmut renames the
  original body (``x…create__mutmut_orig``), so ``co_name == "create"`` is
  never true inside the copy.
* **G2** — the mutmut behaviour G1a's helper rests on, measured with a real
  child interpreter, so a mutmut upgrade that changes it goes red here.
* **G3** — a test parsed ``src`` source through a ``product_app`` module's
  ``__file__``. Inside the copy that is the MUTATED file, which also holds the
  original body as ``x_…__mutmut_orig`` and renamed outer copies; a structural
  count over it is wrong. The safe form reads the real file through
  ``tests.repo_root.find_repo_root``.

This module imports no ``product_app`` and is not marked, so it runs in the
ordinary suite and inside the copy alike.

What these static walks cannot see (recorded, not closed):

* G1a looks only at a list LITERAL whose first item is ``*.executable``; an
  argument list built in a variable (``argv = [...]; run(argv, cwd=tmp)``)
  escapes. Its ``product_app`` reach is one level of ``tests.*`` import.
* G1b knows the spellings named in ``_FRAME_ATTRIBUTES`` /
  ``_FRAME_CALLS``; ``traceback.walk_stack``, ``inspect.getouterframes`` and
  ``getattr(x, "co_name")`` escape.
* G3 tracks names through simple assignments, ``with … as``, ``Path``/``str``
  /``open`` wrappers, ``/`` joins, ``.parent(s)`` and the read methods, and a
  module reached through a same-file helper that returns
  ``importlib.import_module("product_app…")``. A source path built from the
  TEST's own ``__file__`` (``Path(__file__).parents[2] / "src"``) is a
  different spelling of the same hazard and is not tracked.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

import yaml
from tests.mutmut_cwd import mutmut_can_run_in
from tests.repo_root import find_repo_root
from tests.subprocess_env import env_without_coverage
from tests.unit.test_mutation_test_set_integrity import DESELECTED_FROM_THE_MUTANT_RUN

REPO_ROOT = find_repo_root(Path(__file__))
TESTS_DIR = REPO_ROOT / "tests"

#: The name of ``tests/mutmut_cwd.py``'s helper, which the static walks look
#: for at each ``chdir`` and child ``cwd=`` site.
HELPER = "mutmut_can_run_in"

#: Python children that run from the tree's own root. Under mutmut that root is
#: ``./mutants/``, which holds ``src``, so mutmut finds its source there. Keyed
#: on ``(module, ast.unparse(cwd))`` so a new site is never covered by an old
#: entry.
ROOT_FOLDER_CHILDREN = {
    (
        "tests/unit/test_logging_config_sentry_redaction.py",
        "'.'",
    ): "the process's own folder: the repository root, or ./mutants/ under mutmut",
    (
        "tests/unit/test_session_exemptions.py",
        "root",
    ): "Path(__file__).parents[2]: the tree this test is in, which holds src",
    (
        "tests/unit/test_telemetry_sink.py",
        "str(repo_root)",
    ): "Path(__file__).parents[2]: the tree this test is in, which holds src",
    (
        "tests/perf/test_perf_gate_hermeticity.py",
        "str(REPO_ROOT)",
    ): "Path(__file__).parents[2]: the tree this test is in, which holds src",
    # Found by this walk on 7f8cf00.
    # ``_REPO_ROOT = Path(__file__).resolve().parents[1]``: the tree's root.
    (
        "tests/test_store_shutdown_safety.py",
        "_REPO_ROOT",
    ): "Path(__file__).parents[1]: the tree this test is in, which holds src",
}

_FRAME_ATTRIBUTES = frozenset({"co_name", "co_qualname", "funcName"})
_FRAME_CALLS = frozenset({"_getframe", "currentframe", "extract_stack"})

#: Calls that hand a path's file or text on: ``Path(x)``, ``str(x)``, ``open(x)``.
_PATH_WRAPPERS = frozenset({"Path", "PurePath", "str", "open", "fspath"})
#: Methods of a path or file whose result still carries that file.
_PATH_METHODS = frozenset(
    {"read_text", "read_bytes", "read", "open", "resolve", "absolute", "with_name"}
)
#: Attributes of a path that still lead into the same tree.
_PATH_ATTRIBUTES = frozenset({"parent", "parents"})


def _parse(text: str) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(text)


_SOURCES: list[tuple[str, ast.Module]] = []


def _test_sources() -> Iterator[tuple[str, ast.Module]]:
    """Every ``.py`` file under ``tests/`` that mutmut runs, parsed (once per
    process: the four walks share it)."""
    if not _SOURCES:
        deselected = set(DESELECTED_FROM_THE_MUTANT_RUN)
        for path in sorted(TESTS_DIR.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel not in deselected:
                _SOURCES.append((rel, _parse(path.read_text(encoding="utf-8"))))
    assert len(_SOURCES) > 100, f"only {len(_SOURCES)} test sources found — the glob is wrong"
    yield from _SOURCES


def _is_product_app(name: str) -> bool:
    return name == "product_app" or name.startswith("product_app.")


def _imports_product_app_directly(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(_is_product_app(a.name) for a in node.names):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and _is_product_app(node.module or "")
        ):
            return True
        if _is_import_module_of_product_app(node):
            return True
    return False


def _imported_test_helpers(tree: ast.Module) -> set[str]:
    """``tests.*`` module names this module imports."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names if a.name.startswith("tests."))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.startswith("tests."):
                names.add(node.module)
            elif node.module == "tests":
                names.update(f"tests.{a.name}" for a in node.names)
    return names


def _reaches_product_app(tree: ast.Module) -> bool:
    """Imports ``product_app`` itself, or through one ``tests.*`` module that does."""
    if _imports_product_app_directly(tree):
        return True
    for name in _imported_test_helpers(tree):
        stem = REPO_ROOT.joinpath(*name.split("."))
        for path in (stem.with_suffix(".py"), stem / "__init__.py"):
            if path.is_file() and _imports_product_app_directly(
                _parse(path.read_text(encoding="utf-8"))
            ):
                return True
    return False


class _Scopes:
    """Simple-assignment lookup per function, falling back to enclosing scopes."""

    def __init__(self, tree: ast.Module) -> None:
        self.scope_of: dict[ast.AST, ast.AST] = {}
        self.parent_scope: dict[ast.AST, ast.AST] = {}
        self.assigned: dict[ast.AST, dict[str, list[ast.expr]]] = {}
        self._visit(tree, tree)

    def _visit(self, node: ast.AST, scope: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            child_scope = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                self.parent_scope[child] = scope
                child_scope = child
            self.scope_of[child] = scope
            table = self.assigned.setdefault(scope, {})
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        table.setdefault(target.id, []).append(child.value)
            elif isinstance(child, ast.AnnAssign | ast.NamedExpr) and child.value is not None:
                if isinstance(child.target, ast.Name):
                    table.setdefault(child.target.id, []).append(child.value)
            elif isinstance(child, ast.withitem) and isinstance(child.optional_vars, ast.Name):
                table.setdefault(child.optional_vars.id, []).append(child.context_expr)
            self._visit(child, child_scope)

    def values(self, name: ast.Name) -> list[ast.expr]:
        """Every value assigned to ``name`` in its scope or the nearest outer one."""
        scope: ast.AST | None = self.scope_of.get(name)
        while scope is not None:
            found = self.assigned.get(scope, {}).get(name.id)
            if found:
                return found
            scope = self.parent_scope.get(scope)
        return []


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


# --- G1a ----------------------------------------------------------------------


def _is_prepared_folder(
    node: ast.expr, scopes: _Scopes, seen: frozenset[str] = frozenset()
) -> bool:
    """``mutmut_can_run_in(...)``, possibly through ``str(...)`` or a name bound
    ONLY to such values."""
    if isinstance(node, ast.Call):
        name = _call_name(node.func)
        if name == HELPER:
            return True
        if name in {"str", "Path"} and len(node.args) == 1 and not node.keywords:
            return _is_prepared_folder(node.args[0], scopes, seen)
        return False
    if isinstance(node, ast.Name) and node.id not in seen:
        values = scopes.values(node)
        return bool(values) and all(
            _is_prepared_folder(v, scopes, seen | {node.id}) for v in values
        )
    return False


def _starts_an_interpreter(call: ast.Call) -> bool:
    if not call.args or not isinstance(call.args[0], ast.List | ast.Tuple):
        return False
    items = call.args[0].elts
    return bool(items) and _call_name(items[0]) == "executable"


def _chdir_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "chdir"
    ]


def _g1a_sites(module: str, tree: ast.Module) -> tuple[list[str], set[tuple[str, str]]]:
    """(unprepared folder sites, pinned root-folder pairs seen) in one module."""
    if not _reaches_product_app(tree):
        return [], set()
    scopes = _Scopes(tree)
    sites: list[str] = []
    pinned: set[tuple[str, str]] = set()
    for call in _chdir_calls(tree):
        folder = call.args[0] if call.args else None
        if folder is None or not _is_prepared_folder(folder, scopes):
            shown = ast.unparse(folder) if folder is not None else ""
            sites.append(f"{module}:{call.lineno}: chdir({shown})")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _starts_an_interpreter(node):
            continue
        for keyword in node.keywords:
            if keyword.arg != "cwd" or _is_prepared_folder(keyword.value, scopes):
                continue
            key = (module, ast.unparse(keyword.value))
            if key in ROOT_FOLDER_CHILDREN:
                pinned.add(key)
            else:
                sites.append(f"{module}:{keyword.value.lineno}: cwd={key[1]}")
    return sorted(sites, key=lambda site: int(site.split(":")[1])), pinned


def _g1a_scan() -> tuple[list[str], set[tuple[str, str]]]:
    sites: list[str] = []
    pinned: set[tuple[str, str]] = set()
    for module, tree in _test_sources():
        found, seen = _g1a_sites(module, tree)
        sites.extend(found)
        pinned |= seen
    return sites, pinned


def test_g1a_no_test_runs_src_code_from_a_folder_without_src() -> None:
    """Every folder a ``product_app``-reaching test moves to, or starts a Python
    child in, is made by ``mutmut_can_run_in`` (or is a pinned root-folder
    child, each still present). Only list literals starting with
    ``*.executable`` are seen.

    Red when: a test calls src code after ``chdir`` to a bare temp folder, or
    starts an interpreter list ``[sys.executable, ...]`` with ``cwd=`` a bare
    one, or a pinned root-folder child is removed (on ``7f8cf00``: 6 sites)."""
    sites, pinned = _g1a_scan()
    assert sites == [], (
        "these tests run src code from a folder with no `src`, so under mutmut "
        "they fail with FileNotFoundError: 'src' (in process) or 'Could not "
        "figure out where the code to mutate is' (in a child). Wrap the folder "
        f"in tests.mutmut_cwd.{HELPER}(...):\n" + "\n".join(sites)
    )
    stale = sorted(set(ROOT_FOLDER_CHILDREN) - pinned)
    assert stale == [], f"pinned root-folder children no longer present: {stale}"


def test_g1a_partner_a_planted_bare_folder_is_flagged_and_the_helper_form_is_not() -> None:
    """The walk sees both shapes it exists for, accepts the helper's, and
    exempts a module that reaches no ``product_app``.

    Red when: ``_g1a_sites`` stops flagging ``chdir(tmp_path)``, ``cwd=tmp_path``
    on an interpreter list, a name rebound to a bare folder, or a module that
    reaches ``product_app`` through a ``tests.*`` helper; or starts flagging
    the helper."""
    bare = _parse(
        "import subprocess, sys\n"
        "import product_app\n"
        "def test_x(monkeypatch, tmp_path):\n"
        "    monkeypatch.chdir(tmp_path)\n"
        "    subprocess.run([sys.executable, '-c', 'x'], cwd=tmp_path)\n"
    )
    assert _g1a_sites("planted.py", bare)[0] == [
        "planted.py:4: chdir(tmp_path)",
        "planted.py:5: cwd=tmp_path",
    ]
    helper = _parse(
        "import subprocess, sys\n"
        "import product_app\n"
        "from tests.mutmut_cwd import mutmut_can_run_in\n"
        "def test_x(monkeypatch, tmp_path):\n"
        "    monkeypatch.chdir(mutmut_can_run_in(tmp_path))\n"
        "    subprocess.run([sys.executable, '-c', 'x'], cwd=str(mutmut_can_run_in(tmp_path)))\n"
        "    folder = mutmut_can_run_in(tmp_path)\n"
        "    subprocess.Popen([sys.executable, '-c', 'x'], cwd=folder)\n"
    )
    assert _g1a_sites("planted.py", helper) == ([], set())
    rebound = _parse(
        "import subprocess, sys\n"
        "import product_app\n"
        "def test_x(tmp_path):\n"
        "    folder = mutmut_can_run_in(tmp_path)\n"
        "    folder = tmp_path\n"
        "    subprocess.run([sys.executable], cwd=folder)\n"
    )
    assert _g1a_sites("planted.py", rebound)[0] == ["planted.py:6: cwd=folder"]
    no_app = _parse("def test_x(monkeypatch, tmp_path):\n    monkeypatch.chdir(tmp_path)\n")
    assert _g1a_sites("planted.py", no_app) == ([], set())
    # One level of `tests.*` import: the real harness imports product_app.
    through_helper = _parse(
        "from tests.end_sessions_harness import run_command\n"
        "def test_x(monkeypatch, tmp_path):\n"
        "    monkeypatch.chdir(tmp_path)\n"
    )
    assert _g1a_sites("planted.py", through_helper)[0] == ["planted.py:3: chdir(tmp_path)"]


def test_g1a_partner_the_walk_counts_the_exempt_chdir_calls() -> None:
    """The real tree has ``chdir`` calls the walk sees and exempts: 11 in
    ``test_gate_liveness_floors.py`` and 1 in ``test_perf_percentiles_artifact.py``,
    neither of which reaches ``product_app``.

    Red when: ``_chdir_calls`` stops finding real calls, or either module starts
    reaching ``product_app`` (then its 12 calls need the helper)."""
    counted = 0
    for module, tree in _test_sources():
        if module in {
            "tests/unit/test_gate_liveness_floors.py",
            "tests/unit/test_perf_percentiles_artifact.py",
        }:
            counted += len(_chdir_calls(tree))
            assert not _reaches_product_app(tree), module
            assert _g1a_sites(module, tree) == ([], set()), module
    assert counted == 12


# --- G1b ----------------------------------------------------------------------


def _g1b_sites(module: str, tree: ast.Module) -> list[str]:
    hits: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FRAME_ATTRIBUTES:
            hits.setdefault(node.lineno, set()).add(node.attr)
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            is_inspect_stack = (
                name == "stack"
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "inspect"
            )
            if name in _FRAME_CALLS or is_inspect_stack:
                hits.setdefault(node.lineno, set()).add(f"{name}()")
    return [f"{module}:{line}: {', '.join(sorted(names))}" for line, names in sorted(hits.items())]


def test_g1b_no_test_recognises_a_function_by_its_frame() -> None:
    """No module mutmut runs reads ``co_name`` / ``co_qualname`` / ``funcName``
    or calls ``_getframe``, ``currentframe``, ``inspect.stack``,
    ``extract_stack``: mutmut renames every mutated function's code object.

    Red when: a test recognises a function by its frame (on ``7f8cf00``:
    ``tests/integration/test_late_run_refusal.py:346``)."""
    sites = [site for module, tree in _test_sources() for site in _g1b_sites(module, tree)]
    assert sites == [], (
        "these tests recognise a function by its frame; under mutmut the "
        "function is renamed (x…__mutmut_orig), so the check is never true. "
        "Record the call another way (a wrapper on the object):\n" + "\n".join(sites)
    )


def test_g1b_partner_a_planted_frame_read_is_flagged_and_a_thread_id_is_not() -> None:
    """Red when: ``_g1b_sites`` stops flagging a frame-name read."""
    planted = _parse(
        "import inspect, logging, sys, threading, traceback\n"
        "a = sys._getframe(1).f_code.co_name\n"
        "b = inspect.currentframe()\n"
        "c = inspect.stack()\n"
        "d = traceback.extract_stack()\n"
        "e = record.funcName\n"
        "f = threading.get_ident()\n"
    )
    assert _g1b_sites("planted.py", planted) == [
        "planted.py:2: _getframe(), co_name",
        "planted.py:3: currentframe()",
        "planted.py:4: stack()",
        "planted.py:5: extract_stack()",
        "planted.py:6: funcName",
    ]


# --- G2 -----------------------------------------------------------------------

_HIT = (
    "import mutmut.mutation.trampoline\n"
    "from mutmut.__main__ import record_trampoline_hit\n"
    "record_trampoline_hit('product_app.x.x_f')\n"
    "print('HIT OK')\n"
)
_HIT_AFTER_CHDIR = (
    "import os, sys\n"
    "import mutmut.mutation.trampoline\n"
    "from mutmut.__main__ import record_trampoline_hit\n"
    "os.chdir(sys.argv[1])\n"
    "record_trampoline_hit('product_app.x.x_f')\n"
    "print('HIT OK')\n"
)


def _mutmut_child(script: str, folder: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """mutmut's trampoline import and one recorded hit, as a mutated src file
    does them, in a fresh isolated interpreter whose folder is ``folder``."""
    return subprocess.run(
        [sys.executable, "-I", "-c", script, *args],
        cwd=folder,
        env=env_without_coverage({"PATH": "/usr/bin:/bin"}),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_g2a_mutmut_cannot_start_in_a_folder_without_src(tmp_path: Path) -> None:
    """mutmut's import fails in a bare folder and works once ``src`` exists
    (the folder is made by hand here, not by the helper).

    Red when: a mutmut upgrade stops failing at import in a folder with no
    ``src`` (then G1a guards a hazard that is gone), or the child cannot run
    mutmut at all (the hand-made partner fails)."""
    bare = tmp_path / "bare"
    bare.mkdir()
    done = _mutmut_child(_HIT, bare)
    assert done.returncode != 0, done
    assert "Could not figure out where the code to mutate is" in done.stderr, done.stderr
    prepared = tmp_path / "prepared"
    (prepared / "src").mkdir(parents=True)
    done = _mutmut_child(_HIT, prepared)
    assert (done.returncode, done.stdout) == (0, "HIT OK\n"), done


def test_g2b_the_helper_makes_a_folder_mutmut_can_start_in(tmp_path: Path) -> None:
    """``mutmut_can_run_in(folder)`` returns ``folder``, may be called twice on
    it, leaves an EMPTY ``src`` there (nothing importable), and mutmut starts
    and records a hit from it.

    Red when: the helper stops making ``src`` (mutmut then fails at import),
    returns another folder, puts something in ``src``, or fails on a second
    call."""
    folder = tmp_path / "child"
    folder.mkdir()
    assert mutmut_can_run_in(folder) == folder
    done = _mutmut_child(_HIT, folder)
    assert (done.returncode, done.stdout) == (0, "HIT OK\n"), done
    assert mutmut_can_run_in(folder) == folder
    assert list((folder / "src").iterdir()) == []


def test_g2c_mutmut_needs_src_again_at_every_hit(tmp_path: Path) -> None:
    """Imported in a prepared folder, mutmut still resolves the RELATIVE
    ``src`` at each recorded hit, so a later ``chdir`` to a bare folder fails
    with ``FileNotFoundError: 'src'``; staying in the prepared folder works.

    Red when: a mutmut upgrade resolves ``source_paths`` once, absolutely (then
    G1a's in-process ``chdir`` rule guards a hazard that is gone), or the
    prepared-folder partner fails."""
    prepared = tmp_path / "prepared"
    (prepared / "src").mkdir(parents=True)
    bare = tmp_path / "bare"
    bare.mkdir()
    done = _mutmut_child(_HIT_AFTER_CHDIR, prepared, str(bare))
    assert done.returncode != 0, done
    assert "FileNotFoundError: [Errno 2] No such file or directory: 'src'" in done.stderr, (
        done.stderr
    )
    done = _mutmut_child(_HIT_AFTER_CHDIR, prepared, str(prepared))
    assert (done.returncode, done.stdout) == (0, "HIT OK\n"), done


# --- G3 -----------------------------------------------------------------------


def _is_import_module_of_product_app(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and _call_name(node.func) == "import_module"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and _is_product_app(node.args[0].value)
    )


def _product_app_names(tree: ast.Module) -> set[str]:
    """Names this module binds to something imported from ``product_app``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_product_app(alias.name):
                    names.add(alias.asname or alias.name.split(".")[0])
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and _is_product_app(node.module or "")
        ):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _module_helpers(tree: ast.Module, names: set[str]) -> set[str]:
    """Same-file functions every ``return`` of which is a ``product_app`` module."""
    helpers: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        returns = [n.value for n in ast.walk(node) if isinstance(n, ast.Return)]
        if returns and all(
            r is not None and (_is_import_module_of_product_app(r) or _rooted_in(r, names))
            for r in returns
        ):
            helpers.add(node.name)
    return helpers


def _rooted_in(node: ast.expr, names: set[str]) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id in names


class _Taint:
    """Does an expression carry the file of a ``product_app`` module?"""

    def __init__(self, tree: ast.Module) -> None:
        self.names = _product_app_names(tree)
        self.helpers = _module_helpers(tree, self.names)
        self.scopes = _Scopes(tree)

    def is_module(self, node: ast.expr, seen: frozenset[str]) -> bool:
        if _rooted_in(node, self.names) or _is_import_module_of_product_app(node):
            return True
        if isinstance(node, ast.Call) and _call_name(node.func) in self.helpers:
            return True
        if isinstance(node, ast.Name) and node.id not in seen:
            return any(self.is_module(v, seen | {node.id}) for v in self.scopes.values(node))
        return False

    def carries_src_file(self, node: ast.expr, seen: frozenset[str] = frozenset()) -> bool:
        if isinstance(node, ast.Attribute):
            if node.attr == "__file__":
                return self.is_module(node.value, seen)
            return node.attr in _PATH_ATTRIBUTES and self.carries_src_file(node.value, seen)
        if isinstance(node, ast.Subscript):
            return self.carries_src_file(node.value, seen)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self.carries_src_file(node.left, seen)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _PATH_METHODS:
                return self.carries_src_file(func.value, seen)
            if _call_name(func) in _PATH_WRAPPERS and node.args:
                return self.carries_src_file(node.args[0], seen)
            return False
        if isinstance(node, ast.Name) and node.id not in seen:
            return any(self.carries_src_file(v, seen | {node.id}) for v in self.scopes.values(node))
        return False


def _g3_sites(module: str, tree: ast.Module) -> list[str]:
    taint = _Taint(tree)
    if not taint.names and not any(_is_import_module_of_product_app(n) for n in ast.walk(tree)):
        return []
    sites: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "parse"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ast"
            and node.args
            and taint.carries_src_file(node.args[0])
        ):
            sites.append(f"{module}:{node.lineno}: ast.parse({ast.unparse(node.args[0])})")
    return sorted(sites, key=lambda site: int(site.split(":")[1]))


def test_g3_no_test_parses_src_through_a_module_file() -> None:
    """No module mutmut runs passes to ``ast.parse`` the source of a
    ``product_app`` module reached through that module's ``__file__`` (tracked
    through simple assignments, path wrappers and read methods). Inside the
    copy that file is the MUTATED one. A substring read is not flagged: the
    original body survives in the mutated file, so it still passes.

    Red when: a test parses src source through a ``product_app`` module's
    ``__file__`` (on ``7f8cf00``: 7 sites)."""
    sites = [site for module, tree in _test_sources() for site in _g3_sites(module, tree)]
    assert sites == [], (
        "these tests parse src source through a product_app module's __file__; "
        "under mutmut that is the mutated file. Read the real one through "
        "tests.repo_root.find_repo_root(Path(__file__)) / 'src' / ...:\n" + "\n".join(sites)
    )


def test_g3_partner_a_planted_module_file_parse_is_flagged_and_the_real_file_is_not() -> None:
    """Red when: ``_g3_sites`` stops flagging any of the four planted shapes,
    or starts flagging the real-file read, a substring read, or a stdlib
    module's ``__file__``."""
    flagged = _parse(
        "import ast, importlib, pathlib\n"
        "from pathlib import Path\n"
        "from product_app import auth\n"
        "import product_app.providers as providers\n"
        "def _fs():\n"
        "    return importlib.import_module('product_app.fetch_site')\n"
        "def test_a():\n"
        "    ast.parse(Path(auth.__file__).read_text(encoding='utf-8'))\n"
        "def test_b():\n"
        "    source = pathlib.Path(providers.__file__).read_text()\n"
        "    tree = ast.parse(source)\n"
        "def test_c():\n"
        "    path = Path(_fs().__file__)\n"
        "    ast.parse(path.read_text())\n"
        "def test_d():\n"
        "    with open(Path(auth.__file__).parent / 'auth.py') as handle:\n"
        "        ast.parse(handle.read())\n"
    )
    assert [site.split(": ", 1)[0] for site in _g3_sites("planted.py", flagged)] == [
        "planted.py:8",
        "planted.py:11",
        "planted.py:14",
        "planted.py:17",
    ]
    safe = _parse(
        "import ast, json\n"
        "from pathlib import Path\n"
        "from product_app import auth\n"
        "from tests.repo_root import find_repo_root\n"
        "def test_a():\n"
        "    real = find_repo_root(Path(__file__)) / 'src' / 'product_app' / 'auth.py'\n"
        "    ast.parse(real.read_text())\n"
        "def test_b():\n"
        "    assert '_gc_loop' in Path(auth.__file__).read_text()\n"
        "def test_c():\n"
        "    ast.parse(Path(json.__file__).read_text())\n"
    )
    assert _g3_sites("planted.py", safe) == []


# --- The run deadline fits inside the job limit -------------------------------


def _makefile_deadline_seconds() -> int:
    """``MUTATION_RUN_DEADLINE_SECONDS ?= N`` from the Makefile, exactly once."""
    values = [
        line.split("?=", 1)[1].strip()
        for line in (REPO_ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
        if line.split("?=", 1)[0].strip() == "MUTATION_RUN_DEADLINE_SECONDS" and "?=" in line
    ]
    assert len(values) == 1, values
    return int(values[0])


def _mutation_job_timeout_minutes() -> int:
    """The ``mutation-baseline`` job's ``timeout-minutes`` in ci.yml, read by YAML."""
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    minutes = workflow["jobs"]["mutation-baseline"]["timeout-minutes"]
    assert isinstance(minutes, int), minutes
    return minutes


def _kill_wait_seconds() -> list[int]:
    """Each ``*.wait(timeout=<number>)`` in scripts/run_with_deadline.py: the
    bounded waits after SIGTERM and after SIGKILL. The deadline's own wait,
    ``wait(timeout=deadline_seconds)``, is a name, not a number, so it is not
    counted."""
    tree = _parse((REPO_ROOT / "scripts" / "run_with_deadline.py").read_text(encoding="utf-8"))
    return [
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "wait"
        for keyword in node.keywords
        if keyword.arg == "timeout"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, int)
    ]


def test_the_mutation_run_deadline_ends_before_the_job_limit() -> None:
    """``make mutation-baseline`` ends ``mutmut run`` at its own deadline so the
    report step still prints a score (#182). The Makefile's comment states the
    budget: the 50-minute job leaves 600 s after the 2400 s deadline, and 580 s
    after the deadline script's two kill waits, for checkout, setup and the
    report.

    Red when: the deadline or the job limit moves from 2400 s / 50 minutes, or
    a kill wait changes, without this test and that comment being updated."""
    deadline = _makefile_deadline_seconds()
    job_minutes = _mutation_job_timeout_minutes()
    kill_waits = _kill_wait_seconds()
    assert deadline == 2400
    assert job_minutes == 50
    assert len(kill_waits) == 2, kill_waits
    assert job_minutes * 60 - deadline - sum(kill_waits) == 580, (
        deadline,
        kill_waits,
        job_minutes,
    )
