"""#368: a test's child process must not measure a source tree nobody changed.

`pyproject.toml:125` is `addopts = "--cov=src ..."`. That `src` is a RELATIVE
path, and there is no `[tool.coverage]` section pinning a source. pytest-cov
exports the string verbatim to every child, through a `.pth` file that runs at
interpreter start-up. Measured on this tree, from inside a run of this suite::

    VAL COV_CORE_CONFIG=':'
    VAL COV_CORE_DATAFILE='/Users/.../quorum-ai/.coverage'
    VAL COV_CORE_SOURCE='src'

A child launched with a `cwd` outside the repository resolves `src` against
ITS OWN working directory. `coverage`'s `find_possibly_unexecuted_files()`
then walks that directory at save time and records every importable `.py`
file under it at 0%; the child writes its data beside the ABSOLUTE
`COV_CORE_DATAFILE`, and the parent combines it. The parent's statement TOTAL
grows by a tree nobody changed, and `--cov-fail-under=88` — a REQUIRED status
check — fails for a reason unrelated to the diff.

Measured on this repository, both directions, 2026-08-25::

    $ .venv/bin/python -m pytest \
        tests/unit/test_stance_majority_flags_has_no_equivalent_mutants.py \
        --cov=src --cov-report=term -q
    TOTAL   5847  3963  32%

    $ .venv/bin/python -m pytest \
        tests/unit/test_replay_scope_matches_makefile_scope.py \
        --cov=src --cov-report=term -q
    TOTAL  10426  8551  18%

FOUR CONDITIONS, not three. The leak needs (1) a CPython child — a `git`,
`make`, `node` or `/bin/sh` child never loads the `.pth`; (2) `COV_CORE_*`
surviving into its environment; (3) a `cwd` outside the repository; and (4) an
IMPORTABLE package under `<cwd>/src` — `coverage`'s `find_python_files()` only
descends into directories holding an `__init__.py`. Condition (4) is why four
of the five call sites this module was written against cost **zero** statements
today while being every bit as armed as the fifth. Measured, same tree, same
command, adding an `__init__.py` to the probe tree's package the only
change between the two runs::

    == WITHOUT __init__.py ==   child recorded 0 files
    == WITH    __init__.py ==   child recorded 2 files -- the package's own
                                `__init__.py` and its one module

That measurement is the reason the statement-TOTAL test below plants an
`__init__.py` in its probe tree. A probe tree without one passes for EVERY
implementation, including one that strips nothing — the exact vacuity trap
AGENTS.md warns about.

WHAT THIS MODULE FORBIDS. A subprocess call under `tests/` that launches a
Python interpreter with a `cwd=` this scan cannot prove is the repository
root, and hands it an environment this scan cannot prove is free of the
coverage variables. The safe form is `tests.subprocess_env.env_without_coverage`.

WHAT IT DELIBERATELY DOES NOT FORBID, and why — each of these was measured on
this tree, and flagging them would have made the suite WORSE, not safer:

* **A call with no `cwd=` at all.** The child inherits the parent's working
  directory, which is the repository root in every lane that measures
  coverage: no Makefile recipe `cd`s, and no workflow sets `working-directory`
  for a pytest step. Under `mutmut run` the inherited cwd IS the `./mutants/`
  copy — but `pyproject.toml`'s `[tool.mutmut]` passes `--no-cov`, so no
  coverage is running there to leak into.
* **A `cwd` that is the literal `"."`.** Same reasoning, written explicitly.
* **A `cwd` derived from `__file__` or `find_repo_root`, anywhere in the
  module** — including inside a function body. `ast.walk` is used for that on
  purpose. `tests/unit/test_telemetry_sink.py:780` binds
  `repo_root = Path(__file__).resolve().parents[2]` INSIDE a function and runs
  a child there with `PYTHONPATH=<real src>`; that child imports the REAL
  `product_app.telemetry_sink` and its measured lines are GENUINE coverage.
  A module-level-only reader would have called it an offender, and "fixing"
  it by stripping the environment would have DELETED real coverage to make a
  gate green — precisely what rule 14 forbids.
  `tests/unit/test_logging_config_sentry_redaction.py:677` is the same shape
  behind a `cwd="."`.

KNOWN AND UNCLOSED. The recognition layer is an ENUMERATION of spellings, not
a catch-all. An adversarial review built fifteen evasions against an earlier
form of this module and thirteen of them leaked; the ones below are what
survived hardening. Each was fed to `_python_children_at_an_unproven_cwd` on
2026-08-25 and came back with NO offender — that is a measurement of the
limit, not a guess at it:

1. A runner bound INDIRECTLY: `runner = subprocess.run`, then
   `runner([...], cwd=copy)`. The name is not an import alias, so nothing ties
   it back to `subprocess`.
2. A star import: `from subprocess import *`, then `run([...], cwd=copy)`.
   `ast` records the imported name as `*`.
3. A wrapper living in ANOTHER module — `helpers.run_python(argv, cwd=copy)`.
   This scan reads one file's AST and does not follow calls across files, so
   NEITHER side is an offender: the wrapper's argv is a parameter, and the
   caller's function is not a recognised runner. Not closable by a per-file
   AST scan.
4. A Python child started WITHOUT `subprocess` — `multiprocessing` with the
   `spawn` context. The spawned interpreter loads the `.pth` hook and leaks
   exactly like a `subprocess` child. Nothing under `tests/` spawns one today.
5. An interpreter path this reader cannot resolve — read from a dict, or
   returned by a helper in another file. A name bound to `sys.executable`, a
   bare `from sys import executable`, an argv bound to a name, and
   `[sys.executable] + args` are all resolved and are NOT limits any more.

Limits 1-3 are inherited verbatim from
`tests/unit/test_mutation_gate_root_resolution.py::_cwd_scoped_git_calls`,
which recognises calls the same way; 4 and 5 are this module's own.

WHAT TURNS EACH TEST RED is stated on the test.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest
from tests.repo_root import find_repo_root
from tests.subprocess_env import env_without_coverage

# This module parses and executes against the REAL repository and shells out to
# a nested pytest run. It kills no mutant of `src/` and cannot: it imports
# nothing from the application.
pytestmark = pytest.mark.repo_introspection

REPO_ROOT = find_repo_root(Path(__file__))
TESTS_DIR = REPO_ROOT / "tests"

_SUBPROCESS_CALLS = frozenset({"run", "check_output", "check_call", "Popen", "call"})

#: The one spelling that proves an environment has been cleaned, and the ONLY
#: module it may be imported from — the name on its own proves nothing.
HELPER_NAME = "env_without_coverage"
HELPER_MODULE = "tests.subprocess_env"

#: `cwd` values that name the process's own working directory, which is the
#: repository root in every lane that measures coverage (see the module
#: docstring).
_SELF_CWD_LITERALS = frozenset({".", "./", ""})


# --------------------------------------------------------------------------
# Recognition — which calls are subprocess calls, and what do they launch
# --------------------------------------------------------------------------


def _repo_root_names(tree: ast.Module) -> frozenset[str]:
    """Names bound anywhere in the module to a repository-root path.

    `ast.walk` rather than a scan of `tree.body`, so a root bound INSIDE a
    function counts — `tests/unit/test_telemetry_sink.py:780` binds
    `repo_root = Path(__file__).resolve().parents[2]` in a function body and
    runs a child there that measures the REAL `src/`.

    A name is proven only if EVERY binding of it in the module is
    root-derived. A name bound once from `__file__` and later reassigned —

        root = Path(__file__).resolve().parents[2]
        ...
        root = tmp_path                 # now a throwaway directory
        subprocess.run([sys.executable, ...], cwd=root)

    — is NOT proven, because the value reaching the call is the reassigned
    one. `ast.walk` ignores scope and order, so it cannot tell which binding
    reaches the call; the only sound answer available to it is to refuse the
    name outright (ADR-0047). Measured on this tree: no module loses its
    exemption to this rule, so it costs nothing today and closes the shape
    before it appears.
    """
    root_derived: set[str] = set()
    other: set[str] = set()

    def record(target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                record(element, value)
            return
        if not isinstance(target, ast.Name):
            return
        source = ast.unparse(value)
        if "find_repo_root" in source or "__file__" in source:
            root_derived.add(target.id)
            return
        # A rebinding DERIVED FROM THE NAME ITSELF — `root = root.resolve()`,
        # `repo = repo / "build"` — still names a path inside the repository,
        # so it must not withdraw the exemption. Without this, adding a
        # `.resolve()` to `tests/unit/test_telemetry_sink.py`'s `repo_root`
        # would have turned a call that measures the REAL `src/` into an
        # offender, and the only way to make the gate green would have been to
        # strip its environment — deleting 282 real statements of coverage.
        if target.id in {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}:
            return
        other.add(target.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record(target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            record(node.target, node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            record(node.target, node.iter)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            record(node.optional_vars, node.context_expr)
    return frozenset(root_derived - other)


def _subprocess_aliases(tree: ast.Module) -> frozenset[str]:
    """Bare names bound to a runner by `from subprocess import run [as ...]`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in _SUBPROCESS_CALLS:
                    names.add(alias.asname or alias.name)
    return frozenset(names)


