"""Replay real history through the mutation gate's scope logic. READ ONLY.

Answers the question that should precede shipping ANY gate: *what would this
have done to our last N commits?* For the mutation gate that answer decided a
real reversal — see ``docs/metrics/mutation-gate-study.md`` §3, where this
script measured an 8% silent-pass rate concentrated on money configuration.

Usage:  python3 scripts/replay_mutation_scope.py [limit]

Mirrors MUTMUT_SCOPE_PY exactly, except it reads file content with
`git show <rev>:<path>` instead of the working tree, so no checkout is needed
and the tree is never touched. That equivalence is pinned by a differential
test — `tests/unit/test_replay_scope_matches_makefile_scope.py` (#143) — which
extracts the real Makefile block and runs both over real commit history,
asserting identical glob sets. It is not just prose anymore: before that test
existed, this script had no `unmutatable()` exclusion at all and could name a
glob for a decorated function mutmut never builds a mutant for.

For every commit that changed Python under src/, classify it:

  MEASURED  - at least one function landed in scope; the gate would run
  BLOCKED   - src/*.py changed but NO function matched; today that is a silent
              "nothing to mutate" pass, and option 3 would fail it closed

Also reports WHY a commit produced an empty scope, which is the number that
decides whether option 3 is free or a tax.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from collections import Counter


def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def changed_lines(base: str, head: str) -> dict[str, set[int]]:
    """New-side line numbers per .py file under src/, as the gate computes them."""
    ranges: dict[str, set[int]] = {}
    out = git("diff", "-U0", f"{base}...{head}", "--", "src")
    path = None
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@") and path and path.endswith(".py"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if not m:
                continue
            start, count = int(m.group(1)), int(m.group(2) or 1)
            if count:
                ranges.setdefault(path, set()).update(range(start, start + count))
            else:
                # A pure deletion: no new-side lines at all.
                ranges.setdefault(path, set())
    return ranges


def unmutatable(node: ast.AST) -> bool:
    """True when mutmut will not generate mutants for this function.

    Byte-for-byte port of `unmutatable()` in the Makefile's `MUTMUT_SCOPE_PY`
    (mirrors mutmut/mutation/file_mutation.py:230-235): decorated functions
    are skipped because the trampoline copy re-runs decorators, EXCEPT a lone
    bare @staticmethod/@classmethod, which mutmut handles.

    #143: this function did not exist here before, so the replay script
    named globs for decorated functions the Makefile's real gate excludes —
    a real drift the differential test in
    tests/unit/test_replay_scope_matches_makefile_scope.py caught.
    """
    decorators = getattr(node, "decorator_list", [])
    if not decorators:
        return False
    if len(decorators) == 1:
        only = decorators[0]
        if isinstance(only, ast.Name) and only.id in ("staticmethod", "classmethod"):
            return False
    return True


def _joined_str_has_a_real_string_literal(node: ast.JoinedStr, source: str) -> bool:
    """True when a `JoinedStr` contains a PLAIN (non-f) string token.

    Byte-for-byte port of the Makefile's `MUTMUT_SCOPE_PY` helper of the same
    name (#146) — see there for the full rationale.
    """
    segment = ast.get_source_segment(source, node)
    if segment is None:
        return True  # can't prove it safe -- caller fails closed on this
    try:
        tokens = tokenize.generate_tokens(io.StringIO(segment).readline)
        return any(tok.type == tokenize.STRING for tok in tokens)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return True


def _safe_comprehension(generators: list[ast.comprehension], source: str) -> bool:
    """True when every `for ... in ...` clause of a comprehension is safe.

    Byte-for-byte port of the Makefile's `MUTMUT_SCOPE_PY` helper of the same
    name (#146).
    """
    for gen in generators:
        if not _safe_expr(gen.iter, source):
            return False
        if any(not _safe_expr(cond, source) for cond in gen.ifs):
            return False
    return True


def _safe_expr(node: ast.AST | None, source: str) -> bool:
    """True when mutmut has NO operator that can touch this expression.

    Byte-for-byte port of the Makefile's `MUTMUT_SCOPE_PY` `_safe_expr` (#146)
    — see there for the full rationale and the FAILS CLOSED contract.
    """
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _safe_expr(node.value, source)
    if isinstance(node, ast.Constant):
        return node.value is None or node.value is Ellipsis
    if isinstance(node, ast.Call):
        if node.args or node.keywords:
            return False
        return _safe_expr(node.func, source)
    if isinstance(node, ast.IfExp):
        return (
            _safe_expr(node.test, source)
            and _safe_expr(node.body, source)
            and _safe_expr(node.orelse, source)
        )
    if isinstance(node, ast.Tuple | ast.List):
        return all(_safe_expr(elt, source) for elt in node.elts)
    if isinstance(node, ast.JoinedStr):
        if _joined_str_has_a_real_string_literal(node, source):
            return False
        for part in node.values:
            if isinstance(part, ast.Constant):
                continue  # literal text: operator_string ignores FormattedString entirely
            if isinstance(part, ast.FormattedValue):
                if part.format_spec is not None or not _safe_expr(part.value, source):
                    return False
                continue
            return False
        return True
    if isinstance(node, ast.DictComp):
        return (
            _safe_expr(node.key, source)
            and _safe_expr(node.value, source)
            and _safe_comprehension(node.generators, source)
        )
    if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
        return _safe_expr(node.elt, source) and _safe_comprehension(node.generators, source)
    return False


def no_mutable_content(func: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> bool:
    """True when NOTHING mutmut can mutate lives anywhere in `func`.

    Byte-for-byte port of the Makefile's `MUTMUT_SCOPE_PY` `no_mutable_content`
    (#146) — see there for the full rationale and the FAILS CLOSED contract.
    """
    body = list(func.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        # A leading docstring never counts against a function: mutmut's own
        # operator_string explicitly excuses triple-quoted strings ("we
        # assume triple-quoted stuff are docs").
        body = body[1:]
    if not body:
        return True

    def safe_stmts(stmts: list[ast.stmt]) -> bool:
        for stmt in stmts:
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Return | ast.Expr):
                if not _safe_expr(stmt.value, source):
                    return False
                continue
            if isinstance(stmt, ast.With | ast.AsyncWith):
                for item in stmt.items:
                    if not _safe_expr(item.context_expr, source):
                        return False
                    if item.optional_vars is not None and not isinstance(
                        item.optional_vars, ast.Name
                    ):
                        return False
                if not safe_stmts(stmt.body):
                    return False
                continue
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if unmutatable(stmt):
                    continue
                if not no_mutable_content(stmt, source):
                    return False
                continue
            # If/For/While/Try/Assign/Raise/... are not provably inert.
            return False
        return True

    return safe_stmts(body)


def scope(base: str, head: str) -> tuple[list[str], dict[str, int]]:
    """Return (globs, reason counts) for the diff base...head."""
    globs: list[str] = []
    reasons: Counter[str] = Counter()

    for path, lines in changed_lines(base, head).items():
        source = git("show", f"{head}:{path}")
        if not source:
            reasons["file absent at head (deleted/renamed)"] += 1
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            reasons["unparseable"] += 1
            continue

        if not lines:
            reasons["pure deletion (no new-side lines)"] += 1
            continue

        module = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
        matched = 0
        skipped_count = 0
        covered: set[int] = set()

        def walk(
            node: ast.AST,
            changed: set[int],
            seen: set[int],
            mod: str,
            src: str,
            cls: str | None = None,
            frozen: bool = False,
        ) -> int:
            """Return how many functions overlapped `changed`.

            `changed`/`seen`/`src` are passed explicitly rather than closed
            over: a closure here binds the loop variable, so every file would
            be walked against the LAST file's changed lines/source (ruff
            B023).

            `frozen` mirrors the Makefile: a DECORATED CLASS is skipped by
            mutmut together with its whole subtree, so every method inside it
            is unmutatable, decorated or not (e.g. every @dataclass).
            """
            nonlocal skipped_count
            hits = 0
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    hits += walk(
                        child,
                        changed,
                        seen,
                        mod,
                        src,
                        child.name,
                        frozen or bool(child.decorator_list),
                    )
                elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    span = set(range(child.lineno, (child.end_lineno or child.lineno) + 1))
                    seen.update(span)
                    if changed & span:
                        hits += 1
                        if frozen or unmutatable(child):
                            skipped_count += 1
                        elif no_mutable_content(child, src):
                            # #146: genuinely nothing for any mutmut operator
                            # to touch anywhere in this function (own body or
                            # a nested def inside it) - same dead-glob cause
                            # the Makefile's scope() excludes.
                            skipped_count += 1
                        else:
                            name = f"xǁ{cls}ǁ{child.name}" if cls else f"x_{child.name}"
                            globs.append(f"{mod}.{name}__mutmut_*")
                    # Do NOT recurse into a FunctionDef's body looking for
                    # further FunctionDefs: mutmut attributes EVERY mutation
                    # inside a nested `def` - at any depth - to this SAME
                    # enclosing name (OuterFunctionProvider), never to the
                    # nested def's own name (#146, mirrors the Makefile).
            return hits

        matched = walk(tree, lines, covered, module, source)
        if not matched:
            # Why did nothing match? Distinguish the real causes.
            if lines - covered:
                reasons["changed lines outside any def (module/class level)"] += 1
            else:
                reasons["other"] += 1
        elif skipped_count and skipped_count == matched:
            # Every matched function is decorated/unmutatable: mutmut builds
            # no mutants for any of them, so this file globs nothing -- the
            # same blind spot as "outside any def", just reached a different
            # way. Reported so it is never silent (#136's "38% carry one
            # silently" applies here too).
            reasons["changed lines only in unmutatable (decorated) functions"] += 1

    return sorted(set(globs)), dict(reasons)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    revs = git(
        "log", f"-{limit}", "--format=%H", "--first-parent", "origin/main", "--", "src"
    ).split()

    measured, blocked = [], []
    all_reasons: Counter[str] = Counter()

    for rev in revs:
        parent = git("rev-parse", f"{rev}^").strip()
        if not parent:
            continue
        # Only commits that actually changed Python under src/.
        if not any(
            p.endswith(".py")
            for p in git("diff", "--name-only", f"{parent}...{rev}", "--", "src").split()
        ):
            continue
        globs, reasons = scope(parent, rev)
        subject = git("log", "-1", "--format=%s", rev).strip()[:58]
        if globs:
            measured.append((rev[:8], len(globs), subject))
        else:
            blocked.append((rev[:8], reasons, subject))
            all_reasons.update(reasons)

    total = len(measured) + len(blocked)
    print(f"Commits on main changing src/**.py (first-parent, last {limit}): {total}\n")
    print(f"  MEASURED (gate actually runs)   : {len(measured)}")
    print(f"  EMPTY SCOPE (silent pass today): {len(blocked)}")
    if total:
        print(
            f"  -> silent-pass rate = {len(blocked)}/{total} = {100 * len(blocked) / total:.0f}%\n"
        )

    if blocked:
        print("Why the scope came out empty:")
        for reason, n in all_reasons.most_common():
            print(f"  {n:3d}  {reason}")
        print("\nThe commits that passed having measured nothing:")
        for sha, reasons, subject in blocked:
            print(f"  {sha}  {subject}")
            for reason, n in reasons.items():
                print(f"            └─ {n}x {reason}")

    print("\nScope size distribution for the measured ones (mutant cost proxy):")
    sizes = sorted(n for _, n, _ in measured)
    if sizes:
        print(f"  min {sizes[0]}, median {sizes[len(sizes) // 2]}, max {sizes[-1]}")
        big = [(s, n, t) for s, n, t in measured if n >= 20]
        print(f"  commits with >=20 functions in scope: {len(big)}")
        for sha, n, subject in big[:10]:
            print(f"    {sha}  {n:3d} funcs  {subject}")


if __name__ == "__main__":
    main()
