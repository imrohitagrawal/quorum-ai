"""Replay real history through the mutation gate's scope logic. READ ONLY.

Answers the question that should precede shipping ANY gate: *what would this
have done to our last N commits?* For the mutation gate that answer decided a
real reversal — see ``docs/metrics/mutation-gate-study.md`` §3, where this
script measured an 8% silent-pass rate concentrated on money configuration.

Usage:  python3 scripts/replay_mutation_scope.py [limit]

Mirrors MUTMUT_SCOPE_PY exactly, except it reads file content with
`git show <rev>:<path>` instead of the working tree, so no checkout is needed
and the tree is never touched.

For every commit that changed Python under src/, classify it:

  MEASURED  - at least one function landed in scope; the gate would run
  BLOCKED   - src/*.py changed but NO function matched; today that is a silent
              "nothing to mutate" pass, and option 3 would fail it closed

Also reports WHY a commit produced an empty scope, which is the number that
decides whether option 3 is free or a tax.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
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
        covered: set[int] = set()

        def walk(
            node: ast.AST,
            changed: set[int],
            seen: set[int],
            mod: str,
            cls: str | None = None,
        ) -> int:
            """Return how many functions overlapped `changed`.

            `changed`/`seen` are passed explicitly rather than closed over: a
            closure here binds the loop variable, so every file would be walked
            against the LAST file's changed lines (ruff B023).
            """
            hits = 0
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    hits += walk(child, changed, seen, mod, child.name)
                elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    span = set(range(child.lineno, (child.end_lineno or child.lineno) + 1))
                    seen.update(span)
                    if changed & span:
                        name = f"xǁ{cls}ǁ{child.name}" if cls else f"x_{child.name}"
                        globs.append(f"{mod}.{name}__mutmut_*")
                        hits += 1
                    hits += walk(child, changed, seen, mod, cls)
            return hits

        matched = walk(tree, lines, covered, module)
        if not matched:
            # Why did nothing match? Distinguish the real causes.
            if lines - covered:
                reasons["changed lines outside any def (module/class level)"] += 1
            else:
                reasons["other"] += 1

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