def _subprocess_module_names(tree: ast.Module) -> frozenset[str]:
    """Names bound to the `subprocess` MODULE, including `import subprocess as sp`."""
    names = {"subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    names.add(alias.asname or alias.name)
    return frozenset(names)


def _interpreter_names(tree: ast.Module) -> frozenset[str]:
    """Names bound anywhere in the module to a Python interpreter path.

    `PYTHON = sys.executable` at module level, then
    `subprocess.run([PYTHON, ...], cwd=copy)`, is the single most likely
    accidental spelling an adversarial review found, and a reader that looked
    only at literals in the argv did not see it. `from sys import executable`
    binds the bare name, so that spelling is recorded too.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "sys":
            for alias in node.names:
                if alias.name == "executable":
                    names.add(alias.asname or alias.name)
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and value is not None
            and _names_an_interpreter(ast.unparse(value))
        ):
            names.add(target.id)
    return frozenset(names)


def _names_an_interpreter(text: str) -> bool:
    """Whether a snippet of source names a Python interpreter."""
    if "sys.executable" in text:
        return True
    return any(
        word in text
        for word in ('"pytest"', "'pytest'", "shutil.which('python", 'shutil.which("python')
    )


def _launches_a_python_interpreter(argv: ast.expr, interpreters: frozenset[str]) -> bool:
    """Whether this argv starts a CPython process.

    Only a Python child loads pytest-cov's `.pth` hook, so a `git`, `make`,
    `node` or `/bin/sh` child cannot leak and must not be flagged. `uv run`
    is included because it execs an interpreter.

    Reads three shapes: a `List`/`Tuple` literal (the common one); a `BinOp`
    concatenation such as `[sys.executable] + args`, whose operands are read
    recursively; and any expression naming a module-level interpreter binding
    from `_interpreter_names`. A `JoinedStr` command for `shell=True` is read
    through its unparse.

    STILL NOT SEEN — an interpreter path computed at runtime from a value this
    module cannot resolve, e.g. read out of a dict or returned by a helper in
    another file. That is the same per-file boundary recorded under KNOWN AND
    UNCLOSED in the module docstring.
    """
    if isinstance(argv, ast.BinOp):
        return _launches_a_python_interpreter(
            argv.left, interpreters
        ) or _launches_a_python_interpreter(argv.right, interpreters)
    if isinstance(argv, ast.Name):
        return argv.id in interpreters
    if isinstance(argv, (ast.JoinedStr, ast.Constant)):
        return _names_an_interpreter(ast.unparse(argv))
    if not isinstance(argv, (ast.List, ast.Tuple)):
        # An expression this reader cannot decompose. Fail closed if anything
        # inside it names an interpreter (ADR-0047).
        text = ast.unparse(argv)
        return _names_an_interpreter(text) or any(
            name in {node.id for node in ast.walk(argv) if isinstance(node, ast.Name)}
            for name in interpreters
        )
    for element in argv.elts:
        if _names_an_interpreter(ast.unparse(element)):
            return True
        if isinstance(element, ast.Name) and element.id in interpreters:
            return True
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            basename = element.value.rsplit("/", 1)[-1]
            if basename in ("pytest", "uv") or basename.startswith("python"):
                return True
    return False


def _cwd_is_proven_repo_root(
    cwd: ast.expr | None, roots: frozenset[str], *, module_chdirs: bool
) -> bool:
    """Whether the call's `cwd` is provably the repository root.

    Fails CLOSED on an expression it cannot decide (ADR-0047): an unrecognised
    `cwd` is treated as NOT proven, which sends the call on to the environment
    check rather than exempting it.

    A MISSING `cwd=` is normally proven, because the child inherits the
    parent's working directory and that is the repository root in every lane
    that measures coverage. `module_chdirs` withdraws that: a module that
    calls `chdir` anywhere may have moved the process out of the repository
    before the call, so an inherited cwd is no longer known. Twelve
    `monkeypatch.chdir` calls already exist under `tests/`, so this is a live
    shape rather than a hypothetical one — an adversarial review demonstrated
    it leaking with no `cwd=` argument at all.
    """
    if cwd is None:
        return not module_chdirs
    if isinstance(cwd, ast.Constant) and cwd.value in _SELF_CWD_LITERALS:
        return not module_chdirs
    if ast.unparse(cwd).rstrip("()") in ("os.getcwd", "Path.cwd", "pathlib.Path.cwd"):
        # The same statement as `cwd="."`, spelled as a call.
        return not module_chdirs
    # Names used as the FUNCTION of a call (`str(ROOT)`, `Path(ROOT)`) are
    # spelling, not data, and do not make the expression ambiguous.
    callees = {ast.unparse(node.func) for node in ast.walk(cwd) if isinstance(node, ast.Call)}
    named = {
        node.id for node in ast.walk(cwd) if isinstance(node, ast.Name) and node.id not in callees
    }
    if not named & roots:
        return False
    # `cwd=tmp_path / ROOT.name` NAMES a root but is not one. An expression
    # that mixes a root with any other binding is ambiguous, and ADR-0047
    # resolves ambiguity toward RED. `repo / "build"` names only `repo` and
    # stays proven.
    return not (named - roots)


def _module_calls_chdir(tree: ast.Module) -> bool:
    """Whether anything in the module changes the process working directory."""
    return any(
        isinstance(node, ast.Call) and ast.unparse(node.func).rpartition(".")[2] == "chdir"
        for node in ast.walk(tree)
    )


def _environ_names(tree: ast.Module) -> frozenset[str]:
    """Names bound anywhere in the module to the process environment.

    `PARENT_ENV = os.environ` then `env={**PARENT_ENV, ...}`, and
    `from os import environ as base` then a comprehension over `base`, both
    defeat a reader that only looks for the text `environ` at the call site.
    An adversarial review demonstrated both leaking.
    """
    names = {"environ"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name == "environ":
                    names.add(alias.asname or alias.name)
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and value is not None:
            referenced = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
            if referenced & names or "os.environ" in ast.unparse(value):
                names.add(target.id)
    return frozenset(names)


def _imports_the_real_helper(tree: ast.Module) -> bool:
    """Whether `env_without_coverage` in this module is THIS repository's.

    The name alone is not proof. `from somewhere_else import
    env_without_coverage` would satisfy a reader that only matched the
    spelling, and the call would strip nothing. The import must name
    `tests.subprocess_env`.
    """
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == HELPER_MODULE
        and any(alias.name == HELPER_NAME for alias in node.names)
        for node in ast.walk(tree)
    )


def _env_is_proven_clean(
    env: ast.expr | None, environs: frozenset[str], *, real_helper: bool
) -> bool:
    """Whether the call's `env=` is provably free of the coverage variables.

    Two shapes are accepted, both STRUCTURAL rather than textual:

    * a call to `env_without_coverage` — the one home of the strip; and
    * a dict literal or comprehension that never mentions `environ`, i.e. an
      environment assembled from scratch.

    Everything else — no `env=` at all, `{**os.environ, ...}`, or a name bound
    to a dict built earlier from `os.environ` — is NOT proven. That last shape
    is not hypothetical: `tests/unit/test_session_hygiene.py:154` writes
    `env = dict(os.environ)` and passes the NAME, which a reader that only
    looked for the text `os.environ` at the call site would have cleared.
    """
    if env is None:
        return False
    if isinstance(env, ast.Call):
        return real_helper and ast.unparse(env.func).rpartition(".")[2] == HELPER_NAME
    if isinstance(env, (ast.Dict, ast.DictComp)):
        # STRUCTURAL, not textual: a key or comment containing the letters
        # "environ" must not make a scratch environment look dirty, and an
        # alias for `os.environ` must not make a dirty one look clean.
        if any(
            isinstance(node, ast.Attribute) and node.attr == "environ" for node in ast.walk(env)
        ):
            return False
        referenced = {node.id for node in ast.walk(env) if isinstance(node, ast.Name)}
        return not (referenced & environs)
    return False


def _python_children_at_an_unproven_cwd(tree: ast.Module) -> list[tuple[int, bool]]:
    """Every Python child launched at a cwd not proven to be the repo root.

    Returns `(lineno, env_is_proven_clean)` per call, so a caller can use the
    same list both as the population floor and as the offender filter — a
    scan that recognised nothing would then fail the floor rather than pass
    the gate.
    """
    roots = _repo_root_names(tree)
    aliases = _subprocess_aliases(tree)
    modules = _subprocess_module_names(tree)
    interpreters = _interpreter_names(tree)
    environs = _environ_names(tree)
    module_chdirs = _module_calls_chdir(tree)
    real_helper = _imports_the_real_helper(tree)
    found: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        prefix, _, attribute = func.rpartition(".")
        qualified = (
            prefix in modules or func.startswith("subprocess.")
        ) and attribute in _SUBPROCESS_CALLS
        if not (qualified or func in aliases):
            continue
        # `subprocess.Popen(args=[...])` passes argv as a KEYWORD. Reading only
        # `node.args[0]` skipped such a call entirely — demonstrated leaking.
        argv: ast.expr | None = node.args[0] if node.args else None
        if argv is None:
            argv = next((kw.value for kw in node.keywords if kw.arg == "args"), None)
        if argv is None or not _launches_a_python_interpreter(argv, interpreters):
            continue
        cwd = next((kw.value for kw in node.keywords if kw.arg == "cwd"), None)
        if _cwd_is_proven_repo_root(cwd, roots, module_chdirs=module_chdirs):
            continue
        env = next((kw.value for kw in node.keywords if kw.arg == "env"), None)
        found.append((node.lineno, _env_is_proven_clean(env, environs, real_helper=real_helper)))
    return found


def _count_recognised_subprocess_calls(tree: ast.Module) -> int:
    """How many subprocess calls of ANY kind this module recognised.

    The population the offender check is a subset of. Counted separately so a
    recognition layer that stopped matching a spelling shows up as a floor
    failure with a number, not as a silently clean gate.
    """
    aliases = _subprocess_aliases(tree)
    modules = _subprocess_module_names(tree)
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        prefix, _, attribute = func.rpartition(".")
        qualified = (
            prefix in modules or func.startswith("subprocess.")
        ) and attribute in _SUBPROCESS_CALLS
        if qualified or func in aliases:
            total += 1
    return total


def _scan_sources(
    sources: Iterable[tuple[str, str]],
) -> tuple[int, int, dict[str, list[int]], dict[str, list[int]]]:
    """`(files, subprocess calls, python-children-at-an-unproven-cwd, offenders)`.

    Takes `(name, source)` pairs rather than reading the tree itself, so the
    AGGREGATION — including the branch that promotes a reached call into an
    offender — can be driven from planted source by
    `test_the_aggregation_promotes_a_dirty_call_into_the_offender_set`.

    An adversarial review deleted exactly that branch and every test in this
    module still passed: the classifier table calls
    `_python_children_at_an_unproven_cwd` directly, the floors and the
    positive partner read only `at_unproven_cwd`, and the statement-TOTAL test
    never touches the scan. Nothing exercised the promotion. That is why this
    function takes its input instead of fetching it.
    """
    files = 0
    calls = 0
    at_unproven_cwd: dict[str, list[int]] = {}
    offenders: dict[str, list[int]] = {}
    for name, source in sources:
        files += 1
        tree = ast.parse(source)
        calls += _count_recognised_subprocess_calls(tree)
        for lineno, clean in _python_children_at_an_unproven_cwd(tree):
            at_unproven_cwd.setdefault(name, []).append(lineno)
            if not clean:
                offenders.setdefault(name, []).append(lineno)
    return files, calls, at_unproven_cwd, offenders


def _test_suite_sources() -> Iterator[tuple[str, str]]:
    for path in sorted(TESTS_DIR.rglob("*.py")):
        yield str(path.relative_to(REPO_ROOT)), path.read_text(encoding="utf-8")


def _scan_test_suite() -> tuple[int, int, dict[str, list[int]], dict[str, list[int]]]:
    """`_scan_sources` over the real `tests/` tree."""
    return _scan_sources(_test_suite_sources())


# --------------------------------------------------------------------------
# Floors and positive partners
# --------------------------------------------------------------------------


def test_the_scan_measures_a_non_empty_population() -> None:
    """The gate below is a negative check, which is trivially true over nothing.

    The three floors sit below the figures measured on this tree on 2026-08-25
    — 271 files, 92 recognised subprocess calls, 8 Python children at a cwd not
    proven to be the repository root, printed by
    `_scan_test_suite()` — so ordinary growth does not trip them while a
    recognition layer that stopped seeing a spelling does. The third floor has
    the least headroom of the three because its population is genuinely small;
    it is set at 6 against a measured 8 so that removing one such call site
    does not fail this test spuriously.
    Written as literals on both sides: no floor is compared against the
    constant that produces it (rule 7a).

    Turns red if: the sweep stops walking `tests/`, `_count_recognised_subprocess_calls`
    stops matching a runner spelling, or `_launches_a_python_interpreter` stops
    recognising `sys.executable`.
    """
    files, calls, at_unproven_cwd, _offenders = _scan_test_suite()
    reached = sum(len(lines) for lines in at_unproven_cwd.values())

    assert files >= 250, f"only parsed {files} files under {TESTS_DIR}"
    assert calls >= 80, (
        f"the scan recognised {calls} subprocess calls under {TESTS_DIR}; "
        "the recognition layer has stopped matching a spelling it used to see"
    )
    assert reached >= 6, (
        f"the scan reached only {reached} Python child(ren) at a cwd it could "
        "not prove is the repository root, across "
        f"{len(at_unproven_cwd)} module(s) — the offender check below is a "
        "subset of that set, so a scan this small makes it near-vacuous"
    )


def test_the_discovery_finds_the_call_sites_that_are_known_to_strip_coverage() -> None:
    """Positive partner for the gate: name two modules the scan MUST reach.

    Both copy the real `src/` — `__init__.py` and all — into a temporary tree
    and run a Python child there, and both already strip the coverage
    environment. They are the shape the gate exists to police, so a scan that
    stopped reaching them would make the gate pass by seeing nothing. The
    assertion is that the scan SEES them, not that they are the only ones.

    Turns red if: the sweep stops finding these modules, or the recognition
    layer stops classifying `subprocess.run([sys.executable, ...], cwd=<copy>)`
    as a Python child at an unproven cwd.
    """
    _files, _calls, at_unproven_cwd, _offenders = _scan_test_suite()
    assert "tests/unit/test_mutation_copy_completeness.py" in at_unproven_cwd, at_unproven_cwd
    assert "tests/unit/test_mutation_gate_root_resolution.py" in at_unproven_cwd, at_unproven_cwd


def test_no_python_child_at_an_unproven_cwd_inherits_the_coverage_environment() -> None:
    """The gate.

    Turns red if: any subprocess call under `tests/` launches a Python
    interpreter at a `cwd` this scan cannot prove is the repository root while
    handing it an environment it cannot prove is free of `COV_CORE_*` /
    `COVERAGE_*`. Verified by reverting `_makefile_globs`'s `env=` argument in
    `tests/unit/test_replay_scope_matches_makefile_scope.py`, which takes that
    file's isolated statement TOTAL from 5847 back to 10426.
    """
    _files, _calls, _reached, offenders = _scan_test_suite()
    assert not offenders, (
        "these calls start a Python interpreter in a directory this scan "
        "cannot prove is the repository root, and hand it an environment that "
        "may still carry pytest-cov's subprocess hooks. The child resolves the "
        "RELATIVE `--cov=src` against its own working directory, records that "
        "tree's `src/` at 0%, and the parent combines it — inflating the "
        "statement denominator of a REQUIRED gate with a tree nobody changed "
        "(#368). Pass `env=tests.subprocess_env.env_without_coverage(...)`, or "
        "give the call a `cwd` derived from `find_repo_root`/`__file__` if it "
        "is genuinely meant to measure this repository's own source: "
        f"{offenders}"
    )


def test_the_aggregation_promotes_a_dirty_call_into_the_offender_set() -> None:
    """The offender branch of `_scan_sources` itself, driven from planted source.

    Every other test in this module reaches the classifier directly or reads
    only `at_unproven_cwd`. An adversarial review deleted the two lines that
    promote a dirty call into `offenders` and all tests stayed green — the gate
    below then had an empty dict to assert on and passed over a planted,
    blatant offender. This test is the partner that removal now has to survive.

    Turns red if: `_scan_sources` stops promoting a reached-but-dirty call into
    `offenders`, stops counting files, or starts reporting a clean call as an
    offender.
    """
    dirty = 'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path)\n'
    clean = (
        "from tests.subprocess_env import env_without_coverage\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path,\n'
        "               env=env_without_coverage())\n"
    )
    files, _calls, reached, offenders = _scan_sources(
        [("planted/dirty.py", dirty), ("planted/clean.py", clean)]
    )

    assert files == 2, files
    # Both calls are REACHED — same cwd, same argv. They differ only in `env=`,
    # so a classifier that stopped reading `env=` would fail this pair rather
    # than pass it.
    assert reached == {"planted/dirty.py": [1], "planted/clean.py": [2]}, reached
    assert offenders == {"planted/dirty.py": [1]}, offenders


# --------------------------------------------------------------------------
# Guard-of-the-guard: shapes the classifier must not drop
# --------------------------------------------------------------------------

# Fed to the classifier as text, never imported. Entries come in pairs that
# differ ONLY in the argument under test, so a classifier that stopped reading
# the shape at all fails the SAFE half rather than passing the offending one.
#
# This list is not a claim of totality — see KNOWN AND UNCLOSED in the module
# docstring.
_CLASSIFIER_CASES: tuple[tuple[str, bool, str], ...] = (
    (
        "no env= at all, cwd a throwaway directory",
        True,
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path)\n',
    ),
    (
        "the helper, cwd a throwaway directory",
        False,
        "from tests.subprocess_env import env_without_coverage\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path,\n'
        "               env=env_without_coverage())\n",
    ),
    (
        "os.environ splatted into a dict literal",
        True,
        'subprocess.run([sys.executable, "-c", "pass"], cwd=copy,\n'
        '               env={**os.environ, "PYTHONPATH": str(copy)})\n',
    ),
    (
        "the helper with an override, same call",
        False,
        "from tests.subprocess_env import env_without_coverage\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=copy,\n'
        "               env=env_without_coverage(PYTHONPATH=str(copy)))\n",
    ),
    (
        "a name bound earlier from os.environ",
        True,
        "env = dict(os.environ)\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=repo, env=env)\n',
    ),
    (
        "an environment assembled from scratch",
        False,
        'subprocess.run([sys.executable, "-c", "pass"], cwd=repo,\n'
        '               env={"PATH": "/usr/bin:/bin"})\n',
    ),
    (
        "a dict comprehension that filters os.environ by hand",
        True,
        'subprocess.run([sys.executable, "-c", "pass"], cwd=repo,\n'
        "               env={k: v for k, v in os.environ.items()\n"
        '                    if not k.startswith(("COV_CORE", "COVERAGE"))})\n',
    ),
    (
        "runner reached through a module alias",
        True,
        'import subprocess as sp\nsp.run([sys.executable, "-c", "pass"], cwd=tmp_path)\n',
    ),
    (
        "runner imported bare from subprocess under a new name",
        True,
        "from subprocess import run as launch\n"
        'launch([sys.executable, "-c", "pass"], cwd=tmp_path)\n',
    ),
    (
        "Popen, not run",
        True,
        'subprocess.Popen([sys.executable, "-c", "pass"], cwd=tmp_path)\n',
    ),
    (
        "a shell child, which never loads the .pth hook",
        False,
        'subprocess.run(["/bin/sh", "-c", "echo hi"], cwd=tmp_path)\n',
    ),
    (
        "a git child, which never loads the .pth hook",
        False,
        'subprocess.run(["git", "status"], cwd=tmp_path)\n',
    ),
    (
        "a python child with no cwd at all",
        False,
        'subprocess.run([sys.executable, "-c", "pass"])\n',
    ),
    (
        "a python child at a module-level root",
        False,
        "ROOT = find_repo_root(Path(__file__))\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=ROOT)\n',
    ),
    (
        "a python child at a root bound inside a function",
        False,
        "def test_thing():\n"
        "    root = Path(__file__).resolve().parents[2]\n"
        '    subprocess.run([sys.executable, "-c", "pass"], cwd=str(root))\n',
    ),
    (
        "a python child at the literal current directory",
        False,
        'subprocess.run([sys.executable, "-c", script], cwd=".")\n',
    ),
    (
        "a root name REASSIGNED to a throwaway directory before the call",
        True,
        "root = Path(__file__).resolve().parents[2]\n"
        "def test_thing(tmp_path):\n"
        "    root = tmp_path / 'copy'\n"
        '    subprocess.run([sys.executable, "-c", "pass"], cwd=root)\n',
    ),
    (
        "the interpreter bound to a module-level name",
        True,
        'PYTHON = sys.executable\nsubprocess.run([PYTHON, "-c", "pass"], cwd=tmp_path)\n',
    ),
    (
        "the whole argv bound to a name",
        True,
        'argv = [sys.executable, "-c", "pass"]\nsubprocess.run(argv, cwd=tmp_path)\n',
    ),
    (
        "argv built by list concatenation",
        True,
        "subprocess.run([sys.executable] + extra, cwd=tmp_path)\n",
    ),
    (
        "the interpreter imported bare from sys",
        True,
        'from sys import executable\nsubprocess.run([executable, "-c", "pass"], cwd=tmp_path)\n',
    ),
    (
        "Popen with argv passed as the args KEYWORD",
        True,
        'subprocess.Popen(args=[sys.executable, "-c", "pass"], cwd=tmp_path)\n',
    ),
    (
        "no cwd= at all, in a module that calls chdir",
        True,
        "def test_thing(monkeypatch, tmp_path):\n"
        "    monkeypatch.chdir(tmp_path)\n"
        '    subprocess.run([sys.executable, "-c", "pass"])\n',
    ),
    (
        "no cwd= at all, in a module that never calls chdir",
        False,
        'subprocess.run([sys.executable, "-c", "pass"])\n',
    ),
    (
        "os.environ reached through a module-level alias",
        True,
        "PARENT_ENV = os.environ\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path,\n'
        '               env={**PARENT_ENV, "MARKER": "1"})\n',
    ),
    (
        "os.environ imported under another name and comprehended",
        True,
        "from os import environ as base\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path,\n'
        "               env={k: v for k, v in base.items()})\n",
    ),
    (
        "the helper name imported from somewhere that is not the real module",
        True,
        "from evil import env_without_coverage\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path,\n'
        "               env=env_without_coverage())\n",
    ),
    (
        "the helper name imported from the real module",
        False,
        "from tests.subprocess_env import env_without_coverage\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path,\n'
        "               env=env_without_coverage())\n",
    ),
    (
        "a cwd that MENTIONS a root without being one",
        True,
        "ROOT = Path(__file__).resolve().parents[2]\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path / ROOT.name)\n',
    ),
    (
        "a cwd that is the root, wrapped in a call",
        False,
        "ROOT = find_repo_root(Path(__file__))\n"
        'subprocess.run([sys.executable, "-c", "pass"], cwd=str(ROOT))\n',
    ),
    (
        "a root REBOUND from itself, which still names the repository",
        False,
        "def test_thing():\n"
        "    repo_root = Path(__file__).resolve().parents[2]\n"
        "    repo_root = repo_root.resolve()\n"
        '    subprocess.run([sys.executable, "-c", probe], cwd=str(repo_root))\n',
    ),
    (
        "a root NARROWED to a subdirectory of itself",
        False,
        "repo = find_repo_root(Path(__file__))\n"
        "repo = repo / 'build'\n"
        'subprocess.run([sys.executable, "-c", probe], cwd=repo)\n',
    ),
    (
        "the current directory spelled as a call",
        False,
        'subprocess.run([sys.executable, "-c", script], cwd=os.getcwd())\n',
    ),
    (
        "a scratch environment whose KEY merely contains the letters environ",
        False,
        'subprocess.run([sys.executable, "-c", "pass"], cwd=tmp_path,\n'
        '               env={"PATH": "/usr/bin:/bin", "app_environment": "test"})\n',
    ),
)


@pytest.mark.parametrize(("shape", "is_offender", "source"), _CLASSIFIER_CASES)
def test_the_classifier_never_drops_a_leaking_subprocess_call(
    shape: str, is_offender: bool, source: str
) -> None:
    """Every shape LISTED HERE must be classified as this table says.

    This is the guard-of-the-guard, and it is only as wide as this list. Each
    expected value is written as a literal — the table is never parametrized
    over the classifier's own output (rule 7a).

    Turns red if: `_repo_root_names` stops reading a root bound inside a
    function, `_subprocess_module_names`/`_subprocess_aliases` stop resolving
    an alias, `_launches_a_python_interpreter` starts flagging a shell child,
    or `_env_is_proven_clean` starts clearing a name bound from `os.environ`.
    """
    tree = ast.parse(source)
    found = _python_children_at_an_unproven_cwd(tree)
    offenders = [lineno for lineno, clean in found if not clean]
    assert bool(offenders) is is_offender, f"{shape}: reached={found}"


# --------------------------------------------------------------------------
# The executable proof: the statement TOTAL itself
# --------------------------------------------------------------------------

#: Exactly three statements. The number is asserted as a literal on both sides
#: below rather than recomputed from this string, so a change to one without
#: the other goes red instead of agreeing with itself (rule 7a).
_PLANTED_MODULE = "ALPHA = 1\nBETA = 2\nGAMMA = 3\n"

_PLANTED_STATEMENTS = 3

_LEAK_PROBE = """\
import os
import subprocess
import sys

from tests.subprocess_env import env_without_coverage


def test_launch_a_child_at_the_planted_tree() -> None:
    tree = os.environ["LEAK_PROBE_TREE"]
    if os.environ["LEAK_PROBE_STRIP"] == "1":
        env = env_without_coverage()
    else:
        env = dict(os.environ)
    result = subprocess.run([sys.executable, "-c", "pass"], cwd=tree, env=env)
    assert result.returncode == 0
"""


def _statement_total(report: str) -> int:
    for line in report.splitlines():
        if line.startswith("TOTAL"):
            return int(line.split()[1])
    raise AssertionError(f"no TOTAL row in the nested run's coverage report:\n{report}")


def _nested_coverage_report(probe: Path, planted: Path, *, strip: bool, data: Path) -> str:
    """Run `probe` under `--cov=src` from the repository root and return the report.

    The nested run is itself launched with a stripped environment, so it can
    never be measured by the OUTER run this test belongs to — otherwise this
    test would move the very number it exists to police.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(probe),
            "--cov=src",
            "--cov-report=term",
            "--cov-fail-under=0",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env_without_coverage(
            COVERAGE_FILE=str(data),
            PYTHONPATH=str(REPO_ROOT),
            LEAK_PROBE_TREE=str(planted),
            LEAK_PROBE_STRIP="1" if strip else "0",
        ),
    )
    assert completed.returncode == 0, (
        f"the nested coverage run failed:\n{completed.stdout}\n{completed.stderr}"
    )
    return completed.stdout


