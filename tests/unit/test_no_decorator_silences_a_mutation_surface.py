"""A decorator may not take a function off the mutation surface unseen. Issue #369, ADR-0072.

#366 closed the `# pragma: no mutate` hatch (ADR-0069, decision 4). It left the
cheaper one open and said so: mutmut generates **no mutants at all** for a
decorated function. Measured on `synthesis_consensus.py` with mutmut 3.6.0's own
generator (`mutmut.mutation.file_mutation.mutate_file_contents`):

    file as-is            : 384 mutants, 11 for _stance_majority_flags
    + @functools.cache    : 373 mutants,  0
    + @property           : 373 mutants,  0
    + @staticmethod       : 384 mutants, 11   (mutmut special-cases this one)

One ordinary line, no suspicious keyword, and the pragma guard next door stays
green (5 passed with the decorator planted). The same skip covers every method
of a decorated class (each `@dataclass` here) and a decorated `def` nested
inside a plain one — the nested case deletes the inner body's mutants while the
enclosing function's count stays non-zero, so a "went to zero" check cannot
see it.

The decision (ADR-0072) is to make the effect VISIBLE, not to refuse decorators:
a decorator is ordinary Python and most of the population is FastAPI routes and
pydantic validators that cannot be written any other way. So this module keeps
a committed inventory, `mutation_surface_inventory.txt`, of every function
mutmut will not mutate for this reason, and compares it with the tree. Adding a
decorator (or a method to a `@dataclass`) then forces an inventory edit in the
same diff, where a reviewer sees "this function now has zero mutants" as a
second hunk in a file whose name says what happened.

GATE CHARTER
-----------
WHY THIS EXISTS: mutmut ships a one-line, comment-free way to remove a whole
function from the mutated population, the merge-blocking guard shipped for the
pragma route cannot see it by construction (it scans COMMENT tokens), and the
`[decorated]` note the Makefile's scope step writes to stderr is read by
nothing and only covers functions changed in a diff-scoped run.

WHAT IT CANNOT SEE: intent. It cannot tell a route that must be decorated from a
cache that was added to hide a survivor; it makes both visible and lets review
decide. It cannot see the OTHER way a function yields zero mutants — a body
with nothing any operator touches (#146, `no_mutable_content` in the Makefile)
— which no decorator causes. It cannot see anything outside `[tool.mutmut]`'s
`only_mutate` (e.g. `src/httpx2/`), which is correct: nothing there is mutated,
so nothing there can be silenced. It records a decorated NESTED def once and
does not look inside it further. And it mirrors mutmut's predicate by SPELLING,
exactly as mutmut does — `@cm` where `cm = classmethod` is skipped by mutmut
and is recorded here; `@(staticmethod)` is mutated by mutmut and is not — so do
not make the scanner "smarter" than the tool it mirrors.

FALSE-POSITIVE COST: one inventory line per decorated function added, renamed
or moved, or per method added to a decorated class. Measured population on
2026-08-25: 43 entries over 27 files, accumulated over the repository's whole
life, so the expected cost is well under one line per pull request. The
failure message prints the exact lines to add or remove, and running this
module as a script regenerates the file.

WHEN TO REMOVE: when mutmut mutates decorated functions.
`test_the_scanner_agrees_with_the_installed_mutmut` turns red on that day, and
then the inventory records nothing real and this whole module is dead weight.

Turns red if: a decorator that is not a lone bare `@staticmethod`/`@classmethod`
is added to, or removed from, any `def` under `only_mutate` without the same
change to `mutation_surface_inventory.txt`; a class under `only_mutate` gains or
loses a decorator; a method is added to or removed from a decorated class; or
the inventory names a function that no longer exists. Proven by mutation
(`cp` aside, mutate, restore from the copy, `diff -q`): planting
`@functools.cache` on `_stance_majority_flags` turned this module red naming
`product_app.synthesis_consensus:_stance_majority_flags` as NEW, and the
in-memory partner asserts the same detection on every run.
"""

from __future__ import annotations

import ast
import fnmatch
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

import pytest
from tests.repo_root import find_repo_root

