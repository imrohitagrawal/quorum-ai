#!/usr/bin/env python3
"""How many tracked ``.md`` files can a new agent reach by following links?

A new session auto-loads ``AGENTS.md`` (through ``CLAUDE.md``). This counts the
tracked ``.md`` files (skills excluded) reachable from those two files by
following Markdown links and back-ticked ``.md`` paths, hop by hop, and how
many are NOT reachable within three hops. It is a measurement, not a gate:
run it before and after changing the entry points and quote both numbers.

Measured 2026-09-30 at ``7c74b4f`` (before ``docs/README.md`` existed):
538 files; hop 1: 35; hop 2: 61 more; hop 3: 172 more; 268 not reachable
within three hops.

Run from the repository root: ``python3 scripts/measure_doc_reachability.py``.
"""

from __future__ import annotations

import collections
import pathlib
import re
import subprocess

_LINK = re.compile(r"(?:\]\(|`)((?:\.{0,2}/)?[\w./-]+\.md)")


def tracked_docs(root: pathlib.Path) -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, cwd=root, check=True
    ).stdout.split()
    return {f for f in out if not f.startswith((".agents/", "node_modules"))}


def references(root: pathlib.Path, source: str, files: set[str]) -> set[str]:
    """Tracked files that ``source`` links to, resolved relative to the root or to ``source``."""
    found: set[str] = set()
    text = (root / source).read_text(errors="ignore")
    for target in _LINK.findall(text):
        for candidate in (root / target, root / pathlib.Path(source).parent / target):
            try:
                rel = str(candidate.resolve().relative_to(root.resolve()))
            except ValueError:
                continue
            if rel in files:
                found.add(rel)
    return found


def measure(
    root: pathlib.Path, starts: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md"), max_hops: int = 3
) -> dict[str, int]:
    files = tracked_docs(root)
    hops = {s: 0 for s in starts if s in files}
    frontier = set(hops)
    for hop in range(1, max_hops + 1):
        nxt = {r for f in frontier for r in references(root, f, files) if r not in hops}
        hops.update({r: hop for r in nxt})
        frontier = nxt
    counts = collections.Counter(hops.values())
    result = {"tracked": len(files)}
    for hop in range(max_hops + 1):
        result[f"hop_{hop}"] = counts.get(hop, 0)
    result["unreachable"] = len(files) - len(hops)
    return result


def main() -> int:
    result = measure(pathlib.Path.cwd())
    print(f"tracked .md (excl. skills): {result['tracked']}")
    for key, value in result.items():
        if key.startswith("hop_"):
            print(f"{key.replace('_', ' ')}: {value}")
    print(f"not reachable within 3 hops: {result['unreachable']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