def test_a_child_at_an_unproven_cwd_does_not_inflate_the_statement_total(
    tmp_path: Path,
) -> None:
    """The defect itself, measured, in both directions.

    Plants a three-statement importable package under `<tmp>/src`, runs the
    same nested `pytest --cov=src` twice — once handing the child an
    unfiltered environment, once using `env_without_coverage` — and compares
    the STATEMENT TOTALS. The total is the right subject: the percentage moves
    for legitimate reasons and the denominator does not.

    The unfiltered half is the POSITIVE PARTNER. If the leak ever stopped
    happening — a coverage release that resolves `source` differently, a pinned
    absolute source — this test goes red on that half rather than passing over
    a check that no longer checks anything.

    Turns red if: `env_without_coverage` stops removing `COV_CORE_*` (the two
    totals become equal, and the equality assertion fails), or the planted tree
    stops being importable (both totals become equal for the opposite reason,
    and the same assertion fails).
    """
    planted = tmp_path / "planted"
    (planted / "src" / "plantedpkg").mkdir(parents=True)
    (planted / "src" / "plantedpkg" / "__init__.py").write_text("", encoding="utf-8")
    (planted / "src" / "plantedpkg" / "mod.py").write_text(_PLANTED_MODULE, encoding="utf-8")

    probe = tmp_path / "test_leak_probe.py"
    probe.write_text(_LEAK_PROBE, encoding="utf-8")

    leaked = _nested_coverage_report(probe, planted, strip=False, data=tmp_path / "leaked.coverage")
    guarded = _nested_coverage_report(
        probe, planted, strip=True, data=tmp_path / "guarded.coverage"
    )

    leaked_total = _statement_total(leaked)
    guarded_total = _statement_total(guarded)

    # Floor: the guarded run must have measured this repository's own source.
    # A nested run that measured nothing would satisfy the difference below
    # with both totals at zero.
    assert guarded_total > 1000, (
        f"the guarded nested run reported {guarded_total} statements, which is "
        "not this repository's src/ — the comparison below would be vacuous"
    )

    # The planted package is `__init__.py` (0 statements) + a 3-statement
    # module. Both sides literal: neither is derived from the other.
    assert leaked_total - guarded_total == 3, (
        f"unfiltered child: {leaked_total} statements; stripped child: "
        f"{guarded_total}. The difference should be exactly the "
        f"{_PLANTED_STATEMENTS} statements of the planted package — a "
        "difference of 0 means the child never leaked and this test proves "
        "nothing; any other difference means the planted tree is not what "
        "this test thinks it is."
    )

    assert "plantedpkg" in leaked, (
        "the unfiltered nested run did not report the planted package at all, "
        f"so the positive partner did not fire:\n{leaked}"
    )
    assert "plantedpkg" not in guarded, (
        f"the stripped nested run still reported the planted package:\n{guarded}"
    )