#: The REAL tree, never mutmut's `./mutants/` copy: inside the copy every
#: mutated function carries a generated, DECORATED `x_<name>__mutmut_N` variant,
#: so a census of decorated functions there reads hundreds where the tree has
#: dozens (#158 is exactly this).
REPO_ROOT = find_repo_root(Path(__file__))

#: One `module:qualname` per line; `#` comments and blank lines are ignored.
#: Lives next to this module so the copy mutmut makes carries it unchanged.
INVENTORY = Path(__file__).with_name("mutation_surface_inventory.txt")

#: Run with `-m` from the repository root; as a bare script `tests` is not importable.
REGENERATE_MODULE = "tests.unit.test_no_decorator_silences_a_mutation_surface"

#: mutmut's one exception (`mutmut/mutation/file_mutation.py`, the
#: `_skip_node_and_children` decorator branch): exactly ONE decorator, spelled
#: as a bare name, and that name is one of these two. Anything else — stacked,
#: dotted, called, aliased, parenthesised — is skipped with its whole subtree.
MUTMUT_TOLERATED_DECORATORS = ("staticmethod", "classmethod")

INVENTORY_HEADER = """\
# Functions mutmut 3.x will NOT mutate because of a decorator, ADR-0072.
#
# One `module:qualname` per line. This file is a RECORD, not a permission list:
# `tests/unit/test_no_decorator_silences_a_mutation_surface.py` scans every
# file [tool.mutmut] mutates and fails if the tree and this file disagree in
# EITHER direction. A function is listed when it carries any decorator other
# than a lone bare @staticmethod/@classmethod, when it is a method of a
# decorated class (every @dataclass), or when it is a decorated def nested in a
# plain function. Adding a decorator therefore shows up in review as an edit
# here — that visibility is the whole point (#369). If your decorator is
# legitimate, add the line; if you are decorating to make a survivor go away,
# write the test instead.
#
# Regenerate: ./.venv/bin/python -m tests.unit.test_no_decorator_silences_a_mutation_surface
"""


def _skipped_by_decorators(decorators: list[ast.expr]) -> bool:
    """True when mutmut skips a `def` carrying exactly these decorators.

    Mirrors the installed mutmut by SPELLING, deliberately. mutmut checks the
    decorator's syntax, not what the name is bound to.
    """
    if not decorators:
        return False
    if len(decorators) == 1:
        only = decorators[0]
        if isinstance(only, ast.Name) and only.id in MUTMUT_TOLERATED_DECORATORS:
            return False
    return True


def unmutatable_functions(source: str) -> dict[str, str]:
    """`qualname -> reason` for every function in `source` mutmut will not mutate.

    Walks classes (a decorated class freezes its whole subtree) and the bodies
    of plain functions (a decorated nested def loses its own body's mutants).
    A function that is recorded is NOT walked further: its whole subtree is
    already gone, and one entry says so.

    Raises on unparseable source rather than returning an empty census, because
    an empty census passes the gate and a syntax error must not.
    """
    found: dict[str, str] = {}

    def walk(node: ast.AST, prefix: str, frozen: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}{child.name}.", frozen or bool(child.decorator_list))
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualname = f"{prefix}{child.name}"
                if frozen:
                    found[qualname] = "inside a decorated class"
                elif _skipped_by_decorators(child.decorator_list):
                    found[qualname] = "decorated"
                else:
                    walk(child, f"{qualname}.", False)
            else:
                walk(child, prefix, frozen)

    walk(ast.parse(source), "", False)
    return found


def _mutmut_table() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return dict(tomllib.load(handle)["tool"]["mutmut"])


def _is_mutated_path(relative_posix: str, only_mutate: Iterable[str]) -> bool:
    """mutmut's own selection rule (`configuration.py`, `_should_include_for_mutation`):
    `fnmatch` against each `only_mutate` pattern.

    Deliberately NOT `Path.glob`: in `fnmatch` a `*` crosses `/`, so
    `src/product_app/*.py` also selects `src/product_app/sub/x.py`, and mutmut
    would mutate that file. Adversarial review planted exactly that file and
    watched a `Path.glob` version of this scanner miss it while mutmut skipped
    its decorated function: the census must select what the tool selects.
    """
    return any(fnmatch.fnmatch(relative_posix, pattern) for pattern in only_mutate)


