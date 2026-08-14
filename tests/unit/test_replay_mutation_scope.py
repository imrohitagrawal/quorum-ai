"""The gate-replay instrument must classify commits correctly.

`scripts/replay_mutation_scope.py` answers "what would this gate have done to
our last N commits?" — the question that reversed the #130 promotion
(`docs/metrics/mutation-gate-study.md` §3). An instrument that mis-classifies is
worse than none, because its output is quoted as evidence in that study.

So this drives it against a purpose-built git repository with three commits of
known shape, and asserts the classification. Not against the real repo: that
would make the test move with unrelated history.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "replay_mutation_scope.py"

pytestmark = pytest.mark.repo_introspection


def _load(cwd: Path) -> Any:
    """Import the script with its git helper rebound to run inside `cwd`.

    Typed `Any` deliberately: this is a dynamically loaded script module, so
    mypy has no stub for its attributes.
    """
    spec = importlib.util.spec_from_file_location("replay_mutation_scope", SCRIPT)
    assert spec and spec.loader
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real = module.git

    def git_in(*args: str) -> str:
        result: str = real("-C", str(cwd), *args)
        return result

    module.git = git_in
    return module


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Three commits: an in-function change, a module-level change, a deletion."""
    root = tmp_path / "repo"
    (root / "src" / "pkg").mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)

    module = root / "src" / "pkg" / "thing.py"
    git("init", "-q", "-b", "main")
    module.write_text(
        "LIMIT = 10\nEXTRA = 1\n\n\ndef f(x):\n    return x + 1\n",
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-qm", "base")

    # (1) change INSIDE a function body -> must be MEASURED
    module.write_text(
        "LIMIT = 10\nEXTRA = 1\n\n\ndef f(x):\n    return x + 2\n",
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-qm", "in-function change")

    # (2) change a MODULE-LEVEL constant -> empty scope, the 8% blind spot
    module.write_text(
        "LIMIT = 99\nEXTRA = 1\n\n\ndef f(x):\n    return x + 2\n",
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-qm", "module-level constant change")

    # (3) PURE DELETION of a module-level line -> empty scope, no new-side lines
    module.write_text(
        "LIMIT = 99\n\n\ndef f(x):\n    return x + 2\n",
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-qm", "pure deletion")
    return root


def _scope_for(module: Any, subject: str) -> tuple[list[str], dict[str, int]]:
    rev = module.git("log", "--format=%H %s", "--all").strip().splitlines()
    sha = next(line.split()[0] for line in rev if subject in line)
    parent = module.git("rev-parse", f"{sha}^").strip()
    scoped: tuple[list[str], dict[str, int]] = module.scope(parent, sha)
    return scoped


def test_a_change_inside_a_function_is_measured(repo: Path) -> None:
    """The gate runs. Turns red if scope() stops matching function bodies."""
    module = _load(repo)
    globs, _ = _scope_for(module, "in-function change")
    assert globs == ["pkg.thing.x_f__mutmut_*"], globs


def test_a_module_level_constant_change_produces_an_empty_scope(repo: Path) -> None:
    """The measured 8% blind spot, reproduced deterministically.

    This is the shape of `9c502398 cost: raise daily cap to $0.20`. Turns red if
    scope() is ever widened to attribute module-level lines to a function — at
    which point the study's §3.1 number is stale and must be re-measured.
    """
    module = _load(repo)
    globs, reasons = _scope_for(module, "module-level constant change")
    assert globs == [], f"expected an empty scope, got {globs}"
    assert "changed lines outside any def (module/class level)" in reasons, reasons


def test_a_pure_deletion_produces_an_empty_scope(repo: Path) -> None:
    """A deletion has no new-side line, so a line-scoped selector selects nothing.

    Turns red if the `@@ ... +N,0` (zero new-side lines) case stops being
    recognised and is silently folded into another reason.
    """
    module = _load(repo)
    globs, reasons = _scope_for(module, "pure deletion")
    assert globs == [], f"expected an empty scope, got {globs}"
    assert "pure deletion (no new-side lines)" in reasons, reasons


def test_the_classifier_distinguishes_the_two_empty_scope_causes(repo: Path) -> None:
    """Positive partner: the two empty-scope reasons must not collapse into one.

    Both cases above assert an empty scope; without this, a classifier that
    returned one fixed reason for everything would satisfy both.
    """
    module = _load(repo)
    _, constant = _scope_for(module, "module-level constant change")
    _, deletion = _scope_for(module, "pure deletion")
    assert set(constant) != set(deletion), (
        f"both empty-scope causes report the same reason: {constant} vs {deletion}"
    )


def test_a_tokenize_failure_fails_closed_instead_of_crashing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_joined_str_has_a_real_string_literal()` (#146) catches a real
    tokenize failure on the node's own source segment and fails closed
    (returns True — "can't prove it safe"), mirroring the Makefile's
    `MUTMUT_SCOPE_PY` copy of the same helper.

    Before this test existed, the except clause named an exception class
    that does not exist on this Python (`tokenize.TokenizeError` — the real
    name is `tokenize.TokenError`). Because Python evaluates an
    `except (...)` tuple only when an exception actually needs matching,
    this was silent for every JoinedStr that tokenizes cleanly, and only
    broke — with an `AttributeError` masking the real tokenize error — the
    one time a segment genuinely failed to tokenize (a single unterminated
    string literal genuinely raises `tokenize.TokenError`, confirmed
    directly against CPython 3.14's `tokenize` module).

    Turns red if: `tokenize.TokenError` reverts to the nonexistent
    `tokenize.TokenizeError` name (an `AttributeError` propagates instead of
    the function returning `True`).
    """
    module = _load(repo)
    monkeypatch.setattr(module.ast, "get_source_segment", lambda *_a, **_k: '"')

    expr_stmt = ast.parse('f"x"').body[0]
    assert isinstance(expr_stmt, ast.Expr)
    node = expr_stmt.value
    assert isinstance(node, ast.JoinedStr)

    assert module._joined_str_has_a_real_string_literal(node, 'f"x"') is True
