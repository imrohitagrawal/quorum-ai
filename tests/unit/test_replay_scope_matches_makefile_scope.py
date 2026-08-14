"""#143: pin the equivalence `scripts/replay_mutation_scope.py` claims to have
with the Makefile's `MUTMUT_SCOPE_PY`.

The replay script's own docstring says it "Mirrors MUTMUT_SCOPE_PY exactly,"
and that claim is quoted as evidence throughout
`docs/metrics/mutation-gate-study.md` (the 8% silent-pass rate, the scope-size
distribution) — but nothing tested it. Confirmed drift before this test
existed: the Makefile's `scope()` excludes decorated/unmutatable functions
(mutmut builds no mutants for them — see `unmutatable()` and the `frozen`
flag propagated through decorated classes), and the replay script had no such
exclusion at all, so it could name a glob mutmut would never generate and the
gate would never run. Reproduced with the DECORATED_BEFORE/AFTER fixture
below: pre-fix, the replay script emitted `pkg.thing.xǁCǁvalue__mutmut_*` for
a change inside a bare `@property`, while the real Makefile scope excluded it.

Two tests here:

  * `test_replay_scope_matches_the_makefile_scope_over_real_commits` — the
    differential test #143 asks for: run BOTH the real `MUTMUT_SCOPE_PY`
    block (extracted from the Makefile, exactly as
    `test_mutation_gate_integrity.py` already does) and the real
    `replay_mutation_scope.scope()` over the same set of real commits, and
    assert the glob sets are identical. Anti-vacuity: asserts the examined
    count is non-zero.

  * `test_the_differential_guard_bites_on_the_decorator_regression` — the
    concrete first instance of #167: uses `tests/guard_bite.py`'s general
    mechanism to prove the differential check above can actually go red, by
    replaying the exact regression this file was written to close.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.guard_bite import assert_guard_bites

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
REPLAY_SCRIPT = REPO_ROOT / "scripts" / "replay_mutation_scope.py"
SCOPE_BLOCK = re.compile(r"^define MUTMUT_SCOPE_PY\n(.*?)^endef$", re.DOTALL | re.MULTILINE)

pytestmark = pytest.mark.repo_introspection


# --------------------------------------------------------------------------
# Shared plumbing
# --------------------------------------------------------------------------


def _extract_makefile_scope_script(dest_dir: Path) -> Path:
    match = SCOPE_BLOCK.search(MAKEFILE.read_text(encoding="utf-8"))
    assert match, "MUTMUT_SCOPE_PY define block not found in the Makefile"
    dest_dir.mkdir(parents=True, exist_ok=True)
    script = dest_dir / "mutscope.py"
    script.write_text(match.group(1), encoding="utf-8")
    return script


def _makefile_globs(script: Path, cwd: Path, base: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, str(script), "scope", base, "80"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"the real Makefile scope script exited non-zero: {result.stdout}{result.stderr}"
    )
    return {line for line in result.stdout.splitlines() if line}


def _load_replay_module(script: Path, git_cwd: Path | None = None) -> Any:
    """Import a (possibly mutated) copy of replay_mutation_scope.py.

    `replay_mutation_scope.git()` runs `git` in the calling process's cwd
    (correct for the real-commit test below, which runs inside REPO_ROOT).
    When `git_cwd` is given, the module's `git` is rebound to run `-C
    git_cwd`, the same trick `tests/unit/test_replay_mutation_scope.py`
    already uses, so the synthetic-fixture test can point it at a throwaway
    repo instead.

    Typed `Any` deliberately: dynamically loaded module, no mypy stub.
    """
    spec = importlib.util.spec_from_file_location("replay_mutation_scope_under_test", script)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if git_cwd is not None:
        real_git = module.git

        def git_in(*args: str) -> str:
            result: str = real_git("-C", str(git_cwd), *args)
            return result

        module.git = git_in
    return module


def _replay_globs(module: Any, base: str, head: str) -> set[str]:
    globs, _reasons = module.scope(base, head)
    return set(globs)


# --------------------------------------------------------------------------
# #143: differential test over real commit history
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def local_clone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A disposable, fully-local clone so `git checkout` per commit never
    touches this worktree — the Makefile's `scope()` reads files off disk
    (`open(path)`), unlike the replay script, which reads via `git show`.
    """
    clone = tmp_path_factory.mktemp("mutscope-clone") / "repo"
    subprocess.run(
        ["git", "clone", "--local", "--quiet", str(REPO_ROOT), str(clone)],
        check=True,
        capture_output=True,
    )
    return clone


def test_replay_scope_matches_the_makefile_scope_over_real_commits(
    local_clone: Path, tmp_path: Path
) -> None:
    script = _extract_makefile_scope_script(tmp_path)
    replay = _load_replay_module(REPLAY_SCRIPT)

    revs = subprocess.run(
        ["git", "log", "-60", "--format=%H", "--first-parent", "origin/main", "--", "src"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    examined = 0
    mismatches: list[tuple[str, set[str]]] = []
    for rev in revs:
        parent = subprocess.run(
            ["git", "rev-parse", f"{rev}^"], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip()
        if not parent:
            continue
        changed_paths = subprocess.run(
            ["git", "diff", "--name-only", f"{parent}...{rev}", "--", "src"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        ).stdout.split()
        if not any(p.endswith(".py") for p in changed_paths):
            continue

        subprocess.run(["git", "checkout", "--quiet", "--detach", rev], cwd=local_clone, check=True)
        makefile_globs = _makefile_globs(script, local_clone, parent)
        replay_scope_globs = _replay_globs(replay, parent, rev)

        examined += 1
        diff = makefile_globs ^ replay_scope_globs
        if diff:
            mismatches.append((rev[:8], diff))

    # Anti-vacuity: the comparison must have actually examined something.
    assert examined > 0, (
        "no commits with src/**.py changes were examined -- the differential "
        "comparison ran over an empty set and proves nothing"
    )
    assert not mismatches, (
        f"replay_mutation_scope.py disagrees with the Makefile's MUTMUT_SCOPE_PY "
        f"glob set on {len(mismatches)}/{examined} commit(s): {mismatches[:5]}"
    )


# --------------------------------------------------------------------------
# #167: concrete first instance -- prove the differential test above bites
# --------------------------------------------------------------------------

DECORATED_BEFORE = """\
class C:
    @property
    def value(self):
        return 1
"""
DECORATED_AFTER = DECORATED_BEFORE.replace("return 1", "return 2")


def _decorated_change_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A two-commit repo: a change entirely inside a bare `@property`.

    mutmut generates no mutants for a decorated function, so the Makefile's
    real scope() excludes it; this is the exact shape that revealed the drift
    this module exists to close.
    """
    repo = tmp_path / "decorated-repo"
    (repo / "src" / "pkg").mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    module_path = repo / "src" / "pkg" / "thing.py"
    module_path.write_text(DECORATED_BEFORE, encoding="utf-8")
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-qm", "base")
    module_path.write_text(DECORATED_AFTER, encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "decorated change")

    base = subprocess.run(
        ["git", "rev-parse", "HEAD^"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, base, head


def _strip_decorator_mirroring(source: str) -> str:
    """Reproduce the pre-fix drift: delete `unmutatable()` and make every
    matched function glob unconditionally, regardless of decorators.

    This is not a synthetic toy mutation -- it is exactly the state
    `scripts/replay_mutation_scope.py` was in before this PR, confirmed by
    running it against DECORATED_BEFORE/AFTER above and observing it emit
    `pkg.thing.xǁCǁvalue__mutmut_*`, which the real Makefile scope excludes.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    def_starts = {
        node.name: node.lineno
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in ("unmutatable", "scope")
    }
    assert "unmutatable" in def_starts and "scope" in def_starts, (
        "expected unmutatable() and scope() at module level in "
        "replay_mutation_scope.py -- the mutation helper is stale"
    )

    # Drop the unmutatable() function body entirely (lines from its `def` up
    # to the line before the next module-level def), and drop the exclusion
    # check inside scope()'s nested walk() by replacing the mutation-added
    # condition with the pre-fix unconditional glob.
    keep: list[str] = []
    skipping_unmutatable = False
    for i, line in enumerate(lines, start=1):
        if i == def_starts["unmutatable"]:
            skipping_unmutatable = True
            continue
        if skipping_unmutatable and i == def_starts["scope"]:
            skipping_unmutatable = False
        if skipping_unmutatable:
            continue
        keep.append(line)
    stripped = "".join(keep)

    unconditional_glob = (
        "                    if changed & span:\n"
        "                        hits += 1\n"
        "                        if frozen or unmutatable(child):\n"
        "                            skipped_count += 1\n"
        "                        elif no_mutable_content(child, src):\n"
        "                            # #146: genuinely nothing for any mutmut operator\n"
        "                            # to touch anywhere in this function (own body or\n"
        "                            # a nested def inside it) - same dead-glob cause\n"
        "                            # the Makefile's scope() excludes.\n"
        "                            skipped_count += 1\n"
        "                        else:\n"
        '                            name = f"xǁ{cls}ǁ{child.name}" if cls else f"x_{child.name}"\n'
        '                            globs.append(f"{mod}.{name}__mutmut_*")\n'
    )
    replacement = (
        "                    if changed & span:\n"
        "                        hits += 1\n"
        '                        name = f"xǁ{cls}ǁ{child.name}" if cls else f"x_{child.name}"\n'
        '                        globs.append(f"{mod}.{name}__mutmut_*")\n'
    )
    assert unconditional_glob in stripped, (
        "the exclusion block this helper strips no longer matches the real "
        "source of replay_mutation_scope.py -- update _strip_decorator_mirroring"
    )
    stripped = stripped.replace(unconditional_glob, replacement)
    return stripped


def test_the_differential_guard_bites_on_the_decorator_regression(tmp_path: Path) -> None:
    """The concrete first instance of #167: prove the #143 differential test
    above can actually fail, without paying for a `tests/`-wide mutation run.

    Turns red if: `_strip_decorator_mirroring` stops matching the real source
    of `replay_mutation_scope.py` (in which case it raises, not silently
    passes -- see the asserts inside it), or if the differential comparison
    stops detecting the reintroduced drift.
    """
    decorated_repo, base, head = _decorated_change_repo(tmp_path / "fixture")
    makefile_script = _extract_makefile_scope_script(tmp_path / "makefile-scope")

    def run_guard(replay_script_copy: Path) -> None:
        replay = _load_replay_module(replay_script_copy, git_cwd=decorated_repo)
        makefile_globs = _makefile_globs(makefile_script, decorated_repo, base)
        replay_scope_globs = _replay_globs(replay, base, head)
        assert makefile_globs == replay_scope_globs, (
            f"scope mismatch on the decorated-function fixture: "
            f"makefile={makefile_globs} replay={replay_scope_globs}"
        )

    assert_guard_bites(REPLAY_SCRIPT, _strip_decorator_mirroring, run_guard)