def _mutated_files() -> list[Path]:
    """Every file `[tool.mutmut]` mutates — `source_paths` walked, `only_mutate`
    applied — PARSED from pyproject, never assumed to be `src/`, so a widened
    or moved scope is followed."""
    table = _mutmut_table()
    only_mutate = [str(pattern) for pattern in table["only_mutate"]]  # type: ignore[attr-defined]
    candidates = (
        path
        for source_path in table["source_paths"]  # type: ignore[attr-defined]
        for path in (REPO_ROOT / str(source_path)).rglob("*.py")
    )
    return sorted(
        path
        for path in candidates
        if _is_mutated_path(path.relative_to(REPO_ROOT).as_posix(), only_mutate)
    )


def _module_name(path: Path) -> str:
    return path.relative_to(REPO_ROOT / "src").with_suffix("").as_posix().replace("/", ".")


def scan_tree(files: Iterable[Path]) -> dict[str, str]:
    """`module:qualname -> reason` over every file given."""
    census: dict[str, str] = {}
    for path in files:
        module = _module_name(path)
        for qualname, reason in unmutatable_functions(path.read_text(encoding="utf-8")).items():
            census[f"{module}:{qualname}"] = reason
    return census


def _inventory_entries(text: str) -> set[str]:
    entries = set()
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            entries.add(line)
    return entries


def _render_inventory(census: dict[str, str]) -> str:
    return INVENTORY_HEADER + "\n" + "".join(f"{key}\n" for key in sorted(census))


def _check_inventory(actual: dict[str, str], recorded: set[str]) -> None:
    """Fail with the exact edit needed when the tree and the inventory differ."""
    new = sorted(set(actual) - recorded)
    stale = sorted(recorded - set(actual))
    if not new and not stale:
        return
    lines = []
    if new:
        lines.append(
            "NEW — these functions now generate ZERO mutants because of a "
            "decorator, and the inventory does not say so:"
        )
        lines.extend(f"    {key}    [{actual[key]}]" for key in new)
    if stale:
        lines.append(
            "STALE — the inventory lists these, but they are no longer "
            "decorator-skipped (removed, renamed, moved, or un-decorated):"
        )
        lines.extend(f"    {key}" for key in stale)
    raise AssertionError(
        f"{INVENTORY.name} does not match the tree.\n"
        + "\n".join(lines)
        + "\nA decorated function is invisible to the mutation gate — every "
        "survivor in it goes uncounted. If the decorator is legitimate, edit "
        f"{INVENTORY.name} in this same change so the reviewer sees the "
        "surface it gives up (or regenerate it: "
        f"./.venv/bin/python -m {REGENERATE_MODULE}). "
        "If it is there to make a survivor disappear, write the test instead."
    )


# --------------------------------------------------------------------------
# floors: every check below is a comparison of two sets, and both would be
# empty over nothing (rule 7)
# --------------------------------------------------------------------------


def test_the_scan_reads_the_population_mutmut_mutates() -> None:
    """Turns red if: `[tool.mutmut] only_mutate` stops matching the real
    source, or the tree moves out from under it."""
    files = _mutated_files()
    assert len(files) >= 20, (
        f"only {len(files)} file(s) matched [tool.mutmut] only_mutate — the "
        "scope moved or the pattern is wrong; this gate refuses to pass over "
        "an empty population"
    )
    assert all(path.stat().st_size > 0 for path in files)


def test_the_population_rule_is_mutmut_s_rule_not_a_shell_glob() -> None:
    """Turns red if: `_is_mutated_path` stops crossing `/` the way mutmut's
    `fnmatch` does, or starts selecting outside `only_mutate`."""
    patterns = ["src/product_app/*.py"]
    assert _is_mutated_path("src/product_app/main.py", patterns)
    assert _is_mutated_path("src/product_app/subpkg/hidden.py", patterns), (
        "mutmut would mutate a subpackage file; the census must scan it too"
    )
    assert not _is_mutated_path("src/httpx2/compat.py", patterns)
    assert not _is_mutated_path("tests/unit/test_x.py", patterns)


def test_an_unparseable_source_file_fails_loudly_rather_than_shrinking_the_census() -> None:
    """Turns red if: `unmutatable_functions` starts swallowing `SyntaxError`,
    which would drop the file from the census and let the gate pass over it."""
    with pytest.raises(SyntaxError):
        unmutatable_functions("def (:\n")


def test_the_inventory_and_the_scanner_both_name_a_function_known_to_be_skipped() -> None:
    """Positive partner for the gate: `/health` is a FastAPI route, decorated
    with `@app.get(...)`, and mutmut has never mutated it.

    Turns red if: the inventory is emptied or unreadable, or the scanner
    returns nothing for the real tree. Deliberately names ONE fact independent
    of the inventory's own size (rule 7a), never a count.
    """
    known = "product_app.main:health"
    assert known in _inventory_entries(INVENTORY.read_text(encoding="utf-8"))
    census = scan_tree(_mutated_files())
    assert census.get(known) == "decorated", census.get(known)


# --------------------------------------------------------------------------
# the detector, proven in memory on every run
# --------------------------------------------------------------------------


def test_the_scanner_sees_a_decorator_planted_in_memory() -> None:
    """Plant each spelling that silences a function, and each that does not,
    on the real `_stance_majority_flags` source — in memory, structurally.

    Turns red if: the predicate is inverted, loosened to tolerate any
    single decorator, or stops walking classes and nested defs.
    """
    real = REPO_ROOT / "src" / "product_app" / "synthesis_consensus.py"
    source = real.read_text(encoding="utf-8")
    anchor = "def _stance_majority_flags("
    assert source.count(anchor) == 1, "the anchor moved; re-point it rather than deleting the proof"
    assert "_stance_majority_flags" not in unmutatable_functions(source), (
        "the fixture function is already decorated; this proof needs a clean one"
    )

    silencing = (
        "@functools.cache",
        "@functools.lru_cache(maxsize=1)",
        "@ft.cache",
        "@cache",
        "@property",
        "@typing.overload",
        "@(functools.cache)",  # parenthesised (PEP 614): still an Attribute underneath
        "@staticmethod\n@functools.cache",  # stacked: no longer a LONE tolerated decorator
        "@functools.lru_cache(\n    maxsize=1,\n)",
    )
    for spelling in silencing:
        planted = source.replace(anchor, f"{spelling}\n{anchor}", 1)
        assert unmutatable_functions(planted).get("_stance_majority_flags") == "decorated", (
            f"the scanner missed {spelling!r}, which mutmut skips"
        )

    # `@(staticmethod)` is here, not above: measured against mutmut 3.6.0, the
    # parentheses change nothing (384 mutants, 11 for the function, same as
    # bare), and `ast` drops them too, so both see a lone Name.
    for tolerated in ("@staticmethod", "@classmethod", "@(staticmethod)"):
        planted = source.replace(anchor, f"{tolerated}\n{anchor}", 1)
        assert "_stance_majority_flags" not in unmutatable_functions(planted), (
            f"the scanner flagged {tolerated!r}, which mutmut still mutates"
        )

    # A decorated class freezes every method; a decorated NESTED def is
    # recorded once, by its dotted path, and its own subtree is not walked.
    census = unmutatable_functions(
        "import dataclasses\n"
        "@dataclasses.dataclass\n"
        "class Frozen:\n"
        "    def plain(self): return 1\n"
        "    @staticmethod\n"
        "    def still_frozen(): return 2\n"
        "class Plain:\n"
        "    def free(self): return 3\n"
        "    @classmethod\n"
        "    def also_free(cls): return 4\n"
        "def outer():\n"
        "    @cache\n"
        "    def inner():\n"
        "        def deeper(): return 5\n"
        "        return 6\n"
        "    return inner()\n"
    )
    assert census == {
        "Frozen.plain": "inside a decorated class",
        "Frozen.still_frozen": "inside a decorated class",
        "outer.inner": "decorated",
    }, census


def test_the_inventory_comparison_fails_in_both_directions() -> None:
    """Turns red if: `_check_inventory` stops reporting NEW or STALE entries,
    or starts raising on agreement."""
    _check_inventory({"m:f": "decorated"}, {"m:f"})

    with pytest.raises(AssertionError) as new:
        _check_inventory({"m:f": "decorated", "m:g": "inside a decorated class"}, {"m:f"})
    assert "NEW" in str(new.value) and "m:g" in str(new.value) and "STALE" not in str(new.value)

    with pytest.raises(AssertionError) as stale:
        _check_inventory({}, {"m:f"})
    assert (
        "STALE" in str(stale.value) and "m:f" in str(stale.value) and "NEW" not in str(stale.value)
    )


def test_the_gate_itself_fails_against_an_inventory_that_disagrees_with_the_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Drive THE GATE FUNCTION, through its real file reader, against a
    disagreeing inventory: the real one with `product_app.main:health` removed
    (so the tree has it and the file does not — NEW) and one made-up entry
    added (STALE).

    Adversarial review found that without this, three mutations left every
    test green: an inventory reader that returned the scanner's own output, a
    gate that compared the tree with itself, and a gate whose body was `pass`.
    `_check_inventory` was proven on literal sets; the wiring to it was not.

    Turns red if: the gate stops reading the inventory file, stops comparing
    it with the tree, or stops failing on either direction.
    """
    real_lines = INVENTORY.read_text(encoding="utf-8").splitlines()
    assert "product_app.main:health" in real_lines
    doctored = [line for line in real_lines if line != "product_app.main:health"]
    doctored.append("product_app.main:this_function_does_not_exist")
    fake = tmp_path / INVENTORY.name
    fake.write_text("\n".join(doctored) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "INVENTORY", fake)

    with pytest.raises(AssertionError) as caught:
        test_no_function_lost_its_mutation_surface_unrecorded()
    message = str(caught.value)
    assert "NEW" in message and "product_app.main:health" in message, message
    assert "STALE" in message and "product_app.main:this_function_does_not_exist" in message, (
        message
    )


# --------------------------------------------------------------------------
# the binding test the issue asks for: mutmut itself, not a mirror of it
# --------------------------------------------------------------------------

#: Every decorator shape the scanner claims to understand, in one module.
SYNTHETIC_MODULE = """\
import functools
import dataclasses
from functools import lru_cache


def plain(a, b):
    return a + b


async def plain_async(a):
    return a * 2


@functools.cache
def cached(a):
    return a - 1


@lru_cache(maxsize=8)
def cached_with_args(a):
    return a - 2


@some.custom.decorator
def custom(a):
    return a - 3


def outer(a):
    @functools.cache
    def inner(b):
        return b - 4
    return inner(a) + 1


class Plain:
    def method(self, a):
        return a + 10

    @staticmethod
    def static(a):
        return a + 11

    @classmethod
    def klass(cls, a):
        return a + 12

    @property
    def prop(self):
        return 13

    @staticmethod
    @functools.cache
    def stacked(a):
        return a + 14


@dataclasses.dataclass
class Frozen:
    x: int = 0

    def method(self, a):
        return a + 20

    @staticmethod
    def static(a):
        return a + 21
"""


def _owners_of(mutant_names: Iterable[str]) -> set[str]:
    """Qualnames mutmut attributes mutants to: `x_<fn>` or `xǁ<Class>ǁ<method>`,
    each followed by `__mutmut_N`."""
    owners = set()
    for name in mutant_names:
        mangled = name.rsplit("__mutmut_", 1)[0].rsplit(".", 1)[-1]
        if mangled.startswith("xǁ"):
            owners.add(".".join(mangled[2:].split("ǁ")))
        else:
            owners.add(mangled.removeprefix("x_"))
    return owners


@pytest.mark.repo_introspection
def test_the_scanner_agrees_with_the_installed_mutmut(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the SAME synthetic module through mutmut's own generator and through
    the scanner; the functions mutmut gave zero mutants must be exactly the
    functions the scanner recorded (nested defs aside — mutmut attributes those
    to the enclosing function, which is why the second half of this test
    strips one decorator at a time and watches the count grow).

    This is the binding check #369 asks for: a real mutant, not a mirror.
    Marked `repo_introspection` because it imports mutmut and reads its config
    from the working directory (`mutate_file_contents` raises without a
    `pyproject.toml` there); it must not run inside mutmut's own copy.

    Turns red if: mutmut changes which decorators it skips, or the scanner
    drifts from it.
    """
    from mutmut.mutation.file_mutation import mutate_file_contents

    monkeypatch.chdir(REPO_ROOT)
    _, names = mutate_file_contents("synthetic.py", SYNTHETIC_MODULE)
    mutated = _owners_of(names)
    census = unmutatable_functions(SYNTHETIC_MODULE)

    top_level = {
        f"{prefix}{node.name}"
        for prefix, body in (
            ("", ast.parse(SYNTHETIC_MODULE).body),
            *(
                (f"{cls.name}.", cls.body)
                for cls in ast.parse(SYNTHETIC_MODULE).body
                if isinstance(cls, ast.ClassDef)
            ),
        )
        for node in body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    zero_mutant = top_level - mutated
    recorded_top_level = {key for key in census if key in top_level}
    assert zero_mutant == recorded_top_level, (
        f"mutmut skipped {sorted(zero_mutant)} but the scanner recorded "
        f"{sorted(recorded_top_level)}"
    )
    # Both halves non-vacuous: mutmut mutated something AND skipped something.
    assert {"plain", "plain_async", "Plain.method", "Plain.static", "Plain.klass"} <= mutated, (
        mutated
    )
    assert {
        "cached",
        "custom",
        "Plain.prop",
        "Plain.stacked",
        "Frozen.method",
        "Frozen.static",
    } <= zero_mutant

    # A real mutant reappears when the decorator goes: strip one at a time and
    # the count must strictly GROW. This is the only way to see the nested
    # case, whose mutants are attributed to `outer`.
    baseline = len(names)
    for decorator in (
        "@functools.cache\ndef cached",
        "@lru_cache(maxsize=8)\n",
        "@some.custom.decorator\n",
        "    @functools.cache\n    def inner",
        "    @property\n",
        "@dataclasses.dataclass\n",
    ):
        assert SYNTHETIC_MODULE.count(decorator) == 1, decorator
        head, _, tail = decorator.partition("\n")
        stripped = SYNTHETIC_MODULE.replace(decorator, tail if tail else "", 1)
        assert stripped != SYNTHETIC_MODULE
        _, more = mutate_file_contents("synthetic.py", stripped)
        assert len(more) > baseline, (
            f"removing {head.strip()!r} did not bring any mutant back "
            f"({len(more)} vs {baseline}); the scanner is recording something "
            "mutmut does not actually skip"
        )


# --------------------------------------------------------------------------
# THE GATE
# --------------------------------------------------------------------------


def test_no_function_lost_its_mutation_surface_unrecorded() -> None:
    """The gate itself. ADR-0072.

    Turns red if: any function under `only_mutate` becomes, or stops being,
    decorator-skipped without the matching edit to the inventory. Its partners
    above prove the scanner detects a planted decorator, the comparison fails
    in both directions, and the population and inventory are real.
    """
    assert INVENTORY.is_file(), (
        f"{INVENTORY} is missing — regenerate it with ./.venv/bin/python -m {REGENERATE_MODULE}"
    )
    _check_inventory(
        actual=scan_tree(_mutated_files()),
        recorded=_inventory_entries(INVENTORY.read_text(encoding="utf-8")),
    )


if __name__ == "__main__":  # pragma: no cover - contributor convenience, not a test path
    INVENTORY.write_text(_render_inventory(scan_tree(_mutated_files())), encoding="utf-8")
    sys.stdout.write(f"wrote {INVENTORY.relative_to(REPO_ROOT).as_posix()}\n")
